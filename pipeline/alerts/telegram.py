"""Telegram dispatch - the execution desk's out-of-band daily brief.

Sends the certified session verdicts to a Telegram chat as a clean,
monospace, institutional one-pager (HTML <pre> block, values to two
decimals, honest em-dashes for missing levels).

Delivery is strictly BEST-EFFORT:
  * Missing TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID -> warning + False.
  * Transport / API errors -> warning + False.
The pipeline's verdicts are already stored by the time dispatch runs, so
a chat failure must never fail a pipeline run.
"""

from __future__ import annotations

import html
import logging
import os
from datetime import date
from typing import Any, Iterable, Optional

import requests

LOGGER = logging.getLogger(__name__)

TELEGRAM_SEND_MESSAGE_URL = "https://api.telegram.org/bot{token}/sendMessage"
TELEGRAM_TIMEOUT = 15.0
# Telegram hard limit is 4096 characters; leave headroom for <pre> tags.
TELEGRAM_MAX_TEXT = 4000

HORIZON_LABELS = {
    "SHORT_TERM": "[1] SHORT-TERM (1-5D)",
    "MID_TERM": "[2] MID-TERM (2-8W)",
    "LONG_TERM": "[3] RISK RADAR (AVOID)",
}


def _sector_line(verdict: dict[str, Any]) -> str:
    """Sector tag for the brief: Sector: <NAME> [<STATUS> #<rank>]."""
    sector_name = verdict.get("sector_name")
    status = verdict.get("sector_status")
    rank = verdict.get("sector_rank")
    if not sector_name:
        return ""
    rank_txt = f" #{rank}" if rank is not None else ""
    status_txt = f"[{status}{rank_txt}]" if status else ""
    return f"Sector: {_text(sector_name)} {status_txt}".strip()


DASH = "\u2014"


def _credentials() -> tuple[str, str]:
    """(token, chat_id) from the environment - either may be empty."""
    return (
        os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
        os.getenv("TELEGRAM_CHAT_ID", "").strip(),
    )


def _num(value: Any, digits: int = 2) -> str:
    """Fixed-decimal number, honest em-dash for missing values."""
    if value is None:
        return DASH
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return DASH


def _text(value: Any) -> str:
    return str(value) if value not in (None, "") else DASH


def _by_horizon(verdicts: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(v.get("horizon") or ""): v for v in verdicts or []}


def build_dispatch_message(
    trade_date: Any, verdicts: Iterable[dict[str, Any]], tape_state: str
) -> str:
    """The exact plain-text brief - exported so tests can print it."""
    by_horizon = _by_horizon(verdicts)
    session = (
        trade_date.isoformat() if isinstance(trade_date, date) else str(trade_date)
    )
    lines = [
        "\U0001F3DB PSX TERMINAL \u2014 EXECUTION DESK",
        f"Session: {session} | Tape: {tape_state or 'UNKNOWN'}",
        "-" * 38,
    ]

    short = by_horizon.get("SHORT_TERM")
    lines.append(HORIZON_LABELS["SHORT_TERM"])
    if short:
        lines.append(f"Status: {short.get('direction') or 'CASH / NO SETUP'}")
        lines.append(f"Ticker: {_text(short.get('ticker'))}")
        sl = _sector_line(short)
        if sl:
            lines.append(sl)
        lines.append(f"Note: {_text(short.get('logic_text'))}")
    else:
        lines.append("Status: CASH / NO SETUP")
        lines.append("Note: No qualifying setup; capital preserved in cash.")
    lines.append("")

    mid = by_horizon.get("MID_TERM")
    lines.append(HORIZON_LABELS["MID_TERM"])
    if mid:
        lines.append(
            f"Status: {mid.get('direction') or 'CASH / NO SETUP'}"
            f" | Ticker: {_text(mid.get('ticker'))}"
        )
        sl = _sector_line(mid)
        if sl:
            lines.append(sl)
        lines.append(f"\u2022 Entry Ref: PKR {_num(mid.get('entry_ref'))}")
        lines.append(f"\u2022 Invalidation: PKR {_num(mid.get('stop_loss'))}")
        lines.append(f"\u2022 TP1 Target: PKR {_num(mid.get('target_price'))}")
        lines.append(f"\u2022 Reward : Risk: {_num(mid.get('risk_reward_ratio'))}")
        lines.append(
            f"\u2022 Max Alloc: {_num(mid.get('suggested_alloc_pct'), 1)}%"
            f" | Edge: {_num(mid.get('historical_win_rate'), 0)}%"
        )
        action = (
            "Locked"
            if mid.get("macro_tape_state") == "DEFENSIVE_CASH"
            else "Active Execution"
        )
        lines.append(f"\u2022 Action: {action}")
    else:
        lines.append("Status: CASH / NO SETUP")
    lines.append("")

    risk = by_horizon.get("LONG_TERM")
    lines.append(HORIZON_LABELS["LONG_TERM"])
    if risk:
        lines.append(f"Ticker: {_text(risk.get('ticker'))}")
        lines.append(f"Note: {_text(risk.get('logic_text'))}")
    else:
        lines.append("Note: No active risk radar this session.")

    lines += ["-" * 38, "Certified EOD & NCCPL Pipeline"]
    return "\n".join(lines)


def send_daily_dispatch(
    trade_date: Any,
    verdicts: Iterable[dict[str, Any]],
    tape_state: Optional[str],
) -> bool:
    """Send the session brief to Telegram. Never raises.

    Returns True only when Telegram accepted the message. Missing
    credentials or transport/API failures log a warning and return False
    so the pipeline continues regardless of chat availability.
    """
    token, chat_id = _credentials()
    if not token or not chat_id:
        LOGGER.warning(
            "telegram dispatch skipped: TELEGRAM_BOT_TOKEN / "
            "TELEGRAM_CHAT_ID not set"
        )
        return False

    text = build_dispatch_message(trade_date, verdicts, tape_state)
    payload = {
        "chat_id": chat_id,
        # Escaped <pre> keeps the brief monospace and injection-proof.
        "text": f"<pre>{html.escape(text[:TELEGRAM_MAX_TEXT])}</pre>",
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    url = TELEGRAM_SEND_MESSAGE_URL.format(token=token)
    try:
        response = requests.post(url, json=payload, timeout=TELEGRAM_TIMEOUT)
        response.raise_for_status()
    except requests.RequestException as exc:
        # The token is part of the URL - never log the URL or its detail.
        LOGGER.warning(
            "telegram dispatch failed (%s): %s",
            type(exc).__name__,
            getattr(exc, "response", None).status_code
            if getattr(exc, "response", None) is not None
            else exc,
        )
        return False
    LOGGER.info(
        "telegram dispatch delivered for session %s (tape=%s)",
        trade_date,
        tape_state,
    )
    return True
