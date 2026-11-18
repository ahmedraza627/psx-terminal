from collections import defaultdict
from datetime import datetime, date
import sqlite3
from typing import Dict, List, Tuple
from pydantic import ValidationError
from src.core.models import DailyBar


def parse_psx_date(raw_date: str) -> date:
    for fmt in ("%Y-%m-%d", "%d%b%Y", "%d-%b-%Y"):
        try:
            return datetime.strptime(raw_date.strip(), fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Unrecognized date format: {raw_date}")


def load_validated_bars(db_path: str) -> Tuple[Dict[str, List[DailyBar]], int]:
    """
    Loads all EOD rows from `daily_eod`, validates them through Pydantic DailyBar,
    and returns (ticker -> sorted DailyBar list, rejected_row_count).
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    rows = cur.execute(
        """
        SELECT ticker, date, open, high, low, close, volume
        FROM daily_eod
        ORDER BY rowid ASC
        """
    ).fetchall()
    conn.close()

    grouped: Dict[str, List[DailyBar]] = defaultdict(list)
    rejected = 0

    for r in rows:
        try:
            bar = DailyBar(
                ticker=r["ticker"],
                trade_date=parse_psx_date(r["date"]),
                open_price=r["open"],
                high_price=r["high"],
                low_price=r["low"],
                close_price=r["close"],
                volume=int(r["volume"] or 0),
            )
            grouped[bar.ticker].append(bar)
        except (ValidationError, ValueError, TypeError):
            rejected += 1

    for ticker in grouped:
        grouped[ticker].sort(key=lambda b: b.trade_date)

    return dict(grouped), rejected