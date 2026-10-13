"""Supabase client and chunked upsert helpers."""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from datetime import date, timedelta
from typing import Any, Optional

from dotenv import load_dotenv
from supabase import Client, create_client

from pipeline.parsing import chunked

LOGGER = logging.getLogger(__name__)

CHUNK_SIZE = 500

# Calendar-day floor for EOD history reads. 220 days ≈ 150 trading sessions:
# keeps 200-SMA baselines, quarterly research and RRG 60-session lookbacks
# fully fed regardless of the `days` a caller passes.
EOD_HISTORY_MIN_DAYS = 220

# Decision-engine universe tail: a calendar-bounded EOD window for the
# SHORT_TERM / MID_TERM / LONG_TERM candidate screens. 30 calendar days is
# enough for breadth, 20D highs, 5-day pullbacks and 14D ATR, and small
# enough to paginate over a handful of 1000-row pages instead of the
# multi-month fetch that exhausted the Supabase pool on cloud runs.
_ENGINE_UNIVERSE_DAYS = 30

_client: Optional[Client] = None


def get_client() -> Client:
    """Create (once) a Supabase client from SUPABASE_URL / SUPABASE_KEY.

    The pipeline runs headless in GitHub Actions, so it uses the
    service-role key, which bypasses row level security. Fail fast with a
    clear message if configuration is missing.
    """
    global _client
    if _client is not None:
        return _client

    load_dotenv()
    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_KEY", "").strip()

    if not url or not key:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_KEY must be set (env vars or .env). "
            "Copy .env.example to .env and fill in your project values."
        )
    if not url.startswith("http"):
        raise ValueError("SUPABASE_URL must start with http:// or https://")

    from supabase.lib.client_options import SyncClientOptions
    from httpx import Client as HttpxClient

    _client = create_client(
        url,
        key,
        options=SyncClientOptions(
            postgrest_client_timeout=15.0,
            httpx_client=HttpxClient(timeout=15.0),
        ),
    )
    LOGGER.info("Supabase client initialised for %s", url)
    return _client


def _strip_unknown_columns(
    table: str,
    records: list[dict[str, Any]],
    missing_cols: set[str],
) -> list[dict[str, Any]]:
    """Drop the given (missing) keys from every record (returns a new list)."""
    LOGGER.warning(
        "%s: schema drift detected (missing: %s) - degrading to the live "
        "columns so the feed keeps flowing; apply the pending migration "
        "to heal.",
        table,
        ", ".join(sorted(missing_cols)),
    )
    return [
        {k: v for k, v in record.items() if k not in missing_cols}
        for record in records
    ]


def purge_verdict_horizons(trade_date: str, horizons: list[str]) -> int:
    """Delete verdict rows for one session whose horizons were RETIRED.

    The engine SKIPS a horizon when no candidate certifies (never
    fabricated). Without this, an upsert leaves the prior session's row for
    that horizon in place, and the frontend's latest-session fallback
    renders a stale verdict as current. Scope is strictly (trade_date AND
    horizon in horizons) - never a whole-table wipe. Best-effort: a missing
    table or permission error logs and returns 0 so the run survives.
    """
    if not horizons:
        return 0
    try:
        client = get_client()
        result = (
            client.table("psx_system_verdicts")
            .delete()
            .eq("trade_date", trade_date)
            .in_("horizon", horizons)
            .execute()
        )
        purged = len(result.data or [])
        if purged:
            LOGGER.info(
                "psx_system_verdicts: retired %d stale row(s) for %s (%s)",
                purged, trade_date, ", ".join(sorted(horizons)),
            )
        return purged
    except Exception as exc:  # noqa: BLE001 - purge must never kill the run
        LOGGER.warning("psx_system_verdicts: horizon purge failed: %s", exc)
        return 0


