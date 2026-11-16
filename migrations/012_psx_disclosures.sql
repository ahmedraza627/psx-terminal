-- ============================================================================
-- 012 - psx_disclosures: director footprint / insider activity disclosures
-- ============================================================================
--
-- Parsed PSX board-letter / insider-transaction records for the clause
-- 5.6.4 director-footprint module. One row per announcement.
--
-- Run ONCE in the Supabase SQL editor (or `psql -f migrations/012_psx_disclosures.sql`).
-- Idempotent - safe to re-run.
-- ============================================================================

create table if not exists public.psx_disclosures (
    id               bigserial primary key,
    trade_date       date           not null,
    ticker           varchar(16)    not null,
    headline         text           not null,
    disclosure_url   text,
    created_at       timestamptz    default now(),
    constraint uq_disclosure tick
        unique (trade_date, ticker, headline)
);

create index if not exists idx_disclosure_date
    on public.psx_disclosures (trade_date desc);

create index if not exists idx_disclosure_ticker_date
    on public.psx_disclosures (ticker, trade_date desc);

alter table public.psx_disclosures
    enable row level security;

drop policy if exists "public read psx_disclosures"
    on public.psx_disclosures;

create policy "public read psx_disclosures"
    on public.psx_disclosures for select
    to anon, authenticated
    using (true);

grant select on public.psx_disclosures to anon, authenticated;
