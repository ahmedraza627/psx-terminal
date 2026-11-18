#!/usr/bin/env python3
"""ingest_eod.py - live PSX EOD ingestion -> psx_history.db -> quant engine -> JSON.

Pulls the official PSX market-summary tape for the most recent trading session (with a
per-symbol EOD endpoint as fallback), writes it through a WAL-mode ingestion manager,
mirrors the session into the quant engine's store and regenerates
frontend/public/data/latest.json + history.json for the actual current date.
"""
from __future__ import annotations

import argparse
import gzip
import json
import logging
import sqlite3
import sys
import zipfile
import zlib
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

BASE_DIR = Path(__file__).resolve().parent.parent.parent
HISTORY_DB = Path(__file__).resolve().parent.parent / "psx_history.db"
ENGINE_DB = BASE_DIR / "data" / "portfolio.db"
CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "tape_cache"
TAPE_URL = "https://dps.psx.com.pk/download/mkt_summary/{}.Z"
EOD_URL = "https://dps.psx.com.pk/timeseries/eod/{}"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"}
LOG = logging.getLogger("ingest_eod")


class WALIngestionManager:
    """SQLite writer: WAL journalling plus one atomic batch per session."""

    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA busy_timeout=10000")
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS daily_eod (
                date TEXT, ticker TEXT, sector TEXT, open REAL, high REAL, low REAL,
                close REAL, volume REAL, turnover REAL, PRIMARY KEY (date, ticker));
            CREATE TABLE IF NOT EXISTS ingest_runs (
                run_at TEXT, session TEXT, source TEXT, rows INTEGER, tickers INTEGER, status TEXT);
        """)
        self.conn.commit()

    def sector_map(self) -> dict[str, str]:
        return dict(self.conn.execute(
            "SELECT ticker, MAX(sector) FROM daily_eod WHERE sector IS NOT NULL GROUP BY ticker"))

    def latest_session(self) -> str | None:
        row = self.conn.execute("SELECT MAX(date) FROM daily_eod").fetchone()
        return row[0] if row else None

    def ingest(self, session: str, rows: list[dict], source: str) -> int:
        sectors = self.sector_map()
        payload = [(session, row["ticker"], sectors.get(row["ticker"], "UNKNOWN"), row["open"], row["high"],
                    row["low"], row["close"], row["volume"], row["turnover"]) for row in rows]
        with self.conn:  # single transaction: all rows land, or none
            self.conn.executemany("INSERT OR REPLACE INTO daily_eod VALUES (?,?,?,?,?,?,?,?,?)", payload)
            self.conn.execute("INSERT INTO ingest_runs VALUES (?,?,?,?,?,?)",
                              (datetime.now().isoformat(timespec="seconds"), session, source, len(payload),
                               len({row["ticker"] for row in rows}), "OK"))
        return len(payload)

    def fail(self, session: str, reason: str) -> None:
        with self.conn:
            self.conn.execute("INSERT INTO ingest_runs VALUES (?,?,?,?,?,?)",
                              (datetime.now().isoformat(timespec="seconds"), session, "-", 0, 0, reason[:200]))


class PSXFeed:
    """Reads the public DPS (Pakistan Stock Exchange data portal) endpoints."""

    def __init__(self, timeout: int = 45):
        self.timeout = timeout

    def tape(self, day: date) -> list[dict]:
        stamp = day.isoformat()
        cached = CACHE_DIR / f"{stamp}.Z"
        raw = cached.read_bytes() if cached.is_file() else None
        if raw is None:
            response = requests.get(TAPE_URL.format(stamp), headers=HEADERS, timeout=self.timeout)
            response.raise_for_status()
            raw = response.content
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cached.write_bytes(raw)
        return self._parse(raw)

    @staticmethod
    def _parse(raw: bytes) -> list[dict]:
        if zipfile.is_zipfile(__import__("io").BytesIO(raw)):
            with zipfile.ZipFile(__import__("io").BytesIO(raw)) as archive:
                text = "".join(archive.read(name).decode("utf-8", "replace") for name in archive.namelist())
        elif raw[:2] == b"\x1f\x8b":
            text = gzip.decompress(raw).decode("utf-8", "replace")
        elif raw[:1] == b"\x1f":
            text = zlib.decompress(raw, -15).decode("utf-8", "replace")
        else:
            text = raw.decode("utf-8", "replace")
        rows = []
        for line in text.splitlines():
            parts = line.split("|")
            try:
                ticker = parts[1].strip().upper()
                if "-" in ticker or any(ch.isdigit() for ch in ticker):
                    continue  # futures, bonds and index rows stay out of daily_eod
                close = round(float(parts[7]), 2)
                volume = float(parts[8] or 0)
                rows.append({"ticker": ticker, "open": round(float(parts[4]), 2),
                             "high": float(parts[5]), "low": float(parts[6]), "close": close,
                             "volume": volume, "turnover": round(close * volume, 2)})
            except (ValueError, IndexError):
                continue
        return rows

    def symbol_eod(self, ticker: str) -> dict | None:
        """Fallback when the summary tape is unavailable for the session."""
        try:
            response = requests.get(EOD_URL.format(ticker), headers=HEADERS, timeout=12)
            data = response.json().get("data") or []
        except (requests.RequestException, ValueError):
            return None
        if not data:
            return None
        bar = data[-1]
        try:
            close, volume, open_, high, low = float(bar[1]), float(bar[2]), float(bar[3]), float(bar[4]), float(bar[5])
        except (IndexError, TypeError, ValueError):
            return None
        return {"ticker": ticker, "open": open_, "high": high, "low": low, "close": close,
                "volume": volume, "turnover": round(close * volume, 2)}


class LiquidityQuantEngine:
    """Hands the ingested session to the signal engine that owns the frontend JSON."""

    def mirror(self, session_iso: str, rows: list[dict]) -> int:
        """Keep the engine's own store in step (it keys sessions as DDMMMYYYY)."""
        ENGINE_DB.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.strptime(session_iso, "%Y-%m-%d").strftime("%d%b%Y").upper()
        conn = sqlite3.connect(ENGINE_DB)
        conn.execute("CREATE TABLE IF NOT EXISTS psx_daily_eod (trade_date TEXT NOT NULL, ticker TEXT NOT NULL, "
                     "open_price REAL, high_price REAL, low_price REAL, close_price REAL, volume INTEGER, "
                     "PRIMARY KEY (trade_date, ticker))")
        payload = [(stamp, row["ticker"], row["open"], row["high"], row["low"], row["close"], int(row["volume"]))
                   for row in rows]
        with conn:
            conn.executemany("INSERT OR REPLACE INTO psx_daily_eod VALUES (?,?,?,?,?,?,?)", payload)
        conn.close()
        return len(payload)

    @staticmethod
    def refresh() -> dict:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import process_daily_tape  # noqa: E402  (import after path setup)
        return process_daily_tape.main()


