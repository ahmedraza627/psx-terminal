"use client";

import type { ArbitrageRow } from "@/lib/queries";

function fmtPrice(value: number | null): string {
  return value == null ? "—" : value.toFixed(2);
}

function fmtPct(value: number | null, digits = 2): string {
  return value == null ? "—" : `${value >= 0 ? "+" : ""}${value.toFixed(digits)}%`;
}

export default function ArbitrageBlotter({
  rows,
  feedOffline = false,
}: {
  rows: ArbitrageRow[];
  feedOffline?: boolean;
}) {
  return (
    <section>
      <div className="flex items-center justify-between border-b border-zinc-800 px-3 py-2">
        <h2 className="text-[10px] font-medium uppercase tracking-widest text-zinc-600">
          Ready vs Deliverable Futures - Cash &amp; Carry Desk
        </h2>
        <span className="font-mono text-[11px] tabular-nums text-zinc-500">
          {rows.length} LOCKED SPREAD{rows.length === 1 ? "" : "S"}
        </span>
      </div>

      {rows.length === 0 && feedOffline ? (
        <div className="border-b border-amber-900/40 bg-amber-950/20 px-3 py-6 text-center">
          <p className="font-mono text-xs uppercase tracking-widest text-amber-300">
            PSX Futures AJAX endpoint offline for session.
          </p>
          <p className="mt-1 font-mono text-[11px] text-amber-200/70">
            Awaiting next clearing window.
          </p>
        </div>
      ) : rows.length === 0 ? (
        <div className="border-b border-zinc-800 px-3 py-6 text-center">
          <p className="font-mono text-xs text-zinc-500">
            NO SPREADS ABOVE THRESHOLD THIS SESSION
          </p>
          <p className="mt-1 text-[11px] text-zinc-600">
            The desk fills automatically when the futures board feed returns
            contract closes (psx_futures_eod).
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[680px] border-collapse text-xs">
            <thead>
              <tr className="border-b border-zinc-800 bg-[#0c1017] text-left text-[10px] uppercase tracking-widest text-zinc-600">
                <th className="px-3 py-2 font-medium">Underlying</th>
                <th className="px-2 py-2 text-right font-medium">Ready</th>
                <th className="px-2 py-2 text-right font-medium">Futures</th>
                <th className="px-2 py-2 text-right font-medium">Spread</th>
                <th className="px-2 py-2 text-right font-medium">Ann. Yield</th>
                <th className="px-3 py-2 font-medium">Execution Order</th>
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
                  <td className="px-2 py-1.5 text-right font-mono tabular-nums text-zinc-100">
                    {fmtPrice(row.readyClose)}
                  </td>
                  <td className="px-2 py-1.5 text-right font-mono tabular-nums text-zinc-300">
                    <span className="block">{fmtPrice(row.futuresClose)}</span>
                    <span className="block text-[10px] text-zinc-600">
                      {row.futuresSymbol ?? "—"}
                    </span>
                  </td>
                  <td className="px-2 py-1.5 text-right">
                    <span className="inline-block rounded bg-cyan-500/10 px-1.5 py-0.5 font-mono tabular-nums text-cyan-300 ring-1 ring-cyan-500/30">
                      {fmtPct(row.spreadPct)}
                    </span>
                  </td>
                  <td className="px-2 py-1.5 text-right font-mono tabular-nums text-zinc-300">
                    {fmtPct(row.annualizedSimplePct, 0)}
                    {row.annualizedCompoundPct != null && (
                      <span className="block text-[10px] text-zinc-600">
                        cmp {fmtPct(row.annualizedCompoundPct, 0)}
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-1.5 font-mono text-[11px] text-emerald-400">
                    {row.order ?? "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
