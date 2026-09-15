"use client";

import { useMemo, useState } from "react";
import {
  Badge,
  DeskFrame,
  IdleState,
  type Tone,
} from "@/components/ui/primitives";
import { fmtPkrB, fmtPkrM, fmtPct } from "@/components/ui/format";
import {
  computeAmihudStats,
  computeSectorSmartMoney,
  type EodPoint,
  type FlowRow,
  type FundamentalsRow,
} from "@/lib/deskQueries";
import type { KiborRow } from "@/lib/queries";

/**
 * Quantitative Insights Wire — Anomaly Signal Engine.
 *
 * Four institutional anomaly detectors fired purely off the terminal's
 * pre-loaded state (no fetches, no mock data, settle-safe — every window
 * guard skips honestly instead of imputing):
 *
 *   1. SMART MONEY ABSORPTION      — shared sector smart-money engine:
 *      institutions net-buying a sector whose equal-weight price fell >1%
 *      over the trailing 5 sessions (OPPORTUNITY).
 *   2. SLIPPAGE TRAP DETECTED      — latest session volume > 2x the prior
 *      20-session average while Amihud sits in the TRAP tier (>= 50, same
 *      tier source as the Breadth desk / quote HUD) (ALERT).
 *   3. MARKET CAPITULATION /       — latest-session A/D ratio < 0.25 is
 *      BREADTH EXPANSION             capitulation (CRITICAL); > 3.0 is
 *                                    expansion (OPPORTUNITY). Same session
 *                                    classification as the Breadth desk.
 *   4. RATE SENSITIVITY            — interest-coverage proxy < 1.2x while
 *      VULNERABILITY                 floating debt > 1B PKR (CRITICAL).
 *
 * Every card dispatches a navigation target (FLOW / BREADTH / KIBOR) with an
 * optional filter through onNavigate — the wire is a routing surface, not a
 * data silo.
 */

// --------------------------------------------------------------- //
// Contract (page.tsx): pre-loaded terminal state — all inputs      //
// optional so the wire renders its idle state before the feeds     //
// land instead of throwing.                                        //
// --------------------------------------------------------------- //
interface Props {
  eod?: EodPoint[];
  fundamentals?: FundamentalsRow[];
  kiborRows?: KiborRow[];
  sectorMap?: Map<string, string>;
  flows?: FlowRow[];
  /** Navigate to a desk ("FLOW" | "BREADTH" | "KIBOR") with optional filter. */
  onNavigate: (desk: string, filter?: string) => void;
}

type SignalCategory = "FLOW" | "LIQUIDITY" | "RATES";
type Severity = "CRITICAL" | "ALERT" | "OPPORTUNITY";
type Chip = "ALL" | SignalCategory;

const CATEGORY_CHIPS: readonly Chip[] = [
  "ALL",
  "FLOW",
  "LIQUIDITY",
  "RATES",
];

const SEVERITY_TONE: Record<Severity, Tone> = {
  CRITICAL: "bear",
  ALERT: "warn",
  OPPORTUNITY: "bull",
};

const SEVERITY_RANK: Record<Severity, number> = {
  CRITICAL: 0,
  ALERT: 1,
  OPPORTUNITY: 2,
};

/** KIBOR stand-in for the interest-coverage proxy (matches the Flow desk). */
const KIBOR_RATE = 0.11;
/** Amihud threshold of the "TRAP — BRUTAL SLIPPAGE" tier (Breadth-desk parity). */
const TRAP_AMIHUD = 50;
/** Volume-spike trigger: latest session vs prior 20-session average. */
const VOLUME_SPIKE_X = 2;
/** Coverage floor for rate vulnerability. */
const MIN_COVERAGE_X = 1.2;
/** Floating-debt floor (PKR) for rate vulnerability. */
const MIN_FLOATING_DEBT_PKR = 1e9;
/** Breadth signals need a real cross-section — never fire on a thin tape. */
const MIN_CLASSIFIED_NAMES = 20;
const EPSILON = 1e-9;

interface SignalMetric {
  label: string;
  value: string;
  tone?: string;
}

interface SignalAction {
  label: string;
  desk: string;
  filter?: string;
}

interface InsightSignal {
  id: string;
  code: string;
  subject: string;
  category: SignalCategory;
  severity: Severity;
  sessionDate: string;
  detail: string;
  metrics: SignalMetric[];
  actions: SignalAction[];
}

function byDate(a: { tradeDate: string }, b: { tradeDate: string }): number {
  return a.tradeDate < b.tradeDate ? -1 : a.tradeDate > b.tradeDate ? 1 : 0;
}

