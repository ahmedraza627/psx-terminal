-- ============================================================================
-- PSX / NCCPL Intelligence System - unified schema (Supabase / PostgreSQL)
-- Run once in Supabase SQL Editor (or `psql -f schema.sql`).
-- Safe to re-run: uses IF NOT EXISTS everywhere.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- 1. Daily end-of-day bars for every listed ticker
-- ---------------------------------------------------------------------------
create table if not exists public.psx_daily_eod (
    id           bigserial primary key,
    trade_date   date           not null,
    ticker       varchar(20)    not null,
    open_price   numeric(10, 2),
    high_price   numeric(10, 2),
    low_price    numeric(10, 2),
    close_price  numeric(10, 2),
    volume       bigint,
    constraint psx_daily_eod_date_ticker_key unique (trade_date, ticker),
    constraint psx_daily_eod_price_sanity check (
        close_price is null or close_price > 0
    )
);

create index if not exists psx_daily_eod_ticker_date_idx
    on public.psx_daily_eod (ticker, trade_date desc);

create index if not exists psx_daily_eod_date_idx
    on public.psx_daily_eod (trade_date desc);

-- ---------------------------------------------------------------------------
-- 2. NCCPL FIPI/LIPI participant flows (aggregates + per-sector, PKR)
-- ---------------------------------------------------------------------------
create table if not exists public.nccpl_fipi_lipi (
    id               bigserial primary key,
    trade_date       date           not null,
    participant_type varchar(50)    not null,   -- MUTUAL FUNDS, FOREIGN CORPORATES, INDIVIDUALS, BANKS, ...
    sector_name      varchar(100)   not null default 'ALL',
    buy_pkr          numeric(15, 2),
    sell_pkr         numeric(15, 2),
    net_pkr          numeric(15, 2),
    constraint nccpl_fipi_lipi_unique_key
        unique (trade_date, participant_type, sector_name)
);

-- Legacy runs may carry the older, buggy net-balance check; drop it.
alter table public.nccpl_fipi_lipi
    drop constraint if exists nccpl_fipi_lipi_net_balance;

create index if not exists nccpl_fipi_lipi_date_sector_idx
    on public.nccpl_fipi_lipi (trade_date desc, sector_name);

create index if not exists nccpl_fipi_lipi_participant_idx
    on public.nccpl_fipi_lipi (participant_type, trade_date desc);

-- ---------------------------------------------------------------------------
-- 3. Off-market / negotiated (NDM) block deals
-- ---------------------------------------------------------------------------
create table if not exists public.psx_offmarket_deals (
    id         bigserial primary key,
    trade_date date           not null,
    ticker     varchar(20)    not null,
    quantity   bigint,
    rate       numeric(10, 2),
    value      numeric(15, 2)
);

create index if not exists psx_offmarket_deals_date_ticker_idx
    on public.psx_offmarket_deals (trade_date desc, ticker);

-- ---------------------------------------------------------------------------
-- 3b. Deliverable single-stock futures closes (XXX-FUT) for the cash &
--     carry arbitrage desk. Populated by pipeline/scrapers/psx_futures.py;
--     empty until PSX's contract feed responds.
-- ---------------------------------------------------------------------------
create table if not exists public.psx_futures_eod (
    id          bigserial primary key,
    trade_date  date           not null,
    ticker      varchar(20)    not null,   -- e.g. TRG-FUT
    open_price  numeric(10, 2),
    high_price  numeric(10, 2),
    low_price   numeric(10, 2),
    close_price numeric(10, 2),
    volume      bigint,
    oi_shares   bigint,                     -- open interest (DFC scanner leg)
    constraint psx_futures_eod_date_ticker_key unique (trade_date, ticker)
);

-- Installed tables created before the OI column are migrated forward here.
alter table public.psx_futures_eod
    add column if not exists oi_shares bigint;

create index if not exists psx_futures_eod_ticker_date_idx
    on public.psx_futures_eod (ticker, trade_date desc);

