"""regime_filter.py - Hurst exponent & market regime detection for the PSX quant desk.

Provides a single, shared regime-reader that both the liquidity-sweep and the
momentum-rotation engines can call so the same tape produces the same regime
classification at every session in a backtest.

Two ideas drive the module:

* The Hurst exponent H tells you whether the recent tape is trending
  (H > 0.5), mean-reverting / choppy (H < 0.5) or close to a random walk
  (H ~= 0.5). We compute it with a rolling variance-ratio style estimator on
  the closing-price series, capped to a finite lookback so an institutional
  backtest stays O(N) rather than O(N^2).

* We expose a lightweight regime gate that lets the desk route capital by market
  state: momentum rotation is favored in trending regimes and mean-reversion /
  liquidity sweeps are favored in choppy regimes. The gate is opt-in and stays
  out of the published baseline until turned on, so the existing metrics stay
  readable.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from src.core.models import DailyBar  # noqa: E402

SESSIONS_PER_YEAR = 252
MONTHS_PER_YEAR = 12

# ---------------------------------------------------------------------------
# Regime configuration
# ---------------------------------------------------------------------------


@dataclass
class RegimeConfig:
    """Hurst / variance-ratio regime settings.

    * ``hurst_lookback_sessions`` — capped lookback used for the rolling H estimate.
    * ``hurst_trend_threshold`` — above this -> TRENDING; below -> CHOppy.
    * ``hurst_neutral_band`` — band around 0.5 treated asRANDOM_WALK.
    * ``regime_gate`` — when True, route signals by regime; otherwise everything passes.
    * ``trending_regime_favors_momentum`` — which strategy the gate prefers when trending.
    """

    hurst_lookback_sessions: int = 126  # ~6 months on daily PSX tape
    hurst_trend_threshold: float = 0.52
    hurst_neutral_band: float = 0.05
    regime_gate: bool = False
    trending_regime_favors_momentum: bool = True


# ---------------------------------------------------------------------------
# Hurst exponent and rolling variance ratio
# ---------------------------------------------------------------------------


def _log_price_series(bars: List[DailyBar]) -> List[float]:
    return [math.log(max(b.close_price, 1e-9)) for b in bars]


def hurst_exponent(bars: List[DailyBar], max_lag: Optional[int] = None) -> float:
    """Estimate the Hurst exponent H from a closing-price series.

    Uses a variance-ratio style slope on log-lag vs log-variance of lagged
    differences:  var(diff(tau)) ~ c * tau^(2H), so 2H is the slope of
    log(var) vs log(tau). We keep it bounded to small lags so the backtest is
    fast and deterministic; the estimate is intentionally approximate, not a
    forensic estimator.
    """
    series = _log_price_series(bars)
    n = len(series)
    if n < 8:
        return 0.5

    max_lag = max_lag or min(32, n // 2)
    if max_lag < 2:
        return 0.5

    xs: List[float] = []
    ys: List[float] = []
    for tau in range(2, max_lag + 1):
        diffs = [series[i] - series[i - tau] for i in range(tau, n)]
        if len(diffs) < 2:
            continue
        mean = sum(diffs) / len(diffs)
        var = sum((d - mean) ** 2 for d in diffs) / len(diffs)
        if var <= 1e-18:
            continue
        xs.append(math.log(tau))
        ys.append(math.log(var))
    if len(xs) < 2:
        return 0.5

    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = sum((x - mx) ** 2 for x in xs)
    if den <= 1e-18:
        return 0.5
    slope = num / den
    h = slope / 2.0
    if not math.isfinite(h):
        return 0.5
    return float(max(0.0, min(1.0, h)))


def rolling_variance_ratio(
    bars: List[DailyBar],
    long_lag: int = 12,
    short_lag: int = 2,
) -> float:
    """Rolling variance ratio VR(s,l) = Var(r_long) / Var(r_short).

    For a pure random walk VR ~= 1. VR < 1 is mean-reverting; VR > 1 is
    trending. This is the quick companion to the Hurst estimate, useful when
    you want a single number per bar without fitting a slope.
    """
    series = _log_price_series(bars)
    n = len(series)
    if n < max(long_lag, short_lag) + 2:
        return 1.0

    def var_lag(lag: int) -> float:
        diffs = [series[i] - series[i - lag] for i in range(lag, n)]
        if len(diffs) < 2:
            return 0.0
        m = sum(diffs) / len(diffs)
        return sum((d - m) ** 2 for d in diffs) / len(diffs)

    v_long = var_lag(long_lag)
    v_short = var_lag(short_lag)
    if v_short <= 1e-18:
        return 1.0
    ratio = v_long / v_short
    if not math.isfinite(ratio):
        return 1.0
    return float(ratio)


def classify_hurst(h: float, cfg: Optional[RegimeConfig] = None) -> str:
    """Turn an H estimate into a human label."""
    cfg = cfg or RegimeConfig()
    if h > cfg.hurst_trend_threshold:
        return "TRENDING"
    if h < cfg.hurst_trend_threshold - cfg.hurst_neutral_band:
        return "CHOPPY"
    return "RANDOM_WALK"


def market_regime_from_tape(
    bars: List[DailyBar],
    cfg: Optional[RegimeConfig] = None,
) -> str:
    """One-regime-per-tape classification from the latest available closes.

    Prefer the Hurst-based label; fall back to the variance-ratio heuristic when
    the estimate is degenerate or neutral.
    """
    cfg = cfg or RegimeConfig()
    lookback = max(2, min(cfg.hurst_lookback_sessions, len(bars) // 2))
    h = hurst_exponent(bars, max_lag=lookback)
    label = classify_hurst(h, cfg)
    if label == "RANDOM_WALK":
        vr = rolling_variance_ratio(bars)
        if vr > 1.08:
            label = "TRENDING"
        elif vr < 0.92:
            label = "CHOPPY"
    elif label == "TRENDING" and h <= cfg.hurst_trend_threshold:
        # borderline trending: let variance ratio nudge it back if it disagrees strongly
        vr = rolling_variance_ratio(bars)
        if vr < 0.92:
            label = "CHOPPY"
    return label


# ---------------------------------------------------------------------------
# Regime Gate for strategy routing
# ---------------------------------------------------------------------------


@dataclass
class RegimeGateState:
    """One line the backtest can write into its payload."""

    regime: str
    hurst_exponent: float
    variance_ratio: float
    momentum_favored: bool  # True if the current regime should favor momentum rotation


def regime_gate_state(
    bars: List[DailyBar],
    cfg: Optional[RegimeConfig] = None,
) -> RegimeGateState:
    """Current regime classification + which strategy the gate prefers now."""
    cfg = cfg or RegimeConfig()
    h = hurst_exponent(bars, max_lag=min(cfg.hurst_lookback_sessions, len(bars) // 2 or 1))
    vr = rolling_variance_ratio(bars)
    regime = classify_hurst(h, cfg)
    if regime == "RANDOM_WALK":
        regime = "TRENDING" if vr > 1.0 else "CHOPPY"
    momentum_favored = (regime == "TRENDING") if cfg.trending_regime_favors_momentum else (regime != "TRENDING")
    if not cfg.regime_gate:
        momentum_favored = True
    return RegimeGateState(
        regime=regime,
        hurst_exponent=round(h, 3),
        variance_ratio=round(vr, 3),
        momentum_favored=momentum_favored,
    )


def should_seek_momentum(
    bars: List[DailyBar],
    cfg: Optional[RegimeConfig] = None,
) -> bool:
    """True when the regime gate says momentum rotation is the favored play now."""
    return regime_gate_state(bars, cfg).momentum_favored


def should_seek_mean_reversion(
    bars: List[DailyBar],
    cfg: Optional[RegimeConfig] = None,
) -> bool:
    """True when the regime gate says mean-reversion / liquidity sweeps are favored now."""
    return not should_seek_momentum(bars, cfg)