function latestDateOf(dates: string[]): string {
  return dates.length > 0 ? dates[0] : "—";
}

function fmtShares(v: number): string {
  const m = v / 1e6;
  if (m >= 1) return `${m.toFixed(2)}M`;
  return Math.round(v).toLocaleString("en-US");
}

function fmtCoverage(v: number): string {
  return `${v.toFixed(2)}x`;
}

// --------------------------------------------------------------- //
// Signal 1: sector smart-money absorption (shared engine source).  //
// --------------------------------------------------------------- //
function absorptionSignals(
  flows: FlowRow[],
  eod: EodPoint[],
  sectorMap: Map<string, string>,
  flowSession: string
): InsightSignal[] {
  if (flows.length === 0 || eod.length === 0) return [];
  return computeSectorSmartMoney({ flows, eod, sectorMap })
    .filter((r) => r.absorption)
    .sort((a, b) => b.net5dPkr - a.net5dPkr)
    .map((r) => ({
      id: `ABSORPTION:${r.sector}`,
      code: "SMART MONEY ABSORPTION",
      subject: r.sector,
      category: "FLOW" as const,
      severity: "OPPORTUNITY" as const,
      sessionDate: flowSession,
      detail:
        "Institutions net-bought while equal-weight price bled — accumulation "
        + "under distribution. Confirm with breadth before sizing.",
      metrics: [
        {
          label: "INST 5D NET",
          value: fmtPkrM(r.net5dPkr),
          tone: "text-bull",
        },
        {
          label: "PRICE 5D EQW",
          value: r.price5dPct == null ? "—" : fmtPct(r.price5dPct, 1),
          tone: "text-bear",
        },
        {
          label: "LATEST NET",
          value: fmtPkrM(r.latestPkr),
          tone: r.latestPkr > 0 ? "text-bull" : "text-bear",
        },
      ],
      actions: [
        { label: "FLOW @ SECTOR", desk: "FLOW", filter: r.sector },
        { label: "BREADTH", desk: "BREADTH" },
      ],
    }));
}

// --------------------------------------------------------------- //
// Signal 2: volume spike inside an Amihud TRAP tier.               //
// --------------------------------------------------------------- //
interface TrapRow {
  ticker: string;
  latestVol: number;
  avgVol: number;
  ratio: number;
  amihud: number;
  close: number | null;
}

function findSlippageTraps(eod: EodPoint[]): TrapRow[] {
  if (eod.length === 0) return [];
  const byTicker = new Map<string, EodPoint[]>();
  for (const r of eod) {
    const arr = byTicker.get(r.ticker);
    if (arr) arr.push(r);
    else byTicker.set(r.ticker, [r]);
  }
  const out: TrapRow[] = [];
  for (const [ticker, rows] of byTicker) {
    const chrono = rows
      .filter((r) => r.close != null && r.close > 0)
      .sort(byDate);
    if (chrono.length < 11) continue; // latest + ≥10 prior sessions — honest floor
    const latest = chrono[chrono.length - 1];
    if (latest.volume == null || latest.volume <= 0) continue;
    // Prior-20 session volume base: the spike session never dilutes its own baseline.
    const priorVols: number[] = [];
    for (let i = chrono.length - 2; i >= 0 && priorVols.length < 20; i--) {
      const v = chrono[i].volume;
      if (v != null && v > 0) priorVols.push(v);
    }
    if (priorVols.length < 10) continue;
    const avgVol = priorVols.reduce((a, b) => a + b, 0) / priorVols.length;
    const ratio = latest.volume / avgVol;
    if (ratio <= VOLUME_SPIKE_X) continue;
    // Amihud from the shared helper — identical formula to Breadth + quote HUD.
    const { amihud } = computeAmihudStats(
      chrono.map((r) => ({ close: r.close, volume: r.volume })),
      20,
      10
    );
    if (amihud == null || amihud < TRAP_AMIHUD) continue;
    out.push({
      ticker,
      latestVol: latest.volume,
      avgVol,
      ratio,
      amihud,
      close: latest.close,
    });
  }
  return out.sort((a, b) => b.ratio - a.ratio);
}

