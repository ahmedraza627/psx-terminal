"""backtest.py - chronological replay of the desk's liquidity-sweep book.

The rules mirror what ``/`` shows live: a BUY is taken at the signal close, the
stop is the ATR stop bounded by an outer safety cap, and the target is a flat
+12%. Positions are marked against every session in the store, so stops, targets
and the equity curve all come from the same tape the desk trades.

Two horizons are supported from one engine:

* ``--years 1``  the 250-session lab that tracks the live desk
* ``--years 5``  the macro stress test across bull, correction and chop cycles

The macro run additionally reports CAGR, calendar-year returns and every major
drawdown episode (peak, trough, depth, recovery), which is what makes a 5-year
replay readable rather than one opaque total return.

Run it:  python backend/src/quant/backtest.py [--years 5] [--db PATH] [--out PATH]
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
from src.quant.engine import LiquidityQuantEngine  # noqa: E402

PROJECT_ROOT = BACKEND_DIR.parent
DATA_DIR = PROJECT_ROOT / "frontend" / "public" / "data"
DEFAULT_OUTPUT = DATA_DIR / "backtest_metrics.json"
DEFAULT_OUTPUT_5Y = DATA_DIR / "backtest_5y_metrics.json"

SESSIONS_PER_YEAR = 252
# The engine reads at most ~60 bars of context (trend) or ~56 (weekly). Capping the
# slice keeps a 5-year replay linear instead of copying the whole prefix per session.
HISTORY_CAP = 210


@dataclass
class StrategyConfig:
    lookback_days: int = 5
    min_avg_volume: int = 50_000
    target_pct: float = 12.0
    max_stop_pct: float = 15.0  # outer safety bound only; the stop itself is ATR-scaled
    hold_horizon: int = 30
    max_sessions: int = 250
    starting_capital: float = 100_000.0
    position_pct: float = 10.0  # each position deploys 10% of live equity
    trend_ma_days: int = 50
    trend_slope_bars: int = 10
    min_rvol: float = 1.5
    min_vol_z: float = 1.0
    atr_stop_mult: float = 2.0
    trend_reference_bars: int = 1
    # Confluence hooks: off by default, so the published baseline is unchanged.
    require_weekly_confluence: bool = False
    weekly_ma_weeks: int = 10
    require_poc_confluence: bool = False
    poc_band_pct: float = 3.0


@dataclass
class Position:
    ticker: str
    signal_date: str
    entry: float
    stop: float
    target: float
    notional: float
    confidence: float
    reason: str
    bars_held: int = 0
    last_close: float = 0.0
    outcome: str = "IN PLAY"
    exit_date: Optional[str] = None
    exit_price: Optional[float] = None
    pnl_pct: float = 0.0

    def open_pnl_pkr(self) -> float:
        if not self.entry:
            return 0.0
        return self.notional * ((self.last_close - self.entry) / self.entry)


def years_between(first: date, last: date) -> float:
    """Calendar years spanned, floored so a CAGR never divides by zero."""
    return max((last - first).days / 365.25, 1 / 365.25)


def year_returns(curve: List[dict], starting_capital: float) -> List[dict]:
    """Compound each calendar year from the equity curve's own closes."""
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


def drawdown_episodes(curve: List[dict], limit: int = 5) -> Tuple[List[dict], Optional[dict]]:
    """Peak -> trough -> recovery for each material underwater stretch."""
    episodes: List[dict] = []
    peak_value = float("-inf")
    peak_date: Optional[str] = None
    trough_value = float("inf")
    trough_date: Optional[str] = None

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

    # Still underwater at the end of the tape: report it, don't invent a recovery.
    if peak_date is not None and trough_date is not None and trough_value < peak_value:
        episodes.append({
            "peakDate": peak_date,
            "troughDate": trough_date,
            "depthPct": round((trough_value / peak_value - 1) * 100, 2),
            "recoveryDate": None,
            "sessions": None,
        })

    dates = [point["date"] for point in curve]
    for episode in episodes:
        start = dates.index(episode["peakDate"])
        end = dates.index(episode["recoveryDate"]) if episode["recoveryDate"] else len(dates) - 1
        episode["sessions"] = end - start

    episodes.sort(key=lambda item: item["depthPct"])  # deepest (most negative) first
    return episodes[:limit], (episodes[0] if episodes else None)


