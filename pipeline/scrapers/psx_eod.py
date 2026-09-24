"""PSX end-of-day scraper.

Source chain (verified live 2026-09-25):

1. www.psx.com.pk/market-summary       PRIMARY. One static page holding the
   full listed universe (~570 rows) as sector tables with columns
   SCRIP/LDCP/OPEN/HIGH/LOW/CURRENT/CHANGE/VOLUME. The symbol lives in the
   first cell's ``data-srip`` attribute (PSX's own attribute typo - not a
   typo on our side). The page carries an <h4>YYYY-MM-DD HH:MM:SS</h4>
   snapshot stamp and an exchange status row (Open/Closed/Pre-Open).

2. dps.psx.com.pk/market-watch         FALLBACK. The legacy server-rendered
   snapshot (11 columns, ``data-order`` machine numbers). Verified returning
   404 with browser headers / 403-empty with AJAX headers as of 2026-09-25 -
   the route is gone from the DPS navigation - so this tier usually no-ops,
   but it is kept as a cheap first try in case the block is transient.

Session-date semantics (important): the market-summary <h4> stamp is the
page GENERATION time, not the session date. A "2026-09-25 03:05:01 Closed"
page holds the *previous* session's finalized data (Thursday 09-24).
``_infer_session_date`` therefore maps the stamp to the session the data
belongs to: pre-open stamps (< 09:15) and weekend stamps walk back to the
last weekday. Requested-vs-served mismatches are guarded in the CLI.

3. dps.psx.com.pk/timeseries/eod/<SYM> LAST RESORT (per-symbol). JSON rows
   ``[epoch, close, volume, ldcp]``. Verified 404ing per-symbol as of
   2026-09-25, so it is only exercised when both table sources fail and
   only for a bounded symbol list.

Historical notes kept for the audit trail:
- dps /historical POST is gated by reCAPTCHA (403 empty) - unusable for
  automation.
- ``fetch_historical_month`` / ``fetch_timeseries_close`` remain as
  utilities for the ``backfill_history`` indicator window filler.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, time as dtime, timedelta
from typing import Any, Optional

import requests
from bs4 import BeautifulSoup

from pipeline.http_client import ajax_headers, http_get, http_post

LOGGER = logging.getLogger(__name__)

BASE_URL = "https://dps.psx.com.pk"
WWW_BASE_URL = "https://www.psx.com.pk"
MARKET_WATCH_URL = f"{BASE_URL}/market-watch"
WWW_MARKET_SUMMARY_URL = f"{WWW_BASE_URL}/market-summary"
HISTORICAL_URL = f"{BASE_URL}/historical"
TIMESERIES_URL = f"{BASE_URL}/timeseries/eod"

_MAX_BACKFILL_MONTHS = 3
# PSX pre-open begins 09:15 PKT; a stamp earlier than this means the page
# was generated before the session opened and shows the PREVIOUS session.
_SESSION_OPEN_TIME = dtime(9, 15)
# Session cells may legitimately be "-" (no trade) but a volume cell that
# fails numeric parsing means the row layout changed - that one is counted.
_NUM_RE = re.compile(r"^-?[\d,]+(?:\.\d+)?$")
_SYM_RE = re.compile(r"^[A-Z][A-Z0-9\-]{1,19}$")
_TS_RE = re.compile(r"(20\d{2}-\d{2}-\d{2})")

UserFacingError = RuntimeError


def _num(cell_text: str) -> Optional[float]:
    """Parse a display number like '1,234.50' or '-0.35'; '-' -> None."""
    text = (cell_text or "").strip().replace(",", "")
    if not text or text in {"-", "--"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _market_summary_headers() -> dict[str, str]:
    """Headers that look like a real browser hitting the main PSX site."""
    return {
        "Referer": f"{WWW_BASE_URL}/",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }


def _infer_session_date(stamp: Optional[datetime]) -> Optional[date]:
    """Map a market-summary generation stamp to the session it holds.

    - Stamp before 09:15 (pre-open) or on a weekend: the data shown is the
      last COMPLETED weekday session -> walk back to the previous weekday.
    - Otherwise (live or post-close stamp): the data is that day's session.
    """
    if stamp is None:
        return None
    day = stamp.date()
    if day.weekday() >= 5 or stamp.time() < _SESSION_OPEN_TIME:
        day -= timedelta(days=1)
        while day.weekday() >= 5:
            day -= timedelta(days=1)
    return day


def _parse_market_summary(html: str) -> dict[str, Any]:
    """Parse the www.psx.com.pk market-summary page.

    Returns ``{"records": [...], "snapshot_at": date|None, "status": str|None,
    "rows_seen": int, "rows_skipped": int, "skip_reasons": Counter-dict}``.
    Raises UserFacingError only for structural failures (no table at all).
    """
    soup = BeautifulSoup(html, "html.parser")

    snapshot_dt: Optional[datetime] = None
    for h4 in soup.find_all("h4"):
        match = re.search(
            r"(20\d{2}-\d{2}-\d{2})[ T](\d{2}:\d{2}(?::\d{2})?)",
            h4.get_text(" ", strip=True),
        )
        if match:
            try:
                stamp = datetime.fromisoformat(
                    f"{match.group(1)} {match.group(2)}"
                )
            except ValueError:
                continue
            if snapshot_dt is None or stamp > snapshot_dt:
                snapshot_dt = stamp

    session_date = _infer_session_date(snapshot_dt)

    status: Optional[str] = None
    for tr in soup.find_all("tr"):
        text = tr.get_text(" ", strip=True)
        if "Status:" in text:
            match = re.search(
                r"Status:\s*(Open|Closed|Pre-Open|Pre\s*Open)", text, re.I
            )
            if match:
                status = match.group(1).replace(" ", "-").title()
                break

    records: list[dict] = []
    seen: set[str] = set()
    reasons: dict[str, int] = {"no-symbol": 0, "bad-close": 0, "dupe": 0,
                               "bad-volume": 0}
    rows_seen = 0

    for tr in soup.find_all("tr"):
        cells = tr.find_all("td")
        if len(cells) != 8:  # header (th-only), sector banner (1), junk
            continue
        first = cells[0]
        symbol = (first.get("data-srip") or "").strip().upper()
        if not symbol:
            # fallback: symbol as visible text of the first cell
            symbol = first.get_text(strip=True).upper()
        if not _SYM_RE.match(symbol):
            reasons["no-symbol"] += 1
            continue
        rows_seen += 1
        # Columns: SCRIP | LDCP | OPEN | HIGH | LOW | CURRENT | CHANGE | VOLUME
        ldcp, open_price, high_price, low_price, close_price, _chg, volume = (
            _num(c.get_text(strip=True)) for c in cells[1:]
        )

        if close_price is None or close_price <= 0:
            reasons["bad-close"] += 1
            continue
        if symbol in seen:
            reasons["dupe"] += 1
            continue
        seen.add(symbol)

        volume_int: Optional[int] = None
        if volume is not None and volume >= 0:
            volume_int = int(round(volume))
        elif volume is None:
            volume_int = None
        else:
            reasons["bad-volume"] += 1
            volume_int = None

        trade_date = (
            session_date.isoformat() if session_date else date.today().isoformat()
        )
        records.append(
            {
                "trade_date": trade_date,
                "ticker": symbol,
                "open_price": open_price,
                "high_price": high_price,
                "low_price": low_price,
                "close_price": round(close_price, 2),
                "volume": volume_int,
            }
        )

    if rows_seen == 0:
        raise UserFacingError(
            "market-summary served no ticker rows (layout change or WAF page)"
        )
    return {
        "records": records,
        "snapshot_at": snapshot_dt,
        "session_date": session_date,
        "status": status,
        "rows_seen": rows_seen,
        "rows_skipped": sum(reasons.values()),
        "skip_reasons": reasons,
    }


def fetch_market_snapshot(trade_date: Optional[date] = None) -> list[dict]:
    """Scrape the full server-rendered market-watch table for one date.

    ``trade_date`` is used purely for labelling (PSX serves the latest
    session); callers pass the day being processed.
    """
    response = http_get(MARKET_WATCH_URL, headers=ajax_headers(BASE_URL + "/"))
    soup = BeautifulSoup(response.text, "html.parser")
    table = soup.find("table", class_="tbl")
    if table is None:
        raise ValueError("market-watch page did not contain the market table")

    tbody = table.find("tbody")
    if tbody is None:
        raise ValueError("market-watch table has no tbody")

    records: list[dict] = []
    seen: set[str] = set()
    for tr in tbody.find_all("tr"):
        record = _row_to_record(tr, trade_date or date.today())
        if record and record["ticker"] not in seen:
            seen.add(record["ticker"])
            records.append(record)

    if not records:
        raise ValueError("market-watch table parsed to zero rows")
    LOGGER.info("market-watch: parsed %d tickers", len(records))
    return records


def fetch_www_market_summary(expected_date: Optional[date] = None) -> list[dict]:
    """PRIMARY source: the main-site full-universe snapshot.

    - Serves the latest published session; an explicit ``expected_date``
      mismatch degrades to a WARNING, not a hard stop (the caller decides
      whether the data is usable).
    - Raises UserFacingError on structural failure so the source chain can
      fall through.
    """
    try:
        response = http_get(
            WWW_MARKET_SUMMARY_URL, headers=_market_summary_headers()
        )
    except Exception as exc:  # noqa: BLE001 - degrade to next tier
        raise UserFacingError(f"www market-summary GET failed: {exc}") from exc

    try:
        result = _parse_market_summary(response.text)
    except UserFacingError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise UserFacingError(f"www market-summary parse failed: {exc}") from exc

    records: list[dict] = result["records"]
    session = result["session_date"]
    if expected_date is not None and session is not None and session != expected_date:
        LOGGER.warning(
            "www market-summary holds session %s but %s was requested "
            "(page serves the latest published session only)",
            session,
            expected_date,
        )
    LOGGER.info(
        "www market-summary: %d tickers (rows=%d skipped=%d status=%s "
        "stamp=%s session=%s) skip-reasons=%s",
        len(records),
        result["rows_seen"],
        result["rows_skipped"],
        result["status"],
        result["snapshot_at"],
        session,
        result["skip_reasons"],
    )
    return records


# ---------------------------------------------------------------------------
# Legacy DPS sources (fallbacks / utilities)
# ---------------------------------------------------------------------------


def _cell_number(cell) -> Optional[float]:
    """Read the numeric value of a table cell via its data-order attr."""
    if cell is None:
        return None
    raw = cell.get("data-order")
    if raw is None:
        return None
    try:
        return float(str(raw).replace(",", ""))
    except ValueError:
        return None


def _row_to_record(tr, trade_date: date) -> Optional[dict]:
    """Convert one market-watch <tr> into an EOD record (None to skip)."""
    tds = tr.find_all("td")
    if len(tds) < 11:
        return None

    symbol_cell = tds[0].find("a", class_="tbl__symbol")
    if symbol_cell is None:
        return None
    ticker = symbol_cell.get_text(strip=True).upper()
    if not ticker or len(ticker) > 20:
        return None

    # Columns: SYMBOL, SECTOR, LISTED-IN, LDCP, OPEN, HIGH, LOW, CLOSE,
    #          CHANGE, CHANGE%, VOLUME
    prev_close = _cell_number(tds[3])
    open_price = _cell_number(tds[4])
    high_price = _cell_number(tds[5])
    low_price = _cell_number(tds[6])
    close_price = _cell_number(tds[7])
    volume = _cell_number(tds[10])

    close_price = close_price if close_price is not None else prev_close
    if close_price is None or close_price <= 0:
        return None
    if open_price is not None and open_price <= 0:
        open_price = None

    volume_int: Optional[int] = None
    if volume is not None and volume >= 0:
        volume_int = int(round(volume))

    # Skip placeholder rows (e.g. 100-share bookkeeping entries) that PSX
    # renders with open=high=low=0 and no real turnover.
    if open_price in (None, 0) and high_price in (None, 0) and low_price in (None, 0):
        if volume_int is None or volume_int < 500:
            return None

    return {
        "trade_date": trade_date.isoformat(),
        "ticker": ticker,
        "open_price": open_price,
        "high_price": high_price,
        "low_price": low_price,
        "close_price": round(close_price, 2),
        "volume": volume_int,
    }


def fetch_historical_month(
    symbol: str, year: int, month: int
) -> list[dict]:
    """Fetch one symbol's monthly OHLCV table from the DPS historical API."""
    response = http_post(
        HISTORICAL_URL,
        data={"symbol": symbol, "month": str(month), "year": str(year)},
        headers=ajax_headers(f"{BASE_URL}/historical"),
    )
    soup = BeautifulSoup(response.text, "html.parser")
    records: list[dict] = []
    for tr in soup.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 5:
            continue
        epoch = tds[0].get("data-order")
        try:
            trade_date = datetime.utcfromtimestamp(int(str(epoch))).date()
        except (TypeError, ValueError):
            continue
        values = [_cell_number(td) for td in tds[1:5]]
        open_price, high_price, low_price, close_price = values
        volume = _cell_number(tds[5]) if len(tds) > 5 else None
        if close_price is None or close_price <= 0:
            continue
        records.append(
            {
                "trade_date": trade_date.isoformat(),
                "ticker": symbol.upper(),
                "open_price": open_price,
                "high_price": high_price,
                "low_price": low_price,
                "close_price": round(close_price, 2),
                "volume": int(round(volume)) if volume is not None else None,
            }
        )
    return records


