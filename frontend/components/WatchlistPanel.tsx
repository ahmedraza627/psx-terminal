"use client";

import { useEffect, useMemo, useState, type FormEvent } from "react";
import { addTicker, removeTicker, loadWatchlist } from "@/lib/watchlistStore";
import { fmtInt, fmtPct } from "@/components/ui/format";
import type { BreadthData, NdmBlock } from "@/lib/consoleQueries";

/**
 * MY PORTFOLIO - browser-local watchlist (localStorage).
 *
 * Fully public terminal: no auth, no server actions, no user_id. Add/remove
 * are synchronous client operations persisted under "psx-desk-watchlist".
 * Chips link to the public /ticker/[ticker] deep-dive and surface the
 * session's certified facts (NDM print, close-over-close verdict) straight
 * from the props the console already fetched - filtering the existing tape,
 * never re-querying Supabase.
 */
export default function WatchlistPanel({
  ndm,
  breadth,
}: {
  ndm: NdmBlock[] | null;
  breadth: BreadthData | null;
}) {
  const [tickers, setTickers] = useState<string[]>([]);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);

  // Hydrate from localStorage after mount (SSR paints the empty state first,
  // so there is no hydration mismatch).
  useEffect(() => {
    setTickers(loadWatchlist());
  }, []);

  const tape = ndm ?? [];

  // Watchlist rows filtered OUT of the already-fetched tape (no queries).
  const onTape = useMemo(
    () => tape.filter((b) => tickers.includes(b.ticker)),
    [tape, tickers],
  );

  // Watchlist close-over-close verdicts from the certified breadth set.
  const movers = useMemo(() => {
    if (breadth == null) return [];
    return breadth.moves
      .filter((m) => tickers.includes(m.ticker) && m.changePct != null)
      .sort((a, b) => Math.abs(b.changePct ?? 0) - Math.abs(a.changePct ?? 0))
      .slice(0, 8);
  }, [breadth, tickers]);

  const handleAdd = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const result = addTicker(draft);
    if (!result.ok) {
      setError(result.message);
      return;
    }
    setTickers(result.tickers);
    setDraft("");
    setError(null);
  };

  const handleRemove = (t: string) => {
    setTickers(removeTicker(t));
    setError(null);
  };

  return (
    <section className="border border-hairline bg-panel">
      <header className="flex items-center justify-between gap-2 border-b border-hairline bg-obsidian/60 px-3 py-2">
        <h2 className="flex items-baseline gap-2 font-mono text-[11px] font-bold uppercase tracking-[0.18em] text-ink">
          <span className="text-info">P</span>
          My Portfolio
        </h2>
        <span className="font-mono text-[10px] tabular-nums text-ghost">
          {tickers.length} NAMES · BROWSER-LOCAL
        </span>
      </header>

      <div className="px-3 py-2.5">
        {/* Add form - inline validation, errors never silent. */}
        <form onSubmit={handleAdd} className="flex items-center gap-2">
          <input
            type="text"
            value={draft}
            onChange={(e) => {
              setDraft(e.target.value);
              if (error != null) setError(null);
            }}
            maxLength={20}
            placeholder="ADD TICKER (E.G. OGDC)"
            aria-label="Ticker to add"
            className="min-w-0 flex-1 border border-hairline bg-obsidian px-2 py-1 font-mono text-[11px] uppercase tracking-widest text-ink placeholder:text-ghost/60 focus:border-info focus:outline-none"
          />
          <button
            type="submit"
            className="border border-info/40 bg-info/10 px-2 py-1 font-mono text-[10px] font-bold uppercase tracking-widest text-info hover:bg-info/20"
          >
            Add
          </button>
        </form>
        {error != null && (
          <p role="alert" className="pt-1.5 font-mono text-[10px] text-bear">
            ▲ {error}
          </p>
        )}

        {tickers.length === 0 ? (
          <p className="pt-2.5 font-mono text-[10px] uppercase tracking-widest text-ghost">
            NO NAMES SAVED - ADD A TICKER TO TRACK ITS BLOCK TAPE PRINTS
          </p>
        ) : (
          <div className="flex flex-wrap gap-1.5 pt-2.5">
            {tickers.map((t) => {
              const print = tape.find((b) => b.ticker === t);
              const verdict = breadth?.moves.find((m) => m.ticker === t);
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
                        (print.spreadPct ?? 0) >= 0 ? "text-bull" : "text-bear"
                      }`}
                      title="Today's NDM print: volume @ spread vs market"
                    >
                      {fmtInt(print.quantity)} @ {fmtPct(print.spreadPct, 1)}
                    </span>
                  )}
                  {verdict?.changePct != null && (
                    <span
                      className={`font-mono text-[9px] tabular-nums ${
                        verdict.changePct >= 0 ? "text-bull" : "text-bear"
                      }`}
                      title="Close-over-close verdict"
                    >
                      {fmtPct(verdict.changePct, 2)}
                    </span>
                  )}
                  <button
                    type="button"
                    onClick={() => handleRemove(t)}
                    aria-label={`Remove ${t}`}
                    title={`Remove ${t}`}
                    className="px-0.5 font-mono text-[10px] leading-none text-ghost hover:text-bear"
                  >
                    ✕
                  </button>
                </span>
              );
            })}
          </div>
        )}

        {/* Filtered slice of the existing NDM tape - watchlist names only. */}
        {onTape.length > 0 && (
          <div className="mt-2.5 border-t border-hairline pt-2">
            <p className="font-mono text-[9px] uppercase tracking-[0.2em] text-ghost">
              {onTape.length} WATCHLIST NAME{onTape.length === 1 ? "" : "S"} ON
              TODAY&apos;S NDM TAPE
            </p>
            <div className="overflow-x-auto">
              <table className="w-full border-collapse">
                <thead>
                  <tr>
                    <th className="border-b border-hairline px-2 py-1 text-left font-mono text-[9px] font-semibold uppercase tracking-[0.15em] text-ghost">
                      Ticker
                    </th>
                    <th className="border-b border-hairline px-2 py-1 text-right font-mono text-[9px] font-semibold uppercase tracking-[0.15em] text-ghost">
                      Volume
                    </th>
                    <th className="border-b border-hairline px-2 py-1 text-right font-mono text-[9px] font-semibold uppercase tracking-[0.15em] text-ghost">
                      Rate
                    </th>
                    <th className="border-b border-hairline px-2 py-1 text-right font-mono text-[9px] font-semibold uppercase tracking-[0.15em] text-ghost">
                      Mkt
                    </th>
                    <th className="border-b border-hairline px-2 py-1 text-right font-mono text-[9px] font-semibold uppercase tracking-[0.15em] text-ghost">
                      Spread %
                    </th>
                    <th className="border-b border-hairline px-2 py-1 text-right font-mono text-[9px] font-semibold uppercase tracking-[0.15em] text-ghost">
                      Flag
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {onTape.map((b, i) => (
                    <tr
                      key={`${b.ticker}-${b.quantity}-${i}`}
                      className={
                        b.distribution
                          ? "bg-bear/10"
                          : b.accumulation
                            ? "bg-bull/10"
                            : "hover:bg-hoverline"
                      }
                    >
                      <td className="whitespace-nowrap border-b border-hairline/60 px-2 py-1 font-mono text-[11px] font-bold text-ink">
                        <a href={`/ticker/${b.ticker}`} className="hover:text-info">
                          {b.ticker}
                        </a>
                      </td>
                      <td className="whitespace-nowrap border-b border-hairline/60 px-2 py-1 text-right font-mono text-[11px] tabular-nums text-ink">
                        {fmtInt(b.quantity)}
                      </td>
                      <td className="whitespace-nowrap border-b border-hairline/60 px-2 py-1 text-right font-mono text-[11px] tabular-nums text-ink">
                        {b.rate == null ? "—" : b.rate.toFixed(2)}
                      </td>
                      <td className="whitespace-nowrap border-b border-hairline/60 px-2 py-1 text-right font-mono text-[11px] tabular-nums text-muted">
                        {b.marketPrice == null ? "—" : b.marketPrice.toFixed(2)}
                      </td>
                      <td
                        className={`whitespace-nowrap border-b border-hairline/60 px-2 py-1 text-right font-mono text-[11px] tabular-nums ${
                          b.spreadPct == null
                            ? "text-ghost"
                            : b.spreadPct < 0
                              ? "text-bear"
                              : "text-bull"
                        }`}
                      >
                        {fmtPct(b.spreadPct, 1)}
                      </td>
                      <td
                        className={`whitespace-nowrap border-b border-hairline/60 px-2 py-1 text-right font-mono text-[9px] font-bold uppercase tracking-widest ${
                          b.distribution
                            ? "text-bear"
                            : b.accumulation
                              ? "text-bull"
                              : "text-ghost"
                        }`}
                      >
                        {b.distribution
                          ? "DIST"
                          : b.accumulation
                            ? "ACCUM"
                            : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Watchlist breadth verdicts - largest absolute moves first. */}
        {movers.length > 0 && (
          <p className="mt-2 border-t border-hairline pt-2 font-mono text-[10px] tabular-nums text-muted">
            <span className="mr-2 font-mono text-[9px] uppercase tracking-[0.2em] text-ghost">
              SESSION VERDICTS
            </span>
            {movers.map((m) => (
              <span key={m.ticker} className="mr-3 whitespace-nowrap">
                {m.ticker}{" "}
                <span
                  className={
                    (m.changePct ?? 0) >= 0 ? "text-bull" : "text-bear"
                  }
                >
                  {fmtPct(m.changePct, 2)}
                </span>
              </span>
            ))}
          </p>
        )}
      </div>
    </section>
  );
}
