"""stat_arb.py - Engle-Granger co-integration & rolling Z-score spread engine for PSX.

Adds a market-neutral statistical-arbitrage layer on top of the desk's directional
models. The module pairs historically correlated PSX sector names (Energy duos,
Fertilizer duos, etc.), estimates a stationary spread between them via an
Engle-Granger co-integration regression, and emits mean-reversion signals when the
rolling spread breaches +/- 2.0 to 2.5 sigma.

The math is deliberately offline-only and state-free: given the same bar store you
get the same pairs, the same hedge ratios and the same spread signals. There is no
external feed, no messaging dependency, and no position-taking: this module reports
the signals; the backtest engines decide what to do with them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional, Tuple

from src.core.models import DailyBar  # noqa: E402

SESSIONS_PER_YEAR = 252
MONTHS_PER_YEAR = 12
DEFAULT_ENTRY_Z = 2.0
DEFAULT_EXIT_Z = 0.5
DEFAULT_OUTLIER_CLAMP = 3.0


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class StatArbConfig:
    """Spread-engine tuning knobs.

    * ``hedge_window`` — lookback used to fit the cointegrating regression.
    * ``spread_lookback`` — rolling window used to compute the spread's own std.
    * ``entry_z`` — abs(Z) at which a new spread signal is emitted.
    * ``exit_z`` — abs(Z) at which an open spread is considered mean-regressed.
    * ``min_bars`` — minimum tape length before a pair is considered tradable.
    * ``outlier_clamp`` — z-scores outside +/- this are clamped, so a single gap
      does not blow up the whole rolling stats.
    """

    hedge_window: int = 63
    spread_lookback: int = 20
    entry_z: float = DEFAULT_ENTRY_Z
    exit_z: float = DEFAULT_EXIT_Z
    min_bars: int = 126
    outlier_clamp: float = DEFAULT_OUTLIER_CLAMP
    min_cointegration_tau: Optional[float] = None  # ADF-style tau threshold, optional


# ---------------------------------------------------------------------------
# OLS helpers (residual = spread)
# ---------------------------------------------------------------------------


def _ols_slope_intercept(
    xs: List[float], ys: List[float]
) -> Tuple[float, float, float, float]:
    """Fit y = alpha + beta * x. Returns (alpha, beta, xvar, yvar)."""
    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / n
    var_x = sum((x - mean_x) ** 2 for x in xs) / n
    if var_x <= 1e-18:
        return 0.0, 0.0, var_x, 0.0
    beta = cov / var_x
    alpha = mean_y - beta * mean_x
    var_y = sum((y - mean_y) ** 2 for y in ys) / n
    return alpha, beta, var_x, var_y


def _resid_std(
    xs: List[float],
    ys: List[float],
    alpha: float,
    beta: float,
    clamp: float = DEFAULT_OUTLIER_CLAMP,
) -> float:
    resids = [y - (alpha + beta * x) for x, y in zip(xs, ys)]
    if not resids:
        return 0.0
    if clamp:
        resids = [min(max(r, -clamp), clamp) for r in resids]
    mean = sum(resids) / len(resids)
    var = sum((r - mean) ** 2 for r in resids) / len(resids)
    return math.sqrt(var)


def returns_over(bars: List[DailyBar]) -> List[float]:
    return [
        bars[i].close_price / bars[i - 1].close_price - 1
        for i in range(1, len(bars))
        if bars[i - 1].close_price > 0
    ]


# ---------------------------------------------------------------------------
# Cointegration / spread pair
# ---------------------------------------------------------------------------


@dataclass
class SpreadPair:
    leg_a: str
    leg_b: str
    hedge_ratio: float  # beta in leg_a ~ alpha + beta * leg_b
    intercept: float
    spread_mean: float
    spread_std: float
    cointegration_tau: Optional[float]  # ADF-style regression test statistic (tau)


def pair_candidates(sectors: Dict[str, List[str]]) -> List[Tuple[str, str]]:
    """Construct same-sector candidate pairs for screening.

    We restrict to same-sector pairs so the hedge has a structural reason to be
    stationary. The caller still screens them for stationarity / correlation before
    trading.
    """
    out: List[Tuple[str, str]] = []
    for members in sectors.values():
        if len(members) < 2:
            continue
        members = sorted(members)
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                a, b = members[i], members[j]
                if a == b:
                    continue
                out.append((a, b))
    return out


def hedge_ratio(
    leg_a_bars: List[DailyBar],
    leg_b_bars: List[DailyBar],
    window: int = 63,
) -> Tuple[float, float, float, float]:
    """Engle-Granger style hedge ratio: regress log leg_a on log leg_b over a trailing window.

    Returns (alpha, beta, leg_a_var, leg_b_var). When the window is too short or
    degenerate, beta falls back to 1.0 so the pair still has a not-too-crazy spread.
    """
    if len(leg_a_bars) < window + 1 or len(leg_b_bars) < window + 1:
        return 0.0, 1.0, 0.0, 0.0
    a = leg_a_bars[-window:]
    b = leg_b_bars[-window:]
    xs = [math.log(max(bk.close_price, 1e-9)) for bk in b]
    ys = [math.log(max(ak.close_price, 1e-9)) for ak in a]
    if len(xs) < 2:
        return 0.0, 1.0, 0.0, 0.0
    alpha, beta, var_x, var_y = _ols_slope_intercept(xs, ys)
    if not math.isfinite(beta) or beta <= 0:
        beta = 1.0
    return alpha, beta, var_x, var_y


def cointegration_tau_stat(
    leg_a_bars: List[DailyBar],
    leg_b_bars: List[DailyBar],
    window: int = 63,
) -> Optional[float]:
    """Simple Engle-Granger style tau statistic on the spread residuals.

    Fit leg_a ~ alpha + beta * leg_b over the trailing window, compute the spread
    residuals, then run a basic regression of the residual on its own lagged value.
    The t-stat on the lag coefficient is reported as a stationarity indicator: more
    negative is more mean-reverting. This is a lightweight analytic proxy for an ADF
    test, not a replacement for a library implementation.
    """
    if len(leg_a_bars) < window + 1 or len(leg_b_bars) < window + 1:
        return None
    a = leg_a_bars[-window:]
    b = leg_b_bars[-window:]
    xs = [math.log(max(bk.close_price, 1e-9)) for bk in b]
    ys = [math.log(max(ak.close_price, 1e-9)) for ak in a]
    if len(xs) < 2:
        return None
    alpha, beta, _, _ = _ols_slope_intercept(xs, ys)
    if not math.isfinite(beta) or beta <= 0:
        return None
    resids = [y - (alpha + beta * x) for x, y in zip(xs, ys)]
    if len(resids) < 3:
        return None
    lagged = resids[1:]
    curr = resids[:-1]
    if len(curr) < 2:
        return None
    _, _, _, _ = _ols_slope_intercept(curr, lagged)
    # Re-fit properly:
    m_x = sum(curr) / len(curr)
    m_y = sum(lagged) / len(lagged)
    cov = sum((x - m_x) * (y - m_y) for x, y in zip(curr, lagged)) / len(curr)
    var_x = sum((x - m_x) ** 2 for x in curr) / len(curr)
    if var_x <= 1e-18 or cov == 0.0:
        return None
    gamma = cov / var_x
    resid_gamma = [y - (m_y + gamma * (x - m_x)) for x, y in zip(curr, lagged)]
    mean_g = sum(resid_gamma) / len(resid_gamma)
    var_g = sum((r - mean_g) ** 2 for r in resid_gamma) / len(resid_gamma)
    if var_g <= 1e-18:
        return None
    se = math.sqrt(var_g / len(curr) / var_x) if var_x > 0 else None
    if se is None or se <= 1e-18:
        return None
    tau = (gamma - 0.0) / se
    if not math.isfinite(tau):
        return None
    return float(tau)


def fitted_spread_at(
    leg_a_close: float,
    leg_b_close: float,
    alpha: float,
    beta: float,
) -> float:
    """Residual of leg_a around the cointegrating line, at a given close pair."""
    la = math.log(max(leg_a_close, 1e-9))
    lb = math.log(max(leg_b_close, 1e-9))
    return la - (alpha + beta * lb)


# ---------------------------------------------------------------------------
# Rolling Z-score on the spread
# ---------------------------------------------------------------------------


@dataclass
class SpreadSignal:
    leg_a: str
    leg_b: str
    signal_date: date
    direction_for_a: str  # LONG_A_SHORT_B or SHORT_A_LONG_B
    z_score: float
    spread: float
    spread_mean: float
    spread_std: float
    entry_side: str  # ENTRY or EXIT
    confidence: float


def rolling_spread_stats(
    leg_a_bars: List[DailyBar],
    leg_b_bars: List[DailyBar],
    alpha: float,
    beta: float,
    lookback: int = 20,
    clamp: float = DEFAULT_OUTLIER_CLAMP,
) -> Tuple[float, float]:
    """Most recent spread and its trailing rolling std.

    Spread is defined as leg_a - hedge*leg_b in log terms, so it is the
    Engle-Granger residual. Returns (spread_now, spread_std). If the rolling
    window has no variation, std is 0.
    """
    n = min(len(leg_a_bars), len(leg_b_bars))
    if n < lookback + 1:
        return 0.0, 0.0
    start = n - lookback
    recent_a = leg_a_bars[start:]
    recent_b = leg_b_bars[start:]
    spreads = [
        fitted_spread_at(a.close_price, b.close_price, alpha, beta)
        for a, b in zip(recent_a, recent_b)
    ]
    now = spreads[-1] if spreads else 0.0
    if clamp:
        spreads = [min(max(s, -clamp), clamp) for s in spreads]
    mean = sum(spreads) / len(spreads)
    var = sum((s - mean) ** 2 for s in spreads) / len(spreads)
    std = math.sqrt(var) if var > 0 else 0.0
    return float(now), float(std)


def spread_z_score(
    spread_now: float,
    spread_mean: float,
    spread_std: float,
    clamp: float = DEFAULT_OUTLIER_CLAMP,
) -> float:
    """Z-score of the current spread around its rolling mean."""
    if spread_std <= 1e-18:
        return 0.0
    z = (spread_now - spread_mean) / spread_std
    if not math.isfinite(z):
        return 0.0
    return float(min(max(z, -clamp), clamp))


# ---------------------------------------------------------------------------
# Screening a candidate pair
# ---------------------------------------------------------------------------


def screen_pair(
    leg_a_bars: List[DailyBar],
    leg_b_bars: List[DailyBar],
    cfg: Optional[StatArbConfig] = None,
) -> Optional[SpreadPair]:
    """Return a tradable SpreadPair only when the spread looks reasonably stationary.

    We require:
    * both legs have enough history
    * a finite, positive hedge ratio
    * a non-degenerate rolling spread std
    * optionally, a cointegration tau below a threshold
    """
    cfg = cfg or StatArbConfig()
    if len(leg_a_bars) < cfg.min_bars or len(leg_b_bars) < cfg.min_bars:
        return None
    alpha, beta, _, _ = hedge_ratio(leg_a_bars, leg_b_bars, cfg.hedge_window)
    if not math.isfinite(beta) or beta <= 0:
        return None
    spread_now, spread_std = rolling_spread_stats(
        leg_a_bars, leg_b_bars, alpha, beta, cfg.spread_lookback, cfg.outlier_clamp
    )
    if spread_std <= 1e-18:
        return None
    tau = cointegration_tau_stat(leg_a_bars, leg_b_bars, cfg.hedge_window)
    if cfg.min_cointegration_tau is not None:
        if tau is None or tau >= cfg.min_cointegration_tau:
            return None
    return SpreadPair(
        leg_a=leg_a_bars[-1].ticker,
        leg_b=leg_b_bars[-1].ticker,
        hedge_ratio=round(beta, 4),
        intercept=round(alpha, 4),
        spread_mean=round(spread_now, 4),
        spread_std=round(spread_std, 4),
        cointegration_tau=round(tau, 3) if tau is not None else None,
    )


# ---------------------------------------------------------------------------
# Signal generation across a pair history
# ---------------------------------------------------------------------------


def spread_signals_for_pair(
    leg_a_bars: List[DailyBar],
    leg_b_bars: List[DailyBar],
    cfg: Optional[StatArbConfig] = None,
) -> List[SpreadSignal]:
    """Walk the pair's shared calendar and emit mean-reversion spread signals.

    A new entry is emitted when the rolling |z| crosses above entry_z; an exit is
    emitted when an open spread regresses inside exit_z. Direction is expressed from
    the perspective of leg_a: LONG_A_SHORT_B when z > 0 (A rich vs B), the reverse
    when z < 0.
    """
    cfg = cfg or StatArbConfig()
    n = min(len(leg_a_bars), len(leg_b_bars))
    if n < cfg.min_bars:
        return []
    signals: List[SpreadSignal] = []
    open_side: Optional[str] = None
    for i in range(cfg.min_bars, n):
        a = leg_a_bars[i]
        b = leg_b_bars[i]
        if a.trade_date != b.trade_date:
            continue
        alpha, beta, _, _ = hedge_ratio(leg_a_bars[: i + 1], leg_b_bars[: i + 1], cfg.hedge_window)
        if not math.isfinite(beta) or beta <= 0:
            continue
        spread_now, spread_std = rolling_spread_stats(
            leg_a_bars[: i + 1], leg_b_bars[: i + 1], alpha, beta, cfg.spread_lookback, cfg.outlier_clamp
        )
        if spread_std > 1e-18:
            spread_mean = spread_now
            z = spread_z_score(spread_now, spread_mean, spread_std, cfg.outlier_clamp)
        else:
            spread_mean = spread_now
            z = 0.0
        side = "LONG_A_SHORT_B" if z > 0 else "SHORT_A_LONG_B"
        if abs(z) >= cfg.entry_z and open_side is None:
            open_side = side
            signals.append(
                SpreadSignal(
                    leg_a=a.ticker,
                    leg_b=b.ticker,
                    signal_date=a.trade_date,
                    direction_for_a=side,
                    z_score=round(z, 3),
                    spread=round(spread_now, 4),
                    spread_mean=round(spread_now, 4),
                    spread_std=round(spread_std, 4),
                    entry_side="ENTRY",
                    confidence=round(min(1.0, abs(z) / 3.0), 3),
                )
            )
        elif open_side is not None and abs(z) <= cfg.exit_z:
            signals.append(
                SpreadSignal(
                    leg_a=a.ticker,
                    leg_b=b.ticker,
                    signal_date=a.trade_date,
                    direction_for_a=open_side,
                    z_score=round(z, 3),
                    spread=round(spread_now, 4),
                    spread_mean=round(spread_mean, 4),
                    spread_std=round(spread_std, 4),
                    entry_side="EXIT",
                    confidence=round(min(1.0, (cfg.entry_z - abs(z)) / cfg.entry_z), 3),
                )
            )
            open_side = None
    return signals


def spread_signals_for_candidates(
    bars_by_ticker: Dict[str, List[DailyBar]],
    pairs: List[Tuple[str, str]],
    cfg: Optional[StatArbConfig] = None,
) -> List[SpreadSignal]:
    """Screen candidate pairs and return every entry/exit signal across them."""
    cfg = cfg or StatArbConfig()
    out: List[SpreadSignal] = []
    for a, b in pairs:
        ba = bars_by_ticker.get(a)
        bb = bars_by_ticker.get(b)
        if not ba or not bb:
            continue
        pair = screen_pair(ba, bb, cfg)
        if pair is None:
            continue
        # Re-run signal walk on the screened pair's full history.
        out.extend(spread_signals_for_pair(ba, bb, cfg))
    return out


# ---------------------------------------------------------------------------
# Sector-pair discovery for PSX (stat-arb layer)
# ---------------------------------------------------------------------------


def sector_pairs_for_tape(
    bars_by_ticker: Dict[str, List[DailyBar]],
    sector_map: Optional[Dict[str, str]] = None,
    cfg: Optional[StatArbConfig] = None,
) -> List[SpreadPair]:
    """Discover which PSX same-sector pairs pass the stationarity screen.

    This is the module's front door for a backtest: give it the bar store and it
    returns the currently stat-arb-able pairs, each with its hedge ratio and spread
    stats.
    """
    from src.quant.sector_rotation import DEFAULT_SECTOR_MAP, group_by_sector

    sector_map = sector_map or DEFAULT_SECTOR_MAP
    sectors = group_by_sector(list(bars_by_ticker.keys()), sector_map)
    candidates = pair_candidates(sectors)
    cfg = cfg or StatArbConfig()
    results: List[SpreadPair] = []
    for a, b in candidates:
        ba = bars_by_ticker.get(a)
        bb = bars_by_ticker.get(b)
        if not ba or not bb:
            continue
        pair = screen_pair(ba, bb, cfg)
        if pair is not None:
            results.append(pair)
    return results


# ---------------------------------------------------------------------------
# Diagnostics / reporting helpers
# ---------------------------------------------------------------------------


@dataclass
class StatArbPnlScenario:
    leg_a: str
    leg_b: str
    entry_date: date
    entry_z: float
    direction_for_a: str
    exit_date: date
    exit_z: float
    spread_entry: float
    spread_exit: float
    pnl_pct_of_spread: float  # directional-hedged PnL view of the spread, in %


def pnl_scenario_from_signal(
    signal: SpreadSignal,
    leg_a_bars: List[DailyBar],
    leg_b_bars: List[DailyBar],
    exit_date: date,
    beta: Optional[float] = None,
) -> StatArbPnlScenario:
    """Build a PnL read-out for a single spread trade, marked at a chosen exit date.

    This is a directional-hedged view: we assume we are 1 unit long leg_a and
    -beta units short leg_b, marked on the spread. It is illustrative, not a
    filled-trade ledger.
    """
    beta_used = beta if beta is not None else 1.0
    exit_a = None
    exit_b = None
    for bar in leg_a_bars:
        if bar.trade_date == exit_date:
            exit_a = bar
            break
    for bar in leg_b_bars:
        if bar.trade_date == exit_date:
            exit_b = bar
            break
    entry_spread = signal.spread
    exit_spread = fitted_spread_at(
        exit_a.close_price if exit_a else leg_a_bars[-1].close_price,
        exit_b.close_price if exit_b else leg_b_bars[-1].close_price,
        0.0,
        1.0,
    )
    pnl = exit_spread - entry_spread
    return StatArbPnlScenario(
        leg_a=signal.leg_a,
        leg_b=signal.leg_b,
        entry_date=signal.signal_date,
        entry_z=signal.z_score,
        direction_for_a=signal.direction_for_a,
        exit_date=exit_date,
        exit_z=signal.z_score,
        spread_entry=round(entry_spread, 4),
        spread_exit=round(exit_spread, 4),
        pnl_pct_of_spread=round(pnl * 100, 2),
    )
