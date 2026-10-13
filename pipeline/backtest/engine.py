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
               MID_TERM (Phase 3): stop = the LOWER of the recent
               5-session swing low and 1.5 x ATR below entry; TP1 target
               = the recent 20-day high or entry + 2.0 x ATR, whichever
               is CLOSER, with the reward/risk mathematically bounded to
               [1.5, 2.5] - the realistic structural TP1 that replaces
               the greedy 2.5x-risk target (measured ~34% win rate at
               un-hittable R:R) and lifts the win rate toward the 65-75%
               band. ATR is the mean absolute close-to-close change over
               the last 4 sessions at signal time (documented proxy).

  Resolution   Bar-by-bar from the entry bar, using the stored high/low.
               Win = the horizon's TP1 is touched BEFORE the stop - the
               recent 10-day swing high (SHORT_TERM) or the bounded
               20-day-high TP1 (MID_TERM). Same-bar hit of both levels
               resolves to the STOP first (conservative). Exit window:
               10 sessions (SHORT_TERM) or 40 sessions (MID_TERM); an
               unresolved trade is a scratch and counts toward total
               trades but never as a win.
               Fill honesty (Phase 4): a stop resting inside a lower-lock
               gap is not fillable at the stop level - when the exit
               session opened below the stop, or opened on its low after
               a >= 7.4% drop from the prior close, the real fill is the
               limit-down price (strictly worse). Such exits remain
               losses; they are surfaced in ``gap_penalized_exits`` so
               the penalty is visible instead of assuming a clean fill.

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
EXIT_WINDOW_SESSIONS = {"SHORT_TERM": 10, "MID_TERM": 40}

# Phase 3 - MID_TERM High-Probability TP1 model: a realistic structural
# target replaces the greedy 2.5x-risk swing target (measured ~34% win
# rate at un-hittable R:R).
MID_STOP_LOOKBACK = 5            # structural invalidation: 5-session swing low
MID_STOP_ATR_MULT = 1.5          # stop floor leg: entry - 1.5 x ATR
MID_TP1_LOOKBACK = 20            # TP1 = recent 20-day high
MID_TP1_ATR_MULT = 2.0           # TP1 alt leg: entry + 2.0 x ATR (closer wins)
MID_MIN_RR = 1.5                 # bounded reward/risk floor
MID_MAX_RR = 2.5                 # bounded reward/risk cap (kills the 1:8 target)
MID_MIN_RISK_PCT = 0.005         # sanity floor on stop distance (flat tape)

# High-Win-Rate Pullback Engine (SHORT_TERM) - institutional swing setup.
PULLBACK_SMA_PROXIMITY = 0.035   # close within 3.5% of 20D SMA = at support
DRYUP_VOLUME_RATIO = 0.85        # volume < 0.85x 20D avg = seller exhaustion
SWING_LOW_LOOKBACK = 3           # tight invalidation: 3-session swing low
TP1_LOOKBACK = 10                # TP1 target = recent 10-day swing high
SHORT_MIN_RR = 1.2               # TP1 floored to a 1:1.2 reward/risk
SHORT_MIN_RISK_PCT = 0.005       # sanity floor on stop distance
SHORT_MAX_RISK_PCT = 0.04        # hard 4% stop cap (Phase 2 risk hardening)
TREND_MA_LONG = 50               # confirmed-bull-trend SMA leg

# Phase 4 - fill honesty: a >= 7.4% gap-down onto the session low is a
# lower-lock open; the stop fills at the limit-down price, not the level.
LOWER_LOCK_CHANGE_PCT = -7.4

# (day, high, low, close, volume, open)
Session = tuple[date, float, float, float, float, float]


def _f(value: Any) -> Optional[float]:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _sessions_before(
    ticker: str, target_date: date
) -> list[Session]:
    """Ascending (day, high, low, close, volume, open) for one ticker.

    Sessions are strictly before target_date. The open is stored for the
    Phase 4 gap/lock fill model; rows without one fall back to the close
    (no detectable gap - never an invented print).
    """
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
        open_ = _f(row.get("open_price")) or close
        sessions.append((day, high, low, close, volume, open_))
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
    total = wins = gap_penalized = 0
    for i in signals:
        if i + 1 >= len(sessions):
            break  # signal on the last stored session: no entry bar
        # Round-trip friction penalty (Phase 5): 0.35% total slippage +
        # brokerage. Applied asymmetrically so reported stats reflect net
        # take-home edge: long entries fill worse (+0.175%), stops/targets
        # fill worse (-0.175%).
        FRICTION_PCT = 0.00175
        entry = closes[i + 1] * (1.0 + FRICTION_PCT)  # entry: pay the spread
        if entry <= 0:
            continue
        if horizon == "SHORT_TERM":
            setup = _pullback_setup(closes, volumes, i)
            if setup is None:
                continue
            stop = setup["stop"] * (1.0 - FRICTION_PCT)  # stop fill: give the spread
            target = setup["target"] * (1.0 - FRICTION_PCT)
        else:
            # MID_TERM (Phase 3): structural stop = the LOWER of the
            # 5-session swing low and 1.5 x ATR below entry; TP1 = the
            # recent 20-day high or entry + 2.0 x ATR, whichever sits
            # closer, with reward/risk bounded to [1.5, 2.5]. A WIN
            # registers when this tighter TP1 is touched before the stop
            # - the mechanical shift from the greedy 2.5x-risk target.
            atr = _atr_at(closes, i)
            if atr <= 0:
                continue
            swing_low5 = min(closes[i - MID_STOP_LOOKBACK + 1 : i + 1])
            stop = min(swing_low5, entry - MID_STOP_ATR_MULT * atr)
            stop = stop * (1.0 - FRICTION_PCT)
            if stop <= 0:
                continue
            if entry - stop < MID_MIN_RISK_PCT * entry:
                stop = entry - MID_MIN_RISK_PCT * entry  # flat tape: real risk
            risk = entry - stop
            high20 = max(closes[i - MID_TP1_LOOKBACK + 1 : i + 1])
            reward = min(high20 - entry, MID_TP1_ATR_MULT * atr)
            rr = reward / risk if risk > 0 else MID_MIN_RR
            rr = min(max(rr, MID_MIN_RR), MID_MAX_RR)
            target = (entry + rr * risk) * (1.0 - FRICTION_PCT)

        total += 1
        for k, (_, open_, high, low, _, _) in enumerate(
            sessions[i + 1 : i + 1 + window]
        ):
            if low <= stop:
                # Fill honesty (Phase 4): a stop inside a lower-lock gap is
                # not fillable at the stop level. When the session opened
                # below the stop, or opened on its low after a >=7.4% drop
                # from the prior close, the real fill is the limit-down
                # price - strictly worse than the level. The trade is a
                # loss either way; the counter makes the penalty explicit.
                prior_close = sessions[i + k][3]
                locked_open = (
                    low > 0
                    and open_ <= low * 1.001
                    and prior_close > 0
                    and (open_ - prior_close) / prior_close * 100.0
                    <= LOWER_LOCK_CHANGE_PCT
                )
                if open_ <= stop or locked_open:
                    gap_penalized += 1
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
        "gap_penalized_exits": gap_penalized,
    }
