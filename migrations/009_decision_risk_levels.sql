-- ============================================================================
-- 009 - decision engine risk math (psx_system_verdicts execution fields).
--
-- Upserts rows with a certified candidate now freshly written by the
-- decision engine carry execution fields: entry_ref, stop_loss,
-- target_price, risk_reward_ratio and regime_status. Columns are added
-- with IF NOT EXISTS so the migration is re-runnable.
--
-- Run ONCE in the Supabase SQL Editor. Safe to re-run.
-- ============================================================================

-- Execution levels: ONE row per (trade_date, horizon) now carries the
-- numbers the Action Desk cards display: entry (latest session close, or
-- structural), stop-loss (3-day swing low / ATR), target (2:1 min R:R),
-- and the rounded risk-reward ratio.
alter table public.psx_system_verdicts
  add column if not exists entry_ref numeric(12, 2);

alter table public.psx_system_verdicts
  add column if not exists stop_loss numeric(12, 2);

alter table public.psx_system_verdicts
  add column if not exists target_price numeric(12, 2);

alter table public.psx_system_verdicts
  add column if not exists risk_reward_ratio numeric(6, 2);

-- Market regime stamp on every verdict row (institutional risk framing).
alter table public.psx_system_verdicts
  add column if not exists regime_status varchar(50) default 'NORMAL';

-- Existing public read + the new numeric columns.
drop policy if exists "public_read" on public.psx_system_verdicts;
create policy "public_read" on public.psx_system_verdicts for select to anon, authenticated using (true);

grant select on public.psx_system_verdicts to anon, authenticated;

create index if not exists psx_system_verdicts_date_idx on public.psx_system_verdicts (trade_date desc);
