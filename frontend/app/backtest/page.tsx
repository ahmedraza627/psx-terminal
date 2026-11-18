"use client";

import { useEffect, useMemo, useState } from "react";

type Trade = {
  id: number;
  ticker: string;
  signalDate: string;
  exitDate: string | null;
  side: string;
  entryPrice: number;
  stopLoss: number;
  targetPrice: number;
  exitPrice: number | null;
  outcome: string;
  pnlPct: number;
  barsHeld: number;
  confidence: number;
  reason: string;
};

type CurvePoint = { date: string; equity: number; drawdownPct: number };

type YearRow = {
  year: number;
  returnPct: number;
  sessions: number;
  signals: number;
  maxDrawdownPct: number;
  startingEquity: number;
  endingEquity: number;
};

type DrawdownEpisode = {
  peakDate: string;
  troughDate: string;
  depthPct: number;
  recoveryDate: string | null;
  sessions: number | null;
};

type BasePayload = {
  generatedAt?: string;
  horizonYears?: number;
  sessionRange?: { from: string | null; to: string | null; sessions: number; years?: number; tickers?: number };
  equityCurve?: CurvePoint[];
};

type SweepPayload = BasePayload & {
  strategy?: {
    name: string;
    lookbackDays?: number;
    targetPct?: number;
    maxStopPct?: number;
    holdHorizonSessions?: number;
    positionPct?: number;
    trendMaDays?: number;
    trendSlopeBars?: number;
    trendReferenceBars?: number;
    minRvol?: number;
    minVolZ?: number;
    atrStopMult?: number;
  };
  metrics?: {
    totalSignals: number;
    wins: number;
    losses: number;
    inPlay: number;
    winRatePct: number;
    profitFactor: number | null;
    maxDrawdownPct: number;
    totalReturnPct: number;
    cagrPct?: number;
    avgPnlPct: number;
    avgBarsHeld: number;
    bestTradePct: number;
    worstTradePct: number;
    grossProfitPct: number;
    grossLossPct: number;
    startingCapital?: number;
    endingEquity: number;
    tradesPerYear?: number;
  };
  yearlyReturns?: YearRow[];
  drawdownEpisodes?: DrawdownEpisode[];
  maxDrawdown?: DrawdownEpisode | null;
  trades?: Trade[];
};

type MomentumPayload = BasePayload & {
  strategy?: {
    name: string;
    topN?: number;
    hardStopPct?: number;
    smaStopDays?: number;
    momentumLookbacksMonths?: number[];
    rebalanceFrequency?: string;
    positionSizing?: string;
  };
  metrics?: {
    totalSignals: number;
    wins: number;
    losses: number;
    inPlay: number;
    winRatePct: number;
    profitFactor: number | null;
    maxDrawdownPct: number;
    totalReturnPct: number;
    cagrPct?: number;
    avgPnlPct: number;
    avgBarsHeld: number;
    bestTradePct: number;
    worstTradePct: number;
    grossProfitPct: number;
    grossLossPct: number;
    startingCapital?: number;
    endingEquity: number;
    rebalanceMonths?: number;
  };
  yearlyReturns?: YearRow[];
  drawdownEpisodes?: DrawdownEpisode[];
  maxDrawdown?: DrawdownEpisode | null;
  trades?: Trade[];
  rebalanceSchedule?: { date: string; leaders: string[] }[];
  worstDrawdowns?: { ticker: string; peakDate: string; troughDate: string; depthPct: number; recovered: boolean }[];
};

type StressTestWindow = {
  window: string;
  from: string;
  to: string;
  sessions: number;
  oosFrom: string;
  oosTo: string;
  oosSessions: number;
  oosYears: number;
  regime: string;
  sweep: {
    signals: number;
    wins: number;
    losses: number;
    winRatePct: number;
    totalReturnPct: number;
    cagrPct: number;
    maxDrawdownPct: number;
    profitFactor: number | null;
  };
  momentum: {
    positions: number;
    wins: number;
    losses: number;
    winRatePct: number;
    totalReturnPct: number;
    cagrPct: number;
    maxDrawdownPct: number;
    profitFactor: number | null;
  };
  statArb: {
    pairs: number;
    signals: number;
    entrySignals: number;
    exitSignals: number;
  };
};

type StressTestAggregate = {
  sweep: {
    totalSignals: number;
    wins: number;
    losses: number;
    winRatePct: number;
    avgWinRatePct: number;
    avgDrawdownPct: number;
    worstWindowDrawdownPct: number;
    windowsAbove3DD: number;
    windowsAbove10DD: number;
  };
  momentum: {
    totalPositions: number;
    wins: number;
    losses: number;
    winRatePct: number;
    avgWinRatePct: number;
    avgDrawdownPct: number;
    worstWindowDrawdownPct: number;
    windowsAbove3DD: number;
    windowsAbove10DD: number;
  };
  regimeSwitching: Array<{ regime: string; windows: number }>;
};

