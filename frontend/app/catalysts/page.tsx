import path from "node:path";
import fs from "node:fs";

import { catalystMetadata } from "@/lib/catalystEngine";
import type { CatalystMetadata } from "@/lib/catalystEngine";

/** Catalyst & Dividend View — dedicated page for upcoming PSX board meetings. */
export const dynamic = "force-dynamic";

function loadBuys(): { ticker: string }[] {
  try {
    const raw = fs.readFileSync(
      path.join(process.cwd(), "frontend", "public", "data", "state.json"),
      "utf-8",
    );
    const parsed = JSON.parse(raw) as { top_buy_setups?: { ticker: string }[] };
    return parsed.top_buy_setups ?? [];
  } catch (err) {
    console.error("[Catalysts] state.json read failed:", err);
    return [];
  }
}

function loadAvoided(): { ticker: string }[] {
  try {
    const raw = fs.readFileSync(
      path.join(process.cwd(), "frontend", "public", "data", "state.json"),
      "utf-8",
    );
    const parsed = JSON.parse(raw) as { top_avoid_setups?: { ticker: string }[] };
    return parsed.top_avoid_setups ?? [];
  } catch (err) {
    console.error("[Catalysts] state.json read failed:", err);
    return [];
  }
}

function formatDate(dateStr: string): string {
  const d = new Date(dateStr);
  return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}

export default function CatalystsPage() {
  const buys = loadBuys();
  const avoids = loadAvoided();

  const rows: { ticker: string; metadata: CatalystMetadata | null }[] = [];
  for (const b of [...buys, ...avoids]) {
    const meta = catalystMetadata[b.ticker.toUpperCase()];
    if (meta) rows.push({ ticker: b.ticker, metadata: meta });
  }
  // Deterministic ordering: by board meeting date.
  rows.sort((a, b) => a.metadata!.boardMeetingDate!.localeCompare(b.metadata!.boardMeetingDate!));

  const upcoming = rows.filter((r) => r.metadata!.daysToMeeting <= 14);

  return (
    <div className="space-y-6">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-slate-100">
            Corporate Catalyst &amp; Dividend View
          </h1>
          <p className="text-xs text-slate-400">
            Upcoming PSX board meetings · dividend schedule · pre-meeting run-up vs. dump risk
          </p>
        </div>
        <span className="rounded-full bg-slate-800/70 px-3 py-1 text-[11px] font-semibold text-slate-400 border border-slate-800">
          Live
        </span>
      </div>

      {upcoming.length === 0 ? (
        <div className="rounded-xl border border-slate-800 bg-slate-50/40 p-6 text-center">
          <p className="text-xs text-slate-500">No catalyst entries due within 14 days.</p>
        </div>
      ) : (
        <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-5 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800 px-4 py-3">
            <div>
              <h3 className="text-sm font-bold text-slate-300">Upcoming Board Meetings (≤14 days)</h3>
              <p className="text-[11px] text-slate-500">Priority watchlist — pre-meeting run-up vs. post-result dump risk</p>
            </div>
            <span className="inline-flex items-center gap-1 rounded-full bg-blue-100 px-2.5 py-0.5 text-[10px] font-bold text-blue-300">
              ≤14 days
            </span>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="bg-slate-800/70 text-slate-400 uppercase text-[10px] tracking-wider">
                  <th className="px-4 py-2.5 text-left font-semibold">Ticker</th>
                  <th className="px-4 py-2.5 text-left font-semibold">Meeting Date</th>
                  <th className="px-4 py-2.5 text-left font-semibold">Expected Payout</th>
                  <th className="px-4 py-2.5 text-left font-semibold">Cash Dividend Yield</th>
                  <th className="px-4 py-2.5 text-left font-semibold">14D Run-up Status</th>
                  <th className="px-4 py-2.5 text-left font-semibold">Smart Money Verdict</th>
                </tr>
              </thead>
              <tbody>
                {upcoming.map(({ ticker, metadata }) => {
                  const isBuy = buys.some((b) => b.ticker === ticker);
                  const v = metadata!.catalystPhase;
                  const verdict =
                    v === "ACCUMULATION_RUNUP" && isBuy
                      ? "RIDE RUMOR"
                      : v === "EXHAUSTION_DUMP_WINDOW"
                      ? "DUMP ON NEWS"
                      : "MONITOR";
                  const verdictBadge =
                    verdict === "RIDE RUMOR"
                      ? "bg-emerald-500/10 text-emerald-300 border border-emerald-500/30"
                      : verdict === "DUMP ON NEWS"
                      ? "bg-rose-500/10 text-rose-300 border border-rose-500/30"
                      : "bg-blue-500/10 text-blue-300 border border-blue-500/30";
                  const payout = isBuy
                    ? metadata!.dividendYieldPct > 8
                      ? "High"
                      : "Normal"
                    : "N/A";
                  return (
                    <tr
                      key={ticker}
                      className="border-t border-slate-800 transition hover:bg-slate-50/60"
                    >
                      <td className="px-4 py-2.5 font-bold text-slate-100">{ticker}</td>
                      <td className="px-4 py-2.5 font-mono text-slate-400">{formatDate(metadata!.boardMeetingDate)}</td>
                      <td className="px-4 py-2.5 font-mono text-slate-400">{metadata!.dividendYieldPct > 0 ? metadata!.dividendYieldPct.toFixed(1) + "%" : "—"}</td>
                      <td className="px-4 py-2.5 font-mono text-slate-400">{metadata!.dividendYieldPct > 0 ? metadata!.dividendYieldPct.toFixed(1) + " %" : "—"}</td>
                      <td className="px-4 py-2.5 font-mono text-slate-400">
                        <span className="font-bold">+{metadata!.avgPreRunupPct.toFixed(1)}%</span>
                        <span className="text-slate-500"> avg (10-14d prior)</span>
                      </td>
                      <td className="px-4 py-2.5">
                        <span className={`inline-flex rounded-full px-2 py-0.5 text-[10px] font-bold ${verdictBadge}`}>
                          {verdict}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {rows.length > upcoming.length && (
            <div className="mt-4 rounded-xl border border-slate-800 bg-slate-50/40 p-4 text-xs text-slate-400">
              <span className="font-semibold text-slate-400">Note:</span> showing {upcoming.length} of {rows.length} tickers with catalyst metadata; all presented by meeting date.
            </div>
          )}
        </div>
      )}
    </div>
  );
}
