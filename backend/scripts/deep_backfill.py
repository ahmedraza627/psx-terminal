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
    [--single-span] [--universe core|extended|discovered|all] [--tickers ...]

--universe defaults to "all": the core 65 names, the wider static active PSX
list, and any symbols discovered live from the PSX data portal. A ticker that
the upstream endpoint does not carry (404) or that returns no valid OHLC is
recorded as failed and skipped, so a wide universe never breaks a run.

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
import re
import sqlite3
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from src.core.models import DailyBar  # noqa: E402
from src.ingestion.wal_adapter import WALIngestionManager  # noqa: E402
from src.ingestion.universe import CORE_TICKERS  # noqa: E402
from src.quant.sector_rotation import DEFAULT_SECTOR_MAP  # noqa: E402

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

# Wider active PSX equity universe: every name in the sector registry that the
# core book does not already hold (655 registry symbols across the 36 official
# PSX sectors). Deriving it from DEFAULT_SECTOR_MAP keeps the fetch list and the
# sector labels in one place, so a ticker can never be fetched without a sector
# or mapped without being fetched.
EXTENDED_TICKERS: List[str] = sorted(
    t for t in DEFAULT_SECTOR_MAP if t not in set(CORE_TICKERS)
)

# Live symbol discovery. PSX's data portal is the same source the daily market
# sync uses, so a discovered symbol is an actively quoted PSX name by
# construction. Discovery is best-effort: the static extended list above is the
# fallback when the portal is unreachable (offline runs, rate limits, outages).
DPS_MARKET_WATCH_URL = "https://dps.psx.com.pk/market-watch"
DISCOVERY_TIMEOUT_SECONDS = 15.0
_SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9]{1,9}$")
# Debt instruments, funds and rights/ETF lines share the symbol table but have
# no usable equity OHLC series, so they are dropped during discovery.
_NON_EQUITY_MARKERS = ("ETF", "TFC", "SUKUK", "FUND", "PREF", "RIGHT", "BOND")

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
        first_date = datetime.fromtimestamp(first_ts, timezone.utc).date()
        last_date = datetime.fromtimestamp(last_ts, timezone.utc).date()
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


