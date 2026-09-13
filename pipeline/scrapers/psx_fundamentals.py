"""Fundamentals scraper: DPS screener (sector, cap, PE, yield) + payouts.

Source (verified 2026-09-10): https://dps.psx.com.pk/screener serves one
server-rendered table (740 tickers) with columns
SYMBOL | SECTOR(code) | LISTED-IN | MARKET CAP. | PRICE | CHANGE (%) |
1-YEAR CH. (%) | PE RATIO (TTM) | DIVIDEND YIELD (%) | FREE FLOAT |
30D VOLUME AVG.

The SECTOR column shows a numeric code; readable sector names come from
https://dps.psx.com.pk/sector-summary/sectorwise whose <h3> headings
segment per-sector symbol tables, giving a ticker -> sector-name map.

Payout history: POST /company/payouts {symbol} returns announcement rows
including the payout percentage text (e.g. "60% (F) (D)").
"""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import Optional

from bs4 import BeautifulSoup

from pipeline.http_client import ajax_headers, http_get, http_post
from pipeline.parsing import to_int, to_number

LOGGER = logging.getLogger(__name__)

BASE_URL = "https://dps.psx.com.pk"
SCREENER_URL = f"{BASE_URL}/screener"
SECTORWISE_URL = f"{BASE_URL}/sector-summary/sectorwise"
COMPANY_PAYOUTS_URL = f"{BASE_URL}/company/payouts"

CASH_DIVIDEND_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*%", re.IGNORECASE
)


def _cell_number(cell) -> Optional[float]:
    if cell is None:
        return None
    raw = cell.get("data-order") or cell.get("data-filter")
    if raw is None:
        return None
    try:
        return float(str(raw).replace(",", ""))
    except ValueError:
        return None


def fetch_sector_map() -> dict[str, str]:
    """Ticker -> readable sector name from the DPS sectorwise page."""
    response = http_get(SECTORWISE_URL, headers=ajax_headers(SECTORWISE_URL))
    soup = BeautifulSoup(response.text, "html.parser")
    mapping: dict[str, str] = {}
    for heading in soup.find_all("h3"):
        sector_name = heading.get_text(" ", strip=True).upper()
        if not sector_name or len(sector_name) > 100:
            continue
        table = heading.find_next("table")
        if table is None:
            continue
        for a in table.find_all("a", class_="tbl__symbol"):
            ticker = a.get_text(strip=True).upper()
            if ticker and ticker not in mapping:
                mapping[ticker] = sector_name[:100]
    LOGGER.info("sector map: %d tickers", len(mapping))
    return mapping


def fetch_screener(trade_date: date, sector_map: Optional[dict[str, str]] = None) -> list[dict]:
    """Parse the DPS screener table into psx_fundamentals rows."""
    sector_map = sector_map if sector_map is not None else {}
    response = http_get(SCREENER_URL, headers=ajax_headers(SCREENER_URL))
    soup = BeautifulSoup(response.text, "html.parser")
    table = soup.find("table", class_="tbl")
    if table is None:
        raise ValueError("screener page did not contain a table")

    records: list[dict] = []
    tbody = table.find("tbody")
    for tr in (tbody or table).find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 11:
            continue
        link = tds[0].find("a", class_="tbl__symbol")
        if link is None:
            continue
        ticker = link.get_text(strip=True).upper()
        if not ticker or len(ticker) > 20:
            continue
        close_price = _cell_number(tds[4])
        if close_price is None or close_price <= 0:
            continue
        sector_code = tr.find("td", attrs={"data-name": "sector"})
        sector_name = sector_map.get(
            ticker, (sector_code.get_text(strip=True) if sector_code else None)
        )
        records.append(
            {
                "trade_date": trade_date.isoformat(),
                "ticker": ticker,
                "sector_name": (sector_name or "UNKNOWN")[:100],
                "market_cap_pkr": _cell_number(tds[3]),
                "close_price": round(close_price, 2),
                "pe_ratio": _cell_number(tds[7]),
                "dividend_yield": _cell_number(tds[8]),
                "free_float": (lambda v: int(round(v)) if v is not None else None)(
                    _cell_number(tds[9])
                ),
                "volume_30d_avg": _cell_number(tds[10]),
            }
        )
    if not records:
        raise ValueError("screener parsed to zero rows")
    LOGGER.info("screener: %d tickers with fundamentals", len(records))
    return records


def fetch_cash_dividends(symbol: str, *, limit: int = 6) -> list[float]:
    """Most recent cash-dividend percentages (as fractions, e.g. 0.6 = 60%).

    Payout text like "60% (F) (D)" is a cash dividend (D); bonus-only rows
    like "10% (B)" carry no cash and are ignored.
    """
    try:
        response = http_post(
            COMPANY_PAYOUTS_URL,
            data={"symbol": symbol},
            headers=ajax_headers(f"{BASE_URL}/payouts"),
            timeout=20.0,
        )
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("payouts %s failed: %s", symbol, exc)
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    payouts: list[float] = []
    for row_text in soup.stripped_strings:
        text = " ".join(str(row_text).upper().split())
        if "(D)" not in text:
            continue
        match = CASH_DIVIDEND_RE.search(text)
        if match:
            try:
                payouts.append(float(match.group(1)) / 100.0)
            except ValueError:
                continue
        if len(payouts) >= limit:
            break
    return payouts
