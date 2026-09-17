-- ============================================================================
-- 002 - psx_daily_eod schema-drift repair (idempotent).
--
-- Symptom: the scraper parses the full ~500-ticker market-watch universe,
-- but `upsert_records` commits ZERO rows. Root cause: the DEPLOYED table was
-- created from an older DDL and lacks the OHLC columns the scraper emits
-- (open_price / high_price / low_price). Every upsert chunk fails with
-- PostgREST PGRST204 ("column not present"), the writer logged-and-skipped,
-- and the run exited green - leaving Panel C reading a stale/partial
-- session (the "9-ticker universe").
--
-- Run this ONCE in the Supabase SQL editor (service-role connection).
-- Every statement is idempotent: safe to re-run.
-- ============================================================================

-- 1. Add the missing OHLC columns (no-ops if already present). ---------------
alter table public.psx_daily_eod
    add column if not exists open_price  numeric(10, 2);
alter table public.psx_daily_eod
    add column if not exists high_price  numeric(10, 2);
alter table public.psx_daily_eod
    add column if not exists low_price   numeric(10, 2);

-- 2. Guarantee the natural key the upsert conflicts on. ----------------------
-- If the deployed table predates the constraint, backfill duplicates can
-- exist (failed upserts never wrote, but plain inserts may have); dedupe
-- first keeping the LOWEST id per (trade_date, ticker), then create the
-- unique index if neither the constraint nor an equivalent index exists.
do $$
begin
    delete from public.psx_daily_eod a
    using public.psx_daily_eod b
    where a.trade_date = b.trade_date
      and a.ticker     = b.ticker
      and a.id        > b.id;

    if not exists (
        select 1 from pg_constraint c
        join pg_class t on t.oid = c.conrelid
        where t.relname = 'psx_daily_eod'
          and c.contype = 'u'
          and (
              select string_agg(att.attname, ',' order by att.attnum)
              from unnest(c.conkey) k
              join pg_attribute att on att.attrelid = c.conrelid and att.attnum = k
          ) = 'trade_date,ticker'
    ) and not exists (
        select 1 from pg_indexes
        where tablename = 'psx_daily_eod'
          and indexdef ilike '%unique%(trade_date, ticker)%'
    ) then
        create unique index psx_daily_eod_date_ticker_repair_uidx
            on public.psx_daily_eod (trade_date, ticker);
    end if;
end $$;

-- 3. Price sanity (matches schema.sql) - no-op when present. ------------------
do $$
begin
    if not exists (
        select 1 from pg_constraint
        where conname = 'psx_daily_eod_price_sanity'
    ) then
        alter table public.psx_daily_eod
            add constraint psx_daily_eod_price_sanity
            check (close_price is null or close_price > 0);
    end if;
end $$;

-- 4. Anonymous read access for the RSC console (idempotent). ------------------
do $$
begin
    if not exists (
        select 1 from pg_policies
        where schemaname = 'public'
          and tablename  = 'psx_daily_eod'
          and policyname = 'anon read psx_daily_eod'
    ) then
        create policy "anon read psx_daily_eod"
            on public.psx_daily_eod
            for select
            to anon
            using (true);
    end if;
end $$;

-- 5. Verify (run manually after applying): ------------------------------------
--   select column_name from information_schema.columns
--    where table_name = 'psx_daily_eod' order by ordinal_position;
--   select trade_date, count(*) from psx_daily_eod
--    group by 1 order by 1 desc limit 5;   -- expect ~500+ rows/session
--
-- Then run:  python main.py
-- The pipeline now fails LOUDLY if it scrapes >0 rows but writes 0.
