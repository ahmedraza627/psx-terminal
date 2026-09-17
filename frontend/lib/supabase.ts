import { createClient, type SupabaseClient } from "@supabase/supabase-js";

/**
 * Shared Supabase anon client (browser + server components).
 * The env check is LAZY - it fires on the first getSupabase() call, never at
 * module import, so builds and client chunks never break on missing env.
 */
let client: SupabaseClient | null = null;

export function getSupabase(): SupabaseClient {
  if (!client) {
    const url = process.env.NEXT_PUBLIC_SUPABASE_URL ?? "";
    const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "";
    if (!url || !key) {
      throw new Error(
        "Missing NEXT_PUBLIC_SUPABASE_URL / NEXT_PUBLIC_SUPABASE_ANON_KEY. " +
          "This terminal queries live Supabase data only - no fallbacks."
      );
    }
    client = createClient(url, key, {
      auth: { persistSession: false, autoRefreshToken: false },
    });
  }
  return client;
}
