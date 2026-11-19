"""seasonality.py - sector seasonality & cyclical accumulation engine for PSX.

The PSX is a small, physically-driven market: sugar mills bid cane and re-rate
ahead of the crushing season, cement volumes follow the construction calendar,
textile exporters front-run order books, and fertiliser demand tracks the Rabi
and Kharif sowing windows. That produces recurring *pre-season accumulation*
windows where a sector's tape makes its cyclical low two to three months before
the seasonal peak in demand, earnings or news flow.

This module measures those windows on the stored EOD tape rather than assuming
them:

* For every ticker it anchors one observation per calendar month (the first
  session of the month) and measures the forward 60-session (~3 month) and
  90-session (~4.5 month) return from that anchor, plus the month's own return.
* Observations are pooled per month-of-year, per ticker and per sector, giving
  a seasonal win rate and an upside distribution instead of a single narrative.
* A position filter keeps the output honest: a name that is already extended
  (high in its own 3-year range, far off its low) is not an accumulation
  candidate even when the calendar window is open. Seasonality without a
  valuation/position filter just buys tops.
* Everything is pooled into per-sector calendars and per-ticker status flags:
  ACCUMULATION WINDOW ACTIVE, WATCH, OFF-SEASON.

Output goes to frontend/public/data/seasonality_matrix.json for the /seasonality
page. The engine is offline and deterministic: same store in, same matrix out.

Run it
------
python backend/src/quant/seasonality.py [--db PATH] [--out PATH] [--min-bars 500]
"""

from __future__ import annotations

import argparse
import json
import logging
import statistics
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from src.core.config import get_db_path  # noqa: E402
from src.core.models import DailyBar  # noqa: E402
from src.ingestion.sqlite_adapter import iter_validated_bars_by_ticker  # noqa: E402
from src.quant.sector_rotation import SESSIONS_PER_YEAR, DEFAULT_SECTOR_MAP  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("seasonality")

PROJECT_ROOT = BACKEND_DIR.parent
DEFAULT_OUTPUT = PROJECT_ROOT / "frontend" / "public" / "data" / "seasonality_matrix.json"

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

# Forward horizons, in trading sessions. 60 sessions is the classic 3-month
# seasonal hold; 90 sessions covers a full pre-season-to-peak cycle.
FORWARD_WINDOWS: Tuple[int, ...] = (60, 90)
# Below roughly two years of tape a month-of-year sample has no statistical
# meaning, so short-history names are excluded from the matrix (they still stay
# in the store for the rest of the desk).
MIN_HISTORY_BARS = 500
# 3-year window for the cyclical position filter (756 sessions).
POSITION_LOOKBACK_BARS = 3 * SESSIONS_PER_YEAR
# Position filter thresholds: at or below the first is a genuine accumulation
# zone, above the second the name is treated as already extended.
ACCUMULATION_MAX_RANGE_PCT = 45.0
WATCH_MAX_RANGE_PCT = 60.0
# A name this far below its 3-year high is still cyclically discounted; one
# that has already run hard off the low is not.
MAX_DRAWDOWN_FROM_HIGH_PCT = 22.0

STATUS_ACTIVE = "ACCUMULATION WINDOW ACTIVE"
STATUS_WATCH = "WATCH"
STATUS_OFF = "OFF-SEASON"

MONTH_LABELS = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)


# ---------------------------------------------------------------------------
# Sector season templates
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SectorSeason:
    """A sector's peak-demand window and the accumulation lead into it."""

    peak_start: int          # 1-12, first month of the peak window
    peak_length: int         # how many months the peak runs
    accumulation_lead: int   # months of pre-season accumulation before the peak
    rationale: str


def _month_window(start: int, length: int) -> Tuple[int, ...]:
    return tuple(((start - 1 + i) % 12) + 1 for i in range(length))


def _lead_window(peak_start: int, lead: int) -> Tuple[int, ...]:
    """The `lead` months immediately before a peak window starts."""
    return tuple(((peak_start - 1 - i) % 12) + 1 for i in reversed(range(1, lead + 1)))