function slippageSignals(
  traps: TrapRow[],
  fundamentals: FundamentalsRow[],
  sectorMap: Map<string, string>,
  eodSession: string
): InsightSignal[] {
  const fundByTicker = new Map(fundamentals.map((f) => [f.ticker, f]));
  return traps.map((t) => {
    const fund = fundByTicker.get(t.ticker) ?? null;
    const sector = fund?.sectorName ?? sectorMap.get(t.ticker) ?? null;
    return {
      id: `TRAP:${t.ticker}`,
      code: "SLIPPAGE TRAP DETECTED",
      subject: sector != null ? `${t.ticker} · ${sector}` : t.ticker,
      category: "LIQUIDITY" as const,
      severity: "ALERT" as const,
      sessionDate: eodSession,
      detail:
        "Volume burst inside the TRAP — BRUTAL SLIPPAGE tier: size entering an "
        + "illiquid tape pays the spread. Work orders or stand down.",
      metrics: [
        {
          label: "VOL SPIKE",
          value: `${t.ratio.toFixed(1)}x`,
          tone: "text-warn",
        },
        { label: "VOL (LATEST)", value: fmtShares(t.latestVol) },
        { label: "VOL 20D AVG", value: fmtShares(t.avgVol) },
        {
          label: "AMIHUD",
          value: t.amihud >= 100 ? t.amihud.toFixed(0) : t.amihud.toFixed(1),
          tone: "text-bear",
        },
        { label: "LTP", value: t.close == null ? "—" : t.close.toFixed(2) },
        {
          label: "MKT CAP",
          value: fund?.marketCapPkr == null ? "—" : fmtPkrB(fund.marketCapPkr),
        },
      ],
      actions: [
        ...(sector != null
          ? [{ label: "FLOW @ SECTOR", desk: "FLOW", filter: sector }]
          : []),
        { label: "BREADTH", desk: "BREADTH" },
      ],
    };
  });
}

// --------------------------------------------------------------- //
// Signal 3: session A/D regime (capitulation vs expansion).        //
// Classification mirrors the Market Breadth desk exactly.          //
// --------------------------------------------------------------- //
function breadthSignal(
  eod: EodPoint[],
  eodSession: string
): InsightSignal | null {
  if (eod.length === 0) return null;
  const dates = Array.from(new Set(eod.map((r) => r.tradeDate)))
    .sort()
    .reverse();
  const latest = dates[0];
  const byTicker = new Map<string, { tradeDate: string; close: number }[]>();
  for (const r of eod) {
    if (r.close == null) continue;
    const arr = byTicker.get(r.ticker);
    if (arr) arr.push({ tradeDate: r.tradeDate, close: r.close });
    else byTicker.set(r.ticker, [{ tradeDate: r.tradeDate, close: r.close }]);
  }
  let adv = 0;
  let dec = 0;
  let unch = 0;
  for (const rows of byTicker.values()) {
    const series = rows
      .filter((r) => r.tradeDate <= latest)
      .sort(byDate);
    if (series.length < 2) continue; // no prior close — not classified
    const base = series[series.length - 2].close;
    if (base <= EPSILON) continue;
    const chg = series[series.length - 1].close - base;
    if (chg > EPSILON) adv += 1;
    else if (chg < -EPSILON) dec += 1;
    else unch += 1;
  }
  const classified = adv + dec + unch;
  if (classified < MIN_CLASSIFIED_NAMES) return null; // thin tape — no read
  const ratio = dec > 0 ? adv / dec : adv > 0 ? Infinity : null;
  if (ratio == null) return null;

  const capitulation = ratio < 0.25;
  const expansion = ratio > 3.0;
  if (!capitulation && !expansion) return null;

  const metrics: SignalMetric[] = [
    { label: "ADVANCES", value: String(adv), tone: "text-bull" },
    { label: "DECLINES", value: String(dec), tone: "text-bear" },
    {
      label: "A/D RATIO",
      value: Number.isFinite(ratio) ? ratio.toFixed(2) : "∞",
      tone: capitulation ? "text-bear" : "text-bull",
    },
    { label: "UNCHANGED", value: String(unch) },
  ];

  return capitulation
    ? {
        id: "CAPITULATION",
        code: "MARKET CAPITULATION",
        subject: `KSE ALL SHARE · ${classified} CLASSIFIED`,
        category: "FLOW",
        severity: "CRITICAL",
        sessionDate: eodSession,
        detail:
          "A/D collapsed below 0.25 — broad distribution, not rotation. Fade "
          + "attribution before trusting any single-sector read.",
        metrics,
        actions: [
          { label: "FLOW", desk: "FLOW" },
          { label: "BREADTH", desk: "BREADTH" },
        ],
      }
    : {
        id: "EXPANSION",
        code: "BREADTH EXPANSION",
        subject: `KSE ALL SHARE · ${classified} CLASSIFIED`,
        category: "FLOW",
        severity: "OPPORTUNITY",
        sessionDate: eodSession,
        detail:
          "A/D above 3.0 — participation is broad. Watch for follow-through "
          + "turnover before extending exposure.",
        metrics,
        actions: [
          { label: "FLOW", desk: "FLOW" },
          { label: "BREADTH", desk: "BREADTH" },
        ],
      };
}

