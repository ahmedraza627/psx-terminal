#!/usr/bin/env python3
"""sync_company_fundamentals.py - low-float / value screen + rights tracking.

Fills two tables in data/portfolio.db:

    company_fundamentals(ticker, free_float_pct, pe_ratio, pb_ratio,
                         turnaround_catalyst, updated_at)
    active_right_issues(ticker, announcement_date, ratio, issue_price, terp,
                        status, source, updated_at)

Fundamentals come from the DPS screener (market cap, price, trailing P/E and
free-float shares); free_float_pct is free-float shares divided by total shares
implied by market cap / price. The screener publishes no book value, so
pb_ratio stays NULL unless supplied in a CSV - it is never guessed.

`--file` accepts CSV columns ticker,pe_ratio,pb_ratio,free_float_pct to override
or fill gaps. `--rights-file` accepts ticker,announcement_date,ratio,issue_price,terp
for the rights/LoR spread tracker. Rows already stored keep their P/B unless a
CSV row names a new value.

Run it
------
python backend/scripts/sync_company_fundamentals.py
python backend/scripts/sync_company_fundamentals.py --file fundamentals.csv
"""
from __future__ import annotations

import argparse
import csv
import logging
import sqlite3
import sys
from datetime import date, datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
BASE_DIR = BACKEND_DIR.parent
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from quant_modules import _iso_day, calc_catalyst  # noqa: E402

DB_PATH = BASE_DIR / "data" / "portfolio.db"
LOG = logging.getLogger("sync_company_fundamentals")

FUNDAMENTALS_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS company_fundamentals (ticker TEXT PRIMARY KEY, "
    "free_float_pct REAL, pe_ratio REAL, pb_ratio REAL, turnaround_catalyst INTEGER NOT NULL DEFAULT 0, "
    "updated_at TEXT NOT NULL)")
RIGHTS_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS active_right_issues (ticker TEXT NOT NULL, "
    "announcement_date TEXT NOT NULL, ratio TEXT, issue_price REAL, terp REAL, "
    "status TEXT NOT NULL DEFAULT 'ANNOUNCED', source TEXT, updated_at TEXT NOT NULL, "
    "PRIMARY KEY (ticker, announcement_date))")

UPSERT_FUNDAMENTAL = (
    "INSERT INTO company_fundamentals (ticker, free_float_pct, pe_ratio, pb_ratio, "
    "turnaround_catalyst, updated_at) VALUES (?,?,?,?,?,?) "
    "ON CONFLICT(ticker) DO UPDATE SET "
    "free_float_pct=COALESCE(excluded.free_float_pct, free_float_pct), "
    "pe_ratio=COALESCE(excluded.pe_ratio, pe_ratio), "
    "pb_ratio=COALESCE(excluded.pb_ratio, pb_ratio), "
    "turnaround_catalyst=excluded.turnaround_catalyst, updated_at=excluded.updated_at")
UPSERT_RIGHTS = (
    "INSERT INTO active_right_issues (ticker, announcement_date, ratio, issue_price, terp, "
    "status, source, updated_at) VALUES (?,?,?,?,?,?,?,?) "
    "ON CONFLICT(ticker, announcement_date) DO UPDATE SET "
    "ratio=COALESCE(excluded.ratio, ratio), issue_price=COALESCE(excluded.issue_price, issue_price), "
    "terp=COALESCE(excluded.terp, terp), status=excluded.status, updated_at=excluded.updated_at")


