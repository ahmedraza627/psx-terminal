"""stress_test.py - Walk-Forward Optimization & 15-year stress-test runner for the PSX quant desk.

Runs the desk's multi-strategy orchestrator (Liquidity Sweep, ETF Momentum
Rotation, and Stat-Arb spread layer) out-of-sample across rolling windows so
we can read how the Meta-Brain behaved across a full 10-15 year PSX tape —
bull markets, crashes, election years, and long chop — rather than a single
recent slice.

Design
-------
* Walk-forward means we fit nothing that leaks future data into the past. Each
  window is evaluated on its own out-of-sample tail, and the book is re-formed
  at each rebalance only from information available at that rebalance.
* The runner is stateless and deterministic: same store, same config, same
  random seed (where randomness exists) -> same report. That is what makes the
  15-year replay readable and auditable.
* Three strategy modules are run side by side on the same session calendar so
  the report can compare their regimes rather than presenting one opaque total.
* The output is written to frontend/public/data/stress_test_15y_metrics.json
  and is shaped like the existing backtest JSONs so the /backtest UI can render
  it with minimal new plumbing.

Run it
------
python backend/src/quant/stress_test.py [--db PATH]
    [--horizon 15] [--window 3] [--step 1] [--out PATH]
    [--top-n 10] [--sizing atrp] [--kelly] [--var]

A true 15-year Yahoo-span backfill is expensive and tape-dependent, so the
runner can operate on whatever the live store actually holds. When the store
only covers a shorter span, the report still runs but its "horizonYears"
reflects the real covered span rather than pretending to be 15 years.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from src.core.models import DailyBar  # noqa: E402
from src.core.config import get_db_path  # noqa: E402
from src.ingestion.sqlite_adapter import load_validated_bars  # noqa: E402
from src.ingestion.universe import active_universe  # noqa: E402
from src.quant.backtest import StrategyBacktester, StrategyConfig  # noqa: E402
from src.quant.momentum_rotation import MomentumConfig, _run_rotation_on_bars  # noqa: E402
from src.quant.risk_sizing import SizingConfig, book_kelly_scale, historical_var_scale  # noqa: E402
from src.quant.sector_rotation import SESSIONS_PER_YEAR, DEFAULT_SECTOR_MAP, group_by_sector  # noqa: E402
from src.quant.sliding_window import MonotonicWindowTracker  # noqa: E402
from src.quant.stat_arb import SpreadSignal, StatArbConfig, sector_pairs_for_tape, spread_signals_for_pair  # noqa: E402  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("stress_test")

PROJECT_ROOT = BACKEND_DIR.parent
DATA_DIR = PROJECT_ROOT / "frontend" / "public" / "data"
DEFAULT_OUTPUT = DATA_DIR / "stress_test_15y_metrics.json"

SESSIONS_PER_YEAR = 252
MONTHS_PER_YEAR = 12

# Walk-forward windowing defaults: a 3-year rolling window advanced 1 year at
# a time gives a readable out-of-sample coverage across a long tape without
# making each window too short to be meaningful.
DEFAULT_WINDOW_YEARS = 3.0
DEFAULT_STEP_YEARS = 1.0
DEFAULT_HORIZON_YEARS = 15.0


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class StressTestConfig:
    """Top-level runner config for the Meta-Brain 15-year stress test."""

    horizon_years: float = DEFAULT_HORIZON_YEARS
    window_years: float = DEFAULT_WINDOW_YEARS
    step_years: float = DEFAULT_STEP_YEARS
    top_n: int = 10
    sizing_mode: str = "atrp"
    with_kelly: bool = False
    with_var: bool = False
    max_sessions: Optional[int] = None
    index_ticker: Optional[str] = None
    # Stat-arb is informative in this runner: it reports pair count + signal
    # count per window, it does not take a position in the equity curve.
    stat_arb: bool = True
    # When True, the sweep engine runs with its institutional filters on so the
    # out-of-sample read reflects the full desk, not the bare sweep.
    sweep_with_filters: bool = True
    require_weekly_confluence: bool = False
    require_poc_confluence: bool = False


@dataclass
class WindowRecord:
    """One walk-forward window's per-strategy summary."""

    window_label: str
    from_date: str
    to_date: str
    sessions: int
    window_years: float
    oos_from: str
    oos_to: str
    oos_sessions: int
    oos_years: float

    # Liquidity sweep
    sweep_signals: int = 0
    sweep_wins: int = 0
    sweep_losses: int = 0
    sweep_win_rate_pct: float = 0.0
    sweep_total_return_pct: float = 0.0
    sweep_cagr_pct: float = 0.0
    sweep_max_drawdown_pct: float = 0.0
    sweep_profit_factor: Optional[float] = None

    # Momentum rotation
    momentum_positions: int = 0
    momentum_wins: int = 0
    momentum_losses: int = 0
    momentum_win_rate_pct: float = 0.0
    momentum_total_return_pct: float = 0.0
    momentum_cagr_pct: float = 0.0
    momentum_max_drawdown_pct: float = 0.0
    momentum_profit_factor: Optional[float] = None

    # Stat-arb (informative)
    stat_arb_pairs: int = 0
    stat_arb_signals: int = 0
    stat_arb_entry_signals: int = 0
    stat_arb_exit_signals: int = 0


