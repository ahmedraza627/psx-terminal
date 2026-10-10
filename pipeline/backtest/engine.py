"""Quick walk-forward backtester - the decision engine's historical edge proof.

Simulates the engine's own entry/stop/target logic on a ticker's stored
tape so the Action Desk can show a certified win rate next to every BUY
verdict instead of asking the user to trust an unproven signal.

Methodology (documented, never fabricated):

  History      The last 3 years of psx_daily_eod for ONE ticker, sessions
               strictly before ``target_date`` (no look-ahead).

  SHORT_TERM   Signal = session volume > 2.5x the 20-day volume SMA (the
               exact criterion the live engine certifies on).
  MID_TERM     Signal = close above its 20-day SMA with positive
               5-session momentum (the mid-horizon "performing leader"
               proxy; the live flow cross-check has no daily history).
  LONG_TERM    An AVOID verdict carries no trade to simulate -> None.

  Entry        The next session's close after the signal - the same
               "entry = latest session close" convention the live engine
               stamps into entry_ref (you cannot trade the close you just
               watched form).

  Stop/Target  Stop = entry - 1.5 x ATR, where ATR is the mean absolute
               close-to-close change over the last 4 sessions at signal
               time (the engine's documented ATR proxy). Target =
               entry + 2.0 x risk (SHORT_TERM, minimum 1:2 R:R) or
               entry + 2.5 x risk (MID_TERM).

  Resolution   Bar-by-bar from the entry bar, using the stored high/low.
               Same-bar hit of both levels resolves to the STOP first
               (conservative). Exit window: 10 sessions (SHORT_TERM) or
               40 sessions (MID_TERM); an unresolved trade is a scratch
               and counts toward total trades but never as a win.

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
VOLUME_SPIKE_RATIO = 2.5     # matches the live SHORT_TERM criterion
VOLUME_SMA_WINDOW = 20
ATR_PROXY_SESSIONS = 4
REWARD_MULT = {"SHORT_TERM": 2.0, "MID_TERM": 2.5}
EXIT_WINDOW_SESSIONS = {"SHORT_TERM": 10, "MID_TERM": 40}

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


def _signal_indexes(
    horizon: str, closes: list[float], volumes: list[float]
) -> list[int]:
    """Historical signal bars for the horizon's documented criterion."""
    signals: list[int] = []
    for i in range(VOLUME_SMA_WINDOW, len(closes)):
        if horizon == "SHORT_TERM":
            sma = sum(volumes[i - VOLUME_SMA_WINDOW : i]) / VOLUME_SMA_WINDOW
            if sma > 0 and volumes[i] > VOLUME_SPIKE_RATIO * sma:
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
    mult = REWARD_MULT.get(horizon)
    if mult is None:
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
        # ATR proxy at signal time: mean |close-to-close| over the last 4 sessions.
        leg = closes[max(0, i - ATR_PROXY_SESSIONS + 1) : i + 1]
        changes = [abs(leg[k] - leg[k - 1]) for k in range(1, len(leg))]
        atr = sum(changes) / len(changes) if changes else 0.0
        if atr <= 0:
            continue
        stop = entry - 1.5 * atr
        if stop <= 0:
            continue
        target = entry + mult * (entry - stop)

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