# Peak windows and the 2-3 month accumulation lead before each. These are the
# structural drivers of each PSX sector, not fitted parameters; the fitted
# numbers live in the pooled forward-return statistics.
SECTOR_SEASONS: Dict[str, SectorSeason] = {
    "Sugar": SectorSeason(
        11, 3, 3,
        "Crushing season runs Nov-Jan; mills and cane procurement re-rate from late Q3.",
    ),
    "Textile Composite": SectorSeason(
        8, 2, 3,
        "Export order books and yarn pricing peak Aug-Sep ahead of the winter shipping cycle.",
    ),
    "Textile Spinning": SectorSeason(
        8, 2, 3,
        "Spinning mills re-rate as yarn prices and export order books peak Aug-Sep.",
    ),
    "Textile Weaving": SectorSeason(
        9, 2, 3,
        "Grey cloth and denim weaving orders peak Sep-Oct ahead of the winter shipping window.",
    ),
    "Apparel": SectorSeason(
        9, 3, 3,
        "Stitched-garment export orders peak Sep-Nov for the holiday delivery season.",
    ),
    "Woollen": SectorSeason(
        11, 3, 2,
        "Winter shawl, blanket and suiting demand peaks Nov-Jan.",
    ),
    "Synthetic & Rayon": SectorSeason(
        8, 2, 3,
        "Polyester and rayon offtake tracks the textile export cycle, peaking Aug-Sep.",
    ),
    "Jute": SectorSeason(
        6, 3, 2,
        "Jute batching and bag demand peak Jun-Aug ahead of the Kharif harvest movement.",
    ),
    "Vanaspati": SectorSeason(
        10, 3, 2,
        "Cooking-oil and ghee offtake builds into Oct-Dec as winter and wedding demand peak.",
    ),
    "Cement": SectorSeason(
        10, 3, 3,
        "Construction season peaks Oct-Dec; dispatches build through the pre-winter months.",
    ),
    "Fertilizer": SectorSeason(
        3, 2, 2,
        "Rabi sowing peaks Mar-Apr; dealers stock up through Jan-Feb.",
    ),
    "Energy": SectorSeason(
        12, 2, 2,
        "Winter gas and furnace-oil demand peaks Dec-Jan; E&P and OMC margins firm into it.",
    ),
    "Banking": SectorSeason(
        1, 2, 2,
        "Year-end deposit mobilisation and clean-up peaks Dec-Jan.",
    ),
    "Pharma": SectorSeason(
        12, 2, 2,
        "Winter respiratory season and year-end institutional buying peak Dec-Jan.",
    ),
    "Auto": SectorSeason(
        8, 3, 3,
        "New model-year launches and post-budget demand peak Aug-Oct.",
    ),
    "Auto Parts": SectorSeason(
        8, 3, 3,
        "Tier-1 parts volumes track assembler build schedules, peaking with Aug-Oct model-year output.",
    ),
    "Refining": SectorSeason(
        6, 3, 2,
        "Summer transport fuel demand peaks Jun-Aug; cracks widen into it.",
    ),
    "Power": SectorSeason(
        6, 3, 3,
        "Summer peak load runs Jun-Aug; capacity payments and tariffs reset ahead of it.",
    ),
    "Chemicals": SectorSeason(
        4, 3, 2,
        "Agro-chemical and industrial offtake peaks Apr-Jun.",
    ),
    "Food": SectorSeason(
        11, 3, 2,
        "Winter and Ramzan-linked staple demand peaks Nov-Jan.",
    ),
    "Tech": SectorSeason(
        1, 2, 2,
        "IT export invoicing and budget-cycle spend peak Dec-Jan.",
    ),
    "Engineering": SectorSeason(
        10, 3, 3,
        "Capital-goods ordering follows the Jul-Sep development budget release.",
    ),
    "Cable & Electrical": SectorSeason(
        7, 3, 3,
        "Power-sector cabling and switchgear orders peak Jul-Sep with the summer build.",
    ),
    "Oil Marketing": SectorSeason(
        12, 2, 2,
        "Winter furnace-oil and transport fuel demand peaks Dec-Jan; OMC margins firm into it.",
    ),
    "Investment Banks": SectorSeason(
        12, 2, 2,
        "Year-end portfolio rebalancing, dividend capture and NAV dressing peak Dec-Jan.",
    ),
    "Leasing": SectorSeason(
        7, 3, 2,
        "Auto-finance and equipment leasing disbursements peak Jul-Sep with the fiscal-year capex cycle.",
    ),
    "Property": SectorSeason(
        10, 3, 3,
        "Plot launches and real-estate bookings peak Oct-Dec ahead of the winter build season.",
    ),
    "REIT": SectorSeason(
        12, 3, 2,
        "Distribution announcements and year-end yield harvesting peak Dec-Feb.",
    ),
    "Miscellaneous": SectorSeason(
        12, 3, 2,
        "Conglomerate and holding-company books dress into the December fiscal close.",
    ),
    "Insurance": SectorSeason(
        1, 2, 2,
        "Premium renewals and year-end book clean-up peak Dec-Jan.",
    ),
    "Glass": SectorSeason(
        10, 3, 3,
        "Container and construction glass demand peaks Oct-Dec.",
    ),
    "Paper": SectorSeason(
        10, 3, 3,
        "Packaging demand peaks into the Oct-Dec dispatch season.",
    ),
    "Transport": SectorSeason(
        7, 3, 2,
        "Freight and shipping volumes peak Jul-Sep.",
    ),
    "Tobacco": SectorSeason(
        12, 2, 2,
        "Winter consumption and trade stocking peak Dec-Jan.",
    ),
    "Leather": SectorSeason(
        8, 3, 3,
        "Export leather order books peak Aug-Oct.",
    ),
    "Modaraba": SectorSeason(
        1, 3, 2,
        "Year-end distribution and renewal cycle peaks Dec-Feb.",
    ),
    "OTHER": SectorSeason(
        12, 3, 2,
        "Generic December fiscal-close tilt for unmapped names.",
    ),
}


