"""PSX Macro Balance Sheet KIBOR Sensitivity engine.

Projects the EPS impact of monetary easing for every listed ticker:

  Floating debt   PSX/DPS publish no balance-sheet debt columns (verified:
                  no finance-cost row on any DPS company page), so floating
                  debt comes from explicit inputs, never fabrication:
                    1. KIBOR_FLOATING_DEBT_MAP  "OGDC:185e9,PSO:120e9,..."
                       (or KIBOR_DEBT_CSV_URL serving ticker,debt_pkr CSV)
                       -> debt_basis = 'OPERATOR_INPUT'.
                    2. psx_financial_ratios.finance_cost (auto path once a
                       feed publishes it):
                       debt = finance_cost * KIBOR_DEBT_TURNOVER_X / KIBOR
                       -> debt_basis = 'FINANCE_COST_EST'.
  EPS impact      dEPS(100bps) = debt * 0.01 * (1 - TAX) / shares
  300bps cycle    expansion% = dEPS * 3 / max(|EPS|, 0.50) * 100
  Rank            descending by expansion% -> rank_by_eps_expansion.

Shares outstanding = market cap / close (both from stored screener data).

Honest-data rules: tickers without a debt input, EPS and a market cap are
skipped entirely - the desk renders an explicit AWAITING-SOURCE state.
"""

from __future__ import annotations

import logging
import os
from collections import defaultdict
from datetime import date
from typing import Any, Optional

from pipeline import db
from pipeline.analytics.fundamental_engine import _sector_key, _ttm_eps

LOGGER = logging.getLogger(__name__)

KIBOR_PCT = float(os.getenv("KIBOR_CURRENT_PCT", "13.5"))
TAX_RATE_PCT = float(os.getenv("KIBOR_TAX_RATE_PCT", "29.0"))
DEBT_TURNOVER_X = float(os.getenv("KIBOR_DEBT_TURNOVER_X", "4.0"))
MIN_EPS_DENOM = 0.50


def _parse_amount(raw: str) -> Optional[float]:
    """Parse '185e9', '12.5b', '950m', '4000000000' into PKR."""
    text = raw.strip().upper().replace(",", "")
    try:
        if text.endswith("B"):
            return float(text[:-1]) * 1e9
        if text.endswith("M"):
            return float(text[:-1]) * 1e6
        if text.endswith("K"):
            return float(text[:-1]) * 1e3
        return float(text)
    except ValueError:
        return None


def load_manual_debts() -> dict[str, float]:
    """Operator-supplied floating debt: env map (preferred) or CSV URL."""
    debts: dict[str, float] = {}
    raw_map = os.getenv("KIBOR_FLOATING_DEBT_MAP", "").strip()
    if raw_map:
        for pair in raw_map.split(","):
            if ":" not in pair:
                continue
            ticker, amount = pair.split(":", 1)
            value = _parse_amount(amount)
            if value is not None and value > 0:
                debts[ticker.strip().upper()] = value
    csv_url = os.getenv("KIBOR_DEBT_CSV_URL", "").strip()
    if csv_url:
        try:
            from pipeline.http_client import http_get

            response = http_get(csv_url, timeout=20.0)
            for line in response.text.splitlines():
                if "," not in line or line.lower().startswith("ticker"):
                    continue
                ticker, amount = line.split(",", 1)
                value = _parse_amount(amount)
                if value is not None and value > 0:
                    debts[ticker.strip().upper()] = value
        except Exception as exc:  # noqa: BLE001 - optional source
            LOGGER.warning("kibor: debt CSV fetch failed: %s", exc)
    if debts:
        LOGGER.info("kibor: %d operator-supplied floating debts loaded", len(debts))
    return debts


