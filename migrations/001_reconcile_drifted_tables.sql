-- ===========================================================================
-- 001_reconcile_drifted_tables.sql
--
-- Root cause of the browser-console 400s: four tables exist in the deployed
-- database in an EARLIER DDL draft than repo schema.sql. `create table if
-- not exists` is a no-op on existing tables, so every later rename never
-- migrated; the pipeline's chunked upserts logged the PGRST204 errors and
-- skipped -> three of these tables have silently received ZERO rows.
--
-- Writer contracts (verified against pipeline emit dicts):
--   psx_macro_prediction      main.py via macro_engine.py (trade_date,
--                             driver_code, sector_name, shock_window_sessions,
--                             shock_pct, expected_move_pct, optimal_lag_days,
--                             confidence, stock_plays)
--   psx_macro_correlation     macro_engine.py (trade_date, driver_code,
--                             sector_name, lag_days, correlation, beta,
--                             sample_size, method)
--   psx_insider_disclosures   main.py via psx_insider.py (trade_date, ticker,
--                             insider_name, designation, trade_type, quantity,
--                             rate, notional_pkr, conviction, disclosure_url)
--   signal_backtest_performance  db.upsert_backtest_rows incl. tiered columns
--                             (tp1_hit, tp2_hit, runner_hit, full_stop,
--                             realized_r)
--
-- Every statement is idempotent. Safe to run repeatedly. Run in the Supabase
-- SQL editor with the service-role connection.
-- ===========================================================================

-- ---------------------------------------------------------------------------
-- 1. psx_macro_prediction — add the two columns the live table predates.
-- ---------------------------------------------------------------------------
alter table public.psx_macro_prediction
    add column if not exists shock_window_sessions integer;
alter table public.psx_macro_prediction
    add column if not exists optimal_lag_days integer;

-- Backfill defaults so any legacy rows satisfy NOT NULL where applicable.
update public.psx_macro_prediction
set shock_window_sessions = coalesce(shock_window_sessions, 5)
where shock_window_sessions is null;

alter table public.psx_macro_prediction
    alter column shock_window_sessions set not null;

-- Natural-key upsert (writer: on_conflict="trade_date,driver_code,sector_name").
-- No-op when the constraint already exists.
alter table public.psx_macro_prediction
    drop constraint if exists uq_macro_pred_legacy;
do $$
begin
    if not exists (
        select 1 from pg_constraint c
        join pg_class t on t.oid = c.conrelid
        where t.relname = 'psx_macro_prediction'
          and c.conname = 'uq_macro_pred'
    ) then
        alter table public.psx_macro_prediction
            add constraint uq_macro_pred
            unique (trade_date, driver_code, sector_name);
    end if;
end $$;

create index if not exists idx_macro_pred
    on public.psx_macro_prediction (trade_date desc, driver_code);

-- ---------------------------------------------------------------------------
-- 2. psx_macro_correlation — live table carries only driver_code,
--    sector_name, sample_size. The unique key in place prevents upsert
--    duplicates but the correlation payload itself was never writable.
-- ---------------------------------------------------------------------------
alter table public.psx_macro_correlation
    add column if not exists trade_date date;
alter table public.psx_macro_correlation
    add column if not exists lag_days integer;
alter table public.psx_macro_correlation
    add column if not exists correlation numeric(6, 4);
alter table public.psx_macro_correlation
    add column if not exists beta numeric(10, 4);
alter table public.psx_macro_correlation
    add column if not exists method varchar(32) not null default 'pearson_lagged_ols';

-- Existing rows predate the correlation engine: they cannot carry meaningful
-- lag/r/beta. Clear them so the next pipeline run repopulates cleanly.
delete from public.psx_macro_correlation where trade_date is null;

alter table public.psx_macro_correlation
    alter column trade_date set not null;
alter table public.psx_macro_correlation
    alter column lag_days set not null;
alter table public.psx_macro_correlation
    alter column correlation set not null;
alter table public.psx_macro_correlation
    alter column sample_size set not null;

do $$
begin
    if not exists (
        select 1 from pg_constraint c
        join pg_class t on t.oid = c.conrelid
        where t.relname = 'psx_macro_correlation'
          and c.conname = 'uq_macro_corr'
    ) then
        alter table public.psx_macro_correlation
            add constraint uq_macro_corr
            unique (trade_date, driver_code, sector_name);
    end if;