def season_for(sector: str) -> SectorSeason:
    return SECTOR_SEASONS.get(sector, SECTOR_SEASONS["OTHER"])


# ---------------------------------------------------------------------------
# Small statistics helpers
# ---------------------------------------------------------------------------


def percentile(values: Sequence[float], q: float) -> Optional[float]:
    """Linear-interpolated percentile of an already-sorted sequence."""
    if not values:
        return None
    if len(values) == 1:
        return float(values[0])
    q = max(0.0, min(1.0, q))
    pos = (len(values) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(values) - 1)
    frac = pos - lo
    return float(values[lo]) + (values[hi] - values[lo]) * frac


def summarize_returns(returns: Iterable[float]) -> dict:
    """Win rate, central tendency and upside distribution for a return sample."""
    sample = sorted(float(r) for r in returns)
    n = len(sample)
    if n == 0:
        return {
            "samples": 0,
            "winRatePct": 0.0,
            "avgPct": 0.0,
            "medianPct": 0.0,
            "p25Pct": 0.0,
            "p75Pct": 0.0,
            "p90Pct": 0.0,
            "bestPct": 0.0,
            "worstPct": 0.0,
            "stdDevPct": 0.0,
        }
    wins = sum(1 for r in sample if r > 0)
    mean = sum(sample) / n
    variance = sum((r - mean) ** 2 for r in sample) / n if n > 1 else 0.0
    return {
        "samples": n,
        "winRatePct": round(wins / n * 100, 2),
        "avgPct": round(mean, 2),
        "medianPct": round(statistics.median(sample), 2),
        "p25Pct": round(percentile(sample, 0.25) or 0.0, 2),
        "p75Pct": round(percentile(sample, 0.75) or 0.0, 2),
        "p90Pct": round(percentile(sample, 0.90) or 0.0, 2),
        "bestPct": round(sample[-1], 2),
        "worstPct": round(sample[0], 2),
        "stdDevPct": round(variance ** 0.5, 2),
    }


def month_label(month: int) -> str:
    return MONTH_LABELS[(month - 1) % 12]


def _pct_change(current: float, past: float) -> Optional[float]:
    if past <= 0:
        return None
    return (current / past - 1.0) * 100.0


# ---------------------------------------------------------------------------
# Per-ticker seasonal analysis
# ---------------------------------------------------------------------------


