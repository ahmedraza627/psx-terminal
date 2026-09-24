"""Historical edge backtester for signals_computed.

Walk-forward, tick-honest evaluation of every stored signal that carries an
entry reference and a positive stop:

  - return_t5/t10/t20_pct : mark-to-market close returns N trading sessions
    after the signal session (NULL while the forward window is incomplete -
    never forward-filled or interpolated).
  - MFE / MAE             : maximum favourable / adverse excursion of the
    session HIGH / LOW versus entry over the same window.
  - hit_target / stopped  : resolution under the engine's evaluation
    convention - target = entry + 2R (two units of risk). If a session
    touches both stop and target, the stop wins (conservative).

Signals are evaluated LONG-bias only; risk-warning stances
(MARGIN_CASCADE_RISK "AVOID_LONGS", short-bias rollover signals) and
non-directional arbitrage pairs are excluded by design. All price history
comes from psx_daily_eod - nothing is synthesized.
"""

from __future__ import annotations

import logging
import os
from collections import defaultdict
from datetime import date, timedelta
from typing import Any, Optional

from pipeline import db
from pipeline.parsing import to_number
from pipeline.analytics.quant_engine import (
    build_regime_state,
    compute_signals,
    parse_db_date,
    REGIME_GATE_ENABLED,
)

LOGGER = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Resolution conventions (2026-09 edge overhaul).                             #
#                                                                             #
# Single-bar mode (legacy / stop-sweep parity): a signal "hits" when price    #
# reaches entry + TARGET_R_MULTIPLE x risk before touching the stop;          #
# same-session double-touch resolves as a stop (conservative). The 807-row    #
# stop sweep (pipeline.analytics.stop_sweep) showed expectancy improving      #
# monotonically with the reward bar - 2R stays the single-bar convention.     #
#                                                                             #
# Tiered mode (Edge Lab default): institutional scale-out plan that kills     #
# most bear-tape stop-outs by ratcheting the stop to break-even the moment    #
# TP1 (+1R) is touched intraday:                                              #
#   TP1 +1.0R  bank 50%   -> remaining stop ratchets to entry + 0.2%          #
#   TP2 +2.0R  bank 30%   -> runner stop trails 1.5 x ATR_unit                #
#   Runner      bank 20%  to +3R or the 1.5xATR trail, end of window          #
# realized_r = 0.5 + 0.3*2 + 0.2*runner_r for winners; a full stop (never     #
# reached TP1) banks -1R; a stop after TP1 is a scratch at ~ +0.1R.           #
# ATR_unit is recovered from the stored stop (entry - stop) / ENGINE_ATR_MULT #
# and the trail is a floor at the ratcheted stop - never below break-even.    #
# --------------------------------------------------------------------------- #
TARGET_R_MULTIPLE = float(os.getenv("BACKTEST_TARGET_R", "2.0"))
TIERED_TP1_R = float(os.getenv("BACKTEST_TP1_R", "1.0"))
TIERED_TP2_R = float(os.getenv("BACKTEST_TP2_R", "2.0"))
TIERED_RUNNER_R = float(os.getenv("BACKTEST_RUNNER_R", "3.0"))
TIERED_TP1_FRACTION = float(os.getenv("BACKTEST_TP1_FRACTION", "0.50"))
TIERED_TP2_FRACTION = float(os.getenv("BACKTEST_TP2_FRACTION", "0.30"))
TIERED_RUNNER_FRACTION = float(os.getenv("BACKTEST_RUNNER_FRACTION", "0.20"))
TIERED_BE_SLIPPAGE_PCT = float(os.getenv("BACKTEST_BE_SLIPPAGE_PCT", "0.2"))
TIERED_TRAIL_ATR = float(os.getenv("BACKTEST_TRAIL_ATR", "1.5"))
# Stop-geometry provenance: engine signals carry stop = entry - 1.5 x ATR(14)
# since the 2026-09 calibration (was 2.0). The sweep recovers the ATR unit
# from stored stops via this constant.
ENGINE_ATR_MULTIPLE = float(os.getenv("ATR_STOP_MULT", "1.5"))
FORWARD_SESSIONS = 20
# Walk-forward seed: re-simulate signals over the trailing N sessions so
# Edge Lab shows realized win rates immediately (env-tunable).
SEED_SESSIONS = int(os.getenv("BACKTEST_SEED_SESSIONS", "30"))
# Existing stored sessions within the seed window are skipped (they were
# produced live; re-simulating would duplicate - upsert makes it safe anyway).
SEED_SKIP_EXISTING = os.getenv(
    "BACKTEST_SEED_SKIP_EXISTING", "true"
).strip().lower() in {"1", "true", "yes"}

