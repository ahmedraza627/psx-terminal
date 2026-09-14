"use client";

import { useMemo, useState } from "react";
import type { WhaleRow } from "@/lib/queries";

const CONVICTION_CLS: Record<string, string> = {
  HIGH: "bg-bull/10 text-bull ring-bull/30",
  ELEVATED: "bg-info/10 text-info ring-info/30",
  MODERATE: "bg-panel text-muted ring-hairline",
  NOTABLE_VOLUME_SPIKE: "bg-warn/10 text-warn ring-warn/30",
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
    <section className="border-b border-hairline">
      <div className="flex items-center gap-2 border-b border-hairline px-3 py-2">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="FILTER SYMBOL / SECTOR…"
          aria-label="Filter whale blotter"
          className="w-full max-w-xs rounded-[2px] border border-hairline bg-obsidian px-2 py-1.5 font-mono text-xs uppercase tracking-wider text-ink placeholder:text-ghost focus:border-info/50 focus:outline-none"
        />
        <span className="ml-auto font-mono text-[11px] tabular-nums text-muted">
          {sorted.length} ROW{sorted.length === 1 ? "" : "S"}
        </span>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] border-collapse text-xs">
          <thead>
            <tr className="border-b border-hairline bg-panel text-left text-[10px] uppercase tracking-widest text-ghost">
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
                  ? "text-ink"
                  : drift >= 0
                    ? "text-bull"
                    : "text-bear";
              const conviction = row.meta.conviction ?? "MODERATE";
              return (
                <tr
                  key={`${row.trade_date}-${row.ticker}`}
                  className="border-b border-hairline hover:bg-hoverline"
                >
                  <td className="px-3 py-1.5 font-mono font-semibold text-ink">
                    {row.ticker}
                  </td>
                  <td className="max-w-[140px] truncate px-2 py-1.5 text-muted">
                    {row.meta.sector
                      ? row.meta.sector.toLowerCase().replace(/\b\w/g, (c) =>
                          c.toUpperCase()
                        )
                      : "—"}
                  </td>
                  <td className="px-2 py-1.5 text-right font-mono tabular-nums text-ink">
                    {fmtPrice(row.entry_reference)}
                  </td>
                  <td
                    className={`px-2 py-1.5 text-right font-mono tabular-nums ${dayCls}`}
                  >
                    {fmtPct(drift)}
                  </td>
                  <td className="px-2 py-1.5 text-right font-mono tabular-nums text-info">
                    {row.meta.vol_multiple?.toFixed(1) ?? "—"}x
                  </td>
                  <td className="px-2 py-1.5 text-right font-mono tabular-nums text-muted">
                    {row.meta.range_pct != null
                      ? `${row.meta.range_pct.toFixed(1)}%`
                      : "—"}
                  </td>
                  <td className="px-2 py-1.5 text-right font-mono tabular-nums text-bear/90">
                    {fmtPrice(row.stop_loss)}
                  </td>
                  <td className="px-3 py-1.5 text-right">
                    <span
                      className={`inline-block rounded-[2px] px-1.5 py-0.5 font-mono text-[10px] font-semibold uppercase ring-1 ${
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
