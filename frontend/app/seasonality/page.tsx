"use client";

import { useEffect, useMemo, useState } from "react";

/* ------------------------------------------------------------------ types */

type WindowStats = {
  samples: number;
  winRatePct: number;
  avgPct: number;
  medianPct: number;
  p25Pct: number;
  p75Pct: number;
  p90Pct: number;
  bestPct: number;
  worstPct: number;
  stdDevPct: number;
};

type CalendarCell = {
  month: number;
  label: string;
  samples: number;
  winRatePct: number;
  avgForward60Pct: number;
  avgForward90Pct: number;
  isPeak: boolean;
  isAccumulation: boolean;
};

type Position = {
  rangePositionPct: number;
  drawdownFromHighPct: number;
  offLowPct: number;
  rangeSpanPct?: number;
  momentum60Pct: number;
  lookbackSessions: number;
};

type MonthStat = {
  label: string;
  winRatePct: number;
  avgForward60Pct: number;
  medianForward60Pct: number;
  avgForward90Pct: number;
  p25Forward60Pct: number;
  p75Forward60Pct: number;
  bestForward60Pct: number;
  worstForward60Pct: number;
  samples: number;
  monthReturnAvgPct: number;
};

type TickerRecord = {
  ticker: string;
  sector: string;
  status: string;
  phaseNote: string;
  lastDate: string;
  lastClose: number;
  historyBars: number;
  yearsCovered: number;
  peakMonths: string[];
  accumulationMonths: string[];
  monthsUntilWindow: number;
  accumulationWindowStats: { forward60: WindowStats; forward90: WindowStats };
  peakWindowStats: { forward60: WindowStats; forward90?: WindowStats };
  bestMonth: string | null;
  bestMonthScore: number | null;
  position: Position;
  calendar: CalendarCell[];
  statsByMonth: Record<string, MonthStat>;
};

type SectorRow = {
  sector: string;
  status: string;
  members: number;
  activeCount: number;
  watchCount: number;
  offSeasonCount: number;
  peakMonths: string[];
  accumulationMonths: string[];
  rationale: string;
  bestMonth: string | null;
  bestMonthAvgForward60Pct: number;
  accumulationWindow: { forward60: WindowStats; forward90: WindowStats };
  peakWindow: { forward60: WindowStats };
  calendar: CalendarCell[];
  tickers: TickerRecord[];
};

type SeasonalityPayload = {
  generatedAt: string;
  meta: {
    name: string;
    currentMonth: number;
    currentMonthLabel: string;
    forwardWindows: number[];
    minHistoryBars: number;
    positionFilter: Record<string, number>;
    statusDefinitions: Record<string, string>;
    method: string;
  };
  sessionRange: { from: string | null; to: string | null; tickers: number; sectors: number };
  summary: {
    tickersAnalyzed: number;
    activeWindows: number;
    sectorsActive: number;
    sectorsWatching: number;
    sectorsOffSeason: number;
  };
  activeWindows: Array<{
    ticker: string;
    sector: string;
    status: string;
    monthsUntilWindow: number;
    rangePositionPct: number;
    drawdownFromHighPct: number;
    winRate60Pct: number;
    avgForward60Pct: number;
    avgForward90Pct: number;
    lastClose: number;
    lastDate: string;
  }>;
  sectors: SectorRow[];
};

/* ---------------------------------------------------------------- helpers */

const STATUS_ACTIVE = "ACCUMULATION WINDOW ACTIVE";
const STATUS_WATCH = "WATCH";
const STATUS_OFF = "OFF-SEASON";
const STATUSES = [STATUS_ACTIVE, STATUS_WATCH, STATUS_OFF] as const;

const statusTone = (status: string) => {
  if (status === STATUS_ACTIVE) return "border-emerald-400/40 bg-emerald-400/15 text-emerald-300";
  if (status === STATUS_WATCH) return "border-amber-400/40 bg-amber-400/15 text-amber-300";
  return "border-slate-600/60 bg-slate-700/30 text-slate-400";
};

const shortStatus = (status: string) => {
  if (status === STATUS_ACTIVE) return "ACCUMULATE";
  if (status === STATUS_WATCH) return "WATCH";
  return "OFF-SEASON";
};

const signed = (value: number, digits = 2) =>
  `${value >= 0 ? "+" : ""}${value.toFixed(digits)}%`;

