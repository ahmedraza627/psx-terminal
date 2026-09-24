"""Sector Relative Rotation (RRG) engine - benchmarked against KSE-100.

Methodology (daily RRG):
  1. Sector index      : equal-weighted accumulation of member daily
                         returns from stored psx_daily_eod closes.
  2. Benchmark index   : KSE-100 closes fetched live from the DPS
                         timeseries endpoint; when that 404s/down, falls
                         back to index rows stored in psx_daily_eod, then
                         to an equal-weight close-over-close market proxy
                         computed from the stored universe (basis labels:
                         DPS_LIVE / EOD_STORED / MARKET_PROXY).
  3. RS-Ratio          : sector_index / benchmark_index, normalised to a
                         base of 100 over the lookback window.
  4. RS-Momentum       : 100 x (rs_ratio_norm(t) / rs_ratio_norm(t - span)),
                         span = RRG_JACOB_SPAN sessions (default 5).
  5. Quadrant          : LEADING (ratio>=100, mom>=100) / WEAKENING
                         (ratio>=100, mom<100) / IMPROVING (ratio<100,
                         mom>=100) / LAGGING (ratio<100, mom<100).

Institutional flow-engine enrichment (v2) - one psx_sector_rotation row
carries the full desk view:
  - sessions_in_quadrant / weeks_in_quadrant: consecutive-session regime
    persistence from stored rotation history (honest: NULL on first sight).
  - breadth_pct: % of sector members whose latest close is above their own
    20-session SMA (SMA includes the session close, standard convention);
    flags BROAD_PARTICIPATION (>=70%), NARROW_TRAP (<=30% while the sector
    index rose over 5 sessions) or NARROW (<=30% without divergence).
  - net_inst_flow_pkr_5d / net_retail_flow_pkr_5d: 5-session cumulative
    NCCPL net flow per sector (institutions = MUTUAL FUNDS + FIPI;
    retail = INDIVIDUALS).
  - alpha_drivers / alpha_draggers: top-2 / bottom-2 members by 5-session
    return, each with LTP, 5D %, RS vs the sector mean and volume x SMA20.
  - verdict: EARLY_ACCUMULATION (Improving + positive inst flow),
    MOMENTUM_RIDE (Leading + broad breadth), DISTRIBUTION_RISK (Weakening,
    or Leading with negative flow), AVOID_CAPITAL_TRAP (Lagging + narrow
    breadth); NULL = mixed signals, desk shows MONITOR - never forced.

Sectors come from the psx_fundamentals snapshot's sector_name mapping.
A sector is only published when it has >= MIN_SECTOR_MEMBERS tickers with
prices at both ends of the window - thin sectors are skipped, never
extrapolated. Leader/dragger are the best/worst window performers with
real closes on both endpoint sessions.
"""

from __future__ import annotations

import logging
import math
import os
from collections import defaultdict
from datetime import date, timedelta
from typing import Any, Optional

from pipeline import db
from pipeline.http_client import http_get

LOGGER = logging.getLogger(__name__)

RRG_LOOKBACK_SESSIONS = int(os.getenv("RRG_LOOKBACK_SESSIONS", "60"))
RRG_JACOB_SPAN = int(os.getenv("RRG_JACOB_SPAN", "5"))
MIN_SECTOR_MEMBERS = int(os.getenv("RRG_MIN_SECTOR_MEMBERS", "4"))
BENCHMARK_SYMBOL = os.getenv("RRG_BENCHMARK", "KSE100")

# Flow-engine enrichment tunables.
BREADTH_SMA_SESSIONS = int(os.getenv("RRG_BREADTH_SMA", "20"))
FLOW_WINDOW_SESSIONS = int(os.getenv("RRG_FLOW_WINDOW", "5"))
BREADTH_BROAD_PCT = float(os.getenv("RRG_BREADTH_BROAD", "70"))
BREADTH_NARROW_PCT = float(os.getenv("RRG_BREADTH_NARROW", "30"))
INST_FLOW_TYPES = {"MUTUAL FUNDS", "FIPI"}
RETAIL_FLOW_TYPES = {"INDIVIDUALS"}

