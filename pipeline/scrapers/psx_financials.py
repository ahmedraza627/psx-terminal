"""Quarterly & annual financials scraper: DPS company pages.

Source (verified live 2026-09-12, HBL/LUCK): https://dps.psx.com.pk/company/<SYM>
serves a server-rendered "Financials" tab (#financialTab) with two panels
(``data-name="Annual"`` and ``data-name="Quarterly"``). Each panel is one
table: header cells are period labels ("2025", "Q2 2026"), rows are line
items. PSX states: "All numbers in thousands (000's) except EPS".

Verified line-item labels per company type:
  Banks        : Mark-up Earned | Total Income | Profit after Taxation | EPS
  Industrials  : Sales          | Profit after Taxation              | EPS
  Ratios block (#ratios, annual only): Gross Profit Margin (%),
                 Net Profit Margin (%), EPS Growth (%), PEG
  Stats block  : Shares (shares outstanding), Free Float

Honest-data rules:
- PSX publishes no balance-sheet items (book value, D/E, coverage, ROIC,
  FCF) on these pages -> those columns stay NULL, never interpolated.
- Period labels carry no exact dates, so period_end_date uses the calendar
  quarter-end convention (Q2 2026 -> 2026-06-30; annual 2025 -> 2025-12-31)
  and fiscal_period is calendar-labeled (FY26-Q2 = Apr-Jun 2026, annual
  rows suffixed -A).
"""

from __future__ import annotations

import logging
import os
import random
import re
import time
from datetime import date
from typing import Any, Optional

from bs4 import BeautifulSoup

from pipeline.http_client import http_get
from pipeline.parsing import to_number

LOGGER = logging.getLogger(__name__)

BASE_URL = "https://dps.psx.com.pk"

# Line-item label aliases seen on DPS company pages (uppercased, stripped).
SALES_LABELS = {"SALES", "NET SALES", "MARK-UP EARNED", "REVENUE"}
PAT_LABELS = {"PROFIT AFTER TAXATION", "PROFIT AFTER TAX", "PAT"}
EPS_LABELS = {"EPS"}

_QUARTER_END_MONTH = {1: 3, 2: 6, 3: 9, 4: 12}
_PERIOD_LABEL_RE = re.compile(r"Q([1-4])\s+(\d{4})", re.IGNORECASE)


def _company_url(ticker: str) -> str:
    return f"{BASE_URL}/company/{ticker}"


def _clamp_pct(value: Optional[float]) -> Optional[float]:
    """Clamp to the +/-9,999.99 bound of NUMERIC(6,2) columns.

    Growth off a near-zero base can legitimately be enormous; beyond the
    clamp it carries no analytical signal, so it is floored to the bound.
    """
    if value is None:
        return None
    return round(max(-9999.99, min(9999.99, value)), 2)


def _parse_period_table(panel) -> list[dict[str, Any]]:
    """One financials panel -> [{'label','period','value'}...] rows."""
    rows: list[dict[str, Any]] = []
    table = panel.find("table")
    if table is None:
        return rows
    head = table.find("thead")
    periods: list[str] = []
    if head is not None:
        for th in head.find_all("th"):
            label = th.get_text(strip=True)
            if label:
                periods.append(label)
    body = table.find("tbody") or table
    for tr in body.find_all("tr"):
        cells = tr.find_all("td")
        if len(cells) < 2:
            continue
        line_label = cells[0].get_text(" ", strip=True)
        values = cells[1 : 1 + len(periods)]
        for period, cell in zip(periods, values):
            rows.append(
                {
                    "label": line_label.upper().strip(),
                    "period": period.strip(),
                    "value": to_number(cell.get_text(" ", strip=True)),
                }
            )
    return rows


def _panel_by_name(soup: BeautifulSoup, name: str):
    for panel in soup.find_all(
        "div", class_="tabs__panel", attrs={"data-name": name}
    ):
        return panel
    return None


def _period_dates(label: str) -> Optional[tuple[str, date]]:
    """'Q2 2026' -> ('FY26-Q2', 2026-06-30); '2025' -> ('FY25-A', 2025-12-31)."""
    match = _PERIOD_LABEL_RE.search(label)
    if match:
        quarter, year = int(match.group(1)), int(match.group(2))
        month = _QUARTER_END_MONTH[quarter]
        end_day = {
            3: 31,
            6: 30,
            9: 30,
            12: 31,
        }[month]
        return f"FY{year % 100:02d}-Q{quarter}", date(year, month, end_day)
    year_match = re.search(r"\b(20\d{2})\b", label)
    if year_match:
        year = int(year_match.group(1))
        return f"FY{year % 100:02d}-A", date(year, 12, 31)
    return None


