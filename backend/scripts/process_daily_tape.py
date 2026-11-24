#!/usr/bin/env python3
# process_daily_tape.py - PSX .Z tape -> frontend/public/data/latest.json
from __future__ import annotations

import gzip, json, logging, os, re, sqlite3, sys, urllib.request, zipfile, zlib
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import median
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(BACKEND_DIR))  # `src.*` imports resolve from the backend package
from quant_modules import (calc_dfx_carry, calc_director_footprint,  # noqa: E402
                          calc_mansfield_rs, calc_vpvr_sweep)
from v5_ledger import log_signals  # noqa: E402
from src.core.models import DailyBar  # noqa: E402
from src.ingestion.sqlite_adapter import parse_psx_date  # noqa: E402
from src.quant.engine import LiquidityQuantEngine  # noqa: E402
BASE_DIR = Path(__file__).resolve().parent.parent.parent  # project root
DB_PATH = BASE_DIR / "data" / "portfolio.db"
OUTPUT_PATH = Path(os.getenv("SYNC_OUTPUT_PATH",
                             str(BASE_DIR / "frontend" / "public" / "data" / "latest.json")))
LOCAL_Z_DIR = Path(os.getenv("PSX_Z_DIR", r"D:\downloads"))
HISTORY_PATH = OUTPUT_PATH.with_name("history.json")  # V5 audit ledger
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
        if one(cur, "SELECT 1 FROM psx_daily_eod WHERE trade_date=? LIMIT 1", (stamp,)):
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
def scrape_disclosures(conn: sqlite3.Connection, tickers: list[str]) -> int:  # Clause 5.6.4
    cur, added = conn.cursor(), 0
    for ticker in tickers:
        try:
            html = fetch(FILINGS_URL.format(ticker))
        except Exception as exc:
            LOG.warning("filings unavailable for %s (%s)", ticker, exc); continue
        start = html.find('class="tabs__panel" data-name="Others"')
        block = html[start:html.find("</table>", start)] if start != -1 else ""
        for date, title in re.findall(r"<tr><td>([^<]+)</td><td>(.*?)</td>", block, re.S):
            headline = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", title)).strip()
            if not headline or not any(h in headline.lower() for h in ("5.6.4", "director", "acquisition",
                                       "purchase", "sale of shares", "disclosure of interest", "insider")):
                continue
            try:
                day = datetime.strptime(date.strip(), "%b %d, %Y").strftime("%d%b%Y")
            except ValueError:
                continue
            cur.execute("INSERT OR REPLACE INTO psx_disclosures VALUES (?,?,?,?)",
                        (day, ticker, headline[:300], "Clause 5.6.4"))
            added += 1
    conn.commit()
    LOG.info("clause 5.6.4 filings stored: %d", added)
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
def analyse(cur, session: str, session_date, rows) -> tuple[list, list, list]:
    """Desk calls come from the same engine the backtest replays - no separate rules."""
    kse_proxy = one(cur, "SELECT AVG(close_price) FROM psx_daily_eod WHERE trade_date=? AND close_price>0 AND ticker "
                         "NOT LIKE '%-%'", (session,))
    sweeps, leaders, traps = [], [], []
    for row in rows:
        ticker, close = row["ticker"], row["close_price"]
        bars = tape_bars(cur, ticker, session_date)
        if not bars or bars[-1].trade_date != session_date:
            continue  # stale ticker or a bar that failed OHLC validation
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
        fut = one(cur, "SELECT close_price FROM psx_futures_eod WHERE trade_date=? AND ticker LIKE ? AND close_price>0 "
                       "ORDER BY COALESCE(volume,0) DESC LIMIT 1", (session, f"{ticker}-%"))
        if fut and fut > 0:
            carry = calc_dfx_carry(close, fut, session_date, ticker)
            if carry["leverageOverheated"] and mansfield < 0 and not trend_ok:  # never short a strong RS leader
                traps.append({"ticker": ticker, "spotClose": close, "futClose": fut, "mansfieldRs": mansfield,
                              "annualizedCarryPct": carry["annualizedCarryPct"]})
    sweeps.sort(key=lambda s: -s["mansfieldRs"])
    leaders.sort(key=lambda s: -s["mansfieldRs"])
    traps.sort(key=lambda s: -s["annualizedCarryPct"])
    return sweeps[:5], leaders[:5], traps[:5]
def main() -> dict:
    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row
    ensure_tables(conn)
    stats = backfill(conn)
    LOG.info("tape files loaded: %d, rows: %d", stats["files"], stats["rows"])
    cur = conn.cursor()
    dates = [r[0] for r in cur.execute("SELECT DISTINCT trade_date FROM psx_daily_eod")]
    if not dates: raise SystemExit("no PSX tape rows - put YYYY-MM-DD.Z in " + str(LOCAL_Z_DIR))
    dates.sort(key=lambda s: datetime.strptime(s, "%d%b%Y"))
    session = dates[-1]; session_date = datetime.strptime(session, "%d%b%Y").date()
    sweeps, leaders, traps = analyse(cur, session, session_date, liquid(cur, dates[-15:], session))
    scrape_disclosures(conn, sorted({row["ticker"] for row in sweeps + leaders + traps}))
    for item in sweeps:
        item["directorFootprint"] = calc_director_footprint(cur, item["ticker"], item["close"], item["poc"])["directorFootprint"]
    watch = [] if sweeps else [lead for lead in leaders if lead["mansfieldRs"] >= 8.0]
    audited = log_signals(conn, cur, session, sweeps + watch, traps, HISTORY_PATH)
    payload = {"sessionDate": session_date.isoformat(), "kse100": index_snapshot(), "sbpRate": SBP_RATE_PCT,
               "liquiditySweeps": sweeps, "rsLeaders": leaders, "carryTraps": traps,
               "engine": {"lookbackDays": LOOKBACK_DAYS, "trendMaDays": TREND_MA_DAYS,
                          "trendSlopeBars": TREND_SLOPE_BARS, "minRvol": MIN_RVOL, "minVolZ": MIN_VOL_Z,
                          "atrStopMult": ATR_STOP_MULT, "maxStopPct": MAX_STOP_PCT, "targetPct": TARGET_PCT,
                          "weeklyConfluence": False, "pocConfluence": False}}
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True); OUTPUT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    LOG.info("wrote %s and %d audited ledger rows", OUTPUT_PATH, audited)
    return payload
if __name__ == "__main__":
    main()
