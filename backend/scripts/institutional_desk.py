#!/usr/bin/env python3
"""institutional_desk.py - the six-layer pre-breakout & alpha framework.

Every published setup is scored against the same six layers:

  1. Macro / liquidity        market breadth plus the name's own liquidity
  2. Sector seasonality       current-month accumulation window
  3. NCCPL + insider flow     10-session FIPI/LIPI absorption, Form 31/32 filings
  4. Catalysts                low float, LoR/TERP, PUCARS material information
  5. Volume setup             20-30% dry-up of the 50d average, >2x pocket pivot
  6. Risk / exit              no 15% free-float distribution, 30-session time-stop

The confluence score is simply the number of layers satisfied (1-6). The board
shows the five highest-scoring names diversified across sectors; the alert board
shows distribution, free-float turnover, dead-capital and stale-tape flags.

Pure-ish: reads through the sqlite3 cursor it is handed, writes nothing.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

from quant_modules import (CONFLUENCE_LAYERS, FREE_FLOAT_DISTRIBUTION_PCT, TIME_STOP_SESSIONS,
                           calc_catalyst, calc_confluence_score, calc_flow_streak,
                           calc_float_turnover, calc_institutional_flows, calc_lor_spread,
                           calc_low_float, calc_time_stop)

CATALYST_WINDOW_DAYS = 60
NCCPL_SECTOR_NAMES = {
    "Cement": "CEMENT",
    "Banking": "COMMERCIAL BANKS",
    "Fertilizer": "FERTILIZER",
    "Food": "FOOD AND PERSONAL CARE PRODUCTS",
    "Energy": "OIL AND GAS EXPLORATION COMPANIES",
    "Oil Marketing": "OIL AND GAS MARKETING COMPANIES",
    "Power": "POWER GENERATION AND DISTRIBUTION",
    "Tech": "TECHNOLOGY AND COMMUNICATION",
    "Textile Composite": "TEXTILE COMPOSITE",
}
DEFAULT_NCCPL_SECTOR = "ALL OTHER SECTORS"
CATALYST_WEIGHTS = {"FORM 31 INSIDER": 18, "FORM 32 SUBSTANTIAL": 18, "PUBLIC INTENTION": 16,
                    "ACQUISITION": 15, "SCHEME OF ARRANGEMENT": 14, "DEMERGER": 13,
                    "NON-CORE ASSET SALE": 13, "LAND SALE": 12, "BUY-BACK": 11,
                    "RESUMPTION": 9, "RIGHT ISSUE": 7}
STRATEGY_PRIORITY = ("LoR TRAP", "INSIDER / FORM 31-32", "PUCARS CATALYST", "LOW-FLOAT SQUEEZE",
                     "FIPI/LIPI ABSORPTION", "SEASONAL ALIGNED", "POCKET PIVOT", "VOLUME DRY-UP")
INSIDER_TAGS = {"FORM 31 INSIDER", "FORM 32 SUBSTANTIAL"}
MACRO_BREADTH_FLOOR_PCT = 40.0   # share of the liquid tape above its 50d SMA
MIN_CONFLUENCE = 3               # a setup needs at least half the framework
TIME_STOP_CALENDAR_DAYS = 42     # ~30 PSX sessions of dead capital


def load_seasonality(path: Path) -> tuple[dict, str | None]:
    """Ticker -> seasonal status/60-day stats from the published matrix."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, None
    month = (payload.get("meta") or {}).get("currentMonthLabel")
    by_ticker: dict[str, dict] = {}
    for sector_row in payload.get("sectors") or []:
        for rec in sector_row.get("tickers") or []:
            stats = ((rec.get("accumulationWindowStats") or {}).get("forward60") or {})
            by_ticker[rec.get("ticker")] = {
                "sector": rec.get("sector") or sector_row.get("sector"),
                "status": rec.get("status"),
                "month": month,
                "rangePositionPct": (rec.get("position") or {}).get("rangePositionPct"),
                "winRate60Pct": stats.get("winRatePct"),
                "avgForward60Pct": stats.get("avgPct"),
            }
    return by_ticker, month