-- ---------------------------------------------------------------------------
-- 4. Computed signals (written by pipeline/analytics/quant_engine.py)
-- ---------------------------------------------------------------------------
create table if not exists public.signals_computed (
    id             bigserial primary key,
    trade_date     date           not null,
    ticker         varchar(20)    not null,
    timeframe      varchar(20)    not null,   -- SHORT_TERM | MEDIUM_TERM | LONG_TERM
    signal_type    varchar(50)    not null,   -- ACCUMULATION | DISTRIBUTION_TRAP | VALUE_YIELD
    entry_reference numeric(10, 2),
    stop_loss      numeric(10, 2),
    rationale      text           not null,
    metadata       jsonb,
    constraint signals_computed_unique_key
        unique (trade_date, ticker, timeframe, signal_type),
    constraint signals_computed_timeframe_check check (
        timeframe in (
            'SHORT_TERM', 'MEDIUM_TERM', 'LONG_TERM',
            'WHALE_RADAR', 'ARBITRAGE', 'MOMENTUM',
            'INSIDER_RADAR', 'MTS_SQUEEZE', 'ROLLOVER_DESK'
        )
    ),
    constraint signals_computed_signal_type_check check (
        signal_type in (
            'ACCUMULATION', 'DISTRIBUTION_TRAP', 'VALUE_YIELD',
            'STEALTH_ACCUMULATION', 'CASH_CARRY', 'INSTITUTIONAL_TARGET',
            'HIGH_YIELD', 'MOMENTUM_BREAKOUT', 'INSIDER_BUYING',
            'MARGIN_CASCADE_RISK', 'LEVERAGE_FLUSH_BOTTOM',
            'BASIS_INVERSION_SHORT', 'ROLLOVER_SQUEEZE'
        )
    )
);

create index if not exists signals_computed_date_timeframe_idx
    on public.signals_computed (trade_date desc, timeframe);

-- Legacy installs may carry the older 3-column unique key + narrow checks;
-- migrate them forward idempotently.
alter table public.signals_computed
    drop constraint if exists signals_computed_unique_key;
alter table public.signals_computed
    drop constraint if exists signals_computed_timeframe_check;
alter table public.signals_computed
    drop constraint if exists signals_computed_signal_type_check;
alter table public.signals_computed
    drop constraint if exists signals_computed_date_ticker_timeframe_key;
alter table public.signals_computed add column if not exists metadata jsonb;

alter table public.signals_computed
    add constraint signals_computed_unique_key
    unique (trade_date, ticker, timeframe, signal_type);
alter table public.signals_computed
    add constraint signals_computed_timeframe_check check (
        timeframe in (
            'SHORT_TERM', 'MEDIUM_TERM', 'LONG_TERM',
            'WHALE_RADAR', 'ARBITRAGE', 'MOMENTUM',
            'INSIDER_RADAR', 'MTS_SQUEEZE', 'ROLLOVER_DESK'
        )
    );
alter table public.signals_computed
    add constraint signals_computed_signal_type_check check (
        signal_type in (
            'ACCUMULATION', 'DISTRIBUTION_TRAP', 'VALUE_YIELD',
            'STEALTH_ACCUMULATION', 'CASH_CARRY', 'INSTITUTIONAL_TARGET',
            'HIGH_YIELD', 'MOMENTUM_BREAKOUT', 'INSIDER_BUYING',
            'MARGIN_CASCADE_RISK', 'LEVERAGE_FLUSH_BOTTOM',
            'BASIS_INVERSION_SHORT', 'ROLLOVER_SQUEEZE'
        )
    );

-- ---------------------------------------------------------------------------
-- 4b. SECP / PSX insider & sponsor transactions (board-letter disclosures)
-- ---------------------------------------------------------------------------
create table if not exists public.psx_insider_trades (
    id            bigserial primary key,
    trade_date    date           not null,
    ticker        varchar(16)    not null,
    insider_name  text           not null,
    designation   varchar(64)    not null,   -- Director, CEO, Sponsor, Substantial Shareholder
    trade_type    varchar(16)    not null,   -- BUY / SELL
    quantity      bigint         not null,
    rate          numeric(12, 2),
    notional_pkr  numeric(16, 2),
    disclosure_url text,
    created_at    timestamptz    default now(),
    constraint uq_insider_trade
        unique (trade_date, ticker, insider_name, quantity, trade_type)
);

create index if not exists idx_insider_lookup
    on public.psx_insider_trades (ticker, trade_date desc);

-- ---------------------------------------------------------------------------
-- 4c. NCCPL MTS (Margin Trading System) daily exposure per scrip
-- ---------------------------------------------------------------------------
create table if not exists public.nccpl_mts_leverage (
    id                       bigserial primary key,
    trade_date               date           not null,
    ticker                   varchar(16)    not null,
    mts_shares               bigint         not null,
    mts_value_pkr            numeric(16, 2) not null,
    leverage_utilization_pct numeric(6, 2),  -- % of authorized leverage cap
    unfinanced_volume        bigint,
    created_at               timestamptz    default now(),
    constraint uq_mts_leverage unique (trade_date, ticker)
);

