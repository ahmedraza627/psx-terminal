"""System verdict engine - the Action Desk's three certified verdicts.

Writes exactly one psx_system_verdicts row per horizon per session
(PK trade_date, horizon), idempotently upserted:

  SHORT_TERM (1-5 days)   BUY   Institutional Pullback & Dry-up
                                 Accumulation engine (replaces the 16.9%
                                 breakout chase). Gate stack, in order:
                                   A. Liquidity/solvency pre-filter:
                                      5-day avg turnover >= PKR 20M, PE > 0,
                                      close >= PKR 10 (no sub-10 penny traps).
                                   B. Macro tape gate (below) must not be
                                      DEFENSIVE_CASH.
                                   C. Trend: close > 20D SMA AND 20D SMA >
                                      50D SMA (confirmed bull trend).
                                   D. Sector flow: FIPI + MUTUAL FUNDS +
                                      BANKS net positive across the 3-session
                                      window for the ticker's sector.
                                   E. Trigger: retraced 1-3 sessions from the
                                      10-day high, within 3.5% of the 20D
                                      SMA, on volume < 0.85x the 20D average.
                                 Execution levels + fixed-fractional sizing
                                 (1.5% portfolio risk) are stamped on the row.
  MID_TERM  (2-8 weeks)   BUY   Sector with the largest 5-session net
                                 institutional absorption while retail
                                 distributed; the leader is that sector's
                                 highest-turnover ticker with positive
                                 5-session performance.
  LONG_TERM (avoid/risk)  AVOID The retail-heaviest sector where
                                 institutions are net negative, flagged via
                                 its highest-turnover priced member. Falls
                                 back to the breadth trap (advance/decline <
                                 0.8 while KSE-100 closed green -> KSE100)
                                 when no trap-sector ticker is priced.

Macro tape gate (_macro_tape_state) - stamped on every row as
macro_tape_state and used to block SHORT_TERM buys:
  RISK_ON        KSE-100 above its 50D SMA and A/D ratio >= 1.0.
  DEFENSIVE_CASH KSE-100 below its 50D SMA and A/D ratio < 0.7
                 (blocks new SHORT_TERM buys - cash preservation).
  NEUTRAL        everything else.
Honest-data rules: when KSE-100 history is too thin to form a 50D SMA, or
the A/D ratio is unverifiable, the state is NEUTRAL - never fabricated.

Participant vocabulary: institutions = FOREIGN TOTAL + FIPI + BANKS +
MUTUAL FUNDS. NCCPL's FIPI aggregate is stored as the "FOREIGN TOTAL"
rollup on current scraper generations (and as literal "FIPI" on legacy
rows), so both labels are honoured. Retail is detected by the substring
"INDIVIDUAL" at the session level (covers both INDIVIDUAL and
INDIVIDUALS labels).

Honest-data rules (house convention): a horizon with no certified
candidate is SKIPPED - never fabricated, never defaulted. The frontend
renders the missing horizon as its own idle state.
"""

from __future__ import annotations

import logging
import os
from collections import defaultdict
from datetime import date, timedelta
from typing import Any, Optional

from pipeline import db
from pipeline.alerts.telegram import send_daily_dispatch
from pipeline.analytics.outcome_tracker import log_active_setups
from pipeline.analytics.sector_matrix import compute_sector_matrix, get_ticker_sector_status
import math

from pipeline.backtest.engine import run_quick_backtest
from pipeline.http_client import http_get

# Re-export the EOD tail window from db so callers that want the constant can
# read it from the decision engine namespace (used by the synthetic verify probe).
ENGINE_UNIVERSE_DAYS = db._ENGINE_UNIVERSE_DAYS


LOGGER = logging.getLogger(__name__)

VOLUME_SMA_WINDOW = int(os.getenv("VERDICT_VOLUME_SMA_WINDOW", "20"))
FLOW_WINDOW_SESSIONS = int(os.getenv("VERDICT_FLOW_WINDOW_SESSIONS", "5"))
BREADTH_RED_RATIO = float(os.getenv("VERDICT_BREADTH_RED_RATIO", "0.8"))

# High-Win-Rate Pullback Engine (SHORT_TERM) - institutional swing setup.
# Buys a quiet pullback into rising support in a confirmed uptrend, aims
# for a swift TP1 at the recent swing high with tight invalidation.
PULLBACK_SMA_PROXIMITY = 0.035   # close within 3.5% of 20D SMA = at support
DRYUP_VOLUME_RATIO = 0.85        # volume < 0.85x 20D avg = seller exhaustion
SWING_LOW_LOOKBACK = 3           # tight invalidation: 3-session swing low
TP1_LOOKBACK = 10                # TP1 target = recent 10-day swing high
SHORT_MIN_RR = 1.2               # TP1 floored to a 1:1.2 reward/risk
SHORT_MIN_RISK_PCT = 0.005       # sanity floor on stop distance
SHORT_MAX_RISK_PCT = 0.04        # hard 4% stop cap: a wider stop is tightened

# Phase 3 - MID_TERM TP1 optimization: swap the greedy extended-target
# swing model (measured ~34% win rate at un-hittable 1:8 R:R) for a
# realistic structural TP1 with a mathematically bounded reward/risk.
MID_STOP_LOOKBACK = 5            # structural invalidation: 5-session swing low
MID_STOP_ATR_MULT = 1.5          # stop floor leg: entry - 1.5 x ATR
MID_TP1_LOOKBACK = 20            # TP1 = recent 20-day high
MID_TP1_ATR_MULT = 2.0           # TP1 alt leg: entry + 2.0 x ATR (closer wins)
MID_MIN_RR = 1.5                 # bounded reward/risk floor
MID_MAX_RR = 2.5                 # bounded reward/risk cap (kills the 1:8 target)
MID_MIN_RISK_PCT = 0.005         # sanity floor on stop distance (flat tape)

# Phase 4 - PSX circuit-breaker guardrail: a name that CLOSED at its lower
# circuit limit (close == low and session change <= -7.4%) has no exit
# liquidity and is rejected from every BUY horizon.
LOWER_LOCK_CHANGE_PCT = -7.4

# --------------------------------------------------------------------------- #
# Phase 2 - Institutional Alpha Engine: liquidity/solvency pre-filter, macro
# tape gate, and fixed-fractional (1.5% risk) position sizing.
# --------------------------------------------------------------------------- #
# Solvency + turnover floor: PSX penny operators (< PKR 10) lock on lower
# circuits, and a thin book cannot absorb an institutional order - both are
# un-tradeable at institutional size. 5-day avg turnover is close x volume.
LIQUIDITY_TURNOVER_FLOOR_PKR = 20_000_000.0
MIN_PRICE_PKR = 10.0
TURNOVER_WINDOW = 5

# Fixed-fractional sizing: risk 1.5% of portfolio equity per trade, sized on
# the stop distance, capped at 15% of the portfolio in any one name.
RISK_BUDGET_PCT = 1.5
MAX_ALLOC_PCT = 15.0
# Order may not exceed 2% of the 20D average volume (clean exit liquidity).
VOLUME_PARTICIPATION = 0.02

# Macro tape gate thresholds (KSE-100 50D SMA + advance/decline ratio).
TAPE_RISK_ON = "RISK_ON"
TAPE_DEFENSIVE = "DEFENSIVE_CASH"
TAPE_NEUTRAL = "NEUTRAL"
TAPE_MA_WINDOW = 50
TAPE_RISK_ON_AD = 1.0
TAPE_DEFENSIVE_AD = 0.7

INST_FLOW_TYPES = {"BANKS", "MUTUAL FUNDS", "FIPI", "FOREIGN TOTAL"}
RETAIL_FLOW_TYPES = {"INDIVIDUALS"}

