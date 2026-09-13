"use client";

import FeedErrorPill from "./FeedErrorPill";
import type { DataStatus } from "@/lib/queries";
import {
  KE_REQUIRED,
  PIB_YIELD_PCT,
  DIV_GROWTH_PCT,
  sectorTargetPe,
} from "@/lib/valuation";

export interface ResearchRow {
  tradeDate: string;
  ticker: string;
  alphaScore: number;
  intrinsicValuePkr: number | null;
  valuationDiscountPct: number | null;
  valuationStatus: string;
  balanceSheetRiskFlag: string | null;
  targetPeUsed: number | null;
  dividendFloorPkr: number | null;
  modelVersion: string | null;
}

function fmtPrice(value: number | null): string {
  return value == null ? "—" : value.toFixed(2);
}

function fmtDiscount(value: number | null): string {
  if (value == null) return "—";
  return `${value >= 0 ? "+" : "−"}${Math.abs(value).toFixed(1)}%`;
}

const STATUS_STYLES: Record<string, string> = {
  UNDERVALUED: "bg-emerald-500/10 text-emerald-300 ring-emerald-500/30",
  FAIR_VALUE: "bg-sky-500/10 text-sky-300 ring-sky-500/30",
  OVERVALUED: "bg-rose-500/10 text-rose-300 ring-rose-500/30",
};

function scoreColor(score: number): string {
  if (score >= 75) return "text-emerald-400";
  if (score >= 55) return "text-sky-300";
  if (score >= 35) return "text-zinc-300";
  return "text-zinc-500";
}

