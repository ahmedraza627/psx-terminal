"""Global macro & commodity correlation / prediction engine.

Cross-correlates global macro driver daily returns against PSX sector and
constituent returns at lags T+0, T+1, T+2, T+3, T+5, T+10, fits an OLS beta
per lag, picks the optimal lag per pair, and stores:

  psx_macro_correlation  (trade_date, driver_code, sector_name) unique
      correlation, beta, optimal lag, sample size per SECTOR
  psx_macro_prediction   (trade_date, driver_code, sector_name) unique
      current shocks, expected sector move, confidence, named stock plays

Method (stdlib only - the pipeline carries no numpy):
  - Driver return at lag L pairs the macro return printed on session d with
    the PSX sector return L PSX-sessions later (session-geometric lag, not
    calendar-day lag: PSX holidays would otherwise distort the profile).
  - PSX sector return = equal-weight mean of member stock daily returns.
  - Pearson r per lag over overlapping pairs; OLS beta = r * (sd_psx / sd_drv).
  - Optimal lag = argmax |r| subject to n >= MIN_PAIRS and |r| >=
    MIN_CORRELATION; below the gate the pair is UNCORRELATED and is never
    predicted from.
  - Shock = latest macro close vs SHOCK_WINDOW sessions earlier - 1.
  - Prediction E[sector %] = beta_opt * shock_pct.
  - Confidence = |r| damped by its two-sided t-statistic when t < 2: a 0.80
    correlation on 15 samples is noise, and the desk says so.
"""

from __future__ import annotations

import logging
import math
from bisect import bisect_left
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Optional

from pipeline import db
from pipeline.scrapers.macro_indicators import STOOQ_DRIVERS, USD_PKR_DRIVER

LOGGER = logging.getLogger(__name__)

LAGS: tuple[int, ...] = (0, 1, 2, 3, 5, 10)
MIN_PAIRS = 60
MIN_CORRELATION = 0.30
SHOCK_WINDOW = 5
SHOCK_ALERT_THRESHOLD_PCT = 2.0
TOP_STOCKS_PER_SECTOR = 4
STOCK_MIN_CORRELATION = 0.25
LOOKBACK_DAYS = 400

DRIVER_LABELS: dict[str, str] = {
    code: label for code, (_sym, label) in STOOQ_DRIVERS.items()
}
DRIVER_LABELS[USD_PKR_DRIVER] = "USD/PKR"


