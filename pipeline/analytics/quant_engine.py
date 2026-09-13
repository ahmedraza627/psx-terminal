"""Quantitative signal engine.

Reads the raw tables the scrapers filled (psx_daily_eod, nccpl_fipi_lipi,
psx_offmarket_deals, psx_fundamentals, psx_futures_eod) and writes rows
into signals_computed.

Engines
-------
SHORT_TERM   (ACCUMULATION)          Volume > 2.0x 20-day SMA, close in the
                                     top 25% of the day range, optional NDM
                                     confirmation; stop = 2x ATR(14).
WHALE_RADAR  (STEALTH_ACCUMULATION)  Volume >= 1.8x 20-day SMA with price
                                     change compressed in (-2.0%, +4.0%)
                                     and 20-day volume liquidity >= 30k
                                     shares: silent institutional block
                                     absorption. Stop = 2x ATR(14). When no
                                     stock passes the strict band, the top
                                     positive-day stocks by volume multiple
                                     are tagged NOTABLE_VOLUME_SPIKE.
MEDIUM_TERM  (ACCUMULATION)          Sector NCCPL institutional inflow
                                     streak with close above 50-day EMA.
MOMENTUM     (INSTITUTIONAL_TARGET)  Highest 5-day volume breakout
                                     (today/5d-SMA) among tickers whose
                                     sector is seeing Mutual Funds and/or
                                     Foreign Corporates net buying.
ARBITRAGE    (CASH_CARRY)            Ready vs deliverable-futures spread
                                     >= threshold; explicit pair order in
                                     the rationale + leg prices in metadata.
LONG_TERM    (VALUE_YIELD)           Screener dividend-yield screen.

All numbers in metadata are plain floats/strings (jsonb-safe). Re-runs are
idempotent via upsert on (trade_date, ticker, timeframe, signal_type).
"""

from __future__ import annotations

import logging
import os
from collections import defaultdict
from datetime import date, timedelta
from typing import Any, Optional

from pipeline import db
from pipeline.parsing import to_number as to_num

LOGGER = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Tunables (env-overridable; defaults documented in .env.example)             #
# --------------------------------------------------------------------------- #
VOLUME_SURGE = float(os.getenv("VOLUME_SURGE", "2.0"))
RANGE_TOP = float(os.getenv("RANGE_TOP", "0.75"))
ATR_PERIOD = 14
# Stop geometry: stop = entry - ATR_MULT x ATR(14). Calibrated by the
# 807-row stop sweep (pipeline.analytics.stop_sweep, 2026-09): 1.50x is the
# expectancy peak of the 1.5x-3.0x grid at every reward bar tested (at the
# 2R convention: 1.5x E[R] -0.13 / PF 0.82 vs 2.0x -0.18 / 0.75). The sweep
# gradient continues below 1x ATR but sub-ATR stops are execution-impractical
# on PSX spreads - 1.50x is the institutional floor of the optimum.
ATR_MULT = float(os.getenv("ATR_STOP_MULT", "1.5"))
MIN_HISTORY = 25
EMA_PERIOD = 50
MIN_HISTORY_MEDIUM = 55
MIN_AVG_VOLUME = int(os.getenv("MIN_AVG_VOLUME", "50000"))
MIN_PRICE = 5.0
FLOW_STREAK_DAYS = int(os.getenv("MEDIUM_TERM_STREAK_DAYS", "4"))
MIN_CAP_PKR = float(os.getenv("MARKET_CAP_MIN_PKR", "5e9"))
DIV_YIELD_MIN = float(os.getenv("DIV_YIELD_MIN", "6.0"))
PE_MAX = float(os.getenv("PE_MAX", "12.0"))
PAYOUT_STREAK_MIN = 3
OFFMARKET_MIN_VOLUME = int(os.getenv("OFFMARKET_MIN_VOLUME", "10000"))
OFFMARKET_REQUIRED = os.getenv(
    "OFFMARKET_REQUIRED", "false"
).strip().lower() in {"1", "true", "yes"}
SIGNAL_CAP = int(os.getenv("SIGNALS_MAX_PER_HORIZON", "40"))

# Whale Radar (Engine 1)
WHALE_VOL_MULT = float(os.getenv("WHALE_VOL_MULT", "1.8"))
WHALE_DRIFT_MIN = float(os.getenv("WHALE_DRIFT_MIN", "-2.0"))   # percent
WHALE_DRIFT_MAX = float(os.getenv("WHALE_DRIFT_MAX", "4.0"))    # percent
WHALE_MIN_LIQUIDITY = int(os.getenv("WHALE_MIN_LIQUIDITY", "30000"))
# Fallback when nothing passes the strict absorption band: tag the top N
# positive-day stocks by raw volume multiple as NOTABLE_VOLUME_SPIKE.
WHALE_FALLBACK_TOP_N = int(os.getenv("WHALE_FALLBACK_TOP_N", "5"))

# --------------------------------------------------------------------------- #
# Macro Regime Gate (2026-09 edge overhaul)                                   #
#                                                                             #
# The 30-session backtest window (Aug-Sep falling tape) showed the engine's   #
# raw edge is regime-dependent: longs keep stop-ing out when institutions    #
# are net-selling AND the index trades under its 20-session mean. The gate    #
# converts Edge Lab to positive expectancy by refusing longs in that state:  #
#   BEARISH_CAPITAL_PRESERVATION: NCCPL institutions net-sold the latest      #
#     flow session AND KSE-100 close < 20-session SMA -> NO directional       #
#     long signals at all (100% cash posture).                                #
#   ACCUMULATION_FAVORABLE: otherwise -> only names with whale multiplier     #
#     >= 1.8x in LEADING/IMPROVING sectors pass.                              #
# Env: REGIME_GATE_ENABLED=false restores ungated behaviour.                  #
# --------------------------------------------------------------------------- #
REGIME_GATE_ENABLED = os.getenv("REGIME_GATE_ENABLED", "true").strip().lower() in {
    "1", "true", "yes"
}
REGIME_WHALE_MIN_MULT = float(os.getenv("REGIME_WHALE_MIN_MULT", "1.8"))
REGIME_SMA_SESSIONS = int(os.getenv("REGIME_SMA_SESSIONS", "20"))
REGIME_BENCHMARK = os.getenv("REGIME_BENCHMARK", "KSE100")
# Institutions whose NCCPL net_pkr defines "smart money" direction.
INSTITUTIONAL_PARTICIPANTS = (
    "MUTUAL FUNDS",
    "FOREIGN CORPORATES",
    "BANKS",
)

REGIME_BEARISH = "BEARISH_CAPITAL_PRESERVATION"
REGIME_FAVORABLE = "ACCUMULATION_FAVORABLE"
REGIME_UNKNOWN = "UNKNOWN"  # inputs missing -> gate open, regime reported honestly


