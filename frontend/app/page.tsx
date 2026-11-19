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

const RS_WATCH_FLOOR = 8.0; // only elite relative strength qualifies when no sweep fired
const CARRY_FLOOR = 18.0; // % annualised carry that beats the 11% policy rate by enough

const REGIME_TONE: Record<string, string> = {
  TRENDING: "border-emerald-200 bg-emerald-50 text-emerald-700",
  CHOPPY: "border-amber-200 bg-amber-50 text-amber-700",
  STRESS: "border-rose-200 bg-rose-50 text-rose-700",
  UNKNOWN: "border-slate-200 bg-slate-50 text-slate-600",
};

const EDGE_TONE: Record<string, string> = {
  "ACCUMULATION WINDOW ACTIVE": "border-blue-200 bg-blue-50 text-blue-700",
  "MOMENTUM LEADER": "border-emerald-200 bg-emerald-50 text-emerald-700",
  "LIQUIDITY SWEEP": "border-amber-200 bg-amber-50 text-amber-700",
  "ABOVE 50D SMA": "border-slate-200 bg-slate-50 text-slate-600",
};

function Tag({children}: {children: React.ReactNode}) {
  return (
    <span className="rounded border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[10px] font-semibold text-slate-600">
      {children}
    </span>
  );
}

function Stat({label, value, tone}: {label: string; value: string; tone?: string}) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white px-4 py-3 shadow-sm">
      <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">{label}</div>
      <div className={`mt-0.5 font-mono text-base font-bold ${tone ?? "text-slate-900"}`}>{value}</div>
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
        <div>
          <h1 className="text-xl font-bold tracking-tight text-slate-900">Today&apos;s Trade Desk</h1>
          <p className="text-xs text-slate-500">
            Buys and avoids are computed at the close — one engine, the same gates the 1-year lab replays.
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
            tone={kseUp ? "text-emerald-700" : "text-rose-700"}
          />
          <Stat label="SBP Policy Rate" value={`${pct(sbpRate, 1)}%`} tone="text-slate-900" />
        </div>
      </div>

      {/* UNIFIED DAILY ALPHA BRIEF — regime, confluence picks, stat-arb */}
      {alpha ? (
        <section className="rounded-xl border border-slate-200 bg-white shadow-sm">
          <header className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-200 p-4 sm:p-5">
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-base font-bold text-slate-900">Daily Alpha Brief</h2>
                <span
                  className={`rounded border px-2 py-0.5 text-[10px] font-bold tracking-wide ${
                    REGIME_TONE[alpha.marketRegime.regime] ?? REGIME_TONE.UNKNOWN
                  }`}
                >
                  {alpha.marketRegime.regime}
                </span>
                <span className="rounded border border-slate-200 bg-slate-50 px-2 py-0.5 text-[10px] font-semibold text-slate-500">
                  {alpha.sessionDate ?? "—"}
                </span>
              </div>
              <p className="mt-1 text-[11px] text-slate-500">{alpha.marketRegime.posture}</p>
              <div className="mt-2 flex flex-wrap gap-1.5">
                <Tag>Hurst {pct(alpha.marketRegime.hurstExponent, 3)}</Tag>
                <Tag>Variance ratio {pct(alpha.marketRegime.varianceRatio, 2)}</Tag>
                <Tag>Drawdown {pct(alpha.marketRegime.drawdownFromHighPct)}%</Tag>
                <Tag>Stress {pct(alpha.marketRegime.stressScore, 1)}/100</Tag>
                <Tag>Breadth {pct(alpha.marketRegime.breadthPct, 1)}%</Tag>
              </div>
            </div>
            <div className="text-right text-[10px] leading-relaxed text-slate-400">
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
            <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400">
              High-Conviction Confluence Picks
            </h3>
            {alpha.picks.length === 0 ? (
              <p className="px-1 py-6 text-center text-xs text-slate-400">
                No name clears two independent edges today — the regime says wait.
              </p>
            ) : (
              <div className="mt-2 overflow-x-auto">
                <table className="w-full min-w-[640px] border-collapse text-left text-[11px]">
                  <thead>
                    <tr className="border-b border-slate-200 text-[9px] uppercase tracking-wide text-slate-400">
                      <th className="py-1.5 pr-2 font-semibold">Ticker</th>
                      <th className="py-1.5 pr-2 font-semibold">Sector</th>
                      <th className="py-1.5 pr-2 font-semibold">Active Edges</th>
                      <th className="py-1.5 pr-2 text-right font-semibold">Win Rate</th>
                      <th className="py-1.5 pr-2 text-right font-semibold">Stop-Loss</th>
                      <th className="py-1.5 text-right font-semibold">Target Wt %</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {alpha.picks.map((pick) => (
                      <tr key={pick.ticker} className="align-top">
                        <td className="py-2 pr-2">
                          <div className="font-mono text-sm font-bold text-slate-900">{pick.ticker}</div>
                          <div className="font-mono text-[10px] text-slate-400">{money(pick.close)}</div>
                        </td>
                        <td className="py-2 pr-2 text-slate-600">{pick.sector}</td>
                        <td className="py-2 pr-2">
                          <div className="flex flex-wrap gap-1">
                            {pick.edges.map((edge) => (
                              <span
                                key={edge}
                                className={`rounded border px-1.5 py-0.5 text-[9px] font-semibold ${
                                  EDGE_TONE[edge] ?? "border-slate-200 bg-slate-50 text-slate-600"
                                }`}
                              >
                                {edge}
                              </span>
                            ))}
                          </div>
                        </td>
                        <td className="py-2 pr-2 text-right font-mono font-semibold text-slate-700">
                          {pick.winRatePct === null ? "—" : `${pct(pick.winRatePct, 1)}%`}
                        </td>
                        <td className="py-2 pr-2 text-right font-mono font-semibold text-rose-700">
                          {money(pick.stopLoss)}
                          <div className="text-[9px] font-normal text-rose-400">-{pct(pick.stopDistancePct, 1)}%</div>
                        </td>
                        <td className="py-2 text-right font-mono font-semibold text-slate-900">
                          {pct(pick.targetWeightPct, 2)}%
                          <div className="text-[9px] font-normal text-slate-400">risk {pct(pick.riskBudgetPct, 2)}%</div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            <div className="mt-4 border-t border-slate-200 pt-3">
              <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400">
                Active Stat-Arb Spreads (|z| ≥ 2.0)
              </h3>
              {alpha.statArb.length === 0 ? (
                <p className="px-1 py-4 text-center text-xs text-slate-400">
                  No same-sector spread is stretched beyond two sigma.
                </p>
              ) : (
                <ul className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
                  {alpha.statArb.map((arb) => (
                    <li
                      key={`${arb.legA}-${arb.legB}`}
                      className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-mono text-xs font-bold text-slate-900">
                          {arb.legA} / {arb.legB}
                        </span>
                        <span
                          className={`font-mono text-xs font-bold ${
                            arb.zScore > 0 ? "text-rose-700" : "text-emerald-700"
                          }`}
                        >
                          {arb.zScore > 0 ? "+" : ""}
                          {pct(arb.zScore)}σ
                        </span>
                      </div>
                      <div className="mt-0.5 text-[10px] font-semibold text-slate-600">{arb.action}</div>
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
        <div className="rounded-xl border border-slate-200 bg-white p-4 text-xs text-slate-500 shadow-sm">
          Daily alpha brief not generated yet — run{" "}
          <code className="font-mono">python backend/src/quant/daily_alpha.py</code>.
        </div>
      )}

      {!latest && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
          No signal file yet — run <code className="font-mono">python backend/scripts/process_daily_tape.py</code>.
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {/* LEFT — BUY / ACCUMULATE */}
        <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5">
          <header className="border-b border-slate-200 pb-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-base font-bold text-slate-900">Buy / Accumulate Setups</h2>
              <span className="rounded border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-[10px] font-bold text-emerald-700">
                SPOT MARKET
              </span>
            </div>
            <p className="mt-0.5 text-[11px] text-slate-500">
              Enter near the volume point of control, ATR × {engine.atrStopMult} stop, target +{engine.targetPct}%.
            </p>
          </header>

          {sweeps.length === 0 && watch.length === 0 ? (
            <p className="px-1 py-6 text-center text-xs text-slate-400">
              No qualified long setup this session — stay in cash.
            </p>
          ) : (
            <ul className="divide-y divide-slate-200">
              {sweeps.map((item) => {
                const stop = item.stopLoss;
                return (
                  <li key={item.ticker} className="py-3">
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-sm font-bold text-slate-900">{item.ticker}</span>
                        <span className="rounded border border-blue-200 bg-blue-50 px-1.5 py-0.5 text-[10px] font-bold text-blue-700">
                          LIQUIDITY SWEEP BUY
                        </span>
                      </div>
                      <span className="font-mono text-sm font-bold text-slate-800">{money(item.close)}</span>
                    </div>

                    <div className="mt-2 grid grid-cols-3 gap-2 text-[11px]">
                      <div className="rounded border border-slate-200 bg-slate-50 px-2 py-1">
                        <div className="text-[9px] uppercase tracking-wide text-slate-400">Entry Zone</div>
                        <div className="font-mono font-bold text-slate-800">{money(item.poc)}</div>
                      </div>
                      <div className="rounded border border-rose-200 bg-rose-50 px-2 py-1">
                        <div className="text-[9px] uppercase tracking-wide text-rose-500">Hard Stop</div>
                        <div className="font-mono font-bold text-rose-700">{money(stop)}</div>
                      </div>
                      <div className="rounded border border-emerald-200 bg-emerald-50 px-2 py-1">
                        <div className="text-[9px] uppercase tracking-wide text-emerald-600">Target +12%</div>
                        <div className="font-mono font-bold text-emerald-700">{money(item.target)}</div>
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
                        <span className="font-mono text-sm font-bold text-slate-900">{item.ticker}</span>
                        <span className="rounded border border-amber-200 bg-amber-50 px-1.5 py-0.5 text-[10px] font-bold text-amber-700">
                          RS ACCUMULATION WATCH
                        </span>
                      </div>
                      <span className="font-mono text-sm font-bold text-slate-800">{money(item.close)}</span>
                    </div>

                    <div className="mt-2 grid grid-cols-3 gap-2 text-[11px]">
                      <div className="rounded border border-slate-200 bg-slate-50 px-2 py-1">
                        <div className="text-[9px] uppercase tracking-wide text-slate-400">Entry Zone</div>
                        <div className="font-mono font-bold text-slate-800">{money(entry)}</div>
                      </div>
                      <div className="rounded border border-rose-200 bg-rose-50 px-2 py-1">
                        <div className="text-[9px] uppercase tracking-wide text-rose-500">Hard Stop</div>
                        <div className="font-mono font-bold text-rose-700">{money(item.stopLoss ?? item.close * 0.85)}</div>
                      </div>
                      <div className="rounded border border-emerald-200 bg-emerald-50 px-2 py-1">
                        <div className="text-[9px] uppercase tracking-wide text-emerald-600">Target +12%</div>
                        <div className="font-mono font-bold text-emerald-700">
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
                    <p className="mt-2 text-[10px] text-slate-400">
                      No sweep fired today, so this is accumulation only — trim size, no chasing.
                    </p>
                  </li>
                );
              })}
            </ul>
          )}
        </section>

        {/* RIGHT — DO NOT BUY / SHORT TRAPS */}
        <section className="rounded-xl border border-rose-200 bg-white p-4 shadow-sm sm:p-5">
          <header className="border-b border-slate-200 pb-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-base font-bold text-slate-900">Do Not Buy / DFX Short Traps</h2>
              <span className="rounded border border-rose-200 bg-rose-50 px-2 py-0.5 text-[10px] font-bold text-rose-700">
                FUTURES ONLY
              </span>
            </div>
            <p className="mt-0.5 text-[11px] text-slate-500">
              Carry above {CARRY_FLOOR.toFixed(0)}% against the {pct(sbpRate, 1)}% SBP rate, with broken relative
              strength — never buy spot here.
            </p>
          </header>

          {traps.length === 0 ? (
            <p className="px-1 py-6 text-center text-xs text-slate-400">
              No contract is carrying hard enough to flag today.
            </p>
          ) : (
            <ul className="divide-y divide-slate-200">
              {traps.map((item) => {
                const spread = item.annualizedCarryPct - sbpRate;
                return (
                  <li key={item.ticker} className="py-3">
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-sm font-bold text-slate-900">{item.ticker}</span>
                        <span className="rounded border border-rose-200 bg-rose-50 px-1.5 py-0.5 text-[10px] font-bold text-rose-700">
                          AVOID SPOT
                        </span>
                      </div>
                      <span className="font-mono text-sm font-bold text-rose-700">
                        {pct(item.annualizedCarryPct)}%
                      </span>
                    </div>

                    <div className="mt-2 grid grid-cols-2 gap-2 text-[11px]">
                      <div className="rounded border border-slate-200 bg-slate-50 px-2 py-1">
                        <div className="text-[9px] uppercase tracking-wide text-slate-400">Spot</div>
                        <div className="font-mono font-bold text-slate-800">{money(item.spotClose)}</div>
                      </div>
                      <div className="rounded border border-slate-200 bg-slate-50 px-2 py-1">
                        <div className="text-[9px] uppercase tracking-wide text-slate-400">Futures</div>
                        <div className="font-mono font-bold text-slate-800">{money(item.futClose)}</div>
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
