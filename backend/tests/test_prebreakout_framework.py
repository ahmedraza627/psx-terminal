"""Tests for the six-layer pre-breakout framework primitives."""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND / "scripts"))

from institutional_desk import _stat, build_desk, load_seasonality  # noqa: E402
from process_daily_tape import reconcile_traps  # noqa: E402
from quant_modules import (CONFLUENCE_LAYERS, calc_confluence_score, calc_float_turnover,  # noqa: E402
                           calc_pocket_pivot, calc_time_stop, calc_volume_dryup)
from v5_ledger import log_signals  # noqa: E402


def bar(close: float, volume: float):
    return SimpleNamespace(close_price=close, volume=volume)


def tape(closes: list[float], volumes: list[float]):
    return [bar(c, v) for c, v in zip(closes, volumes)]


def flat_tape(sessions: int = 60, volume: float = 100_000, close: float = 100.0):
    return tape([close] * sessions, [volume] * sessions)


def test_dry_up_band_is_twenty_to_thirty_percent_of_the_fifty_day_average():
    bars = flat_tape(60, volume=100_000)
    for i in range(55, 60):
        bars[i] = bar(100.0, 25_000)  # 25% of the 50d average
    result = calc_volume_dryup(bars)
    assert result["dryUp"] is True
    assert 0.20 <= result["dryUpRatio"] <= 0.30

    outside = flat_tape(60, volume=100_000)
    for i in range(55, 60):
        outside[i] = bar(100.0, 5_000)  # 5%: dead tape, below the band
    assert calc_volume_dryup(outside)["dryUp"] is False
    assert calc_volume_dryup(outside)["contracting"] is True


def test_pocket_pivot_needs_an_up_day_above_two_times_average_volume():
    bars = flat_tape(60, volume=100_000)
    bars[-2] = bar(100.0, 300_000)  # a down day with heavy volume
    bars[-1] = bar(102.0, 250_000)  # up day, 2.5x the 50d average, above the down volume
    pivot = calc_pocket_pivot(bars)
    assert pivot["pocketPivot"] is True
    assert pivot["volumeRatio50"] >= 2.0

    weak = flat_tape(60, volume=100_000)
    weak[-1] = bar(102.0, 120_000)  # up, but nowhere near 2x
    assert calc_pocket_pivot(weak)["pocketPivot"] is False


def test_float_turnover_flags_fifteen_percent_distribution():
    ok = calc_float_turnover(1_000_000, 20_000_000)   # 5% of the float
    assert ok["distributionWarning"] is False
    heavy = calc_float_turnover(3_500_000, 20_000_000)  # 17.5% of the float
    assert heavy["distributionWarning"] is True
    assert heavy["floatTurnoverPct"] == 17.5
    assert calc_float_turnover(None, 20_000_000)["floatTurnoverPct"] is None


def test_confluence_score_counts_satisfied_layers_only():
    assert calc_confluence_score({}) == 0
    assert calc_confluence_score({"macroLiquidity": True, "volumeSetup": True}) == 2
    full = {key: True for key, _label in CONFLUENCE_LAYERS}
    assert calc_confluence_score(full) == 6


def test_time_stop_marks_dead_capital_at_thirty_sessions():
    assert calc_time_stop(12)["sessionsRemaining"] == 18
    assert calc_time_stop(12)["deadCapital"] is False
    spent = calc_time_stop(31)
    assert spent["deadCapital"] is True
    assert spent["sessionsRemaining"] == 0


def test_sector_window_covers_a_ticker_the_matrix_cannot_score(tmp_path):
    payload = {"meta": {"currentMonthLabel": "Nov"}, "sectors": [{
        "sector": "Investment Banks", "status": "WATCH", "members": 28, "activeCount": 5,
        "accumulationWindow": {"forward60": {"winRatePct": 58.08, "avgPct": 14.68}},
        "tickers": [{"ticker": "DLL", "sector": "Investment Banks",
                     "status": "ACCUMULATION WINDOW ACTIVE",
                     "position": {"rangePositionPct": 20.0},
                     "accumulationWindowStats": {"forward60": {"winRatePct": 61.0, "avgPct": 9.0}}}]}]}
    path = tmp_path / "seasonality_matrix.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    by_ticker, month, by_sector = load_seasonality(path)
    assert by_ticker["DLL"]["coverage"] == "TICKER"
    assert "ENGROH" not in by_ticker  # a new listing the matrix cannot score yet
    sector = by_sector["Investment Banks"]
    assert sector["coverage"] == "SECTOR" and sector["status"] == "WATCH"
    assert sector["winRate60Pct"] == 58.08
    assert month == "Nov"


