"""live_fetcher.py - pulls the live PSX end-of-day tape straight from the exchange.

Primary source is the official DPS market-summary tape (a .Z/zip of pipe-delimited
rows); the per-symbol EOD endpoint is used as a fallback for a handful of tickers
when the summary file for the session is not published yet.
"""
from __future__ import annotations

import gzip
import io
import zipfile
import zlib
from datetime import date, timedelta
from pathlib import Path
from typing import Optional, Tuple

import requests
from pydantic import ValidationError

from src.core.models import DailyBar

TAPE_URL = "https://dps.psx.com.pk/download/mkt_summary/{}.Z"
SYMBOL_EOD_URL = "https://dps.psx.com.pk/timeseries/eod/{}"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0.0.0 Safari/537.36"
}


class LiveEODFetcher:
    """Fetches real session data; nothing here reads a cached or hardcoded price."""

    def __init__(self, timeout: int = 45, cache_dir: Optional[Path] = None):
        self.timeout = timeout
        self.cache_dir = Path(cache_dir) if cache_dir else None

    def latest_session(self, start: Optional[date] = None,
                       lookback: int = 8) -> Tuple[Optional[date], list[DailyBar], str]:
        """Walks back from today until a session with published tape is found."""
        day = start or date.today()
        for back in range(lookback):
            candidate = day - timedelta(days=back)
            if candidate.weekday() >= 5:  # PSX trades Monday-Friday
                continue
            try:
                bars = self.fetch_session(candidate)
            except requests.RequestException:
                continue
            if bars:
                return candidate, bars, "market_summary_tape"
        return None, [], "unavailable"

    def fetch_session(self, day: date) -> list[DailyBar]:
        raw = self._download(day)
        if raw is None:
            return []
        return self.parse_tape(raw, day)

    def _download(self, day: date) -> Optional[bytes]:
        cached = self.cache_dir / f"{day.isoformat()}.Z" if self.cache_dir else None
        if cached and cached.is_file():
            return cached.read_bytes()
        response = requests.get(TAPE_URL.format(day.isoformat()), headers=HEADERS, timeout=self.timeout)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        if cached:
            cached.parent.mkdir(parents=True, exist_ok=True)
            cached.write_bytes(response.content)
        return response.content

    @staticmethod
    def _decode(raw: bytes) -> str:
        if zipfile.is_zipfile(io.BytesIO(raw)):
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                return "".join(archive.read(name).decode("utf-8", "replace") for name in archive.namelist())
        if raw[:2] == b"\x1f\x8b":
            return gzip.decompress(raw).decode("utf-8", "replace")
        if raw[:1] == b"\x1f":
            return zlib.decompress(raw, -15).decode("utf-8", "replace")
        return raw.decode("utf-8", "replace")

    def parse_tape(self, raw: bytes, day: date) -> list[DailyBar]:
        """Rows arrive as date|ticker|time|name|open|high|low|close|volume|prev_close."""
        bars: list[DailyBar] = []
        for line in self._decode(raw).splitlines():
            parts = line.split("|")
            if len(parts) < 9:
                continue
            ticker = parts[1].strip().upper()
            if not ticker or "-" in ticker or any(ch.isdigit() for ch in ticker):
                continue  # futures contracts, bonds and index rows are not equities
            try:
                bars.append(DailyBar(
                    ticker=ticker,
                    trade_date=day,
                    open_price=round(float(parts[4]), 2),
                    high_price=float(parts[5]),
                    low_price=float(parts[6]),
                    close_price=round(float(parts[7]), 2),
                    volume=int(float(parts[8] or 0)),
                ))
            except (ValueError, IndexError, ValidationError):
                continue  # malformed OHLC row is skipped, not guessed
        return bars

    def symbol_bar(self, ticker: str, day: date) -> Optional[DailyBar]:
        """Fallback: the per-symbol EOD series endpoint."""
        try:
            response = requests.get(SYMBOL_EOD_URL.format(ticker), headers=HEADERS, timeout=12)
            bars = (response.json() or {}).get("data") or []
        except (requests.RequestException, ValueError):
            return None
        if not bars:
            return None
        try:
            return DailyBar(ticker=ticker, trade_date=day, open_price=float(bars[-1][3]),
                            high_price=float(bars[-1][4]), low_price=float(bars[-1][5]),
                            close_price=float(bars[-1][1]), volume=int(float(bars[-1][2])))
        except (IndexError, TypeError, ValueError, ValidationError):
            return None
