"""SECP / PSX insider & sponsor transaction scraper.

PSX publishes company announcements (including SECP-mandated insider
dealings disclosures / board letters) on the Data Portal. The current
announcements page (https://dps.psx.com.pk/announcements/companies) is
JS-rendered: there is no server-side table and no discoverable JSON
endpoint in the static HTML (verified 2026-09-12). This scraper therefore

1. requests the announcements page,
2. walks every anchored block in discovery order, classifying each as an
   insider disclosure when its text carries a tradable ticker and an
   insider designation, and parses BUY/SELL, quantity and optional rate,
3. returns [] with a logged explanation when PSX's renderer serves no
   parseable disclosures - never fabricated rows.

Row shape matches psx_insider_trades (schema.sql).
"""

from __future__ import annotations

import logging
import os
import re
from datetime import date
from typing import Any, Optional

from bs4 import BeautifulSoup

from pipeline.http_client import http_get

LOGGER = logging.getLogger(__name__)

BASE_URL = "https://dps.psx.com.pk"
ANNOUNCEMENTS_URL = f"{BASE_URL}/announcements/companies"

# Insider designations that qualify a disclosure for the radar.
DESIGNATIONS = (
    "SUBSTANTIAL SHAREHOLDER",
    "SPONSOR",
    "DIRECTOR",
    "CEO",
    "CHIEF EXECUTIVE",
    "EXECUTIVE OFFICER",
    "CFO",
    "COMPANY SECRETARY",
)

ULTRA_HIGH_NOTIONAL_PKR = float(os.getenv("INSIDER_ULTRA_HIGH_NOTIONAL_PKR", "1e7"))
ULTRA_HIGH_DESIGNATIONS = {"Sponsor", "Director"}


def tag_conviction(row: dict[str, Any]) -> str:
    """Conviction tag for one disclosure row.

    ULTRA_HIGH : BUY >= 10M PKR by a Sponsor or Director (the strongest
                 alignment signal on PSX - principal money, not salary).
    HIGH       : BUY >= 10M PKR by any other insider, or BUY >= 2M PKR by
                 a Sponsor/Director.
    STANDARD   : everything else (small buys, sells, unknown notional).
    """
    notional = row.get("notional_pkr")
    if row.get("trade_type") != "BUY" or notional is None:
        return "STANDARD"
    designation = str(row.get("designation") or "")
    if float(notional) >= ULTRA_HIGH_NOTIONAL_PKR:
        if any(d in designation for d in ULTRA_HIGH_DESIGNATIONS):
            return "ULTRA_HIGH"
        return "HIGH"
    if float(notional) >= ULTRA_HIGH_NOTIONAL_PKR / 5.0 and any(
        d in designation for d in ULTRA_HIGH_DESIGNATIONS
    ):
        return "HIGH"
    return "STANDARD"