def catalyst_events(cur, session_date, window_days: int = CATALYST_WINDOW_DAYS) -> dict[str, list[dict]]:
    """Recent PUCARS / board-meeting catalysts per ticker, newest first."""
    try:
        rows = cur.execute("SELECT ticker, trade_date, headline, disclosure_type FROM psx_disclosures "
                           "WHERE disclosure_type LIKE 'PUCARS%' OR disclosure_type LIKE 'BOARD MEETING%' "
                           "ORDER BY trade_date DESC").fetchall()
    except sqlite3.OperationalError:
        return {}
    out: dict[str, list[dict]] = {}
    for row in rows:
        ticker, stamp, headline, kind = row[0], row[1], row[2], row[3]
        try:
            day = datetime.strptime(str(stamp), "%d%b%Y").date()
        except (TypeError, ValueError):
            continue
        if (session_date - day).days > window_days:
            continue
        tag = calc_catalyst(headline)
        if not tag["catalyst"]:
            continue
        out.setdefault(ticker, []).append({"catalyst": tag["catalyst"], "headline": headline or "",
                                           "date": day.isoformat(), "source": kind})
    return out


def active_rights(cur) -> dict[str, dict]:
    """Open rights issues with a usable TERP (LoR spread)."""
    try:
        rows = cur.execute("SELECT ticker, terp, issue_price, ratio, lor_price, subscription_price, "
                           "days_remaining, purpose, sponsor_committed FROM active_right_issues "
                           "WHERE status!='CLOSED' AND terp IS NOT NULL").fetchall()
    except sqlite3.OperationalError:
        return {}
    return {row[0]: {"terp": row[1], "issuePrice": row[2], "ratio": row[3], "lorPrice": row[4],
                     "subscriptionPrice": row[5], "daysRemaining": row[6], "purpose": row[7],
                     "sponsorCommitted": bool(row[8]) if row[8] is not None else None}
            for row in rows}


def stale_tickers(cur, session: str, window: list[str]) -> list[dict]:
    """Names that traded in the window but printed no volume on the session."""
    if not window:
        return []
    marks = ", ".join("?" * len(window))
    try:
        rows = cur.execute(
            f"SELECT ticker, MAX(trade_date), SUM(CASE WHEN trade_date=? THEN COALESCE(volume,0) ELSE 0 END) "
            f"FROM psx_daily_eod WHERE trade_date IN ({marks}) GROUP BY ticker",
            (session, *window)).fetchall()
    except sqlite3.OperationalError:
        return []
    out = []
    for ticker, last_day, volume in rows:
        if volume:
            continue
        try:
            last = datetime.strptime(str(last_day), "%d%b%Y").date().isoformat()
        except ValueError:
            last = str(last_day)
        out.append({"ticker": ticker, "lastSession": last, "volume": int(volume or 0)})
    return out


def open_position_ages(cur, session_date: date, session_dates: list[date]) -> list[dict]:
    """Ledger BUY calls that have used up (or exceeded) the 30-session clock."""
    try:
        rows = cur.execute("SELECT trade_date, ticker, entry FROM v5_signal_log WHERE call='BUY'").fetchall()
    except sqlite3.OperationalError:
        return []
    seen: dict[str, dict] = {}
    for stamp, ticker, entry in rows:
        try:
            entry_day = datetime.strptime(str(stamp), "%d%b%Y").date()
        except ValueError:
            continue
        held = sum(1 for day in session_dates if entry_day < day <= session_date)
        if held < TIME_STOP_SESSIONS:
            continue
        if ticker not in seen or seen[ticker]["sessionsHeld"] < held:
            seen[ticker] = {"ticker": ticker, "entryDate": entry_day.isoformat(),
                            "entry": entry, "sessionsHeld": held}
    return list(seen.values())


def _fmt_pkr(value: float) -> str:
    return f"PKR {value / 1_000_000:+,.0f}M"


def _pkr(value) -> str:
    return "PKR —" if value is None else f"PKR {float(value):,.2f}"