class StrategyBacktester:
    """Walks the session calendar once, resolving risk before taking new risk."""

    def __init__(self, config: Optional[StrategyConfig] = None):
        self.cfg = config or StrategyConfig()

    def _settle(self, pos: Position, bar: DailyBar, price: float, outcome: str) -> None:
        pos.outcome = outcome
        pos.exit_price = round(price, 2)
        pos.exit_date = bar.trade_date.isoformat()
        pos.pnl_pct = round(((price - pos.entry) / pos.entry) * 100, 2)

    def run(self, bars_by_ticker: Dict[str, List[DailyBar]]) -> dict:
        cfg = self.cfg
        engine = LiquidityQuantEngine(
            lookback_days=cfg.lookback_days,
            min_avg_volume=cfg.min_avg_volume,
            atr_stop_mult=cfg.atr_stop_mult,
            trend_ma_days=cfg.trend_ma_days,
            trend_slope_bars=cfg.trend_slope_bars,
            min_rvol=cfg.min_rvol,
            min_vol_z=cfg.min_vol_z,
            trend_reference_bars=cfg.trend_reference_bars,
            require_weekly_confluence=cfg.require_weekly_confluence,
            weekly_ma_weeks=cfg.weekly_ma_weeks,
            require_poc_confluence=cfg.require_poc_confluence,
            poc_band_pct=cfg.poc_band_pct,
        )

        closes: Dict[str, Dict[date, DailyBar]] = {}
        index: Dict[date, List[tuple[str, int]]] = {}
        for ticker, bars in bars_by_ticker.items():
            if len(bars) < cfg.lookback_days + 2:
                continue
            per_day = {bar.trade_date: bar for bar in bars}
            closes[ticker] = per_day
            for position, bar in enumerate(bars):
                index.setdefault(bar.trade_date, []).append((ticker, position))

        if not closes:
            raise ValueError("no ticker carries enough history to backtest")

        sessions: List[date] = sorted(index.keys())[-cfg.max_sessions:]
        positions: List[Position] = []
        open_by_ticker: Dict[str, Position] = {}
        realized = 0.0
        peak = cfg.starting_capital
        curve: List[dict] = []
        skipped_evaluations = 0

        for session in sessions:
            session_str = session.isoformat()

            # 1) Resolve existing risk first; a bar that tags stop and target counts as a stop.
            for ticker, pos in list(open_by_ticker.items()):
                bar = closes[ticker].get(session)
                if bar is None:
                    continue  # halted / untraded: hold with the last mark, never crash
                pos.bars_held += 1
                pos.last_close = bar.close_price
                if bar.low_price <= pos.stop:
                    self._settle(pos, bar, pos.stop, "STOPPED OUT")
                elif bar.high_price >= pos.target:
                    self._settle(pos, bar, pos.target, "TARGET HIT")
                elif pos.bars_held >= cfg.hold_horizon:
                    self._settle(pos, bar, bar.close_price, "TIME EXIT")
                if pos.exit_date:
                    realized += pos.notional * pos.pnl_pct / 100
                    open_by_ticker.pop(ticker, None)

            # 2) Mark the book at today's close.
            equity = cfg.starting_capital + realized + sum(p.open_pnl_pkr() for p in open_by_ticker.values())

            # 3) Take new signals at the close, one position per ticker.
            for ticker, position in index.get(session, []):
                if ticker in open_by_ticker:
                    continue
                bars = bars_by_ticker[ticker]
                start = max(0, position + 1 - HISTORY_CAP)
                try:
                    signal = engine.evaluate_ticker(bars[start : position + 1])
                except (ValueError, ZeroDivisionError, IndexError):
                    skipped_evaluations += 1
                    continue
                if signal is None or signal.side != "BUY":
                    continue
                entry = signal.entry_price
                stop = round(max(signal.stop_loss, entry * (1 - cfg.max_stop_pct / 100)), 2)
                if stop >= entry:
                    continue
                pos = Position(
                    ticker=ticker,
                    signal_date=session_str,
                    entry=entry,
                    stop=stop,
                    target=round(entry * (1 + cfg.target_pct / 100), 2),
                    notional=equity * cfg.position_pct / 100,
                    confidence=signal.confidence_score,
                    reason=signal.reason,
                    last_close=entry,
                )
                positions.append(pos)
                open_by_ticker[ticker] = pos

            peak = max(peak, equity)
            curve.append({
                "date": session_str,
                "equity": round(equity, 2),
                "drawdownPct": round((equity / peak - 1) * 100, 2),
            })

        # Anything still live at the tape's end is reported, never silently dropped.
        for pos in open_by_ticker.values():
            pos.outcome = "IN PLAY"
            if pos.entry:
                pos.pnl_pct = round(((pos.last_close - pos.entry) / pos.entry) * 100, 2)

        return self._payload(positions, curve, sessions, skipped_evaluations, len(closes))

    def _payload(
        self,
        positions: List[Position],
        curve: List[dict],
        sessions: List[date],
        skipped_evaluations: int = 0,
        universe_size: int = 0,
    ) -> dict:
        cfg = self.cfg
        closed = [p for p in positions if p.outcome != "IN PLAY"]
        wins = [p for p in closed if p.pnl_pct > 0]
        losses = [p for p in closed if p.pnl_pct <= 0]
        gross_profit = sum(p.pnl_pct for p in wins)
        gross_loss = abs(sum(p.pnl_pct for p in losses))
        ending_equity = curve[-1]["equity"] if curve else cfg.starting_capital
        max_dd = abs(min((point["drawdownPct"] for point in curve), default=0.0))

        first, last = (sessions[0], sessions[-1]) if sessions else (None, None)
        horizon_years = years_between(first, last) if first and last else 0.0
        growth = ending_equity / cfg.starting_capital if cfg.starting_capital else 0.0
        cagr = (growth ** (1 / horizon_years) - 1) * 100 if horizon_years and growth > 0 else 0.0

        episodes, deepest = drawdown_episodes(curve)
        yearly = year_returns(curve, cfg.starting_capital)
        by_year: Dict[int, int] = {}
        for pos in positions:
            year = int(pos.signal_date[:4])
            by_year[year] = by_year.get(year, 0) + 1
        for row in yearly:
            row["signals"] = by_year.get(row["year"], 0)

        metrics = {
            "totalSignals": len(positions),
            "wins": len(wins),
            "losses": len(losses),
            "inPlay": len(positions) - len(closed),
            "winRatePct": round(len(wins) / len(closed) * 100, 2) if closed else 0.0,
            "profitFactor": round(gross_profit / gross_loss, 2) if gross_loss else None,
            "maxDrawdownPct": round(max_dd, 2),
            "totalReturnPct": round((ending_equity / cfg.starting_capital - 1) * 100, 2),
            "cagrPct": round(cagr, 2),
            "avgPnlPct": round(sum(p.pnl_pct for p in closed) / len(closed), 2) if closed else 0.0,
            "avgBarsHeld": round(sum(p.bars_held for p in closed) / len(closed), 1) if closed else 0.0,
            "bestTradePct": round(max((p.pnl_pct for p in closed), default=0.0), 2),
            "worstTradePct": round(min((p.pnl_pct for p in closed), default=0.0), 2),
            "grossProfitPct": round(gross_profit, 2),
            "grossLossPct": round(gross_loss, 2),
            "startingCapital": cfg.starting_capital,
            "endingEquity": ending_equity,
            "tradesPerYear": round(len(positions) / horizon_years, 1) if horizon_years else 0.0,
            "skippedEvaluations": skipped_evaluations,
        }

        trades = []
        for order, pos in enumerate(sorted(positions, key=lambda p: (p.signal_date, p.ticker), reverse=True)):
            trades.append({
                "id": order + 1,
                "ticker": pos.ticker,
                "signalDate": pos.signal_date,
                "exitDate": pos.exit_date,
                "side": "BUY",
                "entryPrice": pos.entry,
                "stopLoss": pos.stop,
                "targetPrice": pos.target,
                "exitPrice": pos.exit_price,
                "outcome": pos.outcome,
                "pnlPct": pos.pnl_pct,
                "barsHeld": pos.bars_held,
                "confidence": pos.confidence,
                "reason": pos.reason,
            })

        return {
            "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "horizonYears": round(horizon_years, 2),
            "strategy": {
                "name": "Liquidity Sweep Reclaim + Institutional Filters",
                "lookbackDays": cfg.lookback_days,
                "minAvgVolume": cfg.min_avg_volume,
                "targetPct": cfg.target_pct,
                "maxStopPct": cfg.max_stop_pct,
                "holdHorizonSessions": cfg.hold_horizon,
                "positionPct": cfg.position_pct,
                "trendMaDays": cfg.trend_ma_days,
                "trendSlopeBars": cfg.trend_slope_bars,
                "trendReferenceBars": cfg.trend_reference_bars,
                "minRvol": cfg.min_rvol,
                "minVolZ": cfg.min_vol_z,
                "atrStopMult": cfg.atr_stop_mult,
                "requireWeeklyConfluence": cfg.require_weekly_confluence,
                "weeklyMaWeeks": cfg.weekly_ma_weeks,
                "requirePocConfluence": cfg.require_poc_confluence,
                "pocBandPct": cfg.poc_band_pct,
            },
            "sessionRange": {
                "from": first.isoformat() if first else None,
                "to": last.isoformat() if last else None,
                "sessions": len(sessions),
                "years": round(horizon_years, 2),
                "tickers": universe_size,
            },
            "metrics": metrics,
            "yearlyReturns": yearly,
            "drawdownEpisodes": episodes,
            "maxDrawdown": deepest,
            "equityCurve": curve,
            "trades": trades,
        }


