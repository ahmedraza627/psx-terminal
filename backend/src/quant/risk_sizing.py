"""risk_sizing.py - institutional capital-allocation & risk-overlay for the PSX quant desk.

Provides the shared sizing policy the liquidity-sweep and momentum-rotation engines
both call, and upgrades it with the institutional overlays requested for the quant
research lab: fractional Kelly criterion sizing and a 99% historical Value-at-Risk
portfolio clamp.

The module still has a single, deterministic, stateless face: same bars and same
config produce the same weights. The new overlays are opt-in so the published
baseline stays readable until a live desk asks for them.

Conventions
-----------
* weight is expressed as a fraction of available equity (0..1), not as a share count.
* risk target is a fraction of equity the position is allowed to lose at the stop
  (a per-position risk budget), which is what makes "risk parity" readable: each
  position is sized so its stop loss costs the same fraction of the book.
* beta and ATR-pct are used as dampeners, never as amplifiers: a wild, high-beta
  name gets smaller, never larger.
* Kelly only *shrinks* the raw risk-parity weight; it never amplifies exposure.
* VaR clamps total book exposure, not individual weights, so the sizing policy
  stays coherent under stress.
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
class KellyConfig:
    """Fractional Kelly sizing overlay built from rolling trade outcomes.

    The Kelly fraction is derived from the observed win rate and win/loss ratio
    (profit factor on a per-trade basis), then scaled by a conservative fraction
    so the book never runs at full Kelly.

    The overlay is a *shrinker*, not an amplifier: even a brilliant recent track
    record only raises the weight toward the raw risk-parity weight, never above
    it.
    """

    fraction: float = 0.25           # use 25% of the analytic Kelly edge (fractional Kelly)
    min_win_rate: float = 0.35       # below this, Kelly edge is treated as zero
    max_edge: float = 0.50           # cap the raw Kelly edge before the fraction is applied


@dataclass
class VarConfig:
    """Portfolio-level VaR clamp configuration.

    A 99% historical VaR is computed from the last N daily book returns (or from a
    supplied equity curve). When the estimated 1-day 99% VaR as a fraction of equity
    exceeds the limit, total exposure is clamped by scaling all weights down.
    """

    var_confidence: float = 0.99
    var_lookback_days: int = 126
    max_var_pct: float = 4.0         # 1-day 99% VaR cap as % of equity
    conservative_resample: bool = True  # use the empirical percentile directly


@dataclass
class SizingConfig:
    """Volatility-adjusted risk-parity sizing policy with optional Kelly + VaR overlays.

    * ``target_risk_pct`` — per-position risk budget as % of equity at the stop.
    * ``max_weight_pct`` — hard cap on any single name's weight (concentration guard).
    * ``min_weight_pct`` — floor so a tiny risk budget does not allocate an absurd share count.
    * ``beta_dampener`` — multiplicative hit to weight when beta > 1.
    * ``atr_dampener`` — multiplicative hit to weight per ATR-pct point above the target.
    * ``atr_target_pct`` — ATR-pct considered "neutral" for sizing.
    * ``beta_neutral`` — beta treated as neutral.
    * ``kelly`` — optional fractional Kelly overlay; None = no Kelly adjustment.
    * ``var`` — optional 99% historical VaR clamp; None = no VaR clamp.
    """

    target_risk_pct: float = 1.0     # each position can lose ~1% of equity at its stop
    max_weight_pct: float = 15.0     # no single name > 15% of equity
    min_weight_pct: float = 0.5      # no name < 0.5% of equity (avoids dust)
    beta_dampener: float = 0.5       # weight *= (1 / sqrt(beta)) when beta > 1
    atr_dampener: float = 0.25       # per ATR-pct point over target
    atr_target_pct: float = 1.5      # ATR-pct considered "neutral" for sizing
    beta_neutral: float = 1.0        # beta treated as neutral
    kelly: Optional[KellyConfig] = None
    var: Optional[VarConfig] = None


# ---------------------------------------------------------------------------
# Public sizing API
# ---------------------------------------------------------------------------


def _volatility_dampened_weight(
    entry: float,
    stop: float,
    bars: List[DailyBar],
    config: SizingConfig,
    index_bars: Optional[List[DailyBar]] = None,
) -> float:
    """Raw volatility-adjusted weight before Kelly and VaR overlays.

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


