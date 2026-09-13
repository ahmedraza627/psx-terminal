"""PSX end-of-day scraper.

Primary source (verified 2026-09-10): https://dps.psx.com.pk/market-watch
serves one server-rendered page containing every listed ticker with LDCP
(previous close), OPEN, HIGH, LOW, CURRENT (last/close) and VOLUME. Every
numeric cell carries a machine-readable ``data-order`` attribute, which is
what we parse (immune to thousand separators and icon spans).

Fallback history source: POST https://dps.psx.com.pk/historical with form
fields ``symbol``, ``month``, ``year`` returns that symbol's monthly OHLCV
table (rows keyed by a unix-epoch ``data-order``) - used to backfill the
20/50-day indicator windows for newly tracked tickers.

Third source: GET https://dps.psx.com.pk/timeseries/eod/<SYMBOL> returns
``{"status":1,"data":[[epoch, close, volume, ldcp], ...]}`` and is used as a
final fallback to fill close/volume when the table parsers fail.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Optional

import requests
from bs4 import BeautifulSoup

from pipeline.http_client import ajax_headers, http_get, http_post

LOGGER = logging.getLogger(__name__)

BASE_URL = "https://dps.psx.com.pk"
MARKET_WATCH_URL = f"{BASE_URL}/market-watch"
HISTORICAL_URL = f"{BASE_URL}/historical"
TIMESERIES_URL = f"{BASE_URL}/timeseries/eod"

_MAX_BACKFILL_MONTHS = 3


def _cell_number(cell) -> Optional[float]:
    """Read the numeric value of a table cell via its data-order attr."""
    if cell is None:
        return None
    raw = cell.get("data-order")
    if raw is None:
        return None
    try:
        return float(str(raw).replace(",", ""))
    except ValueError:
        return None


def _row_to_record(tr, trade_date: date) -> Optional[dict]:
    """Convert one market-watch <tr> into an EOD record (None to skip)."""
    tds = tr.find_all("td")
    if len(tds) < 11:
        return None

    symbol_cell = tds[0].find("a", class_="tbl__symbol")
    if symbol_cell is None:
        return None
    ticker = symbol_cell.get_text(strip=True).upper()
    if not ticker or len(ticker) > 20:
        return None

    # Columns: SYMBOL, SECTOR, LISTED-IN, LDCP, OPEN, HIGH, LOW, CLOSE,
    #          CHANGE, CHANGE%, VOLUME
    prev_close = _cell_number(tds[3])
    open_price = _cell_number(tds[4])
    high_price = _cell_number(tds[5])
    low_price = _cell_number(tds[6])
    close_price = _cell_number(tds[7])
    volume = _cell_number(tds[10])

    close_price = close_price if close_price is not None else prev_close
    if close_price is None or close_price <= 0:
        return None
    if open_price is not None and open_price <= 0:
        open_price = None

    volume_int: Optional[int] = None
    if volume is not None and volume >= 0:
        volume_int = int(round(volume))

    # Skip placeholder rows (e.g. 100-share bookkeeping entries) that PSX
    # renders with open=high=low=0 and no real turnover.
    if open_price in (None, 0) and high_price in (None, 0) and low_price in (None, 0):
        if volume_int is None or volume_int < 500:
            return None

    return {
        "trade_date": trade_date.isoformat(),
        "ticker": ticker,
        "open_price": open_price,
        "high_price": high_price,
        "low_price": low_price,
        "close_price": round(close_price, 2),
        "volume": volume_int,
    }


def fetch_market_snapshot(trade_date: Optional[date] = None) -> list[dict]:
    """Scrape the full server-rendered market-watch table for one date.

    ``trade_date`` is used purely for labelling (PSX serves the latest
    session); callers pass the day being processed.
    """
    response = http_get(MARKET_WATCH_URL, headers=ajax_headers(BASE_URL + "/"))
    soup = BeautifulSoup(response.text, "html.parser")
    table = soup.find("table", class_="tbl")
    if table is None:
        raise ValueError("market-watch page did not contain the market table")

    tbody = table.find("tbody")
    if tbody is None:
        raise ValueError("market-watch table has no tbody")

    records: list[dict] = []
    seen: set[str] = set()
    for tr in tbody.find_all("tr"):
        record = _row_to_record(tr, trade_date or date.today())
        if record and record["ticker"] not in seen:
            seen.add(record["ticker"])
            records.append(record)

    if not records:
        raise ValueError("market-watch table parsed to zero rows")
    LOGGER.info("market-watch: parsed %d tickers", len(records))
    return records


def fetch_historical_month(
    symbol: str, year: int, month: int
) -> list[dict]:
    """Fetch one symbol's monthly OHLCV table from the DPS historical API."""
    response = http_post(
        HISTORICAL_URL,
        data={"symbol": symbol, "month": str(month), "year": str(year)},
        headers=ajax_headers(f"{BASE_URL}/historical"),
    )
    soup = BeautifulSoup(response.text, "html.parser")
    records: list[dict] = []
    for tr in soup.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 5:
            continue
        epoch = tds[0].get("data-order")
        try:
            trade_date = datetime.utcfromtimestamp(int(str(epoch))).date()
        except (TypeError, ValueError):
            continue
        values = [ _cell_number(td) for td in tds[1:5] ]
        open_price, high_price, low_price, close_price = values
        volume = _cell_number(tds[5]) if len(tds) > 5 else None
        if close_price is None or close_price <= 0:
            continue
        records.append(
            {
                "trade_date": trade_date.isoformat(),
                "ticker": symbol.upper(),
                "open_price": open_price,
                "high_price": high_price,
                "low_price": low_price,
                "close_price": round(close_price, 2),
                "volume": int(round(volume)) if volume is not None else None,
            }
        )
    return records


