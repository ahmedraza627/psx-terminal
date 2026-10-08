// VOLUME ANOMALIES (/breakouts) - volume spikes and top movers only.
//
// The top-turnover mover table (certified close x volume) next to the
// top-25 dislocation set (new entrants vs yesterday) with insider-buy
// footprints. Server-rendered at request time; honest empty states.

import PageHeader from "@/components/PageHeader";
import SessionPill from "@/components/SessionPill";
import { VolumeBreakoutsPanel } from "@/components/ConsolePanels";
import {
  fetchLatestEodSession,
  fetchUniverseBreadth,
  fetchVolumeDislocation,
  resolveCertifiedEodPair,
} from "@/lib/consoleQueries";

export const dynamic = "force-dynamic";
export const revalidate = 0;

export default async function VolumeAnomaliesPage() {
  const session = await fetchLatestEodSession();
  const pair = session != null ? await resolveCertifiedEodPair() : null;
  const breadth = pair != null ? await fetchUniverseBreadth(pair) : null;
  const dislocation =
    pair != null ? await fetchVolumeDislocation(pair) : null;

  return (
    <div className="mx-auto w-full max-w-6xl px-4 pb-12 pt-6 sm:px-6">
      <PageHeader
        title="Volume Anomalies"
        subtitle="Volume spikes, new top-25 entrants, and the session's heaviest turnover."
        right={<SessionPill session={breadth?.sessionDate ?? session} />}
      />

      <div className="mt-6">
        <VolumeBreakoutsPanel
          breadth={breadth}
          dislocation={dislocation}
          id="volume-breakouts"
        />
      </div>
    </div>
  );
}
