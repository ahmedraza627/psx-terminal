from datetime import date
import sqlite3
from typing import Dict, Set, Tuple
from src.ingestion.sqlite_adapter import parse_psx_date


def load_institutional_context(db_path: str) -> Tuple[Dict[date, float], Set[Tuple[str, date]]]:
    """
    Loads:
      1. Macro smart-money net flow per date (smart_money_net_pkr from `institutional_flow`)
      2. Institutional NDM block activity set of (ticker, date) from `ndm_blocks`
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    smart_flow_by_date: Dict[date, float] = {}
    for r in cur.execute("SELECT date, smart_money_net_pkr FROM institutional_flow"):
        try:
            dt = parse_psx_date(r["date"])
            smart_flow_by_date[dt] = float(r["smart_money_net_pkr"] or 0.0)
        except (ValueError, TypeError):
            continue

    ndm_activity: Set[Tuple[str, date]] = set()
    for r in cur.execute("SELECT ticker, trade_date FROM ndm_blocks"):
        try:
            dt = parse_psx_date(r["trade_date"])
            ndm_activity.add((r["ticker"].strip().upper(), dt))
        except (ValueError, TypeError):
            continue

    conn.close()
    return smart_flow_by_date, ndm_activity