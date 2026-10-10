import TickerLink from "@/components/TickerLink";

/**
 * DecisionCard - the Action Desk's atomic verdict unit.
 *
 * One card = one machine verdict: a time horizon, a direction badge
 * (BUY/ACCUMULATE = soft emerald, AVOID/SHORT = soft rose), the target
 * ticker, a single readable system-logic sentence, and - when the engine
 * certified risk math for the horizon - an execution grid with the entry
 * reference, invalidation (stop), target zone and reward-to-risk ratio.
 * A DEFENSIVE_CASH regime stamp surfaces as a small amber sizing warning.
 * Light SaaS styling: white card, rounded-xl, soft shadow, slate borders,
 * Inter typography, zero emojis. Pure server component; fed live by the
 * pipeline's decision engine via psx_system_verdicts.
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
  /** Entry reference price in PKR (null = no certified levels). */
  entryRef?: number | null;
  /** Invalidation / stop-loss level in PKR. */
  stopLoss?: number | null;
  /** Target zone price in PKR. */
  targetPrice?: number | null;
  /** Reward-to-risk ratio (2.4 renders as "1:2.4 R:R"). */
  riskReward?: number | null;
  /** NORMAL | DEFENSIVE_CASH - the macro regime stamp. */
  regimeStatus?: string | null;
  /**
   * 3-year walk-forward win rate (%) of this ticker's own entry/stop/
   * target logic. Null when history was too thin to simulate, when the
   * migration carrying it is pending, or for AVOID verdicts.
   */
  historicalWinRate?: number | null;
  /** "PROFITABLE (PE > 0)" once the strict fundamental gate passed. */
  fundamentalScore?: string | null;
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

/** PKR price with thousand separators and 2 decimals. */
function pkr(value: number): string {
  return value.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

export default function DecisionCard({
  horizon,
  direction,
  ticker,
  logic,
  entryRef,
  stopLoss,
  targetPrice,
  riskReward,
  regimeStatus,
  historicalWinRate = null,
  fundamentalScore = null,
}: DecisionCardProps) {
  const s = DIRECTION_STYLE[direction];
  const hasLevels =
    entryRef != null || stopLoss != null || targetPrice != null;
  const defensive = regimeStatus === "DEFENSIVE_CASH";
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

        {/* System logic + historical edge proof */}
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-[13px] leading-relaxed text-slate-600">{logic}</p>
          {historicalWinRate != null && (
            <span className="inline-flex shrink-0 items-center rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[11px] font-semibold tabular-nums text-slate-600">
              {historicalWinRate.toFixed(0)}% Hist. Win Rate
            </span>
          )}
        </div>

        {/* Execution grid - certified risk math (when the engine stored it) */}
        {hasLevels && (
          <div className="grid grid-cols-2 gap-x-4 gap-y-3 rounded-lg border border-slate-200 bg-slate-50 px-4 py-3">
            <div className="flex flex-col">
              <span className="text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-400">
                Entry Ref
              </span>
              <span className="mt-1 text-[13px] font-semibold tabular-nums text-slate-800">
                {entryRef != null ? `PKR ${pkr(entryRef)}` : "—"}
              </span>
            </div>

            <div className="flex flex-col">
              <span className="text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-400">
                Invalidation / Stop
              </span>
              <span className="mt-1 w-fit rounded-md border border-rose-200 bg-rose-50 px-1.5 py-0.5 text-[13px] font-semibold tabular-nums text-rose-700">
                {stopLoss != null ? `PKR ${pkr(stopLoss)}` : "—"}
              </span>
            </div>

            <div className="flex flex-col">
              <span className="text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-400">
                Target Zone
              </span>
              <span className="mt-1 w-fit rounded-md border border-emerald-200 bg-emerald-50 px-1.5 py-0.5 text-[13px] font-semibold tabular-nums text-emerald-700">
                {targetPrice != null ? `PKR ${pkr(targetPrice)}` : "—"}
              </span>
            </div>

            <div className="flex flex-col">
              <span className="text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-400">
                Reward : Risk
              </span>
              <span className="mt-1 text-[13px] font-semibold tabular-nums text-slate-800">
                {riskReward != null ? `1:${riskReward} R:R` : "—"}
              </span>
            </div>
          </div>
        )}

        {/* Macro regime - defensive tape sizing warning */}
        {defensive && (
          <div
            role="status"
            className="flex items-center justify-center rounded-md border border-amber-200 bg-amber-50 px-3 py-1.5"
          >
            <span className="text-[11px] font-semibold tracking-wide text-amber-700">
              Defensive Tape &middot; Reduce Position Size
            </span>
          </div>
        )}
      </div>

      {/* Fundamental gate stamp - the verdict passed the strict PE filter */}
      {fundamentalScore && (
        <div className="border-t border-slate-100 px-5 py-2 pl-6">
          <p className="text-[11px] font-medium tracking-wide text-slate-400">
            Fundamental filter: {fundamentalScore}
          </p>
        </div>
      )}
    </article>
  );
}