# --------------------------------------------------------------------------- #
# Stats helpers (stdlib)                                                      #
# --------------------------------------------------------------------------- #
def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _sd(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mu = _mean(values)
    return math.sqrt(sum((v - mu) ** 2 for v in values) / (len(values) - 1))


def _pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 3 or n != len(ys):
        return 0.0
    mx, my = _mean(xs), _mean(ys)
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx <= 0 or vy <= 0:
        return 0.0
    return cov / math.sqrt(vx * vy)


def _confidence(r: float, n: int) -> float:
    """|r| damped linearly by its t-statistic below the t=2 bar."""
    ar = abs(r)
    if n < 3:
        return 0.0
    denom = 1.0 - r * r
    if denom <= 0:
        return ar
    t = ar * math.sqrt((n - 2) / denom)
    if t >= 2.0:
        return ar
    return ar * (t / 2.0)


# --------------------------------------------------------------------------- #
# Series loading                                                              #
# --------------------------------------------------------------------------- #
def _parse_date(value: Any) -> Optional[date]:
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def load_macro_series() -> dict[str, dict[date, float]]:
    """driver_code -> {session date: close} (all stored history)."""
    rows = db.fetch_macro_prices()
    out: dict[str, dict[date, float]] = defaultdict(dict)
    for r in rows:
        d = _parse_date(r.get("trade_date"))
        close = r.get("close")
        if d is None or close is None or float(close) <= 0:
            continue
        code = str(r.get("driver_code") or "").upper()
        if code:
            out[code][d] = float(close)
    return dict(out)


def load_psx_return_maps(
    days: int = LOOKBACK_DAYS,
) -> tuple[
    dict[str, dict[date, float]],          # ticker -> {date: daily return}
    dict[str, dict[date, float]],          # sector -> {date: equal-weight return}
    list[date],                            # active PSX sessions ascending
    dict[str, list[str]],                  # sector -> [ticker, ...]
]:
    """Daily return maps + calendar + membership from stored EOD + fundamentals."""
    eod = db.fetch_recent_eod(days=days)
    fundamentals = db.fetch_recent_fundamentals()

    member: dict[str, str] = {}
    for row in fundamentals:  # newest-first; first sighting wins
        ticker = str(row.get("ticker") or "").upper()
        sector = str(row.get("sector_name") or "").strip().upper()
        if ticker and sector and ticker not in member:
            member[ticker] = sector

    closes: dict[str, dict[date, float]] = defaultdict(dict)
    active: set[date] = set()
    for row in eod:
        d = _parse_date(row.get("trade_date"))
        close = row.get("close_price")
        if d is None or close is None or float(close) <= 0:
            continue
        ticker = str(row.get("ticker") or "").upper()
        closes[ticker][d] = float(close)
        if (row.get("volume") or 0) > 0:
            active.add(d)

    stock_ret: dict[str, dict[date, float]] = defaultdict(dict)
    for ticker, by_date in closes.items():
        dates_asc = sorted(by_date)
        for prev, cur in zip(dates_asc, dates_asc[1:]):
            base = by_date[prev]
            if base > 0:
                stock_ret[ticker][cur] = by_date[cur] / base - 1.0

    sector_ret: dict[str, dict[date, float]] = defaultdict(dict)
    sector_members: dict[str, list[str]] = defaultdict(list)
    buffers: dict[str, dict[date, list[float]]] = defaultdict(lambda: defaultdict(list))
    for ticker, rets in stock_ret.items():
        sector = member.get(ticker)
        if not sector:
            continue
        sector_members[sector].append(ticker)
        for d, r in rets.items():
            buffers[sector][d].append(r)
    for sector, by_date in buffers.items():
        for d, values in by_date.items():
            sector_ret[sector][d] = sum(values) / len(values)

    return dict(stock_ret), dict(sector_ret), sorted(active), dict(sector_members)


# --------------------------------------------------------------------------- #
# Lagged cross-correlation                                                    #
# --------------------------------------------------------------------------- #
def _lag_profile(
    driver_by_date: dict[date, float],
    psx_by_date: dict[date, float],
    psx_dates_asc: list[date],
    lag: int,
) -> tuple[list[float], list[float]]:
    """Paired (driver_ret, psx_ret) samples at the given session lag."""
    xs: list[float] = []
    ys: list[float] = []
    for d, dr in driver_by_date.items():
        i = bisect_left(psx_dates_asc, d)
        j = i + lag
        if j >= len(psx_dates_asc):
            continue
        target = psx_dates_asc[j]
        pr = psx_by_date.get(target)
        if pr is None:
            continue
        xs.append(dr)
        ys.append(pr)
    return xs, ys


def correlation_profile(
    driver_by_date: dict[date, float],
    psx_by_date: dict[date, float],
    psx_dates_asc: list[date],
) -> dict[int, dict[str, float]]:
    """lag -> {r, n, beta} across LAGS for one driver/target pair."""
    profile: dict[int, dict[str, float]] = {}
    for lag in LAGS:
        xs, ys = _lag_profile(driver_by_date, psx_by_date, psx_dates_asc, lag)
        n = min(len(xs), len(ys))
        if n < 3:
            continue
        r = _pearson(xs, ys)
        sd_x, sd_y = _sd(xs), _sd(ys)
        beta = r * (sd_y / sd_x) if sd_x > 0 else 0.0
        profile[lag] = {"r": r, "n": float(n), "beta": beta}
    return profile


def optimal_lag(profile: dict[int, dict[str, float]]) -> Optional[int]:
    """argmax |r| among lags passing the sample + correlation gates."""
    best: Optional[int] = None
    best_abs = 0.0
    for lag, stats in profile.items():
        n = int(stats["n"])
        r = stats["r"]
        if n < MIN_PAIRS or abs(r) < MIN_CORRELATION:
            continue
        if abs(r) > best_abs:
            best_abs = abs(r)
            best = lag
    return best


def driver_shock_pct(driver_by_date: dict[date, float]) -> Optional[float]:
    """Latest macro close vs SHOCK_WINDOW sessions earlier, in %."""
    if len(driver_by_date) < SHOCK_WINDOW + 1:
        return None
    dates_desc = sorted(driver_by_date, reverse=True)
    latest = driver_by_date[dates_desc[0]]
    base = driver_by_date[dates_desc[SHOCK_WINDOW]]
    if base <= 0:
        return None
    return (latest / base - 1.0) * 100.0


# --------------------------------------------------------------------------- #
# Stock-level attribution at the sector's optimal lag                         #
# --------------------------------------------------------------------------- #
def top_stock_plays(
    sector: str,
    members: list[str],
    stock_ret: dict[str, dict[date, float]],
    driver_by_date: dict[date, float],
    psx_dates_asc: list[date],
    lag: int,
    shock_pct: float,
) -> list[dict[str, Any]]:
    plays: list[dict[str, Any]] = []
    for ticker in members:
        rets = stock_ret.get(ticker)
        if not rets:
            continue
        xs, ys = _lag_profile(driver_by_date, rets, psx_dates_asc, lag)
        if min(len(xs), len(ys)) < MIN_PAIRS:
            continue
        r = _pearson(xs, ys)
        if abs(r) < STOCK_MIN_CORRELATION:
            continue
        sd_x, sd_y = _sd(xs), _sd(ys)
        beta = r * (sd_y / sd_x) if sd_x > 0 else 0.0
        plays.append(
            {
                "ticker": ticker,
                "correlation": round(r, 4),
                "beta": round(beta, 4),
                "expected_move_pct": round(beta * shock_pct, 2),
            }
        )
    plays.sort(key=lambda p: abs(p["expected_move_pct"]), reverse=True)
    return plays[:TOP_STOCKS_PER_SECTOR]


# --------------------------------------------------------------------------- #
# Engine entry point                                                          #
# --------------------------------------------------------------------------- #
def run_macro_engine(
    session_date: date | None = None, *, write: bool = True
) -> int:
    """Compute + store correlation profiles and live-shock predictions.

    Returns the number of prediction rows written (correlations always
    refresh when data allows). Degrades to 0 with a warning when either
    feed is too short - never fabricates a correlation.
    """
    trade_date = session_date or date.today()
    macro = load_macro_series()
    if not macro:
        LOGGER.warning("macro engine: no indicator prices stored; run the macro scraper first")
        return 0

    stock_ret, sector_ret, psx_sessions, members = load_psx_return_maps()
    if not sector_ret or len(psx_sessions) < MIN_PAIRS:
        LOGGER.warning(
            "macro engine: PSX history too short (%d sessions); correlations idle",
            len(psx_sessions),
        )
        return 0

    correlation_rows: list[dict[str, Any]] = []
    prediction_rows: list[dict[str, Any]] = []

    for code in sorted(set(macro) | {USD_PKR_DRIVER}):
        series = macro.get(code)
        if not series or len(series) < MIN_PAIRS:
            LOGGER.info("macro engine: %s has < %d sessions; skipped", code, MIN_PAIRS)
            continue

        shock = driver_shock_pct(series)
        if shock is None:
            LOGGER.info("macro engine: %s shock window unavailable", code)
            continue

        for sector in sorted(sector_ret):
            profile = correlation_profile(series, sector_ret[sector], psx_sessions)
            if not profile:
                continue
            lag_opt = optimal_lag(profile)
            if lag_opt is None:
                continue  # honest UNCORRELATED: no row, no prediction
            stats = profile[lag_opt]
            correlation_rows.append(
                {
                    "trade_date": trade_date.isoformat(),
                    "driver_code": code,
                    "sector_name": sector,
                    "lag_days": int(lag_opt),
                    "correlation": round(stats["r"], 4),
                    "beta": round(stats["beta"], 4),
                    "sample_size": int(stats["n"]),
                    "method": "pearson_lagged_ols",
                }
            )

            if abs(shock) < SHOCK_ALERT_THRESHOLD_PCT:
                continue  # standing matrix only; no prediction below shock gate

            expected = stats["beta"] * shock
            plays = top_stock_plays(
                sector,
                members.get(sector, []),
                stock_ret,
                series,
                psx_sessions,
                lag_opt,
                shock,
            )
            prediction_rows.append(
                {
                    "trade_date": trade_date.isoformat(),
                    "driver_code": code,
                    "sector_name": sector,
                    "shock_window_sessions": SHOCK_WINDOW,
                    "shock_pct": round(shock, 2),
                    "expected_move_pct": round(expected, 2),
                    "optimal_lag_days": int(lag_opt),
                    "confidence": round(_confidence(stats["r"], int(stats["n"])), 4),
                    "stock_plays": plays,
                }
            )

    if not write:
        LOGGER.info(
            "macro engine (dry): %d correlations, %d predictions",
            len(correlation_rows),
            len(prediction_rows),
        )
        return len(prediction_rows)

    written_corr = 0
    written_pred = 0
    if correlation_rows:
        try:
            written_corr = db.upsert_records(
                "psx_macro_correlation",
                correlation_rows,
                on_conflict="trade_date,driver_code,sector_name",
            )
        except Exception as exc:  # noqa: BLE001
            if "PGRST205" in str(exc) or "schema cache" in str(exc):
                LOGGER.warning("psx_macro_correlation missing - apply schema.sql")
            else:
                raise
    if prediction_rows:
        try:
            written_pred = db.upsert_records(
                "psx_macro_prediction",
                prediction_rows,
                on_conflict="trade_date,driver_code,sector_name",
            )
        except Exception as exc:  # noqa: BLE001
            if "PGRST205" in str(exc) or "schema cache" in str(exc):
                LOGGER.warning("psx_macro_prediction missing - apply schema.sql")
            else:
                raise

    LOGGER.info(
        "macro engine: %d correlation rows, %d prediction rows (session %s)",
        written_corr,
        written_pred,
        trade_date,
    )
    return written_pred