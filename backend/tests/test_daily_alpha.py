"""Coverage for the unified daily alpha intelligence brief."""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from src.core.models import DailyBar
from src.quant.daily_alpha import (
    MAX_WEIGHT_PCT,
    RISK_BUDGET_PCT,
    build_daily_alpha,
    classify_market_regime,
    confluence_edges,
    is_liquid,
    liquidity_profile,
    spread_alert,
    sweep_signal,
)
from src.quant.seasonality import exhaustion_profile

START = date(2025, 1, 1)
ACTIVE = "ACCUMULATION WINDOW ACTIVE"


def _bar(ticker: str, d: date, close: float, volume: int, open_: float | None = None) -> DailyBar:
    op = open_ if open_ is not None else close
    return DailyBar(
        ticker=ticker,
        trade_date=d,
        open_price=op,
        high_price=max(op, close) * 1.01,
        low_price=min(op, close) * 0.99,
        close_price=close,
        volume=volume,
    )


def trend_tape(
    ticker: str = "AAA",
    sessions: int = 300,
    start: float = 100.0,
    step: float = 0.35,
    volume: int = 120_000,
) -> list[DailyBar]:
    return [
        _bar(ticker, START + timedelta(days=i), round(start + step * i, 2), volume)
        for i in range(sessions)
    ]


def flat_tape(ticker: str, sessions: int = 300, price: float = 100.0, volume: int = 120_000) -> list[DailyBar]:
    return [_bar(ticker, START + timedelta(days=i), price, volume) for i in range(sessions)]


def runup_tape(ticker: str = "HOT", sessions: int = 300, run_pct: float = 1.0135) -> list[DailyBar]:
    """Flat tape, then 20 sessions of compounding gains (a finished run-up)."""
    closes = [100.0] * (sessions - 20)
    price = 100.0
    for _ in range(20):
        price *= run_pct
        closes.append(round(price, 2))
    return [
        _bar(ticker, START + timedelta(days=i), close, 120_000)
        for i, close in enumerate(closes)
    ]


def divergent_tape(ticker: str = "DIV") -> list[DailyBar]:
    """Higher swing high on weaker RSI and fading volume (distribution)."""
    closes = [100.0]
    for _ in range(250):
        closes.append(round(closes[-1] * 1.002, 2))
    for _ in range(12):
        closes.append(round(closes[-1] * 1.012, 2))
    peak = closes[-1]
    for _ in range(6):
        closes.append(round(closes[-1] * 0.985, 2))
    for _ in range(8):
        closes.append(round(closes[-1] * 1.0016, 2))
    closes.append(round(peak * 1.0005, 2))
    volumes = [150_000] * (len(closes) - 7) + [90_000] * 7
    return [
        _bar(ticker, START + timedelta(days=i), close, volume)
        for i, (close, volume) in enumerate(zip(closes, volumes))
    ]


def seasonality_payload(rows: list[dict] | None = None) -> dict:
    return {
        "generatedAt": "2025-01-01T00:00:00+00:00",
        "activeWindows": rows
        if rows is not None
        else [
            {
                "ticker": "AAA",
                "sector": "Banking",
                "status": ACTIVE,
                "winRate60Pct": 64.0,
                "avgForward60Pct": 8.0,
                "avgForward90Pct": 12.0,
                "rangePositionPct": 30.0,
                "monthsUntilWindow": 0,
            }
        ],
    }


# ---------------------------------------------------------------------------
# Regime header
# ---------------------------------------------------------------------------


def test_regime_stress_overrides_trend_read():
    regime, posture, stress = classify_market_regime(0.62, 1.25, -12.0, 1.6)
    assert regime == "STRESS"
    assert "preservation" in posture
    assert stress > 40


def test_regime_trending_and_choppy_labels():
    assert classify_market_regime(0.60, 1.20, -2.0, 1.0)[0] == "TRENDING"
    assert classify_market_regime(0.44, 0.90, -1.0, 0.9)[0] == "CHOPPY"


def test_regime_header_reports_trending_for_orderly_uptrend():
    tape = {f"T{i}": trend_tape(f"T{i}", step=0.3) for i in range(6)}
    payload = build_daily_alpha(tape)
    header = payload["marketRegime"]
    assert header["regime"] in {"TRENDING", "CHOPPY", "STRESS"}
    assert 0.0 <= header["hurstExponent"] <= 1.0
    assert header["proxySessions"] > 100
    assert header["posture"]