def run_backtest(db_path: str, config: Optional[StrategyConfig] = None) -> dict:
    bars_by_ticker, _rejected = load_validated_bars(db_path)
    return StrategyBacktester(config).run(bars_by_ticker)


def write_backtest_report(payload: dict, out_path: Path = DEFAULT_OUTPUT) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out_path


def output_for_years(years: float) -> Path:
    """The lab reads a fixed pair of files, so the horizon picks the destination."""
    return DEFAULT_OUTPUT_5Y if years >= 3 else DEFAULT_OUTPUT


def main() -> int:
    parser = argparse.ArgumentParser(description="PSX liquidity-sweep backtest (1Y or 5Y)")
    parser.add_argument("--db", help="SQLite store (default: backend/psx_history.db)")
    parser.add_argument("--out", help="output JSON path")
    parser.add_argument("--years", type=float, default=None, help="replay horizon in years (1 or 5)")
    parser.add_argument("--sessions", type=int, default=None, help="override trading sessions to replay")
    args = parser.parse_args()

    from src.core.config import get_db_path

    years = args.years if args.years is not None else 1.0
    sessions = args.sessions if args.sessions is not None else int(round(years * SESSIONS_PER_YEAR))

    db_path = args.db or str(get_db_path())
    payload = run_backtest(db_path, StrategyConfig(max_sessions=sessions))
    out = write_backtest_report(
        payload, Path(args.out) if args.out else output_for_years(years)
    )

    m = payload["metrics"]
    print(f"store        : {db_path}")
    print(f"horizon      : {payload['sessionRange']['years']}y / "
          f"{payload['sessionRange']['sessions']} sessions "
          f"({payload['sessionRange']['from']} -> {payload['sessionRange']['to']})")
    print(f"universe     : {payload['sessionRange']['tickers']} tickers")
    print(f"signals      : {m['totalSignals']} ({m['wins']}W / {m['losses']}L / {m['inPlay']} open)")
    print(f"win rate     : {m['winRatePct']}%")
    print(f"profit factor: {m['profitFactor'] if m['profitFactor'] is not None else 'inf'}")
    print(f"total return : {m['totalReturnPct']}% | CAGR {m['cagrPct']}% | max DD {m['maxDrawdownPct']}%")
    for row in payload["yearlyReturns"]:
        print(f"  {row['year']}: {row['returnPct']:>7.2f}%  "
              f"{row['signals']:>3} signals  DD -{row['maxDrawdownPct']:.1f}%")
    if payload["maxDrawdown"]:
        dd = payload["maxDrawdown"]
        print(f"worst DD     : {dd['depthPct']}% {dd['peakDate']} -> {dd['troughDate']}"
              f" (recovered {dd['recoveryDate'] or 'not yet'})")
    print(f"written      : {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
