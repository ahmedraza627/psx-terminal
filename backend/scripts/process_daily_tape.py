#!/usr/bin/env python3
"""
Daily Tape Processor - Quantitative Signal Pipeline
====================================================

Data-driven alternatives to arbitrary retail scoring. Strips out
prob-score heuristics (e.g. "53.0 +") and 20/50 SMA support assumptions;
replaces them with 4 pure quantitative modules driven by:

  1. Liquidity Sweep Long (VPVR POC + stop-hunt detection)
  2. Annualized DFX Cost-of-Carry (leverage flash detection)
  3. Mansfield Relative Strength vs KSE-100
  4. Director Footprint (Clause 5.6.4)

Database: connects to Supabase (psx_daily_eod, psx_futures_eod,
psx_disclosures) with automatic migration 012 application on first run.

Outputs: frontend/public/data/latest.json
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_PATH = Path(
    os.getenv("SYNC_OUTPUT_PATH", str(BASE_DIR / "frontend" / "public" / "data" / "latest.json"))
)

# VPVR parameters
VPVR_N_SESSIONS = 15
VPVR_BINS = 20

# Liquidity Sweep parameters
SWEEP_N_LOOKBACK = 3
SWEEP_VOLZ_MIN = 1.5

# DFX Cost-of-Carry parameters
DFX_OVERHEAT_PCT = 18.0

# Mansfield RS parameters
MANSDEN_MIN_RS = -0.5

# Director Footprint parameters
DIRECTOR_CONVICTION_TIGHT = 0.03

# Logging
LOGGER = logging.getLogger("process_daily_tape")


def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


# ---------------------------------------------------------------------------
# Database connection
# ---------------------------------------------------------------------------

def get_database_connection():
    supabase_url = os.getenv("SUPABASE_URL", "").strip()
    supabase_key = os.getenv("SUPABASE_KEY", "").strip()

    if supabase_url and supabase_key:
        LOGGER.info("Using Supabase database")
        try:
            import psycopg2
            from psycopg2.extras import RealDictRow
            conn = psycopg2.connect(
                f"postgresql://{supabase_key}@{supabase_url.replace('https://', '').replace('/', '')}",
                row_factory=RealDictRow,
            )
            return conn
        except ImportError:
            from pipeline.db import get_client
            client = get_client()
            return client

    LOGGER.info("Using local SQLite database: %s", BASE_DIR / "data" / "portfolio.db")
    import sqlite3
    conn = sqlite3.connect(BASE_DIR / "data" / "portfolio.db")
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Migration auto-application (migration 012)
# ---------------------------------------------------------------------------

def ensure_migration_012(conn) -> bool:
    has_table = False
    if hasattr(conn, "execute"):
        cur = conn.cursor()
        cur.execute(
            "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'psx_disclosures')"
        )
        has_table = cur.fetchone()[0]
    else:
        cur = conn.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='psx_disclosures'"
        )
        has_table = cur.fetchone() is not None

    if has_table:
        LOGGER.info("psx_disclosures table already exists - skipping migration 012")
        return True

    LOGGER.info("Applying migration 012: creating psx_disclosures table...")

    try:
        if hasattr(conn, "execute"):
            cur = conn.cursor()
            create_sql = """
            CREATE TABLE IF NOT EXISTS public.psx_disclosures (
                id               BIGSERIAL PRIMARY KEY,
                trade_date       DATE           NOT NULL,
                ticker           VARCHAR(16)    NOT NULL,
                headline         TEXT           NOT NULL,
                disclosure_url   TEXT,
                created_at       TIMESTAMPTZ    DEFAULT NOW(),
                CONSTRAINT uq_disclosure UNIQUE (trade_date, ticker, headline)
            );
            CREATE INDEX IF NOT EXISTS idx_disclosure_date
                ON public.psx_disclosures (trade_date DESC);
            CREATE INDEX IF NOT EXISTS idx_disclosure_ticker_date
                ON public.psx_disclosures (ticker, trade_date DESC);
            """
            cur.execute(create_sql)
            conn.commit()
            LOGGER.info("Migration 012 applied to PostgreSQL")
        else:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS psx_disclosures (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trade_date TEXT NOT NULL,
                    ticker TEXT NOT NULL,
                    headline TEXT NOT NULL,
                    disclosure_url TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(trade_date, ticker, headline)
                )
            """)
            conn.commit()
            LOGGER.info("Migration 012 applied to SQLite")
        return True
    except Exception as e:
        LOGGER.exception("Failed to apply migration 012: %s", e)
        raise