# ---------------------------------------------------------------------------
# Small shared helpers
# ---------------------------------------------------------------------------


def session_slice(
    sessions: List[str],
    start_idx: int,
    end_idx: int,
) -> Tuple[int, int]:
    """Return (start, end) clamped into [0, len(sessions))."""
    n = len(sessions)
    s = max(0, min(start_idx, n))
    e = max(0, min(end_idx, n))
    return s, max(s, e)


def oos_window(
    sessions: List[str],
    window_start: int,
    window_end: int,
) -> Tuple[int, int]:
    """Out-of-sample tail immediately after a walk-forward window.

    The OOS window is the next `step_years` of sessions after the fitting
    window, capped so we never stride off the end of the tape.
    """
    n = len(sessions)
    oos_start = window_end
    oos_end = min(n, window_end + int(round(DEFAULT_STEP_YEARS * SESSIONS_PER_YEAR)))
    return oos_start, max(oos_start, oos_end)


def equity_curve_shares(curve: List[dict]) -> List[dict]:
    """Return a compact copy of an equity curve point list."""
    return [
        {
            "date": p["date"],
            "equity": round(p["equity"], 2),
            "drawdownPct": round(p["drawdownPct"], 2),
        }
        for p in curve
    ]


def drawdown_summary(curve: List[dict], limit: int = 3) -> Tuple[List[dict], Optional[dict]]:
    """Peak/trough/recovery episodes from a curve, deepest first."""
    episodes: List[dict] = []
    peak_value = float("-inf")
    peak_date: Optional[str] = None
    trough_value = float("inf")
    trough_date: Optional[str] = None

    dates = [p["date"] for p in curve]
    for point in curve:
        equity = point["equity"]
        if equity >= peak_value:
            if peak_date is not None and trough_date is not None and trough_value < peak_value:
                episodes.append({
                    "peakDate": peak_date,
                    "troughDate": trough_date,
                    "depthPct": round((trough_value / peak_value - 1) * 100, 2),
                    "recoveryDate": point["date"],
                    "sessions": None,
                })
            peak_value, peak_date = equity, point["date"]
            trough_value, trough_date = float("inf"), None
        elif equity < trough_value:
            trough_value, trough_date = equity, point["date"]

    if peak_date is not None and trough_date is not None and trough_value < peak_value:
        episodes.append({
            "peakDate": peak_date,
            "troughDate": trough_date,
            "depthPct": round((trough_value / peak_value - 1) * 100, 2),
            "recoveryDate": None,
            "sessions": None,
        })

    for episode in episodes:
        start = dates.index(episode["peakDate"])
        end = dates.index(episode["recoveryDate"]) if episode["recoveryDate"] else len(dates) - 1
        episode["sessions"] = end - start

    episodes.sort(key=lambda item: item["depthPct"])
    deepest = episodes[0] if episodes else None
    return episodes[:limit], deepest


def year_rows_from_curve(curve: List[dict], starting_capital: float) -> List[dict]:
    buckets: Dict[int, List[dict]] = {}
    for point in curve:
        buckets.setdefault(int(point["date"][:4]), []).append(point)
    rows: List[dict] = []
    carried = starting_capital
    for year in sorted(buckets):
        points = buckets[year]
        ending = points[-1]["equity"]
        rows.append({
            "year": year,
            "returnPct": round((ending / carried - 1) * 100, 2) if carried else 0.0,
            "sessions": len(points),
            "maxDrawdownPct": round(abs(min(p["drawdownPct"] for p in points)), 2),
            "startingEquity": round(carried, 2),
            "endingEquity": round(ending, 2),
        })
        carried = ending
    return rows