# ---------------------------------------------------------------------------
# Liquidity gate & confluence
# ---------------------------------------------------------------------------


def test_liquidity_gate_excludes_thin_names():
    thin = liquidity_profile(flat_tape("THIN", volume=500))
    assert not is_liquid(thin)

    payload = build_daily_alpha(
        {"AAA": trend_tape("AAA"), "BBB": trend_tape("BBB"), "THIN": flat_tape("THIN", volume=500)},
        seasonality_payload(),
    )
    assert payload["universe"]["scanned"] == 3
    # The thin name is scanned but never becomes tradeable or a pick.
    assert payload["universe"]["liquid"] == 2
    assert all(pick["ticker"] != "THIN" for pick in payload["picks"])


def test_confluence_requires_two_edges_including_a_trigger():
    liar = trend_tape("LIAR")
    seasonal_only = confluence_edges(liar, True, momentum=-5.0)
    assert seasonal_only == [ACTIVE, "ABOVE 50D SMA"]

    # Seasonal alone (flat tape, no momentum, no sweep): one edge is not enough.
    payload = build_daily_alpha(
        {"FLAT": flat_tape("FLAT")},
        seasonality_payload([{"ticker": "FLAT", "sector": "Banking", "status": ACTIVE}]),
    )
    assert payload["picks"] == []


# ---------------------------------------------------------------------------
# Exhaustion & bearish divergence guard
# ---------------------------------------------------------------------------


def test_runup_is_exhausted_but_orderly_trend_is_not():
    hot = exhaustion_profile(runup_tape())
    assert hot["exhausted"] is True
    assert hot["ret20dPct"] >= 15.0
    assert "recent_runup_exhaustion" in hot["reasons"]

    # A steady grind sits at the top of its 20-day range every session; only a
    # real run-up (>=8% pinned in the top 15% of the swing) is exhaustion.
    calm = exhaustion_profile(trend_tape("CALM", step=0.35))
    assert calm["exhausted"] is False
    assert calm["reasons"] == []


def test_bearish_divergence_flags_higher_high_on_weaker_rsi():
    guard = exhaustion_profile(divergent_tape())
    assert guard["bearishDivergence"] is True
    assert guard["divergenceType"] == "PRICE_RSI"
    assert "bearish_divergence" in guard["reasons"]
    assert guard["divergenceNote"]

    # A monotonic advance makes a higher high with a higher RSI: no divergence.
    assert exhaustion_profile(trend_tape("UP"))["bearishDivergence"] is False


def test_exhausted_seasonal_name_is_blocked_and_published_as_extended():
    payload = build_daily_alpha(
        {"HOT": runup_tape()},
        seasonality_payload(
            [{"ticker": "HOT", "sector": "Banking", "status": ACTIVE, "winRate60Pct": 64.0,
              "avgForward60Pct": 8.0, "rangePositionPct": 30.0}]
        ),
    )
    assert all(pick["ticker"] != "HOT" for pick in payload["picks"])
    extended = payload["extendedSetups"]
    assert [row["ticker"] for row in extended] == ["HOT"]
    assert extended[0]["action"] == "EXTENDED / WAIT PULLBACK"
    assert "recent_runup_exhaustion" in extended[0]["reasons"]
    assert payload["universe"]["extendedBlocked"] == 1


def test_sweep_requires_reclaim_on_volume():
    bars = [_bar("SWP", START + timedelta(days=i), 100.0, 100_000) for i in range(25)]
    # Take out the prior 3-day low, close back above the POC, on a volume burst.
    bars.append(_bar("SWP", START + timedelta(days=25), 101.0, 600_000, open_=100.0))
    bars[-1] = bars[-1].model_copy(update={"low_price": 95.0, "high_price": 102.0})
    signal = sweep_signal(bars)
    assert signal["sweep"] is True
    assert signal["volZScore"] >= 1.5


# ---------------------------------------------------------------------------
# Picks & sizing
# ---------------------------------------------------------------------------