# ---------------------------------------------------------------------------
# Module 1: Liquidity Sweep & VPVR
# ---------------------------------------------------------------------------

class LiquiditySweep:
    """Computes POC from VPVR (H+L+C)/3 into 20 volume-weighted bins."""

    def __init__(self, conn):
        self.conn = conn

    def _query(self, sql, params=()):
        cur = self.conn.execute(sql, params) if hasattr(self.conn, "execute") else self.conn.cursor()
        if hasattr(cur, "fetchall"):
            return cur.fetchall()
        return cur

    def compute_poc(self) -> tuple[Optional[float], list[dict]]:
        cutoff = datetime.now().date() - timedelta(days=VPVR_N_SESSIONS * 4)
        rows = self._query(
            """
            SELECT trade_date, ticker, high_price, low_price, close_price
            FROM psx_daily_eod
            WHERE trade_date >= ? AND high_price IS NOT NULL
            ORDER BY trade_date, ticker
            """,
            (cutoff.isoformat(),),
        )
        if not rows:
            LOGGER.warning("No OHLC data found for VPVR")
            return None, []
        mid_prices = sorted(set(((r["high_price"] + r["low_price"] + r["close_price"]) / 3) for r in rows))
        if not mid_prices:
            LOGGER.warning("No mid-prices computed")
            return None, []
        lo, hi = min(mid_prices), max(mid_prices)
        bin_width = (hi - lo) / VPVR_BINS
        bin_hist = {i: 0.0 for i in range(VPVR_BINS)}
        for row in rows:
            mid = (row["high_price"] + row["low_price"] + row["close_price"]) / 3
            idx = min(int((mid - lo) / bin_width), VPVR_BINS - 1)
            bin_hist[idx] += row["volume"]
        total_volume = sum(bin_hist.values())
        if total_volume == 0:
            LOGGER.warning("Total volume is zero")
            return None, []
        poc_idx = max(range(VPVR_BINS), key=lambda i: bin_hist[i])
        poc_price = lo + (poc_idx + 0.5) * bin_width
        return poc_price, bin_hist

    def get_past_n_session_low(self, n: int) -> Optional[float]:
        cutoff = datetime.now().date() - timedelta(days=n * 4)
        rows = self._query(
            """
            SELECT MIN(low_price) as min_low FROM psx_daily_eod
            WHERE trade_date >= ? AND trade_date <= ?
            """,
            (cutoff.isoformat(), datetime.now().date().isoformat()),
        )
        return rows[0]["min_low"] if rows and rows[0]["min_low"] else None

    def get_last_close(self) -> Optional[float]:
        rows = self._query(
            """
            SELECT close_price FROM psx_daily_eod
            ORDER BY trade_date DESC LIMIT 1
            """
        )
        return rows[0]["close_price"] if rows else None

    def compute_volatility_zscore(self, current_close: float, lookback: int = 20) -> Optional[float]:
        if lookback <= 0:
            return None
        rows = self._query(
            """
            SELECT close_price, volume FROM psx_daily_eod
            WHERE trade_date <= ? AND close_price IS NOT NULL
            ORDER BY trade_date DESC
            LIMIT ?
            """,
            (datetime.now().date().isoformat(), lookback),
        )
        if len(rows) < max(lookback // 2, 5):
            return None
        closes = [r["close_price"] for r in rows]
        volumes = [r["volume"] for r in rows if r["volume"] is not None]
        if not closes or not volumes:
            return None
        avg_close = sum(closes) / len(closes)
        if avg_close == 0:
            return None
        volume_std = (sum((v - (sum(volumes)/len(volumes)))**2 for v in volumes) / len(volumes)) ** 0.5
        if volume_std == 0:
            return None
        return (current_close - avg_close) / volume_std

    def evaluate(self) -> dict:
        close = self.get_last_close()
        if not close:
            LOGGER.warning("No last close for liquidity sweep")
            return {"poc": None, "close": None, "liquidity_sweep": False, "volZScore": None}
        prior_3_session_low = self.get_past_n_session_low(SWEEP_N_LOOKBACK)
        poc_price, _ = self.compute_poc()
        if not poc_price:
            LOGGER.warning("No POC computed")
            return {"poc": None, "close": close, "liquidity_sweep": False, "volZScore": None}
        intraday_low = None
        volz = self.compute_volatility_zscore(close)
        if intraday_low is None or prior_3_session_low is None:
            return {
                "poc": poc_price,
                "close": close,
                "prior_3_session_low": prior_3_session_low,
                "liquidity_sweep": False,
                "volZScore": round(volz, 2) if volz else None,
            }
        stop_hunt = intraday_low < prior_3_session_low
        reclaim_poc = close > poc_price
        eligible = volz is not None and volz >= SWEEP_VOLZ_MIN
        sweep_triggered = stop_hunt and reclaim_poc and eligible
        LOGGER.info(
            "Liquidity sweep: stop_hunt=%s reclaim_poc=%s volz=%.2f eligible=%s trigger=%s",
            stop_hunt, reclaim_poc, volz or 0, eligible, sweep_triggered,
        )
        return {
            "poc": round(poc_price, 2),
            "close": round(close, 2),
            "prior_3_session_low": prior_3_session_low,
            "prev_low_swept": stop_hunt,
            "reclaim_poc": reclaim_poc,
            "volZScore": round(volz, 2) if volz else None,
            "liquidity_sweep": sweep_triggered,
        }


# ---------------------------------------------------------------------------
# Module 2: Annualized DFX Cost-of-Carry
# ---------------------------------------------------------------------------

class CostOfCarry:
    """Annualized spread: ((Futures - Spot)/Spot) * (365/days_to_expiry) * 100."""

    def __init__(self, conn):
        self.conn = conn

    def _last_friday(self, year: int, month: int) -> datetime.date:
        if month == 12:
            last_day = datetime(year + 1, 1, 1) - timedelta(days=1)
        else:
            last_day = datetime(year, month + 1, 1) - timedelta(days=1)
        while last_day.weekday() != 4:
            last_day -= timedelta(days=1)
        return last_day

    def get_friday_expiry_days(self) -> tuple[Optional[datetime.date], Optional[int]]:
        ref_date = datetime.now().date()
        expiry = self._last_friday(ref_date.year, ref_date.month)
        delta = (expiry - ref_date).days
        return expiry, delta

    def get_most_recent_futures_close(self, ticker: str) -> Optional[float]:
        rows = self.conn.execute(
            """
            SELECT close_price FROM psx_futures_eod
            WHERE ticker = ? AND close_price IS NOT NULL
            ORDER BY trade_date DESC LIMIT 1
            """,
            (ticker,),
        )
        return rows[0]["close_price"] if rows else None

    def get_latest_spot(self, ticker: str) -> Optional[float]:
        rows = self.conn.execute(
            """
            SELECT close_price FROM psx_daily_eod
            WHERE ticker = ? AND close_price IS NOT NULL
            ORDER BY trade_date DESC LIMIT 1
            """,
            (ticker,),
        )
        return rows[0]["close_price"] if rows else None

    def compute_carry(self, ticker: str) -> dict:
        futures_close = self.get_most_recent_futures_close(ticker)
        spot_close = self.get_latest_spot(ticker)
        expiry_dt, days = self.get_friday_expiry_days()
        if futures_close is None or spot_close is None or days is None or days == 0:
            LOGGER.warning("Missing data for cost-of-carry on %s", ticker)
            return {
                "ticker": ticker,
                "futures_close": futures_close,
                "spot_close": spot_close,
                "days_to_expiry": days,
                "annualizedCarryPct": None,
                "leverageOverheated": False,
            }
        annualized = ((futures_close - spot_close) / spot_close) * (365 / days) * 100
        flagged = annualized > DFX_OVERHEAT_PCT
        LOGGER.info(
            "Cost-of-carry %s: F=%s S=%s DTE=%d carry=%.2f%% flagged=%s",
            ticker, futures_close, spot_close, days, annualized, flagged,
        )
        return {
            "ticker": ticker,
            "futures_close": futures_close,
            "spot_close": spot_close,
            "days_to_expiry": days,
            "expiry_date": expiry_dt.isoformat() if expiry_dt else None,
            "annualizedCarryPct": round(annualized, 2),
            "leverageOverheated": flagged,
        }

    def evaluate_all(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT DISTINCT ticker FROM psx_daily_eod ORDER BY ticker"
        ).fetchall()
        tickers = [r["ticker"] for r in rows]
        return [self.compute_carry(t) for t in tickers]


# ---------------------------------------------------------------------------
# Module 3: Mansfield Relative Strength vs KSE-100
# ---------------------------------------------------------------------------

class MansfieldRS:
    """RS = Stock/KSE100; Mansfield_RS = ((RS/RS_20d_avg) - 1) * 100."""

    def __init__(self, conn):
        self.conn = conn
        self._rs_20d_cache = {}

    def get_stock_close(self, ticker: str) -> Optional[float]:
        rows = self.conn.execute(
            """
            SELECT close_price FROM psx_daily_eod
            WHERE ticker = ? AND close_price IS NOT NULL
            ORDER BY trade_date DESC LIMIT 1
            """,
            (ticker,),
        )
        return rows[0]["close_price"] if rows else None

    def get_kse100_close(self) -> Optional[float]:
        rows = self.conn.execute(
            """
            SELECT close_price FROM psx_daily_eod
            WHERE ticker = ? AND close_price IS NOT NULL
            ORDER BY trade_date DESC LIMIT 1
            """,
            ("KSE-100",),
        )
        return rows[0]["close_price"] if rows else None

    def _get_rs_20d_avg(self, ticker: str) -> Optional[float]:
        if ticker in self._rs_20d_cache:
            return self._rs_20d_cache[ticker]
        stock_close = self.get_stock_close(ticker)
        kse100_close = self.get_kse100_close()
        if not stock_close or not kse100_close or kse100_close == 0:
            self._rs_20d_cache[ticker] = None
            return None
        rows = self.conn.execute(
            """
            SELECT close_price, (SELECT close_price FROM psx_daily_eod
                                 WHERE ticker = ? AND close_price IS NOT NULL
                                 ORDER BY trade_date DESC LIMIT 1 OFFSET i) AS k_close
            FROM (SELECT trade_date, close_price,
                  ROW_NUMBER() OVER (ORDER BY trade_date DESC) - 1 AS i
                   FROM psx_daily_eod WHERE ticker = ?)
            WHERE i < 20 AND k_close IS NOT NULL
            """,
            (ticker, ticker),
        ).fetchall()
        rs_values = []
        for r in rows:
            kc = r["k_close"]
            sc = r["close_price"]
            if kc and kc != 0:
                rs_values.append(sc / kc)
        if not rs_values:
            self._rs_20d_cache[ticker] = None
            return None
        avg = sum(rs_values) / len(rs_values)
        self._rs_20d_cache[ticker] = avg
        return avg

    def compute_mansfield_rs(self, ticker: str) -> dict:
        stock_close = self.get_stock_close(ticker)
        kse100_close = self.get_kse100_close()
        if not stock_close or not kse100_close or kse100_close == 0:
            return {
                "ticker": ticker,
                "rs": None,
                "mansfieldRs": None,
                "mansfield_rs_20d_avg": None,
                "kse100Close": kse100_close,
                "hard_drop": False,
                "flag_rising_positive": False,
            }
        rs = stock_close / kse100_close
        rs_20d_avg = self._get_rs_20d_avg(ticker)
        if rs_20d_avg is None or rs_20d_avg == 0:
            return {
                "ticker": ticker,
                "rs": round(rs, 4),
                "mansfieldRs": None,
                "mansfield_rs_20d_avg": None,
                "kse100Close": kse100_close,
                "hard_drop": False,
                "flag_rising_positive": False,
            }
        mansfield_rs = ((rs / rs_20d_avg) - 1) * 100
        hard_drop = mansfield_rs < 0
        LOGGER.info(
            "Mansfield RS %s: RS=%.4f rs_20d_avg=%.4f Mansfield_RS=%.2f hard_drop=%s",
            ticker, rs, rs_20d_avg, mansfield_rs, hard_drop,
        )
        return {
            "ticker": ticker,
            "rs": round(rs, 4),
            "mansfieldRs": round(mansfield_rs, 2),
            "mansfield_rs_20d_avg": round(rs_20d_avg, 4),
            "kse100Close": kse100_close,
            "hard_drop": hard_drop,
            "flag_rising_positive": True,
        }

    def evaluate(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT DISTINCT ticker FROM psx_daily_eod ORDER BY ticker"
        ).fetchall()
        tickers = [r["ticker"] for r in rows]
        return [self.compute_mansfield_rs(t) for t in tickers]


# ---------------------------------------------------------------------------
# Module 4: Director Footprint (Clause 5.6.4)
# ---------------------------------------------------------------------------

class DirectorFootprint:
    """Parse psx_disclosures for acquisition/disposal; boost conviction +/-3% of POC/disclosure price."""

    def __init__(self, conn):
        self.conn = conn
        self.acq_keywords = [
            "acquisition", "acquisition of", "agreement to acquire", "acquirer",
            "bid", "bid for", "buy", "takeover", "merger", "joint venture",
            "equity injection", "investment in", "in-principle approval",
        ]
        self.disposal_keywords = [
            "disposal", "sale", "sold", "divestiture", "exit", "partition",
            "transfer", "donation", "loss of shares", "offload", "sell",
        ]

    def _classify_headline(self, headline: str) -> str:
        hl_lower = headline.lower()
        for kw in self.acq_keywords:
            if kw in hl_lower:
                return "ACQ"
        for kw in self.disposal_keywords:
            if kw in hl_lower:
                return "DIS"
        return "NONE"

    def get_disclosures_for_ticker(self, ticker: str) -> list[dict]:
        rows = self.conn.execute(
            """
            SELECT trade_date, headline, disclosure_url, created_at
            FROM psx_disclosures
            WHERE ticker = ? AND headline IS NOT NULL
            ORDER BY trade_date DESC
            """,
            (ticker,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_latest_disclosure_date_close(self, ticker: str) -> Optional[float]:
        rows = self.conn.execute(
            """
            SELECT d.trade_date, d.close_price
            FROM psx_daily_eod d
            JOIN psx_disclosures dis ON d.ticker = dis.ticker AND d.trade_date = dis.trade_date
            WHERE dis.ticker = ? AND d.close_price IS NOT NULL
            ORDER BY d.trade_date DESC LIMIT 1
            """,
            (ticker,),
        ).fetchall()
        if not rows:
            return None
        return rows[0]["close_price"]

    def get_current_close(self, ticker: str) -> Optional[float]:
        rows = self.conn.execute(
            """
            SELECT close_price FROM psx_daily_eod
            WHERE ticker = ? AND close_price IS NOT NULL
            ORDER BY trade_date DESC LIMIT 1
            """
        )
        return rows[0]["close_price"] if rows else None

    def get_poc(self) -> Optional[float]:
        ls = LiquiditySweep(self.conn)
        poc, _ = ls.compute_poc()
        return poc

    def evaluate(self, ticker: str) -> dict:
        disclosures = self.get_disclosures_for_ticker(ticker)
        if not disclosures:
            LOGGER.info("No disclosures found for %s", ticker)
            return {
                "ticker": ticker,
                "totalDisclosures": 0,
                "acquisitionDeclarations": 0,
                "disposalDisclosures": 0,
                "recent": [],
                "currentClose": None,
                "disclosureDateClose": None,
                "poc": None,
                "priceWithin3pctPoc": False,
                "priceWithin3pctDisclosure": False,
                "recentConvictionBoost": False,
            }
        recent = []
        recent_acquis = []
        recent_disposals = []
        for d in disclosures[:10]:
            headline = d.get("headline", "")
            cls = self._classify_headline(headline)
            rec = {
                "date": d["trade_date"],
                "headline": headline,
                "type": cls,
                "url": d.get("disclosure_url"),
            }
            recent.append(rec)
            if cls == "ACQ":
                recent_acquis.append(rec)
            elif cls == "DIS":
                recent_disposals.append(rec)
        current_close = self.get_current_close(ticker)
        disclosure_close = self.get_latest_disclosure_date_close(ticker)
        poc = self.get_poc()
        boosted = False
        if current_close and disclosure_close:
            pct = abs(current_close - disclosure_close) / disclosure_close * 100
            if pct <= DIRECTOR_CONVICTION_TIGHT:
                boosted = True
        if current_close and poc:
            pct = abs(current_close - poc) / poc * 100
            if pct <= DIRECTOR_CONVICTION_TIGHT:
                boosted = True
        LOGGER.info(
            "Director footprint %s: acq=%d dis=%d boosted=%s",
            ticker, len(recent_acquis), len(recent_disposals), boosted,
        )
        return {
            "ticker": ticker,
            "totalDisclosures": len(recent),
            "acquisitionDeclarations": len(recent_acquis),
            "disposalDisclosures": len(recent_disposals),
            "recent": recent,
            "currentClose": current_close,
            "disclosureDateClose": disclosure_close,
            "poc": poc,
            "priceWithin3pctPoc": bool(poc and current_close and
                                      abs(current_close - poc) / poc * 100 <= DIRECTOR_CONVICTION_TIGHT),
            "priceWithin3pctDisclosure": bool(current_close and disclosure_close and
                                              abs(current_close - disclosure_close) / disclosure_close * 100 <= DIRECTOR_CONVICTION_TIGHT),
            "recentConvictionBoost": boosted,
        }


# ---------------------------------------------------------------------------
# Main aggregation & JSON export
# ---------------------------------------------------------------------------

def aggregate_results() -> dict:
    conn = get_database_connection()
    try:
        ensure_migration_012(conn)
        ls = LiquiditySweep(conn)
        coc = CostOfCarry(conn)
        mr = MansfieldRS(conn)
        df = DirectorFootprint(conn)
        ls_eval = ls.evaluate()
        coc_results = coc.evaluate_all()
        mans_results = mr.evaluate()
        tickers = [r["ticker"] for r in conn.execute("SELECT DISTINCT ticker FROM psx_daily_eod ORDER BY ticker").fetchall()]
        director_results = [df.evaluate(t) for t in tickers]
        payload = {
            "sessionDate": datetime.now().strftime("%Y-%m-%d"),
            "sessionTime": datetime.now().strftime("%H:%M:%S"),
            "poc": ls_eval.get("poc"),
            "volZScore": ls_eval.get("volZScore"),
            "liquiditySweep": ls_eval.get("liquidity_sweep"),
            "annualizedCarryPct": {r["ticker"]: r["annualizedCarryPct"] for r in coc_results},
            "carryFlags": {
                r["ticker"]: {
                    "leverageOverheated": r["leverageOverheated"],
                    "daysToExpiry": r["days_to_expiry"],
                } for r in coc_results
            },
            "mansfieldRs": {r["ticker"]: {
                "rs": r["rs"],
                "mansfieldRs": r["mansfieldRs"],
                "mansfieldRs20dAvg": r["mansfield_rs_20d_avg"],
                "hardDrop": r["hard_drop"],
                "flagRisingPositive": r["flag_rising_positive"],
            } for r in mans_results},
            "directorFootprint": {
                t["ticker"]: {
                    "totalDisclosures": t["totalDisclosures"],
                    "acquisitionDeclarations": t["acquisitionDeclarations"],
                    "disposalDisclosures": t["disposalDisclosures"],
                    "priceWithin3pctPoc": t["priceWithin3pctPoc"],
                    "priceWithin3pctDisclosure": t["priceWithin3pctDisclosure"],
                    "recentConvictionBoost": t["recent_conviction_boost"],
                } for t in director_results
            },
        }
        LOGGER.info("Aggregated %d tickers into latest.json", len(tickers))
        return payload
    finally:
        if not isinstance(conn, sqlite3.Connection):
            try:
                conn.close()
            except Exception:
                pass


def write_json(payload: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = None
    if path.exists():
        try:
            with open(path) as f:
                existing = json.load(f)
        except Exception:
            existing = None
    if existing != payload:
        with open(path, "w") as f:
            json.dump(payload, f, indent=2)
        LOGGER.info("Wrote %s (%d bytes)", path, path.stat().st_size)
    else:
        LOGGER.info("No change - skipped write to %s", path)


def main(argv: Optional[list[str]] = None) -> int:
    _setup_logging()
    LOGGER.info("Starting daily tape processor")
    try:
        payload = aggregate_results()
        write_json(payload, OUTPUT_PATH)
        LOGGER.info("Daily tape processor completed successfully")
        return 0
    except ImportError as ie:
        LOGGER.error("Missing dependency: %s (install with: pip install -r requirements.txt)", ie)
        return 1
    except Exception as e:
        LOGGER.exception("Daily tape processor failed: %s", e)
        try:
            error_payload = {
                "sessionDate": datetime.now().strftime("%Y-%m-%d"),
                "sessionTime": datetime.now().strftime("%H:%M:%S"),
                "error": str(e),
                "poc": None,
                "volZScore": None,
                "liquiditySweep": False,
                "annualizedCarryPct": {},
                "carryFlags": {},
                "mansfieldRs": {},
                "directorFootprint": {},
            }
            write_json(error_payload, OUTPUT_PATH)
            LOGGER.warning("Error payload written to %s", OUTPUT_PATH)
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    sys.exit(main())
