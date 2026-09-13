"""Institutional risk & position sizing engine.

Fixed-fractional risk sizing over the active session's actionable signals:

  risk_pkr per trade  = equity * RISK_PER_TRADE_PCT
  stop_distance_pct   = (entry - stop) / entry
  position_value_pkr  = risk_pkr / stop_distance_pct      (risk parity)
  shares              = floor(position_value / entry)

Portfolio-level guardrails applied in priority order (conviction, then
tighter stop geometry):

  - RISK_MAX_PORTFOLIO_HEAT_PCT : total open risk across accepted positions
    never exceeds this fraction of equity; lower-priority candidates are
    trimmed or rejected to respect the cap.
  - RISK_MAX_POSITION_PCT       : any single position's market value is
    capped as a fraction of equity.
  - RISK_MAX_POSITIONS          : hard cap on simultaneous positions.
  - RISK_MIN_STOP_DISTANCE_PCT  : setups whose stop sits closer than this
    (noise-level geometry) are rejected rather than oversized.

Sizing uses only stored session data (entry_reference, stop_loss, ATR from
metadata when present). Nothing is simulated or invented; signals without a
valid long-bias stop are skipped.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from pipeline import db

LOGGER = logging.getLogger(__name__)

RISK_PER_TRADE_PCT = float(os.getenv("RISK_PER_TRADE_PCT", "1.0")) / 100.0
MAX_PORTFOLIO_HEAT_PCT = float(os.getenv("RISK_MAX_PORTFOLIO_HEAT_PCT", "6.0")) / 100.0
MAX_POSITION_PCT = float(os.getenv("RISK_MAX_POSITION_PCT", "20.0")) / 100.0
MAX_POSITIONS = int(os.getenv("RISK_MAX_POSITIONS", "8"))
# Noise floor for stop geometry. The 807-row stop sweep (2026-09) put the
# expectancy peak of the 1.5x-3.0x ATR grid at 1.5x ATR (~1.1% median stop
# distance) - the floor now sits at the calibrated stop, not above it, so the
# engine's own geometry passes sizing instead of being re-widened.
MIN_STOP_DISTANCE_PCT = float(os.getenv("RISK_MIN_STOP_DISTANCE_PCT", "1.0")) / 100.0
# Max gross notional exposure as a fraction of equity (cash guardrail).
MAX_GROSS_EXPOSURE_PCT = float(os.getenv("RISK_MAX_GROSS_EXPOSURE_PCT", "100.0")) / 100.0
# Smallest position worth holding (broker fees dominate below this).
MIN_POSITION_VALUE_PKR = float(os.getenv("RISK_MIN_POSITION_VALUE_PKR", "25000"))

# Signals that represent actionable long setups with a protective stop.
ACTIONABLE_SIGNAL_TYPES = {
    "ACCUMULATION",
    "STEALTH_ACCUMULATION",
    "INSTITUTIONAL_TARGET",
    "MOMENTUM_BREAKOUT",
    "INSIDER_BUYING",
    "LEVERAGE_FLUSH_BOTTOM",
    "VALUE_YIELD",
    "HIGH_YIELD",
}

# Conviction rank for queue priority (higher wins the heat budget first).
_CONVICTIION_RANK = {"HIGH": 3, "ELEVATED": 2, "NOTABLE_VOLUME_SPIKE": 2, "MODERATE": 1}


def _conviction_rank(metadata: dict[str, Any] | None) -> int:
    if not metadata:
        return 0
    return _CONVICTIION_RANK.get(str(metadata.get("conviction", "")).upper(), 0)


def size_positions(
    signals: list[dict[str, Any]],
    *,
    equity_pkr: float,
) -> dict[str, Any]:
    """Allocate the session's signals into a risk-sized book.

    Returns {
      positions: [accepted sized positions],
      rejected:  [{ticker, reason}],
      totals:    {positions, deployed_value_pkr, total_risk_pkr,
                  portfolio_heat_pct, avg_stop_distance_pct}
    }
    """
    if equity_pkr <= 0:
        raise ValueError("equity_pkr must be positive")

    risk_budget_pkr = equity_pkr * RISK_PER_TRADE_PCT
    heat_cap_pkr = equity_pkr * MAX_PORTFOLIO_HEAT_PCT

    # Candidate queue: actionable long setups with valid stop geometry,
    # ranked by conviction then tighter (wider) stop distance quality.
    candidates: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for signal in signals:
        if signal.get("signal_type") not in ACTIONABLE_SIGNAL_TYPES:
            rejected.append({"ticker": signal.get("ticker"), "reason": "NON_ACTIONABLE_TYPE"})
            continue
        entry = signal.get("entry_reference")
        stop = signal.get("stop_loss")
        if entry is None or stop is None or entry <= 0:
            rejected.append({"ticker": signal.get("ticker"), "reason": "NO_ENTRY"})
            continue
        stop_distance = (float(entry) - float(stop)) / float(entry)
        if stop_distance <= 0:
            rejected.append({"ticker": signal.get("ticker"), "reason": "NOT_LONG_BIAS"})
            continue
        if stop_distance < MIN_STOP_DISTANCE_PCT:
            rejected.append(
                {"ticker": signal.get("ticker"), "reason": "STOP_TOO_TIGHT"}
            )
            continue
        candidates.append(
            {
                **signal,
                "_stop_distance_pct": stop_distance,
                "_conv": _conviction_rank(signal.get("metadata")),
            }
        )

    # Priority: conviction desc, then tighter risk geometry (smaller stop
    # distance ranks higher - less price must travel to invalidate).
    candidates.sort(key=lambda c: (-c["_conv"], c["_stop_distance_pct"]))

    positions: list[dict[str, Any]] = []
    deployed_value = 0.0
    total_risk = 0.0
    seen_tickers: set[str] = set()
    gross_cap_pkr = equity_pkr * MAX_GROSS_EXPOSURE_PCT

    for candidate in candidates:
        if len(positions) >= MAX_POSITIONS:
            rejected.append({"ticker": candidate["ticker"], "reason": "MAX_POSITIONS"})
            continue

        # One position per underlying: multiple timeframes may flag the same
        # ticker; only the highest-priority occurrence gets sized.
        ticker_key = str(candidate["ticker"]).upper().strip()
        if ticker_key in seen_tickers:
            rejected.append({"ticker": candidate["ticker"], "reason": "DUPLICATE_TICKER"})
            continue

        stop_distance = candidate["_stop_distance_pct"]
        entry = float(candidate["entry_reference"])

        # Risk-parity notional, then clamp to the per-position cap.
        position_value = risk_budget_pkr / stop_distance
        max_value = equity_pkr * MAX_POSITION_PCT
        clamped = position_value > max_value
        if clamped:
            position_value = max_value

        # Remaining portfolio heat budget.
        trade_risk = position_value * stop_distance
        remaining_heat = heat_cap_pkr - total_risk
        if trade_risk > remaining_heat + 1e-9:
            if remaining_heat <= 1e-9:
                rejected.append({"ticker": candidate["ticker"], "reason": "HEAT_CAP"})
                continue
            # Trim the position to fit the remaining heat budget.
            position_value = remaining_heat / stop_distance
            trade_risk = remaining_heat

        # Gross-exposure guardrail: trim to the remaining cash budget.
        remaining_gross = gross_cap_pkr - deployed_value
        if position_value > remaining_gross:
            if remaining_gross <= 1e-9:
                rejected.append(
                    {"ticker": candidate["ticker"], "reason": "GROSS_EXPOSURE_CAP"}
                )
                continue
            position_value = remaining_gross
            trade_risk = position_value * stop_distance

        shares = int(position_value // entry)
        if shares <= 0 or shares * entry < MIN_POSITION_VALUE_PKR:
            rejected.append({"ticker": candidate["ticker"], "reason": "BELOW_MIN_SIZE"})
            continue

        seen_tickers.add(ticker_key)
        deployed_value += shares * entry
        total_risk += trade_risk
        positions.append(
            {
                "ticker": candidate["ticker"],
                "signal_type": candidate["signal_type"],
                "entry_reference": round(entry, 2),
                "stop_loss": round(float(candidate["stop_loss"]), 2),
                "stop_distance_pct": round(stop_distance * 100.0, 2),
                "shares": shares,
                "position_value_pkr": round(shares * entry, 0),
                "risk_pkr": round(trade_risk, 0),
                "risk_pct_of_equity": round(trade_risk / equity_pkr * 100.0, 3),
                "conviction": (candidate.get("metadata") or {}).get("conviction"),
                "clamped_by_max_position": clamped,
            }
        )

    totals = {
        "positions": len(positions),
        "deployed_value_pkr": round(deployed_value, 0),
        "deployed_pct_of_equity": round(deployed_value / equity_pkr * 100.0, 2),
        "total_risk_pkr": round(total_risk, 0),
        "portfolio_heat_pct": round(total_risk / equity_pkr * 100.0, 3),
        "avg_stop_distance_pct": (
            round(
                sum(p["stop_distance_pct"] for p in positions) / len(positions), 2
            )
            if positions
            else 0.0
        ),
    }
    LOGGER.info(
        "risk engine: %d positions, heat %.2f%% of equity, %d rejected",
        len(positions),
        totals["portfolio_heat_pct"],
        len(rejected),
    )
    return {"positions": positions, "rejected": rejected, "totals": totals}


def size_session_book(
    *,
    equity_pkr: float,
    session_date: str | None = None,
) -> dict[str, Any]:
    """Load the active session's signals from Supabase and size the book.

    session_date defaults to the latest stored session in psx_daily_eod
    (never the wall clock).
    """
    from pipeline.analytics.quant_engine import parse_db_date

    client = db.get_client()
    if session_date:
        active = session_date
    else:
        res = (
            client.table("psx_daily_eod")
            .select("trade_date")
            .gt("volume", 0)
            .order("trade_date", desc=True)
            .limit(10)
            .execute()
        )
        active = None
        for row in res.data:
            day = parse_db_date(row.get("trade_date"))
            if day is not None and day.weekday() < 5:
                active = row["trade_date"]
                break
        if active is None:
            raise RuntimeError("no active session in psx_daily_eod")

    res = (
        client.table("signals_computed")
        .select(
            "trade_date,ticker,timeframe,signal_type,entry_reference,stop_loss,metadata"
        )
        .eq("trade_date", active)
        .limit(500)
        .execute()
    )
    signals = res.data or []
    book = size_positions(signals, equity_pkr=equity_pkr)
    book["session_date"] = active
    return book
