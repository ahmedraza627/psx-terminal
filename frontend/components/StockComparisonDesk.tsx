"use client";

import { Fragment, useEffect, useMemo, useState } from "react";
import {
  Badge,
  DataTable,
  DeskFrame,
  DivergeBar,
  IdleState,
  Row,
} from "@/components/ui/primitives";
import {
  fmtPct,
  fmtPkrB,
  fmtPkrM,
  fmtPrice,
  fmtX,
} from "@/components/ui/format";
import {
  fetchSignalHistory,
  fetchTickerOhlcv,
  type FundamentalsRow,
  type HistSignal,
  type OhlcvRow,
} from "@/lib/deskQueries";
import type { KiborRow } from "@/lib/queries";
import type { ResearchRow } from "@/components/ResearchDeskBlotter";

/**
 * Bloomberg-grade head-to-head comparison blotter.
 *
 * Metric rows are grouped into machined bands — SESSION CONTEXT, VALUATION,
 * BALANCE-SHEET RISK, LIQUIDITY & FLOW. Every rankable row highlights the
 * quantitatively superior ticker (bull green) and renders a signed delta bar
 * vs the cross-ticker mean, so superiority reads at a glance.
 *
 * Data honesty: P/B, EV/EBITDA, D/E and interest coverage render as "—"
 * until a fundamentals feed publishes them — never estimated. Per-ticker
 * clearing net PKR is not published by NCCPL (sector-level only), so the
 * institutional column counts actionable signal events across the trailing
 * 30 stored sessions instead, and says so.
 */

// --------------------------------------------------------------- //
// Contract (page.tsx): fundamentals / kibor / research /           //
// initialPicked — all optional; every feed degrades gracefully.    //
// --------------------------------------------------------------- //
interface Props {
  fundamentals?: FundamentalsRow[];
  kibor?: KiborRow[];
  research?: ResearchRow[];
  initialPicked?: string[];
}

interface Cell {
  text: string;
  /** Raw numeric value driving winner highlight + delta bar; null = n/a. */
  value: number | null;
}

type Group =
  | "SESSION CONTEXT"
  | "VALUATION"
  | "BALANCE-SHEET RISK"
  | "LIQUIDITY & FLOW";

interface MetricDef {
  id: number;
  label: string;
  group: Group;
  /** Winner = lowest value (P/E, P/B multiples). Default: highest wins. */
  lowerWins?: boolean;
  /** Row renders a 30-session sparkline instead of a scalar. */
  spark?: boolean;
  /** Row renders a semantic flag instead of a ranked scalar. */
  flag?: boolean;
  /** Row never highlights a winner (context / informational). */
  context?: boolean;
}

const METRICS: MetricDef[] = [
  { id: 0, label: "LTP (PKR)", group: "SESSION CONTEXT", context: true },
  { id: 1, label: "5D Change %", group: "SESSION CONTEXT", context: true },
  { id: 2, label: "30S Trend", group: "SESSION CONTEXT", spark: true, context: true },
  { id: 3, label: "Vol x SMA20", group: "SESSION CONTEXT", context: true },
  { id: 4, label: "TTM P/E", group: "VALUATION", lowerWins: true },
  { id: 5, label: "P/B", group: "VALUATION", lowerWins: true },
  { id: 6, label: "EV/EBITDA", group: "VALUATION", lowerWins: true },
  { id: 7, label: "Dividend Yield %", group: "VALUATION" },
  { id: 8, label: "Intrinsic Value (PSX-MF)", group: "VALUATION", context: true },
  { id: 9, label: "Valuation Spread", group: "VALUATION" },
  { id: 10, label: "Debt / Equity", group: "BALANCE-SHEET RISK", lowerWins: true },
  { id: 11, label: "Interest Coverage", group: "BALANCE-SHEET RISK" },
  { id: 12, label: "KIBOR +300bps EPS Impact", group: "BALANCE-SHEET RISK" },
  { id: 13, label: "Balance-Sheet Flag", group: "BALANCE-SHEET RISK", flag: true, context: true },
  { id: 14, label: "Market Cap (PKR)", group: "LIQUIDITY & FLOW", context: true },
  { id: 15, label: "30D Avg Turnover (PKR)", group: "LIQUIDITY & FLOW" },
  { id: 16, label: "Free-Float Daily Turnover %", group: "LIQUIDITY & FLOW" },
  { id: 17, label: "30D Inst Signal Events", group: "LIQUIDITY & FLOW" },
];