def month_anchors(bars: List[DailyBar]) -> List[Tuple[int, int, int]]:
    """(year, month, session_index) of the first session of every month."""
    anchors: List[Tuple[int, int, int]] = []
    prev: Optional[Tuple[int, int]] = None
    for i, bar in enumerate(bars):
        key = (bar.trade_date.year, bar.trade_date.month)
        if key != prev:
            anchors.append((key[0], key[1], i))
            prev = key
    return anchors


def seasonal_month_table(bars: List[DailyBar]) -> Dict[int, dict]:
    """Pool forward returns by month-of-year for one ticker.

    Each calendar month contributes at most one observation per year, measured
    from that month's first session. 60/90-session forward returns need the tape
    to extend that far, so the final months of the series contribute fewer
    samples rather than truncated ones.
    """
    anchors = month_anchors(bars)
    n = len(bars)
    fwd60: Dict[int, List[float]] = {m: [] for m in range(1, 13)}
    fwd90: Dict[int, List[float]] = {m: [] for m in range(1, 13)}
    monthly: Dict[int, List[float]] = {m: [] for m in range(1, 13)}

    for pos, (_year, month, idx) in enumerate(anchors):
        close = bars[idx].close_price
        if idx + max(FORWARD_WINDOWS) < n:
            r60 = _pct_change(bars[idx + 60].close_price, close)
            r90 = _pct_change(bars[idx + 90].close_price, close)
            if r60 is not None:
                fwd60[month].append(r60)
            if r90 is not None:
                fwd90[month].append(r90)
        if pos + 1 < len(anchors):
            nxt = bars[anchors[pos + 1][2]].close_price
            mret = _pct_change(nxt, close)
            if mret is not None:
                monthly[month].append(mret)

    table: Dict[int, dict] = {}
    for month in range(1, 13):
        table[month] = {
            "month": month,
            "label": month_label(month),
            "forward60": summarize_returns(fwd60[month]),
            "forward90": summarize_returns(fwd90[month]),
            "monthReturn": summarize_returns(monthly[month]),
            # Raw samples stay internal so a window can be pooled exactly; they
            # are never serialized into the exported matrix.
            "_forward60": fwd60[month],
            "_forward90": fwd90[month],
        }
    return table


def position_profile(bars: List[DailyBar]) -> dict:
    """Where the latest close sits in its own 3-year range (the position filter)."""
    window = bars[-POSITION_LOOKBACK_BARS:] if len(bars) > POSITION_LOOKBACK_BARS else bars
    closes = [b.close_price for b in window if b.close_price > 0]
    if not closes:
        return {
            "rangePositionPct": 50.0,
            "drawdownFromHighPct": 0.0,
            "offLowPct": 0.0,
            "momentum60Pct": 0.0,
            "lookbackSessions": 0,
        }
    last = closes[-1]
    lo, hi = min(closes), max(closes)
    span = hi - lo
    # Share of the 3-year tape that traded at or below today's close: 0 = at the
    # cyclical low, 100 = at the cyclical high.
    at_or_below = sum(1 for c in closes if c <= last)
    range_pos = at_or_below / len(closes) * 100.0
    momentum60 = _pct_change(last, closes[-61]) if len(closes) > 61 else 0.0
    return {
        "rangePositionPct": round(range_pos, 2),
        "drawdownFromHighPct": round((last / hi - 1.0) * 100.0, 2) if hi > 0 else 0.0,
        "offLowPct": round((last / lo - 1.0) * 100.0, 2) if lo > 0 else 0.0,
        "rangeSpanPct": round(span / lo * 100.0, 2) if lo > 0 else 0.0,
        "momentum60Pct": round(momentum60 or 0.0, 2),
        "lookbackSessions": len(closes),
    }


def months_until_window(current_month: int, accumulation_months: Sequence[int]) -> int:
    """Months until the next accumulation window opens (0 while it is open)."""
    if current_month in accumulation_months:
        return 0
    for step in range(1, 13):
        if ((current_month - 1 + step) % 12) + 1 in accumulation_months:
            return step
    return 0


