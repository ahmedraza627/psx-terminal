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

STATUS UPDATE (probed live 2026-10-01): every dps.psx.com.pk data route
above returns 403 with an EMPTY body to this runner's IP class (edge WAF
- not header- or TLS-fingerprint-fixable), while DPS content pages still
serve 200. Optional ScraperAPI egress covers exactly these gated targets:
set SCRAPER_API_KEY and route through http_get_via_scraperapi() so the
request exits from ScraperAPI's IP pool instead of the runner's.
"""

from __future__ import annotations

import logging
import os
import random
import time
from typing import Any, Optional
from urllib.parse import quote

import requests

LOGGER = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

DEFAULT_TIMEOUT = 30.0
MAX_RETRIES = 3
BACKOFF_BASE = 1.5

# ScraperAPI egress (optional, env SCRAPER_API_KEY): single-attempt proxied
# GETs for WAF-gated targets. 60s because the proxy fetches the target
# server-side; retrying here would burn ScraperAPI credits.
SCRAPERAPI_ENDPOINT = "http://api.scraperapi.com"
SCRAPERAPI_TIMEOUT = 60.0


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


# ---------------------------------------------------------------------------
# ScraperAPI proxy egress (optional)
# ---------------------------------------------------------------------------


def scraperapi_key() -> str:
    """Configured ScraperAPI key ('' when unset) from env SCRAPER_API_KEY."""
    return os.getenv("SCRAPER_API_KEY", "").strip()


def scraperapi_proxied_url(target_url: str, key: Optional[str] = None) -> str:
    """Wrap a target URL for ScraperAPI egress.

    http://api.scraperapi.com?api_key={KEY}&url={url-encoded target}
    Both params are percent-encoded (the target carries its own query
    string); the key must never appear in logs or raised exceptions.
    """
    resolved = (key if key is not None else scraperapi_key()).strip()
    if not resolved:
        raise ValueError(
            "ScraperAPI egress requested but SCRAPER_API_KEY is not set"
        )
    return (
        f"{SCRAPERAPI_ENDPOINT}?api_key={quote(resolved, safe='')}"
        f"&url={quote(target_url, safe='')}"
    )


def http_get_via_scraperapi(
    target_url: str, *, timeout: float = SCRAPERAPI_TIMEOUT
) -> requests.Response:
    """Single-attempt GET through ScraperAPI egress (requires SCRAPER_API_KEY).

    Deliberately NOT raise_for_status and NOT retried: callers classify the
    target-side status themselves (403-empty WAF block vs retired-route 404
    vs a healthy board), and every retry would burn ScraperAPI credits.
    Transport failures raise a sanitized RequestException - the api_key is
    part of the request URL, so raw exception strings must never surface it.
    """
    proxied_url = scraperapi_proxied_url(target_url)
    try:
        response = SESSION.get(proxied_url, timeout=timeout)
    except requests.RequestException as exc:
        raise requests.RequestException(
            f"ScraperAPI egress failed for {target_url}: "
            f"{type(exc).__name__} (transport detail suppressed: carries api_key)"
        ) from None
    LOGGER.info(
        "ScraperAPI egress %s -> HTTP %d (%d bytes)",
        target_url,
        response.status_code,
        len(response.content),
    )
    return response


def http_post_via_scraperapi(
    target_url: str,
    *,
    data: Any = None,
    json_body: Any = None,
    timeout: float = SCRAPERAPI_TIMEOUT,
) -> requests.Response:
    """Single-attempt POST through ScraperAPI egress (requires SCRAPER_API_KEY).

    ScraperAPI forwards the HTTP method and body to the target. Same
    discipline as http_get_via_scraperapi: no retries (each burns credits),
    no raise_for_status (callers classify the target-side status), and
    sanitized transport errors (the api_key is part of the request URL and
    must never leak into exception strings).
    """
    proxied_url = scraperapi_proxied_url(target_url)
    try:
        response = SESSION.post(
            proxied_url, data=data, json=json_body, timeout=timeout
        )
    except requests.RequestException as exc:
        raise requests.RequestException(
            f"ScraperAPI egress failed for {target_url}: "
            f"{type(exc).__name__} (transport detail suppressed: carries api_key)"
        ) from None
    LOGGER.info(
        "ScraperAPI POST %s -> HTTP %d (%d bytes)",
        target_url,
        response.status_code,
        len(response.content),
    )
    return response