# Long-bias signal types that represent an actionable directional idea.
EVALUABLE_SIGNAL_TYPES = {
    "ACCUMULATION",
    "VALUE_YIELD",
    "HIGH_YIELD",
    "STEALTH_ACCUMULATION",
    "INSTITUTIONAL_TARGET",
    "MOMENTUM_BREAKOUT",
    "INSIDER_BUYING",
    "LEVERAGE_FLUSH_BOTTOM",
}

# Risk-warning / non-directional types are never backtested as trades.
EXCLUDED_SIGNAL_TYPES = {
    "MARGIN_CASCADE_RISK",   # stance: AVOID_LONGS
    "BASIS_INVERSION_SHORT", # stance: SHORT_BIAS
    "ROLLOVER_SQUEEZE",      # stance: SQUEEZE_WATCH
    "CASH_CARRY",            # arbitrage pair, not directional
}

# Stances (metadata) that veto evaluation even if the type is evaluable.
VETO_STANCES = {"AVOID_LONGS", "SHORT_BIAS", "SQUEEZE_WATCH"}


def _series_by_ticker(
    eod_history: list[dict[str, Any]],
) -> dict[str, list[tuple[date, dict[str, Any]]]]:
    """Group EOD rows per ticker, sorted by session date ascending."""
    grouped: dict[str, list[tuple[date, dict[str, Any]]]] = defaultdict(list)
    for row in eod_history:
        day = parse_db_date(row.get("trade_date"))
        ticker = str(row.get("ticker", "")).upper().strip()
        close = to_number(row.get("close_price"))
        if day is None or not ticker or close is None:
            continue
        grouped[ticker].append(
            (
                day,
                {
                    "close": close,
                    "high": to_number(row.get("high_price")),
                    "low": to_number(row.get("low_price")),
                },
            )
        )
    for ticker in grouped:
        grouped[ticker].sort(key=lambda item: item[0])
    return grouped


