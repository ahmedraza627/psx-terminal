import os
import re
import sqlite3
import requests
import urllib3
from datetime import datetime

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

DB_PATH = os.path.join("backend", "psx_history.db")

NCCPL_FIPI_URL = "https://www.nccpl.com.pk/en/market-information/fipi-lipi/fipi-normal-daily"
NCCPL_LIPI_URL = "https://www.nccpl.com.pk/en/market-information/fipi-lipi/lipi-normal-daily"

def parse_number(val_str):
    cleaned = re.sub(r"[^\d.\-]", "", val_str.replace(",", ""))
    try:
        return float(cleaned)
    except ValueError:
        return 0.0

def extract_table_rows(html):
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.DOTALL | re.IGNORECASE)
    parsed = []
    for r in rows:
        cols = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, re.DOTALL | re.IGNORECASE)
        clean_cols = [re.sub(r"<[^>]+>", "", c).strip() for c in cols]
        if clean_cols:
            parsed.append(clean_cols)
    return parsed

def fetch_live_nccpl():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    }
    fipi_resp = requests.get(NCCPL_FIPI_URL, headers=headers, timeout=20, verify=False)
    lipi_resp = requests.get(NCCPL_LIPI_URL, headers=headers, timeout=20, verify=False)

    if fipi_resp.status_code != 200 or lipi_resp.status_code != 200:
        raise RuntimeError(f"NCCPL HTTP status: FIPI={fipi_resp.status_code}, LIPI={lipi_resp.status_code}")

    fipi_rows = extract_table_rows(fipi_resp.text)
    lipi_rows = extract_table_rows(lipi_resp.text)

    foreign_net_usd = 0.0
    for row in fipi_rows:
        row_text = " ".join(row).upper()
        if "TOTAL" in row_text or "FOREIGN CORPORATES" in row_text:
            nums = [parse_number(c) for c in row if re.search(r"\d", c)]
            if nums:
                foreign_net_usd = nums[-1]
                if "TOTAL" in row_text:
                    break

    mutual_funds_pkr = 0.0
    banks_dfi_pkr = 0.0
    companies_pkr = 0.0
    individuals_pkr = 0.0

    for row in lipi_rows:
        if len(row) < 2:
            continue
        label = row[0].upper()
        nums = [parse_number(c) for c in row[1:] if re.search(r"\d", c)]
        if not nums:
            continue
        net_val = nums[-1]

        # NCCPL LIPI values are typically in USD or PKR millions; normalize if < 10000
        if abs(net_val) < 50000:
            net_val_pkr = net_val * 278500.0
        else:
            net_val_pkr = net_val

        if "MUTUAL FUND" in label:
            mutual_funds_pkr = net_val_pkr
        elif "BANK" in label or "DFI" in label:
            banks_dfi_pkr = net_val_pkr
        elif "COMPAN" in label:
            companies_pkr = net_val_pkr
        elif "INDIVIDUAL" in label:
            individuals_pkr = net_val_pkr

    if mutual_funds_pkr == 0.0 and individuals_pkr == 0.0 and foreign_net_usd == 0.0:
        raise ValueError("NCCPL HTML structure returned zero parsed figures (market holiday or pending upload).")

    return {
        "foreign_net_usd": round(foreign_net_usd, 1),
        "mutual_funds_pkr": round(mutual_funds_pkr, 1),
        "banks_dfi_pkr": round(banks_dfi_pkr, 1),
        "companies_pkr": round(companies_pkr, 1),
        "individuals_pkr": round(individuals_pkr, 1),
        "source": "LIVE_NCCPL_PORTAL"
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

    try:
        live = fetch_live_nccpl()
        for_usd = live["foreign_net_usd"]
        mf_pkr = live["mutual_funds_pkr"]
        banks_pkr = live["banks_dfi_pkr"]
        comp_pkr = live["companies_pkr"]
        indiv_pkr = live["individuals_pkr"]

        smart_net = round(mf_pkr + banks_pkr + comp_pkr + (for_usd * 278.5), 1)
        if smart_net > 50000000 and indiv_pkr < 0:
            sentiment = "STRONG INSTITUTIONAL ABSORPTION (FUNDS BUYING RETAIL PANIC)"
        elif smart_net > 0:
            sentiment = "NET INSTITUTIONAL ACCUMULATION (LIVE NCCPL)"
        else:
            sentiment = "BROAD INSTITUTIONAL DISTRIBUTION (RISK-OFF)"

        cur.execute("""
            INSERT OR REPLACE INTO institutional_flow
            (date, foreign_net_usd, mutual_funds_pkr, banks_dfi_pkr, companies_pkr, individuals_pkr, smart_money_net_pkr, market_sentiment)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (db_date, for_usd, mf_pkr, banks_pkr, comp_pkr, indiv_pkr, smart_net, sentiment))
        conn.commit()
        print(f"\n[NCCPL LIVE SCRAPER] Synchronized for {db_date} from NCCPL Portal:")
        print(f"  Sentiment: {sentiment}")
        print(f"  Mutual Funds: {mf_pkr/1e6:+.1f}M PKR | Foreign: ${for_usd/1e3:+.1f}K | Retail: {indiv_pkr/1e6:+.1f}M PKR")
    except Exception as e:
        print(f"\n[NCCPL SCRAPER NOTE] Live portal unavailable ({e}). Tape engine will use breadth-calibrated flow.")
    finally:
        conn.close()

if __name__ == "__main__":
    sync_nccpl()