"""test_deep_backfill.py - deep ingestion sanity tests (offline, no network)."""

from __future__ import annotations

import json
import sqlite3
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import List
from urllib.request import Request, urlopen

import pytest

from src.core.models import DailyBar
from src.quant.stress_test import (
    StressTestConfig,
    _short_tape_payload,
    build_window_date_labels,
    equity_curve_shares,
    regime_label_for_window,
    WindowRecord,
)
from src.quant.stat_arb import SpreadSignal
from src.quant.sector_rotation import SESSIONS_PER_YEAR, MONTHS_PER_YEAR
from src.ingestion.sqlite_adapter import load_validated_bars
from src.ingestion.wal_adapter import WALIngestionManager
from src.quant.backtest import StrategyConfig as SweepConfig
from src.quant.backtest import StrategyBacktester
from src.quant.momentum_rotation import MomentumConfig, _run_rotation_on_bars


def _bar(ticker: str, d: date, close: float, volume: int = 50_000,
         high: float | None = None, low: float | None = None) -> DailyBar:
    hi = high if high is not None else close * 1.02
    lo = low if low is not None else close * 0.98
    return DailyBar(
        ticker=ticker,
        trade_date=d,
        open_price=close,
        high_price=hi,
        low_price=lo,
        close_price=close,
        volume=volume,
    )


def _tape(ticker: str, start: date, steps: int, close_start: float = 100.0,
          volume: int = 50_000) -> List[DailyBar]:
    bars: List[DailyBar] = []
    for i in range(steps):
        close = close_start * (1 + 0.0008 * i)
        bar = _bar(ticker, start + __import__("datetime").timedelta(days=i * 2), close, volume)
        bars.append(bar)
    return bars


def _write_tape_to_db(db_path: Path, ticker: str, bars: List[DailyBar]) -> None:
    manager = WALIngestionManager(str(db_path))
    inserted, quarantined = manager.upsert_bars(bars)
    assert inserted == len(bars)
    assert quarantined == 0


# ---------------------------------------------------------------------------
# Deep backfill offline helpers
# ---------------------------------------------------------------------------


def test_deep_ingestion_write_and_readback(tmp_path: Path) -> None:
    db = tmp_path / "deep_test.db"
    bars = _tape("TEST", date(2024, 1, 2), 252, close_start=100.0)
    _write_tape_to_db(db, "TEST", bars)

    by_ticker, rejected = load_validated_bars(str(db))
    assert rejected == 0
    assert len(by_ticker["TEST"]) == 252
    assert by_ticker["TEST"][0].trade_date == date(2024, 1, 2)
    assert by_ticker["TEST"][-1].close_price > by_ticker["TEST"][0].close_price


def test_deep_ingestion_skip_enough_history(tmp_path: Path) -> None:
    db = tmp_path / "deep_test.db"
    bars = _tape("FULL", date(2020, 1, 2), 1500, close_start=100.0)
    _write_tape_to_db(db, "FULL", bars)

    from backend.src.ingestion.universe import active_universe
    uni = active_universe(str(db), min_bars=252)
    assert "FULL" in uni


# ---------------------------------------------------------------------------
# Walk-forward / stress-test helpers
# ---------------------------------------------------------------------------


def test_window_date_labels_produce_readable_strings() -> None:
    sessions = [date(2024, 1, 1) + __import__("datetime").timedelta(days=i) for i in range(500)]
    session_strs = [s.isoformat() for s in sessions]
    label, f, t, oos_f, oos_t, sess, oos_sess, w_y, oos_y = build_window_date_labels(
        session_strs, 0, 252, 252, 350
    )
    assert "2024-01" in label
    assert f == "2024-01-01"
    assert oos_f.startswith("2024-09")
    assert sess == 252
    assert oos_sess == 98
    assert abs(w_y - 1.0) < 0.01
    assert abs(oos_y - 0.39) < 0.01


def test_regime_label_stress_when_dd_large() -> None:
    w = WindowRecordDemux(
        window_label="w1",
        from_date="2020-01-01",
        to_date="2021-01-01",
        sessions=252,
        window_years=1.0,
        oos_from="2021-01-01",
        oos_to="2021-04-01",
        oos_sessions=63,
        oos_years=0.25,
        sweep_max_drawdown_pct=18.0,
        momentum_max_drawdown_pct=4.0,
        sweep_win_rate_pct=40.0,
        momentum_win_rate_pct=30.0,
    )
    assert regime_label_for_window(w._as_record()) == "STRESS"


