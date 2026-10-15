"""Pipeline context: single immutable session snapshot for analytics.

Encapsulates all session-scoped inputs the verdict engine and downstream
analyzers need, so call sites stop passing loose multi-argument tuples and
scoping bugs like unbound closure refs stop recurring.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from pipeline.analytics.sector_matrix import compute_sector_matrix


@dataclass(frozen=True)
class MarketContext:
    """Immutable session snapshot for the analytics pipeline.

    All verdict evaluators receive this single object instead of a long loose
    argument tuple. Adding a new indicator or filter therefore never touches
    caller / callee signatures across the pipeline.
    """

    trade_date: date
    macro_regime: str
    sector_matrix: dict[str, Any]
    eod_by_ticker: dict[str, list[dict[str, Any]]]
    flows_by_ticker: dict[str, Any]
    metadata: dict[str, Any]

    # Derived verifier state, computed once by build_market_context and read
    # by the three horizon evaluators + the Telegram / telemetry shapers.
    series: dict[str, list[tuple[date, float, float]]]
    sessions_desc: list[date]
    sector_by_ticker: dict[str, str]
    pe_map: dict[str, float | None]
    locked_tickers: set[str]
    tape_state: str


def build_market_context(
    trade_date: date,
    *,
    eod_rows: list[dict[str, Any]] | None = None,
    flow_rows: list[dict[str, Any]] | None = None,
    fundamentals: list[dict[str, Any]] | None = None,
    pe_rows: list[dict[str, Any]] | None = None,
    sector_matrix: dict[str, Any] | None = None,
    macro_regime: str | None = None,
    tape_state: str | None = None,
    series: dict[str, list[tuple[date, float, float]]] | None = None,
    sessions_desc: list[date] | None = None,
    sector_by_ticker: dict[str, str] | None = None,
    pe_map: dict[str, float | None] | None = None,
    locked_tickers: set[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> MarketContext:
    """Assemble an immutable MarketContext for one session.

    When raw rows are passed in, this builds the derived structures
    (series, sector_by_ticker, pe_map, locked_tickers, sector_matrix,
    macro_regime, tape_state). When derived values are passed in, those are
    reused as-is — which is what the real engine does so the context build
    stays cheap and deterministic for a given set of inputs.
    """

    eod_by_ticker: dict[str, list[dict[str, Any]]] = {}
    flows_by_ticker: dict[str, Any] = {}

    if eod_rows is not None:
        eod_by_ticker = _group_eod_by_ticker(eod_rows, trade_date)

    if flow_rows is not None:
        flows_by_ticker = _group_flows_by_ticker(flow_rows)

    if series is None and eod_rows is not None:
        all_eod = [r for rows in eod_by_ticker.values() for r in rows]
        series = _session_series(all_eod)
        sessions_desc = _session_dates_desc(series)
    elif series is None:
        series = {}
    if sessions_desc is None:
        sessions_desc = _session_dates_desc(series)

    if sector_by_ticker is None and fundamentals is not None:
        sector_by_ticker = _sector_map(fundamentals)
    elif sector_by_ticker is None:
        sector_by_ticker = {}

    if pe_map is None and pe_rows is not None:
        pe_map = _pe_map(pe_rows)
    elif pe_map is None:
        pe_map = {}

    if locked_tickers is None and eod_rows is not None:
        locked_tickers = _lower_lock_tickers(eod_rows, trade_date)
    elif locked_tickers is None:
        locked_tickers = set()

    if sector_matrix is None or not sector_matrix:
        sector_matrix = _build_sector_matrix_from_context(
            trade_date=trade_date,
            eod_by_ticker=eod_by_ticker,
            flow_rows=flow_rows,
            fundamentals=fundamentals,
            pe_rows=pe_rows,
            sector_by_ticker=sector_by_ticker,
        )

    if macro_regime is None or tape_state is None:
        macro_regime, tape_state = _derive_macro_regime_and_tape(
            trade_date=trade_date,
            eod_by_ticker=eod_by_ticker,
            flow_rows=flow_rows,
            series=series,
            sessions_desc=sessions_desc,
            macro_regime=macro_regime,
            tape_state=tape_state,
        )

    return MarketContext(
        trade_date=trade_date,
        macro_regime=macro_regime,
        sector_matrix=sector_matrix,
        eod_by_ticker=eod_by_ticker,
        flows_by_ticker=flows_by_ticker,
        metadata={
            **(metadata or {}),
            "fundamentals": fundamentals,
            "pe_rows": pe_rows,
        },
        series=series,
        sessions_desc=sessions_desc,
        sector_by_ticker=sector_by_ticker,
        pe_map=pe_map,
        locked_tickers=locked_tickers,
        tape_state=tape_state,
    )


# --------------------------------------------------------------------------- #
# Context helpers                                                             #
# --------------------------------------------------------------------------- #


def _group_eod_by_ticker(
    eod_rows: list[dict[str, Any]], trade_date: date
) -> dict[str, list[dict[str, Any]]]:
    """ticker -> EOD rows for that ticker, including prior sessions."""

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in eod_rows:
        ticker = row.get("ticker")
        day = _parse_day(row.get("trade_date"))
        if not ticker or day is None or day > trade_date:
            continue
        grouped.setdefault(ticker, []).append(row)
    return grouped


def _group_flows_by_ticker(flow_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Return flow rows grouped in a shape the context consumers expect."""

    return {"rows": flow_rows}


