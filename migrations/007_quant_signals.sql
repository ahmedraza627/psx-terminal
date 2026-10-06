-- ============================================================================
-- 007 - daily quant signals (psx_daily_quant_signals).
--
-- Certified daily signal rows from pipeline/analytics/quant_signals.py.
-- One row per (trade_date, ticker, signal_type): volume breakouts,
-- institutional accumulation/distribution cross-checks, retail-trap
-- sectors, and the session-level MARKET_BREADTH divergence flag.
--
-- Run ONCE in the Supabase SQL Editor. Idempotent - safe to re-run.
-- The pipeline writes with the service-role key (bypasses RLS entirely).
-- ============================================================================

create table if not exists public.psx_daily_quant_signals (
    trade_date     date           not null,
    ticker         varchar(20)    not null,
    signal_type    varchar(50)    not null,   -- VOLUME_EXPANSION | INSTITUTIONAL_ACCUMULATION | RETAIL_TRAP_SHORT | MARKET_BREADTH
    confidence_score integer,                  -- 1-100 conviction score; NULL when uncalibrated
    catalyst_reason text,                      -- human-readable cross-reference driver
    sector         varchar(100),               -- sector attribution where available
    primary key (trade_date, ticker, signal_type)
);

alter table public.psx_daily_quant_signals enable row level security;

-- Public read (console), matching this house's migration style.
drop policy if exists "public_read" on public.psx_daily_quant_signals;
create policy "public_read"
    on public.psx_daily_quant_signals
    for select
    to anon, authenticated
    using (true);

grant select on public.psx_daily_quant_signals to anon, authenticated;

create index if not exists psx_daily_quant_signals_date_type_idx
    on public.psx_daily_quant_signals (trade_date desc, signal_type);
