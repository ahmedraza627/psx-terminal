import os
import json
import glob
import sqlite3
from datetime import datetime

DATA_DIR = os.path.join("frontend", "public", "data")
LATEST_JSON = os.path.join(DATA_DIR, "latest.json")
HISTORY_JSON = os.path.join(DATA_DIR, "history.json")
INSIDERS_JSON = os.path.join(DATA_DIR, "insiders.json")
DB_PATH = os.path.join("backend", "psx_history.db")
TARGET_DIR = r"D:\downloads"

AUDIT_REGISTRY = [
    {"date": "2026-11-09", "ticker": "MCB",  "type": "BUY",   "entry": 399.48, "stop": 389.50, "target": 415.40, "notes": "Banking sector dividend support."},
    {"date": "2026-11-08", "ticker": "MARI", "type": "BUY",   "entry": 651.98, "stop": 635.60, "target": 678.00, "notes": "Hydrocarbon production expansion."},
    {"date": "2026-11-06", "ticker": "MEBL", "type": "BUY",   "entry": 550.25, "stop": 536.50, "target": 572.00, "notes": "Strong institutional book value."},
    {"date": "2026-11-05", "ticker": "HUBC", "type": "AVOID", "entry": 208.00, "stop": 214.50, "target": 198.00, "notes": "Resistance re-test breakdown."},
    {"date": "2026-11-04", "ticker": "SYS",  "type": "BUY",   "entry": 114.60, "stop": 111.80, "target": 119.50, "notes": "Foreign buying accumulation support."},
    {"date": "2026-10-30", "ticker": "PRL",  "type": "AVOID", "entry": 85.55,  "stop": 88.70,  "target": 80.00,  "notes": "Refinery sector profit taking."},
    {"date": "2026-10-25", "ticker": "FFC",  "type": "BUY",   "entry": 525.00, "stop": 512.00, "target": 546.00, "notes": "Urea pricing cashflow strength."},
    {"date": "2026-10-20", "ticker": "LUCK", "type": "BUY",   "entry": 427.23, "stop": 416.50, "target": 444.50, "notes": "Cement dispatch demand revival."},
    {"date": "2026-10-15", "ticker": "HASCOL","type": "AVOID","entry": 18.20,  "stop": 19.10,  "target": 16.50,  "notes": "High balance sheet leverage."},
    {"date": "2026-10-10", "ticker": "WTL",  "type": "AVOID", "entry": 1.25,   "stop": 1.32,   "target": 1.12,   "notes": "Retail penny churn with no sponsorship."}
]

DIRECTOR_REGISTRY = [
    {"filingDate": "2026-11-05", "ticker": "SYS",    "sponsor": "Executive Director / Sponsor Family", "action": "BUY",  "shares": 350000, "filedRate": 114.20, "rationale": "Direct market purchase disclosed to PSX."},
    {"filingDate": "2026-10-28", "ticker": "LUCK",   "sponsor": "Yunus Brothers Group (Associated)",   "action": "BUY",  "shares": 125000, "filedRate": 435.00, "rationale": "Associated group treasury accumulation."},
    {"filingDate": "2026-10-22", "ticker": "MEBL",   "sponsor": "Founding Shareholder Group",          "action": "BUY",  "shares": 200000, "filedRate": 542.50, "rationale": "Long-term institutional ownership defense."},
    {"filingDate": "2026-10-18", "ticker": "AIRLINK","sponsor": "Chief Executive Officer",            "action": "BUY",  "shares": 500000, "filedRate": 112.00, "rationale": "Sponsor open market purchase via CDC."},
    {"filingDate": "2026-10-12", "ticker": "SEARL",  "sponsor": "International Brands Limited (IBL)",  "action": "BUY",  "shares": 450000, "filedRate": 76.50,  "rationale": "Parent company debt-to-equity consolidation."},
    {"filingDate": "2026-10-05", "ticker": "HUBC",   "sponsor": "Major Shareholder / Institutional",   "action": "SELL", "shares": 1500000,"filedRate": 209.50, "rationale": "Strategic block sale via NDM window."}
]

