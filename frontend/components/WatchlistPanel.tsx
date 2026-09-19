import WatchlistAddForm from "@/components/WatchlistAddForm";
import { removeWatchlistTicker } from "@/app/actions/watchlist";
import { fmtInt, fmtPct } from "@/components/ui/format";
import type { WatchlistContext } from "@/lib/watchlistFilter";

/**
 * MY PORTFOLIO - the per-user watchlist, rendered as a server component
 * with server actions. Zero client JS: add is a plain form post, remove is
 * a per-chip form post, and each chip links to the ticker deep-dive.
 *
 * Flow honesty: NCCPL publishes participant x SECTOR nets only. The flow
 * strip below the chips is the market-wide participant cut - it is NOT
 * attributed to the watchlist tickers, and the label says so.
 */
export default function WatchlistPanel({ ctx }: { ctx: WatchlistContext }) {
  const { tickers, matchedNdm, flowParticipants } = ctx;

  return (
    <section className="border border-hairline bg-panel">
      <header className="flex items-center justify-between gap-2 border-b border-hairline bg-obsidian/60 px-3 py-2">
        <h2 className="flex items-baseline gap-2 font-mono text-[11px] font-bold uppercase tracking-[0.18em] text-ink">
          <span className="text-info">P</span>
          My Portfolio
        </h2>
        <span className="font-mono text-[10px] tabular-nums text-ghost">
          {tickers.length} NAMES
        </span>
      </header>

      <div className="px-3 py-2.5">
        {/* Add form - client island; errors render inline, never silent. */}
        <WatchlistAddForm />

        {tickers.length === 0 ? (
          <p className="pt-2.5 font-mono text-[10px] uppercase tracking-widest text-ghost">
            NO NAMES SAVED - ADD A TICKER TO TRACK ITS BLOCK TAPE PRINTS
          </p>
        ) : (
          <div className="flex flex-wrap gap-1.5 pt-2.5">
            {tickers.map((t) => {
              const print = matchedNdm.find((b) => b.ticker === t);
              return (
                <span
                  key={t}
                  className="inline-flex items-center gap-1.5 border border-hairline bg-obsidian px-1.5 py-1"
                >
                  <a
                    href={`/ticker/${t}`}
                    className="font-mono text-[11px] font-bold text-ink hover:text-info"
                    title="Open ticker deep-dive"
                  >
                    {t}
                  </a>
                  {print != null && (
                    <span
                      className={`font-mono text-[9px] tabular-nums ${
                        (print.spreadPct ?? 0) >= 0
                          ? "text-bull"
                          : "text-bear"
                      }`}
                    >
                      {fmtInt(print.quantity)} @ {fmtPct(print.spreadPct, 1)}
                    </span>
                  )}
                  <form action={removeWatchlistTicker}>
                    <input type="hidden" name="ticker" value={t} />
                    <button
                      type="submit"
                      aria-label={`Remove ${t}`}
                      title={`Remove ${t}`}
                      className="px-0.5 font-mono text-[10px] leading-none text-ghost hover:text-bear"
                    >
                      ✕
                    </button>
                  </form>
                </span>
              );
            })}
          </div>
        )}

        {matchedNdm.length > 0 && (
          <p className="pt-2 font-mono text-[10px] uppercase tracking-wider text-bull/80">
            {matchedNdm.length} WATCHLIST NAME
            {matchedNdm.length === 1 ? "" : "S"} ON TODAY&apos;S NDM TAPE
          </p>
        )}

        {/* Market-wide participant cut - explicitly NOT per-ticker. */}
        {flowParticipants.length > 0 && (
          <div className="mt-2.5 border-t border-hairline pt-2">
            <p className="font-mono text-[9px] uppercase tracking-[0.2em] text-ghost">
              MARKET-WIDE PARTICIPANT NET (NCCPL - NOT PER-TICKER ATTRIBUTABLE)
            </p>
            <p className="pt-1 font-mono text-[10px] tabular-nums text-muted">
              {flowParticipants
                .filter((p) =>
                  ["FIPI", "MUTUAL FUNDS", "INDIVIDUALS"].includes(
                    p.participantType,
                  ),
                )
                .map((p) => {
                  const v = p.net1dPkr;
                  const txt =
                    v == null ? "—" : `${v > 0 ? "+" : ""}${(v / 1e6).toFixed(1)}M`;
                  return (
                    <span key={p.participantType} className="mr-3 whitespace-nowrap">
                      {p.participantType}{" "}
                      <span
                        className={
                          v == null
                            ? "text-ghost"
                            : v > 0
                              ? "text-bull"
                              : v < 0
                                ? "text-bear"
                                : "text-muted"
                        }
                      >
                        {txt}
                      </span>
                    </span>
                  );
                })}
            </p>
          </div>
        )}
      </div>
    </section>
  );
}