end $$;

create index if not exists idx_macro_corr
    on public.psx_macro_correlation (trade_date desc, driver_code);

-- ---------------------------------------------------------------------------
-- 3. psx_insider_disclosures — live table predates the conviction ledger:
--    date column is disclosure_date and the trade/size/conviction columns
--    are absent. Add the writer contract and backfill the date rename.
-- ---------------------------------------------------------------------------
alter table public.psx_insider_disclosures
    add column if not exists trade_date date;
alter table public.psx_insider_disclosures
    add column if not exists trade_type varchar(16);
alter table public.psx_insider_disclosures
    add column if not exists quantity bigint;
alter table public.psx_insider_disclosures
    add column if not exists rate numeric(12, 2);
alter table public.psx_insider_disclosures
    add column if not exists notional_pkr numeric(16, 2);
alter table public.psx_insider_disclosures
    add column if not exists conviction varchar(16) not null default 'STANDARD';
alter table public.psx_insider_disclosures
    add column if not exists disclosure_url text;

-- Backfill trade_date from the legacy disclosure_date when present.
update public.psx_insider_disclosures
set trade_date = coalesce(
        trade_date,
        (case
             when exists (
                 select 1 from information_schema.columns c
                 where c.table_schema = 'public'
                   and c.table_name   = 'psx_insider_disclosures'
                   and c.column_name  = 'disclosure_date'
             )
             then disclosure_date
             else null
         end)
)
where trade_date is null;

-- Rows that cannot be dated or sized are unusable to the engine and would
-- violate the NOT NULLs: drop them (legacy draft rows only).
delete from public.psx_insider_disclosures where trade_date is null;
delete from public.psx_insider_disclosures where quantity is null;

alter table public.psx_insider_disclosures
    alter column trade_date set not null;
alter table public.psx_insider_disclosures
    alter column trade_type set not null;
alter table public.psx_insider_disclosures
    alter column quantity set not null;

do $$
begin
    if not exists (
        select 1 from pg_constraint c
        join pg_class t on t.oid = c.conrelid
        where t.relname = 'psx_insider_disclosures'
          and c.conname = 'uq_insider_disclosure'
    ) then
        alter table public.psx_insider_disclosures
            add constraint uq_insider_disclosure
            unique (trade_date, ticker, insider_name, quantity, trade_type);
    end if;
end $$;

create index if not exists idx_insider_conv
    on public.psx_insider_disclosures (trade_date desc, conviction);

-- ---------------------------------------------------------------------------
-- 4. signal_backtest_performance — add the remaining tiered-exit columns.
--    (tp1_hit / realized_r already exist live; the writer's legacy retry has
--    been masking the other three as degraded rows.)
-- ---------------------------------------------------------------------------
alter table public.signal_backtest_performance
    add column if not exists tp2_hit boolean;
alter table public.signal_backtest_performance
    add column if not exists runner_hit boolean;
alter table public.signal_backtest_performance
    add column if not exists full_stop boolean;

-- ---------------------------------------------------------------------------
-- 5. Public read policies — re-assert in case the drifted tables were created
--    without the anon SELECT grants the frontend depends on.
-- ---------------------------------------------------------------------------
alter table public.psx_macro_prediction      enable row level security;
alter table public.psx_macro_correlation     enable row level security;
alter table public.psx_insider_disclosures   enable row level security;
alter table public.signal_backtest_performance enable row level security;

drop policy if exists "public read psx_macro_prediction"
    on public.psx_macro_prediction;
create policy "public read psx_macro_prediction"
    on public.psx_macro_prediction for select using (true);

drop policy if exists "public read psx_macro_correlation"
    on public.psx_macro_correlation;
create policy "public read psx_macro_correlation"
    on public.psx_macro_correlation for select using (true);

drop policy if exists "public read psx_insider_disclosures"
    on public.psx_insider_disclosures;
create policy "public read psx_insider_disclosures"
    on public.psx_insider_disclosures for select using (true);

drop policy if exists "public read signal_backtest_performance"
    on public.signal_backtest_performance;
create policy "public read signal_backtest_performance"
    on public.signal_backtest_performance for select using (true);
