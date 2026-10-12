// MARKET PULSE (/pulse) - advance/decline breadth & market health only.
//
// One certified T/T-1 resolution feeds the verified universe breadth:
// A/D KPIs plus the session's top movers. Server-rendered at request
// time; every fetcher is settle-safe and renders honest empty states.

import { BreadthPanel } from "@/components/ConsolePanels";
import PageHeader from "@/components/PageHeader";
import SessionPill from "@/components/SessionPill";
import {
  fetchLatestEodSession,
  fetchUniverseBreadth,
  resolveCertifiedEodPair,
} from "@/lib/consoleQueries";

export const dynamic = "force-dynamic";
export const revalidate = 0;

export default async function MarketPulsePage() {
  const session = await fetchLatestEodSession();
  const pair = session != null ? await resolveCertifiedEodPair() : null;
  const breadth = pair != null ? await fetchUniverseBreadth(pair) : null;

  return (
    <div className="mx-auto w-full max-w-6xl px-4 pb-12 pt-16 sm:px-6 md:pt-6">
      <PageHeader
        title="Market Pulse"
        subtitle="Verified advance/decline breadth and market health for the latest certified session."
        right={<SessionPill session={breadth?.sessionDate ?? session} />}
      />

      <div className="mt-6 w-full overflow-x-auto -mx-4 px-4 sm:mx-0 sm:px-0">
        <BreadthPanel data={breadth} id="universe-breadth" />
      </div>
    </div>
  );
}
