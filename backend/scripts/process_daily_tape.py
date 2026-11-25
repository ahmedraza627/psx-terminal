#!/usr/bin/env python3
# process_daily_tape.py - PSX .Z tape -> frontend/public/data/latest.json
from __future__ import annotations

import gzip, json, logging, os, re, sqlite3, sys, urllib.request, zipfile, zlib
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import median
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(BACKEND_DIR))  # `src.*` imports resolve from the backend package
from quant_modules import (calc_catalyst, calc_dfx_carry, calc_director_footprint,  # noqa: E402
                          calc_mansfield_rs, calc_pocket_pivot, calc_quiet_absorption,
                          calc_volume_dryup, calc_vpvr_sweep)
from institutional_desk import (active_rights, build_desk, catalyst_events,  # noqa: E402
                               load_seasonality, open_position_ages, stale_tickers)
from v5_ledger import log_signals  # noqa: E402
from src.core.models import DailyBar  # noqa: E402
from src.ingestion.sqlite_adapter import parse_psx_date  # noqa: E402
from src.quant.engine import LiquidityQuantEngine  # noqa: E402
from src.quant.sector_rotation import DEFAULT_SECTOR_MAP  # noqa: E402
BASE_DIR = Path(__file__).resolve().parent.parent.parent  # project root
DB_PATH = BASE_DIR / "data" / "portfolio.db"
OUTPUT_PATH = Path(os.getenv("SYNC_OUTPUT_PATH",
                             str(BASE_DIR / "frontend" / "public" / "data" / "latest.json")))
LOCAL_Z_DIR = Path(os.getenv("PSX_Z_DIR", r"D:\downloads"))
HISTORY_PATH = OUTPUT_PATH.with_name("history.json")  # V5 audit ledger
SEASONALITY_PATH = OUTPUT_PATH.with_name("seasonality_matrix.json")
TAPE_URL = "https://dps.psx.com.pk/download/mkt_summary/{}.Z"
INDICES_URL = "https://dps.psx.com.pk/indices"
FILINGS_URL = "https://dps.psx.com.pk/company/{}"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
SBP_RATE_PCT = 12.0  # policy rate the frontend compares carry against
MIN_CLOSE_PKR, MIN_TURNOVER_PKR, MIN_MEDIAN_TURNOVER_PKR = 12.0, 20_000_000, 15_000_000
# Institutional gates. These must stay byte-identical to the engine defaults the
# 1-year backtest reports, otherwise the desk and the lab disagree.
LOOKBACK_DAYS, MIN_RVOL, MIN_VOL_Z = 5, 1.5, 1.0
TREND_MA_DAYS, TREND_SLOPE_BARS, ATR_STOP_MULT = 50, 10, 2.0
MAX_STOP_PCT, TARGET_PCT = 15.0, 12.0  # outer stop bound, flat target — same as StrategyConfig
HISTORY_DB = BACKEND_DIR / "psx_history.db"  # WAL store the 1-year lab replays
ENGINE = LiquidityQuantEngine(lookback_days=LOOKBACK_DAYS, trend_ma_days=TREND_MA_DAYS,
                              trend_slope_bars=TREND_SLOPE_BARS, min_rvol=MIN_RVOL,
                              min_vol_z=MIN_VOL_Z, atr_stop_mult=ATR_STOP_MULT)
EOD_SCHEMA = ("CREATE TABLE IF NOT EXISTS {} (trade_date TEXT NOT NULL, ticker TEXT NOT NULL, open_price REAL, high_price REAL, "
              "low_price REAL, close_price REAL, volume INTEGER, PRIMARY KEY (trade_date, ticker))")
INSERT = ("INSERT OR REPLACE INTO {} (trade_date, ticker, open_price, high_price, low_price, close_price, volume) VALUES "
          "(:trade_date, :ticker, :open_price, :high_price, :low_price, :close_price, :volume)")
LOG = logging.getLogger("process_daily_tape")
def fetch(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": UA}); return urllib.request.urlopen(
        request, timeout=60).read().decode("utf-8", "replace")
def one(cur: sqlite3.Cursor, sql: str, params=()):
    row = cur.execute(sql, params).fetchone(); return row[0] if row else None