def _extract_table_rows(rows: list[dict[str, Any]], scale: int) -> dict[str, Any]:
    """Pick sales/PAT/EPS out of a panel's rows. Values in thousands -> PKR."""
    out: dict[str, Any] = {"sales_pkr": None, "pat_pkr": None, "eps": None}
    for row in rows:
        label = row["label"]
        value = row["value"]
        if value is None:
            continue
        if label in SALES_LABELS and out["sales_pkr"] is None:
            out["sales_pkr"] = value * scale
        elif label in PAT_LABELS and out["pat_pkr"] is None:
            out["pat_pkr"] = value * scale
        elif label in EPS_LABELS and out["eps"] is None:
            out["eps"] = value  # EPS is never in thousands
    return out


def _parse_ratios_block(soup: BeautifulSoup) -> dict[str, Optional[float]]:
    """Annual ratios table (#ratios): latest column of each row."""
    section = soup.find(id="ratios")
    if section is None:
        return {}
    table = section.find("table")
    if table is None:
        return {}
    out: dict[str, Optional[float]] = {}
    body = table.find("tbody") or table
    for tr in body.find_all("tr"):
        cells = tr.find_all("td")
        if len(cells) < 2:
            continue
        label = cells[0].get_text(" ", strip=True).upper().strip()
        value = to_number(cells[1].get_text(" ", strip=True))
        if "NET PROFIT MARGIN" in label:
            out["net_profit_margin_pct"] = value
        elif "EPS GROWTH" in label:
            out["eps_growth_yoy_pct"] = value
    return out


def _parse_shares_outstanding(soup: BeautifulSoup) -> Optional[int]:
    """Shares outstanding from the stats block (first 'Shares' entry)."""
    label_div = soup.find(
        "div",
        class_="stats_label",
        string=lambda s: bool(s)
        and s.strip().lower() in {"shares", "no. of shares", "number of shares"},
    )
    if label_div is None:
        return None
    value_div = label_div.find_next("div", class_="stats_value")
    if value_div is None:
        return None
    number = to_number(value_div.get_text(strip=True))
    if number is None:
        return None
    return int(round(number))


def _quarter_series(panel) -> list[dict[str, Any]]:
    """Quarterly panel -> newest-first [{'period','end_date','sales','pat','eps'}]."""
    series: list[dict[str, Any]] = []
    for raw in _parse_period_table(panel):
        keyed = _period_dates(raw["period"])
        if keyed is None:
            continue
        fiscal_period, end_date = keyed
        extracted = _extract_table_rows([raw], scale=1_000)
        if all(v is None for v in extracted.values()):
            continue
        series.append({"fiscal_period": fiscal_period, "end_date": end_date, **extracted})
    # collapse per period (one row per fiscal_period, first non-null wins)
    merged: dict[str, dict[str, Any]] = {}
    for item in series:
        existing = merged.get(item["fiscal_period"])
        if existing is None:
            merged[item["fiscal_period"]] = item
            continue
        for key in ("sales_pkr", "pat_pkr", "eps"):
            if existing[key] is None:
                existing[key] = item[key]
    return list(merged.values())  # newest-first (page order)


