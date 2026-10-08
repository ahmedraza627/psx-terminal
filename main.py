#!/usr/bin/env python3
"""PSX / NCCPL intelligence pipeline - CLI coordinator.

Daily flow (GitHub Actions cron, Mon-Fri 13:30 UTC / 18:30 PKT):
  1. Scrape the full-market EOD snapshot            -> psx_daily_eod
  2. Scrape NCCPL FIPI/LIPI participant flows       -> nccpl_fipi_lipi
  3. Scrape NDM negotiated block deals              -> psx_offmarket_deals
                                                       + psx_offmarket_summary
  4. Scrape the DPS screener fundamentals           -> psx_fundamentals
  5. Backfill indicator history on the first run    -> psx_daily_eod
  6. Run the quant engine                           -> signals_computed

Each step degrades gracefully: one source failing never blocks the rest,
and the run exits non-zero only when the core EOD step fails.

Usage:
  python main.py                    # today's full run
  python main.py --date 2026-09-10  # label a specific session
  python main.py --skip-flows --skip-offmarket --skip-fundamentals
  python main.py --force-backfill   # re-pull 3 months of history
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, datetime, timedelta
from typing import Optional

from pipeline import db
from pipeline.analytics.decision_engine import run_decision_engine
from pipeline.analytics.quant_engine import run_quant_engine
from pipeline.scrapers.nccpl_flows import fetch_recent_flows
from pipeline.scrapers.nccpl_mts import fetch_mts_exposure
from pipeline.scrapers.psx_eod import backfill_history, fetch_eod
from pipeline.scrapers.psx_fundamentals import fetch_screener, fetch_sector_map
from pipeline.scrapers.psx_financials import scrape_financials_for_universe
from pipeline.scrapers.psx_futures import fetch_futures_contracts
from pipeline.scrapers.psx_insider import fetch_insider_trades
from pipeline.scrapers.psx_offmarket import (
    fetch_ndm_summary_row,
    fetch_offmarket_deals,
)
from pipeline.scrapers.macro_indicators import collect_macro_rows
from pipeline.analytics.quant_signals import run_daily_quant_signals

LOGGER = logging.getLogger("pipeline")

BACKFILL_TICKERS = 150   # most liquid tickers to seed history for
BACKFILL_MONTHS = 3      # enough for the 50-day EMA window


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the PSX/NCCPL ingestion + quant pipeline."
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Session date to label records with (ISO, default: today).",
    )
    parser.add_argument("--skip-eod", action="store_true", help="Skip EOD scrape.")
    parser.add_argument("--skip-flows", action="store_true", help="Skip NCCPL flows.")
    parser.add_argument(
        "--skip-offmarket", action="store_true", help="Skip NDM block deals."
    )
    parser.add_argument(
        "--skip-futures", action="store_true", help="Skip futures board scrape."
    )
    parser.add_argument(
        "--skip-insider", action="store_true", help="Skip insider disclosures."
    )
    parser.add_argument(
        "--skip-mts", action="store_true", help="Skip NCCPL MTS exposure."
    )
    parser.add_argument(
        "--skip-fundamentals", action="store_true", help="Skip screener scrape."
    )
    parser.add_argument(
        "--skip-financials",
        action="store_true",
        help="Skip DPS company-page quarterly financials.",
    )
    parser.add_argument(
        "--skip-research",
        action="store_true",
        help="Skip the fundamental research (alpha score) engine.",
    )
    parser.add_argument(
        "--skip-rotation",
        action="store_true",
        help="Skip the sector rotation (RRG) engine.",
    )
    parser.add_argument(
        "--skip-kibor",
        action="store_true",
        help="Skip the KIBOR easing sensitivity engine.",
    )
    parser.add_argument(
        "--skip-macro",
        action="store_true",
        help="Skip global macro indicator ingestion + correlation engine.",
    )
    parser.add_argument(
        "--skip-signals", action="store_true", help="Skip the quant engine."
    )
    parser.add_argument(
        "--skip-backtest",
        action="store_true",
        help="Skip historical edge backtesting of prior signals.",
    )
    parser.add_argument(
        "--skip-risk",
        action="store_true",
        help="Skip risk/position sizing of the session book.",
    )
    parser.add_argument(
        "--equity",
        type=float,
        default=float(os.getenv("PORTFOLIO_EQUITY_PKR", "5000000")),
        help="Portfolio equity in PKR for position sizing (default 5m).",
    )
    parser.add_argument(
        "--force-backfill",
        action="store_true",
        help="Backfill 3 months of OHLCV history for liquid tickers.",
    )
    parser.add_argument(
        "--min-block-volume",
        type=int,
        default=None,
        help="Minimum NDM share volume to record as a block deal.",
    )
    return parser.parse_args(argv)


def _table_is_empty(table: str) -> bool:
    """True when the table has no rows yet (triggers first-run backfill)."""
    try:
        response = db.get_client().table(table).select("id", count="exact").limit(1).execute()
        return (response.count or 0) == 0
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("could not count %s (%s); assuming non-empty", table, exc)
        return False


def _step(name: str):
    """Decorator-style context that isolates one pipeline step's failures."""
    class _Step:
        def __enter__(self):
            LOGGER.info("=== %s ===", name)
            return self

        def __exit__(self, exc_type, exc, tb):
            if exc_type is not None:
                LOGGER.error("%s failed: %s", name, exc)
                return True  # swallow: next steps still run
            return False

    return _Step()


