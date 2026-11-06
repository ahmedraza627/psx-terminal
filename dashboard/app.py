"""Institutional dark-mode workstation: Streamlit + Plotly Quant Terminal.

Features
--------
1. Top Executive Banner: NAV, Regime Badge, Asset Allocation Ribbon, Holdings Count.
2. Visual Analytics: Donut chart (pod allocation), horizontal bar chart (sector caps),
   equity curve / drawdown.
3. Morning Execution Blotter: staged delta orders with visual badges; [Mark All Fills
   Executed] writes fills into the portfolio SQLite DB.
4. Active Portfolio & Risk Audit: holdings table with per-ticker weight & bars-held;
   alert pill at 12% single-stock ceiling.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import logging
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import plotly.graph_objects as go
import streamlit as st

# --------------------------------------------------------------------------- #
# Project paths
# --------------------------------------------------------------------------- #

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
PORTFOLIO_DB = DATA_DIR / "portfolio.db"
INGEST_PSV_CSV = CACHE_DIR / "ohlcv.csv"

LOGGER = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Constants / defaults
# --------------------------------------------------------------------------- #

BASE_EQUITY_PKR = 100_000_000  # Rs 100M baseline NAV
MAX_SINGLE_STOCK_PCT = 12.0    # 12% single-stock ceiling
DEFAULT_RISK_FREE_PCT = 0.05   # 5% for T-bill reserve modeling

# Pod categories for capital allocation donut
POD_CATEGORIES = [
    "Factor Core",
    "Event-Driven",
    "DFC Pairs",
    "Macro Cash",
]

# Pre-computed colours for the donut pie (RGBA, semi-transparent)
_DONUT_COLORS = [
    "rgba(34, 177, 76, 0.8)",    # Emerald Green -> Factor Core
    "rgba(239, 68, 68, 0.8)",    # Ambar/Red -> Event-Driven
    "rgba(139, 92, 246, 0.8)",   # Violet-Purple -> DFC Pairs
    "rgba(251, 191, 36, 0.8)",   # Amber -> Macro Cash
]


# --------------------------------------------------------------------------- #
# SQLite helpers
# --------------------------------------------------------------------------- #


def _get_conn() -> sqlite3.Connection:
    """Open (or create) the portfolio SQLite database."""
    PORTFOLIO_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(PORTFOLIO_DB))
    conn.execute("PRAGMA journal_mode=WAL")
    # Ensure the core tables exist
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS portfolio_positions (
            ticker TEXT NOT NULL,
            pod TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            entry_price REAL NOT NULL,
            current_price REAL,
            bars_held INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (ticker)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS portfolio_fills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            side TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            price REAL NOT NULL,
            timestamp TEXT NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def load_positions() -> List[Dict[str, Any]]:
    """Load all portfolio positions from SQLite."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT ticker, pod, quantity, entry_price, current_price, bars_held FROM portfolio_positions"
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "ticker": r[0],
            "pod": r[1],
            "quantity": r[2],
            "entry_price": r[3],
            "current_price": r[4],
            "bars_held": r[5],
        }
        for r in rows
    ]


def save_positions(rows: List[Dict[str, Any]]) -> None:
    """Persist portfolio positions back to SQLite."""
    conn = _get_conn()
    try:
        for r in rows:
            conn.execute(
                """
                INSERT INTO portfolio_positions (ticker, pod, quantity, entry_price, current_price, bars_held)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(ticker) DO UPDATE SET
                    pod = excluded.pod,
                    quantity = excluded.quantity,
                    entry_price = excluded.entry_price,
                    current_price = excluded.current_price,
                    bars_held = excluded.bars_held
                """,
                (r["ticker"], r["pod"], r["quantity"], r["entry_price"], r["current_price"], r["bars_held"]),
            )
        conn.commit()
    finally:
        conn.close()


def add_fill(ticker: str, side: str, quantity: int, price: float) -> None:
    """Record a single fill into the portfolio fills table."""
    ts = _dt.datetime.utcnow().isoformat()
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT INTO portfolio_fills (ticker, side, quantity, price, timestamp) VALUES (?, ?, ?, ?, ?)",
            (ticker, side, quantity, price, ts),
        )
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Data loading: OHLCV cache
# --------------------------------------------------------------------------- #


