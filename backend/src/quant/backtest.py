"""backtest.py - one-year, day-by-day simulation of the desk's liquidity-sweep book.

The rules mirror what ``/`` shows live: a BUY is taken at the signal close, the
stop is the ATR stop capped at 7% below entry, and the target is a flat +12%.
Positions are marked against every session in the store, so stops, targets and
the equity curve all come from the same tape the desk trades.

Run it:  python backend/src/quant/backtest.py [--sessions 250] [--db PATH]
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:  # allow direct CLI execution
    sys.path.insert(0, str(BACKEND_DIR))

from src.core.models import DailyBar  # noqa: E402
from src.ingestion.sqlite_adapter import load_validated_bars  # noqa: E402
from src.quant.engine import LiquidityQuantEngine  # noqa: E402

PROJECT_ROOT = BACKEND_DIR.parent
DEFAULT_OUTPUT = PROJECT_ROOT / "frontend" / "public" / "data" / "backtest_metrics.json"


@dataclass
class StrategyConfig:
    lookback_days: int = 15
    min_avg_volume: int = 50_000
    target_pct: float = 12.0
    max_stop_pct: float = 7.0
    hold_horizon: int = 15
    max_sessions: int = 250
    starting_capital: float = 100_000.0
    position_pct: float = 10.0  # each position deploys 10% of live equity


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
        engine = LiquidityQuantEngine(lookback_days=cfg.lookback_days, min_avg_volume=cfg.min_avg_volume)

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

        for session in sessions:
            session_str = session.isoformat()

            # 1) Resolve existing risk first; a bar that tags stop and target counts as a stop.
            for ticker, pos in list(open_by_ticker.items()):
                bar = closes[ticker].get(session)
                if bar is None:
                    continue
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
                signal = engine.evaluate_ticker(bars[: position + 1])
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

        return self._payload(positions, curve, sessions)

    def _payload(self, positions: List[Position], curve: List[dict], sessions: List[date]) -> dict:
        cfg = self.cfg
        closed = [p for p in positions if p.outcome != "IN PLAY"]
        wins = [p for p in closed if p.pnl_pct > 0]
        losses = [p for p in closed if p.pnl_pct <= 0]
        gross_profit = sum(p.pnl_pct for p in wins)
        gross_loss = abs(sum(p.pnl_pct for p in losses))
        ending_equity = curve[-1]["equity"] if curve else cfg.starting_capital
        max_dd = abs(min((point["drawdownPct"] for point in curve), default=0.0))

        metrics = {
            "totalSignals": len(positions),
            "wins": len(wins),
            "losses": len(losses),
            "inPlay": len(positions) - len(closed),
            "winRatePct": round(len(wins) / len(closed) * 100, 2) if closed else 0.0,
            "profitFactor": round(gross_profit / gross_loss, 2) if gross_loss else None,
            "maxDrawdownPct": round(max_dd, 2),
            "totalReturnPct": round((ending_equity / cfg.starting_capital - 1) * 100, 2),
            "avgPnlPct": round(sum(p.pnl_pct for p in closed) / len(closed), 2) if closed else 0.0,
            "avgBarsHeld": round(sum(p.bars_held for p in closed) / len(closed), 1) if closed else 0.0,
            "bestTradePct": round(max((p.pnl_pct for p in closed), default=0.0), 2),
            "worstTradePct": round(min((p.pnl_pct for p in closed), default=0.0), 2),
            "grossProfitPct": round(gross_profit, 2),
            "grossLossPct": round(gross_loss, 2),
            "startingCapital": cfg.starting_capital,
            "endingEquity": ending_equity,
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
            "strategy": {
                "name": "Liquidity Sweep Reclaim",
                "lookbackDays": cfg.lookback_days,
                "minAvgVolume": cfg.min_avg_volume,
                "targetPct": cfg.target_pct,
                "maxStopPct": cfg.max_stop_pct,
                "holdHorizonSessions": cfg.hold_horizon,
                "positionPct": cfg.position_pct,
            },
            "sessionRange": {
                "from": sessions[0].isoformat() if sessions else None,
                "to": sessions[-1].isoformat() if sessions else None,
                "sessions": len(sessions),
            },
            "metrics": metrics,
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


def main() -> int:
    parser = argparse.ArgumentParser(description="1-year liquidity-sweep backtest")
    parser.add_argument("--db", help="SQLite store (default: backend/psx_history.db)")
    parser.add_argument("--out", help="output JSON path")
    parser.add_argument("--sessions", type=int, default=250, help="trading sessions to replay")
    args = parser.parse_args()

    from src.core.config import get_db_path

    db_path = args.db or str(get_db_path())
    payload = run_backtest(db_path, StrategyConfig(max_sessions=args.sessions))
    out = write_backtest_report(payload, Path(args.out) if args.out else DEFAULT_OUTPUT)

    m = payload["metrics"]
    print(f"store        : {db_path}")
    print(f"sessions     : {payload['sessionRange']['sessions']} "
          f"({payload['sessionRange']['from']} -> {payload['sessionRange']['to']})")
    print(f"signals      : {m['totalSignals']} ({m['wins']}W / {m['losses']}L / {m['inPlay']} open)")
    print(f"win rate     : {m['winRatePct']}%")
    print(f"profit factor: {m['profitFactor'] if m['profitFactor'] is not None else 'inf'}")
    print(f"total return : {m['totalReturnPct']}% | max DD {m['maxDrawdownPct']}%")
    print(f"written      : {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
