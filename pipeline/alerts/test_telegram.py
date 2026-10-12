"""Dry-run the Telegram dispatch (Phase 4 verification).

Loads .env exactly like the pipeline, sends ONE synthetic execution-desk
brief through send_daily_dispatch(), and reports delivery. Exit code 0
only when Telegram accepted the message.

Run:  python -m pipeline.alerts.test_telegram
"""

from __future__ import annotations

import logging
import sys
from datetime import date

from dotenv import load_dotenv

from pipeline.alerts.telegram import send_daily_dispatch

SAMPLE_VERDICTS = [
    {
        "horizon": "SHORT_TERM",
        "direction": "BUY",
        "ticker": "SYS",
        "logic_text": (
            "Institutional pullback into 20D SMA support with volume "
            "dry-up (-42% vs 20D avg) in confirmed uptrend."
        ),
        "macro_tape_state": "NEUTRAL",
        "entry_ref": 116.0,
        "stop_loss": 112.4,
        "target_price": 124.5,
        "risk_reward_ratio": 1.5,
        "suggested_alloc_pct": 15.0,
        "historical_win_rate": 71.2,
    },
    {
        "horizon": "MID_TERM",
        "direction": "BUY",
        "ticker": "AIRLINK",
        "logic_text": (
            "Sustained institutional net absorption across 5 sessions "
            "while retail distributed."
        ),
        "macro_tape_state": "NEUTRAL",
        "entry_ref": 117.99,
        "stop_loss": 112.09,
        "target_price": 126.84,
        "risk_reward_ratio": 1.5,
        "suggested_alloc_pct": None,
        "historical_win_rate": 45.0,
    },
    {
        "horizon": "LONG_TERM",
        "direction": "AVOID",
        "ticker": "DGKC",
        "logic_text": (
            "Retail trap active: institutions net distributing into "
            "retail liquidity."
        ),
        "macro_tape_state": "NEUTRAL",
    },
]


def main() -> int:
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    sent = send_daily_dispatch(date.today(), SAMPLE_VERDICTS, "NEUTRAL")
    if sent:
        print("OK: dry-run dispatch delivered to Telegram.")
        return 0
    print(
        "FAIL: dispatch not delivered - check TELEGRAM_BOT_TOKEN / "
        "TELEGRAM_CHAT_ID in .env and the warning above."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
