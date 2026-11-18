from datetime import date
import sqlite3
from typing import Dict, List, Optional, Tuple
from pydantic import ValidationError
from src.core.models import DailyBar


class WALIngestionManager:
    """
    Manages SQLite database connections in WAL mode with idempotent UPSERT transactions.
    """

    def __init__(self, db_path: str):
        self.db_path = db_path

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.row_factory = sqlite3.Row
        return conn

    def ensure_tables(self) -> None:
        conn = self._get_connection()
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS daily_eod (
                    trade_date TEXT NOT NULL,
                    ticker TEXT NOT NULL,
                    sector TEXT,
                    open_price REAL NOT NULL,
                    high_price REAL NOT NULL,
                    low_price REAL NOT NULL,
                    close_price REAL NOT NULL,
                    volume INTEGER NOT NULL,
                    turnover REAL NOT NULL,
                    PRIMARY KEY (trade_date, ticker)
                );
                """
            )
        conn.close()

    def upsert_bars(self, bars: List[DailyBar]) -> Tuple[int, int]:
        """
        Idempotently inserts or updates validated daily bars using a single transaction.
        Returns (inserted_count, quarantined_count).
        """
        self.ensure_tables()
        conn = self._get_connection()
        inserted = 0
        quarantined = 0

        try:
            with conn:
                cursor = conn.cursor()
                for bar in bars:
                    try:
                        cursor.execute(
                            """
                            INSERT INTO daily_eod (trade_date, ticker, sector, open_price, high_price, low_price, close_price, volume, turnover)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(trade_date, ticker) DO UPDATE SET
                                sector = excluded.sector,
                                open_price = excluded.open_price,
                                high_price = excluded.high_price,
                                low_price = excluded.low_price,
                                close_price = excluded.close_price,
                                volume = excluded.volume,
                                turnover = excluded.turnover;
                            """,
                            (
                                str(bar.trade_date),
                                bar.ticker,
                                bar.sector,
                                bar.open_price,
                                bar.high_price,
                                bar.low_price,
                                bar.close_price,
                                bar.volume,
                                bar.turnover,
                            ),
                        )
                        inserted += 1
                    except Exception:
                        quarantined += 1
        finally:
            conn.close()

        return inserted, quarantined