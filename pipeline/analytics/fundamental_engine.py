"""Fundamental Alpha & Research engine (PSX-adapted valuation model).

Produces one psx_equity_research row per ticker per session.

Valuation model — PSX_INSTITUTIONAL_V1 (replaces the US Graham EPV, whose
4.4/y bond factor mis-prices PKR names under 13-15% PIB yields and assigned
absurd -78% "overvaluation" to cash-generating leaders like OGDC):

  TTM EPS     the annual panel's current-fiscal-year EPS print is the
              trailing-twelve-month EPS (verified against DPS screener PE
              TTM); fallback = sum of the last 4 standalone quarterly
              prints. Never synthesized when prints are missing.
  Component A Intrinsic_PE   = TTM EPS x Sector Normal P/E
                              (E&P 6.0x, Fertilizer 7.5x, Cement 7.0x,
                               Tech 12.0x, Commercial Banks 5.0x,
                               default 6.5x - env-tunable).
  Component B Intrinsic_Yield = TTM DPS / K_e with
                              K_e = PIB yield (13.5%) - dividend growth (4%)
                                  = 9.5% hurdle (env-tunable).
                              TTM DPS = screener dividend yield % x close
                              (market-implied trailing DPS).
  Composite   regular dividend payer (TTM DPS > 0):
                0.60 x Intrinsic_PE + 0.40 x Intrinsic_Yield
              non-payer: Intrinsic_PE.

  alpha_score        0-100 composite of valuation (earnings yield / PSX
                     discount), quality (margin), growth and shareholder
                     yield; weights env-tunable, cross-sectional ranks.
  valuation_status   UNDERVALUED at >= +15% discount, OVERVALUED at
                     <= -15%, else FAIR_VALUE (env-tunable bands).
  risk_flag          HIGH_DEBT_BURDEN needs D/E (not published by DPS yet ->
                     flag stays CLEAN today; the hook activates the moment a
                     balance-sheet feed lands).

Honest-data rules: a ticker with no TTM EPS gets a NULL intrinsic value and
NULL discount - it is scored only on the factors that are real.
"""

from __future__ import annotations

import logging
import os
from collections import defaultdict
from datetime import date
from typing import Any, Optional

from pipeline import db

LOGGER = logging.getLogger(__name__)

MODEL_VERSION = "PSX_MF_V1"

# ---- env-tunable weights (sum normalised to 100 internally) ---------------- #
W_VALUATION = float(os.getenv("ALPHA_W_VALUATION", "35"))
W_QUALITY = float(os.getenv("ALPHA_W_QUALITY", "25"))
W_GROWTH = float(os.getenv("ALPHA_W_GROWTH", "20"))
W_YIELD = float(os.getenv("ALPHA_W_YIELD", "20"))

UNDERVALUED_BAND = float(os.getenv("ALPHA_UNDERVALUED_BAND_PCT", "15"))
OVERVALUED_BAND = float(os.getenv("ALPHA_OVERVALUED_BAND_PCT", "-15"))

# ---- PSX Institutional Valuation Multi-Factor Model tunables --------------- #
SECTOR_TARGET_PES = {
    "EP": float(os.getenv("ALPHA_PE_EP", "6.0")),
    "FERTILIZER": float(os.getenv("ALPHA_PE_FERTILIZER", "7.5")),
    "CEMENT": float(os.getenv("ALPHA_PE_CEMENT", "7.0")),
    "TECH": float(os.getenv("ALPHA_PE_TECH", "12.0")),
    "BANKS": float(os.getenv("ALPHA_PE_BANKS", "5.0")),
}
DEFAULT_TARGET_PE = float(os.getenv("ALPHA_PE_DEFAULT", "6.5"))

PIB_YIELD_PCT = float(os.getenv("ALPHA_PIB_YIELD_PCT", "13.5"))
DIV_GROWTH_PCT = float(os.getenv("ALPHA_DIV_GROWTH_PCT", "4.0"))
KE_REQUIRED = max((PIB_YIELD_PCT - DIV_GROWTH_PCT) / 100.0, 0.01)

