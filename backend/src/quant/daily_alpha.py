"""daily_alpha.py - the desk's unified Daily Alpha Intelligence Engine.

One post-close pass over the stored tape produces a single, decision-ready brief:

* a market regime header (Hurst exponent, variance ratio, TRENDING / CHOPPY /
  STRESS, and the posture that regime implies)
* high-conviction confluence picks: names that are liquid enough to trade and
  line up on more than one independent edge (seasonal accumulation window,
  momentum leadership, liquidity sweep, trend)
* exact position sizing on every pick: ATR-derived stop, Kelly-shrunk and
  VaR-clamped target weight, and the risk budget that weight consumes
* live same-sector stat-arb spreads trading beyond +/- 2.0 sigma

Everything here is a pure function of the bar store plus, optionally, the
seasonality matrix that ``seasonality.py`` already publishes. The CLI writes
``frontend/public/data/daily_alpha_brief.json``; the payload is deliberately
small (a few kilobytes), so the dashboard does not pay for the 1.76M-bar tape.

Run it:
    python backend/src/quant/daily_alpha.py [--db PATH] [--out PATH]
                                           [--refresh-seasonality]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:  # allow direct CLI execution
    sys.path.insert(0, str(BACKEND_DIR))

from src.core.models import DailyBar  # noqa: E402
from src.ingestion.sqlite_adapter import iter_validated_bars_by_ticker  # noqa: E402
from src.quant.regime_filter import RegimeConfig, hurst_exponent  # noqa: E402
from src.quant.risk_sizing import (  # noqa: E402
    KellyConfig,
    SizingConfig,
    fractional_kelly_edge,
    historical_var_pct,
    position_weight,
)
from src.quant.sector_rotation import (  # noqa: E402
    DEFAULT_SECTOR_MAP,
    atr,
    atr_pct,
    composite_momentum,
    group_by_sector,
    sector_of,
)
from src.quant.stat_arb import StatArbConfig, fitted_spread_at, hedge_ratio  # noqa: E402

PROJECT_ROOT = BACKEND_DIR.parent
DATA_DIR = PROJECT_ROOT / "frontend" / "public" / "data"
DEFAULT_OUTPUT = DATA_DIR / "daily_alpha_brief.json"
SEASONALITY_OUTPUT = DATA_DIR / "seasonality_matrix.json"

STATUS_ACTIVE = "ACCUMULATION WINDOW ACTIVE"

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

HISTORY_CAP = 320          # bars kept per ticker in memory (enough for 6M ROC)
MIN_HISTORY_BARS = 140     # a name needs both momentum horizons to be ranked
TURNOVER_WINDOW = 20       # sessions in the liquidity average
MIN_AVG_TURNOVER = 5_000_000.0   # PKR per session; below this is untradeable
MIN_AVG_VOLUME = 20_000    # shares per session
MIN_PRICE = 5.0            # penny-stock guard

POC_WINDOW = 15
POC_BUCKETS = 20
SWEEP_VOL_Z = 1.5
MOMENTUM_LEADER_MIN = 10.0  # composite 3M+6M ROC in %

TOP_N = 10
RISK_BUDGET_PCT = 1.0      # equity at risk per position at its stop
MAX_WEIGHT_PCT = 12.0      # per-name concentration cap
MIN_WEIGHT_PCT = 1.0
VAR_CAP_PCT = 4.0          # 1-day 99% VaR headroom for the whole book

STAT_ARB_ENTRY_Z = 2.0
STAT_ARB_LOOKBACK = 20
STAT_ARB_HEDGE_WINDOW = 63
STAT_ARB_MIN_BARS = 126
MAX_STAT_ARB_ALERTS = 8
SECTOR_PAIR_LIMIT = 6      # most liquid names per sector considered for pairs

EDGE_SEASONAL = STATUS_ACTIVE
EDGE_MOMENTUM = "MOMENTUM LEADER"
EDGE_SWEEP = "LIQUIDITY SWEEP"
EDGE_TREND = "ABOVE 50D SMA"

POSTURE = {
    "TRENDING": "Risk-on - press momentum leaders, trail stops under the 50-day.",
    "CHOPPY": "Mean-reversion - buy sweeps into support, bank profit fast, size down.",
    "STRESS": "Capital preservation - cut gross exposure, avoid new beta, hold cash.",
    "UNKNOWN": "Insufficient tape - no new risk until the proxy has more sessions.",
}


# ---------------------------------------------------------------------------
# Small statistics helpers
# ---------------------------------------------------------------------------


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _stdev(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = _mean(values)
    return math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))


def _returns(closes: Sequence[float]) -> List[float]:
    return [
        closes[i] / closes[i - 1] - 1.0
        for i in range(1, len(closes))
        if closes[i - 1] > 0
    ]


# ---------------------------------------------------------------------------
# Market regime
# ---------------------------------------------------------------------------


def classify_market_regime(
    hurst: float,
    variance_ratio: float,
    drawdown_pct: float,
    volatility_ratio: float,
) -> Tuple[str, str, float]:
    """Map the tape statistics onto one regime label, posture and stress score.

    STRESS overrides the Hurst read: a deep drawdown from the recent high while
    realized volatility is expanding is a de-risking state regardless of how
    trendy the six-month tape looks. Otherwise the Hurst exponent is the primary
    label and the variance ratio only breaks ties inside the neutral band, so the
    headline H and the regime can never contradict each other.
    """
    if drawdown_pct <= -8.0 and volatility_ratio >= 1.25:
        regime = "STRESS"
    elif hurst > 0.52:
        regime = "TRENDING"
    elif hurst >= 0.47 and variance_ratio > 1.15:
        regime = "TRENDING"
    else:
        regime = "CHOPPY"

    stress = -drawdown_pct * 4.0 + max(0.0, volatility_ratio - 1.0) * 40.0
    stress_score = round(max(0.0, min(100.0, stress)), 1)
    return regime, POSTURE[regime], stress_score


def market_proxy(
    bars_by_ticker: Dict[str, List[DailyBar]],
) -> Tuple[List[DailyBar], List[float], float]:
    """Equal-weighted index proxy + its daily returns + breadth of the last session.

    PSX has no free intraday index series in this store, so the desk builds its
    own breadth-weighted proxy: one observation per session, the cross-sectional
    mean return of every liquid name that traded. Extreme single-name moves are
    dropped so a corporate action cannot masquerade as a market crash.
    """
    returns_by_date: Dict[object, List[float]] = {}
    for bars in bars_by_ticker.values():
        for i in range(1, len(bars)):
            prev, curr = bars[i - 1], bars[i]
            if prev.close_price <= 0:
                continue
            if (curr.trade_date - prev.trade_date).days > 10:
                continue  # resumed after a halt: the gap is not a daily return
            r = curr.close_price / prev.close_price - 1.0
            if abs(r) > 0.35:
                continue  # split / corporate action guard
            returns_by_date.setdefault(curr.trade_date, []).append(r)

    names = len(bars_by_ticker)
    needed = 2 if names < 8 else max(3, min(10, names // 4))
    dates = sorted(d for d, rows in returns_by_date.items() if len(rows) >= needed)
    if not dates:
        return [], [], 0.0

    level = 1000.0
    proxy_bars: List[DailyBar] = []
    proxy_returns: List[float] = []
    for d in dates:
        r = _mean(returns_by_date[d])
        level *= 1.0 + r
        proxy_returns.append(r)
        proxy_bars.append(
            DailyBar(
                ticker="PSX-EW",
                trade_date=d,
                open_price=round(level, 4),
                high_price=round(level, 4),
                low_price=round(level, 4),
                close_price=round(level, 4),
                volume=0,
            )
        )

    last_date = dates[-1]
    last_rows = returns_by_date[last_date]
    breadth = sum(1 for r in last_rows if r > 0) / len(last_rows) * 100.0 if last_rows else 0.0
    return proxy_bars, proxy_returns, round(breadth, 1)


def normalized_variance_ratio(
    bars: List[DailyBar], long_lag: int = 12, short_lag: int = 2
) -> float:
    """Lag-normalized variance ratio of the log-price series, centred on 1.0.

    ``rolling_variance_ratio`` in regime_filter returns the raw variance ratio,
    which grows with the lag length even on a random walk. Dividing each
    variance by its own lag puts the neutral point back at 1.0, which is what
    the regime thresholds assume: >1 trends, <1 mean-reverts.
    """
    closes = [math.log(max(b.close_price, 1e-9)) for b in bars]
    n = len(closes)
    if n < long_lag + 2:
        return 1.0

    def var_at(lag: int) -> float:
        diffs = [closes[i] - closes[i - lag] for i in range(lag, n)]
        return _stdev(diffs) ** 2

    var_long = var_at(long_lag)
    var_short = var_at(short_lag)
    if var_short <= 1e-18:
        return 1.0
    vr = (var_long / long_lag) / (var_short / short_lag)
    return float(vr) if math.isfinite(vr) else 1.0


def regime_header(proxy_bars: List[DailyBar], proxy_returns: List[float], breadth: float) -> dict:
    """Build the market-regime block of the brief."""
    if len(proxy_bars) < 30:
        return {
            "regime": "UNKNOWN",
            "hurstExponent": 0.5,
            "varianceRatio": 1.0,
            "posture": POSTURE["UNKNOWN"],
            "stressScore": 0.0,
            "drawdownFromHighPct": 0.0,
            "volatilityRatio": 1.0,
            "breadthPct": breadth,
            "proxySessions": len(proxy_bars),
            "proxyLast": None,
        }

    cfg = RegimeConfig()
    lookback = max(8, min(cfg.hurst_lookback_sessions, len(proxy_bars) // 2))
    h = hurst_exponent(proxy_bars, max_lag=lookback)
    vr = normalized_variance_ratio(proxy_bars)

    closes = [b.close_price for b in proxy_bars]
    peak60 = max(closes[-60:]) if len(closes) >= 60 else max(closes)
    drawdown = (closes[-1] / peak60 - 1.0) * 100.0 if peak60 > 0 else 0.0
    vol20 = _stdev(proxy_returns[-20:])
    vol120 = _stdev(proxy_returns[-120:])
    vol_ratio = vol20 / vol120 if vol120 > 1e-12 else 1.0

    regime, posture, stress = classify_market_regime(h, vr, drawdown, vol_ratio)
    return {
        "regime": regime,
        "hurstExponent": round(h, 3),
        "varianceRatio": round(vr, 3),
        "posture": posture,
        "stressScore": stress,
        "drawdownFromHighPct": round(drawdown, 2),
        "volatilityRatio": round(vol_ratio, 2),
        "breadthPct": breadth,
        "proxySessions": len(proxy_bars),
        "proxyLast": round(closes[-1], 2),
    }


# ---------------------------------------------------------------------------
# Liquidity & confluence
# ---------------------------------------------------------------------------


def liquidity_profile(bars: List[DailyBar], window: int = TURNOVER_WINDOW) -> dict:
    """Average turnover / volume over the trailing window, plus a tradeability flag."""
    recent = bars[-window:] if len(bars) > window else bars
    turnover = _mean([b.close_price * b.volume for b in recent])
    volume = _mean([float(b.volume) for b in recent])
    return {
        "avgTurnoverPkr": round(turnover, 0),
        "avgVolume": round(volume, 0),
        "lastClose": round(bars[-1].close_price, 2) if bars else 0.0,
    }


def is_liquid(profile: dict) -> bool:
    """Institutional tradeability gate: turnover, size and price all have to clear."""
    return (
        profile["avgTurnoverPkr"] >= MIN_AVG_TURNOVER
        and profile["avgVolume"] >= MIN_AVG_VOLUME
        and profile["lastClose"] >= MIN_PRICE
    )


def volume_point_of_control(bars: List[DailyBar]) -> float:
    """Volume-weighted point of control over the last POC_WINDOW sessions."""
    profile = bars[-POC_WINDOW:] if len(bars) > POC_WINDOW else bars
    mids = [(b.high_price + b.low_price + b.close_price) / 3.0 for b in profile]
    lo, hi = min(mids), max(mids)
    if hi - lo < 1e-9:
        return round(lo, 2)
    width = (hi - lo) / POC_BUCKETS
    buckets = [0.0] * POC_BUCKETS
    for bar, mid in zip(profile, mids):
        idx = min(int((mid - lo) / width), POC_BUCKETS - 1)
        buckets[idx] += float(bar.volume)
    return round(lo + (buckets.index(max(buckets)) + 0.5) * width, 2)


def volume_z_score(bars: List[DailyBar], window: int = 20) -> float:
    recent = bars[-window:]
    volumes = [float(b.volume) for b in recent]
    sd = _stdev(volumes)
    return (volumes[-1] - _mean(volumes)) / sd if sd > 1e-9 else 0.0


def sweep_signal(bars: List[DailyBar]) -> dict:
    """Liquidity sweep: take out the prior 3-day low, reclaim the POC on volume."""
    poc = volume_point_of_control(bars)
    vol_z = volume_z_score(bars)
    prior = bars[-4:-1]
    swept = False
    if len(prior) == 3:
        swept = bool(
            bars[-1].low_price < min(b.low_price for b in prior)
            and bars[-1].close_price > poc
            and vol_z >= SWEEP_VOL_Z
        )
    return {"poc": poc, "volZScore": round(vol_z, 2), "sweep": swept}


def _sma(bars: List[DailyBar], days: int = 50) -> Optional[float]:
    if len(bars) < days:
        return None
    return _mean([b.close_price for b in bars[-days:]])


def confluence_edges(bars: List[DailyBar], seasonal_active: bool, momentum: float) -> List[str]:
    """Every independent edge the name currently carries, as display labels."""
    edges: List[str] = []
    if seasonal_active:
        edges.append(EDGE_SEASONAL)
    if momentum >= MOMENTUM_LEADER_MIN:
        edges.append(EDGE_MOMENTUM)
    if sweep_signal(bars)["sweep"]:
        edges.append(EDGE_SWEEP)
    sma = _sma(bars)
    if sma is not None and bars[-1].close_price > sma:
        edges.append(EDGE_TREND)
    return edges


def confluence_score(edges: Sequence[str], momentum: float) -> float:
    """Weighted conviction score; seasonal alignment is the strongest prior."""
    score = 0.0
    if EDGE_SEASONAL in edges:
        score += 35.0
    if EDGE_MOMENTUM in edges:
        score += min(1.0, momentum / 40.0) * 30.0
    if EDGE_SWEEP in edges:
        score += 20.0
    if EDGE_TREND in edges:
        score += 15.0
    return round(score, 2)


def qualifies(edges: Sequence[str]) -> bool:
    """Confluence means at least two edges, one of them a real trigger.

    Trend plus seasonal is not enough on its own — the desk wants either price
    leadership or a live accumulation trigger before it allocates.
    """
    if len(edges) < 2:
        return False
    return EDGE_MOMENTUM in edges or EDGE_SWEEP in edges


# ---------------------------------------------------------------------------
# Seasonality lookup
# ---------------------------------------------------------------------------


def load_seasonality(path: Path = SEASONALITY_OUTPUT) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def seasonal_index(payload: Optional[dict]) -> Dict[str, dict]:
    """Ticker -> its seasonality record: status, window win rate and forward edge.

    Every analysed ticker in the matrix carries its accumulation-window stats,
    not just the ones whose window is open, so a momentum pick that is off-season
    still reports the historical hit rate of its sector's pre-season window. The
    top-level ``activeWindows`` list refines the status where it exists.
    """
    if not payload:
        return {}
    out: Dict[str, dict] = {}
    for sector_row in payload.get("sectors", []) or []:
        sector = sector_row.get("sector")
        for row in sector_row.get("tickers", []) or []:
            ticker = str(row.get("ticker", "")).upper()
            if not ticker:
                continue
            stats = (row.get("accumulationWindowStats") or {}).get("forward60") or {}
            position = row.get("position") or {}
            out[ticker] = {
                "status": row.get("status"),
                "sector": row.get("sector") or sector,
                "winRate60Pct": stats.get("winRatePct"),
                "avgForward60Pct": stats.get("avgPct"),
                "avgForward90Pct": ((row.get("accumulationWindowStats") or {}).get("forward90") or {}).get("avgPct"),
                "rangePositionPct": position.get("rangePositionPct"),
                "monthsUntilWindow": row.get("monthsUntilWindow"),
            }
    for row in payload.get("activeWindows", []) or []:
        ticker = str(row.get("ticker", "")).upper()
        if not ticker:
            continue
        record = out.setdefault(ticker, {})
        record.update({
            "status": row.get("status", STATUS_ACTIVE),
            "sector": row.get("sector") or record.get("sector"),
            "winRate60Pct": row.get("winRate60Pct", record.get("winRate60Pct")),
            "avgForward60Pct": row.get("avgForward60Pct", record.get("avgForward60Pct")),
            "avgForward90Pct": row.get("avgForward90Pct", record.get("avgForward90Pct")),
            "rangePositionPct": row.get("rangePositionPct", record.get("rangePositionPct")),
            "monthsUntilWindow": row.get("monthsUntilWindow", record.get("monthsUntilWindow")),
        })
    return out


# ---------------------------------------------------------------------------
# Position sizing
# ---------------------------------------------------------------------------


def kelly_multiplier(win_rate_pct: Optional[float], avg_forward_pct: Optional[float]) -> float:
    """Half-to-full fractional-Kelly shrinker for a pick's target weight.

    The win rate and the seasonal forward edge stand in for the trade record the
    desk does not yet have for a fresh setup. Kelly is only ever allowed to
    shrink the ATR risk-parity weight: the multiplier lives in [0.5, 1.0], so a
    thin or unmeasured edge halves the position but never zeroes it out and a
    strong one still cannot exceed the volatility-derived cap.
    """
    if win_rate_pct is None:
        return 0.5
    win_rate = max(0.0, min(1.0, win_rate_pct / 100.0))
    # A bigger seasonal forward return implies a better win/loss payoff ratio.
    payoff = 1.0 + max(0.0, (avg_forward_pct or 0.0)) / 10.0
    edge = fractional_kelly_edge(
        win_rate,
        payoff,
        KellyConfig(fraction=0.5, min_win_rate=0.35, max_edge=1.0),
    )
    return round(max(0.5, min(1.0, 0.5 + 0.5 * edge)), 4)


def atr_stop(close: float, bars: List[DailyBar], mult: float = 2.0) -> Tuple[float, float]:
    """ATR stop with sane floors: never tighter than 2%, never wider than 15%."""
    a = atr(bars, 14)
    if a is None or a <= 0:
        a = close * 0.02
    distance = min(max(mult * a, close * 0.02), close * 0.15)
    return round(close - distance, 2), round(distance / close * 100.0, 2)


def size_picks(rows: List[dict], proxy_bars: List[DailyBar], proxy_returns: List[float]) -> dict:
    """Attach stop, target weight, risk budget and reference shares to each pick.

    Three overlays, in order: ATR/beta risk parity (the shared sizing policy),
    a fractional-Kelly shrink from the pick's own seasonal record, then a 99%
    historical VaR clamp on the whole book. Mutates ``rows``.
    """
    cfg = SizingConfig(
        target_risk_pct=RISK_BUDGET_PCT,
        max_weight_pct=MAX_WEIGHT_PCT,
        min_weight_pct=MIN_WEIGHT_PCT,
    )
    ref_equity = 1_000_000.0
    for row in rows:
        bars: List[DailyBar] = row.pop("_bars")
        close = row["close"]
        stop, stop_pct = atr_stop(close, bars)
        if stop <= 0 or stop >= close:
            stop = round(close * 0.92, 2)
            stop_pct = 8.0
        # The shared policy computes risk_budget / (entry - stop), so feed it a
        # unit-notional position (entry 1.0) to get a true fraction of equity.
        distance_fraction = max(1e-4, (close - stop) / close)
        raw = position_weight(1.0, 1.0 - distance_fraction, bars, cfg, proxy_bars)
        multiplier = kelly_multiplier(row.get("winRatePct"), row.get("avgForward60Pct"))
        weight = raw * multiplier
        row.update({
            "stopLoss": stop,
            "stopDistancePct": stop_pct,
            "atrPct": round(atr_pct(bars), 2),
            "kellyMultiplier": multiplier,
            "targetWeightPct": round(weight * 100.0, 2),
        })

    gross = sum(r["targetWeightPct"] for r in rows)
    var_pct = historical_var_pct(proxy_returns, 0.99, 126) * 100.0 if proxy_returns else 0.0
    # Book VaR scales with gross exposure: clamp exposure until VaR sits inside cap.
    book_var = gross / 100.0 * var_pct
    scale = 1.0
    if book_var > VAR_CAP_PCT and gross > 0:
        scale = VAR_CAP_PCT / book_var
    if gross * scale > 100.0 and gross > 0:
        scale *= 100.0 / (gross * scale)

    for row in rows:
        weight = row["targetWeightPct"] * scale
        row["targetWeightPct"] = round(weight, 2)
        row["riskBudgetPct"] = round(weight * row["stopDistancePct"] / 100.0, 2)
        row["referenceShares"] = int(ref_equity * weight / 100.0 / row["close"]) if row["close"] > 0 else 0

    gross_after = sum(row["targetWeightPct"] for row in rows)
    return {
        "grossExposurePct": round(gross_after, 2),
        "portfolioVarPct": round(gross_after / 100.0 * var_pct, 2),
        "varCapPct": VAR_CAP_PCT,
        "varScaleApplied": round(scale, 4),
    }


# ---------------------------------------------------------------------------
# Stat-arb alerts
# ---------------------------------------------------------------------------


def _aligned(a: List[DailyBar], b: List[DailyBar]) -> Tuple[List[DailyBar], List[DailyBar]]:
    """Trim two tapes to the sessions both names actually traded."""
    b_by_date = {bar.trade_date: bar for bar in b}
    left: List[DailyBar] = []
    right: List[DailyBar] = []
    for bar in a:
        other = b_by_date.get(bar.trade_date)
        if other is not None:
            left.append(bar)
            right.append(other)
    return left, right


def spread_alert(
    leg_a: str,
    leg_b: str,
    bars_a: List[DailyBar],
    bars_b: List[DailyBar],
    sector: str,
    entry_z: float = STAT_ARB_ENTRY_Z,
) -> Optional[dict]:
    """One sector-spread read-out, or None when it is inside the entry band."""
    a, b = _aligned(bars_a, bars_b)
    if len(a) < STAT_ARB_MIN_BARS:
        return None
    alpha, beta, _, _ = hedge_ratio(a, b, STAT_ARB_HEDGE_WINDOW)
    if not math.isfinite(beta) or beta <= 0:
        return None

    tail = min(STAT_ARB_LOOKBACK, len(a))
    spreads = [
        fitted_spread_at(x.close_price, y.close_price, alpha, beta)
        for x, y in zip(a[-tail:], b[-tail:])
    ]
    if len(spreads) < 5:
        return None
    sd = _stdev(spreads)
    if sd <= 1e-9:
        return None
    mean = _mean(spreads)
    z = (spreads[-1] - mean) / sd
    if not math.isfinite(z) or abs(z) < entry_z:
        return None

    # z > 0 means leg A trades rich to its hedge: sell A, buy B.
    direction = "SHORT_A_LONG_B" if z > 0 else "LONG_A_SHORT_B"
    return {
        "legA": leg_a,
        "legB": leg_b,
        "sector": sector,
        "zScore": round(z, 2),
        "directionForA": direction,
        "action": f"{'SHORT' if z > 0 else 'LONG'} {leg_a} / {'LONG' if z > 0 else 'SHORT'} {leg_b}",
        "hedgeRatio": round(beta, 3),
        "spreadStd": round(sd, 5),
        "lastSpread": round(spreads[-1], 5),
        "entryZ": entry_z,
        "confidencePct": round(min(100.0, abs(z) / 3.0 * 100.0), 1),
    }


def stat_arb_alerts(
    liquid: Dict[str, List[DailyBar]],
    profile_by_ticker: Dict[str, dict],
    entry_z: float = STAT_ARB_ENTRY_Z,
    pair_limit: int = SECTOR_PAIR_LIMIT,
    max_alerts: int = MAX_STAT_ARB_ALERTS,
    max_leg_repeats: int = 2,
) -> List[dict]:
    """Screen the most liquid same-sector pairs and keep the richest spreads.

    Only the top ``pair_limit`` names per sector by turnover are paired, which
    keeps the pass linear-ish instead of testing every pair in a 40-name sector.
    """
    ranked: List[Tuple[str, float]] = sorted(
        liquid, key=lambda t: -profile_by_ticker.get(t, {}).get("avgTurnoverPkr", 0.0)
    )
    sectors = group_by_sector(ranked, DEFAULT_SECTOR_MAP)
    chosen: List[Tuple[str, str, str]] = []
    for sector, members in sectors.items():
        top = sorted(members, key=lambda t: -profile_by_ticker.get(t, {}).get("avgTurnoverPkr", 0.0))[:pair_limit]
        for i in range(len(top)):
            for j in range(i + 1, len(top)):
                chosen.append((top[i], top[j], sector))

    alerts: List[dict] = []
    for a, b, sector in chosen:
        alert = spread_alert(a, b, liquid[a], liquid[b], sector, entry_z)
        if alert is not None:
            alerts.append(alert)
    alerts.sort(key=lambda row: -abs(row["zScore"]))
    # One stretched name should not fill the whole board: cap how often a leg repeats.
    kept: List[dict] = []
    leg_counts: Dict[str, int] = {}
    for alert in alerts:
        a, b = alert["legA"], alert["legB"]
        if leg_counts.get(a, 0) >= max_leg_repeats or leg_counts.get(b, 0) >= max_leg_repeats:
            continue
        leg_counts[a] = leg_counts.get(a, 0) + 1
        leg_counts[b] = leg_counts.get(b, 0) + 1
        kept.append(alert)
        if len(kept) >= max_alerts:
            break
    return kept


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def build_daily_alpha(
    bars_by_ticker: Dict[str, List[DailyBar]],
    seasonality: Optional[dict] = None,
    top_n: int = TOP_N,
    entry_z: float = STAT_ARB_ENTRY_Z,
) -> dict:
    """Fuse every module's view of one tape into the daily brief payload."""
    recent = {t: bars for t, bars in bars_by_ticker.items() if len(bars) >= MIN_HISTORY_BARS}

    profiles = {t: liquidity_profile(bars) for t, bars in recent.items()}
    liquid = {
        t: bars
        for t, bars in recent.items()
        if is_liquid(profiles[t]) and len(bars) >= STAT_ARB_MIN_BARS
    }
    liquid_profiles = {t: profiles[t] for t in liquid}

    proxy_bars, proxy_returns, breadth = market_proxy(liquid if len(liquid) >= 3 else recent)
    regime = regime_header(proxy_bars, proxy_returns, breadth)

    seasonal = seasonal_index(seasonality)
    candidates: List[dict] = []
    for ticker, bars in liquid.items():
        momentum = composite_momentum(bars, len(bars) - 1)
        season_row = seasonal.get(ticker)
        seasonal_active = bool(season_row) and season_row.get("status") == STATUS_ACTIVE
        edges = confluence_edges(bars, seasonal_active, momentum)
        if not qualifies(edges):
            continue
        sector = (season_row or {}).get("sector") or sector_of(ticker)
        shape = sweep_signal(bars)
        candidates.append({
            "_bars": bars,
            "ticker": ticker,
            "sector": sector,
            "close": round(bars[-1].close_price, 2),
            "edges": edges,
            "edgeCount": len(edges),
            "score": confluence_score(edges, momentum),
            "momentum3mPct": round(_momentum(bars, 3), 2),
            "momentum6mPct": round(_momentum(bars, 6), 2),
            "avgTurnoverPkr": liquid_profiles[ticker]["avgTurnoverPkr"],
            "avgVolume": liquid_profiles[ticker]["avgVolume"],
            "volumeZScore": shape["volZScore"],
            "poc": shape["poc"],
            "seasonalStatus": (season_row or {}).get("status"),
            "winRatePct": (season_row or {}).get("winRate60Pct"),
            "avgForward60Pct": (season_row or {}).get("avgForward60Pct"),
            "rangePositionPct": (season_row or {}).get("rangePositionPct"),
            "lastDate": bars[-1].trade_date.isoformat(),
        })

    candidates.sort(key=lambda row: (-row["score"], -row["momentum6mPct"]))
    picks = candidates[:top_n]
    portfolio = size_picks(picks, proxy_bars, proxy_returns)
    for rank, row in enumerate(picks, start=1):
        row["rank"] = rank
        row.pop("_bars", None)

    for row in candidates[len(picks):]:
        row.pop("_bars", None)

    alerts = stat_arb_alerts(liquid, liquid_profiles, entry_z=entry_z)

    last_dates = [bars[-1].trade_date for bars in recent.values()] or [
        bars[-1].trade_date for bars in bars_by_ticker.values() if bars
    ]
    session = max(last_dates).isoformat() if last_dates else None
    history = max((len(b) for b in recent.values()), default=0)

    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sessionDate": session,
        "marketRegime": regime,
        "portfolio": portfolio,
        "picks": picks,
        "statArb": alerts,
        "universe": {
            "scanned": len(bars_by_ticker),
            "eligible": len(recent),
            "liquid": len(liquid),
            "historySessions": history,
            "minAvgTurnoverPkr": MIN_AVG_TURNOVER,
            "minAvgVolume": MIN_AVG_VOLUME,
            "minPrice": MIN_PRICE,
            "turnoverWindow": TURNOVER_WINDOW,
        },
        "meta": {
            "name": "PSX Daily Alpha Intelligence Brief",
            "topN": top_n,
            "confluenceRule": "2+ edges, one of which is momentum leadership or a liquidity sweep",
            "edgeWeights": {EDGE_SEASONAL: 35, EDGE_MOMENTUM: 30, EDGE_SWEEP: 20, EDGE_TREND: 15},
            "sizing": {
                "riskBudgetPct": RISK_BUDGET_PCT,
                "maxWeightPct": MAX_WEIGHT_PCT,
                "varCapPct": VAR_CAP_PCT,
                "referenceCapitalPkr": 1_000_000,
                "method": "ATR(14) x2 stop, ATR/beta risk parity, fractional-Kelly shrink, 99% historical VaR clamp",
            },
            "statArb": {
                "entryZ": entry_z,
                "spreadLookback": STAT_ARB_LOOKBACK,
                "hedgeWindow": STAT_ARB_HEDGE_WINDOW,
                "pairsPerSector": SECTOR_PAIR_LIMIT,
            },
            "seasonalityRefreshedAt": (seasonality or {}).get("generatedAt"),
        },
    }