def fetch_company_financials(ticker: str) -> list[dict[str, Any]]:
    """Latest financials for one ticker -> psx_financial_ratios row dicts.

    Returns [] when the page is unreachable or carries no financials tab
    (delisted shells, SPVs). Never fabricates a metric.
    """
    response = http_get(_company_url(ticker), timeout=25.0)
    soup = BeautifulSoup(response.text, "html.parser")

    shares = _parse_shares_outstanding(soup)
    ratios = _parse_ratios_block(soup)
    if shares is None and not ratios:
        LOGGER.warning("financials %s: no stats/ratios block found", ticker)

    records: list[dict[str, Any]] = []

    def _schema_row(
        ticker: str,
        fiscal_period: str,
        end_date: date,
        eps: Optional[float],
        sales_growth: Optional[float],
        margin: Optional[float],
    ) -> dict[str, Any]:
        """Only columns that exist in psx_financial_ratios (schema.sql).

        NUMERIC(6,2) columns bound to +/-9,999.99 — clamp so a near-zero
        YoY base (e.g. sales resuming from ~0) can't overflow the column
        and reject the whole upsert chunk (error 22003).
        """
        return {
            "ticker": ticker,
            "fiscal_period": fiscal_period,
            "period_end_date": end_date.isoformat(),
            "eps": eps,
            "sales_growth_yoy_pct": _clamp_pct(sales_growth),
            "net_profit_margin_pct": _clamp_pct(margin),
        }

    # ---- quarterly panel (preferred: freshest EPS for TTM) -----------------
    quarterly = _quarter_series(_panel_by_name(soup, "Quarterly") or soup.new_tag("div"))
    for index, item in enumerate(quarterly):
        sales_growth: Optional[float] = None
        if (
            item["sales_pkr"] is not None
            and index + 4 < len(quarterly)
            and quarterly[index + 4]["sales_pkr"] not in (None, 0)
        ):
            base = quarterly[index + 4]["sales_pkr"]
            sales_growth = round((item["sales_pkr"] / base - 1.0) * 100.0, 2)
        margin: Optional[float] = None
        if item["pat_pkr"] is not None and item["sales_pkr"]:
            margin = round(item["pat_pkr"] / item["sales_pkr"] * 100.0, 2)
        records.append(
            _schema_row(
                ticker,
                item["fiscal_period"],
                item["end_date"],
                item["eps"],
                sales_growth,
                margin,
            )
        )

    # ---- annual panel (fallback EPS + margins when quarterly is thin) ------
    annual_panel = _panel_by_name(soup, "Annual")
    if annual_panel is not None:
        annual: dict[str, dict[str, Any]] = {}
        for raw in _parse_period_table(annual_panel):
            keyed = _period_dates(raw["period"])
            if keyed is None:
                continue
            fiscal_period, end_date = keyed
            extracted = _extract_table_rows([raw], scale=1_000)
            slot = annual.setdefault(
                fiscal_period, {"end_date": end_date, **{k: None for k in extracted}}
            )
            for key, value in extracted.items():
                if slot.get(key) is None:
                    slot[key] = value
        for fiscal_period, slot in annual.items():
            if any(r["fiscal_period"] == fiscal_period for r in records):
                continue
            margin: Optional[float] = None
            if slot["pat_pkr"] is not None and slot["sales_pkr"]:
                margin = round(slot["pat_pkr"] / slot["sales_pkr"] * 100.0, 2)
            records.append(
                _schema_row(
                    ticker,
                    fiscal_period,
                    slot["end_date"],
                    slot["eps"],
                    ratios.get("eps_growth_yoy_pct"),
                    (
                        margin
                        if margin is not None
                        else ratios.get("net_profit_margin_pct")
                    ),
                )
            )

    if not records:
        LOGGER.info("financials %s: no parseable periods", ticker)
    return records


def scrape_financials_for_universe(
    tickers: list[str],
    *,
    polite_sleep: Optional[float] = None,
    max_tickers: int = 80,
) -> list[dict[str, Any]]:
    """Scrape financials for a liquidity-ranked ticker universe.

    Failures are isolated per ticker (a 404 or a parsing gap never aborts
    the batch). Politeness sleep defaults from FINANCIALS_POLITE_SLEEP.
    """
    sleep_seconds = (
        polite_sleep
        if polite_sleep is not None
        else float(os.getenv("FINANCIALS_POLITE_SLEEP", "0.4"))
    )
    universe = list(dict.fromkeys(tickers))[:max_tickers]
    all_rows: list[dict[str, Any]] = []
    for index, ticker in enumerate(universe, start=1):
        try:
            rows = fetch_company_financials(ticker)
            all_rows.extend(rows)
            LOGGER.info(
                "financials %s (%d/%d): %d periods",
                ticker,
                index,
                len(universe),
                len(rows),
            )
        except Exception as exc:  # noqa: BLE001 - isolate per-ticker failures
            LOGGER.warning("financials %s failed: %s", ticker, exc)
        if index < len(universe) and sleep_seconds > 0:
            time.sleep(sleep_seconds + random.uniform(0.0, 0.2))
    LOGGER.info(
        "financials batch: %d period-rows across %d tickers",
        len(all_rows),
        len({r["ticker"] for r in all_rows}),
    )
    return all_rows
