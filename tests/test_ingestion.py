"""Tests for PSX EOD Ingestion and Session Bar Aging.

Verifies:
  1. Synthetic step advances cache dates with realistic drift.
  2. PortfolioLedger aging is idempotent (skip on repeat date).
  3. bars_held increments correctly across advances.
"""

from __future__ import annotations

import csv
import tempfile
import os
from datetime import date
from pathlib import Path

import pytest
from pytest import mark

# --------------------------------------------------------------------------- #
# Test data directory
# --------------------------------------------------------------------------- #

PROJECT_ROOT = Path(__file__).parent.parent
CACHE_DIR = PROJECT_ROOT / "data" / "cache"
INGEST_PSV_CSV = CACHE_DIR / "ohlcv.csv"


# --------------------------------------------------------------------------- #
# Helper: write a minimal OHLCV CSV
# --------------------------------------------------------------------------- #

def _write_ohlcv(rows: list[dict]) -> Path:
    """Write a temporary OHLCV CSV and return the path."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / "ohlcv.csv"
    fieldnames = ["ticker", "date", "open", "high", "low", "close", "volume"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "ticker": row["ticker"],
                    "date": row["date"],
                    "open": row["open"],
                    "high": row["high"],
                    "low": row["low"],
                    "close": row["close"],
                    "volume": row["volume"],
                }
            )
    return path


# --------------------------------------------------------------------------- #
# Import the modules under test
# --------------------------------------------------------------------------- #

from data.ingest_psx import ingest, synthetic_step
from portfolio.ledger import PortfolioLedger


# --------------------------------------------------------------------------- #
# Ingestion tests
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _clean_cache():
    """Ensure a fresh cache for each test."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / "ohlcv.csv"
    if path.exists():
        path.unlink()
    yield
    if path.exists():
        path.unlink()