def resolve(feed: PSXFeed, requested: str | None) -> tuple[date, list[dict], str]:
    """Walk back from today (or --session) until a session with real tape is found."""
    start = datetime.strptime(requested, "%Y-%m-%d").date() if requested else date.today()
    for back in range(8):
        day = start - timedelta(days=back)
        if day.weekday() >= 5:
            continue
        try:
            rows = feed.tape(day)
        except requests.RequestException as exc:
            LOG.warning("no summary tape for %s (%s)", day, exc)
            continue
        if rows:
            return day, rows, "market_summary_tape"
    return start, [], "unavailable"


def main() -> int:
    parser = argparse.ArgumentParser(description="Live PSX EOD ingestion + quant refresh")
    parser.add_argument("--session", help="target session YYYY-MM-DD (default: today)")
    parser.add_argument("--skip-quant", action="store_true", help="ingest only, do not regenerate JSON")
    parser.add_argument("--symbol-cap", type=int, default=40, help="max per-symbol fallback requests")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")
    wal = WALIngestionManager(HISTORY_DB)
    feed = PSXFeed()

    day, rows, source = resolve(feed, args.session)
    if not rows and args.session:
        fallback = [feed.symbol_eod(ticker) for ticker in _active_tickers()[: args.symbol_cap]]
        rows = [row for row in fallback if row]
        source = "symbol_eod_fallback"
    if not rows:
        wal.fail(day.isoformat(), "no data from any PSX source")
        LOG.error("ingestion failed: no PSX data for %s", day)
        return 1

    session_iso = day.isoformat()
    count = wal.ingest(session_iso, rows, source)
    LOG.info("ingested %d rows for %s via %s (wal=%s)", count, session_iso,
             source, wal.conn.execute("PRAGMA journal_mode").fetchone()[0])

    if args.skip_quant:
        return 0
    LiquidityQuantEngine().mirror(session_iso, rows)
    payload = LiquidityQuantEngine.refresh()
    LOG.info("engine refreshed: session=%s sweeps=%d leaders=%d traps=%d", payload["sessionDate"],
             len(payload["liquiditySweeps"]), len(payload["rsLeaders"]), len(payload["carryTraps"]))
    print(json.dumps({"session": session_iso, "rows": count, "source": source,
                      "signals": {key: len(value) for key, value in payload.items() if isinstance(value, list)}}))
    return 0


def _active_tickers() -> list[str]:
    conn = sqlite3.connect(HISTORY_DB)
    latest = conn.execute("SELECT MAX(date) FROM daily_eod").fetchone()[0]
    tickers = [row[0] for row in conn.execute(
        "SELECT ticker FROM daily_eod WHERE date=? ORDER BY turnover DESC", (latest,))]
    conn.close()
    return tickers


if __name__ == "__main__":
    sys.exit(main())
