import type { DivergenceName } from "@/lib/consoleQueries";

/**
 * SMART MONEY OUTPERFORMERS - a pure server component (zero client JS).
 *
 * Displays the factual intersection computed by findIsolatedAccumulation:
 * names appearing in at least TWO of the session's certified facts
 * (NDM flat-or-positive block, top-10 gainer, positive move on >= 2x
 * average volume). No scoring engine, no signal language - the strip
 * reads what the panels already showed and nothing else.
 */
export default function DivergenceStrip({ names }: { names: DivergenceName[] }) {
  // Honest empty state: nothing fabricated, nothing hidden.
  if (names.length === 0) {
    return (
      <p className="border border-hairline bg-panel/60 px-3 py-1.5 font-mono text-[10px] uppercase tracking-[0.18em] text-ghost">
        NO ISOLATED ACCUMULATION DIVERGENCE DETECTED
      </p>
    );
  }

  return (
    <p className="border border-hairline bg-panel/60 px-3 py-1.5 font-mono text-[10px] uppercase tracking-[0.18em] text-bull/90">
      <span className="mr-1.5 inline-block h-2 w-2 rounded-[2px] bg-bull align-middle" />
      ISOLATED ACCUMULATION NAMES (FADING TAPE):{" "}
      {names.map((n, i) => (
        <span key={n.ticker}>
          {i > 0 && <span className="text-ghost"> · </span>}
          <span className="font-bold text-bull">{n.ticker}</span>
          <span className="tabular-nums">
            {n.changePct != null
              ? ` (${n.changePct > 0 ? "+" : ""}${n.changePct.toFixed(1)}%)`
              : " (NDM ONLY)"}
          </span>
        </span>
      ))}
    </p>
  );
}