def test_regime_label_favorable_when_win_rates_high() -> None:
    w = WindowRecordDemux(
        window_label="w1",
        from_date="2023-01-01",
        to_date="2024-01-01",
        sessions=252,
        window_years=1.0,
        oos_from="2024-01-01",
        oos_to="2024-04-01",
        oos_sessions=63,
        oos_years=0.25,
        sweep_max_drawdown_pct=3.0,
        momentum_max_drawdown_pct=2.0,
        sweep_win_rate_pct=60.0,
        momentum_win_rate_pct=40.0,
    )
    assert regime_label_for_window(w._as_record()) == "FAVORABLE"


def test_regime_label_unfavorable_when_win_rates_low() -> None:
    w = WindowRecordDemux(
        window_label="w1",
        from_date="2018-01-01",
        to_date="2019-01-01",
        sessions=252,
        window_years=1.0,
        oos_from="2019-01-01",
        oos_to="2019-04-01",
        oos_sessions=63,
        oos_years=0.25,
        sweep_max_drawdown_pct=5.0,
        momentum_max_drawdown_pct=4.0,
        sweep_win_rate_pct=30.0,
        momentum_win_rate_pct=20.0,
    )
    assert regime_label_for_window(w._as_record()) == "UNFAVORABLE"


def test_regime_label_neutral_by_default() -> None:
    w = WindowRecordDemux(
        window_label="w1",
        from_date="2022-01-01",
        to_date="2023-01-01",
        sessions=252,
        window_years=1.0,
        oos_from="2023-01-01",
        oos_to="2023-04-01",
        oos_sessions=63,
        oos_years=0.25,
        sweep_max_drawdown_pct=5.0,
        momentum_max_drawdown_pct=3.0,
        sweep_win_rate_pct=45.0,
        momentum_win_rate_pct=30.0,
    )
    assert regime_label_for_window(w._as_record()) == "NEUTRAL"


def test_short_tape_fallback_returns_payload(tmp_path: Path) -> None:
    db = tmp_path / "short.db"
    bars = _tape("S", date(2020, 1, 2), 600, close_start=100.0)
    _write_tape_to_db(db, "S", bars)
    by_ticker, _rejected = load_validated_bars(str(db))

    config = StressTestConfig(horizon_years=15, window_years=3, step_years=1, top_n=10, sizing_mode="equal")
    sessions = [b.trade_date.isoformat() for b in bars]
    universe = ["S"]
    payload = _short_tape_payload(by_ticker, sessions, config, universe=universe)

    assert payload["meta"]["windowCount"] == 1
    assert payload["windows"][0]["regime"] == "SHORT_TAPE"
    assert payload["windows"][0]["sweep"]["signals"] >= 0
    assert payload["windows"][0]["momentum"]["positions"] >= 0
    assert isinstance(payload["equityCurve"], list)


def test_equity_curve_shares_round_trip() -> None:
    curve = [
        {"date": "2024-01-01", "equity": 100000.0, "drawdownPct": 0.0},
        {"date": "2024-01-02", "equity": 100500.0, "drawdownPct": -0.5},
    ]
    compact = equity_curve_shares(curve)
    assert compact[0]["date"] == "2024-01-01"
    assert compact[0]["equity"] == 100000.0
    assert compact[1]["drawdownPct"] == -0.5


def test_stress_config_defaults_are_sensible() -> None:
    cfg = StressTestConfig()
    assert cfg.horizon_years == 15.0
    assert cfg.window_years == 3.0
    assert cfg.step_years == 1.0
    assert cfg.top_n == 10
    assert cfg.sizing_mode == "atrp"
    assert cfg.with_kelly is False
    assert cfg.with_var is False
    assert cfg.stat_arb is True


def test_stress_config_strict_flag_behavior() -> None:
    cfg = StressTestConfig(with_kelly=True, with_var=True, stat_arb=False, sweep_with_filters=True)
    assert cfg.with_kelly is True
    assert cfg.with_var is True
    assert cfg.stat_arb is False
    assert cfg.sweep_with_filters is True