# Upsert degrade: enriched write falls back to the core column set when the
# v2 ALTERs have not been applied yet (PGRST204 unknown-column rejection).
CORE_ROTATION_FIELDS = (
    "trade_date",
    "sector_name",
    "rs_ratio",
    "rs_momentum",
    "quadrant",
    "top_leader_ticker",
    "top_dragger_ticker",
)

_benchmark_cache: dict[str, list[tuple[date, float]]] = {}
_benchmark_basis: dict[str, str] = {}

# Legacy/alias index rows that may sit in psx_daily_eod depending on the
# scraper generation that wrote them. Checked in order of preference.
INDEX_TICKER_CANDIDATES = ("KSE100", "KSE-100", "KSE 100", "100INDEX", "KSE30")
# Calendar window for local benchmark pulls: covers the 60-session RRG
# lookback plus the regime SMA20 with margin (65 sessions ~ 95 calendar
# days; holidays need extra room).
LOCAL_BENCH_WINDOW_DAYS = 160
# Minimum chained sessions before an aggregated market proxy is trusted
# (below this the SMA20/RS baselines would be noise).
MIN_PROXY_SESSIONS = 21


def _dps_live_series(symbol: str) -> list[tuple[date, float]]:
    """DPS timeseries closes, or [] when the endpoint is dead (e.g. 404)."""
    url = f"https://dps.psx.com.pk/timeseries/eod/{symbol}"
    try:
        response = http_get(url, timeout=25.0)
        payload = response.json()
    except Exception as exc:  # noqa: BLE001 - benchmark down = fallback tier
        LOGGER.warning("benchmark DPS timeseries %s unavailable: %s", symbol, exc)
        return []
    rows = payload.get("data") if isinstance(payload, dict) else None
    series: list[tuple[date, float]] = []
    for row in rows or []:
        try:
            ts = int(row[0])
            close = float(row[1])
        except (TypeError, ValueError, IndexError):
            continue
        if close <= 0:
            continue
        day = date.fromtimestamp(ts)
        series.append((day, close))
    series.sort()
    return series


def _stored_index_series() -> list[tuple[date, float]]:
    """Benchmark closes stored in psx_daily_eod under an index ticker.

    One window-bounded query (see db.fetch_recent_eod - no full-table scan);
    the alias set covers every index-ticker convention the pipeline has
    ever written. Needs >= MIN_PROXY_SESSIONS live closes to qualify.
    """
    alias_filter = "({})".format(",".join(INDEX_TICKER_CANDIDATES))
    try:
        rows = db._paginated_select(
            "psx_daily_eod",
            "trade_date,ticker,close_price,volume",
            order_desc_col="trade_date",
            order_asc_col="ticker",
            max_rows=400,
            filters=[
                ("ticker", "in", alias_filter),
                ("trade_date", "gte", (
                    date.today() - timedelta(days=LOCAL_BENCH_WINDOW_DAYS)
                ).isoformat()),
            ],
        )
    except Exception as exc:  # noqa: BLE001 - degrade to the next tier
        LOGGER.warning("benchmark stored-index probe failed: %s", exc)
        return []
    series: list[tuple[date, float]] = []
    for row in rows:
        try:
            day = date.fromisoformat(str(row["trade_date"])[:10])
            close = float(row["close_price"])
        except (TypeError, ValueError, KeyError):
            continue
        if close > 0:
            series.append((day, close))
    series.sort()
    # De-dupe (one level per session - keep the first alias hit).
    deduped: list[tuple[date, float]] = []
    seen: set[date] = set()
    for day, close in series:
        if day in seen:
            continue
        seen.add(day)
        deduped.append((day, close))
    return deduped


