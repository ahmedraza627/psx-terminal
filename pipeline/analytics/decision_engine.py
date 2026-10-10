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
  LONG_TERM (avoid/risk)  AVOID The retail-heaviest sector where
                                 institutions are net negative, flagged via
                                 its highest-turnover priced member. Falls
                                 back to the breadth trap (advance/decline <
                                 0.8 while KSE-100 closed green -> KSE100)
                                 when no trap-sector ticker is priced.

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
from datetime import date
from typing import Any, Optional

from pipeline import db
from pipeline.backtest.engine import run_quick_backtest
from pipeline.http_client import http_get

LOGGER = logging.getLogger(__name__)

VOLUME_SPIKE_RATIO = float(os.getenv("VERDICT_VOLUME_SPIKE_RATIO", "2.5"))
VOLUME_SMA_WINDOW = int(os.getenv("VERDICT_VOLUME_SMA_WINDOW", "20"))
FLOW_WINDOW_SESSIONS = int(os.getenv("VERDICT_FLOW_WINDOW_SESSIONS", "5"))
BREADTH_RED_RATIO = float(os.getenv("VERDICT_BREADTH_RED_RATIO", "0.8"))

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
    pe_map: dict[str, Optional[float]],
) -> Optional[dict[str, Any]]:
    """Volume spike > 2.5x 20D SMA, gated on the session flow cross-check.

    Institutional execution levels are derived from the certified tape:
    entry = latest session close; stop = recent 3-day swing low (or
    1.5x ATR below); target = 2:1 minimum risk/reward.
    """
    nets = _market_wide_net(flow_rows, session_date)
    if not nets:
        LOGGER.info("decision engine: no session flows for %s; SHORT_TERM skipped", session_date)
        return None
    # Participant labels are normalised (upper/strip) by _market_wide_net;
    # retail is detected by substring so both INDIVIDUAL and INDIVIDUALS
    # labels count. A missing / zero retail line does NOT block the verdict
    # (fix for the 2026-10-07 all-skip): institutions net buying carries
    # the cross-check on its own. Only net RETAIL BUYING falsifies the
    # "absorbed retail selling" narrative and blocks it.
    inst_net = sum(nets.get(p, 0.0) for p in INST_FLOW_TYPES)
    retail_net = sum(v for k, v in nets.items() if "INDIVIDUAL" in k)
    if inst_net <= 0 or retail_net > 0:
        LOGGER.info(
            "decision engine %s: flow cross-check failed "
            "(inst=%.0f, retail=%.0f); SHORT_TERM skipped",
            session_date, inst_net, retail_net,
        )
        return None

    # Rank every qualifying spike by volume, then walk down the list to
    # the BEST FUNDAMENTALLY VERIFIED candidate: loss-making or unpriced
    # tickers are skipped, never certified (institutional strict rule).
    candidates: list[tuple[float, float, str]] = []  # (volume, spike_pct, ticker)
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
        candidates.append((volume, (volume / sma - 1.0) * 100.0, ticker))

    best_ticker: Optional[str] = None
    best_spike_pct = 0.0
    for volume, spike_pct, ticker in sorted(candidates, reverse=True):
        if _is_profitable(pe_map, ticker):
            best_ticker = ticker
            best_spike_pct = spike_pct
            break
        LOGGER.info(
            "decision engine %s: fundamental filter skipped %s "
            "(pe_ratio=%s); next candidate",
            session_date, ticker, pe_map.get(ticker),
        )

    if best_ticker is None:
        if candidates:
            LOGGER.info(
                "decision engine %s: %d volume spike(s) but none profitable "
                "(PE > 0); SHORT_TERM skipped",
                session_date, len(candidates),
            )
        else:
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
    pe_map: Optional[dict[str, Optional[float]]] = None,
    require_profitable: bool = False,
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
) -> Optional[dict[str, Any]]:
    """Sector with the largest 5-session institutional absorption while
    retail distributed; leader = highest-turnover member with positive 5D.

    Institutional execution levels: entry = latest session close;
    stop = 20-day SMA or 5% trailing structural support (whichever is
    tighter); target = trailing-52-week resistance or 2.5:1 minimum R:R.
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
        )
    if leader is None:
        LOGGER.info(
            "decision engine %s: sector %s has no priced ticker at the session; "
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


def _execution_levels(
    verdict: dict[str, Any],
    session_date: date,
    series: dict[str, list[tuple[date, float, float]]],
) -> dict[str, Any]:
    """Precise execution levels per horizon (institutional risk math).

    Points are (day, close, volume) - the stored tape carries no high/low,
    so the ATR leg is the mean absolute close-to-close change (documented
    proxy, never a fabricated number).

      SHORT_TERM: entry = session close; stop = the LOWER of the 3-session
        swing low and 1.5x ATR below close; target = 2.0x the risked
        distance (minimum 1:2 reward/risk).
      MID_TERM:   entry = session close; stop = structural support = the
        lower of the 3-session swing low, the 20-day SMA and close x 0.95
        (5% trailing); target = trailing 52-week resistance when it pays
        at least 1:1 on the structural risk, else 2.5x the risked distance.
      LONG_TERM is an AVOID/risk verdict - it has no entry, so it carries
        honest null levels (the desk renders no grid for it).

    Missing / unpriced session data -> all-null levels, never invented.
    """
    empty = {
        "entry_ref": None,
        "stop_loss": None,
        "target_price": None,
        "risk_reward_ratio": None,
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

    if verdict["horizon"] == HORIZON_SHORT:
        # ATR proxy: mean |close-to-close| change over the last 4 sessions.
        closes = [p[1] for p in window[-4:] if p[1] > 0]
        changes = [abs(closes[i] - closes[i - 1]) for i in range(1, len(closes))]
        atr = sum(changes) / len(changes) if changes else 0.0
        candidates = [swing_low] + ([close - 1.5 * atr] if atr > 0 else [])
        stop = min(s for s in candidates if s > 0)
        target = close + 2.0 * (close - stop)
    else:
        # MID_TERM structural support: swing low, 20D SMA, 5% trailing.
        closes20 = [p[1] for p in window[-20:] if p[1] > 0]
        supports = [swing_low, close * 0.95]
        if len(closes20) == 20:
            supports.append(sum(closes20) / 20)
        stop = min(supports)
        risk = close - stop
        # Trailing 52-week resistance as target when it clears 1:1 on the
        # structural risk; otherwise the 2.5x risked-distance fallback.
        year_closes = [
            p[1]
            for p in window
            if (session_date - p[0]).days <= 365 and p[1] > 0
        ]
        resistance = max(year_closes) if year_closes else 0.0
        target = (
            resistance
            if resistance > close and resistance - close >= risk
            else close + 2.5 * risk
        )

    risked = max(close - stop, 0.01)  # spec floor: never divide below 0.01
    return {
        "entry_ref": round(close, 2),
        "stop_loss": round(stop, 2),
        "target_price": round(target, 2),
        "risk_reward_ratio": round((target - close) / risked, 2),
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

    # Market regime: the macro gate all execution levels are stamped with.
    prior = [d for d in sessions_desc if d < trade_date]
    regime = _regime_status(trade_date, prior[0] if prior else trade_date, series)

    def with_execution(v: dict[str, Any]) -> dict[str, Any]:
        levels = _execution_levels(v, trade_date, series)
        v.update(levels)
        v["regime_status"] = regime
        # Fundamental gate result + historical edge proof. BUY verdicts
        # already passed the strict PE gate in candidate selection; AVOID
        # verdicts are warnings, so they stay UNVERIFIED and unbacktested.
        profitable = _is_profitable(pe_map, v["ticker"])
        v["fundamental_score"] = (
            FUNDAMENTAL_SCORE_LABEL if profitable else FUNDAMENTAL_UNVERIFIED
        )
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

    rows = [
        with_execution(v)
        for v in (
            _short_term_verdict(trade_date, series, flow_rows, pe_map),
            _mid_term_verdict(trade_date, sessions_desc, series, flow_rows, sector_by_ticker, pe_map),
            _long_term_verdict(trade_date, sessions_desc, series, flow_rows, sector_by_ticker),
        )
        if v is not None
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
        "decision engine %s: %d/%d verdicts stored (regime=%s) (%s)",
        trade_date,
        written,
        len(rows),
        regime,
        ", ".join(r["horizon"] for r in rows),
    )
    return written
