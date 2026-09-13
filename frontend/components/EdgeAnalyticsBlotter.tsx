"use client";

import { useMemo } from "react";
import {
  summarizeEdge,
  type BacktestRow,
  type EdgeSummary,
} from "@/lib/queries";

function fmtPct(value: number | null, digits = 1): string {
  return value == null
    ? "—"
    : `${value >= 0 ? "+" : ""}${value.toFixed(digits)}%`;
}

function fmtR(value: number | null): string {
  return value == null ? "—" : `${value >= 0 ? "+" : ""}${value.toFixed(2)}R`;
}

function fmtPf(value: number | null): string {
  if (value == null) return "—";
  if (!Number.isFinite(value)) return "∞";
  return value.toFixed(2);
}

function pfColor(value: number | null): string {
  if (value == null) return "text-zinc-600";
  if (!Number.isFinite(value)) return "text-emerald-400";
  if (value >= 1.25) return "text-emerald-400";
  if (value >= 1.0) return "text-sky-300";
  return "text-rose-400";
}

function expectancyBadge(value: number | null) {
  if (value == null) {
    return (
      <span className="font-mono tabular-nums text-zinc-600">—</span>
    );
  }
  const cls =
    value > 0
      ? "bg-emerald-500/10 text-emerald-300 ring-emerald-500/30"
      : value < 0
        ? "bg-rose-500/10 text-rose-300 ring-rose-500/30"
        : "bg-zinc-800 text-zinc-400 ring-zinc-700";
  return (
    <span
      className={`inline-block rounded px-1.5 py-0.5 font-mono tabular-nums ring-1 ${cls}`}
    >
      {fmtR(value)}
    </span>
  );
}

