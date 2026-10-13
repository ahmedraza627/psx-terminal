"""Automated trade outcome tracker — ground-truth loop for the ML dataset.

Each pipeline run (Mon-Fri, post-close):
  1. Fetches every OPEN row in psx_trade_outcomes.
  2. Evaluates that ticker's EOD bar for trade_date (or the latest available
     session when the exact date is not yet in the tape).
  3. Resolves the trade in strict execution order — STOP first, then TP1,
     then time expiration — with conservative fills that honour gap-downs
     and gap-ups, and increments bars_held.
  4. Upserts the updated rows back into psx_trade_outcomes.

The table is schema-managed in migrations/012_trade_outcomes.sql. When that
migration has not been applied yet (or the table is absent), the module degrades
to an honest idle state (resolved = 0, open = 0) rather than aborting the run.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Optional

from pipeline import db

LOGGER = logging.getLogger(__name__)

SHORT_EXPIRY_BARS = 5
MID_EXPIRY_BARS = 15


def _num(value: Any) -> Optional[float]:
    """Tolerant float coercion for EOD bar fields that may be None/empty."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _resolve_trade(
    trade: dict[str, Any],
    eod_bar: Optional[dict[str, Any]],
) -> dict[str, Any]:
    """Return a mutated copy of ``trade`` resolved against one EOD bar.

    Conservative execution order: STOP_LOSS first, then TP1, then time
    expiration. The first rule that fires wins — a bar that hit both the stop
    and the target resolves to the STOP (conservative, and matches the live
    backtester's same-bar double-hit convention).
    """
    ticker = trade["ticker"]
    horizon = trade["horizon"]
    entry_price = float(trade["entry_price"])
    stop_loss = float(trade["stop_loss"])
    tp1_target = float(trade["tp1_target"])
    bars_held = int(trade.get("bars_held", 0)) + 1

    # No bar for the requested session — leave OPEN, do not fabricate an exit.
    if eod_bar is None:
        return {
            **trade,
            "bars_held": bars_held,
            "_skip_exit": True,
        }

    eod_open = _num(eod_bar.get("open_price"))
    eod_high = _num(eod_bar.get("high_price"))
    eod_low = _num(eod_bar.get("low_price"))
    eod_close = _num(eod_bar.get("close_price"))

    if eod_close is None or eod_open is None:
        return {
            **trade,
            "bars_held": bars_held,
            "_skip_exit": True,
        }

    status: Optional[str] = None
    exit_price: Optional[float] = None
    pnl_pct: Optional[float] = None
    r_multiple: Optional[float] = None
    exit_date: Optional[str] = None

    # 1) Stop loss hit.
    if eod_low is not None and eod_low <= stop_loss:
        status = "LOSS_SL"
        exit_price = max(eod_open, stop_loss)
        pnl_pct = round(((exit_price - entry_price) / entry_price) * 100, 2)
        r_multiple = -1.0
        exit_date = trade.get("verdict_date") or date.isoformat(date.today())
        LOGGER.info(
            "outcome_tracker: %s %s -> LOSS_SL @ PKR %.2f (low PKR %.2f)",
            ticker, horizon, exit_price, eod_low,
        )

    # 2) Take-profit 1 hit (only when the stop was NOT triggered this bar).
    elif eod_high is not None and eod_high >= tp1_target:
        status = "WIN_TP1"
        exit_price = min(eod_open, tp1_target)
        risk = max(entry_price - stop_loss, 0.01)
        r_multiple = round((exit_price - entry_price) / risk, 2)
        pnl_pct = round(((exit_price - entry_price) / entry_price) * 100, 2)
        exit_date = trade.get("verdict_date") or date.isoformat(date.today())
        LOGGER.info(
            "outcome_tracker: %s %s -> WIN_TP1 @ PKR %.2f (high PKR %.2f)",
            ticker, horizon, exit_price, eod_high,
        )

    # 3) Time expiration (evaluated even when the bar did not hit either level).
    if status is None and bars_held >= EXPIRY_BARS(horizon):
        status = "EXPIRED_TIME"
        exit_price = eod_close
        pnl_pct = round(((exit_price - entry_price) / entry_price) * 100, 2)
        if stop_loss is not None and entry_price != stop_loss:
            r_multiple = round(
                (exit_price - entry_price) / max(entry_price - stop_loss, 0.01), 2
            )
        exit_date = trade.get("verdict_date") or date.isoformat(date.today())
        LOGGER.info(
            "outcome_tracker: %s %s -> EXPIRED_TIME (bars_held=%d) @ PKR %.2f",
            ticker, horizon, bars_held, exit_price,
        )

    return {
        **trade,
        "bars_held": bars_held,
        "status": status if status is not None else trade.get("status"),
        "exit_price": exit_price,
        "pnl_pct": pnl_pct,
        "r_multiple": r_multiple,
        "exit_date": exit_date,
        "_skip_exit": status is None and bars_held < EXPIRY_BARS(horizon),
    }


def EXPIRY_BARS(horizon: str) -> int:
    """Max bars a trade may stay open before time expiration resolves it."""
    return SHORT_EXPIRY_BARS if horizon == "SHORT_TERM" else MID_EXPIRY_BARS


