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

type Action = "ACCUMULATE ON DIPS" | "WAIT FOR TRIGGER" | "EXTENDED / SKIP";

const ACTION_TONE: Record<Action, string> = {
  "ACCUMULATE ON DIPS": "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
  "WAIT FOR TRIGGER": "border-amber-500/40 bg-amber-500/10 text-amber-300",
  "EXTENDED / SKIP": "border-slate-700 bg-slate-800/60 text-slate-400",
};

const ACTION_ORDER: Action[] = ["ACCUMULATE ON DIPS", "WAIT FOR TRIGGER", "EXTENDED / SKIP"];

const ACTION_HINT: Record<Action, string> = {
  "ACCUMULATE ON DIPS":
    "Calendar window open, price in the lower 45% of its 3-year range and turnover clears the desk's liquidity gate. Scale in on red sessions.",
  "WAIT FOR TRIGGER":
    "Window opens next month, or the name still needs a liquid close inside the accumulation zone. Set alerts, do not pre-buy.",
  "EXTENDED / SKIP":
    "Calendar is closed to this name or the tape is already stretched. No new risk from a seasonal entry.",
};

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

/** Turnover in millions, the unit a PSX desk actually quotes. */
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

/** The one line the desk needs: buy, wait, or ignore. */
function playAction(t: TickerRecord): Action {
  const range = t.position.rangePositionPct;
  if (t.status === STATUS_ACTIVE && isLiquid(t)) return "ACCUMULATE ON DIPS";
  if (t.status === STATUS_ACTIVE || t.status === STATUS_WATCH) return "WAIT FOR TRIGGER";
  if (range <= 45 && isLiquid(t)) return "WAIT FOR TRIGGER";
  return "EXTENDED / SKIP";
}

function Stat({ label, value, hint, tone }: { label: string; value: string; hint: string; tone: string }) {
  return (
    <div className="rounded-2xl border border-slate-800/80 bg-slate-900/50 p-4">
      <span className="block text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
        {label}
      </span>
      <span className={`mt-1.5 block font-mono text-xl font-bold tabular-nums ${tone}`}>{value}</span>
      <span className="mt-1 block text-[10px] leading-snug text-slate-500">{hint}</span>
    </div>
  );
}

function QuestionCard({
  index,
  question,
  answer,
  children,
  className = "",
}: {
  index: number;
  question: string;
  answer: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={`flex flex-col rounded-2xl border border-slate-800/80 bg-slate-900/40 ${className}`}>
      <header className="border-b border-slate-800/80 px-4 py-3 sm:px-5">
        <div className="flex items-start gap-2.5">
          <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded border border-slate-700 bg-slate-950 font-mono text-[10px] font-bold text-emerald-300">
            {index}
          </span>
          <div className="min-w-0">
            <h2 className="text-[13px] font-bold tracking-tight text-slate-100">{question}</h2>
            <p className="mt-0.5 text-[11px] leading-snug text-slate-500">{answer}</p>
          </div>
        </div>
      </header>
      <div className="min-w-0 flex-1 p-4 sm:p-5">{children}</div>
    </section>
  );
}

