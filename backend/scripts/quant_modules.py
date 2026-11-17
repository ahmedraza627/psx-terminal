#!/usr/bin/env python3
"""quant_modules.py - four pure quantitative functions for the PSX daily tape.

No network, no file writes: each function reads through the sqlite3 cursor it
is handed and returns a dict of camelCase values.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta

SESSION_FMT = "%d%b%Y"  # tape sessions look like 16NOV2026
ACQ_KEYWORDS = ("acquisition", "acquirer", "purchase", "buy-back", "buyback",
                "subscription", "takeover", "merger", "investment")
DIS_KEYWORDS = ("disposal", "sale", "divest", "exit", "transfer", "donation")


def _marks(values) -> str:
    return ",".join("?" * len(values))


def _sessions(cur: sqlite3.Cursor, n: int) -> list[str]:
    """Last n trade dates held in psx_daily_eod, oldest first."""
    cur.execute("SELECT DISTINCT trade_date FROM psx_daily_eod")
    seen = [r[0] for r in cur.fetchall() if r[0]]
    seen.sort(key=lambda s: datetime.strptime(s, SESSION_FMT))
    return seen[-n:]


def pick_ticker(cur: sqlite3.Cursor) -> str | None:
    """Highest-volume plain-equity ticker of the most recent session."""
    dates = _sessions(cur, 1)
    if not dates:
        return None
    cur.execute("SELECT ticker FROM psx_daily_eod WHERE trade_date=? AND close_price>0 "
                "AND ticker NOT LIKE '%-%' AND ticker NOT GLOB '*[0-9]*' "
                "ORDER BY COALESCE(volume,0) DESC LIMIT 1", (dates[0],))
    row = cur.fetchone()
    return row[0] if row else None


def calc_vpvr_sweep(cur, ticker, today_ohlc=None):
    """15-session volume profile + 20-session volume z-score + sweep flag.

    (H+L+C)/3 of the last 15 sessions is binned into 20 equally spaced,
    volume-weighted price buckets; the POC is the centre of the heaviest
    bucket. liquiditySweep needs the latest low to take out the prior 3-day
    low, the close back above the POC and volZScore >= 1.5.
    """
    empty = {"poc": None, "volZScore": None, "liquiditySweep": False}
    if not ticker:
        return empty
    window = _sessions(cur, 20)
    if len(window) < 2:
        return empty
    cur.execute(f"""SELECT trade_date, high_price, low_price, close_price, volume
            FROM psx_daily_eod WHERE ticker=? AND trade_date IN ({_marks(window)})
              AND high_price IS NOT NULL AND low_price IS NOT NULL
              AND close_price IS NOT NULL AND close_price > 0""", (ticker, *window))
    bars = sorted(cur.fetchall(), key=lambda b: datetime.strptime(b["trade_date"], SESSION_FMT))
    if len(bars) < 2:
        return empty

    profile = bars[-15:]
    mids = [(b["high_price"] + b["low_price"] + b["close_price"]) / 3 for b in profile]
    lo, hi = min(mids), max(mids)
    if hi - lo < 1e-9:
        lo, hi = lo - 0.005, hi + 0.005
    width = (hi - lo) / 20
    buckets = [0.0] * 20
    for bar, mid in zip(profile, mids):
        buckets[min(int((mid - lo) / width), 19)] += float(bar["volume"] or 0)
    poc = lo + (buckets.index(max(buckets)) + 0.5) * width

    volumes = [float(b["volume"] or 0) for b in bars[-20:]]
    mean = sum(volumes) / len(volumes)
    sd = (sum((v - mean) ** 2 for v in volumes) / len(volumes)) ** 0.5
    latest = bars[-1]
    vol_z = (float(latest["volume"] or 0) - mean) / sd if sd > 1e-9 else 0.0

    sweep = False
    prior = bars[-4:-1]
    if len(prior) == 3:
        sweep = bool(latest["low_price"] < min(b["low_price"] for b in prior)
                     and latest["close_price"] > poc and vol_z >= 1.5)
    return {"poc": round(poc, 2), "volZScore": round(vol_z, 2), "liquiditySweep": sweep}


def calc_dfx_carry(spot_close, fut_close, session_date):
    """Annualised carry to the last Friday of the month, flagged above 18%."""
    out = {"annualizedCarryPct": None, "leverageOverheated": False}
    if not spot_close or not fut_close or spot_close <= 0:
        return out
    if isinstance(session_date, datetime):
        today = session_date.date()
    elif isinstance(session_date, date):
        today = session_date
    else:
        today = datetime.strptime(str(session_date)[:10], "%Y-%m-%d").date()

    expiry = (today.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    while expiry.weekday() != 4:  # walk back to Friday
        expiry -= timedelta(days=1)

    effective_days = max((expiry - today).days, 10)  # guards month-end rollover compression
    carry = ((fut_close - spot_close) / spot_close) * (365 / effective_days) * 100
    out["annualizedCarryPct"] = round(carry, 2)
    out["leverageOverheated"] = carry > 18.0
    return out


def calc_mansfield_rs(cur, ticker, stock_close, kse_close):
    """RS = stock/index close, mansfieldRs = ((RS / RS 20d avg) - 1) * 100."""
    out = {"rs": None, "mansfieldRs": None}
    if not ticker or not stock_close or not kse_close:
        return out
    rs_now = stock_close / kse_close
    out["rs"] = round(rs_now, 4)
    window = _sessions(cur, 20)
    if len(window) < 2:
        return out
    cur.execute(f"""SELECT trade_date, AVG(close_price) AS mkt FROM psx_daily_eod
            WHERE trade_date IN ({_marks(window)}) AND close_price > 0
            GROUP BY trade_date""", tuple(window))
    market = {r["trade_date"]: r["mkt"] for r in cur.fetchall() if r["mkt"]}
    cur.execute(f"""SELECT trade_date, close_price FROM psx_daily_eod
            WHERE ticker=? AND trade_date IN ({_marks(window)}) AND close_price > 0""",
                (ticker, *window))
    series = [r["close_price"] / market[r["trade_date"]]
              for r in cur.fetchall() if market.get(r["trade_date"])]
    if series and (avg := sum(series) / len(series)):
        out["mansfieldRs"] = round(((rs_now / avg) - 1) * 100, 2)
    return out


def calc_director_footprint(cur, ticker, current_price, poc):
    """Director/insider footprint from psx_disclosures around the POC.

    directorFootprint is True when the close sits within +-3% of the POC or a
    recent acquisition/purchase declaration exists for the ticker.
    """
    out = {"directorFootprint": False, "priceWithin3pctPoc": False,
           "totalDisclosures": 0, "acquisitionDeclarations": 0,
           "disposalDeclarations": 0}
    if current_price and poc:
        out["priceWithin3pctPoc"] = abs(current_price - poc) / poc * 100 <= 3.0

    rows = []
    if ticker:
        try:
            cur.execute("SELECT headline FROM psx_disclosures WHERE ticker=? "
                        "AND headline IS NOT NULL ORDER BY trade_date DESC LIMIT 20",
                        (ticker,))
            rows = cur.fetchall()
        except sqlite3.OperationalError:  # table not migrated yet
            rows = []
    out["totalDisclosures"] = len(rows)
    for row in rows:
        headline = (row["headline"] or "").lower()
        if any(k in headline for k in ACQ_KEYWORDS):
            out["acquisitionDeclarations"] += 1
        elif any(k in headline for k in DIS_KEYWORDS):
            out["disposalDeclarations"] += 1

    out["directorFootprint"] = bool(out["priceWithin3pctPoc"]
                                    or out["acquisitionDeclarations"] > 0)
    return out
