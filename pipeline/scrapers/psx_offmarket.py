"""PSX negotiated / off-market (NDM) deals scraper.

Source (verified 2026-09-10): the DPS trading panel renders each board via
GET https://dps.psx.com.pk/trading-board/NDM/NDM which returns an HTML
table: SYMBOL | NAME | TRADES (C2C) | TRADES (M2M) | VOLUME. This is the
Negotiated Deals Market board - large negotiated block trades that never
hit the regular order book.

The public board aggregates volume per symbol (per-trade rates are not
published), so each row is stored as one aggregated deal with:
  quantity = board volume
  rate     = same-day market-watch close (best public proxy)
  value    = quantity x close
The board reflects the latest session, matching the market-watch snapshot.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from bs4 import BeautifulSoup

from pipeline.http_client import ajax_headers, http_get
from pipeline.parsing import to_int

LOGGER = logging.getLogger(__name__)

BASE_URL = "https://dps.psx.com.pk"
NDM_BOARD_URL = f"{BASE_URL}/trading-board/NDM/NDM"


def fetch_ndm_rows() -> list[dict]:
    """Fetch the raw NDM board rows: ticker, name, c2c, m2m, volume."""
    response = http_get(NDM_BOARD_URL, headers=ajax_headers(f"{BASE_URL}/trading-panel"))
    soup = BeautifulSoup(response.text, "html.parser")
    table = soup.find("table", id="tradingBoardTable")
    if table is None:
        LOGGER.warning("NDM board table missing (market closed or layout change)")
        return []

    rows: list[dict] = []
    tbody = table.find("tbody")
    for tr in (tbody or table).find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 5:
            continue
        link = tds[0].find("a", class_="tbl__symbol")
        if link is None:
            continue
        ticker = link.get_text(strip=True).upper()
        name = tds[1].get_text(" ", strip=True)
        c2c = to_int(tds[2].get_text(" ", strip=True)) or 0
        m2m = to_int(tds[3].get_text(" ", strip=True)) or 0
        volume = to_int(tds[4].get_text(" ", strip=True))
        if not ticker or volume is None or volume <= 0:
            continue
        rows.append(
            {
                "ticker": ticker,
                "name": name,
                "trades_c2c": c2c,
                "trades_m2m": m2m,
                "volume": volume,
            }
        )
    LOGGER.info("NDM board: %d symbols", len(rows))
    return rows


def fetch_offmarket_deals(
    trade_date: date,
    close_prices: Optional[dict[str, float]] = None,
    *,
    min_volume: int = 10_000,
) -> list[dict]:
    """Convert NDM board rows into psx_offmarket_deals records.

    ``close_prices`` maps ticker -> same-day close so the stored deal value
    uses the best public price proxy. Deals below ``min_volume`` are
    skipped to keep the table focused on institutional-size blocks.
    """
    close_prices = close_prices or {}
    deals: list[dict] = []
    for row in fetch_ndm_rows():
        volume = row["volume"]
        if volume < min_volume:
            continue
        ticker = row["ticker"]
        rate = close_prices.get(ticker)
        value = rate * volume if rate is not None else None
        deals.append(
            {
                "trade_date": trade_date.isoformat(),
                "ticker": ticker,
                "quantity": volume,
                "rate": round(rate, 2) if rate is not None else None,
                "value": round(value, 2) if value is not None else None,
            }
        )
    LOGGER.info(
        "off-market deals %s: %d blocks >= %d shares",
        trade_date,
        len(deals),
        min_volume,
    )
    return deals