def _aggregate_market_proxy() -> list[tuple[date, float]]:
    """Equal-weight market index chained from stored universe closes.

    The certified last resort: level_t = level_{t-1} x (1 + mean cross-"
    "sectional close-over-close return), seeded at 100. Uses ONLY stored
    closes - no invented prices, no forward filling; sessions without a
    readable prior day are skipped. Requires >= MIN_PROXY_SESSIONS chained
    sessions, otherwise the SMA20 regime leg is noise and we publish none.
    """
    try:
        history = db.fetch_recent_eod(days=LOCAL_BENCH_WINDOW_DAYS)
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("benchmark market-proxy probe failed: %s", exc)
        return []
    by_day: dict[date, dict[str, float]] = {}
    for row in history:
        try:
            day = date.fromisoformat(str(row["trade_date"])[:10])
            close = float(row["close_price"])
            ticker = str(row.get("ticker") or "").upper().strip()
        except (TypeError, ValueError, KeyError):
            continue
        if day.weekday() >= 5 or close <= 0 or not ticker:
            continue
        by_day.setdefault(day, {})[ticker] = close
    days = sorted(by_day)
    levels: list[tuple[date, float]] = []
    level: Optional[float] = None
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
    if len(levels) < MIN_PROXY_SESSIONS:
        return []
    return levels


def get_benchmark_basis(symbol: str = BENCHMARK_SYMBOL) -> str:
    """How the cached benchmark series was sourced (observability hook)."""
    return _benchmark_basis.get(symbol, "NO_DATA")


def fetch_benchmark_series(symbol: str = BENCHMARK_SYMBOL) -> list[tuple[date, float]]:
    """KSE-100 (or any DPS index) closes, newest-first, cached per process.

    Fallback chain - a dead DPS endpoint NEVER aborts the run:
      1. DPS_LIVE    : dps.psx.com.pk/timeseries/eod/<symbol>
      2. EOD_STORED  : index rows already in psx_daily_eod (ticker aliases)
      3. MARKET_PROXY: equal-weight close-over-close composite of the whole
                       stored universe (levels, not PKR prices - honest
                       basis label so desks know the scale differs)
    Total failure returns [] (desk idles) exactly as before.
    """
    if symbol in _benchmark_cache:
        return _benchmark_cache[symbol]

    series = _dps_live_series(symbol)
    basis = "DPS_LIVE"
    if not series:
        series = _stored_index_series()
        basis = "EOD_STORED"
    if not series:
        series = _aggregate_market_proxy()
        basis = "MARKET_PROXY"
    if not series:
        basis = "NO_DATA"

    _benchmark_cache[symbol] = series
    _benchmark_basis[symbol] = basis
    if basis == "NO_DATA":
        LOGGER.warning("benchmark %s: no source produced a usable series", symbol)
    else:
        LOGGER.info(
            "benchmark %s: %d sessions (basis=%s)", symbol, len(series), basis
        )
    return series


def _quadrant(rs_ratio: float, rs_momentum: float) -> str:
    if rs_ratio >= 100.0:
        return "LEADING" if rs_momentum >= 100.0 else "WEAKENING"
    return "IMPROVING" if rs_momentum >= 100.0 else "LAGGING"


