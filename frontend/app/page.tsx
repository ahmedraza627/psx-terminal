import fs from "node:fs";
import path from "node:path";

/** Today's actionable PSX desk: posture, what to buy, what to avoid. */
export const dynamic = "force-dynamic";

type Sweep = {
  ticker: string;
  close: number;
  poc: number;
  volZScore: number;
  mansfieldRs: number;
  stopLoss: number;
  target: number;
  rvol?: number;
  atr?: number;
  directorFootprint: boolean;
};

type Leader = {
  ticker: string;
  close: number;
  mansfieldRs: number;
  volZScore: number;
  poc: number;
  rvol?: number;
  stopLoss?: number;
  target?: number;
};

type Trap = {
  ticker: string;
  spotClose: number;
  futClose: number;
  annualizedCarryPct: number;
  mansfieldRs: number;
};

type AlphaPick = {
  rank: number;
  ticker: string;
  sector: string;
  close: number;
  edges: string[];
  stopLoss: number;
  targetWeightPct: number;
  riskBudgetPct: number;
};

type ExtendedSetup = {
  ticker: string;
  sector: string;
  close: number;
  note: string;
  ret20dPct: number | null;
  swingPositionPct: number | null;
  rsi14: number | null;
  bearishDivergence: boolean;
  divergenceType: string | null;
  divergenceNote: string | null;
};

type AlphaBrief = {
  sessionDate: string;
  marketRegime: { regime: string; posture: string };
  picks: AlphaPick[];
  extendedSetups?: ExtendedSetup[];
};

type Latest = {
  sessionDate: string;
  kse100?: { close: number | null; changePct: number | null };
  sbpRate?: number;
  liquiditySweeps?: Sweep[];
  rsLeaders?: Leader[];
  carryTraps?: Trap[];
  engine?: { targetPct?: number };
};

function readAlpha(): AlphaBrief | null {
  const candidates = [
    path.join(process.cwd(), "public", "data", "daily_alpha_brief.json"),
    path.join(process.cwd(), "frontend", "public", "data", "daily_alpha_brief.json"),
  ];
  for (const file of candidates) {
    try {
      return JSON.parse(fs.readFileSync(file, "utf-8")) as AlphaBrief;
    } catch {
      // try the next candidate
    }
  }
  return null;
}

function readLatest(): Latest | null {
  const candidates = [
    path.join(process.cwd(), "public", "data", "latest.json"),
    path.join(process.cwd(), "frontend", "public", "data", "latest.json"),
  ];
  for (const file of candidates) {
    try {
      return JSON.parse(fs.readFileSync(file, "utf-8")) as Latest;
    } catch {
      // try the next candidate
    }
  }
  return null;
}