const heat = (value: number, samples: number) => {
  if (samples === 0) return "bg-slate-900/60 text-slate-600";
  if (value >= 6) return "bg-emerald-500/35 text-emerald-100";
  if (value >= 3) return "bg-emerald-500/20 text-emerald-200";
  if (value >= 1) return "bg-emerald-500/10 text-emerald-300";
  if (value > -1) return "bg-slate-800/70 text-slate-300";
  if (value > -3) return "bg-rose-500/15 text-rose-300";
  return "bg-rose-500/25 text-rose-200";
};

function StatCard({ label, value, hint, tone }: { label: string; value: string; hint: string; tone: string }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-3">
      <span className="block text-[10px] font-semibold uppercase tracking-wider text-slate-500">{label}</span>
      <span className={`mt-1 block font-mono text-xl font-black ${tone}`}>{value}</span>
      <span className="mt-0.5 block text-[10px] text-slate-500">{hint}</span>
    </div>
  );
}

/* ------------------------------------------------------------------- page */

export default function SeasonalityPage() {
  const [data, setData] = useState<SeasonalityPayload | null>(null);
  const [error, setError] = useState(false);
  const [statusFilter, setStatusFilter] = useState<string>("ALL");
  const [sectorFilter, setSectorFilter] = useState<string>("ALL");
  const [query, setQuery] = useState("");

  useEffect(() => {
    fetch("/data/seasonality_matrix.json")
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`HTTP ${res.status}`))))
      .then((payload: SeasonalityPayload) => setData(payload))
      .catch((err) => {
        console.error("[Seasonality] matrix load failed:", err);
        setError(true);
      });
  }, []);

  const tickers = useMemo(() => {
    if (!data) return [] as TickerRecord[];
    const needle = query.trim().toUpperCase();
    return data.sectors.flatMap((sector) =>
      sector.tickers.filter((t) => {
        if (statusFilter !== "ALL" && t.status !== statusFilter) return false;
        if (sectorFilter !== "ALL" && t.sector !== sectorFilter) return false;
        if (needle && !t.ticker.includes(needle) && !t.sector.toUpperCase().includes(needle)) return false;
        return true;
      }),
    );
  }, [data, statusFilter, sectorFilter, query]);

  if (error) {
    return (
      <div className="rounded-2xl border border-amber-500/40 bg-slate-950 p-6 text-sm text-amber-300">
        No seasonality matrix found. Run{" "}
        <code className="rounded bg-slate-900 px-1.5 py-0.5 font-mono text-xs text-amber-200">
          python backend/src/quant/seasonality.py
        </code>{" "}
        to build <span className="font-mono text-xs">frontend/public/data/seasonality_matrix.json</span>.
      </div>
    );
  }

  if (!data) {
    return (
      <div className="rounded-2xl border border-slate-800 bg-slate-950 p-8 text-center font-mono text-xs text-slate-500">
        Loading sector seasonality matrix…
      </div>
    );
  }

  const { summary, meta } = data;
  const sectorOptions = data.sectors.map((s) => s.sector);

  return (
    <div className="space-y-5 rounded-2xl border border-slate-800 bg-slate-950 p-4 text-slate-100 sm:p-6">
      {/* header */}
      <div className="flex flex-col gap-3 border-b border-slate-800 pb-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="font-mono text-lg font-bold tracking-tight text-slate-50 sm:text-xl">
              SECTOR SEASONALITY &amp; CYCLICAL ALPHA MATRIX
            </h1>
            <span className="rounded border border-emerald-400/40 bg-emerald-400/10 px-2 py-0.5 text-[10px] font-mono font-bold text-emerald-300">
              {meta.currentMonthLabel.toUpperCase()} · PRE-SEASON SCAN
            </span>
          </div>
          <p className="mt-1 max-w-3xl text-[11px] text-slate-400">
            Forward 60/90-session return distributions from every month-of-year across{" "}
            {data.sessionRange.from ?? "—"} → {data.sessionRange.to ?? "—"} · position filter keeps
            accumulation calls to names still in the lower half of their 3-year range.
          </p>
        </div>
        <div className="font-mono text-[10px] text-slate-500 lg:text-right">
          <div>{summary.tickersAnalyzed} tickers · {data.sessionRange.sectors} sectors</div>
          <div>generated {data.generatedAt.replace("T", " ").slice(0, 19)} UTC</div>
        </div>
      </div>

      {/* summary */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <StatCard
          label="Active Windows"
          value={String(summary.activeWindows)}
          hint="calendar + price both qualified"
          tone="text-emerald-400"
        />
        <StatCard
          label="Sectors Active"
          value={String(summary.sectorsActive)}
          hint="≥30% of members in window"
          tone="text-emerald-400"
        />
        <StatCard
          label="Sectors Watching"
          value={String(summary.sectorsWatching)}
          hint="window opens next month"
          tone="text-amber-300"
        />
        <StatCard
          label="Off-Season"
          value={String(summary.sectorsOffSeason)}
          hint="no pre-season bid"
          tone="text-slate-400"
        />
        <StatCard
          label="Tape Depth"
          value={`${meta.forwardWindows.join("/")}d`}
          hint={`min ${meta.minHistoryBars} sessions per name`}
          tone="text-slate-200"
        />
      </div>

      {/* active accumulation list */}
      {data.activeWindows.length > 0 && (
        <section className="rounded-xl border border-emerald-500/30 bg-emerald-500/5 p-4">
          <div className="flex items-center gap-2">
            <span className="h-2 w-2 animate-pulse rounded-full bg-emerald-400" />
            <h2 className="font-mono text-xs font-bold uppercase tracking-wider text-emerald-300">
              Live Accumulation Windows
            </h2>
          </div>
          <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
            {data.activeWindows.map((row) => (
              <div
                key={`${row.sector}-${row.ticker}`}
                className="rounded-lg border border-slate-800 bg-slate-900/70 p-3"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-sm font-bold text-slate-50">{row.ticker}</span>
                  <span className="rounded border border-emerald-400/40 bg-emerald-400/10 px-1.5 py-0.5 text-[9px] font-mono font-bold text-emerald-300">
                    {row.sector.toUpperCase()}
                  </span>
                </div>
                <div className="mt-2 grid grid-cols-3 gap-1 text-center font-mono text-[10px]">
                  <div>
                    <div className="text-slate-500">RANGE</div>
                    <div className="font-bold text-slate-200">{row.rangePositionPct.toFixed(0)}%</div>
                  </div>
                  <div>
                    <div className="text-slate-500">WIN 60D</div>
                    <div className="font-bold text-emerald-300">{row.winRate60Pct.toFixed(0)}%</div>
                  </div>
                  <div>
                    <div className="text-slate-500">FWD 60D</div>
                    <div className={`font-bold ${row.avgForward60Pct >= 0 ? "text-emerald-300" : "text-rose-300"}`}>
                      {signed(row.avgForward60Pct, 1)}
                    </div>
                  </div>
                </div>
                <div className="mt-1.5 flex justify-between font-mono text-[10px] text-slate-500">
                  <span>PKR {row.lastClose.toFixed(2)}</span>
                  <span>DD {row.drawdownFromHighPct.toFixed(1)}%</span>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* seasonality calendar */}
      <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="font-mono text-xs font-bold uppercase tracking-wider text-slate-200">
              Seasonality Calendar
            </h2>
            <p className="text-[11px] text-slate-500">
              Mean forward 60-session return by month · <span className="text-emerald-300">A</span> pre-season
              accumulation · <span className="text-amber-300">P</span> peak season
            </p>
          </div>
          <div className="flex items-center gap-2 font-mono text-[10px] text-slate-500">
            <span className="h-2.5 w-4 rounded-sm bg-rose-500/25" /> weak
            <span className="h-2.5 w-4 rounded-sm bg-slate-800" /> flat
            <span className="h-2.5 w-4 rounded-sm bg-emerald-500/35" /> strong
          </div>
        </div>

        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[820px] border-separate border-spacing-y-1 font-mono text-[10px]">
            <thead>
              <tr className="text-slate-500">
                <th className="sticky left-0 z-10 bg-slate-950 px-2 py-1 text-left font-semibold">SECTOR</th>
                {["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"].map(
                  (label) => (
                    <th key={label} className="px-1 py-1 text-center font-semibold">
                      {label}
                    </th>
                  ),
                )}
              </tr>
            </thead>
            <tbody>
              {data.sectors.map((sector) => (
                <tr key={sector.sector}>
                  <td className="sticky left-0 z-10 whitespace-nowrap bg-slate-950 px-2 py-1">
                    <span className="text-slate-200">{sector.sector}</span>
                    <span className="ml-1 text-slate-600">{sector.members}</span>
                  </td>
                  {sector.calendar.map((cell) => (
                    <td key={cell.month} className="p-0">
                      <div
                        title={`${sector.sector} ${cell.label}: ${cell.samples} samples · win ${cell.winRatePct.toFixed(
                          0,
                        )}% · avg ${signed(cell.avgForward60Pct, 1)}`}
                        className={`relative mx-0.5 rounded px-1 py-1.5 text-center ${heat(
                          cell.avgForward60Pct,
                          cell.samples,
                        )}`}
                      >
                        <span className="block font-bold">{cell.avgForward60Pct.toFixed(1)}</span>
                        <span className="block text-[8px] opacity-70">{cell.winRatePct.toFixed(0)}%</span>
                        {cell.isAccumulation && (
                          <span className="absolute right-0.5 top-0 text-[8px] font-black text-emerald-300">A</span>
                        )}
                        {cell.isPeak && (
                          <span className="absolute bottom-0 right-0.5 text-[8px] font-black text-amber-300">P</span>
                        )}
                      </div>
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* sector cards */}
      <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
        <h2 className="font-mono text-xs font-bold uppercase tracking-wider text-slate-200">
          Sector Window Scorecard
        </h2>
        <div className="mt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {data.sectors.map((sector) => (
            <div key={sector.sector} className="rounded-lg border border-slate-800 bg-slate-950/70 p-3">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <div className="font-mono text-sm font-bold text-slate-50">{sector.sector}</div>
                  <div className="font-mono text-[10px] text-slate-500">
                    {sector.members} names · {sector.activeCount} active · {sector.watchCount} watch
                  </div>
                </div>
                <span
                  className={`shrink-0 rounded border px-1.5 py-0.5 text-[9px] font-mono font-bold ${statusTone(
                    sector.status,
                  )}`}
                >
                  {shortStatus(sector.status)}
                </span>
              </div>

              <div className="mt-2 flex flex-wrap gap-1 font-mono text-[9px]">
                <span className="rounded border border-emerald-400/30 bg-emerald-400/10 px-1.5 py-0.5 text-emerald-300">
                  ACC {sector.accumulationMonths.join("·")}
                </span>
                <span className="rounded border border-amber-400/30 bg-amber-400/10 px-1.5 py-0.5 text-amber-300">
                  PEAK {sector.peakMonths.join("·")}
                </span>
              </div>

              <div className="mt-3 grid grid-cols-4 gap-1 text-center font-mono text-[10px]">
                <div>
                  <div className="text-slate-500">WIN 60</div>
                  <div className="font-bold text-slate-100">
                    {sector.accumulationWindow.forward60.winRatePct.toFixed(0)}%
                  </div>
                </div>
                <div>
                  <div className="text-slate-500">AVG 60</div>
                  <div
                    className={`font-bold ${
                      sector.accumulationWindow.forward60.avgPct >= 0 ? "text-emerald-300" : "text-rose-300"
                    }`}
                  >
                    {signed(sector.accumulationWindow.forward60.avgPct, 1)}
                  </div>
                </div>
                <div>
                  <div className="text-slate-500">AVG 90</div>
                  <div
                    className={`font-bold ${
                      sector.accumulationWindow.forward90.avgPct >= 0 ? "text-emerald-300" : "text-rose-300"
                    }`}
                  >
                    {signed(sector.accumulationWindow.forward90.avgPct, 1)}
                  </div>
                </div>
                <div>
                  <div className="text-slate-500">SAMPLES</div>
                  <div className="font-bold text-slate-300">{sector.accumulationWindow.forward60.samples}</div>
                </div>
              </div>

              <p className="mt-2 border-t border-slate-800 pt-2 text-[10px] leading-snug text-slate-500">
                {sector.rationale}
              </p>
            </div>
          ))}
        </div>
      </section>

      {/* ticker table */}
      <section className="overflow-hidden rounded-xl border border-slate-800 bg-slate-900/40">
        <div className="flex flex-col gap-2 border-b border-slate-800 p-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex flex-wrap items-center gap-1">
            {(["ALL", ...STATUSES] as const).map((option) => (
              <button
                key={option}
                type="button"
                onClick={() => setStatusFilter(option)}
                aria-pressed={statusFilter === option}
                className={`rounded border px-2 py-1 font-mono text-[10px] font-bold transition-colors ${
                  statusFilter === option
                    ? "border-emerald-400/50 bg-emerald-400/15 text-emerald-300"
                    : "border-slate-700 bg-slate-950 text-slate-400 hover:bg-slate-900"
                }`}
              >
                {option === "ALL" ? "ALL" : shortStatus(option)}
              </button>
            ))}
          </div>
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
            <select
              value={sectorFilter}
              onChange={(event) => setSectorFilter(event.target.value)}
              aria-label="Filter by sector"
              className="rounded border border-slate-700 bg-slate-950 px-2 py-1.5 font-mono text-[11px] text-slate-200 focus:border-emerald-400/60 focus:outline-none"
            >
              <option value="ALL">All sectors</option>
              {sectorOptions.map((sector) => (
                <option key={sector} value={sector}>
                  {sector}
                </option>
              ))}
            </select>
            <input
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search ticker…"
              aria-label="Search tickers"
              className="w-full rounded border border-slate-700 bg-slate-950 px-2.5 py-1.5 font-mono text-[11px] text-slate-200 placeholder:text-slate-600 focus:border-emerald-400/60 focus:outline-none sm:w-44"
            />
            <span className="font-mono text-[10px] text-slate-500">{tickers.length} rows</span>
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full min-w-[960px] text-left font-mono text-[11px]">
            <thead className="bg-slate-950/80 text-[9px] uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-3 py-2">Ticker</th>
                <th className="px-3 py-2">Sector</th>
                <th className="px-3 py-2">Status</th>
                <th className="px-3 py-2 text-right">Range Pos</th>
                <th className="px-3 py-2 text-right">3Y DD</th>
                <th className="px-3 py-2 text-right">Win 60D</th>
                <th className="px-3 py-2 text-right">Fwd 60D</th>
                <th className="px-3 py-2 text-right">Fwd 90D</th>
                <th className="px-3 py-2 text-right">P25 / P75</th>
                <th className="px-3 py-2 text-right">Best Month</th>
                <th className="px-3 py-2 text-right">Close</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/70">
              {tickers.map((t) => {
                const w60 = t.accumulationWindowStats.forward60;
                const w90 = t.accumulationWindowStats.forward90;
                return (
                  <tr key={`${t.sector}-${t.ticker}`} className="hover:bg-slate-900/60">
                    <td className="whitespace-nowrap px-3 py-2 font-bold text-slate-50">{t.ticker}</td>
                    <td className="whitespace-nowrap px-3 py-2 text-slate-400">{t.sector}</td>
                    <td className="whitespace-nowrap px-3 py-2">
                      <span
                        className={`inline-block rounded border px-1.5 py-0.5 text-[9px] font-bold ${statusTone(
                          t.status,
                        )}`}
                        title={t.phaseNote}
                      >
                        {shortStatus(t.status)}
                      </span>
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 text-right text-slate-300">
                      {t.position.rangePositionPct.toFixed(0)}%
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 text-right text-rose-300">
                      {t.position.drawdownFromHighPct.toFixed(1)}%
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 text-right text-slate-200">
                      {w60.winRatePct.toFixed(0)}%
                    </td>
                    <td
                      className={`whitespace-nowrap px-3 py-2 text-right font-bold ${
                        w60.avgPct >= 0 ? "text-emerald-300" : "text-rose-300"
                      }`}
                    >
                      {signed(w60.avgPct, 1)}
                    </td>
                    <td
                      className={`whitespace-nowrap px-3 py-2 text-right font-bold ${
                        w90.avgPct >= 0 ? "text-emerald-300" : "text-rose-300"
                      }`}
                    >
                      {signed(w90.avgPct, 1)}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 text-right text-slate-400">
                      {signed(w60.p25Pct, 1)} / {signed(w60.p75Pct, 1)}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 text-right text-slate-300">
                      {t.bestMonth ?? "—"}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 text-right text-slate-400">
                      {t.lastClose.toFixed(2)}
                    </td>
                  </tr>
                );
              })}
              {tickers.length === 0 && (
                <tr>
                  <td colSpan={11} className="px-3 py-8 text-center text-slate-500">
                    No tickers match this filter.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <p className="border-t border-slate-800 px-3 py-2 text-[10px] text-slate-500">{meta.method}</p>
      </section>
    </div>
  );
}
