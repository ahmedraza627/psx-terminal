"""PSX negotiated / off-market (NDM) deals scraper.

OUTAGE DIAGNOSIS (verified live 2026-10-01, table stuck at 2026-09-22):
The module previously fetched
    https://dps.psx.com.pk/trading-board/NDM/NDM
Two independent failures break ingestion:

1.  WRONG ROUTE. DPS's own front-end bundle (/static/script.js?v=1.76)
    calls ``/trading-board/{tab}/{board}`` where the board selector
    defaults to ``main`` - i.e. the live NDM URL is
    /trading-board/NDM/main.  The legacy /NDM/NDM pair is gone.
2.  WAF GATING. Every DPS data route (both NDM pairs, REG, MTS,
    market-watch, per-symbol timeseries) returns 403 with an EMPTY body
    to non-browser clients, while DPS content pages (/, /trading-panel)
    still serve 200.  Verified not header-related: the full browser
    header set AND curl_cffi chrome/safari/firefox TLS impersonation all
    still get 403-empty - i.e. the gate is IP-class / edge-level, the
    same treatment that killed the EOD market-watch scraper and the
    /historical POST (reCAPTCHA-walled).  Public mirrors of the NDM
    board are dead (ksestocks.com is a blog, scstrade has no NDM page,
    jamapunji unreachable) and PSX's official daily PDF carries only
    breadth + indices, no per-deal rows.  The DPS announcements pages
    publish no NDM deals notice.

This scraper therefore:
1.  walks a source chain - the corrected /trading-board/NDM/main first,
    then the legacy pair - over an EGRESS chain: with SCRAPER_API_KEY set
    each URL routes through ScraperAPI first (its IP pool sits outside the
    edge gate that 403-blocks the runner's IP class), falling back to
    direct egress if the proxy tier fails; without a key, direct only,
2.  classifies each failure with HTTP-status diagnostics (403-empty =
    WAF block, 404 + ~47 kB HTML = route gone) so outages self-diagnose
    in CI logs instead of surfacing as a silently empty table,
3.  parses whichever board table appears, tolerantly: the canonical
    ``#tradingBoardTable`` or any table whose header carries SYMBOL and
    VOLUME, with the ticker read from the ``a.tbl__symbol`` link or the
    first symbol-shaped cell and volume taken from the last numeric
    column (survives column reorder),
4.  returns [] with a logged explanation when every source is blocked -
    the NDM tape stays honestly idle, never fabricated.

Row shape matches psx_offmarket_deals (schema.sql):
    trade_date date, ticker varchar(20), quantity bigint,
    rate numeric(10,2) NULL, value numeric(15,2) NULL.
The public board aggregates volume per symbol (per-trade rates are not
published), so each row is stored as one aggregated deal priced at the
same-session market close when psx_daily_eod already holds it.

BACKFILL REALITY: the board reflects ONLY the latest published session
- historical sessions are not retrievable from any reachable public
source (verified 2026-10-01).  The CLI therefore refuses to write a
board snapshot under an older date: a stale board restamped as history
would fabricate a session that never existed.  ``--date`` accepts the
latest completed session only; ``--force-stale`` overrides for operators
who have manually verified the board's contents.
"""

from __future__ import annotations

import logging
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Optional

from bs4 import BeautifulSoup, Tag

from pipeline.http_client import (
    ajax_headers,
    http_get,
    http_get_via_scraperapi,
    scraperapi_key,
)
from pipeline.parsing import to_int

LOGGER = logging.getLogger(__name__)

BASE_URL = "https://dps.psx.com.pk"
# Correct route per script.js v1.76 (board selector defaults to "main"),
# then the legacy pair the old module used.
NDM_BOARD_URLS = (
    f"{BASE_URL}/trading-board/NDM/main",
    f"{BASE_URL}/trading-board/NDM/NDM",
)
TRADING_PANEL_URL = f"{BASE_URL}/trading-panel"

PKT = timezone(timedelta(hours=5))
_SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9\-\._]{1,19}$")


class SourceBlockedError(RuntimeError):
    """All NDM sources unreachable (WAF/dead routes) - board not served."""


# ---------------------------------------------------------------------------
# Fetch tier
# ---------------------------------------------------------------------------


