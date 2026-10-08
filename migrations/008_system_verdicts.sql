-- ============================================================================
-- 008 - system verdicts (psx_system_verdicts).
--
-- Certified Action Desk verdicts from pipeline/analytics/decision_engine.py.
-- One row per (trade_date, horizon): the SHORT_TERM (1-5 day) volume-spike
-- buy, the MID_TERM (2-8 week) institutional-absorption buy, and the
-- LONG_TERM retail-trap avoid flag.
--
-- Run ONCE in the Supabase SQL Editor. Idempotent - safe to re-run.
-- The pipeline writes with the service-role key (bypasses RLS entirely).
-- ============================================================================

create table if not exists public.psx_system_verdicts (
    trade_date date not null,
    horizon varchar(50) not null, -- 'SHORT_TERM' | 'MID_TERM' | 'LONG_TERM'
    direction varchar(20) not null, -- 'BUY' | 'AVOID' | 'ACCUMULATE'
    ticker varchar(20) not null,
    logic_text text not null,
    primary key (trade_date, horizon)
);

alter table public.psx_system_verdicts enable row level security;

-- Public read (console), matching this house's migration style.
drop policy if exists "public_read" on public.psx_system_verdicts;
create policy "public_read" on public.psx_system_verdicts for select to anon, authenticated using (true);

grant select on public.psx_system_verdicts to anon, authenticated;

create index if not exists psx_system_verdicts_date_idx on public.psx_system_verdicts (trade_date desc);
