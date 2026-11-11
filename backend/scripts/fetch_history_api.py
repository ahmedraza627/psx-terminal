import os
import sqlite3
import requests
from datetime import datetime
import time

DB_PATH = os.path.join("backend", "psx_history.db")

# Core Tier-1 Universe (Yahoo Finance Karachi format: TICKER.KA)
CORE_TICKERS = [
    # Banking
    "UBL", "MCB", "MEBL", "HBL", "BAHL", "BAFL", "NBP", "BOP", "AKBL", "FABBL",
    # Cement
    "MLCF", "LUCK", "DGKC", "FCCL", "PIOC", "CHCC", "ACPL", "BWCL", "KOHC",
    # Oil, Gas & E&P
    "OGDC", "PPL", "MARI", "POL", "PSO", "SHEL", "SNGP", "SSGC", "HASCOL",
    # Fertilizer
    "FFC", "ENGRO", "EFERT", "FATIMA", "FFBL",
    # Technology
    "SYS", "TRG", "AIRLINK", "AVN", "NETSOL", "OCTOPUS",
    # Refineries
    "PRL", "NRL", "ATRL", "CNERGY",
    # Power, Chemicals, Pharma & Manufacturing
    "HUBC", "KAPCO", "KEL", "EPCL", "LOTCHEM", "SEARL", "AGP", "ABOT", "ILP", "NML", "PAEL", "UNITY", "INIL", "ISL", "MTL", "INDU", "HCAR", "PSMC", "THALL", "GTYR", "TREET", "AICL"
]

def init_db():
    os.makedirs("backend", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS daily_eod (
            date TEXT, ticker TEXT, sector TEXT, open REAL, high REAL, low REAL, close REAL, volume REAL, turnover REAL,
            PRIMARY KEY (date, ticker)
        )
    """)
    conn.commit()
    conn.close()

def fetch_history_yahoo():
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    print(f"[START] Ingesting 1-Year Historical Bars via Yahoo Finance (.KA) for {len(CORE_TICKERS)} tickers...\n")

    total_records = 0
    synced_tickers = 0

    for idx, ticker in enumerate(CORE_TICKERS, 1):
        yahoo_sym = f"{ticker}.KA"
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_sym}?range=1y&interval=1d"

        try:
            r = requests.get(url, headers=headers, timeout=12)
            if r.status_code == 200:
                payload = r.json()
                results = payload.get("chart", {}).get("result", [])

                if results:
                    data_obj = results[0]
                    timestamps = data_obj.get("timestamp", [])
                    indicators = data_obj.get("indicators", {}).get("quote", [{}])[0]

                    opens = indicators.get("open", [])
                    highs = indicators.get("high", [])
                    lows = indicators.get("low", [])
                    closes = indicators.get("close", [])
                    volumes = indicators.get("volume", [])

                    records = []
                    for i in range(len(timestamps)):
                        if (i < len(opens) and opens[i] is not None and
                            i < len(highs) and highs[i] is not None and
                            i < len(lows) and lows[i] is not None and
                            i < len(closes) and closes[i] is not None):

                            dt_str = datetime.fromtimestamp(timestamps[i]).strftime("%Y-%m-%d")
                            o = round(float(opens[i]), 2)
                            h = round(float(highs[i]), 2)
                            l = round(float(lows[i]), 2)
                            c = round(float(closes[i]), 2)
                            v = float(volumes[i]) if (i < len(volumes) and volumes[i] is not None) else 0.0
                            turnover = round(c * v, 2)

                            records.append((dt_str, ticker, "", o, h, l, c, v, turnover))

                    if records:
                        cur.executemany("""
                            INSERT OR REPLACE INTO daily_eod (date, ticker, sector, open, high, low, close, volume, turnover)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, records)
                        conn.commit()
                        total_records += len(records)
                        synced_tickers += 1
                        print(f"[{idx}/{len(CORE_TICKERS)}] {ticker}: Synced {len(records)} daily sessions.")
                    else:
                        print(f"[{idx}/{len(CORE_TICKERS)}] {ticker}: No valid OHLC bars.")
                else:
                    print(f"[{idx}/{len(CORE_TICKERS)}] {ticker}: Empty series.")
            else:
                print(f"[{idx}/{len(CORE_TICKERS)}] {ticker}: HTTP {r.status_code}")
        except Exception as e:
            print(f"[{idx}/{len(CORE_TICKERS)}] {ticker}: Error -> {e}")

        time.sleep(0.25)

    conn.close()
    print(f"\n[COMPLETE] Ingested {total_records} historical daily bars across {synced_tickers} tickers into '{DB_PATH}'.")

if __name__ == "__main__":
    fetch_history_yahoo()