def upsert_records(
    table: str,
    records: list[dict[str, Any]],
    *,
    on_conflict: str,
    chunk_size: int = CHUNK_SIZE,
) -> int:
    """Upsert records in safe chunks; returns rows written.

    - Chunks of 500 keep each POST small enough for Supabase free tier.
    - A failed chunk is logged and skipped so one bad row never kills a
      whole day's run.
    - PGRST204 (column not present in the live table) triggers a ONE-SHOT
      degrade: the writer introspects which record keys the table lacks,
      strips them, and retries - schema drift degrades the COLUMNS instead
      of silently zeroing the table. All other errors keep log-and-skip.
    """
    if not records:
        LOGGER.info("upsert(%s): nothing to write", table)
        return 0

    client = get_client()
    written = 0
    degrade: Optional[set[str]] = None  # set once on the first PGRST204
    index = 0
    chunks = list(chunked(records, chunk_size))
    while index < len(chunks):
        chunk = chunks[index]
        index += 1
        payload = chunk
        if degrade is not None:
            payload = [
                {k: v for k, v in row.items() if k not in degrade}
                for row in chunk
            ]
        try:
            client.table(table).upsert(payload, on_conflict=on_conflict).execute()
            written += len(payload)
            continue
        except Exception as exc:  # noqa: BLE001 - keep the run alive
            message = str(exc)
            # Missing-column drift surfaces as PGRST204 (schema-cache miss)
            # or as Postgres 42703 passed through by some PostgREST builds.
            if ("PGRST204" in message or "42703" in message) and degrade is None:
                degrade = _detect_missing_columns(table, records)
                if degrade:
                    LOGGER.warning(
                        "upsert(%s): PGRST204 - degrading columns: %s",
                        table,
                        ", ".join(sorted(degrade)),
                    )
                    records[:] = _strip_unknown_columns(table, records, degrade)
                    chunks = list(chunked(records, chunk_size))
                    index -= 1  # reprocess this chunk in degraded form
                    continue
            LOGGER.error(
                "upsert(%s): chunk %d/%d failed: %s",
                table,
                index,
                len(chunks),
                exc,
            )
    LOGGER.info("upsert(%s): %d/%d rows written", table, written, len(records))
    return written


