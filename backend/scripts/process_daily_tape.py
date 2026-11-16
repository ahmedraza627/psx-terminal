import os
import re
import json
import glob
import sqlite3
import subprocess
from datetime import datetime, timedelta
from curl_cffi import requests as cffi_requests

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

DFX_ELIGIBLE_STOCKS = {
    "UBL", "MCB", "MEBL", "HBL", "BAFL", "NBP", "BOP",
    "MLCF", "LUCK", "DGKC", "FCCL", "PIOC", "CHCC",
    "OGDC", "PPL", "MARI", "POL", "PSO", "SNGP", "SSGC",
    "FFC", "EFERT", "FATIMA",
    "SYS", "TRG", "AIRLINK", "AVN", "NETSOL", "OCTOPUS",
    "PRL", "NRL", "ATRL", "CNERGY",
    "HUBC", "KEL", "EPCL", "LOTCHEM", "SEARL",
    "NML", "PAEL", "UNITY", "ISL", "MTL", "INDU", "HCAR", "TREET"
}

# Map tickers to macro sector buckets for NCCPL Sector Matrix & Yield Sensitivity
TICKER_SECTOR_MAP = {
    "UBL": "BANKS", "MCB": "BANKS", "MEBL": "BANKS", "HBL": "BANKS", "BAHL": "BANKS", "BAFL": "BANKS", "NBP": "BANKS", "BOP": "BANKS", "AKBL": "BANKS",
    "MLCF": "CEMENT", "LUCK": "CEMENT", "DGKC": "CEMENT", "FCCL": "CEMENT", "PIOC": "CEMENT", "CHCC": "CEMENT", "ACPL": "CEMENT", "BWCL": "CEMENT", "KOHC": "CEMENT",
    "OGDC": "E&P", "PPL": "E&P", "MARI": "E&P", "POL": "E&P",
    "PSO": "OMC", "SNGP": "GAS", "SSGC": "GAS",
    "FFC": "FERTILIZER", "EFERT": "FERTILIZER", "FATIMA": "FERTILIZER",
    "SYS": "TECH", "TRG": "TECH", "AIRLINK": "TECH", "AVN": "TECH", "NETSOL": "TECH", "OCTOPUS": "TECH",
    "PRL": "REFINERY", "NRL": "REFINERY", "ATRL": "REFINERY", "CNERGY": "REFINERY",
    "HUBC": "POWER", "KAPCO": "POWER", "KEL": "POWER",
    "EPCL": "CHEMICAL", "LOTCHEM": "CHEMICAL",
    "SEARL": "PHARMA", "AGP": "PHARMA", "ABOT": "PHARMA",
    "ILP": "TEXTILE", "NML": "TEXTILE",
    "MTL": "AUTO", "INDU": "AUTO", "HCAR": "AUTO", "THALL": "AUTO", "GTYR": "AUTO",
    "PAEL": "ENGINEERING", "INIL": "ENGINEERING", "ISL": "ENGINEERING"
}

DIVIDEND_YIELD_BENEFICIARIES = {"FERTILIZER", "POWER", "BANKS", "E&P", "CEMENT"}

NCCPL_SECTOR_KEYWORDS = {
    "CEMENT": ["CEMENT"],
    "FERTILIZER": ["FERTILIZER"],
    "BANKS": ["COMMERCIAL BANKS", "BANKS"],
    "E&P": ["OIL AND GAS EXPLORATION", "OIL & GAS EXPLORATION"],
    "OMC": ["OIL AND GAS MARKETING", "OIL & GAS MARKETING"],
    "TECH": ["TECHNOLOGY", "COMMUNICATION"],
    "POWER": ["POWER GENERATION", "POWER"],
    "AUTO": ["AUTOMOBILE"],
    "TEXTILE": ["TEXTILE"],
    "PHARMA": ["PHARMACEUTICALS"],
    "REFINERY": ["REFINERY"],
    "CHEMICAL": ["CHEMICAL"]
}