type StressTestPayload = BasePayload & {
  meta?: {
    name: string;
    horizonYears: number;
    windowYears: number;
    stepYears: number;
    windowCount: number;
    withKelly: boolean;
    withVar: boolean;
    sizingMode: string;
    topN: number;
    statArbEnabled: boolean;
    sweepFiltersOn: boolean;
  };
  windowLabels?: string[];
  windows?: StressTestWindow[];
  aggregates?: StressTestAggregate;
};

type Payload = SweepPayload | MomentumPayload | StressTestPayload;

const HORIZONS = [
  { id: "1Y", label: "1-Year Lab", file: "/data/backtest_metrics.json" },
  { id: "5Y", label: "5-Year Macro Stress Test", file: "/data/backtest_5y_metrics.json" },
  { id: "15Y", label: "15-Year Meta-Brain Stress Test", file: "/data/stress_test_15y_metrics.json" },
] as const;

type Horizon = (typeof HORIZONS)[number]["id"];

const STRATEGIES = [
  {
    id: "sweep",
    label: "Liquidity Sweep Strategy",
    files: {
      "1Y": "/data/backtest_metrics.json",
      "5Y": "/data/backtest_5y_metrics.json",
      "15Y": "/data/stress_test_15y_metrics.json",
    },
  },
  {
    id: "momentum",
    label: "ETF Momentum Rotation Strategy",
    files: {
      "1Y": "/data/backtest_metrics.json",
      "5Y": "/data/momentum_5y_metrics.json",
      "15Y": "/data/stress_test_15y_metrics.json",
    },
  },
] as const;

type Strategy = (typeof STRATEGIES)[number]["id"];

const money = (value: number | null | undefined) =>
  value === null || value === undefined ? "—" : value.toFixed(2);