def fetch_timeseries_close(symbol: str) -> list[dict]:
    """Fallback: DPS JSON timeseries ``[epoch, close, volume, ldcp]``."""
    response = http_get(
        f"{TIMESERIES_URL}/{requests.utils.quote(symbol)}",
        headers=ajax_headers(f"{BASE_URL}/historical"),
        timeout=20.0,
    )
    payload = response.json()
    rows = payload.get("data") or [] if isinstance(payload, dict) else []
    records: list[dict] = []
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 4:
            continue
        try:
            trade_date = datetime.utcfromtimestamp(int(row[0])).date()
            close_price = float(row[1])
            volume = int(round(float(row[2])))
        except (TypeError, ValueError):
            continue
        if close_price <= 0:
            continue
        records.append(
            {
                "trade_date": trade_date.isoformat(),
                "ticker": symbol.upper(),
                "open_price": None,
                "high_price": None,
                "low_price": None,
                "close_price": round(close_price, 2),
                "volume": volume,
            }
        )
    return records


def backfill_history(
    tickers: list[str],
    *,
    months: int = _MAX_BACKFILL_MONTHS,
    today: Optional[date] = None,
) -> list[dict]:
    """Backfill recent monthly history for a set of tickers.

    Used before the first full run so 20/50-day indicators have data. The
    historical POST accepts one symbol at a time, so this is inherently
    sequential; keep the ticker list short.
    """
    today = today or date.today()
    months_windows: list[tuple[int, int]] = []
    cursor = date(today.year, today.month, 1)
    for _ in range(months):
        months_windows.append((cursor.year, cursor.month))
        cursor = (cursor - timedelta(days=1)).replace(day=1)

    all_records: list[dict] = []
    for ticker in tickers:
        seen: dict[str, dict] = {}
        for year, month in months_windows:
            try:
                for record in fetch_historical_month(ticker, year, month):
                    seen[record["trade_date"]] = record
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning(
                    "historical backfill %s %04d-%02d failed: %s",
                    ticker,
                    year,
                    month,
                    exc,
                )
        if not seen:
            try:
                for record in fetch_timeseries_close(ticker):
                    seen[record["trade_date"]] = record
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("timeseries fallback %s failed: %s", ticker, exc)
        all_records.extend(seen.values())
        LOGGER.info("backfill %s: %d rows", ticker, len(seen))
    return all_records


