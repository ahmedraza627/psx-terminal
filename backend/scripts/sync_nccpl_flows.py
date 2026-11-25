#!/usr/bin/env python3
"""sync_nccpl_flows.py - NCCPL FIPI/LIPI sector flows -> data/portfolio.db.

Stores the participant x sector net buy/sell table the desk reads for
institutional absorption and distribution alerts:

    nccpl_flows(trade_date, participant_type, sector_name,
                buy_pkr, sell_pkr, net_pkr, source, ingested_at)

Source: the scstrade mirror of NCCPL (pipeline.scrapers.nccpl_flows), which
returns USD-million values converted to PKR at the free USD/PKR rate. Sessions
are taken from the stored PSX tape so a flow row always lines up with a session
the desk actually traded. `--file` ingests a previously exported JSON list for
offline/CI replay; nothing is interpolated - a missing session simply stays
missing.

Run it
------
python backend/scripts/sync_nccpl_flows.py --days 12
python backend/scripts/sync_nccpl_flows.py --file nccpl_flows_export.json
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
BASE_DIR = BACKEND_DIR.parent
sys.path.insert(0, str(BASE_DIR))               # pipeline.* imports
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from quant_modules import _iso_day  # noqa: E402

DB_PATH = BASE_DIR / "data" / "portfolio.db"
FX_FALLBACK = 278.5
LOG = logging.getLogger("sync_nccpl_flows")

SCHEMA = ("CREATE TABLE IF NOT EXISTS nccpl_flows ("
          "trade_date TEXT NOT NULL, participant_type TEXT NOT NULL, sector_name TEXT NOT NULL, "
          "buy_pkr REAL, sell_pkr REAL, net_pkr REAL NOT NULL, source TEXT, "
          "ingested_at TEXT NOT NULL DEFAULT (datetime('now')), "
          "PRIMARY KEY (trade_date, participant_type, sector_name))")
INDEX = ("CREATE INDEX IF NOT EXISTS nccpl_flows_date_sector_idx "
         "ON nccpl_flows (trade_date DESC, sector_name)")
INSERT = ("INSERT OR REPLACE INTO nccpl_flows "
          "(trade_date, participant_type, sector_name, buy_pkr, sell_pkr, net_pkr, source) "
          "VALUES (?,?,?,?,?,?,?)")


def ensure_table(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute(SCHEMA)
    cur.execute(INDEX)
    conn.commit()


def tape_sessions(conn: sqlite3.Connection, days: int) -> list[date]:
    """Last `days` stored PSX sessions, oldest first (they are what flows attach to)."""
    rows = [r[0] for r in conn.execute("SELECT DISTINCT trade_date FROM psx_daily_eod")]
    parsed = []
    for stamp in rows:
        try:
            parsed.append(datetime.strptime(str(stamp), "%d%b%Y").date())
        except ValueError:
            continue
    return sorted(parsed)[-days:]


def ingest(conn: sqlite3.Connection, rows: list[dict], source: str) -> int:
    """Upsert sector-flow rows; rows without a sector or net are dropped."""
    cur, written = conn.cursor(), 0
    for row in rows:
        try:
            day = _iso_day(row["trade_date"])
            participant = str(row["participant_type"]).strip().upper()
            sector = str(row["sector_name"]).strip().upper()
            net = float(row["net_pkr"])
        except (KeyError, TypeError, ValueError):
            continue
        if not day or not participant or not sector:
            continue
        cur.execute(INSERT, (day, participant, sector, row.get("buy_pkr"), row.get("sell_pkr"),
                             net, source))
        written += 1
    conn.commit()
    return written


def _fetch_day(day: date, fx: float) -> list[dict]:
    from pipeline.scrapers.nccpl_flows import fetch_sector_flows_for_date
    return fetch_sector_flows_for_date(day, fx=fx)


def _fx_rate() -> float:
    try:
        from pipeline.scrapers.nccpl_flows import fetch_usd_pkr
        return fetch_usd_pkr(fallback=FX_FALLBACK)
    except Exception as exc:  # noqa: BLE001
        LOG.warning("FX lookup unavailable (%s); using %.1f", exc, FX_FALLBACK)
        return FX_FALLBACK


def sync(db_path: Path = DB_PATH, days: int = 12, offline_file: Path | None = None,
         fx: float | None = None) -> dict:
    """Pull the last `days` tape sessions (or an offline export) into nccpl_flows."""
    conn = sqlite3.connect(db_path)
    ensure_table(conn)

    if offline_file is not None:
        rows = json.loads(Path(offline_file).read_text(encoding="utf-8"))
        written = ingest(conn, rows, "file")
        conn.close()
        return {"sessions": len({r.get("trade_date") for r in rows}), "rows": written,
                "source": "file"}

    rate = fx if fx is not None else _fx_rate()
    sessions = tape_sessions(conn, days)
    written, fetched = 0, 0
    for day in sessions:
        try:
            rows = _fetch_day(day, rate)
        except Exception as exc:  # noqa: BLE001 - a blocked/quiet session must not abort the run
            LOG.warning("NCCPL sector flows unavailable for %s (%s)", day, exc)
            continue
        if not rows:
            continue
        fetched += 1
        written += ingest(conn, rows, "scstrade")
    stored = conn.execute("SELECT COUNT(*), COUNT(DISTINCT trade_date) FROM nccpl_flows").fetchone()
    conn.close()
    return {"sessions": fetched, "rows": written, "storedRows": stored[0],
            "storedSessions": stored[1], "source": "scstrade", "fx": rate}


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")
    parser = argparse.ArgumentParser(description="Ingest NCCPL FIPI/LIPI sector flows")
    parser.add_argument("--db", default=str(DB_PATH), help="SQLite store")
    parser.add_argument("--days", type=int, default=12, help="tape sessions to fetch")
    parser.add_argument("--file", help="offline JSON export of sector-flow rows")
    parser.add_argument("--fx", type=float, default=None, help="override USD/PKR")
    args = parser.parse_args()

    stats = sync(Path(args.db), days=args.days,
                 offline_file=Path(args.file) if args.file else None, fx=args.fx)
    LOG.info("nccpl_flows: %d rows written across %d session(s) from %s (store now %s rows / %s sessions)",
             stats["rows"], stats["sessions"], stats["source"],
             stats.get("storedRows", stats["rows"]), stats.get("storedSessions", stats["sessions"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
