"""ATR stop-geometry sweep over stored signals + EOD history.

Every directional signal stores stop_loss = entry - 2.0 x ATR(14) at signal
time (the engine's convention). From (entry, stop) we recover the signal-day
ATR unit exactly:

    ATR_unit = (entry - stop) / 2.0

The sweep re-stops every setup at multiple = m x ATR_unit for m in
{1.50, 1.75, ..., 3.00} and resolves the synthetic trade with the backtester's
shared resolver (target = entry + 2R; same-session double touch = stop;
t+5/10/20 close returns; HIGH/LOW excursions).

Stats per multiple (resolved trades only; NULL-flag windows excluded):

    win-rate %   share of resolved trades hitting the 2R target first
    profit factor gross wins / gross losses (winners bank +2R, losers -1R)
    expectancy E[R] = hit_rate x 2 - (1 - hit_rate)

Results are cross-sectional averages over the full dataset and per signal
type. Nothing is written to the database - this is read-only analysis.

Usage:
    python -m pipeline.analytics.stop_sweep
    python -m pipeline.analytics.stop_sweep --per-type --min-distance-pct 1.5
"""

from __future__ import annotations

import argparse
import logging
import os
from collections import defaultdict
from typing import Any

from pipeline import db
from pipeline.analytics.backtester import ENGINE_ATR_MULTIPLE, resolve_trade
from pipeline.analytics.quant_engine import parse_db_date

LOGGER = logging.getLogger(__name__)

# ATR provenance: importable from the backtester (env ATR_STOP_MULT), so the
# sweep, backtester and engine always share one definition of "engine stop".
DEFAULT_MULTIPLES = (1.00, 1.25, 1.50, 1.75, 2.00, 2.25, 2.50, 2.75, 3.00)
TARGET_R = float(os.getenv("BACKTEST_TARGET_R", "2.0"))
MIN_STOP_DISTANCE_PCT = float(os.getenv("RISK_MIN_STOP_DISTANCE_PCT", "1.5"))


def load_setups() -> list[dict[str, Any]]:
    """Evaluable long-bias setups: entry, engine stop, ticker, type."""
    signals = db.fetch_unbacktested_signals(
        max_age_days=10_000, limit=20000
    )
    # fetch_unbacktested_signals anti-joins backtest rows; the sweep wants
    # every evaluable signal regardless of evaluation state, so re-pull raw.
    signals = db._paginated_select(
        "signals_computed",
        "id,trade_date,ticker,signal_type,entry_reference,stop_loss,metadata",
        order_desc_col="trade_date",
        order_asc_col="id",
        max_rows=20000,
    )
    setups: list[dict[str, Any]] = []
    skipped = 0
    for signal in signals:
        entry = signal.get("entry_reference")
        stop = signal.get("stop_loss")
        if entry is None or stop is None:
            skipped += 1
            continue
        entry = float(entry)
        stop = float(stop)
        risk = entry - stop
        if risk <= 0:
            skipped += 1
            continue
        atr_unit = risk / ENGINE_ATR_MULTIPLE
        if atr_unit <= 0:
            skipped += 1
            continue
        setups.append(
            {
                "id": signal["id"],
                "trade_date": parse_db_date(signal["trade_date"]),
                "ticker": str(signal["ticker"]).upper().strip(),
                "signal_type": signal["signal_type"],
                "entry": entry,
                "stop": stop,
                "atr_unit": atr_unit,
            }
        )
    LOGGER.info(
        "sweep: %d setups loaded (%d skipped - no entry/stop)",
        len(setups),
        skipped,
    )
    return setups


def _series_by_ticker(history: list[dict[str, Any]]):
    from collections import defaultdict

    grouped: dict[str, list[tuple[Any, dict[str, float]]]] = defaultdict(list)
    for row in history:
        day = parse_db_date(row.get("trade_date"))
        ticker = str(row.get("ticker", "")).upper().strip()
        close = row.get("close_price")
        if day is None or not ticker or close is None:
            continue
        grouped[ticker].append(
            (
                day,
                {
                    "close": float(close),
                    "high": float(row["high_price"]) if row.get("high_price") is not None else float(close),
                    "low": float(row["low_price"]) if row.get("low_price") is not None else float(close),
                },
            )
        )
    for ticker in grouped:
        grouped[ticker].sort(key=lambda item: item[0])
    return grouped