def fetch_eod(trade_date: Optional[date] = None) -> list[dict]:
    """Public entry point: latest full-market EOD snapshot.

    Tries the primary source (www.psx.com.pk/market-summary) and falls back
    to the legacy DPS market-watch page, then per-symbol timeseries. Every
    failure is logged with its source name and exception - a total failure
    raises UserFacingError so the caller can warn instead of crash.
    """
    failures: list[str] = []

    # ---- Tier 1: www market-summary (full universe, static HTML) ----------
    try:
        records = fetch_www_market_summary(expected_date=trade_date)
        if records:
            return records
        failures.append("www market-summary: 0 rows parsed")
    except Exception as exc:  # noqa: BLE001
        failures.append(f"www market-summary: {exc}")
        LOGGER.warning("EOD tier-1 source failed: %s", exc)

    # ---- Tier 2: legacy DPS market-watch ----------------------------------
    try:
        records = fetch_market_snapshot(trade_date)
        if records:
            LOGGER.info("EOD recovered via legacy dps market-watch")
            return records
        failures.append("dps market-watch: 0 rows parsed")
    except Exception as exc:  # noqa: BLE001
        failures.append(f"dps market-watch: {exc}")
        LOGGER.warning("EOD tier-2 source failed: %s", exc)

    # ---- Tier 3: per-symbol DPS timeseries for known tickers --------------
    stored = _recent_tickers()
    if stored:
        LOGGER.warning(
            "EOD table sources exhausted; attempting per-symbol timeseries "
            "for %d stored tickers (this is slow and rate-limited)",
            len(stored),
        )
        merged: dict[str, dict] = {}
        latest = trade_date or date.today()
        for symbol in stored[:200]:  # bounded: this is a last resort
            try:
                for record in fetch_timeseries_close(symbol):
                    try:
                        record_date = date.fromisoformat(record["trade_date"])
                    except ValueError:
                        continue
                    if record_date > latest:
                        continue
                    merged.setdefault(record_date.isoformat(), {})[
                        record["ticker"]
                    ] = record
            except Exception as exc:  # noqa: BLE001
                failures.append(f"timeseries {symbol}: {exc}")
                continue
        # Return the best single session (the one closest to `trade_date`)
        for candidate in sorted(merged, reverse=True):
            if len(merged[candidate]) >= 100:
                LOGGER.info(
                    "EOD recovered via dps timeseries for session %s (%d tickers)",
                    candidate,
                    len(merged[candidate]),
                )
                return list(merged[candidate].values())

    raise UserFacingError(
        "all EOD sources failed: " + ("; ".join(failures) or "no attempts")
    )


