"""risk_sizing.py - volatility-adjusted, ATR/beta-aware position sizing for the PSX quant desk.

Provides a single, shared sizing policy that both the liquidity-sweep and the
momentum-rotation engines can call so that high-beta / high-volatility names
receive less capital and the portfolio drawdown is bounded by construction rather
than by hope.

The policy is deliberately stateless and deterministic: same bars → same weight.
It is built for backtests and for a live desk that would otherwise run the same
math on today's tape.

Conventions
-----------
* weight is expressed as a fraction of available equity (0..1), not as a share count.
* risk target is a fraction of equity the position is allowed to lose at the stop
  (a per-position risk budget), which is what makes "risk parity" readable: each
  position is sized so its stop loss costs the same fraction of the book.
* beta and ATR-pct are used as dampeners, never as amplifiers: a wild, high-beta
  name gets smaller, never larger.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from src.core.models import DailyBar  # noqa: E402
from src.quant.sector_rotation import (
    SESSIONS_PER_YEAR,
    atr,
    atr_pct,
    beta_vs_index,
)  # noqa: E402

MONTHS_PER_YEAR = 12

# ---------------------------------------------------------------------------
# Sizing configuration
# ---------------------------------------------------------------------------


@dataclass
class SizingConfig:
    """Volatility-adjusted risk-parity sizing policy.

    * ``target_risk_pct`` — per-position risk budget as % of equity at the stop.
    * ``max_weight_pct`` — hard cap on any single name's weight (concentration guard).
    * ``min_weight_pct`` — floor so a tiny risk budget does not allocate an absurd share count.
    * ``beta_smoothing`` — how much beta can inflate a weight before we clamp it back down.
    * ``atr_dampener`` — multiplicative hit to weight per ATR-pct point above the target.
    * ``sma_stop_days`` — lookback used when we need a trend stop for sizing context.
    """

    target_risk_pct: float = 1.0     # each position can lose ~1% of equity at its stop
    max_weight_pct: float = 15.0     # no single name > 15% of equity
    min_weight_pct: float = 0.5      # no name < 0.5% of equity (avoids dust)
    beta_dampener: float = 0.5       # weight *= (1 / sqrt(beta)) when beta > 1
    atr_dampener: float = 0.25       # per ATR-pct point over target
    atr_target_pct: float = 1.5      # ATR-pct considered "neutral" for sizing
    beta_neutral: float = 1.0        # beta treated as neutral


# ---------------------------------------------------------------------------
# Public sizing API
# ---------------------------------------------------------------------------


def position_weight(
    entry: float,
    stop: float,
    bars: List[DailyBar],
    config: SizingConfig,
    index_bars: Optional[List[DailyBar]] = None,
) -> float:
    """Volatility-adjusted weight for one position, as a fraction of equity.

    Steps
    * raw weight from the risk budget:  risk_budget / (entry - stop)
    * dampen by ATR-pct if the name is more volatile than neutral
    * dampen by beta if the name is more sensitive than the market
    * clamp to [min_weight, max_weight]
    """
    if not bars or entry <= 0 or stop >= entry:
        return 0.0

    risk_budget = config.target_risk_pct / 100.0 * 1.0  # normalized to 1 equity unit
    raw_weight = risk_budget / max(entry - stop, 1e-9)

    # Volatility dampener: ATR-pct above target shrinks the weight.
    a_pct = atr_pct(bars)
    if a_pct > config.atr_target_pct:
        raw_weight *= 1.0 / (1.0 + config.atr_dampener * (a_pct - config.atr_target_pct))

    # Beta dampener: high-beta names get less capital.
    beta = beta_vs_index(bars, index_bars) if index_bars else 1.0
    if beta > config.beta_neutral:
        raw_weight *= 1.0 / math.sqrt(beta) ** config.beta_dampener

    # Concentration + dust floors.
    lo = config.min_weight_pct / 100.0
    hi = config.max_weight_pct / 100.0
    return float(max(lo, min(hi, raw_weight)))


def position_shares(
    entry: float,
    stop: float,
    bars: List[DailyBar],
    equity: float,
    config: SizingConfig,
    index_bars: Optional[List[DailyBar]] = None,
) -> int:
    """Whole-share count sized by the volatility policy (equity × weight / entry)."""
    w = position_weight(entry, stop, bars, config, index_bars)
    if w <= 0 or entry <= 0:
        return 0
    return int(equity * w / entry)


def risk_parity_weights(
    positions: List[Tuple[str, float, float, List[DailyBar], Optional[List[DailyBar]]]],
    equity: float,
    config: SizingConfig,
) -> Dict[str, float]:
    """Equal-risk-budget weights across a candidate set, then normalized.

    Each candidate is (ticker, entry, stop, bars, index_bars). Weights are first
    computed per-position under the risk-parity policy, then normalized so the book
    does not exceed 100% while still respecting each position's volatility scaling
    relative to the others.
    """
    if not positions:
        return {}

    raw: Dict[str, float] = {}
    for ticker, entry, stop, bars, index_bars in positions:
        w = position_weight(entry, stop, bars, config, index_bars)
        if w > 0:
            raw[ticker] = w

    total = sum(raw.values())
    if total <= 0:
        return {}

    # Normalize to the book, but never let the sum exceed 100%.
    scale = min(1.0, 1.0 / total)
    return {t: w * scale for t, w in raw.items()}


# ---------------------------------------------------------------------------
# Diagnostics / reporting helpers
# ---------------------------------------------------------------------------


@dataclass
class SizingDiagnostics:
    ticker: str
    entry: float
    stop: float
    atr_pct: float
    beta: float
    raw_weight: float
    final_weight: float
    shares: int
    risk_pkr: float  # PKR at risk at the stop on the sizing day


def sizing_table(
    ticker: str,
    entry: float,
    stop: float,
    bars: List[DailyBar],
    equity: float,
    config: SizingConfig,
    index_bars: Optional[List[DailyBar]] = None,
) -> SizingDiagnostics:
    """Human-readable row for a single sized position (used by reports / UI)."""
    w = position_weight(entry, stop, bars, config, index_bars)
    shares = int(equity * w / entry) if entry > 0 else 0
    a_pct = atr_pct(bars)
    beta = beta_vs_index(bars, index_bars) if index_bars else 1.0
    raw = (config.target_risk_pct / 100.0) / max(entry - stop, 1e-9)
    return SizingDiagnostics(
        ticker=ticker,
        entry=entry,
        stop=stop,
        atr_pct=round(a_pct, 2),
        beta=round(beta, 2),
        raw_weight=round(raw, 4),
        final_weight=round(w, 4),
        shares=shares,
        risk_pkr=round(equity * w * (entry - stop) / entry, 0),
    )