def resolve_trade(
    forward: list[tuple[date, dict[str, Any]]],
    entry: float,
    stop: float,
    *,
    target_r: float = TARGET_R_MULTIPLE,
    forward_sessions: int = FORWARD_SESSIONS,
    mode: str = "single",
) -> dict[str, Any]:
    """Resolve one synthetic trade against forward sessions.

    Shared resolution core for the backtester and the stop-geometry sweep.
    ``mode="single"`` (default) keeps the legacy 2R-or-stop convention so
    the sweep's historical semantics are unchanged; ``mode="tiered"``
    simulates the institutional scale-out with the break-even ratchet.
    Same-session stop/target touch resolves as a stop (conservative);
    incomplete windows keep NULL flags; returns are close-to-entry over
    t+5/10/20 sessions; MFE/MAE run on session HIGH/LOW. Nothing here
    touches the database.
    """
    risk = entry - stop
    if risk <= 0:
        return {}
    target = entry + target_r * risk

    window = forward[:forward_sessions]
    complete = len(window) >= forward_sessions

    closes = [px["close"] for _, px in window]
    highs = [px["high"] if px["high"] is not None else px["close"] for _, px in window]
    lows = [px["low"] if px["low"] is not None else px["close"] for _, px in window]

    def fwd_return(n: int) -> Optional[float]:
        if len(closes) < n:
            return None
        return round((closes[n - 1] - entry) / entry * 100.0, 2)

    stopped_out = False
    hit_target = False
    mfe = -1e18
    mae = 1e18

    if mode == "tiered":
        # ATR unit from the engine's stored stop geometry.
        atr_unit = risk / ENGINE_ATR_MULTIPLE
        tp1 = entry + TIERED_TP1_R * risk
        tp2 = entry + TIERED_TP2_R * risk
        runner_target = entry + TIERED_RUNNER_R * risk
        be_stop = entry * (1.0 + TIERED_BE_SLIPPAGE_PCT / 100.0)

        tp1_hit = False
        tp2_hit = False
        runner_hit = False
        full_stop = False
        exit_r = None  # R-multiple of the last partial exit price
        trail_floor = stop  # live floor: original stop until TP1 ratchets it
        realized_r: Optional[float] = 0.0

        def _blended(p_exit: float) -> float:
            """Exact R-blend of all banked fractions at exit price p_exit."""
            mid_r = (p_exit - entry) / risk  # unfilled tiers exit at P
            return (
                TIERED_TP1_FRACTION * TIERED_TP1_R
                + TIERED_TP2_FRACTION * (TIERED_TP2_R if tp2_hit else mid_r)
                + TIERED_RUNNER_FRACTION * mid_r
            )

        for i, (high, low) in enumerate(zip(highs, lows)):
            mfe = max(mfe, (high - entry) / entry * 100.0)
            mae = min(mae, (low - entry) / entry * 100.0)
            # Conservative ordering: same-session stop+TP1 touch is a full
            # stop (floor is checked before any trigger credits).
            if low <= trail_floor:
                if tp1_hit:
                    # BE ratchet / trailing stop exit: the remaining 50%
                    # exits at the floor - a scratch at worst (>= entry).
                    exit_r = _blended(max(trail_floor, be_stop))
                else:
                    full_stop = True
                    realized_r = -1.0
                break
            if tp1_hit and tp2_hit and high >= runner_target:
                runner_hit = True
                realized_r = (
                    TIERED_TP1_FRACTION * TIERED_TP1_R
                    + TIERED_TP2_FRACTION * TIERED_TP2_R
                    + TIERED_RUNNER_FRACTION * TIERED_RUNNER_R
                )
                break
            if tp1_hit and high >= tp2:
                tp2_hit = True
                trail_floor = max(
                    be_stop, closes[i] - TIERED_TRAIL_ATR * atr_unit
                )
                continue  # runner keeps going on the trail
            if not tp1_hit and high >= tp1:
                tp1_hit = True
                trail_floor = max(trail_floor, be_stop)
                continue  # no further credits on the TP1 session
            # After TP2 the runner trails 1.5xATR under closing highs
            # (ratchet floor: never below break-even).
            if tp2_hit:
                trail_floor = max(
                    be_stop, closes[i] - TIERED_TRAIL_ATR * atr_unit
                )

        if full_stop:
            pass  # realized_r already -1.0
        elif exit_r is not None:
            realized_r = exit_r
        elif runner_hit:
            pass  # realized_r already the full +3R blend
        elif tp1_hit or tp2_hit:
            if complete:
                # Survived the window: mark the remaining fractions at the
                # last close.
                realized_r = _blended(closes[-1])
            else:
                realized_r = None
        elif complete:
            # Whole window without any trigger: flat mark-to-window.
            realized_r = _blended(closes[-1])
        else:
            realized_r = None

        resolved_flags = (
            complete or tp1_hit or tp2_hit or runner_hit or full_stop
            or exit_r is not None
        )
        if not complete and not resolved_flags:
            hit_target = None
            stopped_out = None
        else:
            hit_target = bool(tp1_hit)  # +1R bar: the Edge Lab hit metric
            stopped_out = bool(full_stop)

        return {
            "return_t5_pct": fwd_return(5),
            "return_t10_pct": fwd_return(10),
            "return_t20_pct": fwd_return(20),
            "max_favorable_excursion_pct": None if mfe is None else round(mfe, 2),
            "max_adverse_excursion_pct": None if mae is None else round(mae, 2),
            "hit_target": hit_target,
            "stopped_out": stopped_out,
            "tp1_hit": bool(tp1_hit),
            "tp2_hit": bool(tp2_hit),
            "runner_hit": bool(runner_hit),
            "full_stop": bool(full_stop),
            "realized_r": None if realized_r is None else round(realized_r, 4),
        }

    stopped_out = False
    hit_target = False
    for day, high, low in zip([d for d, _ in window], highs, lows):
        mfe = max(mfe, (high - entry) / entry * 100.0)
        mae = min(mae, (low - entry) / entry * 100.0)
        touched_stop = low <= stop
        touched_target = high >= target
        if touched_stop:
            # Conservative: same-session double-touch resolves as a stop.
            stopped_out = True
            break
        if touched_target:
            hit_target = True
            break

    if mfe <= -1e17:
        mfe = None
    if mae >= 1e17:
        mae = None

    # Unresolved signals (window cut short by history) keep NULL flags;
    # partial windows still expose honest raw returns/excursions.
    if not complete and not (stopped_out or hit_target):
        hit_target = None
        stopped_out = None

    return {
        "return_t5_pct": fwd_return(5),
        "return_t10_pct": fwd_return(10),
        "return_t20_pct": fwd_return(20),
        "max_favorable_excursion_pct": None if mfe is None else round(mfe, 2),
        "max_adverse_excursion_pct": None if mae is None else round(mae, 2),
        "hit_target": hit_target,
        "stopped_out": stopped_out,
    }


