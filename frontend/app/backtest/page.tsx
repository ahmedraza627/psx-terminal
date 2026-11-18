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

type Payload = {
  generatedAt?: string;
  strategy?: {
    name: string;
    lookbackDays: number;
    targetPct: number;
    maxStopPct: number;
    holdHorizonSessions: number;
    positionPct: number;
  };
  sessionRange?: { from: string | null; to: string | null; sessions: number };
  metrics?: {
    totalSignals: number;
    wins: number;
    losses: number;
    inPlay: number;
    winRatePct: number;
    profitFactor: number | null;
    maxDrawdownPct: number;
    totalReturnPct: number;
    avgPnlPct: number;
    avgBarsHeld: number;
    bestTradePct: number;
    worstTradePct: number;
    grossProfitPct: number;
    grossLossPct: number;
    endingEquity: number;
  };
  equityCurve?: CurvePoint[];
  trades?: Trade[];
};

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

export default function BacktestPage() {
  const [data, setData] = useState<Payload | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [query, setQuery] = useState("");
  const [outcome, setOutcome] = useState<"ALL" | "WINS" | "LOSSES" | "OPEN">("ALL");

  useEffect(() => {
    fetch("/data/backtest_metrics.json")
      .then((res) => res.json())
      .then((payload: Payload) => setData(payload))
      .catch((err) => console.error("Error loading backtest:", err))
      .finally(() => setLoaded(true));
  }, []);

  const metrics = data?.metrics;
  const curve = data?.equityCurve ?? [];
  const trades = data?.trades ?? [];

  const rows = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return trades.filter((trade) => {
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

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div className="min-w-0">
          <h1 className="text-xl font-bold tracking-tight text-slate-900">1Y Backtest Lab</h1>
          <p className="text-xs text-slate-500">
            {data?.strategy?.name ?? "Liquidity sweep"} replayed session by session against the stored tape
            {data?.sessionRange?.from && data?.sessionRange?.to
              ? ` — ${data.sessionRange.from} to ${data.sessionRange.to} (${data.sessionRange.sessions} sessions).`
              : "."}
          </p>
        </div>
        <div className="flex flex-wrap gap-1.5">
          <span className="rounded border border-slate-200 bg-white px-2 py-1 text-[10px] font-semibold text-slate-600">
            Target +{data?.strategy?.targetPct ?? 12}%
          </span>
          <span className="rounded border border-slate-200 bg-white px-2 py-1 text-[10px] font-semibold text-slate-600">
            Stop ≤ {data?.strategy?.maxStopPct ?? 7}%
          </span>
          <span className="rounded border border-slate-200 bg-white px-2 py-1 text-[10px] font-semibold text-slate-600">
            {data?.strategy?.holdHorizonSessions ?? 15}s max hold
          </span>
        </div>
      </div>

      {!loaded && (
        <div className="rounded-xl border border-slate-200 bg-white p-6 text-center text-xs text-slate-400 shadow-sm">
          Replaying the stored year…
        </div>
      )}

      {loaded && !data && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
          No backtest file yet — run <code className="font-mono">python backend/src/quant/backtest.py</code>.
        </div>
      )}

      {metrics && (
        <>
          <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">
            <Metric
              label="1Y Win Rate"
              value={`${metrics.winRatePct.toFixed(1)}%`}
              hint={`${metrics.wins}W / ${metrics.losses}L resolved`}
              tone="text-emerald-600"
            />
            <Metric
              label="Total P&L"
              value={signed(metrics.totalReturnPct)}
              hint={`PKR ${money(metrics.endingEquity)} book`}
              tone={positive ? "text-emerald-600" : "text-rose-600"}
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
              hint="Peak-to-trough on equity"
              tone="text-rose-600"
            />
          </div>

          <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <h2 className="text-base font-bold text-slate-900">Equity Curve</h2>
                <p className="text-[11px] text-slate-500">
                  ${`${data?.strategy?.positionPct ?? 10}%`} of live equity per signal · dashed line is starting capital
                </p>
              </div>
              <div className="flex gap-3 font-mono text-[11px]">
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
                <EquityChart
                  points={curve}
                  baseline={curve[0]?.equity ?? 100000}
                  positive={positive}
                />
              ) : (
                <p className="py-10 text-center text-xs text-slate-400">Not enough sessions for a curve yet.</p>
              )}
            </div>
          </section>
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
              {rows.map((trade) => (
                <tr key={`${trade.id}-${trade.ticker}-${trade.signalDate}`} className="hover:bg-slate-50">
                  <td className="whitespace-nowrap px-3 py-3 text-[11px] text-slate-500 sm:px-4">{trade.signalDate}</td>
                  <td className="whitespace-nowrap px-3 py-3 text-sm font-bold text-slate-900 sm:px-4">{trade.ticker}</td>
                  <td className="whitespace-nowrap px-3 py-3 text-right font-semibold text-slate-700 sm:px-4">
                    {money(trade.entryPrice)}
                  </td>
                  <td className="whitespace-nowrap px-3 py-3 text-right font-semibold text-rose-600 sm:px-4">
                    {money(trade.stopLoss)}
                  </td>
                  <td className="whitespace-nowrap px-3 py-3 text-right font-semibold text-emerald-600 sm:px-4">
                    {money(trade.targetPrice)}
                  </td>
                  <td className="whitespace-nowrap px-3 py-3 text-right font-semibold text-slate-700 sm:px-4">
                    {money(trade.exitPrice)}
                  </td>
                  <td
                    className={`whitespace-nowrap px-3 py-3 text-right font-bold sm:px-4 ${
                      trade.pnlPct >= 0 ? "text-emerald-600" : "text-rose-600"
                    }`}
                  >
                    {trade.pnlPct >= 0 ? "+" : ""}
                    {trade.pnlPct.toFixed(1)}%
                  </td>
                  <td className="whitespace-nowrap px-3 py-3 text-center text-[11px] text-slate-500 sm:px-4">
                    {trade.barsHeld}d
                  </td>
                  <td className="whitespace-nowrap px-3 py-3 text-center sm:px-4">
                    <span className={`inline-block rounded-full border px-2.5 py-1 text-[10px] font-bold ${outcomeTone(trade.outcome)}`}>
                      {trade.outcome}
                    </span>
                  </td>
                  <td className="max-w-xs truncate px-3 py-3 font-sans text-[11px] text-slate-500 sm:px-4" title={trade.reason}>
                    {trade.reason}
                  </td>
                </tr>
              ))}
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
