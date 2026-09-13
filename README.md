# PSX / NCCPL Intelligence System

Zero-cost, end-to-end market intelligence for the Pakistan Stock Exchange:

- **Pipeline** — headless Python scrapers + quant engines, run daily by GitHub
  Actions, stored in Supabase (PostgreSQL).
- **Terminal** — mobile-first Next.js institutional blotter on Vercel:
  Whale Matrix, Cash Arbitrage desk, Institutional Momentum and NDM block
  tape, rendered live from Supabase with zero mock fallbacks.

All data sources are free and verified live (2026-09-10):

| Source | What it provides |
| --- | --- |
| `dps.psx.com.pk/market-watch` | Full-market EOD snapshot (OHLC + volume) |
| `dps.psx.com.pk/historical` (POST) | Per-symbol monthly OHLCV backfill |
| `dps.psx.com.pk/timeseries/eod/<SYM>` | JSON close/volume history fallback |
| `dps.psx.com.pk/trading-board/NDM/NDM` | Negotiated (off-market) block deals |
| `dps.psx.com.pk/screener` | Sector, market cap, P/E, dividend yield |
| `dps.psx.com.pk/payouts` (POST) | Cash-dividend payout history |
| `scstrade.com/FIPILIPI.aspx` (JSON POST) | NCCPL FIPI/LIPI participant flows (USD mn, converted to PKR) |
| `psx.com.pk/psx/market-summary/future-contract-ajax` (POST) | Deliverable single-stock futures closes (feed currently rejecting payloads) |

## Folder structure

```
.
├── schema.sql                    # Supabase schema (run once)
├── main.py                       # CLI pipeline coordinator
├── requirements.txt
├── pipeline/
│   ├── http_client.py            # shared session, retries, headers
│   ├── parsing.py                # defensive number/date parsers
│   ├── db.py                     # Supabase client + chunked upserts (500)
│   ├── scrapers/
│   │   ├── psx_eod.py            # market-watch snapshot + history backfill
│   │   ├── nccpl_flows.py        # FIPI/LIPI participant flows (USD -> PKR)
│   │   ├── psx_offmarket.py      # NDM block deals
│   │   ├── psx_futures.py        # deliverable futures board (XXX-FUT)
│   │   └── psx_fundamentals.py   # screener fundamentals + payout history
│   └── analytics/
│       └── quant_engine.py       # six-engine signal desk
├── .github/workflows/daily_run.yml
└── frontend/                     # Next.js 14 quant terminal (deploy to Vercel)
    ├── app/                      # layout.tsx, page.tsx, globals.css
    ├── components/               # blotters, barometer tape, skeleton, error panel
    └── lib/                      # supabase.ts, queries.ts, types.ts
```

## 1. Supabase setup (once)

