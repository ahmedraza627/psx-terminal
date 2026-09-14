"use client";

import FeedErrorPill from "./FeedErrorPill";
import type { DataStatus } from "@/lib/queries";

export interface InsiderRow {
  tradeDate: string;
  ticker: string;
  entryReference: number | null;
  netNotionalPkr: number | null;
  disclosureCount: number | null;
  seniorDisclosures: number | null;
  conviction: string | null;
  rationale: string;
}

function fmtPrice(value: number | null): string {
  return value == null ? "—" : value.toFixed(2);
}

function fmtMillions(value: number | null): string {
  return value == null
    ? "—"
    : `${value >= 0 ? "+" : ""}${(value / 1e6).toFixed(1)}M`;
}

function convictionBadge(conviction: string | null) {
  if (conviction === "HIGH") {
    return (
      <span className="inline-block rounded-[2px] bg-bull/10 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-bull ring-1 ring-bull/30">
        HIGH
      </span>
    );
  }
  if (conviction === "ELEVATED") {
    return (
      <span className="inline-block rounded-[2px] bg-info/10 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-info ring-1 ring-info/30">
        ELEVATED
      </span>
    );
  }
  return (
    <span className="inline-block rounded-[2px] bg-panel px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-muted">
      {conviction ?? "—"}
    </span>
  );
}

export default function InsiderRadarBlotter({
  rows,
  status,
}: {
  rows: InsiderRow[];
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
          <>
            <p className="font-mono text-xs uppercase tracking-widest text-warn">
              [SCHEMA PENDING: RUN SCHEMA.SQL IN SUPABASE]
            </p>
            <p className="mt-1 text-[11px] text-ghost">
              The psx_insider_trades table does not exist yet in Supabase.
            </p>
          </>
        ) : pending ? (
          <>
            <p className="font-mono text-xs uppercase tracking-widest text-info">
              [INSIDER FEED: AWAITING PSX ANNOUNCEMENTS FEED]
            </p>
            <p className="mt-1 text-[11px] text-ghost">
              Fills when aggregated SECP/PSX sponsor &amp; director disclosures
              exceed the 5m PKR net-notional floor (psx_insider_trades).
            </p>
          </>
        ) : (
          <>
            <p className="font-mono text-xs text-muted">
              NO QUALIFYING INSIDER ACCUMULATION THIS SESSION
            </p>
            <p className="mt-1 text-[11px] text-ghost">
              Fills when aggregated SECP/PSX sponsor &amp; director disclosures
              exceed the 5m PKR net-notional floor (psx_insider_trades).
            </p>
          </>
        )}
      </div>
    );
  }

  return (
    <section>
      <div className="flex items-center justify-between border-b border-hairline px-3 py-2">
        <h2 className="text-[10px] font-medium uppercase tracking-widest text-ghost">
          SECP Insider &amp; Sponsor Accumulation Radar
        </h2>
        <span className="font-mono text-[11px] tabular-nums text-muted">
          {rows.length} NET BUYER{rows.length === 1 ? "" : "S"}
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] border-collapse text-xs">
          <thead>
            <tr className="border-b border-hairline bg-panel text-left text-[10px] uppercase tracking-widest text-ghost">
              <th className="px-3 py-2 font-medium">Ticker</th>
              <th className="px-2 py-2 font-medium">Conviction</th>
              <th className="px-2 py-2 text-right font-medium">LTP</th>
              <th className="px-2 py-2 text-right font-medium">Net Notional</th>
              <th className="px-2 py-2 text-right font-medium">Disclosures</th>
              <th className="px-3 py-2 text-right font-medium">Senior</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={`${row.tradeDate}-${row.ticker}`}
                className="border-b border-hairline hover:bg-hoverline"
              >
                <td className="px-3 py-1.5 font-mono font-semibold text-ink">
                  {row.ticker}
                </td>
                <td className="px-2 py-1.5">
                  {convictionBadge(row.conviction)}
                </td>
                <td className="px-2 py-1.5 text-right font-mono tabular-nums text-ink">
                  {fmtPrice(row.entryReference)}
                </td>
                <td className="px-2 py-1.5 text-right font-mono tabular-nums text-bull">
                  {fmtMillions(row.netNotionalPkr)}
                </td>
                <td className="px-2 py-1.5 text-right font-mono tabular-nums text-ink">
                  {row.disclosureCount ?? "—"}
                </td>
                <td className="px-3 py-1.5 text-right font-mono tabular-nums text-ink">
                  {row.seniorDisclosures ?? 0}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="border-t border-hairline px-3 py-2">
        <p className="font-mono text-[10px] leading-relaxed text-ghost">
          Rationale trail:
          {rows.slice(0, 3).map((r) => (
            <span key={r.ticker} className="mt-1 block text-muted">
              ▸ {r.ticker} — {r.rationale}
            </span>
          ))}
        </p>
      </div>
    </section>
  );
}
