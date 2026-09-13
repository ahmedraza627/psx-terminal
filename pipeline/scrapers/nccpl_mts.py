"""NCCPL MTS (Margin Trading System) exposure scraper.

NCCPL publishes MTS utilization per scrip (shares financed, PKR value,
utilization vs authorized leverage, unfinanced volume). Their portal sits
behind Cloudflare ("Just a moment...") for datacenter IPs and the legacy
scstrade MTS screeners 404 today (both verified 2026-09-12), so this
scraper

1. tries the NCCPL MTS page directly (works when Cloudflare relents or a
   residential egress runs the pipeline),
2. falls back to scstrade's MTS screener mirrors,
3. parses whichever server-side table appears, in column order
   SYMBOL / MTS SHARES / MTS VALUE / UTILISATION % / UNFINANCED VOL,
4. returns [] with a logged explanation when every source is blocked -
   the MTS_SQUEEZE desk then stays honestly idle, never fabricated.

Row shape matches nccpl_mts_leverage (schema.sql).
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Optional

from bs4 import BeautifulSoup

from pipeline.http_client import http_get
from pipeline.parsing import to_int, to_number

LOGGER = logging.getLogger(__name__)

NCCPL_MTS_URL = (
    "https://www.nccpl.com.pk/en/products-services/margin-trading-system-mts"
)
SCSTRADE_MTS_URLS = (
    "https://www.scstrade.com/stockscreeners/MTS/MTSScreen.aspx",
    "https://www.scstrade.com/stockscreeners/MTS/MTS.aspx",
    "https://www.scstrade.com/MTS.aspx",
)

# Header fragments -> canonical meaning, matched case-insensitively.
_HEADER_HINTS = {
    "symbol": "symbol",
    "scrip": "symbol",
    "code": "symbol",
    "shares": "shares",
    "volume": "shares",
    "value": "value",
    "util": "util",
    "utilisation": "util",
    "utilization": "util",
    "unfinanced": "unfinanced",
}


def _column_map(headers: list[str]) -> Optional[dict[str, int]]:
    """Map canonical fields to column indexes from a table header row."""
    mapping: dict[str, int] = {}
    for idx, header in enumerate(headers):
        key = _HEADER_HINTS.get(header.strip().lower())
        if key and key not in mapping:
            mapping[key] = idx
    if "symbol" not in mapping or ("shares" not in mapping and "value" not in mapping):
        return None
    return mapping


def _parse_mts_table(html: str, trade_date: date) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    for table in soup.find_all("table"):
        header_cells = [c.get_text(" ", strip=True) for c in table.find_all("th")]
        column_map = _column_map(header_cells) if header_cells else None
        tbody = table.find("tbody") or table
        for tr in tbody.find_all("tr"):
            tds = tr.find_all("td")
            if column_map is None:
                # Header-less table: try discovery-order layout.
                if len(tds) < 4:
                    continue
                column_map = {"symbol": 0, "shares": 1, "value": 2, "util": 3}
            if len(tds) <= max(column_map.values()):
                continue

            ticker = tds[column_map["symbol"]].get_text(strip=True).upper()
            if not ticker or len(ticker) > 16 or "-" in ticker:
                continue

            shares = (
                to_int(tds[column_map["shares"]].get_text(" ", strip=True))
                if "shares" in column_map else None
            )
            value = (
                to_number(tds[column_map["value"]].get_text(" ", strip=True))
                if "value" in column_map else None
            )
            if (shares is None or shares <= 0) and (value is None or value <= 0):
                continue

            util = (
                to_number(tds[column_map["util"]].get_text(" ", strip=True))
                if "util" in column_map else None
            )
            unfinanced = (
                to_int(tds[column_map["unfinanced"]].get_text(" ", strip=True))
                if "unfinanced" in column_map else None
            )

            # MTS values are reported in PKR millions on NCCPL tables.
            if value is not None and value < 10_000:
                value *= 1_000_000

            yield {
                "trade_date": trade_date.isoformat(),
                "ticker": ticker,
                "mts_shares": int(shares or 0),
                "mts_value_pkr": round(value or 0.0, 2),
                "leverage_utilization_pct": round(util, 2) if util is not None else None,
                "unfinanced_volume": unfinanced,
            }
            if column_map.get("util") == 3 and "unfinanced" not in column_map:
                column_map = None  # reset heuristic for the next table


def _try_sources(trade_date: date) -> tuple[list[dict[str, Any]], str]:
    sources = [(NCCPL_MTS_URL, "nccpl")] + [
        (url, "scstrade") for url in SCSTRADE_MTS_URLS
    ]
    for url, label in sources:
        try:
            response = http_get(url, timeout=25.0)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("mts source %s (%s) unreachable: %s", label, url, exc)
            continue
        rows = list(_parse_mts_table(response.text, trade_date))
        if rows:
            LOGGER.info("mts: %d scrips from %s", len(rows), label)
            return rows, url
        LOGGER.info("mts source %s (%s) served no parsable table", label, url)
    return [], ""


def fetch_mts_exposure(trade_date: Optional[date] = None) -> list[dict[str, Any]]:
    """Scrape per-scrip MTS leverage exposure; [] when sources are blocked.

    Empty output is the honest signal that NCCPL/Cloudflare blocked the
    run - the MTS_SQUEEZE engine treats [] as "desk idle", never as
    "zero leverage".
    """
    trade_date = trade_date or date.today()
    rows, source = _try_sources(trade_date)
    if not rows:
        LOGGER.warning(
            "mts: all sources blocked or unparsable (NCCPL Cloudflare / "
            "scstrade 404); MTS_SQUEEZE stays idle (no fabricated data)"
        )
        return []
    del source
    # Dedupe on the (trade_date, ticker) unique key.
    deduped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        deduped.setdefault((row["trade_date"], row["ticker"]), row)
    return list(deduped.values())
