// INSTITUTIONAL FLOW (/flow) - the dedicated NCCPL FIPI/LIPI page.
//
// Smart-money vs retail nets across 1D/5D/30D windows, with the retail
// trap flag and the 30D accumulation leader. Server-rendered at request
// time; honest empty state when no flow sessions are stored.

import { FlowMatrixPanel } from "@/components/ConsolePanels";
import PageHeader from "@/components/PageHeader";
import SessionPill from "@/components/SessionPill";
import SectorMatrixTable from "@/components/SectorMatrixTable";
import {
  fetchFlowMatrix,
  fetchLatestEodSession,
  fetchSectorMatrix,
} from "@/lib/consoleQueries";

export const dynamic = "force-dynamic";
export const revalidate = 0;

export default async function InstitutionalFlowPage() {
  const session = await fetchLatestEodSession();
  const flow = await fetchFlowMatrix();
  const sector = await fetchSectorMatrix();

  return (
    <div className="mx-auto w-full max-w-6xl px-4 pb-12 pt-16 sm:px-6 md:pt-6">
      <PageHeader
        title="Institutional Flow"
        subtitle="FIPI / LIPI matrix — where smart money and retail actually traded."
        right={<SessionPill session={flow?.asOfDate ?? session} />}
      />

      <div className="mt-6 w-full">
        <SectorMatrixTable data={sector} />
      </div>

      <div className="mt-6 w-full overflow-x-auto -mx-4 px-4 sm:mx-0 sm:px-0">
        <FlowMatrixPanel data={flow} id="flow-matrix" />
      </div>
    </div>
  );
}
