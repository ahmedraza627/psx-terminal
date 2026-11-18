"""sync_daily.py - live PSX ingestion -> WAL store -> quant engine -> frontend JSON.

Run from the repo root:  python -m backend.src.sync_daily
or from anywhere:        python backend/src/sync_daily.py [--date 2026-11-18] [--offline]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))  # `src.*` imports resolve from the backend package

from src.core.config import get_db_path  # noqa: E402
from src.ingestion.live_fetcher import LiveEODFetcher  # noqa: E402
from src.ingestion.sqlite_adapter import load_validated_bars  # noqa: E402
from src.ingestion.wal_adapter import WALIngestionManager  # noqa: E402
from src.quant.backtest import StrategyConfig, run_backtest, write_backtest_report  # noqa: E402
from src.quant.engine import LiquidityQuantEngine  # noqa: E402

DATA_DIR = PROJECT_ROOT / "frontend" / "public" / "data"
LOOKBACK_DAYS = 5
MIN_AVG_VOLUME = 50_000
TREND_MA_DAYS = 50
MIN_RVOL = 1.5
MIN_VOL_Z = 1.0
ATR_STOP_MULT = 2.0
LAB_SESSIONS = 250
MACRO_SESSIONS = 1260  # ~5 years: bull run, 2023 correction and sideways chop


def ingest(db_path: Path, session: date | None) -> tuple[date | None, int, int, str]:
    """Fetch the newest published session and upsert it through the WAL manager."""
    manager = WALIngestionManager(str(db_path))
    manager.ensure_tables()
    fetcher = LiveEODFetcher(cache_dir=PROJECT_ROOT / "data" / "tape_cache")

    session_day, bars, source = fetcher.latest_session(session)
    if not bars:
        return session_day, 0, 0, "unavailable"

    inserted, quarantined = manager.upsert_bars(bars)
    return session_day, inserted, quarantined, source


def scan(db_path: Path) -> tuple[list[dict], int, date | None]:
    """Run LiquidityQuantEngine over every validated bar in the store."""
    bars_by_ticker, rejected = load_validated_bars(str(db_path))
    engine = LiquidityQuantEngine(
        lookback_days=LOOKBACK_DAYS,
        min_avg_volume=MIN_AVG_VOLUME,
        trend_ma_days=TREND_MA_DAYS,
        min_rvol=MIN_RVOL,
        min_vol_z=MIN_VOL_Z,
        atr_stop_mult=ATR_STOP_MULT,
    )

    signals, latest = [], None
    for bars in bars_by_ticker.values():
        if not bars:
            continue
        latest = bars[-1].trade_date if latest is None else max(latest, bars[-1].trade_date)
        signal = engine.evaluate_ticker(bars)
        if signal:
            signals.append(signal.model_dump(mode="json"))
    signals.sort(key=lambda item: -item["confidence_score"])
    return signals, rejected, latest


def refresh_desk_files() -> dict | None:
    """Let the desk pipeline rewrite latest.json / history.json for the same session."""
    sys.path.insert(0, str(BACKEND_DIR / "scripts"))
    try:
        import process_daily_tape  # noqa: E402

        return process_daily_tape.main()
    except Exception as exc:  # the engine output above is still written
        print(f"[WARN] desk refresh skipped: {exc}")
        return None


def run_daily_sync(session: date | None = None, offline: bool = False) -> int:
    print("=" * 52)
    print("   PSX QUANT FUND: LIVE INGESTION + QUANT SYNC")
    print("=" * 52)

    db_path = get_db_path()
    manager = WALIngestionManager(str(db_path))
    manager.ensure_tables()
    print(f"[INFO] store: {db_path} (WAL)")

    if offline:
        session_day, inserted, quarantined, source = None, 0, 0, "stored-state"
    else:
        session_day, inserted, quarantined, source = ingest(db_path, session)
        print(f"[INFO] {source}: {inserted} bars upserted, {quarantined} quarantined"
              f"{f' for {session_day}' if session_day else ''}")

    signals, rejected, latest_bar = scan(db_path)
    session_day = session_day or latest_bar
    print(f"[INFO] engine: {len(signals)} signals over stored bars ({rejected} invalid rows skipped)")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "signals.json").write_text(json.dumps({
        "sessionDate": session_day.isoformat() if session_day else None,
        "source": source,
        "engine": {
            "lookbackDays": LOOKBACK_DAYS,
            "minAvgVolume": MIN_AVG_VOLUME,
            "trendMaDays": TREND_MA_DAYS,
            "minRvol": MIN_RVOL,
            "minVolZ": MIN_VOL_Z,
            "atrStopMult": ATR_STOP_MULT,
            "weeklyConfluence": False,
            "pocConfluence": False,
        },
        "signals": signals,
    }, indent=2), encoding="utf-8")

    desk = refresh_desk_files()

    # Replay the stored year so the backtest lab tracks the same tape as the desk.
    try:
        report = run_backtest(str(db_path), StrategyConfig(max_sessions=LAB_SESSIONS))
        write_backtest_report(report, DATA_DIR / "backtest_metrics.json")
        metrics = report["metrics"]
        print(f"[INFO] backtest: {metrics['totalSignals']} signals over "
              f"{report['sessionRange']['sessions']} sessions "
              f"({metrics['winRatePct']}% win, {metrics['totalReturnPct']}% return)")
    except Exception as exc:  # a backtest gap must never block today's signals
        print(f"[WARN] backtest skipped: {exc}")

    # Same rules over the full multi-year cycle, for the macro stress-test tab.
    try:
        macro = run_backtest(str(db_path), StrategyConfig(max_sessions=MACRO_SESSIONS))
        write_backtest_report(macro, DATA_DIR / "backtest_5y_metrics.json")
        m = macro["metrics"]
        print(f"[INFO] macro backtest: {m['totalSignals']} signals over "
              f"{macro['sessionRange']['years']}y ({m['winRatePct']}% win, "
              f"CAGR {m['cagrPct']}%, max DD {m['maxDrawdownPct']}%)")
    except Exception as exc:
        print(f"[WARN] macro backtest skipped: {exc}")

    (DATA_DIR / "sync_status.json").write_text(json.dumps({
        "lastSynced": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sessionDate": session_day.isoformat() if session_day else None,
        "status": "SUCCESS" if (signals or desk) else "NO_DATA",
        "source": source,
        "barsUpserted": inserted,
        "quarantined": quarantined,
        "signals": len(signals),
        "engineVersion": "v2.0-wal-live",
    }, indent=2), encoding="utf-8")

    print(f"[SUCCESS] wrote {DATA_DIR / 'signals.json'} and sync_status.json")
    if desk:
        print(f"[SUCCESS] desk refreshed for {desk['sessionDate']}")
    return 0 if (signals or desk) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Live PSX ingestion + quant refresh")
    parser.add_argument("--date", help="pin a session (YYYY-MM-DD); default: newest published")
    parser.add_argument("--offline", action="store_true", help="rescan the stored state only")
    args = parser.parse_args()
    session = datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else None
    return run_daily_sync(session=session, offline=args.offline)


if __name__ == "__main__":
    sys.exit(main())