create index if not exists idx_mts_lookup
    on public.nccpl_mts_leverage (trade_date desc, leverage_utilization_pct desc);

-- ---------------------------------------------------------------------------
-- 5. Fundamentals snapshot (DPS screener + sector map) used by the quant
--    engine. Additive to the four core tables; keeps signals reproducible
--    without re-scraping.
-- ---------------------------------------------------------------------------
create table if not exists public.psx_fundamentals (
    id              bigserial primary key,
    trade_date      date           not null,
    ticker          varchar(20)    not null,
    sector_name     varchar(100),
    market_cap_pkr  numeric(18, 2),
    close_price     numeric(10, 2),
    pe_ratio        numeric(10, 2),
    dividend_yield  numeric(6, 2),
    free_float      bigint,
    volume_30d_avg  numeric(15, 2),
    constraint psx_fundamentals_unique_key unique (trade_date, ticker)
);

create index if not exists psx_fundamentals_date_idx
    on public.psx_fundamentals (trade_date desc);

create index if not exists psx_fundamentals_sector_idx
    on public.psx_fundamentals (sector_name, trade_date desc);

-- ---------------------------------------------------------------------------
-- 7. Historical edge backtester: forward performance of every evaluated
--    signal (filled by pipeline/analytics/backtester.py). One row per
--    signal - t+5/t+10/t+20 forward returns, excursion extremes, and the
--    stop/target resolution used for hit-rate statistics.
-- ---------------------------------------------------------------------------
create table if not exists public.signal_backtest_performance (
    id                            bigserial primary key,
    signal_id                     bigint        not null references public.signals_computed (id) on delete cascade,
    ticker                        varchar(16)   not null,
    trade_date                    date          not null,
    signal_type                   varchar(64)   not null,
    entry_price                   numeric(12, 2) not null,
    stop_loss                     numeric(12, 2) not null,
    return_t5_pct                 numeric(6, 2),
    return_t10_pct                numeric(6, 2),
    return_t20_pct                numeric(6, 2),
    max_favorable_excursion_pct   numeric(6, 2),
    max_adverse_excursion_pct     numeric(6, 2),
    hit_target                    boolean,
    stopped_out                   boolean,

    -- Tiered-exit resolution (TP1 +1R bank 50% / BE ratchet / TP2 +2R bank
    -- 30% / runner 20% to +3R or 1.5xATR trail). tp1_hit_pkr = tp2_hit when
    -- tp1 fired (the ratchet guarantees TP1 before TP2). full_stop = flat
    -- stop without ever reaching TP1. Expectancy/PF are R-weighted:
    -- realized_r = 0.5*1 + 0.3*2 + 0.2*runner_r on winners-with-TP1.
    tp1_hit                       boolean,
    tp2_hit                       boolean,
    runner_hit                    boolean,
    full_stop                     boolean,
    realized_r                    numeric(8, 4),
    created_at                    timestamptz   default now(),
    constraint signal_backtest_unique_key unique (signal_id)
);

-- Migration for deployments created before the tiered-exit upgrade.
alter table public.signal_backtest_performance add column if not exists tp1_hit     boolean;
alter table public.signal_backtest_performance add column if not exists tp2_hit     boolean;
alter table public.signal_backtest_performance add column if not exists runner_hit  boolean;
alter table public.signal_backtest_performance add column if not exists full_stop   boolean;
alter table public.signal_backtest_performance add column if not exists realized_r  numeric(8, 4);

create index if not exists idx_backtest_eval
    on public.signal_backtest_performance (signal_type, hit_target);

create index if not exists idx_backtest_date
    on public.signal_backtest_performance (trade_date desc);

-- ---------------------------------------------------------------------------
-- 8. Fundamental Alpha & Research Layer
--    8a. Quarterly balance sheet / income / cash-flow ratios (DPS company
--        pages). Items PSX does not publish stay NULL - never interpolated.
-- ---------------------------------------------------------------------------
create table if not exists public.psx_financial_ratios (
    id                      bigserial primary key,
    ticker                  varchar(16)   not null,
    fiscal_period           varchar(16)   not null,  -- e.g. 'FY26-Q2', 'FY25-Q4'
    period_end_date         date          not null,
    eps                     numeric(10, 2),
    book_value_per_share    numeric(10, 2),
    sales_growth_yoy_pct    numeric(6, 2),
    net_profit_margin_pct   numeric(6, 2),
    debt_to_equity          numeric(8, 2),
    interest_coverage_ratio numeric(8, 2),
    fcf_per_share           numeric(10, 2),
    roic_pct                numeric(6, 2),
    shariah_compliant       boolean,
    created_at              timestamptz   default now(),
    constraint uq_financial_ticker_period unique (ticker, fiscal_period)
);

