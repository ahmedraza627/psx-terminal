import { createClient as createSupabaseClient } from "@supabase/supabase-js";

/**
 * Public anonymous Supabase client for server components.
 *
 * The terminal is fully public: no auth wall, no cookies, no session.
 * Sessions are disabled outright (persistSession: false) so no auth
 * storage is touched and the anon key's read access is governed purely
 * by the database's RLS policies (see migrations/005_public_read_access.sql).
 *
 * LIVE DATA GUARANTEE: every request is issued with cache: "no-store".
 * Next.js otherwise treats supabase-js fetches as cacheable by default,
 * which froze the Action Desk's session pill on a stale trade_date between
 * builds (the certified session could not advance to the next EOD day).
 * Certified facts must be read fresh on every render.
 */
export function createClient() {
  const noStoreFetch: typeof fetch = (input, init) =>
    fetch(input, { ...init, cache: "no-store" });
  return createSupabaseClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL ?? "",
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "",
    {
      auth: { persistSession: false, autoRefreshToken: false },
      global: { fetch: noStoreFetch },
    },
  );
}