def _latest_active_session() -> Optional[date]:
    """Latest trade_date in psx_daily_eod with any volume > 0.

    PSX serves the market snapshot even on closed days (zero volumes), so
    the active trading session is detected by volume - never by the wall
    clock. Weekend/holiday runs therefore target the last real session.
    """
    try:
        response = (
            db.get_client()
            .table("psx_daily_eod")
            .select("trade_date,volume")
            .order("trade_date", desc=True)
            .limit(2000)  # covers several sessions x ~500 tickers
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("could not resolve latest active session: %s", exc)
        return None

    best: Optional[date] = None
    for row in response.data or []:
        if (row.get("volume") or 0) > 0:
            try:
                parsed = datetime.strptime(
                    str(row["trade_date"])[:10], "%Y-%m-%d"
                ).date()
            except ValueError:
                continue
            # PSX never trades Sat/Sun; a weekend-stamped date is always
            # a restamped snapshot from a closed-day run, never a session.
            if parsed.weekday() >= 5:
                continue
            if best is None or parsed > best:
                best = parsed
    return best


def run(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    _setup_logging()

    trade_date = (
        datetime.strptime(args.date, "%Y-%m-%d").date()
        if args.date
        else date.today()
    )
    LOGGER.info("pipeline run for requested date %s", trade_date)

    min_block_volume = args.min_block_volume
    if min_block_volume is None:
        import os

        min_block_volume = int(os.getenv("OFFMARKET_MIN_VOLUME", "10000"))

    eod_records: list[dict] = []
    core_ok = True
    market_active_today = False

    # ------------------------------------------------------------------ #
    # 1. EOD snapshot (core step - failure aborts the run)               #
    # ------------------------------------------------------------------ #
    first_run = _table_is_empty("psx_daily_eod")
    if not args.skip_eod:
        written = 0
        with _step("EOD market snapshot"):
            eod_records = fetch_eod(trade_date)
            written = db.upsert_records(
                "psx_daily_eod", eod_records, on_conflict="trade_date,ticker"
            )
            LOGGER.info("psx_daily_eod: %d rows written", written)
        if eod_records and written == 0:
            # Scrape succeeded but NOTHING committed: the table is rejecting
            # the payload (schema drift). Fail the run loudly - a silently
            # stale psx_daily_eod is the worst possible state.
            LOGGER.error(
                "psx_daily_eod: scraped %d rows but wrote 0 - schema drift "
                "or permission failure; apply migrations/002_psx_daily_eod_repair.sql",
                len(eod_records),
            )
            core_ok = False
        elif not eod_records:
            # Source unavailable (blocked, down, or the session file is not
            # published yet). NOT immediately fatal: session resolution
            # below falls back to the latest verified stored session and
            # the exit-policy block (1c) decides the exit code.
            LOGGER.warning(
                "EOD snapshot unavailable for %s (source down or session "
                "not yet published) - falling back to stored sessions",
                trade_date,
            )
        else:
            market_active_today = any(
                (r.get("volume") or 0) > 0 for r in eod_records
            )
    else:
        LOGGER.info("EOD scrape skipped by flag")

    # ------------------------------------------------------------------ #
    # 1b. Session resolution: never target a dead session. If today's    #
    # market is closed (weekend/holiday) or the snapshot shows zero      #
    # volume, fall back to the latest stored session with activity.      #
    # ------------------------------------------------------------------ #
    if market_active_today:
        target_session_date = trade_date
    else:
        # The snapshot served on a closed day is the last real session's
        # data restamped with today's dead date - remove it so history
        # stays clean and session resolution cannot pick it.
        if eod_records and trade_date.weekday() >= 5:
            try:
                db.get_client().table("psx_daily_eod").delete().eq(
                    "trade_date", trade_date.isoformat()
                ).execute()
                LOGGER.info(
                    "removed %d restamped closed-day rows for %s",
                    len(eod_records),
                    trade_date,
                )
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("closed-day cleanup failed: %s", exc)
        resolved = _latest_active_session()
        target_session_date = resolved if resolved is not None else trade_date
        if target_session_date != trade_date:
            LOGGER.warning(
                "market inactive for %s (closed or zero volume); engine "
                "targets last active session %s from psx_daily_eod",
                trade_date,
                target_session_date,
            )

    # ------------------------------------------------------------------ #
    # 1c. Exit policy: today's EOD file being unavailable is not fatal   #
    # when a verified stored session exists to process. The run exits    #
    # non-zero only when there is NOTHING verifiable to compute on.      #
    # ------------------------------------------------------------------ #
    if not args.skip_eod and not eod_records:
        min_verified_rows = int(os.getenv("MIN_VERIFIED_SESSION_ROWS", "50"))
        try:
            probe = (
                db.get_client()
                .table("psx_daily_eod")
                .select("volume")
                .eq("trade_date", target_session_date.isoformat())
                .execute()
            )
            verified_rows = sum(
                1 for r in (probe.data or []) if (r.get("volume") or 0) > 0
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("verified-session probe failed: %s", exc)
            verified_rows = 0
        if verified_rows >= min_verified_rows:
            LOGGER.warning(
                "session-verified mode: today's snapshot unavailable; "
                "proceeding on stored session %s (%d live rows)",
                target_session_date,
                verified_rows,
            )
        else:
            LOGGER.error(
                "no verified market session available: today's scrape "
                "failed AND stored session %s has only %d live rows "
                "(floor %d) - nothing to compute on",
                target_session_date,
                verified_rows,
                min_verified_rows,
            )
            core_ok = False

    # ------------------------------------------------------------------ #
    # 2. NCCPL participant flows                                         #
    # ------------------------------------------------------------------ #
    if not args.skip_flows:
        with _step("NCCPL FIPI/LIPI flows"):
            flow_rows = fetch_recent_flows(days=6, today=trade_date)
            if flow_rows:
                written = db.upsert_records(
                    "nccpl_fipi_lipi",
                    flow_rows,
                    on_conflict="trade_date,participant_type,sector_name",
                )
                LOGGER.info("nccpl_fipi_lipi: %d rows written", written)
            else:
                LOGGER.warning("no flow rows collected (holidays or source down)")

    # ------------------------------------------------------------------ #
    # 3. NDM negotiated block deals (needs today's closes for valuation) #
    # ------------------------------------------------------------------ #
    if not args.skip_offmarket:
        with _step("NDM off-market deals"):
            # Session aggregate first: the certified NDM facts PSX still
            # publishes (trades / volume / turnover) land in
            # psx_offmarket_summary even when no per-symbol rows or stored
            # closes exist. One panel GET feeds both this and the deals
            # fetch below (snapshot memoized per process).
            summary = fetch_ndm_summary_row(trade_date)
            if summary is not None:
                written = db.upsert_records(
                    "psx_offmarket_summary", [summary], on_conflict="trade_date"
                )
                LOGGER.info("psx_offmarket_summary: %d row written", written)

            if eod_records:
                close_prices = {
                    r["ticker"]: float(r["close_price"])
                    for r in eod_records
                    if r.get("close_price")
                }
                deals = fetch_offmarket_deals(
                    trade_date,
                    close_prices=close_prices,
                    min_volume=min_block_volume,
                )
            else:
                LOGGER.info(
                    "NDM per-deal valuation skipped (no stored closes this session)"
                )
                deals = []
            if deals:
                # The table has no unique key; drop tickers already recorded
                # for this date so workflow re-runs never duplicate blocks.
                existing = (
                    db.get_client()
                    .table("psx_offmarket_deals")
                    .select("ticker")
                    .eq("trade_date", trade_date.isoformat())
                    .execute()
                )
                seen = {r["ticker"] for r in (existing.data or [])}
                deals = [d for d in deals if d["ticker"] not in seen]
            if deals:
                db.get_client().table("psx_offmarket_deals").insert(deals).execute()
                LOGGER.info("psx_offmarket_deals: %d rows inserted", len(deals))
            else:
                LOGGER.info("no NDM block deals above %d shares", min_block_volume)

    # ------------------------------------------------------------------ #
    # 3b. Deliverable futures board (arbitrage desk legs)                #
    # ------------------------------------------------------------------ #
    if not args.skip_futures:
        with _step("PSX deliverable futures board"):
            futures = fetch_futures_contracts(trade_date)
            if futures:
                written = db.upsert_futures_rows(futures)
                LOGGER.info("psx_futures_eod: %d rows written", written)
            else:
                LOGGER.warning(
                    "psx_futures_eod: no contracts retrieved; arbitrage desk "
                    "stays empty (no fabricated spreads)"
                )

    # ------------------------------------------------------------------ #
    # 3c. SECP insider / sponsor disclosures (board letters)             #
    # ------------------------------------------------------------------ #
    if not args.skip_insider:
        with _step("SECP insider disclosures"):
            insider_rows = fetch_insider_trades(target_session_date)
            if insider_rows:
                written = db.upsert_records(
                    "psx_insider_trades",
                    insider_rows,
                    on_conflict="trade_date,ticker,insider_name,quantity,trade_type",
                )
                LOGGER.info("psx_insider_trades: %d rows written", written)
                from pipeline.scrapers.psx_insider import build_disclosure_ledger

                ledger = build_disclosure_ledger(insider_rows)
                if ledger:
                    try:
                        led_written = db.upsert_records(
                            "psx_insider_disclosures",
                            ledger,
                            on_conflict=(
                                "trade_date,ticker,insider_name,quantity,trade_type"
                            ),
                        )
                        LOGGER.info(
                            "psx_insider_disclosures: %d rows written",
                            led_written,
                        )
                    except Exception as exc:  # noqa: BLE001
                        if "PGRST205" in str(exc) or "schema cache" in str(exc):
                            LOGGER.warning(
                                "psx_insider_disclosures missing - apply schema.sql"
                            )
                        else:
                            raise
            else:
                LOGGER.warning(
                    "psx_insider_trades: no parseable disclosures; "
                    "INSIDER_RADAR stays idle"
                )

    # ------------------------------------------------------------------ #
    # 3d. NCCPL MTS leverage exposure                                    #
    # ------------------------------------------------------------------ #
    if not args.skip_mts:
        with _step("NCCPL MTS exposure"):
            mts_rows = fetch_mts_exposure(target_session_date)
            if mts_rows:
                written = db.upsert_records(
                    "nccpl_mts_leverage",
                    mts_rows,
                    on_conflict="trade_date,ticker",
                )
                LOGGER.info("nccpl_mts_leverage: %d rows written", written)
            else:
                LOGGER.warning(
                    "nccpl_mts_leverage: sources blocked or unparsable; "
                    "MTS_SQUEEZE stays idle"
                )

    # ------------------------------------------------------------------ #
    # 4. Fundamentals snapshot (screener + sector map)                   #
    # ------------------------------------------------------------------ #
    if not args.skip_fundamentals:
        with _step("DPS screener fundamentals"):
            sector_map = {}
            try:
                sector_map = fetch_sector_map()
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("sector map unavailable (%s); proceeding", exc)
            fundamentals = fetch_screener(trade_date, sector_map=sector_map)
            written = db.upsert_records(
                "psx_fundamentals", fundamentals, on_conflict="trade_date,ticker"
            )
            LOGGER.info("psx_fundamentals: %d rows written", written)

    # ------------------------------------------------------------------ #
    # 5. First-run / forced backfill of indicator history                #
    # ------------------------------------------------------------------ #
    # ------------------------------------------------------------------
    # 4b. Quarterly financials from DPS company pages (research layer)   #
    # ------------------------------------------------------------------
    if not args.skip_financials:
        with _step("DPS company financials"):
            universe = sorted(
                (r for r in eod_records if r.get("volume")),
                key=lambda r: int(r["volume"] or 0),
                reverse=True,
            )
            max_tickers = int(os.getenv("FINANCIALS_MAX_TICKERS", "80"))
            seed = [r["ticker"] for r in universe[:max_tickers]]
            if seed:
                ratio_rows = scrape_financials_for_universe(
                    seed, max_tickers=max_tickers
                )
                if ratio_rows:
                    written = db.upsert_financial_ratios(ratio_rows)
                    LOGGER.info("psx_financial_ratios: %d rows written", written)
                else:
                    LOGGER.warning("psx_financial_ratios: no periods parsed")

    if eod_records and (args.force_backfill or first_run):
        tickers = sorted(
            (r for r in eod_records if r.get("volume")),
            key=lambda r: int(r["volume"] or 0),
            reverse=True,
        )
        seed = [r["ticker"] for r in tickers[:BACKFILL_TICKERS]]
        LOGGER.info(
            "backfilling %d months of history for %d liquid tickers",
            BACKFILL_MONTHS, len(seed),
        )
        history = backfill_history(seed, months=BACKFILL_MONTHS, today=trade_date)
        if history:
            written = db.upsert_records(
                "psx_daily_eod", history, on_conflict="trade_date,ticker"
            )
            LOGGER.info("backfill: %d historical rows written", written)

    # ------------------------------------------------------------------ #
    # 6. Quant engine -> signals_computed                                #
    # ------------------------------------------------------------------ #
    if not args.skip_signals:
        if core_ok or not args.skip_eod:
            with _step("quant engine"):
                run_quant_engine(session_date=target_session_date)
            with _step("daily quant signals"):
                counts = run_daily_quant_signals(target_session_date)
                LOGGER.info(
                    "daily quant signals: volume_expansion=%d institutional_accumulation=%d "
                    "retail_trap_short=%d market_breadth=%d written=%d",
                    counts["volume_expansion"],
                    counts["institutional_accumulation"],
                    counts["retail_trap_short"],
                    counts["market_breadth"],
                    counts["written"],
                )
            with _step("system decision engine"):
                verdicts_written = run_decision_engine(
                    session_date=target_session_date
                )
                LOGGER.info("system verdicts: %d rows written", verdicts_written)
        else:
            LOGGER.warning("skipping quant engine: core EOD data unavailable")
    else:
        LOGGER.info("quant engine skipped by flag")

    # ------------------------------------------------------------------ #
    # 7. Historical edge backtester (evaluate matured prior signals)     #
    # ------------------------------------------------------------------ #
    # ------------------------------------------------------------------
    # 6b. Fundamental research engine -> psx_equity_research             #
    # ------------------------------------------------------------------
    if not args.skip_research:
        with _step("fundamental research engine"):
            from pipeline.analytics.fundamental_engine import run_fundamental_engine

            run_fundamental_engine(session_date=target_session_date)

    # ------------------------------------------------------------------
    # 6c. Sector rotation (RRG) -> psx_sector_rotation                   #
    # ------------------------------------------------------------------
    if not args.skip_rotation:
        with _step("sector rotation engine"):
            from pipeline.analytics.sector_rotation import run_sector_rotation

            run_sector_rotation(session_date=target_session_date)

    # ------------------------------------------------------------------
    # 6d. KIBOR easing sensitivity -> psx_kibor_sensitivity              #
    # ------------------------------------------------------------------
    if not args.skip_kibor:
        with _step("KIBOR sensitivity engine"):
            from pipeline.analytics.kibor_engine import run_kibor_engine

            run_kibor_engine(session_date=target_session_date)

    # ------------------------------------------------------------------
    # 6e. Global macro & commodity correlation / prediction engine
    # ------------------------------------------------------------------
    if not args.skip_macro:
        with _step("global macro correlation engine"):
            macro_rows = collect_macro_rows(days=450)
            if macro_rows:
                written = db.upsert_records(
                    "psx_macro_indicator_prices",
                    macro_rows,
                    on_conflict="driver_code,trade_date",
                )
                LOGGER.info("psx_macro_indicator_prices: %d rows written", written)
            else:
                LOGGER.warning("psx_macro_indicator_prices: no macro rows collected")
            from pipeline.analytics.macro_engine import run_macro_engine

            run_macro_engine(session_date=target_session_date)

    if not args.skip_backtest:
        with _step("signal backtester"):
            from pipeline.analytics.backtester import run_backtester

            run_backtester()

    # ------------------------------------------------------------------ #
    # 8. Risk engine: size the session book (log + terminal summary)     #
    # ------------------------------------------------------------------ #
    if not args.skip_risk:
        with _step("risk engine"):
            from pipeline.analytics.risk_engine import size_session_book

            book = size_session_book(equity_pkr=args.equity)
            totals = book["totals"]
            LOGGER.info(
                "book: %d positions | deployed %s PKR (%.1f%% equity) | "
                "heat %.2f%% | %d rejected",
                totals["positions"],
                f"{totals['deployed_value_pkr']:,.0f}",
                totals["deployed_pct_of_equity"],
                totals["portfolio_heat_pct"],
                len(book["rejected"]),
            )
            for position in book["positions"]:
                LOGGER.info(
                    "  size %s %-22s shares=%-8d entry=%-9.2f stop=%-9.2f "
                    "risk=%.1f%% equity",
                    (position.get("conviction") or "-")[:9],
                    position["ticker"],
                    position["shares"],
                    position["entry_reference"],
                    position["stop_loss"],
                    position["risk_pct_of_equity"],
                )

    LOGGER.info(
        "pipeline run finished (requested=%s, session=%s, core_ok=%s)",
        trade_date,
        target_session_date,
        core_ok,
    )
    return 0 if core_ok else 1


if __name__ == "__main__":
    sys.exit(run())
