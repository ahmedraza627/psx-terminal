import fs from "node:fs";
import path from "node:path";

/** Today's actionable PSX desk: what to buy, what to stay out of. */
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
  trendStretchPct?: number;
  atr?: number;
  reason?: string;
  directorFootprint: boolean;
};

type Leader = {
  ticker: string;
  close: number;
  mansfieldRs: number;
  volZScore: number;
  poc: number;
  rvol?: number;
  trendStretchPct?: number;
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
  edgeCount: number;
  score: number;
  winRatePct: number | null;
  stopLoss: number;
  stopDistancePct: number;
  targetWeightPct: number;
  riskBudgetPct: number;
  momentum6mPct: number;
  avgTurnoverPkr: number;
  seasonalStatus?: string | null;
};

type ExtendedSetup = {
  ticker: string;
  sector: string;
  close: number;
  action: string;
  reasons: string[];
  note: string;
  ret20dPct: number | null;
  swingPositionPct: number | null;
  rsi14: number | null;
  bearishDivergence: boolean;
  divergenceType: string | null;
  divergenceNote: string | null;
  score: number;
  seasonalStatus?: string | null;
};

type AlphaArb = {
  legA: string;
  legB: string;
  sector: string;
  zScore: number;
  action: string;
  hedgeRatio: number;
  confidencePct: number;
};

type AlphaBrief = {
  generatedAt: string;
  sessionDate: string;
  marketRegime: {
    regime: string;
    hurstExponent: number;
    varianceRatio: number;
    posture: string;
    stressScore: number;
    drawdownFromHighPct: number;
    breadthPct: number;
    proxySessions: number;
  };
  portfolio?: { grossExposurePct: number; portfolioVarPct: number; varCapPct: number };
  picks: AlphaPick[];
  extendedSetups?: ExtendedSetup[];
  statArb: AlphaArb[];
  universe: { scanned: number; eligible: number; liquid: number };
};

