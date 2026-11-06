"""Pipeline dispatch and execution layer.

Responsibilities
----------------
- Route reconciliation and signal processing to the appropriate handlers.
- Format DFC (Dynamic Fence Circuit) stop-loss sentinel values into human-readable form.
- Manage per-session bookkeeping so the aging guard in ``portfolio/ledger.py``
  stays consistent.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DFC Stop-Loss Sentinel formatting
# ---------------------------------------------------------------------------

# The internal sentinel used when a stop-loss is not applicable (e.g. the
# hedge is already in place).  Previously this was printed raw as ``1.00``,
# which is uninformative.  Now it is formatted as a descriptive pill.
_DFC_SENTINEL_INTERNAL = 1.00

# Human-readable format strings keyed by sentinel kind.
_DFC_FORMATTERS = {
    "open_hedged": "SL: OPEN (SPREAD_HEDGED)",
    "flat": "FLAT",
    "none": "-",
}


def format_dfc_sl(value: Any, kind: str = "open_hedged") -> str:
    """Format a DFC stop-loss value for display.

    Parameters
    ----------
    value: the raw sentinel or stop-loss price.
    kind: formatting variant — one of ``"open_hedged"``, ``"flat"``, ``"none"``.

    Returns
    -------
    str
        A display-friendly stop-loss string.
    """
    if value is None:
        return _DFC_FORMATTERS["none"]

    # If the value is the numeric sentinel 1.00, render the descriptive pill.
    try:
        fval = float(value)
    except (TypeError, ValueError):
        pass
    else:
        if fval == _DFC_SENTINEL_INTERNAL and kind == "open_hedged":
            return _DFC_FORMATTERS["open_hedged"]

    # Default: render as a price with two decimal places.
    try:
        return f"SL: {float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


# ---------------------------------------------------------------------------
# Dispatch helpers (placeholders for the wider pipeline integration)
# ---------------------------------------------------------------------------

def dispatch_reconcile(session_date: str, positions: Optional[list[dict[str, Any]]] = None) -> dict[str, Any]:
    """Run the reconciliation dispatch for one session.

    This is a placeholder that integrates with the ``PortfolioLedger`` aging
    guard.  In the full pipeline it would:
      1. Persist EOD data.
      2. Increment ``bars_held`` via the ledger's idempotent guard.
      3. Format any DFC stop-loss values for the dashboard.

    Parameters
    ----------
    session_date: ISO-format date string (``YYYY-MM-DD``).
    positions: optional list of position dicts keyed by ticker, entry, stop, etc.

    Returns
    -------
    dict with keys ``session_date``, ``bars_incremented``, ``dfc_sl``.
    """
    from portfolio.ledger import PortfolioLedger

    ledger = PortfolioLedger()
    try:
        # Normalise to a date object for the aging guard
        target = __import__("datetime").date.fromisoformat(session_date)
    except ValueError:
        LOGGER.error("Invalid session_date format: %s", session_date)
        return {"session_date": session_date, "bars_incremented": 0, "dfc_sl": "-"}

    # Default tickers when none supplied (in a real run these come from the book)
    tickers = [pos.get("ticker", "UNKNOWN") for pos in (positions or [])]

    result = ledger.reconcile(target, tickers)

    # Format the DFC stop-loss for this session
    # The internal sentinel 1.00 becomes the descriptive pill
    dfc_sl = format_dfc_sl(_DFC_SENTINEL_INTERNAL, kind="open_hedged")

    return {
        "session_date": session_date,
        "bars_incremented": result["advanced"],
        "skipped": result["skipped"],
        "dfc_sl": dfc_sl,
    }


# ---------------------------------------------------------------------------
# Module-level test guard
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Quick smoke test when run directly
    import sys

    # Test the formatter
    print("format_dfc_sl(1.00):", format_dfc_sl(1.00))
    print("format_dfc_sl(None):", format_dfc_sl(None))
    print("format_dfc_sl(0.85):", format_dfc_sl(0.85))

    # Test dispatch_reconcile with no positions
    out = dispatch_reconcile("2026-11-04", [{"ticker": "TEST", "entry": 100.0, "stop": 95.0}])
    print("dispatch_reconcile output:", out)
    sys.exit(0)