from dataclasses import dataclass as _dataclass
import dataclasses


@_dataclass
class WindowRecordDemux:
    window_label: str
    from_date: str
    to_date: str
    sessions: int
    window_years: float
    oos_from: str
    oos_to: str
    oos_sessions: int
    oos_years: float
    sweep_max_drawdown_pct: float
    momentum_max_drawdown_pct: float
    sweep_win_rate_pct: float
    momentum_win_rate_pct: float

    def _as_record(self):
        return WindowRecord(
            window_label=self.window_label,
            from_date=self.from_date,
            to_date=self.to_date,
            sessions=self.sessions,
            window_years=self.window_years,
            oos_from=self.oos_from,
            oos_to=self.oos_to,
            oos_sessions=self.oos_sessions,
            oos_years=self.oos_years,
            sweep_max_drawdown_pct=self.sweep_max_drawdown_pct,
            momentum_max_drawdown_pct=self.momentum_max_drawdown_pct,
            sweep_win_rate_pct=self.sweep_win_rate_pct,
            momentum_win_rate_pct=self.momentum_win_rate_pct,
        )


def test_window_record_fields_round_trip(tmp_path: Path) -> None:
    db = tmp_path / "wfr.db"
    bars = _tape("W", date(2022, 1, 3), 800, close_start=100.0)
    _write_tape_to_db(db, "W", bars)
    by_ticker, _ = load_validated_bars(str(db))
    sessions = [b.trade_date.isoformat() for b in bars]

    from backend.src.quant.stress_test import StressTestConfig, run_walk_forward_window
    cfg = StressTestConfig(horizon_years=15, window_years=3, step_years=1, top_n=10, sizing_mode="equal",
                          stat_arb=True)

    rec = run_walk_forward_window(by_ticker, sessions, 0, 252, cfg, universe=["W"])
    assert rec.window_label
    assert rec.from_date
    assert rec.to_date
    assert rec.sessions > 0
    assert rec.window_years > 0
    assert rec.oos_sessions > 0
    assert rec.oos_years > 0

    # Sweep fields present.
    assert rec.sweep_signals >= 0
    assert rec.sweep_wins >= 0
    assert rec.sweep_losses >= 0
    assert 0.0 <= rec.sweep_win_rate_pct <= 100.0
    assert rec.sweep_total_return_pct >= -100.0
    assert rec.sweep_max_drawdown_pct >= 0.0

    # Momentum fields present.
    assert rec.momentum_positions >= 0
    assert rec.momentum_wins >= 0
    assert rec.momentum_losses >= 0
    assert 0.0 <= rec.momentum_win_rate_pct <= 100.0
    assert rec.momentum_max_drawdown_pct >= 0.0

    # Stat-arb informative fields present.
    assert rec.stat_arb_pairs >= 0
    assert rec.stat_arb_signals >= 0
    assert rec.stat_arb_entry_signals >= 0
    assert rec.stat_arb_exit_signals >= 0


def test_aggregate_payload_has_regime_switching() -> None:
    windows = [
        WindowRecordDemux(
            window_label="2020->2021", from_date="2020-01-01", to_date="2021-01-01",
            sessions=252, window_years=1.0, oos_from="2021-01-01", oos_to="2021-04-01",
            oos_sessions=63, oos_years=0.25,
            sweep_max_drawdown_pct=12.0, momentum_max_drawdown_pct=5.0,
            sweep_win_rate_pct=35.0, momentum_win_rate_pct=25.0,
        ),
        WindowRecordDemux(
            window_label="2021->2022", from_date="2021-01-01", to_date="2022-01-01",
            sessions=252, window_years=1.0, oos_from="2022-01-01", oos_to="2022-04-01",
            oos_sessions=63, oos_years=0.25,
            sweep_max_drawdown_pct=3.0, momentum_max_drawdown_pct=2.0,
            sweep_win_rate_pct=58.0, momentum_win_rate_pct=40.0,
        ),
    ]
    recs = [w._as_record() for w in windows]

    from src.quant.stress_test import regime_label_for_window
    labels = [regime_label_for_window(r) for r in recs]
    assert "STRESS" in labels or "NEUTRAL" in labels
    assert "FAVORABLE" in labels
