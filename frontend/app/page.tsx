// SINGLE-PAGE INSTITUTIONAL CONSOLE - server component, fully public.
//
// Every request re-reads the pipeline's certified data straight from Supabase
// at render time: no client fetch layer, no signal engines, no hydration of
// market state. No auth wall - anonymous visitors read the same certified
// facts (migrations/005_public_read_access.sql grants anon SELECT).
//
// Panels: A) NCCPL flow matrix, B) NDM block tape, C) verified universe
// breadth. Certified facts only - the machine displays, the human reads.

import ConsoleRefresh from "@/components/ConsoleRefresh";
import DivergenceStrip from "@/components/DivergenceStrip";
import VolumeDislocationStrip from "@/components/VolumeDislocationStrip";
import WatchlistPanel from "@/components/WatchlistPanel";
import {
  BreadthPanel,
  FlowMatrixPanel,
  NdmTapePanel,
} from "@/components/ConsolePanels";
import {
  fetchFlowMatrix,
  fetchLatestEodSession,
  fetchNdmBlocks,
  fetchUniverseBreadth,
  fetchVolumeDislocation,
  findIsolatedAccumulation,
  resolveCertifiedEodPair,
  type BreadthData,
  type NdmBlock,
} from "@/lib/consoleQueries";

export const dynamic = "force-dynamic";
export const revalidate = 0;

export default async function HomePage() {
  const session = await fetchLatestEodSession();

  // The NDM tape may lead or lag EOD: it binds to its own latest session,
  // so it renders even when EOD is empty. Flow is session-independent.
  const [flow, ndm] = await Promise.all([
    fetchFlowMatrix(),
    fetchNdmBlocks(100_000),
  ]);

  // One certified T/T-1 resolution per render, shared by breadth and the
  // dislocation scanner (5-date depth covers the insider-trading window).
  const pair = session != null ? await resolveCertifiedEodPair() : null;

  const breadth: BreadthData | null =
    pair != null ? await fetchUniverseBreadth(pair) : null;
  const dislocation =
    pair != null ? await fetchVolumeDislocation(pair) : null;

  const sessionLabel =
    breadth?.sessionDate ?? flow?.asOfDate ?? ndm?.[0]?.tradeDate ?? null;
  const hasAnyData = breadth != null || flow != null || ndm != null;

  return (
    <main className="mx-auto min-h-dvh w-full max-w-[1600px] bg-obsidian px-2.5 pb-8 text-ink">
      <header className="sticky top-0 z-20 border-b border-hairline bg-panel/95 backdrop-blur">
        <div className="flex items-center justify-between gap-2 px-0.5 py-1.5">
          <div className="flex items-center gap-2.5">
            <h1 className="font-mono text-[13px] font-bold tracking-[0.18em] text-ink">
              PSX<span className="text-info">·</span>DESK
            </h1>
            {sessionLabel && (
              <span className="rounded-[2px] border border-hairline bg-obsidian px-1.5 py-0.5 font-mono text-[10px] tabular-nums text-info">
                SESSION {sessionLabel}
                {breadth?.sessionDate == null ? " (EOD PENDING)" : ""}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <span className="hidden font-mono text-[9px] uppercase tracking-[0.2em] text-ghost md:inline">
              CERTIFIED PIPELINE DATA · NO SIGNALS GENERATED
            </span>
            <ConsoleRefresh syncing={false} />
          </div>
        </div>
      </header>

      {/* Factual smart-money divergence read, pinned below the chrome. */}
      <div className="pt-2.5">
        <DivergenceStrip names={findIsolatedAccumulation(breadth, ndm)} />
      </div>

      {/* Volume dislocation: new top-25 inflows with insider/NDM footprints. */}
      <VolumeDislocationStrip data={dislocation} />

      {!hasAnyData ? (
        <p className="px-1 py-16 text-center font-mono text-[11px] uppercase tracking-[0.2em] text-ghost">
          NO PIPELINE DATA STORED - RUN THE SYNC PIPELINE
        </p>
      ) : (
        <div className="space-y-2.5 pt-2.5">
          <WatchlistPanel ndm={ndm} breadth={breadth} />
          <FlowMatrixPanel data={flow} id="flow-matrix" />
          <NdmTapePanel blocks={ndm} id="ndm-tape" />
          <BreadthPanel
            data={breadth}
            id="universe-breadth"
            accumTickers={(ndm ?? [])
              .filter((b) => b.accumulation)
              .map((b) => b.ticker)}
            inst1dPkr={flow?.institutions1dPkr ?? null}
          />
        </div>
      )}

      <footer className="px-0.5 pt-2.5">
        <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-ghost">
          {`FLOW ${flow?.asOfDate ?? "—"} · NDM ${ndm?.[0]?.tradeDate ?? "—"} · EOD ${breadth?.sessionDate ?? "—"} · ADV ${breadth?.advancers ?? "—"} / DEC ${breadth?.decliners ?? "—"}`}
        </p>
      </footer>
    </main>
  );
}