const GROUPS: Group[] = [
  "SESSION CONTEXT",
  "VALUATION",
  "BALANCE-SHEET RISK",
  "LIQUIDITY & FLOW",
];

const CELL_COUNT = METRICS.length;

// --------------------------------------------------------------- //
// Per-ticker derived market context (self-fetched, settle-safe).   //
// --------------------------------------------------------------- //
interface TickerQuote {
  ltp: number | null;
  chg5dPct: number | null;
  /** Chronological closes across the trailing 30 stored sessions. */
  closes: number[];
  volVsSma20: number | null;
}

function buildQuote(rows: OhlcvRow[]): TickerQuote {
  const chrono = rows.slice().reverse(); // oldest -> newest
  const closes = chrono
    .map((r) => r.close)
    .filter((c): c is number => c != null);
  const ltp = closes.length > 0 ? closes[closes.length - 1] : null;
  const chg5dPct =
    closes.length >= 5 && closes[closes.length - 5] > 0
      ? ((closes[closes.length - 1] - closes[closes.length - 5]) /
          closes[closes.length - 5]) *
        100
      : null;
  const vols = chrono
    .slice(-21)
    .map((r) => r.volume)
    .filter((v): v is number => v != null);
  let volVsSma20: number | null = null;
  if (vols.length === 21) {
    const [latest, ...window] = vols;
    const sma = window.reduce((a, b) => a + b, 0) / window.length;
    volVsSma20 = sma > 0 ? latest / sma : null;
  }
  return { ltp, chg5dPct, closes, volVsSma20 };
}

function fmtPkrAdaptive(v: number | null): string {
  if (v == null) return "—";
  if (Math.abs(v) >= 1e9) return fmtPkrB(v, 2);
  if (Math.abs(v) >= 1e6) return fmtPkrM(v, 0);
  return Math.round(v).toLocaleString("en-US");
}

function flagTone(flag: string): string {
  const f = flag.toUpperCase();
  if (f.includes("CONSERVATIVE")) return "text-bull";
  if (f.includes("AGGRESSIVE")) return "text-bear";
  if (f.includes("MODERATE")) return "text-warn";
  return "text-muted";
}

