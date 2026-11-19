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
  liquidity?: { avgTurnoverPkr: number; avgVolume: number; liquid: boolean };
  avgTurnoverPkr?: number;
  avgVolume?: number;
  liquid?: boolean;
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

type LiquidityGate = {
  turnoverWindow: number;
  minAvgTurnoverPkr: number;
  minAvgVolume: number;
  minPricePkr: number;
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
    liquidityGate?: LiquidityGate;
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
    avgTurnoverPkr?: number;
    avgVolume?: number;
    liquid?: boolean;
    medianForward60Pct?: number;
  }>;
  sectors: SectorRow[];
};

/* ---------------------------------------------------------------- helpers */

const STATUS_ACTIVE = "ACCUMULATION WINDOW ACTIVE";
const STATUS_WATCH = "WATCH";
const STATUS_OFF = "OFF-SEASON";
const STATUSES = [STATUS_ACTIVE, STATUS_WATCH, STATUS_OFF] as const;

const PAGE_SIZE = 25;
const MAX_RANGE_PCT = 45;

type Action = "ACCUMULATE ON DIPS" | "WAIT FOR TRIGGER" | "EXTENDED / SKIP";

const ACTION_TONE: Record<Action, string> = {
  "ACCUMULATE ON DIPS": "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
  "WAIT FOR TRIGGER": "border-amber-500/40 bg-amber-500/10 text-amber-300",
  "EXTENDED / SKIP": "border-slate-700 bg-slate-800/60 text-slate-400",
};

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