def _momentum(bars: List[DailyBar], months: int) -> float:
    """ROC over a whole number of months, as a percentage (0 when too short)."""
    sessions = int(months * 252 / 12)
    idx = len(bars) - 1
    if idx - sessions < 0:
        return 0.0
    past = bars[idx - sessions].close_price
    if past <= 0:
        return 0.0
    return (bars[idx].close_price / past - 1.0) * 100.0


# ---------------------------------------------------------------------------
# Pipeline entry points
# ---------------------------------------------------------------------------


def load_recent_bars(db_path: str, history_cap: int = HISTORY_CAP) -> Tuple[Dict[str, List[DailyBar]], int]:
    """Stream the store and keep only the recent window for each ticker."""
    rejected = [0]
    recent: Dict[str, List[DailyBar]] = {}
    stream = iter_validated_bars_by_ticker(db_path, min_bars=MIN_HISTORY_BARS, rejected=rejected)
    for ticker, bars in stream:
        recent[ticker] = bars[-history_cap:]
    return recent, rejected[0]


def refresh_seasonality_matrix(db_path: str, out_path: Path = SEASONALITY_OUTPUT) -> dict:
    """Regenerate the seasonality matrix the brief reads its accumulation flags from."""
    from src.quant.seasonality import MIN_HISTORY_BARS as SEASONAL_MIN, build_seasonality_matrix

    rejected = [0]
    stream = iter_validated_bars_by_ticker(db_path, min_bars=SEASONAL_MIN, rejected=rejected)
    payload = build_seasonality_matrix(stream, min_bars=SEASONAL_MIN)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def refresh_daily_alpha(
    db_path: str,
    out_path: Path = DEFAULT_OUTPUT,
    seasonality_path: Path = SEASONALITY_OUTPUT,
    refresh_seasonality: bool = False,
    top_n: int = TOP_N,
) -> dict:
    """Full refresh: optional seasonality rebuild, then the brief, then the JSON write."""
    seasonality = None if refresh_seasonality else load_seasonality(seasonality_path)
    if refresh_seasonality or seasonality is None:
        seasonality = refresh_seasonality_matrix(db_path, seasonality_path)
    recent, _rejected = load_recent_bars(db_path)
    payload = build_daily_alpha(recent, seasonality, top_n=top_n)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="PSX unified daily alpha intelligence brief")
    parser.add_argument("--db", help="SQLite store (default: backend/psx_history.db)")
    parser.add_argument("--out", help="output JSON path")
    parser.add_argument("--top-n", type=int, default=TOP_N, help="confluence picks to publish")
    parser.add_argument(
        "--refresh-seasonality",
        action="store_true",
        help="rebuild seasonality_matrix.json before aggregating",
    )
    args = parser.parse_args()

    from src.core.config import get_db_path

    db_path = args.db or str(get_db_path())
    payload = refresh_daily_alpha(
        db_path,
        out_path=Path(args.out) if args.out else DEFAULT_OUTPUT,
        refresh_seasonality=args.refresh_seasonality,
        top_n=args.top_n,
    )

    regime = payload["marketRegime"]
    universe = payload["universe"]
    print(f"store        : {db_path}")
    print(f"session      : {payload['sessionDate']}  ({universe['historySessions']} sessions kept)")
    print(f"universe     : {universe['scanned']} scanned / {universe['eligible']} eligible / "
          f"{universe['liquid']} liquid")
    print(f"regime       : {regime['regime']}  H={regime['hurstExponent']}  "
          f"VR={regime['varianceRatio']}  DD={regime['drawdownFromHighPct']}%")
    print(f"posture      : {regime['posture']}")
    print(f"picks        : {len(payload['picks'])}")
    for row in payload["picks"]:
        print(f"  {row['rank']:>2}. {row['ticker']:<8} {row['sector']:<20} "
              f"score {row['score']:>6.1f}  stop {row['stopLoss']:>8.2f}  "
              f"w {row['targetWeightPct']:>5.2f}%  edges: {', '.join(row['edges'])}")
    print(f"stat-arb     : {len(payload['statArb'])} spreads beyond +/-{STAT_ARB_ENTRY_Z} sigma")
    for row in payload["statArb"]:
        print(f"  {row['legA']:>6}/{row['legB']:<6} z {row['zScore']:+.2f}  {row['action']}")
    out = Path(args.out) if args.out else DEFAULT_OUTPUT
    print(f"written      : {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
