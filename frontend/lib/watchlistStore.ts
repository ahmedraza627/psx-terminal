// ---------------------------------------------------------------------------
// BROWSER-LOCAL WATCHLIST STORE.
//
// The terminal is fully public (no auth): the watchlist lives entirely in
// each visitor's localStorage. No Supabase calls, no server actions, no
// user_id - add/remove are synchronous client operations.
// ---------------------------------------------------------------------------

const STORAGE_KEY = "psx-desk-watchlist";

/** PSX symbols: uppercase alphanumerics with optional hyphen (OGDC, MARI, SNGPL). */
export const TICKER_RE = /^[A-Z0-9-]{1,20}$/;

export function loadWatchlist(): string[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    const parsed: unknown = raw == null ? [] : JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((t): t is string => typeof t === "string")
      .map((t) => t.trim().toUpperCase())
      .filter((t) => TICKER_RE.test(t));
  } catch {
    return [];
  }
}

function saveWatchlist(tickers: string[]): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(tickers));
  } catch {
    // Storage full / disabled - watchlist simply becomes session-only.
  }
}

export type AddResult =
  | { ok: true; tickers: string[] }
  | { ok: false; message: string };

export function addTicker(input: string): AddResult {
  const symbol = input.trim().toUpperCase();
  if (!TICKER_RE.test(symbol)) {
    return {
      ok: false,
      message: `Invalid ticker: "${input.trim() || "empty"}" - use letters/digits, max 20 chars`,
    };
  }
  const current = loadWatchlist();
  if (current.includes(symbol)) {
    return { ok: false, message: `${symbol} is already on your watchlist` };
  }
  const next = [...current, symbol];
  saveWatchlist(next);
  return { ok: true, tickers: next };
}

export function removeTicker(symbol: string): string[] {
  const next = loadWatchlist().filter((t) => t !== symbol);
  saveWatchlist(next);
  return next;
}