def _derive_macro_regime_and_tape(
    *,
    trade_date: date,
    eod_by_ticker: dict[str, list[dict[str, Any]]],
    flow_rows: list[dict[str, Any]] | None,
    series: dict[str, list[tuple[date, float, float]]],
    sessions_desc: list[date],
    macro_regime: str | None,
    tape_state: str | None,
) -> tuple[str, str]:
    """Compute macro_regime + tape_state from the session tape when possible.

    To avoid a circular import at module level, the tape helpers are imported
    lazily inside this function.
    """

    from pipeline.analytics.decision_engine import (
        _macro_tape_gate_label,
        _macro_tape_state,
        _regime_status,
        _session_dates_desc,
        _session_series,
    )

    use_regime = macro_regime
    use_tape = tape_state

    if use_regime is None or use_tape is None:
        flat_eod = [r for rows in eod_by_ticker.values() for r in rows]
        resolved_series = series if series else _session_series(flat_eod)
        resolved_desc = sessions_desc if sessions_desc else _session_dates_desc(resolved_series)
        prior = [d for d in resolved_desc if d < trade_date]
        prior_date = prior[0] if prior else trade_date

        if use_regime is None:
            use_regime = _regime_status(trade_date, prior_date, resolved_series)
        if use_tape is None:
            use_tape = _macro_tape_state(trade_date, prior_date, resolved_series)

    if macro_regime is None:
        macro_regime = _macro_tape_gate_label(use_regime, use_tape)

    return macro_regime, use_tape


def _sector_matrix_is_empty(sector_matrix: dict[str, Any]) -> bool:
    """True when sector_matrix should be recomputed inside build_market_context."""

    return not sector_matrix or not isinstance(sector_matrix, dict) or not sector_matrix


def _build_sector_matrix_from_context(
    *,
    trade_date: date,
    eod_by_ticker: dict[str, list[dict[str, Any]]],
    flow_rows: list[dict[str, Any]] | None,
    fundamentals: list[dict[str, Any]] | None = None,
    pe_rows: list[dict[str, Any]] | None = None,
    sector_by_ticker: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Derive sector_matrix from context fields when the caller did not supply one."""

    flat_eod = [r for rows in eod_by_ticker.values() for r in rows]
    resolved_sector_by_ticker = sector_by_ticker or _sector_map(fundamentals or [])
    return compute_sector_matrix(
        trade_date,
        eod_rows=flat_eod,
        flow_rows=flow_rows or [],
        sector_by_ticker=resolved_sector_by_ticker,
    )


def _parse_day(value: Any) -> date | None:
    """Parse a trade_date value; returns None when unverifiable."""

    try:
        return date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None


# Local re-exports of the pure series helpers so build_market_context does not
# reach into decision_engine for them at import time. They are imported lazily
# above only when macro/tape resolution is required inside the builder.
def _session_series(
    eod_rows: list[dict[str, Any]],
) -> dict[str, list[tuple[date, float, float]]]:
    """ticker -> [(day, close, volume)] sorted ascending."""

    from pipeline.analytics.decision_engine import _session_series as _impl

    return _impl(eod_rows)


def _session_dates_desc(
    series: dict[str, list[tuple[date, float, float]]],
) -> list[date]:
    """All stored sessions, newest first (across the universe)."""

    from pipeline.analytics.decision_engine import _session_dates_desc as _impl

    return _impl(series)


def _sector_map(fundamental_rows: list[dict[str, Any]]) -> dict[str, str]:
    """ticker -> sector label (upper) from psx_fundamentals."""

    from pipeline.analytics.decision_engine import _sector_map as _impl

    return _impl(fundamental_rows)


def _pe_map(fundamentals: list[dict[str, Any]]) -> dict[str, float | None]:
    """ticker -> pe_ratio from its NEWEST screener snapshot."""

    from pipeline.analytics.decision_engine import _pe_map as _impl

    return _impl(fundamentals)


def _lower_lock_tickers(
    eod_rows: list[dict[str, Any]], session_date: date
) -> set[str]:
    """Tickers that CLOSED at their lower circuit limit on ``session_date``."""

    from pipeline.analytics.decision_engine import _lower_lock_tickers as _impl

    return _impl(eod_rows, session_date)