// --------------------------------------------------------------- //
// Signal 4: rate vulnerability (coverage < 1.2x, floating > 1B).   //
// --------------------------------------------------------------- //
function rateSignals(kiborRows: KiborRow[]): InsightSignal[] {
  return kiborRows
    .map((row) => {
      // Coverage proxy identical to the Flow desk: EPS ÷ annual interest per
      // share at the 11% 6M-KIBOR stand-in (epsImpact100bps × 11).
      const annualInterestPerShare =
        row.epsImpact100bpsPkr != null && row.epsImpact100bpsPkr > 0
          ? row.epsImpact100bpsPkr * (KIBOR_RATE * 100)
          : null;
      const coverage =
        annualInterestPerShare != null &&
        row.currentEps != null &&
        annualInterestPerShare > 0
          ? row.currentEps / annualInterestPerShare
          : null;
      return { row, coverage };
    })
    .filter(
      (s) =>
        s.coverage != null &&
        s.coverage < MIN_COVERAGE_X &&
        s.row.floatingDebtPkr != null &&
        s.row.floatingDebtPkr > MIN_FLOATING_DEBT_PKR
    )
    .sort((a, b) => (a.coverage as number) - (b.coverage as number))
    .map(({ row, coverage }) => {
      const impact = row.epsImpact100bpsPkr;
      return {
        id: `RATES:${row.ticker}`,
        code: "RATE SENSITIVITY VULNERABILITY",
        subject:
          row.sectorName != null
            ? `${row.ticker} · ${row.sectorName}`
            : row.ticker,
        category: "RATES" as const,
        severity: "CRITICAL" as const,
        sessionDate: row.tradeDate,
        detail:
          "Interest coverage below 1.2x on >1B PKR floating debt — a further "
          + "100bps hike flips the name cash-flow negative at the EPS line.",
        metrics: [
          {
            label: "FLT DEBT",
            value: fmtPkrB(row.floatingDebtPkr),
            tone: "text-ink",
          },
          {
            label: "COVERAGE",
            value: fmtCoverage(coverage as number),
            tone: "text-bear",
          },
          {
            label: "ΔEPS @+100BPS",
            value: impact == null ? "—" : `${-impact >= 0 ? "+" : ""}${(-impact).toFixed(2)}`,
            tone: "text-bear",
          },
          {
            label: "BASE EPS",
            value: row.currentEps == null ? "—" : row.currentEps.toFixed(2),
          },
        ],
        actions: [{ label: "KIBOR DESK", desk: "KIBOR" }],
      };
    });
}

