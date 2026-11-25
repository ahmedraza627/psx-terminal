"""v5_ledger.py - persist every V5 desk call and audit it against the live tape.

`history.json` is the ledger of record: the SQLite table is a scratch store that
is rebuilt from the tape on every run, so a fresh (CI) store re-seeds itself from
the committed ledger instead of truncating it.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = ("CREATE TABLE IF NOT EXISTS v5_signal_log (trade_date TEXT NOT NULL, ticker TEXT NOT NULL, "
          "call TEXT NOT NULL, label TEXT, entry REAL, stop REAL, target REAL, poc REAL, vol_z REAL, "
          "mansfield_rs REAL, carry_pct REAL, director INTEGER, PRIMARY KEY (trade_date, ticker, call))")
INSERT = ("INSERT OR REPLACE INTO v5_signal_log (trade_date, ticker, call, label, entry, stop, target, poc, "
          "vol_z, mansfield_rs, carry_pct, director, notes) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)")


def _close(cur: sqlite3.Cursor, session: str, ticker: str) -> float | None:
    row = cur.execute("SELECT close_price FROM psx_daily_eod WHERE trade_date=? AND ticker=?",
                      (session, ticker)).fetchone()
    return row[0] if row else None


def _audit(call: str, entry: float | None, stop: float | None, target: float | None,
           live: float | None) -> tuple[float, str]:
    """Mark a call to market: BUY rides price up, AVOID profits when spot falls."""
    if not entry or not live:
        return 0.0, "IN PLAY"
    if call == "BUY":
        pnl = (live - entry) / entry * 100
        if target and live >= target:
            return pnl, "TARGET HIT"
        if stop and live <= stop:
            return pnl, "STOPPED OUT"
        return pnl, "IN PLAY"
    pnl = (entry - live) / entry * 100
    if abs(live - entry) < 1e-9:
        return pnl, "IN PLAY"
    return pnl, ("AVOID WORKED" if live < entry else "AVOID FAILED")


def _prepare(cur: sqlite3.Cursor) -> None:
    cur.execute(SCHEMA)
    try:  # full basis text survives a re-seed; older tables simply gain the column
        cur.execute("ALTER TABLE v5_signal_log ADD COLUMN notes TEXT")
    except sqlite3.OperationalError:
        pass


def _seed_from_ledger(cur: sqlite3.Cursor, out: Path,
                      exclude: set[tuple[str, str]] | None = None) -> int:
    """A fresh store (CI runner) must not wipe the audited history already in git."""
    exclude = exclude or set()
    if cur.execute("SELECT COUNT(*) FROM v5_signal_log").fetchone()[0] or not out.is_file():
        return 0
    try:
        entries = json.loads(out.read_text(encoding="utf-8")).get("entries") or []
    except (OSError, ValueError, AttributeError):
        return 0
    seeded = 0
    for entry in entries:
        try:
            day = datetime.strptime(entry["date"], "%d %b %Y").strftime("%d%b%Y")
            ticker, call = entry["ticker"], entry["call"]
        except (KeyError, ValueError):
            continue
        if call == "AVOID" and (day, ticker) in exclude:
            continue
        cur.execute(INSERT, (day, ticker, call, entry.get("label") or call, entry.get("entry"),
                             entry.get("stop"), entry.get("target"), None, None, None, None, 0,
                             entry.get("notes")))
        seeded += 1
    return seeded


def log_signals(conn: sqlite3.Connection, cur: sqlite3.Cursor, session: str, buys: list[dict],
                avoids: list[dict], out: Path,
                exclude: set[tuple[str, str]] | None = None) -> int:
    """Upsert today's calls, then rewrite history.json with live P&L for every past call.

    `exclude` names (session, ticker) AVOID rows that a same-session BUY setup
    overrides: they are dropped from the store, from the re-seed and from the ledger.
    """
    exclude = exclude or set()
    _prepare(cur)
    seeded = _seed_from_ledger(cur, out, exclude)
    for item in buys:
        close = item["close"]
        cur.execute(INSERT, (session, item["ticker"], "BUY",
                             item.get("label") or ("LIQUIDITY SWEEP BUY" if "stopLoss" in item
                                                   else "RS ACCUMULATION WATCH"),
                             item["poc"] or close, item.get("stopLoss") or round(close * 0.93, 2),
                             item.get("target") or round(close * 1.12, 2), item["poc"], item.get("volZScore"),
                             item["mansfieldRs"], None, int(bool(item.get("directorFootprint"))), None))
    for item in avoids:
        if (session, item["ticker"]) in exclude:
            continue
        cur.execute(INSERT, (session, item["ticker"], "AVOID", "DFX CARRY TRAP", item["spotClose"], None, None,
                             None, None, item["mansfieldRs"], item["annualizedCarryPct"], 0, None))
    for day, ticker in exclude:  # reconcile a contradictory AVOID written by an earlier run
        cur.execute("DELETE FROM v5_signal_log WHERE trade_date=? AND ticker=? AND call='AVOID'",
                    (day, ticker))
    conn.commit()

    entries = []
    # fetchall first: _close() reuses this cursor and would cut the iteration short
    for row in cur.execute("SELECT * FROM v5_signal_log ORDER BY trade_date DESC, call, mansfield_rs DESC").fetchall():
        live = _close(cur, session, row["ticker"]) or row["entry"]
        pnl, status = _audit(row["call"], row["entry"], row["stop"], row["target"], live)
        tags = [row["label"] or row["call"]]
        if row["poc"]:
            tags.append(f"POC {row['poc']:.2f}")
        if row["vol_z"] is not None:
            tags.append(f"Vol Z {row['vol_z']:.2f}")
        if row["mansfield_rs"] is not None:
            tags.append(f"Mansfield RS {row['mansfield_rs']:+.2f}%")
        if row["carry_pct"] is not None:
            tags.append(f"Carry {row['carry_pct']:.1f}% vs SBP 12.0%")
        if row["director"]:
            tags.append("Director footprint")
        entries.append({"date": datetime.strptime(row["trade_date"], "%d%b%Y").strftime("%d %b %Y"),
                        "ticker": row["ticker"], "call": row["call"], "label": row["label"],
                        "entry": round(row["entry"], 2) if row["entry"] else None,
                        "stop": round(row["stop"], 2) if row["stop"] else None,
                        "target": round(row["target"], 2) if row["target"] else None,
                        "latestClose": round(live, 2) if live else None, "pnlPct": round(pnl, 2),
                        "status": status, "notes": row["notes"] or " · ".join(tags)})

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"sessionDate": session, "generatedAt": datetime.now(timezone.utc).isoformat(),
                               "entries": entries}, indent=2), encoding="utf-8")
    if seeded:
        print(f"[INFO] ledger seeded from {out.name}: {seeded} historical calls restored")
    return len(entries)
