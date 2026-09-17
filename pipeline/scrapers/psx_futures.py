"""PSX single-stock futures (deliverable) contract scraper.

Two live sources are attempted, in order of preference (verified 2026-09-12):

1. POST https://www.psx.com.pk/psx/market-summary/future-contract-ajax
       form: month=<format>, limit=<int>
       -> server-rendered SYMBOL/OPEN/HIGH/LOW/CURRENT/CHANGE/VOLUME table
          rows, symbol cells in <a class="tbl__symbol"> (e.g. "TRG-FUT").
   The accepted month format comes from a JS-built <select> that is absent
   from the static HTML, so a wide cascade of formats is tried. As of
   2026-09-12 the PSX WAF answers every payload with "Invalid input." or
   "Forbidden" (automation filtering).

2. GET $FUTURES_FALLBACK_URL (optional operator-configured source).
   The PSX futures board is currently WAF-gated against automation, so the
   scraper accepts an env-configured URL for any page that serves the same
   SYMBOL/OPEN/HIGH/LOW/CURRENT/CHANGE/VOLUME table shape with XXX-FUT
   symbols (a restored PSX board, an authenticated NCCPL export, or a
   mirror). When unset or unparsable, this tier is skipped with a clear log.

Optional OPEN INTEREST column: when a source table carries a parseable
non-negative integer in the 8th cell, it is stored in oi_shares. This is the
DFC short scanner's second leg (rising OI + negative basis = shorts pressing);
sources without the column leave oi_shares NULL and the scanner degrades to
basis-only. Never inferred, never imputed.

When neither source yields contract rows for the session, the scraper
returns an empty list and logs explicitly - psx_futures_eod stays empty and
the arbitrage / rollover desks render their idle banners. No synthetic
spreads are ever produced.
"""

from __future__ import annotations

import calendar
import logging
import os
from datetime import date
from typing import Any, Optional

from bs4 import BeautifulSoup
from requests import Response

from pipeline.http_client import ajax_headers, http_get, http_post
from pipeline.parsing import to_int, to_number

LOGGER = logging.getLogger(__name__)

FUTURES_AJAX_URL = (
    "https://www.psx.com.pk/psx/market-summary/future-contract-ajax"
)
FUTURES_PAGE_URL = "https://www.psx.com.pk/market-summary/future-contracts/"
# Operator-configured fallback source (see module docstring, tier 2).
FALLBACK_URL_ENV = "FUTURES_FALLBACK_URL"

# Month formats the endpoint might accept (cascade, cheapest first).
_MONTH_FORMATS = (
    "Month-YYYY",   # e.g. Sep-2026
    "M-YYYY",       # e.g. SEPT-2026 (non-standard abbreviations)
    "MM-YYYY",      # e.g. 09-2026
    "MYYYY",        # e.g. SEP2026
    "M YY",         # e.g. SEP 26
)

_REJECTED_MARKERS = ("invalid input", "no data found", "forbidden")


def _month_variants(year: int, month: int) -> list[str]:
    """All month-string candidates for one (year, month) pair."""
    full = calendar.month_name[month]
    abbrevs = {calendar.month_abbr[month]}
    if month == 9:
        abbrevs.add("SEPT")  # PSX uses non-standard September abbreviations
    variants: list[str] = []
    for abbrev in sorted(abbrevs):
        variants.extend(
            (
                f"{abbrev}-{year}",
                f"{abbrev}{year}",
                f"{abbrev} {str(year)[2:]}",
                f"{abbrev}-{str(year)[2:]}",
            )
        )
    variants.extend((f"{month:02d}-{year}", f"{month:02d}{year}"))
    variants.append(full)  # September-2026
    return variants


def _is_rejected(body: str) -> bool:
    """True when the AJAX body is a WAF/application rejection, not a table."""
    stripped = body.strip()
    if not stripped:
        return True
    lowered = stripped.lower()
    return any(marker in lowered for marker in _REJECTED_MARKERS)