def test_desk_badges_sector_coverage_instead_of_no_coverage():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE company_fundamentals (ticker TEXT, free_float_pct REAL, "
                 "free_float_shares REAL, pe_ratio REAL, pb_ratio REAL, turnaround_catalyst INTEGER)")
    conn.execute("CREATE TABLE nccpl_flows (trade_date TEXT, participant_type TEXT, sector_name TEXT, "
                 "buy_pkr REAL, sell_pkr REAL, net_pkr REAL)")
    conn.execute("INSERT INTO company_fundamentals VALUES ('ENGROH', 75.0, 1000.0, 38.85, NULL, 1)")
    metrics = {"ENGROH": {"ticker": "ENGROH", "close": 300.0, "sector": "Investment Banks",
                          "atr": 6.0, "poc": 296.0, "stop": 288.0, "quiet": {}, "dryup": {},
                          "pivot": {}, "volume": 500, "aboveSma50": True}}
    sector_season = {"Investment Banks": {"sector": "Investment Banks", "status": "WATCH",
                                          "month": "Nov", "winRate60Pct": 58.08,
                                          "avgForward60Pct": 14.68, "coverage": "SECTOR"}}

    _setups, alerts, _summary = build_desk(conn.cursor(), date(2026, 11, 25), metrics, {}, "Nov", {}, {},
                                           breadth_pct=70.0, sector_season=sector_season)
    assert alerts and alerts[0]["ticker"] == "ENGROH"  # 50% of the free float in one session
    assert alerts[0]["seasonality"]["status"] == "WATCH"
    assert alerts[0]["seasonality"]["coverage"] == "SECTOR"


def test_missing_pb_prints_na_instead_of_an_empty_slot():
    assert _stat(None) == "N/A"
    assert _stat(0.85) == "0.85"


def test_same_session_setup_wins_over_a_contradictory_carry_trap():
    traps = [{"ticker": "AGP", "spotClose": 308.0, "annualizedCarryPct": 22.0},
             {"ticker": "NPL", "spotClose": 40.0, "annualizedCarryPct": 18.0}]
    setups = [{"ticker": "AGP"}]
    kept, suppressed = reconcile_traps(traps, setups)
    assert [row["ticker"] for row in kept] == ["NPL"]
    assert suppressed == [{"ticker": "AGP", "call": "AVOID", "label": "DFX CARRY TRAP",
                           "reason": "active six-layer setup on the same session"}]


def _ledger_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE psx_daily_eod (trade_date TEXT, ticker TEXT, close_price REAL)")
    return conn


def test_ledger_logs_desk_alerts_as_avoid_calls(tmp_path):
    conn = _ledger_conn()
    conn.execute("INSERT INTO psx_daily_eod VALUES ('27NOV2026', 'TPLL', 210.0)")
    out = tmp_path / "history.json"
    alerts = [{"ticker": "TPLL", "alert": "FREE-FLOAT DISTRIBUTION", "close": 210.0,
               "detail": "17% of the free float turned over in one session."}]

    log_signals(conn, conn.cursor(), "27NOV2026", [], alerts, out)
    entries = json.loads(out.read_text(encoding="utf-8"))["entries"]
    assert len(entries) == 1
    assert entries[0]["call"] == "AVOID"
    assert entries[0]["label"] == "FREE-FLOAT DISTRIBUTION"
    assert "free float" in entries[0]["notes"]


def test_ledger_retires_legacy_carry_trap_avoids(tmp_path):
    conn = _ledger_conn()
    out = tmp_path / "history.json"
    out.write_text(json.dumps({"sessionDate": "25NOV2026", "entries": [
        {"date": "25 Nov 2026", "ticker": "GHNI", "call": "AVOID", "label": "DFX CARRY TRAP",
         "entry": 40.0, "stop": None, "target": None,
         "notes": "Carry 22.0% vs SBP 12.0%"}]}), encoding="utf-8")

    log_signals(conn, conn.cursor(), "27NOV2026", [], [], out)
    assert json.loads(out.read_text(encoding="utf-8"))["entries"] == []


def test_ledger_drops_an_avoid_suppressed_by_the_same_session_setup(tmp_path):
    conn = _ledger_conn()
    conn.execute("INSERT INTO psx_daily_eod VALUES ('27NOV2026', 'AGP', 310.0)")
    out = tmp_path / "history.json"
    alerts = [{"ticker": "AGP", "alert": "INSTITUTIONAL DISTRIBUTION", "close": 308.0,
               "detail": "Institutions sold five straight sessions."}]

    log_signals(conn, conn.cursor(), "27NOV2026", [], alerts, out)
    assert any(e["ticker"] == "AGP" and e["call"] == "AVOID"
               for e in json.loads(out.read_text(encoding="utf-8"))["entries"])

    log_signals(conn, conn.cursor(), "27NOV2026", [], alerts, out,
                exclude={("27NOV2026", "AGP")})
    assert json.loads(out.read_text(encoding="utf-8"))["entries"] == []
