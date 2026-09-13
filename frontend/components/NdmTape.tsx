"use client";

import { useMemo, useState } from "react";
import type { NdmRow } from "@/lib/queries";

function fmtShares(value: number | null): string {
  if (value == null) return "—";
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(2)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(0)}K`;
  return value.toFixed(0);
}

function fmtPrice(value: number | null): string {
  return value == null ? "—" : value.toFixed(2);
}

function fmtPct(value: number | null): string {
  return value == null ? "—" : `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}

export default function NdmTape({ rows }: { rows: NdmRow[] }) {
  const [query, setQuery] = useState("");

  const filtered = useMemo(() => {
    const q = query.trim().toUpperCase();
    if (!q) return rows;
    return rows.filter((r) => r.ticker.includes(q));
  }, [rows, query]);

  return (
    <section>
      <div className="flex items-center gap-2 border-b border-zinc-800 px-3 py-2">
        <h2 className="text-[10px] font-medium uppercase tracking-widest text-zinc-600">
          NDM Block Tape - Trades &ge; 50K Shares
        </h2>
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="FILTER…"
          aria-label="Filter NDM tape"
          className="ml-auto w-28 rounded border border-zinc-800 bg-[#05070a] px-2 py-1 font-mono text-[11px] uppercase text-zinc-200 placeholder:text-zinc-600 focus:border-sky-500/60 focus:outline-none"
        />
        <span className="font-mono text-[11px] tabular-nums text-zinc-500">
          {filtered.length}
        </span>
      </div>

      {filtered.length === 0 ? (
        <div className="px-3 py-6 text-center">
          <p className="font-mono text-xs text-zinc-500">
            NO BLOCKS &ge; 50K SHARES ON TAPE
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[560px] border-collapse text-xs">
            <thead>
              <tr className="border-b border-zinc-800 bg-[#0c1017] text-left text-[10px] uppercase tracking-widest text-zinc-600">
                <th className="px-3 py-2 font-medium">Date</th>
                <th className="px-2 py-2 font-medium">Ticker</th>
                <th className="px-2 py-2 text-right font-medium">Volume</th>
                <th className="px-2 py-2 text-right font-medium">Rate</th>
                <th className="px-2 py-2 text-right font-medium">Mkt LTP</th>
                <th className="px-3 py-2 text-right font-medium">Diff %</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((row, idx) => {
                const diffCls =
                  row.ltpDiffPct == null
                    ? "text-zinc-500"
                    : row.ltpDiffPct >= 0
                      ? "text-emerald-400"
                      : "text-rose-400";
                return (
                  <tr
                    key={`${row.tradeDate}-${row.ticker}-${idx}`}
                    className="border-b border-zinc-900 hover:bg-zinc-900/40"
                  >
                    <td className="px-3 py-1.5 font-mono tabular-nums text-zinc-400">
                      {row.tradeDate}
                    </td>
                    <td className="px-2 py-1.5 font-mono font-semibold text-zinc-100">
                      {row.ticker}
                    </td>
                    <td className="px-2 py-1.5 text-right font-mono tabular-nums text-sky-300">
                      {fmtShares(row.quantity)}
                    </td>
                    <td className="px-2 py-1.5 text-right font-mono tabular-nums text-zinc-100">
                      {fmtPrice(row.rate)}
                    </td>
                    <td className="px-2 py-1.5 text-right font-mono tabular-nums text-zinc-400">
                      {fmtPrice(row.marketLtp)}
                    </td>
                    <td
                      className={`px-3 py-1.5 text-right font-mono tabular-nums ${diffCls}`}
                    >
                      {fmtPct(row.ltpDiffPct)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
