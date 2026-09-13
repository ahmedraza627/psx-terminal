"use client";

import { useMemo, useState } from "react";
import type { WhaleRow } from "@/lib/queries";

const CONVICTION_CLS: Record<string, string> = {
  HIGH: "bg-emerald-500/10 text-emerald-400 ring-emerald-500/30",
  ELEVATED: "bg-sky-500/10 text-sky-300 ring-sky-500/30",
  MODERATE: "bg-zinc-500/10 text-zinc-400 ring-zinc-600/30",
  NOTABLE_VOLUME_SPIKE: "bg-amber-500/10 text-amber-300 ring-amber-500/30",
};

function fmtPrice(value: number | null | undefined): string {
  return value == null ? "—" : value.toFixed(2);
}

function fmtPct(value: number | null | undefined): string {
  if (value == null) return "—";
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}

export default function StockBlotter({ rows }: { rows: WhaleRow[] }) {
  const [query, setQuery] = useState("");

  const filtered = useMemo(() => {
    const q = query.trim().toUpperCase();
    if (!q) return rows;
    return rows.filter(
      (r) =>
        r.ticker.includes(q) ||
        (r.meta.sector ?? "").toUpperCase().includes(q)
    );
  }, [rows, query]);

  const sorted = useMemo(
    () =>
      [...filtered].sort(
        (a, b) => (b.meta.vol_multiple ?? 0) - (a.meta.vol_multiple ?? 0)
      ),
    [filtered]
  );

  return (
    <section className="border-b border-zinc-800">
      <div className="flex items-center gap-2 border-b border-zinc-800 px-3 py-2">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="FILTER SYMBOL / SECTOR…"
          aria-label="Filter whale blotter"
          className="w-full max-w-xs rounded border border-zinc-800 bg-[#05070a] px-2 py-1.5 font-mono text-xs uppercase tracking-wider text-zinc-200 placeholder:text-zinc-600 focus:border-sky-500/60 focus:outline-none"
        />
        <span className="ml-auto font-mono text-[11px] tabular-nums text-zinc-500">
          {sorted.length} ROW{sorted.length === 1 ? "" : "S"}
        </span>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] border-collapse text-xs">
          <thead>
            <tr className="border-b border-zinc-800 bg-[#0c1017] text-left text-[10px] uppercase tracking-widest text-zinc-600">
              <th className="px-3 py-2 font-medium">Ticker</th>
              <th className="px-2 py-2 font-medium">Sector</th>
              <th className="px-2 py-2 text-right font-medium">LTP</th>
              <th className="px-2 py-2 text-right font-medium">Day %</th>
              <th className="px-2 py-2 text-right font-medium">Vol x SMA20</th>
              <th className="px-2 py-2 text-right font-medium">Tightness</th>
              <th className="px-2 py-2 text-right font-medium">Stop</th>
              <th className="px-3 py-2 text-right font-medium">Conviction</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((row) => {
              const drift = row.meta.drift_pct;
              const dayCls =
                drift == null
                  ? "text-zinc-300"
                  : drift >= 0
                    ? "text-emerald-400"
                    : "text-rose-400";
              const conviction = row.meta.conviction ?? "MODERATE";
              return (
                <tr
                  key={`${row.trade_date}-${row.ticker}`}
                  className="border-b border-zinc-900 hover:bg-zinc-900/40"
                >
                  <td className="px-3 py-1.5 font-mono font-semibold text-zinc-100">
                    {row.ticker}
                  </td>
                  <td className="max-w-[140px] truncate px-2 py-1.5 text-zinc-500">
                    {row.meta.sector
                      ? row.meta.sector.toLowerCase().replace(/\b\w/g, (c) =>
                          c.toUpperCase()
                        )
                      : "—"}
                  </td>
                  <td className="px-2 py-1.5 text-right font-mono tabular-nums text-zinc-100">
                    {fmtPrice(row.entry_reference)}
                  </td>
                  <td
                    className={`px-2 py-1.5 text-right font-mono tabular-nums ${dayCls}`}
                  >
                    {fmtPct(drift)}
                  </td>
                  <td className="px-2 py-1.5 text-right font-mono tabular-nums text-sky-300">
                    {row.meta.vol_multiple?.toFixed(1) ?? "—"}x
                  </td>
                  <td className="px-2 py-1.5 text-right font-mono tabular-nums text-zinc-400">
                    {row.meta.range_pct != null
                      ? `${row.meta.range_pct.toFixed(1)}%`
                      : "—"}
                  </td>
                  <td className="px-2 py-1.5 text-right font-mono tabular-nums text-rose-400/90">
                    {fmtPrice(row.stop_loss)}
                  </td>
                  <td className="px-3 py-1.5 text-right">
                    <span
                      className={`inline-block rounded px-1.5 py-0.5 font-mono text-[10px] font-semibold uppercase ring-1 ${
                        CONVICTION_CLS[conviction] ?? CONVICTION_CLS.MODERATE
                      }`}
                    >
                      {conviction}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