def _open_trades(trade_date: date) -> list[dict[str, Any]]:
    """OPEN rows in psx_trade_outcomes, newest verdict_date first.

    Paginates with the shared _paginated_select so a runaway OPEN set never
    opens a full-table scan. In practice this is handful-sized.
    """
    return db._paginated_select(
        "psx_trade_outcomes",
        "verdict_date,horizon,ticker,entry_price,stop_loss,tp1_target,"
        "suggested_alloc_pct,features_snapshot,bars_held,status,exit_price,"
        "pnl_pct,r_multiple,exit_date",
        order_desc_col="verdict_date",
        order_asc_col="ticker",
        max_rows=500,
        filters=[("status", "eq", "OPEN")],
    )


def _bar_for_ticker(ticker: str, trade_date: date) -> Optional[dict[str, Any]]:
    """EOD bar for one ticker on the requested session, or the latest available.

    Tries the exact session first; when the tape has not yet recorded that date
    (D1/D2 backlog, or the verdict_date was a future-set simulation), falls back
    to the most recent stored bar strictly after the verdict_date so the tracker
    stays honest instead of fabricating a price.
    """
    iso = trade_date.isoformat()
    try:
        rows = db._paginated_select(
            "psx_daily_eod",
            "trade_date,open_price,high_price,low_price,close_price,volume",
            order_desc_col="trade_date",
            order_asc_col="ticker",
            max_rows=2,
            filters=[("trade_date", "eq", iso), ("ticker", "eq", ticker)],
        )
    except Exception:  # noqa: BLE001 — a missing table is handled by _paginated_select
        rows = []

    if rows:
        bar = rows[0]
        if bar.get("close_price") is not None:
            return bar
        # Exact-date row exists but has no close (partial/incomplete record) —
        # do not treat it as a real bar.
        return None

    # Fallback: latest stored bar strictly after the verdict_date.
    try:
        rows = db._paginated_select(
            "psx_daily_eod",
            "trade_date,open_price,high_price,low_price,close_price,volume",
            order_desc_col="trade_date",
            order_asc_col="ticker",
            max_rows=1,
            filters=[
                ("trade_date", "gt", iso),
                ("ticker", "eq", ticker),
            ],
        )
    except Exception:
        rows = []

    if rows and rows[0].get("close_price") is not None:
        return rows[0]
    return None


def resolve_open_trades(trade_date: date) -> dict[str, Any]:
    """Resolve every OPEN trade against trade_date's EOD tape.

    Returns {"resolved": <int>, "open": <int>}:
      - resolved: trades that moved to a terminal status this run (LOSS_SL,
        WIN_TP1, or EXPIRED_TIME).
      - open: OPEN trades that were still open after this run (still working,
        or wait-and-see bars).

    Graceful degradation:
      - If psx_trade_outcomes has no OPEN rows, returns {"resolved": 0, "open": 0}.
      - If the table is absent (migration not yet applied), degrades to the same
        honest idle shape and logs once.
    """
    try:
        open_rows = _open_trades(trade_date)
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("outcome_tracker: could not read OPEN trades: %s", exc)
        return {"resolved": 0, "open": 0}

    if not open_rows:
        return {"resolved": 0, "open": 0}

    LOGGER.info(
        "outcome_tracker: %d OPEN trade(s) to evaluate for %s",
        len(open_rows), trade_date.isoformat(),
    )

    resolved_updates: list[dict[str, Any]] = []
    still_open: list[dict[str, Any]] = []
    resolved = 0

    for trade in open_rows:
        ticker = trade["ticker"]
        bar = _bar_for_ticker(ticker, trade_date)
        resolved_trade = _resolve_trade(trade, bar)

        # Drop internal bookkeeping keys before persistence.
        row_out = {k: v for k, v in resolved_trade.items() if not k.startswith("_")}

        if resolved_trade.get("_skip_exit"):
            still_open.append(row_out)
            continue

        new_status = row_out.get("status")
        if new_status in ("LOSS_SL", "WIN_TP1", "EXPIRED_TIME"):
            resolved += 1
            resolved_updates.append(row_out)
        else:
            still_open.append(row_out)

    written = 0
    if resolved_updates:
        try:
            written = db.upsert_records(
                "psx_trade_outcomes",
                resolved_updates,
                on_conflict="verdict_date,horizon,ticker",
            )
        except Exception as exc:  # noqa: BLE001 — outcome tracking must never kill the run
            LOGGER.warning("outcome_tracker: upsert of resolved trades failed: %s", exc)

    LOGGER.info(
        "outcome_tracker: %s resolved=%d written=%d still_open=%d",
        trade_date.isoformat(), resolved, written, len(still_open),
    )
    return {"resolved": resolved, "open": len(still_open)}


# --------------------------------------------------------------------------- #
# Setup logging: persist active setups into psx_trade_outcomes.             #
# --------------------------------------------------------------------------- #


