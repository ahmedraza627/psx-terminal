-- ============================================================================
-- 003 - Lock console read access behind Supabase Auth.
--
-- The terminal now authenticates every request through Supabase
-- (@supabase/ssr middleware + /login). Until RLS reflects that, the ANON
-- key can still read the market tables directly from the REST endpoint -
-- the middleware would be decoration. Run ONCE in the Supabase SQL editor.
--
-- Effects:
--   * anon key  -> ZERO rows on all three console tables (401/empty)
--   * authenticated (logged-in via /login) -> full read access
--   * pipeline (service_role key) -> unaffected (service_role bypasses RLS)
--
-- One-time dashboard setup:
--   1. Authentication > Providers > Email: enable (disable confirmations
--      for hand-created operators).
--   2. Authentication > Users > Add user: create each operator
--      (email + password). No public signup exists.
--   3. Project Settings > API: copy the anon key into
--      NEXT_PUBLIC_SUPABASE_ANON_KEY (it now gates, not serves).
-- ============================================================================

-- Safety: RLS must be on for every table we touch.
ALTER TABLE public.psx_daily_eod        ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.nccpl_fipi_lipi      ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.psx_offmarket_deals  ENABLE ROW LEVEL SECURITY;

-- Replace every existing SELECT policy (legacy anon-read grants included)
-- with a single authenticated-only read policy, per table.
DO $$
DECLARE
  t  text;
  pol record;
BEGIN
  FOREACH t IN ARRAY ARRAY[
    'psx_daily_eod',
    'nccpl_fipi_lipi',
    'psx_offmarket_deals'
  ]
  LOOP
    -- Drop ALL existing SELECT policies on the table, whatever their names.
    FOR pol IN
      SELECT policyname
      FROM pg_policies
      WHERE schemaname = 'public'
        AND tablename  = t
        AND cmd        = 'SELECT'
    LOOP
      EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', pol.policyname, t);
    END LOOP;

    -- Single certified read path: signed-in operators only.
    EXECUTE format(
      'CREATE POLICY "read_requires_authenticated" ON public.%I
       FOR SELECT TO authenticated
       USING (true);',
      t
    );
  END LOOP;
END $$;

-- ---------------------------------------------------------------------------
-- VERIFY (expect: role=authenticated rows only, role=anon returns 0 rows):
--   select tablename, policyname, roles from pg_policies
--    where schemaname='public' and tablename like 'psx_%'
--       or tablename = 'nccpl_fipi_lipi';
-- ---------------------------------------------------------------------------