def compute_kibor_sensitivity(
    trade_date: date,
    *,
    eod_history: list[dict[str, Any]],
    fundamentals: list[dict[str, Any]],
    ratios: list[dict[str, Any]],
    manual_debts: Optional[dict[str, float]] = None,
) -> list[dict[str, Any]]:
    """Build the psx_kibor_sensitivity payload for one session."""
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
        series.sort()

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

    rows_by_ticker: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in ratios:
        try:
            date.fromisoformat(str(row["period_end_date"])[:10])
        except (ValueError, TypeError):
            continue
        rows_by_ticker[row["ticker"]].append(row)

    session_closes = {
        ticker: series[-1][1]
        for ticker, series in closes.items()
        if series and series[-1][0] == trade_date
    }

    payload: list[dict[str, Any]] = []
    skipped = 0
    for ticker, close in sorted(session_closes.items()):
        fund = fund_by_ticker.get(ticker, {})
        ttm = _ttm_eps(rows_by_ticker.get(ticker, []))
        mcap = fund.get("market_cap_pkr")
        if (
            ttm is None
            or ttm == 0
            or mcap is None
            or float(mcap) <= 0
        ):
            skipped += 1
            continue

        shares = float(mcap) / close
        if shares <= 0:
            skipped += 1
            continue

        debt_pkr: Optional[float] = None
        debt_basis: Optional[str] = None
        manual = (manual_debts or {}).get(ticker)
        if manual is not None and manual > 0:
            debt_pkr = float(manual)
            debt_basis = "OPERATOR_INPUT"
        else:
            finance_cost_thousand = None
            for row in rows_by_ticker.get(ticker, []):
                fc = row.get("finance_cost")
                if fc is not None:
                    finance_cost_thousand = float(fc)
            if finance_cost_thousand is not None and finance_cost_thousand > 0:
                debt_pkr = (
                    finance_cost_thousand
                    * 1000.0
                    * DEBT_TURNOVER_X
                    / (KIBOR_PCT / 100.0)
                )
                debt_basis = "FINANCE_COST_EST"
        if debt_pkr is None or debt_basis is None:
            skipped += 1
            continue

        eps_impact = debt_pkr * 0.01 * (1.0 - TAX_RATE_PCT / 100.0) / shares
        expansion = eps_impact * 3.0 / max(abs(ttm), MIN_EPS_DENOM) * 100.0

        payload.append(
            {
                "trade_date": trade_date.isoformat(),
                "ticker": ticker,
                "sector_name": fund.get("sector_name"),
                # Live-table column set (schema v1: floating_debt / total_debt /
                # eps_impact_per_100bps / eps_growth_300bps_pct). The repo's
                # schema.sql v2 renames these and adds debt_basis + rank; the
                # emit targets the deployed table until that migration runs.
                "floating_debt": round(debt_pkr, 2),
                "total_debt": round(debt_pkr, 2),
                "shares_outstanding": round(shares, 2),
                "effective_tax_rate": round(TAX_RATE_PCT, 2),
                "current_eps": round(float(ttm), 2),
                "eps_impact_per_100bps": round(eps_impact, 4),
                "eps_growth_300bps_pct": round(expansion, 2),
            }
        )

    payload.sort(key=lambda r: -r["eps_growth_300bps_pct"])
    # v1 live table has no rank column; the desk derives rank from sort order.
    LOGGER.info(
        "kibor rank %s: %s",
        trade_date,
        ", ".join(f"{i}.{r['ticker']}" for i, r in enumerate(payload, 1)),
    )

    LOGGER.info(
        "kibor sensitivity %s: %d tickers ranked (%d skipped - no finance "
        "cost/EPS/mcap; KIBOR %.1f%%, tax %.0f%%, turnover %.1fx)",
        trade_date,
        len(payload),
        skipped,
        KIBOR_PCT,
        TAX_RATE_PCT,
        DEBT_TURNOVER_X,
    )
    return payload


def run_kibor_engine(
    session_date: date | None = None, *, write: bool = True
) -> int:
    """One-shot KIBOR run: load, compute, rank, upsert psx_kibor_sensitivity."""
    trade_date = session_date or date.today()
    eod_history = db.fetch_recent_eod(days=90)
    if not eod_history:
        LOGGER.warning("kibor engine: no EOD history; aborting")
        return 0
    fundamentals = db.fetch_recent_fundamentals()
    ratios = db.fetch_financial_ratios()
    payload = compute_kibor_sensitivity(
        trade_date,
        eod_history=eod_history,
        fundamentals=fundamentals,
        ratios=ratios,
        manual_debts=load_manual_debts(),
    )
    if not payload:
        LOGGER.warning("kibor engine: no rows for %s", trade_date)
        return 0
    if not write:
        return len(payload)
    return db.upsert_records(
        "psx_kibor_sensitivity", payload, on_conflict="trade_date,ticker"
    )