const statusTone = (status: string) => {
  if (status === STATUS_ACTIVE) return "border-emerald-500/40 bg-emerald-500/10 text-emerald-300";
  if (status === STATUS_WATCH) return "border-amber-500/40 bg-amber-500/10 text-amber-300";
  return "border-slate-700 bg-slate-800/60 text-slate-400";
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

/** Turnover in the units a PSX desk quotes. */
const rupees = (value: number | null | undefined) => {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  if (value >= 1_000_000_000) return `Rs ${(value / 1_000_000_000).toFixed(2)}bn`;
  if (value >= 1_000_000) return `Rs ${(value / 1_000_000).toFixed(1)}mn`;
  if (value >= 1_000) return `Rs ${(value / 1_000).toFixed(0)}k`;
  return `Rs ${value.toFixed(0)}`;
};

const isLiquid = (t: TickerRecord) =>
  t.liquid ?? t.liquidity?.liquid ?? (t.avgTurnoverPkr ?? 0) >= 5_000_000;

const turnoverOf = (t: TickerRecord) => t.avgTurnoverPkr ?? t.liquidity?.avgTurnoverPkr ?? 0;

/** The one decision the desk needs. */
function playAction(t: TickerRecord): Action {
  if (t.status === STATUS_ACTIVE && isLiquid(t)) return "ACCUMULATE ON DIPS";
  if (t.status === STATUS_ACTIVE || t.status === STATUS_WATCH) return "WAIT FOR TRIGGER";
  if (t.position.rangePositionPct <= MAX_RANGE_PCT && isLiquid(t)) return "WAIT FOR TRIGGER";
  return "EXTENDED / SKIP";
}

/** Months from the current calendar month to a window month, wrapping the year. */
function monthsUntil(currentMonth: number, targetMonth: number) {
  return (targetMonth - currentMonth + 12) % 12;
}

function nextWindowIn(sector: SectorRow, currentMonth: number) {
  const offsets = sector.accumulationMonths
    .map((label) => MONTHS.indexOf(label) + 1)
    .filter((month) => month > 0)
    .map((month) => {
      const delta = monthsUntil(currentMonth, month);
      return delta === 0 ? 12 : delta;
    });
  if (offsets.length === 0) return null;
  const delta = Math.min(...offsets);
  if (delta > 3) return null;
  return { delta, month: MONTHS[(currentMonth + delta - 1) % 12] };
}

/* ------------------------------------------------------------------- page */

export default function SeasonalityPage() {
  const [data, setData] = useState<SeasonalityPayload | null>(null);
  const [error, setError] = useState(false);
  const [statusFilter, setStatusFilter] = useState<string>("ALL");
  const [sectorFilter, setSectorFilter] = useState<string>("ALL");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [heatmapOpen, setHeatmapOpen] = useState(false);

  useEffect(() => {
    fetch("/data/seasonality_matrix.json")
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`HTTP ${res.status}`))))
      .then((payload: SeasonalityPayload) => setData(payload))
      .catch((err) => {
        console.error("[Seasonality] matrix load failed:", err);
        setError(true);
      });
  }, []);

  const allTickers = useMemo(
    () => (data ? data.sectors.flatMap((sector) => sector.tickers) : []),
    [data],
  );

  const sectorByName = useMemo(() => {
    const map = new Map<string, SectorRow>();
    for (const sector of data?.sectors ?? []) map.set(sector.sector, sector);
    return map;
  }, [data]);

  /** Action Now: liquid names whose calendar is open and price is still in range. */
  const actionNow = useMemo(
    () =>
      allTickers
        .filter(
          (t) =>
            t.status === STATUS_ACTIVE &&
            isLiquid(t) &&
            t.position.rangePositionPct <= MAX_RANGE_PCT,
        )
        .sort(
          (a, b) =>
            b.accumulationWindowStats.forward60.winRatePct -
            a.accumulationWindowStats.forward60.winRatePct,
        ),
    [allTickers],
  );

  /** Upcoming Next: sectors opening within 3 months (WATCH is the one-month case). */
  const upcoming = useMemo(() => {
    if (!data) return [];
    const current = data.meta.currentMonth;
    return data.sectors
      .filter((sector) => sector.status !== STATUS_ACTIVE)
      .map((sector) => ({ sector, next: nextWindowIn(sector, current) }))
      .filter(
        (row): row is { sector: SectorRow; next: { delta: number; month: string } } =>
          row.next !== null,
      )
      .sort((a, b) => a.next.delta - b.next.delta);
  }, [data]);

  const tickers = useMemo(() => {
    const needle = query.trim().toUpperCase();
    return allTickers.filter((t) => {
      if (statusFilter !== "ALL" && t.status !== statusFilter) return false;
      if (sectorFilter !== "ALL" && t.sector !== sectorFilter) return false;
      if (needle && !t.ticker.includes(needle) && !t.sector.toUpperCase().includes(needle))
        return false;
      return true;
    });
  }, [allTickers, statusFilter, sectorFilter, query]);

  const pageCount = Math.max(1, Math.ceil(tickers.length / PAGE_SIZE));
  const currentPage = Math.min(page, pageCount);
  const pageRows = tickers.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE);

  // Any filter change invalidates the page offset; reset before paint.
  useEffect(() => {
    setPage(1);
  }, [statusFilter, sectorFilter, query]);

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
  const gate = meta.liquidityGate;
  const turnoverGate = gate?.minAvgTurnoverPkr ?? 5_000_000;
  const activeSectors = data.sectors
    .filter((sector) => sector.status === STATUS_ACTIVE)
    .sort((a, b) => b.activeCount - a.activeCount);

  return (
    <div className="space-y-5">
      {/* header */}
      <div className="flex flex-col gap-3 border-b border-slate-800 pb-4 lg:flex-row lg:items-end lg:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-lg font-bold tracking-tight text-slate-50 sm:text-xl">
              Seasonal Playbook
            </h1>
            <span className="rounded border border-emerald-500/40 bg-emerald-500/10 px-2 py-0.5 font-mono text-[10px] font-bold text-emerald-300">
              {meta.currentMonthLabel.toUpperCase()} · NOW &amp; UPCOMING
            </span>
          </div>
          <p className="mt-1 text-[11px] leading-relaxed text-slate-400">
            {actionNow.length} liquid names buyable now · {activeSectors.length} sectors in window ·{" "}
            {upcoming.length} opening in the next 3 months. Liquidity gate{" "}
            {rupees(turnoverGate)}/day, range ≤{MAX_RANGE_PCT}%.
          </p>
        </div>
        <div className="font-mono text-[10px] text-slate-500 lg:text-right">
          <div className="tabular-nums">
            {summary.tickersAnalyzed} tickers · {data.sessionRange.sectors} sectors
          </div>
          <div>
            {data.sessionRange.from ?? "—"} → {data.sessionRange.to ?? "—"} · generated{" "}
            {data.generatedAt.slice(0, 10)}
          </div>
        </div>
      </div>

      {/* ---------------------------------------------------- action now */}
      <section className="overflow-hidden rounded-2xl border border-emerald-500/25 bg-slate-900/40">
        <header className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-800/80 px-4 py-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <h2 className="text-[13px] font-bold tracking-tight text-slate-100">Action Now</h2>
              <span className="rounded border border-emerald-500/40 bg-emerald-500/10 px-1.5 py-0.5 font-mono text-[9px] font-bold text-emerald-300">
                ACCUMULATE ON DIPS
              </span>
              <span className="font-mono text-[10px] tabular-nums text-slate-500">
                {actionNow.length}
              </span>
            </div>
            <p className="mt-0.5 text-[11px] leading-snug text-slate-500">
              Window open and price inside the lower {MAX_RANGE_PCT}% of its 3-year range — scale in
              on red sessions.
            </p>
          </div>
          {activeSectors.length > 0 && (
            <div className="flex flex-wrap gap-1 font-mono text-[9px]">
              {activeSectors.map((sector) => (
                <span
                  key={sector.sector}
                  className="rounded border border-emerald-500/30 bg-emerald-500/5 px-1.5 py-0.5 text-emerald-300/90"
                  title={sector.rationale}
                >
                  {sector.sector}
                </span>
              ))}
            </div>
          )}
        </header>

        {actionNow.length === 0 ? (
          <p className="px-4 py-8 text-center text-xs text-slate-500">
            No liquid name is inside its accumulation zone — wait for a pullback.
          </p>
        ) : (
          <>
            {/* desktop table */}
            <div className="hidden overflow-x-auto overscroll-x-contain [-webkit-overflow-scrolling:touch] md:block">
              <table className="w-full min-w-[820px] text-left font-mono text-[11px]">
                <thead className="bg-slate-950/60 text-[9px] uppercase tracking-wide text-slate-500">
                  <tr>
                    <th className="px-3 py-2">Ticker</th>
                    <th className="px-3 py-2">Sector</th>
                    <th className="px-3 py-2 text-right">Range</th>
                    <th className="px-3 py-2 text-right">Win 60D</th>
                    <th className="px-3 py-2 text-right">Win 90D</th>
                    <th className="px-3 py-2 text-right">Avg 90D</th>
                    <th className="px-3 py-2 font-sans normal-case">Why now</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/70">
                  {actionNow.map((t) => {
                    const w60 = t.accumulationWindowStats.forward60;
                    const w90 = t.accumulationWindowStats.forward90;
                    return (
                      <tr key={`${t.sector}-${t.ticker}`} className="hover:bg-slate-900/60">
                        <td className="whitespace-nowrap px-3 py-2 font-bold text-slate-50">
                          {t.ticker}
                          <span className="ml-1.5 text-[9px] font-normal text-slate-500">
                            {rupees(turnoverOf(t))}
                          </span>
                        </td>
                        <td className="whitespace-nowrap px-3 py-2 text-slate-400">{t.sector}</td>
                        <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums text-slate-200">
                          {t.position.rangePositionPct.toFixed(0)}%
                        </td>
                        <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums text-slate-200">
                          {w60.winRatePct.toFixed(0)}%
                        </td>
                        <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums text-slate-200">
                          {w90.winRatePct.toFixed(0)}%
                        </td>
                        <td
                          className={`whitespace-nowrap px-3 py-2 text-right font-bold tabular-nums ${
                            w90.avgPct >= 0 ? "text-emerald-300" : "text-rose-300"
                          }`}
                        >
                          {signed(w90.avgPct, 1)}
                        </td>
                        <td className="max-w-[22rem] px-3 py-2 font-sans text-[10px] leading-snug text-slate-400">
                          {sectorByName.get(t.sector)?.rationale ?? t.phaseNote}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {/* mobile: two-line rows, no tall cards */}
            <ul className="divide-y divide-slate-800/70 md:hidden">
              {actionNow.map((t) => {
                const w60 = t.accumulationWindowStats.forward60;
                const w90 = t.accumulationWindowStats.forward90;
                return (
                  <li key={`${t.sector}-${t.ticker}`} className="px-3 py-2.5">
                    <div className="flex items-baseline justify-between gap-2">
                      <div className="flex min-w-0 items-baseline gap-1.5">
                        <span className="font-mono text-sm font-bold text-slate-50">{t.ticker}</span>
                        <span className="truncate font-mono text-[9px] text-slate-500">
                          {t.sector}
                        </span>
                      </div>
                      <span className="shrink-0 font-mono text-[10px] tabular-nums text-slate-300">
                        range {t.position.rangePositionPct.toFixed(0)}%
                      </span>
                    </div>
                    <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 font-mono text-[10px] tabular-nums text-slate-400">
                      <span>
                        win60 <span className="text-slate-200">{w60.winRatePct.toFixed(0)}%</span>
                      </span>
                      <span>
                        win90 <span className="text-slate-200">{w90.winRatePct.toFixed(0)}%</span>
                      </span>
                      <span>
                        avg90{" "}
                        <span className={w90.avgPct >= 0 ? "text-emerald-300" : "text-rose-300"}>
                          {signed(w90.avgPct, 1)}
                        </span>
                      </span>
                    </div>
                    <p className="mt-1 line-clamp-2 font-sans text-[10px] leading-snug text-slate-500">
                      {sectorByName.get(t.sector)?.rationale ?? t.phaseNote}
                    </p>
                  </li>
                );
              })}
            </ul>
          </>
        )}
      </section>

      {/* -------------------------------------------------------- upcoming */}
      <section className="rounded-2xl border border-amber-500/25 bg-slate-900/40">
        <header className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-800/80 px-4 py-3">
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-[13px] font-bold tracking-tight text-slate-100">Upcoming Next</h2>
              <span className="rounded border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 font-mono text-[9px] font-bold text-amber-300">
                WATCH · 1–3 MONTHS
              </span>
              <span className="font-mono text-[10px] tabular-nums text-slate-500">
                {upcoming.length}
              </span>
            </div>
            <p className="mt-0.5 text-[11px] leading-snug text-slate-500">
              Set alerts on the liquid names now; do not pre-buy before the window opens.
            </p>
          </div>
        </header>

        {upcoming.length === 0 ? (
          <p className="px-4 py-8 text-center text-xs text-slate-500">
            Nothing opens in the next three months — the next bid is further out.
          </p>
        ) : (
          <ul className="grid gap-px bg-slate-800/60 sm:grid-cols-2 xl:grid-cols-3">
            {upcoming.map(({ sector, next }) => {
              const monitors = sector.tickers
                .filter(isLiquid)
                .sort(
                  (a, b) =>
                    a.position.rangePositionPct - b.position.rangePositionPct ||
                    b.accumulationWindowStats.forward60.winRatePct -
                      a.accumulationWindowStats.forward60.winRatePct,
                )
                .slice(0, 3);
              return (
                <li key={sector.sector} className="bg-slate-900/40 px-4 py-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex min-w-0 items-center gap-2">
                      <span className="truncate font-mono text-[12px] font-bold text-slate-100">
                        {sector.sector}
                      </span>
                      <span
                        className={`shrink-0 rounded border px-1.5 py-0.5 font-mono text-[9px] font-bold ${statusTone(
                          sector.status,
                        )}`}
                      >
                        {shortStatus(sector.status)}
                      </span>
                    </div>
                    <span className="shrink-0 font-mono text-[10px] tabular-nums text-amber-300">
                      {next.month} · {next.delta === 1 ? "next month" : `in ${next.delta} mo`}
                    </span>
                  </div>

                  <div className="mt-1 font-mono text-[9px] text-slate-500">
                    window {sector.accumulationMonths.join("·") || "—"} · peak{" "}
                    {sector.peakMonths.join("·") || "—"}
                  </div>

                  <p className="mt-1.5 text-[10px] leading-snug text-slate-400">
                    {sector.rationale}
                  </p>

                  <div className="mt-2 flex flex-wrap items-center gap-1">
                    <span className="font-mono text-[9px] uppercase tracking-wide text-slate-600">
                      watch
                    </span>
                    {monitors.length === 0 ? (
                      <span className="font-mono text-[10px] text-slate-600">no liquid names</span>
                    ) : (
                      monitors.map((t) => (
                        <span
                          key={t.ticker}
                          className="rounded border border-slate-700 bg-slate-950 px-1.5 py-0.5 font-mono text-[9px] text-slate-300"
                          title={`range ${t.position.rangePositionPct.toFixed(0)}% · win60 ${t.accumulationWindowStats.forward60.winRatePct.toFixed(0)}% · ${rupees(turnoverOf(t))}/day`}
                        >
                          {t.ticker}{" "}
                          <span className="text-slate-500">
                            {t.position.rangePositionPct.toFixed(0)}%
                          </span>
                        </span>
                      ))
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      {/* ------------------------------------------- collapsible heatmap */}
      <section className="overflow-hidden rounded-2xl border border-slate-800/80 bg-slate-900/40">
        <button
          type="button"
          onClick={() => setHeatmapOpen((open) => !open)}
          aria-expanded={heatmapOpen}
          className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left transition-colors hover:bg-slate-900/70"
        >
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-[13px] font-bold tracking-tight text-slate-100">
                Seasonality calendar
              </h2>
              <span className="font-mono text-[9px] text-slate-500">
                {data.sectors.length} sectors × 12 months
              </span>
            </div>
            <p className="mt-0.5 text-[11px] text-slate-500">
              Mean forward 60-session return by month ·{" "}
              <span className="text-emerald-300">A</span> accumulation ·{" "}
              <span className="text-amber-300">P</span> peak
            </p>
          </div>
          <span className="shrink-0 rounded border border-slate-700 bg-slate-950 px-2 py-1 font-mono text-[10px] text-slate-400">
            {heatmapOpen ? "Hide" : "Show"}
          </span>
        </button>

        {heatmapOpen && (
          <div className="border-t border-slate-800/80 p-2 sm:p-3">
            <div className="overflow-x-auto overscroll-x-contain [-webkit-overflow-scrolling:touch]">
              <table className="w-full min-w-[680px] border-separate border-spacing-y-px font-mono text-[10px]">
                <thead>
                  <tr className="text-[8px] uppercase tracking-wide text-slate-500">
                    <th className="sticky left-0 z-10 bg-slate-950 px-2 py-1 text-left font-semibold">
                      Sector
                    </th>
                    {MONTHS.map((label) => (
                      <th key={label} className="px-0.5 py-1 text-center font-semibold">
                        {label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.sectors.map((sector) => (
                    <tr key={sector.sector}>
                      <td className="sticky left-0 z-10 whitespace-nowrap bg-slate-950 px-2 py-0.5">
                        <span className="text-[10px] text-slate-300">{sector.sector}</span>
                        <span className="ml-1 text-slate-600">{sector.members}</span>
                      </td>
                      {sector.calendar.map((cell) => (
                        <td key={cell.month} className="p-0">
                          <div
                            title={`${sector.sector} ${cell.label}: ${cell.samples} samples · win ${cell.winRatePct.toFixed(
                              0,
                            )}% · avg ${signed(cell.avgForward60Pct, 1)}`}
                            className={`relative mx-px rounded-sm py-0.5 text-center tabular-nums ${heat(
                              cell.avgForward60Pct,
                              cell.samples,
                            )}`}
                          >
                            <span className="block text-[9px] font-bold leading-tight">
                              {cell.avgForward60Pct.toFixed(1)}
                            </span>
                            {cell.isAccumulation && (
                              <span className="absolute right-0 top-0 text-[7px] font-black text-emerald-300">
                                A
                              </span>
                            )}
                            {cell.isPeak && (
                              <span className="absolute bottom-0 right-0 text-[7px] font-black text-amber-300">
                                P
                              </span>
                            )}
                          </div>
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </section>

      {/* --------------------------------------------------------- explorer */}
      <section className="overflow-hidden rounded-2xl border border-slate-800/80 bg-slate-900/40">
        <div className="flex flex-col gap-3 border-b border-slate-800/80 p-3 sm:p-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex flex-wrap items-center gap-1">
            {(["ALL", ...STATUSES] as const).map((option) => (
              <button
                key={option}
                type="button"
                onClick={() => setStatusFilter(option)}
                aria-pressed={statusFilter === option}
                className={`rounded border px-2 py-1 font-mono text-[10px] font-bold transition-colors ${
                  statusFilter === option
                    ? "border-emerald-500/50 bg-emerald-500/15 text-emerald-300"
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
              className="rounded border border-slate-700 bg-slate-950 px-2 py-1.5 font-mono text-[11px] text-slate-200 focus:border-emerald-500/60 focus:outline-none"
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
              className="w-full rounded border border-slate-700 bg-slate-950 px-2.5 py-1.5 font-mono text-[11px] text-slate-200 placeholder:text-slate-600 focus:border-emerald-500/60 focus:outline-none sm:w-44"
            />
            <span className="font-mono text-[10px] tabular-nums text-slate-500">
              {tickers.length} rows
            </span>
          </div>
        </div>

        {/* desktop / tablet table */}
        <div className="hidden overflow-x-auto overscroll-x-contain [-webkit-overflow-scrolling:touch] md:block">
          <table className="w-full min-w-[880px] text-left font-mono text-[11px]">
            <thead className="bg-slate-950/80 text-[9px] uppercase tracking-wide text-slate-500">
              <tr>
                <th className="sticky left-0 z-10 bg-slate-950 px-3 py-2">Ticker</th>
                <th className="px-3 py-2">Sector</th>
                <th className="px-3 py-2">Action</th>
                <th className="px-3 py-2 text-right">Range</th>
                <th className="px-3 py-2 text-right">Win 60D</th>
                <th className="px-3 py-2 text-right">Med 60D</th>
                <th className="px-3 py-2 text-right">Avg 90D</th>
                <th className="px-3 py-2 text-right">Turnover</th>
                <th className="px-3 py-2 text-right">Close</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/70">
              {pageRows.map((t) => {
                const w60 = t.accumulationWindowStats.forward60;
                const w90 = t.accumulationWindowStats.forward90;
                const action = playAction(t);
                return (
                  <tr key={`${t.sector}-${t.ticker}`} className="hover:bg-slate-900/60">
                    <td className="sticky left-0 z-10 whitespace-nowrap bg-slate-900/95 px-3 py-2 font-bold text-slate-50 backdrop-blur">
                      {t.ticker}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 text-slate-400">{t.sector}</td>
                    <td className="whitespace-nowrap px-3 py-2">
                      <span
                        className={`inline-block rounded border px-1.5 py-0.5 text-[9px] font-bold ${ACTION_TONE[action]}`}
                        title={t.phaseNote}
                      >
                        {action}
                      </span>
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums text-slate-300">
                      {t.position.rangePositionPct.toFixed(0)}%
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums text-slate-200">
                      {w60.winRatePct.toFixed(0)}%
                    </td>
                    <td
                      className={`whitespace-nowrap px-3 py-2 text-right font-bold tabular-nums ${
                        w60.medianPct >= 0 ? "text-emerald-300" : "text-rose-300"
                      }`}
                    >
                      {signed(w60.medianPct, 1)}
                    </td>
                    <td
                      className={`whitespace-nowrap px-3 py-2 text-right font-bold tabular-nums ${
                        w90.avgPct >= 0 ? "text-emerald-300" : "text-rose-300"
                      }`}
                    >
                      {signed(w90.avgPct, 1)}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums text-slate-400">
                      {rupees(turnoverOf(t))}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums text-slate-400">
                      {t.lastClose.toFixed(2)}
                    </td>
                  </tr>
                );
              })}
              {pageRows.length === 0 && (
                <tr>
                  <td colSpan={9} className="px-3 py-8 text-center text-slate-500">
                    No tickers match this filter.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {/* mobile compact rows */}
        <ul className="divide-y divide-slate-800/70 md:hidden">
          {pageRows.map((t) => {
            const w60 = t.accumulationWindowStats.forward60;
            const w90 = t.accumulationWindowStats.forward90;
            const action = playAction(t);
            return (
              <li key={`${t.sector}-${t.ticker}`} className="px-3 py-2">
                <div className="flex items-baseline justify-between gap-2">
                  <div className="flex min-w-0 items-baseline gap-1.5">
                    <span className="font-mono text-[13px] font-bold text-slate-50">{t.ticker}</span>
                    <span className="truncate font-mono text-[9px] text-slate-500">{t.sector}</span>
                  </div>
                  <span
                    className={`shrink-0 rounded border px-1.5 py-0.5 font-mono text-[8px] font-bold ${ACTION_TONE[action]}`}
                  >
                    {action}
                  </span>
                </div>
                <div className="mt-0.5 flex flex-wrap gap-x-3 font-mono text-[10px] tabular-nums text-slate-400">
                  <span>
                    range <span className="text-slate-200">{t.position.rangePositionPct.toFixed(0)}%</span>
                  </span>
                  <span>
                    win60 <span className="text-slate-200">{w60.winRatePct.toFixed(0)}%</span>
                  </span>
                  <span>
                    avg90{" "}
                    <span className={w90.avgPct >= 0 ? "text-emerald-300" : "text-rose-300"}>
                      {signed(w90.avgPct, 1)}
                    </span>
                  </span>
                </div>
              </li>
            );
          })}
          {pageRows.length === 0 && (
            <li className="px-3 py-8 text-center text-xs text-slate-500">
              No tickers match this filter.
            </li>
          )}
        </ul>

        {/* pagination */}
        <div className="flex flex-col gap-2 border-t border-slate-800/80 px-3 py-2.5 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-[10px] leading-snug text-slate-500">{meta.method}</p>
          <div className="flex items-center gap-2 font-mono text-[10px] tabular-nums text-slate-400">
            <button
              type="button"
              onClick={() => setPage(Math.max(1, currentPage - 1))}
              disabled={currentPage <= 1}
              className="rounded border border-slate-700 bg-slate-950 px-2 py-1 font-bold text-slate-300 disabled:cursor-not-allowed disabled:opacity-40"
            >
              Prev
            </button>
            <span className="whitespace-nowrap">
              {currentPage} / {pageCount} · {tickers.length} rows
            </span>
            <button
              type="button"
              onClick={() => setPage(Math.min(pageCount, currentPage + 1))}
              disabled={currentPage >= pageCount}
              className="rounded border border-slate-700 bg-slate-950 px-2 py-1 font-bold text-slate-300 disabled:cursor-not-allowed disabled:opacity-40"
            >
              Next
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}
