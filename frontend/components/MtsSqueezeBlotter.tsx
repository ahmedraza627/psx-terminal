"use client";

import FeedErrorPill from "./FeedErrorPill";
import type { DataStatus } from "@/lib/queries";

export interface MtsRow {
  tradeDate: string;
  ticker: string;
  entryReference: number | null;
  signalType: string;
  utilizationPct: number | null;
  valueDropPct: number | null;
  priceDropPct: number | null;
  mtsValuePkr: number | null;
  stance: string | null;
  rationale: string;
}

function fmtPrice(value: number | null): string {
  return value == null ? "—" : value.toFixed(2);
}

function fmtPct(value: number | null, digits = 1): string {
  return value == null ? "—" : `${value.toFixed(digits)}%`;
}

function fmtMillions(value: number | null): string {
  return value == null ? "—" : `${(value / 1e6).toFixed(0)}M`;
}

export default function MtsSqueezeBlotter({
  rows,
  status,
}: {
  rows: MtsRow[];
  status?: DataStatus | null;
}) {
  if (rows.length === 0) {
    const pending = status?.feedPending ?? false;
    const missing = status?.tableMissing ?? false;
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
            [MTS FEED: AWAITING NCCPL CLEARING]
          </p>
        ) : (
          <p className="font-mono text-xs text-muted">
            NO MARGIN CASCADE OR FLUSHOUT FOOTPRINTS THIS SESSION
          </p>
        )}
        <p className="mt-1 text-[11px] text-ghost">
          Fills when NCCPL MTS exposure data shows crowded leveraged longs
          (utilization ≥ 80% of cap) or forced-deleveraging bottoms
          (nccpl_mts_leverage).
        </p>
      </div>
    );
  }

  const cascadeCount = rows.filter(
    (r) => r.signalType === "MARGIN_CASCADE_RISK"
  ).length;

  return (
    <section>
      <div className="flex items-center justify-between border-b border-hairline px-3 py-2">
        <h2 className="text-[10px] font-medium uppercase tracking-widest text-ghost">
          NCCPL MTS Leverage - Cascade &amp; Flushout Hunter
        </h2>
        <span className="font-mono text-[11px] tabular-nums text-muted">
          {cascadeCount} CASCADE · {rows.length - cascadeCount} FLUSH
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[680px] border-collapse text-xs">
          <thead>
            <tr className="border-b border-hairline bg-panel text-left text-[10px] uppercase tracking-widest text-ghost">
              <th className="px-3 py-2 font-medium">Ticker</th>
              <th className="px-2 py-2 font-medium">Signal</th>
              <th className="px-2 py-2 text-right font-medium">LTP</th>
              <th className="px-2 py-2 text-right font-medium">Util %</th>
              <th className="px-2 py-2 text-right font-medium">Val Drop</th>
              <th className="px-2 py-2 text-right font-medium">Price Drop</th>
              <th className="px-3 py-2 text-right font-medium">MTS Value</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const isCascade = row.signalType === "MARGIN_CASCADE_RISK";
              return (
                <tr
                  key={`${row.tradeDate}-${row.ticker}-${row.signalType}`}
                  className="border-b border-hairline hover:bg-hoverline"
                >
                  <td className="px-3 py-1.5 font-mono font-semibold text-ink">
                    {row.ticker}
                  </td>
                  <td className="px-2 py-1.5">
                    <span
                      className={`inline-block rounded-[2px] px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider ring-1 ${
                        isCascade
                          ? "bg-bear/10 text-bear ring-bear/30"
                          : "bg-warn/10 text-warn ring-warn/30"
                      }`}
                    >
                      {isCascade ? "CASCADE RISK" : "FLUSH BOTTOM"}
                    </span>
                  </td>
                  <td className="px-2 py-1.5 text-right font-mono tabular-nums text-ink">
                    {fmtPrice(row.entryReference)}
                  </td>
                  <td
                    className={`px-2 py-1.5 text-right font-mono tabular-nums ${
                      row.utilizationPct != null && row.utilizationPct >= 80
                        ? "text-bear"
                        : "text-ink"
                    }`}
                  >
                    {row.utilizationPct == null
                      ? "—"
                      : `${row.utilizationPct.toFixed(0)}%`}
                  </td>
                  <td className="px-2 py-1.5 text-right font-mono tabular-nums text-ink">
                    {fmtPct(row.valueDropPct, 0)}
                  </td>
                  <td className="px-2 py-1.5 text-right font-mono tabular-nums text-bear">
                    {row.priceDropPct != null && row.priceDropPct > 0
                      ? `−${fmtPct(row.priceDropPct)}`
                      : "—"}
                  </td>
                  <td className="px-3 py-1.5 text-right font-mono tabular-nums text-ink">
                    {fmtMillions(row.mtsValuePkr)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="border-t border-hairline px-3 py-2">
        <p className="font-mono text-[10px] leading-relaxed text-ghost">
          Stances:
          {rows.slice(0, 3).map((r) => (
            <span key={`${r.ticker}-${r.signalType}`} className="mt-1 block text-muted">
              ▸ {r.ticker} [{r.stance ?? "—"}] — {r.rationale}
            </span>
          ))}
        </p>
      </div>
    </section>
  );
}