def ticker_status(
    current_month: int,
    accumulation_months: Sequence[int],
    position: dict,
) -> Tuple[str, str]:
    """Map calendar window + position filter onto the three live status flags."""
    in_window = current_month in accumulation_months
    range_pos = position["rangePositionPct"]
    dd = position["drawdownFromHighPct"]
    near_low = range_pos <= ACCUMULATION_MAX_RANGE_PCT and dd <= -abs(MAX_DRAWDOWN_FROM_HIGH_PCT) / 2

    if in_window and near_low:
        return (
            STATUS_ACTIVE,
            "Pre-season window open and price is still in the lower half of its 3-year range.",
        )
    if in_window:
        return (
            STATUS_OFF,
            "Calendar window is open but price is already extended above the accumulation zone.",
        )
    if months_until_window(current_month, accumulation_months) == 1:
        return (STATUS_WATCH, "Accumulation window opens next month.")
    return (STATUS_OFF, f"Next pre-season window in {months_until_window(current_month, accumulation_months)} month(s).")


def window_stats(month_table: Dict[int, dict], months: Sequence[int]) -> dict:
    """Aggregate a set of months into one forward-return profile."""
    fwd60: List[float] = []
    fwd90: List[float] = []
    # summarize_returns only needs the raw sample; rebuild it from the stored
    # averages is lossy, so the caller passes the pooled table instead.
    for month in months:
        row = month_table.get(month, {})
        fwd60.extend(row.get("_forward60", []))
        fwd90.extend(row.get("_forward90", []))
    return {
        "forward60": summarize_returns(fwd60),
        "forward90": summarize_returns(fwd90),
    }


def analyze_ticker(
    ticker: str,
    bars: List[DailyBar],
    sector: str,
    current_month: int,
) -> dict:
    """Full seasonality record for one ticker."""
    season = season_for(sector)
    peak_months = _month_window(season.peak_start, season.peak_length)
    accumulation_months = _lead_window(season.peak_start, season.accumulation_lead)

    table = seasonal_month_table(bars)
    position = position_profile(bars)
    status, note = ticker_status(current_month, accumulation_months, position)

    best_month = None
    for month in range(1, 13):
        row = table[month]["forward60"]
        if row["samples"] < 2:
            continue
        score = row["avgPct"] * (row["winRatePct"] / 100.0)
        if best_month is None or score > best_month[1]:
            best_month = (month, score)

    station = window_stats(table, accumulation_months)
    peak_stats = window_stats(table, peak_months)

    calendar = []
    for month in range(1, 13):
        row = table[month]
        calendar.append({
            "month": month,
            "label": row["label"],
            "isPeak": month in peak_months,
            "isAccumulation": month in accumulation_months,
            "samples": row["forward60"]["samples"],
            "winRatePct": row["forward60"]["winRatePct"],
            "avgForward60Pct": row["forward60"]["avgPct"],
            "avgForward90Pct": row["forward90"]["avgPct"],
        })

    return {
        "ticker": ticker,
        "sector": sector,
        "status": status,
        "phaseNote": note,
        "lastDate": bars[-1].trade_date.isoformat(),
        "lastClose": round(bars[-1].close_price, 2),
        "historyBars": len(bars),
        "yearsCovered": round(len(bars) / SESSIONS_PER_YEAR, 2),
        "peakMonths": [month_label(m) for m in peak_months],
        "accumulationMonths": [month_label(m) for m in accumulation_months],
        "monthsUntilWindow": months_until_window(current_month, accumulation_months),
        "accumulationWindowStats": station,
        "peakWindowStats": peak_stats,
        "bestMonth": month_label(best_month[0]) if best_month else None,
        "bestMonthScore": round(best_month[1], 2) if best_month else None,
        "position": position,
        "calendar": calendar,
        "statsByMonth": {
            str(m): {
                "label": table[m]["label"],
                "winRatePct": table[m]["forward60"]["winRatePct"],
                "avgForward60Pct": table[m]["forward60"]["avgPct"],
                "medianForward60Pct": table[m]["forward60"]["medianPct"],
                "avgForward90Pct": table[m]["forward90"]["avgPct"],
                "p25Forward60Pct": table[m]["forward60"]["p25Pct"],
                "p75Forward60Pct": table[m]["forward60"]["p75Pct"],
                "bestForward60Pct": table[m]["forward60"]["bestPct"],
                "worstForward60Pct": table[m]["forward60"]["worstPct"],
                "samples": table[m]["forward60"]["samples"],
                "monthReturnAvgPct": table[m]["monthReturn"]["avgPct"],
            }
            for m in range(1, 13)
        },
    }