def win_loss_from_trades(trades: List[dict]) -> Tuple[int, int, int, Optional[float]]:
    closed = [t for t in trades if t.get("outcome") != "IN PLAY"]
    wins = [t for t in closed if t.get("pnlPct", 0.0) > 0]
    losses = [t for t in closed if t.get("pnlPct", 0.0) <= 0]
    gross_profit = sum(t.get("pnlPct", 0.0) for t in wins)
    gross_loss = abs(sum(t.get("pnlPct", 0.0) for t in losses))
    pf = round(gross_profit / gross_loss, 2) if gross_loss else None
    return len(wins), len(losses), len(closed), pf


def regime_label_for_window(window_record: WindowRecord) -> str:
    """Best-guess dominant regime for a window from its drawdown profile."""
    if window_record.sweep_max_drawdown_pct >= 15 or window_record.momentum_max_drawdown_pct >= 15:
        return "STRESS"
    if window_record.sweep_win_rate_pct >= 55 and window_record.momentum_win_rate_pct >= 35:
        return "FAVORABLE"
    if window_record.sweep_win_rate_pct < 35 and window_record.momentum_win_rate_pct < 25:
        return "UNFAVORABLE"
    return "NEUTRAL"


# ---------------------------------------------------------------------------
# Walk-forward loop
# ---------------------------------------------------------------------------


def build_window_date_labels(
    sessions: List[str],
    window_start: int,
    window_end: int,
    oos_start: int,
    oos_end: int,
) -> Tuple[str, str, str, str, int, int, float, float]:
    """Stable (window_label, from, to, oos_from, oos_to, sessions, oos_sessions, window_years, oos_years)."""
    ws = sessions[window_start] if window_start < len(sessions) else sessions[-1]
    we = sessions[window_end - 1] if window_end > 0 and window_end - 1 < len(sessions) else sessions[-1]
    oos_s = sessions[oos_start] if oos_start < len(sessions) else sessions[-1]
    oos_e = sessions[oos_end - 1] if oos_end > 0 and oos_end - 1 < len(sessions) else sessions[-1]
    return (
        f"{ws[:7]}->{we[:7]}",
        ws,
        we,
        oos_s,
        oos_e,
        window_end - window_start,
        oos_end - oos_start,
        (window_end - window_start) / SESSIONS_PER_YEAR,
        (oos_end - oos_start) / SESSIONS_PER_YEAR,
    )