export default function EdgeAnalyticsBlotter({
  rows,
  tableMissing,
}: {
  rows: BacktestRow[];
  tableMissing: boolean;
}) {
  // 30-session realized window: only rows whose signal session falls in the
  // trailing 30 distinct trading sessions of stored evaluations.
  const windowRows: BacktestRow[] = useMemo(() => {
    const days = Array.from(
      new Set(rows.map((r) => r.tradeDate))
    ).sort().reverse().slice(0, 30);
    const daySet = new Set(days);
    return rows.filter((r) => daySet.has(r.tradeDate));
  }, [rows]);
  const summary: EdgeSummary[] = useMemo(
    () => summarizeEdge(windowRows),
    [windowRows]
  );

  if (tableMissing) {
    return (
      <div className="px-3 py-6 text-center">
        <p className="font-mono text-xs uppercase tracking-widest text-amber-300">
          [SCHEMA PENDING: RUN SCHEMA.SQL IN SUPABASE]
        </p>
        <p className="mt-1 text-[11px] text-zinc-600">
          The signal_backtest_performance table does not exist yet.
        </p>
      </div>
    );
  }

  if (rows.length === 0) {
    return (
      <div className="px-3 py-6 text-center">
        <p className="font-mono text-xs uppercase tracking-widest text-sky-300">
          [EDGE LAB: ACCUMULATING FORWARD SESSIONS]
        </p>
        <p className="mt-1 text-[11px] text-zinc-600">
          The walk-forward seed re-simulates the quant engine over the trailing
          30 sessions and scores every signal 2R-target-vs-stop against stored
          EOD history. Win rates populate on the first pipeline pass.
        </p>
      </div>
    );
  }

  const totalEvaluated = windowRows.length;
  const totalResolved = summary.reduce((a, s) => a + s.resolved, 0);
  const totalHits = Math.round(
    (summary.reduce((a, s) => a + (s.hitRatePct ?? 0) * s.resolved, 0)) / 100
  );
  const windowDays = new Set(windowRows.map((r) => r.tradeDate)).size;

  return (
    <section>
      <div className="flex items-center justify-between border-b border-zinc-800 px-3 py-2">
        <h2 className="text-[10px] font-medium uppercase tracking-widest text-zinc-600">
          Historical Edge Lab - 30-Session Realized Win Rates
        </h2>
        <span className="font-mono text-[11px] tabular-nums text-zinc-500">
          {totalEvaluated} EVAL · {totalResolved} RESOLVED ·{" "}
          {windowDays}D WINDOW
        </span>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[760px] border-collapse text-xs">
          <thead>
            <tr className="border-b border-zinc-800 bg-[#0c1017] text-left text-[10px] uppercase tracking-widest text-zinc-600">
              <th className="px-3 py-2 font-medium">Signal Type</th>
              <th className="px-2 py-2 text-right font-medium">N</th>
              <th className="px-2 py-2 text-right font-medium">Resolved</th>
              <th className="px-2 py-2 text-right font-medium">Hit 2R</th>
              <th className="px-2 py-2 text-right font-medium">Stopped</th>
              <th className="px-2 py-2 text-right font-medium">PF</th>
              <th className="px-2 py-2 text-right font-medium">Avg T+5</th>
              <th className="px-2 py-2 text-right font-medium">Avg T+10</th>
              <th className="px-2 py-2 text-right font-medium">Avg T+20</th>
              <th className="px-2 py-2 text-right font-medium">MFE / MAE</th>
              <th className="px-3 py-2 text-right font-medium">Expectancy</th>
            </tr>
          </thead>
          <tbody>
            {summary.map((s) => (
              <tr
                key={s.signalType}
                className="border-b border-zinc-900 hover:bg-zinc-900/40"
              >
                <td className="px-3 py-1.5 font-mono text-[11px] font-semibold text-zinc-100">
                  {s.signalType.replace(/_/g, " ")}
                </td>
                <td className="px-2 py-1.5 text-right font-mono tabular-nums text-zinc-300">
                  {s.signals}
                </td>
                <td className="px-2 py-1.5 text-right font-mono tabular-nums text-zinc-400">
                  {s.resolved}
                </td>
                <td
                  className={`px-2 py-1.5 text-right font-mono tabular-nums ${
                    (s.hitRatePct ?? 0) >= 50 ? "text-emerald-400" : "text-zinc-300"
                  }`}
                >
                  {s.hitRatePct == null ? "—" : `${s.hitRatePct.toFixed(1)}%`}
                </td>
                <td
                  className={`px-2 py-1.5 text-right font-mono tabular-nums ${
                    (s.stoppedPct ?? 0) >= 50 ? "text-rose-400" : "text-zinc-300"
                  }`}
                >
                  {s.stoppedPct == null ? "—" : `${s.stoppedPct.toFixed(1)}%`}
                </td>
                <td
                  className={`px-2 py-1.5 text-right font-mono tabular-nums font-semibold ${pfColor(
                    s.profitFactor
                  )}`}
                >
                  {fmtPf(s.profitFactor)}
                </td>
                <td className="px-2 py-1.5 text-right font-mono tabular-nums text-zinc-300">
                  {fmtPct(s.avgT5Pct)}
                </td>
                <td className="px-2 py-1.5 text-right font-mono tabular-nums text-zinc-300">
                  {fmtPct(s.avgT10Pct)}
                </td>
                <td className="px-2 py-1.5 text-right font-mono tabular-nums text-zinc-300">
                  {fmtPct(s.avgT20Pct)}
                </td>
                <td className="px-2 py-1.5 text-right font-mono tabular-nums text-zinc-500">
                  <span className="text-emerald-500/80">{fmtPct(s.avgMfePct, 0)}</span>
                  {" / "}
                  <span className="text-rose-500/80">{fmtPct(s.avgMaePct, 0)}</span>
                </td>
                <td className="px-3 py-1.5 text-right">
                  {expectancyBadge(s.expectancyR)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="border-t border-zinc-900 px-3 py-2">
        <p className="font-mono text-[10px] leading-relaxed text-zinc-600">
          30-session realized window · Convention: target = entry + 2R (stop
          distance), same-session stop/target touch resolves as stop
          (conservative). Expectancy E[R] = hit%×2 − (1−hit%). Profit factor
          = gross wins ÷ gross losses in R units (≥1.25 green, ≥1.00 blue).
          Unresolved windows keep NULL flags. · Latest individual evaluations:{" "}
          {totalHits > 0 ? "green tail below" : "pending"}
          {windowRows
            .filter((r) => r.hitTarget != null || r.returnT5Pct != null)
            .slice(0, 3)
            .map((r) => (
              <span key={r.signalId} className="mt-1 block text-zinc-500">
                ▸ {r.tradeDate} {r.ticker} [{r.signalType}] t5{" "}
                {fmtPct(r.returnT5Pct)} · {r.hitTarget == null
                  ? "unresolved"
                  : r.hitTarget
                    ? "HIT 2R"
                    : r.stoppedOut
                      ? "STOPPED"
                      : "OPEN"}
              </span>
            ))}
        </p>
      </div>
    </section>
  );
}