W_PE_VALUE = float(os.getenv("ALPHA_W_PE_VALUE", "0.60"))
W_DIV_FLOOR = float(os.getenv("ALPHA_W_DIV_FLOOR", "0.40"))

MAX_DISCOUNT_PCT = 9999.99  # NUMERIC(6,2) column bound


def _clamp_pct(value: Optional[float]) -> Optional[float]:
    """Clamp to the +/-9,999.99 bound of the NUMERIC(6,2) discount column."""
    if value is None:
        return None
    return round(max(-MAX_DISCOUNT_PCT, min(MAX_DISCOUNT_PCT, value)), 2)


def _sector_key(sector_name: Optional[str]) -> str:
    """Map a PSX sector label to a valuation-model sector key."""
    s = (sector_name or "").upper()
    if "EXPLORATION" in s or "E&P" in s or "OIL & GAS" in s:
        return "EP"
    if "FERTILIZER" in s:
        return "FERTILIZER"
    if "CEMENT" in s:
        return "CEMENT"
    if "TECHNOLOGY" in s or "SOFTWARE" in s or "IT " in f"{s} ":
        return "TECH"
    if "BANK" in s:
        return "BANKS"
    return "DEFAULT"


def _sector_target_pe(sector_name: Optional[str]) -> float:
    key = _sector_key(sector_name)
    if key == "DEFAULT":
        return DEFAULT_TARGET_PE
    return SECTOR_TARGET_PES[key]


def _ttm_eps(rows: list[dict[str, Any]]) -> Optional[float]:
    """TTM EPS from stored ratio rows for one ticker.

    Preference order (verified against DPS company pages):
      1. The latest annual-panel print (current fiscal year = trailing 12m).
      2. Sum of the last 4 standalone quarterly prints.
    """
    annual = [
        r for r in rows
        if str(r.get("fiscal_period", "")).upper().endswith("-A")
        and r.get("eps") is not None
    ]
    if annual:
        latest = max(annual, key=lambda r: str(r["period_end_date"]))
        value = float(latest["eps"])
        if value > 0:
            return value

    quarterly = [
        (str(r["period_end_date"]), float(r["eps"]))
        for r in rows
        if r.get("eps") is not None
    ]
    quarterly.sort()
    last4 = quarterly[-4:]
    if len(last4) == 4 and all(e > 0 for _, e in last4):
        return round(sum(e for _, e in last4), 2)
    return None


def _percentile_score(
    values: dict[str, float], ticker: str, *, invert: bool = False
) -> float:
    """Cross-sectional 0-1 score of ticker within values (higher=better)."""
    if ticker not in values or not values:
        return 0.0
    sorted_vals = sorted(values.values())
    n = len(sorted_vals)
    rank = sum(1 for v in sorted_vals if v <= values[ticker])
    score = (rank - 1) / max(n - 1, 1)
    return (1.0 - score) if invert else score


def _risk_flag(ratio_row: Optional[dict[str, Any]]) -> str:
    """Balance-sheet risk classification (activates when D/E exists)."""
    if ratio_row is None:
        return "CLEAN"
    de = ratio_row.get("debt_to_equity")
    if de is not None and float(de) >= 1.5:
        return "HIGH_DEBT_BURDEN"
    return "CLEAN"


