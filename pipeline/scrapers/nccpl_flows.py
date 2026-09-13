"""NCCPL FIPI/LIPI participant-flow scraper.

NCCPL's own portal blocks datacenter IPs (WAF 403), but the Standard
Capital Securities (scstrade) mirror exposes the exact NCCPL dataset via a
small JSON API, verified live on 2026-09-10:

  POST https://scstrade.com/FIPILIPI.aspx/loadmainsum
       body {"date1":"MM/DD/YYYY","date2":"MM/DD/YYYY"}
       ->  {"d":[{FLType, FLBuyValue, FLSellValue, FLNetValueUSD}]}  (USD mn)

  POST https://scstrade.com/FIPILIPI.aspx/loadmain
       ->  {"d":[{MType, FLType, NetValue}]}  per-participant net, USD mn

  POST .../loadfipisector  ->  per participant x sector rows with
       FLBuyValue/FLSellValue/FLNetValueUSD (USD mn)

Values are USD millions; they are converted to PKR with the free
open.er-api.com USD/PKR rate (falling back to a configured constant).
`loadmain` is the authoritative participant breakdown, so it is the
primary source; `loadmainsum` (FIPI/LIPI totals) fills the
FOREIGN_TOTAL/LOCAL_TOTAL rollups.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, Optional

import requests

from pipeline.http_client import http_get, http_post, json_headers
from pipeline.parsing import to_number

LOGGER = logging.getLogger(__name__)

SCSTRADE_URL = "https://scstrade.com/FIPILIPI.aspx"
FX_URL = "https://open.er-api.com/v6/latest/USD"

# scstrade FLType labels -> canonical participant_type values stored in DB.
PARTICIPANT_MAP: dict[str, str] = {
    "OVERSEAS PAKISTANI": "OVERSEAS PAKISTANIS",
    "FOREIGN CORPORATES": "FOREIGN CORPORATES",
    "FOREIGN INDIVIDUAL": "FOREIGN INDIVIDUALS",
    "INDIVIDUALS": "INDIVIDUALS",
    "MUTUAL FUNDS": "MUTUAL FUNDS",
    "BROKER PROPRIETARY TRADING": "BROKER PROPRIETARY",
    "BANKS / DFI": "BANKS",
    "COMPANIES": "COMPANIES",
    "INSURANCE COMPANIES": "INSURANCE",
    "OTHER ORGANIZATION": "OTHER ORGANIZATIONS",
    "NBFC": "NBFC",
}

INSTITUTIONAL_PARTICIPANTS = {
    "MUTUAL FUNDS",
    "FOREIGN CORPORATES",
    "BANKS",
    "INSURANCE",
    "COMPANIES",
    "BROKER PROPRIETARY",
    "NBFC",
    "OVERSEAS PAKISTANIS",
}

DEFAULT_SECTOR = "ALL"


def fetch_usd_pkr(fallback: float = 284.0) -> float:
    """Current USD/PKR from a free API; returns fallback on any failure."""
    try:
        response = http_get(FX_URL, timeout=15.0)
        rate = float(response.json()["rates"]["PKR"])
        if 50.0 < rate < 1000.0:
            return rate
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("FX lookup failed (%s); using fallback %.1f", exc, fallback)
    return fallback


def _post_scstrade(endpoint: str, day: date) -> list[dict[str, Any]]:
    """POST one scstrade endpoint and unwrap its ASP.NET {"d": [...]} body."""
    body = {
        "date1": day.strftime("%m/%d/%Y"),
        "date2": day.strftime("%m/%d/%Y"),
    }
    response = http_post(
        f"{SCSTRADE_URL}/{endpoint}",
        json_body=body,
        headers=json_headers(SCSTRADE_URL + "/" + endpoint),
    )
    payload = response.json()
    rows = payload.get("d") if isinstance(payload, dict) else payload
    return rows if isinstance(rows, list) else []


def _mk_flow(
    trade_date: date,
    participant: str,
    buy_usd: Optional[float],
    sell_usd: Optional[float],
    fx: float,
    sector: str = DEFAULT_SECTOR,
) -> Optional[dict[str, Any]]:
    """Build one nccpl_fipi_lipi row from USD-million values."""
    if participant not in PARTICIPANT_MAP.values() and participant not in PARTICIPANT_MAP:
        participant = participant.strip().upper()
    canonical = PARTICIPANT_MAP.get(participant, participant)
    if not canonical:
        return None
    buy = buy_usd * 1_000_000 * fx if buy_usd is not None else None
    sell = sell_usd * 1_000_000 * fx if sell_usd is not None else None
    if buy is None and sell is None:
        return None
    if buy is None or sell is None:
        net = (buy or 0.0) + (sell or 0.0)
    else:
        net = buy + sell  # scstrade sell values are already negative
    return {
        "trade_date": trade_date.isoformat(),
        "participant_type": canonical,
        "sector_name": sector,
        "buy_pkr": round(buy, 2) if buy is not None else None,
        "sell_pkr": round(sell, 2) if sell is not None else None,
        "net_pkr": round(net, 2),
    }


def fetch_flows_for_date(day: date, *, fx: Optional[float] = None) -> list[dict]:
    """Participant-level flows for one trading day, converted to PKR."""
    fx = fx if fx is not None else fetch_usd_pkr()
    records: list[dict] = []
    seen: set[str] = set()

    try:
        rows = _post_scstrade("loadmain", day)
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("loadmain failed for %s: %s", day, exc)
        rows = []

    for row in rows:
        participant = str(row.get("FLType") or "").strip().upper()
        net = to_number(row.get("NetValue"))
        if not participant or net is None:
            continue
        record = _mk_flow(trade_date=day, participant=participant,
                          buy_usd=None, sell_usd=None, fx=fx)
        if record is None:
            continue
        # loadmain only provides net -> derive one-sided flows as unknown
        record["buy_pkr"] = None
        record["sell_pkr"] = None
        record["net_pkr"] = round(net * 1_000_000 * fx, 2)
        key = (record["participant_type"], record["sector_name"])
        if key not in seen:
            seen.add(key)
            records.append(record)

    if not records:
        LOGGER.warning("loadmain empty for %s; trying loadmainsum", day)

    try:
        rows = _post_scstrade("loadmainsum", day)
        for row in rows:
            label = str(row.get("FLType") or "").strip().upper()
            buy = to_number(row.get("FLBuyValue"))
            sell = to_number(row.get("FLSellValue"))
            if not label:
                continue
            participant = {
                "FIPI": "FOREIGN TOTAL",
                "LIPI": "LOCAL TOTAL",
            }.get(label, label)
            if participant in {"FOREIGN TOTAL", "LOCAL TOTAL"}:
                record = _mk_flow(day, participant, buy, sell, fx)
                if record:
                    key = (record["participant_type"], record["sector_name"])
                    if key not in seen:
                        seen.add(key)
                        records.append(record)
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("loadmainsum failed for %s: %s", day, exc)

    LOGGER.info("flows %s: %d participant rows", day, len(records))
    return records


def fetch_sector_flows_for_date(day: date, *, fx: Optional[float] = None) -> list[dict]:
    """Participant x sector flows (FIPI/LIPI sector tables), in PKR."""
    fx = fx if fx is not None else fetch_usd_pkr()
    records: list[dict] = []
    try:
        rows = _post_scstrade("loadfipisector", day)
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("loadfipisector failed for %s: %s", day, exc)
        return records

    for row in rows:
        participant = str(row.get("FLTypeNew") or "").strip().upper()
        sector = str(row.get("FLSectorName") or "").strip()
        sector = sector.replace("(mn$)", "").strip().upper() or DEFAULT_SECTOR
        if sector == "DEBT MARKET":
            continue  # equity signals only
        buy = to_number(row.get("FLBuyValue"))
        sell = to_number(row.get("FLSellValue"))
        record = _mk_flow(day, participant, buy, sell, fx, sector=sector)
        if record:
            records.append(record)

    LOGGER.info("sector flows %s: %d rows", day, len(records))
    return records


def fetch_recent_flows(
    days: int = 6, *, today: Optional[date] = None
) -> list[dict]:
    """Walk back from ``today`` collecting the most recent ``days`` sessions.

    Weekends and PSX holidays simply return empty payloads and are skipped,
    so we probe a slightly wider calendar window than the session count.
    """
    today = today or date.today()
    all_records: list[dict] = []
    fx: Optional[float] = None
    probe_skip = 0
    collected_days = 0
    cursor = today

    while collected_days < days and probe_skip < 10:
        day_flows: list[dict] = []
        try:
            if fx is None:
                fx = fetch_usd_pkr()
            day_flows = fetch_flows_for_date(cursor, fx=fx)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("flow fetch %s failed: %s", cursor, exc)

        if day_flows:
            collected_days += 1
            all_records.extend(day_flows)
            try:
                all_records.extend(fetch_sector_flows_for_date(cursor, fx=fx))
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("sector flows %s failed: %s", cursor, exc)
        else:
            probe_skip += 1
        cursor -= timedelta(days=1)

    LOGGER.info(
        "recent flows: %d rows across %d sessions", len(all_records), collected_days
    )
    return all_records
