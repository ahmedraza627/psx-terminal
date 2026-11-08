"use client";

import React, { useState } from "react";

export interface HistoryRecord {
  date: string;
  ticker: string;
  type: "BUY" | "AVOID";
  entryPrice: number;
  stopPrice: number;
  targetPrice: number;
  postPrice30D: number;
  notes: string;
}

export default function HistoryLedgerClient({ initialRecords }: { initialRecords: HistoryRecord[] }) {
  const [filter, setFilter] = useState<"ALL" | "BUYS" | "AVOIDS" | "TARGET_HIT">("ALL");

  const processed = initialRecords.map((item) => {
    const returnPct = Number((((item.postPrice30D - item.entryPrice) / item.entryPrice) * 100).toFixed(2));
    let status: "TARGET HIT" | "STOPPED OUT" | "ACTIVE" | "PRESERVED" = "ACTIVE";

    if (item.type === "AVOID") {
      status = "PRESERVED";
    } else if (item.postPrice30D >= item.targetPrice) {
      status = "TARGET HIT";
    } else if (item.postPrice30D <= item.stopPrice) {
      status = "STOPPED OUT";
    }

    return { ...item, returnPct, status };
  });

  const filtered = processed.filter((item) => {
    if (filter === "BUYS") return item.type === "BUY";
    if (filter === "AVOIDS") return item.type === "AVOID";
    if (filter === "TARGET_HIT") return item.status === "TARGET HIT";
    return true;
  });

  return (
    <div className="rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden">
      <div className="flex flex-wrap items-center justify-between p-4 border-b border-slate-100 gap-3">
        <div className="flex items-center gap-2">
          {(["ALL", "BUYS", "AVOIDS", "TARGET_HIT"] as const).map((mode) => (
            <button
              key={mode}
              onClick={() => setFilter(mode)}
              className={`px-3 py-1 text-xs font-semibold rounded-md transition-all ${
                filter === mode ? "bg-blue-600 text-white shadow-sm" : "bg-slate-100 text-slate-600 hover:bg-slate-200"
              }`}
            >
              {mode.replace("_", " ")}
            </button>
          ))}
        </div>
        <span className="text-xs text-slate-400 font-mono">Showing {filtered.length} of {processed.length} Logs</span>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs font-mono">
          <thead className="bg-slate-50 text-[10px] text-slate-500 uppercase border-b border-slate-200">
            <tr>
              <th className="p-3">Date</th>
              <th className="p-3">Ticker</th>
              <th className="p-3">Type</th>
              <th className="p-3">Entry Ref</th>
              <th className="p-3">Invalidation</th>
              <th className="p-3">Target</th>
              <th className="p-3">Latest Close</th>
              <th className="p-3">P&amp;L %</th>
              <th className="p-3">Audit Status</th>
              <th className="p-3">Notes</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {filtered.map((item, idx) => (
              <tr key={idx} className="hover:bg-slate-50/80 transition-colors">
                <td className="p-3 text-slate-500 whitespace-nowrap">{item.date}</td>
                <td className="p-3 font-extrabold text-slate-900">{item.ticker}</td>
                <td className="p-3">
                  <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                    item.type === "BUY" ? "bg-blue-50 text-blue-700 border border-blue-200" : "bg-rose-50 text-rose-700 border border-rose-200"
                  }`}>
                    {item.type}
                  </span>
                </td>
                <td className="p-3 font-bold text-slate-800">PKR {item.entryPrice}</td>
                <td className="p-3 text-rose-600">PKR {item.stopPrice}</td>
                <td className="p-3 text-emerald-600">PKR {item.targetPrice}</td>
                <td className="p-3 font-black text-slate-900">PKR {item.postPrice30D}</td>
                <td className={`p-3 font-black ${
                  item.returnPct > 0 ? "text-emerald-600" : item.returnPct < 0 ? "text-rose-600" : "text-slate-600"
                }`}>
                  {item.returnPct > 0 ? `+${item.returnPct}%` : `${item.returnPct}%`}
                </td>
                <td className="p-3 whitespace-nowrap">
                  <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                    item.status === "TARGET HIT" ? "bg-emerald-100 text-emerald-800" :
                    item.status === "PRESERVED" ? "bg-slate-100 text-slate-700" :
                    item.status === "STOPPED OUT" ? "bg-rose-100 text-rose-800" : "bg-blue-100 text-blue-800"
                  }`}>
                    {item.status}
                  </span>
                </td>
                <td className="p-3 text-slate-600 max-w-xs font-sans text-[11px]">{item.notes}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}