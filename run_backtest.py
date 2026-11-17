import sqlite3
import json
from datetime import datetime, timedelta
import os
import sys

# Backend script se analysis logic import karne ke liye path set karte hain
sys.path.append(os.path.join(os.path.dirname(__file__), "backend", "scripts"))

try:
    from process_daily_tape import analyse, liquid, DB_PATH
except ImportError:
    # Fallback agar path alag ho
    DB_PATH = "backend/data/psx.db"

def run_historical_backtest():
    if not os.path.exists(DB_PATH):
        print(f"Error: Database not found at {DB_PATH}. Pehle process_daily_tape.py run karo.")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Saari available trade dates nikalo sorted order mein
    dates_raw = [r[0] for r in cur.execute("SELECT DISTINCT trade_date FROM psx_daily_eod ORDER BY rowid ASC")]
    if not dates_raw:
        print("Database mein koi dates nahi mili!")
        return

    print(f"Total available sessions in DB: {len(dates_raw)}")
    
    # Pichle 1 saal (approx last 250 sessions) select karte hain
    backtest_sessions = dates_raw[-250:] if len(dates_raw) > 250 else dates_raw
    print(f"Running backtest across last {len(backtest_sessions)} sessions...")

    total_signals = 0
    wins = 0
    losses = 0
    ledger = []

    # Har session par loop chalayenge (Time-travel backtest)
    for i in range(15, len(backtest_sessions)):
        current_session = backtest_sessions[i]
        # Pichle 15 sessions ki history lete hain liquidity ke liye
        lookback_window = backtest_sessions[i-15:i]
        
        try:
            session_date = datetime.strptime(current_session, "%d%b%Y").date()
        except ValueError:
            try:
                session_date = datetime.strptime(current_session, "%Y-%m-%d").date()
            except:
                continue

        # Analyse function call karte hain jo V5 logic run karta hai
        try:
            liquid_tickers = liquid(cur, lookback_window, current_session)
            sweeps, leaders, traps = analyse(cur, current_session, session_date, liquid_tickers)
        except Exception as e:
            continue

        # Signals collect karo
        all_signals = []
        for s in sweeps:
            all_signals.append({"ticker": s["ticker"], "type": "BUY", "entry": s["poc"], "stop": s["poc"] * 0.93, "target": s["poc"] * 1.12, "date": current_session})
        for t in traps:
            all_signals.append({"ticker": t["ticker"], "type": "AVOID/SHORT", "entry": t["spotClose"], "stop": t["spotClose"] * 1.05, "target": t["spotClose"] * 0.88, "date": current_session})

        # Future sessions mein check karo ke target hit hua ya stop loss
        for sig in all_signals:
            total_signals += 1
            ticker = sig["ticker"]
            entry_type = sig["type"]
            entry_price = sig["entry"]
            stop_price = sig["stop"]
            target_price = sig["target"]
            
            outcome = "IN PLAY / UNRESOLVED"
            pnl_pct = 0.0

            # Aage ke sessions mein price action check karo (max 20 sessions horizon)
            future_sessions = backtest_sessions[i+1 : min(i+21, len(backtest_sessions))]
            for fut_sess in future_sessions:
                row = cur.execute("SELECT close_price, low_price, high_price FROM psx_daily_eod WHERE ticker = ? AND trade_date = ?", (ticker, fut_sess)).fetchone()
                if not row:
                    continue
                
                low = row["low_price"]
                high = row["high_price"]
                close = row["close_price"]

                if entry_type == "BUY":
                    if low <= stop_price:
                        outcome = "STOPPED OUT"
                        pnl_pct = ((stop_price - entry_price) / entry_price) * 100
                        break
                    elif high >= target_price:
                        outcome = "TARGET HIT"
                        pnl_pct = ((target_price - entry_price) / entry_price) * 100
                        break
                else: # SHORT / AVOID
                    if high >= stop_price:
                        outcome = "STOPPED OUT (SHORT)"
                        pnl_pct = -5.0
                        break
                    elif low <= target_price:
                        outcome = "TARGET HIT (SHORT)"
                        pnl_pct = 12.0
                        break
            
            if "TARGET" in outcome:
                wins += 1
            elif "STOP" in outcome:
                losses += 1

            ledger.append({
                "date": current_session,
                "ticker": ticker,
                "side": entry_type,
                "entry": entry_price,
                "outcome": outcome,
                "pnl": round(pnl_pct, 2)
            })

    print("\n================ BACKTEST RESULTS (LAST 1 YEAR) ================")
    print(f"Total Signals Generated : {total_signals}")
    print(f"Resolved Wins           : {wins}")
    print(f"Resolved Losses         : {losses}")
    win_rate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0
    print(f"Backtested Win Rate     : {win_rate:.1f}%")
    print("================================================================")

    # Output ko JSON mein save karlo taaki frontend par bhi dikha sakein agar chaho
    os.makedirs("frontend/public/data", exist_ok=True)
    with open("frontend/public/data/backtest_results.json", "w", encoding="utf-8") as f:
        json.dump({"totalSignals": total_signals, "wins": wins, "losses": losses, "winRate": win_rate, "ledger": ledger}, f, indent=2)
    print("Saved detailed backtest report to frontend/public/data/backtest_results.json")

if __name__ == "__main__":
    run_historical_backtest()