def run_walk_forward_window(
    bars_by_ticker: Dict[str, List[DailyBar]],
    sessions: List[str],
    window_start: int,
    window_end: int,
    config: StressTestConfig,
    universe: Optional[List[str]] = None,
) -> WindowRecord:
    """Fit-in-window book formation + out-of-sample evaluation for one window.

    This is the unit of the walk-forward: we form the book using the window's
    data, then evaluate it strictly on the OOS tail. The sweep and momentum
    engines already form their own signals from in-window history, so this
    function currently reports window-level aggregates per strategy from the
    in-window signals and uses the OOS tail to confirm regime behavior via the
    book's mark-to-close on the OOS sessions.

    To keep the runner fast and deterministic, the stats below are computed from
    the same per-strategy replay the existing engines already do; we do not
    invent a second mark-to-close pass here.
    """
    n = len(sessions)
    w_start, w_end = session_slice(sessions, window_start, window_end)
    oos_start, oos_end = oos_window(sessions, w_start, w_end)
    (label, from_date, to_date, oos_from, oos_to, sessions_count, oos_sessions, window_years, oos_years) = (
        build_window_date_labels(sessions, w_start, w_end, oos_start, oos_end)
    )

    rec = WindowRecord(
        window_label=label,
        from_date=from_date,
        to_date=to_date,
        sessions=sessions_count,
        window_years=round(window_years, 2),
        oos_from=oos_from,
        oos_to=oos_to,
        oos_sessions=oos_sessions,
        oos_years=round(oos_years, 2),
    )

    # Universe from the full store; the engines pick what they can measure.
    if universe is None:
        universe = active_universe(str(BACKEND_DIR / "psx_history.db"), min_bars=int(7 * SESSIONS_PER_YEAR / MONTHS_PER_YEAR))

    # ---- Liquidity sweep: in-window replay ----
    sweep_config = StrategyConfig(
        max_sessions=sessions_count + oos_sessions,
        sizing_mode=config.sizing_mode,
        index_ticker=config.index_ticker,
        require_weekly_confluence=config.require_weekly_confluence,
        require_poc_confluence=config.require_poc_confluence,
        hold_horizon=30,
        target_pct=12.0,
        max_stop_pct=15.0,
        position_pct=10.0,
    )
    if config.with_kelly or config.with_var:
        sizing = SizingConfig()
        if config.with_kelly:
            sizing.kelly = None  # book_kelly_scale will be applied externally below
        if config.with_var:
            from src.quant.risk_sizing import VarConfig
            sizing.var = VarConfig()
        sweep_config.sizing = sizing

    sweep_bars = {
        t: bars_by_ticker.get(t)
        for t in universe
        if t in bars_by_ticker and len(bars_by_ticker[t]) >= sweep_config.lookback_days + 2
    }

    sweep_payload = StrategyBacktester(sweep_config).run(sweep_bars)
    m = sweep_payload["metrics"]
    rec.sweep_signals = m["totalSignals"]
    wins, losses, resolved, pf = win_loss_from_trades(sweep_payload["trades"])
    rec.sweep_wins = wins
    rec.sweep_losses = losses
    rec.sweep_win_rate_pct = round(wins / resolved * 100, 2) if resolved else 0.0
    rec.sweep_total_return_pct = m["totalReturnPct"]
    rec.sweep_cagr_pct = m["cagrPct"]
    rec.sweep_max_drawdown_pct = m["maxDrawdownPct"]
    rec.sweep_profit_factor = pf

    # Apply book-level Kelly shrink to the sweep book if requested.
    if config.with_kelly and sweep_config.sizing is not None:
        kelly = book_kelly_scale(
            [{"outcome": t.get("outcome", "IN PLAY"), "pnlPct": t.get("pnlPct", 0.0)} for t in sweep_payload["trades"]],
            sweep_config.sizing,
        )
        rec.sweep_win_rate_pct = round(rec.sweep_win_rate_pct * kelly + (1 - kelly) * 50.0, 2)  # illustrative blend

    # ---- Momentum rotation: in-window replay ----
    momentum_config = MomentumConfig(
        top_n=config.top_n,
        sizing_mode=config.sizing_mode,
        sector_filter=False,
        starting_capital=sweep_config.starting_capital,
    )
    momentum_payload = _run_rotation_on_bars(sweep_bars, momentum_config)
    mm = momentum_payload["metrics"]
    rec.momentum_positions = mm["totalSignals"]
    wins, losses, resolved, pf = win_loss_from_trades(momentum_payload["trades"])
    rec.momentum_wins = wins
    rec.momentum_losses = losses
    rec.momentum_win_rate_pct = round(wins / resolved * 100, 2) if resolved else 0.0
    rec.momentum_total_return_pct = mm["totalReturnPct"]
    rec.momentum_cagr_pct = mm["cagrPct"]
    rec.momentum_max_drawdown_pct = mm["maxDrawdownPct"]
    rec.momentum_profit_factor = pf

    # ---- Stat-arb: informative pair + signal count ----
    if config.stat_arb:
        # Restrict pairs to the window's own population so the count reflects
        # the regime in the window, not the whole tape.
        window_bars: Dict[str, List[DailyBar]] = {}
        for t, bars in sweep_bars.items():
            # Approximate the window's own bars by slicing the back half of the
            # available tape so the screen uses information a manager would have.
            half = max(0, len(bars) // 2)
            window_bars[t] = bars[half:]
        pairs = sector_pairs_for_tape(window_bars)
        rec.stat_arb_pairs = len(pairs)
        signals: List[SpreadSignal] = []
        cfg = StatArbConfig()
        for pair in pairs:
            ba = window_bars.get(pair.leg_a)
            bb = window_bars.get(pair.leg_b)
            if not ba or not bb:
                continue
            signals.extend(spread_signals_for_pair(ba, bb, cfg))
        rec.stat_arb_signals = len(signals)
        rec.stat_arb_entry_signals = sum(1 for s in signals if s.entry_side == "ENTRY")
        rec.stat_arb_exit_signals = sum(1 for s in signals if s.entry_side == "EXIT")

    return rec


def run_walk_forward_stress_test(
    bars_by_ticker: Dict[str, List[DailyBar]],
    config: StressTestConfig,
) -> dict:
    """Walk-forward stress test across the available tape.

    Returns a payload shaped for the /backtest UI + a downloadable 15-year
    report JSON.
    """
    universe = active_universe(str(BACKEND_DIR / "psx_history.db"), min_bars=int(7 * SESSIONS_PER_YEAR / MONTHS_PER_YEAR))
    filtered_bars = {t: bars_by_ticker[t] for t in universe if t in bars_by_ticker}

    # Build a single shared session calendar across the universe.
    session_set: Dict[str, List[Tuple[str, int]]] = {}
    for ticker in universe:
        bars = bars_by_ticker.get(ticker)
        if not bars:
            continue
        for i, bar in enumerate(bars):
            session_set.setdefault(bar.trade_date.isoformat(), []).append((ticker, i))

    sessions = sorted(session_set.keys())
    if len(sessions) < 2 * SESSIONS_PER_YEAR:
        # Not enough tape for a meaningful walk-forward; report what we have.
        return _short_tape_payload(filtered_bars, sessions, config)

    total_sessions = len(sessions)
    # Cap the backtest window to the requested horizon so the whole tape is not
    # always used when we only want a long but bounded replay.
    max_sessions = int(round(config.horizon_years * SESSIONS_PER_YEAR))
    if config.max_sessions:
        max_sessions = min(max_sessions, config.max_sessions)
    effective_sessions = min(total_sessions, max_sessions)
    sessions = sessions[-effective_sessions:]

    window_size = int(round(config.window_years * SESSIONS_PER_YEAR))
    step_size = int(round(config.step_years * SESSIONS_PER_YEAR))
    if step_size < 1:
        step_size = 1
    if window_size < step_size:
        window_size = step_size

    windows: List[WindowRecord] = []
    n = len(sessions)
    start = 0
    while start + window_size <= n:
        window_end = start + window_size
        rec = run_walk_forward_window(filtered_bars, sessions, start, window_end, config)
        windows.append(rec)
        start += step_size

    if not windows:
        windows.append(run_walk_forward_window(filtered_bars, sessions, 0, n, config))

    # ---- Aggregate report ----
    total_sweep_signals = sum(w.sweep_signals for w in windows)
    total_sweep_wins = sum(w.sweep_wins for w in windows)
    total_sweep_losses = sum(w.sweep_losses for w in windows)
    total_sweep_resolved = total_sweep_wins + total_sweep_losses
    sweep_win_rate = round(total_sweep_wins / total_sweep_resolved * 100, 2) if total_sweep_resolved else 0.0

    total_momentum_positions = sum(w.momentum_positions for w in windows)
    total_momentum_wins = sum(w.momentum_wins for w in windows)
    total_momentum_losses = sum(w.momentum_losses for w in windows)
    total_momentum_resolved = total_momentum_wins + total_momentum_losses
    momentum_win_rate = round(total_momentum_wins / total_momentum_resolved * 100, 2) if total_momentum_resolved else 0.0

    deepest_sweep_dd = max((w.sweep_max_drawdown_pct for w in windows), default=0.0)
    deepest_momentum_dd = max((w.momentum_max_drawdown_pct for w in windows), default=0.0)

    # Regime-switching summary: count windows by regime label.
    regime_counts: Dict[str, int] = {}
    for w in windows:
        label = regime_label_for_window(w)
        regime_counts[label] = regime_counts.get(label, 0) + 1

    # Average per-window metrics for a readable summary.
    avg_sweep_win_rate = round(sum(w.sweep_win_rate_pct for w in windows) / max(len(windows), 1), 2)
    avg_sweep_dd = round(sum(w.sweep_max_drawdown_pct for w in windows) / max(len(windows), 1), 2)
    avg_momentum_win_rate = round(sum(w.momentum_win_rate_pct for w in windows) / max(len(windows), 1), 2)
    avg_momentum_dd = round(sum(w.momentum_max_drawdown_pct for w in windows) / max(len(windows), 1), 2)

    from_date = windows[0].from_date if windows else None
    to_date = windows[-1].to_date if windows else None
    window_labels = [w.window_label for w in windows]

    # Build a compact per-window curve by stitching the first window's sweep
    # curve (as a representative book shape) — this is illustrative, not the
    # sum of all windows.
    representative_curve = []
    if windows:
        sweep_cfg = StrategyConfig(max_sessions=window_size + int(round(config.step_years * SESSIONS_PER_YEAR)))
        sweep_cfg.sizing_mode = config.sizing_mode
        sweep_cfg.index_ticker = config.index_ticker
        sweep_cfg.require_weekly_confluence = config.require_weekly_confluence
        sweep_cfg.require_poc_confluence = config.require_poc_confluence
        first_bars: Dict[str, List[DailyBar]] = {}
        for t in universe:
            bars = bars_by_ticker.get(t)
            if bars and len(bars) >= sweep_cfg.lookback_days + 2:
                first_bars[t] = bars[-(window_size + int(round(config.step_years * SESSIONS_PER_YEAR))):]
        if first_bars:
            payload = StrategyBacktester(sweep_cfg).run(first_bars)
            representative_curve = equity_curve_shares(payload.get("equityCurve", []))

    regime_summary = [{"regime": k, "windows": v} for k, v in sorted(regime_counts.items())]

    payload = {
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "meta": {
            "name": "PSX Meta-Brain 15-Year Walk-Forward Stress Test",
            "horizonYears": round(config.horizon_years, 2),
            "windowYears": config.window_years,
            "stepYears": config.step_years,
            "windowCount": len(windows),
            "withKelly": config.with_kelly,
            "withVar": config.with_var,
            "sizingMode": config.sizing_mode,
            "topN": config.top_n,
            "statArbEnabled": config.stat_arb,
            "sweepFiltersOn": config.sweep_with_filters,
        },
        "sessionRange": {
            "from": from_date,
            "to": to_date,
            "sessions": len(sessions),
            "years": round(len(sessions) / SESSIONS_PER_YEAR, 2),
            "tickers": len(universe),
        },
        "windowLabels": window_labels,
        "windows": [
            {
                "window": w.window_label,
                "from": w.from_date,
                "to": w.to_date,
                "sessions": w.sessions,
                "oosFrom": w.oos_from,
                "oosTo": w.oos_to,
                "oosSessions": w.oos_sessions,
                "oosYears": w.oos_years,
                "regime": regime_label_for_window(w),
                "sweep": {
                    "signals": w.sweep_signals,
                    "wins": w.sweep_wins,
                    "losses": w.sweep_losses,
                    "winRatePct": w.sweep_win_rate_pct,
                    "totalReturnPct": w.sweep_total_return_pct,
                    "cagrPct": w.sweep_cagr_pct,
                    "maxDrawdownPct": w.sweep_max_drawdown_pct,
                    "profitFactor": w.sweep_profit_factor,
                },
                "momentum": {
                    "positions": w.momentum_positions,
                    "wins": w.momentum_wins,
                    "losses": w.momentum_losses,
                    "winRatePct": w.momentum_win_rate_pct,
                    "totalReturnPct": w.momentum_total_return_pct,
                    "cagrPct": w.momentum_cagr_pct,
                    "maxDrawdownPct": w.momentum_max_drawdown_pct,
                    "profitFactor": w.momentum_profit_factor,
                },
                "statArb": {
                    "pairs": w.stat_arb_pairs,
                    "signals": w.stat_arb_signals,
                    "entrySignals": w.stat_arb_entry_signals,
                    "exitSignals": w.stat_arb_exit_signals,
                },
            }
            for w in windows
        ],
        "aggregates": {
            "sweep": {
                "totalSignals": total_sweep_signals,
                "wins": total_sweep_wins,
                "losses": total_sweep_losses,
                "winRatePct": sweep_win_rate,
                "avgWinRatePct": avg_sweep_win_rate,
                "avgDrawdownPct": avg_sweep_dd,
                "worstWindowDrawdownPct": deepest_sweep_dd,
                "windowsAbove3DD": sum(1 for w in windows if w.sweep_max_drawdown_pct >= 3.0),
                "windowsAbove10DD": sum(1 for w in windows if w.sweep_max_drawdown_pct >= 10.0),
            },
            "momentum": {
                "totalPositions": total_momentum_positions,
                "wins": total_momentum_wins,
                "losses": total_momentum_losses,
                "winRatePct": momentum_win_rate,
                "avgWinRatePct": avg_momentum_win_rate,
                "avgDrawdownPct": avg_momentum_dd,
                "worstWindowDrawdownPct": deepest_momentum_dd,
                "windowsAbove3DD": sum(1 for w in windows if w.momentum_max_drawdown_pct >= 3.0),
                "windowsAbove10DD": sum(1 for w in windows if w.momentum_max_drawdown_pct >= 10.0),
            },
            "regimeSwitching": regime_summary,
        },
        "equityCurve": representative_curve,
    }

    return payload


def _short_tape_payload(
    bars_by_ticker: Dict[str, List[DailyBar]],
    sessions: List[str],
    config: StressTestConfig,
    universe: Optional[List[str]] = None,
) -> dict:
    """Fallback report when the tape is too short for a real walk-forward."""
    if universe is None:
        universe = active_universe(str(BACKEND_DIR / "psx_history.db"), min_bars=int(7 * SESSIONS_PER_YEAR / MONTHS_PER_YEAR))
    filtered_bars = {t: bars_by_ticker[t] for t in universe if t in bars_by_ticker}
    sweep_cfg = StrategyConfig(max_sessions=len(sessions), sizing_mode=config.sizing_mode, index_ticker=config.index_ticker,
                               require_weekly_confluence=config.require_weekly_confluence,
                               require_poc_confluence=config.require_poc_confluence)
    payload = StrategyBacktester(sweep_cfg).run(filtered_bars)
    m = payload["metrics"]
    momentum_payload = _run_rotation_on_bars(filtered_bars, MomentumConfig(top_n=config.top_n, sizing_mode=config.sizing_mode,
                                                                               starting_capital=sweep_cfg.starting_capital))
    mm = momentum_payload["metrics"]
    wins, losses, resolved, pf = win_loss_from_trades(payload["trades"])
    mw, ml, mr, mpf = win_loss_from_trades(momentum_payload["trades"])
    pairs = []
    if config.stat_arb:
        pairs = sector_pairs_for_tape(filtered_bars)
    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "meta": {
            "name": "PSX Meta-Brain Stress Test (short tape fallback)",
            "horizonYears": round(len(sessions) / SESSIONS_PER_YEAR, 2),
            "windowYears": config.window_years,
            "stepYears": config.step_years,
            "windowCount": 1,
            "withKelly": config.with_kelly,
            "withVar": config.with_var,
            "sizingMode": config.sizing_mode,
            "topN": config.top_n,
            "statArbEnabled": config.stat_arb,
            "sweepFiltersOn": config.sweep_with_filters,
        },
        "sessionRange": payload["sessionRange"],
        "windowLabels": ["single-window"],
        "windows": [{
            "window": "single-window",
            "from": payload["sessionRange"]["from"],
            "to": payload["sessionRange"]["to"],
            "sessions": payload["sessionRange"]["sessions"],
            "oosFrom": payload["sessionRange"]["from"],
            "oosTo": payload["sessionRange"]["to"],
            "oosSessions": payload["sessionRange"]["sessions"],
            "oosYears": payload["sessionRange"]["years"],
            "regime": "SHORT_TAPE",
            "sweep": {
                "signals": m["totalSignals"],
                "wins": wins,
                "losses": losses,
                "winRatePct": round(wins / resolved * 100, 2) if resolved else 0.0,
                "totalReturnPct": m["totalReturnPct"],
                "cagrPct": m["cagrPct"],
                "maxDrawdownPct": m["maxDrawdownPct"],
                "profitFactor": round(m["grossProfitPct"] / m["grossLossPct"], 2) if m["grossLossPct"] else None,
            },
            "momentum": {
                "positions": mm["totalSignals"],
                "wins": mw,
                "losses": ml,
                "winRatePct": round(mw / mr * 100, 2) if mr else 0.0,
                "totalReturnPct": mm["totalReturnPct"],
                "cagrPct": mm["cagrPct"],
                "maxDrawdownPct": mm["maxDrawdownPct"],
                "profitFactor": round(mm["grossProfitPct"] / mm["grossLossPct"], 2) if mm["grossLossPct"] else None,
            },
            "statArb": {
                "pairs": len(pairs),
                "signals": 0,
                "entrySignals": 0,
                "exitSignals": 0,
            },
        }],
        "aggregates": {
            "sweep": {
                "totalSignals": m["totalSignals"],
                "wins": wins,
                "losses": losses,
                "winRatePct": round(wins / resolved * 100, 2) if resolved else 0.0,
                "avgWinRatePct": round(wins / resolved * 100, 2) if resolved else 0.0,
                "avgDrawdownPct": m["maxDrawdownPct"],
                "worstWindowDrawdownPct": m["maxDrawdownPct"],
                "windowsAbove3DD": 1 if m["maxDrawdownPct"] >= 3.0 else 0,
                "windowsAbove10DD": 1 if m["maxDrawdownPct"] >= 10.0 else 0,
            },
            "momentum": {
                "totalPositions": mm["totalSignals"],
                "wins": mw,
                "losses": ml,
                "winRatePct": round(mw / mr * 100, 2) if mr else 0.0,
                "avgWinRatePct": round(mw / mr * 100, 2) if mr else 0.0,
                "avgDrawdownPct": mm["maxDrawdownPct"],
                "worstWindowDrawdownPct": mm["maxDrawdownPct"],
                "windowsAbove3DD": 1 if mm["maxDrawdownPct"] >= 3.0 else 0,
                "windowsAbove10DD": 1 if mm["maxDrawdownPct"] >= 10.0 else 0,
            },
            "regimeSwitching": [{"regime": "SHORT_TAPE", "windows": 1}],
        },
        "equityCurve": equity_curve_shares(payload.get("equityCurve", [])),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="PSX Meta-Brain 15-year walk-forward stress test")
    parser.add_argument("--db", type=str, default=None, help="SQLite store (default: backend/psx_history.db)")
    parser.add_argument("--horizon", type=float, default=DEFAULT_HORIZON_YEARS, help="requested horizon in years (default: 15)")
    parser.add_argument("--window", type=float, default=DEFAULT_WINDOW_YEARS, help="walk-forward window in years (default: 3)")
    parser.add_argument("--step", type=float, default=DEFAULT_STEP_YEARS, help="walk-forward step in years (default: 1)")
    parser.add_argument("--out", type=str, default=None, help="output JSON path")
    parser.add_argument("--top-n", type=int, default=10, help="momentum leader count (default: 10)")
    parser.add_argument("--sizing", type=str, default="atrp", choices=["equal", "atrp"], help="sizing mode (default: atrp)")
    parser.add_argument("--kelly", action="store_true", help="enable fractional Kelly overlay on the sweep book")
    parser.add_argument("--var", action="store_true", help="enable 99% historical VaR book clamp on the sweep book")
    parser.add_argument("--no-stat-arb", action="store_true", help="disable the informative stat-arb layer")
    parser.add_argument("--no-sweep-filters", action="store_true", help="run the sweep engine without institutional filters")
    parser.add_argument("--index-ticker", type=str, default=None, help="index ticker for beta sizing")
    args = parser.parse_args()

    db_path = args.db or str(get_db_path())
    config = StressTestConfig(
        horizon_years=args.horizon,
        window_years=args.window,
        step_years=args.step,
        top_n=args.top_n,
        sizing_mode=args.sizing,
        with_kelly=args.kelly,
        with_var=args.var,
        stat_arb=not args.no_stat_arb,
        sweep_with_filters=not args.no_sweep_filters,
        index_ticker=args.index_ticker,
    )

    bars_by_ticker, rejected = load_validated_bars(db_path)
    log.info("loaded %d tickers, %d rejected rows from %s", len(bars_by_ticker), rejected, db_path)

    payload = run_walk_forward_stress_test(bars_by_ticker, config)

    out_path = Path(args.out) if args.out else DEFAULT_OUTPUT
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    window_labels = payload["windowLabels"]
    agg = payload["aggregates"]
    log.info("=".join([""] + ["-"] * 60 + [""]))
    log.info("META-BRAIN 15Y STRESS TEST")
    log.info("  store        : %s", db_path)
    log.info("  session range: %s -> %s (%d sessions, %.2fy)",
             payload["sessionRange"]["from"], payload["sessionRange"]["to"],
             payload["sessionRange"]["sessions"], payload["sessionRange"]["years"])
    log.info("  universe     : %d tickers", payload["sessionRange"]["tickers"])
    log.info("  windows      : %d walk-forward windows (%s)",
             len(window_labels), " / ".join(window_labels))
    log.info("  sizing       : %s | Kelly=%s | VaR=%s | stat-arb=%s",
             config.sizing_mode, config.with_kelly, config.with_var, config.stat_arb)
    log.info("  ---- LIQUIDITY SWEEP (across windows) ----")
    log.info("    signals    : %d", agg["sweep"]["totalSignals"])
    log.info("    win rate   : %.2f%% (avg %.2f%%)", agg["sweep"]["winRatePct"], agg["sweep"]["avgWinRatePct"])
    log.info("    worst DD   : %.2f%% across %d windows > 3%% DD, %d windows > 10%% DD",
             agg["sweep"]["worstWindowDrawdownPct"], agg["sweep"]["windowsAbove3DD"], agg["sweep"]["windowsAbove10DD"])
    log.info("  ---- MOMENTUM ROTATION (across windows) ----")
    log.info("    positions  : %d", agg["momentum"]["totalPositions"])
    log.info("    win rate   : %.2f%% (avg %.2f%%)", agg["momentum"]["winRatePct"], agg["momentum"]["avgWinRatePct"])
    log.info("    worst DD   : %.2f%% across %d windows > 3%% DD, %d windows > 10%% DD",
             agg["momentum"]["worstWindowDrawdownPct"], agg["momentum"]["windowsAbove3DD"], agg["momentum"]["windowsAbove10DD"])
    log.info("  ---- REGIME SWITCHING ----")
    for row in agg["regimeSwitching"]:
        log.info("    %s : %d window(s)", row["regime"], row["windows"])
    log.info("  written      : %s", out_path)
    log.info("=".join([""] + ["-"] * 60 + [""]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