type Latest = {
  sessionDate: string;
  kse100?: { close: number | null; changePct: number | null };
  sbpRate?: number;
  liquiditySweeps?: Sweep[];
  rsLeaders?: Leader[];
  carryTraps?: Trap[];
  engine?: {
    trendMaDays?: number;
    minRvol?: number;
    minVolZ?: number;
    atrStopMult?: number;
    targetPct?: number;
  };
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
const CARRY_FLOOR = 18.0; // % annualised carry that beats the 11% policy rate by enough

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

function Tag({children}: {children: React.ReactNode}) {
  return (
    <span className="rounded border border-slate-700/70 bg-slate-800/50 px-1.5 py-0.5 font-mono text-[10px] font-semibold tabular-nums text-slate-400">
      {children}
    </span>
  );
}

function Stat({label, value, tone}: {label: string; value: string; tone?: string}) {
  return (
    <div className="rounded-2xl border border-slate-800/80 bg-slate-900/50 px-4 py-3">
      <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">{label}</div>
      <div className={`mt-1 font-mono text-sm font-bold tabular-nums sm:text-base ${tone ?? "text-slate-100"}`}>{value}</div>
    </div>
  );
}

export default function DailyDeskPage() {
  const latest = readLatest();
  const alpha = readAlpha();
  // Live gates, published by the desk run. The desk and the 1-year lab share one engine.
  const engine = {
    trendMaDays: latest?.engine?.trendMaDays ?? 50,
    minRvol: latest?.engine?.minRvol ?? 1.5,
    minVolZ: latest?.engine?.minVolZ ?? 1.0,
    atrStopMult: latest?.engine?.atrStopMult ?? 2,
    targetPct: latest?.engine?.targetPct ?? 12,
  };
  const sweeps = latest?.liquiditySweeps ?? [];
  const traps = (latest?.carryTraps ?? []).filter(
    (trap) => (trap.annualizedCarryPct ?? 0) > CARRY_FLOOR && (trap.mansfieldRs ?? 0) < 0,
  );
  const watch = sweeps.length
    ? []
    : (latest?.rsLeaders ?? []).filter((lead) => (lead.mansfieldRs ?? 0) >= RS_WATCH_FLOOR);
  const sbpRate = latest?.sbpRate ?? 11;
  const kse = latest?.kse100;
  const kseUp = (kse?.changePct ?? 0) >= 0;

  return (
    <div className="space-y-5">
      {/* Session strip */}
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div className="min-w-0">
          <span className="font-mono text-[10px] font-bold uppercase tracking-[0.18em] text-emerald-400/80">
            PSX · EOD intelligence
          </span>
          <h1 className="mt-1 text-xl font-bold tracking-tight text-slate-50 sm:text-2xl">
            Today&apos;s Trade Desk
          </h1>
          <p className="mt-1 max-w-2xl text-[11px] leading-relaxed text-slate-400">
            Buys and avoids are computed at the close — one engine, the same gates the backtest lab
            replays.
          </p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            <Tag>Above SMA{engine.trendMaDays}</Tag>
            <Tag>RVOL ≥ {engine.minRvol}x · Z ≥ {engine.minVolZ}</Tag>
            <Tag>ATR × {engine.atrStopMult} stop</Tag>
            <Tag>Target +{engine.targetPct}%</Tag>
          </div>
        </div>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-3 sm:gap-3">
          <Stat label="Session" value={latest?.sessionDate ?? "—"} />
          <Stat
            label="KSE-100"
            value={`${money(kse?.close)}  ${(kse?.changePct ?? 0) >= 0 ? "+" : ""}${pct(kse?.changePct)}%`}
            tone={kseUp ? "text-emerald-300" : "text-rose-300"}
          />
          <Stat label="SBP Policy Rate" value={`${pct(sbpRate, 1)}%`} tone="text-slate-100" />
        </div>
      </div>

      {/* UNIFIED DAILY ALPHA BRIEF — regime, confluence picks, stat-arb */}
      {alpha ? (
        <section className="overflow-hidden rounded-2xl border border-slate-800/80 bg-slate-900/40">
          <header className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-800 p-4 sm:p-5">
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-base font-bold text-slate-100">Daily Alpha Brief</h2>
                <span
                  className={`rounded border px-2 py-0.5 text-[10px] font-bold tracking-wide ${
                    REGIME_TONE[alpha.marketRegime.regime] ?? REGIME_TONE.UNKNOWN
                  }`}
                >
                  {alpha.marketRegime.regime}
                </span>
                <span className="rounded border border-slate-800 bg-slate-900/40 px-2 py-0.5 text-[10px] font-semibold text-slate-400">
                  {alpha.sessionDate ?? "—"}
                </span>
              </div>
              <p className="mt-1 text-[11px] text-slate-400">{alpha.marketRegime.posture}</p>
              <div className="mt-2 flex flex-wrap gap-1.5">
                <Tag>Hurst {pct(alpha.marketRegime.hurstExponent, 3)}</Tag>
                <Tag>Variance ratio {pct(alpha.marketRegime.varianceRatio, 2)}</Tag>
                <Tag>Drawdown {pct(alpha.marketRegime.drawdownFromHighPct)}%</Tag>
                <Tag>Stress {pct(alpha.marketRegime.stressScore, 1)}/100</Tag>
                <Tag>Breadth {pct(alpha.marketRegime.breadthPct, 1)}%</Tag>
              </div>
            </div>
            <div className="text-right text-[10px] leading-relaxed text-slate-500">
              <div>{alpha.universe.liquid} liquid of {alpha.universe.eligible} eligible</div>
              <div>{alpha.picks.length} confluence picks · {alpha.statArb.length} stat-arb</div>
              {alpha.portfolio && (
                <div>
                  gross {pct(alpha.portfolio.grossExposurePct, 1)}% · VaR {pct(alpha.portfolio.portfolioVarPct, 2)}%
                </div>
              )}
              <div>refreshed {alpha.generatedAt.slice(0, 16).replace("T", " ")} UTC</div>
            </div>
          </header>

          <div className="p-4 sm:p-5">
            <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500">
              High-Conviction Confluence Picks
            </h3>
            {alpha.picks.length === 0 ? (
              <p className="px-1 py-6 text-center text-xs text-slate-500">
                No name clears two independent edges today — the regime says wait.
              </p>
            ) : (
              <>
                {/* mobile: card stack, no horizontal overflow */}
                <ul className="mt-3 space-y-2 md:hidden">
                  {alpha.picks.map((pick) => (
                    <li
                      key={pick.ticker}
                      className="rounded-xl border border-slate-800/80 bg-slate-950/60 p-3"
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="font-mono text-sm font-bold text-slate-50">
                              {pick.ticker}
                            </span>
                            <span className="font-mono text-[9px] text-slate-500">#{pick.rank}</span>
                          </div>
                          <div className="font-mono text-[10px] text-slate-500">
                            {pick.sector} · PKR {money(pick.close)}
                          </div>
                        </div>
                        <div className="shrink-0 text-right">
                          <div className="font-mono text-sm font-bold tabular-nums text-slate-100">
                            {pct(pick.targetWeightPct, 2)}%
                          </div>
                          <div className="text-[9px] uppercase tracking-wide text-slate-500">
                            target wt
                          </div>
                        </div>
                      </div>

                      <div className="mt-2 flex flex-wrap gap-1">
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

                      <div className="mt-2 grid grid-cols-3 gap-1.5 font-mono text-[10px]">
                        <div className="rounded-lg border border-slate-800/70 bg-slate-900/60 px-2 py-1">
                          <div className="text-[8px] uppercase text-slate-500">win rate</div>
                          <div className="tabular-nums text-slate-200">
                            {pick.winRatePct === null ? "—" : `${pct(pick.winRatePct, 1)}%`}
                          </div>
                        </div>
                        <div className="rounded-lg border border-slate-800/70 bg-slate-900/60 px-2 py-1">
                          <div className="text-[8px] uppercase text-slate-500">stop</div>
                          <div className="tabular-nums text-rose-300">{money(pick.stopLoss)}</div>
                        </div>
                        <div className="rounded-lg border border-slate-800/70 bg-slate-900/60 px-2 py-1">
                          <div className="text-[8px] uppercase text-slate-500">risk</div>
                          <div className="tabular-nums text-slate-200">
                            {pct(pick.riskBudgetPct, 2)}%
                          </div>
                        </div>
                      </div>
                    </li>
                  ))}
                </ul>

                {/* desktop: full table with a pinned ticker column */}
                <div className="mt-3 hidden overflow-x-auto md:block">
                  <table className="w-full border-collapse text-left text-[11px]">
                    <thead>
                      <tr className="border-b border-slate-800 text-[9px] uppercase tracking-wide text-slate-500">
                        <th className="py-1.5 pr-2 font-semibold">Ticker</th>
                        <th className="py-1.5 pr-2 font-semibold">Sector</th>
                        <th className="py-1.5 pr-2 font-semibold">Active Edges</th>
                        <th className="py-1.5 pr-2 text-right font-semibold">Win Rate</th>
                        <th className="py-1.5 pr-2 text-right font-semibold">Stop-Loss</th>
                        <th className="py-1.5 text-right font-semibold">Target Wt %</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800/70">
                      {alpha.picks.map((pick) => (
                        <tr key={pick.ticker} className="align-top hover:bg-slate-900/50">
                          <td className="whitespace-nowrap py-2 pr-2">
                            <div className="font-mono text-sm font-bold text-slate-50">{pick.ticker}</div>
                            <div className="font-mono text-[10px] tabular-nums text-slate-500">
                              {money(pick.close)}
                            </div>
                          </td>
                          <td className="whitespace-nowrap py-2 pr-2 text-slate-400">{pick.sector}</td>
                          <td className="py-2 pr-2">
                            <div className="flex flex-wrap gap-1">
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
                          </td>
                          <td className="whitespace-nowrap py-2 pr-2 text-right font-mono font-semibold tabular-nums text-slate-300">
                            {pick.winRatePct === null ? "—" : `${pct(pick.winRatePct, 1)}%`}
                          </td>
                          <td className="whitespace-nowrap py-2 pr-2 text-right font-mono font-semibold tabular-nums text-rose-300">
                            {money(pick.stopLoss)}
                            <div className="text-[9px] font-normal text-rose-400">
                              -{pct(pick.stopDistancePct, 1)}%
                            </div>
                          </td>
                          <td className="whitespace-nowrap py-2 text-right font-mono font-semibold tabular-nums text-slate-100">
                            {pct(pick.targetWeightPct, 2)}%
                            <div className="text-[9px] font-normal text-slate-500">
                              risk {pct(pick.riskBudgetPct, 2)}%
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}

            {alpha.extendedSetups && alpha.extendedSetups.length > 0 && (
              <div className="mt-4 border-t border-slate-800 pt-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500">
                    Extended — Buy Suppressed
                  </h3>
                  <span className="rounded border border-rose-500/40 bg-rose-500/10 px-2 py-0.5 font-mono text-[9px] font-bold text-rose-300">
                    {alpha.extendedSetups.length} WAIT PULLBACK
                  </span>
                </div>
                <ul className="mt-2 divide-y divide-slate-800/70 overflow-hidden rounded-xl border border-rose-500/25 bg-slate-950/40">
                  {alpha.extendedSetups.map((setup) => (
                    <li key={setup.ticker} className="px-3 py-2">
                      <div className="flex flex-wrap items-baseline justify-between gap-x-2 gap-y-1">
                        <div className="flex min-w-0 flex-wrap items-center gap-1.5">
                          <span className="font-mono text-sm font-bold text-slate-50">
                            {setup.ticker}
                          </span>
                          <span className="rounded border border-rose-500/40 bg-rose-500/10 px-1.5 py-0.5 font-mono text-[9px] font-bold text-rose-300">
                            EXTENDED / WAIT PULLBACK
                          </span>
                          {setup.bearishDivergence && (
                            <span
                              className="rounded border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 font-mono text-[9px] font-bold text-amber-300"
                              title={setup.divergenceNote ?? "Swing-high divergence"}
                            >
                              BEARISH DIVERGENCE · {setup.divergenceType === "PRICE_VOLUME" ? "VOLUME" : "RSI"}
                            </span>
                          )}
                          <span className="font-mono text-[10px] text-slate-500">{setup.sector}</span>
                        </div>
                        <span className="font-mono text-[10px] tabular-nums text-slate-400">
                          {money(setup.close)}
                        </span>
                      </div>
                      <p className="mt-1 text-[10px] leading-relaxed text-slate-400">{setup.note}</p>
                      <div className="mt-1 flex flex-wrap gap-1.5">
                        <Tag>20D {signedPct(setup.ret20dPct)}</Tag>
                        <Tag>swing {setup.swingPositionPct === null ? "—" : `${pct(setup.swingPositionPct, 0)}%`}</Tag>
                        {setup.rsi14 !== null && <Tag>RSI {pct(setup.rsi14, 1)}</Tag>}
                        {setup.divergenceType && <Tag>{setup.divergenceType}</Tag>}
                      </div>
                    </li>
                  ))}
                </ul>
                <p className="mt-1.5 text-[10px] leading-snug text-slate-500">
                  No buy promotion for these names: a 20-session run-up pinned at the top of its swing, or
                  price making a higher high on weaker RSI/volume. Wait for the pullback.
                </p>
              </div>
            )}

            <div className="mt-4 border-t border-slate-800 pt-3">
              <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500">
                Active Stat-Arb Spreads (|z| ≥ 2.0)
              </h3>
              {alpha.statArb.length === 0 ? (
                <p className="px-1 py-4 text-center text-xs text-slate-500">
                  No same-sector spread is stretched beyond two sigma.
                </p>
              ) : (
                <ul className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
                  {alpha.statArb.map((arb) => (
                    <li
                      key={`${arb.legA}-${arb.legB}`}
                      className="rounded-lg border border-slate-800 bg-slate-900/40 px-3 py-2"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-mono text-xs font-bold text-slate-100">
                          {arb.legA} / {arb.legB}
                        </span>
                        <span
                          className={`font-mono text-xs font-bold ${
                            arb.zScore > 0 ? "text-rose-300" : "text-emerald-300"
                          }`}
                        >
                          {arb.zScore > 0 ? "+" : ""}
                          {pct(arb.zScore)}σ
                        </span>
                      </div>
                      <div className="mt-0.5 text-[10px] font-semibold text-slate-400">{arb.action}</div>
                      <div className="mt-1 flex flex-wrap gap-1.5">
                        <Tag>{arb.sector}</Tag>
                        <Tag>hedge {pct(arb.hedgeRatio, 3)}</Tag>
                        <Tag>conf {pct(arb.confidencePct, 0)}%</Tag>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </section>
      ) : (
        <div className="rounded-2xl border border-slate-800/80 bg-slate-900/40 p-4 text-xs text-slate-400">
          Daily alpha brief not generated yet — run{" "}
          <code className="font-mono">python backend/src/quant/daily_alpha.py</code>.
        </div>
      )}

      {!latest && (
        <div className="rounded-2xl border border-amber-500/30 bg-amber-500/10 p-4 text-sm text-amber-200">
          No signal file yet — run <code className="font-mono">python backend/scripts/process_daily_tape.py</code>.
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {/* LEFT — BUY / ACCUMULATE */}
        <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 shadow-sm sm:p-5">
          <header className="border-b border-slate-800 pb-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-base font-bold text-slate-100">Buy / Accumulate Setups</h2>
              <span className="rounded border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-[10px] font-bold text-emerald-300">
                SPOT MARKET
              </span>
            </div>
            <p className="mt-0.5 text-[11px] text-slate-400">
              Enter near the volume point of control, ATR × {engine.atrStopMult} stop, target +{engine.targetPct}%.
            </p>
          </header>

          {sweeps.length === 0 && watch.length === 0 ? (
            <p className="px-1 py-6 text-center text-xs text-slate-500">
              No qualified long setup this session — stay in cash.
            </p>
          ) : (
            <ul className="divide-y divide-slate-800">
              {sweeps.map((item) => {
                const stop = item.stopLoss;
                return (
                  <li key={item.ticker} className="py-3">
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-sm font-bold text-slate-100">{item.ticker}</span>
                        <span className="rounded border border-blue-500/30 bg-blue-500/10 px-1.5 py-0.5 text-[10px] font-bold text-blue-300">
                          LIQUIDITY SWEEP BUY
                        </span>
                      </div>
                      <span className="font-mono text-sm font-bold text-slate-200">{money(item.close)}</span>
                    </div>

                    <div className="mt-2 grid grid-cols-3 gap-2 text-[11px]">
                      <div className="rounded border border-slate-800 bg-slate-900/40 px-2 py-1">
                        <div className="text-[9px] uppercase tracking-wide text-slate-500">Entry Zone</div>
                        <div className="font-mono font-bold text-slate-200">{money(item.poc)}</div>
                      </div>
                      <div className="rounded border border-rose-500/30 bg-rose-500/10 px-2 py-1">
                        <div className="text-[9px] uppercase tracking-wide text-rose-500">Hard Stop</div>
                        <div className="font-mono font-bold text-rose-300">{money(stop)}</div>
                      </div>
                      <div className="rounded border border-emerald-500/30 bg-emerald-500/10 px-2 py-1">
                        <div className="text-[9px] uppercase tracking-wide text-emerald-400">Target +12%</div>
                        <div className="font-mono font-bold text-emerald-300">{money(item.target)}</div>
                      </div>
                    </div>

                    <div className="mt-2 flex flex-wrap gap-1.5">
                      <Tag>POC {pct(item.poc)}</Tag>
                      <Tag>RVOL {pct(item.rvol)}x</Tag>
                      <Tag>Vol Z {pct(item.volZScore)}</Tag>
                      <Tag>Mansfield RS +{pct(item.mansfieldRs)}%</Tag>
                      <Tag>{item.directorFootprint ? "Director footprint" : "No director filing"}</Tag>
                    </div>
                  </li>
                );
              })}

              {watch.map((item) => {
                const entry = item.poc || item.close;
                return (
                  <li key={item.ticker} className="py-3">
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-sm font-bold text-slate-100">{item.ticker}</span>
                        <span className="rounded border border-amber-500/30 bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-bold text-amber-300">
                          RS ACCUMULATION WATCH
                        </span>
                      </div>
                      <span className="font-mono text-sm font-bold text-slate-200">{money(item.close)}</span>
                    </div>

                    <div className="mt-2 grid grid-cols-3 gap-2 text-[11px]">
                      <div className="rounded border border-slate-800 bg-slate-900/40 px-2 py-1">
                        <div className="text-[9px] uppercase tracking-wide text-slate-500">Entry Zone</div>
                        <div className="font-mono font-bold text-slate-200">{money(entry)}</div>
                      </div>
                      <div className="rounded border border-rose-500/30 bg-rose-500/10 px-2 py-1">
                        <div className="text-[9px] uppercase tracking-wide text-rose-500">Hard Stop</div>
                        <div className="font-mono font-bold text-rose-300">{money(item.stopLoss ?? item.close * 0.85)}</div>
                      </div>
                      <div className="rounded border border-emerald-500/30 bg-emerald-500/10 px-2 py-1">
                        <div className="text-[9px] uppercase tracking-wide text-emerald-400">Target +12%</div>
                        <div className="font-mono font-bold text-emerald-300">
                          {money(item.target ?? item.close * (1 + engine.targetPct / 100))}
                        </div>
                      </div>
                    </div>

                    <div className="mt-2 flex flex-wrap gap-1.5">
                      <Tag>POC {pct(item.poc)}</Tag>
                      <Tag>RVOL {pct(item.rvol)}x</Tag>
                      <Tag>Vol Z {pct(item.volZScore)}</Tag>
                      <Tag>Mansfield RS +{pct(item.mansfieldRs)}%</Tag>
                    </div>
                    <p className="mt-2 text-[10px] text-slate-500">
                      No sweep fired today, so this is accumulation only — trim size, no chasing.
                    </p>
                  </li>
                );
              })}
            </ul>
          )}
        </section>

        {/* RIGHT — DO NOT BUY / SHORT TRAPS */}
        <section className="rounded-xl border border-rose-500/30 bg-slate-900/60 p-4 shadow-sm sm:p-5">
          <header className="border-b border-slate-800 pb-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-base font-bold text-slate-100">Do Not Buy / DFX Short Traps</h2>
              <span className="rounded border border-rose-500/30 bg-rose-500/10 px-2 py-0.5 text-[10px] font-bold text-rose-300">
                FUTURES ONLY
              </span>
            </div>
            <p className="mt-0.5 text-[11px] text-slate-400">
              Carry above {CARRY_FLOOR.toFixed(0)}% against the {pct(sbpRate, 1)}% SBP rate, with broken relative
              strength — never buy spot here.
            </p>
          </header>

          {traps.length === 0 ? (
            <p className="px-1 py-6 text-center text-xs text-slate-500">
              No contract is carrying hard enough to flag today.
            </p>
          ) : (
            <ul className="divide-y divide-slate-800">
              {traps.map((item) => {
                const spread = item.annualizedCarryPct - sbpRate;
                return (
                  <li key={item.ticker} className="py-3">
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-sm font-bold text-slate-100">{item.ticker}</span>
                        <span className="rounded border border-rose-500/30 bg-rose-500/10 px-1.5 py-0.5 text-[10px] font-bold text-rose-300">
                          AVOID SPOT
                        </span>
                      </div>
                      <span className="font-mono text-sm font-bold text-rose-300">
                        {pct(item.annualizedCarryPct)}%
                      </span>
                    </div>

                    <div className="mt-2 grid grid-cols-2 gap-2 text-[11px]">
                      <div className="rounded border border-slate-800 bg-slate-900/40 px-2 py-1">
                        <div className="text-[9px] uppercase tracking-wide text-slate-500">Spot</div>
                        <div className="font-mono font-bold text-slate-200">{money(item.spotClose)}</div>
                      </div>
                      <div className="rounded border border-slate-800 bg-slate-900/40 px-2 py-1">
                        <div className="text-[9px] uppercase tracking-wide text-slate-500">Futures</div>
                        <div className="font-mono font-bold text-slate-200">{money(item.futClose)}</div>
                      </div>
                    </div>

                    <div className="mt-2 flex flex-wrap items-center gap-1.5">
                      <Tag>Carry +{pct(spread)}% over SBP {pct(sbpRate, 1)}%</Tag>
                      <Tag>Mansfield RS {pct(item.mansfieldRs)}%</Tag>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}
