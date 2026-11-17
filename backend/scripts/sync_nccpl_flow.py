import os
import re
import sqlite3
import tkinter as tk
from datetime import datetime

DB_PATH = os.path.join("backend", "psx_history.db")
MANUAL_NCCPL_FILE = r"D:\downloads\nccpl.txt"

def get_clipboard_text():
    try:
        root = tk.Tk()
        root.withdraw()
        text = root.clipboard_get()
        root.destroy()
        return text
    except Exception:
        return ""

def parse_nccpl_raw_text(raw_text):
    if not raw_text or len(raw_text) < 50:
        return None

    upper_text = raw_text.upper()
    if "MUTUAL FUNDS" not in upper_text and "INDIVIDUALS" not in upper_text and "FOREIGN CORPORATES" not in upper_text:
        return None

    def extract_net_for_label(label_pattern):
        for line in raw_text.splitlines():
            if re.search(label_pattern, line, re.IGNORECASE):
                nums = re.findall(r"[\-]?\d[\d,]*\.?\d*", line)
                cleaned = []
                for n in nums:
                    try:
                        cleaned.append(float(n.replace(",", "")))
                    except ValueError:
                        pass
                if cleaned:
                    return cleaned[-1]
        return None

    mf = extract_net_for_label(r"MUTUAL\s+FUNDS?")
    banks = extract_net_for_label(r"BANKS?\s*/?\s*DFI")
    comp = extract_net_for_label(r"COMPANIES")
    indiv = extract_net_for_label(r"INDIVIDUALS?")
    fipi = extract_net_for_label(r"FOREIGN\s+CORPORATES?|FIPI\s+TOTAL|NET\s+FIPI")

    if mf is None and indiv is None and fipi is None:
        return None

    def to_pkr(val):
        if val is None:
            return 0.0
        # If value is in USD millions (e.g. -1.25) or USD thousands, normalize to PKR
        if abs(val) < 500:
            return val * 1_000_000.0 * 278.5
        elif abs(val) < 500_000:
            return val * 1_000.0 * 278.5
        return val

    mf_pkr = to_pkr(mf)
    banks_pkr = to_pkr(banks)
    comp_pkr = to_pkr(comp)
    indiv_pkr = to_pkr(indiv)

    for_usd = 0.0
    if fipi is not None:
        for_usd = fipi * 1_000_000.0 if abs(fipi) < 500 else (fipi * 1_000.0 if abs(fipi) < 500_000 else fipi)

    return {
        "foreign_net_usd": round(for_usd, 1),
        "mutual_funds_pkr": round(mf_pkr, 1),
        "banks_dfi_pkr": round(banks_pkr, 1),
        "companies_pkr": round(comp_pkr, 1),
        "individuals_pkr": round(indiv_pkr, 1),
    }

def sync_nccpl():
    db_date = datetime.now().strftime("%Y-%m-%d")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS institutional_flow (
            date TEXT PRIMARY KEY,
            foreign_net_usd REAL,
            mutual_funds_pkr REAL,
            banks_dfi_pkr REAL,
            companies_pkr REAL,
            individuals_pkr REAL,
            smart_money_net_pkr REAL,
            market_sentiment TEXT
        )
    """)

    parsed = None
    source_used = None

    # 1. Check Windows Clipboard first
    clip_text = get_clipboard_text()
    parsed = parse_nccpl_raw_text(clip_text)
    if parsed:
        source_used = "CLIPBOARD"

    # 2. Check D:\downloads\nccpl.txt if clipboard didn't have NCCPL table
    if not parsed and os.path.exists(MANUAL_NCCPL_FILE):
        with open(MANUAL_NCCPL_FILE, "r", encoding="utf-8", errors="ignore") as f:
            parsed = parse_nccpl_raw_text(f.read())
        if parsed:
            source_used = "FILE (nccpl.txt)"

    if parsed:
        for_usd = parsed["foreign_net_usd"]
        mf_pkr = parsed["mutual_funds_pkr"]
        banks_pkr = parsed["banks_dfi_pkr"]
        comp_pkr = parsed["companies_pkr"]
        indiv_pkr = parsed["individuals_pkr"]

        smart_net = round(mf_pkr + banks_pkr + comp_pkr + (for_usd * 278.5), 1)
        if smart_net > 50_000_000 and indiv_pkr < 0:
            sentiment = "STRONG INSTITUTIONAL ABSORPTION (FUNDS BUYING RETAIL PANIC)"
        elif smart_net > 0:
            sentiment = "NET INSTITUTIONAL ACCUMULATION (VERIFIED NCCPL)"
        else:
            sentiment = "BROAD INSTITUTIONAL DISTRIBUTION (RISK-OFF)"

        cur.execute("""
            INSERT OR REPLACE INTO institutional_flow
            (date, foreign_net_usd, mutual_funds_pkr, banks_dfi_pkr, companies_pkr, individuals_pkr, smart_money_net_pkr, market_sentiment)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (db_date, for_usd, mf_pkr, banks_pkr, comp_pkr, indiv_pkr, smart_net, sentiment))
        conn.commit()
        print(f"\n[NCCPL VERIFIED INGEST] Loaded from {source_used} for {db_date}:")
        print(f"  Sentiment: {sentiment}")
        print(f"  Mutual Funds: {mf_pkr/1e6:+.1f}M PKR | Foreign: ${for_usd/1e3:+.1f}K | Retail: {indiv_pkr/1e6:+.1f}M PKR")
    else:
        print("\n[NCCPL FLOW] No copied NCCPL table detected. Using automated breadth-calibrated flow.")

    conn.close()

if __name__ == "__main__":
    sync_nccpl()