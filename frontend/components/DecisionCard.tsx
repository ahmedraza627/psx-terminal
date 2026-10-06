import TickerLink from "@/components/TickerLink";

/**
 * DecisionCard - the Action Desk's atomic verdict unit.
 *
 * One card = one machine verdict: a time horizon, a direction badge
 * (BUY = emerald, AVOID/SHORT = crimson), the target ticker, and a single
 * readable system-logic sentence. Pure server component; the backend
 * verdict engine wires into the same props shape later (Phase 2).
 */

export type DecisionDirection = "BUY" | "AVOID" | "SHORT";

export interface DecisionCardProps {
  /** e.g. "SHORT-TERM SWING" | "MID-TERM ACCUMULATION" | "LONG-TERM HOLD" */
  horizon: string;
  direction: DecisionDirection;
  /** Target symbol, e.g. "HUBC" or "MEBL". */
  ticker: string;
  /** One highly readable sentence: WHY the engine fired. */
  logic: string;
}

const DIRECTION_STYLE: Record<
  DecisionDirection,
  { badge: string; accent: string }
> = {
  BUY: {
    badge: "bg-bull/15 text-bull ring-1 ring-bull/40",
    accent: "bg-bull",
  },
  AVOID: {
    badge: "bg-bear/15 text-bear ring-1 ring-bear/40",
    accent: "bg-bear",
  },
  SHORT: {
    badge: "bg-bear/15 text-bear ring-1 ring-bear/40",
    accent: "bg-bear",
  },
};

export default function DecisionCard({
  horizon,
  direction,
  ticker,
  logic,
}: DecisionCardProps) {
  const s = DIRECTION_STYLE[direction];
  return (
    <article className="relative flex min-w-0 flex-col overflow-hidden border border-hairline bg-panel">
      {/* Direction spine - the card's semantic color at a glance */}
      <span aria-hidden className={`absolute inset-y-0 left-0 w-0.5 ${s.accent}`} />

      <div className="flex flex-col gap-2.5 px-4 py-3.5 pl-5">
        {/* Horizon + direction */}
        <div className="flex items-center justify-between gap-2">
          <p className="font-mono text-[9px] font-bold uppercase tracking-[0.22em] text-ghost">
            {horizon}
          </p>
          <span
            className={`rounded-[2px] px-2 py-0.5 font-mono text-[10px] font-bold uppercase tracking-widest ${s.badge}`}
          >
            {direction}
          </span>
        </div>

        {/* Target ticker */}
        <p className="font-sans text-[22px] font-bold leading-none tracking-tight text-ink">
          <TickerLink ticker={ticker} title="Open deep-dive" />
        </p>

        {/* System logic - the single readable sentence */}
        <p className="border-t border-hairline pt-2.5 text-[12px] leading-relaxed text-muted">
          <span className="mr-1.5 font-mono text-[9px] uppercase tracking-widest text-ghost">
            LOGIC
          </span>
          {logic}
        </p>
      </div>
    </article>
  );
}
