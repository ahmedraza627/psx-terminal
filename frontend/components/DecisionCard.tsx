import TickerLink from "@/components/TickerLink";

/**
 * DecisionCard - the Action Desk's atomic verdict unit.
 *
 * One card = one machine verdict: a time horizon, a direction badge
 * (BUY/ACCUMULATE = soft emerald, AVOID/SHORT = soft rose), the target
 * ticker, a single readable system-logic sentence, and - when the engine
 * certified risk math for the horizon - an execution grid with the entry
 * reference, invalidation (stop), target zone, reward-to-risk ratio and
 * the suggested allocation cap. A horizon with no certified setup renders
 * a muted slate cash-preservation placeholder so the desk grid never
 * collapses. A DEFENSIVE_CASH regime stamp surfaces as a small amber
 * sizing warning.
 * Light SaaS styling: white card, rounded-xl, soft shadow, slate borders,
 * Inter typography, zero emojis. Pure server component; fed live by the
 * pipeline's decision engine via psx_system_verdicts.
 */

export type DecisionDirection = "BUY" | "AVOID" | "SHORT" | "ACCUMULATE";

export interface DecisionCardProps {
  /** e.g. "Short-Term (1-5 Days)" | "Mid-Term (2-8 Weeks)" */
  horizon: string;
  /**
   * Horizon has no certified setup: render the muted cash placeholder
   * (slate, no red/green) instead of an engine verdict.
   */
  cashState?: boolean;
  direction?: DecisionDirection;
  /** Target symbol, e.g. "HUBC" or "MEBL". */
  ticker?: string;
  /** One highly readable sentence: WHY the engine fired. */
  logic?: string | null;
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
  /** Suggested portfolio allocation (%) from the 1.5% risk budget. */
  suggestedAllocPct?: number | null;
  /** Order size capped at 2% of the 20D average volume (shares). */
  maxVolumeCapacityShares?: number | null;
  /** RISK_ON | NEUTRAL | DEFENSIVE_CASH - the macro tape gate. */
  macroTapeState?: string | null;
}

const DIRECTION_STYLE: Record<
  DecisionDirection,
  { badge: string; accent: string }