export default function ResearchDeskBlotter({
  rows,
  status,
}: {
  rows: ResearchRow[];
  status?: DataStatus | null;
}) {
  if (rows.length === 0) {
    const missing = status?.tableMissing ?? false;
    const pending = status?.feedPending ?? false;
    const unreachable = status?.unreachable ?? false;
    return (
      <div className="px-3 py-6 text-center">
        {unreachable ? (
          <FeedErrorPill />
        ) : missing ? (
          <p className="font-mono text-xs uppercase tracking-widest text-amber-300">
            [SCHEMA PENDING: RUN SCHEMA.SQL IN SUPABASE]
          </p>
        ) : pending ? (
          <p className="font-mono text-xs uppercase tracking-widest text-sky-300">
            [RESEARCH DESK: AWAITING FIRST SCORING PASS]
          </p>
        ) : (
          <p className="font-mono text-xs text-zinc-500">
            NO RESEARCH COVERAGE FOR THIS SESSION
          </p>
        )}
        <p className="mt-1 text-[11px] text-zinc-600">
          Composite alpha scores (valuation 35 / quality 25 / growth 20 /
          yield 20) with the PSX institutional multi-factor intrinsic value,
          built from quarterly DPS financials (psx_equity_research).
        </p>
      </div>
    );
  }

  const undervalued = rows.filter((r) => r.valuationStatus === "UNDERVALUED").length;
  const overvalued = rows.filter((r) => r.valuationStatus === "OVERVALUED").length;
  const highScore = rows.filter((r) => r.alphaScore >= 75).length;
  // Adaptive columns: NULL-only metrics (e.g. Risk before debt ingestion, or
  // provenance columns pre-migration) are suppressed so the desk stays a
  // clean relative screener instead of a wall of em-dashes.
  const hasTargetPe = rows.some((r) => r.targetPeUsed != null);
  const hasDivFloor = rows.some((r) => r.dividendFloorPkr != null);
  const hasRisk = rows.some(
    (r) => r.balanceSheetRiskFlag != null && r.balanceSheetRiskFlag !== "CLEAN"
  );

  return (
    <section>
      <div className="flex items-center justify-between border-b border-zinc-800 px-3 py-2">
        <h2 className="text-[10px] font-medium uppercase tracking-widest text-zinc-600">
          Research Desk - Sector P/E Multiple + Dividend Floor Model
        </h2>
        <span className="font-mono text-[11px] tabular-nums text-zinc-500">
          {undervalued} UNDER · {overvalued} OVER · {highScore} α≥75
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] border-collapse text-xs">
          <thead>
            <tr className="border-b border-zinc-800 bg-[#0c1017] text-left text-[10px] uppercase tracking-widest text-zinc-600">
              <th className="px-3 py-2 font-medium">Ticker</th>
              <th className="px-2 py-2 text-right font-medium">α Score</th>
              <th className="px-2 py-2 text-right font-medium">Intrinsic</th>
              <th className="px-2 py-2 text-right font-medium">Disc %</th>
              {hasTargetPe && (
                <th className="px-2 py-2 text-right font-medium">Tgt P/E</th>
              )}
              {hasDivFloor && (
                <th className="px-2 py-2 text-right font-medium">Div Floor</th>
              )}
              <th className="px-2 py-2 font-medium">Verdict</th>
              {hasRisk && <th className="px-3 py-2 font-medium">Risk</th>}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={`${row.tradeDate}-${row.ticker}`}
                className="border-b border-zinc-900 hover:bg-zinc-900/40"
              >
                <td className="px-3 py-1.5 font-mono font-semibold text-zinc-100">
                  {row.ticker}
                </td>
                <td
                  className={`px-2 py-1.5 text-right font-mono text-sm font-bold tabular-nums ${scoreColor(
                    row.alphaScore
                  )}`}
                >
                  {row.alphaScore}
                </td>
                <td className="px-2 py-1.5 text-right font-mono tabular-nums text-zinc-300">
                  {fmtPrice(row.intrinsicValuePkr)}
                </td>
                <td
                  className={`px-2 py-1.5 text-right font-mono tabular-nums ${
                    row.valuationDiscountPct == null
                      ? "text-zinc-500"
                      : row.valuationDiscountPct >= 15
                        ? "text-emerald-400"
                        : row.valuationDiscountPct <= -15
                          ? "text-rose-400"
                          : "text-zinc-300"
                  }`}
                >
                  {fmtDiscount(row.valuationDiscountPct)}
                </td>
                {hasTargetPe && (
                  <td className="px-2 py-1.5 text-right font-mono tabular-nums text-zinc-400">
                    {row.targetPeUsed == null
                      ? "—"
                      : `${row.targetPeUsed.toFixed(1)}x`}
                  </td>
                )}
                {hasDivFloor && (
                  <td className="px-2 py-1.5 text-right font-mono tabular-nums text-zinc-400">
                    {fmtPrice(row.dividendFloorPkr)}
                  </td>
                )}
                <td className="px-2 py-1.5">
                  <span
                    className={`inline-block rounded px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider ring-1 ${
                      STATUS_STYLES[row.valuationStatus] ??
                      "bg-zinc-800 text-zinc-400 ring-zinc-700"
                    }`}
                  >
                    {row.valuationStatus.replace("_", " ")}
                  </span>
                </td>
                {hasRisk && (
                  <td className="px-3 py-1.5">
                    <span
                      className={`font-mono text-[10px] uppercase tracking-wider ${
                        row.balanceSheetRiskFlag &&
                        row.balanceSheetRiskFlag !== "CLEAN"
                          ? "text-rose-400"
                          : "text-zinc-600"
                      }`}
                    >
                      {row.balanceSheetRiskFlag ?? "—"}
                    </span>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="border-t border-zinc-900 px-3 py-2">
        <p className="font-mono text-[10px] leading-relaxed text-zinc-600">
          MODEL: SECTOR P/E MULTIPLE + DIVIDEND FLOOR (PSX_MF_V1) — intrinsic
          = TTM EPS × sector normal P/E (E&amp;P 6.0x · fertilizer 7.5x ·
          cement 7.0x · tech 12.0x · banks 5.0x · default 6.5x); dividend
          payers blend 60% P/E leg + 40% dividend floor (TTM DPS ÷ K_e = PIB{" "}
          {PIB_YIELD_PCT}% − growth {DIV_GROWTH_PCT}% ={" "}
          {(KE_REQUIRED * 100).toFixed(1)}%). Discount + = price below
          intrinsic. Relative screener — metric columns that are NULL across
          the session are auto-suppressed.
        </p>
      </div>
    </section>
  );
}