create index if not exists idx_fin_lookup
    on public.psx_financial_ratios (ticker, period_end_date desc);

-- 8b. Quantitative alpha score & intrinsic valuation matrix (research engine)
create table if not exists public.psx_equity_research (
    id                     bigserial primary key,
    trade_date             date          not null,
    ticker                 varchar(16)   not null,
    alpha_score            integer       not null check (alpha_score between 0 and 100),
    intrinsic_value_pkr    numeric(12, 2),
    valuation_discount_pct numeric(6, 2),   -- discount (+) / overvaluation (-) vs LTP
    valuation_status       varchar(24)   not null,  -- UNDERVALUED | FAIR_VALUE | OVERVALUED
    balance_sheet_risk_flag text,
    created_at             timestamptz   default now(),
    constraint uq_equity_research unique (trade_date, ticker),
    constraint equity_research_status_check
        check (valuation_status in ('UNDERVALUED', 'FAIR_VALUE', 'OVERVALUED'))
);

create index if not exists idx_research_score
    on public.psx_equity_research (trade_date desc, alpha_score desc);

-- 8b-i. PSX-adapted valuation model provenance columns (Graham EPV retired:
--        US 4.4/y bond factor mis-prices PKR names under 13-15% PIB yields).
alter table public.psx_equity_research
    add column if not exists target_pe_used numeric(6, 2);
alter table public.psx_equity_research
    add column if not exists dividend_floor_pkr numeric(12, 2);
alter table public.psx_equity_research
    add column if not exists model_version varchar(24) not null default 'PSX_MF_V1';

