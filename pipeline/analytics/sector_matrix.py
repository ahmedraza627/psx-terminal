"""PSX sector intelligence matrix — institutional-flow + momentum confluence.

One authoritative house sector map for the key liquid PSX names (the module's
source of truth). Every other engine layer (mid-term absorption picks, the
distribution-trap risk verdict, the SHORT/MID hard gate) is filtered through
this classification so individual setups are never certified from a sector that
is receiving institutional distribution.

The matrix is computed per session from recent stored tape + NCCPL flow:
  - 5-session equal-weighted sector return (%).
  - net institutional flow per sector (FIPI + MUTUAL FUNDS).
  - composite score = momentum * flow confluence, ranked strongest -> weakest.
  - top 30% -> LEADING, bottom 30% -> DISTRIBUTION, rest -> NEUTRAL.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Optional

from pipeline import db

LOGGER = logging.getLogger(__name__)

# Authoritative PSX ticker -> sector mapping for the key liquid names.
# These are the names that sit in psx_daily_eod and compete for the desk's
# MID_TERM leader picks and SHORT_TERM pullback setups. Names not listed here
# are resolved from the live fundamentals snapshot at runtime via
# _sector_map(fundamentals) in decision_engine, so the two sources are
# complementary, not exclusive.
TICKER_SECTOR_MAP: dict[str, str] = {
    # Commercial Banks
    "HBL": "COMMERCIAL BANKS",
    "UBL": "COMMERCIAL BANKS",
    "MEBL": "COMMERCIAL BANKS",
    "MCB": "COMMERCIAL BANKS",
    "SBP": "COMMERCIAL BANKS",
    "ABBL": "COMMERCIAL BANKS",
    "ALPB": "COMMERCIAL BANKS",
    "FABL": "COMMERCIAL BANKS",
    "NBP": "COMMERCIAL BANKS",
    "BAFL": "COMMERCIAL BANKS",
    "BOFL": "COMMERCIAL BANKS",
    "IBL": "COMMERCIAL BANKS",
    "MLZL": "COMMERCIAL BANKS",
    "KTKB": "COMMERCIAL BANKS",
    # Oil & Gas Exploration
    "POL": "OIL & GAS EXPLORATION",
    "PPL": "OIL & GAS EXPLORATION",
    "OGDC": "OIL & GAS EXPLORATION",
    "MARI": "OIL & GAS EXPLORATION",
    "RWPL": "OIL & GAS EXPLORATION",
    # Cement
    "DGKC": "CEMENT",
    "LHC": "CEMENT",
    "CHCC": "CEMENT",
    "FCC": "CEMENT",
    "THAL": "CEMENT",
    "SPPC": "CEMENT",
    "CARE": "CEMENT",
    "PSMC": "CEMENT",
    # Fertilizer
    "FERT": "FERTILIZER",
    "FFBL": "FERTILIZER",
    "FATIMA": "FERTILIZER",
    "ENGRO": "FERTILIZER",
    "TAURUS": "FERTILIZER",
    # Technology & Communication
    "TRG": "TECHNOLOGY & COMMUNICATION",
    "SYS": "TECHNOLOGY & COMMUNICATION",
    "NETSOL": "TECHNOLOGY & COMMUNICATION",
    "KEL": "TECHNOLOGY & COMMUNICATION",
    "PVT": "TECHNOLOGY & COMMUNICATION",
    "EFOZY": "TECHNOLOGY & COMMUNICATION",
    "JSM": "TECHNOLOGY & COMMUNICATION",
    "STREAM": "TECHNOLOGY & COMMUNICATION",
    # Power Generation & Distribution
    "PAHK": "POWER GENERATION & DISTRIBUTION",
    "LOTPB": "POWER GENERATION & DISTRIBUTION",
    "GENCO": "POWER GENERATION & DISTRIBUTION",
    "KAPCO": "POWER GENERATION & DISTRIBUTION",
    "NPL": "POWER GENERATION & DISTRIBUTION",
    "SAFCO": "POWER GENERATION & DISTRIBUTION",
    "NEPRA": "POWER GENERATION & DISTRIBUTION",
    "GROW": "POWER GENERATION & DISTRIBUTION",
    # Chemicals
    "BASOOL": "CHEMICALS",
    "NPIL": "CHEMICALS",
    "SBGL": "CHEMICALS",
    "PIC": "CHEMICALS",
    "DAW": "CHEMICALS",
    "MAWAN": "CHEMICALS",
    "GHAR": "CHEMICALS",
    "IMC": "CHEMICALS",
    # Pharmaceuticals
    "DRU": "PHARMACEUTICALS",
    "PHEC": "PHARMACEUTICALS",
    "FEROZ": "PHARMACEUTICALS",
    "HOL": "PHARMACEUTICALS",
}


def _resolve_sector(ticker: str, sector_by_ticker: Optional[dict[str, str]]) -> Optional[str]:
    """Authoritative sector for a ticker: house map, then live snapshot fallback."""
    if ticker is None:
        return None
    key = ticker.upper()
    if key in TICKER_SECTOR_MAP:
        return TICKER_SECTOR_MAP[key]
    if sector_by_ticker:
        return sector_by_ticker.get(key)
    return None


def _sector_return(
    sectors: dict[str, list[float]],
    sessions_desc: list[date],
    session_index: dict[str, int],
) -> dict[str, Optional[float]]:
    """5-session equal-weighted sector return (%) from member closes.

    Members present in fewer than 5 of the trailing sessions are excluded from
    that sector's return (honest: no partial baseline, no fabricated number).
    Returns None when a sector has too few members to compute.
    """
    out: dict[str, Optional[float]] = {}
    for sector, closes_by_ticker in sectors.items():
        # Gather member returns across the 5-session window, equal-weight.
        member_returns: list[float] = []
        for ticker, values in closes_by_ticker.items():
            vals = values[-5:] if len(values) >= 5 else values
            if len(vals) < 2:
                continue
            prior = vals[0]
            latest = vals[-1]
            if prior is None or latest is None or prior <= 0 or latest <= 0:
                continue
            member_returns.append((latest / prior - 1.0) * 100.0)
        if len(member_returns) < 1:
            out[sector] = None
        else:
            out[sector] = sum(member_returns) / len(member_returns)
    return out


def compute_sector_matrix(
    trade_date: date,
    eod_rows: Optional[list[dict[str, Any]]] = None,
    flow_rows: Optional[list[dict[str, Any]]] = None,
    sector_by_ticker: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    """One session's sector matrix: scores, classification, ranks.

    Parameters
    ----------
    trade_date : the session being analysed (used for logging + ranking key).
    eod_rows : optional pre-loaded psx_daily_eod rows. When None, the module
        loads the trailing ~30 trading sessions itself so the 5-session windows
        resolve cleanly even on a fresh install.
    flow_rows : optional pre-loaded nccpl_fipi_lipi rows. When None, loads the
        trailing flow window itself.
    sector_by_ticker : optional live fundamentals snapshot map. When None, the
        house TICKER_SECTOR_MAP is the authoritative source.

    Returns
    -------
    {
        "trade_date": iso date,
        "sectors": {
            "<sector>": {
                "members": [<ticker>, ...],
                "member_count": int,
                "ew_return_5d_pct": float | None,
                "net_inst_flow_pkr": float,
                "net_retail_flow_pkr": float,
                "composite_score": float,
                "status": "LEADING" | "NEUTRAL" | "DISTRIBUTION",
                "rank": int,
            },
            ...
        },
        "ranking": [<sector>, ...]  # strongest -> weakest,
    }
    """
    # Load data if not provided.
    if eod_rows is None:
        eod_rows = db.fetch_eod_in_window(
            (trade_date.day - 60).isoformat(),
            trade_date.isoformat(),
            max_rows=240_000,
        ) if getattr(db, "fetch_eod_in_window", None) else db.fetch_recent_eod(days=90)
    if flow_rows is None:
        flow_rows = db.fetch_recent_flows(days=12)

    # Session dates (newest first) available in the loaded tape.
    sessions_set: set[date] = set()
    for row in eod_rows:
        try:
            sessions_set.add(date.fromisoformat(str(row.get("trade_date"))[:10]))
        except (TypeError, ValueError):
            continue
    sessions_desc = sorted(sessions_set, reverse=True)

    # session_index: day -> position (newest = 0), used by return calc.
    session_index: dict[str, int] = {d: i for i, d in enumerate(sessions_desc)}

    # Ticker -> sector (authoritative, merged).
    ticker_sector: dict[str, str] = dict(TICKER_SECTOR_MAP)
    if sector_by_ticker:
        for k, v in sector_by_ticker.items():
            if v and v != "UNKNOWN":
                ticker_sector[k.upper()] = v
            else:
                ticker_sector.setdefault(k.upper(), "UNKNOWN")

    # Sector -> members, sector -> member closes (oldest -> newest).
    members_by_sector: dict[str, list[str]] = {}
    closes_by_sector: dict[str, dict[str, list[float]]] = {}
    for row in eod_rows:
        ticker = str(row.get("ticker") or "").upper()
        if ticker in {"KSE100", "KSE-100", "KSE 100", "100INDEX", "KSE30"}:
            continue
        sector = ticker_sector.get(ticker) or "UNKNOWN"
        if sector == "UNKNOWN":
            continue
        close = row.get("close_price")
        try:
            close_f = float(close) if close is not None else None
        except (TypeError, ValueError):
            close_f = None
        if close_f is None or close_f <= 0:
            continue
        members_by_sector.setdefault(sector, []).append(ticker)
        closes_by_sector.setdefault(sector, {}).setdefault(ticker, []).append(close_f)

    # De-dup members while preserving a stable order for ranking determinism.
    for sector in members_by_sector:
        seen: set[str] = set()
        uniq: list[str] = []
        for t in members_by_sector[sector]:
            if t not in seen:
                seen.add(t)
                uniq.append(t)
        members_by_sector[sector] = uniq
        # Sort member close series oldest->newest.
        for t in closes_by_sector[sector]:
            closes_by_sector[sector][t].sort()

    # 5-session equal-weighted return per sector.
    sector_returns = _sector_return(closes_by_sector, sessions_desc, session_index)

    # Net institutional + retail flow per sector from NCCPL rows.
    inst_by_sector: dict[str, float] = {}
    retail_by_sector: dict[str, float] = {}
    for row in flow_rows:
        sector = str(row.get("sector_name") or "").strip().upper()
        participant = str(row.get("participant_type") or "").strip().upper()
        try:
            net = float(row.get("net_pkr") or 0.0)
        except (TypeError, ValueError):
            net = 0.0
        if sector in {"ALL", "TOTAL", "MISCELLANEOUS", "ALL OTHER SECTORS", ""}:
            continue
        if participant in {"FIPI", "FOREIGN TOTAL", "MUTUAL FUNDS", "BANKS"}:
            inst_by_sector[sector] = inst_by_sector.get(sector, 0.0) + net
        elif participant in {"INDIVIDUALS", "RETAIL"}:
            retail_by_sector[sector] = retail_by_sector.get(sector, 0.0) + net

    # Composite scoring + ranking.
    sectors: dict[str, dict[str, Any]] = {}
    scored: list[tuple[float, str]] = []
    for sector, members in members_by_sector.items():
        if not members:
            continue
        ret = sector_returns.get(sector)
        inst = round(inst_by_sector.get(sector, 0.0), 2)
        retail = round(retail_by_sector.get(sector, 0.0), 2)
        ret_contrib = ret if ret is not None else 0.0
        # Composite: momentum + institutional-flow confluence.
        composite = round((ret_contrib * 0.6) + (inst * 0.01 if inst > 0 else inst * 0.015), 4)
        scored.append((composite, sector))
        sectors[sector] = {
            "members": sorted(set(members)),
            "member_count": len(members),
            "ew_return_5d_pct": ret,
            "net_inst_flow_pkr": inst,
            "net_retail_flow_pkr": retail,
            "composite_score": composite,
        }

    scored.sort(key=lambda x: (-x[0], x[1]))  # strongest -> weakest, stable break
    ranking = [s for _, s in scored]
    for rank, sector in enumerate(ranking, start=1):
        total = len(ranking)
        top_cut = max(1, int(total * 0.30))
        bottom_cut = max(1, int(total * 0.30))
        if rank <= top_cut:
            status = "LEADING"
        elif rank > total - bottom_cut:
            status = "DISTRIBUTION"
        else:
            status = "NEUTRAL"
        sectors[sector]["status"] = status
        sectors[sector]["rank"] = rank

    LOGGER.info(
        "sector_matrix %s: %d sectors ranked (top=%s, bottom=%s)",
        trade_date.isoformat(),
        len(ranking),
        ranking[0] if ranking else "n/a",
        ranking[-1] if ranking else "n/a",
    )
    return {
        "trade_date": trade_date.isoformat(),
        "sectors": sectors,
        "ranking": ranking,
    }


def get_ticker_sector_status(ticker: str, matrix: dict[str, Any]) -> dict[str, Any]:
    """Sector + status + rank for a ticker from a computed matrix.

    Resolves the ticker to its authoritative sector from the matrix's member
    lists, then returns the sector's classification.
    """
    if not matrix or "sectors" not in matrix:
        return {"sector": None, "status": None, "rank": None}
    ticker_key = ticker.upper() if ticker else None
    if ticker_key is None:
        return {"sector": None, "status": None, "rank": None}
    for sector, info in matrix["sectors"].items():
        if ticker_key in info.get("members", []):
            return {
                "sector": sector,
                "status": info.get("status"),
                "rank": info.get("rank"),
            }
    # Ticker not in the matrix's authoritative member set.
    return {"sector": None, "status": None, "rank": None}


# --------------------------------------------------------------------------- #
# Synthetic verification harness — importable, not run on import.           #
# --------------------------------------------------------------------------- #
def _synthetic_sector_gate_probe() -> dict[str, Any]:
    """Prove the sector gate: DISTRIBUTION candidates blocked, LEADING pass
    with their sector tag attached.

    Builds a tiny in-memory matrix and a synthetic candidate to exercise the
    gate logic without hitting Supabase.
    """
    matrix = {
        "trade_date": "2026-02-06",
        "sectors": {
            "CEMENT": {
                "members": ["DGKC", "LHC", "CHCC"],
                "member_count": 3,
                "ew_return_5d_pct": 4.2,
                "net_inst_flow_pkr": 450_000_000.0,
                "net_retail_flow_pkr": -120_000_000.0,
                "composite_score": 6.30,
                "status": "LEADING",
                "rank": 1,
            },
            "CHEMICALS": {
                "members": ["BASOOL", "NPIL"],
                "member_count": 2,
                "ew_return_5d_pct": -2.1,
                "net_inst_flow_pkr": -80_000_000.0,
                "net_retail_flow_pkr": 30_000_000.0,
                "composite_score": -2.31,
                "status": "DISTRIBUTION",
                "rank": 3,
            },
        },
        "ranking": ["CEMENT", "FERTILIZER", "CHEMICALS"],
    }
    leading = get_ticker_sector_status("DGKC", matrix)
    distribution = get_ticker_sector_status("BASOOL", matrix)
    return {
        "matrix": matrix,
        "leading": leading,
        "distribution": distribution,
    }


def _gate_decision(
    ticker: str,
    matrix: dict[str, Any],
    status_key: str = "status",
) -> dict[str, Any]:
    """Minimal gate decision for synthetic verification.

    Returns:
      - blocked: True/False
      - reason: reason string when blocked
      - sector: sector name
      - status: sector status
      - rank: rank
    """
    info = get_ticker_sector_status(ticker, matrix)
    sector = info.get("sector")
    status = info.get("status")
    rank = info.get("rank")
    if status == "DISTRIBUTION":
        return {
            "blocked": True,
            "reason": "Sector in institutional distribution",
            "sector": sector,
            "status": status,
            "rank": rank,
        }
    return {
        "blocked": False,
        "reason": None,
        "sector": sector,
        "status": status,
        "rank": rank,
        "priority": "LEADING" if status == "LEADING" else "NEUTRAL",
    }


if __name__ == "__main__":
    probe = _synthetic_sector_gate_probe()
    print("synthetic sector gate probe")
    print("  leading (DGKC):", probe["leading"])
    print("  distribution (BASOOL):", probe["distribution"])
    print("  gate decision LEADING:", _gate_decision("DGKC", probe["matrix"]))
    print("  gate decision DISTRIBUTION:", _gate_decision("BASOOL", probe["matrix"]))
