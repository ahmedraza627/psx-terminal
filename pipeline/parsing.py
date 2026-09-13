"""Text and number parsing helpers shared by the scrapers.

PSX pages render numbers like "1,234.50", "(45.20)" for negatives and
sometimes leave cells blank. Everything here is defensive: malformed input
becomes None rather than an exception.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import Iterable, Optional

LOGGER = logging.getLogger(__name__)

_NUMBER_RE = re.compile(r"-?\d[\d,]*\.?\d*")
_WS_RE = re.compile(r"\s+")


def clean_text(value: object) -> str:
    """Collapse whitespace and strip HTML entities/indentation noise."""
    if value is None:
        return ""
    text = str(value)
    text = text.replace("\xa0", " ")
    return _WS_RE.sub(" ", text).strip()


def to_number(value: object) -> Optional[float]:
    """Parse "12,345.67", "(45.20)", "-3.1%" etc. -> float or None."""
    text = clean_text(value)
    if not text or text in {"-", "--", "N/A", "n/a", "NA"}:
        return None
    negative_paren = text.startswith("(") and text.endswith(")")
    match = _NUMBER_RE.search(text)
    if not match:
        return None
    try:
        number = float(match.group(0).replace(",", ""))
    except ValueError:
        return None
    if negative_paren:
        number = -abs(number)
    return number


def to_int(value: object) -> Optional[int]:
    """Parse "99,405,516" -> int or None."""
    number = to_number(value)
    if number is None:
        return None
    try:
        return int(round(number))
    except (ValueError, OverflowError):
        return None


def to_date(value: object, *, year: Optional[int] = None) -> Optional[date]:
    """Parse the date formats found on PSX/scstrade pages.

    Handles: "2026-09-09", "Sep 09, 2026", "September 9, 2026",
    "09/09/2026", "09-09-2026".
    """
    text = clean_text(value)
    if not text:
        return None
    fmts = (
        "%Y-%m-%d",
        "%b %d, %Y",
        "%B %d, %Y",
        "%d/%m/%Y",
        "%m/%d/%Y",
        "%d-%m-%Y",
        "%d %b %Y",
        "%d %B %Y",
    )
    for fmt in fmts:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    # Month/year selectors from the DPS historical table ("8", "2026")
    if year is not None:
        try:
            month = int(text)
            return date(int(year), month, 1)
        except (ValueError, TypeError):
            return None
    return None


def utc_ts_to_date(ts: object) -> Optional[date]:
    """DPS timeseries rows start with a unix epoch (seconds)."""
    try:
        seconds = int(float(ts))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return datetime.utcfromtimestamp(seconds).date()


def parse_decimal_comma_safe(cell_text: str) -> Optional[float]:
    """Last-resort parser for cells like '1.234,56' (comma decimals)."""
    text = clean_text(cell_text)
    if not text:
        return None
    swapped = text.replace(".", "").replace(",", ".")
    try:
        return float(_NUMBER_RE.search(swapped).group(0).replace(",", ""))  # type: ignore[union-attr]
    except (ValueError, AttributeError):
        return None


def chunked(records: list, size: int) -> Iterable[list]:
    """Yield successive size-chunks from records."""
    for start in range(0, len(records), size):
        yield records[start : start + size]
