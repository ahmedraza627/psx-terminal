// ACTION DESK (/) - the decision engine's front door.
//
// De-cluttered by design: exactly three high-conviction decision cards
// (Short-Term, Mid-Term, Long-Term) under a clean greeting header with the
// active session pill and quick search. Zero raw tables, zero legacy
// strips, zero status noise. Raw data lives on the dedicated sub-routes
// (/pulse, /flow, /breakouts). Verdicts are the certified rows the
// pipeline's decision engine stores in psx_system_verdicts - never
// samples; a session without engine output renders an honest clean state.

import DecisionCard from "@/components/DecisionCard";
import PageHeader from "@/components/PageHeader";
import SearchBox from "@/components/SearchBox";
import SessionPill from "@/components/SessionPill";
import {
  fetchLatestEodSession,
  fetchSystemVerdicts,
} from "@/lib/consoleQueries";

export const dynamic = "force-dynamic";

/** Card order and display labels for the engine's three horizons. */
const HORIZONS: { key: string; label: string }[] = [
  { key: "SHORT_TERM", label: "Short-Term (1-5 Days)" },
  { key: "MID_TERM", label: "Mid-Term (2-8 Weeks)" },
  { key: "LONG_TERM", label: "Long-Term (Avoid / Risk)" },
];

/** Greeting from the current Pakistan Standard Time hour. */
function greeting(hourPkt: number): string {
  if (hourPkt < 12) return "Good morning";
  if (hourPkt < 17) return "Good afternoon";
  return "Good evening";
}

export default async function ActionDeskPage() {
  const session = await fetchLatestEodSession();
  const verdicts = await fetchSystemVerdicts(session);
  // The query falls back to the latest CERTIFIED session when the engine
  // has not stamped the active one yet, so cards carry their actual
  // tradeDate - surface the one-session lag honestly instead of getting
  // stuck on the awaiting state.
  const verdictDate = verdicts[0]?.tradeDate ?? null;
  const showingPriorSession = Boolean(
    session && verdictDate && verdictDate !== session,
  );
  const hourPkt = Number(
    new Date().toLocaleString("en-US", {
      timeZone: "Asia/Karachi",
      hour: "numeric",
      hour12: false,
    }),
  );

  // Engine-stamped horizons, rendered in canonical card order. The engine
  // only stores horizons with a certified candidate, so a partial set
  // renders fewer cards - never placeholders.
  const byHorizon = new Map(verdicts.map((v) => [v.horizon, v]));
  const cards = HORIZONS.flatMap((h) => {
    const verdict = byHorizon.get(h.key);
    return verdict ? [{ label: h.label, verdict }] : [];
  });

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

      {cards.length === 0 ? (
        /* Honest clean state: the engine has not stamped this session yet. */
        <div className="mt-6 rounded-xl border border-slate-200 bg-white px-6 py-12 text-center shadow-sm">
          <p className="text-[13px] font-medium text-slate-500">
            Awaiting EOD Decision Engine execution for this session
          </p>
        </div>
      ) : (
        /* Executive verdict grid: one card per certified horizon */
        <>
          <div className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            {cards.map(({ label, verdict }) => (
              <DecisionCard
                key={verdict.horizon}
                horizon={label}
                direction={verdict.direction}
                ticker={verdict.ticker}
                logic={verdict.logic}
                entryRef={verdict.entryRef}
                stopLoss={verdict.stopLoss}
                targetPrice={verdict.targetPrice}
                riskReward={verdict.riskReward}
                regimeStatus={verdict.regimeStatus}
              />
            ))}
          </div>
          {showingPriorSession && (
            <p className="mt-3 text-center text-[13px] text-slate-500">
              Showing certified verdicts from {verdictDate} - the decision
              engine has not stamped session {session} yet.
            </p>
          )}
        </>
      )}
    </div>
  );
}