const signed = (value: number) => `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;

const outcomeTone = (outcome: string) => {
  if (outcome === "TARGET HIT") return "border-emerald-300 bg-emerald-50 text-emerald-700";
  if (outcome === "STOPPED OUT") return "border-rose-300 bg-rose-50 text-rose-700";
  if (outcome === "TIME EXIT") return "border-slate-300 bg-slate-50 text-slate-600";
  return "border-blue-300 bg-blue-50 text-blue-700";
};

function Metric({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: string;
  hint: string;
  tone: string;
}) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-3 shadow-sm sm:p-4">
      <span className="block text-[10px] font-semibold uppercase tracking-wider text-slate-400">{label}</span>
      <span className={`mt-1 block font-mono text-xl font-black sm:text-2xl ${tone}`}>{value}</span>
      <span className="mt-0.5 block text-[10px] text-slate-500">{hint}</span>
    </div>
  );
}

function HorizonToggle({
  value,
  onChange,
}: {
  value: Horizon;
  onChange: (next: Horizon) => void;
}) {
  return (
    <div
      role="group"
      aria-label="Backtest horizon"
      className="inline-flex w-full rounded-lg border border-slate-200 bg-white p-0.5 shadow-sm sm:w-auto"
    >
      {HORIZONS.map((option) => (
        <button
          key={option.id}
          type="button"
          onClick={() => onChange(option.id)}
          aria-pressed={value === option.id}
          className={`flex-1 whitespace-nowrap rounded-md px-3 py-1.5 text-[11px] font-semibold transition-colors sm:flex-none ${
            value === option.id
              ? "bg-slate-900 text-white"
              : "text-slate-600 hover:bg-slate-50"
          }`}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

function StrategyToggle({
  value,
  onChange,
}: {
  value: Strategy;
  onChange: (next: Strategy) => void;
}) {
  return (
    <div
      role="group"
      aria-label="Backtest strategy"
      className="inline-flex w-full rounded-lg border border-slate-200 bg-white p-0.5 shadow-sm sm:w-auto"
    >
      {STRATEGIES.map((option) => (
        <button
          key={option.id}
          type="button"
          onClick={() => onChange(option.id)}
          aria-pressed={value === option.id}
          className={`flex-1 whitespace-nowrap rounded-md px-3 py-1.5 text-[11px] font-semibold transition-colors sm:flex-none ${
            value === option.id
              ? "bg-amber-600 text-white"
              : "text-slate-600 hover:bg-slate-50"
          }`}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

function EquityChart({
  points,
  baseline,
  positive,
}: {
  points: CurvePoint[];
  baseline: number;
  positive: boolean;
}) {
  const W = 1000;
  const H = 260;
  const values = points.map((point) => point.equity);
  const lo = Math.min(...values, baseline);
  const hi = Math.max(...values, baseline);
  const span = hi - lo || 1;
  const x = (index: number) => (index / Math.max(points.length - 1, 1)) * W;
  const y = (value: number) => H - ((value - lo) / span) * H;
  const line = points
    .map((point, index) => `${index === 0 ? "M" : "L"}${x(index).toFixed(1)} ${y(point.equity).toFixed(1)}`)
    .join(" ");
  const area = `${line} L${W} ${H} L0 ${H} Z`;
  const stroke = positive ? "#059669" : "#e11d48";
  const fill = positive ? "#10b981" : "#f43f5e";
  const first = points[0];
  const last = points[points.length - 1];

  return (
    <div className="relative h-52 w-full sm:h-64">
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="absolute inset-0 h-full w-full" role="img" aria-label="Strategy equity curve">
        <defs>
          <linearGradient id="backtestEquityFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={fill} stopOpacity="0.22" />
            <stop offset="100%" stopColor={fill} stopOpacity="0.02" />
          </linearGradient>
        </defs>
        {[0.25, 0.5, 0.75].map((fraction) => (
          <line
            key={fraction}
            x1="0"
            y1={H * fraction}
            x2={W}
            y2={H * fraction}
            stroke="#e2e8f0"
            strokeWidth="1"
            vectorEffect="non-scaling-stroke"
          />
        ))}
        <line
          x1="0"
          y1={y(baseline)}
          x2={W}
          y2={y(baseline)}
          stroke="#94a3b8"
          strokeDasharray="4 4"
          strokeWidth="1"
          vectorEffect="non-scaling-stroke"
        />
        <path d={area} fill="url(#backtestEquityFill)" />
        <path
          d={line}
          fill="none"
          stroke={stroke}
          strokeWidth="2"
          strokeLinejoin="round"
          strokeLinecap="round"
          vectorEffect="non-scaling-stroke"
        />
      </svg>
      <span className="pointer-events-none absolute left-0 top-0 rounded bg-white/90 px-1.5 py-0.5 font-mono text-[10px] font-bold text-slate-700">
        {money(Math.max(...values))}
      </span>
      <span className="pointer-events-none absolute bottom-0 left-0 rounded bg-white/90 px-1.5 py-0.5 font-mono text-[10px] text-slate-500">
        {money(Math.min(...values))}
      </span>
      <span className="pointer-events-none absolute right-0 top-0 rounded bg-white/90 px-1.5 py-0.5 font-mono text-[10px] font-bold text-slate-900">
        PKR {money(last?.equity)}
      </span>
      <div className="pointer-events-none absolute inset-x-0 -bottom-5 flex justify-between font-mono text-[10px] text-slate-400">
        <span>{first?.date}</span>
        <span>{last?.date}</span>
      </div>
    </div>
  );
}

function CycleTable({ rows }: { rows: YearRow[] }) {
  return (
    <div className="overflow-x-auto overscroll-x-contain [-webkit-overflow-scrolling:touch]">
      <table className="w-full min-w-[380px] text-left font-mono text-xs">
        <thead className="border-b border-slate-200 text-[10px] uppercase tracking-wide text-slate-500">
          <tr>
            <th className="py-2 pr-3 font-semibold">Year</th>
            <th className="px-3 py-2 text-right font-semibold">Return</th>
            <th className="px-3 py-2 text-right font-semibold">Signals</th>
            <th className="py-2 pl-3 text-right font-semibold">Max DD</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map((row) => (
            <tr key={row.year}>
              <td className="py-2 pr-3 font-semibold text-slate-900">{row.year}</td>
              <td className={`px-3 py-2 text-right font-bold ${row.returnPct >= 0 ? "text-emerald-600" : "text-rose-600"}`}>
                {signed(row.returnPct)}
              </td>
              <td className="px-3 py-2 text-right text-slate-600">{row.signals}</td>
              <td className="py-2 pl-3 text-right text-rose-600">-{row.maxDrawdownPct.toFixed(1)}%</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DrawdownList({ episodes }: { episodes: DrawdownEpisode[] }) {
  return (
    <ul className="divide-y divide-slate-100">
      {episodes.map((episode) => (
        <li key={`${episode.peakDate}-${episode.troughDate}`} className="py-2 first:pt-0 last:pb-0">
          <div className="flex items-baseline justify-between gap-3">
            <span className="font-mono text-sm font-bold text-rose-600">{episode.depthPct.toFixed(1)}%</span>
            <span className="font-mono text-[10px] text-slate-500">
              {episode.peakDate} → {episode.troughDate}
            </span>
          </div>
          <p className="mt-0.5 text-[10px] text-slate-500">
            {episode.recoveryDate
              ? `Recovered ${episode.recoveryDate}${episode.sessions ? ` · ${episode.sessions} sessions underwater` : ""}`
              : "Still underwater at the end of the tape"}
          </p>
        </li>
      ))}
    </ul>
  );
}

// ---------------------------------------------------------------------------
// Stress-test inspector (walk-forward windows + regime switching)
// ---------------------------------------------------------------------------

function WindowTable({ windows }: { windows: Array<StressTestWindow> }) {
  return (
    <div className="overflow-x-auto overscroll-x-contain [-webkit-overflow-scrolling:touch]">
      <table className="w-full min-w-[480px] text-left font-mono text-xs">
        <thead className="border-b border-slate-200 text-[10px] uppercase tracking-wide text-slate-500">
          <tr>
            <th className="py-2 pr-2 font-semibold">Window</th>
            <th className="px-2 py-2 text-right font-semibold">OOS Sessions</th>
            <th className="px-2 py-2 text-right font-semibold">Sweep Win Rate</th>
            <th className="px-2 py-2 text-right font-semibold">Sweep DD</th>
            <th className="px-2 py-2 text-right font-semibold">Momentum Win Rate</th>
            <th className="px-2 py-2 text-right font-semibold">Momentum DD</th>
            <th className="px-2 py-2 text-right font-semibold">stat-arb Pairs</th>
            <th className="px-2 py-2 text-right font-semibold">Regime</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {(windows ?? []).map((w) => (
            <tr key={w.window}>
              <td className="py-2 pr-2 font-semibold text-slate-900">{w.window}</td>
              <td className="px-2 py-2 text-right text-slate-600">{w.oosSessions}</td>
              <td className={`px-2 py-2 text-right font-bold ${w.sweep.winRatePct >= 45 ? "text-emerald-600" : w.sweep.winRatePct >= 35 ? "text-slate-900" : "text-rose-600"}`}>
                {w.sweep.winRatePct.toFixed(1)}%
              </td>
              <td className="px-2 py-2 text-right text-rose-600">-{w.sweep.maxDrawdownPct.toFixed(1)}%</td>
              <td className={`px-2 py-2 text-right font-bold ${w.momentum.winRatePct >= 30 ? "text-emerald-600" : w.momentum.winRatePct >= 22 ? "text-slate-900" : "text-rose-600"}`}>
                {w.momentum.winRatePct.toFixed(1)}%
              </td>
              <td className="px-2 py-2 text-right text-rose-600">-{w.momentum.maxDrawdownPct.toFixed(1)}%</td>
              <td className="px-2 py-2 text-right text-slate-600">{w.statArb.pairs}</td>
              <td className="px-2 py-2 text-right">
                <span className={`inline-block rounded-full border px-2 py-0.5 text-[10px] font-bold ${w.regime === "FAVORABLE" ? "border-emerald-300 bg-emerald-50 text-emerald-700" : w.regime === "STRESS" ? "border-rose-300 bg-rose-50 text-rose-700" : w.regime === "UNFAVORABLE" ? "border-rose-300 bg-rose-50 text-rose-700" : "border-slate-300 bg-slate-50 text-slate-600"}`}>
                  {w.regime}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RegimeSwitchingChart({ rows }: { rows: Array<{ regime: string; windows: number }> }) {
  const total = rows.reduce((s, r) => s + r.windows, 0) || 1;
  const colorFor = (regime: string) => {
    if (regime === "FAVORABLE") return "#059669";
    if (regime === "STRESS") return "#e11d48";
    if (regime === "UNFAVORABLE") return "#f59e0b";
    return "#64748b";
  };
  return (
    <div className="flex items-center gap-3">
      {rows.map((row) => (
        <div key={row.regime} className="flex-1 flex flex-col items-center">
          <span className="text-[10px] font-semibold text-slate-500">{row.windows}</span>
          <div
            className="mt-1 h-6 rounded-md"
            style={{ width: `${(row.windows / total) * 100}%`, backgroundColor: colorFor(row.regime) }}
          />
          <span className="mt-1 text-[10px] font-semibold text-slate-700">{row.regime}</span>
        </div>
      ))}
    </div>
  );
}

function StressTestView({ data }: { data: StressTestPayload }) {
  const agg = data.aggregates;
  const meta = data.meta;
  const windows: StressTestWindow[] = data.windows ?? [];
  const isSweep = data.sessionRange?.tickers ? true : true;

  return (
    <>
      <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-3 xl:grid-cols-6">
        <Metric
          label="Windows"
          value={String(meta?.windowCount ?? windows.length)}
          hint="walk-forward out-of-sample windows"
          tone="text-slate-900"
        />
        <Metric
          label="Sweep Win Rate"
          value={`${agg?.sweep.winRatePct.toFixed(1)}%`}
          hint={`${agg?.sweep.wins}W / ${agg?.sweep.losses}L · avg ${agg?.sweep.avgWinRatePct.toFixed(1)}%`}
          tone={agg && agg.sweep.winRatePct >= 45 ? "text-emerald-600" : "text-rose-600"}
        />
        <Metric
          label="Sweep Worst DD"
          value={`-${agg?.sweep.worstWindowDrawdownPct.toFixed(1)}%`}
          hint={`${agg?.sweep.windowsAbove10DD} window(s) > 10% DD`}
          tone="text-rose-600"
        />
        <Metric
          label="Momentum Win Rate"
          value={`${agg?.momentum.winRatePct.toFixed(1)}%`}
          hint={`${agg?.momentum.wins}W / ${agg?.momentum.losses}L · avg ${agg?.momentum.avgWinRatePct.toFixed(1)}%`}
          tone={agg && agg.momentum.winRatePct >= 30 ? "text-emerald-600" : "text-rose-600"}
        />
        <Metric
          label="Momentum Worst DD"
          value={`-${agg?.momentum.worstWindowDrawdownPct.toFixed(1)}%`}
          hint={`${agg?.momentum.windowsAbove10DD} window(s) > 10% DD`}
          tone="text-rose-600"
        />
        <Metric
          label="stat-arb Pairs"
          value={String(windows.reduce((s, w) => s + w.statArb.pairs, 0))}
          hint={`${windows.reduce((s, w) => s + w.statArb.signals, 0)} spread signals across all windows`}
          tone="text-slate-900"
        />
      </div>

      <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="text-base font-bold text-slate-900">Walk-Forward Windows</h2>
            <p className="text-[11px] text-slate-500">
              Each window is fit in-sample, then evaluated on the next OOS tail; regime is labelled from the window's drawdown + win-rate profile.
            </p>
          </div>
          <div className="flex flex-wrap gap-3 font-mono text-[11px]">
            <span className="text-slate-500">
              Sizing <span className="text-slate-700">{meta?.sizingMode ?? "atrp"}</span>
            </span>
            <span className="text-slate-500">
              Kelly <span className="text-slate-700">{meta?.withKelly ? "on" : "off"}</span>
            </span>
            <span className="text-slate-500">
              VaR <span className="text-slate-700">{meta?.withVar ? "on" : "off"}</span>
            </span>
            <span className="text-slate-500">
              stat-arb <span className="text-slate-700">{meta?.statArbEnabled ? "on" : "off"}</span>
            </span>
          </div>
        </div>

        {windows.length > 0 ? (
          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <div>
              <h3 className="text-sm font-bold text-slate-700 mb-2">Per-Window Detail</h3>
              <WindowTable windows={windows} />
            </div>

            <div>
              <h3 className="text-sm font-bold text-slate-700 mb-2">Regime Switching</h3>
              <RegimeSwitchingChart rows={agg?.regimeSwitching ?? []} />
              <ul className="mt-3 divide-y divide-slate-100">
                {(agg?.regimeSwitching ?? []).map((row) => (
                  <li key={row.regime} className="py-1.5 text-xs text-slate-600">
                    <span className="font-semibold">{row.regime}</span>: {row.windows} window{row.windows === 1 ? "" : "s"}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        ) : (
          <p className="py-6 text-center text-xs text-slate-400">No walk-forward windows yet.</p>
        )}
      </section>

      {data.equityCurve && data.equityCurve.length > 1 ? (
        <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <h2 className="text-base font-bold text-slate-900">Representative Equity Curve</h2>
              <p className="text-[11px] text-slate-500">
                First walk-forward window's book, as a representative shape of the desk through the tape.
              </p>
            </div>
          </div>
          <div className="mt-4 pb-6">
            <EquityChart points={data.equityCurve} baseline={100000} positive={(data.aggregates?.sweep.totalSignals ?? 0) > 0} />
          </div>
        </section>
      ) : null}
    </>
  );
}

export default function BacktestPage() {
  const [horizon, setHorizon] = useState<Horizon>("1Y");
  const [strategy, setStrategy] = useState<Strategy>("sweep");
  const [payloads, setPayloads] = useState<Record<string, Payload | null>>({});
  const [loaded, setLoaded] = useState(false);
  const [query, setQuery] = useState("");
  const [outcome, setOutcome] = useState<"ALL" | "WINS" | "LOSSES" | "OPEN">("ALL");

  useEffect(() => {
    const strategyConfig = STRATEGIES.find((s) => s.id === strategy);
    if (!strategyConfig) return;

    Promise.allSettled(
      HORIZONS.map((option) =>
        fetch(strategyConfig.files[option.id]).then((res) =>
          res.ok ? (res.json() as Promise<Payload>) : null,
        ),
      ),
    )
      .then((results) => {
        const byHorizon: Record<string, Payload | null> = {};
        results.forEach((result, index) => {
          byHorizon[HORIZONS[index].id] =
            result.status === "fulfilled" ? result.value : null;
          if (result.status === "rejected") {
            console.error(
              `Error loading ${strategyConfig.label} (${HORIZONS[index].label}):`,
              result.reason,
            );
          }
        });
        setPayloads(byHorizon);
      })
      .finally(() => setLoaded(true));
  }, [strategy]);

  // Filters are horizon-specific; a stale search would silently hide new rows.
  useEffect(() => {
    setQuery("");
    setOutcome("ALL");
  }, [horizon]);

  const data = payloads[horizon];
  const isStress = data && ('meta' in data);
  const nonStressData = (!isStress && data) ? data as SweepPayload | MomentumPayload : null;
  const metrics = nonStressData?.metrics;
  const curve = data?.equityCurve ?? [];
  const trades = nonStressData?.trades ?? [];
  const macro = horizon === "5Y";
  const isMomentum = strategy === "momentum";
  const strategyData = nonStressData?.strategy;
  const strategyTopN = isMomentum ? (strategyData as MomentumPayload["strategy"] | undefined)?.topN : undefined;
  const strategyTrendMaDays = (!isMomentum) ? (strategyData as SweepPayload["strategy"] | undefined)?.trendMaDays : undefined;
  const strategyMinRvol = (!isMomentum) ? (strategyData as SweepPayload["strategy"] | undefined)?.minRvol : undefined;
  const strategyMinVolZ = (!isMomentum) ? (strategyData as SweepPayload["strategy"] | undefined)?.minVolZ : undefined;
  const strategyAtrStopMult = (!isMomentum) ? (strategyData as SweepPayload["strategy"] | undefined)?.atrStopMult : undefined;
  const strategyTargetPct = (!isMomentum) ? (strategyData as SweepPayload["strategy"] | undefined)?.targetPct : undefined;
  const strategyHoldHorizonSessions = (!isMomentum) ? (strategyData as SweepPayload["strategy"] | undefined)?.holdHorizonSessions : undefined;
  const strategyPositionPct = (!isMomentum) ? (strategyData as SweepPayload["strategy"] | undefined)?.positionPct : undefined;

  const rows = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return (trades as Trade[]).filter((trade) => {
      if (outcome === "WINS" && !(trade.outcome !== "IN PLAY" && trade.pnlPct > 0)) return false;
      if (outcome === "LOSSES" && !(trade.outcome !== "IN PLAY" && trade.pnlPct <= 0)) return false;
      if (outcome === "OPEN" && trade.outcome !== "IN PLAY") return false;
      if (!needle) return true;
      return [trade.ticker, trade.signalDate, trade.outcome, trade.reason].some((field) =>
        (field ?? "").toLowerCase().includes(needle),
      );
    });
  }, [trades, outcome, query]);

  const isFiltered = outcome !== "ALL" || query.trim().length > 0;
  const positive = (metrics?.totalReturnPct ?? 0) >= 0;
  const profitFactor =
    metrics?.profitFactor === null || metrics?.profitFactor === undefined
      ? metrics && metrics.wins > 0
        ? "∞"
        : "—"
      : metrics.profitFactor.toFixed(2);
  const years = data?.horizonYears ?? data?.sessionRange?.years ?? 1;
  const baseline = metrics?.startingCapital ?? curve[0]?.equity ?? 100000;

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div className="min-w-0">
          <h1 className="text-xl font-bold tracking-tight text-slate-900">
            {horizon === "1Y" ? "1Y Backtest Lab" : horizon === "5Y" ? "5Y Macro Stress Test" : "15Y Meta-Brain Stress Test"}
          </h1>
          <p className="text-xs text-slate-500">
            {(horizon === "15Y" && data && ("meta" in data) && (data as StressTestPayload).meta?.name)
              ? (data as StressTestPayload).meta!.name
              : (data && ("strategy" in data) ? (data as SweepPayload | MomentumPayload).strategy?.name : "Strategy")}
            {" "}replayed session by session
            {data?.sessionRange?.from && data?.sessionRange?.to
              ? ` — ${data.sessionRange.from} to ${data.sessionRange.to} (${data.sessionRange.sessions} sessions${
                  data.sessionRange.tickers ? ` · ${data.sessionRange.tickers} names` : ""
                }).`
              : "."}
          </p>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
          <StrategyToggle value={strategy} onChange={setStrategy} />
          <HorizonToggle value={horizon} onChange={setHorizon} />
        </div>
      </div>

      <div className="flex flex-wrap gap-1.5">
        {isMomentum ? (
          [
            `Top ${strategyTopN ?? 10} momentum leaders`,
            `3M + 6M ROC composite score`,
            `Monthly rebalance (month-end)`,
            `7% hard stop · 50d SMA break exit`,
            `Equal-weight basket`,
          ].map((chip) => (
            <span
              key={chip}
              className="rounded border border-slate-200 bg-white px-2 py-1 text-[10px] font-semibold text-slate-600"
            >
              {chip}
            </span>
          ))
        ) : (
          [
            `Above SMA${strategyTrendMaDays ?? 50}`,
            `RVOL ≥ ${strategyMinRvol ?? 1.5}x · Z ≥ ${strategyMinVolZ ?? 1}`,
            `ATR × ${strategyAtrStopMult ?? 2} stop`,
            `Target +${strategyTargetPct ?? 12}%`,
            `${strategyHoldHorizonSessions ?? 30}s max hold`,
          ].map((chip) => (
            <span
              key={chip}
              className="rounded border border-slate-200 bg-white px-2 py-1 text-[10px] font-semibold text-slate-600"
            >
              {chip}
            </span>
          ))
        )}
      </div>

      {!loaded && (
        <div className="rounded-xl border border-slate-200 bg-white p-6 text-center text-xs text-slate-400 shadow-sm">
          Replaying the stored tape…
        </div>
      )}

      {loaded && !data && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
          {horizon === "15Y" ? (
            <>
              No 15-year Meta-Brain stress test yet — run{" "}
              <code className="font-mono">python backend/src/quant/stress_test.py</code>.
            </>
          ) : isMomentum ? (
            <>
              No momentum rotation report yet — run{" "}
              <code className="font-mono">python backend/src/quant/momentum_rotation.py</code>.
            </>
          ) : macro ? (
            <>
              No 5-year report yet — run{" "}
              <code className="font-mono">python backend/src/quant/backtest.py --years 5</code>.
            </>
          ) : (
            <>
              No backtest file yet — run <code className="font-mono">python backend/src/quant/backtest.py</code>.
            </>
          )}
        </div>
      )}

      {horizon === "15Y" && data && (
        <StressTestView data={data as StressTestPayload} />
      )}

      {metrics && horizon !== "15Y" && (
        <>
          <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-3 xl:grid-cols-6">
            <Metric
              label="Win Rate"
              value={`${metrics.winRatePct.toFixed(1)}%`}
              hint={`${metrics.wins}W / ${metrics.losses}L resolved`}
              tone="text-emerald-600"
            />
            <Metric
              label="Total Return"
              value={signed(metrics.totalReturnPct)}
              hint={`PKR ${money(metrics.endingEquity)} book`}
              tone={positive ? "text-emerald-600" : "text-rose-600"}
            />
            <Metric
              label="CAGR"
              value={`${(metrics.cagrPct ?? 0).toFixed(2)}%`}
              hint={`${years.toFixed(1)}y annualised`}
              tone={(metrics.cagrPct ?? 0) >= 0 ? "text-emerald-600" : "text-rose-600"}
            />
            <Metric
              label="Profit Factor"
              value={profitFactor}
              hint={`Gross +${metrics.grossProfitPct.toFixed(1)}% vs -${metrics.grossLossPct.toFixed(1)}%`}
              tone="text-slate-900"
            />
            <Metric
              label="Max Drawdown"
              value={`-${metrics.maxDrawdownPct.toFixed(1)}%`}
              hint={
                macro && !isStress && data && ('maxDrawdown' in data) ? `Trough ${(data as SweepPayload | MomentumPayload).maxDrawdown?.troughDate ?? ""}`
                  : "Peak-to-trough on equity"
              }
              tone="text-rose-600"
            />
            <Metric
              label="Signals"
              value={String(metrics.totalSignals)}
              hint={`${!isStress && ('tradesPerYear' in metrics) ? metrics.tradesPerYear ?? 0 : 0}/yr · ${metrics.avgBarsHeld.toFixed(0)}d avg hold`}
              tone="text-slate-900"
            />
          </div>

          <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <h2 className="text-base font-bold text-slate-900">Equity Curve</h2>
                <p className="text-[11px] text-slate-500">
                  ${strategyPositionPct ?? 10}% of live equity per signal · dashed line is starting capital
                </p>
              </div>
              <div className="flex flex-wrap gap-3 font-mono text-[11px]">
                <span className="text-slate-500">
                  Avg/trade <span className={metrics.avgPnlPct >= 0 ? "text-emerald-600" : "text-rose-600"}>{signed(metrics.avgPnlPct)}</span>
                </span>
                <span className="text-slate-500">
                  Best <span className="text-emerald-600">{signed(metrics.bestTradePct)}</span>
                </span>
                <span className="text-slate-500">
                  Worst <span className="text-rose-600">{signed(metrics.worstTradePct)}</span>
                </span>
              </div>
            </div>
            <div className="mt-4 pb-6">
              {curve.length > 1 ? (
                <EquityChart points={curve} baseline={baseline} positive={positive} />
              ) : (
                <p className="py-10 text-center text-xs text-slate-400">Not enough sessions for a curve yet.</p>
              )}
            </div>
          </section>

          {macro && !isStress && ((data && ('yearlyReturns' in data) && (data as SweepPayload | MomentumPayload).yearlyReturns?.length) || (data && ('drawdownEpisodes' in data) && (data as SweepPayload | MomentumPayload).drawdownEpisodes?.length)) ? (
            <div className="grid gap-4 lg:grid-cols-2">
              <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5">
                <h2 className="text-base font-bold text-slate-900">Market Cycles</h2>
                <p className="mb-3 text-[11px] text-slate-500">Calendar-year return, signal count and worst drawdown</p>
                {data?.yearlyReturns?.length ? (
                  <CycleTable rows={data.yearlyReturns} />
                ) : (
                  <p className="py-6 text-center text-xs text-slate-400">No completed calendar years yet.</p>
                )}
              </section>

              <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5">
                <h2 className="text-base font-bold text-slate-900">Drawdown Episodes</h2>
                <p className="mb-3 text-[11px] text-slate-500">Peak-to-trough underwater stretches, deepest first</p>
                {data?.drawdownEpisodes?.length ? (
                  <DrawdownList episodes={data.drawdownEpisodes} />
                ) : (
                  <p className="py-6 text-center text-xs text-slate-400">No drawdown recorded.</p>
                )}
              </section>
            </div>
          ) : null}
        </>
      )}

      <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
        <div className="flex flex-col gap-2 border-b border-slate-200 p-3 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
          <div className="flex items-center gap-1.5">
            {(["ALL", "WINS", "LOSSES", "OPEN"] as const).map((tab) => (
              <button
                key={tab}
                type="button"
                onClick={() => setOutcome(tab)}
                aria-pressed={outcome === tab}
                className={`rounded-md border px-2.5 py-1.5 text-[11px] font-semibold transition-colors ${
                  outcome === tab
                    ? "border-slate-900 bg-slate-900 text-white"
                    : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
                }`}
              >
                {tab}
              </button>
            ))}
          </div>
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:gap-3">
            <div className="relative w-full sm:w-56">
              <span className="pointer-events-none absolute inset-y-0 left-3 flex items-center text-slate-400">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
                  <circle cx="11" cy="11" r="7" />
                  <path d="M20 20l-3.5-3.5" />
                </svg>
              </span>
              <input
                type="search"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search ticker, date, outcome…"
                aria-label="Search simulated trades"
                className="w-full rounded-lg border border-slate-200 bg-white py-2 pl-9 pr-3 font-sans text-xs text-slate-900 placeholder:text-slate-400 focus:border-slate-400 focus:outline-none focus:ring-1 focus:ring-slate-300"
              />
            </div>
            <div className="flex items-center gap-2 text-[11px] text-slate-500">
              <span className="font-mono font-semibold text-slate-700">
                {rows.length} {rows.length === 1 ? "trade" : "trades"}
              </span>
              {isFiltered && (
                <button
                  type="button"
                  onClick={() => {
                    setQuery("");
                    setOutcome("ALL");
                  }}
                  className="rounded border border-slate-200 px-2 py-0.5 font-semibold text-slate-600 transition-colors hover:bg-slate-50"
                >
                  Reset
                </button>
              )}
            </div>
          </div>
        </div>

        <div className="overflow-x-auto overscroll-x-contain [-webkit-overflow-scrolling:touch]">
          <table className="w-full min-w-[900px] text-left font-mono text-xs">
            <thead className="border-b border-slate-200 bg-slate-50 text-[10px] uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-3 py-3 sm:px-4">Signal</th>
                <th className="px-3 py-3 sm:px-4">Ticker</th>
                <th className="px-3 py-3 text-right sm:px-4">Entry</th>
                <th className="px-3 py-3 text-right sm:px-4">Stop</th>
                <th className="px-3 py-3 text-right sm:px-4">Target</th>
                <th className="px-3 py-3 text-right sm:px-4">Exit</th>
                <th className="px-3 py-3 text-right sm:px-4">P&L</th>
                <th className="px-3 py-3 text-center sm:px-4">Held</th>
                <th className="px-3 py-3 text-center sm:px-4">Outcome</th>
                <th className="px-3 py-3 font-sans sm:px-4">Basis</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {rows.map((trade) => {
                  const t = trade as Trade;
                  return (
                    <tr key={`${t.id}-${t.ticker}-${t.signalDate}`} className="hover:bg-slate-50">
                      <td className="whitespace-nowrap px-3 py-3 text-[11px] text-slate-500 sm:px-4">{t.signalDate}</td>
                      <td className="whitespace-nowrap px-3 py-3 text-sm font-bold text-slate-900 sm:px-4">{t.ticker}</td>
                      <td className="whitespace-nowrap px-3 py-3 text-right font-semibold text-slate-700 sm:px-4">
                        {money(t.entryPrice)}
                      </td>
                      <td className="whitespace-nowrap px-3 py-3 text-right font-semibold text-rose-600 sm:px-4">
                        {money(t.stopLoss)}
                      </td>
                      <td className="whitespace-nowrap px-3 py-3 text-right font-semibold text-emerald-600 sm:px-4">
                        {money(t.targetPrice)}
                      </td>
                      <td className="whitespace-nowrap px-3 py-3 text-right font-semibold text-slate-700 sm:px-4">
                        {money(t.exitPrice)}
                      </td>
                      <td
                        className={`whitespace-nowrap px-3 py-3 text-right font-bold sm:px-4 ${
                          t.pnlPct >= 0 ? "text-emerald-600" : "text-rose-600"
                        }`}
                      >
                        {t.pnlPct >= 0 ? "+" : ""}
                        {t.pnlPct.toFixed(1)}%
                      </td>
                      <td className="whitespace-nowrap px-3 py-3 text-center text-[11px] text-slate-500 sm:px-4">
                        {t.barsHeld}d
                      </td>
                      <td className="whitespace-nowrap px-3 py-3 text-center sm:px-4">
                        <span className={`inline-block rounded-full border px-2.5 py-1 text-[10px] font-bold ${outcomeTone(t.outcome)}`}>
                          {t.outcome}
                        </span>
                      </td>
                      <td className="max-w-xs truncate px-3 py-3 font-sans text-[11px] text-slate-500 sm:px-4" title={t.reason}>
                        {t.reason}
                      </td>
                    </tr>
                  );
                })}
              {loaded && rows.length === 0 && (
                <tr>
                  <td colSpan={10} className="px-4 py-8 text-center font-sans text-xs text-slate-400">
                    {isFiltered
                      ? "No simulated trades match this filter."
                      : "No simulated trades yet — the backtest fills this once the store holds history."}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <p className="border-t border-slate-200 px-3 py-2 text-center text-[10px] text-slate-400 lg:hidden">
          Swipe the table sideways to see every column.
        </p>
      </section>
    </div>
  );
}
