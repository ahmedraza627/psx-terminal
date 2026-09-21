-- ============================================================================
-- 005 - Reopen the console to PUBLIC READ (auth wall removed).
--
-- The Next.js middleware gate, /login and SessionTimeout have been deleted;
-- the frontend now reads with the anon key and no session. Without this
-- migration every panel would render ZERO rows: migration 003 revoked anon
-- SELECT and replaced it with an authenticated-only policy.
--
-- Run ONCE in the Supabase SQL editor. Idempotent - safe to re-run.
-- The pipeline is unaffected (service_role bypasses RLS entirely).
-- ============================================================================

-- 1. Public read on every table the console queries.
ALTER TABLE public.psx_daily_eod        ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.nccpl_fipi_lipi      ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.psx_offmarket_deals  ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.psx_insider_trades   ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.psx_fundamentals     ENABLE ROW LEVEL SECURITY;

DO $$
DECLARE
  t  text;
  pol record;
BEGIN
  FOREACH t IN ARRAY ARRAY[
    'psx_daily_eod',
    'nccpl_fipi_lipi',
    'psx_offmarket_deals',
    'psx_insider_trades',
    'psx_fundamentals'
  ]
  LOOP
    -- Replace ALL existing SELECT policies (authenticated-only from 003,
    -- plus any legacy grants) with one public read policy.
    FOR pol IN
      SELECT policyname
      FROM pg_policies
      WHERE schemaname = 'public'
        AND tablename  = t
        AND cmd        = 'SELECT'
    LOOP
      EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', pol.policyname, t);
    END LOOP;

    EXECUTE format(
      'CREATE POLICY "public_read" ON public.%I
       FOR SELECT TO anon, authenticated
       USING (true);',
      t
    );
  END LOOP;
END $$;

-- 2. Anon must hold the table-level SELECT privilege as well (RLS then
--    scopes rows). Mirror-image of the revoke in migration 003/004.
GRANT SELECT ON public.psx_daily_eod        TO anon;
GRANT SELECT ON public.nccpl_fipi_lipi      TO anon;
GRANT SELECT ON public.psx_offmarket_deals  TO anon;
GRANT SELECT ON public.psx_insider_trades   TO anon;
GRANT SELECT ON public.psx_fundamentals     TO anon;

-- 3. user_watchlist is dead: writes were server-action/RFS-guarded and the
--    actions are deleted. Nothing writes to it, so drop it entirely.
--    (Watchlists now live in each visitor's localStorage.)
DROP TABLE IF EXISTS public.user_watchlist CASCADE;

-- Revoke the privilege grants that no longer have a table (no-ops if
-- already gone, kept for operators re-running the whole chain).
REVOKE ALL ON public.user_watchlist FROM anon, authenticated;

-- ---------------------------------------------------------------------------
-- VERIFY:
--   select tablename, policyname, roles from pg_policies
--    where schemaname='public'
--      and tablename in ('psx_daily_eod','nccpl_fipi_lipi','psx_offmarket_deals',
--                        'psx_insider_trades','psx_fundamentals');
--   -- every row above must show roles = {anon,authenticated}
--   select to_regclass('public.user_watchlist');   -- expect NULL
--   -- smoke test with the anon key (no auth header):
--   --   curl "$SUPABASE_URL/rest/v1/psx_daily_eod?select=trade_date&limit=1" \
--   --     -H "apikey: $SUPABASE_ANON_KEY"
--   -- expect 200 + one row, not 401/empty.
-- ---------------------------------------------------------------------------
