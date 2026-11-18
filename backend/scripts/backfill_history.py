"""backfill_history.py - extend the EOD store to a full multi-year cycle.

The live desk only appends today's tape, so the research store has to be seeded
separately. This script pulls a long daily history from the public Yahoo Finance
chart endpoint (PSX symbols use the ``.KA`` suffix) and upserts every bar through
the same WAL manager the live pipeline uses, so rows keep one schema, one primary
key and the same validation rules.

Gaps are expected, not exceptional: PSX halts names, Yahoo omits sessions and some
symbols do not exist on the vendor at all. A missing row is skipped, a symbol that
fails after its retries is reported, and the run always exits 0 with a coverage
table so a short history never breaks a simulation.

Run it:  python backend/scripts/backfill_history.py --years 5
         python backend/scripts/backfill_history.py --tickers UBL,MCB --years 5
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, List

import requests

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:  # allow direct CLI execution
    sys.path.insert(0, str(BACKEND_DIR))

from src.core.config import get_db_path  # noqa: E402
from src.core.models import DailyBar  # noqa: E402
from src.ingestion.wal_adapter import WALIngestionManager  # noqa: E402
from src.ingestion.universe import active_universe  # noqa: E402

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}


def _session_range() -> tuple[date, date]:
    today = datetime.now(timezone.utc).date()
    return today - timedelta(days=366 * 6), today


def fetch_symbol(symbol: str, years: int, retries: int = 3) -> List[DailyBar]:
    """One Yahoo chart request -> validated DailyBar list (empty when unavailable)."""
    params = {"range": f"{years}y", "interval": "1d"}
    for attempt in range(retries):
        try:
            response = requests.get(
                CHART_URL.format(symbol=symbol), params=params, headers=HEADERS, timeout=20
            )
            if response.status_code == 429:
                time.sleep(2 + attempt * 2)
                continue
            if response.status_code != 200:
                print(f"    HTTP {response.status_code}")
                return []
            results = response.json().get("chart", {}).get("result") or []
            if not results:
                return []
            data = results[0]
            stamps = data.get("timestamp") or []
            quote = (data.get("indicators", {}).get("quote") or [{}])[0]
            opens = quote.get("open") or []
            highs = quote.get("high") or []
            lows = quote.get("low") or []
            closes = quote.get("close") or []
            volumes = quote.get("volume") or []
            ticker = symbol.split(".")[0].upper()

            bars: List[DailyBar] = []
            for i, stamp in enumerate(stamps):
                # Vendor holes are normal: require the whole OHLC row before accepting it.
                if not all(i < len(series) and series[i] is not None for series in (opens, highs, lows, closes)):
                    continue
                try:
                    bars.append(
                        DailyBar(
                            ticker=ticker,
                            trade_date=datetime.fromtimestamp(stamp, timezone.utc).date(),
                            open_price=round(float(opens[i]), 2),
                            high_price=round(float(highs[i]), 2),
                            low_price=round(float(lows[i]), 2),
                            close_price=round(float(closes[i]), 2),
                            volume=int(volumes[i] or 0) if i < len(volumes) else 0,
                        )
                    )
                except (ValueError, TypeError):
                    continue  # a corrupt print must not kill the symbol
            return bars
        except (requests.RequestException, ValueError) as exc:
            if attempt == retries - 1:
                print(f"    failed: {exc}")
                return []
            time.sleep(1 + attempt)
    return []


def backfill(db_path: str, tickers: Iterable[str], years: int, sleep: float = 0.3) -> dict:
    manager = WALIngestionManager(db_path)
    manager.ensure_tables()
    summary = {"symbols": 0, "bars": 0, "empty": [], "firstSession": None, "lastSession": None}

    for ticker in sorted({t.strip().upper() for t in tickers if t.strip()}):
        symbol = ticker if "." in ticker else f"{ticker}.KA"
        bars = fetch_symbol(symbol, years)
        if not bars and "." in symbol:
            bars = fetch_symbol(ticker, years)  # some vendors publish the bare symbol
        if not bars:
            summary["empty"].append(ticker)
            print(f"[MISS] {ticker}: no usable bars")
            time.sleep(sleep)
            continue

        inserted, quarantined = manager.upsert_bars(bars)
        summary["symbols"] += 1
        summary["bars"] += len(bars)
        first, last = bars[0].trade_date, bars[-1].trade_date
        summary["firstSession"] = min(filter(None, [summary["firstSession"], first]))
        summary["lastSession"] = max(filter(None, [summary["lastSession"], last]))
        print(f"[OK]   {ticker}: {inserted} bars {first} -> {last}"
              f"{f' ({quarantined} rejected)' if quarantined else ''}")
        time.sleep(sleep)

    return summary


def coverage(db_path: str, min_bars: int = 250) -> list[tuple[str, int, str, str]]:
    import sqlite3

    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT ticker, COUNT(*), MIN(date), MAX(date) FROM daily_eod "
            "GROUP BY ticker HAVING COUNT(*) >= ? ORDER BY COUNT(*) DESC",
            (min_bars,),
        ).fetchall()
    finally:
        conn.close()
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill multi-year PSX EOD history")
    parser.add_argument("--db", help="SQLite store (default: backend/psx_history.db)")
    parser.add_argument("--years", type=int, default=5, help="calendar years to request")
    parser.add_argument("--tickers", help="comma-separated symbols; default: active universe")
    parser.add_argument("--all", action="store_true", help="every symbol already in the store")
    parser.add_argument("--sleep", type=float, default=0.3, help="politeness delay per symbol")
    parser.add_argument("--min-bars", type=int, default=250, help="coverage floor for the report")
    args = parser.parse_args()

    db_path = args.db or str(get_db_path())
    if args.tickers:
        tickers = [t for t in args.tickers.split(",") if t.strip()]
    elif args.all:
        import sqlite3

        conn = sqlite3.connect(db_path)
        tickers = [row[0] for row in conn.execute("SELECT DISTINCT ticker FROM daily_eod")]
        conn.close()
    else:
        tickers = active_universe(db_path)

    print(f"store   : {db_path}")
    print(f"universe: {len(tickers)} symbols · requesting {args.years}y of daily bars\n")

    summary = backfill(db_path, tickers, args.years, sleep=args.sleep)

    print("\ncoverage (>= %d bars):" % args.min_bars)
    rows = coverage(db_path, args.min_bars)
    for ticker, count, first, last in rows[:15]:
        print(f"  {ticker:<10} {count:>5} bars  {first} -> {last}")
    print(f"  … {len(rows)} symbols qualify")

    print(
        f"\ndone: {summary['symbols']}/{len(tickers)} symbols, {summary['bars']} bars, "
        f"{len(summary['empty'])} unavailable"
    )
    if summary["firstSession"]:
        print(f"range: {summary['firstSession']} -> {summary['lastSession']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