def compute_research_matrix(
    trade_date: date,
    *,
    eod_history: list[dict[str, Any]],
    fundamentals: list[dict[str, Any]],
    ratios: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build the psx_equity_research payload for one session.

    ``eod_history``  : recent psx_daily_eod rows (close series per ticker)
    ``fundamentals`` : latest psx_fundamentals snapshot (PE, yield, sector)
    ``ratios``       : psx_financial_ratios rows (eps, margins, growth)
    """
    closes: dict[str, list[tuple[date, float]]] = defaultdict(list)
    for row in eod_history:
        try:
            day = date.fromisoformat(str(row["trade_date"])[:10])
        except (ValueError, TypeError):
            continue
        close = row.get("close_price")
        if close is None or float(close) <= 0:
            continue
        closes[row["ticker"]].append((day, float(close)))
    for series in closes.values():
        series.sort()  # rows arrive trade_date DESC; [-1] must be the newest

    fund_by_ticker: dict[str, dict[str, Any]] = {}
    fund_day: Optional[date] = None
    for row in fundamentals:
        try:
            day = date.fromisoformat(str(row["trade_date"])[:10])
        except (ValueError, TypeError):
            continue
        if fund_day is None or day > fund_day:
            fund_day = day
    for row in fundamentals:
        try:
            day = date.fromisoformat(str(row["trade_date"])[:10])
        except (ValueError, TypeError):
            continue
        if fund_day is not None and day == fund_day:
            fund_by_ticker[row["ticker"]] = row

    ratios_by_ticker: dict[str, dict[str, Any]] = {}
    rows_by_ticker: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in ratios:
        try:
            end = date.fromisoformat(str(row["period_end_date"])[:10])
        except (ValueError, TypeError):
            continue
        ticker = row["ticker"]
        rows_by_ticker[ticker].append(row)
        current = ratios_by_ticker.get(ticker)
        if current is None or end > date.fromisoformat(
            str(current["period_end_date"])[:10]
        ):
            ratios_by_ticker[ticker] = row

    session_closes = {
        ticker: series[-1][1]
        for ticker, series in closes.items()
        if series and series[-1][0] == trade_date
    }

    # ---- raw factor values per ticker -------------------------------------- #
    earnings_yield: dict[str, float] = {}
    div_yield: dict[str, float] = {}
    margin: dict[str, float] = {}
    growth: dict[str, float] = {}
    psx_discount: dict[str, float] = {}

    for ticker, close in session_closes.items():
        fund = fund_by_ticker.get(ticker, {})
        pe = fund.get("pe_ratio")
        if pe is not None and float(pe) > 0:
            earnings_yield[ticker] = 100.0 / float(pe)
        dy = fund.get("dividend_yield")
        if dy is not None:
            div_yield[ticker] = float(dy)
        ratio_row = ratios_by_ticker.get(ticker)
        npm = ratio_row.get("net_profit_margin_pct") if ratio_row else None
        if npm is not None:
            margin[ticker] = float(npm)
        sg = ratio_row.get("sales_growth_yoy_pct") if ratio_row else None
        if sg is None and ratio_row is not None:
            sg = ratio_row.get("eps_growth_yoy_pct")
        if sg is not None:
            growth[ticker] = float(sg)

        ttm = _ttm_eps(rows_by_ticker.get(ticker, []))
        if ttm is None or ttm <= 0 or close <= 0:
            continue
        target_pe = _sector_target_pe(
            (fund.get("sector_name") if fund else None)
        )
        intrinsic_pe = ttm * target_pe
        # TTM DPS from the screener's market-implied trailing dividend yield.
        dps = (float(dy) / 100.0) * close if dy is not None and dy > 0 else 0.0
        if dps > 0:
            intrinsic = W_PE_VALUE * intrinsic_pe + W_DIV_FLOOR * (dps / KE_REQUIRED)
        else:
            intrinsic = intrinsic_pe
        if intrinsic is not None and intrinsic > 0:
            psx_discount[ticker] = (intrinsic / close - 1.0) * 100.0

    weights = {
        "valuation": max(W_VALUATION, 0.0),
        "quality": max(W_QUALITY, 0.0),
        "growth": max(W_GROWTH, 0.0),
        "yield": max(W_YIELD, 0.0),
    }
    weight_total = sum(weights.values()) or 1.0

    payload: list[dict[str, Any]] = []
    for ticker, close in sorted(session_closes.items()):
        factor_scores = {
            "valuation": max(
                _percentile_score(earnings_yield, ticker),
                _percentile_score(psx_discount, ticker),
            ),
            "quality": _percentile_score(margin, ticker),
            "growth": _percentile_score(growth, ticker),
            "yield": _percentile_score(div_yield, ticker),
        }
        alpha_score = round(
            sum(weights[name] * score for name, score in factor_scores.items())
            / weight_total
            * 100.0
        )
        alpha_score = max(0, min(100, int(alpha_score)))

        discount = psx_discount.get(ticker)
        if discount is None:
            status = "FAIR_VALUE"
        elif discount >= UNDERVALUED_BAND:
            status = "UNDERVALUED"
        elif discount <= OVERVALUED_BAND:
            status = "OVERVALUED"
        else:
            status = "FAIR_VALUE"

        # Provenance: rebuild the composite leg values for the blotter.
        fund = fund_by_ticker.get(ticker, {})
        ttm = _ttm_eps(rows_by_ticker.get(ticker, []))
        target_pe_used: Optional[float] = None
        dividend_floor: Optional[float] = None
        intrinsic: Optional[float] = None
        if ttm is not None and ttm > 0 and discount is not None:
            target_pe_used = _sector_target_pe(
                fund.get("sector_name") if fund else None
            )
            intrinsic_pe = ttm * target_pe_used
            dy = fund.get("dividend_yield") if fund else None
            dps = (
                (float(dy) / 100.0) * close
                if dy is not None and dy > 0
                else 0.0
            )
            if dps > 0:
                dividend_floor = round(dps / KE_REQUIRED, 2)
                intrinsic = W_PE_VALUE * intrinsic_pe + W_DIV_FLOOR * dividend_floor
            else:
                intrinsic = intrinsic_pe
            intrinsic = round(intrinsic, 2)

        payload.append(
            {
                "trade_date": trade_date.isoformat(),
                "ticker": ticker,
                "alpha_score": alpha_score,
                "intrinsic_value_pkr": intrinsic,
                "valuation_discount_pct": _clamp_pct(discount),
                "valuation_status": status,
                "balance_sheet_risk_flag": _risk_flag(
                    ratios_by_ticker.get(ticker)
                ),
                "target_pe_used": (
                    round(target_pe_used, 2)
                    if target_pe_used is not None
                    else None
                ),
                "dividend_floor_pkr": dividend_floor,
                "model_version": MODEL_VERSION,
            }
        )

    LOGGER.info(
        "research matrix %s: %d tickers scored (%d with PSX-MF intrinsic value)",
        trade_date,
        len(payload),
        sum(1 for r in payload if r["intrinsic_value_pkr"] is not None),
    )
    return payload


_PROVENANCE_OK: Optional[bool] = None


def _provenance_columns_supported() -> bool:
    """True when psx_equity_research carries the PSX-MF provenance columns.

    Probing once per process keeps runs green before schema.sql's ALTERs are
    applied (the payload then drops the extra columns instead of failing).
    """
    global _PROVENANCE_OK
    if _PROVENANCE_OK is not None:
        return _PROVENANCE_OK
    try:
        db.get_client().table("psx_equity_research").select(
            "target_pe_used,dividend_floor_pkr,model_version"
        ).limit(1).execute()
        _PROVENANCE_OK = True
    except Exception as exc:  # noqa: BLE001 - narrow via message
        message = str(exc)
        if "target_pe_used" in message or "42703" in message or "PGRST204" in message:
            LOGGER.warning(
                "research: provenance columns missing - run schema.sql; "
                "writing base columns only"
            )
            _PROVENANCE_OK = False
        else:
            _PROVENANCE_OK = True  # transient failure: try full payload
    return _PROVENANCE_OK


def run_fundamental_engine(
    session_date: date | None = None, *, write: bool = True
) -> int:
    """One-shot research engine run: load, score, upsert psx_equity_research."""
    trade_date = session_date or date.today()
    eod_history = db.fetch_recent_eod(days=90)
    if not eod_history:
        LOGGER.warning("research engine: no EOD history; aborting")
        return 0
    fundamentals = db.fetch_recent_fundamentals()
    ratios = db.fetch_financial_ratios()
    payload = compute_research_matrix(
        trade_date,
        eod_history=eod_history,
        fundamentals=fundamentals,
        ratios=ratios,
    )
    if not payload:
        LOGGER.warning("research engine: no rows for %s", trade_date)
        return 0
    if not write:
        return len(payload)
    if not _provenance_columns_supported():
        payload = [
            {k: v for k, v in row.items() if k not in
             ("target_pe_used", "dividend_floor_pkr", "model_version")}
            for row in payload
        ]
    return db.upsert_records(
        "psx_equity_research", payload, on_conflict="trade_date,ticker"
    )
