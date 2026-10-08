import TickerLink from "@/components/TickerLink";

/**
 * DecisionCard - the Action Desk's atomic verdict unit.
 *
 * One card = one machine verdict: a time horizon, a direction badge
 * (BUY/ACCUMULATE = soft emerald, AVOID/SHORT = soft rose), the target
 * ticker, and a single readable system-logic sentence. Light SaaS styling:
 * white card, rounded-xl, soft shadow. Pure server component; fed live by
 * the pipeline's decision engine via psx_system_verdicts.
 */

export type DecisionDirection = "BUY" | "AVOID" | "SHORT" | "ACCUMULATE";

export interface DecisionCardProps {
  /** e.g. "Short-Term (1-5 Days)" | "Mid-Term (2-8 Weeks)" */
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
    badge: "border border-emerald-200 bg-emerald-50 text-emerald-700",
    accent: "bg-emerald-500",
  },
  ACCUMULATE: {
    badge: "border border-emerald-200 bg-emerald-50 text-emerald-700",
    accent: "bg-emerald-500",
  },
  AVOID: {
    badge: "border border-rose-200 bg-rose-50 text-rose-700",
    accent: "bg-rose-500",
  },
  SHORT: {
    badge: "border border-rose-200 bg-rose-50 text-rose-700",
    accent: "bg-rose-500",
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
    <article className="relative flex min-w-0 flex-col overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm transition-shadow hover:shadow-md">
      {/* Direction spine - the card's semantic color at a glance */}
      <span aria-hidden className={`absolute inset-y-0 left-0 w-1 ${s.accent}`} />

      <div className="flex flex-col gap-3 px-5 py-4 pl-6">
        {/* Horizon + direction */}
        <div className="flex items-center justify-between gap-2">
          <p className="text-[11px] font-semibold tracking-[0.14em] text-slate-400">
            {horizon}
          </p>
          <span
            className={`rounded-full px-2.5 py-0.5 text-[11px] font-bold tracking-wide ${s.badge}`}
          >
            {direction}
          </span>
        </div>

        {/* Target ticker */}
        <p className="text-[26px] font-bold leading-none tracking-tight text-slate-900">
          <TickerLink ticker={ticker} title="Open deep-dive" />
        </p>

        {/* System logic - the single readable sentence */}
        <p className="text-[13px] leading-relaxed text-slate-600">{logic}</p>
      </div>
    </article>
  );
}
