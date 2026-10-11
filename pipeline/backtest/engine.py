"""Quick walk-forward backtester - the decision engine's historical edge proof.

Simulates the engine's own entry/stop/target logic on a ticker's stored
tape so the Action Desk can show a certified win rate next to every BUY
verdict instead of asking the user to trust an unproven signal.

Methodology (documented, never fabricated):

  History      The last 3 years of psx_daily_eod for ONE ticker, sessions
               strictly before ``target_date`` (no look-ahead).

  SHORT_TERM   Institutional Pullback & Dry-up Accumulation setup (NOT
               breakout chasing, which backtested at 16.9% on PSX). All of:
                 - Confirmed bull trend: close > 20D SMA AND 20D SMA >
                   50D SMA (the Phase 2 50D confirmation gate).
                 - Pullback to support: close within 3.5% of its 20D SMA.
                 - Retraced 1-3 sessions from the recent 10-day high.
                 - Volume dry-up: volume < 0.85x the 20D volume SMA
                   (seller exhaustion, not smart-money distribution).
               (The live PE, liquidity and sector-flow gates are not daily
               series and cannot be replayed bar-by-bar; they are applied
               at certification time only.)
  MID_TERM     Signal = close above its 20-day SMA with positive
               5-session momentum (the mid-horizon "performing leader"
               proxy; the live flow cross-check has no daily history).
  LONG_TERM    An AVOID verdict carries no trade to simulate -> None.

  Entry        The next session's close after the signal - the same
               "entry = latest session close" convention the live engine
               stamps into entry_ref (you cannot trade the close you just
               watched form).

  Stop/Target  SHORT_TERM: stop = the structural support the pullback
               is bouncing off - the LOWER of the recent 3-session swing
               low and the 1.0 x ATR floor beneath it, hardened to a
               maximum 4% risk from entry; TP1 target = the recent 10-day
               swing high, floored so it pays at least 1:1.2 R:R.
               MID_TERM: stop = entry - 1.5 x ATR; target = entry + 2.5 x
               risk. ATR is the mean absolute close-to-close change over
               the last 4 sessions at signal time (documented proxy).

  Resolution   Bar-by-bar from the entry bar, using the stored high/low.
               Win = the 10-day swing high (TP1) is touched BEFORE the
               stop. Same-bar hit of both levels resolves to the STOP
               first (conservative). Exit window: 10 sessions
               (SHORT_TERM) or 40 sessions (MID_TERM); an unresolved
               trade is a scratch and counts toward total trades but
               never as a win.

  Output       {"win_rate": <winning/total x 100>, "total_signals": n,
               "winning_trades": w}, or None when history is insufficient
               (< 30 sessions) or no historical signal fired - the engine
               then stores a null win rate rather than an invented number.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Optional

from pipeline import db

LOGGER = logging.getLogger(__name__)

BACKTEST_WINDOW_DAYS = 1100  # ~3 years of trading sessions
MIN_SESSIONS = 30            # honest floor: fewer sessions -> no verdict
VOLUME_SMA_WINDOW = 20
ATR_PROXY_SESSIONS = 4
REWARD_MULT = {"MID_TERM": 2.5}
EXIT_WINDOW_SESSIONS = {"SHORT_TERM": 10, "MID_TERM": 40}

# High-Win-Rate Pullback Engine (SHORT_TERM) - institutional swing setup.
PULLBACK_SMA_PROXIMITY = 0.035   # close within 3.5% of 20D SMA = at support
DRYUP_VOLUME_RATIO = 0.85        # volume < 0.85x 20D avg = seller exhaustion
SWING_LOW_LOOKBACK = 3           # tight invalidation: 3-session swing low
TP1_LOOKBACK = 10                # TP1 target = recent 10-day swing high
SHORT_MIN_RR = 1.2               # TP1 floored to a 1:1.2 reward/risk
SHORT_MIN_RISK_PCT = 0.005       # sanity floor on stop distance
SHORT_MAX_RISK_PCT = 0.04        # hard 4% stop cap (Phase 2 risk hardening)
TREND_MA_LONG = 50               # confirmed-bull-trend SMA leg

# (day, high, low, close, volume)
Session = tuple[date, float, float, float, float]


def _f(value: Any) -> Optional[float]:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _sessions_before(
    ticker: str, target_date: date
) -> list[Session]:
    """Ascending (day, high, low, close, volume) for one ticker, < target_date."""
    rows = db.fetch_eod_for_ticker(ticker, days=BACKTEST_WINDOW_DAYS)
    sessions: list[Session] = []
    for row in rows:
        try:
            day = date.fromisoformat(str(row.get("trade_date"))[:10])
        except (TypeError, ValueError):
            continue
        if day >= target_date:
            continue
        close = _f(row.get("close_price"))
        volume = _f(row.get("volume"))
        if close is None or close <= 0 or volume is None:
            continue
        high = _f(row.get("high_price")) or close
        low = _f(row.get("low_price")) or close
        sessions.append((day, high, low, close, volume))
    sessions.sort(key=lambda s: s[0])
    return sessions


def _atr_at(closes: list[float], i: int) -> float:
    """Mean absolute close-to-close change over the last 4 sessions at i."""
    leg = closes[max(0, i - ATR_PROXY_SESSIONS + 1) : i + 1]
    changes = [abs(leg[k] - leg[k - 1]) for k in range(1, len(leg))]
    return sum(changes) / len(changes) if changes else 0.0


def _pullback_setup(
    closes: list[float], volumes: list[float], i: int
) -> Optional[dict[str, float]]:
    """The SHORT_TERM pullback rule at bar i, or None when absent.

    Enforces the full institutional setup: uptrend filter, proximity to
    20D support, a 1-3 session retracement from the 10-day high, and a
    volume dry-up. Returns the resolved stop (the LOWER of the 3-session
    swing low and the 1.0 x ATR floor beneath it - structural support)
    and TP1 target (10-day swing high, floored at 1:1.2 R:R).
    """
    if i < VOLUME_SMA_WINDOW:
        return None
    close = closes[i]
    sma20 = sum(closes[i - VOLUME_SMA_WINDOW : i]) / VOLUME_SMA_WINDOW
    if sma20 <= 0:
        return None
    # Confirmed bull trend (Phase 2): close > 20D SMA AND 20D SMA > 50D SMA.
    if close <= sma20:
        return None
    if i < TREND_MA_LONG:
        return None  # no confirmed-trend verdict without a full 50D leg
    sma50 = sum(closes[i - TREND_MA_LONG : i]) / TREND_MA_LONG
    if sma50 <= 0 or not sma20 > sma50:
        return None
    # Pullback into the 20D support band (not extended).
    if (close - sma20) / sma20 > PULLBACK_SMA_PROXIMITY:
        return None
    # Retraced 1-3 sessions from the recent 10-day high.
    high10 = max(closes[i - TP1_LOOKBACK + 1 : i + 1])
    if close >= high10:
        return None  # still at the high, no pullback yet
    peak = max(range(i - 3, i + 1), key=lambda k: closes[k])
    sessions_since_peak = i - peak
    if not 1 <= sessions_since_peak <= 3:
        return None
    # Volume dry-up: seller exhaustion, not smart-money distribution.
    vol_sma20 = sum(volumes[i - VOLUME_SMA_WINDOW : i]) / VOLUME_SMA_WINDOW
    if vol_sma20 <= 0 or volumes[i] >= DRYUP_VOLUME_RATIO * vol_sma20:
        return None

    atr = _atr_at(closes, i)
    swing_low = min(closes[i - SWING_LOW_LOOKBACK + 1 : i + 1])
    stops = [swing_low] + ([close - atr] if atr > 0 else [])
    # Valid stop = the LOWER of the swing low and the ATR floor - the
    # structural support the pullback is bouncing off. (Taking the higher
    # leg instead pins risk a hair under entry, so TP1 sits ~12x the risk
    # away and the win rate collapses on noise; the 1.0x ATR term is a
    # FLOOR beneath the swing, not a ceiling above it.)
    stop = min(s for s in stops if s > 0)
    if stop <= 0:
        return None
    # Phase 2 hardening: cap total risk at 4% of entry so a wide swing
    # cannot produce an un-tradeable stop that no target can outrun.
    stop = max(stop, close * (1.0 - SHORT_MAX_RISK_PCT))
    risk = close - stop
    if risk < SHORT_MIN_RISK_PCT * close:
        stop = close - SHORT_MIN_RISK_PCT * close  # avoid a zero-risk stop
        risk = close - stop
    target = max(high10, close + SHORT_MIN_RR * risk)  # TP1 floored to 1:1.2
    return {"stop": stop, "target": target}


def _signal_indexes(
    horizon: str, closes: list[float], volumes: list[float]
) -> list[int]:
    """Historical signal bars for the horizon's documented criterion."""
    signals: list[int] = []
    for i in range(VOLUME_SMA_WINDOW, len(closes)):
        if horizon == "SHORT_TERM":
            if _pullback_setup(closes, volumes, i) is not None:
                signals.append(i)
        else:  # MID_TERM: above 20D SMA with positive 5-session momentum
            if i < 5:
                continue
            sma = sum(closes[i - VOLUME_SMA_WINDOW : i]) / VOLUME_SMA_WINDOW
            if closes[i] > sma and closes[i] > closes[i - 5]:
                signals.append(i)
    return signals