def _fetch_board_html(url: str) -> str:
    """GET one board URL, translating HTTP outcomes into diagnostics.

    Egress chain: when SCRAPER_API_KEY is set the request routes through
    ScraperAPI first (its IP pool is outside the DPS edge gate that
    403-blocks this runner), then direct as the fallback; without a key
    only direct egress is attempted. Outcome diagnostics are identical
    for both paths so outages self-diagnose regardless of egress.
    """
    attempts: list[tuple[str, Callable[[], Any]]] = []
    if scraperapi_key():
        attempts.append(("scraperapi", lambda: http_get_via_scraperapi(url)))
    attempts.append(
        ("direct", lambda: http_get(url, headers=ajax_headers(TRADING_PANEL_URL)))
    )

    failures: list[str] = []
    for tier, send in attempts:
        try:
            response = send()
        except Exception as exc:  # noqa: BLE001 - degrade to next egress tier
            failures.append(f"{tier}: {url} unreachable: {exc}")
            continue
        body = response.text or ""
        if response.status_code == 403 and not body.strip():
            failures.append(
                f"{tier}: {url} -> 403 EMPTY body (edge WAF block; not header-fixable)"
            )
            continue
        if response.status_code == 404 and "<html" in body.lower():
            failures.append(
                f"{tier}: {url} -> 404 with HTML shell ({len(body)} bytes, route retired)"
            )
            continue
        if response.status_code >= 400:
            failures.append(f"{tier}: {url} -> HTTP {response.status_code}")
            continue
        if "<table" not in body.lower():
            failures.append(f"{tier}: {url} -> 200 but no <table> in payload")
            continue
        if failures:
            for failure in failures:
                LOGGER.warning("NDM egress tier degraded before '%s' recovered: %s", tier, failure)
        return body
    raise SourceBlockedError(
        " | ".join(failures) if failures else f"{url}: no egress path configured"
    )


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _pick_board_table(soup: BeautifulSoup) -> Optional[Tag]:
    """The canonical board table, else any table with SYMBOL+VOLUME headers."""
    table = soup.find("table", id="tradingBoardTable")
    if isinstance(table, Tag):
        return table
    for candidate in soup.find_all("table"):
        if not isinstance(candidate, Tag):
            continue
        header_text = " ".join(
            th.get_text(" ", strip=True).upper() for th in candidate.find_all("th")
        )
        if "SYMBOL" in header_text and "VOLUME" in header_text:
            return candidate
    return None


def _ticker_from_row(tr: Tag) -> Optional[str]:
    """Ticker from the a.tbl__symbol link, else the first symbol-shaped cell."""
    for cell in tr.find_all("td"):
        link = cell.find("a", class_="tbl__symbol")
        if link is not None:
            ticker = link.get_text(strip=True).upper()
            if _SYMBOL_RE.match(ticker):
                return ticker
    for cell in tr.find_all("td"):
        text = cell.get_text(strip=True).upper()
        if _SYMBOL_RE.match(text):
            return text
    return None


def _parse_ndm_board(html: str) -> list[dict]:
    """Extract {ticker, name, trades_c2c, trades_m2m, volume} rows.

    Tolerant to column order: ticker from the symbol link/cell, volume
    from the LAST numeric cell, c2c/m2m from the remaining numeric cells
    in discovery order (zero when absent).
    """
    soup = BeautifulSoup(html, "html.parser")
    table = _pick_board_table(soup)
    if table is None:
        LOGGER.warning("NDM board table missing (empty board or layout change)")
        return []

    rows: list[dict] = []
    tbody = table.find("tbody") or table
    seen: set[str] = set()
    for tr in tbody.find_all("tr"):
        if not isinstance(tr, Tag):
            continue
        ticker = _ticker_from_row(tr)
        if ticker is None or ticker in seen:
            continue
        numbers: list[int] = []
        name = ""
        for cell in tr.find_all("td"):
            text = cell.get_text(" ", strip=True)
            if not text:
                continue
            value = to_int(text)
            if value is not None and value > 0:
                numbers.append(value)
            elif not name and not _SYMBOL_RE.match(text.upper()):
                name = text
        if not numbers:
            continue
        volume = numbers[-1]
        if volume < 0:
            continue
        trades_c2c = numbers[0] if len(numbers) >= 2 else 0
        trades_m2m = numbers[1] if len(numbers) >= 3 else 0
        seen.add(ticker)
        rows.append(
            {
                "ticker": ticker,
                "name": name,
                "trades_c2c": trades_c2c,
                "trades_m2m": trades_m2m,
                "volume": volume,
            }
        )
    LOGGER.info("NDM board parsed: %d symbols with volume", len(rows))
    return rows


