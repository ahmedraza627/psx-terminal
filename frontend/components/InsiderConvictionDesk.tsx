"use client";

import FeedErrorPill from "./FeedErrorPill";
import type { DataStatus, DisclosureRow } from "@/lib/queries";

function fmtMn(value: number | null): string {
  if (value == null) return "—";
  const mn = value / 1e6;
  if (mn >= 1000) return `${(mn / 1000).toFixed(2)}B`;
  if (mn >= 10) return mn.toFixed(0);
  return mn.toFixed(2);
}

function fmtQty(value: number): string {
  if (value >= 1e6) return `${(value / 1e6).toFixed(2)}M`;
  if (value >= 1e3) return `${(value / 1e3).toFixed(0)}K`;
  return String(value);
}

const CONVICTION_STYLES: Record<string, string> = {
  ULTRA_HIGH:
    "bg-amber-400/15 text-warn ring-amber-400/40 font-bold",
  HIGH: "bg-bull/10 text-bull ring-bull/30",
  STANDARD: "bg-panel text-muted ring-hairline",
};

const TYPE_STYLES: Record<string, string> = {
  BUY: "text-bull",
  SELL: "text-bear",
};

export default function InsiderConvictionDesk({
  rows,
  status,
}: {
  rows: DisclosureRow[];
  status?: DataStatus | null;
}) {
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
            [INSIDER LEDGER: AWAITING PSX BOARD-LETTER FEED]
          </p>
        ) : (
          <p className="font-mono text-xs uppercase tracking-widest text-info">
            [INSIDER LEDGER: NO FILINGS THIS SESSION]
          </p>
        )}
        <p className="mt-1 text-[11px] leading-relaxed text-ghost">
          SECP-mandated insider dealings parsed from PSX company
          announcements. PSX&apos;s announcements renderer is JS-only today;
          the ledger populates the moment filings parse — never fabricated.
        </p>
      </div>
    );
  }

  const ultra = rows.filter((r) => r.conviction === "ULTRA_HIGH").length;
  const buys = rows.filter((r) => r.tradeType === "BUY").length;
  const netNotional = rows.reduce(
    (acc, r) =>
      acc + (r.notionalPkr ?? 0) * (r.tradeType === "SELL" ? -1 : 1),
    0
  );

  return (
    <section>
      <div className="flex items-center justify-between border-b border-hairline px-3 py-2">
        <h2 className="text-[10px] font-medium uppercase tracking-widest text-ghost">
          Insider Conviction - SECP Director / Sponsor Filings
        </h2>
        <span className="font-mono text-[11px] tabular-nums text-muted">
          {ultra} ULTRA · {buys}/{rows.length} BUY ·{" "}
          <span className={netNotional >= 0 ? "text-bull" : "text-bear"}>
            {netNotional >= 0 ? "+" : "−"}
            {fmtMn(Math.abs(netNotional))}M NET
          </span>
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] border-collapse text-xs">
          <thead>
            <tr className="border-b border-hairline bg-panel text-left text-[10px] uppercase tracking-widest text-ghost">
              <th className="px-3 py-2 font-medium">Ticker</th>
              <th className="px-2 py-2 font-medium">Insider</th>
              <th className="px-2 py-2 font-medium">Designation</th>
              <th className="px-2 py-2 font-medium">Side</th>
              <th className="px-2 py-2 text-right font-medium">Qty</th>
              <th className="px-2 py-2 text-right font-medium">Rate</th>
              <th className="px-2 py-2 text-right font-medium">Notional (M)</th>
              <th className="px-3 py-2 font-medium">Conviction</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <tr
                key={`${row.tradeDate}-${row.ticker}-${row.insiderName}-${row.quantity}-${index}`}
                className="border-b border-hairline hover:bg-hoverline"
              >
                <td className="px-3 py-1.5 font-mono font-semibold text-ink">
                  {row.ticker}
                </td>
                <td className="max-w-[140px] truncate px-2 py-1.5 font-mono text-[11px] text-muted">
                  {row.insiderName}
                </td>
                <td className="px-2 py-1.5 font-mono text-[10px] uppercase tracking-wider text-muted">
                  {row.designation}
                </td>
                <td
                  className={`px-2 py-1.5 font-mono text-[11px] font-bold ${
                    TYPE_STYLES[row.tradeType] ?? "text-muted"
                  }`}
                >
                  {row.tradeType}
                </td>
                <td className="px-2 py-1.5 text-right font-mono tabular-nums text-ink">
                  {fmtQty(row.quantity)}
                </td>
                <td className="px-2 py-1.5 text-right font-mono tabular-nums text-muted">
                  {row.rate == null ? "—" : row.rate.toFixed(2)}
                </td>
                <td className="px-2 py-1.5 text-right font-mono tabular-nums text-ink">
                  {fmtMn(row.notionalPkr)}
                </td>
                <td className="px-3 py-1.5">
                  <span
                    className={`inline-block rounded-[2px] px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider ring-1 ${
                      CONVICTION_STYLES[row.conviction] ??
                      CONVICTION_STYLES.STANDARD
                    }`}
                  >
                    {row.conviction.replace("_", "-")}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="border-t border-hairline px-3 py-2">
        <p className="font-mono text-[10px] leading-relaxed text-ghost">
          ULTRA-HIGH = BUY ≥ 10M PKR by a Sponsor/Director (principal money,
          strongest alignment signal on PSX) · HIGH = BUY ≥ 10M any insider or
          ≥ 2M Sponsor/Director · net notional is signed by side.
        </p>
      </div>
    </section>
  );
}
