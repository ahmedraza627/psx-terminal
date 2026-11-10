import os
import json
import glob
import sqlite3
import math
from datetime import datetime

DATA_DIR = os.path.join("frontend", "public", "data")
LATEST_JSON = os.path.join(DATA_DIR, "latest.json")
HISTORY_JSON = os.path.join(DATA_DIR, "history.json")
INSIDERS_JSON = os.path.join(DATA_DIR, "insiders.json")
DB_PATH = os.path.join("backend", "psx_history.db")
TARGET_DIR = r"D:\downloads"

AUDIT_REGISTRY = [
    {"date": "2026-11-09", "ticker": "MCB",  "type": "BUY",   "entry": 399.48, "stop": 382.70, "target": 433.40, "notes": "Corporate liquidity & spread defense."},
    {"date": "2026-11-08", "ticker": "MARI", "type": "BUY",   "entry": 651.98, "stop": 624.60, "target": 707.40, "notes": "Commercial discovery expansion."},
    {"date": "2026-11-06", "ticker": "MEBL", "type": "BUY",   "entry": 550.25, "stop": 527.14, "target": 597.00, "notes": "Islamic bank dividend floor."},
    {"date": "2026-11-05", "ticker": "HUBC", "type": "AVOID", "entry": 208.00, "stop": 220.50, "target": 184.00, "notes": "Retail trap at renegotiation resistance."},
    {"date": "2026-11-04", "ticker": "SYS",  "type": "BUY",   "entry": 114.60, "stop": 109.80, "target": 124.30, "notes": "Foreign accumulation support test."},
    {"date": "2026-10-30", "ticker": "PRL",  "type": "AVOID", "entry": 85.55,  "stop": 90.70,  "target": 72.00,  "notes": "Refinery policy supply overhang."},
    {"date": "2026-10-25", "ticker": "FFC",  "type": "BUY",   "entry": 525.00, "stop": 502.95, "target": 570.00, "notes": "Fertilizer cashflow yield pivot."},
    {"date": "2026-10-20", "ticker": "LUCK", "type": "BUY",   "entry": 427.23, "stop": 409.28, "target": 463.50, "notes": "Cement conglomerate breakout."},
    {"date": "2026-10-15", "ticker": "HASCOL","type": "AVOID","entry": 18.20,  "stop": 19.30,  "target": 14.50,  "notes": "Chronic negative balance sheet."},
    {"date": "2026-10-10", "ticker": "WTL",  "type": "AVOID", "entry": 1.25,   "stop": 1.35,   "target": 0.95,   "notes": "Penny churn without sponsorship."}
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
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume REAL,
            turnover REAL,
            PRIMARY KEY (date, ticker)
        )
    """)
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
        print("[ERROR] Uncompressed closing file D:\\downloads mein nahi mili!")
        return

    print(f"[FOUND & VERIFIED] Live Tape File: {filepath}")
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

                    if vol >= 200000 and close_p >= 4.0:
                        turnover = close_p * vol
                        parsed_today.append({
                            "ticker": sym,
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

    # 1. UPSERT INTO SQLITE DB
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    for row in parsed_today:
        cur.execute("""
            INSERT OR REPLACE INTO daily_eod (date, ticker, open, high, low, close, volume, turnover)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (db_date, row["ticker"], row["open"], row["high"], row["low"], row["close"], row["vol"], row["turnover"]))
    conn.commit()

    # 2. QUANT MULTI-FACTOR ENGINE
    scored_candidates = []
    for item in parsed_today:
        sym = item["ticker"]
        # Fetch up to 20 past sessions for baseline
        cur.execute("SELECT high, low, close, volume FROM daily_eod WHERE ticker = ? ORDER BY date DESC LIMIT 20", (sym,))
        hist = cur.fetchall()

        # Relative Volume (RVOL)
        if len(hist) > 1:
            avg_vol = sum([h[3] for h in hist]) / len(hist)
            rvol = round(item["vol"] / avg_vol, 2) if avg_vol > 0 else 1.0
        else:
            rvol = round(item["turnover"] / 15000000, 2)
            rvol = max(1.1, min(rvol, 4.5))

        # Close Location Value (CLV: 0 to 1) - Higher means closed near high
        rng = item["high"] - item["low"]
        if rng > 0:
            clv = (item["close"] - item["low"]) / rng
        else:
            clv = 0.5

        # Dynamic Volatility (ATR Estimation)
        true_range = max(rng, abs(item["high"] - item["close"]), abs(item["low"] - item["close"]))
        atr = true_range if true_range > 0 else (item["close"] * 0.035)

        # Statistical Probability Score (0 to 100)
        # Factors: Turnover depth, RVOL expansion, CLV absorption, Change
        prob_score = 50.0
        if item["change"] > 0:
            prob_score += min(item["change"] * 2.0, 15.0)  # Momentum (+15 max)
            prob_score += min(rvol * 5.0, 15.0)            # RVOL Surge (+15 max)
            prob_score += (clv * 15.0)                     # Near-day high finish (+15 max)
            if item["turnover"] > 50000000:                # Institutional depth (+5)
                prob_score += 5.0
        else:
            prob_score += max(item["change"] * 2.0, -15.0)
            prob_score -= min(rvol * 4.0, 12.0)
            prob_score -= ((1.0 - clv) * 15.0)

        prob_score = round(max(35.0, min(prob_score, 88.0)), 1)

        scored_candidates.append({
            **item,
            "rvol": rvol,
            "clv": round(clv, 2),
            "atr": atr,
            "prob": prob_score
        })

    conn.close()

    # 3. SELECTION LOGIC
    # Buys: High Prob + High Turnover
    gainers = [c for c in scored_candidates if c["change"] >= 0]
    gainers.sort(key=lambda x: (x["prob"], x["turnover"]), reverse=True)
    top_buys_raw = gainers[:5]

    # Avoids: Low Prob + High Volume Distribution
    losers = [c for c in scored_candidates if c["change"] < 0]
    losers.sort(key=lambda x: (x["turnover"], -x["change"]), reverse=True)
    top_avoids_raw = losers[:5]

    buys = []
    for idx, item in enumerate(top_buys_raw, 1):
        price = item["close"]
        # Volatility-adjusted stop (1.5x ATR) and target (3.0x ATR)
        stop = round(max(price - (1.5 * item["atr"]), price * 0.94), 2)
        target = round(price + (2.5 * item["atr"]), 2)
        rr_calc = round((target - price) / (price - stop), 1) if (price - stop) > 0 else 2.0

        buys.append({
            "rank": idx,
            "ticker": item["ticker"],
            "entry": f"PKR {price:.2f}",
            "stop": f"PKR {stop:.2f}",
            "target": f"PKR {target:.2f}",
            "rr": f"1:{rr_calc}",
            "probability": f"{item['prob']}%",
            "rvol": f"{item['rvol']}x",
            "notes": f"Quant Probability {item['prob']}% | RVOL {item['rvol']}x | Volume {int(item['vol']):,} shares."
        })

    avoids = []
    for idx, item in enumerate(top_avoids_raw, 1):
        price = item["close"]
        avoid_ref = round(price + (0.8 * item["atr"]), 2)
        downside = round(price - (2.0 * item["atr"]), 2)
        invalidation = round(price + (1.5 * item["atr"]), 2)

        avoids.append({
            "rank": idx,
            "ticker": item["ticker"],
            "avoidRef": f"PKR {avoid_ref:.2f}",
            "downside": f"PKR {downside:.2f}",
            "price": f"PKR {price:.2f}",
            "invalidation": f"PKR {invalidation:.2f}",
            "tag": "DISTRIBUTION TRAP",
            "probability": f"{100.0 - item['prob']:.1f}%",
            "rvol": f"{item['rvol']}x",
            "notes": f"Heavy Supply Distribution | Downside Risk {100.0 - item['prob']:.1f}% | RVOL {item['rvol']}x."
        })

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(LATEST_JSON, "w") as f:
        json.dump({"sessionDate": session_date, "sessionTime": session_time, "buys": buys, "avoids": avoids}, f, indent=2)

    # 4. AUDIT & RE-VALUATE HISTORY
    history_logs = []
    for item in AUDIT_REGISTRY:
        sym = item["ticker"]
        live_close = market_rates.get(sym, item["entry"])
        
        if item["type"] == "BUY":
            pnl = round(((live_close - item["entry"]) / item["entry"]) * 100, 1)
            if live_close >= item["target"]:
                status = "TARGET HIT"
            elif live_close <= item["stop"]:
                status = "STOPPED OUT"
            else:
                status = "IN PLAY"
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

    # 5. RE-VALUATE INSIDERS
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

    print(f"\n[QUANT V2] Pipeline Synchronized & DB Updated ({db_date}):")
    print(f"  1. latest.json   -> {len(buys)} Buys, {len(avoids)} Avoids (ATR & RVOL Calculated)")
    print(f"  2. history.json  -> {len(history_logs)} Setups audited")
    print(f"  3. insiders.json -> {len(insider_logs)} Sponsor positions re-valued live")

if __name__ == "__main__":
    process_all()