"""System verdict engine - the Action Desk's three certified verdicts.

Writes exactly one psx_system_verdicts row per horizon per session
(PK trade_date, horizon), idempotently upserted:

  SHORT_TERM (1-5 days)   BUY   Session volume > 2.5x the 20-day SMA,
                                 cross-checked against the session's NCCPL
                                 participant flows: institutions net buying
                                 while individuals net selling. The highest-
                                 volume qualifying ticker carries the row.
  MID_TERM  (2-8 weeks)   BUY   Sector with the largest 5-session net
                                 institutional absorption while retail
                                 distributed; the leader is that sector's
                                 highest-turnover ticker with positive
                                 5-session performance.
  LONG_TERM (avoid/risk)  AVOID Breadth trap: advance/decline < 0.8 while
                                 KSE-100 closed green -> flag KSE100.
                                 Otherwise the retail-heaviest sector where
                                 institutions are net negative, flagged via
                                 its highest-turnover member.

Participant vocabulary: institutions = BANKS + MUTUAL FUNDS + FIPI.
NCCPL's FIPI aggregate is stored as the "FOREIGN TOTAL" rollup on current
scraper generations (and as literal "FIPI" on legacy rows), so both labels
are honoured. Retail = INDIVIDUALS.

Honest-data rules (house convention): a horizon with no certified
candidate is SKIPPED - never fabricated, never defaulted. The frontend
renders the missing horizon as its own idle state.
"""

from __future__ import annotations

import logging
import os
from collections import defaultdict
from datetime import date
from typing import Any, Optional

from pipeline import db
from pipeline.http_client import http_get

LOGGER = logging.getLogger(__name__)

VOLUME_SPIKE_RATIO = float(os.getenv("VERDICT_VOLUME_SPIKE_RATIO", "2.5"))
VOLUME_SMA_WINDOW = int(os.getenv("VERDICT_VOLUME_SMA_WINDOW", "20"))
FLOW_WINDOW_SESSIONS = int(os.getenv("VERDICT_FLOW_WINDOW_SESSIONS", "5"))
BREADTH_RED_RATIO = float(os.getenv("VERDICT_BREADTH_RED_RATIO", "0.8"))

INST_FLOW_TYPES = {"BANKS", "MUTUAL FUNDS", "FIPI", "FOREIGN TOTAL"}
RETAIL_FLOW_TYPES = {"INDIVIDUALS"}

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


def _sector_flow_totals(
    flow_rows: list[dict[str, Any]], days: list[date]
) -> dict[str, dict[str, float]]:
    """sector -> participant -> cumulative net over the given flow sessions."""
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
        totals[sector][participant] += _net_of(row)
    return totals


def _sector_map(fundamental_rows: list[dict[str, Any]]) -> dict[str, str]:
    """ticker -> sector label (upper) from the newest fundamentals snapshot."""
    newest: Optional[date] = None
    for row in fundamental_rows:
        day = _parse_day(row.get("trade_date"))
        if day is not None and (newest is None or day > newest):
            newest = day
    mapping: dict[str, str] = {}
    for row in fundamental_rows:
        day = _parse_day(row.get("trade_date"))
        if day is None or newest is None or day != newest:
            continue
        sector = str(row.get("sector_name") or "").strip().upper()
        if sector:
            mapping[row["ticker"]] = sector
    return mapping


def _inst_retail_nets(nets: dict[str, float]) -> tuple[float, float]:
    inst = sum(nets.get(p, 0.0) for p in INST_FLOW_TYPES)
    retail = sum(nets.get(p, 0.0) for p in RETAIL_FLOW_TYPES)
    return inst, retail


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


# --------------------------------------------------------------------------- #
# Horizon verdicts                                                            #
# --------------------------------------------------------------------------- #
def _short_term_verdict(
    session_date: date,
    series: dict[str, list[tuple[date, float, float]]],
    flow_rows: list[dict[str, Any]],
) -> Optional[dict[str, Any]]:
    """Volume spike > 2.5x 20D SMA, gated on the session flow cross-check."""
    nets = _market_wide_net(flow_rows, session_date)
    if not nets:
        LOGGER.info("decision engine: no session flows for %s; SHORT_TERM skipped", session_date)
        return None
    inst_net, retail_net = _inst_retail_nets(nets)
    if inst_net <= 0 or retail_net >= 0:
        LOGGER.info(
            "decision engine %s: flow cross-check failed "
            "(inst=%.0f, retail=%.0f); SHORT_TERM skipped",
            session_date, inst_net, retail_net,
        )
        return None

    best_ticker: Optional[str] = None
    best_volume = 0.0
    best_spike_pct = 0.0
    for ticker, points in series.items():
        if ticker.upper() in INDEX_TICKERS:
            continue
        session_point = _point_at(points, session_date)
        if session_point is None:
            continue
        _, volume = session_point
        if volume <= 0:
            continue
        window = [p for p in points if p[0] <= session_date][-VOLUME_SMA_WINDOW:]
        if len(window) < VOLUME_SMA_WINDOW:
            continue  # honest: no full 20D baseline, no verdict
        sma = sum(p[2] for p in window) / len(window)
        if sma <= 0 or volume <= VOLUME_SPIKE_RATIO * sma:
            continue
        if volume > best_volume:
            best_ticker = ticker
            best_volume = volume
            best_spike_pct = (volume / sma - 1.0) * 100.0

    if best_ticker is None:
        LOGGER.info("decision engine %s: no 2.5x volume spike; SHORT_TERM skipped", session_date)
        return None
    return {
        "trade_date": session_date.isoformat(),
        "horizon": HORIZON_SHORT,
        "direction": "BUY",
        "ticker": best_ticker,
        "logic_text": (
            "Smart money absorbed retail selling on a "
            f"+{best_spike_pct:.0f}% volume spike over the 20D average."
        ),
    }


