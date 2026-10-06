// ACTION-FIRST DECISION ENGINE - Action Desk (Phase 1 dummy surface).
//
// The pivot: the user should not have to think. This page will render the
// engine's direct SHORT / MID / LONG verdicts. For Phase 1 the three
// DecisionCards below are static dummies with the exact final shape, so
// the UI/UX can be reviewed before the verdict engine is wired (Phase 2).
// No Supabase fetches on this route yet - zero data, zero pretense.

import DecisionCard from "@/components/DecisionCard";

export const dynamic = "force-dynamic";

export default function ActionDeskPage() {
  return (
    <div className="mx-auto w-full max-w-[1600px] px-4 pb-10 pt-5">
      {/* Desk header */}
      <header className="flex flex-wrap items-end justify-between gap-3 border-b border-hairline pb-3">
        <div>
          <h1 className="font-sans text-[20px] font-bold tracking-tight text-ink">
            Action Desk
          </h1>
          <p className="pt-0.5 font-mono text-[10px] uppercase tracking-[0.22em] text-ghost">
            Direct verdicts · Short / Mid / Long horizon
          </p>
        </div>
        <span className="rounded-[2px] border border-warn/40 bg-warn/10 px-2 py-0.5 font-mono text-[9px] font-bold uppercase tracking-widest text-warn">
          Phase 1 · UI Shell · Verdict Engine Not Wired
        </span>
      </header>

      {/* Verdict grid: one dummy card per time horizon */}
      <div className="mt-5 grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
        <DecisionCard
          horizon="SHORT-TERM SWING"
          direction="BUY"
          ticker="HUBC"
          logic="Institutions buying for 3 days + Volume up 300%."
        />
        <DecisionCard
          horizon="MID-TERM ACCUMULATION"
          direction="BUY"
          ticker="MEBL"
          logic="FIPI + Mutual Funds net 5-session accumulation while retail distributes."
        />
        <DecisionCard
          horizon="LONG-TERM HOLD"
          direction="AVOID"
          ticker="KSE100"
          logic="Advance/decline ratio 0.62 with institutions net sellers - tape not confirming."
        />
      </div>

      {/* Phase note - honest about the dummy state */}
      <p className="mt-5 font-mono text-[10px] uppercase tracking-[0.2em] text-ghost">
        Static dummy verdicts for UI/UX review - the decision engine wiring
        arrives in Phase 2.
      </p>
    </div>
  );
}