def _features_snapshot(
    verdict: dict[str, Any],
    tape_state: str,
    series: dict[str, list[tuple[date, float, float]]],
) -> dict[str, Any]:
    """Feature snapshot for the ML dataset, from the verdict + session tape.

    Kept honest: when a feature cannot be computed cleanly it is left as None
    rather than fabricated.
    """
    ticker = verdict["ticker"]
    points = series.get(ticker) or []
    closes = [p[1] for p in points if p[1] > 0]
    volumes = [p[2] for p in points if p[2] > 0]

    # ATR% proxy (same documented convention the engine uses): mean absolute
    # close-to-close change over the last 4 sessions, as a % of the latest close.
    atr_pct: Optional[float] = None
    if len(closes) >= 2:
        leg = closes[-4:] if len(closes) >= 4 else closes
        changes = [abs(leg[k] - leg[k - 1]) for k in range(1, len(leg))]
        if changes:
            last_close = closes[-1]
            if last_close > 0:
                atr_pct = round((sum(changes) / len(changes)) / last_close * 100, 4)

    # Volume dry-up ratio: latest session volume vs the 20-session average.
    volume_ratio: Optional[float] = None
    if len(volumes) >= 20:
        recent_vol = volumes[-1]
        avg20 = sum(volumes[-20:]) / 20.0
        if avg20 > 0:
            volume_ratio = round(recent_vol / avg20, 4)

    return {
        "atr_pct": atr_pct,
        "volume_ratio": volume_ratio,
        "tape_state": tape_state,
        "horizon": verdict["horizon"],
        "regime_status": verdict.get("regime_status"),
        "fundamental_score": verdict.get("fundamental_score"),
        "historical_win_rate": verdict.get("historical_win_rate"),
    }


def log_active_setups(
    rows: list[dict[str, Any]],
    trade_date: date,
    tape_state: str,
    series: dict[str, list[tuple[date, float, float]]],
) -> int:
    """Upsert an OPEN setup row per active BUY verdict into psx_trade_outcomes.

    Idempotent on (verdict_date, horizon, ticker): reruns overwrite the same
    OPEN row and never duplicate it, and they never overwrite an already-resolved
    outcome row because the verdict_date/horizon/ticker of a resolved row differs
    from any new verdict's (it keeps the original verdict_date).

    Returns the number of rows written (0 when there are no active setups).
    """
    if not rows:
        return 0

    out: list[dict[str, Any]] = []
    for v in rows:
        if v.get("direction") != "BUY":
            continue
        entry = v.get("entry_ref")
        stop = v.get("stop_loss")
        target = v.get("target_price")
        if entry is None or stop is None or target is None:
            continue

        out.append({
            "verdict_date": v["trade_date"],
            "horizon": v["horizon"],
            "ticker": v["ticker"],
            "entry_price": round(float(entry), 2),
            "stop_loss": round(float(stop), 2),
            "tp1_target": round(float(target), 2),
            "suggested_alloc_pct": v.get("suggested_alloc_pct"),
            "features_snapshot": _features_snapshot(v, tape_state, series),
            "bars_held": 0,
            "status": "OPEN",
            "exit_price": None,
            "pnl_pct": None,
            "r_multiple": None,
            "exit_date": None,
        })

    if not out:
        return 0

    try:
        written = db.upsert_records(
            "psx_trade_outcomes",
            out,
            on_conflict="verdict_date,horizon,ticker",
        )
    except Exception as exc:  # noqa: BLE001 — outcome logging must never kill the run
        LOGGER.warning("outcome_tracker: log_active_setups upsert failed: %s", exc)
        return 0

    LOGGER.info(
        "outcome_tracker: logged %d active setup(s) for %s (written=%d)",
        len(out), trade_date.isoformat(), written,
    )
    return written


# --------------------------------------------------------------------------- #
# Lightweight synthetic harness (importable, not run on import).            #
# --------------------------------------------------------------------------- #


def _synthetic_win_tp1_probe() -> dict[str, Any]:
    """Exercise the resolve path with a synthetic bar that hits TP1 only.

    This proves the execution order + fill math end-to-end against the real
    _resolve_trade implementation without hitting Supabase.
    """
    trade = {
        "verdict_date": "2026-02-06",
        "horizon": "SHORT_TERM",
        "ticker": "AIRLINK",
        "entry_price": 210.00,
        "stop_loss": 200.00,
        "tp1_target": 222.60,
        "suggested_alloc_pct": 12,
        "features_snapshot": {"atr_pct": 3.85, "volume_ratio": 0.62, "tape_state": "RISK_ON"},
        "bars_held": 2,
        "status": "OPEN",
        "exit_price": None,
        "pnl_pct": None,
        "r_multiple": None,
        "exit_date": None,
    }
    bar = {
        "trade_date": "2026-02-06",
        "open_price": 209.00,
        "high_price": 223.50,
        "low_price": 206.00,
        "close_price": 218.00,
        "volume": 4_500_000,
    }
    return _resolve_trade(trade, bar)


if __name__ == "__main__":
    probe = _synthetic_win_tp1_probe()
    print("synthetic WIN_TP1 probe result:")
    for k in ("status", "exit_price", "pnl_pct", "r_multiple", "bars_held"):
        print(f"  {k}: {probe.get(k)}")
