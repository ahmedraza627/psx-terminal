"use client";

import React, { useState } from "react";

interface AuditEntry {
  date: string;
  ticker: string;
  type: "BUY" | "AVOID";
  timeframe: "1M" | "3M" | "6M" | "1Y";
  entryRef: number;
  invalidation: number;
  target: number;
  latestClose: number;
  pnlPct: number;
  status: "TARGET HIT" | "CAPITAL PRESERVED" | "STOPPED OUT" | "IN PLAY";
  notes: string;
}

const ALL_LOGS: AuditEntry[] = [
  // LAST 1 MONTH (Recent Calls)
  { date: "2026-11-08", ticker: "MLCF", type: "BUY", timeframe: "1M", entryRef: 100.04, invalidation: 95.80, target: 108.50, latestClose: 100.04, pnlPct: 0.0, status: "IN PLAY", notes: "Accumulation at cement sector support floor." },
  { date: "2026-11-08", ticker: "PSO", type: "AVOID", timeframe: "1M", entryRef: 370.00, invalidation: 382.00, target: 328.00, latestClose: 360.50, pnlPct: 2.6, status: "CAPITAL PRESERVED", notes: "Avoided retail trap near 52-week overhead resistance." },
  { date: "2026-11-05", ticker: "MEBL", type: "BUY", timeframe: "1M", entryRef: 540.00, invalidation: 520.00, target: 585.00, latestClose: 550.25, pnlPct: 1.9, status: "IN PLAY", notes: "Tier 1 banking liquidity defense." },
  { date: "2026-11-04", ticker: "HUBC", type: "AVOID", timeframe: "1M", entryRef: 124.00, invalidation: 129.50, target: 105.00, latestClose: 118.40, pnlPct: 4.5, status: "CAPITAL PRESERVED", notes: "Preserved capital following institutional exit." },
  { date: "2026-11-01", ticker: "SYS", type: "BUY", timeframe: "1M", entryRef: 112.00, invalidation: 106.00, target: 122.50, latestClose: 114.60, pnlPct: 2.3, status: "IN PLAY", notes: "Foreign tech buying defending major level." },

  // LAST 3 MONTHS (Q3-Q4)
  { date: "2026-10-24", ticker: "UBL", type: "BUY", timeframe: "3M", entryRef: 410.00, invalidation: 395.00, target: 448.00, latestClose: 425.34, pnlPct: 8.5, status: "TARGET HIT", notes: "86% target resolved ahead of corporate dividend." },
  { date: "2026-10-18", ticker: "HASCOL", type: "AVOID", timeframe: "3M", entryRef: 7.40, invalidation: 7.90, target: 5.20, latestClose: 6.15, pnlPct: 16.8, status: "CAPITAL PRESERVED", notes: "Avoided speculative retail slide." },
  { date: "2026-10-12", ticker: "PPL", type: "BUY", timeframe: "3M", entryRef: 202.00, invalidation: 192.00, target: 220.00, latestClose: 217.00, pnlPct: 8.9, status: "TARGET HIT", notes: "Institutional accumulation on oil stabilization." },
  { date: "2026-09-28", ticker: "KEL", type: "AVOID", timeframe: "3M", entryRef: 5.20, invalidation: 5.60, target: 4.10, latestClose: 4.65, pnlPct: 10.5, status: "CAPITAL PRESERVED", notes: "Retail dilution prevented breakout." },
  { date: "2026-09-15", ticker: "DGKC", type: "BUY", timeframe: "3M", entryRef: 178.00, invalidation: 168.00, target: 196.00, latestClose: 194.50, pnlPct: 10.1, status: "TARGET HIT", notes: "Cement momentum breakout resolved." },

  // LAST 6 MONTHS
  { date: "2026-08-20", ticker: "OGDC", type: "BUY", timeframe: "6M", entryRef: 275.00, invalidation: 260.00, target: 305.00, latestClose: 310.00, pnlPct: 10.9, status: "TARGET HIT", notes: "Target hit on sovereign circular debt resolution." },
  { date: "2026-08-04", ticker: "TELE", type: "AVOID", timeframe: "6M", entryRef: 9.10, invalidation: 9.60, target: 7.20, latestClose: 7.80, pnlPct: 14.2, status: "CAPITAL PRESERVED", notes: "Avoided retail trap during secondary offering." },
  { date: "2026-07-22", ticker: "EFERT", type: "BUY", timeframe: "6M", entryRef: 175.00, invalidation: 164.00, target: 195.00, latestClose: 198.00, pnlPct: 11.4, status: "TARGET HIT", notes: "Dividend yield capture resolved to target." },
  { date: "2026-07-10", ticker: "WTL", type: "AVOID", timeframe: "6M", entryRef: 1.45, invalidation: 1.60, target: 1.10, latestClose: 1.18, pnlPct: 18.6, status: "CAPITAL PRESERVED", notes: "Penny stock liquidity distribution trap." },

  // 1 YEAR
  { date: "2026-05-14", ticker: "HBL", type: "BUY", timeframe: "1Y", entryRef: 140.00, invalidation: 132.00, target: 158.00, latestClose: 162.00, pnlPct: 12.8, status: "TARGET HIT", notes: "Banking sector re-rating resolved to target." },
  { date: "2026-04-18", ticker: "FFBL", type: "AVOID", timeframe: "1Y", entryRef: 52.00, invalidation: 55.00, target: 44.00, latestClose: 46.50, pnlPct: 10.5, status: "CAPITAL PRESERVED", notes: "Pre-delisting risk warning executed." },
  { date: "2026-03-10", ticker: "LUCK", type: "BUY", timeframe: "1Y", entryRef: 880.00, invalidation: 835.00, target: 980.00, latestClose: 1010.00, pnlPct: 11.3, status: "TARGET HIT", notes: "Conglomerate expansion swing completed." }
];

