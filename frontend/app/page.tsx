// ACTION DESK (/) - the decision engine's front door.
//
// De-cluttered by design: exactly three high-conviction decision cards
// (Short-Term, Mid-Term, Long-Term) under a clean greeting header with the
// active session pill and quick search. Zero raw tables, zero legacy
// strips, zero status noise. Raw data lives on the dedicated sub-routes
// (/pulse, /flow, /breakouts). Verdicts are static dummies until the
// engine wiring lands (Phase 2) - labeled as such, never disguised.

import DecisionCard from "@/components/DecisionCard";
import PageHeader from "@/components/PageHeader";
import SearchBox from "@/components/SearchBox";
import SessionPill from "@/components/SessionPill";
import { fetchLatestEodSession } from "@/lib/consoleQueries";

export const dynamic = "force-dynamic";

/** Greeting from the current Pakistan Standard Time hour. */
function greeting(hourPkt: number): string {
  if (hourPkt < 12) return "Good morning";
  if (hourPkt < 17) return "Good afternoon";
  return "Good evening";
}

export default async function ActionDeskPage() {
  const session = await fetchLatestEodSession();
  const hourPkt = Number(
    new Date().toLocaleString("en-US", {
      timeZone: "Asia/Karachi",
      hour: "numeric",
      hour12: false,
    }),
  );

  return (
    <div className="mx-auto w-full max-w-6xl px-4 pb-12 pt-6 sm:px-6">
      <PageHeader
        title={`${greeting(Number.isNaN(hourPkt) ? 10 : hourPkt)} - here's your desk`}
        subtitle="Three verdicts, zero noise. The machine reads the tape; you make the call."
        right={
          <>
            <SessionPill session={session} />
            <SearchBox />
          </>
        }
      />

      {/* Executive verdict grid: one card per time horizon */}
      <div className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        <DecisionCard
          horizon="Short-Term Swing"
          direction="BUY"
          ticker="HUBC"
          logic="Institutions buying for 3 days straight + volume up 300% over the 20-session average."
        />
        <DecisionCard
          horizon="Mid-Term Accumulation"
          direction="BUY"
          ticker="MEBL"
          logic="FIPI and Mutual Funds accumulated for 5 sessions while retail kept selling into the tape."
        />
        <DecisionCard
          horizon="Long-Term Avoid"
          direction="AVOID"
          ticker="KSE100"
          logic="Advance/decline ratio at 0.62 with institutions net sellers — the tape is not confirming."
        />
      </div>

      <p className="mt-6 text-[12px] text-slate-400">
        Sample verdicts for UI review - the decision engine wiring arrives in
        Phase 2. Raw market data lives under Market Pulse, Institutional
        Flow, and Volume Anomalies.
      </p>
    </div>
  );
}