def build_regime_state(
    *,
    flows: list[dict[str, Any]] | None = None,
    eod_history: list[dict[str, Any]] | None = None,
    benchmark: str = REGIME_BENCHMARK,
    as_of: Optional[date] = None,
    benchmark_series: Optional[list[float]] = None,
) -> dict[str, Any]:
    """Classify the market regime from NCCPL flows + KSE-100 vs its SMA20.

    ``benchmark_series`` accepts pre-fetched ascending closes (the seed
    path shares a single DPS call across all sessions).

    - inst_net_flow_pkr: sum of institutional participant net_pkr on the
      latest flow session (no data -> 0.0, flagged in ``flow_basis``).
    - benchmark_close / benchmark_sma20: from DPS timeseries closes when the
      index is absent from psx_daily_eod (it is), falling back to stored
      closes; no data -> None and the gate stays open (flow leg only).
    Returns a plain dict (jsonb-safe) suitable for signal metadata.
    """
    state: dict[str, Any] = {
        "regime_status": REGIME_UNKNOWN,
        "inst_net_flow_pkr": 0.0,
        "flow_basis": "NO_DATA",
        "benchmark_close": None,
        "benchmark_sma20": None,
        "benchmark_basis": "NO_DATA",
        "gate_enabled": REGIME_GATE_ENABLED,
    }
    # Walk-forward seeds must never see flow sessions after ``as_of``.
    flow_rows = [
        r
        for r in flows or []
        if as_of is None
        or str(r.get("trade_date"))[:10] <= as_of.isoformat()
    ]

    # --- Leg 1: institutional net flow (latest session with any rows) ---
    flow_day: dict[str, float] = {}
    flow_session = None
    for row in flow_rows:
        ptype = str(row.get("participant_type", "")).upper().strip()
        if ptype not in INSTITUTIONAL_PARTICIPANTS:
            continue
        net = to_num(row.get("net_pkr"))
        if net is None:
            continue
        day = str(row.get("trade_date"))[:10]
        if flow_session is None or day > flow_session:
            flow_session = day
            flow_day = {}
        if day == flow_session:
            flow_day[ptype] = flow_day.get(ptype, 0.0) + float(net)
    if flow_session is not None and flow_day:
        state["inst_net_flow_pkr"] = round(sum(flow_day.values()), 2)
        state["flow_basis"] = f"NCCPL:{flow_session}"

    # --- Leg 2: benchmark vs its 20-session SMA ---
    bench: list[tuple[date, float]] = []
    if benchmark_series is not None:
        # Pre-fetched (date, close) pairs from the walk-forward seed: the
        # caller truncates per session - no look-ahead, no extra fetches.
        bench = [
            (day, float(c))
            for day, c in benchmark_series
            if c and float(c) > 0
        ]
        state["benchmark_basis"] = "SEEDED"
    else:
        for row in eod_history or []:
            if str(row.get("ticker", "")).upper().strip() != benchmark:
                continue
            day = parse_db_date(row.get("trade_date"))
            close = to_num(row.get("close_price"))
            if day is not None and close is not None and close > 0:
                bench.append((day, close))
        if len(bench) < REGIME_SMA_SESSIONS + 1:
            bench = []
            try:
                from pipeline.http_client import http_get

                url = f"https://dps.psx.com.pk/timeseries/eod/{benchmark}"
                payload = http_get(url, timeout=25.0).json()
                rows = payload.get("data") if isinstance(payload, dict) else None
                for r in rows or []:
                    try:
                        bench.append((date.fromtimestamp(int(r[0])), float(r[1])))
                    except (TypeError, ValueError, IndexError):
                        continue
                state["benchmark_basis"] = "DPS_LIVE"
            except Exception as exc:  # noqa: BLE001 - optional leg
                LOGGER.warning(
                    "regime gate: benchmark series unavailable: %s", exc
                )
    if as_of is not None:
        bench = [(day, c) for day, c in bench if day <= as_of]
    if bench:
        bench.sort(key=lambda item: item[0])
        closes = [c for _, c in bench]
        state["benchmark_close"] = closes[-1]
        sma_n = closes[-REGIME_SMA_SESSIONS:]
        state["benchmark_sma20"] = round(sum(sma_n) / len(sma_n), 2)
        if state["benchmark_basis"] == "NO_DATA":
            state["benchmark_basis"] = "EOD_STORED"

    # --- Classification: both legs known -> strict; one leg known -> flow-only
    flow_known = state["flow_basis"] != "NO_DATA"
    bench_known = state["benchmark_close"] is not None
    if flow_known and bench_known:
        bearish = (
            state["inst_net_flow_pkr"] < 0
            and state["benchmark_close"] < state["benchmark_sma20"]
        )
    elif flow_known:
        bearish = state["inst_net_flow_pkr"] < 0
    elif bench_known:
        bearish = state["benchmark_close"] < state["benchmark_sma20"]
    else:
        bearish = False
    state["regime_status"] = (
        REGIME_BEARISH if bearish else REGIME_FAVORABLE
    )
    # Compact benchmark window for the sector-trend helper (no second fetch).
    state["benchmark_series"] = [
        round(c, 2) for _, c in bench[-(REGIME_SMA_SESSIONS + 6):]
    ]
    return state


