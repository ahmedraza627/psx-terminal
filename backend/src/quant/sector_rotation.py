"""sector_rotation.py - sector performance tracking & catalyst filtering for PSX.

Groups tickers by PSX sector (Energy, Fertilizer, Banking, Cement, Tech, etc.),
tracks sector-relative momentum, and filters stock-level momentum selections to
favor names belonging to the top outperforming sectors of the month.

Sector scores are computed from the same in-memory bar store the rest of the
quant engine uses, so the module stays offline-only and has no external feed / messaging dependency.

Run as a module or import the functions from the quant package.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional, Tuple

from src.core.models import DailyBar  # noqa: E402

SESSIONS_PER_YEAR = 252
MONTHS_PER_YEAR = 12

# ---------------------------------------------------------------------------
# Sector registry
# ---------------------------------------------------------------------------

# Conservative, conservative-by-source PSX sector mapping for the tracked
# core universe. Names absent from the map default to "OTHER" so a new ticker
# never silently gets assigned to a sector it does not belong to.
DEFAULT_SECTOR_MAP: Dict[str, str] = {
    # Banking
    "UBL": "Banking", "MCB": "Banking", "MEBL": "Banking", "HBL": "Banking",
    "BAHL": "Banking", "BAFL": "Banking", "NBP": "Banking", "BOP": "Banking",
    "AKBL": "Banking", "FABL": "Banking",
    # Cement
    "MLCF": "Cement", "LUCK": "Cement", "DGKC": "Cement", "FCCL": "Cement",
    "PIOC": "Cement", "CHCC": "Cement", "ACPL": "Cement", "BWCL": "Cement",
    "KOHC": "Cement",
    # Oil, gas & E&P
    "OGDC": "Energy", "PPL": "Energy", "MARI": "Energy", "POL": "Energy",
    "PSO": "Energy", "SHEL": "Energy", "SNGP": "Energy", "SSGC": "Energy",
    "HASCOL": "Energy",
    # Fertiliser
    "FFC": "Fertilizer", "ENGRO": "Fertilizer", "EFERT": "Fertilizer",
    "FATIMA": "Fertilizer", "FFBL": "Fertilizer",
    # Technology
    "SYS": "Tech", "TRG": "Tech", "AIRLINK": "Tech", "AVN": "Tech",
    "NETSOL": "Tech", "OCTOPUS": "Tech",
    # Refineries
    "PRL": "Refining", "NRL": "Refining", "ATRL": "Refining", "CNERGY": "Refining",
    # Power
    "HUBC": "Power", "KAPCO": "Power", "KEL": "Power",
    # Chemicals / agro / manufacturing / pharma
    "EPCL": "Chemicals", "LOTCHEM": "Chemicals", "AGP": "Chemicals",
    "SEARL": "Textiles", "ABOT": "Food", "ILP": "Food",
    "NML": "Steel", "PAEL": "Pharma", "UNITY": "Engineering",
    "INIL": "Cabling", "ISL": "Cabling", "MTL": "Cabling",
    "INDU": "Manufacturing", "HCAR": "Auto", "PSMC": "Auto",
    "THALL": "Steel", "GTYR": "Cement", "TREET": "Cement", "AICL": "Cement",
}


@dataclass
class SectorStats:
    sector: str
    members: int
    momentum: float  # average composite 3M+6M ROC across members with enough history
    avg_volume: float
    # Catalyst: retail-driven turnover spike minus its own trailing norm, in volume units.
    catalyst_score: float


def sector_of(ticker: str, sector_map: Optional[Dict[str, str]] = None) -> str:
    """Return the canonical sector label for a ticker, defaulting to 'OTHER'."""
    return (sector_map or DEFAULT_SECTOR_MAP).get(ticker.strip().upper(), "OTHER")


def group_by_sector(
    tickers: List[str],
    sector_map: Optional[Dict[str, str]] = None,
) -> Dict[str, List[str]]:
    """Return {sector: [tickers]} for the given universe."""
    out: Dict[str, List[str]] = {}
    for t in tickers:
        out.setdefault(sector_of(t, sector_map), []).append(t)
    return out


# ---------------------------------------------------------------------------
# Risk / volatility helpers (shared by sizing module)
# ---------------------------------------------------------------------------

def atr(bars: List[DailyBar], period: int = 14) -> Optional[float]:
    """Average True Range ending at the last bar in `bars`."""
    if len(bars) < 2:
        return None
    recent = bars[-(period + 1) :]
    trs: List[float] = []
    for i in range(1, len(recent)):
        curr, prev = recent[i], recent[i - 1]
        tr = max(
            curr.high_price - curr.low_price,
            abs(curr.high_price - prev.close_price),
            abs(curr.low_price - prev.close_price),
        )
        trs.append(tr)
    return sum(trs) / len(trs)


def atr_pct(bars: List[DailyBar], period: int = 14) -> float:
    """ATR expressed as a % of the latest close (volatility intensity)."""
    a = atr(bars, period)
    close = bars[-1].close_price if bars else 0.0
    if a is None or close <= 0:
        return 0.0
    return a / close * 100


def beta_vs_index(
    stock_bars: List[DailyBar],
    index_bars: List[DailyBar],
    window: int = 63,
) -> float:
    """Simple single-factor beta of stock returns vs index returns over a trailing window.

    Falls back to 1.0 when either tape is too short or variance is degenerate, which
    is the neutral prior a risk engine would use for an unmeasurable name.
    """
    if len(stock_bars) < window + 1 or len(index_bars) < window + 1:
        return 1.0
    stock = stock_bars[-window - 1 :]
    index = index_bars[-window - 1 :]
    if len(stock) != len(index):
        return 1.0
    stock_ret: List[float] = []
    index_ret: List[float] = []
    for i in range(1, len(stock)):
        sr = (stock[i].close_price / stock[i - 1].close_price) - 1
        ir = (index[i].close_price / index[i - 1].close_price) - 1
        stock_ret.append(sr)
        index_ret.append(ir)
    n = len(stock_ret)
    if n < 2:
        return 1.0
    mean_s = sum(stock_ret) / n
    mean_i = sum(index_ret) / n
    cov = sum((s - mean_s) * (i - mean_i) for s, i in zip(stock_ret, index_ret)) / n
    var_i = sum((i - mean_i) ** 2 for i in index_ret) / n
    if var_i <= 1e-12:
        return 1.0
    beta = cov / var_i
    if not math.isfinite(beta) or beta <= 0:
        return 1.0
    return beta


# ---------------------------------------------------------------------------
# Sector scoring
# ---------------------------------------------------------------------------

def composite_momentum(bars: List[DailyBar], session_index: int) -> float:
    """3-month + 6-month ROC combined — mirrors momentum_rotation.composite_momentum."""
    lookback3 = max(1, int(3 * SESSIONS_PER_YEAR / MONTHS_PER_YEAR))
    lookback6 = max(1, int(6 * SESSIONS_PER_YEAR / MONTHS_PER_YEAR))

    def roc(months_back: int, lb: int) -> float:
        start = session_index - lb
        if start < 0:
            return 0.0
        past = bars[start].close_price
        current = bars[session_index].close_price
        if past <= 0:
            return 0.0
        return (current / past - 1) * 100

    return roc(3, lookback3) + roc(6, lookback6)


def sector_momentum_stats(
    bars_by_ticker: Dict[str, List[DailyBar]],
    sector_map: Optional[Dict[str, str]] = None,
) -> Dict[str, SectorStats]:
    """Score every sector in the tape by member momentum and average turnover.

    Only members with a full 6-month lookback score into the momentum average;
    a sector full of unmeasurable names scores low, which is the conservative
    choice for a catalyst filter.
    """
    groups = group_by_sector(list(bars_by_ticker.keys()), sector_map)
    stats: Dict[str, SectorStats] = {}
    for sector, members in groups.items():
        mom_scores: List[float] = []
        vols: List[float] = []
        for t in members:
            bars = bars_by_ticker.get(t)
            if not bars or len(bars) < int(7 * SESSIONS_PER_YEAR / MONTHS_PER_YEAR):
                continue
            idx = len(bars) - 1
            mom_scores.append(composite_momentum(bars, idx))
            vols.append(bars[-1].volume)
        momentum = sum(mom_scores) / len(mom_scores) if mom_scores else 0.0
        avg_volume = sum(vols) / len(vols) if vols else 0.0
        stats[sector] = SectorStats(
            sector=sector,
            members=len(members),
            momentum=round(momentum, 2),
            avg_volume=round(avg_volume, 0),
            catalyst_score=0.0,
        )
    return stats


def sector_catalyst_scores(
    bars_by_ticker: Dict[str, List[DailyBar]],
    sector_map: Optional[Dict[str, str]] = None,
    window_sessions: int = 10,
) -> Dict[str, float]:
    """Per-sector retail-catalyst score: recent turnover spike above trailing norm.

    For each ticker, catalyst = last-session volume / (avg volume over the trailing
    `window_sessions`) minus 1; the sector score is the member average. A sector whose
    members are collectively seeing elevated turnover (frontside of a catalyst) scores
    higher than a dormant one.
    """
    groups = group_by_sector(list(bars_by_ticker.keys()), sector_map)
    scores: Dict[str, float] = {}
    for sector, members in groups.items():
        cat: List[float] = []
        for t in members:
            bars = bars_by_ticker.get(t)
            if not bars or len(bars) < window_sessions + 1:
                continue
            recent = bars[-(window_sessions + 1) :]
            avg_vol = sum(b.volume for b in recent[:-1]) / window_sessions
            last_vol = recent[-1].volume
            if avg_vol > 0:
                cat.append(last_vol / avg_vol - 1)
        scores[sector] = round(sum(cat) / len(cat) * 100, 2) if cat else 0.0
    return scores


def top_n_sectors(
    bars_by_ticker: Dict[str, List[DailyBar]],
    top_n: int = 2,
    sector_map: Optional[Dict[str, str]] = None,
    use_catalyst: bool = True,
) -> List[Tuple[str, float]]:
    """Return the top-N outperforming sectors of the moment.

    Ranking blends momentum (3M+6M member ROC) with the catalyst score when
    ``use_catalyst`` is on, which is the institutional tilt toward sectors that
    are both strong and actively repricing.
    """
    stats = sector_momentum_stats(bars_by_ticker, sector_map)
    catalysts = sector_catalyst_scores(bars_by_ticker, sector_map) if use_catalyst else {}
    ranked: List[Tuple[str, float]] = []
    for sector, s in stats.items():
        momentum = s.momentum
        catalyst = catalysts.get(sector, 0.0)
        # Momentum carries the weight; catalyst is a tie-breaker/overlay.
        combined = momentum + max(0.0, catalyst) * 0.25
        ranked.append((sector, round(combined, 2)))
    ranked.sort(key=lambda item: -item[1])
    return ranked[: max(top_n, 1)]


def sector_filtered_leaders(
    ticker_ranking: List[Tuple[str, float]],
    bars_by_ticker: Dict[str, List[DailyBar]],
    top_sectors: List[str],
    sector_map: Optional[Dict[str, str]] = None,
    sector_bias_weight: float = 0.5,
) -> List[Tuple[str, float]]:
    """Bias a stock-level momentum ranking toward tickers in `top_sectors`.

    Names in the leading sectors keep their momentum score; names outside them
    are discounted by `sector_bias_weight` so the filter favors sector leaders
    without fully excluding out-of-sector strong names (a basket still wants
    diversification).
    """
    top_set = set(top_sectors)
    out: List[Tuple[str, float]] = []
    for ticker, score in ticker_ranking:
        sec = sector_of(ticker, sector_map)
        adj = score if sec in top_set else score * (1 - sector_bias_weight)
        out.append((ticker, round(adj, 2)))
    out.sort(key=lambda item: -item[1])
    return out
