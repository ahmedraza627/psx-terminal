"""Supabase client and chunked upsert helpers."""

from __future__ import annotations

import logging
import os
from datetime import date, timedelta
from typing import Any, Optional

from dotenv import load_dotenv
from supabase import Client, create_client

from pipeline.parsing import chunked

LOGGER = logging.getLogger(__name__)

CHUNK_SIZE = 500

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

    _client = create_client(url, key)
    LOGGER.info("Supabase client initialised for %s", url)
    return _client


def upsert_records(
    table: str,
    records: list[dict[str, Any]],
    *,
    on_conflict: str,
    chunk_size: int = CHUNK_SIZE,
) -> int:
    """Upsert records into a table in safe chunks; returns rows written.

    - Chunks of 500 keep each POST small enough for Supabase free tier.
    - A failed chunk is logged and skipped so one bad row never kills a
      whole day's run.
    """
    if not records:
        LOGGER.info("upsert(%s): nothing to write", table)
        return 0

    client = get_client()
    written = 0
    for index, chunk in enumerate(chunked(records, chunk_size), start=1):
        try:
            (
                client.table(table)
                .upsert(chunk, on_conflict=on_conflict)
                .execute()
            )
            written += len(chunk)
            LOGGER.debug(
                "upsert(%s): chunk %d wrote %d rows", table, index, len(chunk)
            )
        except Exception as exc:  # noqa: BLE001 - keep the run alive
            LOGGER.error(
                "upsert(%s): chunk %d/%d failed after retries: %s",
                table,
                index,
                (len(records) + chunk_size - 1) // chunk_size,
                exc,
            )
    LOGGER.info("upsert(%s): %d/%d rows written", table, written, len(records))
    return written


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


def fetch_recent_eod(days: int = 90) -> list[dict[str, Any]]:
    """Load the trailing history the quant engine needs for indicators."""
    return _paginated_select(
        "psx_daily_eod",
        "trade_date,ticker,open_price,high_price,low_price,close_price,volume",
        order_desc_col="trade_date",
        order_asc_col="ticker",
        max_rows=days * 800,  # headroom: ~500 traded symbols x days
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
    """Load recent XXX-FUT closes for the cash & carry arbitrage desk."""
    return _paginated_select(
        "psx_futures_eod",
        "trade_date,ticker,open_price,high_price,low_price,close_price,volume",
        order_desc_col="trade_date",
        order_asc_col="ticker",
        max_rows=days * 150,
    )


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


def fetch_recent_fundamentals() -> list[dict[str, Any]]:
    """Latest screener snapshot per ticker (used by the long-term screen)."""
    return _paginated_select(
        "psx_fundamentals",
        "trade_date,ticker,sector_name,market_cap_pkr,"
        "close_price,pe_ratio,dividend_yield",
        order_desc_col="trade_date",
        order_asc_col="ticker",
        max_rows=3000,
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
