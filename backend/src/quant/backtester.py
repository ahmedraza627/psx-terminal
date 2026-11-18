from datetime import date
from typing import Dict, List, Optional, Set, Tuple
from pydantic import BaseModel
from src.core.models import DailyBar, TradeSignal
from src.quant.sliding_window import MonotonicWindowTracker


class BacktestTrade(BaseModel):
    ticker: str
    signal_date: str
    side: str
    entry_price: float
    stop_loss: float
    target_price: float
    outcome: str
    pnl_pct: float
    bars_held: int


class BacktestReport(BaseModel):
    total_signals: int
    wins: int
    losses: int
    open_trades: int
    win_rate_pct: float
    avg_pnl_pct: float
    trades: List[BacktestTrade]


class LinearBacktester:
    """
    O(N) linear-time backtester combining MonotonicWindowTracker, ATR risk sizing,
    Close Location Value (CLV), and institutional flow alignment.
    """

    def __init__(
        self,
        lookback_days: int = 15,
        min_avg_volume: int = 50_000,
        hold_horizon: int = 15,
        atr_stop_mult: float = 1.8,
        atr_tp_mult: float = 2.8,
    ):
        self.lookback_days = lookback_days
        self.min_avg_volume = min_avg_volume
        self.hold_horizon = hold_horizon
        self.atr_stop_mult = atr_stop_mult
        self.atr_tp_mult = atr_tp_mult

    def _scan_ticker_signals(
        self,
        bars: List[DailyBar],
        smart_flow: Optional[Dict[date, float]] = None,
        ndm_activity: Optional[Set[Tuple[str, date]]] = None,
    ) -> List[tuple[int, TradeSignal]]:
        tracker = MonotonicWindowTracker(window_size=self.lookback_days)
        found: List[tuple[int, TradeSignal]] = []
        tr_sum = 0.0

        for idx, bar in enumerate(bars):
            tr = (
                bar.high_price - bar.low_price
                if idx == 0
                else max(
                    bar.high_price - bar.low_price,
                    abs(bar.high_price - bars[idx - 1].close_price),
                    abs(bar.low_price - bars[idx - 1].close_price),
                )
            )

            if tracker.is_full:
                avg_vol = tracker.avg_volume
                w_low = tracker.min_low
                w_high = tracker.max_high
                atr = max(tr_sum / self.lookback_days, bar.close_price * 0.015)
                candle_range = bar.high_price - bar.low_price

                if candle_range > 0 and avg_vol >= self.min_avg_volume and bar.volume > avg_vol * 1.5:
                    clv = (bar.close_price - bar.low_price) / candle_range
                    macro_flow = smart_flow.get(bar.trade_date, 0.0) if smart_flow else 0.0
                    has_ndm = (bar.ticker, bar.trade_date) in ndm_activity if ndm_activity else False

                    # BUY: Sweep low + upper 40% close + non-negative smart money flow (or NDM block)
                    if bar.low_price < w_low and bar.close_price > w_low and clv >= 0.60:
                        if smart_flow is None or macro_flow >= 0 or has_ndm:
                            entry = bar.close_price
                            found.append((
                                idx,
                                TradeSignal(
                                    ticker=bar.ticker,
                                    signal_date=bar.trade_date,
                                    side="BUY",
                                    entry_price=round(entry, 2),
                                    stop_loss=round(entry - (atr * self.atr_stop_mult), 2),
                                    target_price=round(entry + (atr * self.atr_tp_mult), 2),
                                    confidence_score=min(1.0, round(bar.volume / (avg_vol * 2.5), 2)),
                                    reason=f"Swept {self.lookback_days}d low ({w_low}) | ATR {atr:.2f}",
                                ),
                            ))

                    # SHORT: Pierce high + lower 40% close + distribution flow (macro_flow <= 0)
                    elif bar.high_price > w_high and bar.close_price < w_high and clv <= 0.40:
                        if smart_flow is None or macro_flow <= 0:
                            entry = bar.close_price
                            found.append((
                                idx,
                                TradeSignal(
                                    ticker=bar.ticker,
                                    signal_date=bar.trade_date,
                                    side="SHORT",
                                    entry_price=round(entry, 2),
                                    stop_loss=round(entry + (atr * self.atr_stop_mult), 2),
                                    target_price=round(entry - (atr * self.atr_tp_mult), 2),
                                    confidence_score=min(1.0, round(bar.volume / (avg_vol * 2.5), 2)),
                                    reason=f"Rejected above {self.lookback_days}d high ({w_high}) | ATR {atr:.2f}",
                                ),
                            ))

            tracker.push(bar.low_price, bar.high_price, bar.volume)
            tr_sum += tr
            if idx >= self.lookback_days:
                prev_idx = idx - self.lookback_days
                old_tr = (
                    bars[prev_idx].high_price - bars[prev_idx].low_price
                    if prev_idx == 0
                    else max(
                        bars[prev_idx].high_price - bars[prev_idx].low_price,
                        abs(bars[prev_idx].high_price - bars[prev_idx - 1].close_price),
                        abs(bars[prev_idx].low_price - bars[prev_idx - 1].close_price),
                    )
                )
                tr_sum -= old_tr

        return found

    def run(
        self,
        bars_by_ticker: Dict[str, List[DailyBar]],
        smart_flow: Optional[Dict[date, float]] = None,
        ndm_activity: Optional[Set[Tuple[str, date]]] = None,
    ) -> BacktestReport:
        trades: List[BacktestTrade] = []

        for ticker, bars in bars_by_ticker.items():
            signals = self._scan_ticker_signals(bars, smart_flow, ndm_activity)
            for sig_idx, sig in signals:
                outcome = "OPEN"
                pnl_pct = 0.0
                bars_held = 0

                future_bars = bars[sig_idx + 1 : sig_idx + 1 + self.hold_horizon]
                for step, fbar in enumerate(future_bars, start=1):
                    bars_held = step
                    if sig.side == "BUY":
                        if fbar.low_price <= sig.stop_loss:
                            outcome = "LOSS"
                            pnl_pct = round(((sig.stop_loss - sig.entry_price) / sig.entry_price) * 100, 2)
                            break
                        if fbar.high_price >= sig.target_price:
                            outcome = "WIN"
                            pnl_pct = round(((sig.target_price - sig.entry_price) / sig.entry_price) * 100, 2)
                            break
                    else:
                        if fbar.high_price >= sig.stop_loss:
                            outcome = "LOSS"
                            pnl_pct = round(((sig.entry_price - sig.stop_loss) / sig.entry_price) * 100, 2)
                            break
                        if fbar.low_price <= sig.target_price:
                            outcome = "WIN"
                            pnl_pct = round(((sig.entry_price - sig.target_price) / sig.entry_price) * 100, 2)
                            break

                if outcome == "OPEN" and future_bars:
                    last_close = future_bars[-1].close_price
                    raw_diff = (last_close - sig.entry_price) if sig.side == "BUY" else (sig.entry_price - last_close)
                    pnl_pct = round((raw_diff / sig.entry_price) * 100, 2)

                trades.append(
                    BacktestTrade(
                        ticker=sig.ticker,
                        signal_date=str(sig.signal_date),
                        side=sig.side,
                        entry_price=sig.entry_price,
                        stop_loss=sig.stop_loss,
                        target_price=sig.target_price,
                        outcome=outcome,
                        pnl_pct=pnl_pct,
                        bars_held=bars_held,
                    )
                )

        wins = sum(1 for t in trades if t.outcome == "WIN")
        losses = sum(1 for t in trades if t.outcome == "LOSS")
        open_trades = sum(1 for t in trades if t.outcome == "OPEN")
        resolved = wins + losses
        win_rate = round((wins / resolved) * 100, 2) if resolved > 0 else 0.0
        avg_pnl = round(sum(t.pnl_pct for t in trades) / len(trades), 2) if trades else 0.0

        return BacktestReport(
            total_signals=len(trades),
            wins=wins,
            losses=losses,
            open_trades=open_trades,
            win_rate_pct=win_rate,
            avg_pnl_pct=avg_pnl,
            trades=trades,
        )