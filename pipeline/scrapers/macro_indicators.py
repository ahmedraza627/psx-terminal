"""Global macro & commodity indicator ingestion -> psx_macro_indicator_prices.

Sources (all free, keyless, fetched through the shared hardended session):
  - Stooq daily CSV  https://stooq.com/q/d/l/?s=<SYM>&i=d
      CL.F   WTI crude front-month        (proxy for Arab Light differentials)
      CB.F   Brent crude front-month
      XAUUSD gold spot                    (safe-haven / PKR real-rates tell)
      DX.F   ICE dollar index             (global USD leg)
      YAR.OL Yara International           (global urea / fertilizer proxy)
      GLEN.UK Glencore                    (global coal / bulk commodity proxy)
      MT.US  ArcelorMittal                (global steel proxy)
  - open.er-api.com/v6/latest/USD       live USD/PKR spot (already a house
      source); the PKR time series ACCUMULATES one row per run because no free
      historical PKR feed exists - correlations activate once ~60 sessions
      are stored, and never before.

Arab Light note: Saudi OSP differentials are not freely published; WTI/Brent
are the tradable proxies and the desk labels them as such. Every row stores
the raw close; interpretation lives in the correlation engine, never here.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import date, datetime, timedelta
from typing import Any, Optional

from pipeline.http_client import http_get

LOGGER = logging.getLogger(__name__)

STOOQ_CSV_URL = "https://stooq.com/q/d/l/"
ER_API_URL = "https://open.er-api.com/v6/latest/USD"

# driver_code -> (stooq symbol, human label). Proxies are labeled as proxies.
STOOQ_DRIVERS: dict[str, tuple[str, str]] = {
    "WTI": ("cl.f", "WTI Crude (Arab Light proxy)"),
    "BRENT": ("cb.f", "Brent Crude"),
    "XAU": ("xauusd", "Gold Spot"),
    "DXY": ("dx.f", "US Dollar Index"),
    "UREA_PROXY": ("yar.ol", "Yara Intl (Global Urea proxy)"),
    "COAL_PROXY": ("glen.uk", "Glencore (Global Coal proxy)"),
    "STEEL_PROXY": ("mt.us", "ArcelorMittal (Global Steel proxy)"),
}
USD_PKR_DRIVER = "USDPKR"


def _parse_stooq_csv(driver_code: str, payload: str) -> list[dict[str, Any]]:
    """Parse Stooq's Date,Open,High,Low,Close,Volume daily CSV."""
    rows: list[dict[str, Any]] = []
    reader = csv.DictReader(io.StringIO(payload))
    for row in reader:
        raw_date = (row.get("Date") or "").strip()
        raw_close = (row.get("Close") or "").strip()
        if not raw_date or not raw_close:
            continue
        try:
            trade_date = datetime.strptime(raw_date, "%Y-%m-%d").date()
            close = float(raw_close)
        except (ValueError, TypeError):
            continue
        if close <= 0:
            continue
        rows.append(
            {
                "driver_code": driver_code,
                "trade_date": trade_date.isoformat(),
                "close": close,
                "source": "STOOQ",
            }
        )
    return rows


def fetch_macro_history(days: int = 450) -> list[dict[str, Any]]:
    """Pull daily closes for every Stooq driver within the trailing window."""
    cutoff = date.today() - timedelta(days=days)
    out: list[dict[str, Any]] = []
    for driver_code, (symbol, label) in STOOQ_DRIVERS.items():
        try:
            response = http_get(
                STOOQ_CSV_URL,
                params={"s": symbol, "i": "d"},
                timeout=30.0,
            )
            rows = _parse_stooq_csv(driver_code, response.text)
        except Exception as exc:  # noqa: BLE001 - one dead driver never blocks
            LOGGER.warning("macro driver %s (%s) fetch failed: %s", driver_code, label, exc)
            continue
        kept = [r for r in rows if datetime.strptime(r["trade_date"], "%Y-%m-%d").date() >= cutoff]
        LOGGER.info("macro driver %s: %d rows (of %d total)", driver_code, len(kept), len(rows))
        out.extend(kept)
    return out


def fetch_usdpkr_spot() -> Optional[dict[str, Any]]:
    """Today's USD/PKR spot appended to the accumulating series.

    No free historical PKR feed exists, so the series grows one row per
    pipeline run. The engine treats short series honestly: below the minimum
    pair count it emits no correlation, never a guess.
    """
    try:
        payload = http_get(ER_API_URL, timeout=20.0).json()
        pkr = payload.get("rates", {}).get("PKR")
        if not pkr or float(pkr) <= 0:
            LOGGER.warning("er-api: no PKR rate in payload")
            return None
        return {
            "driver_code": USD_PKR_DRIVER,
            "trade_date": date.today().isoformat(),
            "close": round(float(pkr), 4),
            "source": "ER_API",
        }
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("USD/PKR spot fetch failed: %s", exc)
        return None


def collect_macro_rows(days: int = 450) -> list[dict[str, Any]]:
    """Everything to upsert for this run: Stooq history + PKR spot."""
    rows = fetch_macro_history(days=days)
    spot = fetch_usdpkr_spot()
    if spot is not None:
        rows.append(spot)
    LOGGER.info("macro indicators: %d rows collected", len(rows))
    return rows