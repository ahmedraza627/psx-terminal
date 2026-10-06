"""Daily quant signal engine for the PSX terminal.

Runs after daily EOD + flow ingestion and emits one row per
(trade_date, ticker, signal_type) into psx_daily_quant_signals.
Signals are certified facts about the current session's price,
volume, breadth, and flow fingerprints - not forecasts.

Conditions:
  * VOLUME_EXPANSION - current session volume > 2.5x the trailing
    20-session volume SMA and the ticker closed green or flat.
  * INSTITUTIONAL_ACCUMULATION - a sector whose participant cut shows
    smart-money net buying (FIPI + MUTUAL FUNDS + BANKS + FOREIGN
    CORPORATES > 0 on the 5-session window) at the same time retail
    (INDIVIDUALS) is net selling across that window.
  * MARKET_BREADTH - if the latest index session is up but the
    advance/decline ratio across the EOD universe is < 0.8, the
    session is flagged DIVERGENT_BEARISH.
  * RETAIL_TRAP_SHORT - individual names where retail is net buying
    while institutions are net distributing on the latest session.

Output columns:
  trade_date, ticker, signal_type,
  confidence_score (1-100), catalyst_reason (text), sector.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from pipeline import db
from pipeline.parsing import chunked

LOGGER = logging.getLogger(__name__)


def _latest_session() -> date | None:
    """Latest populated psx_daily_eod session date."""
    try:
        resp = (
            db.get_client()
            .table("psx_daily_eod")
            .select("trade_date")
            .order("trade_date", desc=True)
            .limit(1)
            .execute()
        )
        row = resp.data[0] if resp.data else None
        if row is None:
            return None
        return datetime.strptime(str(row["trade_date"])[:10], "%Y-%m-%d").date()
    except Exception as exc:
        LOGGER.warning("could not read latest EOD session: %s", exc)
        return None


def _avg_volume(ticker: str, days: int = 20) -> float:
    """Trailing 20-session average volume for one ticker."""
    try:
        rows = db.fetch_recent_eod(days=max(days, 30))
        ticker_rows = [r for r in rows if r["ticker"] == ticker]
        volumes = [float(r["volume"]) for r in ticker_rows if r["volume"]]
        return sum(volumes) / len(volumes) if volumes else 0.0
    except Exception as exc:
        LOGGER.warning("could not compute avg volume for %s: %s", ticker, exc)
        return 0.0


def _adv_dec_ratio(session: date) -> float | None:
    """Advance/decline ratio across the full EOD universe for one session."""
    try:
        rows = (
            db.get_client()
            .table("psx_daily_eod")
            .select("close_price")
            .eq("trade_date", session.isoformat())
            .execute()
        )
        closes = [float(r["close_price"]) for r in (rows.data or []) if r["close_price"]]
        if not closes:
            return None
        prior = (
            db.get_client()
            .table("psx_daily_eod")
            .select("close_price")
            .eq("trade_date", (session - timedelta(days=1)).isoformat())
            .execute()
        )
        prior_closes = [float(r["close_price"]) for r in (prior.data or []) if r["close_price"]]
        if not prior_closes:
            return None
        adv = 0
        dec = 0
        for cur, pri in zip(closes, prior_closes):
            if cur > pri:
                adv += 1
            elif cur < pri:
                dec += 1
        if dec == 0:
            return None
        return adv / dec
    except Exception as exc:
        LOGGER.warning("could not compute A/D ratio for %s: %s", session, exc)
        return None


def _sector_flows(session: date, window: int = 5) -> dict[str, dict[str, Decimal]]:
    """Net PKR by (sector, participant) for the trailing `window` sessions."""
    try:
        rows = db.fetch_recent_flows(days=window)
        out: dict[str, dict[str, Decimal]] = {}
        for r in rows:
            sec = (r["sector_name"] or "").strip().upper()
            if sec == "ALL":
                continue
            part = (r["participant_type"] or "").strip().upper()
            if not part:
                continue
            net = Decimal(str(r["net_pkr"] or 0))
            out.setdefault(sec, {}).setdefault(part, Decimal(0))
            out[sec][part] += net
        return out
    except Exception as exc:  # noqa: BLE001 - degrade gracefully
        LOGGER.warning("could not load sector flows for %s: %s", session, exc)
        return {}


def _smart_money_accumulation(
    flows: dict[str, dict[str, Decimal]],
) -> list[tuple[str, Decimal]]:
    """Sectors where institutions are net buyers and retail is net seller."""
    smart_parts = {"FIPI", "MUTUAL FUNDS", "BANKS", "FOREIGN CORPORATES"}
    retail_part = {"INDIVIDUALS"}
    result: list[tuple[str, Decimal]] = []
    for sec, parts in flows.items():
        sm = sum(parts.get(p, Decimal(0)) for p in smart_parts)
        retail = sum(parts.get(p, Decimal(0)) for p in retail_part)
        if sm > 0 and retail < 0:
            result.append((sec, sm))
    result.sort(key=lambda x: x[1], reverse=True)
    return result


def _retail_trap_sectors(
    flows: dict[str, dict[str, Decimal]],
) -> list[tuple[str, Decimal]]:
    """Sectors where retail is net buying while institutions net sell."""
    smart_parts = {"FIPI", "MUTUAL FUNDS", "BANKS", "FOREIGN CORPORATES"}
    retail_part = {"INDIVIDUALS"}
    result: list[tuple[str, Decimal]] = []
    for sec, parts in flows.items():
        sm = sum(parts.get(p, Decimal(0)) for p in smart_parts)
        retail = sum(parts.get(p, Decimal(0)) for p in retail_part)
        if retail > 0 and sm < 0:
            result.append((sec, retail))
    result.sort(key=lambda x: x[1], reverse=True)
    return result


def _volume_expansion_candidates(
    session: date,
) -> list[dict[str, Any]]:
    """Tickers whose session volume > 2.5x trailing average."""
    try:
        rows = db.fetch_recent_eod(days=30)
        today = [r for r in rows if r["trade_date"] == session.isoformat()]
        candidates: list[dict[str, Any]] = []
        for row in today:
            vol = float(row["volume"] or 0)
            avg = _avg_volume(row["ticker"], days=20)
            if avg <= 0 or vol <= 2.5 * avg:
                continue
            candidates.append({
                "ticker": row["ticker"],
                "volume": vol,
                "close": float(row["close_price"] or 0),
                "avg_volume": avg,
                "sector": None,  # enriched from fundamentals below
            })
        candidates.sort(key=lambda c: c["volume"] / c["avg_volume"], reverse=True)
        return candidates
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("could not scan volume breakouts: %s", exc)
        return []


def _sector_for_ticker(ticker: str) -> str | None:
    """Latest stored sector name for one ticker (from psx_fundamentals)."""
    try:
        resp = (
            db.get_client()
            .table("psx_fundamentals")
            .select("sector_name")
            .eq("ticker", ticker)
            .order("trade_date", desc=True)
            .limit(1)
            .execute()
        )
        row = resp.data[0] if resp.data else None
        if row is None:
            return None
        sec = (row["sector_name"] or "").strip()
        return sec if sec else None
    except Exception as exc:
        LOGGER.debug("could not resolve sector for %s: %s", ticker, exc)
        return None


def _upsert_signals(
    rows: list[dict[str, Any]],
) -> int:
    """Idempotent chunked upsert into psx_daily_quant_signals."""
    if not rows:
        return 0
    try:
        written = 0
        for chunk in chunked(rows, 500):
            (
                db.get_client()
                .table("psx_daily_quant_signals")
                .upsert(
                    chunk,
                    on_conflict="trade_date,ticker,signal_type",
                )
                .execute()
            )
            written += len(chunk)
        return written
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("quant signal upsert failed: %s", exc)
        return 0


def run_daily_quant_signals(session: date) -> dict[str, int]:
    """One-shot daily signal generation for the live session.

    Returns counts: {volume_expansion, institutional_accumulation,
    retail_trap_short, market_breadth, written}.
    """
    LOGGER.info("quant signals for session %s", session.isoformat())
    flows = _sector_flows(session)
    sm_acc = _smart_money_accumulation(flows)
    retail_trap = _retail_trap_sectors(flows)
    vol_cands = _volume_expansion_candidates(session)

    out: list[dict[str, Any]] = []

    # VOLUME_EXPANSION across the board, scored by the volume spike.
    for cand in vol_cands[:150]:
        ratio = cand["volume"] / cand["avg_volume"]
        conf = int(min(100, 40 + ratio * 8))
        reason = (
            f"{cand['ticker']} vol {cand['volume']:.0f} vs {cand['avg_volume']:.0f} avg "
            f"({ratio:.2f}x); close {cand['close']:.2f}."
        )
        sector = _sector_for_ticker(cand["ticker"])
        out.append({
            "trade_date": session.isoformat(),
            "ticker": cand["ticker"],
            "signal_type": "VOLUME_EXPANSION",
            "confidence_score": conf,
            "catalyst_reason": reason,
            "sector": sector,
        })

    # INSTITUTIONAL_ACCUMULATION per enriched sector with a representative name.
    for sec, sm in sm_acc:
        # Pick the highest-volume ticker in that sector on the session.
        ticker = None
        try:
            rows = (
                db.get_client()
                .table("psx_daily_eod")
                .select("ticker,volume,close_price")
                .eq("trade_date", session.isoformat())
                .order("volume", desc=True)
                .limit(200)
                .execute()
            )
            sector_rows = [
                r for r in (rows.data or [])
                if (r["sector_name"] or "").upper() == sec.upper()
            ]
            if sector_rows:
                ticker = sector_rows[0]["ticker"]
        except Exception as exc:
            LOGGER.debug("sector rep ticker lookup failed for %s: %s", sec, exc)
        if ticker is None:
            continue
        retail = sum(
            parts.get(p, Decimal(0))
            for p in {"INDIVIDUALS"}
            for parts in [flows.get(sec, {})]
        )
        if retail >= 0 and sm > 0:
            conf = int(min(100, 30 + float(sm) / 1e6))
        else:
            conf = int(min(100, 60 + float(sm) / 1e6))
        reason = (
            f"{ticker} sector {sec}: institutions net +{float(sm):,.0f} PKR, "
            f"retail net {float(retail):,.0f} PKR."
        )
        out.append({
            "trade_date": session.isoformat(),
            "ticker": ticker,
            "signal_type": "INSTITUTIONAL_ACCUMULATION",
            "confidence_score": conf,
            "catalyst_reason": reason,
            "sector": sec,
        })

    # RETAIL_TRAP_SHORT per retail-trap sector with representative name.
    for sec, retail in retail_trap:
        ticker = None
        try:
            rows = (
                db.get_client()
                .table("psx_daily_eod")
                .select("ticker,volume,close_price")
                .eq("trade_date", session.isoformat())
                .order("volume", desc=True)
                .limit(200)
                .execute()
            )
            sector_rows = [
                r for r in (rows.data or [])
                if (r["sector_name"] or "").upper() == sec.upper()
            ]
            if sector_rows:
                ticker = sector_rows[0]["ticker"]
        except Exception as exc:
            LOGGER.debug("retail trap rep ticker lookup failed for %s: %s", sec, exc)
        if ticker is None:
            continue
        sm = sum(
            parts.get(p, Decimal(0))
            for p in {"FIPI", "MUTUAL FUNDS", "BANKS", "FOREIGN CORPORATES"}
            for parts in [flows.get(sec, {})]
        )
        conf = int(min(100, 20 + float(abs(sm)) / 1e6 + float(retail) / 1e6))
        reason = (
            f"{ticker} sector {sec}: retail net +{float(retail):,.0f} PKR while "
            f"institutions net {float(sm):,.0f} PKR."
        )
        out.append({
            "trade_date": session.isoformat(),
            "ticker": ticker,
            "signal_type": "RETAIL_TRAP_SHORT",
            "confidence_score": conf,
            "catalyst_reason": reason,
            "sector": sec,
        })

    # MARKET_BREADTH divergence flag as a session-level signal row.
    ratio = _adv_dec_ratio(session)
    if ratio is not None and ratio < 0.8:
        idx_close = None
        try:
            idx_rows = (
                db.get_client()
                .table("psx_daily_eod")
                .select("close_price")
                .eq("ticker", "KSE100")
                .eq("trade_date", session.isoformat())
                .limit(1)
                .execute()
            )
            idx_close = float(idx_rows.data[0]["close_price"]) if idx_rows.data else None
        except Exception:
            idx_close = None
        idx_prev = None
        try:
            prev_rows = (
                db.get_client()
                .table("psx_daily_eod")
                .select("close_price")
                .eq("ticker", "KSE100")
                .eq("trade_date", (session - timedelta(days=1)).isoformat())
                .limit(1)
                .execute()
            )
            idx_prev = float(prev_rows.data[0]["close_price"]) if prev_rows.data else None
        except Exception:
            idx_prev = None
        if idx_close is not None and idx_prev is not None and idx_close > idx_prev:
            conf = int(min(100, 70 + (1 - ratio) * 30))
            reason = (
                f"KSE100 up {(idx_close/idx_prev - 1)*100:.2f}% but A/D ratio {ratio:.2f} "
                f"(< 0.8) - divergent session; market breadth weak beneath the surface."
            )
            out.append({
                "trade_date": session.isoformat(),
                "ticker": "KSE100",
                "signal_type": "MARKET_BREADTH",
                "confidence_score": conf,
                "catalyst_reason": reason,
                "sector": "INDEX",
            })

    written = _upsert_signals(out)
    LOGGER.info(
        "quant signals written: %d rows (%d volume_expansion, %d institutional_accumulation, "
        "%d retail_trap_short, %d market_breadth)",
        written,
        sum(1 for r in out if r["signal_type"] == "VOLUME_EXPANSION"),
        sum(1 for r in out if r["signal_type"] == "INSTITUTIONAL_ACCUMULATION"),
        sum(1 for r in out if r["signal_type"] == "RETAIL_TRAP_SHORT"),
        sum(1 for r in out if r["signal_type"] == "MARKET_BREADTH"),
    )
    return {
        "volume_expansion": sum(1 for r in out if r["signal_type"] == "VOLUME_EXPANSION"),
        "institutional_accumulation": sum(1 for r in out if r["signal_type"] == "INSTITUTIONAL_ACCUMULATION"),
        "retail_trap_short": sum(1 for r in out if r["signal_type"] == "RETAIL_TRAP_SHORT"),
        "market_breadth": sum(1 for r in out if r["signal_type"] == "MARKET_BREADTH"),
        "written": written,
    }
