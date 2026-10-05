"""PSX negotiated / off-market (NDM) deals scraper.

SOURCE AUDIT (verified live 2026-10-06, per-symbol feed gone):

1.  ROUTE RETIREMENT. The per-symbol NDM board routes
    (/trading-board/NDM/main, legacy /trading-board/NDM/NDM) return 404
    with the DPS HTML error shell even through WAF-passing egress
    (ScraperAPI) - PSX has retired the /trading-board/ routes. The
    site's own front-end bundle (script.js v1.76) still calls them, so
    real browser users get a dead NDM tab as well.

2.  WHAT REMAINS PUBLIC. /trading-panel (WAF-free, server-rendered)
    now carries per-MARKET aggregate panels. Its NDM panel certifies
    the session facts (e.g. "Negotiable Deal | Closed | 61 trades |
    42,545,272 shares | PKR 1,324,533,454") but publishes no per-symbol
    rows. NDM therefore still trades - only the per-deal breakdown is
    no longer published.

3.  EXHAUSTED SURFACES. data.psx.com.pk and api/mobile/app/services
    subdomains do not resolve; www.psx.com.pk has no NDM product
    (sitemap + page audit); scstrade/scstrada/ksestocks have no NDM
    pages; the Wayback Machine holds zero NDM board captures; the
    official daily PDF carries only breadth + indices.

4.  LAST UNVERIFIED SURFACE. PSX's own JS populates the dps
    /daily-downloads table via POST {date: YYYY-MM-DD} - a per-session
    file listing that is edge-gated from this runner's IP and reachable
    only through ScraperAPI egress. ``--probe-downloads DATE`` lists
    what PSX serves there, so an NDM deals file (if one is published)
    can be discovered and given a parser next.

This scraper therefore:
1.  walks a tier chain - /trading-panel first (certified aggregate, plus
    per-symbol rows automatically if PSX ever re-adds board rows inline),
    then the legacy board pairs for auto-recovery - over an EGRESS chain
    (ScraperAPI first when SCRAPER_API_KEY is set, direct as fallback;
    without a key, direct only),
2.  distinguishes three honest outcomes: per-symbol rows found; session
    genuinely empty (aggregate certifies 0 trades); or per-symbol feed
    retired while the market demonstrably traded (SourceRetiredError
    carrying the certified aggregate),
3.  parses board tables tolerantly: the canonical ``#tradingBoardTable``
    or any table whose header carries SYMBOL and VOLUME, with the ticker
    read from the ``a.tbl__symbol`` link or the first symbol-shaped cell
    and volume taken from the last numeric column (survives reorder),
4.  returns [] with a logged explanation when no per-deal rows can be
    certified - the NDM tape stays honestly idle, never fabricated,
5.  persists the certified session aggregate (trades / volume / turnover
    value) to psx_offmarket_summary via fetch_ndm_summary_row() - the
    headline the NDM tape keeps when per-symbol rows are gone.

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
    http_post,
    http_post_via_scraperapi,
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


class SourceRetiredError(SourceBlockedError):
    """Per-symbol NDM routes are retired while the market demonstrably
    traded (certified via the /trading-panel aggregate). Distinct from a
    transport block so CI logs name the real condition."""


# ---------------------------------------------------------------------------
# Fetch tier
# ---------------------------------------------------------------------------


def _egress_attempts_get(url: str) -> list[tuple[str, Callable[[], Any]]]:
    """Egress chain for one GET: ScraperAPI proxy first (when keyed), direct
    second. The proxy tier exists because DPS edge-gates data routes by IP
    class; the panel page itself is WAF-free but shares the same chain for
    uniform diagnostics."""
    attempts: list[tuple[str, Callable[[], Any]]] = []
    if scraperapi_key():
        attempts.append(("scraperapi", lambda: http_get_via_scraperapi(url)))
    attempts.append(
        ("direct", lambda: http_get(url, headers=ajax_headers(TRADING_PANEL_URL)))
    )
    return attempts


def _http_get_with_egress(url: str) -> tuple[str, str]:
    """Run the GET egress chain; return (tier, body).

    Body-classification diagnostics (403-empty = WAF, 404+HTML = retired
    route) are logged per failed tier; raises SourceBlockedError only when
    no tier yields a usable body. Degraded-but-recovered tiers are logged
    as warnings so outages stay visible in CI.
    """
    failures: list[str] = []
    for tier, send in _egress_attempts_get(url):
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
        if failures:
            for failure in failures:
                LOGGER.warning(
                    "NDM egress tier degraded before '%s' recovered: %s", tier, failure
                )
        return tier, body
    raise SourceBlockedError(
        " | ".join(failures) if failures else f"{url}: no egress path configured"
    )


def _fetch_board_html(url: str) -> str:
    """GET one board URL over the egress chain, with table diagnostics."""
    tier, body = _http_get_with_egress(url)
    if "<table" not in body.lower():
        raise SourceBlockedError(f"{tier}: {url} -> 200 but no <table> in payload")
    return body


def _fetch_panel_html() -> str:
    """GET /trading-panel - the one DPS page still served WAF-free.

    Server-renders per-market aggregate panels (REG/BNB/DFC/.../NDM/MTS).
    Used as the certified NDM aggregate source AND as a per-symbol source
    should PSX re-add board rows inline.
    """
    tier, body = _http_get_with_egress(TRADING_PANEL_URL)
    if "tabs__panel" not in body:
        raise SourceBlockedError(
            f"{tier}: {TRADING_PANEL_URL} -> 200 but no tabs__panel markup"
        )
    return body


def _extract_ndm_panel(html: str) -> Optional[str]:
    """The NDM tabs__panel div (server-rendered), or None when absent."""
    soup = BeautifulSoup(html, "html.parser")
    panel = soup.find("div", class_="tabs__panel", attrs={"data-name": "NDM"})
    if isinstance(panel, Tag):
        return str(panel)
    return None


def _parse_ndm_aggregate(html: str) -> Optional[dict]:
    """Certified NDM market aggregate from /trading-panel.

    Row shape: Market | State | Trades | Volume | Value. The aggregate row
    is identified by its market label ("Negotiable Deal"), never by row
    position, so added per-symbol rows cannot be misread as the aggregate.
    Returns None when the panel/row cannot be parsed (layout change).
    """
    panel_html = _extract_ndm_panel(html)
    if panel_html is None:
        return None
    soup = BeautifulSoup(panel_html, "html.parser")
    tbody = soup.find("tbody")
    rows = tbody.find_all("tr") if isinstance(tbody, Tag) else []
    for tr in rows:
        if not isinstance(tr, Tag):
            continue
        cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        if len(cells) >= 5 and "negotia" in cells[0].lower():
            return {
                "market": cells[0],
                "state": cells[1],
                "trades": to_int(cells[2]) or 0,
                "volume": to_int(cells[3]) or 0,
                "value": to_int(cells[4]) or 0,
            }
    return None


# ---------------------------------------------------------------------------
# Panel snapshot memo (one /trading-panel GET per process)
# ---------------------------------------------------------------------------

_PANEL_SNAPSHOT: dict[str, Any] = {}


def _load_panel_snapshot() -> tuple[Optional[str], Optional[dict]]:
    """Fetch /trading-panel ONCE per process; memoize (html, aggregate).

    fetch_ndm_rows() and fetch_ndm_aggregate() both need the panel; the
    memo keeps the daily pipeline at one GET regardless of call order.
    """
    if _PANEL_SNAPSHOT.get("done"):
        return _PANEL_SNAPSHOT.get("panel"), _PANEL_SNAPSHOT.get("aggregate")
    panel: Optional[str] = None
    aggregate: Optional[dict] = None
    try:
        panel = _fetch_panel_html()
    except SourceBlockedError as exc:
        LOGGER.warning("NDM panel tier failed: %s", exc)
    else:
        aggregate = _parse_ndm_aggregate(panel)
    _PANEL_SNAPSHOT.update(done=True, panel=panel, aggregate=aggregate)
    return panel, aggregate


def fetch_ndm_aggregate() -> Optional[dict]:
    """Certified NDM session aggregate from /trading-panel (or None).

    The one NDM fact set PSX still publishes after retiring the per-deal
    board: {"market", "state", "trades", "volume", "value"}. Returns None
    when the panel is unreachable or its NDM row cannot be parsed - the
    summary table then honestly skips the session (no zeros guessed).
    """
    _, aggregate = _load_panel_snapshot()
    if aggregate is None:
        LOGGER.warning(
            "NDM aggregate unavailable (panel tier down or NDM row unparseable)"
        )
    else:
        LOGGER.info(
            "NDM aggregate (certified): %d trades | %s shares | PKR %s | state=%s",
            aggregate["trades"],
            f"{aggregate['volume']:,}",
            f"{aggregate['value']:,}",
            aggregate["state"],
        )
    return aggregate


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
    """Fetch NDM per-symbol rows via the tier chain (audit: 2026-10-06).

    Tier 0: /trading-panel - server-rendered aggregates; yields per-symbol
            rows automatically if PSX re-adds board rows inline.
    Tier 1: legacy /trading-board/NDM/* pairs - retired server-side, kept
            for auto-recovery if PSX re-enables them.

    Decision tree:
      - per-symbol rows found on any tier -> returned
      - aggregate certifies 0 trades      -> [] (genuine empty session)
      - a board IS reachable but empty    -> [] (genuine empty board)
      - aggregate proves trading but no per-symbol source -> SourceRetiredError
      - everything unreachable            -> SourceBlockedError
    """
    LOGGER.info(
        "NDM egress: %s",
        "ScraperAPI proxy first, direct fallback"
        if scraperapi_key()
        else "direct only (SCRAPER_API_KEY unset)",
    )

    # Tier 0: trading panel (WAF-free, server-rendered); snapshot memoized
    # per process so fetch_ndm_aggregate()/fetch_ndm_summary_row() reuse it.
    panel, aggregate = _load_panel_snapshot()
    if panel is not None:
        panel_html = _extract_ndm_panel(panel)
        rows = _parse_ndm_board(panel_html) if panel_html else []
        if rows:
            LOGGER.info(
                "NDM per-symbol rows sourced from /trading-panel (%d symbols)",
                len(rows),
            )
            return rows
        if aggregate is None:
            LOGGER.warning(
                "trading panel reachable but NDM panel not parsed (layout change?)"
            )
        elif aggregate["trades"] == 0:
            LOGGER.info(
                "NDM session genuinely empty - /trading-panel certifies 0 trades "
                "(%s)",
                aggregate["state"],
            )
            return []

    # Tier 1: legacy board routes (retired 2026-10; kept for auto-recovery)
    failures: list[str] = []
    reachable_empty = False
    for url in NDM_BOARD_URLS:
        try:
            html = _fetch_board_html(url)
        except SourceBlockedError as exc:
            failures.append(str(exc))
            continue
        rows = _parse_ndm_board(html)
        if rows:
            return rows
        # Empty table from a reachable source: treat as a real empty board.
        failures.append(f"{url} -> 200 with an empty/unparseable board table")
        reachable_empty = True

    if reachable_empty:
        for failure in failures:
            LOGGER.warning("NDM board tier: %s", failure)
        LOGGER.warning(
            "a board source IS reachable but lists zero symbols - "
            "treating as a genuinely empty NDM board"
        )
        return []

    for failure in failures:
        LOGGER.error("NDM source tier failed: %s", failure)
    if aggregate and aggregate["trades"] > 0:
        raise SourceRetiredError(
            "per-symbol NDM board routes are RETIRED and no public per-symbol "
            "source exists - /trading-panel certifies the market TRADED "
            f"{aggregate['trades']} deals / {aggregate['volume']:,} shares / "
            f"PKR {aggregate['value']:,} this session (state: {aggregate['state']}); "
            "per-deal rows cannot be recovered from any public surface"
        )
    raise SourceBlockedError(
        f"all {len(NDM_BOARD_URLS)} NDM board tiers failed "
        "(WAF-gated or retired) and the trading-panel aggregate was unreadable "
        "- NDM tape stays idle this session"
    )


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
    except SourceRetiredError as exc:
        LOGGER.error(
            "off-market deals %s: PER-SYMBOL FEED RETIRED - %s", trade_date, exc
        )
        return []
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


def build_summary_row(aggregate: dict, trade_date: date) -> dict:
    """psx_offmarket_summary row from the certified aggregate (pure).

    Schema (schema.sql 3c): trade_date PK, trades integer, volume bigint,
    value numeric(15,2), state, source. The aggregate is already parsed
    to ints, so this is a straight shape conversion - no invented numbers.
    """
    return {
        "trade_date": trade_date.isoformat(),
        "trades": int(aggregate.get("trades") or 0),
        "volume": int(aggregate.get("volume") or 0),
        "value": (
            float(aggregate["value"]) if aggregate.get("value") is not None else None
        ),
        "state": (str(aggregate.get("state") or "").strip()[:30]) or None,
        "source": "trading-panel",
    }


def fetch_ndm_summary_row(trade_date: date) -> Optional[dict]:
    """Pipeline entry: the certified NDM aggregate as a summary row, or None.

    Reuses the panel GET already performed by fetch_offmarket_deals (the
    snapshot is memoized per process) - one fetch feeds both tables. None
    means the panel tier was down or its NDM row unparseable; callers skip
    the summary rather than write a zeroed guess.
    """
    aggregate = fetch_ndm_aggregate()
    if aggregate is None:
        LOGGER.error(
            "off-market summary %s: aggregate unreadable - summary row skipped",
            trade_date,
        )
        return None
    row = build_summary_row(aggregate, trade_date)
    LOGGER.info("off-market summary %s: %s", trade_date, row)
    return row


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


def _upsert_summary(trade_date: date) -> None:
    """Persist the certified NDM aggregate to psx_offmarket_summary.

    Best-effort: the panel snapshot is memoized (no second GET), and a
    missing table (migration 006 not yet applied) or any upsert failure
    logs a warning and moves on - the deals write is never blocked by the
    summary.
    """
    from pipeline import db as _db

    row = fetch_ndm_summary_row(trade_date)
    if row is None:
        LOGGER.warning(
            "psx_offmarket_summary: aggregate unavailable for %s - skipped",
            trade_date,
        )
        return
    try:
        written = _db.upsert_records(
            "psx_offmarket_summary", [row], on_conflict="trade_date"
        )
    except Exception as exc:  # noqa: BLE001 - summary is secondary to deals
        LOGGER.warning(
            "psx_offmarket_summary: upsert failed for %s (%s) - deals kept",
            trade_date,
            exc,
        )
        return
    if written:
        LOGGER.info("psx_offmarket_summary: row upserted for %s", trade_date)
    else:
        LOGGER.warning(
            "psx_offmarket_summary: upsert reported 0 rows for %s - table "
            "missing (run migration 006) or chunk failed; deals unaffected",
            trade_date,
        )


def _parse_date_arg(raw: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise SystemExit(f"invalid --date {raw!r}: expected YYYY-MM-DD") from exc


def _probe_daily_downloads(raw_date: str) -> int:
    """POST /daily-downloads {date} over the egress chain, list file links.

    PSX's own front-end (script.js getDailyTable) populates the daily
    downloads table exactly this way - the last unverified surface that
    may carry a per-session NDM deals file (edge-gated without egress).
    Exit 0 = listing retrieved (links logged), 2 = unreachable.
    """
    target = f"{BASE_URL}/daily-downloads"
    attempts: list[tuple[str, Callable[[], Any]]] = []
    if scraperapi_key():
        attempts.append(
            (
                "scraperapi",
                lambda: http_post_via_scraperapi(target, data={"date": raw_date}),
            )
        )
    attempts.append(
        (
            "direct",
            lambda: http_post(
                target,
                data={"date": raw_date},
                headers=ajax_headers(TRADING_PANEL_URL),
            ),
        )
    )

    failures: list[str] = []
    body = ""
    tier_used = "direct"
    for tier, send in attempts:
        try:
            response = send()
        except Exception as exc:  # noqa: BLE001 - degrade to next egress tier
            failures.append(f"{tier}: unreachable: {exc}")
            continue
        body = response.text or ""
        if response.status_code == 403 and not body.strip():
            failures.append(f"{tier}: 403 EMPTY body (edge WAF block)")
            continue
        if response.status_code >= 400:
            failures.append(f"{tier}: HTTP {response.status_code}")
            continue
        tier_used = tier
        break

    if not body:
        for failure in failures:
            LOGGER.error("daily-downloads probe tier failed: %s", failure)
        return 2

    links = re.findall(
        r'href="([^"]+\.(?:pdf|xlsx?|csv|zip|txt)[^"]*)"[^>]*>([^<]{0,90})',
        body,
        re.I,
    )
    LOGGER.info(
        "daily-downloads %s (tier=%s): %d file links",
        raw_date,
        tier_used,
        len(links),
    )
    ndm_hits = 0
    for file_url, label in links:
        marker = ""
        if re.search(r"ndm|negotiat|off.?market|deal", f"{file_url} {label}", re.I):
            marker = "  <-- NDM CANDIDATE"
            ndm_hits += 1
        LOGGER.info("   %s | %s%s", file_url[:110], label.strip()[:70], marker)
    if not links:
        LOGGER.warning(
            "listing retrieved but zero file links - empty session or "
            "listing layout change; first 500 chars follow"
        )
        LOGGER.warning("snippet: %s", body[:500])
    elif not ndm_hits:
        LOGGER.info(
            "no NDM/negotiated file name matched - review the links above "
            "for renamed NDM products before concluding absence"
        )
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    """Backfill CLI.

    python -m pipeline.scrapers.psx_offmarket --dry-run
    python -m pipeline.scrapers.psx_offmarket --date 2026-09-30
    python -m pipeline.scrapers.psx_offmarket --probe-downloads 2026-10-05
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
    parser.add_argument(
        "--probe-downloads",
        metavar="YYYY-MM-DD",
        help="probe the edge-gated dps /daily-downloads listing for a "
        "session date (needs SCRAPER_API_KEY in CI) and list its files - "
        "no DB writes, pure source discovery",
    )
    args = parser.parse_args(argv)

    if args.probe_downloads:
        return _probe_daily_downloads(args.probe_downloads)

    requested = _parse_date_arg(args.date) if args.date else None
    now = datetime.now(PKT)

    try:
        rows = fetch_ndm_rows()
    except SourceRetiredError as exc:
        LOGGER.error("NDM PER-SYMBOL FEED RETIRED: %s", exc)
        return 4
    except SourceBlockedError as exc:
        LOGGER.error("NDM FEED UNAVAILABLE: %s", exc)
        return 2

    # Certified aggregate: memoized by the rows fetch above - free here.
    fetch_ndm_aggregate()

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
        aggregate = fetch_ndm_aggregate()
        if aggregate:
            LOGGER.info(
                "DRY RUN - summary row would be: %s",
                build_summary_row(aggregate, session),
            )
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
    _upsert_summary(session)
    return 0 if written >= 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
