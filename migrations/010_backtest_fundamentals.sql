-- ============================================================================
-- 010 - backtest proof + fundamental filter (psx_system_verdicts).
--
-- The decision engine now stamps every BUY verdict with:
--   historical_win_rate  - the strategy's win rate (%) from a 3-year
--                          walk-forward backtest of the same entry/stop/
--                          target logic on the ticker's own tape. Null
--                          when history is insufficient (< 30 sessions) or
--                          no historical signal fired - never fabricated.
--   fundamental_score    - 'PROFITABLE (PE > 0)' once the strict PE gate
--                          passed, else 'UNVERIFIED' (default).
--
-- Columns are added with IF NOT EXISTS so the migration is re-runnable.
-- Run ONCE in the Supabase SQL Editor. Safe to re-run.
-- ============================================================================

alter table public.psx_system_verdicts
  add column if not exists historical_win_rate numeric(5, 2);

alter table public.psx_system_verdicts
  add column if not exists fundamental_score varchar(50) default 'UNVERIFIED';

-- Existing public read covers the new columns; refresh the policy/grant.
drop policy if exists "public_read" on public.psx_system_verdicts;
create policy "public_read" on public.psx_system_verdicts for select to anon, authenticated using (true);

grant select on public.psx_system_verdicts to anon, authenticated;