1. Create a free project at [supabase.com](https://supabase.com).
2. SQL Editor -> paste all of `schema.sql` -> Run. Creates 5 tables with
   constraints, indexes and public-read RLS policies.
3. Project Settings -> API: copy the **project URL**, the **service_role**
   key (pipeline only) and the **anon** key (dashboard only).

## 2. Pipeline — local run

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env             # fill in SUPABASE_URL + SUPABASE_KEY (service role)
python main.py                   # full run for today's session
python main.py --help            # --date, --skip-*, --force-backfill flags
```

The first run auto-detects empty tables and backfills 3 months of OHLCV
history for the 150 most liquid tickers so the 20-day SMA / 50-day EMA
windows have data.

## 3. Pipeline — GitHub Actions (free automation)

1. Push this repo to GitHub.
2. Repo Settings -> Secrets and variables -> Actions -> New repository secret:
   - `SUPABASE_URL` — your project URL
   - `SUPABASE_KEY` — the **service_role** key (server-side only)
3. That's it: `.github/workflows/daily_run.yml` runs Mon-Fri at 13:30 UTC
   (18:30 PKT, after PSX close). Use the "Run workflow" button for manual runs.

## 4. Dashboard — local run

```bash
cd frontend
npm install
cp .env.local.example .env.local  # NEXT_PUBLIC_SUPABASE_URL + NEXT_PUBLIC_SUPABASE_ANON_KEY
npm run dev                       # http://localhost:3000
```

The terminal renders **live Supabase data only** — there is no demo/mock
fallback. Without valid env vars it fails fast at startup; with an empty
database it shows skeleton loading grids until the pipeline has run.

## 5. Dashboard — deploy to Vercel

```bash
npm i -g vercel
cd frontend
vercel           # link the project (framework auto-detected: Next.js)
vercel --prod
```

In the Vercel dashboard -> Settings -> Environment Variables, add for
Production + Preview:

- `NEXT_PUBLIC_SUPABASE_URL`
- `NEXT_PUBLIC_SUPABASE_ANON_KEY`

(or run `vercel env add NEXT_PUBLIC_SUPABASE_URL` etc. from the CLI.)

## Signals explained

| Desk | Logic | Output |
| --- | --- | --- |
| `WHALE_RADAR` / `STEALTH_ACCUMULATION` | Volume ≥ 1.8x 20-day SMA with price drift compressed in (−2.0%, +4.0%) and 20-day liquidity ≥ 30k shares — silent institutional absorption; NDM block on the same day raises conviction to HIGH; if nothing qualifies, the top-N positive-close volume spikes are tagged `NOTABLE_VOLUME_SPIKE`; stop = close − 1.5×ATR(14), sweep-calibrated | entry, stop, metadata (vol multiple, drift, tightness, conviction) |
| `ARBITRAGE` / `CASH_CARRY` | Ready close vs deliverable futures (XXX-FUT) on the **same session**: spread = (FUT − Ready)/Ready ≥ 2.5%; annualized on the nearest ~30-day contract | explicit pair order + both leg prices in metadata |
| `MOMENTUM` / `INSTITUTIONAL_TARGET` | Top 5-day volume breakout (today / 5-day SMA ≥ 1.5x) among tickers whose sector saw Mutual Funds / Foreign Corporates net buying on the latest NCCPL session; with no sector alignment, the market-wide top relative-volume names are used instead | entry, breakout multiple, sector smart-net |
| `INSIDER_RADAR` / `INSIDER_BUYING` | Aggregated net notional of SECP/PSX insider & sponsor disclosures (directors, CEO, sponsors, substantial shareholders) over the last 20 sessions ≥ 5m PKR; senior-designation buying raises conviction | entry, net notional, disclosure count, conviction in metadata |
| `MTS_SQUEEZE` / `MARGIN_CASCADE_RISK` · `LEVERAGE_FLUSH_BOTTOM` | NCCPL MTS exposure: utilization ≥ 80% of authorized cap with falling price = crowded leveraged longs (avoid); financed value down ≥ 25% with price down ≥ 10% over 5 sessions = forced deleveraging exhausting (flushout-bottom watch) | utilization, value, price drop, stance in metadata |
| `ROLLOVER_DESK` / `BASIS_INVERSION_SHORT` · `ROLLOVER_SQUEEZE` | Deliverable futures basis vs spot around rollover windows: futures ≥ 0.5% below spot = hedging shorts overshot (short-bias fade); violent basis swing while spot holds = shorts paying up to roll (squeeze watch) | futures symbol, both closes, basis, stance in metadata |
| `SHORT_TERM` / `ACCUMULATION` | Volume > 2.0x its 20-day SMA, close in top 25% of day range, optional NDM block confirmation; stop = close − 1.5×ATR(14), sweep-calibrated | entry, stop-loss, rationale |
| `RESEARCH` (`psx_equity_research`) | Composite 0-100 alpha score: valuation (earnings yield + Graham discount) 35, quality (net margin) 25, growth (EPS/sales YoY) 20, shareholder yield 20 — each percentile-ranked cross-sectionally on the day. Intrinsic value = Graham earnings power (normalised EPS × (8.5 + 2×capped growth), bond-adjusted); ±15% bands classify UNDERVALUED / FAIR_VALUE / OVERVALUED | alpha score, intrinsic value, discount %, verdict, balance-sheet risk flag |
| `ROTATION` (`psx_sector_rotation`) | Daily RRG vs a live KSE-100 series: equal-weight sector indices from stored closes, RS-Ratio and RS-Momentum rebased to 100 over a 60-session window (5-session Jacob span); LEADING / IMPROVING / WEAKENING / LAGGING quadrants plus each sector's window leader & dragger | rs_ratio, rs_momentum, quadrant, leader/dragger |
| `MEDIUM_TERM` / `ACCUMULATION` | Ticker's sector shows NCCPL institutional net inflow for N straight sessions while close holds above the 50-day EMA | entry, wider stop, rationale |
| `LONG_TERM` / `VALUE_YIELD` | Screener dividend yield ≥ 6% (default), P/E ≤ 12, market cap ≥ 5bn PKR, payout-stability check from DPS payouts | entry, rationale |

### Fundamental Alpha & Research Layer (`psx_financial_ratios` · `psx_equity_research` · `psx_sector_rotation`)

`psx_financial_ratios` stores quarterly EPS, margins and YoY growth scraped
from DPS company pages (`/company/<SYM>` Financials tab — verified
server-rendered; balance-sheet items PSX does not publish stay NULL).
`main.py` step 4b refreshes the liquidity-ranked top-80 universe daily
(`FINANCIALS_MAX_TICKERS`, polite `FINANCIALS_POLITE_SLEEP` pause between
requests). The research engine scores every session ticker into
`psx_equity_research`; the rotation engine publishes sector quadrants into
`psx_sector_rotation` (idle with an explicit log if the KSE-100 benchmark
series is unreachable). All weights/bands/lookbacks are env-tunable
(`ALPHA_*`, `RRG_*` in `.env.example`). The dashboard's **Research** and
**Rotation** tabs render both matrices session-bound.

### Historical Edge Lab (`signal_backtest_performance`)

Every actionable long signal with a stop is walk-forward evaluated after the
sessions close: t+5/t+10/t+20 forward returns, max favourable / adverse
excursion, and a 2R-convention resolution (target = entry + 2× stop
distance; a same-session stop/target touch resolves as a stop,
conservatively). The **Edge Lab** tab aggregates per signal type: hit rate,
stop rate, average forward returns, MFE/MAE and expectancy E[R] =
hit%×2 − (1−hit%). Unresolved forward windows stay NULL — never interpolated.

### Risk Desk (position sizing)

The pipeline sizes the session book with fixed-fractional risk parity:
`risk = equity × 1%`, notional = `risk ÷ stop-distance%`, capped at 20% of
equity per position, 8 positions max, and a 6% total portfolio-heat cap
(filled in conviction order, then tighter stop geometry). Setups with
noise-level stops (< 1.5%) are rejected. The dashboard's **Risk Desk** tab
mirrors the same math client-side with an interactive equity/risk input.
All thresholds are tunable via env vars (see `.env.example`).

Thresholds are tunable via env vars (see `.env.example`).

**Futures feed note:** PSX's `future-contract-ajax` endpoint currently
rejects every month format the scraper offers, so `psx_futures_eod` (and the
Cash Arbitrage + Rollover desks) stays empty — with an explicit log line —
until PSX accepts a payload. No synthetic spreads are ever generated.

**Insider / MTS feed note:** the DPS company-announcements page (insider
disclosures) is JS-rendered with no static endpoint, and the NCCPL MTS
download requires an authenticated portal session. Both scrapers ship
production-ready parsers and log an explicit idle line instead of fabricating
rows; they begin emitting data automatically when a reachable endpoint or
export URL is provided.

## Troubleshooting

- **`SUPABASE_URL and SUPABASE_KEY must be set`** — create `.env` from
  `.env.example`; in CI check the repo secrets' exact names.
- **Empty dashboard** — run the pipeline once; the first run backfills
  history and computes the initial signal set.
- **NCCPL flows missing** — the scstrade mirror blocks some datacenter IPs;
  the pipeline logs a warning and continues. Re-run or run from a different
  network (GitHub Actions runners are typically fine).
- **Signals look stale** — the dashboard shows the latest session with
  signals; check the last successful Actions run.
