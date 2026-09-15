"use client";

import { useMemo, useState } from "react";
import FeedErrorPill from "./FeedErrorPill";
import type { DataStatus } from "@/lib/queries";
import {
  KE_REQUIRED,
  PIB_YIELD_PCT,
  DIV_GROWTH_PCT,
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
  UNDERVALUED: "bg-bull/10 text-bull ring-bull/30",
  FAIR_VALUE: "bg-info/10 text-info ring-info/30",
  OVERVALUED: "bg-bear/10 text-bear ring-bear/30",
};

function scoreColor(score: number): string {
  if (score >= 75) return "text-bull";
  if (score >= 55) return "text-info";
  if (score >= 35) return "text-ink";
  return "text-muted";
}

// Known penny/illiquid outliers that skew automated intrinsic P/E screens
const OUTLIER_EXCLUSION_SET = new Set(["ITANZ", "THCCL", "SLGL", "MDTL", "ZUMA"]);

export default function ResearchDeskBlotter({
  rows,
  status,
}: {
  rows: ResearchRow[];
  status?: DataStatus | null;
}) {
  const [filterMode, setFilterMode] = useState<"LIQUID_CORE" | "ALL">("LIQUID_CORE");

  const sanitizedRows = useMemo(() => {
    if (!Array.isArray(rows)) return [];

    if (filterMode === "ALL") {
      return [...rows].sort((a, b) => (b.alphaScore ?? 0) - (a.alphaScore ?? 0));
    }

    // Institutional Liquidity Filter:
    // 1. Drop known distorted outliers (e.g. ITANZ with broken EPS base)
    // 2. Bound unrealistic discounts (-60% to +150%)
    return rows
      .filter((r) => {
        if (!r.ticker) return false;
        const sym = r.ticker.toUpperCase();
        if (OUTLIER_EXCLUSION_SET.has(sym)) return false;

        const disc = r.valuationDiscountPct ?? 0;
        return disc >= -60 && disc <= 150;
      })
      .sort((a, b) => {
        // High score first, then biggest valid discount
        if (b.alphaScore !== a.alphaScore) {
          return (b.alphaScore ?? 0) - (a.alphaScore ?? 0);
        }
        return (b.valuationDiscountPct ?? 0) - (a.valuationDiscountPct ?? 0);
      });
  }, [rows, filterMode]);

  if (rows.length === 0) {
    const missing = status?.tableMissing ?? false;
    const pending = status?.feedPending ?? false;
    const unreachable = status?.unreachable ?? false;
    return (
      <div className="px-3 py-6 text-center font-mono">
        {unreachable ? (
          <FeedErrorPill />
        ) : missing ? (
          <p className="text-xs uppercase tracking-widest text-warn">
            [SCHEMA PENDING: RUN SCHEMA.SQL IN SUPABASE]
          </p>
        ) : pending ? (
          <p className="text-xs uppercase tracking-widest text-info">
            [RESEARCH DESK: AWAITING FIRST SCORING PASS]
          </p>
        ) : (
          <p className="text-xs text-muted">
            NO RESEARCH COVERAGE FOR THIS SESSION
          </p>
        )}
        <p className="mt-1 text-[11px] text-ghost">
          Composite alpha scores (valuation 35 / quality 25 / growth 20 /
          yield 20) with the PSX institutional multi-factor intrinsic value.
        </p>
      </div>
    );
  }

  const undervalued = sanitizedRows.filter((r) => r.valuationStatus === "UNDERVALUED").length;
  const overvalued = sanitizedRows.filter((r) => r.valuationStatus === "OVERVALUED").length;
  const highScore = sanitizedRows.filter((r) => r.alphaScore >= 70).length;

  const hasTargetPe = sanitizedRows.some((r) => r.targetPeUsed != null);
  const hasDivFloor = sanitizedRows.some((r) => r.dividendFloorPkr != null);
  const hasRisk = sanitizedRows.some(
    (r) => r.balanceSheetRiskFlag != null && r.balanceSheetRiskFlag !== "CLEAN"
  );

  return (
    <section className="font-mono">
      <div className="flex flex-wrap items-center justify-between border-b border-hairline bg-panel px-3 py-2 gap-2">
        <div className="flex items-center gap-3">
          <h2 className="text-[10px] font-bold uppercase tracking-widest text-ghost">
            RESEARCH DESK · INTRINSIC MULTI-FACTOR VALUATION
          </h2>
          <div className="flex items-center rounded border border-hairline bg-obsidian p-0.5 text-[9px]">
            <button
              onClick={() => setFilterMode("LIQUID_CORE")}
              className={`px-2 py-0.5 font-bold uppercase transition-colors ${
                filterMode === "LIQUID_CORE"
                  ? "bg-info/20 text-info"
                  : "text-ghost hover:text-ink"
              }`}
            >
              Institutional Core
            </button>
            <button
              onClick={() => setFilterMode("ALL")}
              className={`px-2 py-0.5 font-bold uppercase transition-colors ${
                filterMode === "ALL"
                  ? "bg-info/20 text-info"
                  : "text-ghost hover:text-ink"
              }`}
            >
              All Universe ({rows.length})
            </button>
          </div>
        </div>
        <span className="text-[11px] tabular-nums text-muted">
          {undervalued} UNDER · {overvalued} OVER · {highScore} α≥70
        </span>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] border-collapse text-xs">
          <thead>
            <tr className="border-b border-hairline bg-panel/70 text-left text-[10px] uppercase tracking-widest text-ghost">
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
              {hasRisk && <th className="px-3 py-2 font-medium">Risk Flag</th>}
            </tr>
          </thead>
          <tbody className="divide-y divide-hairline">
            {sanitizedRows.map((row) => (
              <tr
                key={`${row.tradeDate}-${row.ticker}`}
                className="hover:bg-hoverline transition-colors"
              >
                <td className="px-3 py-1.5 font-mono font-bold text-ink">
                  {row.ticker}
                </td>
                <td
                  className={`px-2 py-1.5 text-right font-mono text-sm font-bold tabular-nums ${scoreColor(
                    row.alphaScore
                  )}`}
                >
                  {row.alphaScore}
                </td>
                <td className="px-2 py-1.5 text-right font-mono tabular-nums text-ink">
                  {fmtPrice(row.intrinsicValuePkr)}
                </td>
                <td
                  className={`px-2 py-1.5 text-right font-mono font-semibold tabular-nums ${
                    row.valuationDiscountPct == null
                      ? "text-muted"
                      : row.valuationDiscountPct >= 15
                        ? "text-bull"
                        : row.valuationDiscountPct <= -15
                          ? "text-bear"
                          : "text-ink"
                  }`}
                >
                  {fmtDiscount(row.valuationDiscountPct)}
                </td>
                {hasTargetPe && (
                  <td className="px-2 py-1.5 text-right font-mono tabular-nums text-muted">
                    {row.targetPeUsed == null
                      ? "—"
                      : `${row.targetPeUsed.toFixed(1)}x`}
                  </td>
                )}
                {hasDivFloor && (
                  <td className="px-2 py-1.5 text-right font-mono tabular-nums text-muted">
                    {fmtPrice(row.dividendFloorPkr)}
                  </td>
                )}
                <td className="px-2 py-1.5">
                  <span
                    className={`inline-block rounded-[2px] px-1.5 py-0.5 font-mono text-[10px] font-semibold uppercase tracking-wider ring-1 ${
                      STATUS_STYLES[row.valuationStatus] ??
                      "bg-panel text-muted ring-hairline"
                    }`}
                  >
                    {row.valuationStatus.replace(/_/g, " ")}
                  </span>
                </td>
                {hasRisk && (
                  <td className="px-3 py-1.5">
                    <span
                      className={`font-mono text-[10px] uppercase tracking-wider ${
                        row.balanceSheetRiskFlag &&
                        row.balanceSheetRiskFlag !== "CLEAN"
                          ? "text-bear font-semibold"
                          : "text-ghost"
                      }`}
                    >
                      {row.balanceSheetRiskFlag ?? "CLEAN"}
                    </span>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="border-t border-hairline bg-panel/30 px-3 py-2 text-[10px] text-ghost leading-relaxed">
        MODEL: SECTOR P/E MULTIPLE + DIVIDEND FLOOR (PSX_MF_V1) — Intrinsic
        = TTM EPS × sector normal P/E (E&amp;P 6.0x · Fertilizer 7.5x ·
        Cement 7.0x · Tech 12.0x · Banks 5.0x · Default 6.5x). Dividend
        payers blend 60% P/E leg + 40% dividend floor (TTM DPS ÷ K_e = PIB{" "}
        {PIB_YIELD_PCT}% − growth {DIV_GROWTH_PCT}% ={" "}
        {(KE_REQUIRED * 100).toFixed(1)}%).
      </div>
    </section>
  );
}