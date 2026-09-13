"""HTTP session shared by all scrapers.

Remote sources verified live on 2026-09-10:
- dps.psx.com.pk/market-watch            server-rendered snapshot of every ticker
- dps.psx.com.pk/historical (POST)       per-symbol monthly OHLCV tables
- dps.psx.com.pk/timeseries/eod/<SYM>    JSON rows [ts, close, volume, ldcp]
- dps.psx.com.pk/trading-board/NDM/NDM   negotiated (off-market) deals board
- dps.psx.com.pk/payouts (POST)          dividend/payout announcements
- dps.psx.com.pk/screener                fundamentals (sector, PE, yield, cap)
- dps.psx.com.pk/sector-summary/sectorwise sector tables
- scstrade.com/FIPILIPI.aspx (POST JSON) NCCPL FIPI/LIPI participant flows
- open.er-api.com/v6/latest/USD          free USD/PKR FX rate
"""

from __future__ import annotations

import logging
import random
import time
from typing import Any, Optional

import requests

LOGGER = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

DEFAULT_TIMEOUT = 30.0
MAX_RETRIES = 3
BACKOFF_BASE = 1.5


def _build_session() -> requests.Session:
    """Create a session with realistic browser headers on every request."""
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,*/*;q=0.8"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }
    )
    return session


SESSION: requests.Session = _build_session()


def _sleep_backoff(attempt: int) -> None:
    """Exponential backoff with jitter so cron runs never hammer the sites."""
    delay = BACKOFF_BASE ** attempt + random.uniform(0.0, 0.75)
    time.sleep(min(delay, 12.0))


def http_get(
    url: str,
    *,
    headers: Optional[dict[str, str]] = None,
    timeout: float = DEFAULT_TIMEOUT,
    params: Optional[dict[str, Any]] = None,
) -> requests.Response:
    """GET with retries/backoff. Raises for status after the final attempt."""
    last_exc: Optional[Exception] = None
    for attempt in range(MAX_RETRIES):
        try:
            response = SESSION.get(
                url, headers=headers, timeout=timeout, params=params
            )
            if response.status_code in (429, 500, 502, 503, 504):
                raise requests.HTTPError(
                    f"{response.status_code} from {url}", response=response
                )
            response.raise_for_status()
            return response
        except (requests.RequestException, requests.HTTPError) as exc:
            last_exc = exc
            LOGGER.warning(
                "GET %s failed (attempt %d/%d): %s",
                url,
                attempt + 1,
                MAX_RETRIES,
                exc,
            )
            if attempt < MAX_RETRIES - 1:
                _sleep_backoff(attempt)
    assert last_exc is not None
    raise last_exc


def http_post(
    url: str,
    *,
    data: Any = None,
    json_body: Any = None,
    headers: Optional[dict[str, str]] = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> requests.Response:
    """POST with retries/backoff. Raises for status after the final attempt."""
    last_exc: Optional[Exception] = None
    for attempt in range(MAX_RETRIES):
        try:
            response = SESSION.post(
                url,
                data=data,
                json=json_body,
                headers=headers,
                timeout=timeout,
            )
            if response.status_code in (429, 500, 502, 503, 504):
                raise requests.HTTPError(
                    f"{response.status_code} from {url}", response=response
                )
            response.raise_for_status()
            return response
        except (requests.RequestException, requests.HTTPError) as exc:
            last_exc = exc
            LOGGER.warning(
                "POST %s failed (attempt %d/%d): %s",
                url,
                attempt + 1,
                MAX_RETRIES,
                exc,
            )
            if attempt < MAX_RETRIES - 1:
                _sleep_backoff(attempt)
    assert last_exc is not None
    raise last_exc


def ajax_headers(referer: str) -> dict[str, str]:
    """Headers that look like the site's own jQuery AJAX calls."""
    return {
        "Referer": referer,
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "text/html, */*; q=0.01",
    }


def json_headers(referer: str) -> dict[str, str]:
    """Headers for JSON-body POST endpoints (scstrade FIPI/LIPI API)."""
    return {
        "Referer": referer,
        "Content-Type": "application/json",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
    }