export default function InsightsWire({
  eod = [],
  fundamentals = [],
  kiborRows = [],
  sectorMap = new Map(),
  flows = [],
  onNavigate,
}: Props) {
  const [chip, setChip] = useState<Chip>("ALL");

  const flowSession = useMemo(
    () =>
      latestDateOf(
        Array.from(new Set(flows.map((r) => r.tradeDate))).sort().reverse()
      ),
    [flows]
  );
  const eodSession = useMemo(
    () =>
      latestDateOf(Array.from(new Set(eod.map((r) => r.tradeDate))).sort().reverse()),
    [eod]
  );

  const traps = useMemo(() => findSlippageTraps(eod), [eod]);

  const signals = useMemo<InsightSignal[]>(() => {
    const breadth: InsightSignal[] = [];
    const regime = breadthSignal(eod, eodSession);
    if (regime != null) breadth.push(regime);
    return [
      ...absorptionSignals(flows, eod, sectorMap, flowSession),
      ...slippageSignals(traps, fundamentals, sectorMap, eodSession),
      ...breadth,
      ...rateSignals(kiborRows),
    ].sort(
      (a, b) => SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity]
    );
  }, [flows, eod, sectorMap, flowSession, traps, fundamentals, eodSession, kiborRows]);

  const counts = useMemo(() => {
    const c: Record<Chip, number> = { ALL: signals.length, FLOW: 0, LIQUIDITY: 0, RATES: 0 };
    for (const s of signals) c[s.category] += 1;
    return c;
  }, [signals]);

  const visible = chip === "ALL" ? signals : signals.filter((s) => s.category === chip);
  const feedsLive = eod.length > 0 || flows.length > 0 || kiborRows.length > 0;

  return (
    <DeskFrame
      title="Quantitative Insights Wire — Anomaly Signal Engine"
      right={
        <span className="font-mono text-[10px] uppercase tracking-wider text-ghost">
          {signals.length} SIGNAL{signals.length === 1 ? "" : "S"} · SESSION{" "}
          {eodSession !== "—" ? eodSession : flowSession}
        </span>
      }
      footer={
        <p className="font-mono text-[10px] leading-relaxed text-ghost">
          Pure derivations over pre-loaded terminal state — zero fetches, zero
          synthetic inputs. ABSORPTION: shared sector smart-money engine
          (institutional 5D net &gt; 0 while equal-weight price 5D &lt; −1%).
          SLIPPAGE TRAP: latest volume &gt; 2x prior 20-session average with
          Amihud ≥ 50 (TRAP tier — same helper as Breadth + quote HUD; the
          spike session never dilutes its own baseline; ≥10 valid sessions
          required). BREADTH: latest-session A/D &lt; 0.25 capitulation or
          &gt; 3.0 expansion, minimum {MIN_CLASSIFIED_NAMES} classified names.
          RATES: coverage proxy (EPS ÷ annual interest per share at the 11%
          6M-KIBOR stand-in) &lt; 1.2x with floating debt &gt; 1B PKR.
        </p>
      }
    >
      {/* Regime filter chips */}
      <div className="flex flex-wrap items-center gap-1 border-b border-hairline bg-obsidian px-2.5 py-1.5">
        <span className="mr-1 font-mono text-[9px] uppercase tracking-widest text-ghost">
          REGIME
        </span>
        {CATEGORY_CHIPS.map((c) => (
          <button
            key={c}
            onClick={() => setChip(c)}
            aria-pressed={chip === c}
            className={`rounded-[2px] border px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider ${
              chip === c
                ? "border-info/60 bg-info/10 text-info"
                : "border-hairline text-muted hover:border-ghost hover:text-ink"
            }`}
          >
            {c}{" "}
            <span className="tabular-nums opacity-70">{counts[c]}</span>
          </button>
        ))}
      </div>

      {!feedsLive ? (
        <IdleState
          tone="warn"
          headline="[SIGNALS ENGINE: AWAITING EOD + NCCPL + KIBOR FEEDS]"
          detail="All four detectors bind to stored sessions only — the wire populates the moment any feed lands."
        />
      ) : visible.length === 0 ? (
        <IdleState
          tone="info"
          headline={`[NO ANOMALIES IN ${chip} REGIME]`}
          detail="All monitored thresholds quiet — zero signals fired on the latest stored session."
        />
      ) : (
        <div className="grid grid-cols-1 gap-2.5 p-2.5 lg:grid-cols-2 2xl:grid-cols-3">
          {visible.map((s) => (
            <article
              key={s.id}
              className="flex flex-col gap-2 border border-hairline bg-panel p-2.5 transition-colors hover:border-info/30"
            >
              <header>
                <div className="flex items-center justify-between gap-2">
                  <div className="flex min-w-0 items-center gap-1.5">
                    <Badge tone={SEVERITY_TONE[s.severity]}>{s.severity}</Badge>
                    <span
                      className="truncate font-mono text-[11px] font-bold tracking-wider text-ink"
                      title={s.code}
                    >
                      {s.code}
                    </span>
                  </div>
                  <span className="shrink-0 font-mono text-[9px] tabular-nums text-ghost">
                    {s.sessionDate}
                  </span>
                </div>
                <p
                  className="mt-0.5 truncate font-mono text-[10px] uppercase tracking-wider text-muted"
                  title={s.subject}
                >
                  {s.subject}
                </p>
              </header>

              <div className="grid grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-3">
                {s.metrics.map((m) => (
                  <div key={m.label}>
                    <p className="font-mono text-[9px] uppercase tracking-widest text-ghost">
                      {m.label}
                    </p>
                    <p
                      className={`font-mono text-[11px] font-semibold tabular-nums ${m.tone ?? "text-ink"}`}
                    >
                      {m.value}
                    </p>
                  </div>
                ))}
              </div>

              <p className="font-mono text-[10px] leading-relaxed text-ghost">
                {s.detail}
              </p>

              <footer className="mt-auto flex flex-wrap gap-1 border-t border-hairline pt-1.5">
                {s.actions.map((a) => (
                  <button
                    key={`${a.desk}:${a.filter ?? "*"}`}
                    onClick={() => onNavigate(a.desk, a.filter)}
                    className="rounded-[2px] border border-hairline bg-obsidian px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-muted hover:border-info/40 hover:text-info"
                  >
                    <span className="mr-1 font-bold text-info">[→]</span>
                    {a.label}
                  </button>
                ))}
              </footer>
            </article>
          ))}
        </div>
      )}
    </DeskFrame>
  );
}