> = {
  BUY: {
    badge: "border border-sky-300 bg-sky-100 text-sky-900",
    accent: "bg-sky-500",
  },
  ACCUMULATE: {
    badge: "border border-sky-300 bg-sky-100 text-sky-900",
    accent: "bg-sky-500",
  },
  AVOID: {
    badge: "border border-rose-300 bg-rose-100 text-rose-900",
    accent: "bg-rose-500",
  },
  SHORT: {
    badge: "border border-rose-300 bg-rose-100 text-rose-900",
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
  cashState = false,
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
  suggestedAllocPct = null,
  maxVolumeCapacityShares = null,
  macroTapeState = null,
}: DecisionCardProps) {
  // Cash placeholder: no certified setup for this horizon. Deliberately
  // slate-only (never red/green) with the execution grid omitted, so the
  // card reads as capital preservation rather than a weak signal.
  if (cashState || direction == null || ticker == null || logic == null) {
    return (
      <article className="relative flex min-w-0 flex-col overflow-hidden rounded-xl border-2 border-dashed border-slate-300 bg-slate-50/80 shadow-sm">
        <div className="flex flex-col gap-3 p-5">
          <div className="flex items-center justify-between gap-2">
            <p className="text-[11px] font-semibold tracking-[0.14em] text-slate-700">
              {horizon}
            </p>
            <span className="shrink-0 rounded-full border border-slate-300 bg-slate-200 px-2.5 py-0.5 text-[11px] font-semibold tracking-wide text-slate-800">
              CASH / NO SETUP
            </span>
          </div>
          <p className="text-[26px] font-bold leading-none tracking-tight text-slate-800">
            CASH
          </p>
          <p className="text-[13px] font-bold leading-relaxed text-slate-700">
            No qualifying pullback setup meeting institutional criteria.
            Preserving capital in cash.
          </p>
        </div>
      </article>
    );
  }
  const s = DIRECTION_STYLE[direction];
  const hasLevels =
    entryRef != null || stopLoss != null || targetPrice != null;
  const defensive = regimeStatus === "DEFENSIVE_CASH";
  // Macro tape pill: RISK_ON renders emerald, DEFENSIVE_CASH amber, NEUTRAL
  // slate - all high-contrast (WCAG AA) fills. Hidden when migration 011 is
  // pending (null) - never fabricated.
  const tapePill =
    macroTapeState === "RISK_ON"
      ? { text: "Tape: RISK_ON", cls: "border-emerald-300 bg-emerald-100 text-emerald-900" }
      : macroTapeState === "DEFENSIVE_CASH"
        ? { text: "Tape: DEFENSIVE_CASH", cls: "border-amber-300 bg-amber-100 text-amber-900" }
        : macroTapeState === "NEUTRAL"
          ? { text: "Tape: NEUTRAL", cls: "border-slate-300 bg-slate-200 text-slate-800" }
          : null;
  // DEFENSIVE_CASH tape overrides the softer sizing warning: the macro
  // gate blocks new buys, so the card recommends capital preservation.
  const preserveCapital =
    macroTapeState === "DEFENSIVE_CASH" || defensive;
  // Max allocation label: whole percents render clean ("15%"), fractional
  // budgets keep one decimal ("12.5%").
  const allocRounded =
    suggestedAllocPct != null
      ? Math.round(suggestedAllocPct * 10) / 10
      : null;
  const allocLabel =
    allocRounded != null
      ? allocRounded % 1 === 0
        ? String(allocRounded)
        : allocRounded.toFixed(1)
      : null;
  const hasExec = hasLevels || suggestedAllocPct != null;
  return (
    <article className="relative flex min-w-0 flex-col overflow-hidden rounded-xl border border-slate-200/90 bg-white shadow-sm transition-all duration-150 hover:shadow-md">
      {/* Direction spine - the card's semantic color at a glance */}
      <span aria-hidden className={`absolute inset-y-0 left-0 w-1 ${s.accent}`} />

      <div className="flex flex-col gap-3 p-4 pl-5 sm:px-5 sm:pl-6">
        {/* Horizon + direction */}
        <div className="flex items-center justify-between gap-2">
          <p className="text-[11px] font-semibold tracking-[0.14em] text-slate-700">
            {horizon}
          </p>
          <div className="flex shrink-0 items-center gap-1.5">
            {tapePill && (
              <span
                className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold tracking-wide ${tapePill.cls}`}
              >
                {tapePill.text}
              </span>
            )}
            <span
              className={`rounded-full px-2.5 py-0.5 text-[11px] font-bold tracking-wide ${s.badge}`}
            >
              {direction}
            </span>
          </div>
        </div>

        {/* Target ticker */}
        <p className="text-[26px] font-bold leading-none tracking-tight text-slate-900">
          <TickerLink ticker={ticker} title="Open deep-dive" />
        </p>

        {/* System logic + historical edge proof + dynamic sizing */}
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-[13px] leading-relaxed text-slate-700">{logic}</p>
          {historicalWinRate != null && (
            <span className="inline-flex shrink-0 items-center rounded-full border border-slate-200 bg-slate-100 px-2 py-0.5 text-[11px] font-semibold tabular-nums text-slate-700">
              {historicalWinRate.toFixed(0)}% Hist. Win Rate
            </span>
          )}
        </div>

        {/* Execution grid - certified risk math (when the engine stored it) */}
        {hasExec && (
          <div className="grid grid-cols-2 gap-x-4 gap-y-3 rounded-lg border border-slate-100 bg-slate-50 px-4 py-3 sm:grid-cols-3">
            <div className="flex flex-col">
              <span className="text-xs font-semibold uppercase tracking-wider text-slate-700">
                Entry Ref
              </span>
              <span className="mt-1 whitespace-nowrap font-mono text-base font-bold text-slate-950">
                {entryRef != null ? `PKR ${pkr(entryRef)}` : "—"}
              </span>
            </div>

            <div className="flex flex-col">
              <span className="text-xs font-semibold uppercase tracking-wider text-slate-700">
                Invalidation / Stop
              </span>
              <span className="mt-1 w-fit whitespace-nowrap rounded-md border border-rose-200 bg-rose-50 px-1.5 py-0.5 font-mono text-base font-bold text-rose-700">
                {stopLoss != null ? `PKR ${pkr(stopLoss)}` : "—"}
              </span>
            </div>

            <div className="flex flex-col">
              <span className="text-xs font-semibold uppercase tracking-wider text-slate-700">
                Target Zone
              </span>
              <span className="mt-1 w-fit whitespace-nowrap rounded-md border border-emerald-200 bg-emerald-50 px-1.5 py-0.5 font-mono text-base font-bold text-emerald-800">
                {targetPrice != null ? `PKR ${pkr(targetPrice)}` : "—"}
              </span>
            </div>

            <div className="flex flex-col">
              <span className="text-xs font-semibold uppercase tracking-wider text-slate-700">
                Reward : Risk
              </span>
              <span className="mt-1 whitespace-nowrap font-mono text-base font-bold text-slate-950">
                {riskReward != null ? `1:${riskReward} R:R` : "—"}
              </span>
            </div>

            {allocLabel != null && (
              <div className="flex flex-col col-span-2 sm:col-span-1">
                <span className="text-xs font-semibold uppercase tracking-wider text-slate-700">
                  Position Size
                </span>
                <span
                  className="mt-1 w-fit rounded border border-slate-300 bg-slate-200/80 px-2 py-0.5 font-mono font-bold text-slate-950"
                  title={
                    maxVolumeCapacityShares != null
                      ? `Order capped at ${maxVolumeCapacityShares.toLocaleString("en-US")} shares (2% of 20D avg volume)`
                      : "Capped at 15% of portfolio"
                  }
                >
                  Max Alloc: {allocLabel}%
                </span>
              </div>
            )}
          </div>
        )}

        {/* Macro regime - defensive tape sizing warning */}
        {preserveCapital && (
          <div
            role="status"
            className="flex items-center justify-center rounded-md border border-amber-300 bg-amber-100 px-3 py-1.5"
          >
            <span className="text-[11px] font-semibold tracking-wide text-amber-900">
              {macroTapeState === "DEFENSIVE_CASH"
                ? "Defensive Tape \u00b7 Preserve Capital, No New Exposure"
                : "Defensive Tape \u00b7 Reduce Position Size"}
            </span>
          </div>
        )}
      </div>

      {/* Fundamental gate stamp - the verdict passed the strict PE filter */}
      {fundamentalScore && (
        <div className="border-t border-slate-100 px-4 py-2 pl-5 sm:px-5 sm:pl-6">
          <p className="text-[11px] font-medium tracking-wide text-slate-700">
            Fundamental filter: {fundamentalScore}
          </p>
        </div>
      )}
    </article>
  );
}