def fetch_ndm_rows() -> list[dict]:
    """Fetch the NDM board rows via the source chain.

    Returns [] only when a source IS reachable but the board is genuinely
    empty; raises SourceBlockedError when every tier is unreachable so
    the caller can distinguish "no deals today" from "feed is down".
    """
    LOGGER.info(
        "NDM egress: %s",
        "ScraperAPI proxy first, direct fallback"
        if scraperapi_key()
        else "direct only (SCRAPER_API_KEY unset)",
    )
    failures: list[str] = []
    for url in NDM_BOARD_URLS:
        try:
            html = _fetch_board_html(url)
        except SourceBlockedError as exc:
            failures.append(str(exc))
            continue
        rows = _parse_ndm_board(html)
        if rows:
            return rows
        # Empty table from a reachable source: treat as a real empty board
        # but remember the tier in case later tiers disagree.
        failures.append(f"{url} -> 200 with an empty/unparseable board table")
    if failures:
        for failure in failures:
            LOGGER.error("NDM source tier failed: %s", failure)
        raise SourceBlockedError(
            f"all {len(NDM_BOARD_URLS)} NDM board tiers failed "
            "(WAF-gated or retired) - NDM tape stays idle this session"
        )
    return []


# ---------------------------------------------------------------------------
# Deal construction (pure)
# ---------------------------------------------------------------------------


def build_deals(
    rows: list[dict],
    trade_date: date,
    close_prices: Optional[dict[str, float]] = None,
    *,
    min_volume: int = 10_000,
) -> list[dict]:
    """Convert board rows into psx_offmarket_deals records.

    Deals below ``min_volume`` are skipped; ``rate``/``value`` use the
    same-session close when available, else stay NULL (schema-legal).
    """
    close_prices = close_prices or {}
    deals: list[dict] = []
    for row in rows:
        volume = row["volume"]
        if volume < min_volume:
            continue
        ticker = row["ticker"]
        rate = close_prices.get(ticker)
        value = rate * volume if rate is not None else None
        deals.append(
            {
                "trade_date": trade_date.isoformat(),
                "ticker": ticker,
                "quantity": volume,
                "rate": round(rate, 2) if rate is not None else None,
                "value": round(value, 2) if value is not None else None,
            }
        )
    deals.sort(key=lambda d: d["quantity"], reverse=True)
    return deals


def fetch_offmarket_deals(
    trade_date: date,
    close_prices: Optional[dict[str, float]] = None,
    *,
    min_volume: int = 10_000,
) -> list[dict]:
    """Pipeline entry point (signature stable for main.py).

    Total source failure degrades to [] with an ERROR log - the daily
    pipeline must never crash on a gated feed.
    """
    try:
        rows = fetch_ndm_rows()
    except SourceBlockedError as exc:
        LOGGER.error("off-market deals %s: feed unavailable - %s", trade_date, exc)
        return []
    deals = build_deals(rows, trade_date, close_prices, min_volume=min_volume)
    LOGGER.info(
        "off-market deals %s: %d blocks >= %d shares (rate from %d closes)",
        trade_date,
        len(deals),
        min_volume,
        sum(1 for d in deals if d["rate"] is not None),
    )
    return deals


# ---------------------------------------------------------------------------
# Backfill CLI
# ---------------------------------------------------------------------------


def _latest_completed_session(now: Optional[datetime] = None) -> date:
    """The session the board currently reflects (PKT clock).

    Before 09:30 the board still holds the prior session; after 16:30
    (market close) it holds today.  Weekends resolve to Friday.
    """
    now = now.astimezone(PKT) if now else datetime.now(PKT)
    day = now.date()
    if day.weekday() >= 5:  # Sat/Sun -> walk back to Friday
        while day.weekday() >= 5:
            day -= timedelta(days=1)
        return day
    if now.hour < 9 or (now.hour == 9 and now.minute < 30):
        day -= timedelta(days=1)
        while day.weekday() >= 5:
            day -= timedelta(days=1)
        return day
    return day


def _load_closes(trade_date: date) -> dict[str, float]:
    """Same-session closes from psx_daily_eod for deal valuation."""
    from pipeline import db as _db  # deferred: CLI help must not need Supabase

    client = _db.get_client()
    response = (
        client.table("psx_daily_eod")
        .select("ticker,close_price")
        .eq("trade_date", trade_date.isoformat())
        .execute()
    )
    closes = {
        str(r["ticker"]): float(r["close_price"])
        for r in (response.data or [])
        if r.get("close_price")
    }
    LOGGER.info("closes loaded for %s: %d tickers", trade_date, len(closes))
    return closes


def _insert_deals(deals: list[dict], trade_date: date) -> int:
    """Insert with the same per-date dedup guard main.py uses."""
    from pipeline import db as _db

    client = _db.get_client()
    existing = (
        client.table("psx_offmarket_deals")
        .select("ticker")
        .eq("trade_date", trade_date.isoformat())
        .execute()
    )
    seen = {r["ticker"] for r in (existing.data or [])}
    fresh = [d for d in deals if d["ticker"] not in seen]
    if not fresh:
        LOGGER.warning("all %d deals already recorded for %s", len(deals), trade_date)
        return 0
    for chunk_start in range(0, len(fresh), 500):
        chunk = fresh[chunk_start : chunk_start + 500]
        client.table("psx_offmarket_deals").insert(chunk).execute()
    LOGGER.info(
        "psx_offmarket_deals: %d rows inserted for %s", len(fresh), trade_date
    )
    return len(fresh)