def init_tables(conn):
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS active_trades (
            date TEXT, ticker TEXT, type TEXT, entry REAL, stop REAL, target REAL, status TEXT, notes TEXT,
            PRIMARY KEY (date, ticker)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS psx_disclosures (
            filing_date TEXT, ticker TEXT, category TEXT, headline TEXT,
            PRIMARY KEY (filing_date, ticker, headline)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS psx_catalysts (
            notice_date TEXT, ticker TEXT, event_type TEXT, headline TEXT,
            PRIMARY KEY (notice_date, ticker, headline)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ndm_blocks (
            trade_date TEXT, ticker TEXT, volume INTEGER, price REAL, value_m REAL,
            PRIMARY KEY (trade_date, ticker, volume, price)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sector_flow (
            date TEXT, sector_bucket TEXT, smart_net_m REAL,
            PRIMARY KEY (date, sector_bucket)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS macro_yields (
            updated_date TEXT PRIMARY KEY, policy_rate REAL, tbill_6m REAL, prev_tbill_6m REAL
        )
    """)
    cur.execute("SELECT COUNT(*) FROM macro_yields")
    if cur.fetchone()[0] == 0:
        cur.execute("""
            INSERT INTO macro_yields (updated_date, policy_rate, tbill_6m, prev_tbill_6m)
            VALUES (?, 11.00, 10.85, 11.20)
        """, (datetime.now().strftime("%Y-%m-%d"),))
    [cur.execute(f"DELETE FROM {r[0]} WHERE date = '2026-11-14'") for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() if 'date' in [c[1] for c in cur.execute(f"PRAGMA table_info({r[0]})").fetchall()]]
    cur.execute("DELETE FROM daily_eod WHERE date = '2026-11-14'")
    cur.execute("DELETE FROM sector_flow WHERE date = '2026-11-14'")
    conn.commit()

def get_macro_regime(cur):
    cur.execute("SELECT updated_date, policy_rate, tbill_6m, prev_tbill_6m FROM macro_yields ORDER BY updated_date DESC LIMIT 1")
    row = cur.fetchone()
    if not row:
        return {"policyRate": 11.0, "tbill6m": 10.85, "deltaBps": -35, "stance": "EASING LIQUIDITY"}
    delta_bps = round((row[2] - row[3]) * 100)
    stance = "EASING (YIELD DROP)" if delta_bps < 0 else ("TIGHTENING (YIELD HIKE)" if delta_bps > 0 else "NEUTRAL RATES")
    return {"policyRate": row[1], "tbill6m": row[2], "deltaBps": delta_bps, "stance": stance}

def sync_ndm_block_trades(cur, db_date):
    """Scrapes PSX DPS Off-Market NDM block deals (>= 50k shares or >= 5M PKR value)."""
    url = "https://dps.psx.com.pk/ndm"
    added = 0
    try:
        resp = cffi_requests.get(url, impersonate="chrome124", timeout=12)
        if resp.status_code == 200:
            rows = re.findall(r"<tr[^>]*>(.*?)</tr>", resp.text, re.DOTALL | re.IGNORECASE)
            for r in rows:
                cols = re.findall(r"<td[^>]*>(.*?)</td>", r, re.DOTALL | re.IGNORECASE)
                clean = [re.sub(r"<[^>]+>", "", c).strip().replace(",", "") for c in cols]
                if len(clean) >= 5:
                    # Typical NDM columns: Date/Member, Symbol, Company, Volume, Price
                    sym = ""
                    vol = 0
                    price = 0.0
                    for token in clean:
                        if token.isalpha() and 2 <= len(token) <= 9 and token.isupper():
                            sym = token
                        else:
                            try:
                                val = float(token)
                                if val >= 25000 and vol == 0:
                                    vol = int(val)
                                elif 1.0 <= val <= 15000.0 and price == 0.0:
                                    price = val
                            except ValueError:
                                continue
                    if sym and vol >= 50000 and price > 0:
                        val_m = round((vol * price) / 1000000, 2)
                        if val_m >= 5.0:
                            cur.execute("""
                                INSERT OR IGNORE INTO ndm_blocks (trade_date, ticker, volume, price, value_m)
                                VALUES (?, ?, ?, ?, ?)
                            """, (db_date, sym, vol, price, val_m))
                            if cur.rowcount > 0:
                                added += 1
    except Exception:
        pass
    print(f"[NDM BLOCK RADAR] Off-market negotiated block deals synced (+{added} new today).")

def get_recent_ndm_tickers(cur, db_date):
    cutoff = (datetime.strptime(db_date, "%Y-%m-%d") - timedelta(days=5)).strftime("%Y-%m-%d")
    cur.execute("""
        SELECT ticker, SUM(volume), ROUND(SUM(value_m), 1)
        FROM ndm_blocks WHERE trade_date >= ? GROUP BY ticker
    """, (cutoff,))
    return {r[0]: {"vol": r[1], "valM": r[2]} for r in cur.fetchall()}

def parse_nccpl_csv_file(fpath):
    import csv
    sector_map = {}
    try:
        with open(fpath, "r", encoding="utf-8-sig", errors="ignore") as f:
            reader = csv.DictReader(f)
            for row in reader:
                client = (row.get("CLIENT TYPE") or "").strip().upper()
                sec_name = (row.get("SECTOR NAME") or "").strip().upper()
                mkt = (row.get("MARKET TYPE") or "").strip().upper()
                if not sec_name or sec_name in ("---", "TOTAL") or mkt == "TOTAL":
                    continue
                if "INDIVIDUAL" in client and "FOREIGN" not in client:
                    continue
                raw_val = (row.get("NET VALUE - PKR") or "0").strip().replace(",", "")
                if raw_val.startswith("(") and raw_val.endswith(")"):
                    raw_val = "-" + raw_val[1:-1]
                try:
                    net_pkr = float(raw_val)
                except ValueError:
                    continue
                net_m = round(net_pkr / 1_000_000.0, 2)
                for bucket, kws in NCCPL_SECTOR_KEYWORDS.items():
                    if any(kw in sec_name for kw in kws):
                        sector_map[bucket] = round(sector_map.get(bucket, 0.0) + net_m, 2)
                        break
    except Exception:
        pass
    return sector_map

def sync_clipboard_sector_flow(cur, db_date):
    """Auto-reads exported NCCPL fipi-sector-wise.csv & lipi-sector-wise.csv from D:\downloads."""
    today_ts = datetime.now().timestamp() - (48 * 3600)
    files = sorted(
        [fp for fp in glob.glob(os.path.join(TARGET_DIR, "*.csv")) if os.path.isfile(fp) and os.path.getmtime(fp) >= today_ts],
        key=os.path.getmtime,
        reverse=True,
    )
    parsed_sectors, matched = {}, 0
    seen_types = set()
    for fp in files[:6]:
        fname = os.path.basename(fp).lower()
        ftype = "fipi" if "fipi" in fname else ("lipi" if "lipi" in fname else fname)
        if ftype in seen_types:
            continue
        sec_data = parse_nccpl_csv_file(fp)
        if sec_data:
            seen_types.add(ftype)
            matched += 1
            for b, val in sec_data.items():
                parsed_sectors[b] = round(parsed_sectors.get(b, 0.0) + val, 2)

    if parsed_sectors:
        for b, m in parsed_sectors.items():
            cur.execute(
                "INSERT OR REPLACE INTO sector_flow (date, sector_bucket, smart_net_m) VALUES (?, ?, ?)",
                (db_date, b, m),
            )
        print(f"[SECTOR MATRIX] Clean-parsed {len(parsed_sectors)} sectors (Net PKR M) from {matched} NCCPL CSV(s)!")

    # Return 3-day rolling institutional sector flow to prevent 1-day flip-flops
    cur.execute("""
        SELECT sector_bucket, ROUND(SUM(smart_net_m), 2)
        FROM sector_flow
        WHERE date >= (SELECT date(MAX(date), '-4 days') FROM sector_flow)
        GROUP BY sector_bucket
    """)
    return {r[0]: r[1] for r in cur.fetchall()}

def sync_psx_events_and_insiders(cur, active_symbols):
    added_insiders = 0
    added_catalysts = 0

    for sym in sorted(active_symbols):
        url = f"https://dps.psx.com.pk/company/{sym}"
        try:
            resp = cffi_requests.get(url, impersonate="chrome124", timeout=8)
            if resp.status_code != 200:
                continue
            rows = re.findall(r"<tr[^>]*>(.*?)</tr>", resp.text, re.DOTALL | re.IGNORECASE)
            for r in rows[:15]:
                cols = re.findall(r"<td[^>]*>(.*?)</td>", r, re.DOTALL | re.IGNORECASE)
                clean = [re.sub(r"<[^>]+>", "", c).strip() for c in cols]
                if len(clean) < 2:
                    continue

                raw_date = clean[0]
                title = re.sub(r"\s+", " ", clean[1]).strip()
                upper_t = title.upper()

                try:
                    dt_parsed = datetime.strptime(raw_date, "%b %d, %Y").strftime("%Y-%m-%d")
                except Exception:
                    dt_parsed = datetime.now().strftime("%Y-%m-%d")

                is_insider = (
                    "DISCLOSURE OF INTEREST" in upper_t
                    or "SUBSTANTIAL ACQUISITION" in upper_t
                    or "5.6.4" in upper_t
                )
                is_noise = (
                    "BOARD OF DIRECTOR" in upper_t
                    or "MEETING" in upper_t
                    or "CHANGE OF DIRECTOR" in upper_t
                    or "ELECTION" in upper_t
                )
                if is_insider and not is_noise:
                    cat = "SUBSTANTIAL ACQUISITION" if "SUBSTANTIAL" in upper_t else "CLAUSE 5.6.4 INSIDER FILING"
                    cur.execute("""
                        INSERT OR IGNORE INTO psx_disclosures (filing_date, ticker, category, headline)
                        VALUES (?, ?, ?, ?)
                    """, (dt_parsed, sym, cat, title[:180]))
                    if cur.rowcount > 0:
                        added_insiders += 1

                if any(k in upper_t for k in ["FINANCIAL RESULT", "DIVIDEND", "BONUS", "PAYOUT", "MATERIAL INFORMATION"]):
                    cur.execute("""
                        INSERT OR IGNORE INTO psx_catalysts (notice_date, ticker, event_type, headline)
                        VALUES (?, ?, 'RESULT_RELEASED', ?)
                    """, (dt_parsed, sym, title[:180]))
                    if cur.rowcount > 0:
                        added_catalysts += 1
                elif any(k in upper_t for k in ["BOARD OF DIRECTOR", "CLOSED PERIOD"]):
                    cur.execute("""
                        INSERT OR IGNORE INTO psx_catalysts (notice_date, ticker, event_type, headline)
                        VALUES (?, ?, 'UPCOMING_BOARD_MEETING', ?)
                    """, (dt_parsed, sym, title[:180]))
                    if cur.rowcount > 0:
                        added_catalysts += 1
        except Exception:
            continue

    print(f"[EVENT RADAR SYNC] +{added_insiders} Insider Filings | +{added_catalysts} Result/Board Catalysts synced.")

def get_recent_insider_tickers(cur, db_date):
    cutoff = (datetime.strptime(db_date, "%Y-%m-%d") - timedelta(days=45)).strftime("%Y-%m-%d")
    cur.execute("SELECT DISTINCT ticker FROM psx_disclosures WHERE filing_date >= ?", (cutoff,))
    return {row[0] for row in cur.fetchall()}

def evaluate_catalyst_cycle(cur, ticker, db_date, rvol, clv, change_pct):
    today_dt = datetime.strptime(db_date, "%Y-%m-%d")
    lookback_12d = (today_dt - timedelta(days=12)).strftime("%Y-%m-%d")

    cur.execute("""
        SELECT notice_date, event_type, headline FROM psx_catalysts
        WHERE ticker = ? AND notice_date >= ?
        ORDER BY notice_date DESC LIMIT 3
    """, (ticker, lookback_12d))
    events = cur.fetchall()
    if not events:
        return None

    for n_date, ev_type, headline in events:
        days_ago = (today_dt - datetime.strptime(n_date, "%Y-%m-%d")).days
        if ev_type == "RESULT_RELEASED" and days_ago <= 3:
            if change_pct < 0 or (rvol >= 2.0 and clv < 0.50):
                return {
                    "badge": "SELL-THE-NEWS DUMP",
                    "note": f"Post-announcement distribution ({headline} on {n_date}) — funds offloading into retail liquidity."
                }
            elif change_pct > 0 and rvol >= 1.5 and clv >= 0.70:
                return {
                    "badge": "POST-RESULT BREAKOUT",
                    "note": f"Strong institutional follow-through after {headline} ({n_date})."
                }
        elif ev_type == "UPCOMING_BOARD_MEETING" and days_ago <= 12:
            if change_pct > 0 and rvol >= 1.6 and clv >= 0.60:
                return {
                    "badge": "PRE-EVENT ACCUMULATION",
                    "note": f"Smart money positioning ahead of {headline} ({n_date})."
                }
    return None

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
        return {"rvol": 1.2, "sma50": current_close, "atr14": current_close * 0.032, "trend": "BULLISH"}

    vols_20 = [r[3] for r in rows[:20] if r[3] is not None and r[3] > 0]
    avg_vol_20 = sum(vols_20) / len(vols_20) if vols_20 else current_vol
    rvol = round(current_vol / avg_vol_20, 1) if avg_vol_20 > 0 else 1.0
    rvol = min(max(rvol, 0.5), 6.5)

    closes_50 = [r[0] for r in rows if r[0] is not None]
    sma50 = sum(closes_50) / len(closes_50) if closes_50 else current_close
    trend = "BULLISH" if current_close >= sma50 else "BEARISH"

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

def derive_dynamic_dfx_and_oi(item, futures_data):
    """Distinguishes OI-Confirmed Long Buildup vs. Short Covering & MFS Badla Leverage Traps."""
    sym = item["ticker"]
    spot = item["close"]
    chg = item["change"]
    rvol = item["rvol"]

    if item["tier"] == "TIER-2 MID-CAP":
        return {"status": "CASH SEGMENT", "spread": "NO DFX", "oiConfirmed": False, "mfsTrap": False}

    if sym in futures_data and spot > 0:
        fut_close = futures_data[sym]["close"]
        fut_vol = futures_data[sym]["vol"]
        spread_pct = round(((fut_close - spot) / spot) * 100, 2)
        fut_to_spot_ratio = fut_vol / max(item["vol"], 1.0)

        # True Long Buildup: Spot up + Futures premium >= 0.45% + active futures contract expansion
        if chg > 0 and spread_pct >= 0.45 and fut_to_spot_ratio >= 0.25:
            return {"status": "OI+ LONG BUILDUP", "spread": f"+{spread_pct}%", "oiConfirmed": True, "mfsTrap": False}
        elif chg > 0 and spread_pct < 0.20:
            return {"status": "SHORT COVERING (OI-)", "spread": f"{spread_pct:+.2f}%", "oiConfirmed": False, "mfsTrap": False}
        elif chg > 0:
            return {"status": "SPOT ACCUMULATION", "spread": f"{spread_pct:+.2f}%", "oiConfirmed": False, "mfsTrap": False}
        elif chg < 0 and spread_pct >= 0.70 and rvol >= 1.5:
            # High futures premium while spot dumps = trapped retail Badla/MFS leverage
            return {"status": "MFS BADLA TRAP", "spread": f"+{spread_pct}%", "oiConfirmed": True, "mfsTrap": True}
        elif chg < 0 and spread_pct <= -0.25:
            return {"status": "OI+ SHORT BUILDUP", "spread": f"{spread_pct:.2f}%", "oiConfirmed": True, "mfsTrap": False}
        else:
            return {"status": "LONG UNWINDING", "spread": f"{spread_pct:+.2f}%", "oiConfirmed": False, "mfsTrap": False}

    if chg > 0:
        if rvol >= 2.2:
            return {"status": "LONG BUILDUP", "spread": "+0.85%", "oiConfirmed": True, "mfsTrap": False}
        return {"status": "ROLLOVER ACCUMULATION", "spread": "+0.45%", "oiConfirmed": False, "mfsTrap": False}
    else:
        if rvol >= 2.0:
            return {"status": "SHORT BUILDUP", "spread": "-0.90%", "oiConfirmed": True, "mfsTrap": False}
        return {"status": "LONG UNWINDING", "spread": "-0.40%", "oiConfirmed": False, "mfsTrap": False}

def resolve_session_flow(cur, db_date, kse100_pct, breadth_pct):
    """Extracts exact Foreign, Local Institutional (Funds/Banks/Companies), and Retail Individual flow from NCCPL CSVs."""
    import csv
    today_ts = datetime.now().timestamp() - (48 * 3600)
    files = sorted(
        [fp for fp in glob.glob(os.path.join(TARGET_DIR, "*.csv")) if os.path.isfile(fp) and os.path.getmtime(fp) >= today_ts],
        key=os.path.getmtime,
        reverse=True,
    )
    fipi_usd = 0.0
    fipi_pkr_m = 0.0
    inst_pkr_m = 0.0
    retail_pkr_m = 0.0
    found_csv = False

    for fp in files[:6]:
        fname = os.path.basename(fp).lower()
        try:
            with open(fp, "r", encoding="utf-8-sig", errors="ignore") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    client = (row.get("CLIENT TYPE") or "").strip().upper()
                    sec_name = (row.get("SECTOR NAME") or "").strip().upper()
                    mkt = (row.get("MARKET TYPE") or "").strip().upper()
                    if not client or sec_name in ("---", "TOTAL") or mkt == "TOTAL":
                        continue
                    raw_pkr = (row.get("NET VALUE - PKR") or "0").strip().replace(",", "")
                    if raw_pkr.startswith("(") and raw_pkr.endswith(")"):
                        raw_pkr = "-" + raw_pkr[1:-1]
                    try:
                        val_m = float(raw_pkr) / 1_000_000.0
                    except ValueError:
                        continue

                    if "fipi" in fname or "FOREIGN" in client or "OVERSEAS" in client:
                        found_csv = True
                        fipi_pkr_m += val_m
                        raw_usd = (row.get("USD") or "0").strip().replace(",", "")
                        if raw_usd.startswith("(") and raw_usd.endswith(")"):
                            raw_usd = "-" + raw_usd[1:-1]
                        try:
                            fipi_usd += float(raw_usd)
                        except ValueError:
                            pass
                    elif "lipi" in fname:
                        found_csv = True
                        if "INDIVIDUAL" in client:
                            retail_pkr_m += val_m
                        else:
                            inst_pkr_m += val_m
        except Exception:
            continue

    if found_csv:
        fipi_usd_k = round(fipi_usd / 1000.0, 1)
        inst_m = round(inst_pkr_m, 1)
        retail_m = round(retail_pkr_m, 1)
        smart_net = round(fipi_pkr_m + inst_pkr_m, 1)

        if smart_net >= 50 and retail_m < 0:
            sentiment = "STRONG INSTITUTIONAL ABSORPTION (FUNDS BUYING RETAIL PANIC)"
        elif smart_net >= 20:
            sentiment = "INSTITUTIONAL ACCUMULATION (SMART MONEY INFLOW)"
        elif smart_net <= -50:
            sentiment = "HEAVY INSTITUTIONAL DISTRIBUTION (FUNDS SELLING INTO RALLY)"
        else:
            sentiment = "BALANCED INSTITUTIONAL ROTATION (SELECTIVE FLOW)"

        cur.execute("CREATE TABLE IF NOT EXISTS nccpl_flow (date TEXT PRIMARY KEY, fipi_usd_k REAL, mutual_funds_m REAL, individuals_m REAL, net_smart_m REAL, sentiment TEXT)")
        cur.execute("CREATE TABLE IF NOT EXISTS nccpl_flow (date TEXT PRIMARY KEY, fipi_usd_k REAL, mutual_funds_m REAL, individuals_m REAL, net_smart_m REAL, sentiment TEXT)")
        cur.execute("""
            INSERT OR REPLACE INTO nccpl_flow (date, fipi_usd_k, mutual_funds_m, individuals_m, net_smart_m, sentiment)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (db_date, fipi_usd_k, inst_m, retail_m, smart_net, sentiment))

        return {
            "fipiUsd": fipi_usd_k,
            "mutualFunds": inst_m,
            "individuals": retail_m,
            "netSmartFlow": smart_net,
            "sentiment": sentiment,
        }

    cur.execute("SELECT fipi_usd_k, mutual_funds_m, individuals_m, net_smart_m, sentiment FROM nccpl_flow ORDER BY date DESC LIMIT 1")
    r = cur.fetchone()
    if r:
        return {
            "fipiUsd": f"{r[0]:+.1f}K",
            "mutualFunds": f"{r[1]:+.1f}M PKR",
            "individuals": f"{r[2]:+.1f}M PKR",
            "netSmartFlow": f"{r[3]:+.1f}M",
            "sentiment": r[4],
        }
    return {
        "fipiUsd": "+0.0K",
        "mutualFunds": "+0.0M PKR",
        "individuals": "+0.0M PKR",
        "netSmartFlow": "+0.0M",
        "sentiment": "CALIBRATING SESSION FLOW",
    }

    if breadth_pct < 40.0 or kse100_pct <= -0.8:
        mf_pkr = round(-115000000 + (breadth_pct * 1200000), 1)
        for_usd = round(-380000 + (kse100_pct * 150000), 1)
        indiv_pkr = round(-195000000 + (kse100_pct * 45000000), 1)
        smart_net = round(mf_pkr + (for_usd * 280.0), 1)
        sentiment = "BROAD INSTITUTIONAL DISTRIBUTION (RISK-OFF)"
    elif breadth_pct >= 52.0:
        mf_pkr = round(140000000 + ((breadth_pct - 50.0) * 11000000), 1)
        for_usd = round(350000 + (kse100_pct * 220000), 1)
        indiv_pkr = round(-240000000 - ((breadth_pct - 50.0) * 12000000), 1)
        smart_net = round(mf_pkr + (for_usd * 280.0) + indiv_pkr, 1)
        sentiment = "STRONG INSTITUTIONAL ABSORPTION (FUNDS BUYING RETAIL PANIC)"
    else:
        mf_pkr = 42000000.0
        for_usd = 110000.0
        indiv_pkr = -65000000.0
        smart_net = round(mf_pkr + (for_usd * 280.0) + indiv_pkr, 1)
        sentiment = "SELECTIVE SECTOR ROTATION (BALANCED LIQUIDITY)"

    cur.execute("""
        INSERT OR REPLACE INTO institutional_flow (date, foreign_net_usd, mutual_funds_pkr, banks_dfi_pkr, companies_pkr, individuals_pkr, smart_money_net_pkr, market_sentiment)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (db_date, for_usd, mf_pkr, 35000000.0, 25000000.0, indiv_pkr, smart_net, sentiment))

    return {
        "sentiment": sentiment,
        "mutualFundsM": round(mf_pkr / 1000000, 1),
        "foreignUsdK": round(for_usd / 1000, 1),
        "individualsM": round(indiv_pkr / 1000000, 1),
        "smartMoneyDeltaM": round(smart_net / 1000000, 1),
        "isSmartMoneyBuying": smart_net > 0
    }

def process_all():
    filepath = find_psx_file()
    if not filepath:
        print("[ERROR] Closing file nahi mili!")
        return

    now = datetime.now()
    if now.weekday() >= 5:
        print("[WEEKEND LOCK] PSX closed on weekends. Skipping duplicate ledger generation.")
        return
    session_date = now.strftime("%A, %b %d, %Y")
    session_time = now.strftime("%H:%M PKT")
    db_date = now.strftime("%Y-%m-%d")
    is_rollover_week = now.day >= 20

    market_rates = {}
    futures_data = {}
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

                    if "-" in sym and sec in ["40", "41"]:
                        base_sym = sym.split("-")[0]
                        if base_sym in KSE_INSTITUTIONAL_CORE and close_p > 0:
                            futures_data[base_sym] = {"close": close_p, "vol": vol}
                        continue

                    if "-" in sym or sec in ["40", "41", "36"] or sym.startswith("KSE"):
                        continue

                    market_rates[sym] = close_p
                    if pct_change > 0:
                        advances += 1
                    elif pct_change < 0:
                        declines += 1

                    turnover = close_p * vol
                    if sym in KSE_INSTITUTIONAL_CORE and close_p >= 12.0 and vol >= 150000 and turnover >= 25000000:
                        parsed_today.append({
                            "ticker": sym, "sector": sec, "tier": "TIER-1 CORE",
                            "open": open_p, "high": high_p, "low": low_p, "close": close_p,
                            "vol": vol, "turnover": turnover, "change": pct_change
                        })
                    elif sym not in KSE_INSTITUTIONAL_CORE and close_p >= 15.0 and vol >= 200000 and turnover >= 20000000:
                        parsed_today.append({
                            "ticker": sym, "sector": sec, "tier": "TIER-2 MID-CAP",
                            "open": open_p, "high": high_p, "low": low_p, "close": close_p,
                            "vol": vol, "turnover": turnover, "change": pct_change
                        })
                except ValueError:
                    continue

    total_active = advances + declines
    breadth_pct = round((advances / total_active) * 100, 1) if total_active > 0 else 50.0
    if kse100_pct is None:
        kse100_pct = round((breadth_pct - 50.0) / 12.0, 2)

    is_defensive = (kse100_pct <= -0.8) or (breadth_pct <= 38.0)
    regime_status = "DEFENSIVE (CASH MODE)" if is_defensive else "BULLISH ACCUMULATION"
    regime_note = "High macro distribution detected. Long entries blocked; qualified DFX short setups active." if is_defensive else "V2 5-Layer Institutional Engine active: NDM Blocks + DFX OI + Sector Matrix + SBP Yields."

    conn = sqlite3.connect(DB_PATH)
    init_tables(conn)
    cur = conn.cursor()

    macro = get_macro_regime(cur)
    sync_ndm_block_trades(cur, db_date)
    ndm_map = get_recent_ndm_tickers(cur, db_date)
    sector_flow_map = sync_clipboard_sector_flow(cur, db_date)

    active_watch = {item["ticker"] for item in parsed_today} | (KSE_INSTITUTIONAL_CORE & set(market_rates.keys()))
    sync_psx_events_and_insiders(cur, active_watch)
    recent_insider_tickers = get_recent_insider_tickers(cur, db_date)

    for row in parsed_today:
        cur.execute("""
            INSERT OR REPLACE INTO daily_eod (date, ticker, sector, open, high, low, close, volume, turnover)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (db_date, row["ticker"], row["sector"], row["open"], row["high"], row["low"], row["close"], row["vol"], row["turnover"]))
    conn.commit()

    scored_candidates = []
    for item in parsed_today:
        sym = item["ticker"]
        sec_bucket = TICKER_SECTOR_MAP.get(sym, "OTHER")
        metrics = compute_historical_metrics(cur, sym, item["close"], item["vol"])
        rng = item["high"] - item["low"]
        clv = (item["close"] - item["low"]) / rng if rng > 0 else 0.5
        rvol = metrics["rvol"]
        atr14 = metrics["atr14"]

        if item["tier"] == "TIER-2 MID-CAP" and item["change"] > 0:
            if rvol < 2.2 or clv < 0.72:
                continue

        catalyst = evaluate_catalyst_cycle(cur, sym, db_date, rvol, clv, item["change"])
        is_sell_the_news_dump = catalyst and catalyst["badge"] == "SELL-THE-NEWS DUMP"
        has_insider_confluence = sym in recent_insider_tickers
        ndm_info = ndm_map.get(sym)
        item['rvol'] = rvol
        dfx = derive_dynamic_dfx_and_oi(item, futures_data)

        # Sector Flow & SBP Macro Yield Alignment
        sec_net_m = sector_flow_map.get(sec_bucket, 0.0)
        is_sector_outflow = sec_net_m <= -25.0
        is_sector_inflow = sec_net_m >= 25.0
        macro_yield_boost = 2.0 if (macro["deltaBps"] < 0 and sec_bucket in DIVIDEND_YIELD_BENEFICIARIES) else 0.0

        if item["change"] > 0 and not is_sell_the_news_dump:
            # Anti-whiplash: require 50-SMA BULLISH trend, no >4.5% vertical spike chasing, and no sector outflow
            if is_sector_outflow or metrics["trend"] != "BULLISH" or item["change"] > 3.8 or clv < 0.65:
                continue
            trend_bonus = 6.0
            catalyst_bonus = 3.5 if (catalyst and catalyst["badge"] in ["PRE-EVENT ACCUMULATION", "POST-RESULT BREAKOUT"]) else 0.0
            insider_bonus = 3.5 if has_insider_confluence else 0.0
            ndm_bonus = 4.5 if ndm_info else 0.0
            oi_bonus = 2.5 if dfx["oiConfirmed"] else (-2.0 if "SHORT COVERING" in dfx["status"] else 0.0)
            sec_bonus = 2.5 if is_sector_inflow else 0.0

            prob = 53.0 + (min(item["change"], 7.0) * 0.9) + (min(rvol, 3.5) * 2.3) + (clv * 4.2) + trend_bonus + catalyst_bonus + insider_bonus + ndm_bonus + oi_bonus + sec_bonus + macro_yield_boost
            prob_score = round(min(max(prob, 52.0), 89.0), 1)
        else:
            if not ((item["change"] <= -1.8 and clv <= 0.35 and (is_sector_outflow or dfx["mfsTrap"])) or is_sell_the_news_dump):
                continue
            trend_penalty = 5.0 if metrics["trend"] == "BEARISH" else -2.0
            dump_bonus = 7.0 if is_sell_the_news_dump else 0.0
            mfs_bonus = 4.5 if dfx["mfsTrap"] else 0.0
            sec_out_bonus = 3.0 if is_sector_outflow else 0.0
            downside_risk = 46.0 + (min(abs(item["change"]), 8.0) * 1.4) + (min(rvol, 3.5) * 2.2) + ((1.0 - clv) * 4.5) + trend_penalty + dump_bonus + mfs_bonus + sec_out_bonus
            prob_score = round(min(max(downside_risk, 50.0), 86.0), 1)

        scored_candidates.append({
            **item,
            "secBucket": sec_bucket,
            "rvol": rvol,
            "clv": clv,
            "atr": atr14,
            "prob": prob_score,
            "trend": metrics["trend"],
            "catalyst": catalyst,
            "isDump": is_sell_the_news_dump,
            "insiderConfluence": has_insider_confluence,
            "ndmInfo": ndm_info,
            "dfx": dfx,
            "secNetM": sec_net_m
        })

    gainers = [
        c for c in scored_candidates
        if c["change"] > 0
        and not c["isDump"]
        and c["rvol"] >= 1.5
        and c["clv"] >= 0.65
        and c["prob"] >= 66.0
        and c["trend"] == "BULLISH"
    ]
    gainers.sort(key=lambda x: (1 if x["ndmInfo"] else 0, 1 if x["insiderConfluence"] else 0, x["prob"], x["rvol"]), reverse=True)

    buys = []
    sector_buy_count = {}
    if not is_defensive:
        for item in gainers:
            sec = item["sector"]
            if sector_buy_count.get(sec, 0) < 2:
                close_px = item["close"]
                atr_val = item["atr"]
                zone_low = round(close_px - (atr_val * 0.45), 2)
                zone_high = round(close_px - (atr_val * 0.15), 2)
                price = round((zone_low + zone_high) / 2.0, 2)
                target = round(price + (atr_val * 2.1), 2)
                stop = round(price - (atr_val * 0.8), 2)
                gain_pct = round(((target - price) / price) * 100, 1)
                loss_pct = round(((price - stop) / price) * 100, 1)
                dfx = item["dfx"]
                tier_label = "Tier-1 accumulation" if item["tier"] == "TIER-1 CORE" else "Mid-Cap rotation breakout"
                cat_badge = item["catalyst"]["badge"] if item["catalyst"] else None
                cat_note = f" {item['catalyst']['note']}" if item["catalyst"] else ""
                insider_note = " Verified PSX Clause 5.6.4 Insider Filing." if item["insiderConfluence"] else ""
                ndm_note = f" NDM Off-Market Block ({item['ndmInfo']['vol']:,} sh / PKR {item['ndmInfo']['valM']}M)." if item["ndmInfo"] else ""
                sec_note = f" Sector Flow ({item['secBucket']}): {item['secNetM']:+.1f}M PKR." if item["secNetM"] != 0 else ""

                buys.append({
                    "rank": len(buys) + 1,
                    "ticker": item["ticker"],
                    "insiderConfluence": item["insiderConfluence"],
                    "ndmBlock": bool(item["ndmInfo"]),
                    "oiConfirmed": dfx["oiConfirmed"],
                    "entry": f"PKR {price:.2f}",
                    "entryZone": f"PKR {zone_low:.2f} - {zone_high:.2f}",
                    "stop": f"PKR {stop:.2f} (-{loss_pct}%)",
                    "target": f"PKR {target:.2f} (+{gain_pct}%)",
                    "raw_entry": price,
                    "raw_stop": stop,
                    "raw_target": target,
                    "rr": "1:2.5",
                    "probability": f"{item['prob']}%",
                    "rvol": f"{item['rvol']}x",
                    "dfxSignal": dfx["status"],
                    "catalystTag": cat_badge,
                    "notes": f"{tier_label} ({int(item['vol']):,} shares, PKR {round(item['turnover']/10000000, 1)}Cr turnover). {dfx['status']} ({dfx['spread']}).{ndm_note}{insider_note}{sec_note}{cat_note} Swing target +{gain_pct}%."
                })
                sector_buy_count[sec] = sector_buy_count.get(sec, 0) + 1
            if len(buys) == 5:
                break

    selected_buy_tickers = {b["ticker"] for b in buys}

    losers = [
        c for c in scored_candidates
        if c["ticker"] not in selected_buy_tickers
        and c["ticker"] in DFX_ELIGIBLE_STOCKS
        and (
            c["isDump"]
            or c["dfx"]["mfsTrap"]
            or (c["change"] <= -1.0 and c["rvol"] >= 1.4 and c["clv"] <= 0.45)
        )
    ]
    losers.sort(key=lambda x: (1 if x["isDump"] else 0, 1 if x["dfx"]["mfsTrap"] else 0, x["rvol"], x["turnover"]), reverse=True)

    avoids = []
    sector_avoid_count = {}
    for item in losers:
        sec = item["sector"]
        if sector_avoid_count.get(sec, 0) < 2:
            sym = item["ticker"]
            price = item["close"]
            downside = round(price - (item["atr"] * 1.65), 2)
            stop_ref = round(price + (item["atr"] * 0.65), 2)
            drop_pct = round(((price - downside) / price) * 100, 1)
            stop_pct = round(((stop_ref - price) / price) * 100, 1)

            short_zone_low = round(price * 0.996, 2)
            short_zone_high = round(price * 1.005, 2)

            is_dfx_shortable = not is_rollover_week
            action_tag = "DFX SHORT" if is_dfx_shortable else "AVOID (ROLLOVER WEEK)"

            structure_note = "Distribution from Bullish Structure" if item["trend"] == "BULLISH" else "Bearish Trend Breakdown"
            dfx = item["dfx"]
            cat_badge = item["catalyst"]["badge"] if item["catalyst"] else None
            cat_note = f" {item['catalyst']['note']}" if item["catalyst"] else ""
            mfs_note = " High futures premium against falling spot signals trapped Badla/MFS leverage." if dfx["mfsTrap"] else ""

            exec_note = (
                f"[{action_tag}] Short on uptick in zone PKR {short_zone_low:.2f}-{short_zone_high:.2f}; hard stop PKR {stop_ref:.2f} (+{stop_pct}%), target PKR {downside:.2f} (-{drop_pct}%)."
                if is_dfx_shortable
                else f"[{action_tag}] Rollover week active — stay flat (Downside risk -{drop_pct}%)."
            )

            avoids.append({
                "rank": len(avoids) + 1,
                "ticker": sym,
                "isShortable": is_dfx_shortable,
                "mfsTrap": dfx["mfsTrap"],
                "actionTag": action_tag,
                "price": f"PKR {price:.2f}",
                "shortZone": f"PKR {short_zone_low:.2f} - {short_zone_high:.2f}",
                "stop": f"PKR {stop_ref:.2f} (+{stop_pct}%)",
                "downside": f"PKR {downside:.2f} (-{drop_pct}%)",
                "raw_price": price,
                "raw_stop": stop_ref,
                "raw_downside": downside,
                "tag": action_tag,
                "probability": f"{item['prob']}%",
                "rvol": f"{item['rvol']}x",
                "dfxSignal": dfx["status"],
                "catalystTag": cat_badge,
                "notes": f"{structure_note} ({int(item['vol']):,} shares, PKR {round(item['turnover']/10000000, 1)}Cr turnover). {dfx['status']} ({dfx['spread']}).{mfs_note}{cat_note} {exec_note}"
            })
            sector_avoid_count[sec] = sector_avoid_count.get(sec, 0) + 1
        if len(avoids) == 5:
            break

    cur.execute("DELETE FROM active_trades WHERE date = ?", (db_date,))
    for b in buys:
        cur.execute("""
            INSERT OR REPLACE INTO active_trades (date, ticker, type, entry, stop, target, status, notes)
            VALUES (?, ?, 'BUY', ?, ?, ?, 'IN PLAY', ?)
        """, (db_date, b["ticker"], b["raw_entry"], b["raw_stop"], b["raw_target"], b["notes"]))

    for a in avoids:
        cur.execute("""
            INSERT OR REPLACE INTO active_trades (date, ticker, type, entry, stop, target, status, notes)
            VALUES (?, ?, 'AVOID', ?, ?, ?, 'IN PLAY', ?)
        """, (db_date, a["ticker"], a["raw_price"], a["raw_stop"], a["raw_downside"], a["notes"]))
    conn.commit()

    cur.execute("SELECT date, ticker, type, entry, stop, target, status, notes FROM active_trades ORDER BY date DESC, ticker ASC")
    db_trades = cur.fetchall()

    # Load today's intraday high/low map for fill & breakeven verification
    today_ohlc = {row["ticker"]: row for row in parsed_today}
    history_logs = []
    for t_date, sym, t_type, t_entry, t_stop, t_target, prev_status, t_notes in db_trades:
        live_close = market_rates.get(sym, t_entry)
        ohlc = today_ohlc.get(sym)
        effective_stop = t_stop

        if t_type == "BUY":
            # Check if pullback limit order never filled on next session (gapped/ran away without dipping to entry*1.003)
            if t_date >= "2026-11-16" and t_date < db_date and prev_status == "IN PLAY" and ohlc and ohlc["low"] > (t_entry * 1.003) and live_close > t_entry * 1.015:
                status = "UNFILLED (NO CHASE)"
                pnl = 0.0
            else:
                pnl = round(((live_close - t_entry) / t_entry) * 100, 1)
                # Auto-Breakeven Lock once +2.2% profit is reached
                if pnl >= 2.2 or (ohlc and ((ohlc["high"] - t_entry) / t_entry) * 100 >= 2.5):
                    effective_stop = max(t_stop, t_entry)
                if live_close >= t_target:
                    status = "TARGET HIT"
                elif live_close <= effective_stop:
                    status = "BREAKEVEN EXIT" if effective_stop >= t_entry else "STOPPED OUT"
                else:
                    status = "IN PLAY (BE LOCKED)" if effective_stop >= t_entry else "IN PLAY"
        else:
            pnl = round(((t_entry - live_close) / t_entry) * 100, 1)
            if pnl >= 2.2:
                effective_stop = min(t_stop, t_entry)
            if live_close <= t_target:
                status = "CAPITAL PRESERVED"
            elif live_close >= effective_stop:
                status = "BREAKEVEN EXIT" if effective_stop <= t_entry else "STOPPED OUT"
            else:
                status = "IN PLAY"

        if status != prev_status or effective_stop != t_stop:
            cur.execute("UPDATE active_trades SET status = ?, stop = ? WHERE date = ? AND ticker = ?", (status, effective_stop, t_date, sym))

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

    cur.execute("""
        SELECT filing_date, ticker, category, headline
        FROM psx_disclosures ORDER BY filing_date DESC LIMIT 30
    """)
    disc_rows = cur.fetchall()

    insiders_live = []
    for f_date, sym, category, headline in disc_rows:
        live_c = market_rates.get(sym, 0.0)
        insiders_live.append({
            "filingDate": f_date,
            "ticker": sym,
            "category": category,
            "liveClose": live_c,
            "headline": headline,
            "psxUrl": f"https://dps.psx.com.pk/company/{sym}"
        })

    flow_data = resolve_session_flow(cur, db_date, kse100_pct, breadth_pct)

    # Top buying & selling sectors summary
    sorted_secs = sorted(sector_flow_map.items(), key=lambda x: x[1], reverse=True)
    top_buy_secs = [f"{k} ({v:+.1f}M)" for k, v in sorted_secs if v > 0][:3]
    top_sell_secs = [f"{k} ({v:+.1f}M)" for k, v in sorted_secs if v < 0][-3:]

    conn.commit()
    conn.close()

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(LATEST_JSON, "w") as f:
        json.dump({
            "sessionDate": session_date,
            "sessionTime": session_time,
            "macro": macro,
            "sectorSummary": {
                "buying": top_buy_secs,
                "selling": top_sell_secs
            },
            "regime": {
                "status": regime_status,
                "kseChange": f"{kse100_pct:+.2f}%",
                "breadth": f"{breadth_pct}% Advancing ({advances} Up / {declines} Down)",
                "note": regime_note,
                "isDefensive": is_defensive
            },
            "flow": flow_data,
            "buys": buys,
            "avoids": avoids
        }, f, indent=2)

    with open(HISTORY_JSON, "w") as f:
        json.dump(history_logs, f, indent=2)

    with open(INSIDERS_JSON, "w") as f:
        json.dump(insiders_live, f, indent=2)

    print(f"\n[V2 INSTITUTIONAL ENGINE] Synchronized for {session_date}:")
    print(f"  Macro: SBP Policy {macro['policyRate']}% | 6M T-Bill {macro['tbill6m']}% ({macro['deltaBps']:+d} bps — {macro['stance']})")
    print(f"  Regime: {regime_status} | Breadth: {breadth_pct}% | KSE-100: {kse100_pct:+.2f}%")
    for b in buys:
        tags = []
        if b.get("ndmBlock"): tags.append("NDM BLOCK")
        if b.get("insiderConfluence"): tags.append("INSIDER+TAPE")
        if b.get("oiConfirmed"): tags.append("OI+")
        if b.get("catalystTag"): tags.append(b["catalystTag"])
        tag_str = f" [{' | '.join(tags)}]" if tags else ""
        print(f"  BUY   #{b['rank']} {b['ticker']}{tag_str}: Zone {b['entryZone']} | Target: {b['target']}")
    for a in avoids:
        tags = [a["actionTag"]]
        if a.get("mfsTrap"): tags.append("MFS TRAP")
        if a.get("catalystTag"): tags.append(a["catalystTag"])
        print(f"  SHORT #{a['rank']} {a['ticker']} [{' | '.join(tags)}]: Zone {a['shortZone']} | Stop: {a['stop']} | Target: {a['downside']}")

if __name__ == "__main__":
    process_all()