def _leader_in_sector(
    sector: str,
    session_date: date,
    series: dict[str, list[tuple[date, float, float]]],
    sector_by_ticker: dict[str, str],
    *,
    require_positive_5d: bool,
    window_start: Optional[date],
) -> Optional[str]:
    """Highest session-turnover ticker mapped to ``sector``.

    With require_positive_5d, only members closing above their window-start
    close qualify - the leader must be performing, not just churning.
    """
    best_ticker: Optional[str] = None
    best_turnover = -1.0
    for ticker, mapped in sector_by_ticker.items():
        if mapped != sector:
            continue
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
) -> Optional[dict[str, Any]]:
    """Sector with the largest 5-session institutional absorption while
    retail distributed; leader = highest-turnover member with positive 5D."""
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
    )
    if leader is None:
        LOGGER.info(
            "decision engine %s: sector %s has no positive-5D turnover leader; "
            "MID_TERM skipped",
            session_date, best_sector,
        )
        return None
    return {
        "trade_date": session_date.isoformat(),
        "horizon": HORIZON_MID,
        "direction": "BUY",
        "ticker": leader,
        "logic_text": "Sustained institutional net absorption across 5 sessions while retail distributed.",
    }


def _long_term_verdict(
    session_date: date,
    sessions_desc: list[date],
    series: dict[str, list[tuple[date, float, float]]],
    flow_rows: list[dict[str, Any]],
    sector_by_ticker: dict[str, str],
) -> Optional[dict[str, Any]]:
    """Breadth trap -> KSE100, else the retail-heaviest institution-sold sector."""
    prior = [d for d in sessions_desc if d < session_date]
    if prior:
        prior_date = prior[0]
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
        if ratio is not None and ratio < BREADTH_RED_RATIO:
            change = _kse100_change_pct(session_date, prior_date, series)
            if change is not None and change > 0:
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
    if trap_sector is None:
        LOGGER.info(
            "decision engine %s: no retail-trap sector; LONG_TERM skipped", session_date
        )
        return None
    leader = _leader_in_sector(
        trap_sector,
        session_date,
        series,
        sector_by_ticker,
        require_positive_5d=False,
        window_start=None,
    )
    if leader is None:
        LOGGER.info(
            "decision engine %s: trap sector %s has no priced leader; LONG_TERM skipped",
            session_date, trap_sector,
        )
        return None
    return {
        "trade_date": session_date.isoformat(),
        "horizon": HORIZON_LONG,
        "direction": "AVOID",
        "ticker": leader,
        "logic_text": "Retail trap active: institutions net distributing into retail liquidity.",
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
    eod_rows = db.fetch_recent_eod()
    if not eod_rows:
        LOGGER.warning("decision engine: no EOD history; aborting")
        return 0
    flow_rows = db.fetch_recent_flows(days=FLOW_WINDOW_SESSIONS + 5)
    fundamentals = db.fetch_recent_fundamentals()

    series = _session_series(eod_rows)
    sessions_desc = _session_dates_desc(series)
    if trade_date not in sessions_desc:
        LOGGER.warning(
            "decision engine: %s has no stored EOD session; aborting", trade_date
        )
        return 0
    sector_by_ticker = _sector_map(fundamentals)

    rows = [
        verdict
        for verdict in (
            _short_term_verdict(trade_date, series, flow_rows),
            _mid_term_verdict(trade_date, sessions_desc, series, flow_rows, sector_by_ticker),
            _long_term_verdict(trade_date, sessions_desc, series, flow_rows, sector_by_ticker),
        )
        if verdict is not None
    ]
    if not rows:
        LOGGER.warning(
            "decision engine %s: no horizon had a certified candidate", trade_date
        )
        return 0
    written = db.upsert_records(
        "psx_system_verdicts", rows, on_conflict="trade_date,horizon"
    )
    LOGGER.info(
        "decision engine %s: %d/%d verdicts stored (%s)",
        trade_date,
        written,
        len(rows),
        ", ".join(r["horizon"] for r in rows),
    )
    return written