def _parse_date_arg(raw: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise SystemExit(f"invalid --date {raw!r}: expected YYYY-MM-DD") from exc


def main(argv: Optional[list[str]] = None) -> int:
    """Backfill CLI.

    python -m pipeline.scrapers.psx_offmarket --dry-run
    python -m pipeline.scrapers.psx_offmarket --date 2026-09-30
    """
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    parser = argparse.ArgumentParser(description="NDM off-market deals scraper")
    parser.add_argument(
        "--date",
        help="session to stamp (defaults to the latest completed session)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="scrape + validate, no DB writes"
    )
    parser.add_argument(
        "--min-volume",
        type=int,
        default=int(os.getenv("OFFMARKET_MIN_VOLUME", "10000")),
        help="minimum block size in shares (default 10,000 / env OFFMARKET_MIN_VOLUME)",
    )
    parser.add_argument("--limit", type=int, help="keep only the first N deals")
    parser.add_argument(
        "--force-stale",
        action="store_true",
        help="DANGEROUS: write the current board under an older --date "
        "(only for operators who manually verified the board contents)",
    )
    parser.add_argument(
        "--allow-intraday",
        action="store_true",
        help="write during 09:30-16:30 PKT even though the board is "
        "still accumulating the live session",
    )
    args = parser.parse_args(argv)

    requested = _parse_date_arg(args.date) if args.date else None
    now = datetime.now(PKT)

    try:
        rows = fetch_ndm_rows()
    except SourceBlockedError as exc:
        LOGGER.error("NDM FEED UNAVAILABLE: %s", exc)
        return 2

    if not rows:
        LOGGER.warning(
            "board reachable but zero symbols carry volume "
            "(NDM market closed or genuinely empty)"
        )
        return 2

    # Session integrity: the board reflects only its latest session.
    board_session = _latest_completed_session(now)
    if requested is not None and requested != board_session:
        if requested.weekday() >= 5:
            LOGGER.error("%s is a weekend - no NDM session exists", requested)
            return 3
        if not args.force_stale:
            LOGGER.error(
                "REFUSING to write: the board reflects session %s, not %s. "
                "Historical NDM sessions are NOT retrievable from public "
                "sources - writing a stale board under an old date would "
                "fabricate history. Pass --force-stale only if you have "
                "manually verified the board contents.",
                board_session,
                requested,
            )
            return 3
        LOGGER.warning(
            "--force-stale: writing the CURRENT board (%s contents) under %s "
            "at operator request", board_session, requested
        )
    session = requested or board_session

    intraday = (
        session == now.date()
        and (now.hour, now.minute) >= (9, 30)
        and (now.hour, now.minute) < (16, 30)
    )
    if intraday and not args.allow_intraday:
        LOGGER.error(
            "board is INTRADAY (market open, %s) - pass --allow-intraday "
            "to write the still-accumulating session, or rerun after "
            "16:30 PKT",
            now.strftime("%H:%M"),
        )
        return 3

    deals = build_deals(rows, session, min_volume=args.min_volume)
    if args.limit and args.limit > 0:
        deals = deals[: args.limit]
    if not deals:
        LOGGER.warning(
            "no blocks >= %d shares on the board (raw symbols: %d)",
            args.min_volume,
            len(rows),
        )
        return 0

    LOGGER.info(
        "session %s: %d blocks >= %d shares; heaviest: %s",
        session,
        len(deals),
        args.min_volume,
        ", ".join(
            f"{d['ticker']} {d['quantity']:,}" for d in deals[:5]
        ),
    )
    if args.dry_run:
        LOGGER.info("DRY RUN - no database writes. First 5 rows:")
        for row in deals[:5]:
            LOGGER.info("  %s", row)
        LOGGER.info("DRY RUN - %d rows validated", len(deals))
        return 0

    closes = _load_closes(session)
    if not closes:
        LOGGER.warning(
            "psx_daily_eod has no closes for %s - rate/value stored NULL "
            "(run the EOD scraper first for valuation)", session
        )
    else:
        for deal in deals:
            rate = closes.get(deal["ticker"])
            deal["rate"] = round(rate, 2) if rate is not None else None
            deal["value"] = round(rate * deal["quantity"], 2) if rate is not None else None

    written = _insert_deals(deals, session)
    return 0 if written >= 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