@pytest.mark.usefixtures("_clean_cache")
class TestIngestionSyntheticStep:
    """--- Part 2: PSX EOD Ingestion -- synthetic-step flag ---"""

    def test_synthetic_step_advances_dates(self):
        """synthetic_step advances all cache dates by one trading session."""
        # Arrange: write a cache with two tickers and a base date
        path = _write_ohlcv(
            [
                {"ticker": "TCFL", "date": "2026-11-04", "open": 10.0, "high": 11.0, "low": 9.5, "close": 10.5, "volume": 100000},
                {"ticker": "BAHL", "date": "2026-11-04", "open": 20.0, "high": 21.0, "low": 19.5, "close": 20.5, "volume": 200000},
            ]
        )

        # Act
        count = synthetic_step()

        # Assert
        assert count == 2, f"Expected 2 rows advanced, got {count}"

        # Read back and verify dates advanced (next trading day = 2026-11-05, Monday)
        from datetime import date
        df_rows = []
        with open(path, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                df_rows.append(
                    {
                        "ticker": row["ticker"],
                        "date": row["date"],
                        "open": float(row["open"]),
                        "high": float(row["high"]),
                        "low": float(row["low"]),
                        "close": float(row["close"]),
                        "volume": int(row["volume"]),
                    }
                )

        # Both dates should have advanced to 2026-11-05 (next trading day)
        for r in df_rows:
            assert r["date"] == "2026-11-05", f"Expected date 2026-11-05, got {r['date']}"
            # Synthetic drift should have been applied to prices
            assert r["open"] != 10.0 or r["close"] != 10.5, (
                f"Expected synthetic drift on prices, got open={r['open']}, close={r['close']}"
            )

    def test_synthetic_step_with_no_cache(self):
        """synthetic_step reports 0 when cache is empty."""
        # Ensure cache is empty (autouse fixture handles this)
        count = synthetic_step()
        assert count == 0, f"Expected 0 rows advanced with empty cache, got {count}"


# --------------------------------------------------------------------------- #
# Ledger aging tests
# --------------------------------------------------------------------------- #


@pytest.mark.usefixtures("_clean_cache")
class TestLedgerAgaging:
    """--- Part 1: Session Aging & DFC Display Guard ---"""

    def test_first_aging_advances_bars_held(self):
        """First time aging a ticker advances bars_held from 0 to 1."""
        ledger = PortfolioLedger(db_path=str(PROJECT_ROOT / "data" / "test_portfolio.db"))

        # Fresh ticker -> first aging should set bars_held=1
        result = ledger.age_session_if_needed(date(2026, 11, 4), "TEST_TICKER")
        assert result is True, "First aging should return True (advanced)"

        bars = ledger.get_bars_held("TEST_TICKER")
        assert bars == 1, f"Expected bars_held=1, got {bars}"

        last_date = ledger.get_last_session_date("TEST_TICKER")
        assert last_date == date(2026, 11, 4), f"Expected last_session_date=2026-11-04, got {last_date}"

    def test_idempotent_skip_on_same_date(self):
        """Running aging twice on the same date skips the second time."""
        ledger = PortfolioLedger(db_path=str(PROJECT_ROOT / "data" / "test_portfolio.db"))

        # First aging
        result1 = ledger.age_session_if_needed(date(2026, 11, 4), "IDEMO_TICKER")
        assert result1 is True, "First aging should advance"

        # Second aging on the same date
        result2 = ledger.age_session_if_needed(date(2026, 11, 4), "IDEMO_TICKER")
        assert result2 is False, "Second aging on same date should be skipped (idempotent)"

        # bars_held should still be 1
        bars = ledger.get_bars_held("IDEMO_TICKER")
        assert bars == 1, f"Expected bars_held=1 after double-run, got {bars}"

    def test_aging_to_newer_date_increments(self):
        """Aging to a newer date increments bars_held again."""
        ledger = PortfolioLedger(db_path=str(PROJECT_ROOT / "data" / "test_portfolio.db"))

        # Age to first date
        ledger.age_session_if_needed(date(2026, 11, 4), "MULTI_TICKER")
        assert ledger.get_bars_held("MULTI_TICKER") == 1

        # Age to a newer date
        ledger.age_session_if_needed(date(2026, 11, 5), "MULTI_TICKER")
        assert ledger.get_bars_held("MULTI_TICKER") == 2, "Bars should increment to 2"

        # Age to yet another newer date
        ledger.age_session_if_needed(date(2026, 11, 6), "MULTI_TICKER")
        assert ledger.get_bars_held("MULTI_TICKER") == 3, "Bars should increment to 3"

    def test_reconcile_batch_idempotent(self):
        """Reconcile batch: some tickers advance, some are skipped."""
        ledger = PortfolioLedger(db_path=str(PROJECT_ROOT / "data" / "test_portfolio.db"))

        # Age two different dates for the same ticker
        ledger.age_session_if_needed(date(2026, 11, 4), "BATCH_TICKER")
        assert ledger.get_bars_held("BATCH_TICKER") == 1

        # Reconcile with mixed tickers: one new, one already aged
        result = ledger.reconcile(date(2026, 11, 4), ["BATCH_TICKER", "NEW_TICKER"])
        assert result["advanced"] == 1, f"Expected 1 advanced, got {result['advanced']}"
        assert result["skipped"] == 1, f"Expected 1 skipped, got {result['skipped']}"

    def test_reconcile_different_dates(self):
        """Reconcile across different dates increments bars_held per session."""
        ledger = PortfolioLedger(db_path=str(PROJECT_ROOT / "data" / "test_portfolio.db"))

        # Session 1
        ledger.reconcile(date(2026, 11, 4), ["CDR_TICKER"])
        assert ledger.get_bars_held("CDR_TICKER") == 1

        # Session 2 (newer date)
        ledger.reconcile(date(2026, 11, 5), ["CDR_TICKER"])
        assert ledger.get_bars_held("CDR_TICKER") == 2, "Bars should be 2 after second session"

        # Session 3 (same date - should be idempotent)
        ledger.reconcile(date(2026, 11, 5), ["CDR_TICKER"])
        assert ledger.get_bars_held("CDR_TICKER") == 2, "Bars should stay 2 (idempotent on same date)"


# --------------------------------------------------------------------------- #
# DFC Display Sentinel test
# --------------------------------------------------------------------------- #


from pipeline.dispatch import format_dfc_sl


class TestDfcDisplaySentinel:
    """--- DFC Display Sentinel formatting ---"""

    def test_open_hedged_format(self):
        """SL: 1.00 sentinel formats as SL: OPEN (SPREAD_HEDGED)."""
        result = format_dfc_sl(1.00, kind="open_hedged")
        assert result == "SL: OPEN (SPREAD_HEDGED)", f"Expected pill format, got '{result}'"

    def test_regular_stop_loss_format(self):
        """Regular stop-loss prices format as SL: <price>."""
        result = format_dfc_sl(0.85, kind="open_hedged")
        assert result == "SL: 0.85", f"Expected price format, got '{result}'"

    def test_none_formats_as_dash(self):
        """None values format as '-'."""
        result = format_dfc_sl(None, kind="open_hedged")
        assert result == "-", f"Expected dash, got '{result}'"

    def test_different_kind_still_works(self):
        """format_dfc_sl with non-matching kind still renders the price."""
        result = format_dfc_sl(1.00, kind="flat")
        # 1.00 with kind="flat" should not trigger the open_hedged pill format
        assert result == "SL: 1.00", f"Expected SL: 1.00, got '{result}'"