def build_desk(cur, session_date: date, metrics: dict, season: dict, season_month: str | None,
               catalysts: dict, rights: dict, breadth_pct: float | None = None,
               positions: list[dict] | None = None, stale: list[dict] | None = None
               ) -> tuple[list, list, dict]:
    """Score the liquid tape across the six layers and publish both boards."""
    flows: dict[str, dict] = {}
    streaks: dict[str, dict] = {}
    setups: list[dict] = []
    alert_pool: dict[str, dict] = {}
    breadth_ok = breadth_pct is not None and breadth_pct >= MACRO_BREADTH_FLOOR_PCT
    deadline = session_date + timedelta(days=TIME_STOP_CALENDAR_DAYS)

    def sector_state(sector: str) -> tuple[dict, dict]:
        name = NCCPL_SECTOR_NAMES.get(sector, DEFAULT_NCCPL_SECTOR)
        if name not in flows:
            flows[name] = calc_institutional_flows(cur, name, session_date)
            streaks[name] = calc_flow_streak(cur, name, session_date)
        return flows[name], streaks[name]

    for ticker, m in metrics.items():
        seasonal = season.get(ticker) or {}
        sector = seasonal.get("sector") or m.get("sector") or "Miscellaneous"
        flow, streak = sector_state(sector)
        quiet = m.get("quiet") or {}
        dryup = m.get("dryup") or {}
        pivot = m.get("pivot") or {}
        low = calc_low_float(cur, ticker)
        events = catalysts.get(ticker) or []
        catalyst = events[0] if events else None
        insider = bool(catalyst and catalyst["catalyst"] in INSIDER_TAGS)
        lor = calc_lor_spread(m["close"], (rights.get(ticker) or {}).get("terp"))
        float_turn = calc_float_turnover(m.get("volume"), low.get("freeFloatShares"))
        aligned = seasonal.get("status") == "ACCUMULATION WINDOW ACTIVE"
        distributing = streak.get("streak", 0) >= 3
        absorb = flow["institutionalNetPkr"] > 0 and bool(quiet.get("absorption")) and not distributing

        ret20 = quiet.get("ret20dPct") or 0.0
        volume_ratio = quiet.get("volumeRatio20") or 0.0
        season_badge = {"status": seasonal.get("status") or "NO COVERAGE",
                        "month": seasonal.get("month"), "tailwind": aligned,
                        "winRate60Pct": seasonal.get("winRate60Pct"),
                        "avgForward60Pct": seasonal.get("avgForward60Pct"),
                        "rangePositionPct": seasonal.get("rangePositionPct")}

        # Layer 6 runs first: a name in distribution is never a buy candidate.
        if distributing:
            alert_pool[ticker] = {
                "ticker": ticker, "sector": sector, "alert": "INSTITUTIONAL DISTRIBUTION",
                "detail": f"Insurance + mutual funds net sold {streak['streak']} straight sessions "
                          f"({_fmt_pkr(streak['windowNetPkr'])} over the window) while price moved "
                          f"{ret20:+.1f}% in 20 sessions on {volume_ratio:.2f}x volume.",
                "sellStreak": streak["streak"], "instNetPkr": streak["windowNetPkr"],
                "ret20dPct": quiet.get("ret20dPct"), "seasonality": season_badge,
                "score": round(45 + streak["streak"] * 8
                               + min(20.0, abs(streak["windowNetPkr"]) / 25_000_000), 1),
            }
        if ret20 >= 15.0 and flow["retailNetPkr"] > 0 and flow["institutionalNetPkr"] < 0:
            score_alert = round(35 + ret20 / 2 + volume_ratio * 5, 1)
            if ticker not in alert_pool or alert_pool[ticker]["score"] < score_alert:
                alert_pool[ticker] = {
                    "ticker": ticker, "sector": sector, "alert": "RETAIL-CHASED EXTENSION",
                    "detail": f"Retail net bought {_fmt_pkr(flow['retailNetPkr'])} while institutions "
                              f"sold {_fmt_pkr(flow['institutionalNetPkr'])}; price ran {ret20:+.1f}% in "
                              f"20 sessions on {volume_ratio:.2f}x volume.",
                    "sellStreak": streak.get("streak", 0), "instNetPkr": flow["institutionalNetPkr"],
                    "ret20dPct": quiet.get("ret20dPct"), "seasonality": season_badge,
                    "score": score_alert,
                }
        if float_turn["distributionWarning"]:
            alert_pool[ticker] = {
                "ticker": ticker, "sector": sector, "alert": "FREE-FLOAT DISTRIBUTION",
                "detail": f"One session turned over {float_turn['floatTurnoverPct']:.1f}% of the "
                          f"{int(low['freeFloatShares']):,}-share free float — supply is being unloaded "
                          "into strength, not accumulated.",
                "sellStreak": streak.get("streak", 0), "instNetPkr": flow["institutionalNetPkr"],
                "ret20dPct": quiet.get("ret20dPct"), "seasonality": season_badge,
                "floatTurnoverPct": float_turn["floatTurnoverPct"],
                "score": round(120 + min(20.0, float_turn["floatTurnoverPct"]), 1),
            }
        if lor.get("lorTrap"):
            alert_pool[ticker] = {
                "ticker": ticker, "sector": sector, "alert": "LoR PREMIUM TRAP",
                "detail": f"Stock trades {lor['lorPremiumPct']:.1f}% above TERP {lor['terp']:.2f}; "
                          "buying the entitlement here pays the premium, not the value.",
                "sellStreak": streak.get("streak", 0), "instNetPkr": flow["institutionalNetPkr"],
                "ret20dPct": quiet.get("ret20dPct"), "seasonality": season_badge, "score": 60.0,
            }
        if distributing or float_turn["distributionWarning"]:
            continue

        # --- six-layer confluence -------------------------------------------------
        layers = {
            "macroLiquidity": bool(breadth_ok and m.get("aboveSma50")),
            "sectorSeasonality": bool(aligned),
            "institutionalFlow": bool(flow["institutionalNetPkr"] > 0 or insider),
            "catalyst": bool(catalyst or low["lowFloat"] or lor.get("lorCheap")),
            "volumeSetup": bool(dryup.get("dryUp") or pivot.get("pocketPivot")),
            "riskExit": bool(not distributing and not float_turn["distributionWarning"]),
        }
        confluence = calc_confluence_score(layers)

        tags: list[str] = []
        facts: list[str] = []
        score = confluence * 20.0
        if absorb:
            tags.append("FIPI/LIPI ABSORPTION")
            score += min(20.0, flow["institutionalNetPkr"] / 25_000_000) + (6 if quiet.get("flat") else 4)
            facts.append(f"Institutions net bought {_fmt_pkr(flow['institutionalNetPkr'])} over "
                         f"{flow['sessions']} sessions (FIPI {_fmt_pkr(flow['fipiPkr'])}, funds "
                         f"{_fmt_pkr(flow['mutualFundsPkr'])}, insurance {_fmt_pkr(flow['insurancePkr'])}) "
                         f"while price moved {ret20:+.1f}% in 20 sessions on {volume_ratio:.2f}x 20d volume.")
        if insider:
            tags.append("INSIDER / FORM 31-32")
            facts.append(f"Insider/substantial-shareholder filing ({catalyst['date']}): "
                         f"{catalyst['headline'][:150]}")
        if catalyst and not insider:
            tags.append("PUCARS CATALYST")
            score += CATALYST_WEIGHTS.get(catalyst["catalyst"], 8)
            facts.append(f"{catalyst['catalyst']} filing ({catalyst['date']}): {catalyst['headline'][:150]}")
        if low["lowFloat"]:
            tags.append("LOW-FLOAT SQUEEZE")
            score += 10 + (6 if low.get("turnaroundCatalyst") else 0)
            facts.append(f"Free float {low['freeFloatPct']:.1f}% against P/E {low['peRatio'] or '—'} / "
                         f"P/B {low['pbRatio'] or '—'} — thin supply, deep value.")
        if lor.get("lorCheap"):
            tags.append("LoR TRAP")
            score += 8
            facts.append(f"Stock trades {abs(lor['lorPremiumPct']):.1f}% below TERP {lor['terp']:.2f} — "
                         "converting the entitlement is accretive; the trap is on LoR sellers.")
        if aligned:
            tags.append("SEASONAL ALIGNED")
            score += 6
            facts.append(f"{seasonal['status']} in {seasonal.get('month') or '—'} (60d win "
                         f"{seasonal.get('winRate60Pct')}%, avg {seasonal.get('avgForward60Pct')}%).")
        if dryup.get("dryUp"):
            tags.append("VOLUME DRY-UP")
            score += 8
            facts.append(f"Supply dry-up: 5-session average volume is {dryup['dryUpRatio'] * 100:.0f}% "
                         f"of the 50-session average ({dryup['vol5dAvg']:,} vs {dryup['vol50dAvg']:,}).")
        if pivot.get("pocketPivot"):
            tags.append("POCKET PIVOT")
            score += 10
            facts.append(f"Pocket pivot ignition: up close on {pivot['volumeRatio50']:.2f}x the 50-session "
                         f"average volume, above the 10-session down-volume max "
                         f"({pivot['priorDownVolume']:,}).")
        if not tags or confluence < MIN_CONFLUENCE:
            continue

        primary = next((tag for tag in STRATEGY_PRIORITY if tag in tags), tags[0])
        entry_high = round(m["close"], 2)
        entry_low = round(min(m.get("poc") or entry_high, entry_high), 2)
        if lor.get("lorCheap") and lor.get("terp"):
            entry_high = max(entry_high, round(lor["terp"], 2))
        stop = m.get("stop") or round(entry_low * 0.92, 2)
        rules = {
            "FIPI/LIPI ABSORPTION": f"Hard exit on a close below {_pkr(stop)} (2xATR, 15% outer bound) "
                                    "or if the 10-session institutional net flips negative.",
            "PUCARS CATALYST": f"Hard exit on a close below {_pkr(stop)} or if PSX withdraws the filing.",
            "LOW-FLOAT SQUEEZE": f"Hard exit on a close below {_pkr(stop)}; a low-float squeeze "
                                 "unwinds faster than it builds.",
            "LoR TRAP": f"Hard exit on a close below {_pkr(stop)} or if the rights issue is withdrawn.",
            "SEASONAL ALIGNED": f"Hard exit on a close below {_pkr(stop)} or when the seasonal "
                                "window closes without institutional flow.",
            "VOLUME DRY-UP": f"Hard exit on a close below {_pkr(stop)}; no ignition by the time-stop "
                             "means the coil failed.",
            "POCKET PIVOT": f"Hard exit on a close below {_pkr(stop)} — the ignition day's low must "
                            "hold, otherwise the pivot failed.",
            "INSIDER / FORM 31-32": f"Hard exit on a close below {_pkr(stop)} or if the insider "
                                    "filing is corrected/withdrawn.",
        }
        ignition_text = " ".join(b for b in (
            (f"Pocket pivot: up close on {pivot['volumeRatio50']:.2f}x the 50-session average volume "
             f"({pivot['volume']:,} shares), above the 10-session down-volume max."
             if pivot.get("pocketPivot") else None),
            (f"Volume dry-up: 5-session average is {dryup['dryUpRatio'] * 100:.0f}% of the 50-session average."
             if dryup.get("dryUp") else None),
            (f"Volume below the dry-up band ({dryup['dryUpRatio'] * 100:.0f}% of the 50-session average) — "
             "dead tape; wait for a pocket pivot before entry." if dryup.get("contracting") else None),
            ("No pocket pivot yet: pre-ignition coil, enter only on a >2x volume up day." if not pivot.get("pocketPivot") else None),
        ) if b)
        setups.append({
            "ticker": ticker, "sector": sector, "strategy": primary, "tags": tags,
            "close": round(m["close"], 2), "trigger": " ".join(facts), "ignition": ignition_text,
            "confluence": {"score": confluence, "max": len(CONFLUENCE_LAYERS),
                           "layers": [{"key": key, "label": label, "met": bool(layers.get(key))}
                                      for key, label in CONFLUENCE_LAYERS]},
            "entryZone": {"low": entry_low, "high": entry_high},
            "invalidation": rules.get(primary, f"Hard exit on a close below {_pkr(stop)}."),
            "invalidationPrice": stop,
            "timeStop": {**calc_time_stop(0), "deadline": deadline.isoformat(),
                         "note": f"30-session dead-capital stop: exit by {deadline:%d %b %Y} if the "
                                 "position has not advanced."},
            "floatTurnover": {"pct": float_turn["floatTurnoverPct"], "warning": False,
                              "freeFloatShares": low.get("freeFloatShares")},
            "seasonality": season_badge, "score": round(score, 1),
            "metrics": {"institutionalNetPkr": flow["institutionalNetPkr"], "flowSessions": flow["sessions"],
                        "flowStreak": streak.get("streak", 0), "ret20dPct": quiet.get("ret20dPct"),
                        "volumeRatio20": quiet.get("volumeRatio20"),
                        "volumeRatio50": pivot.get("volumeRatio50"), "dryUpRatio": dryup.get("dryUpRatio"),
                        "freeFloatPct": low.get("freeFloatPct"), "peRatio": low.get("peRatio"),
                        "catalyst": catalyst["catalyst"] if catalyst else None},
        })

    # --- portfolio-level alerts ------------------------------------------------
    for position in positions or []:
        alert_pool[f"dead::{position['ticker']}"] = {
            "ticker": position["ticker"], "sector": "—", "alert": "DEAD-CAPITAL TIME-STOP",
            "detail": f"Open BUY from {position['entryDate']} has used "
                      f"{position['sessionsHeld']} sessions without resolution — the 30-session "
                      "clock is spent; recycle the capital.",
            "sellStreak": 0, "instNetPkr": 0.0, "ret20dPct": None,
            "seasonality": {"status": "NO COVERAGE", "month": season_month, "tailwind": False,
                            "winRate60Pct": None, "avgForward60Pct": None},
            "diversifyKey": "dead-capital",
            "score": round(100 + min(20, position["sessionsHeld"] - TIME_STOP_SESSIONS), 1),
        }
    for row in stale or []:
        alert_pool[f"stale::{row['ticker']}"] = {
            "ticker": row["ticker"], "sector": "—", "alert": "STALE / NON-TRADED",
            "detail": f"No volume on the session (last traded {row['lastSession']}); a setup cannot "
                      "be entered or exited in a tape this thin.",
            "sellStreak": 0, "instNetPkr": 0.0, "ret20dPct": None,
            "seasonality": {"status": "NO COVERAGE", "month": season_month, "tailwind": False,
                            "winRate60Pct": None, "avgForward60Pct": None},
            "diversifyKey": "stale",
            "score": 80.0,
        }

    def take_diverse(rows: list[dict], limit: int = 5, per_sector: int = 2,
                     per_alert: int = 5) -> list[dict]:
        """Two names per sector (and, for alerts, per alert type) at most."""
        picked, sectors, kinds = [], {}, {}
        for row in rows:
            sector = row.get("diversifyKey") or row.get("sector") or "—"
            kind = row.get("alert") or row.get("strategy") or "—"
            if sectors.get(sector, 0) >= per_sector or kinds.get(kind, 0) >= per_alert:
                continue
            picked.append(row)
            sectors[sector] = sectors.get(sector, 0) + 1
            kinds[kind] = kinds.get(kind, 0) + 1
            if len(picked) >= limit:
                break
        return picked

    setups.sort(key=lambda row: (-row["confluence"]["score"], -row["score"],
                                 (row["metrics"].get("volumeRatio20") or 99.0)))
    alerts = sorted(alert_pool.values(), key=lambda row: -row["score"])
    tracked = [flow for flow in flows.values() if flow["sessions"]]
    summary = {
        "flowSession": max((f["lastSession"] for f in tracked if f["lastSession"]), default=None),
        "flowSessions": max((f["sessions"] for f in tracked), default=0),
        "sectorsTracked": len(tracked),
        "institutionalNetPkr": round(sum(f["institutionalNetPkr"] for f in tracked), 2),
        "catalystWindowDays": CATALYST_WINDOW_DAYS,
        "catalystEvents": sum(len(v) for v in catalysts.values()),
        "rightsTracked": len(rights),
        "seasonalityMonth": season_month,
        "macroBreadthPct": round(breadth_pct, 1) if breadth_pct is not None else None,
        "macroBreadthFloorPct": MACRO_BREADTH_FLOOR_PCT,
        "strategyTags": list(STRATEGY_PRIORITY),
        "frameworkLayers": [{"key": key, "label": label} for key, label in CONFLUENCE_LAYERS],
        "minConfluence": MIN_CONFLUENCE,
        "timeStopSessions": TIME_STOP_SESSIONS,
        "dryUpBandPct": [20, 30],
        "pocketPivotMultiple": 2.0,
        "freeFloatDistributionPct": FREE_FLOAT_DISTRIBUTION_PCT,
        "boards": {"setups": 5, "alerts": 5},
    }
    return take_diverse(setups), take_diverse(alerts, per_alert=2), summary
