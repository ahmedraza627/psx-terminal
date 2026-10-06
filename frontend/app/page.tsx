// SINGLE-PAGE INSTITUTIONAL CONSOLE - server component, fully public.
//
// Every request re-reads the pipeline's certified data straight from Supabase
// at render time: no client fetch layer, no signal engines, no hydration of
// market state. No auth wall - anonymous visitors read the same certified
// facts (migrations/005_public_read_access.sql grants anon SELECT).
//
// Layout: sticky executive TopNav (brand / status pill / four desk tabs /
// session badge / quick search) over server-rendered sections. Tabs anchor-
// jump - the page renders every section, so navigation costs zero client
// data. Sections: RADAR (quant radar + breadth), FLOW (NCCPL matrix +
// watchlist), BLOCKS (NDM tape), BREAKOUTS (volume movers + dislocations).
// Certified facts only - the machine displays, the human reads.

import TopNav from "@/components/TopNav";
import DivergenceStrip from "@/components/DivergenceStrip";
import VolumeDislocationStrip from "@/components/VolumeDislocationStrip";
import WatchlistPanel from "@/components/WatchlistPanel";
import {
  BreadthPanel,
  FlowMatrixPanel,
  NdmTapePanel,
  QuantRadarPanel,
  VolumeBreakoutsPanel,
} from "@/components/ConsolePanels";
import {
  fetchFlowMatrix,
  fetchLatestEodSession,
  fetchNdmBlocks,
  fetchNdmSummary,
  fetchQuantRadar,
  fetchUniverseBreadth,
  fetchVolumeDislocation,
  findIsolatedAccumulation,
  resolveCertifiedEodPair,
  type BreadthData,
  type NdmBlock,
  type QuantRadarData,
} from "@/lib/consoleQueries";

export const dynamic = "force-dynamic";
export const revalidate = 0;

function Section({
  id,
  kicker,
  children,
}: {
  id: string;
  kicker: string;
  children: React.ReactNode;
}) {
  return (
    <section id={id} className="scroll-mt-28 space-y-2.5">
      <p className="px-0.5 font-mono text-[9px] font-bold uppercase tracking-[0.28em] text-ghost">
        {kicker}
      </p>
      {children}
    </section>
  );
}

export default async function HomePage() {
  const session = await fetchLatestEodSession();

  // NDM is pinned to ONE certified session per render: the active EOD
  // session when the aggregate is stamped for it, else the newest
  // certified summary row's own date (always labeled in the panel).
  // Individual deal rows are never drawn from history - a silently stale
  // tape is worse than an honest empty one.
  const [flow, ndmSummary, quantRadar] = await Promise.all([
    fetchFlowMatrix(),
    fetchNdmSummary(session),
    fetchQuantRadar(session, 3).then((q) => ({ ...q, sessionDate: session })),
  ]);
  const ndm = await fetchNdmBlocks(100_000, ndmSummary?.tradeDate ?? session);

  // One certified T/T-1 resolution per render, shared by breadth and the
  // dislocation scanner (5-date depth covers the insider-trading window).
  const pair = session != null ? await resolveCertifiedEodPair() : null;

  const breadth: BreadthData | null =
    pair != null ? await fetchUniverseBreadth(pair) : null;
  const dislocation =
    pair != null ? await fetchVolumeDislocation(pair) : null;

  const sessionLabel =
    breadth?.sessionDate ??
    flow?.asOfDate ??
    ndmSummary?.tradeDate ??
    ndm?.[0]?.tradeDate ??
    null;
  const hasAnyData =
    breadth != null ||
    flow != null ||
    ndmSummary != null ||
    (ndm ?? []).length > 0;

  // Status pill: the certified NDM aggregate carries the exchange's own
  // market state string ("Closed" etc). Absent state = CLOSED, never guessed.
  const marketState: "ACTIVE" | "CLOSED" =
    (ndmSummary?.state ?? "").toLowerCase().includes("open") ||
    (ndmSummary?.state ?? "").toLowerCase().includes("active")
      ? "ACTIVE"
      : "CLOSED";

  return (
    <main className="mx-auto min-h-dvh w-full max-w-[1600px] bg-obsidian px-2.5 pb-10 text-ink">
      <TopNav sessionLabel={sessionLabel} marketState={marketState} />

      {/* Factual smart-money divergence read, pinned below the chrome. */}
      <div className="pt-3">
        <DivergenceStrip names={findIsolatedAccumulation(breadth, ndm)} />
      </div>

      {/* Volume dislocation: new top-25 inflows with insider/NDM footprints. */}
      <div className="mt-2">
        <VolumeDislocationStrip data={dislocation} />
      </div>

      {!hasAnyData ? (
        <p className="px-1 py-16 text-center font-mono text-[11px] uppercase tracking-[0.2em] text-ghost">
          NO PIPELINE DATA STORED - RUN THE SYNC PIPELINE
        </p>
      ) : (
        <div className="space-y-5 pt-4">
          <Section id="radar" kicker="Overview · Quant Action Radar & Breadth">
            <div className="grid grid-cols-1 gap-2.5 xl:grid-cols-2">
              <QuantRadarPanel data={quantRadar} id="quant-radar" />
              <BreadthPanel
                data={breadth}
                id="universe-breadth"
                accumTickers={(ndm ?? [])
                  .filter((b) => b.accumulation)
                  .map((b) => b.ticker)}
                inst1dPkr={flow?.institutions1dPkr ?? null}
              />
            </div>
          </Section>

          <Section id="flow" kicker="Institutional Flow · NCCPL FIPI/LIPI Matrix">
            <div className="grid grid-cols-1 gap-2.5 xl:grid-cols-2">
              <FlowMatrixPanel data={flow} id="flow-matrix" />
              <WatchlistPanel ndm={ndm} breadth={breadth} />
            </div>
          </Section>

          <Section id="blocks" kicker="Off-Market & Blocks · NDM Tape & Aggregates">
            <NdmTapePanel blocks={ndm} summary={ndmSummary} id="ndm-tape" />
          </Section>

          <Section
            id="breakouts"
            kicker="Volume Breakouts · Top Movers & Anomalies"
          >
            <VolumeBreakoutsPanel
              breadth={breadth}
              dislocation={dislocation}
              id="volume-breakouts"
            />
          </Section>
        </div>
      )}

      <footer className="mt-6 border-t border-hairline px-0.5 pt-2.5">
        <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-ghost">
          {`FLOW ${flow?.asOfDate ?? "—"} · NDM ${ndmSummary?.tradeDate ?? ndm?.[0]?.tradeDate ?? "—"} · EOD ${breadth?.sessionDate ?? "—"} · ADV ${breadth?.advancers ?? "—"} / DEC ${breadth?.decliners ?? "—"} · QUANT ${quantRadar.sessionDate ?? "—"}`}
        </p>
        <p className="pt-1 font-mono text-[9px] uppercase tracking-[0.18em] text-ghost/70">
          CERTIFIED PIPELINE DATA · NO SIGNALS GENERATED · THE MACHINE DISPLAYS,
          THE HUMAN DECIDES
        </p>
      </footer>
    </main>
  );
}