def run_quick_backtest(
    ticker: str, horizon: str, target_date: date
) -> Optional[dict[str, Any]]:
    """Win rate (%) + trade count for one ticker/horizon as of target_date.

    Returns None (never a fabricated number) when the horizon has no
    tradeable strategy, history is thinner than MIN_SESSIONS, or no
    historical signal fired.
    """
    if horizon not in EXIT_WINDOW_SESSIONS:
        return None  # AVOID horizons have no trade to simulate

    sessions = _sessions_before(ticker, target_date)
    if len(sessions) < MIN_SESSIONS:
        LOGGER.info(
            "backtest %s %s: only %d sessions (<%d); no verdict",
            ticker, horizon, len(sessions), MIN_SESSIONS,
        )
        return None

    closes = [s[3] for s in sessions]
    volumes = [s[4] for s in sessions]
    signals = _signal_indexes(horizon, closes, volumes)
    if not signals:
        LOGGER.info("backtest %s %s: no historical signals; no verdict", ticker, horizon)
        return None

    window = EXIT_WINDOW_SESSIONS[horizon]
    total = wins = 0
    for i in signals:
        if i + 1 >= len(sessions):
            break  # signal on the last stored session: no entry bar
        entry = closes[i + 1]  # next session close = the live entry_ref convention
        if entry <= 0:
            continue
        if horizon == "SHORT_TERM":
            setup = _pullback_setup(closes, volumes, i)
            if setup is None:
                continue
            stop, target = setup["stop"], setup["target"]
        else:
            # MID_TERM: stop = 1.5 x ATR below; target = 2.5x risk.
            atr = _atr_at(closes, i)
            if atr <= 0:
                continue
            stop = entry - 1.5 * atr
            if stop <= 0:
                continue
            target = entry + REWARD_MULT[horizon] * (entry - stop)

        total += 1
        for _, high, low, _, _ in sessions[i + 1 : i + 1 + window]:
            if low <= stop:
                break  # same-bar double hit resolves to the STOP (conservative)
            if high >= target:
                wins += 1
                break

    if total == 0:
        LOGGER.info("backtest %s %s: signals had no usable entries; no verdict", ticker, horizon)
        return None

    win_rate = round(wins / total * 100.0, 2)
    LOGGER.info(
        "backtest %s %s: %d winning / %d trades -> %.2f%% (%d signals)",
        ticker, horizon, wins, total, win_rate, len(signals),
    )
    return {
        "win_rate": win_rate,
        "total_signals": total,
        "winning_trades": wins,
    }