# --------------------------------------------------------------------------- #
# Flow-engine enrichment helpers (pure, unit-testable).                        #
# --------------------------------------------------------------------------- #
def _weeks_from_sessions(sessions: int) -> int:
    """Trading weeks: 5 sessions/week, minimum 1 week in regime."""
    return max(1, sessions // 5)


def compute_breadth(
    trade_date: date,
    eod_by_ticker: dict[str, list[tuple[date, float, Optional[int]]]],
    tickers: list[str],
    *,
    sma_sessions: int = BREADTH_SMA_SESSIONS,
) -> dict[str, Any]:
    """Sector breadth: % of members above their own 20-SMA (inclusive).

    Volume x SMA20 per member is returned for the drilldown panel. Members
    with < sma_sessions stored sessions are excluded (never guessed).
    """
    above = 0
    counted = 0
    vol_x: dict[str, Optional[float]] = {}
    for t in tickers:
        series = eod_by_ticker.get(t, [])
        if len(series) < sma_sessions:
            vol_x[t] = None
            continue
        window = [c for _, c, _ in series[-sma_sessions:]]
        sma = sum(window) / len(window)
        last_day, last_close, last_vol = series[-1]
        if last_day != trade_date or last_close <= 0:
            vol_x[t] = None
            continue
        counted += 1
        if last_close > sma:
            above += 1
        window_vols = [v for _, _, v in series[-sma_sessions:]]
        vol_x[t] = (
            float(last_vol) / (sum(window_vols) / sma_sessions)
            if last_vol is not None and all(v is not None for v in window_vols)
            else None
        )
    pct = (above / counted * 100.0) if counted else None
    return {"pct": pct, "counted": counted, "vol_x": vol_x}


def compute_sector_flows(
    flows: list[dict[str, Any]],
    sector: str,
    *,
    window_sessions: int = FLOW_WINDOW_SESSIONS,
) -> dict[str, Optional[float]]:
    """5-session cumulative NCCPL net flow for one sector.

    Institutions = MUTUAL FUNDS + FIPI; retail = INDIVIDUALS. Sector rows
    only (ALL totals cancel). Returns {} when the sector has no stored rows.
    """
    dates = sorted(
        {
            str(r.get("trade_date"))[:10]
            for r in flows
            if (r.get("sector_name") or "").strip().upper() == sector
        }
    )
    if not dates:
        return {}
    window = set(dates[-window_sessions:])
    inst = 0.0
    retail = 0.0
    for r in flows:
        if (r.get("sector_name") or "").strip().upper() != sector:
            continue
        if str(r.get("trade_date"))[:10] not in window:
            continue
        ptype = (r.get("participant_type") or "").strip().upper()
        net = r.get("net_pkr")
        if net is None:
            continue
        if ptype in INST_FLOW_TYPES:
            inst += float(net)
        elif ptype in RETAIL_FLOW_TYPES:
            retail += float(net)
    return {"inst": inst, "retail": retail}


def compute_alpha_tails(
    trade_date: date,
    eod_by_ticker: dict[str, list[tuple[date, float, Optional[int]]]],
    tickers: list[str],
    sector_mean_5d: Optional[float],
    vol_x: dict[str, Optional[float]],
    *,
    window: int = 5,
) -> dict[str, list[dict[str, Any]]]:
    """Top-2 / bottom-2 members by 5-session return with full drilldown fields."""
    stocks: list[dict[str, Any]] = []
    for t in tickers:
        series = eod_by_ticker.get(t, [])
        if len(series) < window + 1:
            continue
        end_day, end_close, _ = series[-1]
        start_close = series[-1 - window][1]
        if end_day != trade_date or start_close <= 0 or end_close <= 0:
            continue
        ret_5d = (end_close / start_close - 1.0) * 100.0
        stocks.append(
            {
                "ticker": t,
                "ltp": round(end_close, 2),
                "ret_5d_pct": round(ret_5d, 2),
                "rs_vs_sector_pct": (
                    round(ret_5d - sector_mean_5d, 2)
                    if sector_mean_5d is not None
                    else None
                ),
                "vol_x_sma20": (
                    round(vol_x[t], 2)
                    if vol_x.get(t) is not None
                    else None
                ),
            }
        )
    stocks.sort(key=lambda s: s["ret_5d_pct"], reverse=True)
    return {
        "drivers": stocks[:2],
        "draggers": (
            stocks[-2:][::-1] if len(stocks) >= 2 else []
        ),
    }


def compute_sector_rotation(
    trade_date: date,
    *,
    eod_history: list[dict[str, Any]],
    sector_of: dict[str, str],
    benchmark: list[tuple[date, float]],
    flows: Optional[list[dict[str, Any]]] = None,
    history: Optional[list[dict[str, Any]]] = None,
) -> list[dict[str, Any]]:
    """Build the enriched psx_sector_rotation payload for one session."""
    if len(benchmark) < RRG_LOOKBACK_SESSIONS + 2:
        LOGGER.warning(
            "rotation: benchmark has %d sessions, need %d - desk stays idle",
            len(benchmark),
            RRG_LOOKBACK_SESSIONS + 2,
        )
        return []

    closes: dict[str, list[tuple[date, float]]] = defaultdict(list)
    for row in eod_history:
        try:
            day = date.fromisoformat(str(row["trade_date"])[:10])
        except (ValueError, TypeError):
            continue
        close = row.get("close_price")
        if close is None or float(close) <= 0:
            continue
        closes[row["ticker"]].append((day, float(close)))
    for series in closes.values():
        series.sort()

    bench_by_day = dict(benchmark)
    window_days = sorted(
        day for day in bench_by_day if day <= trade_date
    )[-RRG_LOOKBACK_SESSIONS:]
    if len(window_days) < RRG_LOOKBACK_SESSIONS:
        return []
    if window_days[-1] != trade_date:
        LOGGER.warning(
            "rotation: session %s has no benchmark close (latest %s) - idle",
            trade_date,
            window_days[-1],
        )
        return []

    # EOD series with volume for breadth / alpha attribution: per-ticker
    # [(day, close, volume)] over the full stored span (close>0 only).
    eod_by_ticker: dict[str, list[tuple[date, float, Optional[int]]]] = defaultdict(
        list
    )
    for row in eod_history:
        try:
            day = date.fromisoformat(str(row["trade_date"])[:10])
        except (ValueError, TypeError):
            continue
        close = row.get("close_price")
        if close is None or float(close) <= 0:
            continue
        vol = row.get("volume")
        eod_by_ticker[row["ticker"]].append(
            (day, float(close), int(vol) if vol is not None else None)
        )
    for series in eod_by_ticker.values():
        series.sort(key=lambda x: x[0])

    # Sector membership restricted to tickers with a price on the session.
    members: dict[str, set[str]] = defaultdict(set)
    for ticker, sector in sector_of.items():
        if not sector or ticker not in closes:
            continue
        if any(day == trade_date for day, _ in closes[ticker]):
            members[sector[:64]].add(ticker)

    payload: list[dict[str, Any]] = []
    for sector, tickers in sorted(members.items()):
        # Only members quoted on both window endpoints count for the index.
        first_day, last_day = window_days[0], window_days[-1]
        eligible = [
            t
            for t in tickers
            if any(d == first_day for d, _ in closes[t])
            and any(d == last_day for d, _ in closes[t])
        ]
        if len(eligible) < MIN_SECTOR_MEMBERS:
            continue

        # Equal-weight sector index: accrue mean member daily return.
        price_by_ticker = {
            t: {d: c for d, c in closes[t] if first_day <= d <= last_day}
            for t in eligible
        }
        sector_index = 100.0
        index_path: list[float] = []
        for prev_day, cur_day in zip(window_days, window_days[1:]):
            rets = []
            for prices in price_by_ticker.values():
                prev_close = prices.get(prev_day)
                cur_close = prices.get(cur_day)
                if prev_close and cur_close:
                    rets.append(cur_close / prev_close - 1.0)
            if len(rets) < MIN_SECTOR_MEMBERS:
                index_path.append(float("nan"))
                continue
            sector_index *= 1.0 + sum(rets) / len(rets)
            index_path.append(sector_index)

        # Benchmark rebased to 100 at window start, aligned to index_path.
        base_bench = bench_by_day[first_day]
        bench_path = [bench_by_day[d] / base_bench * 100.0 for d in window_days[1:]]

        # RS-Ratio path normalised to base 100 (mean of the window).
        rs_path: list[float] = []
        for idx, bnc in zip(index_path, bench_path):
            if math.isnan(idx):
                rs_path.append(float("nan"))
                continue
            rs_path.append(idx / bnc * 100.0)
        finite = [v for v in rs_path if not math.isnan(v)]
        if len(finite) < RRG_JACOB_SPAN + 2:
            continue
        rs_mean = sum(finite) / len(finite)
        rs_norm = [v / rs_mean * 100.0 for v in rs_path]

        rs_ratio = rs_norm[-1]
        prev = rs_norm[-1 - RRG_JACOB_SPAN]
        if math.isnan(rs_ratio) or math.isnan(prev) or prev == 0:
            continue
        rs_momentum = rs_ratio / prev * 100.0
        quadrant = _quadrant(rs_ratio, rs_momentum)

        # Window leader/dragger among eligible members.
        def window_return(ticker: str) -> Optional[float]:
            first_close = price_by_ticker[ticker].get(first_day)
            last_close = price_by_ticker[ticker].get(last_day)
            if not first_close or not last_close:
                return None
            return (last_close / first_close - 1.0) * 100.0

        returns = {t: window_return(t) for t in eligible}
        ranked = sorted(
            ((t, r) for t, r in returns.items() if r is not None),
            key=lambda kv: kv[1],
            reverse=True,
        )
        leader = ranked[0][0] if ranked else None
        dragger = ranked[-1][0] if len(ranked) >= 2 else None

        # ---------------- Flow-engine enrichment (v2) ----------------
        breadth = compute_breadth(trade_date, eod_by_ticker, eligible)
        breadth_pct = breadth["pct"]
        sector_mean_5d = (
            sum(r for _, r in ranked) / len(ranked) if ranked else None
        )
        tails = compute_alpha_tails(
            trade_date,
            eod_by_ticker,
            eligible,
            sector_mean_5d,
            breadth["vol_x"],
        )

        inst_flow: Optional[float] = None
        retail_flow: Optional[float] = None
        if flows:
            sector_flows = compute_sector_flows(flows, sector)
            inst_flow = sector_flows.get("inst")
            retail_flow = sector_flows.get("retail")

        # Regime persistence: consecutive stored sessions the sector has
        # held this quadrant (today's own row is session 1).
        sessions_in_quad: Optional[int] = None
        if history:
            sessions_in_quad = 1
            cursor = trade_date
            for _ in range(250):
                cursor = cursor.fromordinal(cursor.toordinal() - 1)
                row_d = next(
                    (
                        r
                        for r in history
                        if str(r.get("trade_date"))[:10] == cursor.isoformat()
                        and str(r.get("sector_name") or "").strip().upper()
                        == sector.upper()
                    ),
                    None,
                )
                if row_d is None:
                    break  # no stored row for that date: stop
                if str(row_d.get("quadrant") or "") != quadrant:
                    break  # regime changed
                sessions_in_quad += 1
        weeks_in_quad = (
            _weeks_from_sessions(sessions_in_quad)
            if sessions_in_quad is not None
            else None
        )

        # Breadth flag: NARROW_TRAP needs the divergence test (breadth
        # <= 30% while the equal-weight sector rose over 5 sessions).
        rose_5d = sector_mean_5d is not None and sector_mean_5d > 0
        breadth_flag: Optional[str] = None
        if breadth_pct is not None:
            if breadth_pct >= BREADTH_BROAD_PCT:
                breadth_flag = "BROAD_PARTICIPATION"
            elif breadth_pct <= BREADTH_NARROW_PCT and rose_5d:
                breadth_flag = "NARROW_TRAP"
            elif breadth_pct <= BREADTH_NARROW_PCT:
                breadth_flag = "NARROW"
            else:
                breadth_flag = "NEUTRAL"

        # Verdict matrix: NULL stays NULL (desk renders MONITOR).
        verdict: Optional[str] = None
        if quadrant == "IMPROVING" and inst_flow is not None and inst_flow > 0:
            verdict = "EARLY_ACCUMULATION"
        elif quadrant == "LEADING" and (
            breadth_pct is not None and breadth_pct >= BREADTH_BROAD_PCT
        ):
            verdict = "MOMENTUM_RIDE"
        elif quadrant == "WEAKENING" or (
            quadrant == "LEADING"
            and inst_flow is not None
            and inst_flow < 0
        ):
            verdict = "DISTRIBUTION_RISK"
        elif quadrant == "LAGGING" and breadth_pct is not None and (
            breadth_pct <= BREADTH_NARROW_PCT
        ):
            verdict = "AVOID_CAPITAL_TRAP"

        payload.append(
            {
                "trade_date": trade_date.isoformat(),
                "sector_name": sector,
                "rs_ratio": round(rs_ratio, 2),
                "rs_momentum": round(rs_momentum, 2),
                "quadrant": quadrant,
                "top_leader_ticker": leader,
                "top_dragger_ticker": dragger,
                "sessions_in_quadrant": sessions_in_quad,
                "weeks_in_quadrant": weeks_in_quad,
                "breadth_pct": (
                    round(breadth_pct, 2) if breadth_pct is not None else None
                ),
                "breadth_flag": breadth_flag,
                "net_inst_flow_pkr_5d": (
                    round(inst_flow, 2) if inst_flow is not None else None
                ),
                "net_retail_flow_pkr_5d": (
                    round(retail_flow, 2)
                    if retail_flow is not None
                    else None
                ),
                "verdict": verdict,
                "alpha_drivers": tails["drivers"],
                "alpha_draggers": tails["draggers"],
            }
        )

    LOGGER.info(
        "rotation %s: %d sectors published (%d members considered)",
        trade_date,
        len(payload),
        len(sector_of),
    )
    return payload


def run_sector_rotation(
    session_date: date | None = None, *, write: bool = True
) -> int:
    """One-shot rotation run: load, compute RRG, upsert psx_sector_rotation."""
    trade_date = session_date or date.today()
    benchmark = fetch_benchmark_series()
    if not benchmark:
        LOGGER.warning("rotation: no benchmark series; desk stays idle")
        return 0
    eod_history = db.fetch_recent_eod(days=90)
    fundamentals = db.fetch_recent_fundamentals()

    # Latest snapshot's ticker -> sector mapping.
    fund_day: Optional[date] = None
    for row in fundamentals:
        try:
            day = date.fromisoformat(str(row["trade_date"])[:10])
        except (ValueError, TypeError):
            continue
        if fund_day is None or day > fund_day:
            fund_day = day
    sector_of: dict[str, str] = {
        row["ticker"]: str(row.get("sector_name") or "")
        for row in fundamentals
        if fund_day is not None
        and str(row.get("trade_date"))[:10] == fund_day.isoformat()
    }

    flows = db.fetch_recent_flows(days=8)
    history = db.fetch_rotation_history(days=120)

    payload = compute_sector_rotation(
        trade_date,
        eod_history=eod_history,
        sector_of=sector_of,
        benchmark=benchmark,
        flows=flows,
        history=history,
    )
    if not payload:
        return 0
    if not write:
        return len(payload)
    written = db.upsert_records(
        "psx_sector_rotation",
        payload,
        on_conflict="trade_date,sector_name",
    )
    if written < len(payload):
        # Enriched columns not migrated yet (PGRST204 unknown column):
        # retry core-only so the desk still gets fresh RRG rows.
        LOGGER.warning(
            "rotation: enriched write incomplete (%d/%d) - retrying core columns",
            written,
            len(payload),
        )
        core = [
            {k: row[k] for k in CORE_ROTATION_FIELDS} for row in payload
        ]
        written += db.upsert_records(
            "psx_sector_rotation",
            core,
            on_conflict="trade_date,sector_name",
        )
    return written
