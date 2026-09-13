"use client";

import type { SignalRow } from "@/lib/types";

function fmtPrice(value: number | null): string {
  return value == null ? "—" : value.toFixed(2);
}

function fmtPct(value: number | null | undefined): string {
  return value == null ? "—" : `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}

export default function MomentumBlotter({ rows }: { rows: SignalRow[] }) {
  if (rows.length === 0) {
    return (
      <div className="px-3 py-6 text-center">
        <p className="font-mono text-xs text-zinc-500">
          NO SMART-MONEY SECTOR ALIGNMENT THIS SESSION
        </p>
        <p className="mt-1 text-[11px] text-zinc-600">
          Fills when NCCPL shows Mutual Funds / Foreign Corporates net buying
          and a member stock breaks out on 5-day volume.
        </p>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[600px] border-collapse text-xs">
        <thead>
          <tr className="border-b border-zinc-800 bg-[#0c1017] text-left text-[10px] uppercase tracking-widest text-zinc-600">
            <th className="px-3 py-2 font-medium">Ticker</th>
            <th className="px-2 py-2 font-medium">Sector</th>
            <th className="px-2 py-2 text-right font-medium">LTP</th>
            <th className="px-2 py-2 text-right font-medium">Day %</th>
            <th className="px-2 py-2 text-right font-medium">Vol x SMA5</th>
            <th className="px-3 py-2 text-right font-medium">Smart Net</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const meta = row.metadata ?? {};
            const day = meta.day_change_pct;
            const smart = meta.sector_smart_net_pkr;
            return (
              <tr
                key={`${row.trade_date}-${row.ticker}`}
                className="border-b border-zinc-900 hover:bg-zinc-900/40"
              >
                <td className="px-3 py-1.5 font-mono font-semibold text-zinc-100">
                  {row.ticker}
                </td>
                <td className="max-w-[150px] truncate px-2 py-1.5 text-zinc-500">
                  {meta.sector
                    ? meta.sector.toLowerCase().replace(/\b\w/g, (c) =>
                        c.toUpperCase()
                      )
                    : "—"}
                </td>
                <td className="px-2 py-1.5 text-right font-mono tabular-nums text-zinc-100">
                  {fmtPrice(row.entry_reference)}
                </td>
                <td
                  className={`px-2 py-1.5 text-right font-mono tabular-nums ${
                    day == null
                      ? "text-zinc-300"
                      : day >= 0
                        ? "text-emerald-400"
                        : "text-rose-400"
                  }`}
                >
                  {fmtPct(day)}
                </td>
                <td className="px-2 py-1.5 text-right font-mono tabular-nums text-sky-300">
                  {meta.breakout_multiple?.toFixed(1) ?? "—"}x
                </td>
                <td className="px-3 py-1.5 text-right font-mono tabular-nums text-zinc-300">
                  {smart == null
                    ? "—"
                    : `${smart >= 0 ? "+" : ""}${(smart / 1e6).toFixed(0)}M`}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
