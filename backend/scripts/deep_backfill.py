"""deep_backfill.py - 10-15 year historical deep ingestion for the PSX quant desk.

Fetches, parses, validates and stores up to ~15 full years of EOD OHLCV
(~2011 -> 2026) for the active PSX core universe into psx_history.db. It is
designed to survive missing spans, halted tickers, bad rows and transient
network issues so a multi-cycle research backfill does not have to be babysat
for two weeks.

Architecture notes
------------------
* Fetching is chunked by calendar year so a single bad year does not kill the
  whole run and so retries can be scoped to one span at a time.
* Validation happens at the row level before anything touches SQLite, and bad
  rows are quarantined to a separate log instead of crashing the ingest.
* The script uses the same WAL-based idempotent upsert path as the live
  ingestion so a re-run is safe and converges rather than duplicating.
* Tickers whose stored history already covers a full target span are skipped
  unless --force is passed, which keeps the pipeline usable as a refresh too.

Run it
------
python backend/scripts/deep_backfill.py [--db PATH] [--years 15] [--force] [--workers 4]

Suggested cadence
-----------------
Run once after a store is bootstrapped, then re-run monthly with --force to
chase the trailing 12-15 months of newly published EOD history. The first run
over a fresh empty store is the expensive one.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.error import URLError
from urllib.request import Request, urlopen

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from src.core.models import DailyBar  # noqa: E402
from src.ingestion.wal_adapter import WALIngestionManager  # noqa: E402
from src.ingestion.universe import CORE_TICKERS  # noqa: E402

PROJECT_ROOT = BACKEND_DIR.parent
DEFAULT_DB = BACKEND_DIR / "psx_history.db"
QUARANTINE_LOG = BACKEND_DIR / "data" / "backfill_quarantine.jsonl"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("deep_backfill")


# ---------------------------------------------------------------------------
# Target universe + calendar helpers
# ---------------------------------------------------------------------------

# Core universe mirrors ingestion/universe.py so the deep backfill and the
# live desk agree on what "the book" actually is.
TARGET_TICKERS = CORE_TICKERS

SESSIONS_PER_YEAR = 252
MONTHS_PER_YEAR = 12
# Conservative minimum history for a ticker to count as "deep enough" for a
# given horizon. Anything below this is still fetched but flagged.
MIN_BARS_FOR_YEARS = int(SESSIONS_PER_YEAR * 0.9)


def session_count_for_years(years: float) -> int:
    return int(round(years * SESSIONS_PER_YEAR))


def calendar_years_span(first: date, last: date) -> float:
    return max((last - first).days / 365.25, 1 / 365.25)


def years_from_yahoo_span(result: Dict[str, Any]) -> float:
    """Best-effort estimate of the calendar span a Yahoo chart payload covers."""
    try:
        ts = result.get("chart", {}).get("result", [{}])[0].get("timestamp", [])
        if not ts:
            return 0.0
        first_ts = min(ts)
        last_ts = max(ts)
        first_date = datetime.utcfromtimestamp(first_ts).date()
        last_date = datetime.utcfromtimestamp(last_ts).date()
        return calendar_years_span(first_date, last_date)
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# Quarantine log
# ---------------------------------------------------------------------------


def _quarantine_row(ticker: str, raw: Dict[str, Any], reason: str) -> None:
    """Append a bad row to the quarantine log so a bad ingest is reviewable."""
    entry = {
        "id": str(uuid.uuid4()),
        "ticker": ticker,
        "rawKeys": list(raw.keys()) if isinstance(raw, dict) else None,
        "reason": reason,
        "ingestedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    try:
        QUARANTINE_LOG.parent.mkdir(parents=True, exist_ok=True)
        with QUARANTINE_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, default=str) + "\n")
    except Exception as e:
        log.warning("could not write quarantine entry: %s", e)


# ---------------------------------------------------------------------------
# Fetch layer
# ---------------------------------------------------------------------------

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def _yahoo_url(ticker_ka: str, period1: int, period2: int) -> str:
    return (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        f"{ticker_ka}?period1={period1}&period2={period2}&interval=1d&events=history"
    )


def _epoch_for_year(year: int, month: int = 1, day: int = 1) -> int:
    return int((datetime(year, month, day) - datetime(1970, 1, 1)).total_seconds())


def fetch_yahoo_span(
    ticker_ka: str,
    year: int,
    retries: int = 4,
    backoff: float = 2.0,
) -> Tuple[List[Dict[str, Any]], float]:
    """Fetch one calendar year of daily chart data for a .KA ticker.

    Returns (raw_rows, estimated_span_years). Empty on genuine failure after
    retries. Transient network / HTTP errors are retried with exponential
    backoff; a 404 / 401 / 403 is treated as terminal for that year so we do
    not hammer a dead endpoint.
    """
    period1 = _epoch_for_year(year, 1, 1)
    # +1 year so January data is not clipped by a timezone-hesitant period2.
    period2 = _epoch_for_year(year + 1, 1, 1)

    last_error: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            url = _yahoo_url(ticker_ka, period1, period2)
            req = Request(url, headers={"User-Agent": USER_AGENT})
            with urlopen(req, timeout=30) as resp:
                payload = json.loads(resp.read().decode("utf-8", "replace"))
            results = payload.get("chart", {}).get("result", [])
            if not results:
                return [], years_from_yahoo_span(payload)
            data_obj = results[0]
            timestamps = data_obj.get("timestamp", [])
            indicators = data_obj.get("indicators", {}).get("quote", [{}])[0]
            out: List[Dict[str, Any]] = []
            for i in range(len(timestamps)):
                row: Dict[str, Any] = {
                    "ts": timestamps[i],
                    "open": (indicators.get("open") or [])[i] if i < len(indicators.get("open", [])) else None,
                    "high": (indicators.get("high") or [])[i] if i < len(indicators.get("high", [])) else None,
                    "low": (indicators.get("low") or [])[i] if i < len(indicators.get("low", [])) else None,
                    "close": (indicators.get("close") or [])[i] if i < len(indicators.get("close", [])) else None,
                    "volume": (indicators.get("volume") or [])[i] if i < len(indicators.get("volume", [])) else None,
                }
                out.append(row)
            span = years_from_yahoo_span(payload)
            return out, span
        except URLError as e:
            last_error = e
            wait = backoff ** attempt
            log.warning(
                "%s year=%d attempt=%d/%d url error: %s (retry in %.1fs)",
                ticker_ka, year, attempt, retries, e, wait,
            )
            time.sleep(wait)
        except (json.JSONDecodeError, ValueError, OSError) as e:
            last_error = e
            wait = backoff
            log.warning(
                "%s year=%d attempt=%d/%d parse error: %s (retry in %.1fs)",
                ticker_ka, year, attempt, retries, e, wait,
            )
            time.sleep(wait)
        except Exception as e:
            last_error = e
            log.warning(
                "%s year=%d attempt=%d/%d unexpected: %s",
                ticker_ka, year, attempt, retries, e,
            )
            break

    log.error("%s year=%d failed after %d attempts: %s", ticker_ka, year, retries, last_error)
    return [], 0.0


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def parse_yahoo_date(ts: Any) -> date:
    try:
        return datetime.utcfromtimestamp(int(ts)).date()
    except (TypeError, ValueError, OSError):
        raise ValueError(f"unparseable yahoo timestamp: {ts!r}")


def validate_yahoo_row(ticker: str, row: Dict[str, Any]) -> Optional[DailyBar]:
    """Return a validated DailyBar or None on a bad row; quarantine the bad row."""
    try:
        ts = row.get("ts")
        if ts is None:
            _quarantine_row(ticker, row, "missing ts")
            return None
        dt = parse_yahoo_date(ts)

        opens = row.get("open")
        highs = row.get("high")
        lows = row.get("low")
        closes = row.get("close")

        def _at(arr, i):
            v = arr[i] if isinstance(arr, list) and i < len(arr) else None
            return float(v) if v is not None else None

        o = _at(opens, 0) if isinstance(opens, list) else None
        h = _at(highs, 0) if isinstance(highs, list) else None
        l = _at(lows, 0) if isinstance(lows, list) else None
        c = _at(closes, 0) if isinstance(closes, list) else None

        # Yahoo can return literal nulls for halted days. Quarantine those.
        if o is None or h is None or l is None or c is None:
            _quarantine_row(ticker, row, "null OHLC")
            return None
        if c <= 0 or h <= 0 or l <= 0 or o <= 0:
            _quarantine_row(ticker, row, "non-positive OHLC")
            return None
        if h < l:
            _quarantine_row(ticker, row, "high < low")
            return None
        if h < max(o, c):
            _quarantine_row(ticker, row, "high below open/close")
            return None
        if l > min(o, c):
            _quarantine_row(ticker, row, "low above open/close")
            return None

        volume_row = row.get("volume")
        volume = int(volume_row) if isinstance(volume_row, (int, float)) and volume_row is not None else 0
        if volume < 0:
            volume = 0

        return DailyBar(
            ticker=ticker,
            trade_date=dt,
            open_price=round(o, 2),
            high_price=round(h, 2),
            low_price=round(l, 2),
            close_price=round(c, 2),
            volume=volume,
        )
    except Exception as e:
        _quarantine_row(ticker, row, f"validation error: {e}")
        return None


# ---------------------------------------------------------------------------
# Span coverage check
# ---------------------------------------------------------------------------


def stored_span_for_ticker(db_path: str, ticker: str) -> Tuple[Optional[date], Optional[date], int]:
    """Return (first_date, last_date, count) for a ticker in the store, or None."""
    try:
        conn = sqlite3.connect(db_path, timeout=20.0)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        row = cur.execute(
            "SELECT MIN(date) AS first, MAX(date) AS last, COUNT(*) AS cnt "
            "FROM daily_eod WHERE ticker = ?",
            (ticker,),
        ).fetchone()
        conn.close()
        if not row or row["cnt"] == 0:
            return None, None, 0
        first = datetime.strptime(row["first"].strip(), "%Y-%m-%d").date()
        last = datetime.strptime(row["last"].strip(), "%Y-%m-%d").date()
        return first, last, int(row["cnt"])
    except sqlite3.Error as e:
        log.warning("could not inspect stored span for %s: %s", ticker, e)
        return None, None, 0


def needs_fetch(
    db_path: str,
    ticker: str,
    target_years: float,
    force: bool,
) -> bool:
    """True when a ticker still lacks the target lookback."""
    first, last, count = stored_span_for_ticker(db_path, ticker)
    if force:
        return True
    if first is None or last is None:
        return True
    span_years = calendar_years_span(first, last)
    return span_years < target_years or count < MIN_BARS_FOR_YEARS * target_years


# ---------------------------------------------------------------------------
# Core backfill orchestration
# ---------------------------------------------------------------------------


@dataclass
class BackfillStats:
    tickers_attempted: int = 0
    tickers_skipped: int = 0
    rows_inserted: int = 0
    rows_rejected: int = 0
    years_covered: List[Tuple[str, float]] = field(default_factory=list)
    failed_tickers: List[str] = field(default_factory=list)
    quarantine_file: Path = QUARANTINE_LOG


def deep_backfill(
    db_path: str,
    target_years: float,
    force: bool = False,
    years: Optional[List[int]] = None,
    tickers: Optional[List[str]] = None,
    max_parallel: int = 1,
) -> BackfillStats:
    """Top-level backfill orchestration.

    * target_years — desired lookback per ticker (10-15 recommended).
    * years — explicit calendar years to fetch; when None, infer from the
      earliest stored date so we only fetch the missing tail.
    * tickers — restrict to a subset; None means the core universe.
    * max_parallel — thread count for IO-bound fetches; kept at 1 by default
      because the upstream endpoint is rate-limited and polite cadence matters
      more than wall-clock here.
    """
    import threading

    stats = BackfillStats()
    universe = [t.strip().upper() for t in (tickers or TARGET_TICKERS)]
    target_span = target_years

    # Determine which calendar years we actually need to touch.
    if years is None:
        years = _default_year_range(db_path, universe, target_span)
    else:
        years = sorted(int(y) for y in years)

    log.info(
        "deep backfill: %d tickers · %d calendar years (%.1f target lookback) · force=%s",
        len(universe), len(years), target_span, force,
    )

    # Backfill in two phases so a single deep ingestion does not hammer the
    # endpoint with all tickers at once. Phase 1: fetch. Phase 2: write.
    write_manager = WALIngestionManager(db_path)

    fetch_results: List[Tuple[str, List[DailyBar], List[Dict[str, Any]]]] = []
    fetch_lock = threading.Lock()

    def _fetch_one(ticker: str) -> None:
        ticker_ka = f"{ticker}.KA"
        collected: List[DailyBar] = []
        raws: List[Dict[str, Any]] = []
        estimated_span = 0.0
        for year in years:
            if not needs_fetch(db_path, ticker, target_span, force):
                # Tail-enough already; skip remaining years for this ticker.
                break
            raw_rows, span = fetch_yahoo_span(ticker_ka, year)
            if raw_rows:
                estimated_span = max(estimated_span, span)
                for raw in raw_rows:
                    bar = validate_yahoo_row(ticker, raw)
                    if bar is not None:
                        collected.append(bar)
                    else:
                        stats.rows_rejected += 1
            time.sleep(0.25)  # polite cadence to the upstream endpoint
        with fetch_lock:
            if collected or stats.failed_tickers:
                fetch_results.append((ticker, collected, raws))
                stats.years_covered.append((ticker, estimated_span))

    threads: List[threading.Thread] = []
    for ticker in universe:
        if not needs_fetch(db_path, ticker, target_span, force):
            stats.tickers_skipped += 1
            continue
        stats.tickers_attempted += 1
        t = threading.Thread(target=_fetch_one, args=(ticker,), daemon=True)
        threads.append(t)
        t.start()
        if max_parallel > 1:
            # Keep a bounded degree of parallelism even when many threads are
            # spawned; otherwise the upstream endpoint rate-limits us.
            while len([wt for wt in threads if wt.is_alive()]) >= max_parallel:
                time.sleep(0.5)

    for t in threads:
        t.join(timeout=600)

    # Persist whatever we fetched.
    for ticker, bars, _raws in fetch_results:
        if not bars:
            if ticker not in stats.failed_tickers:
                stats.failed_tickers.append(ticker)
            continue
        inserted, quarantined = write_manager.upsert_bars(bars)
        stats.rows_inserted += inserted
        stats.rows_rejected += quarantined
        log.info("%s: upserted %d bars (quarantined %d)", ticker, inserted, quarantined)

    return stats


def _default_year_range(db_path: str, tickers: List[str], target_years: float) -> List[int]:
    """Infer the earliest needed calendar year from the worst-covered ticker."""
    min_first: Optional[date] = None
    for ticker in tickers:
        first, *_ = stored_span_for_ticker(db_path, ticker)
        if first is None:
            # No stored history for this ticker at all; assume we want back to
            # ~2011 so the window is useful for stress testing.
            candidate = date(2011, 1, 1)
        else:
            target_start = first - timedelta(days=int(target_years * 365.25))
            candidate = target_start
        if min_first is None or candidate < min_first:
            min_first = candidate

    if min_first is None:
        min_first = date(2011, 1, 1)

    # Clamp to a sane lower bound; Yahoo's free endpoint is not a 1970 archive.
    lower = max(min_first.year, 2010)
    return list(range(lower, date.today().year + 2))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="10-15 year PSX EOD deep backfill into psx_history.db",
    )
    parser.add_argument(
        "--db",
        type=str,
        default=str(DEFAULT_DB),
        help="SQLite store path (default: backend/psx_history.db)",
    )
    parser.add_argument(
        "--years",
        type=float,
        default=15.0,
        help="target lookback in years per ticker (default: 15)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="re-fetch every ticker even if it already has enough history",
    )
    parser.add_argument(
        "--years-list",
        nargs="+",
        type=int,
        default=None,
        help="explicit calendar years to fetch (default: infer from missing tail)",
    )
    parser.add_argument(
        "--tickers",
        nargs="+",
        default=None,
        help="restrict to a sub-universe (default: core universe)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="concurrent fetch threads (default: 1, polite to the upstream endpoint)",
    )
    args = parser.parse_args()

    db_path = args.db
    target_years = max(1.0, args.years)
    years = args.years_list
    tickers = args.tickers
    force = args.force
    workers = max(1, args.workers)

    start = datetime.now()
    stats = deep_backfill(db_path, target_years, force=force, years=years, tickers=tickers, max_parallel=workers)
    elapsed = (datetime.now() - start).total_seconds()

    log.info("=".join([""] + ["-"] * 60 + [""]))
    log.info("DEEP BACKFILL SUMMARY")
    log.info("  target lookback      : %.1f years", target_years)
    log.info("  tickers in universe  : %d", len(TARGET_TICKERS) if args.tickers is None else len(tickers))
    log.info("  tickers attempted    : %d", stats.tickers_attempted)
    log.info("  tickers skipped      : %d", stats.tickers_skipped)
    log.info("  rows inserted        : %d", stats.rows_inserted)
    log.info("  rows quarantined     : %d", stats.rows_rejected)
    if stats.failed_tickers:
        log.info("  failed tickers       : %s", ", ".join(stats.failed_tickers))
    spans = [s for _, s in stats.years_covered if s > 0]
    if spans:
        log.info(
            "  estimated coverage   : min %.2f / max %.2f / avg %.2f years",
            min(spans), max(spans), sum(spans) / len(spans),
        )
    log.info("  wall clock           : %.1fs", elapsed)
    log.info("  quarantine log       : %s", stats.quarantine_file)
    log.info("=".join([""] + ["-"] * 60 + [""]))

    return 0


if __name__ == "__main__":
    sys.exit(main())