def ensure_tables(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute(FUNDAMENTALS_SCHEMA)
    cur.execute(RIGHTS_SCHEMA)
    conn.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def turnaround_tickers(conn: sqlite3.Connection) -> set[str]:
    """Tickers whose stored PUCARS rows carry a turnaround-type catalyst."""
    try:
        rows = conn.execute("SELECT DISTINCT ticker, headline FROM psx_disclosures "
                            "WHERE disclosure_type LIKE 'PUCARS%'").fetchall()
    except sqlite3.OperationalError:
        return set()
    tags = set()
    for ticker, headline in rows:
        if calc_catalyst(headline)["catalyst"]:
            tags.add(ticker)
    return tags


def fundamentals_from_screener(rows: list[dict]) -> dict[str, dict]:
    """Turn screener rows into free-float percentages (no P/B is published)."""
    out: dict[str, dict] = {}
    for row in rows:
        ticker = str(row.get("ticker") or "").strip().upper()
        price = row.get("close_price")
        market_cap = row.get("market_cap_pkr")
        free_float = row.get("free_float")
        if not ticker or not price or not market_cap or price <= 0 or market_cap <= 0:
            continue
        total_shares = market_cap / price
        free_float_pct = (free_float / total_shares * 100) if free_float and total_shares else None
        pe = row.get("pe_ratio")
        out[ticker] = {
            "free_float_pct": round(free_float_pct, 2) if free_float_pct is not None else None,
            "pe_ratio": round(float(pe), 2) if pe not in (None, 0) else None,
        }
    return out


def sync_screener(conn: sqlite3.Connection) -> int:
    from pipeline.scrapers.psx_fundamentals import fetch_screener
    rows = fetch_screener(date.today())
    data = fundamentals_from_screener(rows)
    turns = turnaround_tickers(conn)
    now = _now()
    cur = conn.cursor()
    for ticker, row in data.items():
        cur.execute(UPSERT_FUNDAMENTAL, (ticker, row["free_float_pct"], row["pe_ratio"], None,
                                         int(ticker in turns), now))
    conn.commit()
    LOG.info("company_fundamentals: %d tickers refreshed", len(data))
    return len(data)


def load_fundamentals_csv(conn: sqlite3.Connection, path: Path) -> int:
    written, cur = 0, conn.cursor()
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            ticker = (row.get("ticker") or "").strip().upper()
            if not ticker:
                continue
            def num(key):
                try:
                    return float(row[key]) if row.get(key) not in (None, "") else None
                except ValueError:
                    return None
            cur.execute(UPSERT_FUNDAMENTAL, (ticker, num("free_float_pct"), num("pe_ratio"),
                                             num("pb_ratio"), int(ticker in turnaround_tickers(conn)),
                                             _now()))
            written += 1
    conn.commit()
    LOG.info("company_fundamentals: %d CSV rows upserted", written)
    return written


def load_rights_csv(conn: sqlite3.Connection, path: Path) -> int:
    written, cur = 0, conn.cursor()
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            ticker = (row.get("ticker") or "").strip().upper()
            if not ticker:
                continue
            def num(key):
                try:
                    return float(row[key]) if row.get(key) not in (None, "") else None
                except ValueError:
                    return None
            cur.execute(UPSERT_RIGHTS, (ticker, _iso_day(row.get("announcement_date") or date.today()),
                                        row.get("ratio") or None, num("issue_price"), num("terp"),
                                        (row.get("status") or "ANNOUNCED").upper(), "csv", _now()))
            written += 1
    conn.commit()
    LOG.info("active_right_issues: %d CSV rows upserted", written)
    return written


def sync_right_issue_disclosures(conn: sqlite3.Connection) -> int:
    """Register 'Right Issue' PUCARS rows as active issues (TERP filled later from CSV)."""
    try:
        rows = conn.execute("SELECT ticker, trade_date, headline FROM psx_disclosures "
                            "WHERE disclosure_type LIKE 'PUCARS%'").fetchall()
    except sqlite3.OperationalError:
        return 0
    cur, written = conn.cursor(), 0
    for ticker, trade_date, headline in rows:
        if calc_catalyst(headline)["catalyst"] != "RIGHT ISSUE":
            continue
        cur.execute(UPSERT_RIGHTS, (ticker, _iso_day(trade_date), None, None, None,
                                    "ANNOUNCED", "psx_disclosures", _now()))
        written += 1
    conn.commit()
    return written


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")
    parser = argparse.ArgumentParser(description="Refresh fundamentals and rights tracking")
    parser.add_argument("--db", default=str(DB_PATH))
    parser.add_argument("--file", help="CSV: ticker,pe_ratio,pb_ratio,free_float_pct")
    parser.add_argument("--rights-file", help="CSV: ticker,announcement_date,ratio,issue_price,terp")
    parser.add_argument("--skip-screener", action="store_true")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    ensure_tables(conn)
    refreshed = 0 if args.skip_screener else sync_screener(conn)
    rights = sync_right_issue_disclosures(conn)
    if args.file:
        load_fundamentals_csv(conn, Path(args.file))
    if args.rights_file:
        load_rights_csv(conn, Path(args.rights_file))
    total = conn.execute("SELECT COUNT(*) FROM company_fundamentals").fetchone()[0]
    conn.close()
    LOG.info("company_fundamentals: %d refreshed / %d stored; %d rights rows registered",
             refreshed, total, rights)
    return 0


if __name__ == "__main__":
    sys.exit(main())