# Non-actionable NCCPL aggregate buckets - they are market rollups, not
# investable sectors, and would always dominate a raw "largest net" pick.
AGGREGATE_SECTORS = ("ALL OTHER SECTORS", "TOTAL", "MISCELLANEOUS")

# Fundamental gate (strict): a BUY candidate must be profitable on its
# latest screener snapshot (PE > 0 present). Loss-making or unpriced
# tickers are skipped and the next best candidate is certified instead.
FUNDAMENTAL_SCORE_LABEL = "PROFITABLE (PE > 0)"
FUNDAMENTAL_UNVERIFIED = "UNVERIFIED"

HORIZON_SHORT = "SHORT_TERM"
HORIZON_MID = "MID_TERM"
HORIZON_LONG = "LONG_TERM"

# Index symbols that may sit in psx_daily_eod alongside equities; they are
# never universe members for breadth / turnover picks.
INDEX_TICKERS = {"KSE100", "KSE-100", "KSE 100", "100INDEX", "KSE30"}


# --------------------------------------------------------------------------- #
# Series helpers                                                              #
# --------------------------------------------------------------------------- #
def _parse_day(value: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None


def _session_series(
    eod_rows: list[dict[str, Any]],
) -> dict[str, list[tuple[date, float, float]]]:
    """ticker -> [(day, close, volume)] sorted ascending."""
    series: dict[str, list[tuple[date, float, float]]] = defaultdict(list)
    for row in eod_rows:
        day = _parse_day(row.get("trade_date"))
        close = row.get("close_price")
        volume = row.get("volume")
        if day is None or close is None or volume is None:
            continue
        try:
            series[row["ticker"]].append((day, float(close), float(volume)))
        except (TypeError, ValueError):
            continue
    for points in series.values():
        points.sort()  # rows arrive trade_date DESC; sort fixes the order
    return series


def _session_dates_desc(series: dict[str, list[tuple[date, float, float]]]) -> list[date]:
    """All stored sessions, newest first (across the universe)."""
    return sorted({p[0] for points in series.values() for p in points}, reverse=True)


def _point_at(
    points: list[tuple[date, float, float]], day: date
) -> Optional[tuple[float, float]]:
    """(close, volume) at an exact session, or None when absent."""
    for p_day, close, volume in reversed(points):
        if p_day == day:
            return close, volume
    return None


def _close_at(points: list[tuple[date, float, float]], day: date) -> Optional[float]:
    found = _point_at(points, day)
    return found[0] if found else None


# --------------------------------------------------------------------------- #
# Flow helpers                                                                #
# --------------------------------------------------------------------------- #
def _net_of(row: dict[str, Any]) -> float:
    try:
        return float(row.get("net_pkr") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _market_wide_net(
    flow_rows: list[dict[str, Any]], session_date: date
) -> dict[str, float]:
    """participant -> market-wide net for one session.

    Prefers the market-wide rows (sector_name == "ALL"); falls back to
    summing that session's per-sector rows when the rollup rows are absent.
    """
    day_rows = [
        r for r in flow_rows if _parse_day(r.get("trade_date")) == session_date
    ]
    all_rows = [
        r for r in day_rows if str(r.get("sector_name") or "").upper() == "ALL"
    ]
    source = all_rows if all_rows else day_rows
    nets: dict[str, float] = defaultdict(float)
    for row in source:
        participant = str(row.get("participant_type") or "").strip().upper()
        if participant:
            nets[participant] += _net_of(row)
    return nets


def _flow_sessions_desc(flow_rows: list[dict[str, Any]], session_date: date) -> list[date]:
    """Distinct stored flow dates <= session_date, newest first."""
    days = {
        d
        for d in (_parse_day(r.get("trade_date")) for r in flow_rows)
        if d is not None and d <= session_date
    }
    return sorted(days, reverse=True)


def _is_aggregate_sector(label: str) -> bool:
    """True for NCCPL rollup buckets that name no investable sector."""
    return any(token in label for token in AGGREGATE_SECTORS)


def _sector_flow_totals(
    flow_rows: list[dict[str, Any]], days: list[date]
) -> dict[str, dict[str, float]]:
    """sector -> participant -> cumulative net over the given flow sessions.

    Market-wide rows ("ALL") and non-actionable aggregate buckets are
    excluded - only real sectors compete for the accumulation / trap picks.
    """
    wanted = set(days)
    totals: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for row in flow_rows:
        day = _parse_day(row.get("trade_date"))
        if day not in wanted:
            continue
        sector = str(row.get("sector_name") or "").strip().upper()
        participant = str(row.get("participant_type") or "").strip().upper()
        if not sector or sector == "ALL" or not participant:
            continue  # market-wide rows belong to no sector
        if _is_aggregate_sector(sector):
            continue  # rollup buckets are not investable sectors
        totals[sector][participant] += _net_of(row)
    return totals


def _sector_map(fundamental_rows: list[dict[str, Any]]) -> dict[str, str]:
    """ticker -> sector label (upper) from psx_fundamentals.

    Uses the LATEST KNOWN sector per ticker across all stored snapshots,
    not just the newest date - a stale or missing newest snapshot must not
    empty the mapping and starve the leader picks. Placeholder labels
    ("UNKNOWN", written by the scraper when the DPS sectorwise map fetch
    fails) are skipped too: the 2026-09-23..2026-10-09 snapshots are 100%
    UNKNOWN and were masking the real labels underneath them.
    """
    mapping: dict[str, str] = {}
    best_day: dict[str, date] = {}
    for row in fundamental_rows:
        ticker = row.get("ticker")
        sector = str(row.get("sector_name") or "").strip().upper()
        day = _parse_day(row.get("trade_date"))
        if not ticker or not sector or day is None:
            continue
        if sector == "UNKNOWN":
            continue  # scraper placeholder, not a sector - keep older real label
        previous = best_day.get(ticker)
        if previous is None or day >= previous:
            best_day[ticker] = day
            mapping[ticker] = sector
    return mapping


def _pe_map(fundamentals: list[dict[str, Any]]) -> dict[str, Optional[float]]:
    """ticker -> pe_ratio from its NEWEST screener snapshot.

    Strict by design: the latest snapshot's value wins even when it is
    null - the fundamental gate must see "no data" as "no data", not as
    a stale profitable reading from months ago.
    """
    mapping: dict[str, Optional[float]] = {}
    best_day: dict[str, date] = {}
    for row in fundamentals:
        ticker = row.get("ticker")
        day = _parse_day(row.get("trade_date"))
        if not ticker or day is None:
            continue
        previous = best_day.get(ticker)
        if previous is None or day >= previous:
            best_day[ticker] = day
            pe = row.get("pe_ratio")
            try:
                mapping[ticker] = float(pe) if pe is not None else None
            except (TypeError, ValueError):
                mapping[ticker] = None
    return mapping


def _is_profitable(pe_map: dict[str, Optional[float]], ticker: str) -> bool:
    """True only when the latest snapshot proves PE > 0 (strict gate)."""
    pe = pe_map.get(ticker)
    return pe is not None and pe > 0


def _sector_matches(nccpl_sector: str, mapped_sector: str) -> bool:
    """Tolerant sector join between NCCPL labels and fundamentals labels.

    The two sources drift ("OIL & GAS" vs "OIL & GAS EXPLORATION",
    "TECH" vs "TECHNOLOGY", NCCPL's "POWER GENERATION AND DISTRIBUTION"
    vs DPS's "POWER GENERATION & DISTRIBUTION"), so an equality-only
    join silently drops every member. '&' is normalised to "AND" and
    whitespace collapsed; exact match wins, otherwise containment on the
    normalised labels counts as the same sector family.
    """
    def norm(s: str) -> str:
        return " ".join(s.upper().replace("&", " AND ").split())

    a, b = norm(nccpl_sector), norm(mapped_sector)
    return a == b or a in b or b in a


def _inst_retail_nets(nets: dict[str, float]) -> tuple[float, float]:
    inst = sum(nets.get(p, 0.0) for p in INST_FLOW_TYPES)
    retail = sum(nets.get(p, 0.0) for p in RETAIL_FLOW_TYPES)
    return inst, retail


def _institutional_accumulation(
    flow_rows: list[dict[str, Any]], session_date: date
) -> bool:
    """True when institutions net BULLISH on the session or a 3-session window.

    Pullback entries are only valid while smart money is still accumulating:
    positive net (BANKS + MUTUAL FUNDS + FIPI/FOREIGN TOTAL) on the session
    itself, or summed over the trailing 3 flow sessions when the single
    session is flat/absent. Honest: no flow rows at all -> False (skip).
    """
    days = _flow_sessions_desc(flow_rows, session_date)[:3]
    if not days:
        return False
    totals: dict[str, float] = defaultdict(float)
    wanted = set(days)
    for row in flow_rows:
        if _parse_day(row.get("trade_date")) not in wanted:
            continue
        participant = str(row.get("participant_type") or "").strip().upper()
        if participant in INST_FLOW_TYPES:
            totals[participant] += _net_of(row)
    session_inst = sum(
        v for k, v in _market_wide_net(flow_rows, session_date).items()
        if k in INST_FLOW_TYPES
    )
    window_inst = sum(totals.values())
    return session_inst > 0 or window_inst > 0


# --------------------------------------------------------------------------- #
# Benchmark (KSE-100)                                                         #
# --------------------------------------------------------------------------- #
def _kse100_change_pct(
    session_date: date,
    prior_date: date,
    series: dict[str, list[tuple[date, float, float]]],
) -> Optional[float]:
    """KSE-100 close-over-close % for the session pair; None when unverifiable.

    Tier 1: stored index rows in psx_daily_eod (house legacy convention).
    Tier 2: the live DPS timeseries endpoint. Never a fabricated proxy.
    """
    for candidate in ("KSE100", "KSE-100", "KSE 100", "100INDEX"):
        points = series.get(candidate)
        if not points:
            continue
        now = _close_at(points, session_date)
        before = _close_at(points, prior_date)
        if now is not None and before is not None and before > 0:
            return (now / before - 1.0) * 100.0

    try:
        response = http_get("https://dps.psx.com.pk/timeseries/eod/KSE100", timeout=25.0)
        payload = response.json()
    except Exception as exc:  # noqa: BLE001 - benchmark down = unverifiable
        LOGGER.warning("decision engine: KSE100 DPS timeseries unavailable: %s", exc)
        return None
    closes: dict[date, float] = {}
    for row in payload.get("data") if isinstance(payload, dict) else []:
        try:
            closes[date.fromtimestamp(int(row[0]))] = float(row[1])
        except (TypeError, ValueError, IndexError):
            continue
    now = closes.get(session_date)
    before = closes.get(prior_date)
    if now is not None and before is not None and before > 0:
        return (now / before - 1.0) * 100.0
    return None


# Per-process cache of the DPS KSE-100 timeseries (full history in one
# GET). None = not fetched yet; [] = source dead this run.
_kse100_series_cache: Optional[list[tuple[date, float]]] = None


def _kse100_index_series(
    series: dict[str, list[tuple[date, float, float]]],
) -> list[tuple[date, float]]:
    """KSE-100 closes (day, close), oldest-first; [] when unverifiable.

    The macro tape gate needs a 50-session baseline, so this resolves the
    index with the same discipline as _kse100_change_pct, extended with
    the RRG engine's certified market-proxy fallback:
      Tier 1: stored index rows in psx_daily_eod (any legacy alias), used
        when they carry a full TAPE_MA_WINDOW baseline.
      Tier 2: the live DPS timeseries endpoint - the source the RRG engine
        and the KSE-100 breadth verdict already trust. (As of 2026-10 the
        DPS index endpoint 404s, so production lands on Tier 3.)
      Tier 3: the house equal-weight market proxy - the same certified
        chain the RRG engine falls back to: level_t = level_{t-1} x (1 +
        mean cross-sectional close-over-close return) from the stored
        universe closes already in memory. Real closes only, no forward
        filling, no invented prices; below TAPE_MA_WINDOW chained
        sessions it yields [] and the tape gate honestly reports NEUTRAL.
    """
    global _kse100_series_cache
    # Tier 1: stored alias rows with a full 50-session baseline.
    for candidate in ("KSE100", "KSE-100", "KSE 100", "100INDEX"):
        points = series.get(candidate)
        if not points:
            continue
        closes = sorted(
            (day, close) for day, close, _vol in points if close > 0
        )
        if len(closes) >= TAPE_MA_WINDOW:
            LOGGER.info("macro tape: KSE-100 series from stored %s rows", candidate)
            return closes
    # Tier 2: live DPS timeseries, cached per process.
    if _kse100_series_cache is None:
        try:
            response = http_get(
                "https://dps.psx.com.pk/timeseries/eod/KSE100", timeout=25.0
            )
            payload = response.json()
            closes_by_day: dict[date, float] = {}
            for row in payload.get("data") if isinstance(payload, dict) else []:
                try:
                    closes_by_day[date.fromtimestamp(int(row[0]))] = float(row[1])
                except (TypeError, ValueError, IndexError):
                    continue
            _kse100_series_cache = sorted(
                (day, close) for day, close in closes_by_day.items() if close > 0
            )
        except Exception as exc:  # noqa: BLE001 - dead source -> Tier 3
            LOGGER.warning(
                "macro tape: KSE100 DPS timeseries unavailable: %s", exc
            )
            _kse100_series_cache = []
    if len(_kse100_series_cache) >= TAPE_MA_WINDOW:
        LOGGER.info("macro tape: KSE-100 series from DPS live timeseries")
        return _kse100_series_cache
    # Tier 3: equal-weight market proxy chained from stored universe
    # closes (mirror of sector_rotation._aggregate_market_proxy, fed from
    # the in-memory series so the engine makes no extra DB round-trip).
    by_day: dict[date, dict[str, float]] = {}
    for ticker, points in series.items():
        if ticker.upper() in INDEX_TICKERS:
            continue
        for day, close, _vol in points:
            if close > 0:
                by_day.setdefault(day, {})[ticker] = close
    levels: list[tuple[date, float]] = []
    level: Optional[float] = None
    days = sorted(by_day)
    for prev_day, cur_day in zip(days, days[1:]):
        prev_map, cur_map = by_day[prev_day], by_day[cur_day]
        rets = [
            cur_map[t] / prev_map[t] - 1.0
            for t in cur_map.keys() & prev_map.keys()
            if prev_map[t] > 0
        ]
        if not rets:
            continue
        mean_ret = sum(rets) / len(rets)
        level = 100.0 if level is None else level * (1.0 + mean_ret)
        levels.append((cur_day, round(level, 4)))
    if len(levels) >= TAPE_MA_WINDOW:
        LOGGER.info(
            "macro tape: KSE-100 series unobtainable; using the certified "
            "equal-weight market proxy (%d chained sessions)",
            len(levels),
        )
        return levels
    LOGGER.warning(
        "macro tape: no KSE-100 series available (stored/DPS/proxy all "
        "short); tape gate falls back to NEUTRAL"
    )
    return []


# --------------------------------------------------------------------------- #
# Horizon verdicts                                                            #
# --------------------------------------------------------------------------- #
def _lower_lock_tickers(
    eod_rows: list[dict[str, Any]], session_date: date
) -> set[str]:
    """Tickers that CLOSED at their lower circuit limit on ``session_date``.

    Lock test (documented, Phase 4): close_price == low_price AND the
    session change vs the prior stored close is <= -7.4%. A locked book
    cannot be entered or exited at institutional size, so such names are
    rejected from every BUY candidate set. Order-independent over the
    stored rows (keeps the newest prior close per ticker explicitly).
    """
    latest: dict[str, dict[str, Any]] = {}
    prior: dict[str, tuple[date, float]] = {}
    for row in eod_rows:
        try:
            day = _parse_day(row.get("trade_date"))
            ticker = str(row.get("ticker") or "")
            close = float(row.get("close_price") or 0.0)
        except (TypeError, ValueError):
            continue
        if not ticker or close <= 0 or day is None or day > session_date:
            continue
        if day == session_date:
            latest[ticker] = row
        elif ticker not in prior or day > prior[ticker][0]:
            prior[ticker] = (day, close)
    locked: set[str] = set()
    for ticker, row in latest.items():
        try:
            close = float(row.get("close_price") or 0.0)
            low_raw = row.get("low_price")
            low = float(low_raw) if low_raw is not None else None
        except (TypeError, ValueError):
            continue
        base = prior.get(ticker)
        if low is None or close <= 0 or low <= 0 or base is None:
            continue
        base_close = base[1]
        if base_close <= 0:
            continue
        change_pct = (close - base_close) / base_close * 100.0
        # close == low to the paisa; a locked session pins both at the limit.
        if abs(close - low) <= 0.01 and change_pct <= LOWER_LOCK_CHANGE_PCT:
            locked.add(ticker)
    return locked


def _short_term_verdict(
    session_date: date,
    prior_date: date,
    series: dict[str, list[tuple[date, float, float]]],
    flow_rows: list[dict[str, Any]],
    sector_by_ticker: dict[str, str],
    tape_state: str,
    pe_map: dict[str, Optional[float]],
    locked_tickers: Optional[set[str]] = None,
) -> Optional[dict[str, Any]]:
    """Institutional Pullback & Dry-up Accumulation engine (Phase 2).

    Replaces the 16.9% breakout chase with a quiet-dip-into-support setup,
    gated by liquidity/solvency, the macro tape, a confirmed bull trend and
    sector-level institutional flow. See the module docstring for the full
    A-E gate stack. Execution: entry = session close; stop = the LOWER of
    the 3-session swing low and the 1.0 x ATR floor, hardened to a maximum
    4% risk; TP1 = the 10-day swing high, floored to a 1:1.2 reward/risk.
    """
    if tape_state == TAPE_DEFENSIVE:
        LOGGER.info(
            "decision engine %s: macro tape DEFENSIVE_CASH - preserving "
            "cash, no new SHORT_TERM buys",
            session_date,
        )
        return None

    # Sector -> 3-session institutional net (FIPI + MUTUAL FUNDS + BANKS).
    window_days = _flow_sessions_desc(flow_rows, session_date)[:3]
    sector_flows = _sector_flow_totals(flow_rows, window_days) if window_days else {}

    # Sector rotation matrix gate: a DISTRIBUTION-sector ticker is rejected
    # outright; a LEADING ticker receives priority over NEUTRAL in the
    # candidate ranking. Names that are not in the authoritative matrix are
    # treated as NEUTRAL (the matrix is a floor, not a ceiling).
    def _sector_status_for(ticker: str) -> dict[str, Any]:
        return get_ticker_sector_status(ticker, sector_matrix)

    # (proximity, dry_up_pct, ticker) - tightest setup wins; gates run first.
    candidates: list[tuple[float, float, str]] = []
    for ticker, points in series.items():
        if ticker.upper() in INDEX_TICKERS:
            continue
        # F. Circuit-breaker guardrail (Phase 4): a lower-lock close is
        # untradeable at size - never a BUY candidate.
        if locked_tickers and ticker in locked_tickers:
            continue

        # Sector rotation gate (Phase 5C): reject DISTRIBUTION-sector
        # candidates and remember the sector status for priority ranking.
        sector_info = _sector_status_for(ticker)
        if sector_info.get("status") == "DISTRIBUTION":
            LOGGER.debug(
                "decision engine %s: %s rejected (sector=%s, status=%s)",
                session_date, ticker,
                sector_info.get("sector") or "UNKNOWN",
                sector_info.get("status"),
            )
            continue
        window = [p for p in points if p[0] <= session_date]
        if len(window) < VOLUME_SMA_WINDOW:
            continue  # honest: no full 20D baseline, no verdict
        closes = [p[1] for p in window]
        volumes = [p[2] for p in window]
        close = closes[-1]
        volume = volumes[-1]
        if close <= 0 or volume <= 0:
            continue

        # A. Solvency + liquidity floor (PE is checked at pick time).
        if not _liquidity_ok(points, session_date):
            continue

        # C. Confirmed bull trend: close > 20D SMA and 20D SMA > 50D SMA.
        sma20 = sum(closes[-VOLUME_SMA_WINDOW:]) / VOLUME_SMA_WINDOW
        if sma20 <= 0 or close <= sma20:
            continue
        if len(closes) < 50:
            continue  # Phase 2: a confirmed trend needs the full 50D leg
        sma50 = sum(closes[-50:]) / 50
        if sma50 <= 0 or not sma20 > sma50:
            continue

        # D. Sector institutional flow positive across the 3-session window.
        sector = sector_by_ticker.get(ticker)
        nets = sector_flows.get(sector) if sector else None
        inst_net = sum(nets.get(p, 0.0) for p in INST_FLOW_TYPES) if nets else 0.0
        if inst_net <= 0:
            continue

        # E1. Testing support, not extended: within 3.5% above the 20D SMA.
        proximity = (close - sma20) / sma20
        if proximity > PULLBACK_SMA_PROXIMITY:
            continue

        # E2. Retraced 1-3 sessions from the recent 10-day high.
        recent = closes[-TP1_LOOKBACK:]
        peak_offset = max(range(len(recent)), key=lambda k: recent[k])
        sessions_since_peak = len(recent) - 1 - peak_offset
        if recent[peak_offset] <= close or not 1 <= sessions_since_peak <= 3:
            continue  # still at the high (no pullback) or too stale

        # E3. Volume dry-up: exhaustion of selling pressure.
        vol_sma20 = sum(volumes[-VOLUME_SMA_WINDOW:]) / VOLUME_SMA_WINDOW
        if vol_sma20 <= 0 or volume >= DRYUP_VOLUME_RATIO * vol_sma20:
            continue
        dry_up_pct = (1.0 - volume / vol_sma20) * 100.0

        candidates.append((proximity, dry_up_pct, ticker))

    # A (fundamentals): walk tightest-first to the first strictly profitable
    # name. A loss-maker or unpriced ticker is skipped, never certified.
    # Sector priority: among comparable setups, LEADING-sector tickers are
    # walked before NEUTRAL-sector tickers (DISTRIBUTION already filtered out).
    def _candidate_sort_key(item: tuple[float, float, str]) -> tuple[float, float, int, float]:
        proximity, dry_up, ticker = item
        sector_info = _sector_status_for(ticker)
        status = sector_info.get("status")
        rank = sector_info.get("rank") or 999
        status_rank = 0 if status == "LEADING" else 1  # LEADING first
        return (proximity, dry_up, status_rank, rank)

    best_ticker: Optional[str] = None
    best_dry_up = 0.0
    best_sector_info: dict[str, Any] = {}
    for proximity, dry_up, ticker in sorted(candidates, key=_candidate_sort_key):
        if _is_profitable(pe_map, ticker):
            best_ticker = ticker
            best_dry_up = dry_up
            best_sector_info = _sector_status_for(ticker)
            break

    if best_ticker is None:
        if candidates:
            LOGGER.info(
                "decision engine %s: %d liquid pullback setup(s) but none "
                "profitable (PE > 0); SHORT_TERM skipped",
                session_date, len(candidates),
            )
        else:
            LOGGER.info(
                "decision engine %s: no qualifying pullback setup (tape=%s); "
                "SHORT_TERM skipped",
                session_date, tape_state,
            )
        return None

    levels = _execution_levels(
        {"horizon": HORIZON_SHORT, "ticker": best_ticker}, session_date, series
    )
    entry = levels.get("entry_ref")
    stop = levels.get("stop_loss")
    sizing: dict[str, Any] = {
        "suggested_alloc_pct": None,
        "max_volume_capacity_shares": None,
    }
    if entry is not None and stop is not None:
        points = series.get(best_ticker) or []
        volumes = [p[2] for p in points if p[0] <= session_date]
        alloc, capacity = _position_sizing(float(entry), float(stop), volumes)
        sizing["suggested_alloc_pct"] = alloc
        sizing["max_volume_capacity_shares"] = capacity

    return {
        "trade_date": session_date.isoformat(),
        "horizon": HORIZON_SHORT,
        "direction": "BUY",
        "ticker": best_ticker,
        "logic_text": (
            "Institutional pullback into 20D SMA support with volume "
            f"dry-up (-{best_dry_up:.0f}% vs 20D avg) in confirmed uptrend."
        ),
        **sizing,
        "sector_name": best_sector_info.get("sector"),
        "sector_status": best_sector_info.get("status"),
        "sector_rank": best_sector_info.get("rank"),
    }


def _leader_in_sector(
    sector: str,
    session_date: date,
    series: dict[str, list[tuple[date, float, float]]],
    sector_by_ticker: dict[str, str],
    *,
    require_positive_5d: bool,
    window_start: Optional[date],
    pe_map: Optional[dict[str, Optional[float]]] = None,
    require_profitable: bool = False,
    locked_tickers: Optional[set[str]] = None,
) -> Optional[str]:
    """Highest session-turnover ticker mapped to ``sector``.

    With require_positive_5d, only members closing above their window-start
    close qualify - the leader must be performing, not just churning.
    With require_profitable, only PE > 0 members compete (BUY horizons);
    AVOID verdicts deliberately skip the gate - the trap ticker's
    fundamentals are irrelevant to the warning.
    """
    best_ticker: Optional[str] = None
    best_turnover = -1.0
    for ticker, mapped in sector_by_ticker.items():
        if not _sector_matches(sector, mapped):
            continue
        # Phase 4 circuit-breaker guardrail: lower-lock closes are
        # untradeable at size - never a BUY leader (AVOID verdicts keep
        # scanning: the trap warning still applies to a locked name).
        if locked_tickers and ticker in locked_tickers:
            continue
        if require_profitable and not _is_profitable(pe_map or {}, ticker):
            continue  # strict gate: loss-making / unpriced never certified
        points = series.get(ticker)
        if not points:
            continue
        session_point = _point_at(points, session_date)
        if session_point is None:
            continue
        close, volume = session_point
        if close <= 0:
            continue
        if require_positive_5d:
            if window_start is None:
                continue
            start_close = _close_at(points, window_start)
            if start_close is None or start_close <= 0 or close <= start_close:
                continue
        turnover = close * max(volume, 0.0)
        if turnover > best_turnover:
            best_ticker = ticker
            best_turnover = turnover
    return best_ticker


def _mid_term_verdict(
    session_date: date,
    sessions_desc: list[date],
    series: dict[str, list[tuple[date, float, float]]],
    flow_rows: list[dict[str, Any]],
    sector_by_ticker: dict[str, str],
    pe_map: dict[str, Optional[float]],
    locked_tickers: Optional[set[str]] = None,
) -> Optional[dict[str, Any]]:
    """Sector with the largest 5-session institutional absorption while
    retail distributed; leader = highest-turnover member with positive 5D.

    Institutional execution levels: entry = latest session close;
    stop = the lower of the recent 5-session swing low and 1.5 x ATR
    below entry; target = TP1 = the recent 20-day high or entry + 2.0 x
    ATR (whichever is closer), with reward/risk bounded to [1.5, 2.5]
    (Phase 3: realistic structural target, not the greedy 52-week
    resistance chase that stamped ~1:8 R:R and a ~34% win rate).
    """
    window_days = _flow_sessions_desc(flow_rows, session_date)[:FLOW_WINDOW_SESSIONS]
    if len(window_days) < 2:
        LOGGER.info("decision engine: <2 flow sessions for %s; MID_TERM skipped", session_date)
        return None
    totals = _sector_flow_totals(flow_rows, window_days)

    best_sector: Optional[str] = None
    best_inst = 0.0
    for sector, nets in totals.items():
        inst_net, retail_net = _inst_retail_nets(nets)
        if inst_net > 0 and retail_net < 0 and inst_net > best_inst:
            best_sector = sector
            best_inst = inst_net
    if best_sector is None:
        LOGGER.info("decision engine %s: no absorbed sector; MID_TERM skipped", session_date)
        return None

    # 5-session performance window: the 5th newest stored session <= T.
    prior = [d for d in sessions_desc if d < session_date]
    window_start = prior[FLOW_WINDOW_SESSIONS - 1] if len(prior) >= FLOW_WINDOW_SESSIONS else None
    leader = _leader_in_sector(
        best_sector,
        session_date,
        series,
        sector_by_ticker,
        require_positive_5d=True,
        window_start=window_start,
        pe_map=pe_map,
        require_profitable=True,
        locked_tickers=locked_tickers,
    )
    if leader is None:
        # Sparse history (no usable 5D window) or no positive performer must
        # not drop the sector entirely: fall back to the session's top
        # turnover ticker from psx_daily_eod (fix for the 2026-10-07 skip).
        leader = _leader_in_sector(
            best_sector,
            session_date,
            series,
            sector_by_ticker,
            require_positive_5d=False,
            window_start=None,
            pe_map=pe_map,
            require_profitable=True,
            locked_tickers=locked_tickers,
        )
    if leader is None:
        LOGGER.info(
            "decision engine %s: sector %s has no priced ticker at the session; "
            "MID_TERM skipped",
            session_date, best_sector,
        )
        return None
    leader_sector_info = get_ticker_sector_status(leader, sector_matrix)
    return {
        "trade_date": session_date.isoformat(),
        "horizon": HORIZON_MID,
        "direction": "BUY",
        "ticker": leader,
        "logic_text": "Sustained institutional net absorption across 5 sessions while retail distributed.",
        "sector_name": leader_sector_info.get("sector"),
        "sector_status": leader_sector_info.get("status"),
        "sector_rank": leader_sector_info.get("rank"),
    }


def _breadth_verdict(
    session_date: date,
    prior_date: date,
    series: dict[str, list[tuple[date, float, float]]],
) -> Optional[dict[str, Any]]:
    """Breadth trap: adv/dec < 0.8 while KSE-100 closed green -> KSE100."""
    adv = dec = 0
    for ticker, points in series.items():
        if ticker.upper() in INDEX_TICKERS:
            continue
        now = _close_at(points, session_date)
        before = _close_at(points, prior_date)
        if now is None or before is None or now <= 0 or before <= 0:
            continue
        if now > before:
            adv += 1
        elif now < before:
            dec += 1
    ratio = (adv / dec) if dec > 0 else None
    if ratio is None or ratio >= BREADTH_RED_RATIO:
        return None
    change = _kse100_change_pct(session_date, prior_date, series)
    if change is None or change <= 0:
        return None
    return {
        "trade_date": session_date.isoformat(),
        "horizon": HORIZON_LONG,
        "direction": "AVOID",
        "ticker": "KSE100",
        "logic_text": (
            f"Breadth trap: advance/decline at {ratio:.2f} while "
            f"KSE-100 closed green (+{change:.2f}%) - the rally "
            "is not confirmed by the tape."
        ),
    }


def _long_term_verdict(
    session_date: date,
    sessions_desc: list[date],
    series: dict[str, list[tuple[date, float, float]]],
    flow_rows: list[dict[str, Any]],
    sector_by_ticker: dict[str, str],
) -> Optional[dict[str, Any]]:
    """Retail-trap sector first; KSE-100 breadth trap as the direct fallback.

    v2 (fix for the 2026-10-07 all-skip): when no trap-sector ticker is
    priced in psx_daily_eod (or the mapping starves), the horizon falls
    straight back to the breadth check instead of skipping outright.
    """
    window_days = _flow_sessions_desc(flow_rows, session_date)[:FLOW_WINDOW_SESSIONS]
    totals = _sector_flow_totals(flow_rows, window_days)
    trap_sector: Optional[str] = None
    most_retail_buying = 0.0
    for sector, nets in totals.items():
        inst_net, retail_net = _inst_retail_nets(nets)
        if inst_net >= 0 or retail_net <= 0:
            continue  # want institutions net negative AND retail net buying
        if retail_net > most_retail_buying:
            trap_sector = sector
            most_retail_buying = retail_net
    if trap_sector is not None:
        leader = _leader_in_sector(
            trap_sector,
            session_date,
            series,
            sector_by_ticker,
            require_positive_5d=False,
            window_start=None,
        )
        if leader is not None:
            return {
                "trade_date": session_date.isoformat(),
                "horizon": HORIZON_LONG,
                "direction": "AVOID",
                "ticker": leader,
                "logic_text": "Retail trap active: institutions net distributing into retail liquidity.",
            }
        LOGGER.info(
            "decision engine %s: trap sector %s has no priced ticker; "
            "falling back to breadth",
            session_date, trap_sector,
        )
    else:
        LOGGER.info(
            "decision engine %s: no retail-trap sector; checking breadth", session_date
        )

    prior = [d for d in sessions_desc if d < session_date]
    if not prior:
        LOGGER.info("decision engine %s: no prior session; LONG_TERM skipped", session_date)
        return None
    breadth = _breadth_verdict(session_date, prior[0], series)
    if breadth is None:
        LOGGER.info("decision engine %s: no LONG_TERM candidate certified", session_date)
    return breadth


# --------------------------------------------------------------------------- #
# Market regime (macro gate) + execution levels
# --------------------------------------------------------------------------- #
def _regime_status(
    session_date: date,
    prior_date: date,
    series: dict[str, list[tuple[date, float, float]]],
) -> str:
    """Macro gate: DEFENSIVE_CASH when the tape is breaking down, else NORMAL.

    Severe breakdown = advance/decline < 0.6 AND KSE-100 below its 20-day
    SMA. Never fabricates a regime from missing data.
    """
    adv = dec = 0
    # Points are (day, close, volume): the SMA leg must average CLOSES (p[1])
    # - averaging p[2] would smear volumes into a price test.
    window = [p for p in series.get("KSE100") or [] if p[0] <= session_date][-20:]
    sma20 = sum(p[1] for p in window) / len(window) if len(window) == 20 else 0.0
    for ticker, points in series.items():
        if ticker.upper() in INDEX_TICKERS:
            continue
        now = _close_at(points, session_date)
        before = _close_at(points, prior_date)
        if now is None or before is None or now <= 0 or before <= 0:
            continue
        if now > before:
            adv += 1
        else:
            dec += 1
    ratio = (adv / dec) if dec > 0 else None
    if ratio is None or ratio >= 0.6:
        return "NORMAL"
    now = _close_at(series.get("KSE100") or [], session_date)
    if now is None or sma20 <= 0 or now > sma20:
        return "NORMAL"
    return "DEFENSIVE_CASH"


def _advance_decline_ratio(
    session_date: date,
    prior_date: date,
    series: dict[str, list[tuple[date, float, float]]],
) -> Optional[float]:
    """Session advance/decline ratio (advancers / decliners), or None.

    None means unverifiable (no comparable prior closes, or zero decliners
    with an empty advancer set) - the macro gate treats that as NEUTRAL.
    """
    adv = dec = 0
    for ticker, points in series.items():
        if ticker.upper() in INDEX_TICKERS:
            continue
        now = _close_at(points, session_date)
        before = _close_at(points, prior_date)
        if now is None or before is None or now <= 0 or before <= 0:
            continue
        if now > before:
            adv += 1
        elif now < before:
            dec += 1
    if adv == 0 and dec == 0:
        return None
    if dec == 0:
        return float("inf")  # pure advance tape: strongly risk-on
    return adv / dec


def _macro_tape_state(
    session_date: date,
    prior_date: date,
    series: dict[str, list[tuple[date, float, float]]],
) -> str:
    """Macro tape gate: RISK_ON / NEUTRAL / DEFENSIVE_CASH.

    KSE-100 positioning vs its 50-day SMA, cross-checked with the session
    advance/decline ratio:
      RISK_ON        KSE-100 > 50D SMA and A/D >= 1.0
      DEFENSIVE_CASH KSE-100 < 50D SMA and A/D < 0.7
      NEUTRAL        otherwise (including any unverifiable leg)

    KSE-100 history resolves via _kse100_index_series: stored index rows
    when they carry a 50-session baseline, else the live DPS timeseries
    (the same source the KSE-100 breadth verdict already trusts).

    Honest-data rule: a thin KSE-100 history (< 50 sessions) or an
    uncomputable A/D ratio yields NEUTRAL - the engine never invents a
    macro state to force a BUY through.
    """
    index = _kse100_index_series(series)
    window = [close for day, close in index if day <= session_date]
    now = window[-1] if window else None
    if now is None or len(window) < TAPE_MA_WINDOW:
        LOGGER.info(
            "macro tape: KSE-100 history insufficient for %s (%d sessions "
            "< %d); state=NEUTRAL",
            session_date, len(window), TAPE_MA_WINDOW,
        )
        return TAPE_NEUTRAL
    sma50 = sum(window[-TAPE_MA_WINDOW:]) / TAPE_MA_WINDOW
    ad = _advance_decline_ratio(session_date, prior_date, series)
    above = now > sma50
    if ad is None:
        return TAPE_NEUTRAL
    if above and ad >= TAPE_RISK_ON_AD:
        return TAPE_RISK_ON
    if not above and ad < TAPE_DEFENSIVE_AD:
        return TAPE_DEFENSIVE
    return TAPE_NEUTRAL


def _liquidity_ok(
    points: list[tuple[date, float, float]],
    session_date: date,
) -> bool:
    """Solvency + turnover floor: close >= PKR 10 and 5-day avg turnover
    >= PKR 20M (the institutional exit-liquidity / circuit-lock filter).

    Points are (day, close, volume). Honest: fewer than TURNOVER_WINDOW
    sessions in the window fails the floor (no certified baseline, no buy).
    """
    window = [p for p in points if p[0] <= session_date][-TURNOVER_WINDOW:]
    if len(window) < TURNOVER_WINDOW:
        return False
    close = window[-1][1]
    if close < MIN_PRICE_PKR:
        return False
    turnover = sum(p[1] * p[2] for p in window) / TURNOVER_WINDOW
    return turnover >= LIQUIDITY_TURNOVER_FLOOR_PKR


def _atr_pct(closes: list[float]) -> Optional[float]:
    """14-session-style ATR% proxy from the stored tape.

    The stored EOD tape carries no high/low, so the engine's documented ATR
    proxy is the mean absolute close-to-close change over the last 4 sessions
    (ATR_PROXY_SESSIONS). We scale it to a 14-session reading by resolving the
    mean absolute change across the trailing 14 closes where available, then
    express it as a % of the latest close. Returns None when history is too
    thin to read.
    """
    if len(closes) < 2:
        return None
    window = closes[-14:] if len(closes) >= 14 else closes
    changes = [abs(window[k] - window[k - 1]) for k in range(1, len(window))]
    if not changes:
        return None
    atr = sum(changes) / len(changes)
    close = closes[-1]
    if close <= 0:
        return None
    return (atr / close) * 100.0


def _position_sizing(
    entry: float,
    stop: float,
    volumes: list[float],
    closes: list[float],
) -> tuple[Optional[int], Optional[int]]:
    """Inverse-volatility position sizing from the 14-session ATR%.

    Highly volatile tickers automatically receive smaller allocations
    (5-8%); low-volatility blue chips receive full size (12-15%).

    raw_alloc = 15.0 * (2.5 / max(atr_pct, 1.5)), clamped to [5, 15],
    returned as an integer percent. Volume capacity caps the order at 2% of
    the 20-day average volume so the exit stays liquid.

    Returns (alloc_pct_int, capacity_shares). Both None when sizing cannot
    be resolved (no valid ATR reading) - never a fabricated size.
    """
    if entry <= 0:
        return None, None
    atr_pct = _atr_pct(closes)
    if atr_pct is None:
        return None, None
    raw_alloc = 15.0 * (2.5 / max(atr_pct, 1.5))
    # Integer percent, rounded half away from zero so a 12.5% raw reading
    # lands on 13% rather than Python's banker's-round 12 - the desk wants
    # .5 up for position sizing, not toward the even multiple.
    alloc_pct = int(max(5, min(15, math.floor(raw_alloc + 0.5))))  # type: ignore[arg-type]
    if not volumes:
        return alloc_pct, None
    avg_vol20 = sum(volumes[-VOLUME_SMA_WINDOW:]) / len(volumes[-VOLUME_SMA_WINDOW:])
    capacity = int(avg_vol20 * VOLUME_PARTICIPATION)
    return alloc_pct, (capacity if capacity > 0 else None)


def _execution_levels(
    verdict: dict[str, Any],
    session_date: date,
    series: dict[str, list[tuple[date, float, float]]],
) -> dict[str, Any]:
    """Precise execution levels per horizon (institutional risk math).

    Points are (day, close, volume) - the stored tape carries no high/low,
    so the ATR leg is the mean absolute close-to-close change (documented
    proxy, never a fabricated number).

      SHORT_TERM: entry = session close; stop = the LOWER (structural
        support) of the 3-session swing low and 1.0 x ATR below close;
        target = the recent 10-day swing high (TP1), floored so it pays
        at least 1:1.2 reward/risk. (LOWER, not the tighter/higher leg:
        a stop hugging entry sends the TP1 floor to an unreachable
        ~12-177x R:R and collapses the win rate - measured on ZAL.)
      MID_TERM:   entry = session close; stop = the LOWER of the recent
        5-session swing low and 1.5 x ATR below close (Phase 3 kept the
        structural stop); target = TP1 = the recent 20-day high or
        entry + 2.0 x ATR, whichever sits CLOSER to entry, with the
        reward/risk mathematically bounded to [1.5, 2.5]. The bounds
        replace the greedy trailing-52-week-resistance target that
        produced un-hittable 1:8 ratios and a ~34% historical win rate;
        the tighter structural TP1 is what lifts MID_TERM toward the
        65-75% win-rate band.
      LONG_TERM is an AVOID/risk verdict - it has no entry, so it carries
        honest null levels (the desk renders no grid for it).

    Missing / unpriced session data -> all-null levels, never invented.
    """
    empty = {
        "entry_ref": None,
        "stop_loss": None,
        "target_price": None,
        "risk_reward_ratio": None,
        "suggested_alloc_pct": None,
        "max_volume_capacity_shares": None,
    }
    if verdict["horizon"] not in (HORIZON_SHORT, HORIZON_MID):
        return empty
    eod = series.get(verdict["ticker"])
    if not eod:
        return dict(empty)
    session_point = _point_at(eod, session_date)
    if session_point is None:
        return dict(empty)
    close, _ = session_point
    if close <= 0:
        return dict(empty)

    window = [p for p in eod if p[0] <= session_date]
    closes3 = [p[1] for p in window[-3:] if p[1] > 0]
    if not closes3:
        return dict(empty)
    swing_low = min(closes3)

    # Mean absolute close-to-close change over the last 4 sessions - the
    # documented ATR proxy shared by both tradeable horizons (the stored
    # tape carries no high/low, so a true ATR cannot be computed).
    closes4 = [p[1] for p in window[-4:] if p[1] > 0]
    changes = [abs(closes4[k] - closes4[k - 1]) for k in range(1, len(closes4))]
    atr = sum(changes) / len(changes) if changes else 0.0

    if verdict["horizon"] == HORIZON_SHORT:
        # Structural support: the LOWER of the 3-session swing low and the
        # 1.0 x ATR floor. (The higher leg would pin risk a hair under
        # entry, sending TP1 out of reach and collapsing the win rate -
        # measured on ZAL.) Phase 2 hardening: cap total risk at 4% of
        # entry so a wide swing cannot produce an un-tradeable stop.
        stops = [swing_low] + ([close - atr] if atr > 0 else [])
        stop = min(s for s in stops if s > 0)
        floor = close * (1.0 - SHORT_MAX_RISK_PCT)
        stop = max(stop, floor)  # hard 4% risk cap
        if close - stop < 0.005 * close:
            # Flat tape: the swing low hugs the entry. Widen to a 0.5%
            # structural floor rather than certify a zero-risk stop.
            stop = close - 0.005 * close
        risk = close - stop
        # TP1 = the recent 10-day swing high, floored so it pays 1:1.2.
        high10 = max(p[1] for p in window[-TP1_LOOKBACK:] if p[1] > 0)
        target = max(high10, close + SHORT_MIN_RR * risk)
        # Inverse-volatility sizing from the 14-session ATR% (2% volume cap).
        volumes = [p[2] for p in window if p[2] is not None and p[2] > 0]
        closes_for_sizing = [p[1] for p in window if p[1] is not None and p[1] > 0]
        alloc, capacity = _position_sizing(close, stop, volumes, closes_for_sizing)
    else:
        # MID_TERM (Phase 3): realistic structural TP1 instead of the
        # greedy 52-week-resistance chase that stamped un-hittable 1:8
        # targets (measured ~34% win rate). Stop stays structural: the
        # LOWER of the recent 5-session swing low and the 1.5 x ATR floor
        # beneath entry (the lower leg - a stop hugging entry leaves no
        # room for a structural target, same reasoning as SHORT_TERM).
        closes5 = [p[1] for p in window[-MID_STOP_LOOKBACK:] if p[1] > 0]
        swing_low5 = min(closes5)
        stops = [swing_low5] + (
            [close - MID_STOP_ATR_MULT * atr] if atr > 0 else []
        )
        stop = min(s for s in stops if s > 0)
        if close - stop < MID_MIN_RISK_PCT * close:
            stop = close - MID_MIN_RISK_PCT * close  # flat tape: real risk unit
        risk = close - stop
        # TP1 = the recent 20-day high or entry + 2.0 x ATR, whichever sits
        # closer to entry; the result is then bounded to [1.5, 2.5] R:R so
        # a runaway target can never be stamped again. (The 1.5 floor
        # outranks the structural legs only on a flat tape pinned at the
        # 20-day high - a zero-reward target is not tradeable.)
        high20 = max(p[1] for p in window[-MID_TP1_LOOKBACK:] if p[1] > 0)
        reward = high20 - close
        if atr > 0:
            reward = min(reward, MID_TP1_ATR_MULT * atr)
        rr = reward / risk if risk > 0 else MID_MIN_RR
        rr = max(MID_MIN_RR, min(rr, MID_MAX_RR))
        target = close + rr * risk

        # Inverse-volatility sizing for the MID_TERM leader as well: the
        # sector-absorption pick still gets a dynamic ATR%-based allocation
        # (5-15%), persisted as an integer percent.
        volumes = [p[2] for p in window if p[2] is not None and p[2] > 0]
        closes_for_sizing = [p[1] for p in window if p[1] is not None and p[1] > 0]
        alloc, capacity = _position_sizing(close, stop, volumes, closes_for_sizing)

    risked = max(close - stop, 0.01)  # spec floor: never divide below 0.01
    return {
        "entry_ref": round(close, 2),
        "stop_loss": round(stop, 2),
        "target_price": round(target, 2),
        "risk_reward_ratio": round((target - close) / risked, 2),
        "suggested_alloc_pct": alloc,
        "max_volume_capacity_shares": capacity,
    }


# --------------------------------------------------------------------------- #
# Entry point                                                                 #
# --------------------------------------------------------------------------- #
def run_decision_engine(session_date: Optional[date] = None) -> int:
    """Compute the three certified system verdicts and upsert them.

    Idempotent on (trade_date, horizon): re-running the pipeline for the
    same session overwrites the same rows, never duplicates them.
    Returns the number of rows written.
    """
    trade_date = session_date or date.today()
    # One process-level DPS probe per run at most; failures fall through to
    # the equal-weight market proxy inside _kse100_index_series.
    #
    # Universe tail: a small calendar-bounded window for the candidate
    # screens (breadth, 20D highs, 5-day pullbacks, ATR). The deep
    # historical backtest still runs on the single qualified leader ticker
    # (fetch_eod_for_ticker, ticker=eq.<leader>), which is already fast.
    tail_end = trade_date.isoformat()
    tail_start = (
        trade_date - timedelta(days=ENGINE_UNIVERSE_DAYS)
    ).isoformat()
    eod_rows = db.fetch_eod_in_window(tail_start, tail_end)
    if not eod_rows:
        LOGGER.warning("decision engine: no EOD history; aborting")
        return 0
    flow_rows = db.fetch_recent_flows(days=FLOW_WINDOW_SESSIONS + 5)
    # real_sectors_only: the newest snapshots can be a wall of UNKNOWN
    # placeholders (DPS sectorwise scrape down); ask for the rows that
    # actually carry a sector so the ticker -> sector map can reach the
    # last good snapshot.
    fundamentals = db.fetch_recent_fundamentals(real_sectors_only=True)
    # The PE gate reads the NEWEST snapshots, which are often a wall of
    # UNKNOWN sectors while still carrying fresh PEs - so the gate gets
    # its own unfiltered fetch (3k newest rows cover every ticker).
    pe_rows = db.fetch_recent_fundamentals(real_sectors_only=False)

    series = _session_series(eod_rows)
    sessions_desc = _session_dates_desc(series)
    if trade_date not in sessions_desc:
        LOGGER.warning(
            "decision engine: %s has no stored EOD session; aborting", trade_date
        )
        return 0
    sector_by_ticker = _sector_map(fundamentals)
    pe_map = _pe_map(pe_rows)
    # Phase 4 circuit-breaker guardrail: names that closed at their lower
    # circuit limit are rejected from every BUY candidate set.
    locked_tickers = _lower_lock_tickers(eod_rows, trade_date)

    # Sector rotation & smart-money matrix: classify every sector in the
    # loaded tape as LEADING / NEUTRAL / DISTRIBUTION so individual setups are
    # gated by institutional-flow + momentum confluence, not stock-level alone.
    sector_matrix = compute_sector_matrix(
        trade_date, eod_rows=eod_rows, flow_rows=flow_rows, sector_by_ticker=sector_by_ticker,
    )

    # Market regime + macro tape: the gates every row is stamped with.
    prior = [d for d in sessions_desc if d < trade_date]
    prior_date = prior[0] if prior else trade_date
    regime = _regime_status(trade_date, prior_date, series)
    tape_state = _macro_tape_state(trade_date, prior_date, series)

    def with_execution(v: dict[str, Any]) -> dict[str, Any]:
        levels = _execution_levels(v, trade_date, series)
        v.update(levels)
        v["regime_status"] = regime
        v["macro_tape_state"] = tape_state
        # Sector rotation matrix: attach the sector tag to every verdict
        # so the frontend and the Telegram brief can show where the
        # certified setup sits in the institutional-flow lattice.
        sector_info = get_ticker_sector_status(v["ticker"], sector_matrix)

        # Fundamental gate result + historical edge proof. BUY verdicts
        # already passed the strict PE gate in candidate selection; AVOID
        # verdicts are warnings, so they stay UNVERIFIED and unbacktested.
        profitable = _is_profitable(pe_map, v["ticker"])
        v["fundamental_score"] = (
            FUNDAMENTAL_SCORE_LABEL if profitable else FUNDAMENTAL_UNVERIFIED
        )
        if sector_info:
            v["sector_name"] = sector_info.get("sector")
            v["sector_status"] = sector_info.get("status")
            v["sector_rank"] = sector_info.get("rank")
        v["historical_win_rate"] = None
        if v["direction"] == "BUY" and profitable:
            try:
                result = run_quick_backtest(v["ticker"], v["horizon"], trade_date)
            except Exception as exc:  # noqa: BLE001 - backtest must never kill verdicts
                LOGGER.warning(
                    "decision engine %s: backtest %s failed: %s",
                    trade_date, v["ticker"], exc,
                )
                result = None
            if result is not None:
                v["historical_win_rate"] = result["win_rate"]
        return v

    verdicts = (
        _short_term_verdict(
            trade_date, prior_date, series, flow_rows, sector_by_ticker, tape_state, pe_map,
            locked_tickers
        ),
        _mid_term_verdict(
            trade_date, sessions_desc, series, flow_rows, sector_by_ticker, pe_map,
            locked_tickers
        ),
        _long_term_verdict(trade_date, sessions_desc, series, flow_rows, sector_by_ticker),
    )
    rows = [with_execution(v) for v in verdicts if v is not None]
    if not rows:
        LOGGER.warning(
            "decision engine %s: no horizon had a certified candidate", trade_date
        )
        return 0
    written = db.upsert_records(
        "psx_system_verdicts", rows, on_conflict="trade_date,horizon"
    )
    # Retire horizons that were SKIPPED this run so a prior session's row
    # for the same horizon is not rendered as current by the fallback. The
    # purge is scoped to this trade_date only.
    all_horizons = (HORIZON_SHORT, HORIZON_MID, HORIZON_LONG)
    written_horizons = {r["horizon"] for r in rows}
    retired = [h for h in all_horizons if h not in written_horizons]
    if retired:
        db.purge_verdict_horizons(trade_date.isoformat(), retired)
    # Phase 5B - setup logging for the ML outcome dataset: persist an OPEN
    # row per active BUY verdict so the post-close outcome tracker can evaluate
    # real exits. Idempotent on (verdict_date, horizon, ticker); never overwrites
    # an already-resolved outcome.
    try:
        log_active_setups(rows, trade_date, tape_state, series)
    except Exception as exc:  # noqa: BLE001 - outcome logging is advisory only
        LOGGER.warning(
            "decision engine %s: outcome setup logging failed: %s", trade_date, exc
        )

    # Phase 4 - Telegram dispatch: strictly best-effort. Verdicts are
    # already stored, so delivery problems never fail the pipeline run.
    try:
        send_daily_dispatch(trade_date, rows, tape_state)
    except Exception as exc:  # noqa: BLE001 - dispatch is advisory only
        LOGGER.warning(
            "decision engine %s: telegram dispatch failed: %s", trade_date, exc
        )
    LOGGER.info(
        "decision engine %s: %d/%d verdicts stored (regime=%s, tape=%s) (%s)",
        trade_date,
        written,
        len(rows),
        regime,
        tape_state,
        ", ".join(r["horizon"] for r in rows),
    )
    return written
