import sqlite3
import os
import sys
from datetime import datetime

# Path setup
sys.path.append(os.path.join(os.path.dirname(__file__), "backend", "scripts"))
try:
    from process_daily_tape import analyse, liquid, DB_PATH
except ImportError:
    DB_PATH = "backend/data/psx.db"

def run_clean_backtest():
    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    dates = [r[0] for r in cur.execute("SELECT DISTINCT trade_date FROM psx_daily_eod ORDER BY rowid ASC")]
    print(f"Total sessions available in DB: {len(dates)}")
    
    if len(dates) < 15:
        print("Not enough sessions for 15-day lookback window.")
        return

    wins = 0
    losses = 0
    total = 0

    for i in range(15, len(dates)):
        curr = dates[i]
        window = dates[i-15:i]
        
        try:
            dt = datetime.strptime(curr, "%d%b%Y").date()
        except ValueError:
            try:
                dt = datetime.strptime(curr, "%Y-%m-%d").date()
            except:
                continue

        try:
            liq = liquid(cur, window, curr)
            sweeps, leaders, traps = analyse(cur, curr, dt, liq)
        except Exception:
            continue

        signals = []
        for s in sweeps:
            signals.append({"ticker": s["ticker"], "type": "BUY", "entry": s["poc"], "stop": s["poc"]*0.93, "target": s["poc"]*1.12})
        for t in traps:
            signals.append({"ticker": t["ticker"], "type": "SHORT", "entry": t["spotClose"], "stop": t["spotClose"]*1.05, "target": t["spotClose"]*0.88})

        for sig in signals:
            total += 1
            ticker = sig["ticker"]
            stype = sig["type"]
            stop = sig["stop"]
            target = sig["target"]
            outcome = "UNRESOLVED"

            future_dates = dates[i+1 : min(i+21, len(dates))]
            for fd in future_dates:
                row = cur.execute("SELECT close_price, low_price, high_price FROM psx_daily_eod WHERE ticker = ? AND trade_date = ?", (ticker, fd)).fetchone()
                if not row:
                    continue
                low, high = row["low_price"], row["high_price"]
                
                if stype == "BUY":
                    if low <= stop:
                        outcome = "STOPPED OUT"
                        break
                    elif high >= target:
                        outcome = "TARGET HIT"
                        break
                else:
                    if high >= stop:
                        outcome = "STOPPED OUT (SHORT)"
                        break
                    elif low <= target:
                        outcome = "TARGET HIT (SHORT)"
                        break

            if "TARGET" in outcome:
                wins += 1
            elif "STOP" in outcome:
                losses += 1

    print("\n================ BACKTEST PERFORMANCE REPORT ================")
    print(f"Total Signals Tested : {total}")
    print(f"Wins                 : {wins}")
    print(f"Losses               : {losses}")
    wr = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0
    print(f"Empirical Win Rate   : {wr:.1f}%")
    print("=============================================================")

if __name__ == "__main__":
    run_clean_backtest()