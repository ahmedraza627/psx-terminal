-- ============================================================================
-- 011 - Institutional Alpha Engine upgrade: dynamic position sizing and the
-- macro tape state, written by the decision engine alongside the risk math.
--
-- suggested_alloc_pct         % of portfolio to allocate, from the fixed-
--                             fractional 1.5% risk model, capped at 15%.
-- max_volume_capacity_shares  order size capped at 2% of 20D avg volume so
--                             the exit stays liquid (no lower-circuit lock).
-- macro_tape_state            RISK_ON | NEUTRAL | DEFENSIVE_CASH from the
--                             KSE-100 50D SMA + advance/decline gate.
--
-- All three degrade gracefully when this migration is pending: the writer
-- strips unknown columns on PGRST204/42703, so the feed keeps flowing and
-- the frontend simply hides the sizing/tape UI until the columns land.
-- Re-runnable (IF NOT EXISTS on every statement).
-- ============================================================================

alter table public.psx_system_verdicts
  add column if not exists suggested_alloc_pct numeric(5, 2);

alter table public.psx_system_verdicts
  add column if not exists max_volume_capacity_shares integer;

alter table public.psx_system_verdicts
  add column if not exists macro_tape_state varchar(50) default 'NEUTRAL';

-- Existing public read policy + grant cover the new columns; refresh both
-- so a re-run also repairs a drifted policy.
drop policy if exists "public_read" on public.psx_system_verdicts;
create policy "public_read" on public.psx_system_verdicts for select to anon, authenticated using (true);

grant select on public.psx_system_verdicts to anon, authenticated;
