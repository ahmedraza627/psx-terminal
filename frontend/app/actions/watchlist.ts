"use server";

import { revalidatePath } from "next/cache";
import { createClient } from "@/lib/supabase/server";

/** PSX symbol rules, enforced client- and database-side. */
const TICKER_RE = /^[A-Z0-9-]{1,20}$/;

/**
 * Typed result for the add action - the client island renders `message`
 * verbatim below the input, so a failure can never be silent again.
 */
export interface WatchlistActionResult {
  ok: boolean;
  /** Human-readable failure reason; null on success. */
  message: string | null;
}

/**
 * The signed-in operator's saved tickers, uppercased and sorted. Called
 * from the console RSC each render; settle-safe (errors degrade to []).
 */
export async function getUserWatchlist(): Promise<string[]> {
  try {
    const supabase = createClient();
    const { data, error } = await supabase
      .from("user_watchlist")
      .select("ticker")
      .order("ticker", { ascending: true });
    if (error != null) {
      console.error("[WATCHLIST_ERROR]", error);
      return [];
    }
    return ((data ?? []) as { ticker: string }[]).map((r) => r.ticker);
  } catch (err) {
    console.error("[WATCHLIST_ERROR]", err);
    return [];
  }
}

/**
 * Add a ticker to the operator's watchlist. Called programmatically by
 * the WatchlistAddForm island (useTransition pattern).
 *
 * Postmortem guard: user_id is inserted EXPLICITLY from the verified
 * session. It also carries an auth.uid() default in migration 004, but
 * never rely on the default from app code - the guard below turns a dead
 * session into an explicit error instead of a silent no-op.
 */
export async function addWatchlistTicker(
  ticker: string,
): Promise<WatchlistActionResult> {
  const symbol = ticker.trim().toUpperCase().slice(0, 20);
  if (!TICKER_RE.test(symbol)) {
    return {
      ok: false,
      message: `Invalid PSX symbol: "${symbol || "empty"}" (letters/digits/hyphen, max 20)`,
    };
  }

  try {
    const supabase = createClient();

    // Authentication guard - verify the session before touching the table.
    const { data: userData, error: userError } = await supabase.auth.getUser();
    if (userError != null || userData?.user == null) {
      console.log("[WATCHLIST_DEBUG] User:", userData?.user?.id ?? null, "Ticker:", symbol);
      console.error("[WATCHLIST_ERROR]", userError ?? new Error("no authenticated session"));
      return { ok: false, message: "Unauthorized: Please log in again" };
    }
    const user = userData.user;

    console.log("[WATCHLIST_DEBUG] User:", user.id, "Ticker:", symbol);

    const { error } = await supabase
      .from("user_watchlist")
      .insert({ ticker: symbol, user_id: user.id });

    if (error != null) {
      console.error("[WATCHLIST_ERROR]", error);
      if (error.code === "23505") {
        return { ok: false, message: `${symbol} is already on your watchlist` };
      }
      if (error.code === "42501") {
        // RLS violation - the insert policy rejected the row.
        return { ok: false, message: "Unauthorized: Please log in again" };
      }
      if (error.code === "23502" || error.code === "23514") {
        return {
          ok: false,
          message: `Table constraint rejected "${symbol}" - run migrations/004_user_watchlist.sql`,
        };
      }
      return { ok: false, message: `Database error (${error.code}): ${error.message}` };
    }

    // Explicit revalidation: the console RSC re-renders with the new chip.
    revalidatePath("/");
    return { ok: true, message: null };
  } catch (err) {
    console.error("[WATCHLIST_ERROR]", err);
    return { ok: false, message: "Unexpected server error - check server logs" };
  }
}

/**
 * POST target for each ticker chip's × button (no-JS server form).
 * Hardened with the same auth guard and logging as the add path.
 */
export async function removeWatchlistTicker(formData: FormData): Promise<void> {
  const ticker = String(formData.get("ticker") ?? "")
    .trim()
    .toUpperCase();
  if (!TICKER_RE.test(ticker)) return;

  try {
    const supabase = createClient();
    const { data: userData } = await supabase.auth.getUser();
    if (userData?.user == null) {
      console.error("[WATCHLIST_ERROR]", new Error("remove without session"));
      return;
    }
    console.log("[WATCHLIST_DEBUG] User:", userData.user.id, "Ticker:", ticker, "(remove)");

    const { error } = await supabase
      .from("user_watchlist")
      .delete()
      .eq("ticker", ticker)
      .eq("user_id", userData.user.id); // belt-and-braces; RLS already scopes
    if (error != null) {
      console.error("[WATCHLIST_ERROR]", error);
      return;
    }
  } catch (err) {
    console.error("[WATCHLIST_ERROR]", err);
    return;
  }
  revalidatePath("/");
}