-- 8a-i. Finance cost (quarterly, '000 PKR) for KIBOR sensitivity estimation.
alter table public.psx_financial_ratios
    add column if not exists finance_cost numeric(14, 2);

-- 8c. Sector relative rotation (RRG) benchmarked against KSE-100
create table if not exists public.psx_sector_rotation (
    id                 bigserial primary key,
    trade_date         date         not null,
    sector_name        varchar(64)  not null,
    rs_ratio           numeric(8, 2) not null,   -- relative strength vs KSE-100 (base 100)
    rs_momentum        numeric(8, 2) not null,   -- rate of change of RS-Ratio (base 100)
    quadrant           varchar(16)  not null,    -- LEADING | IMPROVING | WEAKENING | LAGGING
    top_leader_ticker  varchar(16),
    top_dragger_ticker varchar(16),
    -- Institutional flow-engine enrichment (v2):
    sessions_in_quadrant integer,             -- consecutive sessions in quadrant (incl. today)
    weeks_in_quadrant   integer,              -- sessions // 5, min 1
    breadth_pct         numeric(5, 2),        -- % of members above their 20-SMA
    breadth_flag        varchar(24),          -- BROAD_PARTICIPATION | NARROW_TRAP | NEUTRAL
    net_inst_flow_pkr_5d numeric(18, 2),      -- 5d Mutual Funds + FIPI net (sector rows)
    net_retail_flow_pkr_5d numeric(18, 2),    -- 5d INDIVIDUALS net (sector rows)
    verdict             varchar(24),          -- EARLY_ACCUMULATION | MOMENTUM_RIDE |
                                              -- DISTRIBUTION_RISK | AVOID_CAPITAL_TRAP
    alpha_drivers       jsonb,                -- [{ticker,ltp,ret_5d_pct,rs_vs_sector_pct,vol_x_sma20}]
    alpha_draggers      jsonb,
    created_at          timestamptz  default now(),
    constraint uq_sector_rotation unique (trade_date, sector_name),
    constraint sector_rotation_quadrant_check
        check (quadrant in ('LEADING', 'IMPROVING', 'WEAKENING', 'LAGGING'))
);

-- v2 columns for installs created before the flow-engine enrichment.
alter table public.psx_sector_rotation add column if not exists sessions_in_quadrant integer;
alter table public.psx_sector_rotation add column if not exists weeks_in_quadrant integer;
alter table public.psx_sector_rotation add column if not exists breadth_pct numeric(5, 2);
alter table public.psx_sector_rotation add column if not exists breadth_flag varchar(24);
alter table public.psx_sector_rotation add column if not exists net_inst_flow_pkr_5d numeric(18, 2);
alter table public.psx_sector_rotation add column if not exists net_retail_flow_pkr_5d numeric(18, 2);
alter table public.psx_sector_rotation add column if not exists verdict varchar(24);
alter table public.psx_sector_rotation add column if not exists alpha_drivers jsonb;
alter table public.psx_sector_rotation add column if not exists alpha_draggers jsonb;

create index if not exists idx_sector_quad
    on public.psx_sector_rotation (trade_date desc, quadrant);

-- ---------------------------------------------------------------------------
-- 9. KIBOR easing sensitivity: projected EPS expansion per rate cut.
--    Floating debt is estimator input (finance-cost-implied or manually
--    enriched). Column set reconciled to the deployed table and the
--    kibor_engine emit contract (an earlier v2 rename draft never migrated
--    against the live table — see migrations/001_reconcile_drifted_tables.sql).
-- ---------------------------------------------------------------------------
create table if not exists public.psx_kibor_sensitivity (
    id                      bigserial primary key,
    trade_date              date         not null,
    ticker                  varchar(16)  not null,
    sector_name             varchar(64),
    floating_debt           numeric(18, 2),
    total_debt              numeric(18, 2),
    shares_outstanding      numeric(18, 2),
    effective_tax_rate      numeric(5, 2),
    current_eps             numeric(10, 2),
    eps_impact_per_100bps   numeric(10, 4),
    eps_growth_300bps_pct   numeric(10, 2),
    created_at              timestamptz  default now(),
    constraint uq_kibor_ticker_date unique (trade_date, ticker)
);

create index if not exists idx_kibor_rank
    on public.psx_kibor_sensitivity (trade_date desc, eps_growth_300bps_pct desc);

-- 10. Insider conviction ledger: parsed board-letter filings tagged by size.
create table if not exists public.psx_insider_disclosures (
    id              bigserial primary key,
    trade_date      date         not null,
    ticker          varchar(16)  not null,
    insider_name    text         not null,
    designation     varchar(64)  not null,
    trade_type      varchar(16)  not null,
    quantity        bigint       not null,
    rate            numeric(12, 2),
    notional_pkr    numeric(16, 2),
    conviction      varchar(16)  not null default 'STANDARD',
    disclosure_url  text,
    created_at      timestamptz  default now(),
    constraint uq_insider_disclosure unique (trade_date, ticker, insider_name, quantity, trade_type)
);

create index if not exists idx_insider_conv
    on public.psx_insider_disclosures (trade_date desc, conviction);

-- ---------------------------------------------------------------------------
-- 11. Global macro & commodity correlation / prediction engine.
--     Drivers: WTI/Brent crude (Arab Light proxies), XAU, DXY, urea/coal/
--     steel proxies, accumulating USD/PKR spot. Correlations pair macro
--     sessions with PSX sessions (session-geometric lags, never ffill).
-- ---------------------------------------------------------------------------
create table if not exists public.psx_macro_indicator_prices (
    id          bigserial primary key,
    driver_code varchar(16)  not null,
    trade_date  date         not null,
    close       numeric(18, 6) not null,
    source      varchar(24)  not null default 'STOOQ',
    created_at  timestamptz  default now(),
    constraint uq_macro_price unique (driver_code, trade_date)
);

create index if not exists idx_macro_price
    on public.psx_macro_indicator_prices (driver_code, trade_date desc);

create table if not exists public.psx_macro_correlation (
    id           bigserial primary key,
    trade_date   date         not null,
    driver_code  varchar(16)  not null,
    sector_name  varchar(64)  not null,
    lag_days     integer      not null,   -- optimal session lag (argmax |r|)
    correlation  numeric(6, 4) not null,  -- Pearson r at the optimal lag
    beta         numeric(10, 4) not null, -- OLS beta at the optimal lag
    sample_size  integer      not null,   -- overlapping paired sessions
    method       varchar(32)  not null default 'pearson_lagged_ols',
    created_at   timestamptz  default now(),
    constraint uq_macro_corr unique (trade_date, driver_code, sector_name)
);

create index if not exists idx_macro_corr
    on public.psx_macro_correlation (trade_date desc, driver_code);

create table if not exists public.psx_macro_prediction (
    id                     bigserial primary key,
    trade_date             date         not null,
    driver_code            varchar(16)  not null,
    sector_name            varchar(64)  not null,
    shock_window_sessions  integer      not null,
    shock_pct              numeric(10, 2) not null,
    expected_move_pct      numeric(10, 2) not null,
    optimal_lag_days       integer      not null,
    confidence             numeric(6, 4) not null,
    stock_plays            jsonb,       -- [{ticker,correlation,beta,expected_move_pct}]
    created_at             timestamptz  default now(),
    constraint uq_macro_pred unique (trade_date, driver_code, sector_name)
);

create index if not exists idx_macro_pred
    on public.psx_macro_prediction (trade_date desc, driver_code);

-- ---------------------------------------------------------------------------
-- Row Level Security: pipeline writes with the service-role key (bypasses
-- RLS); the website reads with the anon key -> allow public SELECT only.
-- ---------------------------------------------------------------------------
alter table public.psx_daily_eod       enable row level security;
alter table public.nccpl_fipi_lipi     enable row level security;
alter table public.psx_offmarket_deals enable row level security;
alter table public.psx_futures_eod     enable row level security;
alter table public.psx_insider_trades  enable row level security;
alter table public.nccpl_mts_leverage  enable row level security;
alter table public.signals_computed    enable row level security;
alter table public.psx_fundamentals    enable row level security;
alter table public.signal_backtest_performance enable row level security;
alter table public.psx_financial_ratios  enable row level security;
alter table public.psx_equity_research   enable row level security;
alter table public.psx_sector_rotation   enable row level security;
alter table public.psx_kibor_sensitivity enable row level security;
alter table public.psx_insider_disclosures enable row level security;
alter table public.psx_macro_indicator_prices enable row level security;
alter table public.psx_macro_correlation     enable row level security;
alter table public.psx_macro_prediction      enable row level security;

drop policy if exists "public read psx_daily_eod"       on public.psx_daily_eod;
drop policy if exists "public read nccpl_fipi_lipi"     on public.nccpl_fipi_lipi;
drop policy if exists "public read psx_offmarket_deals" on public.psx_offmarket_deals;
drop policy if exists "public read psx_futures_eod"     on public.psx_futures_eod;
drop policy if exists "public read psx_insider_trades"  on public.psx_insider_trades;
drop policy if exists "public read nccpl_mts_leverage"  on public.nccpl_mts_leverage;
drop policy if exists "public read signals_computed"    on public.signals_computed;
drop policy if exists "public read psx_fundamentals"    on public.psx_fundamentals;
drop policy if exists "public read signal_backtest_performance" on public.signal_backtest_performance;
drop policy if exists "public read psx_financial_ratios"  on public.psx_financial_ratios;
drop policy if exists "public read psx_equity_research"   on public.psx_equity_research;
drop policy if exists "public read psx_sector_rotation"   on public.psx_sector_rotation;
drop policy if exists "public read psx_kibor_sensitivity" on public.psx_kibor_sensitivity;
drop policy if exists "public read psx_insider_disclosures" on public.psx_insider_disclosures;

create policy "public read psx_daily_eod"
    on public.psx_daily_eod for select using (true);
create policy "public read nccpl_fipi_lipi"
    on public.nccpl_fipi_lipi for select using (true);
create policy "public read psx_offmarket_deals"
    on public.psx_offmarket_deals for select using (true);
create policy "public read psx_futures_eod"
    on public.psx_futures_eod for select using (true);
create policy "public read psx_insider_trades"
    on public.psx_insider_trades for select using (true);
create policy "public read nccpl_mts_leverage"
    on public.nccpl_mts_leverage for select using (true);
create policy "public read signals_computed"
    on public.signals_computed for select using (true);
create policy "public read psx_fundamentals"
    on public.psx_fundamentals for select using (true);
create policy "public read signal_backtest_performance"
    on public.signal_backtest_performance for select using (true);
create policy "public read psx_financial_ratios"
    on public.psx_financial_ratios for select using (true);
create policy "public read psx_equity_research"
    on public.psx_equity_research for select using (true);
create policy "public read psx_sector_rotation"
    on public.psx_sector_rotation for select using (true);
create policy "public read psx_kibor_sensitivity"
    on public.psx_kibor_sensitivity for select using (true);
create policy "public read psx_insider_disclosures"
    on public.psx_insider_disclosures for select using (true);
create policy "public read psx_macro_indicator_prices"
    on public.psx_macro_indicator_prices for select using (true);
create policy "public read psx_macro_correlation"
    on public.psx_macro_correlation for select using (true);
create policy "public read psx_macro_prediction"
    on public.psx_macro_prediction for select using (true);
