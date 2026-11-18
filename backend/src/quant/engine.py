from typing import List, Optional
from src.core.models import DailyBar, TradeSignal


class LiquidityQuantEngine:
    """
    Stateless, deterministic quant engine with ATR volatility sizing and Close Location Value (CLV).

    Institutional confirmation layers sit on top of the raw sweep:
      * trend filter     - longs only above a rising medium-term average (no macro downtrend dip-buys)
      * liquidity filter - 15d turnover floor plus RVOL expansion and a volume z-score
      * volatility stop  - ATR-multiple risk so ordinary noise does not shake out a valid position
    """

    def __init__(
        self,
        lookback_days: int = 5,
        min_avg_volume: int = 50_000,
        atr_stop_mult: float = 2.0,
        atr_tp_mult: float = 3.2,
        trend_ma_days: int = 50,
        trend_slope_bars: int = 10,
        min_rvol: float = 1.5,
        min_vol_z: float = 1.0,
        trend_reference_bars: int = 1,
    ):
        self.lookback_days = lookback_days
        self.min_avg_volume = min_avg_volume
        self.atr_stop_mult = atr_stop_mult
        self.atr_tp_mult = atr_tp_mult
        self.trend_ma_days = trend_ma_days
        self.trend_slope_bars = trend_slope_bars
        self.min_rvol = min_rvol
        self.min_vol_z = min_vol_z
        self.trend_reference_bars = max(1, trend_reference_bars)

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

    def trend_average(self, bars: List[DailyBar]) -> Optional[float]:
        """Simple moving average of closes ending at the current bar."""
        if self.trend_ma_days <= 0 or len(bars) < self.trend_ma_days:
            return None
        window = bars[-self.trend_ma_days :]
        return sum(b.close_price for b in window) / len(window)

    def trend_confirmed(self, bars: List[DailyBar]) -> bool:
        """Regime is read on the tape entering the signal, not on the dislocated trigger bar.

        The sweep bar itself closes well under its average by construction, so testing it
        would reject every setup. Instead the highest close of the last
        ``trend_reference_bars`` sessions must sit above a medium-term average that is not
        falling: a stock flushed out of an intact uptrend still qualifies, a name that has
        been trading below its average all along does not.
        """
        if self.trend_ma_days <= 0:
            return True
        if len(bars) < 2:
            return False
        prior = bars[:-1]
        if len(prior) < self.trend_ma_days + self.trend_slope_bars:
            return False
        sma = sum(b.close_price for b in prior[-self.trend_ma_days :]) / self.trend_ma_days
        reference_close = max(b.close_price for b in prior[-self.trend_reference_bars :])
        if reference_close <= sma:
            return False
        if self.trend_slope_bars > 0:
            earlier = prior[: -self.trend_slope_bars]
            prior_sma = sum(b.close_price for b in earlier[-self.trend_ma_days :]) / self.trend_ma_days
            if sma <= prior_sma:  # flat or rolling over: no longs
                return False
        return True

    def required_history(self) -> int:
        return max(self.lookback_days + 1, self.trend_ma_days + self.trend_slope_bars + 1)

    def evaluate_ticker(self, bars: List[DailyBar]) -> Optional[TradeSignal]:
        if self.trend_ma_days > 0 and len(bars) < self.required_history():
            return None
        if len(bars) <= self.lookback_days:
            return None

        window = bars[-(self.lookback_days + 1) : -1]
        current = bars[-1]

        avg_vol = sum(b.volume for b in window) / self.lookback_days
        if avg_vol < self.min_avg_volume:
            return None

        # Volume expansion: institutional accumulation leaves a footprint, retail chop does not.
        rvol = current.volume / avg_vol if avg_vol else 0.0
        if rvol < self.min_rvol:
            return None
        vol_z = self.volume_zscore(window, current.volume)
        if vol_z < self.min_vol_z:
            return None

        candle_range = current.high_price - current.low_price
        if candle_range <= 0:
            return None

        clv = (current.close_price - current.low_price) / candle_range
        window_low = min(b.low_price for b in window)
        window_high = max(b.high_price for b in window)
        atr = max(self.compute_atr(bars[:-1]), current.close_price * 0.015)
        sma = self.trend_average(bars[:-1])
        stretch = ((current.close_price / sma) - 1) * 100 if sma else 0.0
        tape = f"RVOL {rvol:.1f}x | Z {vol_z:.1f}"
        if sma:
            tape += f" | Trend +{stretch:.1f}%"

        # Bullish Liquidity Sweep: sweeps 15d low, reclaims above it, closes in upper 40% of range
        if current.low_price < window_low and current.close_price > window_low:
            if clv >= 0.60 and self.trend_confirmed(bars):
                entry = current.close_price
                return TradeSignal(
                    ticker=current.ticker,
                    signal_date=current.trade_date,
                    side="BUY",
                    entry_price=round(entry, 2),
                    stop_loss=round(entry - (atr * self.atr_stop_mult), 2),
                    target_price=round(entry + (atr * self.atr_tp_mult), 2),
                    confidence_score=min(1.0, round(current.volume / (avg_vol * 3.0), 2)),
                    reason=f"Swept {self.lookback_days}d low ({window_low}) | {tape} | ATR {atr:.2f}",
                )

        # Bearish Bull-Trap: pierces 15d high, closes back below it in lower 40% of range
        if current.high_price > window_high and current.close_price < window_high:
            if clv <= 0.40:
                entry = current.close_price
                return TradeSignal(
                    ticker=current.ticker,
                    signal_date=current.trade_date,
                    side="SHORT",
                    entry_price=round(entry, 2),
                    stop_loss=round(entry + (atr * self.atr_stop_mult), 2),
                    target_price=round(entry - (atr * self.atr_tp_mult), 2),
                    confidence_score=min(1.0, round(current.volume / (avg_vol * 3.0), 2)),
                    reason=f"Rejected above {self.lookback_days}d high ({window_high}) | {tape} | ATR {atr:.2f}",
                )

        return None

    @staticmethod
    def volume_zscore(window: List[DailyBar], volume: int) -> float:
        volumes = [b.volume for b in window]
        mean = sum(volumes) / len(volumes)
        variance = sum((v - mean) ** 2 for v in volumes) / len(volumes)
        sd = variance**0.5
        return (volume - mean) / sd if sd > 0 else 0.0