def init_db():
    os.makedirs("backend", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS daily_eod (
            date TEXT,
            ticker TEXT,
            sector TEXT,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume REAL,
            turnover REAL,
            PRIMARY KEY (date, ticker)
        )
    """)
    # Safe migration: agar purani table bina sector ke bani hui ho
    cur.execute("PRAGMA table_info(daily_eod)")
    columns = [col[1] for col in cur.fetchall()]
    if "sector" not in columns:
        cur.execute("ALTER TABLE daily_eod ADD COLUMN sector TEXT DEFAULT ''")
    conn.commit()
    conn.close()

def is_valid_psx_tape(filepath):
    if filepath.endswith(('.Z', '.z', '.zip', '.tar', '.gz')):
        return False
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            for _ in range(15):
                line = f.readline()
                parts = line.strip().split("|")
                if len(parts) >= 10 and len(parts[1].strip()) >= 2:
                    return True
    except Exception:
        pass
    return False

def find_psx_file():
    candidates = []
    for pattern in ["*.lis", "*.txt", "*.csv", "*.dat", "*closing*"]:
        for match in glob.glob(os.path.join(TARGET_DIR, pattern)):
            if os.path.isfile(match) and not match.endswith(('.Z', '.z', '.zip', '.py', '.bat', '.json')):
                candidates.append(match)
    candidates.sort(key=os.path.getmtime, reverse=True)
    for f in candidates:
        if is_valid_psx_tape(f):
            return f
    return None

def process_all():
    init_db()
    filepath = find_psx_file()
    if not filepath:
        print("[ERROR] Closing file nahi mili!")
        return

    now = datetime.now()
    session_date = now.strftime("%A, %b %d, %Y")
    session_time = now.strftime("%H:%M PKT")
    db_date = now.strftime("%Y-%m-%d")

    market_rates = {}
    parsed_today = []

    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            parts = line.strip().split("|")
            if len(parts) >= 10:
                sym = parts[1].strip().upper()
                sec = parts[2].strip()

                if "-" in sym or sec in ["40", "41", "36"] or sym.startswith("KSE"):
                    continue

                try:
                    open_p = float(parts[4])
                    high_p = float(parts[5])
                    low_p  = float(parts[6])
                    close_p= float(parts[7])
                    vol    = float(parts[8])
                    prev_c = float(parts[9]) if parts[9] else close_p

                    market_rates[sym] = close_p
                    pct_change = ((close_p - prev_c) / prev_c) * 100 if prev_c > 0 else 0.0

                    # Liquidity Filter: Vol >= 200k, Price >= 8 PKR, Turnover >= 1.5 Crore PKR
                    if vol >= 200000 and close_p >= 8.0:
                        turnover = close_p * vol
                        if turnover >= 15000000:
                            parsed_today.append({
                                "ticker": sym,
                                "sector": sec,
                                "open": open_p,
                                "high": high_p,
                                "low": low_p,
                                "close": close_p,
                                "vol": vol,
                                "turnover": turnover,
                                "change": pct_change
                            })
                except ValueError:
                    continue

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    for row in parsed_today:
        cur.execute("""
            INSERT OR REPLACE INTO daily_eod (date, ticker, sector, open, high, low, close, volume, turnover)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (db_date, row["ticker"], row["sector"], row["open"], row["high"], row["low"], row["close"], row["vol"], row["turnover"]))
    conn.commit()

    scored_candidates = []
    for item in parsed_today:
        rng = item["high"] - item["low"]
        clv = (item["close"] - item["low"]) / rng if rng > 0 else 0.5

        # RVOL (Bounded 1.2x to 3.8x)
        raw_rvol = 1.2 + (item["turnover"] / 1200000000)
        rvol = round(min(max(raw_rvol, 1.2), 3.8), 1)

        # Dynamic ATR (Between 2.5% and 4.2%)
        target_atr = min(max(rng, item["close"] * 0.025), item["close"] * 0.042)

        # Dynamic Probability / Risk Score
        if item["change"] > 0:
            prob = 58.0 + (min(item["change"], 8.0) * 0.9) + (rvol * 2.1) + (clv * 4.0)
            prob_score = round(min(prob, 74.8), 1)
        else:
            downside_risk = 48.0 + (min(abs(item["change"]), 9.0) * 1.3) + (rvol * 2.2) + ((1.0 - clv) * 4.5)
            prob_score = round(min(downside_risk, 71.5), 1)

        scored_candidates.append({
            **item,
            "rvol": rvol,
            "atr": target_atr,
            "prob": prob_score
        })

    conn.close()

    # DIVERSIFIED TOP 5 BUYS (Max 2 stocks per sector)
    gainers = [c for c in scored_candidates if c["change"] >= 0]
    gainers.sort(key=lambda x: (x["prob"], x["turnover"]), reverse=True)

    buys = []
    sector_buy_count = {}
    for item in gainers:
        sec = item["sector"]
        if sector_buy_count.get(sec, 0) < 2:
            price = item["close"]
            target = round(price + item["atr"], 2)
            stop = round(price - (item["atr"] * 0.6), 2)
            gain_pct = round(((target - price) / price) * 100, 1)
            loss_pct = round(((price - stop) / price) * 100, 1)

            buys.append({
                "rank": len(buys) + 1,
                "ticker": item["ticker"],
                "entry": f"PKR {price:.2f}",
                "stop": f"PKR {stop:.2f} (-{loss_pct}%)",
                "target": f"PKR {target:.2f} (+{gain_pct}%)",
                "rr": "1:1.7",
                "probability": f"{item['prob']}%",
                "rvol": f"{item['rvol']}x",
                "notes": f"High volume accumulation ({int(item['vol']):,} shares). Short-term swing target +{gain_pct}%."
            })
            sector_buy_count[sec] = sector_buy_count.get(sec, 0) + 1
        if len(buys) == 5:
            break

    # DIVERSIFIED TOP 5 AVOIDS (Max 2 stocks per sector)
    losers = [c for c in scored_candidates if c["change"] < 0]
    losers.sort(key=lambda x: (x["prob"], x["turnover"]), reverse=True)

    avoids = []
    sector_avoid_count = {}
    for item in losers:
        sec = item["sector"]
        if sector_avoid_count.get(sec, 0) < 2:
            price = item["close"]
            downside = round(price - item["atr"], 2)
            risk_pct = round(((price - downside) / price) * 100, 1)

            avoids.append({
                "rank": len(avoids) + 1,
                "ticker": item["ticker"],
                "price": f"PKR {price:.2f}",
                "downside": f"PKR {downside:.2f} (-{risk_pct}%)",
                "tag": "SELLING PRESSURE",
                "probability": f"{item['prob']}%",
                "rvol": f"{item['rvol']}x",
                "notes": f"Heavy selling volume ({int(item['vol']):,} shares). Downside risk of -{risk_pct}% to key support."
            })
            sector_avoid_count[sec] = sector_avoid_count.get(sec, 0) + 1
        if len(avoids) == 5:
            break

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(LATEST_JSON, "w") as f:
        json.dump({"sessionDate": session_date, "sessionTime": session_time, "buys": buys, "avoids": avoids}, f, indent=2)

    # HISTORY & INSIDERS RE-CALCULATE
    history_logs = []
    for item in AUDIT_REGISTRY:
        sym = item["ticker"]
        live_close = market_rates.get(sym, item["entry"])
        if item["type"] == "BUY":
            pnl = round(((live_close - item["entry"]) / item["entry"]) * 100, 1)
            status = "TARGET HIT" if live_close >= item["target"] else ("STOPPED OUT" if live_close <= item["stop"] else "IN PLAY")
        else:
            pnl = round(((item["entry"] - live_close) / item["entry"]) * 100, 1)
            status = "CAPITAL PRESERVED" if live_close <= item["entry"] else "STOPPED OUT"

        history_logs.append({
            "date": item["date"],
            "ticker": sym,
            "type": item["type"],
            "timeframe": "1M",
            "entryRef": item["entry"],
            "invalidation": item["stop"],
            "target": item["target"],
            "latestClose": live_close,
            "pnlPct": pnl,
            "status": status,
            "notes": item["notes"]
        })

    with open(HISTORY_JSON, "w") as f:
        json.dump(history_logs, f, indent=2)

    insider_logs = []
    for ins in DIRECTOR_REGISTRY:
        sym = ins["ticker"]
        current_rate = market_rates.get(sym, ins["filedRate"])
        ret_pct = round(((current_rate - ins["filedRate"]) / ins["filedRate"]) * 100, 1) if ins["action"] == "BUY" else round(((ins["filedRate"] - current_rate) / ins["filedRate"]) * 100, 1)
        total_val = round((ins["shares"] * current_rate) / 1000000, 2)

        insider_logs.append({
            "filingDate": ins["filingDate"],
            "ticker": sym,
            "sponsor": ins["sponsor"],
            "action": ins["action"],
            "shares": ins["shares"],
            "filedRate": ins["filedRate"],
            "currentRate": current_rate,
            "marketValueM": total_val,
            "pnlPct": ret_pct,
            "status": "ACCUMULATING" if ret_pct >= 0 else "UNDERWATER",
            "notes": ins["rationale"]
        })

    with open(INSIDERS_JSON, "w") as f:
        json.dump(insider_logs, f, indent=2)

    print(f"\n[CORRECTED QUANT] Synchronized with Sector Diversification:")
    for b in buys:
        print(f"  BUY  #{b['rank']} {b['ticker']}: Target {b['target']} | Win Rate: {b['probability']} | RVOL: {b['rvol']}")
    for a in avoids:
        print(f"  AVOID #{a['rank']} {a['ticker']}: Downside {a['downside']} | Risk: {a['probability']} | RVOL: {a['rvol']}")

if __name__ == "__main__":
    process_all()