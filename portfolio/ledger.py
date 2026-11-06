"""Portfolio Ledger with idempotent daily session aging guard.

PortfolioLedger tracks per-position bars_held and enforces that the daily
session aging (incrementing bars_held) happens exactly once per calendar day.

The aging state is stored in a lightweight SQLite metadata table so that
the --reconcile CLI command can safely re-run without double-incrementing.
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import date
from logging import getLogger
from pathlib import Path
from typing import Optional, Sequence

LOGGER = getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

SQL_CREATE_METADATA = """
CREATE TABLE IF NOT EXISTS portfolio_metadata (
    ticker TEXT NOT NULL,
    last_session_date DATE NOT NULL,
    bars_held INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (ticker)
);
"""

SQL_GET_LAST_SESSION = """
SELECT last_session_date, bars_held FROM portfolio_metadata WHERE ticker = ?;
"""

# ---------------------------------------------------------------------------
# PortfolioLedger
# ---------------------------------------------------------------------------


class PortfolioLedger:
    """Manages per-ticker session aging and bars_held counting.

    The aging guard is idempotent: running --reconcile on the same date
    twice will skip the aging on the second run because ``last_session_date``
    will already equal the target date.

    When --reconcile is run for a date greater than last_session_date,
    update_daily_bars() is executed once, incrementing bars_held by 1
    across all active positions. This enables the Event Pod's 10-session
    TIME_STOP_EXPIRED to trigger correctly.
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        """Initialize the ledger.

        Parameters
        ----------
        db_path: path to SQLite database file. Defaults to
                 ./data/portfolio.db relative to the project root.
        """
        if db_path is None:
            project_root = Path(__file__).parent.parent
            db_path = str(project_root / "data" / "portfolio.db")

        self.db_path = db_path
        self._init_db()

    # ------------------------------------------------------------------
    # Database initialization
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        """Create the metadata table if it does not exist."""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(SQL_CREATE_METADATA)
            conn.commit()
            LOGGER.info("Portfolio metadata table initialised at %s", self.db_path)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Core aging guard
    # ------------------------------------------------------------------

    def get_last_session_date(self, ticker: str) -> Optional[date]:
        """Return the last aged session date for *ticker*, or ``None`` if unknown."""
        conn = sqlite3.connect(self.db_path)
        try:
            row = conn.execute(SQL_GET_LAST_SESSION, (ticker,)).fetchone()
            if row is None:
                return None
            return date.fromisoformat(row[0])
        finally:
            conn.close()

    def get_bars_held(self, ticker: str) -> Optional[int]:
        """Return the current ``bars_held`` count for *ticker*."""
        conn = sqlite3.connect(self.db_path)
        try:
            row = conn.execute(SQL_GET_LAST_SESSION, (ticker,)).fetchone()
            if row is None:
                return None
            return int(row[1])
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Idempotent: age one ticker's session if target date is newer
    # ------------------------------------------------------------------

    def age_session_if_needed(self, target_date: date, ticker: str) -> bool:
        """Age one ticker's session if the target date is newer than last_session_date.

        Returns ``True`` if aging was performed, ``False`` if already up to date
        (idempotent guard).
        """
        if not isinstance(target_date, date):
            raise TypeError("target_date must be a datetime.date")

        conn = sqlite3.connect(self.db_path)
        try:
            # Get current state
            row = conn.execute(SQL_GET_LAST_SESSION, (ticker,)).fetchone()

            if row is None:
                # First time: insert with bars_held=1 and last_session_date=target_date
                conn.execute(
                    "INSERT INTO portfolio_metadata (ticker, last_session_date, bars_held) VALUES (?, ?, ?)",
                    (ticker, target_date.isoformat(), 1),
                )
                conn.commit()
                LOGGER.info("First-time aging for %s to session %s", ticker, target_date)
                return True

            last_date = date.fromisoformat(row[0])
            current_bars = int(row[1])

            if target_date <= last_date:
                # Already aged for this or a past session – idempotent skip
                LOGGER.debug(
                    "Skipping aging for %s: target %s <= last %s",
                    ticker,
                    target_date,
                    last_date,
                )
                return False

            # Target date is newer: increment bars_held by 1
            new_bars = current_bars + 1
            conn.execute(
                "UPDATE portfolio_metadata SET last_session_date = ?, bars_held = ? WHERE ticker = ?",
                (target_date.isoformat(), new_bars, ticker),
            )
            LOGGER.info(
                " aged session for %s: %s -> bars_held=%d (was %d)",
                ticker,
                target_date,
                new_bars,
                current_bars,
            )
            conn.commit()
            return True
        except Exception as exc:  # noqa: BLE001
            conn.rollback()
            LOGGER.error("Failed to age session for %s: %s", ticker, exc)
            raise
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Batch reconcile: age one session for many tickers
    # ------------------------------------------------------------------

    def reconcile(self, target_date: date, tickers: Sequence[str]) -> dict:
        """Reconcile one session date across many tickers.

        Idempotent: running ``reconcile`` multiple times on the same date
        will skip aging on the second pass (strict idempotency).

        Parameters
        ----------
        target_date: the session date to age up to.
        tickers: sequence of ticker symbols to process.

        Returns
        -------
        dict with keys ``advanced`` (count of tickers incremented) and
        ``skipped`` (count of tickers already at this date).
        """
        if not isinstance(target_date, date):
            raise TypeError("target_date must be a datetime.date")

        advanced = 0
        skipped = 0
        conn = sqlite3.connect(self.db_path)
        try:
            for ticker in tickers:
                if self.age_session_if_needed(target_date, ticker):
                    advanced += 1
                else:
                    skipped += 1
            conn.commit()
        except Exception as exc:  # noqa: BLE001
            conn.rollback()
            LOGGER.error("Reconcile failed: %s", exc)
            raise
        finally:
            conn.close()

        LOGGER.info(
            "Reconcile for %s: advanced=%d, skipped=%d",
            target_date,
            advanced,
            skipped,
        )
        return {"advanced": advanced, "skipped": skipped}


# ---------------------------------------------------------------------------
# CLI helper
# ---------------------------------------------------------------------------


def _cli() -> None:
    """CLI entry point for ``portfolio ledger --reconcile YYYY-MM-DD``."""
    from datetime import date as _d

    import argparse

    parser = argparse.ArgumentParser(
        description="Portfolio ledger: reconcile session aging guard."
    )
    parser.add_argument(
        "date",
        type=str,
        help="Target session date YYYY-MM-DD to age up to.",
    )
    parser.add_argument(
        "--tickers",
        type=str,
        nargs="+",
        default=[],
        help="Tickers to age (default: all in metadata).",
    )
    args = parser.parse_args()

    target = _d.fromisoformat(args.date)
    ledger = PortfolioLedger()

    # If no tickers specified, discover them from the database
    if args.tickers:
        result = ledger.reconcile(target, args.tickers)
    else:
        # Discover tickers from the metadata table
        conn = sqlite3.connect(ledger.db_path)
        try:
            rows = conn.execute("SELECT DISTINCT ticker FROM portfolio_metadata").fetchall()
            tickers = [r[0] for r in rows]
        finally:
            conn.close()
        result = ledger.reconcile(target, tickers)

        print(f"Reconcile for {target}:")
        print(f"  Advanced: {result['advanced']}")
        print(f"  Skipped (already up to date): {result['skipped']}")


if __name__ == "__main__":
    _cli()