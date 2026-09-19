// ---------------------------------------------------------------------------
// WATCHLIST FILTER - pure, factual intersection of the user's saved tickers
// with the console's already-fetched certified data. No new queries, no
// scoring: a row shows up here only because it is the same fact the panels
// render, restricted to the watchlist.
//
// HONEST SCOPE NOTE: NCCPL publishes participant x SECTOR nets only - there
// is no per-ticker institutional flow column in the stored schema. So the
// "flow side" of the watchlist surfaces the market-wide participant cut next
// to the user's names' NDM prints, clearly labeled market-wide. Per-ticker
// sector flow lives in the deep-dive (mapped via psx_fundamentals).
// ---------------------------------------------------------------------------

import type { FlowMatrixData, NdmBlock, ParticipantFlow } from "./consoleQueries";

export interface WatchlistContext {
  /** Saved tickers, uppercased, sorted. */
  tickers: string[];
  /** NDM blocks (latest tape) whose ticker is on the watchlist. */
  matchedNdm: NdmBlock[];
  /**
   * Participant net cut (1D/5D/30D) - market-wide by NCCPL's own design.
   * Returned as-is so the panel can present it next to watchlist NDM prints
   * without implying per-ticker attribution that does not exist.
   */
  flowParticipants: ParticipantFlow[];
}

export function buildWatchlistContext(
  tickers: string[],
  flow: FlowMatrixData | null,
  ndm: NdmBlock[] | null,
): WatchlistContext {
  const set = new Set(
    tickers.map((t) => t.trim().toUpperCase()).filter((t) => t !== ""),
  );
  return {
    tickers: Array.from(set).sort(),
    matchedNdm: (ndm ?? []).filter((b) => set.has(b.ticker)),
    flowParticipants: flow?.participants ?? [],
  };
}