def _rows_from_payload(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Flatten a Yahoo chart payload into raw per-session row dicts."""
    results = payload.get("chart", {}).get("result", [])
    if not results:
        return []
    data_obj = results[0]
    timestamps = data_obj.get("timestamp", [])
    indicators = data_obj.get("indicators", {}).get("quote", [{}])[0]
    opens = indicators.get("open") or []
    highs = indicators.get("high") or []
    lows = indicators.get("low") or []
    closes = indicators.get("close") or []
    volumes = indicators.get("volume") or []
    out: List[Dict[str, Any]] = []
    for i in range(len(timestamps)):
        out.append({
            "ts": timestamps[i],
            "open": opens[i] if i < len(opens) else None,
            "high": highs[i] if i < len(highs) else None,
            "low": lows[i] if i < len(lows) else None,
            "close": closes[i] if i < len(closes) else None,
            "volume": volumes[i] if i < len(volumes) else None,
        })
    return out


def _fetch_chart_payload(
    url: str,
    tag: str,
    retries: int = 4,
    backoff: float = 2.0,
) -> Optional[Dict[str, Any]]:
    """Fetch and decode one chart URL, retrying transient failures.

    A 404 / 401 / 403 is terminal for that symbol+span: a delisted or unknown
    ticker will never succeed, so retry backoff is not spent on it.
    """
    last_error: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            req = Request(url, headers={"User-Agent": USER_AGENT})
            with urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8", "replace"))
        except HTTPError as e:
            last_error = e
            if e.code in (401, 403, 404):
                log.info("%s terminal HTTP %s (skipping)", tag, e.code)
                return None
            wait = backoff ** attempt
            log.warning(
                "%s attempt=%d/%d HTTP %s (retry in %.1fs)",
                tag, attempt, retries, e.code, wait,
            )
            time.sleep(wait)
        except URLError as e:
            last_error = e
            wait = backoff ** attempt
            log.warning(
                "%s attempt=%d/%d url error: %s (retry in %.1fs)",
                tag, attempt, retries, e, wait,
            )
            time.sleep(wait)
        except (json.JSONDecodeError, ValueError, OSError) as e:
            last_error = e
            wait = backoff
            log.warning(
                "%s attempt=%d/%d parse error: %s (retry in %.1fs)",
                tag, attempt, retries, e, wait,
            )
            time.sleep(wait)
        except Exception as e:
            last_error = e
            log.warning("%s attempt=%d/%d unexpected: %s", tag, attempt, retries, e)
            break

    log.error("%s failed after %d attempts: %s", tag, retries, last_error)
    return None


def fetch_yahoo_span(
    ticker_ka: str,
    year: int,
    retries: int = 4,
    backoff: float = 2.0,
) -> Tuple[List[Dict[str, Any]], float]:
    """Fetch one calendar year of daily chart data for a .KA ticker.

    Returns (raw_rows, estimated_span_years). Empty on genuine failure after
    retries.
    """
    period1 = _epoch_for_year(year, 1, 1)
    # +1 year so January data is not clipped by a timezone-hesitant period2.
    period2 = _epoch_for_year(year + 1, 1, 1)
    payload = _fetch_chart_payload(
        _yahoo_url(ticker_ka, period1, period2), f"{ticker_ka} year={year}", retries, backoff
    )
    if payload is None:
        return [], 0.0
    return _rows_from_payload(payload), years_from_yahoo_span(payload)


def fetch_yahoo_range(
    ticker_ka: str,
    start_year: int,
    retries: int = 4,
    backoff: float = 2.0,
) -> Tuple[List[Dict[str, Any]], float]:
    """Fetch the whole start_year -> today span in a single request.

    Yahoo happily returns a decade-plus of daily bars per call, so this is both
    far fewer requests than year chunking and much less likely to trip the
    upstream rate limiter during a full-universe backfill.
    """
    period1 = _epoch_for_year(start_year, 1, 1)
    period2 = int(time.time())
    payload = _fetch_chart_payload(
        _yahoo_url(ticker_ka, period1, period2), f"{ticker_ka} span={start_year}+", retries, backoff
    )
    if payload is None:
        return [], 0.0
    return _rows_from_payload(payload), years_from_yahoo_span(payload)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def parse_yahoo_date(ts: Any) -> date:
    try:
        return datetime.fromtimestamp(int(ts), timezone.utc).date()
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

        # Rows arrive flattened (one scalar per field per session), but keep
        # tolerating the raw Yahoo per-field array shape for older callers.
        def _scalar(value: Any) -> Optional[float]:
            if isinstance(value, list):
                value = value[0] if value else None
            try:
                return float(value) if value is not None else None
            except (TypeError, ValueError):
                return None

        o = _scalar(row.get("open"))
        h = _scalar(row.get("high"))
        l = _scalar(row.get("low"))
        c = _scalar(row.get("close"))

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


def stored_spans(db_path: str) -> Dict[str, Tuple[date, date, int]]:
    """Every stored (first_date, last_date, count) in one grouped pass.

    The store has no (ticker, date) index, so asking per ticker turns a
    600-name universe check into 600 full scans of a multi-million row table.
    One GROUP BY keeps the pre-fetch check effectively free.
    """
    try:
        conn = sqlite3.connect(db_path, timeout=30.0)
        cur = conn.cursor()
        rows = cur.execute(
            "SELECT ticker, MIN(date) AS first, MAX(date) AS last, COUNT(*) AS cnt "
            "FROM daily_eod GROUP BY ticker"
        ).fetchall()
        conn.close()
    except sqlite3.Error as e:
        log.warning("could not read stored spans: %s", e)
        return {}
    out: Dict[str, Tuple[date, date, int]] = {}
    for ticker, first, last, cnt in rows:
        try:
            out[str(ticker).strip().upper()] = (
                datetime.strptime(str(first).strip(), "%Y-%m-%d").date(),
                datetime.strptime(str(last).strip(), "%Y-%m-%d").date(),
                int(cnt),
            )
        except (TypeError, ValueError):
            continue
    return out


def _span_is_enough(
    span: Optional[Tuple[date, date, int]],
    target_years: float,
) -> bool:
    if span is None:
        return False
    first, last, count = span
    return (
        calendar_years_span(first, last) >= target_years
        and count >= MIN_BARS_FOR_YEARS * target_years
    )


def discover_psx_universe(timeout: float = DISCOVERY_TIMEOUT_SECONDS) -> List[str]:
    """Best-effort live symbol discovery from the PSX data portal.

    Returns the actively quoted equity symbols found on the market-watch page,
    or an empty list when the portal cannot be reached. Callers fall back to the
    static extended universe, so a network problem never fails a backfill.
    """
    try:
        req = Request(DPS_MARKET_WATCH_URL, headers={"User-Agent": USER_AGENT})
        with urlopen(req, timeout=timeout) as resp:
            html = resp.read().decode("utf-8", "replace")
    except (HTTPError, URLError, TimeoutError, OSError) as e:
        log.warning("PSX symbol discovery unavailable (%s); using static universe", e)
        return []

    symbols = {
        m.group(1).upper()
        for m in re.finditer(r'data-srip="([A-Za-z][A-Za-z0-9]{0,9})"', html)
    }
    if not symbols:
        # Older portal layouts carry the symbol as the anchored row text.
        symbols = {
            m.group(1).upper()
            for m in re.finditer(r'class="tbl__symbol"[^>]*>\s*([A-Za-z][A-Za-z0-9]{0,9})\s*<', html)
        }

    equities = {
        s for s in symbols
        if _SYMBOL_RE.match(s) and not any(marker in s for marker in _NON_EQUITY_MARKERS)
    }
    if equities:
        log.info("PSX symbol discovery: %d equity symbols", len(equities))
    else:
        log.warning("PSX symbol discovery returned no symbols; using static universe")
    return sorted(equities)


def build_universe(mode: str = "all") -> List[str]:
    """Resolve the backfill universe for a discovery mode.

    core       - the original 65-name liquid book
    extended   - core + the wider static active PSX list
    discovered - core + live PSX symbols (static extended list on failure)
    all        - core + static extended + live discovered (default)
    """
    core = list(CORE_TICKERS)
    extended = list(EXTENDED_TICKERS)
    if mode == "core":
        return core
    if mode == "extended":
        return list(dict.fromkeys(core + extended))

    discovered = discover_psx_universe() if mode in ("discovered", "all") else []
    if mode == "discovered":
        if not discovered:
            log.warning("discovery failed; falling back to the static extended universe")
            return list(dict.fromkeys(core + extended))
        return list(dict.fromkeys(core + discovered))
    return list(dict.fromkeys(core + extended + discovered))


def needs_fetch(
    db_path: str,
    ticker: str,
    target_years: float,
    force: bool,
    spans: Optional[Dict[str, Tuple[date, date, int]]] = None,
) -> bool:
    """True when a ticker still lacks the target lookback.

    Pass a precomputed `spans` map (see stored_spans) when checking a whole
    universe so the store is read once instead of once per ticker.
    """
    if force:
        return True
    if spans is not None:
        return not _span_is_enough(spans.get(ticker.strip().upper()), target_years)
    first, last, count = stored_span_for_ticker(db_path, ticker)
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
    single_span: bool = False,
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
    stats = BackfillStats()
    universe = [t.strip().upper() for t in (tickers or TARGET_TICKERS)]
    target_span = target_years

    # One read of the store's per-ticker coverage, reused for the year range
    # and for the needs-fetch decisions.
    spans = stored_spans(db_path)

    # Determine which calendar years we actually need to touch.
    if years is None:
        years = _default_year_range(db_path, universe, target_span, spans)
    else:
        years = sorted(int(y) for y in years)

    log.info(
        "deep backfill: %d tickers · %d calendar years (%.1f target lookback) · force=%s",
        len(universe), len(years), target_span, force,
    )

    # Fetch and persist one ticker at a time, with only `max_parallel` fetches
    # in flight. Writing each ticker as it lands keeps peak memory flat across a
    # 600+ name universe; buffering every name's bars until the end would grow
    # into the gigabytes. A single failed ticker never aborts the run.
    write_manager = WALIngestionManager(db_path)

    def _collect(ticker: str, raw_rows: List[Dict[str, Any]], collected: List[DailyBar]) -> None:
        for raw in raw_rows:
            bar = validate_yahoo_row(ticker, raw)
            if bar is not None:
                collected.append(bar)
            else:
                stats.rows_rejected += 1

    def _fetch_bars(ticker: str) -> Tuple[List[DailyBar], float]:
        ticker_ka = f"{ticker}.KA"
        collected: List[DailyBar] = []
        estimated_span = 0.0
        if single_span:
            raw_rows, span = fetch_yahoo_range(ticker_ka, years[0])
            if raw_rows:
                estimated_span = span
                _collect(ticker, raw_rows, collected)
            time.sleep(0.25)  # polite cadence to the upstream endpoint
        else:
            for year in years:
                if not needs_fetch(db_path, ticker, target_span, force, spans):
                    # Tail-enough already; skip remaining years for this ticker.
                    break
                raw_rows, span = fetch_yahoo_span(ticker_ka, year)
                if raw_rows:
                    estimated_span = max(estimated_span, span)
                    _collect(ticker, raw_rows, collected)
                time.sleep(0.25)  # polite cadence to the upstream endpoint
        return collected, estimated_span

    pending = [t for t in universe if needs_fetch(db_path, t, target_span, force, spans)]
    stats.tickers_skipped = len(universe) - len(pending)
    stats.tickers_attempted = len(pending)

    with ThreadPoolExecutor(max_workers=max_parallel) as pool:
        futures = {pool.submit(_fetch_bars, ticker): ticker for ticker in pending}
        for future in as_completed(futures):
            ticker = futures[future]
            try:
                bars, span = future.result()
            except Exception as e:  # noqa: BLE001 - one bad name must not stop the run
                log.warning("%s fetch raised: %s (skipped)", ticker, e)
                stats.failed_tickers.append(ticker)
                continue
            stats.years_covered.append((ticker, span))
            if not bars:
                stats.failed_tickers.append(ticker)
                continue
            inserted, quarantined = write_manager.upsert_bars(bars)
            stats.rows_inserted += inserted
            stats.rows_rejected += quarantined
            log.info("%s: upserted %d bars (quarantined %d)", ticker, inserted, quarantined)

    return stats


def _default_year_range(
    db_path: str,
    tickers: List[str],
    target_years: float,
    spans: Optional[Dict[str, Tuple[date, date, int]]] = None,
) -> List[int]:
    """Infer the earliest needed calendar year from the worst-covered ticker."""
    spans = spans if spans is not None else stored_spans(db_path)
    min_first: Optional[date] = None
    for ticker in tickers:
        first = (spans.get(ticker.strip().upper()) or (None, None, 0))[0]
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
    # Never walk into future calendar years: Yahoo has no data there and the
    # retries only waste the run's quota.
    return list(range(lower, date.today().year + 1))


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
        help="restrict to an explicit sub-universe (overrides --universe)",
    )
    parser.add_argument(
        "--universe",
        type=str,
        default="all",
        choices=["core", "extended", "discovered", "all"],
        help=(
            "core = original 65 names, extended = core + static wider PSX list, "
            "discovered = core + live PSX symbols, all = extended + discovered (default)"
        ),
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="concurrent fetch threads (default: 1, polite to the upstream endpoint)",
    )
    parser.add_argument(
        "--single-span",
        action="store_true",
        help="fetch the whole lookback in one request per ticker instead of year chunks",
    )
    args = parser.parse_args()

    db_path = args.db
    target_years = max(1.0, args.years)
    years = args.years_list
    tickers = args.tickers if args.tickers else build_universe(args.universe)
    force = args.force
    workers = max(1, args.workers)

    start = datetime.now()
    stats = deep_backfill(
        db_path,
        target_years,
        force=force,
        years=years,
        tickers=tickers,
        max_parallel=workers,
        single_span=args.single_span,
    )
    elapsed = (datetime.now() - start).total_seconds()

    log.info("=".join([""] + ["-"] * 60 + [""]))
    log.info("DEEP BACKFILL SUMMARY")
    log.info("  target lookback      : %.1f years", target_years)
    log.info("  tickers in universe  : %d (%s)", len(tickers), "explicit" if args.tickers else args.universe)
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