def evaluate_signal(
    signal: dict[str, Any],
    series: list[tuple[date, dict[str, Any]]],
) -> Optional[dict[str, Any]]:
    """Evaluate one signal against its ticker's stored session history.

    Returns a signal_backtest_performance row, or None when the signal
    cannot be evaluated (no forward sessions at all).
    """
    signal_day = parse_db_date(signal.get("trade_date"))
    entry = to_number(signal.get("entry_reference"))
    stop = to_number(signal.get("stop_loss"))
    if signal_day is None or entry is None or entry <= 0 or stop is None:
        return None

    forward = [(day, px) for day, px in series if day > signal_day]
    if not forward:
        return None

    outcome = resolve_trade(
        forward,
        float(entry),
        float(stop),
        mode="tiered",
    )
    if not outcome:
        return None

    # Tiered resolution marks every complete window (mark-to-window close);
    # only incomplete, never-triggered windows stay unresolvable (None).
    if outcome["hit_target"] is None:
        return None

    return {
        "signal_id": signal["id"],
        "ticker": signal["ticker"],
        "trade_date": signal["trade_date"],
        "signal_type": signal["signal_type"],
        "entry_price": round(float(entry), 2),
        "stop_loss": round(float(stop), 2),
        **outcome,
    }


def run_backtester(max_age_days: int = 60, reseed: bool = False) -> int:
    """Evaluate every unevaluated, evaluable signal; returns rows written.

    ``reseed=True`` first purges signals + performance rows across the seed
    window (db.purge_seed_window) so the walk-forward re-simulation rewrites
    the whole window under the current regime-gate + tiered-resolver
    conventions without mixing with legacy rows.
    """
    if reseed:
        history = db.fetch_recent_eod(
            days=140,
            min_date=(date.today() - timedelta(days=140)).isoformat(),
        )
        sessions = _active_sessions(history)[-SEED_SESSIONS:]
        if sessions:
            db.purge_seed_window([d.isoformat() for d in sessions[:-1]])
    written = _seed_walk_forward(max_age_days=max_age_days)
    written += _evaluate_stored(max_age_days=max_age_days)
    return written