def ensure_tables(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    for name in ("psx_daily_eod", "psx_futures_eod"):
        cols = [row[1] for row in cur.execute(f"PRAGMA table_info({name})")]
        if cols and "open_price" not in cols: cur.execute(f"DROP TABLE {name}")
        cur.execute(EOD_SCHEMA.format(name))
    cur.execute("CREATE TABLE IF NOT EXISTS psx_disclosures (trade_date TEXT NOT NULL, ticker TEXT NOT NULL, headline TEXT, "
                "disclosure_type TEXT, PRIMARY KEY (trade_date, ticker, headline))")
    # Older stores named the type column disclosure_url; rename it in place so the
    # catalyst queries work against both generations.
    cols = [row[1] for row in cur.execute("PRAGMA table_info(psx_disclosures)")]
    if "disclosure_url" in cols and "disclosure_type" not in cols:
        cur.execute("ALTER TABLE psx_disclosures RENAME COLUMN disclosure_url TO disclosure_type")
    # NCCPL participant x sector flows: the institutional absorption ledger.
    cur.execute("CREATE TABLE IF NOT EXISTS nccpl_flows (trade_date TEXT NOT NULL, participant_type TEXT NOT NULL, "
                "sector_name TEXT NOT NULL, buy_pkr REAL, sell_pkr REAL, net_pkr REAL NOT NULL, source TEXT, "
                "ingested_at TEXT NOT NULL DEFAULT (datetime('now')), "
                "PRIMARY KEY (trade_date, participant_type, sector_name))")
    cur.execute("CREATE INDEX IF NOT EXISTS nccpl_flows_date_sector_idx ON nccpl_flows "
                "(trade_date DESC, sector_name)")
    cur.execute("CREATE TABLE IF NOT EXISTS company_fundamentals (ticker TEXT PRIMARY KEY, free_float_pct REAL, "
                "free_float_shares REAL, pe_ratio REAL, pb_ratio REAL, "
                "turnaround_catalyst INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL)")
    cur.execute("CREATE TABLE IF NOT EXISTS active_right_issues (ticker TEXT NOT NULL, announcement_date TEXT NOT NULL, "
                "ratio TEXT, issue_price REAL, terp REAL, lor_price REAL, subscription_price REAL, "
                "days_remaining INTEGER, purpose TEXT, sponsor_committed INTEGER, "
                "status TEXT NOT NULL DEFAULT 'ANNOUNCED', source TEXT, updated_at TEXT NOT NULL, "
                "PRIMARY KEY (ticker, announcement_date))")
    # Stores created before the six-layer framework gain the new columns in place.
    for table, column, ddl in (("company_fundamentals", "free_float_shares", "REAL"),
                               ("active_right_issues", "lor_price", "REAL"),
                               ("active_right_issues", "subscription_price", "REAL"),
                               ("active_right_issues", "days_remaining", "INTEGER"),
                               ("active_right_issues", "purpose", "TEXT"),
                               ("active_right_issues", "sponsor_committed", "INTEGER")):
        cols = [row[1] for row in cur.execute(f"PRAGMA table_info({table})")]
        if column not in cols:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
    conn.commit()
def parse_tape(path: Path) -> list[dict]:
    """ZIP/gzip/LZW/plain tape: date|ticker|time|name|open|high|low|close|volume|prev."""
    raw = path.read_bytes()
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            text = "".join(archive.read(n).decode("utf-8", "replace") for n in archive.namelist())
    elif raw[:2] == b"\x1f\x8b":
        text = gzip.decompress(raw).decode("utf-8", "replace")
    elif raw[:1] == b"\x1f":
        text = zlib.decompress(raw, -15).decode("utf-8", "replace")
    else:
        text = raw.decode("utf-8", "replace")
    rows = []
    for line in text.splitlines():
        parts = line.split("|")
        try:
            rows.append({"trade_date": parts[0].strip(), "ticker": parts[1].strip().upper(),
                         "open_price": round(float(parts[4]), 2), "high_price": float(parts[5]),
                         "low_price": float(parts[6]), "close_price": round(float(parts[7]), 2),
                         "volume": int(float(parts[8] or 0))})
        except (ValueError, IndexError):
            continue
    return rows
def backfill(conn: sqlite3.Connection, n: int = 25) -> dict[str, int]:  # last n weekdays
    """Fill only sessions the tape store is missing; gap history comes from the WAL store."""
    cur, counts = conn.cursor(), {"files": 0, "rows": 0}
    weekdays = [d.isoformat() for d in
                (datetime.now().date() - timedelta(days=i) for i in range(n * 2, -1, -1)) if d.weekday() < 5][-n:]
    for stamp in sorted(weekdays):
        # Stored sessions use the tape's own format (24NOV2026); the download path
        # and URL use ISO. Comparing the ISO stamp against the tape column never
        # matched, so every run re-downloaded the whole window.
        tape_day = datetime.strptime(stamp, "%Y-%m-%d").strftime("%d%b%Y")
        if one(cur, "SELECT 1 FROM psx_daily_eod WHERE trade_date=? LIMIT 1", (tape_day,)):
            continue  # already ingested - a warm store must not re-download the year
        path = LOCAL_Z_DIR / f"{stamp}.Z"
        if not path.is_file():
            try:
                path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(urllib.request.urlopen(
                    urllib.request.Request(TAPE_URL.format(stamp), headers={"User-Agent": UA}), timeout=60).read())
            except Exception as exc:  # offline, 404, holiday...
                LOG.warning("no tape for %s (%s)", stamp, exc)
                continue
        rows = parse_tape(path)
        counts["files"] += 1
        for row in rows:
            table = "psx_futures_eod" if "-" in row["ticker"] else "psx_daily_eod"
            cur.execute(INSERT.format(table), row)
        counts["rows"] += len(rows)
    conn.commit()
    return counts
def index_snapshot() -> dict:  # KSE-100 close/change from the DPS indices board
    try:
        if hit := re.search(r"KSE100 ([\d,]+\.\d+) (-?[\d.]+) \((-?[\d.]+)%\)",
                            re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", fetch(INDICES_URL)))):
            return {"close": float(hit.group(1).replace(",", "")), "changePct": float(hit.group(3))}
    except Exception as exc:
        LOG.warning("indices unavailable (%s)", exc)
    return {"close": None, "changePct": None}
CATALYST_PANELS = ("Material Information", "Board Meetings", "Others")
DIRECTOR_TERMS = ("5.6.4", "director", "acquisition", "purchase", "sale of shares",
                  "disclosure of interest", "insider", "form 31", "form 32",
                  "substantial shareholding")

def _panel_table(html: str, name: str) -> str:
    """One tabs__panel body up to its closing table (PSX ships the panels server-side)."""
    start = html.find(f'class="tabs__panel" data-name="{name}"')
    if start == -1:
        return ""
    return html[start:html.find("</table>", start)]

def _filing_rows(ticker: str, html: str) -> list[tuple]:
    """(trade_date, ticker, headline, disclosure_type) rows worth storing."""
    rows = []
    for panel in CATALYST_PANELS:
        block = _panel_table(html, panel)
        for date, title in re.findall(r"<tr><td>([^<]+)</td><td>(.*?)</td>", block, re.S):
            headline = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", title)).strip()
            if not headline:
                continue
            catalyst = calc_catalyst(headline)["catalyst"]
            director = any(term in headline.lower() for term in DIRECTOR_TERMS)
            if not catalyst and not director:
                continue
            try:
                day = datetime.strptime(date.strip(), "%b %d, %Y").strftime("%d%b%Y")
            except ValueError:
                continue
            kind = (f"BOARD MEETING · {catalyst}" if catalyst and panel == "Board Meetings"
                    else f"PUCARS · {catalyst}" if catalyst else "Clause 5.6.4")
            rows.append((day, ticker, headline[:300], kind))
    return rows


def scrape_disclosures(conn: sqlite3.Connection, tickers: list[str], workers: int = 8) -> int:
    """PUCARS material information + board meetings, filtered to alpha triggers.

    PSX files material information inside the company announcement panels; each
    row is classified by calc_catalyst() so the desk can tag ACQUISITION, LAND
    SALE, DEMERGER, BUY-BACK, RIGHT ISSUE and friends. Director-interest
    disclosures (Clause 5.6.4) keep flowing into the insider footprint. Company
    pages are independent requests, so they are fetched concurrently.
    """
    def fetch_page(ticker: str) -> tuple[str, str]:
        try:
            request = urllib.request.Request(FILINGS_URL.format(ticker), headers={"User-Agent": UA})
            return ticker, urllib.request.urlopen(request, timeout=20).read().decode("utf-8", "replace")
        except Exception as exc:  # noqa: BLE001 - one blocked page must not stall the desk
            LOG.warning("filings unavailable for %s (%s)", ticker, exc)
            return ticker, ""

    with ThreadPoolExecutor(max_workers=workers) as pool:
        pages = list(pool.map(fetch_page, tickers))
    cur, added = conn.cursor(), 0
    for ticker, html in pages:
        for row in _filing_rows(ticker, html):
            cur.execute("INSERT OR REPLACE INTO psx_disclosures VALUES (?,?,?,?)", row)
            added += 1
    conn.commit()
    LOG.info("PUCARS/board-meeting disclosures stored: %d", added)
    return added
def liquid(cur, window: list[str], session: str) -> list:  # 15-session median turnover floor
    marks = ",".join("?" * len(window))
    series: dict[str, list[float]] = {}
    sql = (f"SELECT ticker, close_price*COALESCE(volume,0) FROM psx_daily_eod WHERE trade_date IN ({marks}) "
           f"AND ticker NOT LIKE '%-%' AND ticker NOT GLOB '*[0-9]*'")
    for ticker, turnover in cur.execute(sql, tuple(window)):
        series.setdefault(ticker, []).append(turnover or 0.0)
    rows = cur.execute("""SELECT ticker, close_price, low_price FROM psx_daily_eod WHERE trade_date=? AND close_price>=?
        AND ticker NOT LIKE '%-%' AND ticker NOT GLOB '*[0-9]*' AND close_price*COALESCE(volume,0)>=?
        ORDER BY close_price*COALESCE(volume,0) DESC""", (session, MIN_CLOSE_PKR, MIN_TURNOVER_PKR)).fetchall()
    return [row for row in rows if median(series.get(row["ticker"], [0])) >= MIN_MEDIAN_TURNOVER_PKR]
def _bar(ticker: str, day, open_price, high_price, low_price, close_price, volume):
    try:
        return DailyBar(ticker=ticker, trade_date=day if isinstance(day, date) else parse_psx_date(str(day)),
                        open_price=float(open_price or close_price), high_price=float(high_price),
                        low_price=float(low_price), close_price=float(close_price), volume=int(volume or 0))
    except (ValueError, TypeError):
        return None

def history_bars(ticker: str, session_date: date) -> dict:
    """Gap history from the WAL store, so the 50-day trend has a year to read."""
    if not HISTORY_DB.is_file():
        return {}
    conn = sqlite3.connect(HISTORY_DB); conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT date, open, high, low, close, volume FROM daily_eod WHERE ticker=?",
                            (ticker,)).fetchall()
    except sqlite3.OperationalError:  # store not migrated yet: the tape alone still works
        rows = []
    finally:
        conn.close()
    out = {}
    for row in rows:
        bar = _bar(ticker, row["date"], row["open"], row["high"], row["low"], row["close"], row["volume"])
        if bar and bar.trade_date <= session_date:
            out[bar.trade_date] = bar
    return out

def tape_bars(cur, ticker: str, session_date: date) -> list[DailyBar]:
    """WAL history merged with today's tape; the live tape wins on a shared session."""
    by_day = history_bars(ticker, session_date)
    rows = cur.execute("SELECT trade_date, open_price, high_price, low_price, close_price, volume "
                       "FROM psx_daily_eod WHERE ticker=? AND high_price>0 AND low_price>0 AND close_price>0",
                       (ticker,)).fetchall()
    for row in rows:
        bar = _bar(ticker, row["trade_date"], row["open_price"], row["high_price"], row["low_price"],
                   row["close_price"], row["volume"])
        if bar and bar.trade_date <= session_date:
            by_day[bar.trade_date] = bar
    return [by_day[day] for day in sorted(by_day)]
def analyse(cur, session: str, session_date, rows) -> tuple[list, list, list, dict]:
    """Desk calls come from the same engine the backtest replays - no separate rules.

    The fourth return value is the per-ticker tape profile (ATR stop, POC, 20-session
    absorption shape) the institutional desk layers event and flow data onto.
    """
    kse_proxy = one(cur, "SELECT AVG(close_price) FROM psx_daily_eod WHERE trade_date=? AND close_price>0 AND ticker "
                         "NOT LIKE '%-%'", (session,))
    sweeps, leaders, traps, metrics = [], [], [], {}
    for row in rows:
        ticker, close = row["ticker"], row["close_price"]
        bars = tape_bars(cur, ticker, session_date)
        if not bars or bars[-1].trade_date != session_date:
            continue  # stale ticker or a bar that failed OHLC validation
        if len(bars) < 2:
            continue  # brand-new listing: no prior bar, so no ATR/volume baseline
        signal = ENGINE.evaluate_ticker(bars)
        vpvr = calc_vpvr_sweep(cur, ticker)
        mansfield = calc_mansfield_rs(cur, ticker, close, kse_proxy)["mansfieldRs"] or 0.0
        window = bars[-(LOOKBACK_DAYS + 1):-1]
        avg_vol = sum(b.volume for b in window) / len(window) if window else 0
        rvol = bars[-1].volume / avg_vol if avg_vol else 0.0
        vol_z = LiquidityQuantEngine.volume_zscore(window, bars[-1].volume) if window else 0.0
        atr = ENGINE.compute_atr(bars[:-1])
        trend_ok = ENGINE.trend_confirmed(bars)
        volume_ok = rvol >= MIN_RVOL and vol_z >= MIN_VOL_Z
        sma = ENGINE.trend_average(bars[:-1])
        stretch = ((close / sma) - 1) * 100 if sma else 0.0
        stop_floor = round(close * (1 - MAX_STOP_PCT / 100), 2)
        if signal and signal.side == "BUY":
            sweeps.append({"ticker": ticker, "close": close, "poc": signal.poc or vpvr["poc"],
                           "mansfieldRs": mansfield, "volZScore": round(vol_z, 2), "rvol": round(rvol, 2),
                           "trendStretchPct": round(stretch, 2), "atr": round(atr, 2),
                           "target": round(signal.entry_price * (1 + TARGET_PCT / 100), 2),
                           "stopLoss": max(signal.stop_loss, stop_floor), "reason": signal.reason,
                           "directorFootprint": False})
        elif trend_ok and volume_ok:
            # Gates passed, no sweep trigger: accumulate into the node, never chase.
            leaders.append({"ticker": ticker, "close": close, "mansfieldRs": mansfield,
                            "volZScore": round(vol_z, 2), "rvol": round(rvol, 2),
                            "trendStretchPct": round(stretch, 2), "poc": vpvr["poc"],
                            "stopLoss": max(ENGINE.atr_stop_price(close, atr), stop_floor),
                            "target": round(close * (1 + TARGET_PCT / 100), 2)})
        metrics[ticker] = {"ticker": ticker, "close": close,
                           "sector": DEFAULT_SECTOR_MAP.get(ticker, "Miscellaneous"),
                           "atr": round(atr, 2), "poc": vpvr["poc"], "mansfieldRs": mansfield,
                           "stop": round(max(close - ATR_STOP_MULT * atr, stop_floor), 2),
                           "quiet": calc_quiet_absorption(bars),
                           "dryup": calc_volume_dryup(bars), "pivot": calc_pocket_pivot(bars),
                           "volume": int(bars[-1].volume or 0),
                           "aboveSma50": bool(sma and close > sma)}
        # Only a contract that actually traded this session counts: a close with no volume is a
        # stale quote, and a scrip-less ticker has no futures market to compare against.
        fut = cur.execute("SELECT ticker, close_price FROM psx_futures_eod WHERE trade_date=? AND ticker LIKE ? "
                          "AND close_price>0 AND COALESCE(volume,0)>0 ORDER BY COALESCE(volume,0) DESC LIMIT 1",
                          (session, f"{ticker}-%")).fetchone()
        if fut and fut[1] and fut[1] > 0:
            carry = calc_dfx_carry(close, fut[1], session_date, fut[0])
            if carry["leverageOverheated"] and mansfield < 0 and not trend_ok:  # never short a strong RS leader
                traps.append({"ticker": ticker, "spotClose": close, "futClose": fut[1], "mansfieldRs": mansfield,
                              "annualizedCarryPct": carry["annualizedCarryPct"]})
    sweeps.sort(key=lambda s: -s["mansfieldRs"])
    leaders.sort(key=lambda s: -s["mansfieldRs"])
    traps.sort(key=lambda s: -s["annualizedCarryPct"])
    return sweeps[:5], leaders[:5], traps[:5], metrics
def reconcile_traps(traps: list[dict], setups: list[dict]) -> tuple[list[dict], list[dict]]:
    """A name cannot be both a live setup and a carry trap on the same session.

    The six-layer setup is the desk's current read, so the carry trap is suppressed
    and the suppression is published - never logged as a contradictory AVOID.
    """
    active = {row["ticker"] for row in setups}
    kept = [row for row in traps if row["ticker"] not in active]
    suppressed = [{"ticker": row["ticker"], "call": "AVOID", "label": "DFX CARRY TRAP",
                   "reason": "active six-layer setup on the same session"}
                  for row in traps if row["ticker"] in active]
    return kept, suppressed
def main() -> dict:
    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30); conn.row_factory = sqlite3.Row
    ensure_tables(conn)
    stats = backfill(conn)
    LOG.info("tape files loaded: %d, rows: %d", stats["files"], stats["rows"])
    cur = conn.cursor()
    dates = [r[0] for r in cur.execute("SELECT DISTINCT trade_date FROM psx_daily_eod")]
    if not dates: raise SystemExit("no PSX tape rows - put YYYY-MM-DD.Z in " + str(LOCAL_Z_DIR))
    dates.sort(key=lambda s: datetime.strptime(s, "%d%b%Y"))
    session = dates[-1]; session_date = datetime.strptime(session, "%d%b%Y").date()
    rows = liquid(cur, dates[-15:], session)
    sweeps, leaders, traps, metrics = analyse(cur, session, session_date, rows)
    scrape_disclosures(conn, sorted({row["ticker"] for row in rows}))
    for item in sweeps:
        item["directorFootprint"] = calc_director_footprint(cur, item["ticker"], item["close"], item["poc"])["directorFootprint"]
    watch = [] if sweeps else [lead for lead in leaders if lead["mansfieldRs"] >= 8.0]
    season, season_month, sector_season = load_seasonality(SEASONALITY_PATH)
    breadth = (sum(1 for m in metrics.values() if m.get("aboveSma50")) / len(metrics) * 100
               if metrics else None)
    session_dates = sorted({datetime.strptime(day, "%d%b%Y").date() for day in dates})
    setups, alerts, desk = build_desk(cur, session_date, metrics, season, season_month,
                                      catalyst_events(cur, session_date), active_rights(cur),
                                      breadth_pct=breadth,
                                      positions=open_position_ages(cur, session_date, session_dates),
                                      stale=stale_tickers(cur, session, dates[-10:]),
                                      sector_season=sector_season)
    traps, suppressed = reconcile_traps(traps, setups)
    desk["carryTrapsSuppressed"] = len(suppressed)
    audited = log_signals(conn, cur, session, sweeps + watch, traps, HISTORY_PATH,
                          exclude={(session, row["ticker"]) for row in suppressed})
    payload = {"sessionDate": session_date.isoformat(), "kse100": index_snapshot(), "sbpRate": SBP_RATE_PCT,
               "liquiditySweeps": sweeps, "rsLeaders": leaders, "carryTraps": traps,
               "suppressedCarryTraps": suppressed,
               "institutionalSetups": setups, "distributionAlerts": alerts, "institutionalDesk": desk,
               "engine": {"lookbackDays": LOOKBACK_DAYS, "trendMaDays": TREND_MA_DAYS,
                          "trendSlopeBars": TREND_SLOPE_BARS, "minRvol": MIN_RVOL, "minVolZ": MIN_VOL_Z,
                          "atrStopMult": ATR_STOP_MULT, "maxStopPct": MAX_STOP_PCT, "targetPct": TARGET_PCT,
                          "weeklyConfluence": False, "pocConfluence": False}}
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True); OUTPUT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    LOG.info("wrote %s and %d audited ledger rows", OUTPUT_PATH, audited)
    return payload
if __name__ == "__main__":
    main()
