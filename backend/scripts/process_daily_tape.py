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

KSE_INSTITUTIONAL_CORE = {
    "UBL", "MCB", "MEBL", "HBL", "BAHL", "BAFL", "NBP", "BOP", "AKBL",
    "MLCF", "LUCK", "DGKC", "FCCL", "PIOC", "CHCC", "ACPL", "BWCL", "KOHC",
    "OGDC", "PPL", "MARI", "POL", "PSO", "SNGP", "SSGC",
    "FFC", "EFERT", "FATIMA",
    "SYS", "TRG", "AIRLINK", "AVN", "NETSOL", "OCTOPUS",
    "PRL", "NRL", "ATRL", "CNERGY",
    "HUBC", "KAPCO", "KEL", "EPCL", "LOTCHEM", "SEARL", "AGP", "ABOT",
    "ILP", "NML", "PAEL", "UNITY", "INIL", "ISL", "MTL", "INDU", "HCAR",
    "THALL", "GTYR", "TREET", "AICL"
}

DIRECTOR_REGISTRY = [
    {"filingDate": "2026-11-05", "ticker": "SYS",    "sponsor": "Executive Director / Sponsor Family", "action": "BUY",  "shares": 350000, "filedRate": 114.20, "rationale": "Direct market purchase disclosed to PSX."},
    {"filingDate": "2026-10-28", "ticker": "LUCK",   "sponsor": "Yunus Brothers Group (Associated)",   "action": "BUY",  "shares": 125000, "filedRate": 435.00, "rationale": "Associated group treasury accumulation."},
    {"filingDate": "2026-10-22", "ticker": "MEBL",   "sponsor": "Founding Shareholder Group",          "action": "BUY",  "shares": 200000, "filedRate": 542.50, "rationale": "Long-term institutional ownership defense."},
    {"filingDate": "2026-10-18", "ticker": "AIRLINK","sponsor": "Chief Executive Officer",            "action": "BUY",  "shares": 500000, "filedRate": 112.00, "rationale": "Sponsor open market purchase via CDC."},
    {"filingDate": "2026-10-12", "ticker": "SEARL",  "sponsor": "International Brands Limited (IBL)",  "action": "BUY",  "shares": 450000, "filedRate": 76.50,  "rationale": "Parent company debt-to-equity consolidation."},
    {"filingDate": "2026-10-05", "ticker": "HUBC",   "sponsor": "Major Shareholder / Institutional",   "action": "SELL", "shares": 1500000,"filedRate": 209.50, "rationale": "Strategic block sale via NDM window."}
]

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

def compute_historical_metrics(cur, ticker, current_close, current_vol):
    cur.execute("""
        SELECT close, high, low, volume FROM daily_eod
        WHERE ticker = ? ORDER BY date DESC LIMIT 50
    """, (ticker,))
    rows = cur.fetchall()

    if not rows or len(rows) < 5:
        # Fallback if brand new ticker
        return {"rvol": 1.2, "sma50": current_close, "atr14": current_close * 0.035, "trend": "NEUTRAL"}

    vols_20 = [r[3] for r in rows[:20] if r[3] is not None and r[3] > 0]
    avg_vol_20 = sum(vols_20) / len(vols_20) if vols_20 else current_vol
    rvol = round(current_vol / avg_vol_20, 1) if avg_vol_20 > 0 else 1.0
    rvol = min(max(rvol, 0.5), 6.5)

    closes_50 = [r[0] for r in rows if r[0] is not None]
    sma50 = sum(closes_50) / len(closes_50) if closes_50 else current_close
    trend = "BULLISH" if current_close >= sma50 else "BEARISH"

    # True 14-day ATR calculation
    tr_list = []
    for i in range(min(14, len(rows) - 1)):
        c_prev = rows[i+1][0]
        h_curr = rows[i][1]
        l_curr = rows[i][2]
        if c_prev and h_curr and l_curr:
            tr = max(h_curr - l_curr, abs(h_curr - c_prev), abs(l_curr - c_prev))
            tr_list.append(tr)

    atr14 = sum(tr_list) / len(tr_list) if tr_list else (current_close * 0.032)
    return {"rvol": rvol, "sma50": round(sma50, 2), "atr14": round(atr14, 2), "trend": trend}

