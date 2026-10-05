-- ============================================================================
-- 006 - NDM session aggregates (psx_offmarket_summary).
--
-- PSX retired the per-deal /trading-board/NDM/* routes (verified 404 even
-- through WAF-passing egress). What the exchange still publishes is the
-- session aggregate on /trading-panel (trades / volume / turnover). This
-- table preserves those certified facts, one row per session, so the NDM
-- tape's headline never goes dark while per-symbol rows are unavailable.
--
-- Run ONCE in the Supabase SQL editor. Idempotent - safe to re-run.
-- The pipeline writes with the service-role key (bypasses RLS entirely).
-- ============================================================================

create table if not exists public.psx_offmarket_summary (
    trade_date date          primary key,
    trades     integer       not null default 0,
    volume     bigint        not null default 0,
    value      numeric(15, 2),          -- PKR turnover (NULL when unparseable)
    state      varchar(30),             -- market state as served, e.g. 'Closed'
    source     varchar(40)   not null default 'trading-panel'
);

alter table public.psx_offmarket_summary enable row level security;

-- Public read (console), matching migration 005's policy + grant style.
drop policy if exists "public_read" on public.psx_offmarket_summary;
create policy "public_read"
    on public.psx_offmarket_summary
    for select
    to anon, authenticated
    using (true);

grant select on public.psx_offmarket_summary to anon, authenticated;