def _detect_missing_columns(
    table: str,
    records: list[dict[str, Any]],
) -> set[str]:
    """Which record keys does the live table lack? (PostgREST introspection.)

    Probes the table's REST metadata (OpenAPI introspection at the root) -
    the response enumerates every exposed column, so missing keys are the
    record keys absent from it. Uses only the stdlib (urllib) so it works
    on every supabase-py generation - the old ``client.rest`` attribute
    does not exist on supabase-py 2.x and silently disabled this path.
    Empty set on any failure (the caller then keeps log-and-skip).
    """
    try:
        client = get_client()
        request = urllib.request.Request(
            f"{client.supabase_url}/rest/v1/",
            headers={
                "apikey": client.supabase_key,
                "Authorization": f"Bearer {client.supabase_key}",
                "Accept": "application/openapi+json",
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
        known = set(
            payload.get("definitions", {}).get(table, {}).get("properties", {}).keys()
        )
        if not known:
            return set()
        return set(records[0].keys()) - known
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("upsert(%s): column introspection failed: %s", table, exc)
        return set()


PAGE_SIZE = 1000  # PostgREST hard-caps a single response at 1000 rows


def _paginated_select(
    table: str,
    columns: str,
    *,
    order_desc_col: str,
    order_asc_col: Optional[str] = None,
    max_rows: int,
    filters: Optional[list[tuple[str, str, Any]]] = None,
) -> list[dict[str, Any]]:
    """Select rows following range pagination until exhausted.

    PostgREST returns at most 1000 rows per request regardless of .limit(),
    so large reads MUST page with .range() or they silently truncate.
    Ordering is (desc_col desc, asc_col asc) for deterministic pages.

    A missing table (PGRST205 - migration not yet applied in Supabase) is
    logged once and yields an empty result so optional feeds degrade to an
    honest idle state instead of aborting the whole engine run.
    """
    client = get_client()
    rows: list[dict[str, Any]] = []
    start = 0
    while len(rows) < max_rows:
        builder = client.table(table).select(columns)
        for column, op, value in filters or []:
            builder = builder.filter(column, op, value)
        builder = builder.order(order_desc_col, desc=True)
        if order_asc_col:
            builder = builder.order(order_asc_col, desc=False)
        try:
            response = builder.range(start, start + PAGE_SIZE - 1).execute()
        except Exception as exc:  # noqa: BLE001 - typed narrow below
            if "PGRST205" in str(exc) or "schema cache" in str(exc):
                LOGGER.warning(
                    "%s: table missing (apply schema.sql in Supabase) - returning []",
                    table,
                )
                return []
            raise
        page = response.data or []
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            break
        start += PAGE_SIZE
    return rows[:max_rows]


def fetch_eod_in_window(
    min_date: str,
    max_date: str,
    max_rows: int = 240_000,
) -> list[dict[str, Any]]:
    """Trade-date-bounded EOD slice across the market.

    Server-side ``trade_date >= min_date AND trade_date <= max_date`` keeps the
    read strictly on the window's pages - never the full table. Used by the
    decision engine so the universe slice fed to the candidate screens is a
    small calendar-bounded tail instead of a multi-month fetch.
    """
    return _paginated_select(
        "psx_daily_eod",
        "trade_date,ticker,open_price,high_price,low_price,close_price,volume",
        order_desc_col="trade_date",
        order_asc_col="ticker",
        max_rows=max_rows,
        filters=[
            ("trade_date", "gte", min_date),
            ("trade_date", "lte", max_date),
        ],
    )


def fetch_recent_eod(days: int = 90, min_date: Optional[str] = None) -> list[dict[str, Any]]:
    """Load the trailing history the quant engines need for indicators.

    Every call is window-bounded: the server filters ``trade_date >= gte``
    before pagination, so a full-table scan (weeks of unbounded pages) can
    never happen again. ``min_date`` wins when given (backtester forward
    windows); otherwise the window is ``max(days, EOD_HISTORY_MIN_DAYS)``
    calendar days back - the floor keeps 200-SMA/quarterly engines fed even
    when a caller passes a small ``days``.
    """
    if min_date is None:
        days = max(days, EOD_HISTORY_MIN_DAYS)
        min_date = (date.today() - timedelta(days=days)).isoformat()
    return _paginated_select(
        "psx_daily_eod",
        "trade_date,ticker,open_price,high_price,low_price,close_price,volume",
        order_desc_col="trade_date",
        order_asc_col="ticker",
        max_rows=days * 800,  # headroom: ~500 traded symbols x days
        filters=[("trade_date", "gte", min_date)],
    )


def fetch_eod_for_ticker(ticker: str, days: int = 1100) -> list[dict[str, Any]]:
    """One ticker's stored EOD history for the quick backtester.

    Filtered server-side on ticker so a 3-year walk-forward costs one
    symbol's rows (~750), never the whole universe's millions.
    Includes bar high/low so backtest resolution uses real ranges.
    """
    min_date = (date.today() - timedelta(days=days)).isoformat()
    return _paginated_select(
        "psx_daily_eod",
        "trade_date,open_price,high_price,low_price,close_price,volume",
        order_desc_col="trade_date",
        order_asc_col="ticker",
        max_rows=days + 100,
        filters=[("trade_date", "gte", min_date), ("ticker", "eq", ticker)],
    )


def fetch_recent_flows(days: int = 15) -> list[dict[str, Any]]:
    """Load recent participant flows for the medium-term engine."""
    return _paginated_select(
        "nccpl_fipi_lipi",
        "trade_date,participant_type,sector_name,net_pkr",
        order_desc_col="trade_date",
        order_asc_col="participant_type",
        max_rows=days * 120,
    )


def fetch_rotation_history(days: int = 120) -> list[dict[str, Any]]:
    """Stored rotation rows for regime-persistence tracking."""
    return _paginated_select(
        "psx_sector_rotation",
        "trade_date,sector_name,quadrant",
        order_desc_col="trade_date",
        order_asc_col="sector_name",
        max_rows=days * 40,
    )


def fetch_recent_offmarket(days: int = 3) -> list[dict[str, Any]]:
    """Load recent NDM block deals for short-term confirmation."""
    return _paginated_select(
        "psx_offmarket_deals",
        "trade_date,ticker,quantity,rate,value",
        order_desc_col="trade_date",
        order_asc_col="ticker",
        max_rows=days * 60,
    )


def fetch_recent_futures(days: int = 7) -> list[dict[str, Any]]:
    """Load recent XXX-FUT closes for the arbitrage desk + DFC scanner.

    oi_shares is read defensively: installs not yet migrated to the column
    are served the legacy shape (PGRST204 -> retry without it) instead of a
    hard failure, mirroring the frontend two-tier convention.
    """
    try:
        return _paginated_select(
            "psx_futures_eod",
            "trade_date,ticker,open_price,high_price,low_price,close_price,volume,oi_shares",
            order_desc_col="trade_date",
            order_asc_col="ticker",
            max_rows=days * 150,
        )
    except Exception:
        return _paginated_select(
            "psx_futures_eod",
            "trade_date,ticker,open_price,high_price,low_price,close_price,volume",
            order_desc_col="trade_date",
            order_asc_col="ticker",
            max_rows=days * 150,
        )


def upsert_futures_rows(rows: list[dict[str, Any]]) -> int:
    """Upsert futures contract rows, degrading gracefully on legacy tables.

    New installs carry oi_shares (DFC scanner leg). Tables created before the
    column answer the upsert with PGRST204; we then retry the exact same rows
    stripped of oi_shares so the pipeline never hard-fails on schema lag and
    prices still land.
    """
    if not rows:
        return 0
    written = upsert_records(
        "psx_futures_eod", rows, on_conflict="trade_date,ticker"
    )
    if written == 0:
        stripped = [
            {k: v for k, v in row.items() if k != "oi_shares"} for row in rows
        ]
        written = upsert_records(
            "psx_futures_eod", stripped, on_conflict="trade_date,ticker"
        )
    return written


def fetch_recent_insider_trades(days: int = 5) -> list[dict[str, Any]]:
    """Recent insider/sponsor disclosures for the INSIDER_RADAR engine."""
    return _paginated_select(
        "psx_insider_trades",
        "trade_date,ticker,insider_name,designation,trade_type,quantity,rate,notional_pkr",
        order_desc_col="trade_date",
        max_rows=days * 200,
    )


def fetch_recent_mts(days: int = 6) -> list[dict[str, Any]]:
    """Recent per-scrip MTS leverage rows for the MTS_SQUEEZE engine."""
    return _paginated_select(
        "nccpl_mts_leverage",
        "trade_date,ticker,mts_shares,mts_value_pkr,leverage_utilization_pct,unfinanced_volume",
        order_desc_col="trade_date",
        order_asc_col="ticker",
        max_rows=days * 200,
    )


def fetch_macro_prices(max_rows: int = 30000) -> list[dict[str, Any]]:
    """All stored macro indicator closes (driver_code, trade_date, close)."""
    return _paginated_select(
        "psx_macro_indicator_prices",
        "driver_code,trade_date,close",
        order_desc_col="trade_date",
        order_asc_col="driver_code",
        max_rows=max_rows,
    )


def fetch_recent_fundamentals(*, real_sectors_only: bool = False) -> list[dict[str, Any]]:
    """Latest screener snapshot per ticker (used by the long-term screen).

    With real_sectors_only, rows whose sector_name is the scraper's
    "UNKNOWN" placeholder are excluded server-side. The DPS sectorwise
    map has been failing since 2026-09-23, so recent snapshots are 100%
    UNKNOWN and a plain newest-first window never reaches the last good
    snapshot; filtering returns only usable labels (~5k rows) instead.
    """
    filters = [("sector_name", "neq", "UNKNOWN")] if real_sectors_only else None
    return _paginated_select(
        "psx_fundamentals",
        "trade_date,ticker,sector_name,market_cap_pkr,"
        "close_price,pe_ratio,dividend_yield",
        order_desc_col="trade_date",
        order_asc_col="ticker",
        max_rows=8000 if real_sectors_only else 3000,
        filters=filters,
    )


# --------------------------------------------------------------------------- #
# Backtester: signals awaiting forward evaluation + performance writes        #
# --------------------------------------------------------------------------- #
def fetch_session_dates_of_signals() -> list[dict[str, Any]]:
    """Distinct signal trade_dates (cheap probe for walk-forward seeding).

    Paginates every stored trade_date: signal history spans months, and a
    single-page probe would under-report old sessions (re-simulating them
    needlessly on every run).
    """
    rows = _paginated_select(
        "signals_computed",
        "trade_date",
        order_desc_col="trade_date",
        max_rows=20000,
    )
    return rows


def fetch_unbacktested_signals(
    max_age_days: int = 60, limit: int = 20000
) -> list[dict[str, Any]]:
    """Signals with no row in signal_backtest_performance (anti-join).

    Left-joined via the upsert-friendly path: we read recent signals and
    filter out ids already present in the performance table. Entry price
    and a positive stop are required for a signal to be evaluable.
    """
    client = get_client()
    cutoff = (date.today() - timedelta(days=max_age_days)).isoformat()
    signals = _paginated_select(
        "signals_computed",
        "id,trade_date,ticker,signal_type,entry_reference,stop_loss,timeframe",
        order_desc_col="trade_date",
        order_asc_col="id",
        max_rows=limit,
        filters=[("trade_date", "gte", cutoff)],
    )
    done = _paginated_select(
        "signal_backtest_performance",
        "signal_id",
        order_desc_col="trade_date",
        max_rows=limit,
        filters=[("trade_date", "gte", cutoff)],
    )
    evaluated = {row["signal_id"] for row in done}
    return [
        s
        for s in signals
        if s["id"] not in evaluated
        and s.get("entry_reference") is not None
        and s.get("stop_loss") is not None
        and float(s["stop_loss"]) > 0
    ]


def fetch_backtest_performance(
    days: int = 180, max_rows: int = 20000
) -> list[dict[str, Any]]:
    """Stored forward-performance rows (frontend edge analytics + stats)."""
    return _paginated_select(
        "signal_backtest_performance",
        "signal_id,ticker,trade_date,signal_type,entry_price,stop_loss,"
        "return_t5_pct,return_t10_pct,return_t20_pct,"
        "max_favorable_excursion_pct,max_adverse_excursion_pct,"
        "hit_target,stopped_out,tp1_hit,tp2_hit,runner_hit,full_stop,realized_r",
        order_desc_col="trade_date",
        max_rows=max_rows,
        filters=[
            (
                "trade_date",
                "gte",
                (date.today() - timedelta(days=days)).isoformat(),
            )
        ],
    )


TIERED_PERF_COLUMNS = (
    "tp1_hit",
    "tp2_hit",
    "runner_hit",
    "full_stop",
    "realized_r",
)


def upsert_backtest_rows(rows: list[dict[str, Any]]) -> int:
    """Idempotently store forward-performance rows keyed by signal_id.

    Degrades gracefully when the live table predates the tiered-exit
    columns (PGRST204): retries with the legacy column set. Tiered
    semantics survive the fallback - hit_target carries TP1-hit and
    stopped_out carries full-stop - but realized_r waits for the
    schema.sql ALTER to be applied.
    """
    if not rows:
        return 0
    written = 0
    for chunk_start in range(0, len(rows), 500):
        chunk = rows[chunk_start : chunk_start + 500]
        try:
            (
                get_client()
                .table("signal_backtest_performance")
                .upsert(
                    chunk,
                    on_conflict="signal_id",
                )
                .execute()
            )
            written += len(chunk)
        except Exception as exc:  # noqa: BLE001 - typed narrow below
            if "PGRST204" in str(exc) and any(
                col in str(exc) for col in TIERED_PERF_COLUMNS
            ):
                LOGGER.warning(
                    "upsert(signal_backtest_performance): table lacks tiered "
                    "columns - retrying legacy set. Apply the schema.sql "
                    "ALTERs to enable R-weighted profit factor / expectancy."
                )
                slim = [
                    {k: v for k, v in row.items() if k not in TIERED_PERF_COLUMNS}
                    for row in chunk
                ]
                (
                    get_client()
                    .table("signal_backtest_performance")
                    .upsert(
                        slim,
                        on_conflict="signal_id",
                    )
                    .execute()
                )
                written += len(slim)
            else:
                raise
    LOGGER.info("upsert(signal_backtest_performance): %d rows", written)
    return written


def _chunked_in_delete(
    table: str, column: str, values: list[Any], chunk_size: int = 200
) -> int:
    """Delete rows where ``column`` is in ``values`` (chunked .in_())."""
    deleted = 0
    client = get_client()
    for start in range(0, len(values), chunk_size):
        chunk = values[start : start + chunk_size]
        result = client.table(table).delete().in_(column, chunk).execute()
        deleted += len(result.data or [])
    return deleted


def purge_seed_window(session_dates: list[str]) -> dict[str, int]:
    """Remove signals + their backtest rows for the given sessions.

    Used by the explicit ``--reseed`` path so Edge Lab never mixes
    resolution conventions (legacy single-bar vs tiered) or pre-gate
    signals. Scoped strictly to the supplied session dates.
    """
    if not session_dates:
        return {"signals": 0, "performance": 0}
    signal_rows = _paginated_select(
        "signals_computed",
        "id",
        order_desc_col="trade_date",
        filters=[("trade_date", "in", f"({','.join(session_dates)})")],
        max_rows=100000,
    )
    signal_ids = [int(r["id"]) for r in signal_rows]
    perf_deleted = (
        _chunked_in_delete("signal_backtest_performance", "signal_id", signal_ids)
        if signal_ids
        else 0
    )
    signals_deleted = _chunked_in_delete(
        "signals_computed", "trade_date", session_dates
    )
    LOGGER.info(
        "purge seed window: %d signals + %d performance rows removed "
        "(%d sessions)",
        signals_deleted,
        perf_deleted,
        len(session_dates),
    )
    return {"signals": signals_deleted, "performance": perf_deleted}


# --------------------------------------------------------------------------- #
# Fundamental Alpha & Research Layer: ratios/research/rotation IO              #
# --------------------------------------------------------------------------- #
def fetch_financial_ratios() -> list[dict[str, Any]]:
    """Stored quarterly ratios (all tickers, newest period first)."""
    return _paginated_select(
        "psx_financial_ratios",
        "ticker,fiscal_period,period_end_date,eps,sales_growth_yoy_pct,"
        "net_profit_margin_pct",
        order_desc_col="period_end_date",
        order_asc_col="ticker",
        max_rows=20000,
    )


def upsert_financial_ratios(rows: list[dict[str, Any]]) -> int:
    """Idempotently store quarterly ratio rows keyed by (ticker, fiscal_period)."""
    return upsert_records(
        "psx_financial_ratios", rows, on_conflict="ticker,fiscal_period"
    )


def fetch_equity_research(session_date: Optional[date] = None) -> list[dict[str, Any]]:
    """Research rows for one session (or the latest available when None)."""
    filters = (
        [("trade_date", "eq", session_date.isoformat())] if session_date else None
    )
    return _paginated_select(
        "psx_equity_research",
        "trade_date,ticker,alpha_score,intrinsic_value_pkr,"
        "valuation_discount_pct,valuation_status,balance_sheet_risk_flag",
        order_desc_col="alpha_score",
        order_asc_col="ticker",
        max_rows=2000,
        filters=filters,
    )


def upsert_equity_research(rows: list[dict[str, Any]]) -> int:
    """Idempotently store research rows keyed by (trade_date, ticker)."""
    return upsert_records(
        "psx_equity_research", rows, on_conflict="trade_date,ticker"
    )


def fetch_sector_rotation(session_date: Optional[date] = None) -> list[dict[str, Any]]:
    """Rotation rows for one session (or the latest available when None)."""
    filters = (
        [("trade_date", "eq", session_date.isoformat())] if session_date else None
    )
    return _paginated_select(
        "psx_sector_rotation",
        "trade_date,sector_name,rs_ratio,rs_momentum,quadrant,"
        "top_leader_ticker,top_dragger_ticker",
        order_desc_col="rs_ratio",
        max_rows=200,
        filters=filters,
    )


def upsert_sector_rotation(rows: list[dict[str, Any]]) -> int:
    """Idempotently store rotation rows keyed by (trade_date, sector_name)."""
    return upsert_records(
        "psx_sector_rotation", rows, on_conflict="trade_date,sector_name"
    )