def process_all():
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
    advances = 0
    declines = 0
    kse100_pct = None

    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            parts = line.strip().split("|")
            if len(parts) >= 10:
                sym = parts[1].strip().upper()
                sec = parts[2].strip()

                try:
                    open_p = float(parts[4])
                    high_p = float(parts[5])
                    low_p  = float(parts[6])
                    close_p= float(parts[7])
                    vol    = float(parts[8])
                    prev_c = float(parts[9]) if parts[9] else close_p
                    pct_change = ((close_p - prev_c) / prev_c) * 100 if prev_c > 0 else 0.0

                    if "KSE100" in sym or sym == "KSE100" or sym == "KSE-100":
                        kse100_pct = pct_change
                        continue

                    if "-" in sym or sec in ["40", "41", "36"] or sym.startswith("KSE"):
                        continue

                    market_rates[sym] = close_p
                    if pct_change > 0:
                        advances += 1
                    elif pct_change < 0:
                        declines += 1

                    if sym in KSE_INSTITUTIONAL_CORE and vol >= 150000:
                        turnover = close_p * vol
                        if turnover >= 20000000:
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

    total_active = advances + declines
    breadth_pct = round((advances / total_active) * 100, 1) if total_active > 0 else 50.0
    if kse100_pct is None:
        kse100_pct = round((breadth_pct - 50.0) / 12.0, 2)

    is_defensive = (kse100_pct <= -0.8) or (breadth_pct <= 38.0)
    regime_status = "DEFENSIVE (CASH MODE)" if is_defensive else "BULLISH ACCUMULATION"
    regime_note = "High macro distribution detected. KSE-100 under heavy selling. New buy setups blocked to protect capital." if is_defensive else "Healthy market breadth. Tier-1 institutional accumulation active across key sectors."

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Ingest today's session into database
    for row in parsed_today:
        cur.execute("""
            INSERT OR REPLACE INTO daily_eod (date, ticker, sector, open, high, low, close, volume, turnover)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (db_date, row["ticker"], row["sector"], row["open"], row["high"], row["low"], row["close"], row["vol"], row["turnover"]))
    conn.commit()

    scored_candidates = []
    for item in parsed_today:
        metrics = compute_historical_metrics(cur, item["ticker"], item["close"], item["vol"])
        rng = item["high"] - item["low"]
        clv = (item["close"] - item["low"]) / rng if rng > 0 else 0.5
        rvol = metrics["rvol"]
        atr14 = metrics["atr14"]

        # MULTI-FACTOR COMPOSITE QUANT FORMULA
        if item["change"] > 0:
            trend_bonus = 6.0 if metrics["trend"] == "BULLISH" else -4.0
            prob = 54.0 + (min(item["change"], 7.0) * 0.9) + (min(rvol, 3.5) * 2.4) + (clv * 4.5) + trend_bonus
            prob_score = round(min(max(prob, 55.0), 78.5), 1)
        else:
            trend_penalty = 5.0 if metrics["trend"] == "BEARISH" else -2.0
            downside_risk = 46.0 + (min(abs(item["change"]), 8.0) * 1.4) + (min(rvol, 3.5) * 2.2) + ((1.0 - clv) * 4.5) + trend_penalty
            prob_score = round(min(max(downside_risk, 50.0), 76.0), 1)

        scored_candidates.append({
            **item,
            "rvol": rvol,
            "atr": atr14,
            "prob": prob_score,
            "trend": metrics["trend"]
        })

    # TOP 5 BUYS (Diversified across sectors, supported by 50-SMA trend)
    gainers = [c for c in scored_candidates if c["change"] >= 0]
    gainers.sort(key=lambda x: (x["turnover"] * (1.2 if x["trend"] == "BULLISH" else 0.8), x["prob"]), reverse=True)

    buys = []
    if not is_defensive:
        sector_buy_count = {}
        for item in gainers:
            sec = item["sector"]
            if sector_buy_count.get(sec, 0) < 2:
                price = item["close"]
                target = round(price + item["atr"], 2)
                stop = round(price - (item["atr"] * 0.6), 2)
                gain_pct = round(((target - price) / price) * 100, 1)
                loss_pct = round(((price - stop) / price) * 100, 1)

                zone_low = round(price * 0.994, 2)
                zone_high = round(price * 1.004, 2)

                buys.append({
                    "rank": len(buys) + 1,
                    "ticker": item["ticker"],
                    "entry": f"PKR {price:.2f}",
                    "entryZone": f"PKR {zone_low:.2f} - {zone_high:.2f}",
                    "stop": f"PKR {stop:.2f} (-{loss_pct}%)",
                    "target": f"PKR {target:.2f} (+{gain_pct}%)",
                    "raw_entry": price,
                    "raw_stop": stop,
                    "raw_target": target,
                    "rr": "1:1.7",
                    "probability": f"{item['prob']}%",
                    "rvol": f"{item['rvol']}x",
                    "notes": f"Historical {item['trend']} trend ({int(item['vol']):,} shares, PKR {round(item['turnover']/10000000, 1)}Cr turnover). Swing target +{gain_pct}%."
                })
                sector_buy_count[sec] = sector_buy_count.get(sec, 0) + 1
            if len(buys) == 5:
                break

    # TOP 5 AVOIDS (Pass 1: Max 2 per sector, Pass 2: Fallback fill for 5th slot)
    losers = [c for c in scored_candidates if c["change"] < 0]
    losers.sort(key=lambda x: (x["turnover"], x["prob"]), reverse=True)

    def build_avoid_item(item, rank):
        price = item["close"]
        downside = round(price - item["atr"], 2)
        risk_pct = round(((price - downside) / price) * 100, 1)
        stop_ref = round(price + (item["atr"] * 0.5), 2)
        return {
            "rank": rank,
            "ticker": item["ticker"],
            "price": f"PKR {price:.2f}",
            "downside": f"PKR {downside:.2f} (-{risk_pct}%)",
            "raw_price": price,
            "raw_stop": stop_ref,
            "raw_downside": downside,
            "tag": "SELLING PRESSURE",
            "probability": f"{item['prob']}%",
            "rvol": f"{item['rvol']}x",
            "notes": f"Historical {item['trend']} breakdown ({int(item['vol']):,} shares, PKR {round(item['turnover']/10000000, 1)}Cr turnover). Downside risk of -{risk_pct}%."
        }

    avoids = []
    sector_avoid_count = {}
    for item in losers:
        sec = item["sector"]
        if sector_avoid_count.get(sec, 0) < 2:
            avoids.append(build_avoid_item(item, len(avoids) + 1))
            sector_avoid_count[sec] = sector_avoid_count.get(sec, 0) + 1
        if len(avoids) == 5:
            break

    if len(avoids) < 5:
        selected_tickers = {a["ticker"] for a in avoids}
        for item in losers:
            if item["ticker"] not in selected_tickers:
                avoids.append(build_avoid_item(item, len(avoids) + 1))
                selected_tickers.add(item["ticker"])
            if len(avoids) == 5:
                break

    # Dynamic Ledger: Insert today's recommended calls into DB
    for b in buys:
        cur.execute("""
            INSERT OR IGNORE INTO active_trades (date, ticker, type, entry, stop, target, status, notes)
            VALUES (?, ?, 'BUY', ?, ?, ?, 'IN PLAY', ?)
        """, (db_date, b["ticker"], b["raw_entry"], b["raw_stop"], b["raw_target"], b["notes"]))

    for a in avoids:
        cur.execute("""
            INSERT OR IGNORE INTO active_trades (date, ticker, type, entry, stop, target, status, notes)
            VALUES (?, ?, 'AVOID', ?, ?, ?, 'IN PLAY', ?)
        """, (db_date, a["ticker"], a["raw_price"], a["raw_stop"], a["raw_downside"], a["notes"]))
    conn.commit()

    # Audit all trades against active tape
    cur.execute("SELECT date, ticker, type, entry, stop, target, status, notes FROM active_trades ORDER BY date DESC, ticker ASC")
    db_trades = cur.fetchall()

    history_logs = []
    for t_date, sym, t_type, t_entry, t_stop, t_target, prev_status, t_notes in db_trades:
        live_close = market_rates.get(sym, t_entry)
        if t_type == "BUY":
            pnl = round(((live_close - t_entry) / t_entry) * 100, 1)
            status = "TARGET HIT" if live_close >= t_target else ("STOPPED OUT" if live_close <= t_stop else "IN PLAY")
        else:
            pnl = round(((t_entry - live_close) / t_entry) * 100, 1)
            status = "CAPITAL PRESERVED" if live_close <= t_target else ("STOPPED OUT" if live_close >= t_stop else "IN PLAY")

        if status != prev_status:
            cur.execute("UPDATE active_trades SET status = ? WHERE date = ? AND ticker = ? AND type = ?", (status, t_date, sym, t_type))

        history_logs.append({
            "date": t_date,
            "ticker": sym,
            "type": t_type,
            "timeframe": "1M",
            "entryRef": t_entry,
            "invalidation": t_stop,
            "target": t_target,
            "latestClose": live_close,
            "pnlPct": pnl,
            "status": status,
            "notes": t_notes
        })
    conn.commit()
    conn.close()

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(LATEST_JSON, "w") as f:
        json.dump({
            "sessionDate": session_date,
            "sessionTime": session_time,
            "regime": {
                "status": regime_status,
                "kseChange": f"{kse100_pct:+.2f}%",
                "breadth": f"{breadth_pct}% Advancing ({advances} Up / {declines} Down)",
                "note": regime_note,
                "isDefensive": is_defensive
            },
            "buys": buys,
            "avoids": avoids
        }, f, indent=2)

    with open(HISTORY_JSON, "w") as f:
        json.dump(history_logs, f, indent=2)

    # Re-evaluate Insiders
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

    print(f"\n[HISTORICAL MULTI-FACTOR ENGINE] Synchronized for {session_date}:")
    print(f"  Regime: {regime_status} | KSE-100: {kse100_pct:+.2f}% | Breadth: {breadth_pct}%")
    print(f"  Active Ledger: {len(history_logs)} lifetime setups audited against 1-year database.")
    for b in buys:
        print(f"  BUY  #{b['rank']} {b['ticker']}: Zone {b['entryZone']} | Target: {b['target']} | RVOL: {b['rvol']}")
    for a in avoids:
        print(f"  AVOID #{a['rank']} {a['ticker']}: Downside {a['downside']} | Risk: {a['probability']} | RVOL: {a['rvol']}")

if __name__ == "__main__":
    process_all()