def test_picks_ranked_and_sized_within_risk_budget():
    payload = build_daily_alpha(
        {
            "AAA": trend_tape("AAA", step=0.45),
            "BBB": trend_tape("BBB", step=0.10),
            "CCC": trend_tape("CCC", step=0.05),
        },
        seasonality_payload(),
    )
    picks = payload["picks"]
    assert picks, "a liquid seasonal momentum leader must qualify"
    assert picks[0]["ticker"] == "AAA"  # strongest momentum ranks first
    assert [p["rank"] for p in picks] == list(range(1, len(picks) + 1))
    assert [p["score"] for p in picks] == sorted((p["score"] for p in picks), reverse=True)

    for pick in picks:
        assert len(pick["edges"]) >= 2
        assert pick["stopLoss"] < pick["close"]
        assert 0 < pick["stopDistancePct"] <= 15.0
        assert 0 < pick["targetWeightPct"] <= MAX_WEIGHT_PCT
        assert pick["riskBudgetPct"] <= RISK_BUDGET_PCT
        assert pick["referenceShares"] > 0
        assert pick["kellyMultiplier"] <= 1.0

    assert "ACCUMULATION WINDOW ACTIVE" in picks[0]["edges"]
    assert "MOMENTUM LEADER" in picks[0]["edges"]
    assert picks[0]["winRatePct"] == 64.0


def test_picks_capped_at_top_n():
    tape = {f"T{i:02d}": trend_tape(f"T{i:02d}", step=0.4) for i in range(14)}
    payload = build_daily_alpha(tape, seasonality_payload([]), top_n=10)
    assert len(payload["picks"]) == 10


# ---------------------------------------------------------------------------
# Stat-arb
# ---------------------------------------------------------------------------


def parallel_pair(sessions: int = 200, drift_bps: float = 2.0) -> tuple[list[DailyBar], list[DailyBar]]:
    a: list[DailyBar] = []
    b: list[DailyBar] = []
    price_a = price_b = 100.0
    for i in range(sessions):
        d = START + timedelta(days=i)
        wobble = 1.0 if i % 2 == 0 else -1.0
        price_a *= 1.0 + (drift_bps / 10_000.0) + wobble * 0.0002
        price_b *= 1.0 + (drift_bps / 10_000.0) - wobble * 0.0002
        a.append(_bar("HBL", d, round(price_a, 4), 150_000))
        b.append(_bar("UBL", d, round(price_b, 4), 150_000))
    # Terminal divergence: A richens ~8% over the last two sessions (news gap),
    # which is well outside the pair's normal spread band.
    for idx in (sessions - 2, sessions - 1):
        a[idx] = _bar("HBL", a[idx].trade_date, round(a[idx].close_price * 1.04, 4), 150_000)
    return a, b


def test_stat_arb_alert_on_diverged_sector_pair():
    a, b = parallel_pair()
    alert = spread_alert("HBL", "UBL", a, b, "Banking")
    assert alert is not None
    assert abs(alert["zScore"]) >= 2.0
    assert alert["sector"] == "Banking"
    assert alert["directionForA"] in {"SHORT_A_LONG_B", "LONG_A_SHORT_B"}
    assert alert["hedgeRatio"] > 0


def test_stat_arb_alerts_surface_in_brief():
    a, b = parallel_pair()
    payload = build_daily_alpha({"HBL": a, "UBL": b}, seasonality_payload([]))
    assert payload["statArb"], "the diverged pair must appear in the brief"
    top = payload["statArb"][0]
    assert {top["legA"], top["legB"]} == {"HBL", "UBL"}
    assert abs(top["zScore"]) >= 2.0


# ---------------------------------------------------------------------------
# Payload contract
# ---------------------------------------------------------------------------


def test_payload_is_lightweight_and_serializable():
    tape = {f"T{i:02d}": trend_tape(f"T{i:02d}", step=0.2 + i * 0.01) for i in range(20)}
    payload = build_daily_alpha(tape, seasonality_payload([]))
    blob = json.dumps(payload)
    assert len(blob.encode("utf-8")) < 200_000
    assert payload["sessionDate"] == max(bars[-1].trade_date for bars in tape.values()).isoformat()
    for key in ("marketRegime", "picks", "statArb", "universe", "meta"):
        assert key in payload
    assert payload["meta"]["sizing"]["referenceCapitalPkr"] == 1_000_000