def _recent_tickers() -> list[str]:
    """Tickers already stored in Supabase - bounds tier-3 fan-out.

    Soft dependency: returns [] when Supabase env is absent (unit tests,
    CLI --dry-run without credentials) so scraping still works offline.
    """
    try:
        from pipeline import db as _db

        response = (
            _db.get_client()
            .table("psx_daily_eod")
            .select("ticker")
            .order("trade_date", desc=True)
            .limit(2000)
            .execute()
        )
        tickers = sorted({row["ticker"] for row in response.data or []})
        return tickers
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("could not load stored tickers (tier-3 unbounded): %s", exc)
        return []


# ---------------------------------------------------------------------------
# CLI: one-command backfill
#
#   python -m pipeline.scrapers.psx_eod                       # latest session
#   python -m pipeline.scrapers.psx_eod --date 2026-09-24
#   python -m pipeline.scrapers.psx_eod --dry-run             # no DB writes
#
# Exit codes: 0 = rows written (or dry-run OK), 2 = scrape failed,
# 3 = date-integrity guard tripped (served session != requested).
# ---------------------------------------------------------------------------


def main(argv: Optional[list[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Scrape the latest PSX full-market EOD snapshot and "
        "upsert it into Supabase psx_daily_eod."
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Requested session date YYYY-MM-DD (advisory: the sources "
        "serve the latest published session).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scrape and report only; no Supabase writes.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Truncate to the first N parsed rows (diagnostics only).",
    )
    parser.add_argument(
        "--strict-date",
        action="store_true",
        help="Abort (exit 3) if the served session differs from --date "
        "instead of writing under the served date.",
    )
    parser.add_argument(
        "--min-rows",
        type=int,
        default=50,
        help="Refuse to write if fewer than this many rows parsed.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    requested = (
        date.fromisoformat(args.date)
        if args.date
        else None
    )

    try:
        records = fetch_eod(requested)
    except UserFacingError as exc:
        LOGGER.error("EOD scrape FAILED: %s", exc)
        return 2
    except Exception as exc:  # noqa: BLE001 - defensive: CLI must not traceback
        LOGGER.exception("EOD scrape crashed: %s", exc)
        return 2

    if args.limit and args.limit > 0:
        records = records[: args.limit]

    if not records:
        LOGGER.error("EOD scrape produced zero rows")
        return 2

    served = records[0]["trade_date"]
    stamp = served[:10]
    with_volume = sum(1 for r in records if (r.get("volume") or 0) > 0)
    LOGGER.info(
        "scrape OK: %d rows, served session %s, %d with volume "
        "(requested: %s)",
        len(records),
        stamp,
        with_volume,
        args.date or "latest",
    )

    # Date-integrity guards: never stamp a session under the wrong date.
    try:
        served_day = date.fromisoformat(stamp)
    except ValueError:
        LOGGER.error("unparseable served trade_date: %r", served)
        return 3
    if served_day.weekday() >= 5:
        LOGGER.error(
            "served session %s is a weekend stamp - refusing to write "
            "(restamped closed-day snapshot)",
            stamp,
        )
        return 3
    if requested is not None and served_day != requested:
        if args.strict_date:
            LOGGER.error(
                "strict-date guard: requested %s but sources serve %s "
                "- no rows written (the requested session may no longer "
                "be published)",
                requested,
                served_day,
            )
            return 3
        LOGGER.warning(
            "requested %s but sources serve %s - writing under the SERVED "
            "date (source of truth)",
            requested,
            served_day,
        )

    if with_volume < args.min_rows:
        LOGGER.error(
            "only %d rows carry volume (floor %d) - snapshot looks like a "
            "dead/closed-day page; nothing written",
            with_volume,
            args.min_rows,
        )
        return 3

    if args.dry_run:
        LOGGER.info("DRY RUN - no database writes. First 5 rows:")
        for row in records[:5]:
            LOGGER.info("  %s", row)
        LOGGER.info("DRY RUN - %d rows validated, all guards passed", len(records))
        return 0

    from pipeline import db as _db

    written = _db.upsert_records(
        "psx_daily_eod", records, on_conflict="trade_date,ticker"
    )
    LOGGER.info(
        "psx_daily_eod: %d/%d rows written for session %s",
        written,
        len(records),
        stamp,
    )
    if written == 0:
        LOGGER.error(
            "upsert wrote 0 rows - schema drift or permissions; apply "
            "migrations/002_psx_daily_eod_repair.sql"
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