function RangeBar({ value }: { value: number }) {
  const clamped = Math.max(0, Math.min(100, value));
  const tone = clamped <= 45 ? "bg-emerald-400/80" : clamped <= 65 ? "bg-amber-400/80" : "bg-rose-400/80";
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-800">
      <div className={`h-full rounded-full ${tone}`} style={{ width: `${clamped}%` }} />
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
  const [page, setPage] = useState(1);

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

  /** Liquid names sitting in the lower 45% of their 3-year range. */
  const playbookCandidates = useMemo(() => {
    const ranked = allTickers
      .filter((t) => isLiquid(t) && t.position.rangePositionPct <= 45)
      .sort((a, b) => {
        const actionRank = (t: TickerRecord) =>
          playAction(t) === "ACCUMULATE ON DIPS" ? 0 : playAction(t) === "WAIT FOR TRIGGER" ? 1 : 2;
        const byAction = actionRank(a) - actionRank(b);
        if (byAction !== 0) return byAction;
        return (
          b.accumulationWindowStats.forward60.winRatePct -
          a.accumulationWindowStats.forward60.winRatePct
        );
      });
    return ranked;
  }, [allTickers]);

  const actionCounts = useMemo(() => {
    const counts: Record<Action, number> = {
      "ACCUMULATE ON DIPS": 0,
      "WAIT FOR TRIGGER": 0,
      "EXTENDED / SKIP": 0,
    };
    for (const t of playbookCandidates) counts[playAction(t)] += 1;
    return counts;
  }, [playbookCandidates]);

  const liveSectors = useMemo(
    () => (data ? data.sectors.filter((s) => s.status !== STATUS_OFF) : []),
    [data],
  );

  const tickers = useMemo(() => {
    const needle = query.trim().toUpperCase();
    return allTickers.filter((t) => {
      if (statusFilter !== "ALL" && t.status !== statusFilter) return false;
      if (sectorFilter !== "ALL" && t.sector !== sectorFilter) return false;
      if (needle && !t.ticker.includes(needle) && !t.sector.toUpperCase().includes(needle)) return false;
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
  const topCandidates = playbookCandidates.slice(0, 12);

  return (
    <div className="space-y-6">
      {/* header */}
      <div className="flex flex-col gap-3 border-b border-slate-800 pb-5 lg:flex-row lg:items-end lg:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-lg font-bold tracking-tight text-slate-50 sm:text-xl">
              Seasonal Playbook
            </h1>
            <span className="rounded border border-emerald-500/40 bg-emerald-500/10 px-2 py-0.5 font-mono text-[10px] font-bold text-emerald-300">
              {meta.currentMonthLabel.toUpperCase()} · PRE-SEASON SCAN
            </span>
          </div>
          <p className="mt-1 max-w-3xl text-[11px] leading-relaxed text-slate-400">
            Which sector calendars are open right now, why the cycle is turning, and which liquid names
            are still cheap enough to buy. Pooled forward 60/90-session returns,{" "}
            {data.sessionRange.from ?? "—"} → {data.sessionRange.to ?? "—"}.
          </p>
        </div>
        <div className="font-mono text-[10px] text-slate-500 lg:text-right">
          <div className="tabular-nums">
            {summary.tickersAnalyzed} tickers · {data.sessionRange.sectors} sectors
          </div>
          <div>
            liquidity gate {rupees(turnoverGate)}/day · range ≤{" "}
            {meta.positionFilter.accumulationMaxRangePct?.toFixed(0) ?? 45}%
          </div>
          <div>generated {data.generatedAt.replace("T", " ").slice(0, 19)} UTC</div>
        </div>
      </div>

      {/* headline stats */}
      <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-5">
        <Stat
          label="Active Windows"
          value={String(summary.activeWindows)}
          hint="calendar + price both qualified"
          tone="text-emerald-400"
        />
        <Stat
          label="Sectors Active"
          value={String(summary.sectorsActive)}
          hint="≥30% of members in window"
          tone="text-emerald-400"
        />
        <Stat
          label="Sectors Watching"
          value={String(summary.sectorsWatching)}
          hint="window opens next month"
          tone="text-amber-300"
        />
        <Stat
          label="Buyable Candidates"
          value={String(actionCounts["ACCUMULATE ON DIPS"])}
          hint="liquid · in-range · window open"
          tone="text-emerald-300"
        />
        <Stat
          label="Off-Season"
          value={String(summary.sectorsOffSeason)}
          hint="no pre-season bid"
          tone="text-slate-400"
        />
      </div>

      {/* ------------------------------------------------ playbook summary */}
      <div className="grid gap-4 xl:grid-cols-2">
        <QuestionCard
          index={1}
          question="Active & upcoming seasons"
          answer="Sector calendars that are open now or open next month."
        >
          {liveSectors.length === 0 ? (
            <p className="py-6 text-center text-xs text-slate-500">
              No sector calendar is open this month — the playbook is in cash.
            </p>
          ) : (
            <ul className="space-y-2.5">
              {liveSectors.map((sector) => (
                <li
                  key={sector.sector}
                  className="rounded-xl border border-slate-800/80 bg-slate-950/60 px-3 py-2.5"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex min-w-0 items-center gap-2">
                      <span className="truncate font-mono text-sm font-bold text-slate-100">
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
                    <span className="font-mono text-[10px] tabular-nums text-slate-500">
                      {sector.activeCount} active · {sector.watchCount} watch
                    </span>
                  </div>
                  <div className="mt-2 flex flex-wrap gap-1 font-mono text-[9px]">
                    <span className="rounded border border-emerald-500/30 bg-emerald-500/10 px-1.5 py-0.5 text-emerald-300">
                      WINDOW {sector.accumulationMonths.join("·") || "—"}
                    </span>
                    <span className="rounded border border-amber-500/30 bg-amber-500/10 px-1.5 py-0.5 text-amber-300">
                      PEAK {sector.peakMonths.join("·") || "—"}
                    </span>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </QuestionCard>

        <QuestionCard
          index={2}
          question="Cyclical catalyst — why now"
          answer="The physical supply-chain reason the window exists, not a chart pattern."
        >
          {liveSectors.length === 0 ? (
            <p className="py-6 text-center text-xs text-slate-500">
              Nothing to buy before the next window opens.
            </p>
          ) : (
            <ul className="space-y-3">
              {liveSectors.map((sector) => (
                <li key={sector.sector} className="border-l-2 border-emerald-500/30 pl-3">
                  <div className="flex flex-wrap items-baseline justify-between gap-x-2 gap-y-1">
                    <span className="font-mono text-[11px] font-bold text-slate-200">{sector.sector}</span>
                    <span className="font-mono text-[10px] tabular-nums text-slate-500">
                      win 60d {sector.accumulationWindow.forward60.winRatePct.toFixed(0)}% · median{" "}
                      {signed(sector.accumulationWindow.forward60.medianPct, 1)}
                    </span>
                  </div>
                  <p className="mt-1 text-[11px] leading-relaxed text-slate-400">{sector.rationale}</p>
                </li>
              ))}
            </ul>
          )}
        </QuestionCard>

        <QuestionCard
          index={3}
          question="Top liquid candidates & timing"
          answer={`Liquid ≥ ${rupees(turnoverGate)}/day and in the lower ≤45% of their 3-year range, ranked by seasonal hit rate.`}
          className="xl:col-span-2"
        >
          {topCandidates.length === 0 ? (
            <p className="py-6 text-center text-xs text-slate-500">
              No liquid name is still inside its accumulation zone — wait for a pullback.
            </p>
          ) : (
            <>
              <ul className="space-y-2">
                {topCandidates.map((t) => {
                  const w60 = t.accumulationWindowStats.forward60;
                  const w90 = t.accumulationWindowStats.forward90;
                  const action = playAction(t);
                  return (
                    <li
                      key={`${t.sector}-${t.ticker}`}
                      className="rounded-xl border border-slate-800/80 bg-slate-950/60 p-3"
                    >
                      <div className="flex flex-wrap items-start justify-between gap-2">
                        <div className="min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="font-mono text-sm font-bold text-slate-50">{t.ticker}</span>
                            <span
                              className={`rounded border px-1.5 py-0.5 font-mono text-[9px] font-bold ${ACTION_TONE[action]}`}
                            >
                              {action}
                            </span>
                          </div>
                          <div className="mt-0.5 font-mono text-[10px] text-slate-500">
                            {t.sector} · PKR {t.lastClose.toFixed(2)} · {rupees(turnoverOf(t))}/day
                          </div>
                        </div>
                        <div className="text-right">
                          <div className="font-mono text-[10px] uppercase tracking-wide text-slate-500">
                            Range position
                          </div>
                          <div className="font-mono text-sm font-bold tabular-nums text-slate-200">
                            {t.position.rangePositionPct.toFixed(0)}%
                          </div>
                        </div>
                      </div>

                      <div className="mt-2">
                        <RangeBar value={t.position.rangePositionPct} />
                      </div>

                      <div className="mt-2.5 grid grid-cols-2 gap-2 sm:grid-cols-4">
                        {[
                          { label: "Win 60D", value: `${w60.winRatePct.toFixed(0)}%`, tone: "text-slate-100" },
                          {
                            label: "Median 60D",
                            value: signed(w60.medianPct, 1),
                            tone: w60.medianPct >= 0 ? "text-emerald-300" : "text-rose-300",
                          },
                          {
                            label: "Avg 90D",
                            value: signed(w90.avgPct, 1),
                            tone: w90.avgPct >= 0 ? "text-emerald-300" : "text-rose-300",
                          },
                          {
                            label: "3Y DD",
                            value: `${t.position.drawdownFromHighPct.toFixed(1)}%`,
                            tone: "text-slate-400",
                          },
                        ].map((cell) => (
                          <div
                            key={cell.label}
                            className="rounded-lg border border-slate-800/70 bg-slate-900/60 px-2 py-1.5"
                          >
                            <div className="text-[9px] uppercase tracking-wide text-slate-500">
                              {cell.label}
                            </div>
                            <div className={`font-mono text-xs font-bold tabular-nums ${cell.tone}`}>
                              {cell.value}
                            </div>
                          </div>
                        ))}
                      </div>
                    </li>
                  );
                })}
              </ul>
              {playbookCandidates.length > topCandidates.length && (
                <p className="mt-3 text-center font-mono text-[10px] text-slate-500">
                  +{playbookCandidates.length - topCandidates.length} more in-range liquid names in the
                  explorer below.
                </p>
              )}
            </>
          )}
        </QuestionCard>

        <QuestionCard
          index={4}
          question="Actionable execution status"
          answer="Every in-range liquid name is tagged with the only decision that matters."
          className="xl:col-span-2"
        >
          <div className="grid gap-3 sm:grid-cols-3">
            {ACTION_ORDER.map((action) => (
              <div
                key={action}
                className={`rounded-xl border px-3 py-3 ${ACTION_TONE[action]}`}
              >
                <div className="flex items-baseline justify-between gap-2">
                  <span className="font-mono text-[10px] font-bold tracking-wide">{action}</span>
                  <span className="font-mono text-lg font-bold tabular-nums">
                    {actionCounts[action]}
                  </span>
                </div>
                <p className="mt-1 text-[10px] leading-snug text-slate-400">{ACTION_HINT[action]}</p>
              </div>
            ))}
          </div>
          <p className="mt-3 text-[10px] leading-relaxed text-slate-500">
            Entry rule: a liquid close inside the lower half of the 3-year range while the calendar window
            is open. No chasing above the 45% range mark, and no position below the {rupees(turnoverGate)}{" "}
            turnover gate — the exit is the edge.
          </p>
        </QuestionCard>
      </div>

      {/* seasonality calendar */}
      <section className="rounded-2xl border border-slate-800/80 bg-slate-900/40 p-4 sm:p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-[13px] font-bold tracking-tight text-slate-100">Seasonality calendar</h2>
            <p className="text-[11px] text-slate-500">
              Mean forward 60-session return by month ·{" "}
              <span className="text-emerald-300">A</span> pre-season accumulation ·{" "}
              <span className="text-amber-300">P</span> peak season
            </p>
          </div>
          <div className="flex items-center gap-2 font-mono text-[10px] text-slate-500">
            <span className="h-2.5 w-4 rounded-sm bg-rose-500/25" /> weak
            <span className="h-2.5 w-4 rounded-sm bg-slate-800" /> flat
            <span className="h-2.5 w-4 rounded-sm bg-emerald-500/35" /> strong
          </div>
        </div>

        <div className="mt-3 overflow-x-auto overscroll-x-contain [-webkit-overflow-scrolling:touch]">
          <table className="w-full min-w-[760px] border-separate border-spacing-y-1 font-mono text-[10px]">
            <thead>
              <tr className="text-slate-500">
                <th className="sticky left-0 z-10 bg-slate-950 px-2 py-1 text-left font-semibold">
                  SECTOR
                </th>
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
                        className={`relative mx-0.5 rounded px-1 py-1.5 text-center tabular-nums ${heat(
                          cell.avgForward60Pct,
                          cell.samples,
                        )}`}
                      >
                        <span className="block font-bold">{cell.avgForward60Pct.toFixed(1)}</span>
                        <span className="block text-[8px] opacity-70">{cell.winRatePct.toFixed(0)}%</span>
                        {cell.isAccumulation && (
                          <span className="absolute right-0.5 top-0 text-[8px] font-black text-emerald-300">
                            A
                          </span>
                        )}
                        {cell.isPeak && (
                          <span className="absolute bottom-0 right-0.5 text-[8px] font-black text-amber-300">
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
      </section>

      {/* sector cards */}
      <section className="rounded-2xl border border-slate-800/80 bg-slate-900/40 p-4 sm:p-5">
        <h2 className="text-[13px] font-bold tracking-tight text-slate-100">Sector window scorecard</h2>
        <p className="text-[11px] text-slate-500">
          Pooled accumulation-window statistics for all {data.sectors.length} sectors.
        </p>
        <div className="mt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {data.sectors.map((sector) => (
            <div
              key={sector.sector}
              className="flex flex-col rounded-xl border border-slate-800/80 bg-slate-950/60 p-3.5"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="truncate font-mono text-sm font-bold text-slate-50">{sector.sector}</div>
                  <div className="font-mono text-[10px] tabular-nums text-slate-500">
                    {sector.members} names · {sector.activeCount} active · {sector.watchCount} watch
                  </div>
                </div>
                <span
                  className={`shrink-0 rounded border px-1.5 py-0.5 font-mono text-[9px] font-bold ${statusTone(
                    sector.status,
                  )}`}
                >
                  {shortStatus(sector.status)}
                </span>
              </div>

              <div className="mt-2.5 flex flex-wrap gap-1 font-mono text-[9px]">
                <span className="rounded border border-emerald-500/30 bg-emerald-500/10 px-1.5 py-0.5 text-emerald-300">
                  ACC {sector.accumulationMonths.join("·") || "—"}
                </span>
                <span className="rounded border border-amber-500/30 bg-amber-500/10 px-1.5 py-0.5 text-amber-300">
                  PEAK {sector.peakMonths.join("·") || "—"}
                </span>
              </div>

              <div className="mt-3 grid grid-cols-4 gap-1 text-center font-mono text-[10px]">
                <div>
                  <div className="text-slate-500">WIN 60</div>
                  <div className="font-bold tabular-nums text-slate-100">
                    {sector.accumulationWindow.forward60.winRatePct.toFixed(0)}%
                  </div>
                </div>
                <div>
                  <div className="text-slate-500">MED 60</div>
                  <div
                    className={`font-bold tabular-nums ${
                      sector.accumulationWindow.forward60.medianPct >= 0
                        ? "text-emerald-300"
                        : "text-rose-300"
                    }`}
                  >
                    {signed(sector.accumulationWindow.forward60.medianPct, 1)}
                  </div>
                </div>
                <div>
                  <div className="text-slate-500">AVG 90</div>
                  <div
                    className={`font-bold tabular-nums ${
                      sector.accumulationWindow.forward90.avgPct >= 0 ? "text-emerald-300" : "text-rose-300"
                    }`}
                  >
                    {signed(sector.accumulationWindow.forward90.avgPct, 1)}
                  </div>
                </div>
                <div>
                  <div className="text-slate-500">N</div>
                  <div className="font-bold tabular-nums text-slate-300">
                    {sector.accumulationWindow.forward60.samples}
                  </div>
                </div>
              </div>

              <p className="mt-3 border-t border-slate-800/80 pt-2.5 text-[10px] leading-snug text-slate-500">
                {sector.rationale}
              </p>
            </div>
          ))}
        </div>
      </section>

      {/* ticker explorer */}
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

        {/* mobile card stack */}
        <ul className="divide-y divide-slate-800/70 md:hidden">
          {pageRows.map((t) => {
            const w60 = t.accumulationWindowStats.forward60;
            const w90 = t.accumulationWindowStats.forward90;
            const action = playAction(t);
            return (
              <li key={`${t.sector}-${t.ticker}`} className="p-3">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="flex items-center gap-1.5">
                      <span className="font-mono text-sm font-bold text-slate-50">{t.ticker}</span>
                      <span
                        className={`rounded border px-1.5 py-0.5 font-mono text-[9px] font-bold ${ACTION_TONE[action]}`}
                      >
                        {action}
                      </span>
                    </div>
                    <div className="mt-0.5 font-mono text-[10px] text-slate-500">
                      {t.sector} · PKR {t.lastClose.toFixed(2)}
                    </div>
                  </div>
                  <span
                    className={`shrink-0 rounded border px-1.5 py-0.5 font-mono text-[9px] font-bold ${statusTone(
                      t.status,
                    )}`}
                  >
                    {shortStatus(t.status)}
                  </span>
                </div>

                <div className="mt-2">
                  <RangeBar value={t.position.rangePositionPct} />
                  <div className="mt-1 flex justify-between font-mono text-[9px] text-slate-500">
                    <span>3Y range {t.position.rangePositionPct.toFixed(0)}%</span>
                    <span>turnover {rupees(turnoverOf(t))}</span>
                  </div>
                </div>

                <div className="mt-2 grid grid-cols-3 gap-1.5 font-mono text-[10px]">
                  <div className="rounded border border-slate-800/70 bg-slate-950/60 px-2 py-1">
                    <div className="text-[8px] uppercase text-slate-500">Win 60D</div>
                    <div className="font-bold tabular-nums text-slate-200">
                      {w60.winRatePct.toFixed(0)}%
                    </div>
                  </div>
                  <div className="rounded border border-slate-800/70 bg-slate-950/60 px-2 py-1">
                    <div className="text-[8px] uppercase text-slate-500">Med 60D</div>
                    <div
                      className={`font-bold tabular-nums ${
                        w60.medianPct >= 0 ? "text-emerald-300" : "text-rose-300"
                      }`}
                    >
                      {signed(w60.medianPct, 1)}
                    </div>
                  </div>
                  <div className="rounded border border-slate-800/70 bg-slate-950/60 px-2 py-1">
                    <div className="text-[8px] uppercase text-slate-500">Avg 90D</div>
                    <div
                      className={`font-bold tabular-nums ${
                        w90.avgPct >= 0 ? "text-emerald-300" : "text-rose-300"
                      }`}
                    >
                      {signed(w90.avgPct, 1)}
                    </div>
                  </div>
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