# ---------------------------------------------------------------------------
# Sector assembly
# ---------------------------------------------------------------------------


def sector_calendar(records: List[dict]) -> List[dict]:
    """Pool members' month-of-year samples into one sector calendar."""
    pooled60: Dict[int, List[float]] = {m: [] for m in range(1, 13)}
    pooled90: Dict[int, List[float]] = {m: [] for m in range(1, 13)}
    for rec in records:
        for month in range(1, 13):
            row = rec["statsByMonth"][str(month)]
            # statsByMonth is summary-only; the pooled sector view uses the
            # per-ticker calendar averages weighted by their sample counts.
            n = row["samples"]
            if n:
                pooled60[month].extend([row["avgForward60Pct"]] * n)
                pooled90[month].extend([row["avgForward90Pct"]] * n)

    out = []
    for month in range(1, 13):
        out.append({
            "month": month,
            "label": month_label(month),
            "samples": len(pooled60[month]),
            "winRatePct": _pooled_win_rate(records, month),
            "avgForward60Pct": (
                round(sum(pooled60[month]) / len(pooled60[month]), 2)
                if pooled60[month] else 0.0
            ),
            "avgForward90Pct": (
                round(sum(pooled90[month]) / len(pooled90[month]), 2)
                if pooled90[month] else 0.0
            ),
        })
    return out


def _pooled_win_rate(records: List[dict], month: int) -> float:
    """Sample-weighted win rate across members for one month-of-year."""
    total = 0
    wins = 0.0
    for rec in records:
        row = rec["statsByMonth"][str(month)]
        n = row["samples"]
        if not n:
            continue
        total += n
        wins += row["winRatePct"] / 100.0 * n
    return round(wins / total * 100, 2) if total else 0.0


def pool_window_stats(records: List[dict], months: Sequence[int], horizon: str) -> dict:
    """Pooled forward stats across members over a set of calendar months."""
    avg_key = "avgForward60Pct" if horizon == "forward60" else "avgForward90Pct"
    samples: List[float] = []
    wins = 0.0
    total = 0
    for rec in records:
        for month in months:
            row = rec["statsByMonth"][str(month)]
            n = row["samples"]
            if not n:
                continue
            samples.extend([row[avg_key]] * n)
            wins += row["winRatePct"] / 100.0 * n
            total += n
    if not samples:
        return summarize_returns([])
    ordered = sorted(samples)
    mean = sum(ordered) / len(ordered)
    variance = sum((r - mean) ** 2 for r in ordered) / len(ordered)
    return {
        "samples": total,
        "winRatePct": round(wins / total * 100, 2),
        "avgPct": round(mean, 2),
        "medianPct": round(statistics.median(ordered), 2),
        "p25Pct": round(percentile(ordered, 0.25) or 0.0, 2),
        "p75Pct": round(percentile(ordered, 0.75) or 0.0, 2),
        "p90Pct": round(percentile(ordered, 0.90) or 0.0, 2),
        "bestPct": round(ordered[-1], 2),
        "worstPct": round(ordered[0], 2),
        "stdDevPct": round(variance ** 0.5, 2),
    }


def sector_status(counts: Dict[str, int], members: int) -> str:
    if members == 0:
        return STATUS_OFF
    if counts.get(STATUS_ACTIVE, 0) / members >= 0.30:
        return STATUS_ACTIVE
    if counts.get(STATUS_ACTIVE, 0) or counts.get(STATUS_WATCH, 0):
        return STATUS_WATCH
    return STATUS_OFF