def fetch_timeseries_close(symbol: str) -> list[dict]:
    """Fallback: DPS JSON timeseries ``[epoch, close, volume, ldcp]``."""
    response = http_get(
        f"{TIMESERIES_URL}/{requests.utils.quote(symbol)}",
        headers=ajax_headers(f"{BASE_URL}/historical"),
        timeout=20.0,
    )
    payload = response.json()
    rows = payload.get("data") or [] if isinstance(payload, dict) else []
    records: list[dict] = []
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 4:
            continue
        try:
            trade_date = datetime.utcfromtimestamp(int(row[0])).date()
            close_price = float(row[1])
            volume = int(round(float(row[2])))
        except (TypeError, ValueError):
            continue
        if close_price <= 0:
            continue
        records.append(
            {
                "trade_date": trade_date.isoformat(),
                "ticker": symbol.upper(),
                "open_price": None,
                "high_price": None,
                "low_price": None,
                "close_price": round(close_price, 2),
                "volume": volume,
            }
        )
    return records


def backfill_history(
    tickers: list[str],
    *,
    months: int = _MAX_BACKFILL_MONTHS,
    today: Optional[date] = None,
) -> list[dict]:
    """Backfill recent monthly history for a set of tickers.

    Used before the first full run so 20/50-day indicators have data. The
    historical POST accepts one symbol at a time, so this is inherently
    sequential; keep the ticker list short.
    """
    today = today or date.today()
    months_windows: list[tuple[int, int]] = []
    cursor = date(today.year, today.month, 1)
    for _ in range(months):
        months_windows.append((cursor.year, cursor.month))
        cursor = (cursor - timedelta(days=1)).replace(day=1)

    all_records: list[dict] = []
    for ticker in tickers:
        seen: dict[str, dict] = {}
        for year, month in months_windows:
            try:
                for record in fetch_historical_month(ticker, year, month):
                    seen[record["trade_date"]] = record
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning(
                    "historical backfill %s %04d-%02d failed: %s",
                    ticker,
                    year,
                    month,
                    exc,
                )
        if not seen:
            try:
                for record in fetch_timeseries_close(ticker):
                    seen[record["trade_date"]] = record
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("timeseries fallback %s failed: %s", ticker, exc)
        all_records.extend(seen.values())
        LOGGER.info("backfill %s: %d rows", ticker, len(seen))
    return all_records


def fetch_eod(trade_date: Optional[date] = None) -> list[dict]:
    """Public entry point: today's full-market EOD snapshot."""
    return fetch_market_snapshot(trade_date)