/** 30-session sparkline — muted bull/bear line, no glow. */
function Spark({ closes, positive }: { closes: number[]; positive: boolean }) {
  if (closes.length < 2) {
    return <span className="font-mono text-[10px] text-ghost">—</span>;
  }
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const span = max - min || 1;
  const pts = closes
    .map(
      (c, i) =>
        `${(i / (closes.length - 1)) * 100},${26 - ((c - min) / span) * 22}`
    )
    .join(" ");
  return (
    <svg
      viewBox="0 0 100 28"
      preserveAspectRatio="none"
      className="ml-auto h-7 w-24"
      aria-label="30-session price trend"
    >
      <polyline
        points={pts}
        fill="none"
        stroke={positive ? "#26A69A" : "#F23645"}
        strokeWidth="1.25"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}

/** Group band separator spanning the blotter width. */
function GroupRow({ label, span }: { label: string; span: number }) {
  return (
    <tr className="border-b border-hairline bg-panel">
      <td
        colSpan={span}
        className="px-2.5 py-0.5 font-mono text-[9px] font-semibold uppercase tracking-[0.2em] text-ghost"
      >
        {label}
      </td>
    </tr>
  );
}

interface Col {
  ticker: string;
  sector: string | null;
  cells: Cell[];
}

/** Winner index per metric: needs ≥2 distinct ranked values to highlight. */
function winnerIdx(cols: Col[], id: number, lowerWins?: boolean): number {
  const ranked = cols
    .map((c, idx) => ({ idx, v: c.cells[id]?.value ?? null }))
    .filter((x): x is { idx: number; v: number } => x.v != null);
  if (ranked.length < 2) return -1;
  const distinct = new Set(ranked.map((x) => x.v)).size;
  if (distinct < 2) return -1;
  return ranked.reduce((a, b) =>
    lowerWins ? (b.v < a.v ? b : a) : b.v > a.v ? b : a
  ).idx;
}

function rowMaxAbs(cols: Col[], id: number): number {
  const vs = cols
    .map((c) => c.cells[id]?.value ?? null)
    .filter((v): v is number => v != null);
  if (vs.length < 2) return 0;
  const mean = vs.reduce((a, b) => a + b, 0) / vs.length;
  return Math.max(0, ...vs.map((v) => Math.abs(v - mean)));
}

function rowMean(cols: Col[], id: number): number {
  const vs = cols
    .map((c) => c.cells[id]?.value ?? null)
    .filter((v): v is number => v != null);
  return vs.reduce((a, b) => a + b, 0) / vs.length;
}

export default function StockComparisonDesk({
  fundamentals = [],
  kibor = [],
  research = [],
  initialPicked,
}: Props) {
  const universe = useMemo(
    () =>
      fundamentals
        .slice()
        .sort((a, b) => (b.marketCapPkr ?? 0) - (a.marketCapPkr ?? 0)),
    [fundamentals]
  );

  const [q, setQ] = useState("");
  const [picked, setPicked] = useState<string[]>([]);

  // Command-bar preselection (COMP <SYM> <SYM>) — never clobbers user edits.
  useEffect(() => {
    const ip = initialPicked;
    if (ip && ip.length >= 2) {
      setPicked((prev) => (prev.length === 0 ? ip.slice(0, 3) : prev));
    }
  }, [initialPicked]);

  const matches = useMemo(() => {
    const needle = q.trim().toUpperCase();
    if (!needle) return universe.slice(0, 10);
    return universe
      .filter(
        (f) =>
          f.ticker.includes(needle) ||
          (f.sectorName ?? "").toUpperCase().includes(needle)
      )
      .slice(0, 10);
  }, [universe, q]);

  const toggle = (t: string) =>
    setPicked((prev) =>
      prev.includes(t)
        ? prev.filter((x) => x !== t)
        : prev.length >= 3
          ? prev
          : [...prev, t]
    );

  // Self-fetched market context per picked ticker (30-session OHLCV).
  const [quotes, setQuotes] = useState<Map<string, TickerQuote>>(new Map());
  useEffect(() => {
    let cancelled = false;
    if (picked.length === 0) {
      setQuotes(new Map());
      return;
    }
    (async () => {
      const settled = await Promise.allSettled(
        picked.map((t) => fetchTickerOhlcv(t, 30))
      );
      if (cancelled) return;
      const map = new Map<string, TickerQuote>();
      settled.forEach((res, i) => {
        if (res.status === "fulfilled") map.set(picked[i], buildQuote(res.value));
      });
      setQuotes(map);
    })();
    return () => {
      cancelled = true;
    };
  }, [picked]);

  // Trailing-30-session actionable signals → institutional event counts.
  const [histSignals, setHistSignals] = useState<HistSignal[]>([]);
  useEffect(() => {
    let cancelled = false;
    fetchSignalHistory(31).then((rows) => {
      if (!cancelled) setHistSignals(rows);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const instEventsByTicker = useMemo(() => {
    const map = new Map<string, number>();
    for (const s of histSignals) {
      map.set(s.ticker, (map.get(s.ticker) ?? 0) + 1);
    }
    return map;
  }, [histSignals]);

  // ------------------------------------------------------------- //
  // Column build: one Cell per metric id, strictly from real data. //
  // ------------------------------------------------------------- //
  const cols: Col[] = useMemo(() => {
    const kiborBy = new Map(kibor.map((k) => [k.ticker.toUpperCase(), k]));
    const researchBy = new Map(research.map((r) => [r.ticker.toUpperCase(), r]));
    return picked
      .map((t) => universe.find((f) => f.ticker === t))
      .filter((f): f is FundamentalsRow => f != null)
      .map((f) => {
        const k = kiborBy.get(f.ticker);
        const r = researchBy.get(f.ticker);
        const quote = quotes.get(f.ticker);
        const instCount = instEventsByTicker.get(f.ticker) ?? 0;
        const turnover30d =
          f.volume30dAvg != null && f.closePrice != null
            ? f.volume30dAvg * f.closePrice
            : null;
        const ffTurnover =
          f.volume30dAvg != null && f.freeFloat != null && f.freeFloat > 0
            ? (f.volume30dAvg / f.freeFloat) * 100
            : null;
        const cells: Cell[] = new Array(CELL_COUNT);
        const put = (id: number, text: string, value: number | null) => {
          cells[id] = { text, value };
        };

        // SESSION CONTEXT
        put(0, fmtPrice(quote?.ltp), quote?.ltp ?? null);
        put(1, fmtPct(quote?.chg5dPct ?? null, 1), quote?.chg5dPct ?? null);
        put(2, quote?.closes.length ? "" : "—", null); // spark row
        put(
          3,
          quote?.volVsSma20 != null ? `${quote.volVsSma20.toFixed(2)}x` : "—",
          quote?.volVsSma20 ?? null
        );
        // VALUATION
        put(
          4,
          f.peRatio != null && f.peRatio > 0 ? fmtX(f.peRatio, 1) : "—",
          f.peRatio != null && f.peRatio > 0 ? f.peRatio : null
        );
        put(5, f.pbRatio != null ? fmtX(f.pbRatio, 1) : "—", f.pbRatio ?? null); // P/B: renders once a feed publishes book value
        put(6, f.evEbitda != null ? fmtX(f.evEbitda, 1) : "—", f.evEbitda ?? null); // EV/EBITDA: same
        put(
          7,
          f.dividendYield != null ? fmtPct(f.dividendYield, 1, false) : "—",
          f.dividendYield
        );
        put(
          8,
          fmtPrice(r?.intrinsicValuePkr ?? null),
          r?.intrinsicValuePkr ?? null
        );
        put(
          9,
          fmtPct(r?.valuationDiscountPct ?? null, 1),
          r?.valuationDiscountPct ?? null
        );
        // BALANCE-SHEET RISK
        put(10, "—", null); // D/E: no published feed yet
        put(11, "—", null); // Interest coverage: no published feed yet
        put(
          12,
          k?.epsExpansion300bpsPct != null
            ? fmtPct(k.epsExpansion300bpsPct, 1)
            : "—",
          k?.epsExpansion300bpsPct ?? null
        );
        put(13, r?.balanceSheetRiskFlag ?? "—", null);
        // LIQUIDITY & FLOW
        put(14, fmtPkrAdaptive(f.marketCapPkr), f.marketCapPkr);
        put(15, fmtPkrAdaptive(turnover30d), turnover30d);
        put(
          16,
          ffTurnover != null ? `${ffTurnover.toFixed(2)}%` : "—",
          ffTurnover
        );
        put(
          17,
          instCount > 0 ? `${instCount}` : "—",
          instCount > 0 ? instCount : null
        );
        return { ticker: f.ticker, sector: f.sectorName, cells };
      });
  }, [picked, universe, kibor, research, quotes, instEventsByTicker]);

  if (universe.length === 0) {
    return (
      <DeskFrame title="Head-to-Head Comparison Desk">
        <IdleState
          tone="warn"
          headline="[COMPARISON DESK: AWAITING FUNDAMENTALS SNAPSHOT]"
          detail="psx_fundamentals has no rows yet — run the research pipeline pass to enable side-by-side screens."
        />
      </DeskFrame>
    );
  }

  const span = 1 + cols.length;

  return (
    <DeskFrame
      title="Head-to-Head Comparison Desk"
      right={
        <span className="font-mono text-[10px] uppercase tracking-wider text-ghost">
          PICK 2-3 · {picked.length}/3 · ⌘K COMP &lt;SYM&gt; &lt;SYM&gt;
        </span>
      }
      footer={
        <p className="font-mono text-[10px] leading-relaxed text-ghost">
          Green = quantitatively superior on the row; delta bars show each
          ticker&apos;s signed deviation from the cross-ticker mean. Lower is
          better on P/E / P/B / EV-EBITDA / D-E multiples. P/B, EV/EBITDA, D/E
          and interest coverage render when a fundamentals feed publishes them
          — never estimated. Intrinsic value and spread come from
          psx_equity_research (PSX-MF model). 30D Inst Signal Events counts
          actionable institutional signal rows in the trailing 30 stored
          sessions (NCCPL clearing is sector-level; per-ticker net PKR is not
          published). 30D Avg Turnover = volume_30d_avg × LTP.
        </p>
      }
    >
      {/* Picker strip */}
      <div className="border-b border-hairline px-2.5 py-1.5">
        <input
          type="text"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="ADD SYMBOL / SECTOR…"
          aria-label="Add comparison ticker"
          className="h-7 w-full max-w-xs rounded-[2px] border border-hairline bg-obsidian px-2 font-mono text-[11px] uppercase tracking-wider text-ink placeholder:text-ghost focus:border-info/50 focus:outline-none"
        />
        <div className="mt-1.5 flex flex-wrap gap-1">
          {matches.map((f) => (
            <button
              key={f.ticker}
              onClick={() => toggle(f.ticker)}
              title={f.sectorName ?? undefined}
              className={`rounded-[2px] px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider ring-1 ${
                picked.includes(f.ticker)
                  ? "bg-info/10 text-info ring-info/30"
                  : "bg-panel text-muted ring-hairline hover:text-ink"
              }`}
            >
              {f.ticker}
            </button>
          ))}
          {picked.length > 0 && (
            <button
              onClick={() => setPicked([])}
              className="rounded-[2px] px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-bear hover:underline"
            >
              CLEAR
            </button>
          )}
        </div>
      </div>

      {cols.length < 2 ? (
        <IdleState
          headline="SELECT AT LEAST TWO SYMBOLS"
          detail="Side-by-side metric bands appear instantly — context, valuation, balance-sheet risk and liquidity blocks."
        />
      ) : (
        <DataTable
          minWidth={680}
          columns={[
            { label: "Metric", width: "24%" },
            ...cols.map((c) => ({ label: c.ticker, align: "right" as const })),
          ]}
        >
          {GROUPS.map((group) => {
            const metrics = METRICS.filter((m) => m.group === group);
            return (
              <Fragment key={group}>
                <GroupRow label={group} span={span} />
                {metrics.map((m) => {
                  const win =
                    m.context || m.flag
                      ? -1
                      : winnerIdx(cols, m.id, m.lowerWins);
                  const maxAbs = m.spark ? 0 : rowMaxAbs(cols, m.id);
                  const mean = m.spark ? 0 : rowMean(cols, m.id);
                  return (
                    <Row key={m.label}>
                      <td className="px-2.5 py-1 font-mono text-[10px] uppercase tracking-wider text-muted">
                        {m.label}
                      </td>
                      {cols.map((c, i) => {
                        const cell = c.cells[m.id];
                        const text = cell?.text || "—";
                        const cls = m.flag
                          ? cell && cell.text !== "—"
                            ? flagTone(cell.text)
                            : "text-ghost"
                          : win === i
                            ? "text-bull font-semibold"
                            : "text-ink";
                        return (
                          <td
                            key={c.ticker}
                            className={`px-2 py-1 text-right font-mono text-[11px] tabular-nums ${cls}`}
                          >
                            {m.spark ? (
                              <Spark
                                closes={quotes.get(c.ticker)?.closes ?? []}
                                positive={
                                  (quotes.get(c.ticker)?.chg5dPct ?? 0) >= 0
                                }
                              />
                            ) : (
                              <>
                                {text}
                                {!m.context && maxAbs > 0 && cell?.value != null && (
                                  <span className="mt-0.5 block">
                                    <DivergeBar
                                      value={cell.value - mean}
                                      maxAbs={maxAbs}
                                    />
                                  </span>
                                )}
                              </>
                            )}
                          </td>
                        );
                      })}
                    </Row>
                  );
                })}
              </Fragment>
            );
          })}
          {/* Sector footer row */}
          <Row>
            <td className="px-2.5 py-1 font-mono text-[10px] uppercase tracking-wider text-muted">
              Sector
            </td>
            {cols.map((c) => (
              <td key={c.ticker} className="px-2 py-1 text-right">
                <Badge tone="neutral">{(c.sector ?? "—").toUpperCase()}</Badge>
              </td>
            ))}
          </Row>
        </DataTable>
      )}
    </DeskFrame>
  );
}
