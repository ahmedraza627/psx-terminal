"""Sector Relative Rotation (RRG) engine - benchmarked against KSE-100.

Methodology (daily RRG):
  1. Sector index      : equal-weighted accumulation of member daily
                         returns from stored psx_daily_eod closes.
  2. Benchmark index   : KSE-100 closes fetched live from the DPS
                         timeseries endpoint (verified 2026-09-12:
                         /timeseries/eod/KSE100 -> [ts, close, vol, ldcp]).
  3. RS-Ratio          : sector_index / benchmark_index, normalised to a
                         base of 100 over the lookback window.
  4. RS-Momentum       : 100 x (rs_ratio_norm(t) / rs_ratio_norm(t - span)),
                         span = RRG_JACOB_SPAN sessions (default 5).
  5. Quadrant          : LEADING (ratio>=100, mom>=100) / WEAKENING
                         (ratio>=100, mom<100) / IMPROVING (ratio<100,
                         mom>=100) / LAGGING (ratio<100, mom<100).

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
from datetime import date
from typing import Any, Optional

from pipeline import db
from pipeline.http_client import http_get

LOGGER = logging.getLogger(__name__)

RRG_LOOKBACK_SESSIONS = int(os.getenv("RRG_LOOKBACK_SESSIONS", "60"))
RRG_JACOB_SPAN = int(os.getenv("RRG_JACOB_SPAN", "5"))
MIN_SECTOR_MEMBERS = int(os.getenv("RRG_MIN_SECTOR_MEMBERS", "4"))
BENCHMARK_SYMBOL = os.getenv("RRG_BENCHMARK", "KSE100")

_benchmark_cache: dict[str, list[tuple[date, float]]] = {}


def fetch_benchmark_series(symbol: str = BENCHMARK_SYMBOL) -> list[tuple[date, float]]:
    """KSE-100 (or any DPS index) closes, newest-first, cached per process."""
    if symbol in _benchmark_cache:
        return _benchmark_cache[symbol]
    url = f"https://dps.psx.com.pk/timeseries/eod/{symbol}"
    try:
        response = http_get(url, timeout=25.0)
        payload = response.json()
    except Exception as exc:  # noqa: BLE001 - benchmark down = idle desk
        LOGGER.warning("benchmark series %s unavailable: %s", symbol, exc)
        _benchmark_cache[symbol] = []
        return _benchmark_cache[symbol]
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
    _benchmark_cache[symbol] = series
    LOGGER.info("benchmark %s: %d sessions", symbol, len(series))
    return series


def _quadrant(rs_ratio: float, rs_momentum: float) -> str:
    if rs_ratio >= 100.0:
        return "LEADING" if rs_momentum >= 100.0 else "WEAKENING"
    return "IMPROVING" if rs_momentum >= 100.0 else "LAGGING"


def compute_sector_rotation(
    trade_date: date,
    *,
    eod_history: list[dict[str, Any]],
    sector_of: dict[str, str],
    benchmark: list[tuple[date, float]],
) -> list[dict[str, Any]]:
    """Build the psx_sector_rotation payload for one session."""
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

        payload.append(
            {
                "trade_date": trade_date.isoformat(),
                "sector_name": sector,
                "rs_ratio": round(rs_ratio, 2),
                "rs_momentum": round(rs_momentum, 2),
                "quadrant": _quadrant(rs_ratio, rs_momentum),
                "top_leader_ticker": leader,
                "top_dragger_ticker": dragger,
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

    payload = compute_sector_rotation(
        trade_date,
        eod_history=eod_history,
        sector_of=sector_of,
        benchmark=benchmark,
    )
    if not payload:
        return 0
    if not write:
        return len(payload)
    return db.upsert_records(
        "psx_sector_rotation", payload, on_conflict="trade_date,sector_name"
    )
