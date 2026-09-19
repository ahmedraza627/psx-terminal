-- ============================================================================
-- 004 - "My Portfolio" watchlist + private-read alignment.
--
-- One row per (user, ticker). Users see ONLY their own rows via RLS.
-- Run once in the Supabase SQL editor; safe to re-run (idempotent).
-- ============================================================================

create table if not exists public.user_watchlist (
    id         uuid primary key default gen_random_uuid(),
    user_id    uuid         not null references auth.users (id) on delete cascade,
    ticker     varchar(20)  not null,
    created_at timestamptz  not null default now(),
    constraint user_watchlist_user_ticker_key unique (user_id, ticker),
    -- PSX symbols: uppercase letters/digits and the -FUT style hyphen only.
    -- Normalization happens in the app before insert; this is the last guard.
    constraint user_watchlist_ticker_format
        check (ticker = upper(ticker) and ticker ~ '^[A-Z0-9\-]{1,20}$')
);

create index if not exists user_watchlist_user_idx
    on public.user_watchlist (user_id, created_at desc);

-- Belt-and-braces: if an insert ever omits user_id, stamp it from the
-- session instead of failing with a silent-looking not-null violation.
alter table public.user_watchlist
    alter column user_id set default auth.uid();

-- Table-level privileges (RLS then scopes rows). Explicit grants make a
-- missing-permission failure impossible to confuse with app logic.
grant select, insert, delete on public.user_watchlist to authenticated;
revoke all on public.user_watchlist from anon;

-- ---------------------------------------------------------------------------
-- RLS: each operator reads/inserts/deletes ONLY their own rows.
-- (update is intentionally not granted - watchlists are append/remove.)
-- ---------------------------------------------------------------------------
alter table public.user_watchlist enable row level security;

drop policy if exists "watchlist_select_own" on public.user_watchlist;
drop policy if exists "watchlist_insert_own" on public.user_watchlist;
drop policy if exists "watchlist_delete_own" on public.user_watchlist;

create policy "watchlist_select_own" on public.user_watchlist
    for select to authenticated
    using (auth.uid() = user_id);

create policy "watchlist_insert_own" on public.user_watchlist
    for insert to authenticated
    with check (auth.uid() = user_id);

create policy "watchlist_delete_own" on public.user_watchlist
    for delete to authenticated
    using (auth.uid() = user_id);

-- ---------------------------------------------------------------------------
-- Console-table read access stays locked to authenticated sessions.
-- (Mirrors 003 for operators who have not run it yet; no-op afterwards.)
-- The pipeline writes with service_role, which bypasses RLS entirely.
-- ---------------------------------------------------------------------------
revoke select on public.psx_daily_eod        from anon;
revoke select on public.nccpl_fipi_lipi      from anon;
revoke select on public.psx_offmarket_deals  from anon;
revoke select on public.psx_insider_trades   from anon;
revoke select on public.psx_fundamentals     from anon;

grant select on public.psx_daily_eod       to authenticated;
grant select on public.nccpl_fipi_lipi     to authenticated;
grant select on public.psx_offmarket_deals to authenticated;
grant select on public.psx_insider_trades  to authenticated;
grant select on public.psx_fundamentals    to authenticated;

-- ---------------------------------------------------------------------------
-- Verify:
--   select * from pg_policies where tablename = 'user_watchlist';
--   -- as a logged-in user:
--   insert into public.user_watchlist (ticker) values ('OGDC') returning *;
--   select * from public.user_watchlist;  -- only your own rows
-- ---------------------------------------------------------------------------