def build_disclosure_ledger(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Convert stored psx_insider_trades rows into conviction-tagged
    psx_insider_disclosures rows (schema of the institutional ledger).
    """
    ledger: list[dict[str, Any]] = []
    for row in rows:
        trade_type = str(row.get("trade_type") or "").upper()
        quantity = row.get("quantity")
        if trade_type not in {"BUY", "SELL"} or quantity in (None, 0):
            continue
        rate = row.get("rate")
        notional = row.get("notional_pkr")
        if notional is None and rate is not None:
            notional = float(rate) * int(quantity)
        entry = {
            "trade_date": row.get("trade_date"),
            "ticker": str(row.get("ticker") or "").upper()[:16],
            "insider_name": str(row.get("insider_name") or "UNKNOWN"),
            "designation": str(row.get("designation") or "UNKNOWN")[:64],
            "trade_type": trade_type,
            "quantity": int(quantity),
            "rate": rate,
            "notional_pkr": round(float(notional), 2) if notional is not None else None,
            "disclosure_url": row.get("disclosure_url"),
        }
        entry["conviction"] = tag_conviction(entry)
        ledger.append(entry)
    return ledger


_TRADE_RE = re.compile(r"\b(BUY|SELL|BOUGHT|SOLD|PURCHASE|SALE[S]?)\b", re.I)
_QTY_RE = re.compile(r"(\d[\d,]{2,})\s*(?:shares|sh|@)", re.I)
_RATE_RE = re.compile(r"(?:@|rate|RS\.?|PKR)\s*(\d[\d,]*(?:\.\d+)?)", re.I)
_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2}|\d{1,2}\s+[A-Z][a-z]{2,8}\s+\d{4})")
_TICKER_RE = re.compile(r"\(([A-Z]{2,6})\)")


def _classify(text: str) -> Optional[tuple[str, str]]:
    """Return (trade_type, designation) when text is an insider disclosure."""
    if not _TRADE_RE.search(text):
        return None
    upper = text.upper()
    designation = next((d for d in DESIGNATIONS if d in upper), None)
    if designation is None:
        return None
    trade_word = _TRADE_RE.search(text).group(1).upper()  # type: ignore[union-attr]
    trade_type = "SELL" if trade_word in {"SELL", "SOLD", "SALE", "SALES"} else "BUY"
    return trade_type, designation.title()


def _parse_disclosure_text(text: str, anchor_url: Optional[str]) -> Optional[dict[str, Any]]:
    """Extract one insider-trade row from an announcement blurb."""
    classified = _classify(text)
    if classified is None:
        return None
    trade_type, designation = classified

    ticker_match = _TICKER_RE.search(text)
    if ticker_match is None:
        return None
    ticker = ticker_match.group(1).upper()

    qty_match = _QTY_RE.search(text)
    if qty_match is None:
        return None
    try:
        quantity = int(qty_match.group(1).replace(",", ""))
    except ValueError:
        return None
    if quantity <= 0:
        return None

    rate_match = _RATE_RE.search(text)
    rate = float(rate_match.group(1).replace(",", "")) if rate_match else None

    trade_day: Optional[date] = None
    date_match = _DATE_RE.search(text)
    if date_match:
        from pipeline.parsing import to_date

        trade_day = to_date(date_match.group(1))

    notional = quantity * rate if rate is not None else None

    return {
        "ticker": ticker[:16],
        "insider_name": "DISCLOSED-ANNOUNCEMENT",
        "designation": designation[:64],
        "trade_type": trade_type,
        "quantity": quantity,
        "rate": rate,
        "notional_pkr": round(notional, 2) if notional is not None else None,
        "disclosure_url": anchor_url,
        "trade_date": trade_day.isoformat() if trade_day else None,
    }


def fetch_insider_trades(reference_day: Optional[date] = None) -> list[dict[str, Any]]:
    """Scrape today's insider/sponsor disclosures from PSX announcements.

    Returns rows for psx_insider_trades. Date-less rows are stamped with
    ``reference_day`` (the session being processed). An unparseable or
    JS-only page yields [] with a warning - the INSIDER_RADAR desk then
    stays honestly empty until PSX's feed is parseable again.
    """
    response = http_get(
        ANNOUNCEMENTS_URL,
        headers={"Referer": BASE_URL + "/"},
        timeout=25.0,
    )
    soup = BeautifulSoup(response.text, "html.parser")

    rows: list[dict[str, Any]] = []
    seen: set[tuple] = set()
    for anchor in soup.find_all("a", href=True):
        text = anchor.get_text(" ", strip=True)
        if len(text) < 30:
            continue
        parsed = _parse_disclosure_text(
            text, anchor["href"] if anchor["href"].startswith("http") else BASE_URL + anchor["href"]
        )
        if parsed is None:
            continue
        trade_day = parsed.pop("trade_date") or (
            reference_day.isoformat() if reference_day else date.today().isoformat()
        )
        parsed["trade_date"] = trade_day
        key = (
            parsed["trade_date"], parsed["ticker"], parsed["insider_name"],
            parsed["quantity"], parsed["trade_type"],
        )
        if key in seen:
            continue
        seen.add(key)
        rows.append(parsed)

    if rows:
        LOGGER.info("insider: %d disclosures parsed", len(rows))
    else:
        LOGGER.warning(
            "insider: PSX announcements page is JS-rendered / yielded no "
            "parseable disclosures; INSIDER_RADAR stays empty (no fabricated rows)"
        )
    return rows
