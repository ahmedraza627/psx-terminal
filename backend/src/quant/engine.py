from typing import List, Optional
from src.core.models import DailyBar, TradeSignal


class LiquidityQuantEngine:
    """
    Stateless, deterministic quant engine with ATR volatility sizing and Close Location Value (CLV).
    """

    def __init__(self, lookback_days: int = 15, min_avg_volume: int = 50_000, atr_stop_mult: float = 1.8, atr_tp_mult: float = 3.2):
        self.lookback_days = lookback_days
        self.min_avg_volume = min_avg_volume
        self.atr_stop_mult = atr_stop_mult
        self.atr_tp_mult = atr_tp_mult

    def compute_atr(self, bars: List[DailyBar], period: int = 14) -> float:
        if len(bars) < 2:
            return bars[-1].high_price - bars[-1].low_price
        subset = bars[-(period + 1) :]
        trs = []
        for i in range(1, len(subset)):
            curr, prev = subset[i], subset[i - 1]
            tr = max(
                curr.high_price - curr.low_price,
                abs(curr.high_price - prev.close_price),
                abs(curr.low_price - prev.close_price),
            )
            trs.append(tr)
        return sum(trs) / len(trs)

    def evaluate_ticker(self, bars: List[DailyBar]) -> Optional[TradeSignal]:
        if len(bars) <= self.lookback_days:
            return None

        window = bars[-(self.lookback_days + 1) : -1]
        current = bars[-1]

        avg_vol = sum(b.volume for b in window) / self.lookback_days
        if avg_vol < self.min_avg_volume:
            return None

        candle_range = current.high_price - current.low_price
        if candle_range <= 0:
            return None

        clv = (current.close_price - current.low_price) / candle_range
        window_low = min(b.low_price for b in window)
        window_high = max(b.high_price for b in window)
        atr = max(self.compute_atr(bars[:-1]), current.close_price * 0.015)

        # Bullish Liquidity Sweep: sweeps 15d low, reclaims above it, closes in upper 40% of range
        if current.low_price < window_low and current.close_price > window_low:
            if current.volume > avg_vol * 1.5 and clv >= 0.60:
                entry = current.close_price
                return TradeSignal(
                    ticker=current.ticker,
                    signal_date=current.trade_date,
                    side="BUY",
                    entry_price=round(entry, 2),
                    stop_loss=round(entry - (atr * self.atr_stop_mult), 2),
                    target_price=round(entry + (atr * self.atr_tp_mult), 2),
                    confidence_score=min(1.0, round(current.volume / (avg_vol * 2.5), 2)),
                    reason=f"Swept {self.lookback_days}d low ({window_low}) | Vol {current.volume/avg_vol:.1f}x | ATR {atr:.2f}",
                )

        # Bearish Bull-Trap: pierces 15d high, closes back below it in lower 40% of range
        if current.high_price > window_high and current.close_price < window_high:
            if current.volume > avg_vol * 1.5 and clv <= 0.40:
                entry = current.close_price
                return TradeSignal(
                    ticker=current.ticker,
                    signal_date=current.trade_date,
                    side="SHORT",
                    entry_price=round(entry, 2),
                    stop_loss=round(entry + (atr * self.atr_stop_mult), 2),
                    target_price=round(entry - (atr * self.atr_tp_mult), 2),
                    confidence_score=min(1.0, round(current.volume / (avg_vol * 2.5), 2)),
                    reason=f"Rejected above {self.lookback_days}d high ({window_high}) | Vol {current.volume/avg_vol:.1f}x | ATR {atr:.2f}",
                )

        return None