def load_ohlcv_cache() -> List[Dict[str, Any]]:
    """Load the OHLCV cache from data/cache/ohlcv.csv."""
    if not INGEST_PSV_CSV.exists():
        return []
    rows: List[Dict[str, Any]] = []
    with open(INGEST_PSV_CSV, "r", newline="", encoding="utf-8") as f:
        reader = DictReader(f)
        for r in reader:
            rows.append(
                {
                    "ticker": r["ticker"],
                    "date": r["date"],
                    "open": float(r["open"]) if r["open"] else None,
                    "high": float(r["high"]) if r["high"] else None,
                    "low": float(r["low"]) if r["low"] else None,
                    "close": float(r["close"]) if r["close"] else None,
                    "volume": int(r["volume"]) if r["volume"] else None,
                }
            )
    return rows


# --------------------------------------------------------------------------- #
# Regime logic
# --------------------------------------------------------------------------- #


def determine_regime(equity_pct_change: float) -> str:
    """Determine the market regime based on daily PnL percentage.

    BEARISH  => equity down, trigger 60% cash defense
    BULLISH => equity up, emerald green
    """
    if equity_pct_change < 0:
        return "BEARISH"
    return "BULLISH"


def regime_color(regime: str) -> str:
    """Return the Pill CSS color class for the regime badge."""
    if regime == "BEARISH":
        return "rgba(239, 68, 68, 0.85)"  # Ambar/Red-ish
    return "rgba(34, 177, 76, 0.85)"     # Emerald Green


# --------------------------------------------------------------------------- #
# Helpers: compute allocation & weight from current positions
# --------------------------------------------------------------------------- #


def compute_allocations(positions: List[Dict[str, Any]], equity_pkr: float) -> Dict[str, float]:
    """Compute % allocations per pod and the cash reserve.

    Returns a dict with pod labels and a "Cash/T-Bill Reserve" key.
    """
    if not positions or equity_pkr <= 0:
        return {cat: 0.0 for cat in POD_CATEGORIES} | {"Cash/T-Bill Reserve": 100.0}

    # Per-ticker absolute current market value
    ticker_mv: Dict[str, float] = {}
    pod_mv: Dict[str, float] = {cat: 0.0 for cat in POD_CATEGORIES}

    for pos in positions:
        ticker = pos["ticker"]
        qty = pos["quantity"]
        cp = pos["current_price"] or pos["entry_price"]
        mv = qty * cp
        ticker_mv[ticker] = mv

        pod = pos.get("pod", "Macro Cash")
        if pod in pod_mv:
            pod_mv[pod] += mv

    total_long_mv = sum(v for v in ticker_mv.values() if v > 0)
    cash_reserve_pct = max(0.0, 100.0 - (total_long_mv / equity_pkr) * 100.0)

    allocation: Dict[str, float] = {}
    for cat in POD_CATEGORIES:
        allocation[cat] = round((pod_mv.get(cat, 0.0) / equity_pkr) * 100.0, 2)
    allocation["Cash/T-Bill Reserve"] = round(cash_reserve_pct, 2)

    return allocation


def compute_single_stock_alert(positions: List[Dict[str, Any]], equity_pkr: float) -> Optional[str]:
    """Return ticker name if any single stock exceeds 12% ceiling, else None."""
    if not positions or equity_pkr <= 0:
        return None
    for pos in positions:
        qty = pos["quantity"]
        cp = pos["current_price"] or pos["entry_price"]
        if cp <= 0:
            continue
        mv = qty * cp
        pct = (mv / equity_pkr) * 100.0
        if pct >= MAX_SINGLE_STOCK_PCT:
            return pos["ticker"]
    return None


# --------------------------------------------------------------------------- #
# Blotter / fill logic
# --------------------------------------------------------------------------- #


def render_badge(side: str) -> str:
    """Return a Streamlit-markdown badge HTML string for the given order side.

    Badge colors per the spec:
      BUY_NEW  -> Green
      SELL_FULL -> Red
      HOLD   -> Gray
      PAIR_SHORT -> Purple
    """
    mapping = {
        "BUY_NEW": "rgba(34, 177, 76, 0.9)",    # Emerald Green
        "SELL_FULL": "rgba(239, 68, 68, 0.9)",  # Ambar/Red
        "HOLD": "rgba(156, 163, 175, 0.9)",     # Gray (slate-400)
        "PAIR_SHORT": "rgba(139, 92, 246, 0.9)", # Violet-Purple
    }
    color = mapping.get(side, "rgba(107, 114, 128, 0.9)")  # default gray
    return f'<span style="display:inline-block;background:{color};color:white;padding:2px 6px;border-radius:3px;font-size:0.75em;">{side}</span>'


# --------------------------------------------------------------------------- #
# Streamlit app layout
# --------------------------------------------------------------------------- #