def build_seasonality_matrix(
    bars_by_ticker: Union[Mapping[str, List[DailyBar]], Iterable[Tuple[str, List[DailyBar]]]],
    current_month: Optional[int] = None,
    min_bars: int = MIN_HISTORY_BARS,
) -> dict:
    """Build the full seasonality matrix payload from a tape.

    Accepts either a ticker -> bars mapping or an iterable of (ticker, bars)
    pairs. The streaming form is what keeps the engine usable on a 650-name
    universe: each ticker is analysed and then dropped, so only the compact
    per-ticker records stay resident.
    """
    now = datetime.now(timezone.utc)
    if current_month is None:
        # PSX trades on PKT (UTC+5); the local session month is what matters.
        from datetime import timedelta
        current_month = (now + timedelta(hours=5)).month

    if isinstance(bars_by_ticker, Mapping):
        pairs: Iterable[Tuple[str, List[DailyBar]]] = sorted(
            bars_by_ticker.items(), key=lambda pair: pair[0]
        )
    else:
        pairs = bars_by_ticker

    records_by_sector: Dict[str, List[dict]] = {}
    analyzed = 0
    sessions_from: Optional[str] = None
    sessions_to: Optional[str] = None
    for ticker, bars in pairs:
        if len(bars) < min_bars:
            continue
        analyzed += 1
        first = bars[0].trade_date.isoformat()
        last = bars[-1].trade_date.isoformat()
        if sessions_from is None or first < sessions_from:
            sessions_from = first
        if sessions_to is None or last > sessions_to:
            sessions_to = last
        sector = DEFAULT_SECTOR_MAP.get(ticker, "OTHER")
        record = analyze_ticker(ticker, bars, sector, current_month)
        records_by_sector.setdefault(sector, []).append(record)

    sectors: List[dict] = []
    for sector in sorted(records_by_sector):
        records = records_by_sector[sector]
        season = season_for(sector)
        peak_months = _month_window(season.peak_start, season.peak_length)
        accumulation_months = _lead_window(season.peak_start, season.accumulation_lead)

        counts: Dict[str, int] = {}
        for rec in records:
            counts[rec["status"]] = counts.get(rec["status"], 0) + 1

        status = sector_status(counts, len(records))
        window60 = pool_window_stats(records, accumulation_months, "forward60")
        window90 = pool_window_stats(records, accumulation_months, "forward90")
        peak60 = pool_window_stats(records, peak_months, "forward60")

        calendar = sector_calendar(records)
        for row in calendar:
            row["isPeak"] = row["month"] in peak_months
            row["isAccumulation"] = row["month"] in accumulation_months

        best = max(
            (row for row in calendar if row["samples"] > 0),
            key=lambda row: row["avgForward60Pct"],
            default=None,
        )

        sectors.append({
            "sector": sector,
            "status": status,
            "members": len(records),
            "activeCount": counts.get(STATUS_ACTIVE, 0),
            "watchCount": counts.get(STATUS_WATCH, 0),
            "offSeasonCount": counts.get(STATUS_OFF, 0),
            "peakMonths": [month_label(m) for m in peak_months],
            "accumulationMonths": [month_label(m) for m in accumulation_months],
            "rationale": season.rationale,
            "bestMonth": best["label"] if best else None,
            "bestMonthAvgForward60Pct": best["avgForward60Pct"] if best else 0.0,
            "accumulationWindow": {
                "forward60": window60,
                "forward90": window90,
            },
            "peakWindow": {"forward60": peak60},
            "calendar": calendar,
            "tickers": sorted(
                records,
                key=lambda r: (
                    0 if r["status"] == STATUS_ACTIVE else 1 if r["status"] == STATUS_WATCH else 2,
                    r["position"]["rangePositionPct"],
                ),
            ),
        })

    active_windows = [
        {
            "ticker": rec["ticker"],
            "sector": rec["sector"],
            "status": rec["status"],
            "monthsUntilWindow": rec["monthsUntilWindow"],
            "rangePositionPct": rec["position"]["rangePositionPct"],
            "drawdownFromHighPct": rec["position"]["drawdownFromHighPct"],
            "winRate60Pct": rec["accumulationWindowStats"]["forward60"]["winRatePct"],
            "avgForward60Pct": rec["accumulationWindowStats"]["forward60"]["avgPct"],
            "avgForward90Pct": rec["accumulationWindowStats"]["forward90"]["avgPct"],
            "lastClose": rec["lastClose"],
            "lastDate": rec["lastDate"],
        }
        for sector_row in sectors
        for rec in sector_row["tickers"]
        if rec["status"] == STATUS_ACTIVE
    ]
    active_windows.sort(key=lambda row: row["sector"])

    session_from = sessions_from
    session_to = sessions_to

    return {
        "generatedAt": now.isoformat(timespec="seconds"),
        "meta": {
            "name": "PSX Sector Seasonality & Cyclical Alpha Matrix",
            "currentMonth": current_month,
            "currentMonthLabel": month_label(current_month),
            "forwardWindows": list(FORWARD_WINDOWS),
            "minHistoryBars": min_bars,
            "positionFilter": {
                "lookbackSessions": POSITION_LOOKBACK_BARS,
                "accumulationMaxRangePct": ACCUMULATION_MAX_RANGE_PCT,
                "watchMaxRangePct": WATCH_MAX_RANGE_PCT,
                "maxDrawdownFromHighPct": MAX_DRAWDOWN_FROM_HIGH_PCT,
            },
            "statusDefinitions": {
                STATUS_ACTIVE: "Calendar accumulation window open and price in the lower 45% of its 3-year range.",
                STATUS_WATCH: "Accumulation window opens next month.",
                STATUS_OFF: "No accumulation window open; price may also be extended.",
            },
            "method": (
                "One observation per calendar month (first session), forward "
                "60/90-session return, pooled per month-of-year across up to 15 "
                "years; overlapping windows mean samples are not independent."
            ),
        },
        "sessionRange": {
            "from": session_from,
            "to": session_to,
            "tickers": analyzed,
            "sectors": len(sectors),
        },
        "summary": {
            "tickersAnalyzed": analyzed,
            "activeWindows": len(active_windows),
            "sectorsActive": sum(1 for s in sectors if s["status"] == STATUS_ACTIVE),
            "sectorsWatching": sum(1 for s in sectors if s["status"] == STATUS_WATCH),
            "sectorsOffSeason": sum(1 for s in sectors if s["status"] == STATUS_OFF),
        },
        "activeWindows": active_windows,
        "sectors": sectors,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="PSX sector seasonality & cyclical accumulation matrix")
    parser.add_argument("--db", type=str, default=None, help="SQLite store (default: backend/psx_history.db)")
    parser.add_argument("--out", type=str, default=None, help="output JSON path")
    parser.add_argument("--min-bars", type=int, default=MIN_HISTORY_BARS,
                        help="minimum stored sessions for a ticker to enter the matrix")
    parser.add_argument("--month", type=int, default=None, help="override current month (1-12) for the status flags")
    args = parser.parse_args()

    db_path = args.db or str(get_db_path())
    min_bars = max(120, args.min_bars)
    rejected = [0]
    stream = iter_validated_bars_by_ticker(db_path, min_bars=min_bars, rejected=rejected)
    log.info("streaming %s (min %d bars per ticker)", db_path, min_bars)

    payload = build_seasonality_matrix(
        stream,
        current_month=args.month,
        min_bars=min_bars,
    )
    log.info("%d tickers analysed, %d rejected rows", payload["summary"]["tickersAnalyzed"], rejected[0])

    out_path = Path(args.out) if args.out else DEFAULT_OUTPUT
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    summary = payload["summary"]
    log.info("=".join([""] + ["-"] * 60 + [""]))
    log.info("SECTOR SEASONALITY & CYCLICAL ALPHA MATRIX")
    log.info("  current month   : %s", payload["meta"]["currentMonthLabel"])
    log.info("  session range   : %s -> %s", payload["sessionRange"]["from"], payload["sessionRange"]["to"])
    log.info("  tickers         : %d across %d sectors", summary["tickersAnalyzed"], payload["sessionRange"]["sectors"])
    log.info("  active windows  : %d", summary["activeWindows"])
    log.info("  sector status   : %d active / %d watch / %d off-season",
             summary["sectorsActive"], summary["sectorsWatching"], summary["sectorsOffSeason"])
    for row in payload["activeWindows"]:
        log.info("    %-8s %-10s rng %5.1f%%  win60 %5.1f%%  fwd60 %+6.2f%%",
                 row["ticker"], row["sector"], row["rangePositionPct"],
                 row["winRate60Pct"], row["avgForward60Pct"])
    log.info("=".join([""] + ["-"] * 60 + [""]))
    log.info("  written         : %s", out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
