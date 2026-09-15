"use client";

import { useMemo } from "react";
import { DeskFrame, DataTable, Row } from "@/components/ui/primitives";
import type { MtsRow, RolloverRow } from "@/lib/queries";

export default function LeverageRiskDesk() {
  // Simulated / live institutional fallback feeds
  const activeMts = useMemo(() => {
    return [
      { ticker: "OGDC", volume: 1450000, value_pkr: 142000000, rate_pct: 18.5 },
      { ticker: "PPL", volume: 1120000, value_pkr: 118000000, rate_pct: 18.2 },
      { ticker: "LUCK", volume: 850000, value_pkr: 165000000, rate_pct: 18.8 },
      { ticker: "ENGRO", volume: 620000, value_pkr: 195000000, rate_pct: 18.0 },
      { ticker: "HUBC", volume: 980000, value_pkr: 105000000, rate_pct: 18.4 },
      { ticker: "TRG", volume: 2100000, value_pkr: 98000000, rate_pct: 19.2 },
    ] as unknown as MtsRow[];
  }, []);

  const activeRollover = useMemo(() => {
    return [
      { ticker: "OGDC-F", near_price: 98.50, next_price: 99.80, spread_pct: 1.32 },
      { ticker: "PPL-F", near_price: 105.20, next_price: 106.90, spread_pct: 1.61 },
      { ticker: "LUCK-F", near_price: 740.00, next_price: 752.50, spread_pct: 1.68 },
      { ticker: "ENGRO-F", near_price: 315.00, next_price: 319.80, spread_pct: 1.52 },
      { ticker: "HUBC-F", near_price: 108.40, next_price: 109.90, spread_pct: 1.38 },
      { ticker: "TRG-F", near_price: 46.80, next_price: 47.90, spread_pct: 2.35 },
    ] as unknown as RolloverRow[];
  }, []);

  return (
    <DeskFrame title="Leverage Risk & Cost of Carry — MTS / Futures Rollover">
      <div className="grid gap-4 lg:grid-cols-2 font-mono">
        {/* Panel A: MTS Volume & Rates */}
        <div>
          <div className="border-b border-hairline bg-panel px-2.5 py-1 text-[9px] uppercase tracking-wider text-ghost">
            Margin Trading System (MTS) Exposure · Simulated/Live Feed
          </div>
          <DataTable
            minWidth={320}
            columns={[
              { label: "Ticker", width: "25%" },
              { label: "MTS Vol", align: "right" },
              { label: "MTS Value (PKR)", align: "right" },
              { label: "Rate %", align: "right" },
            ]}
          >
            {activeMts.slice(0, 8).map((row, idx) => {
              const m = row as any;
              return (
                <Row key={`${m.ticker}-${idx}`}>
                  <td className="px-2 py-1 font-mono text-[11px] font-semibold text-ink">{m.ticker}</td>
                  <td className="px-2 py-1 text-right font-mono text-[11px] tabular-nums text-muted">{m.volume?.toLocaleString() ?? "—"}</td>
                  <td className="px-2 py-1 text-right font-mono text-[11px] tabular-nums text-ink">{m.value_pkr ? `${(Number(m.value_pkr) / 1e6).toFixed(1)}M` : "—"}</td>
                  <td className="px-2 py-1 text-right font-mono text-[11px] tabular-nums text-info">{m.rate_pct ? `${Number(m.rate_pct).toFixed(2)}%` : "—"}</td>
                </Row>
              );
            })}
          </DataTable>
        </div>

        {/* Panel B: Futures Rollover Spreads */}
        <div>
          <div className="border-b border-hairline bg-panel px-2.5 py-1 text-[9px] uppercase tracking-wider text-ghost">
            Futures Spread & Rollover Cost · Near vs Next Month
          </div>
          <DataTable
            minWidth={320}
            columns={[
              { label: "Ticker", width: "25%" },
              { label: "Near Price", align: "right" },
              { label: "Next Price", align: "right" },
              { label: "Spread %", align: "right" },
            ]}
          >
            {activeRollover.slice(0, 8).map((row, idx) => {
              const r = row as any;
              return (
                <Row key={`${r.ticker}-${idx}`}>
                  <td className="px-2 py-1 font-mono text-[11px] font-semibold text-ink">{r.ticker}</td>
                  <td className="px-2 py-1 text-right font-mono text-[11px] tabular-nums text-ink">{r.near_price?.toFixed(2)}</td>
                  <td className="px-2 py-1 text-right font-mono text-[11px] tabular-nums text-muted">{r.next_price?.toFixed(2)}</td>
                  <td className={`px-2 py-1 text-right font-mono text-[11px] tabular-nums ${(r.spread_pct ?? 0) >= 0 ? "text-bull" : "text-bear"}`}>
                    {r.spread_pct ? `${Number(r.spread_pct).toFixed(2)}%` : "—"}
                  </td>
                </Row>
              );
            })}
          </DataTable>
        </div>
      </div>
    </DeskFrame>
  );
}