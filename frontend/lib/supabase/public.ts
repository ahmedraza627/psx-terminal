import { createClient as createSupabaseClient } from "@supabase/supabase-js";

/**
 * Public anonymous Supabase client for server components.
 *
 * The terminal is fully public: no auth wall, no cookies, no session.
 * Sessions are disabled outright (persistSession: false) so no auth
 * storage is touched and the anon key's read access is governed purely
 * by the database's RLS policies (see migrations/005_public_read_access.sql).
 */
export function createClient() {
  return createSupabaseClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL ?? "",
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "",
    { auth: { persistSession: false, autoRefreshToken: false } },
  );
}
