import Link from "next/link";
import TickerDeepDiveView from "@/components/TickerDeepDiveView";
import { fetchTickerDeepDive } from "@/lib/consoleQueries";

/**
 * /ticker/[ticker] - the deep-dive rendered as a slide-over sidebar over
 * the console. Fully server-rendered (RSC, zero client JS beyond the
 * framework): the fetch happens at request time with the public anon client, and the backdrop + Close are plain links
 * back to "/".
 */
export const dynamic = "force-dynamic";
export const revalidate = 0;

export default async function TickerDeepDivePage({
  params,
}: {
  params: { ticker: string };
}) {
  const data = await fetchTickerDeepDive(decodeURIComponent(params.ticker));

  return (
    <div className="fixed inset-0 z-[60]">
      {/* Backdrop: a plain link home - closes without any client JS. */}
      <Link
        href="/"
        aria-label="Close deep-dive"
        className="absolute inset-0 bg-slate-900/50"
      />

      <aside className="absolute inset-y-0 right-0 w-full max-w-xl overflow-y-auto border-l border-hairline bg-panel shadow-2xl">
        <header className="sticky top-0 z-10 flex items-center justify-between gap-2 border-b border-hairline bg-panel/95 px-4 py-2 backdrop-blur">
          <span className="font-sans text-[10px] tracking-[0.2em] text-ghost">
            PSX Desk / Deep-Dive
          </span>
          <Link
            href="/"
            className="border border-hairline px-2 py-0.5 font-sans text-[10px] tracking-widest text-muted hover:border-info/40 hover:text-info"
          >
            Close
          </Link>
        </header>

        <div className="px-4 py-3">
          {data == null ? (
            <p className="py-16 text-center font-sans text-[11px] tracking-widest text-ghost">
              No certified sessions stored - deep-dive unavailable
            </p>
          ) : (
            <TickerDeepDiveView data={data} />
          )}
        </div>

        <footer className="px-4 pb-4 pt-1">
          <p className="border-t border-hairline pt-2 font-sans text-[9px] tracking-[0.18em] text-ghost">
            Certified EOD data · No signals · Flow shown at sector or
            market level only (NCCPL publishes no per-ticker flows)
          </p>
        </footer>
      </aside>
    </div>
  );
}