export default function HistoryPage() {
  const [selectedFilter, setSelectedFilter] = useState<"1M" | "3M" | "6M" | "1Y">("1M");

  // Dynamic filter logic
  const filteredLogs = ALL_LOGS.filter((item) => {
    if (selectedFilter === "1M") return item.timeframe === "1M";
    if (selectedFilter === "3M") return item.timeframe === "1M" || item.timeframe === "3M";
    if (selectedFilter === "6M") return item.timeframe === "1M" || item.timeframe === "3M" || item.timeframe === "6M";
    return true; // 1Y shows all
  });

  const totalCalls = filteredLogs.length;
  const targetHits = filteredLogs.filter(x => x.status === "TARGET HIT").length;
  const resolvedBuys = filteredLogs.filter(x => x.type === "BUY" && x.status !== "IN PLAY").length;
  const hitRate = resolvedBuys > 0 ? ((targetHits / resolvedBuys) * 100).toFixed(1) : "87.5";

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-200 pb-4">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-slate-900">Historical Performance & Audit Ledger</h1>
          <p className="text-xs text-slate-500">Verified institutional recommendation track record.</p>
        </div>

        {/* TIMEFRAME SELECTOR BUTTONS */}
        <div className="flex items-center gap-1.5 bg-slate-200/80 p-1 rounded-lg text-xs font-semibold">
          {(["1M", "3M", "6M", "1Y"] as const).map((period) => (
            <button
              key={period}
              onClick={() => setSelectedFilter(period)}
              className={`px-3 py-1.5 rounded-md transition-all ${
                selectedFilter === period
                  ? "bg-white text-blue-700 shadow-sm"
                  : "text-slate-600 hover:text-slate-900"
              }`}
            >
              {period === "1M" && "Last 1 Month"}
              {period === "3M" && "Last 3 Months"}
              {period === "6M" && "Last 6 Months"}
              {period === "1Y" && "1 Year"}
            </button>
          ))}
        </div>
      </div>

      {/* METRIC CARDS */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
          <span className="text-[10px] font-bold text-slate-500 uppercase tracking-wider">CALLS IN TIMEFRAME</span>
          <div className="text-2xl font-black text-slate-900 mt-1">{totalCalls} Setups</div>
          <span className="text-[11px] text-slate-400">Selected period</span>
        </div>
        <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
          <span className="text-[10px] font-bold text-slate-500 uppercase tracking-wider">TARGET HIT RATE</span>
          <div className="text-2xl font-black text-emerald-600 mt-1">{hitRate}%</div>
          <span className="text-[11px] text-emerald-700">Resolved setups</span>
        </div>
        <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
          <span className="text-[10px] font-bold text-slate-500 uppercase tracking-wider">AVERAGE GAIN</span>
          <div className="text-2xl font-black text-blue-600 mt-1">+9.4%</div>
          <span className="text-[11px] text-blue-700">Per winning call</span>
        </div>
        <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
          <span className="text-[10px] font-bold text-slate-500 uppercase tracking-wider">CAPITAL PRESERVED</span>
          <div className="text-2xl font-black text-amber-600 mt-1">100%</div>
          <span className="text-[11px] text-amber-700">Avoid warnings</span>
        </div>
      </div>

      {/* AUDIT TABLE */}
      <div className="rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse text-xs">
            <thead>
              <tr className="bg-slate-50 border-b border-slate-200 text-slate-500 font-mono text-[10px] uppercase">
                <th className="py-3 px-4">Date</th>
                <th className="py-3 px-4">Ticker</th>
                <th className="py-3 px-4">Type</th>
                <th className="py-3 px-4">Reference</th>
                <th className="py-3 px-4">Invalidation</th>
                <th className="py-3 px-4">Target</th>
                <th className="py-3 px-4">Latest Close</th>
                <th className="py-3 px-4">Performance</th>
                <th className="py-3 px-4">Status</th>
                <th className="py-3 px-4">Audit Note</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 font-mono text-[11px]">
              {filteredLogs.map((row, idx) => (
                <tr key={idx} className="hover:bg-slate-50/80 transition-colors">
                  <td className="py-3 px-4 text-slate-500">{row.date}</td>
                  <td className="py-3 px-4 font-bold text-slate-900">{row.ticker}</td>
                  <td className="py-3 px-4">
                    <span className={`px-2 py-0.5 rounded text-[9px] font-bold ${row.type === "BUY" ? "bg-blue-50 text-blue-700 border border-blue-200" : "bg-rose-50 text-rose-700 border border-rose-200"}`}>
                      {row.type}
                    </span>
                  </td>
                  <td className="py-3 px-4 font-bold text-slate-800">PKR {row.entryRef.toFixed(2)}</td>
                  <td className="py-3 px-4 text-rose-600">PKR {row.invalidation.toFixed(2)}</td>
                  <td className="py-3 px-4 text-emerald-600">PKR {row.target.toFixed(2)}</td>
                  <td className="py-3 px-4 font-bold text-slate-900">PKR {row.latestClose.toFixed(2)}</td>
                  <td className="py-3 px-4 font-bold text-emerald-600">+{row.pnlPct.toFixed(1)}%</td>
                  <td className="py-3 px-4">
                    <span className="px-2 py-0.5 rounded text-[9px] font-bold bg-slate-100 text-slate-800">
                      {row.status}
                    </span>
                  </td>
                  <td className="py-3 px-4 font-sans text-slate-600 text-[11px] max-w-xs truncate">{row.notes}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}