def _parse_contract_rows(html: str, trade_date: date) -> list[dict[str, Any]]:
    """Parse any SYMBOL/OPEN/HIGH/LOW/CURRENT/CHANGE/VOLUME contract table.

    Accepts either the AJAX fragment (bare <tr> rows) or a full page
    (wrapped in <table><tbody>). Returns psx_futures_eod-shaped dicts.
    """
    soup = BeautifulSoup(html, "html.parser")
    records: list[dict[str, Any]] = []
    for table in soup.find_all("table"):
        tbody = table.find("tbody") or table
        for tr in tbody.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) < 7:
                continue
            link = tds[0].find("a", class_="tbl__symbol") or tds[0].find("a")
            symbol_txt = (
                link.get_text(strip=True) if link is not None
                else tds[0].get_text(strip=True)
            )
            symbol = symbol_txt.upper()
            if not symbol or not symbol.endswith("-FUT") or len(symbol) > 20:
                continue
            close = to_number(tds[4].get_text(" ", strip=True))
            if close is None or close <= 0:
                continue
            oi = to_int(tds[7].get_text(" ", strip=True)) if len(tds) >= 8 else None
            records.append(
                {
                    "trade_date": trade_date.isoformat(),
                    "ticker": symbol[:20],
                    "open_price": to_number(tds[1].get_text(" ", strip=True)),
                    "high_price": to_number(tds[2].get_text(" ", strip=True)),
                    "low_price": to_number(tds[3].get_text(" ", strip=True)),
                    "close_price": round(close, 2),
                    "volume": to_int(tds[6].get_text(" ", strip=True)),
                    "oi_shares": oi if (oi is not None and oi >= 0) else None,
                }
            )
    # Dedupe by symbol (mirrored tables render the same contracts twice).
    deduped: dict[str, dict[str, Any]] = {}
    for record in records:
        deduped.setdefault(record["ticker"], record)
    return list(deduped.values())


def _fetch_from_ajax(trade_date: date, *, limit: int) -> list[dict[str, Any]]:
    """Source 1: the market-summary contract AJAX with a format cascade."""
    for month_str in _month_variants(trade_date.year, trade_date.month):
        try:
            response = http_post(
                FUTURES_AJAX_URL,
                data={"month": month_str, "limit": str(limit)},
                headers=ajax_headers(FUTURES_PAGE_URL),
                timeout=25.0,
            )
        except Exception as exc:  # noqa: BLE001 - WAF blocks surface here
            LOGGER.info("futures ajax %r unreachable: %s", month_str, exc)
            continue

        body = (response.text or "").strip()
        if _is_rejected(body):
            LOGGER.info(
                "futures ajax month=%r rejected (%d bytes)", month_str, len(body)
            )
            continue

        records = _parse_contract_rows(body, trade_date)
        if records:
            LOGGER.info(
                "futures: %d contracts via market-summary ajax (month=%r)",
                len(records),
                month_str,
            )
            return records

    LOGGER.info("futures: market-summary ajax accepted no month format")
    return []


def _fetch_from_fallback_url(trade_date: date) -> list[dict[str, Any]]:
    """Source 2: operator-configured fallback URL (FUTURES_FALLBACK_URL).

    Parses the same generic SYMBOL/.../VOLUME contract-table shape via
    _parse_contract_rows. Unset, unreachable, or unparsable sources are
    skipped with an explicit log - never fabricated.
    """
    url = (os.getenv(FALLBACK_URL_ENV) or "").strip()
    if not url:
        LOGGER.info(
            "futures: %s unset - no fallback source configured", FALLBACK_URL_ENV
        )
        return []
    try:
        response: Response = http_get(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/126.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml",
            },
            timeout=25.0,
        )
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("futures fallback %s unreachable: %s", url, exc)
        return []

    records = _parse_contract_rows(response.text or "", trade_date)
    if records:
        LOGGER.info(
            "futures: %d contracts via fallback %s", len(records), url
        )
    else:
        LOGGER.info(
            "futures: fallback %s rendered no priced contract rows", url
        )
    return records


def fetch_futures_contracts(
    trade_date: Optional[date] = None, *, limit: int = 120
) -> list[dict[str, Any]]:
    """Fetch deliverable-futures closes; returns psx_futures_eod rows.

    Tries the market-summary AJAX first (month-format cascade), then the
    public DPS contracts list. Returns an empty list (never fake data) when
    both feeds are unavailable, so the arbitrage and rollover desks render
    their explicit idle states until PSX serves live contract prices.
    """
    trade_date = trade_date or date.today()

    records = _fetch_from_ajax(trade_date, limit=limit)
    if records:
        return records

    records = _fetch_from_fallback_url(trade_date)
    if records:
        return records

    LOGGER.warning(
        "futures: both PSX feeds unavailable this run - psx_futures_eod "
        "stays empty; arbitrage/rollover desks idle (no fabricated data)"
    )
    return []