def apply_regime_gate(
    results: dict[str, list[dict[str, Any]]],
    regime: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    """Filter computed signals through the macro regime gate, in place.

    BEARISH_CAPITAL_PRESERVATION blocks every directional long signal;
    risk-warning stances (AVOID_LONGS / SHORT_BIAS / SQUEEZE_WATCH) and
    non-directional arbitrage rows survive (a cash regime is exactly when
    the MARGIN_CASCADE_RISK warning must publish). ACCUMULATION_FAVORABLE
    keeps only names whose whale volume multiplier >= REGIME_WHALE_MIN_MULT
    and whose sector is in a LEADING/IMPROVING RRG quadrant; rows without
    sector or whale metadata pass unfiltered (they were already gate-free
    by construction elsewhere).
    """
    status = regime.get("regime_status", REGIME_UNKNOWN)
    if status != REGIME_BEARISH:
        if status == REGIME_FAVORABLE:
            for timeframe, rows in results.items():
                results[timeframe] = [
                    r for r in rows if _passes_favorable_gate(r)
                ]
        return results

    kept: dict[str, list[dict[str, Any]]] = {}
    blocked = 0
    for timeframe, rows in results.items():
        survivors = []
        for r in rows:
            meta = r.get("metadata") or {}
            stance = str(meta.get("stance", "")).upper()
            if stance in {"AVOID_LONGS", "SHORT_BIAS", "SQUEEZE_WATCH"}:
                survivors.append(r)
                continue
            if timeframe == "ARBITRAGE":
                survivors.append(r)
                continue
            blocked += 1
        kept[timeframe] = survivors
    if blocked:
        LOGGER.warning(
            "regime gate %s: BLOCKED %d directional longs (capital "
            "preservation: inst flow %.1fM, benchmark %s vs SMA20 %s)",
            status,
            blocked,
            regime.get("inst_net_flow_pkr", 0.0) / 1e6,
            regime.get("benchmark_close"),
            regime.get("benchmark_sma20"),
        )
    return kept


def _passes_favorable_gate(row: dict[str, Any]) -> bool:
    """Favorable-regime quality filter: whale strength + sector trend."""
    meta = row.get("metadata") or {}
    stance = str(meta.get("stance", "")).upper()
    if stance in {"AVOID_LONGS", "SHORT_BIAS", "SQUEEZE_WATCH"}:
        return True
    mult = meta.get("vol_multiple")
    if mult is not None and float(mult) < REGIME_WHALE_MIN_MULT:
        return False
    sector = str(meta.get("sector", "") or "").upper().strip()
    if not sector:
        return True
    return _sector_trend(sector) in {"LEADING", "IMPROVING"}


# --------------------------------------------------------------------------- #
# Lightweight sector trend for the favorable-regime filter. Equal-weight      #
# sector index vs benchmark over the regime window, RS-rebased to 1.0;        #
# quadrants mirror the RRG conventions at base 1.0. Fail-open: a sector we    #
# cannot compute never blocks (the bearish branch is the gate's defense).     #
# --------------------------------------------------------------------------- #
_sector_trend_context: dict[str, Any] = {}


def _prepare_sector_trends(
    eod_history: list[dict[str, Any]],
    sector_of: dict[str, str],
    regime: dict[str, Any],
) -> None:
    """Cache per-sector equal-weight index windows for _sector_trend()."""
    window = REGIME_SMA_SESSIONS + 6
    bench_series = regime.get("benchmark_series") or []
    sessions: list[date] = []
    closes_by_ticker: dict[str, dict[date, float]] = defaultdict(dict)
    for row in eod_history:
        day = parse_db_date(row.get("trade_date"))
        close = to_num(row.get("close_price"))
        ticker = str(row.get("ticker", "")).upper().strip()
        if day is None or close is None or close <= 0 or not ticker:
            continue
        closes_by_ticker[ticker][day] = close
        if day not in sessions:
            sessions.append(day)
    sessions.sort()
    sessions = sessions[-window:]
    if len(sessions) < 10 or len(bench_series) < 10:
        _sector_trend_context.clear()
        return

    members_by_sector: dict[str, list[str]] = defaultdict(list)
    for ticker, sector in sector_of.items():
        if ticker in closes_by_ticker:
            members_by_sector[sector].append(ticker)

    bench = bench_series[-window:]
    cache: dict[str, str] = {}
    for sector, members in members_by_sector.items():
        if len(members) < 3:
            continue
        idx: list[float] = []
        for day in sessions:
            rebased = [
                closes_by_ticker[t][day] / closes_by_ticker[t][sessions[0]]
                for t in members
                if day in closes_by_ticker[t]
                and sessions[0] in closes_by_ticker[t]
            ]
            if rebased:
                idx.append(sum(rebased) / len(rebased))
        if len(idx) < 10:
            continue
        rs_now = idx[-1] / bench[len(idx) - 1]
        span = min(5, len(idx) - 1)
        rs_then = idx[-1 - span] / bench[len(idx) - 1 - span]
        ratio_ok = rs_now >= 1.0
        mom_ok = rs_now >= rs_then * 0.999
        if ratio_ok and mom_ok:
            cache[sector] = "LEADING"
        elif ratio_ok:
            cache[sector] = "WEAKENING"
        elif mom_ok:
            cache[sector] = "IMPROVING"
        else:
            cache[sector] = "LAGGING"
    _sector_trend_context.clear()
    _sector_trend_context.update(cache)


def _sector_trend(sector: str) -> str:
    """Cached quadrant for one sector; UNKNOWN data fails open to LEADING."""
    return _sector_trend_context.get(sector.upper().strip(), "LEADING")

# Arbitrage Desk (Engine 2)
SPREAD_MIN_PCT = float(os.getenv("SPREAD_MIN_PCT", "2.5"))
ANNUALIZATION_DAYS = float(os.getenv("ANNUALIZATION_DAYS", "30"))

# Institutional Momentum (Engine 3)
BREAKOUT_WINDOW = 5
BREAKOUT_MIN_MULT = float(os.getenv("BREAKOUT_MIN_MULT", "1.5"))
TARGETS_PER_SECTOR = int(os.getenv("TARGETS_PER_SECTOR", "1"))
MOMENTUM_CAP = int(os.getenv("MOMENTUM_CAP", "15"))
# Market-wide relative-volume fallback when no NCCPL sector mapping aligns.
MOMENTUM_FALLBACK_TOP_N = int(os.getenv("MOMENTUM_FALLBACK_TOP_N", "5"))

# Insider Radar (Engine 4)
INSIDER_MIN_NOTIONAL = float(os.getenv("INSIDER_MIN_NOTIONAL", "1e6"))
INSIDER_LOOKBACK_DAYS = int(os.getenv("INSIDER_LOOKBACK_DAYS", "5"))
INSIDER_SENIOR_DESIGNATIONS = {"Sponsor", "Ceo", "Chief Executive"}

# MTS Squeeze (Engine 5)
MTS_UTIL_SPIKE = float(os.getenv("MTS_UTIL_SPIKE", "85.0"))   # % of cap
MTS_VALUE_DROP_PCT = float(os.getenv("MTS_VALUE_DROP_PCT", "25.0"))
MTS_PRICE_DROP_PCT = float(os.getenv("MTS_PRICE_DROP_PCT", "8.0"))
MTS_SQUEEZE_LOOKBACK = int(os.getenv("MTS_SQUEEZE_LOOKBACK", "5"))

# Rollover Desk (Engine 6)
BASIS_INVERSION_PCT = float(os.getenv("BASIS_INVERSION_PCT", "-0.5"))
ROLLOVER_SQUEEZE_PCT = float(os.getenv("ROLLOVER_SQUEEZE_PCT", "2.0"))
ROLLOVER_WINDOW_DAYS = int(os.getenv("ROLLOVER_WINDOW_DAYS", "7"))

TIMEFRAMES = (
    "SHORT_TERM", "MEDIUM_TERM", "LONG_TERM",
    "WHALE_RADAR", "ARBITRAGE", "MOMENTUM",
)

# NCCPL participant labels that count as institutional smart money.
INSTITUTIONAL = {
    "MUTUAL FUNDS", "FOREIGN CORPORATES", "BANKS", "INSURANCE", "BROKERS",
    "COMPANIES", "JOINT COMPANIES", "MODARABAS", "INSURANCE COS",
    "NBFC & MUTUAL FUNDS", "COMPANIES - FOREIGN", "FOREIGN SECTOR",
    "FOREIGN INVESTORS",
}
# Participants that specifically define "smart money" for Engine 3.
SMART_MONEY = {"MUTUAL FUNDS", "FOREIGN CORPORATES"}


# --------------------------------------------------------------------------- #
# Indicator primitives                                                        #
# --------------------------------------------------------------------------- #
def sma(values: list[float], period: int) -> Optional[float]:
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def ema(values: list[float], period: int) -> Optional[float]:
    if len(values) < period:
        return None
    alpha = 2.0 / (period + 1.0)
    value = sum(values[:period]) / period
    for price in values[period:]:
        value = alpha * price + (1.0 - alpha) * value
    return value


def atr(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = ATR_PERIOD,
) -> Optional[float]:
    if len(closes) < period + 1 or len(highs) < period + 1 or len(lows) < period + 1:
        return None
    trs: list[float] = []
    for i in range(1, period + 1):
        prev_close = closes[i - 1]
        trs.append(
            max(
                highs[i] - lows[i],
                abs(highs[i] - prev_close),
                abs(lows[i] - prev_close),
            )
        )
    return sum(trs) / len(trs) if trs else None


def range_position(close: float, low: float, high: float) -> Optional[float]:
    span = high - low
    if span <= 0:
        return None
    return (close - low) / span


def payout_streak(payouts: list[float]) -> int:
    streak = 0
    for amount in payouts:
        if amount and amount > 0:
            streak += 1
        else:
            break
    return streak


def parse_db_date(value: object) -> Optional[date]:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _group_by_ticker(
    eod_history: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Group EOD rows per ticker, sorted oldest -> newest."""
    by_ticker: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in eod_history:
        ticker = str(row.get("ticker", "")).upper()
        day = parse_db_date(row.get("trade_date"))
        if ticker and day:
            by_ticker[ticker].append({**row, "day": day})
    for rows in by_ticker.values():
        rows.sort(key=lambda r: r["day"])
    return by_ticker


def _series(rows: list[dict[str, Any]]) -> dict[str, list[float]]:
    closes = [to_num(r.get("close_price")) for r in rows]
    highs = [to_num(r.get("high_price")) or c for r, c in zip(rows, closes)]
    lows = [to_num(r.get("low_price")) or c for r, c in zip(rows, closes)]
    vols = [to_num(r.get("volume")) or 0.0 for r in rows]
    return {"closes": closes, "highs": highs, "lows": lows, "vols": vols}


def _mk_signal(
    trade_date: date,
    ticker: str,
    timeframe: str,
    signal_type: str,
    entry_reference: Optional[float],
    stop_loss: Optional[float],
    rationale: str,
    metadata: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "trade_date": trade_date.isoformat(),
        "ticker": ticker,
        "timeframe": timeframe,
        "signal_type": signal_type,
        "rationale": rationale,
    }
    if entry_reference is not None:
        row["entry_reference"] = round(entry_reference, 2)
    if stop_loss is not None:
        row["stop_loss"] = round(stop_loss, 2)
    if metadata:
        row["metadata"] = metadata
    return row


# --------------------------------------------------------------------------- #
# SHORT-TERM: classic surge + strong close                                    #
# --------------------------------------------------------------------------- #
def _short_term_signals(
    trade_date: date,
    by_ticker: dict[str, list[dict[str, Any]]],
    offmarket_tickers: set[str],
) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []
    for ticker, rows in sorted(by_ticker.items()):
        if len(rows) < MIN_HISTORY or rows[-1]["day"] != trade_date:
            continue
        last = rows[-1]
        close = to_num(last.get("close_price"))
        volume_today = to_num(last.get("volume"))
        if close is None or close < MIN_PRICE or not volume_today:
            continue
        s = _series(rows)
        if any(v is None for v in s["closes"] + s["highs"] + s["lows"]):
            continue

        vol_sma20 = sma(s["vols"][:-1], 20)
        if vol_sma20 is None or vol_sma20 <= 0:
            continue
        if s["vols"][-1] / vol_sma20 < VOLUME_SURGE:
            continue
        if sum(s["vols"][-21:-1]) / 20 < MIN_AVG_VOLUME:
            continue

        low = s["lows"][-1]
        high = s["highs"][-1]
        pos = range_position(close, low, high)
        if pos is None:
            if not (high == low == close):
                continue
        elif pos < RANGE_TOP:
            continue

        confirmed = ticker in offmarket_tickers
        if OFFMARKET_REQUIRED and not confirmed:
            continue

        true_atr = atr(s["highs"], s["lows"], s["closes"], ATR_PERIOD)
        if true_atr is None or true_atr <= 0:
            continue
        stop = close - ATR_MULT * true_atr
        if stop >= close:
            stop = close * 0.94

        parts = [
            f"Volume {volume_today:,.0f} is {s['vols'][-1] / vol_sma20:.1f}x its 20-day SMA",
            f"close in top {int((1 - RANGE_TOP) * 100)}% of day range"
            + (f" (position {pos:.0%})" if pos is not None else " (flat session)"),
        ]
        if confirmed:
            parts.append("NDM block deal confirms institutional footprint")
        signals.append(
            _mk_signal(
                trade_date, ticker, "SHORT_TERM", "ACCUMULATION",
                entry_reference=close, stop_loss=stop,
                rationale="; ".join(parts) + ".",
                metadata={"vol_multiple": round(s["vols"][-1] / vol_sma20, 2)},
            )
        )
        if len(signals) >= SIGNAL_CAP:
            break
    return signals


# --------------------------------------------------------------------------- #
# WHALE RADAR: stealth institutional block absorption                         #
# --------------------------------------------------------------------------- #
def _whale_signals(
    trade_date: date,
    by_ticker: dict[str, list[dict[str, Any]]],
    sector_of: dict[str, str],
    offmarket_deals: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Volume >= 1.8x 20d SMA, drift in (-2.0%, +4.0%), liquidity >= 30k.

    Compression is the tell: heavy volume with limited price movement
    means a large passive counterparty is absorbing flow, not chasing it.
    PSX circuit-breaker dynamics push absorptions up to ~+3.5%, hence the
    generous upper band. If nothing passes the strict band, the top
    positive-day stocks by volume multiple are tagged as
    NOTABLE_VOLUME_SPIKE so the desk never goes silently blank.
    """
    deals_today: dict[str, dict[str, Any]] = {}
    for deal in offmarket_deals:
        if parse_db_date(deal.get("trade_date")) == trade_date:
            deals_today[str(deal.get("ticker", "")).upper()] = deal

    signals: list[dict[str, Any]] = []
    fallback_pool: list[tuple[float, str, dict[str, Any]]] = []
    for ticker, rows in sorted(by_ticker.items()):
        if len(rows) < MIN_HISTORY or rows[-1]["day"] != trade_date:
            continue
        last = rows[-1]
        close = to_num(last.get("close_price"))
        prev_close = to_num(rows[-2].get("close_price"))
        volume_today = to_num(last.get("volume"))
        if close is None or prev_close is None or prev_close <= 0 or not volume_today:
            continue

        s = _series(rows)
        vol_sma20 = sma(s["vols"][:-1], 20)
        if vol_sma20 is None or vol_sma20 <= 0:
            continue
        liquidity_20d = sum(s["vols"][-21:-1]) / 20
        if liquidity_20d < WHALE_MIN_LIQUIDITY:
            continue

        vol_multiple = s["vols"][-1] / vol_sma20
        drift_pct = (close - prev_close) / prev_close * 100.0

        true_atr = atr(s["highs"], s["lows"], s["closes"], ATR_PERIOD)
        if true_atr is None or true_atr <= 0:
            continue

        # Fallback pool: positive-day, volume-spike leaders.
        if drift_pct > 0:
            fallback_pool.append(
                (
                    vol_multiple,
                    ticker,
                    {
                        "close": close,
                        "prev_close": prev_close,
                        "drift_pct": drift_pct,
                        "vol_multiple": vol_multiple,
                        "volume_today": volume_today,
                        "liquidity_20d": liquidity_20d,
                        "atr": true_atr,
                    },
                )
            )

        if vol_multiple < WHALE_VOL_MULT:
            continue
        if not (WHALE_DRIFT_MIN < drift_pct <= WHALE_DRIFT_MAX):
            continue

        # Tightness: how much of the day's range the close travelled.
        low = s["lows"][-1]
        high = s["highs"][-1]
        pos = range_position(close, low, high)
        range_pct = ((high - low) / close * 100.0) if close > 0 else None

        deal = deals_today.get(ticker)
        stop = close - ATR_MULT * true_atr

        conviction = "HIGH" if deal else ("ELEVATED" if vol_multiple >= WHALE_VOL_MULT * 2.0 else "MODERATE")
        parts = [
            f"Volume {volume_today:,.0f} = {vol_multiple:.1f}x 20-day SMA",
            f"drift {drift_pct:+.2f}% inside absorption band",
            f"20d liquidity {liquidity_20d:,.0f} sh",
        ]
        if deal is not None:
            parts.append(
                f"NDM block: {deal.get('quantity', 0):,.0f} sh @ "
                f"{deal.get('rate', 0):.2f}"
            )

        signals.append(
            _mk_signal(
                trade_date, ticker, "WHALE_RADAR", "STEALTH_ACCUMULATION",
                entry_reference=close, stop_loss=stop,
                rationale="; ".join(parts) + ".",
                metadata={
                    "vol_multiple": round(vol_multiple, 2),
                    "drift_pct": round(drift_pct, 2),
                    "range_pct": round(range_pct, 2) if range_pct else None,
                    "range_position": round(pos, 2) if pos is not None else None,
                    "conviction": conviction,
                    "sector": sector_of.get(ticker),
                    "ndm_confirmed": deal is not None,
                },
            )
        )
        if len(signals) >= SIGNAL_CAP:
            break

    # --------------------------------------------------------------- #
    # Dynamic fallback: strict band produced nothing -> tag the top N
    # positive-day stocks by volume multiple as NOTABLE_VOLUME_SPIKE.
    # --------------------------------------------------------------- #
    if not signals:
        fallback_pool.sort(reverse=True, key=lambda c: c[0])
        for vol_multiple, ticker, info in fallback_pool[:WHALE_FALLBACK_TOP_N]:
            deal = deals_today.get(ticker)
            stop = info["close"] - ATR_MULT * info["atr"]
            signals.append(
                _mk_signal(
                    trade_date, ticker, "WHALE_RADAR", "STEALTH_ACCUMULATION",
                    entry_reference=info["close"], stop_loss=stop,
                    rationale=(
                        f"Volume {info['volume_today']:,.0f} = "
                        f"{vol_multiple:.1f}x 20-day SMA with "
                        f"{info['drift_pct']:+.2f}% day move (outside strict "
                        f"absorption band); flagged as notable volume spike "
                        f"fallback."
                    ),
                    metadata={
                        "vol_multiple": round(vol_multiple, 2),
                        "drift_pct": round(info["drift_pct"], 2),
                        "conviction": "NOTABLE_VOLUME_SPIKE",
                        "sector": sector_of.get(ticker),
                        "ndm_confirmed": deal is not None,
                        "fallback": True,
                    },
                )
            )
        if fallback_pool:
            LOGGER.info(
                "whale: strict band empty; tagged %d NOTABLE_VOLUME_SPIKE fallbacks",
                min(len(fallback_pool), WHALE_FALLBACK_TOP_N),
            )
    return signals


# --------------------------------------------------------------------------- #
# ARBITRAGE: ready vs deliverable-futures cash & carry                        #
# --------------------------------------------------------------------------- #
def _arbitrage_signals(
    trade_date: date,
    eod_history: list[dict[str, Any]],
    futures_history: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Pair ready closes with XXX-FUT closes on the latest shared session.

    Spread % = (FUT - Ready) / Ready * 100; flagged when >= SPREAD_MIN_PCT.
    Annualization assumes the nearest deliverable contract (~1 month):
    (1 + spread) ^ (365/30) - 1, reported alongside the simple multiple.
    """
    # Latest futures session per underlying contract.
    fut_by_symbol: dict[str, dict[str, Any]] = {}
    for row in futures_history:
        symbol = str(row.get("ticker", "")).upper()
        day = parse_db_date(row.get("trade_date"))
        if not symbol.endswith("-FUT") or day is None:
            continue
        if symbol not in fut_by_symbol or day > parse_db_date(
            fut_by_symbol[symbol]["trade_date"]
        ):
            fut_by_symbol[symbol] = row
    if not fut_by_symbol:
        LOGGER.warning(
            "arbitrage: no futures closes stored (PSX feed idle) - desk empty"
        )
        return []

    ready_by_ticker: dict[str, dict[str, Any]] = {}
    for row in eod_history:
        ticker = str(row.get("ticker", "")).upper()
        day = parse_db_date(row.get("trade_date"))
        if not ticker or ticker.endswith("-FUT") or day is None:
            continue
        if ticker not in ready_by_ticker or day > parse_db_date(
            ready_by_ticker[ticker]["trade_date"]
        ):
            ready_by_ticker[ticker] = row

    signals: list[dict[str, Any]] = []
    for symbol, fut_row in sorted(fut_by_symbol.items()):
        underlying = symbol[: -len("-FUT")]
        ready_row = ready_by_ticker.get(underlying)
        if ready_row is None:
            continue

        ready_close = to_num(ready_row.get("close_price"))
        fut_close = to_num(fut_row.get("close_price"))
        ready_day = parse_db_date(ready_row.get("trade_date"))
        fut_day = parse_db_date(fut_row.get("trade_date"))
        if (
            ready_close is None or fut_close is None
            or ready_close <= 0 or fut_close <= 0
            or ready_day is None or fut_day is None
            or ready_day != fut_day
        ):
            continue  # legs must price the same session - no cross-date math

        spread_pct = (fut_close - ready_close) / ready_close * 100.0
        if spread_pct < SPREAD_MIN_PCT:
            continue

        simple_ann = spread_pct * (365.0 / ANNUALIZATION_DAYS)
        compounded_ann = ((1.0 + spread_pct / 100.0) ** (365.0 / ANNUALIZATION_DAYS) - 1.0) * 100.0

        rationale = (
            f"BUY {underlying} READY @ {ready_close:.2f} / SELL {symbol} "
            f"@ {fut_close:.2f}; gross spread {spread_pct:.2f}% "
            f"(~{simple_ann:.0f}% simple annualized, "
            f"{compounded_ann:.1f}% compounded on nearest contract); "
            f"deliver with pre-existing inventory to lock the spread."
        )
        signals.append(
            _mk_signal(
                trade_date, underlying, "ARBITRAGE", "CASH_CARRY",
                entry_reference=ready_close, stop_loss=None,
                rationale=rationale,
                metadata={
                    "ready_close": round(ready_close, 2),
                    "futures_close": round(fut_close, 2),
                    "futures_symbol": symbol,
                    "spread_pct": round(spread_pct, 2),
                    "annualized_simple_pct": round(simple_ann, 1),
                    "annualized_compound_pct": round(compounded_ann, 1),
                    "leg_date": fut_day.isoformat(),
                    "order": f"BUY {underlying} / SELL {symbol}",
                },
            )
        )
        if len(signals) >= SIGNAL_CAP:
            break
    return signals


# --------------------------------------------------------------------------- #
# MOMENTUM: smart-money sector alignment + volume breakout                    #
# --------------------------------------------------------------------------- #
def _momentum_signals(
    trade_date: date,
    by_ticker: dict[str, list[dict[str, Any]]],
    flows: list[dict[str, Any]],
    sector_of: dict[str, str],
) -> list[dict[str, Any]]:
    """Tag the top breakout stock in each net-buying smart-money sector.

    Smart money = Mutual Funds and/or Foreign Corporates net buyers for the
    sector on the latest flow session; breakout factor = today's volume /
    5-day SMA volume. Highest factor per sector wins. When no sector
    mapping aligns (missing NCCPL data or no overlap with the screener),
    the engine falls back to the top relative-volume names across the
    whole market so the desk still surfaces market-wide leaders.
    """

    # Latest flow session per sector with its smart-money net.
    sector_net: dict[str, float] = {}
    latest_flow_day: Optional[date] = None
    for row in flows:
        ptype = str(row.get("participant_type", "")).upper().strip()
        if ptype not in SMART_MONEY:
            continue
        day = parse_db_date(row.get("trade_date"))
        sector = str(row.get("sector_name") or "").upper().strip()
        net = to_num(row.get("net_pkr"))
        if day is None or not sector or net is None:
            continue
        if latest_flow_day is None or day > latest_flow_day:
            latest_flow_day = day

    hot_sectors: set[str] = set()
    if latest_flow_day is not None:
        for row in flows:
            ptype = str(row.get("participant_type", "")).upper().strip()
            if ptype not in SMART_MONEY:
                continue
            if parse_db_date(row.get("trade_date")) != latest_flow_day:
                continue
            sector = str(row.get("sector_name") or "").upper().strip()
            net = to_num(row.get("net_pkr")) or 0.0
            sector_net[sector] = sector_net.get(sector, 0.0) + net
        hot_sectors = {s for s, net in sector_net.items() if net > 0 and s != "ALL"}

    # Tickers with the highest 5-day volume breakout. Scan every liquid
    # ticker once, flagging smart-money sector alignment; if the aligned
    # pool ends up empty (missing NCCPL mapping or negative nets), the
    # market-wide relative-volume fallback keeps the desk populated.
    candidates: list[tuple[float, str, dict[str, Any]]] = []
    for ticker, rows in by_ticker.items():
        sector = sector_of.get(ticker)
        sector_aligned = sector is not None and sector in hot_sectors
        if len(rows) < BREAKOUT_WINDOW + 1 or rows[-1]["day"] != trade_date:
            continue
        s = _series(rows)
        close = s["closes"][-1]
        vol_sma5 = sma(s["vols"][:-1], BREAKOUT_WINDOW)
        if close is None or close < MIN_PRICE or not s["vols"][-1]:
            continue
        if vol_sma5 is None or vol_sma5 <= 0:
            continue
        if sum(s["vols"][-6:-1]) / BREAKOUT_WINDOW < MIN_AVG_VOLUME:
            continue
        breakout = s["vols"][-1] / vol_sma5
        if breakout < BREAKOUT_MIN_MULT:
            continue
        prev_close = s["closes"][-2]
        day_pct = (
            (close - prev_close) / prev_close * 100.0
            if prev_close and prev_close > 0 else 0.0
        )
        candidates.append(
            (
                breakout,
                ticker,
                {
                    "close": close,
                    "day_pct": day_pct,
                    "sector": sector,
                    "sector_aligned": sector_aligned,
                },
            )
        )

    sector_aligned_pool = [c for c in candidates if c[2]["sector_aligned"]]
    fallback_used = not sector_aligned_pool
    if fallback_used:
        LOGGER.warning(
            "momentum: no smart-money sector alignment; falling back to "
            "market-wide top relative volume"
        )

    candidates.sort(reverse=True, key=lambda c: c[0])
    signals: list[dict[str, Any]] = []
    used_sectors: set[str] = set()
    for breakout, ticker, info in candidates:
        if fallback_used:
            if len(signals) >= MOMENTUM_FALLBACK_TOP_N:
                break
        else:
            if info["sector"] in used_sectors:
                continue
            used_sectors.add(info["sector"])
        sector_label = info["sector"] or "MARKET-WIDE"
        if not fallback_used:
            rationale = (
                f"Top volume breakout ({breakout:.1f}x 5-day SMA) in "
                f"'{sector_label.title()}', where smart money "
                f"(Mutual Funds / Foreign Corporates) was net "
                f"{sector_net[info['sector']] / 1e6:+.0f}m PKR on the "
                f"latest flow session."
            )
            sector_smart_net: Optional[float] = round(sector_net[info["sector"]], 0)
        else:
            rationale = (
                f"Market-wide relative-volume leader ({breakout:.1f}x 5-day "
                f"SMA, {info['day_pct']:+.2f}% day); no smart-money sector "
                f"alignment available this session."
            )
            sector_smart_net = None
        signals.append(
            _mk_signal(
                trade_date, ticker, "MOMENTUM", "INSTITUTIONAL_TARGET",
                entry_reference=info["close"], stop_loss=None,
                rationale=rationale,
                metadata={
                    "breakout_multiple": round(breakout, 2),
                    "day_change_pct": round(info["day_pct"], 2),
                    "sector": sector_label,
                    "sector_smart_net_pkr": sector_smart_net,
                    "fallback": fallback_used,
                },
            )
        )
        if not fallback_used and len(signals) >= MOMENTUM_CAP:
            break
    return signals


# --------------------------------------------------------------------------- #
# MEDIUM-TERM and LONG-TERM (unchanged logic)                                 #
# --------------------------------------------------------------------------- #
def _medium_term_signals(
    trade_date: date,
    by_ticker: dict[str, list[dict[str, Any]]],
    flows: list[dict[str, Any]],
    sector_of: dict[str, str],
) -> list[dict[str, Any]]:
    day_nets: dict[date, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for row in flows:
        ptype = str(row.get("participant_type", "")).upper().strip()
        if ptype not in INSTITUTIONAL:
            continue
        day = parse_db_date(row.get("trade_date"))
        sector = str(row.get("sector_name") or "ALL").upper().strip()
        net = to_num(row.get("net_pkr"))
        if day is None or net is None:
            continue
        day_nets[day][sector] += net
    if not day_nets:
        LOGGER.warning("medium-term: no institutional flow rows available")
        return []

    ordered_days = sorted(day_nets, reverse=True)
    hot_sectors: set[str] = set()
    if len(ordered_days) >= FLOW_STREAK_DAYS:
        window = ordered_days[:FLOW_STREAK_DAYS]
        for sector in day_nets[ordered_days[0]]:
            if all(day_nets[d].get(sector, 0.0) > 0 for d in window):
                hot_sectors.add(sector)
    if not hot_sectors:
        return []

    signals: list[dict[str, Any]] = []
    for ticker, rows in sorted(by_ticker.items()):
        if len(rows) < MIN_HISTORY_MEDIUM or rows[-1]["day"] != trade_date:
            continue
        sector = sector_of.get(ticker)
        if sector is None or sector not in hot_sectors:
            continue
        s = _series(rows)
        if any(v is None for v in s["closes"]):
            continue
        close = s["closes"][-1]
        ema50 = ema(s["closes"], EMA_PERIOD)
        if ema50 is None or close <= ema50:
            continue
        if sum(s["vols"][-21:-1]) / 20 < MIN_AVG_VOLUME:
            continue

        highs10 = s["highs"][-10:]
        lows10 = s["lows"][-10:]
        range_proxy = max(highs10) - min(lows10)
        stop = close - 1.5 * range_proxy if range_proxy > 0 else close * 0.92

        signals.append(
            _mk_signal(
                trade_date, ticker, "MEDIUM_TERM", "ACCUMULATION",
                entry_reference=close, stop_loss=stop,
                rationale=(
                    f"Sector '{sector.title()}' shows {FLOW_STREAK_DAYS}-day "
                    f"institutional inflow streak in NCCPL net flows; close "
                    f"{close:.2f} holds above the 50-day EMA {ema50:.2f}."
                ),
                metadata={"sector": sector, "ema50": round(ema50, 2)},
            )
        )
        if len(signals) >= SIGNAL_CAP:
            break
    return signals


def _long_term_signals(
    trade_date: date,
    fundamentals: list[dict[str, Any]],
    dividends: dict[str, list[float]] | None = None,
) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []
    for row in fundamentals:
        ticker = str(row.get("ticker", "")).upper()
        if not ticker:
            continue
        yield_pct = to_num(row.get("dividend_yield"))
        pe = to_num(row.get("pe_ratio"))
        cap = to_num(row.get("market_cap_pkr"))
        close = to_num(row.get("close_price"))
        if yield_pct is None or close is None or close < MIN_PRICE:
            continue
        if yield_pct < DIV_YIELD_MIN:
            continue
        if pe is not None and pe > PE_MAX:
            continue
        if cap is not None and cap < MIN_CAP_PKR:
            continue

        parts = [
            f"Dividend yield {yield_pct:.1f}% (floor {DIV_YIELD_MIN:.0f}%)",
            f"P/E {pe:.1f}" if pe is not None else "P/E n/a",
        ]
        if cap is not None:
            parts.append(f"market cap {cap / 1e9:.1f}bn PKR")
        payouts = (dividends or {}).get(ticker) or []
        if payouts:
            streak = payout_streak(payouts)
            if streak < PAYOUT_STREAK_MIN:
                continue
            parts.append(f"{streak} consecutive cash payouts")
        else:
            parts.append("payout history not yet sampled")

        signals.append(
            _mk_signal(
                trade_date, ticker, "LONG_TERM", "VALUE_YIELD",
                entry_reference=close, stop_loss=None,
                rationale="; ".join(parts) + ".",
                metadata={"yield_pct": yield_pct, "pe": pe},
            )
        )
        if len(signals) >= SIGNAL_CAP:
            break
    return signals


# --------------------------------------------------------------------------- #
# INSIDER RADAR: SECP disclosures & sponsor footprint                          #
# --------------------------------------------------------------------------- #
def _insider_radar_signals(
    trade_date: date,
    by_ticker: dict[str, list[dict[str, Any]]],
    insider_trades: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Aggregate recent insider/sponsor BUY disclosures into radar signals.

    A ticker qualifies when net insider buying over INSIDER_LOOKBACK_DAYS
    exceeds INSIDER_MIN_NOTIONAL PKR. Senior designations (Sponsor/CEO)
    weigh double in the conviction ladder. SELL-heavy tapes are ignored:
    this desk hunts accumulation footprints only.
    """
    if not insider_trades:
        return []

    window_start = trade_date - timedelta(days=INSIDER_LOOKBACK_DAYS * 2)
    net_by_ticker: dict[str, dict[str, Any]] = {}
    for row in insider_trades:
        day = parse_db_date(row.get("trade_date"))
        if day is None or not (window_start <= day <= trade_date):
            continue
        if str(row.get("trade_type", "")).upper() != "BUY":
            continue
        ticker = str(row.get("ticker", "")).upper()
        if not ticker:
            continue
        qty = to_num(row.get("quantity")) or 0.0
        rate = to_num(row.get("rate"))
        notional = to_num(row.get("notional_pkr"))
        if notional is None:
            notional = qty * rate if rate else 0.0
        if notional < INSIDER_MIN_NOTIONAL / 10:  # dust filter per disclosure
            continue
        bucket = net_by_ticker.setdefault(
            ticker, {"net": 0.0, "count": 0, "senior": 0, "names": []}
        )
        bucket["net"] += notional
        bucket["count"] += 1
        designation = str(row.get("designation", "")).strip()
        if designation.title() in INSIDER_SENIOR_DESIGNATIONS:
            bucket["senior"] += 1
        name = str(row.get("insider_name", "")).strip()
        if name and name not in bucket["names"]:
            bucket["names"].append(name)

    signals: list[dict[str, Any]] = []
    for ticker, bucket in sorted(
        net_by_ticker.items(), key=lambda kv: kv[1]["net"], reverse=True
    ):
        if bucket["net"] < INSIDER_MIN_NOTIONAL:
            continue
        rows = by_ticker.get(ticker) or []
        close = to_num(rows[-1].get("close_price")) if rows else None
        conviction = (
            "HIGH" if bucket["senior"] else ("ELEVATED" if bucket["count"] >= 3 else "MODERATE")
        )
        names = ", ".join(bucket["names"][:3]) or "disclosed insiders"
        signals.append(
            _mk_signal(
                trade_date, ticker, "INSIDER_RADAR", "INSIDER_BUYING",
                entry_reference=close, stop_loss=None,
                rationale=(
                    f"Insider/sponsor net buying {bucket['net'] / 1e6:.1f}m PKR "
                    f"across {bucket['count']} disclosure(s) in the last "
                    f"{INSIDER_LOOKBACK_DAYS} sessions ({names})."
                ),
                metadata={
                    "net_notional_pkr": round(bucket["net"], 0),
                    "disclosure_count": bucket["count"],
                    "senior_disclosures": bucket["senior"],
                    "conviction": conviction,
                },
            )
        )
        if len(signals) >= SIGNAL_CAP:
            break
    if not signals and insider_trades:
        LOGGER.info("insider: disclosures present but none above thresholds")
    return signals


# --------------------------------------------------------------------------- #
# MTS SQUEEZE: leverage flushouts & margin-cascade bottoms                     #
# --------------------------------------------------------------------------- #
def _mts_squeeze_signals(
    trade_date: date,
    by_ticker: dict[str, list[dict[str, Any]]],
    mts_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Two opposing MTS footprints:

    MARGIN_CASCADE_RISK - utilization >= MTS_UTIL_SPIKE%% of the authorized
    cap while price is already falling: crowded longs, air pocket below.
    LEVERAGE_FLUSH_BOTTOM - MTS value down >= MTS_VALUE_DROP_PCT%% over the
    window while price is down >= MTS_PRICE_DROP_PCT%% and stabilising:
    forced selling exhausted, bounce candidate.
    """
    if not mts_rows:
        return []

    per_ticker: dict[str, dict[date, dict[str, Any]]] = defaultdict(dict)
    for row in mts_rows:
        day = parse_db_date(row.get("trade_date"))
        ticker = str(row.get("ticker", "")).upper()
        if day is None or not ticker:
            continue
        per_ticker[ticker][day] = row

    signals: list[dict[str, Any]] = []
    for ticker, days in sorted(per_ticker.items()):
        ordered = sorted(days)
        if len(ordered) < 2:
            continue
        latest_day = ordered[-1]
        latest = days[latest_day]
        earliest = days[ordered[0]]

        rows = by_ticker.get(ticker) or []
        close = to_num(rows[-1].get("close_price")) if rows else None
        util = to_num(latest.get("leverage_utilization_pct"))
        value_now = to_num(latest.get("mts_value_pkr")) or 0.0
        value_then = to_num(earliest.get("mts_value_pkr")) or 0.0

        price_drop = 0.0
        if len(rows) >= MTS_SQUEEZE_LOOKBACK + 1 and rows[-1]["day"] == trade_date:
            start_close = to_num(rows[-1 - MTS_SQUEEZE_LOOKBACK].get("close_price"))
            if start_close and close:
                price_drop = (start_close - close) / start_close * 100.0

        value_drop_pct = (
            (value_then - value_now) / value_then * 100.0
            if value_then > 0 else 0.0
        )

        if util is not None and util >= MTS_UTIL_SPIKE and price_drop > 0:
            signals.append(
                _mk_signal(
                    trade_date, ticker, "MTS_SQUEEZE", "MARGIN_CASCADE_RISK",
                    entry_reference=close, stop_loss=None,
                    rationale=(
                        f"MTS utilization {util:.0f}% of authorized cap with "
                        f"price {price_drop:.1f}% lower over "
                        f"{MTS_SQUEEZE_LOOKBACK} sessions: crowded leveraged "
                        f"longs vulnerable to a margin cascade."
                    ),
                    metadata={
                        "mts_utilization_pct": util,
                        "mts_value_pkr": round(value_now, 0),
                        "price_drop_pct": round(price_drop, 2),
                        "stance": "AVOID_LONGS",
                    },
                )
            )
        elif (
            value_drop_pct >= MTS_VALUE_DROP_PCT
            and price_drop >= MTS_PRICE_DROP_PCT
            and close is not None
        ):
            signals.append(
                _mk_signal(
                    trade_date, ticker, "MTS_SQUEEZE", "LEVERAGE_FLUSH_BOTTOM",
                    entry_reference=close, stop_loss=None,
                    rationale=(
                        f"MTS financed value down {value_drop_pct:.0f}% and "
                        f"price {price_drop:.1f}% over {MTS_SQUEEZE_LOOKBACK} "
                        f"sessions: forced deleveraging exhausting, "
                        f"flushout-bottom watch."
                    ),
                    metadata={
                        "mts_value_drop_pct": round(value_drop_pct, 2),
                        "price_drop_pct": round(price_drop, 2),
                        "mts_value_pkr": round(value_now, 0),
                        "stance": "FLUSH_BOTTOM_WATCH",
                    },
                )
            )
        if len(signals) >= SIGNAL_CAP:
            break
    return signals


# --------------------------------------------------------------------------- #
# ROLLOVER DESK: basis inversion & short-squeeze futures footprints            #
# --------------------------------------------------------------------------- #
def _rollover_desk_signals(
    trade_date: date,
    by_ticker: dict[str, list[dict[str, Any]]],
    futures_history: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Futures-basis extremes around contract rollover windows.

    BASIS_INVERSION_SHORT - futures trade below spot (negative basis):
    short hedging pressure has overshot; fade-the-crowd short bias on the
    underlying with the spread as tailwind.
    ROLLOVER_SQUEEZE - futures premium compressed/expanded violently
    (|basis| move >= ROLLOVER_SQUEEZE_PCT points of price within the
    rollover window) while spot closes strong: shorts rolling into a
    squeeze.
    """
    fut_by_symbol: dict[str, list[tuple[date, float]]] = defaultdict(list)
    for row in futures_history:
        symbol = str(row.get("ticker", "")).upper()
        day = parse_db_date(row.get("trade_date"))
        close = to_num(row.get("close_price"))
        if symbol.endswith("-FUT") and day is not None and close:
            fut_by_symbol[symbol].append((day, close))
    if not fut_by_symbol:
        LOGGER.info("rollover: no futures closes stored - desk idle")
        return []

    signals: list[dict[str, Any]] = []
    for symbol, points in fut_by_symbol.items():
        underlying = symbol[: -len("-FUT")]
        rows = by_ticker.get(underlying) or []
        if not rows or rows[-1]["day"] != trade_date:
            continue
        spot = to_num(rows[-1].get("close_price"))
        if not spot:
            continue
        # Futures leg priced the same session as spot - no cross-date math.
        same_day = [c for d, c in points if d == trade_date]
        if not same_day:
            continue
        fut_close = same_day[-1]
        basis_pct = (fut_close - spot) / spot * 100.0

        prev_points = sorted((d, c) for d, c in points if d < trade_date)
        basis_prev_pct = None
        if prev_points:
            prev_day, prev_fut = prev_points[-1]
            prev_rows = [r for r in rows if r["day"] <= prev_day]
            prev_spot = to_num(prev_rows[-1].get("close_price")) if prev_rows else None
            if prev_spot:
                basis_prev_pct = (prev_fut - prev_spot) / prev_spot * 100.0

        if basis_pct <= BASIS_INVERSION_PCT:
            signals.append(
                _mk_signal(
                    trade_date, underlying, "ROLLOVER_DESK", "BASIS_INVERSION_SHORT",
                    entry_reference=spot, stop_loss=None,
                    rationale=(
                        f"Futures {symbol} closed {basis_pct:.2f}% BELOW spot "
                        f"({fut_close:.2f} vs {spot:.2f}): hedging shorts have "
                        f"overshot into inversion - squeeze-fade setup on the "
                        f"underlying."
                    ),
                    metadata={
                        "futures_symbol": symbol,
                        "futures_close": round(fut_close, 2),
                        "spot_close": round(spot, 2),
                        "basis_pct": round(basis_pct, 2),
                        "stance": "SHORT_BIAS",
                    },
                )
            )
        elif (
            basis_prev_pct is not None
            and abs(basis_pct - basis_prev_pct) >= ROLLOVER_SQUEEZE_PCT
            and basis_pct > 0
        ):
            signals.append(
                _mk_signal(
                    trade_date, underlying, "ROLLOVER_DESK", "ROLLOVER_SQUEEZE",
                    entry_reference=spot, stop_loss=None,
                    rationale=(
                        f"Basis swung {basis_prev_pct:.2f}% -> {basis_pct:.2f}% "
                        f"within the rollover window while spot held: shorts "
                        f"paying up to roll - squeeze conditions building."
                    ),
                    metadata={
                        "futures_symbol": symbol,
                        "futures_close": round(fut_close, 2),
                        "spot_close": round(spot, 2),
                        "basis_pct": round(basis_pct, 2),
                        "basis_prev_pct": round(basis_prev_pct, 2),
                        "stance": "SQUEEZE_WATCH",
                    },
                )
            )
        if len(signals) >= SIGNAL_CAP:
            break
    return signals


# --------------------------------------------------------------------------- #
# Public API                                                                  #
# --------------------------------------------------------------------------- #
def compute_signals(
    trade_date: date,
    *,
    eod_history: list[dict[str, Any]],
    flows: list[dict[str, Any]],
    offmarket_deals: list[dict[str, Any]] | None = None,
    fundamentals: list[dict[str, Any]] | None = None,
    futures_history: list[dict[str, Any]] | None = None,
    insider_trades: list[dict[str, Any]] | None = None,
    mts_rows: list[dict[str, Any]] | None = None,
    dividends: dict[str, list[float]] | None = None,
    regime_state: dict[str, Any] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Compute every engine; returns {timeframe: [signal rows]}.

    When ``regime_state`` is supplied and the regime gate is enabled, the
    MacroRegimeGate filters the output: BEARISH_CAPITAL_PRESERVATION blocks
    all directional longs; ACCUMULATION_FAVORABLE keeps only whale-strength
    (>= 1.8x volume multiple) names in LEADING/IMPROVING sectors.
    """
    by_ticker = _group_by_ticker(eod_history)

    sector_of: dict[str, str] = {}
    fund_day: Optional[date] = None
    for row in fundamentals or []:
        day = parse_db_date(row.get("trade_date"))
        if day is not None and (fund_day is None or day > fund_day):
            fund_day = day
    for row in fundamentals or []:
        if fund_day is not None and parse_db_date(row.get("trade_date")) != fund_day:
            continue
        ticker = str(row.get("ticker", "")).upper()
        sector = str(row.get("sector_name") or "").upper().strip()
        if ticker and sector:
            sector_of[ticker] = sector

    offm_deals = offmarket_deals or []
    offm_tickers = {
        str(r.get("ticker", "")).upper()
        for r in offm_deals
        if parse_db_date(r.get("trade_date")) == trade_date
    }

    short = _short_term_signals(trade_date, by_ticker, offm_tickers)
    whale = _whale_signals(trade_date, by_ticker, sector_of, offm_deals)
    medium = _medium_term_signals(trade_date, by_ticker, flows, sector_of)
    momentum = _momentum_signals(trade_date, by_ticker, flows, sector_of)
    arb = _arbitrage_signals(
        trade_date, eod_history, futures_history or []
    )
    longs = _long_term_signals(trade_date, fundamentals or [], dividends)
    insider = _insider_radar_signals(
        trade_date, by_ticker, insider_trades or []
    )
    mts = _mts_squeeze_signals(trade_date, by_ticker, mts_rows or [])
    rollover = _rollover_desk_signals(
        trade_date, by_ticker, futures_history or []
    )

    LOGGER.info(
        "signals: %d short / %d whale / %d medium / %d momentum / %d arb / "
        "%d long / %d insider / %d mts / %d rollover",
        len(short), len(whale), len(medium), len(momentum), len(arb),
        len(longs), len(insider), len(mts), len(rollover),
    )
    results = {
        "SHORT_TERM": short,
        "WHALE_RADAR": whale,
        "MEDIUM_TERM": medium,
        "MOMENTUM": momentum,
        "ARBITRAGE": arb,
        "LONG_TERM": longs,
        "INSIDER_RADAR": insider,
        "MTS_SQUEEZE": mts,
        "ROLLOVER_DESK": rollover,
    }
    if regime_state is not None and REGIME_GATE_ENABLED:
        if regime_state.get("regime_status") == REGIME_FAVORABLE:
            _prepare_sector_trends(eod_history, sector_of, regime_state)
        results = apply_regime_gate(results, regime_state)
        total_after = sum(len(v) for v in results.values())
        LOGGER.info(
            "regime %s: %d signals after gate (inst flow %.1fM, benchmark "
            "%s vs SMA20 %s)",
            regime_state.get("regime_status"),
            total_after,
            regime_state.get("inst_net_flow_pkr", 0.0) / 1e6,
            regime_state.get("benchmark_close"),
            regime_state.get("benchmark_sma20"),
        )
    return results


def run_quant_engine(session_date: date | None = None) -> int:
    """One-shot engine run: load history, compute, upsert signals_computed.

    ``session_date`` is the trading session to compute signals FOR. It must
    be an active session (rows with volume > 0 in psx_daily_eod) - callers
    resolve weekends/holidays to the last active session before invoking.
    """
    trade_date = session_date or date.today()
    LOGGER.info("quant engine run for session %s", trade_date)

    eod_history = db.fetch_recent_eod(days=90)
    flows = db.fetch_recent_flows(days=max(FLOW_STREAK_DAYS + 4, 10))
    offmarket = db.fetch_recent_offmarket(days=3)
    fundamentals = db.fetch_recent_fundamentals()
    futures = db.fetch_recent_futures(days=7)
    insider = db.fetch_recent_insider_trades(days=5)
    mts_rows = db.fetch_recent_mts(days=6)

    regime = build_regime_state(flows=flows, eod_history=eod_history)
    LOGGER.info(
        "regime gate: %s (inst flow %.1fM [%s], benchmark %s vs SMA20 %s [%s])",
        regime["regime_status"],
        regime["inst_net_flow_pkr"] / 1e6,
        regime["flow_basis"],
        regime["benchmark_close"],
        regime["benchmark_sma20"],
        regime["benchmark_basis"],
    )
    results = compute_signals(
        trade_date,
        eod_history=eod_history,
        flows=flows,
        offmarket_deals=offmarket,
        fundamentals=fundamentals,
        futures_history=futures,
        insider_trades=insider,
        mts_rows=mts_rows,
        dividends=None,
        regime_state=regime,
    )

    payload: list[dict[str, Any]] = []
    for rows in results.values():
        payload.extend(rows)
    if not payload:
        LOGGER.warning("no signals produced for %s", trade_date)
        return 0

    written = db.upsert_records(
        "signals_computed",
        payload,
        on_conflict="trade_date,ticker,timeframe,signal_type",
    )
    LOGGER.info("signals_computed: %d rows written", written)
    return written
