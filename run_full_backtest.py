import sqlite3
import json
import os
import sys
import urllib.request
import lzma
from datetime import datetime, timedelta

# Backend path setup
sys.path.append(os.path.join(os.path.dirname(__file__), "backend", "scripts"))
try:
    from process_daily_tape import analyse, liquid, DB_PATH, ensure_tables
except ImportError:
    DB_PATH = "backend/data/psx.db"

def backfill_historical_tapes(conn, days=250):
    print(f"Checking and backfilling historical PSX .Z tapes for the last {days} days...")
    cur = conn.cursor()
    ensure_tables(conn)
    
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=days)
    
    current = start_date
    success_count = 0
    
    while current <= end_date:
        # Skip weekends (Saturday=5, Sunday=6)
        if current.weekday() < 5:
            date_str = current.strftime("%Y-%m-%d")
            # Check if data already exists for this date
            exists = cur.execute("SELECT 1 FROM psx_daily_eod WHERE trade_date = ? LIMIT 1", (current.strftime("%d%b%Y"),)).fetchone()
            if not exists:
                url = f"https://dps.psx.com.pk/download/mkt_summary/{date_str}.Z"
                try:
                    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        content = resp.read()
                        # PSX .Z files are LZW compressed or raw text
                        try:
                            # Try lzma or standard decode
                            try:
                                text_data = lzma.decompress(content).decode("utf-8", errors="ignore")
                            except:
                                text_data = content.decode("utf-8", errors="ignore")
                            
                            # Parse JSON if applicable or insert into DB
                            data = json.loads(text_data)
                            trade_date_raw = data.get("date", current.strftime("%d%b%Y"))
                            
                            for item in data.get("symbols", []):
                                symbol = item.get("symbol")
                                close = float(item.get("close", 0) or 0)
                                low = float(item.get("low", 0) or 0)
                                high = float(item.get("high", 0) or 0)
                                volume = float(item.get("volume", 0) or 0)
                                
                                if symbol and close > 0:
                                    is_future = "-" in symbol
                                    table = "psx_futures_eod" if is_future else "psx_daily_eod"
                                    cur.execute(f"""
                                        INSERT OR REPLACE INTO {table} (trade_date, ticker, symbol, close_price, low_price, high_price, volume)
                                        VALUES (?, ?, ?, ?, ?, ?, ?)
                                    """, (trade_date_raw, symbol.split("-")[0], symbol, close, low, high, volume))
                            conn.commit()
                            success_count += 1
                            print(f"[BACKFILL] Loaded {date_str}")
                        except Exception as parse_err:
                            pass
                except Exception:
                    pass
        current += timedelta(days=1)
    print(f"Backfill complete. Successfully fetched {success_count} new historical sessions.")

def run_full_year_backtest():
    if not os.path.exists("backend/data"):
        os.makedirs("backend/data", exist_ok=True)
        
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    # 1. Backfill historical data first
    backfill_historical_tapes(conn, days=250)
    
    cur = conn.cursor()
    dates_raw = [r[0] for r in cur.execute("SELECT DISTINCT trade_date FROM psx_daily_eod ORDER BY rowid ASC")]
    
    if len(dates_raw) < 20:
        print(f"Warning: Only {len(dates_raw)} sessions available in DB. Proceeding with available sessions...")
    else:
        print(f"Total available sessions for backtest: {len(dates_raw)}")

    total_signals = 0
    wins = 0
    losses = 0
    ledger = []

    for i in range(15, len(dates_raw)):
        current_session = dates_raw[i]
        lookback_window = dates_raw[i-15:i]
        
        try:
            session_date = datetime.strptime(current_session, "%d%b%Y").date()
        except ValueError:
            try:
                session_date = datetime.strptime(current_session, "%Y-%m-%d").date()
            except:
                continue

        try:
            liquid_tickers = liquid(cur, lookback_window, current_session)
            sweeps, leaders, traps = analyse(cur, current_session, session_date, liquid_tickers)
        except Exception:
            continue

        all_signals = []
        for s in sweeps:
            all_signals.append({"ticker": s["ticker"], "type": "BUY", "entry": s["poc"], "stop": s["poc"] * 0.93, "target": s["poc"] * 1.12, "date": current_session})
        for t in traps:
            all_signals.append({"ticker": t["ticker"], "type": "AVOID/SHORT", "entry": t["spotClose"], "stop": t["spotClose"] * 1.05, "target": t["spotClose"] * 0.88, "date": current_session})

        for sig in all_signals:
            total_signals += 1
            ticker = sig["ticker"]
            entry_type = sig["type"]
            entry_price = sig["entry"]
            stop_price = sig["stop"]
            target_price = sig["target"]
            
            outcome = "IN PLAY / UNRESOLVED"
            pnl_pct = 0.0

            future_sessions = dates_raw[i+1 : min(i+21, len(dates_raw))]