def main() -> None:
    # Page configuration — institutional dark theme
    st.set_page_config(
        page_title="PSX Quant Workstation",
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # Inject a dark-mode stylesheet + regime badge CSS
    st.markdown(
        """
        <style>
        .main .block-container {
            padding-top: 2rem;
            padding-bottom: 2rem;
        }
        .regime-pill {
            display:inline-block; padding:4px 8px; border-radius:12px; font-weight:600; font-size:0.85rem;
        }
        .donut-text { font-size:1.1rem; }
        .stTable { font-size:0.8rem; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # ------------------------------------------------------------------
    # Sidebar: controls & portfolio editing
    # ------------------------------------------------------------------
    st.sidebar.header("⚙️ Controls")
    equity_input = st.sidebar.number_input(
        "Baseline Equity (Rs PKR)",
        min_value=0,
        value=int(BASE_EQUITY_PKR),
        step=100_000,
    )

    st.sidebar.markdown("---")
    st.sidebar.subheader("Record Fill")
    fill_ticker = st.sidebar.text_input("Ticker", value="")
    fill_side = st.sidebar.selectbox("Side", ["BUY_NEW", "SELL_FULL", "HOLD", "PAIR_SHORT"])
    fill_qty = st.sidebar.number_input("Quantity", min_value=1, value=1, step=1)
    fill_price = st.sidebar.number_input("Price", min_value=0.0, value=0.0, step=0.05)

    if st.sidebar.button("✅ Mark Fill Executed", type="primary"):
        if fill_ticker.strip():
            add_fill(fill_ticker.strip(), fill_side, int(fill_qty), float(fill_price))
            st.sidebar.success(f"Fill recorded: {fill_ticker} {fill_side} {int(fill_qty)} @ {float(fill_price):.2f}")
            st.rerun()
        else:
            st.sidebar.error("Ticker symbol required")

    # ------------------------------------------------------------------
    # Load data
    # ------------------------------------------------------------------
    positions = load_positions()
    ohlcv = load_ohlcv_cache()

    # Compute derived metrics
    equity_pkr = float(equity_input)
    allocation = compute_allocations(positions, equity_pkr)
    single_stock_ticker = compute_single_stock_alert(positions, equity_pkr)

    # Daily PnL computation (simplified: mark-to-market vs entry)
    total_mv = sum(pos["quantity"] * (pos["current_price"] or pos["entry_price"]) for pos in positions)
    daily_pnl_pct = ((total_mv - equity_pkr) / equity_pkr) * 100.0 if equity_pkr else 0.0
    daily_pnl_rs = total_mv - equity_pkr

    # Regime determination
    regime = determine_regime(daily_pnl_pct)
    regime_color_hex = regime_color(regime)

    # ------------------------------------------------------------------
    # Layout: 3-column top banner + main panels
    # ------------------------------------------------------------------
    # Row 1: Executive banner spanning full width
    st.title("🏢 PSX Quant Workstation — Institutional Terminal")

    # Three pillars across the top
    c1, c2, c3 = st.columns(3)

    with c1:
        st.metric(
            label="Total NAV (Rs)",
            value=f"{equity_pkr:,.0f}",
            delta=f"{daily_pnl_pct:.2f}%",
        )

    with c2:
        st.markdown(
            f'<div class="regime-pill" style="background:{regime_color_hex};color:white;">{regime}</div>',
            unsafe_allow_html=True,
        )

    with c3:
        # Asset Allocation Ribbon as a summarized progress indicator
        st.caption("Asset Allocation")
        for cat, pct in allocation.items():
            if pct > 0:
                bar_len = int(pct / 5)  # scale: 5% = 10 chars
                st.caption(f"{cat}: {pct:.1f}% {'█' * max(bar_len, 1)}")

    st.markdown("---")

    # Row 2: Two-column split
    col_left, col_right = st.columns([2, 1])

    # --- Left panel: Visual Analytics ---
    with col_left:
        st.subheader("📊 Visual Analytics")

        # --- Donut: Pod Capital Allocation ---
        fig_donut = go.Figure(data=[
            go.Pie(
                labels=list(allocation.keys()),
                values=list(allocation.values()),
                hole=0.6,
                textinfo="label+percent",
                marker=dict(colors=_DONUT_COLORS),
            )
        ])
        fig_donut.update_traces(
            hoverinfo="label+percent+value",
            hoverlabel=dict(bgcolor="rgba(0,0,0,0.8)"),
        )
        fig_donut.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            font=dict(color="white"),
            legend=dict(font=dict(color="white")),
        )
        st.plotly_chart(fig_donut, use_container_width=True)

        # --- Horizontal bar: Sector Exposure vs 30% Caps ---
        st.markdown("#### Sector Exposure vs. 30% Caps")
        # If we have sector data from OHLCV, use it; otherwise show placeholder
        if ohlcv:
            # Extract sector info from ticker names or use a simple mapping
            # For now, demo with evenly distributed sectors
            sector_data = {
                "Banking": 22.0,
                "Oil & Gas": 18.0,
                "Power": 15.0,
                "Cement": 12.0,
                "Fertilizer": 10.0,
                "Others": 23.0,
            }
            sector_vals = list(sector_data.values())
            sector_names = list(sector_data.keys())

            fig_bar = go.Figure()
            fig_bar.add_trace(go.Bar(
                y=sector_names,
                x=sector_vals,
                orientation="h",
                marker_color="rgba(59, 130, 246, 0.6)",
            ))
            # Add cap line annotation
            fig_bar.add_hline(y=0, x0=0, x1=100, line_dash="dash", line_color="rgba(255,255,255,0.4)")
            fig_bar.update_layout(
                paper_bgcolor="rgba(0,0,0,0)",
                font=dict(color="white"),
                xaxis=dict(range=[0, 35], title="% Exposure", tickcolor="white"),
                yaxis=dict(tickcolor="white"),
                height=300,
            )
            st.plotly_chart(fig_bar, use_container_width=True)
        else:
            st.info("Run EOD ingestion to populate sector exposure data.")

        # --- Equity Curve / Drawdown ---
        st.markdown("#### Historical Equity Curve & Drawdown")
        # Compute intraday equity curve from positions' mark-to-market
        # For demo: cumulative PnL based on current vs entry prices
        if positions:
            equity_curve = []
            cumulative_pnl = 0.0
            for i, pos in enumerate(positions):
                qty = pos["quantity"]
                cp = pos["current_price"] or pos["entry_price"]
                ep = pos["entry_price"]
                pnl = qty * (cp - ep)
                cumulative_pnl += pnl
                equity_curve.append(cumulative_pnl)

            dates = [f"Day {i+1}" for i in range(len(equity_curve))]
            fig_eq = go.Figure()
            fig_eq.add_trace(go.Scatter(
                y=equity_curve,
                mode="lines+markers",
                line=dict(color="rgba(34, 177, 76, 0.8)"),
                marker=dict(color="white"),
            ))
            # Drawdown shading
            peak = np.maximum.accumulate(equity_curve)
            drawdown = np.array(equity_curve) - peak
            fig_eq.add_trace(go.Scatter(
                y=[equity_curve[0]] + (equity_curve[0] + drawdown[1:]).tolist() if len(drawdown) > 1 else [equity_curve[0]],
                fill='tonexty',
                fillcolor='rgba(239,68,68,0.1)',
                line=dict(color='rgba(0,0,0,0)'),
                showlegend=True,
                name="Drawdown",
            ))
            fig_eq.update_layout(
                paper_bgcolor="rgba(0,0,0,0)",
                font=dict(color="white"),
                xaxis=dict(title="Position Index", tickcolor="white"),
                yaxis=dict(title="Cumulative PnL (Rs)", tickcolor="white"),
                height=300,
            )
            st.plotly_chart(fig_eq, use_container_width=True)
        else:
            st.info("No positions loaded. Add positions via the pipeline or record fills.")

    # --- Right panel: Active Portfolio & Risk Audit ---
    with col_right:
        st.subheader("💼 Active Portfolio & Risk")

        # Holdings table
        if positions:
            table_rows = []
            for pos in positions:
                ticker = pos["ticker"]
                qty = pos["quantity"]
                ep = pos["entry_price"]
                cp = pos["current_price"] or ep
                pnl = qty * (cp - ep)
                mv = qty * cp
                weight_pct = (mv / equity_pkr) * 100.0 if equity_pkr else 0.0
                bars = pos["bars_held"]

                # Alert pill if over 12% ceiling
                alert_html = ""
                if ticker == single_stock_ticker:
                    alert_html = f'<span style="display:inline-block;background:rgba(239,68,68,0.8);color:white;padding:2px 6px;border-radius:3px;font-size:0.75em;">12% CEILING</span>'

                table_rows.append(
                    {
                        "Ticker": ticker,
                        "Pod": pos["pod"],
                        "Qty": qty,
                        "Entry": f"{ep:.2f}",
                        "Current": f"{cp:.2f}",
                        "Unrealized PnL": f"{pnl:,.0f}",
                        "Weight %": f"{weight_pct:.1f}%",
                        "Bars Held": bars,
                        "Alert": alert_html,
                    }
                )

            # Sort by weight descending for risk visibility
            table_rows.sort(key=lambda r: float(r["Weight %"].replace("%", "")), reverse=True)

            st.markdown("#### Holdings")
            st.table(table_rows)
        else:
            st.info("No positions in portfolio. Record fills or run the reconciler to build the book.")

        # --- Risk summary ---
        st.markdown("#### Risk Summary")
        total_mv = sum(pos["quantity"] * (pos["current_price"] or pos["entry_price"]) for pos in positions)
        st.caption(f"Total Market Value: Rs {total_mv:,.0f}")
        st.caption(f"Baseline Equity: Rs {equity_pkr:,.0f}")
        if single_stock_ticker:
            st.error(f"⚠️  Single-stock concentration alert: {single_stock_ticker} exceeds 12% ceiling")
        else:
            st.success("✅  Single-stock concentration within limits")

    # Row 3: Execution Blotter (spans full width)
    st.markdown("---")
    st.subheader("📋 Morning Execution Blotter – Staged Delta Orders")

    # For the blotter, we generate synthetic staged orders based on
    # delta between current positions and target exposures.
    # In a real system these would come from the PortfolioReconciler.
    if st.button("🔄 Generate Staged Orders from Reconciler", type="secondary"):
        # Placeholder: generate some sample staged orders
        st.session["staged_orders"] = [
            {"ticker": "TCFL", "side": "BUY_NEW", "quantity": 500, "entry_price": 0.0},
            {"ticker": "BAHL", "side": "SELL_FULL", "quantity": 300, "entry_price": 0.0},
            {"ticker": "PIB", "side": "HOLD", "quantity": 0, "entry_price": 0.0},
            {"ticker": "DFC", "side": "PAIR_SHORT", "quantity": 200, "entry_price": 0.0},
        ]
        st.rerun()

    staged_orders = st.session.get("staged_orders", [])

    if staged_orders:
        for order in staged_orders:
            badge = render_badge(order["side"])
            st.markdown(
                f"{badge} **{order['ticker']}**  |  {order['side']}  |  Qty: {order.get('quantity', 0)}  |  Entry: {order.get('entry_price', 0):.2f}",
            )
    else:
        st.caption("No staged orders yet. Click 'Generate Staged Orders' above.")

    # --- [Mark All Fills Executed] button ---
    st.markdown("#### 🎯 Execute Recorded Fills")
    if st.button("Mark All Fills Executed into Portfolio DB", type="primary"):
        conn = _get_conn()
        try:
            fills_rows = conn.execute("SELECT ticker, side, quantity, price FROM portfolio_fills").fetchall()
            if not fills_rows:
                st.info("No recorded fills to execute.")
            else:
                new_positions = load_positions()  # reload fresh
                for ticker, side, qty, price in fills_rows:
                    # Apply the fill: adjust quantity and update pod
                    # Simple model: BUY increases qty, SELL decreases, HOLD keeps
                    existing = next((p for p in new_positions if p["ticker"] == ticker), None)
                    if side == "BUY_NEW":
                        new_qty = (existing["quantity"] if existing else 0) + qty
                        new_pod = "Factor Core"  # BUY_NEW lands in Factor Core
                    elif side == "SELL_FULL":
                        new_qty = max(0, (existing["quantity"] if existing else 0) - qty)
                        new_pod = existing["pod"] if existing else "Macro Cash"
                    elif side == "HOLD":
                        new_qty = (existing["quantity"] if existing else 0)
                        new_pod = existing["pod"] if existing else "Macro Cash"
                    else:  # PAIR_SHORT
                        new_qty = (existing["quantity"] if existing else 0) - qty
                        new_pod = "DFC Pairs"

                    if new_qty > 0:
                        # Update or insert the position
                        new_positions.append({
                            "ticker": ticker,
                            "pod": new_pod,
                            "quantity": new_qty,
                            "entry_price": price,
                            "current_price": price,
                            "bars_held": 0,
                        })
                    else:
                        # Remove position if qty exhausted
                        new_positions = [p for p in new_positions if p["ticker"] != ticker]

                save_positions(new_positions)
                # Clear the fills table after execution
                conn.execute("DELETE FROM portfolio_fills")
                conn.commit()
                st.success(f"Executed {len(fills_rows)} fill(s) into portfolio.db")
                st.rerun()
        except Exception as exc:
            LOGGER.error("Failed to execute fills: %s", exc)
            st.error(f"Execution failed: {exc}")
        finally:
            conn.close()


if __name__ == "__main__":
    main()