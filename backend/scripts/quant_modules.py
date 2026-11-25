#!/usr/bin/env python3
"""quant_modules.py - pure quantitative helpers for the PSX event/flow desk.

No network, no file writes: each function reads through the sqlite3 cursor it
is handed and returns a dict of camelCase values.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta

SESSION_FMT = "%d%b%Y"  # tape sessions look like 16NOV2026
MONTH_CODES = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")
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


def _last_friday(year: int, month: int) -> date:
    expiry = date(year, month, 28) + timedelta(days=4)
    expiry = expiry.replace(day=1) - timedelta(days=1)
    while expiry.weekday() != 4:  # walk back to Friday
        expiry -= timedelta(days=1)
    return expiry


def _contract_expiry(contract, today: date):
    """Delivery-month expiry of a PSX futures scrip such as ZAL-CDEC / MUGHAL-NOVB."""
    suffix = str(contract or "").upper().rsplit("-", 1)[-1]
    for month, code in enumerate(MONTH_CODES, start=1):
        if code in suffix:
            if month < today.month:
                return None  # quote from a delivery month that has already passed
            return _last_friday(today.year, month)
    return None


def calc_dfx_carry(spot_close, fut_close, session_date, contract=None):
    """Annualised carry to the futures contract's own delivery-month expiry, flagged above 18%.

    A row with no readable delivery month, an expired month, or no traded volume is a
    phantom tape entry: return no carry rather than inventing a rate off it.
    """
    out = {"annualizedCarryPct": None, "leverageOverheated": False}
    if not spot_close or not fut_close or spot_close <= 0:
        return out
    if isinstance(session_date, datetime):
        today = session_date.date()
    elif isinstance(session_date, date):
        today = session_date
    else:
        today = datetime.strptime(str(session_date)[:10], "%Y-%m-%d").date()

    if contract:
        expiry = _contract_expiry(contract, today)
        if expiry is None or (expiry - today).days < 1:
            return out
        effective_days = (expiry - today).days
    else:  # no scrip context (direct call): fall back to this month's expiry
        expiry = _last_friday(today.year, today.month)
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


# ---------------------------------------------------------------------------
# Institutional flow, event catalyst and rights helpers
# ---------------------------------------------------------------------------

# NCCPL participant labels that count as institutional smart money. The scstrade
# mirror ships the foreign aggregate as FIPI (legacy rows carry FOREIGN TOTAL).
INSTITUTIONAL_PARTICIPANTS = ("FIPI", "FOREIGN TOTAL", "MUTUAL FUNDS", "INSURANCE")
DISTRIBUTION_PARTICIPANTS = ("INSURANCE", "MUTUAL FUNDS")
RETAIL_PARTICIPANT = "INDIVIDUALS"

# PUCARS / board-meeting material-information triggers, most specific first:
# a generic word must never shadow a narrower event ("public announcement of
# intention" before "acquisition").
CATALYST_TRIGGERS = (
    ("public announcement of intention", "PUBLIC INTENTION"),
    ("scheme of arrangement", "SCHEME OF ARRANGEMENT"),
    ("non-core asset", "NON-CORE ASSET SALE"),
    ("sale of land", "LAND SALE"),
    ("buy-back", "BUY-BACK"),
    ("buyback", "BUY-BACK"),
    ("demerger", "DEMERGER"),
    ("resumption", "RESUMPTION"),
    ("right issue", "RIGHT ISSUE"),
    ("acquisition", "ACQUISITION"),
)

# Absorption shape: a flat or discounted tape on shrinking volume while
# institutions are net buyers is accumulation, not demand.
QUIET_PRICE_BAND_PCT = 5.0        # +-5% over 15-20 sessions is "flat"
DISCOUNT_BAND_PCT = (10.0, 20.0)  # down 10-20% is a discounted base
ABSORPTION_WINDOW = 20            # sessions compared against their own volume SMA
FLOW_STREAK_SESSIONS = 3          # 3+ straight net-sell sessions = distribution


def _iso_day(value) -> str:
    """Normalise a tape session (24NOV2026) or ISO date into YYYY-MM-DD."""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value or "").strip()
    for fmt, width in (("%Y-%m-%d", 10), (SESSION_FMT, 9)):
        try:
            return datetime.strptime(text[:width], fmt).date().isoformat()
        except ValueError:
            continue
    return text


def _flow_sessions(cur: sqlite3.Cursor, session, n: int) -> list[str]:
    """Stored NCCPL sessions up to `session`, newest first."""
    try:
        cur.execute("SELECT DISTINCT trade_date FROM nccpl_flows WHERE trade_date<=? "
                    "ORDER BY trade_date DESC LIMIT ?", (_iso_day(session), n))
        return [r[0] for r in cur.fetchall() if r[0]]
    except sqlite3.OperationalError:  # table not migrated yet
        return []


def calc_institutional_flows(cur, sector: str, session, sessions: int = 10) -> dict:
    """Cumulative participant net buying per sector over the last `sessions`.

    Returns PKR nets for the institutional block (FIPI + mutual funds +
    insurance), the retail counterpart and every participant that reported, so
    the desk can say *who* absorbed the supply rather than just "smart money".
    """
    out = {"sector": sector, "sessions": 0, "lastSession": None, "institutionalNetPkr": 0.0,
           "retailNetPkr": 0.0, "fipiPkr": 0.0, "mutualFundsPkr": 0.0, "insurancePkr": 0.0,
           "participants": {}}
    days = _flow_sessions(cur, session, sessions)
    if not days or not sector:
        return out
    cur.execute(f"SELECT participant_type, SUM(COALESCE(net_pkr,0)) FROM nccpl_flows "
                f"WHERE sector_name=? AND trade_date IN ({_marks(days)}) GROUP BY participant_type",
                (sector, *days))
    parts = {(r[0] or "").upper(): float(r[1] or 0.0) for r in cur.fetchall()}
    out["sessions"] = len(days)
    out["lastSession"] = days[0]
    out["participants"] = {k: round(v, 2) for k, v in parts.items()}
    out["fipiPkr"] = round(sum(parts.get(p, 0.0) for p in ("FIPI", "FOREIGN TOTAL")), 2)
    out["mutualFundsPkr"] = round(parts.get("MUTUAL FUNDS", 0.0), 2)
    out["insurancePkr"] = round(parts.get("INSURANCE", 0.0), 2)
    out["retailNetPkr"] = round(parts.get(RETAIL_PARTICIPANT, 0.0), 2)
    out["institutionalNetPkr"] = round(out["fipiPkr"] + out["mutualFundsPkr"]
                                       + out["insurancePkr"], 2)
    return out


def calc_flow_streak(cur, sector: str, session, participants=DISTRIBUTION_PARTICIPANTS,
                     limit: int = 6) -> dict:
    """Consecutive net-sell sessions (newest first) for the chosen participants."""
    out = {"streak": 0, "lastSessionNetPkr": 0.0, "windowNetPkr": 0.0}
    days = _flow_sessions(cur, session, limit)
    if not days or not sector:
        return out
    labels = ", ".join("?" * len(participants))
    cur.execute(f"SELECT trade_date, SUM(COALESCE(net_pkr,0)) FROM nccpl_flows WHERE sector_name=? "
                f"AND participant_type IN ({labels}) AND trade_date IN ({_marks(days)}) "
                f"GROUP BY trade_date", (sector, *participants, *days))
    per_day = {r[0]: float(r[1] or 0.0) for r in cur.fetchall()}
    out["windowNetPkr"] = round(sum(per_day.values()), 2)
    out["lastSessionNetPkr"] = round(per_day.get(days[0], 0.0), 2)
    for day in days:
        if per_day.get(day, 0.0) < 0:
            out["streak"] += 1
        else:
            break
    return out


def calc_quiet_absorption(bars, window: int = ABSORPTION_WINDOW) -> dict:
    """Price flat (+-5%) or down 10-20% over 15-20 sessions on sub-SMA volume."""
    out = {"ret15dPct": None, "ret20dPct": None, "volumeRatio20": None,
           "flat": False, "discounted": False, "quiet": False, "absorption": False}
    if len(bars) < window + 1:
        return out
    closes = [b.close_price for b in bars]
    volumes = [float(b.volume or 0) for b in bars]
    last = closes[-1]
    ret15 = (last / closes[-16] - 1) * 100 if closes[-16] > 0 else None
    ret20 = (last / closes[-(window + 1)] - 1) * 100 if closes[-(window + 1)] > 0 else None
    vol_sma = sum(volumes[-window:]) / window
    ratio = volumes[-1] / vol_sma if vol_sma > 0 else None
    out["ret15dPct"] = round(ret15, 2) if ret15 is not None else None
    out["ret20dPct"] = round(ret20, 2) if ret20 is not None else None
    out["volumeRatio20"] = round(ratio, 2) if ratio is not None else None
    lows, highs = DISCOUNT_BAND_PCT
    flat = all(abs(r) <= QUIET_PRICE_BAND_PCT for r in (ret15, ret20) if r is not None)
    discounted = any(-highs <= r <= -lows for r in (ret15, ret20) if r is not None)
    quiet = ratio is not None and ratio <= 1.0
    out.update({"flat": bool(flat), "discounted": bool(discounted), "quiet": bool(quiet),
                "absorption": bool(quiet and (flat or discounted))})
    return out


def calc_catalyst(headline: str) -> dict:
    """Map a PUCARS / board-meeting headline onto one high-alpha event tag."""
    text = " ".join(str(headline or "").lower().split())
    for phrase, tag in CATALYST_TRIGGERS:
        if phrase in text:
            return {"catalyst": tag, "trigger": phrase}
    return {"catalyst": None, "trigger": None}


def calc_low_float(cur, ticker: str) -> dict:
    """Low-float + deep-value screen from company_fundamentals."""
    out = {"freeFloatPct": None, "peRatio": None, "pbRatio": None, "lowFloat": False,
           "turnaroundCatalyst": False}
    if not ticker:
        return out
    try:
        cur.execute("SELECT free_float_pct, pe_ratio, pb_ratio, turnaround_catalyst "
                    "FROM company_fundamentals WHERE ticker=?", (ticker,))
        row = cur.fetchone()
    except sqlite3.OperationalError:
        row = None
    if not row:
        return out
    free_float, pe, pb, turnaround = row
    out.update({"freeFloatPct": round(float(free_float), 2) if free_float is not None else None,
                "peRatio": round(float(pe), 2) if pe is not None else None,
                "pbRatio": round(float(pb), 2) if pb is not None else None,
                "turnaroundCatalyst": bool(turnaround)})
    cheap = (pe is not None and 0 < pe < 5.0) or (pb is not None and 0 < pb < 0.7)
    out["lowFloat"] = bool(free_float is not None and free_float < 20.0 and cheap)
    return out


def calc_lor_spread(close, terp) -> dict:
    """Letter-of-Rights premium: a close far above TERP means the LoR is rich."""
    out = {"terp": None, "lorPremiumPct": None, "lorTrap": False, "lorCheap": False}
    if not close or not terp or close <= 0 or terp <= 0:
        return out
    premium = (close / terp - 1) * 100
    out["terp"] = round(float(terp), 2)
    out["lorPremiumPct"] = round(premium, 2)
    out["lorTrap"] = premium > 5.0      # paying up for the entitlement is the trap
    out["lorCheap"] = premium < -5.0    # converting into a discount is accretive
    return out

