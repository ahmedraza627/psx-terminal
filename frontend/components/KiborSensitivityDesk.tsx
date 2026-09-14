"use client";

import { useMemo, useState } from "react";
import FeedErrorPill from "./FeedErrorPill";
import {
  epsExpansionAtBps,
  type DataStatus,
  type KiborRow,
} from "@/lib/queries";

function fmtBn(value: number | null): string {
  if (value == null) return "—";
  const bn = value / 1e9;
  if (bn >= 100) return bn.toFixed(0);
  if (bn >= 1) return bn.toFixed(1);
  return (value / 1e6).toFixed(0) + "M";
}

function fmtEps(value: number | null): string {
  return value == null ? "—" : value.toFixed(3);
}

function fmtPct(value: number | null): string {
  return value == null
    ? "—"
    : `${value >= 0 ? "+" : ""}${value.toFixed(1)}%`;
}

function expansionColor(value: number | null): string {
  if (value == null) return "text-ghost";
  if (value >= 15) return "text-bull";
  if (value >= 5) return "text-info";
  if (value >= 0) return "text-ink";
  return "text-bear";
}

export default function KiborSensitivityDesk({
  rows,
  status,
}: {
  rows: KiborRow[];
  status?: DataStatus | null;
}) {
  const [bps, setBps] = useState(300);

  const ranked = useMemo(
    () =>
      rows
        .map((r) => ({ ...r, expansion: epsExpansionAtBps(r, bps) }))
        .sort((a, b) => (b.expansion ?? -1e9) - (a.expansion ?? -1e9)),
    [rows, bps]
  );

  if (rows.length === 0) {
    const missing = status?.tableMissing ?? false;
    const pending = status?.feedPending ?? false;
    const unreachable = status?.unreachable ?? false;
    return (
      <div className="px-3 py-6 text-center">
        {unreachable ? (
          <FeedErrorPill />
        ) : missing ? (
          <p className="font-mono text-xs uppercase tracking-widest text-warn">
            [SCHEMA PENDING: RUN SCHEMA.SQL IN SUPABASE]
          </p>
        ) : pending ? (
          <p className="font-mono text-xs uppercase tracking-widest text-info">
            [KIBOR DESK: AWAITING FIRST SENSITIVITY PASS]
          </p>
        ) : (
          <p className="font-mono text-xs uppercase tracking-widest text-info">
            [KIBOR DESK: AWAITING FLOATING-DEBT SOURCE]
          </p>
        )}
        <p className="mt-1 text-[11px] leading-relaxed text-ghost">
          PSX publishes no balance-sheet debt columns. Supply floating debt
          via KIBOR_FLOATING_DEBT_MAP (e.g. &quot;OGDC:185b,PSO:120b&quot;) or
          KIBOR_DEBT_CSV_URL — the desk populates the moment an input lands.
          No estimated debt is ever fabricated.
        </p>
      </div>
    );
  }

  return (
    <section>
      <div className="border-b border-hairline px-3 py-2">
        <div className="flex items-center justify-between">
          <h2 className="text-[10px] font-medium uppercase tracking-widest text-ghost">
            KIBOR Easing Sensitivity - EPS Expansion per Rate Cut
          </h2>
          <span className="font-mono text-[11px] tabular-nums text-muted">
            {rows.length} NAMES
          </span>
        </div>
        <div className="mt-2 flex items-center gap-3">
          <span className="font-mono text-[10px] uppercase tracking-wider text-muted">
            CUT
          </span>
          <input
            type="range"
            min={100}
            max={500}
            step={100}
            value={bps}
            onChange={(e) => setBps(Number(e.target.value))}
            className="h-1 flex-1 accent-sky-400"
            aria-label="Rate cut in basis points"
          />
          <span className="rounded-[2px] border border-sky-500/30 bg-info/10 px-2 py-0.5 font-mono text-xs font-bold tabular-nums text-info">
            {bps} bps
          </span>
        </div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] border-collapse text-xs">
          <thead>
            <tr className="border-b border-hairline bg-panel text-left text-[10px] uppercase tracking-widest text-ghost">
              <th className="px-3 py-2 font-medium">#</th>
              <th className="px-2 py-2 font-medium">Ticker</th>
              <th className="px-2 py-2 font-medium">Sector</th>
              <th className="px-2 py-2 text-right font-medium">Flt Debt (Bn)</th>
              <th className="px-2 py-2 text-right font-medium">ΔEPS/100bps</th>
              <th className="px-3 py-2 text-right font-medium">
                EPS Surge @{bps}bps
              </th>
            </tr>
          </thead>
          <tbody>
            {ranked.map((row, i) => (
              <tr
                key={row.ticker}
                className="border-b border-hairline hover:bg-hoverline"
              >
                <td className="px-3 py-1.5 font-mono tabular-nums text-ghost">
                  {i + 1}
                </td>
                <td className="px-2 py-1.5 font-mono font-semibold text-ink">
                  {row.ticker}
                </td>
                <td className="max-w-[160px] truncate px-2 py-1.5 font-mono text-[10px] uppercase tracking-wider text-muted">
                  {row.sectorName ?? "—"}
                </td>
                <td className="px-2 py-1.5 text-right font-mono tabular-nums text-ink">
                  {fmtBn(row.floatingDebtPkr)}
                </td>
                <td className="px-2 py-1.5 text-right font-mono tabular-nums text-ink">
                  {fmtEps(row.epsImpact100bpsPkr)}
                </td>
                <td
                  className={`px-3 py-1.5 text-right font-mono text-sm font-bold tabular-nums ${expansionColor(
                    row.expansion
                  )}`}
                >
                  {fmtPct(row.expansion)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="border-t border-hairline px-3 py-2">
        <p className="font-mono text-[10px] leading-relaxed text-ghost">
          ΔEPS(100bps) = flt debt × 1% × (1 − 29% tax) ÷ shares · cycle
          projection scales linearly to the slider cut · debt basis:
          OPERATOR_INPUT (published FY25/26 filings, KIBOR_FLOATING_DEBT_MAP)
          · K_e hurdle = PIB 13.5% − div growth 4%.
        </p>
      </div>
    </section>
  );
}
