"use client";

import React, { useEffect, useState } from "react";

interface HistoryEntry {
  date: string;
  ticker: string;
  type: "BUY" | "AVOID";
  entryRef: number;
  invalidation: number;
  target: number;
  latestClose: number;
  pnlPct: number;
  status: string;
  notes?: string;
}

export default function HistoryPage() {
  const [rows, setRows] = useState<HistoryEntry[]>([]);
  const [filter, setFilter] = useState<"ALL" | "BUY" | "AVOID">("ALL");

  useEffect(() => {
    fetch("/data/history.json", { cache: "no-store" })
      .then((r) => r.json())
      .then((d) => setRows(Array.isArray(d) ? d : d.history ?? []))
      .catch(() => {});
  }, []);

  const filtered = rows.filter((r) => (filter === "ALL" ? true : r.type === filter));
  const resolved = rows.filter((r) => r.status !== "IN PLAY");
  const wins = resolved.filter((r) => r.pnlPct > 0).length;
  const winRate = resolved.length ? ((wins / resolved.length) * 100).toFixed(1) : "0.0";

  return (
    <div className="p-4 sm:p-6 max-w-6xl mx-auto space-y-5">
      <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-sm flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <h1 className="text-lg font-bold text-slate-900">Audit &amp; Performance Ledger</h1>
          <p className="text-xs text-slate-500">
            Out-of-sample verification against certified PSX EOD closing tape.
          </p>
        </div>
        <div className="flex items-center gap-1.5 font-mono text-xs">
          {(["ALL", "BUY", "AVOID"] as const).map((tab) => (
            <button
              key={tab}
              onClick={() => setFilter(tab)}
              className={`px-3 py-1.5 rounded-lg border font-bold transition ${
                filter === tab
                  ? "bg-slate-900 text-white border-slate-900"
                  : "bg-white text-slate-700 border-slate-200 hover:bg-slate-50"
              }`}
            >
              {tab}
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 font-mono">
        <div className="bg-white border border-slate-200 rounded-xl p-3.5 shadow-sm">
          <div className="text-[10px] text-slate-500">TOTAL SIGNALS</div>
          <div className="text-lg font-bold text-slate-900 mt-0.5">{rows.length}</div>
        </div>
        <div className="bg-white border border-slate-200 rounded-xl p-3.5 shadow-sm">
          <div className="text-[10px] text-slate-500">RESOLVED WIN RATE</div>
          <div className="text-lg font-bold text-emerald-700 mt-0.5">{winRate}%</div>
        </div>
        <div className="bg-white border border-slate-200 rounded-xl p-3.5 shadow-sm">
          <div className="text-[10px] text-slate-500">ACTIVE IN PLAY</div>
          <div className="text-lg font-bold text-indigo-700 mt-0.5">
            {rows.filter((r) => r.status === "IN PLAY").length}
          </div>
        </div>
        <div className="bg-white border border-slate-200 rounded-xl p-3.5 shadow-sm">
          <div className="text-[10px] text-slate-500">DATA SOURCE</div>
          <div className="text-lg font-bold text-slate-900 mt-0.5">PSX .Z TAPE</div>
        </div>
      </div>

      <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-x-auto">
        <table className="w-full text-left border-collapse text-xs font-mono">
          <thead>
            <tr className="border-b border-slate-200 bg-slate-50 text-[10px] text-slate-500 uppercase">
              <th className="p-3">Date</th>
              <th className="p-3">Ticker</th>
              <th className="p-3">Side</th>
              <th className="p-3">Entry Ref</th>
              <th className="p-3">Stop</th>
              <th className="p-3">Target</th>
              <th className="p-3">Latest</th>
              <th className="p-3">P&amp;L</th>
              <th className="p-3">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {filtered.map((r, i) => (
              <tr key={`${r.date}-${r.ticker}-${i}`} className="hover:bg-slate-50/80">
                <td className="p-3 text-slate-600">{r.date}</td>
                <td className="p-3 font-bold text-slate-900">{r.ticker}</td>
                <td className="p-3">
                  <span
                    className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                      r.type === "BUY" ? "bg-emerald-100 text-emerald-800" : "bg-rose-100 text-rose-800"
                    }`}
                  >
                    {r.type}
                  </span>
                </td>
                <td className="p-3">PKR {r.entryRef.toFixed(2)}</td>
                <td className="p-3 text-rose-600">PKR {r.invalidation.toFixed(2)}</td>
                <td className="p-3 text-emerald-700">PKR {r.target.toFixed(2)}</td>
                <td className="p-3 font-bold">PKR {r.latestClose.toFixed(2)}</td>
                <td className={`p-3 font-bold ${r.pnlPct >= 0 ? "text-emerald-600" : "text-rose-600"}`}>
                  {r.pnlPct >= 0 ? "+" : ""}
                  {r.pnlPct.toFixed(1)}%
                </td>
                <td className="p-3">
                  <span className="px-2 py-0.5 rounded bg-slate-100 text-slate-800 text-[10px] font-bold">
                    {r.status}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
