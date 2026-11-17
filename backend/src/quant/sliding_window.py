from collections import deque
from typing import Deque, Tuple


class MonotonicWindowTracker:
    """
    Maintains rolling window minimum (lows), maximum (highs), and sum (volume)
    in O(1) amortized time per bar using monotonic deques.
    """

    def __init__(self, window_size: int):
        if window_size <= 0:
            raise ValueError("window_size must be positive")
        self.window_size = window_size
        self.index = 0
        self._min_dq: Deque[Tuple[int, float]] = deque()  # (idx, low_price) increasing
        self._max_dq: Deque[Tuple[int, float]] = deque()  # (idx, high_price) decreasing
        self._vol_q: Deque[int] = deque()
        self._vol_sum: int = 0

    def push(self, low: float, high: float, volume: int) -> None:
        cutoff = self.index - self.window_size

        # Evict expired elements from front
        while self._min_dq and self._min_dq[0][0] <= cutoff:
            self._min_dq.popleft()
        while self._max_dq and self._max_dq[0][0] <= cutoff:
            self._max_dq.popleft()

        # Maintain monotonic increasing deque for min
        while self._min_dq and self._min_dq[-1][1] >= low:
            self._min_dq.pop()
        self._min_dq.append((self.index, low))

        # Maintain monotonic decreasing deque for max
        while self._max_dq and self._max_dq[-1][1] <= high:
            self._max_dq.pop()
        self._max_dq.append((self.index, high))

        # Rolling volume sum in O(1)
        if len(self._vol_q) == self.window_size:
            self._vol_sum -= self._vol_q.popleft()
        self._vol_q.append(volume)
        self._vol_sum += volume

        self.index += 1

    @property
    def is_full(self) -> bool:
        return len(self._vol_q) == self.window_size

    @property
    def min_low(self) -> float:
        return self._min_dq[0][1]

    @property
    def max_high(self) -> float:
        return self._max_dq[0][1]

    @property
    def avg_volume(self) -> float:
        return self._vol_sum / len(self._vol_q) if self._vol_q else 0.0