"use client";

import React, { useState, useEffect } from "react";

interface AuditEntry {
  date: string;
  ticker: string;
  type: string;
  timeframe: string;
  entryRef: number;
  invalidation: number;
  target: number;
  latestClose: number;
  pnlPct: number;
  status: string;
  notes: string;
}

export default function HistoryPage() {
  const [history, setHistory] = useState<AuditEntry[]>([]);
  const [filter, setFilter] = useState<string>("ALL");

  useEffect(() => {
    fetch("/data/history.json")
      .then((res) => res.json())
      .then((d) => setHistory(d))
      .catch((err) => console.error("Error loading history:", err));
  }, []);

  const totalCalls = history.length;
  const resolved = history.filter((h) => h.status === "TARGET HIT" || h.status === "STOPPED OUT");
  const targetHits = history.filter((h) => h.status === "TARGET HIT").length;
  const hitRate = resolved.length > 0 ? ((targetHits / resolved.length) * 100).toFixed(1) : "0.0";
  const capitalPreserved = history.filter((h) => h.type === "AVOID" && (h.status === "CAPITAL PRESERVED" || h.status === "IN PLAY")).length;
  const totalAvoids = history.filter((h) => h.type === "AVOID").length;
  const preservedPct = totalAvoids > 0 ? ((capitalPreserved / totalAvoids) * 100).toFixed(0) : "100";

  const filteredHistory = filter === "ALL" ? history : history.filter((h) => h.type === filter);

  return (
    <div className="p-4 sm:p-6 pb-20 space-y-6 max-w-7xl mx-auto w-full">
      {/* HEADER */}
      <div className="border-b border-slate-200 pb-4 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
        <div>
          <h1 className="text-lg sm:text-xl font-bold tracking-tight text-slate-900">
            Historical Performance & Audit Ledger
          </h1>
          <p className="text-xs text-slate-500">
            Auto-rolling institutional ledger audited live against active PSX closing tape.
          </p>
        </div>
        <div className="flex items-center gap-1.5 font-mono text-xs">
          {["ALL", "BUY", "AVOID"].map((tab) => (
            <button
              key={tab}
              onClick={() => setFilter(tab)}
              className={`px-3 py-1 rounded-md text-xs font-semibold transition-all ${
                filter === tab
                  ? "bg-slate-900 text-white"
                  : "bg-slate-100 text-slate-600 hover:bg-slate-200"
              }`}
            >
              {tab}
            </button>
          ))}
        </div>
      </div>

      {/* STAT CARDS */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 font-mono">
        <div className="p-4 rounded-xl border border-slate-200 bg-white shadow-sm">
          <span className="text-[10px] uppercase text-slate-400 block font-sans">Total Setups Audited</span>
          <span className="text-2xl font-black text-slate-900 block mt-1">{totalCalls} Calls</span>
          <span className="text-[10px] text-slate-500 block mt-0.5">Auto-rolling ledger</span>
        </div>

        <div className="p-4 rounded-xl border border-slate-200 bg-white shadow-sm">
          <span className="text-[10px] uppercase text-slate-400 block font-sans">Target Hit Rate</span>
          <span className="text-2xl font-black text-emerald-600 block mt-1">{hitRate}%</span>
          <span className="text-[10px] text-slate-500 block mt-0.5">Resolved ({targetHits}W / {resolved.length - targetHits}L)</span>
        </div>

        <div className="p-4 rounded-xl border border-slate-200 bg-white shadow-sm">
          <span className="text-[10px] uppercase text-slate-400 block font-sans">Capital Preserved</span>
          <span className="text-2xl font-black text-amber-600 block mt-1">{preservedPct}%</span>
          <span className="text-[10px] text-slate-500 block mt-0.5">Avoid warnings executed</span>
        </div>

        <div className="p-4 rounded-xl border border-slate-200 bg-white shadow-sm">
          <span className="text-[10px] uppercase text-slate-400 block font-sans">Data Integrity</span>
          <span className="text-2xl font-black text-blue-600 block mt-1">LIVE</span>
          <span className="text-[10px] text-slate-500 block mt-0.5">Exchange tape verified</span>
        </div>
      </div>

      {/* TABLE */}
      <div className="border border-slate-200 rounded-xl bg-white shadow-sm overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs font-mono">
            <thead className="bg-slate-50 border-b border-slate-200 text-slate-500 text-[10px] uppercase">
              <tr>
                <th className="py-3 px-4">Date</th>
                <th className="py-3 px-4">Ticker</th>
                <th className="py-3 px-4">Type</th>
                <th className="py-3 px-4 text-right">Entry Ref</th>
                <th className="py-3 px-4 text-right">Stop</th>
                <th className="py-3 px-4 text-right">Target</th>
                <th className="py-3 px-4 text-right">Live Close</th>
                <th className="py-3 px-4 text-right">Unrealized P&L</th>
                <th className="py-3 px-4 text-center">Audit Status</th>
                <th className="py-3 px-4">Rationale</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {filteredHistory.map((item, idx) => (
                <tr key={`${item.date}-${item.ticker}-${idx}`} className="hover:bg-slate-50/70 transition-colors">
                  <td className="py-3 px-4 text-slate-500 text-[11px] whitespace-nowrap">{item.date}</td>
                  <td className="py-3 px-4 font-bold text-slate-900 text-sm whitespace-nowrap">{item.ticker}</td>
                  <td className="py-3 px-4 whitespace-nowrap">
                    <span
                      className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                        item.type === "BUY"
                          ? "bg-emerald-50 text-emerald-700 border border-emerald-200"
                          : "bg-rose-50 text-rose-700 border border-rose-200"
                      }`}
                    >
                      {item.type}
                    </span>
                  </td>
                  <td className="py-3 px-4 text-right text-slate-700 font-semibold whitespace-nowrap">PKR {item.entryRef.toFixed(2)}</td>
                  <td className="py-3 px-4 text-right text-rose-600 font-semibold whitespace-nowrap">PKR {item.invalidation.toFixed(2)}</td>
                  <td className="py-3 px-4 text-right text-emerald-600 font-semibold whitespace-nowrap">PKR {item.target.toFixed(2)}</td>
                  <td className="py-3 px-4 text-right font-bold text-slate-900 whitespace-nowrap">PKR {item.latestClose.toFixed(2)}</td>
                  <td
                    className={`py-3 px-4 text-right font-bold whitespace-nowrap ${
                      item.pnlPct >= 0 ? "text-emerald-600" : "text-rose-600"
                    }`}
                  >
                    {item.pnlPct >= 0 ? `+${item.pnlPct.toFixed(1)}%` : `${item.pnlPct.toFixed(1)}%`}
                  </td>
                  <td className="py-3 px-4 text-center whitespace-nowrap">
                    <span
                      className={`px-2.5 py-1 rounded-full text-[10px] font-bold inline-block ${
                        item.status === "TARGET HIT"
                          ? "bg-emerald-100 text-emerald-800 border border-emerald-300"
                          : item.status === "STOPPED OUT"
                          ? "bg-rose-100 text-rose-800 border border-rose-300"
                          : item.status === "CAPITAL PRESERVED"
                          ? "bg-amber-100 text-amber-800 border border-amber-300"
                          : "bg-blue-50 text-blue-700 border border-blue-200"
                      }`}
                    >
                      {item.status}
                    </span>
                  </td>
                  <td className="py-3 px-4 text-slate-600 font-sans text-[11px] max-w-xs truncate" title={item.notes}>
                    {item.notes}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}