def sweep(setups: list[dict[str, Any]], multiples=DEFAULT_MULTIPLES):
    """Re-stop every setup at each multiple; aggregate resolution stats."""
    history = db.fetch_recent_eod(days=140)
    series = _series_by_ticker(history)

    # Pre-split forward windows once per setup (identical across multiples).
    prepared: list[dict[str, Any]] = []
    for setup in setups:
        ticker_series = series.get(setup["ticker"]) or []
        forward = [
            (day, px) for day, px in ticker_series if day > setup["trade_date"]
        ]
        if forward:
            prepared.append({**setup, "forward": forward})

    results: list[dict[str, Any]] = []
    for multiple in multiples:
        resolved = 0
        hits = 0
        stops = 0
        t5: list[float] = []
        per_type: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"resolved": 0, "hits": 0, "stops": 0, "t5": []}
        )
        for setup in prepared:
            # Synthetic stop at m x ATR_unit (m = 2.0 reproduces the engine).
            stop = setup["entry"] - multiple * setup["atr_unit"]
            if (setup["entry"] - stop) / setup["entry"] < MIN_STOP_DISTANCE_PCT / 100.0:
                continue  # below the risk engine's noise floor: not tradeable
            outcome = resolve_trade(
                setup["forward"], setup["entry"], stop, target_r=TARGET_R
            )
            hit_target = outcome["hit_target"]
            stopped_out = outcome["stopped_out"]
            if hit_target is None or not (hit_target or stopped_out):
                continue  # unresolved inside the window: excluded
            resolved += 1
            bucket = per_type[setup["signal_type"]]
            bucket["resolved"] += 1
            if hit_target:
                hits += 1
                bucket["hits"] += 1
            elif stopped_out:
                stops += 1
                bucket["stops"] += 1
            if outcome["return_t5_pct"] is not None:
                t5.append(float(outcome["return_t5_pct"]))
                bucket["t5"].append(float(outcome["return_t5_pct"]))

        hit_rate = hits / resolved if resolved else 0.0
        expectancy = hit_rate * TARGET_R - (1.0 - hit_rate)
        results.append(
            {
                "atr_multiple": multiple,
                "resolved": resolved,
                "hits": hits,
                "stops": stops,
                "win_rate_pct": round(hit_rate * 100.0, 1),
                "stop_rate_pct": round(stops / resolved * 100.0, 1) if resolved else 0.0,
                "profit_factor": (
                    round(hits * TARGET_R / stops, 3) if stops else None
                ),
                "expectancy_r": round(expectancy, 3),
                "avg_t5_pct": round(sum(t5) / len(t5), 2) if t5 else None,
                "per_type": dict(per_type),
            }
        )
    return results


def print_results(results: list[dict[str, Any]], per_type: bool = False) -> None:
    header = (
        f"{'ATRx':>6} {'resolved':>9} {'hit%':>6} {'stop%':>7} "
        f"{'PF':>7} {'E[R]':>7} {'avgT5%':>7}"
    )
    print(header)
    print("-" * len(header))
    for r in results:
        pf = "inf" if r["profit_factor"] is None else f"{r['profit_factor']:.2f}"
        t5 = "—" if r["avg_t5_pct"] is None else f"{r['avg_t5_pct']:.2f}"
        print(
            f"{r['atr_multiple']:>6.2f} {r['resolved']:>9d} "
            f"{r['win_rate_pct']:>6.1f} {r['stop_rate_pct']:>7.1f} "
            f"{pf:>7s} {r['expectancy_r']:>7.2f} {t5:>7s}"
        )
    best = max(results, key=lambda r: r["expectancy_r"])
    print(
        f"\nOptimal expectancy: {best['atr_multiple']:.2f}x ATR "
        f"(E[R]={best['expectancy_r']:.2f}, hit {best['win_rate_pct']}%, "
        f"PF {best['profit_factor']})"
    )

    if per_type:
        for multiple_result in results:
            print(f"\n=== {multiple_result['atr_multiple']:.2f}x per type ===")
            rows = sorted(
                (
                    (t, b["hits"] / b["resolved"] * 100, b["resolved"])
                    for t, b in multiple_result["per_type"].items()
                    if b["resolved"]
                ),
                key=lambda kv: -kv[1],
            )
            for t, hit_pct, n in rows:
                print(f"  {t:26s} hit {hit_pct:5.1f}%  (n={n})")


def main() -> None:
    global MIN_STOP_DISTANCE_PCT
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="ATR stop-geometry sweep")
    parser.add_argument(
        "--per-type", action="store_true", help="Break results down by signal type"
    )
    parser.add_argument(
        "--min-distance-pct",
        type=float,
        default=MIN_STOP_DISTANCE_PCT,
        help="Minimum stop distance %% (risk engine noise floor)",
    )
    args = parser.parse_args()

    MIN_STOP_DISTANCE_PCT = args.min_distance_pct

    setups = load_setups()
    if not setups:
        print("No setups with entry+stop available for the sweep.")
        return
    results = sweep(setups)
    print_results(results, per_type=args.per_type)


if __name__ == "__main__":
    main()
