from datetime import date, timedelta
from src.core.models import DailyBar
from src.quant.sliding_window import MonotonicWindowTracker
from src.quant.backtester import LinearBacktester


def test_monotonic_window_evicts_expired_extremes():
    tracker = MonotonicWindowTracker(window_size=3)
    tracker.push(low=10.0, high=50.0, volume=100)  # index 0 (extreme high 50)
    tracker.push(low=12.0, high=20.0, volume=100)  # index 1
    tracker.push(low=11.0, high=25.0, volume=100)  # index 2
    assert tracker.is_full
    assert tracker.max_high == 50.0
    assert tracker.min_low == 10.0

    # Push index 3 -> index 0 (low=10, high=50) must be evicted in O(1)
    tracker.push(low=15.0, high=30.0, volume=100)
    assert tracker.max_high == 30.0
    assert tracker.min_low == 11.0


def test_linear_backtester_resolves_winning_buy():
    start = date(2026, 10, 1)
    bars = []
    # 5 quiet days around 100 (low=98)
    for i in range(5):
        bars.append(DailyBar(
            ticker="LUCK", trade_date=start + timedelta(days=i),
            open_price=100, high_price=102, low_price=98, close_price=100, volume=100_000
        ))
    # Day 6: Liquidity sweep below 98 -> closes at 100 on 2x volume -> Target = 112.0
    bars.append(DailyBar(
        ticker="LUCK", trade_date=start + timedelta(days=5),
        open_price=99, high_price=101, low_price=96, close_price=100, volume=200_000
    ))
    # Day 7: Rallies to 113 -> hits Target
    bars.append(DailyBar(
        ticker="LUCK", trade_date=start + timedelta(days=6),
        open_price=101, high_price=113, low_price=100, close_price=112, volume=150_000
    ))

    report = LinearBacktester(lookback_days=5, min_avg_volume=50_000).run({"LUCK": bars})
    assert report.total_signals == 1
    assert report.wins == 1
    assert report.trades[0].outcome == "WIN"