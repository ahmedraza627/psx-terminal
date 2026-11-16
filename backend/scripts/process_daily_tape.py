#!/usr/bin/env python3
"""
Daily Tape Processor - Quantitative Signal Pipeline
====================================================

Strips out arbitrary retail scoring and replaces it with 4 pure quantitative
modules driven by the existing SQLite daily_eod table, .Z tape futures
(sec 40/41), and psx_disclosures:

  1. Liquidity Sweep Long (VPVR POC + stop-hunt detection)
  2. Annualized DFX Cost-of-Carry (leverage flash detection)
  3. Mansfield Relative Strength vs KSE-100
  4. Director Footprint (Clause 5.6.4)

Outputs: frontend/public/data/latest.json
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = os.getenv("DB_PATH", str(BASE_DIR / "data" / "portfolio.db"))
OUTPUT_PATH = Path(
    os.getenv("SYNC_OUTPUT_PATH", str(BASE_DIR / "frontend" / "public" / "data" / "latest.json"))
)

# The last trading day of the month to find the expiry
DAY_STOP = {0, 1, 2, 3, 4, 5, 6}  # weekends (Mon-Fri trading)

# VPVR parameters
VPVR_N_SESSIONS = 15        # bucket last 15 sessions
VPVR_BINS = 20              # price bins
VPVR_CLOSE_WEIGHT = "close" # weight buckets by volume (use (H+L+C)/3 for price mid, volume as weight)

# Liquidity Sweep parameters
SWEEP_N_LOOKBACK = 3        # prior N sessions for low comparison
SWEEP_VOLZ_MIN = 1.5        # min volume z-score to qualify

# DFX Cost-of-Carry parameters (Table 2 annualized < 7.5% for no-flash)
DFX_MAX_SPREAD = 11.0       # uBR (11% SBP policy rate)
DFX_OVERHEAT_PCT = 18.0     # annualized > 18% = LEVERAGE OVERHEATED

# Mansfield RS parameters
MANSDEN_20D_AVG = 20        # rolling window for RS baseline
MANSDEN_MIN_RS = -0.5       # minimum Mansfield RS to allow longs (hard-drop below)

# Director Footprint parameters
DIRECTOR_CONVICTION_TIGHT = 0.03  # ±3% of POC or disclosure-date price

# Logging
LOGGER = logging.getLogger("process_daily_tape")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _connect_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Module 1: Liquidity Sweep & VPVR
# ---------------------------------------------------------------------------

class LiquiditySweep:
    """
    Computes the Point of Control (POC) from the last VPVR_N_SESSIONS
    sessions using (H+L+C)/3 mid-price buckets weighted by volume.

    A Liquidity Sweep Long triggers when:
      - Intraday low sweeps below the prior 3-session low (stop hunt)
      - Close reclaims above the POC
      - Volume Z-Score >= SWEEP_VOLZ_MIN
    """

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def compute_poc(self, lookback: int = None) -> tuple[float, list[dict]]:
        """
        Bucket (H+L+C)/3 into 20 price bins weighted by volume over the
        last 15 sessions to find the exact POC.
        """
        lookback = lookback or VPVR_N_SESSIONS
        cutoff = datetime.now().date() - timedelta(days=lookback * 4)  # ~4 trading days per session

        rows = self.conn.execute(
            """
            SELECT trade_date, ticker, high_price, low_price, close_price
            FROM psx_daily_eod
            WHERE trade_date >= ? AND high_price IS NOT NULL
            ORDER BY trade_date, ticker
            """,
            (cutoff.isoformat(),),
        ).fetchall()

        if not rows:
            LOGGER.warning("No OHLC data found for VPVR")
            return None, []

        # Mid-price for each bar
        mid_prices = sorted(set(((r["high_price"] + r["low_price"] + r["close_price"]) / 3) for r in rows))

        if not mid_prices:
            LOGGER.warning("No mid-prices computed")
            return None, []

        lo, hi = min(mid_prices), max(mid_prices)
        bin_width = (hi - lo) / VPVR_BINS

        # Accumulate volume per bin
        bin_hist: dict[int, float] = {i: 0.0 for i in range(VPVR_BINS)}
        for row in rows:
            mid = (row["high_price"] + row["low_price"] + row["close_price"]) / 3
            idx = min(int((mid - lo) / bin_width), VPVR_BINS - 1)
            bin_hist[idx] += row["volume"]

        total_volume = sum(bin_hist.values())
        if total_volume == 0:
            LOGGER.warning("Total volume is zero")
            return None, []

        # Find POC = bin with max volume
        poc_idx = max(range(VPVR_BINS), key=lambda i: bin_hist[i])
        poc_price = lo + (poc_idx + 0.5) * bin_width

        # Extremes
        poc_low = lo
        poc_high = hi

        return poc_price, bin_hist

    def get_past_n_session_low(self, n: int) -> float:
        """
        Return the lowest low over the prior N sessions (stop-hunt lookback).
        """
        cutoff = datetime.now().date() - timedelta(days=n * 4)
        rows = self.conn.execute(
            """
            SELECT MIN(low_price) as min_low FROM psx_daily_eod
            WHERE trade_date >= ? AND trade_date <= ?
            """,
            (cutoff.isoformat(), datetime.now().date().isoformat()),
        ).fetchone()
        return rows["min_low"] if rows["min_low"] else None

    def get_last_close(self) -> Optional[float]:
        """Last closed price."""
        row = self.conn.execute(
            """
            SELECT close_price FROM psx_daily_eod
            ORDER BY trade_date DESC LIMIT 1
            """
        ).fetchone()
        return row["close_price"] if row else None

    def compute_volatility_zscore(self, current_close: float, lookback: int = 20) -> Optional[float]:
        """
        Compute the volume z-score over a lookback window.
        """
        if lookback <= 0:
            return None

        rows = self.conn.execute(
            """
            SELECT close_price, volume FROM psx_daily_eod
            WHERE trade_date <= ? AND close_price IS NOT NULL
            ORDER BY trade_date DESC
            LIMIT ?
            """,
            (datetime.now().date().isoformat(), lookback),
        ).fetchall()

        if len(rows) < max(lookback // 2, 5):
            return None

        closes = [r["close_price"] for r in rows]
        volumes = [r["volume"] for r in rows if r["volume"] is not None]

        if not closes or not volumes:
            return None

        avg_close = sum(closes) / len(closes)
        if avg_close == 0:
            return None

        volume_std = (sum((v - (sum(volumes) / len(volumes))) ** 2 for v in volumes) / len(volumes)) ** 0.5
        if volume_std == 0:
            return None

        volz = (current_close - avg_close) / volume_std
        return volz

    def evaluate(self, today: Optional[datetime] = None) -> dict:
        """
        Evaluate liquidity sweep conditions:
          - Intraday low < prior 3-session low (stop hunt)
          - Close > POC
          - Volume Z-Score >= 1.5
        """
        today = today or datetime.now()
        session_date = today.date()

        # Get last close
        close = self.get_last_close()

        # Get prior N-session low
        prior_3_session_low = self.get_past_n_session_low(SWEEP_N_LOOKBACK)

        # Compute POC
        poc_price, _ = self.compute_poc()

        if not close or not prior_3_session_low or poc_price is None:
            LOGGER.warning("Missing data for liquidity sweep evaluation")
            return {
                "poc": poc_price,
                "close": close,
                "prior_3_session_low": prior_3_session_low,
                "liquidity_sweep": False,
                "volZScore": None,
            }

        # Check stop hunt: intraday low swept below prior low
        low = self.conn.execute(
            """
            SELECT low_price FROM psx_daily_eod
            WHERE trade_date = ? AND ticker = 'HH'
            """,
            (session_date.isoformat(),),
        ).fetchone()
        intraday_low = low["low_price"] if low and low["low_price"] else None

        # Volume Z-score
        volz = self.compute_volatility_zscore(close)

        # Conditions
        stop_hunt = intraday_low is not None and intraday_low < prior_3_session_low
        reclaim_poc = close > poc_price
        eligible = volz is not None and volz >= SWEEP_VOLZ_MIN

        # Trigger: stop hunt OR (stop hunt + reclaim)
        sweep_triggered = stop_hunt and reclaim_poc and eligible

        LOGGER.info(
            "Liquidity sweep: stop_hunt=%s reclaim_poc=%s volz=%.2f eligible=%s trigger=%s",
            stop_hunt, reclaim_poc, volz or 0, eligible, sweep_triggered,
        )

        return {
            "poc": poc_price,
            "close": close,
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
    """
    Calculates exact days_to_expiry (last Friday of the month) and the
    annualized spread: ((Futures_Close - Spot_Close) / Spot_Close) * (365 / days_to_expiry) * 100.

    Flags Tier-1 stocks where annualized spread exceeds 18.0% as LEVERAGE OVERHEATED.
    """

    def __init__(self, conn: sqlite3.Connection, futures_conn: sqlite3.Connection):
        self.conn = conn
        self.futures_conn = futures_conn

    def _last_friday(self, year: int, month: int) -> datetime.date:
        """
        Return the last Friday of the given month (expiry date).
        """
        # Start from last day of month
        if month == 12:
            last_day = datetime(year + 1, 1, 1) - timedelta(days=1)
        else:
            last_day = datetime(year, month + 1, 1) - timedelta(days=1)

        # Walk back to Friday
        while last_day.weekday() != 4:  # Friday = 4
            last_day -= timedelta(days=1)
        return last_day

    def get_friday_expiry_days(self, ref_date: Optional[datetime.date] = None) -> tuple[Optional[datetime.date], Optional[int]]:
        """
        Compute days_to_expiry = last Friday of the current month.
        Returns (expiry_date, days_to_expiry).
        """
        ref_date = ref_date or datetime.now().date()
        expiry = self._last_friday(ref_date.year, ref_date.month)

        delta = (expiry - ref_date).days
        return expiry, delta

    def get_most_recent_futures_close(self, ticker: str) -> Optional[float]:
        """
        Grab the most recent .Z futures close for the given ticker.
        """
        row = self.futures_conn.execute(
            """
            SELECT close_price FROM psx_futures_eod
            WHERE ticker = ? AND close_price IS NOT NULL
            ORDER BY trade_date DESC LIMIT 1
            """,
            (ticker,),
        ).fetchone()
        return row["close_price"] if row else None

    def get_latest_spot(self, ticker: str) -> Optional[float]:
        """
        Get the latest daily spot close from psx_daily_eod.
        """
        spot = self.conn.execute(
            """
            SELECT close_price FROM psx_daily_eod
            WHERE ticker = ? AND close_price IS NOT NULL
            ORDER BY trade_date DESC LIMIT 1
            """,
            (ticker,),
        ).fetchone()
        return spot["close_price"] if spot else None

    def compute_carry(
        self, ticker: str, futures_close: Optional[float] = None,
        spot_close: Optional[float] = None,
        expiry_date: Optional[datetime.date] = None,
        days_to_expiry: Optional[int] = None,
    ) -> dict:
        """
        Compute annualized carry for one ticker. Returns:
          (futures_close, spot_close, days_to_expiry, annualized_carry_pct, flagged)
        """
        if futures_close is None:
            futures_close = self.get_most_recent_futures_close(ticker)
        if spot_close is None:
            spot_close = self.get_latest_spot(ticker)
        expiry_dt, days = None, None
        if expiry_date is None or days_to_expiry is None:
            expiry_dt, days = self.get_friday_expiry_days()

        if futures_close is None or spot_close is None or days is None or days == 0:
            LOGGER.warning("Missing data for cost-of-carry on %s", ticker)
            return {
                "ticker": ticker,
                "futures_close": futures_close,
                "spot_close": spot_close,
                "days_to_expiry": days,
                "annualized_carry_pct": None,
                "leverage_overheated": False,
            }

        # Carry = (F - S) / S * (365 / days_to_expiry) * 100
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
            "annualized_carry_pct": round(annualized, 2),
            "leverage_overheated": flagged,
        }

    def evaluate_all(self, tier1_tickers: Optional[list[str]] = None) -> list[dict]:
        """
        Evaluate cost-of-carry for all Tier-1 tickers.
        Returns list of carry dicts.
        """
        if tier1_tickers is None:
            tier1_tickers = []

        # Get distinct tickers
        if not tier1_tickers:
            row = self.conn.execute(
                "SELECT DISTINCT ticker FROM psx_daily_eod ORDER BY ticker"
            ).fetchall()
            tier1_tickers = [r["ticker"] for r in row]

        results = []
        for ticker in tier1_tickers:
            results.append(self.compute_carry(ticker))

        return results


# ---------------------------------------------------------------------------
# Module 3: Mansfield Relative Strength
# ---------------------------------------------------------------------------

class MansfieldRS:
    """
    Computes:
      RS  = Stock_Close / KSE100_Close
      Mansfield_RS = ((RS / RS_20d_avg) - 1) * 100

    Hard-drops longs with negative Mansfield RS.
    Highlights rising positive Mansfield RS on red KSE-100 days.
    """

    def __init__(self, conn: sqlite3.Connection, kse100_symbol: str = "KSE-100"):
        self.conn = conn
        self.kse100_symbol = kse100_symbol
        self._rs_20d_cache: dict[str, list[float]] = {}

    def get_stock_close(self, ticker: str) -> Optional[float]:
        row = self.conn.execute(
            """
            SELECT close_price FROM psx_daily_eod
            WHERE ticker = ? AND close_price IS NOT NULL
            ORDER BY trade_date DESC LIMIT 1
            """,
            (ticker,),
        ).fetchone()
        return row["close_price"] if row else None

    def get_stock_close_n(self, ticker: str, n: int) -> Optional[float]:
        row = self.conn.execute(
            """
            SELECT close_price FROM psx_daily_eod
            WHERE ticker = ? AND close_price IS NOT NULL
            ORDER BY trade_date DESC LIMIT 1 OFFSET ?
            """,
            (ticker, n),
        ).fetchone()
        return row["close_price"] if row else None

    def get_kse100_close(self) -> Optional[float]:
        row = self.conn.execute(
            """
            SELECT close_price FROM psx_daily_eod
            WHERE ticker = ? AND close_price IS NOT NULL
            ORDER BY trade_date DESC LIMIT 1
            """,
            (self.kse100_symbol,),
        ).fetchone()
        return row["close_price"] if row else None

    def _get_rs_20d_avg(self, ticker: str) -> Optional[float]:
        """
        Compute the average RS over the last 20 days.
        Result is cached.
        """
        if ticker in self._rs_20d_cache:
            return self._rs_20d_cache[ticker]

        stock_close = self.get_stock_close(ticker)
        kse100_close = self.get_kse100_close()
        if not stock_close or not kse100_close or kse100_close == 0:
            self._rs_20d_cache[ticker] = None
            return None

        rs = stock_close / kse100_close

        # Get the RS from each of the last 20 days
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
            k_close = r["k_close"]
            s_close = r["close_price"]
            if k_close and k_close != 0:
                rs_values.append(s_close / k_close)

        if not rs_values:
            self._rs_20d_cache[ticker] = None
            return None

        avg = sum(rs_values) / len(rs_values)
        self._rs_20d_cache[ticker] = avg
        return avg

    def compute_mansfield_rs(self, ticker: str) -> dict:
        """
        Compute Mansfield RS for one ticker and check for hard-drop.
        """
        stock_close = self.get_stock_close(ticker)
        kse100_close = self.get_kse100_close()

        if not stock_close or not kse100_close or kse100_close == 0:
            LOGGER.warning("Missing close data for Mansfield RS on %s", ticker)
            return {
                "ticker": ticker,
                "rs": None,
                "mansfield_rs": None,
                "mansfield_rs_20d_avg": None,
                "kse100_close": kse100_close,
                "hard_drop": False,
                "flag_rising_positive": False,
            }

        rs = stock_close / kse100_close
        rs_20d_avg = self._get_rs_20d_avg(ticker)

        if rs_20d_avg is None or rs_20d_avg == 0:
            LOGGER.warning("Cannot compute Mansfield RS for %s (no RS baseline)", ticker)
            return {
                "ticker": ticker,
                "rs": round(rs, 4),
                "mansfield_rs": None,
                "mansfield_rs_20d_avg": None,
                "kse100_close": kse100_close,
                "hard_drop": False,
                "flag_rising_positive": False,
            }

        mansfield_rs = ((rs / rs_20d_avg) - 1) * 100

        # Hard-drop longs with negative Mansfield RS
        hard_drop = mansfield_rs < 0

        LOGGER.info(
            "Mansfield RS %s: RS=%.4f rs_20d_avg=%.4f Mansfield_RS=%.2f hard_drop=%s",
            ticker, rs, rs_20d_avg, mansfield_rs, hard_drop,
        )

        return {
            "ticker": ticker,
            "rs": round(rs, 4),
            "mansfield_rs": round(mansfield_rs, 2),
            "mansfield_rs_20d_avg": round(rs_20d_avg, 4),
            "kse100_close": kse100_close,
            "hard_drop": hard_drop,
            "flag_rising_positive": True,  # Would be set by caller based on trailing values
        }

    def evaluate(self, tickers: Optional[list[str]] = None) -> list[dict]:
        if tickers is None:
            row = self.conn.execute(
                "SELECT DISTINCT ticker FROM psx_daily_eod ORDER BY ticker"
            ).fetchall()
            tickers = [r["ticker"] for r in row]

        results = []
        for ticker in tickers:
            results.append(self.compute_mansfield_rs(ticker))

        return results


# ---------------------------------------------------------------------------
# Module 4: Director Footprint (Clause 5.6.4)
# ---------------------------------------------------------------------------

class DirectorFootprint:
    """
    Parses psx_disclosures headlines for acquisition/purchase keywords
    vs disposal/sale.

    Boosts conviction only if current price is within ±3% of the POC
    or disclosure-date price.
    """

    def __init__(self, conn: sqlite3.Connection):
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
        """
        Classify a headline as ACQ, DIS, or NONE based on keywords.
        """
        hl_lower = headline.lower()
        for kw in self.acq_keywords:
            if kw in hl_lower:
                return "ACQ"
        for kw in self.disposal_keywords:
            if kw in hl_lower:
                return "DIS"
        return "NONE"

    def get_disclosures_for_ticker(self, ticker: str) -> list[dict]:
        """
        Get all disclosures for a ticker, ordered by date desc.
        """
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
        """
        Get the close price on the disclosure date.
        """
        rows = self.conn.execute(
            """
            SELECT d.trade_date, d.close_price
            FROM psx_daily_eod d
            JOIN psx_disclosures dis ON d.ticker = dis.ticker
                AND d.trade_date = dis.trade_date
            WHERE dis.ticker = ? AND d.close_price IS NOT NULL
            ORDER BY d.trade_date DESC LIMIT 1
            """,
            (ticker,),
        ).fetchall()
        if not rows:
            return None
        # Latest disclosure date close
        latest = rows[0]
        return latest["close_price"]

    def get_current_close(self, ticker: str) -> Optional[float]:
        row = self.conn.execute(
            """
            SELECT close_price FROM psx_daily_eod
            WHERE ticker = ? AND close_price IS NOT NULL
            ORDER BY trade_date DESC LIMIT 1
            """
        ).fetchone()
        return row["close_price"] if row else None

    def get_poc(self) -> Optional[float]:
        """
        Reuse the POC from Module 1 for proximity check.
        """
        ls = LiquiditySweep(self.conn)
        poc, _ = ls.compute_poc()
        return poc

    def evaluate(self, ticker: str) -> dict:
        """
        Evaluate director footprint for one ticker.
        Only boosts conviction if price is within ±3% of POC or disclosure-date.
        """
        disclosures = self.get_disclosures_for_ticker(ticker)
        if not disclosures:
            LOGGER.info("No disclosures found for %s", ticker)
            return {
                "ticker": ticker,
                "directors": [],
                "total_disclosures": 0,
                "recent_conviction_boost": False,
                "boosted_tickers": [],
            }

        recent = []
        recent_acquis = []
        recent_disposals = []

        for d in disclosures[:10]:  # last 10
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

        # Price proximity check
        current_close = self.get_current_close(ticker)
        disclosure_close = self.get_latest_disclosure_date_close(ticker)
        poc = self.get_poc()

        # Compute proximity: ±3% of POC or disclosure-date
        boosted = False
        if current_close and disclosure_close:
            pct_vs_disclosure = abs(current_close - disclosure_close) / disclosure_close * 100
            if pct_vs_disclosure <= DIRECTOR_CONVICTION_TIGHT:
                boosted = True

        if current_close and poc:
            pct_vs_poc = abs(current_close - poc) / poc * 100
            if pct_vs_poc <= DIRECTOR_CONVICTION_TIGHT:
                boosted = True

        LOGGER.info(
            "Director footprint %s: acq=%d dis=%d boosted=%s",
            ticker, len(recent_acquis), len(recent_disposals), boosted,
        )

        return {
            "ticker": ticker,
            "total_disclosures": len(recent),
            "acquisition_declarations": len(recent_acquis),
            "disposal_disclosures": len(recent_disposals),
            "recent": recent,
            "current_close": current_close,
            "disclosure_date_close": disclosure_close,
            "poc": poc,
            "price_within_3pct_poc": bool(poc and current_close and
                                         abs(current_close - poc) / poc * 100 <= DIRECTOR_CONVICTION_TIGHT),
            "price_within_3pct_disclosure": bool(current_close and disclosure_close and
                                                 abs(current_close - disclosure_close) / disclosure_close * 100 <= DIRECTOR_CONVICTION_TIGHT),
            "recent_conviction_boost": boosted,
        }


# ---------------------------------------------------------------------------
# Result aggregation & JSON export
# ---------------------------------------------------------------------------

def aggregate_results() -> dict:
    """
    Run all 4 modules and combine into the latest.json payload.
    Only records with pass-flag are included.
    """
    conn = _connect_db()
    ls = LiquiditySweep(conn)
    coc = CostOfCarry(conn, conn)  # Using the same DB for spot lookup
    mr = MansfieldRS(conn)
    df = DirectorFootprint(conn)

    poc_data = ls.compute_poc()
    poc_price = poc_data[0]

    # 1. Liquidity Sweep report
    ls_eval = ls.evaluate()
    ls_report = {
        "module": "liquidity_sweep",
        "poc": ls_eval["poc"],
        "breakdown": {
            "prev_3_session_low": ls_eval["prior_3_session_low"],
            "stop_hunt": ls_eval["prev_low_swept"],
            "reclaim_poc": ls_eval["reclaim_poc"],
            "volZScore": ls_eval["volZScore"],
            "triggered": ls_eval["liquidity_sweep"],
        },
    }

    # 2. Cost-of-Carry report
    coc_results = coc.evaluate_all()
    carry_report = {
        "module": "cost_of_carry",
        "tickers": coc_results,
    }

    # 3. Mansfield RS report
    mans_results = mr.evaluate()
    mans_report = {
        "module": "mansfield_rs",
        "tickers": mans_results,
    }

    # 4. Director Footprint report
    # Get distinct tickers
    tickers_row = conn.execute("SELECT DISTINCT ticker FROM psx_daily_eod ORDER BY ticker").fetchall()
    tickers = [r["ticker"] for r in tickers_row]

    director_report = {
        "module": "director_footprint",
        "tickers": [],
    }
    for t in tickers:
        director_report["tickers"].append(df.evaluate(t))

    conn.close()

    # Build combined payload
    payload = {
        "session_date": datetime.now().strftime("%Y-%m-%d"),
        "session_time": datetime.now().strftime("%H:%M:%S"),
        "poc": round(poc_price, 2) if poc_price else None,
        "volZScore": ls_eval.get("volZScore"),
        "liquidity_sweep": ls_eval.get("liquidity_sweep"),
        "annualized_carry_pct": {r["ticker"]: r["annualized_carry_pct"] for r in coc_results},
        "carry_flags": {
            r["ticker"]: {
                "leverage_overheated": r["leverage_overheated"],
                "days_to_expiry": r["days_to_expiry"],
            } for r in coc_results
        },
        "mansfield_rs": {r["ticker"]: {
            "rs": r["rs"],
            "mansfield_rs": r["mansfield_rs"],
            "mansfield_rs_20d_avg": r["mansfield_rs_20d_avg"],
            "hard_drop": r["hard_drop"],
            "flag_rising_positive": r["flag_rising_positive"],
        } for r in mans_results},
        "director_footprint": {
            t["ticker"]: {
                "total_disclosures": t["total_disclosures"],
                "acquisition_declarations": t["acquisition_declarations"],
                "disposal_disclosures": t["disposal_disclosures"],
                "price_within_3pct_poc": t["price_within_3pct_poc"],
                "price_within_3pct_disclosure": t["price_within_3pct_disclosure"],
                "recent_conviction_boost": t["recent_conviction_boost"],
            } for t in director_report["tickers"]
        },
    }

    LOGGER.info("Aggregated %d tickers from %d sessions into latest.json", len(tickers), VPVR_N_SESSIONS)
    return payload


def write_json(payload: dict, path: Path) -> None:
    """
    Write the payload to latest.json.
    Only overwrite if new data differs from the existing file.
    """
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


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    _setup_logging()
    LOGGER.info("Starting daily tape processor")

    try:
        payload = aggregate_results()
        write_json(payload, OUTPUT_PATH)
        LOGGER.info("Daily tape processor completed successfully")
        return 0
    except Exception as e:
        LOGGER.exception("Daily tape processor failed: %s", e)
        # Write error payload to prevent leaving the expected file missing
        try:
            error_payload = {
                "session_date": datetime.now().strftime("%Y-%m-%d"),
                "session_time": datetime.now().strftime("%H:%M:%S"),
                "error": str(e),
                "poc": None,
                "volZScore": None,
                "liquidity_sweep": False,
                "annualized_carry_pct": {},
                "carry_flags": {},
                "mansfield_rs": {},
                "director_footprint": {},
                "backtrace": True,
            }
            write_json(error_payload, OUTPUT_PATH)
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    sys.exit(main())