const money = (value: number | null | undefined) =>
  value === null || value === undefined || Number.isNaN(value)
    ? "—"
    : value.toLocaleString("en-PK", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const pct = (value: number | null | undefined, digits = 2) =>
  value === null || value === undefined || Number.isNaN(value) ? "—" : value.toFixed(digits);

const signedPct = (value: number | null | undefined, digits = 1) =>
  value === null || value === undefined || Number.isNaN(value)
    ? "—"
    : `${value >= 0 ? "+" : ""}${value.toFixed(digits)}%`;

const RS_WATCH_FLOOR = 8.0; // only elite relative strength qualifies when no sweep fired
const CARRY_FLOOR = 18.0; // % annualised carry that beats the 12% policy rate by enough

const REGIME_TONE: Record<string, string> = {
  TRENDING: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
  CHOPPY: "border-amber-500/30 bg-amber-500/10 text-amber-300",
  STRESS: "border-rose-500/30 bg-rose-500/10 text-rose-300",
  UNKNOWN: "border-slate-800 bg-slate-900/40 text-slate-400",
};

const EDGE_TONE: Record<string, string> = {
  "ACCUMULATION WINDOW ACTIVE": "border-blue-500/30 bg-blue-500/10 text-blue-300",
  "MOMENTUM LEADER": "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
  "LIQUIDITY SWEEP": "border-amber-500/30 bg-amber-500/10 text-amber-300",
  "ABOVE 50D SMA": "border-slate-800 bg-slate-900/40 text-slate-400",
};

function Tag({ children }: { children: React.ReactNode }) {
  return (
    <span className="rounded border border-slate-700/70 bg-slate-800/50 px-1.5 py-0.5 font-mono text-[10px] font-semibold tabular-nums text-slate-400">
      {children}
    </span>
  );
}

function Metric({ label, value, hint, tone }: { label: string; value: string; hint?: string; tone?: string }) {
  return (
    <div className="rounded-xl border border-slate-800/80 bg-slate-950/40 px-4 py-3">
      <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">{label}</div>
      <div className={`mt-1 font-mono text-sm font-bold tabular-nums sm:text-base ${tone ?? "text-slate-100"}`}>
        {value}
      </div>
      {hint ? <div className="mt-0.5 text-[10px] leading-snug text-slate-500">{hint}</div> : null}
    </div>
  );
}

function SectionHeading({ title, count, tone }: { title: string; count?: string; tone?: string }) {
  return (
    <header className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-800 px-4 py-3 sm:px-5">
      <h2 className="text-base font-bold text-slate-100">{title}</h2>
      {count ? (
        <span className={`rounded border px-2 py-0.5 text-[10px] font-bold ${tone ?? "border-slate-800 bg-slate-900/40 text-slate-400"}`}>
          {count}
        </span>
      ) : null}
    </header>
  );
}

export default function DailyDeskPage() {
  const latest = readLatest();
  const alpha = readAlpha();
  const targetPct = latest?.engine?.targetPct ?? 12;
  const sweeps = latest?.liquiditySweeps ?? [];
  const traps = (latest?.carryTraps ?? []).filter(
    (trap) => (trap.annualizedCarryPct ?? 0) > CARRY_FLOOR && (trap.mansfieldRs ?? 0) < 0,
  );
  const watch = sweeps.length
    ? []
    : (latest?.rsLeaders ?? []).filter((lead) => (lead.mansfieldRs ?? 0) >= RS_WATCH_FLOOR);
  const waitSetups = alpha?.extendedSetups ?? [];
  const picks = alpha?.picks ?? [];
  const sbpRate = latest?.sbpRate ?? 12;
  const regime = alpha?.marketRegime.regime ?? "UNKNOWN";
  const kse = latest?.kse100;
  const kseUp = (kse?.changePct ?? 0) >= 0;
  const watchCount = picks.length + sweeps.length + watch.length;
  const avoidCount = waitSetups.length + traps.length;

  return (
    <div className="space-y-5">
      <header className="min-w-0">
        <span className="font-mono text-[10px] font-bold uppercase tracking-[0.18em] text-emerald-400/80">
          PSX · EOD intelligence
        </span>
        <h1 className="mt-1 text-xl font-bold tracking-tight text-slate-50 sm:text-2xl">Today&apos;s Trade Desk</h1>
      </header>

      {!latest && (
        <div className="rounded-2xl border border-amber-500/30 bg-amber-500/10 p-4 text-sm text-amber-200">
          No signal file yet — run <code className="font-mono">python backend/scripts/process_daily_tape.py</code>.
        </div>
      )}

      {/* (a) MARKET & RATE POSTURE */}
      <section className="overflow-hidden rounded-2xl border border-slate-800/80 bg-slate-900/40">
        <SectionHeading title="Market & Rate Posture" />
        <div className="p-4 sm:p-5">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <Metric
              label="SBP Policy Rate"
              value={`${pct(sbpRate, 2)}%`}
              hint="Ceiling 13.00% · Floor 11.00%"
              tone="text-slate-50"
            />
            <Metric label="Session" value={latest?.sessionDate ?? "—"} hint="Last processed close" />
            <Metric
              label="KSE-100"
              value={`${money(kse?.close)}  ${(kse?.changePct ?? 0) >= 0 ? "+" : ""}${pct(kse?.changePct)}%`}
              hint="Index close"
              tone={kseUp ? "text-emerald-300" : "text-rose-300"}
            />
          </div>

          <div className="mt-3 flex flex-wrap items-center gap-2">
            <span
              className={`rounded border px-2 py-0.5 text-[10px] font-bold tracking-wide ${
                REGIME_TONE[regime] ?? REGIME_TONE.UNKNOWN
              }`}
            >
              {regime}
            </span>
            <p className="text-[11px] leading-relaxed text-slate-400">
              {alpha?.marketRegime.posture ?? "Regime read unavailable for this session."}
            </p>
          </div>

          <p className="mt-2 text-[11px] leading-relaxed text-slate-400">
            At a {pct(sbpRate, 2)}% policy rate, cash and finance costs set a {pct(sbpRate, 2)}% hurdle: carry must
            clear it comfortably before a futures position is worth holding, and spot longs need trend plus volume —
            not just a cheap price.
          </p>
        </div>
      </section>

      {/* (b) ACTIONABLE WATCHLIST */}
      <section className="overflow-hidden rounded-2xl border border-slate-800/80 bg-slate-900/40">
        <SectionHeading
          title="Actionable Watchlist"
          count={`${watchCount} NAME${watchCount === 1 ? "" : "S"}`}
          tone="border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
        />
        {watchCount === 0 ? (
          <p className="px-4 py-8 text-center text-xs text-slate-500 sm:px-5">
            Nothing clears the desk gates this session — stay in cash and wait for the next tape.
          </p>
        ) : (
          <div className="divide-y divide-slate-800/70">
            {picks.map((pick) => (
              <div key={`pick-${pick.ticker}`} className="px-4 py-3 sm:px-5">
                <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
                  <div className="flex min-w-0 flex-wrap items-center gap-2">
                    <span className="font-mono text-sm font-bold text-slate-50">{pick.ticker}</span>
                    <span className="font-mono text-[9px] text-slate-500">#{pick.rank}</span>
                    <span className="font-mono text-[10px] text-slate-500">{pick.sector}</span>
                  </div>
                  <span className="font-mono text-sm font-bold tabular-nums text-slate-200">PKR {money(pick.close)}</span>
                </div>
                <div className="mt-1.5 flex flex-wrap gap-1">
                  {pick.edges.map((edge) => (
                    <span
                      key={edge}
                      className={`rounded border px-1.5 py-0.5 text-[9px] font-semibold ${
                        EDGE_TONE[edge] ?? "border-slate-800 bg-slate-900/40 text-slate-400"
                      }`}
                    >
                      {edge}
                    </span>
                  ))}
                </div>
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  <Tag>stop {money(pick.stopLoss)}</Tag>
                  <Tag>target wt {pct(pick.targetWeightPct, 2)}%</Tag>
                  <Tag>risk {pct(pick.riskBudgetPct, 2)}%</Tag>
                </div>
              </div>
            ))}

            {sweeps.map((item) => (
              <div key={`sweep-${item.ticker}`} className="px-4 py-3 sm:px-5">
                <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
                  <div className="flex min-w-0 flex-wrap items-center gap-2">
                    <span className="font-mono text-sm font-bold text-slate-50">{item.ticker}</span>
                    <span className="rounded border border-blue-500/30 bg-blue-500/10 px-1.5 py-0.5 text-[10px] font-bold text-blue-300">
                      LIQUIDITY SWEEP BUY
                    </span>
                  </div>
                  <span className="font-mono text-sm font-bold tabular-nums text-slate-200">{money(item.close)}</span>
                </div>
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  <Tag>entry {money(item.poc)}</Tag>
                  <Tag>stop {money(item.stopLoss)}</Tag>
                  <Tag>target {money(item.target)}</Tag>
                  <Tag>RVOL {pct(item.rvol)}x</Tag>
                  <Tag>Mansfield RS +{pct(item.mansfieldRs)}%</Tag>
                </div>
              </div>
            ))}

            {watch.map((item) => (
              <div key={`watch-${item.ticker}`} className="px-4 py-3 sm:px-5">
                <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
                  <div className="flex min-w-0 flex-wrap items-center gap-2">
                    <span className="font-mono text-sm font-bold text-slate-50">{item.ticker}</span>
                    <span className="rounded border border-amber-500/30 bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-bold text-amber-300">
                      RS ACCUMULATION WATCH
                    </span>
                  </div>
                  <span className="font-mono text-sm font-bold tabular-nums text-slate-200">{money(item.close)}</span>
                </div>
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  <Tag>entry {money(item.poc || item.close)}</Tag>
                  <Tag>stop {money(item.stopLoss ?? item.close * 0.85)}</Tag>
                  <Tag>target {money(item.target ?? item.close * (1 + targetPct / 100))}</Tag>
                  <Tag>Mansfield RS +{pct(item.mansfieldRs)}%</Tag>
                </div>
                <p className="mt-1 text-[10px] text-slate-500">
                  No sweep fired today, so this is accumulation only — trim size, no chasing.
                </p>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* (c) AVOID / WAIT PULLBACK */}
      <section className="overflow-hidden rounded-2xl border border-rose-500/30 bg-slate-900/40">
        <SectionHeading
          title="Avoid / Wait Pullback"
          count={`${avoidCount} FLAG${avoidCount === 1 ? "" : "S"}`}
          tone="border-rose-500/30 bg-rose-500/10 text-rose-300"
        />
        {avoidCount === 0 ? (
          <p className="px-4 py-8 text-center text-xs text-slate-500 sm:px-5">
            No name is extended or carrying hard enough to flag today.
          </p>
        ) : (
          <div className="divide-y divide-slate-800/70">
            {waitSetups.map((setup) => (
              <div key={`wait-${setup.ticker}`} className="px-4 py-3 sm:px-5">
                <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
                  <div className="flex min-w-0 flex-wrap items-center gap-2">
                    <span className="font-mono text-sm font-bold text-slate-50">{setup.ticker}</span>
                    <span className="rounded border border-rose-500/40 bg-rose-500/10 px-1.5 py-0.5 font-mono text-[9px] font-bold text-rose-300">
                      WAIT PULLBACK
                    </span>
                    <span className="font-mono text-[10px] text-slate-500">{setup.sector}</span>
                  </div>
                  <span className="font-mono text-sm tabular-nums text-slate-300">{money(setup.close)}</span>
                </div>
                <p className="mt-1 text-[10px] leading-relaxed text-slate-400">{setup.note}</p>
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  <Tag>20D {signedPct(setup.ret20dPct)}</Tag>
                  <Tag>swing {setup.swingPositionPct === null ? "—" : `${pct(setup.swingPositionPct, 0)}%`}</Tag>
                  {setup.rsi14 !== null && <Tag>RSI {pct(setup.rsi14, 1)}</Tag>}
                  {setup.bearishDivergence && (
                    <span
                      className="rounded border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 font-mono text-[9px] font-bold text-amber-300"
                      title={setup.divergenceNote ?? "Swing-high divergence"}
                    >
                      DIVERGENCE · {setup.divergenceType === "PRICE_VOLUME" ? "VOLUME" : "RSI"}
                    </span>
                  )}
                </div>
              </div>
            ))}

            {traps.map((item) => (
              <div key={`trap-${item.ticker}`} className="px-4 py-3 sm:px-5">
                <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
                  <div className="flex min-w-0 flex-wrap items-center gap-2">
                    <span className="font-mono text-sm font-bold text-slate-50">{item.ticker}</span>
                    <span className="rounded border border-rose-500/40 bg-rose-500/10 px-1.5 py-0.5 font-mono text-[9px] font-bold text-rose-300">
                      AVOID SPOT
                    </span>
                  </div>
                  <span className="font-mono text-sm font-bold tabular-nums text-rose-300">
                    {pct(item.annualizedCarryPct)}% carry
                  </span>
                </div>
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  <Tag>spot {money(item.spotClose)}</Tag>
                  <Tag>futures {money(item.futClose)}</Tag>
                  <Tag>
                    +{pct((item.annualizedCarryPct ?? 0) - sbpRate)}% over SBP {pct(sbpRate, 2)}%
                  </Tag>
                  <Tag>Mansfield RS {pct(item.mansfieldRs)}%</Tag>
                </div>
              </div>
            ))}
          </div>
        )}
        {traps.length > 0 && (
          <p className="border-t border-slate-800 px-4 py-2 text-[10px] leading-snug text-slate-500 sm:px-5">
            Carry traps are only flagged where a futures contract actually traded on the tape — a name with no
            futures/DFM close is never given a synthetic rate.
          </p>
        )}
      </section>
    </div>
  );
}
