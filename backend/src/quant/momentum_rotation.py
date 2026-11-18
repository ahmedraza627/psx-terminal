"""momentum_rotation.py - cross-sectional momentum factor rotation backtest.

Models an institutional ETF-style smart-beta rotation strategy (cf. JSMFETF-style
momentum factor baskets): every month we rank the active universe by rolling momentum,
hold the Top-N leaders, and exit on a hard stop or a 50-day SMA break.

The design choices mirror what a long-only factor ETF would actually do:

* two momentum horizons (3-month and 6-month ROC) are combined into one composite
  score so the basket is not whipsawed by a single lookback
* rebalancing is calendar-monthly on the last trading day, like a month-end factor
  rebalance, not on every signal bar
* risk is cut either on a 7% hard stop or a 50-day SMA breach, whichever happens first
* each leader is sized equally within the book so the backtest reads like a basket,
  not a concentrated single-name bet

Run it:  python backend/src/quant/momentum_rotation.py [--db PATH] [--out PATH] [--top-n 10]
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:  # allow direct CLI execution
    sys.path.insert(0, str(BACKEND_DIR))

from src.core.models import DailyBar  # noqa: E402
from src.ingestion.sqlite_adapter import load_validated_bars  # noqa: E402
from src.ingestion.universe import active_universe  # noqa: E402

PROJECT_ROOT = BACKEND_DIR.parent
DATA_DIR = PROJECT_ROOT / "frontend" / "public" / "data"
DEFAULT_OUTPUT = DATA_DIR / "momentum_5y_metrics.json"

SESSIONS_PER_YEAR = 252
HISTORY_CAP = 210  # matches the liquidity-sweep engine's capped lookback slice
SMA_STOP_DAYS = 50  # 50-day SMA break exit, like a trend-protection rule in a factor ETF
HARD_STOP_PCT = 7.0  # 7% hard stop per position
TOP_N_DEFAULT = 10
MONTHS_PER_YEAR = 12


@dataclass
class MomentumConfig:
    top_n: int = TOP_N_DEFAULT
    hard_stop_pct: float = HARD_STOP_PCT
    sma_stop_days: int = SMA_STOP_DAYS
    position_count: int = 1  # one share per leader for the equity-curve mark
    starting_capital: float = 100_000.0


@dataclass
class RotationPosition:
    ticker: str
    entry_date: str
    entry_price: float
    hard_stop: float
    sma_stop: Optional[float]
    shares: int
    bars_held: int = 0
    last_close: float = 0.0
    outcome: str = "IN PLAY"
    exit_date: Optional[str] = None
    exit_price: Optional[float] = None
    pnl_pct: float = 0.0
    peak_date: Optional[str] = None
    peak_price: float = 0.0


def roc(bars: List[DailyBar], months_back: int, session_index: int) -> float:
    """Rate of change from `months_back` sessions ago to the current close.

    Returns 0 when there is not enough history; the caller decides whether that
    disqualifies the ticker or just scores it low.
    """
    lookback = max(1, int(months_back * SESSIONS_PER_YEAR / MONTHS_PER_YEAR))
    start = session_index - lookback
    if start < 0:
        return 0.0
    past = bars[start].close_price
    current = bars[session_index].close_price
    if past <= 0:
        return 0.0
    return (current / past - 1) * 100


def composite_momentum(bars: List[DailyBar], session_index: int) -> float:
    """Combine 3-month and 6-month ROC into one score.

    The two horizons are added with equal weight. A name that is rallying on both
    timeframes scores higher than one that is only short-term strong, which is the
    intuition behind a multi-horizon momentum factor.
    """
    return roc(bars, 3, session_index) + roc(bars, 6, session_index)


def sma(bars: List[DailyBar], session_index: int, days: int) -> Optional[float]:
    """Simple moving average of closes ending at `session_index`."""
    if session_index < days:
        return None
    window = bars[session_index - days : session_index]
    return sum(b.close_price for b in window) / days


def last_trading_day_of_month(sessions: List[date]) -> List[date]:
    """Return the last session that falls in each calendar month, in order."""
    by_month: Dict[Tuple[int, int], date] = {}
    for session in sessions:
        key = (session.year, session.month)
        by_month[key] = session  # later sessions overwrite earlier ones
    return sorted(by_month.values())


def rebalance_dates(sessions: List[date]) -> List[date]:
    """Months that have at least one session."""
    return last_trading_day_of_month(sessions)


def build_monthly_rankings(
    bars_by_ticker: Dict[str, List[DailyBar]],
    sessions: List[date],
    universe: List[str],
) -> Dict[date, List[Tuple[str, float]]]:
    """For each rebalance date, rank every universe ticker by composite momentum.

    Tickers without enough history for the 6-month ROC score 0 and sort to the
    bottom, which is the conservative choice: a name we cannot measure does not
    earn a spot in the basket.
    """
    rankings: Dict[date, List[Tuple[str, float]]] = {}
    for rebal_date in rebalance_dates(sessions):
        ranked: List[Tuple[str, float]] = []
        for ticker in universe:
            bars = bars_by_ticker.get(ticker)
            if not bars:
                continue
            # Find the position in this ticker's own tape that corresponds to the
            # rebalance session. Use the last bar at or before the rebalance date.
            idx = _bar_index_at_or_before(bars, rebal_date)
            if idx < 0:
                continue
            score = composite_momentum(bars, idx)
            ranked.append((ticker, round(score, 2)))
        ranked.sort(key=lambda item: -item[1])
        rankings[rebal_date] = ranked
    return rankings


def _bar_index_at_or_before(bars: List[DailyBar], target: date) -> int:
    """Binary-ish search for the last bar whose date is <= target."""
    lo, hi = 0, len(bars) - 1
    best = -1
    while lo <= hi:
        mid = (lo + hi) // 2
        if bars[mid].trade_date <= target:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def _run_rotation_on_bars(
    bars_by_ticker: Dict[str, List[DailyBar]],
    config: MomentumConfig,
) -> dict:
    """Cross-sectional momentum rotation backtest from an in-memory bar store.

    This is the internal engine path used by the CLI (which loads from SQLite) and by
    the tests (which construct their own tapes).
    """
    # Universe = tickers with enough history to be measurable on both horizons.
    min_bars = int(7 * SESSIONS_PER_YEAR / MONTHS_PER_YEAR)
    universe = [ticker for ticker, bars in bars_by_ticker.items() if len(bars) >= min_bars]
    if not universe:
        raise ValueError("no ticker carries enough history for a momentum ranking")

    # Session calendar across the whole universe.
    session_set: Dict[date, List[Tuple[str, int]]] = {}
    for ticker in universe:
        bars = bars_by_ticker.get(ticker)
        if not bars:
            continue
        for i, bar in enumerate(bars):
            session_set.setdefault(bar.trade_date, []).append((ticker, i))

    sessions = sorted(session_set.keys())
    if len(sessions) < config.sma_stop_days + 60:
        raise ValueError("not enough sessions for a meaningful 5-year rotation replay")

    # Backtest window: last ~5 years of sessions, same horizon philosophy as the
    # macro liquidity-sweep run.
    sessions = sessions[-int(5 * SESSIONS_PER_YEAR):]

    monthly_rankings = build_monthly_rankings(bars_by_ticker, sessions, universe)
    rebalance_list = rebalance_dates(sessions)

    positions: List[RotationPosition] = []
    open_by_ticker: Dict[str, RotationPosition] = {}
    equity = config.starting_capital
    peak = equity
    curve: List[dict] = []

    for i, session in enumerate(sessions):
        session_str = session.isoformat()

        # 1) Resolve exits before doing anything else.
        for ticker, pos in list(open_by_ticker.items()):
            bar_list = bars_by_ticker.get(ticker)
            if not bar_list:
                continue
            idx = _bar_index_at_or_before(bar_list, session)
            if idx < 0:
                continue  # halted name: hold the last mark, do not crash
            bar = bar_list[idx]
            pos.bars_held += 1
            pos.last_close = bar.close_price

            # Track the running peak for this position so we can report per-name DD.
            if pos.last_close >= pos.peak_price:
                pos.peak_price = pos.last_close
                pos.peak_date = bar.trade_date.isoformat()

            exit_now = False
            exit_reason = ""
            exit_price: Optional[float] = None

            # Hard stop first.
            if bar.low_price <= pos.hard_stop:
                exit_now = True
                exit_reason = "HARD STOP"
                exit_price = round(pos.hard_stop, 2)
            # 50-day SMA break exit second.
            elif pos.sma_stop is not None and bar.close_price < pos.sma_stop:
                exit_now = True
                exit_reason = "SMA BREAK"
                exit_price = bar.close_price

            if exit_now:
                pos.outcome = exit_reason
                pos.exit_date = session_str
                pos.exit_price = exit_price
                pos.pnl_pct = round(((exit_price - pos.entry_price) / pos.entry_price) * 100, 2)
                equity += pos.shares * (exit_price - pos.entry_price)
                open_by_ticker.pop(ticker, None)

        # 2) Monthly rebalance: drop laggards, add new leaders.
        if session in monthly_rankings:
            ranked = monthly_rankings[session]
            leaders = [ticker for ticker, _ in ranked[: config.top_n]]

            # Exit anything that is no longer a leader.
            for ticker in list(open_by_ticker):
                if ticker not in leaders:
                    pos = open_by_ticker.pop(ticker)
                    # Mark-to-close at the rebalance session's price.
                    bar_list = bars_by_ticker.get(ticker)
                    if bar_list:
                        idx = _bar_index_at_or_before(bar_list, session)
                        if idx >= 0:
                            close = bar_list[idx].close_price
                            pos.outcome = "REBALANCE EXIT"
                            pos.exit_date = session_str
                            pos.exit_price = close
                            pos.pnl_pct = round(((close - pos.entry_price) / pos.entry_price) * 100, 2)
                            equity += pos.shares * (close - pos.entry_price)

            # Enter the new leaders that are not already held.
            for ticker in leaders:
                if ticker in open_by_ticker:
                    continue
                bar_list = bars_by_ticker.get(ticker)
                if not bar_list:
                    continue
                idx = _bar_index_at_or_before(bar_list, session)
                if idx < 0:
                    continue
                bar = bar_list[idx]
                entry = bar.close_price
                if entry <= 0:
                    continue
                hard_stop = round(entry * (1 - config.hard_stop_pct / 100), 2)
                sma_stop = sma(bar_list, idx, config.sma_stop_days)
                shares = config.position_count
                pos = RotationPosition(
                    ticker=ticker,
                    entry_date=session_str,
                    entry_price=round(entry, 2),
                    hard_stop=hard_stop,
                    sma_stop=round(sma_stop, 2) if sma_stop else None,
                    shares=shares,
                    last_close=entry,
                    peak_date=session_str,
                    peak_price=entry,
                )
                positions.append(pos)
                open_by_ticker[ticker] = pos
                # Pay the entry from equity so the curve reflects the real deployment.
                equity -= entry * shares

        # 3) Mark the book: unrealized P&L on open names plus cash.
        unrealized = sum(
            pos.shares * (pos.last_close - pos.entry_price)
            for pos in open_by_ticker.values()
        )
        equity = equity + unrealized
        peak = max(peak, equity)
        curve.append({
            "date": session_str,
            "equity": round(equity, 2),
            "drawdownPct": round((equity / peak - 1) * 100, 2),
        })

    # Close anything still open at the end of the tape.
    for pos in open_by_ticker.values():
        pos.outcome = "IN PLAY"
        if pos.entry_price:
            pos.pnl_pct = round(((pos.last_close - pos.entry_price) / pos.entry_price) * 100, 2)

    return _momentum_payload(
        positions,
        curve,
        sessions,
        rebalance_list,
        monthly_rankings,
        config,
        len(universe),
    )


def run_momentum_rotation(
    db_path: str,
    config: Optional[MomentumConfig] = None,
) -> dict:
    """Cross-sectional momentum rotation backtest over the full stored tape."""
    config = config or MomentumConfig()

    bars_by_ticker, _rejected = load_validated_bars(db_path)
    return _run_rotation_on_bars(bars_by_ticker, config)


def _momentum_payload(
    positions: List[RotationPosition],
    curve: List[dict],
    sessions: List[date],
    rebalance_list: List[date],
    monthly_rankings: Dict[date, List[Tuple[str, float]]],
    config: MomentumConfig,
    universe_size: int,
) -> dict:
    closed = [p for p in positions if p.outcome != "IN PLAY"]
    wins = [p for p in closed if p.pnl_pct > 0]
    losses = [p for p in closed if p.pnl_pct <= 0]
    ending_equity = curve[-1]["equity"] if curve else config.starting_capital
    max_dd = abs(min((point["drawdownPct"] for point in curve), default=0.0))

    first, last = (sessions[0], sessions[-1]) if sessions else (None, None)

    def years_between(a: date, b: date) -> float:
        return max((b - a).days / 365.25, 1 / 365.25)

    horizon_years = years_between(first, last) if first and last else 0.0
    growth = ending_equity / config.starting_capital if config.starting_capital else 0.0
    cagr = (growth ** (1 / horizon_years) - 1) * 100 if horizon_years and growth > 0 else 0.0

    gross_profit = sum(p.pnl_pct for p in wins)
    gross_loss = abs(sum(p.pnl_pct for p in losses))

    metrics = {
        "totalSignals": len(positions),
        "wins": len(wins),
        "losses": len(losses),
        "inPlay": len(positions) - len(closed),
        "winRatePct": round(len(wins) / len(closed) * 100, 2) if closed else 0.0,
        "profitFactor": round(gross_profit / gross_loss, 2) if gross_loss else None,
        "maxDrawdownPct": round(max_dd, 2),
        "totalReturnPct": round((ending_equity / config.starting_capital - 1) * 100, 2),
        "cagrPct": round(cagr, 2),
        "avgPnlPct": round(sum(p.pnl_pct for p in closed) / len(closed), 2) if closed else 0.0,
        "avgBarsHeld": round(sum(p.bars_held for p in closed) / len(closed), 1) if closed else 0.0,
        "bestTradePct": round(max((p.pnl_pct for p in closed), default=0.0), 2),
        "worstTradePct": round(min((p.pnl_pct for p in closed), default=0.0), 2),
        "grossProfitPct": round(gross_profit, 2),
        "grossLossPct": round(gross_loss, 2),
        "startingCapital": config.starting_capital,
        "endingEquity": ending_equity,
        "rebalanceMonths": len(rebalance_list),
        "topN": config.top_n,
    }

    trades = []
    for order, pos in enumerate(
        sorted(positions, key=lambda p: (p.entry_date, p.ticker), reverse=True)
    ):
        trades.append({
            "id": order + 1,
            "ticker": pos.ticker,
            "signalDate": pos.entry_date,
            "exitDate": pos.exit_date,
            "side": "BUY",
            "entryPrice": pos.entry_price,
            "stopLoss": pos.hard_stop,
            "targetPrice": None,
            "exitPrice": pos.exit_price,
            "outcome": pos.outcome,
            "pnlPct": pos.pnl_pct,
            "barsHeld": pos.bars_held,
            "confidence": None,
            "reason": f"Momentum entry · hard stop {config.hard_stop_pct}% · 50d SMA break",
        })

    # Yearly returns from the equity curve, same convention as the liquidity-sweep report.
    yearly: Dict[int, List[dict]] = {}
    for point in curve:
        yearly.setdefault(int(point["date"][:4]), []).append(point)
    year_rows = []
    carried = config.starting_capital
    for year in sorted(yearly):
        points = yearly[year]
        ending = points[-1]["equity"]
        year_rows.append({
            "year": year,
            "returnPct": round((ending / carried - 1) * 100, 2) if carried else 0.0,
            "sessions": len(points),
            "maxDrawdownPct": round(abs(min(p["drawdownPct"] for p in points)), 2),
            "startingEquity": round(carried, 2),
            "endingEquity": round(ending, 2),
        })
        carried = ending

    # Per-position drawdown episodes, deepest first, for the same read as the macro tab.
    def position_episodes() -> List[dict]:
        episodes: List[dict] = []
        for pos in positions:
            if pos.peak_date and pos.last_close < pos.peak_price:
                depth = round((pos.last_close / pos.peak_price - 1) * 100, 2)
                episodes.append({
                    "ticker": pos.ticker,
                    "peakDate": pos.peak_date,
                    "troughDate": pos.exit_date or (last.isoformat() if last else ""),
                    "depthPct": depth,
                    "recovered": pos.last_close >= pos.peak_price,
                })
        episodes.sort(key=lambda item: item["depthPct"])
        return episodes[:5]

    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "horizonYears": round(horizon_years, 2),
        "strategy": {
            "name": "ETF-Style Momentum Factor Rotation (JSMFETF-style)",
            "topN": config.top_n,
            "hardStopPct": config.hard_stop_pct,
            "smaStopDays": config.sma_stop_days,
            "momentumLookbacksMonths": [3, 6],
            "rebalanceFrequency": "monthly",
            "positionSizing": "equal-weight (1 share per leader)",
        },
        "sessionRange": {
            "from": first.isoformat() if first else None,
            "to": last.isoformat() if last else None,
            "sessions": len(sessions),
            "years": round(horizon_years, 2),
            "tickers": universe_size,
        },
        "rebalanceSchedule": [
            {"date": d.isoformat(), "leaders": [t for t, _ in monthly_rankings.get(d, [])[:config.top_n]]}
            for d in rebalance_list
        ],
        "metrics": metrics,
        "yearlyReturns": year_rows,
        "equityCurve": curve,
        "trades": trades,
        "worstDrawdowns": position_episodes(),
    }


def write_momentum_report(payload: dict, out_path: Path = DEFAULT_OUTPUT) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="PSX ETF-style momentum factor rotation backtest (5Y)"
    )
    parser.add_argument("--db", help="SQLite store (default: backend/psx_history.db)")
    parser.add_argument("--out", help="output JSON path")
    parser.add_argument(
        "--top-n",
        type=int,
        default=TOP_N_DEFAULT,
        help="number of top-momentum leaders to hold (default: 10)",
    )
    args = parser.parse_args()

    from src.core.config import get_db_path

    db_path = args.db or str(get_db_path())
    config = MomentumConfig(top_n=args.top_n)
    payload = run_momentum_rotation(db_path, config)
    out = write_momentum_report(payload, Path(args.out) if args.out else DEFAULT_OUTPUT)

    m = payload["metrics"]
    print(f"store        : {db_path}")
    print(f"horizon      : {payload['sessionRange']['years']}y / "
          f"{payload['sessionRange']['sessions']} sessions "
          f"({payload['sessionRange']['from']} -> {payload['sessionRange']['to']})")
    print(f"universe     : {payload['sessionRange']['tickers']} tickers · top {config.top_n}")
    print(f"rebalance    : {m['rebalanceMonths']} monthly rebalances")
    print(f"signals      : {m['totalSignals']} positions ({m['wins']}W / {m['losses']}L / {m['inPlay']} open)")
    print(f"win rate     : {m['winRatePct']}%")
    print(f"profit factor: {m['profitFactor'] if m['profitFactor'] is not None else 'inf'}")
    print(f"total return : {m['totalReturnPct']}% | CAGR {m['cagrPct']}% | max DD {m['maxDrawdownPct']}%")
    for row in payload["yearlyReturns"]:
        print(f"  {row['year']}: {row['returnPct']:>7.2f}%  "
              f"{row['sessions']:>3} sessions  DD -{row['maxDrawdownPct']:.1f}%")
    print(f"worst names  : {len(payload['worstDrawdowns'])} positions")
    for dd in payload["worstDrawdowns"][:3]:
        print(f"    {dd['ticker']:>6} {dd['depthPct']:.1f}% "
              f"{dd['peakDate']} -> {dd['troughDate']} "
              f"{'recovered' if dd['recovered'] else 'open'}")
    print(f"written      : {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