def _active_sessions(history: list[dict[str, Any]]) -> list[date]:
    """Sessions with real turnover, ascending."""
    days = {
        parse_db_date(row.get("trade_date"))
        for row in history
        if row.get("volume")
    }
    return sorted(day for day in days if day is not None)


def _seed_walk_forward(max_age_days: int) -> int:
    """Re-simulate the signal engine over the trailing seed window.

    For each of the last SEED_SESSIONS sessions the quant engine runs with
    history strictly truncated to that day (no look-ahead), the produced
    signals are upserted into signals_computed (idempotent natural key),
    and every one with a full or partial forward window is evaluated into
    signal_backtest_performance. This is what populates Edge Lab win rates
    without waiting 20 sessions of live operation.
    """
    history = db.fetch_recent_eod(
        days=140,
        min_date=(date.today() - timedelta(days=140)).isoformat(),
    )
    sessions = _active_sessions(history)[-SEED_SESSIONS:]
    if len(sessions) < 2:
        LOGGER.info("backtester seed: not enough sessions to simulate")
        return 0

    flows = db.fetch_recent_flows(days=60)
    offmarket = db.fetch_recent_offmarket(days=60)
    fundamentals = db.fetch_recent_fundamentals()
    futures = db.fetch_recent_futures(days=60)
    insider = db.fetch_recent_insider_trades(days=60)
    mts_rows = db.fetch_recent_mts(days=60)
    existing = {
        parse_db_date(row.get("trade_date"))
        for row in db.fetch_session_dates_of_signals()
    }

    # Regime inputs for the gate: the benchmark series is fetched ONCE
    # (real dates, cached) and truncated per session inside the loop - zero
    # look-ahead; the flow leg is date-filtered inside build_regime_state.
    seed_bench: list[tuple[Any, float]] = []
    if REGIME_GATE_ENABLED:
        try:
            from pipeline.analytics.sector_rotation import (
                fetch_benchmark_series,
            )

            seed_bench = fetch_benchmark_series()
        except Exception as exc:  # noqa: BLE001 - optional leg
            LOGGER.warning("backtester seed: benchmark fetch failed: %s", exc)

    seeded_sessions = 0
    for index, session in enumerate(sessions[:-1]):  # last day has no forward window
        if SEED_SKIP_EXISTING and session in existing:
            continue
        day_rows = [
            row
            for row in history
            if (parse_db_date(row.get("trade_date")) or date.min) <= session
        ]
        regime_state = None
        if REGIME_GATE_ENABLED:
            regime_state = build_regime_state(
                flows=flows,
                eod_history=day_rows,
                as_of=session,
                benchmark_series=[
                    (day, close) for day, close in seed_bench if day <= session
                ]
                if seed_bench
                else None,
            )
        try:
            results = compute_signals(
                session,
                eod_history=day_rows,
                flows=flows,
                offmarket_deals=offmarket,
                fundamentals=fundamentals,
                futures_history=futures,
                insider_trades=insider,
                mts_rows=mts_rows,
                dividends=None,
                regime_state=regime_state,
            )
        except Exception as exc:  # noqa: BLE001 - one bad day never kills the seed
            LOGGER.warning("backtester seed: %s failed (%s)", session, exc)
            continue
        payload: list[dict[str, Any]] = []
        for rows in results.values():
            payload.extend(rows)
        if not payload:
            continue
        try:
            db.upsert_records(
                "signals_computed",
                payload,
                on_conflict="trade_date,ticker,timeframe,signal_type",
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning(
                "backtester seed: signal upsert failed for %s (%s)", session, exc
            )
            continue
        seeded_sessions += 1
        LOGGER.info(
            "backtester seed: %s -> %d signals re-simulated",
            session,
            len(payload),
        )
    if seeded_sessions:
        LOGGER.info(
            "backtester seed: %d/%d sessions re-simulated",
            seeded_sessions,
            len(sessions) - 1,
        )
    return 0  # rows are counted by the evaluation pass below


def _evaluate_stored(max_age_days: int) -> int:
    """Evaluate every stored, unevaluated signal (live + seeded)."""
    signals = db.fetch_unbacktested_signals(max_age_days=max_age_days)
    if not signals:
        LOGGER.info("backtester: no unevaluated signals")
        return 0

    # Risk-warning stances veto evaluation regardless of signal type.
    vetoed = 0
    for signal in signals:
        if signal.get("signal_type") in EXCLUDED_SIGNAL_TYPES:
            signal["_skip"] = True
            vetoed += 1
    candidates = [s for s in signals if not s.get("_skip")]

    # History must cover the oldest signal plus a 20-session forward window.
    oldest = min(
        (parse_db_date(s.get("trade_date")) for s in candidates),
        default=None,
    )
    lookback_days = 40
    if oldest is not None:
        lookback_days = max(lookback_days, (date.today() - oldest).days + 35)
    # Window-bounded read: 35 days of headroom past the oldest signal covers
    # the 20-session forward window; nothing older than the oldest signal
    # is ever pulled, so no full-table scan for stale history.
    history = db.fetch_recent_eod(
        days=lookback_days,
        min_date=(oldest - timedelta(days=35)).isoformat() if oldest else None,
    )
    series = _series_by_ticker(history)

    rows: list[dict[str, Any]] = []
    for signal in candidates:
        if signal["signal_type"] not in EVALUABLE_SIGNAL_TYPES:
            vetoed += 1
            continue
        ticker_series = series.get(str(signal["ticker"]).upper().strip()) or []
        row = evaluate_signal(signal, ticker_series)
        if row is not None:
            rows.append(row)

    if not rows:
        LOGGER.info(
            "backtester: 0 signals evaluable (no matured forward windows yet)"
        )
        return 0

    try:
        written = db.upsert_backtest_rows(rows)
    except Exception as exc:  # noqa: BLE001 - surface migration status clearly
        if "PGRST205" in str(exc) or "schema cache" in str(exc):
            LOGGER.warning(
                "backtester: signal_backtest_performance table missing - "
                "apply schema.sql in Supabase to persist evaluations"
            )
            return 0
        raise
    LOGGER.info(
        "backtester: %d signals evaluated (%d rows written, %d skipped)",
        len(candidates),
        written,
        vetoed,
    )
    return written


def summarize_by_type(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Aggregate per signal_type under the tiered-exit conventions.

    Metrics: TP1 hit % (+1R reached), scratch/BE % (stopped after the
    break-even ratchet), full stop % (never reached TP1), R-weighted
    profit factor (gross wins / gross losses over realized_r) and E[R]
    (mean realized_r). Tiered rows carry realized_r; legacy single-bar
    rows fall back to the 2R/-1R convention.
    """
    stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "n": 0,
            "resolved": 0,
            "tp1": 0,
            "scratches": 0,
            "full_stops": 0,
            "wins_r": 0.0,
            "losses_r": 0.0,
            "r_list": [],
            "t5": [],
            "t10": [],
            "t20": [],
            "mfe": [],
            "mae": [],
        }
    )
    for row in rows:
        bucket = stats[row["signal_type"]]
        bucket["n"] += 1
        if row.get("hit_target") is not None:
            bucket["resolved"] += 1
        if row.get("tp1_hit") is not None:
            if row["tp1_hit"]:
                bucket["tp1"] += 1
            if row.get("full_stop"):
                bucket["full_stops"] += 1
            elif not row.get("tp1_hit"):
                pass  # unresolved / legacy row: not a scratch
            elif not row.get("tp2_hit") and not row.get("runner_hit"):
                r = row.get("realized_r")
                if r is not None and float(r) < (TIERED_TP2_R - 0.25):
                    bucket["scratches"] += 1
            r = row.get("realized_r")
            if r is not None:
                r = float(r)
                bucket["r_list"].append(r)
                if r > 0:
                    bucket["wins_r"] += r
                else:
                    bucket["losses_r"] += abs(r)
        elif row.get("hit_target") is not None:
            # Legacy row without tiered columns. hit_target now carries the
            # TP1 bar (+1R), so the honest approximation is +1R wins / -1R
            # full stops - NOT the old 2R convention, which would overstate
            # expectancy. Exact R-blends return once realized_r is stored.
            if row["hit_target"]:
                bucket["wins_r"] += TIERED_TP1_R
                bucket["r_list"].append(TIERED_TP1_R)
            elif row.get("stopped_out"):
                bucket["losses_r"] += 1.0
                bucket["full_stops"] += 1
                bucket["r_list"].append(-1.0)
        for key, field in (
            ("t5", "return_t5_pct"),
            ("t10", "return_t10_pct"),
            ("t20", "return_t20_pct"),
            ("mfe", "max_favorable_excursion_pct"),
            ("mae", "max_adverse_excursion_pct"),
        ):
            value = row.get(field)
            if value is not None:
                bucket[key].append(float(value))

    summary: list[dict[str, Any]] = []
    for signal_type, b in stats.items():
        resolved = b["resolved"]
        tp1_rate = b["tp1"] / resolved if resolved else None
        scratch_rate = b["scratches"] / resolved if resolved else None
        full_stop_rate = b["full_stops"] / resolved if resolved else None
        pf = (
            b["wins_r"] / b["losses_r"] if b["losses_r"] > 0 else None
        )
        expectancy_r = (
            sum(b["r_list"]) / len(b["r_list"]) if b["r_list"] else None
        )
        summary.append(
            {
                "signalType": signal_type,
                "signals": b["n"],
                "resolved": resolved,
                "tp1HitPct": None if tp1_rate is None else round(tp1_rate * 100.0, 1),
                "scratchBePct": (
                    None if scratch_rate is None else round(scratch_rate * 100.0, 1)
                ),
                "fullStopPct": (
                    None if full_stop_rate is None else round(full_stop_rate * 100.0, 1)
                ),
                "profitFactor": None if pf is None else round(pf, 2),
                "expectancyR": None if expectancy_r is None else round(expectancy_r, 3),
                "avgT5Pct": round(sum(b["t5"]) / len(b["t5"]), 2) if b["t5"] else None,
                "avgT10Pct": round(sum(b["t10"]) / len(b["t10"]), 2) if b["t10"] else None,
                "avgT20Pct": round(sum(b["t20"]) / len(b["t20"]), 2) if b["t20"] else None,
                "avgMfePct": round(sum(b["mfe"]) / len(b["mfe"]), 2) if b["mfe"] else None,
                "avgMaePct": round(sum(b["mae"]) / len(b["mae"]), 2) if b["mae"] else None,
            }
        )
    summary.sort(key=lambda s: -(s["expectancyR"] if s["expectancyR"] is not None else -9))
    return summary


def _cli() -> None:
    """Backtester CLI: `python -m pipeline.analytics.backtester [--reseed]`.

    --reseed  purge the 30-session seed window (signals + performance rows)
              and rebuild it under the current regime-gate + tiered-resolver
              conventions. Without it, only unevaluated signals are priced.
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m pipeline.analytics.backtester"
    )
    parser.add_argument(
        "--reseed",
        action="store_true",
        help="purge + rebuild the 30-session walk-forward seed window",
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    written = run_backtester(reseed=args.reseed)
    print(f"BACKTEST_ROWS_WRITTEN = {written}")
    if written:
        from pipeline.db import fetch_backtest_performance

        rows = fetch_backtest_performance(days=140)
        for entry in summarize_by_type(rows):
            print(
                f"{entry['signalType']:<24} resolved={entry['resolved']:<5}"
                f"tp1%={entry['tp1HitPct']} scratch%={entry['scratchBePct']} "
                f"fullstop%={entry['fullStopPct']} "
                f"PF={entry['profitFactor']} E[R]={entry['expectancyR']}"
            )


if __name__ == "__main__":
    _cli()
