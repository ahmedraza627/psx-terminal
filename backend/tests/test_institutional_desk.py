"""Tests for the institutional event / flow desk helpers."""
from __future__ import annotations

import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND / "scripts"))

from quant_modules import (calc_catalyst, calc_flow_streak,  # noqa: E402
                           calc_institutional_flows, calc_lor_spread, calc_quiet_absorption)


def bar(close: float, volume: float):
    return SimpleNamespace(close_price=close, volume=volume)


def tape(closes: list[float], volumes: list[float]):
    return [bar(c, v) for c, v in zip(closes, volumes)]


def flow_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE nccpl_flows (trade_date TEXT, participant_type TEXT, sector_name TEXT, "
                 "buy_pkr REAL, sell_pkr REAL, net_pkr REAL)")
    return conn


def test_catalyst_tags_are_specific_and_ignore_noise():
    assert calc_catalyst("Public announcement of intention to acquire shares")["catalyst"] == "PUBLIC INTENTION"
    assert calc_catalyst("Sale of land - non-core assets")["catalyst"] == "NON-CORE ASSET SALE"
    assert calc_catalyst("Scheme of Arrangement under sections 279-283")["catalyst"] == "SCHEME OF ARRANGEMENT"
    assert calc_catalyst("Board meeting to consider right issue")["catalyst"] == "RIGHT ISSUE"
    assert calc_catalyst("Disclosure of Interest by a Director")["catalyst"] is None


def test_quiet_absorption_needs_flat_or_discounted_tape_on_light_volume():
    flat = tape([100.0 + (i % 3) for i in range(28)], [10_000] * 27 + [5_000])
    assert calc_quiet_absorption(flat)["absorption"] is True

    discounted = tape([120.0 - i * 0.8 for i in range(28)], [10_000] * 27 + [6_000])
    result = calc_quiet_absorption(discounted)
    assert result["discounted"] is True and result["absorption"] is True

    running = tape([100.0 * (1.02 ** i) for i in range(28)], [10_000] * 28)
    assert calc_quiet_absorption(running)["absorption"] is False


def test_lor_spread_flags_rich_and_cheap_entitlements():
    rich = calc_lor_spread(close=110.0, terp=100.0)
    assert rich["lorTrap"] is True and rich["lorPremiumPct"] == 10.0
    cheap = calc_lor_spread(close=90.0, terp=100.0)
    assert cheap["lorCheap"] is True and cheap["lorTrap"] is False


def test_institutional_flows_split_smart_money_from_retail():
    conn = flow_db()
    for i in range(10):
        day = (date(2026, 11, 10) + timedelta(days=i)).isoformat()
        conn.executemany("INSERT INTO nccpl_flows VALUES (?,?,?,?,?,?)",
                         [(day, "FIPI", "CEMENT", None, None, 10_000_000.0),
                          (day, "MUTUAL FUNDS", "CEMENT", None, None, 5_000_000.0),
                          (day, "INSURANCE", "CEMENT", None, None, -1_000_000.0),
                          (day, "INDIVIDUALS", "CEMENT", None, None, -9_000_000.0)])
    conn.commit()
    flow = calc_institutional_flows(conn.cursor(), "CEMENT", date(2026, 11, 20))
    assert flow["sessions"] == 10
    assert flow["institutionalNetPkr"] == 140_000_000.0
    assert flow["retailNetPkr"] == -90_000_000.0


def test_flow_streak_counts_consecutive_net_sell_sessions():
    conn = flow_db()
    days = [date(2026, 11, 16) + timedelta(days=i) for i in range(5)]
    nets = [-5.0, -4.0, -3.0, 2.0, -1.0]  # newest first: -1, +2 -> streak stops at 1
    for day, net in zip(days, nets):
        conn.execute("INSERT INTO nccpl_flows VALUES (?,?,?,?,?,?)",
                     (day.isoformat(), "MUTUAL FUNDS", "CEMENT", None, None, net * 1_000_000))
    conn.commit()
    assert calc_flow_streak(conn.cursor(), "CEMENT", days[-1])["streak"] == 1

    conn.execute("DELETE FROM nccpl_flows")
    for day in days[2:]:
        conn.execute("INSERT INTO nccpl_flows VALUES (?,?,?,?,?,?)",
                     (day.isoformat(), "INSURANCE", "CEMENT", None, None, -2_000_000))
    conn.commit()
    assert calc_flow_streak(conn.cursor(), "CEMENT", days[-1])["streak"] == 3