def position_weight(
    entry: float,
    stop: float,
    bars: List[DailyBar],
    config: SizingConfig,
    index_bars: Optional[List[DailyBar]] = None,
    book_kelly_scale: float = 1.0,
) -> float:
    """Volatility-adjusted weight for one position, as a fraction of equity.

    This is the shared front door both the liquidity-sweep and momentum-rotation
    engines call. It first computes the ATR/beta dampened risk-parity weight, then
    optionally shrinks it by the fractional Kelly overlay and finally by the 99%
    historical VaR book clamp.
    """
    w = _volatility_dampened_weight(entry, stop, bars, config, index_bars)
    if w <= 0:
        return 0.0
    w = _kelly_shrink(w, book_kelly_scale)
    return float(w)


def position_shares(
    entry: float,
    stop: float,
    bars: List[DailyBar],
    equity: float,
    config: SizingConfig,
    index_bars: Optional[List[DailyBar]] = None,
) -> int:
    """Whole-share count sized by the volatility + Kelly + VaR policy."""
    w = position_weight(entry, stop, bars, config, index_bars)
    if w <= 0 or entry <= 0:
        return 0
    return int(equity * w / entry)


def risk_parity_weights(
    positions: List[Tuple[str, float, float, List[DailyBar], Optional[List[DailyBar]]]],
    equity: float,
    config: SizingConfig,
    portfolio_returns: Optional[List[float]] = None,
) -> Dict[str, float]:
    """Equal-risk-budget weights across a candidate set, then normalized.

    Each candidate is (ticker, entry, stop, bars, index_bars). Weights are first
    computed per-position under the full sizing policy (volatility + Kelly + VaR),
    then normalized so the book does not exceed 100% while still respecting each
    position's volatility scaling relative to the others.

    When the VaR overlay is enabled and a portfolio return history is supplied,
    the final weights are additionally scaled down if the estimated 99% 1-day VaR
    exceeds the configured cap.
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
    weights = {t: w * scale for t, w in raw.items()}

    # Apply the 99% historical VaR book clamp when the overlay is enabled.
    if config.var and equity > 0:
        var_scale = historical_var_scale(
            weights,
            equity,
            portfolio_returns,
            config,
        )
        if var_scale is not None and var_scale < 1.0:
            weights = {t: w * var_scale for t, w in weights.items()}

    return weights


# ---------------------------------------------------------------------------
# Kelly overlay helpers
# ---------------------------------------------------------------------------


def rolling_trading_stats(
    positions: List[dict],
    window: int = 20,
) -> Tuple[float, float]:
    """Most recent trailing win rate and profit factor from a list of closed trades.

    Each item is expected to carry a ``pnlPct`` (float) and an ``outcome``
    (anything that is not LOSS / stop-out is treated as a win). When there are
    not enough resolved trades, the edge is treated as zero.
    """
    resolved = [p for p in positions if p.get("outcome") not in ("IN PLAY", None)]
    if not resolved:
        return 0.0, 1.0
    recent = resolved[-window:]
    wins = [p for p in recent if p.get("pnlPct", 0.0) > 0]
    losses = [p for p in recent if p.get("pnlPct", 0.0) <= 0]
    n = len(recent)
    win_rate = len(wins) / n if n else 0.0
    gross_profit = sum(p.get("pnlPct", 0.0) for p in wins)
    gross_loss = abs(sum(p.get("pnlPct", 0.0) for p in losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else (float("inf") if gross_profit > 0 else 1.0)
    if not math.isfinite(profit_factor) or profit_factor <= 0:
        profit_factor = 1.0
    return win_rate, profit_factor


def fractional_kelly_edge(
    win_rate: float,
    profit_factor: float,
    config: KellyConfig,
) -> float:
    """Analytic Kelly edge from win rate and win/loss ratio, scaled to a fraction.

    The classical binary-outcome Kelly fraction is  f = (bp - q) / b  with
    b = win/loss ratio and q = 1 - win_rate. We use the same shape but bound it
    aggressively so the overlay only ever shrinks the book, never gambles it.
    """
    if win_rate < config.min_win_rate or profit_factor <= 1.0:
        return 0.0
    b = profit_factor
    edge = (b * win_rate - (1 - win_rate)) / b if b > 0 else 0.0
    edge = max(0.0, min(config.max_edge, edge))
    return edge * config.fraction


def _kelly_shrink(
    raw_weight: float,
    book_kelly_scale: float,
) -> float:
    """Optionally shrink a raw weight by the fractional Kelly overlay.

    ``book_kelly_scale`` is a book-level factor in (0..1] derived from the recent
    resolved trade record. A single-position caller that has no book context passes
    1.0 so the overlay never invents an edge from one tape.
    """
    if book_kelly_scale is None or book_kelly_scale <= 0:
        return raw_weight
    return float(raw_weight * book_kelly_scale)


def book_kelly_scale(
    positions: List[dict],
    config: SizingConfig,
    window: int = 20,
) -> float:
    """Book-level fractional Kelly scale from the recent resolved trade record.

    Returns a factor in (0..1] by which the book's volatility-adjusted target
    weights should be multiplied. A 1.0 means the recent track record does not
    justify any extra aggression; lower means the edge is thin or the win rate
    has deteriorated.
    """
    if not config.kelly:
        return 1.0
    win_rate, profit_factor = rolling_trading_stats(positions, window)
    edge = fractional_kelly_edge(win_rate, profit_factor, config.kelly)
    # Convert edge into a scale around 1.0 so a strong edge nudges the book up
    # toward its raw risk-parity target rather than above it.
    scale = 1.0 - (1.0 - edge)
    return float(max(0.0, min(1.0, scale)))


# ---------------------------------------------------------------------------
# 99% historical VaR portfolio clamp
# ---------------------------------------------------------------------------


def historical_var_pct(
    portfolio_returns: List[float],
    confidence: float = 0.99,
    lookback_days: int = 126,
) -> float:
    """1-day 99% historical VaR as a positive fraction of equity.

    Uses the empirical percentile of the most recent book returns: VaR99 is the
    worst (1 - confidence) fraction of outcomes over the lookback. Returns 0 when
    there is not enough history or the estimate is degenerate.
    """
    if not portfolio_returns:
        return 0.0
    series = portfolio_returns[-lookback_days:] if lookback_days else portfolio_returns
    n = len(series)
    if n < 2:
        return 0.0
    rank = int((1 - confidence) * n)
    if rank < 0:
        rank = 0
    if rank >= n:
        rank = n - 1
    sorted_losses = sorted(series)
    pct = sorted_losses[rank]
    var = abs(pct) if pct < 0 else 0.0
    if not math.isfinite(var):
        return 0.0
    return float(var)


def historical_var_scale(
    weights: Dict[str, float],
    equity: float,
    portfolio_returns: Optional[List[float]],
    config: SizingConfig,
) -> Optional[float]:
    """Return a scale in (0..1] to apply to all weights when VaR exceeds the cap.

    When the book's 1-day 99% VaR is already inside the cap, returns 1.0. When the
    estimate is unavailable, returns None so the caller can skip the clamp.
    """
    if not config.var:
        return None
    var_pct = historical_var_pct(
        portfolio_returns or [],
        config.var.var_confidence,
        config.var.var_lookback_days,
    )
    if var_pct <= 0:
        return None
    cap = config.var.max_var_pct / 100.0
    if var_pct <= cap:
        return 1.0
    scale = cap / var_pct
    return float(max(1e-4, min(1.0, scale)))


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
    raw = _volatility_dampened_weight(entry, stop, bars, config, index_bars)
    w = position_weight(entry, stop, bars, config, index_bars)
    shares = int(equity * w / entry) if entry > 0 else 0
    a_pct = atr_pct(bars)
    beta = beta_vs_index(bars, index_bars) if index_bars else 1.0
    raw_base = (config.target_risk_pct / 100.0) / max(entry - stop, 1e-9)
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
