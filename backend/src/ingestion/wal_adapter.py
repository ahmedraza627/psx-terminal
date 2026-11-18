from datetime import date
import sqlite3
from typing import List, Tuple
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
        conn.execute("PRAGMA busy_timeout=10000;")
        conn.row_factory = sqlite3.Row
        return conn

    def ensure_tables(self) -> None:
        conn = self._get_connection()
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS daily_eod (
                    date TEXT NOT NULL,
                    ticker TEXT NOT NULL,
                    sector TEXT,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume INTEGER NOT NULL,
                    turnover REAL NOT NULL,
                    PRIMARY KEY (date, ticker)
                );
                """
            )
        conn.close()

    def upsert_bars(self, bars: List[DailyBar]) -> Tuple[int, int]:
        self.ensure_tables()
        conn = self._get_connection()
        inserted = 0
        quarantined = 0

        try:
            with conn:
                cursor = conn.cursor()
                for bar in bars:
                    try:
                        ticker = bar.ticker
                        trade_date = str(bar.trade_date)
                        sector = getattr(bar, "sector", "EQUITY")
                        open_p = bar.open_price
                        high_p = bar.high_price
                        low_p = bar.low_price
                        close_p = bar.close_price
                        volume = bar.volume
                        turnover = close_p * volume

                        cursor.execute(
                            """
                            INSERT INTO daily_eod (date, ticker, sector, open, high, low, close, volume, turnover)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(date, ticker) DO UPDATE SET
                                sector = excluded.sector,
                                open = excluded.open,
                                high = excluded.high,
                                low = excluded.low,
                                close = excluded.close,
                                volume = excluded.volume,
                                turnover = excluded.turnover;
                            """,
                            (trade_date, ticker, sector, open_p, high_p, low_p, close_p, volume, turnover),
                        )
                        inserted += 1
                    except Exception as e:
                        print(f"QUARANTINED BAR ERROR: {e}")
                        quarantined += 1
        finally:
            conn.close()

        return inserted, quarantined