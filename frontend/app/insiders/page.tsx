"use client";

import React, { useState, useEffect } from "react";

interface InsiderEntry {
  filingDate: string;
  ticker: string;
  sponsor: string;
  action: "BUY" | "SELL";
  shares: number;
  filedRate: number;
  currentRate: number;
  marketValueM: number;
  pnlPct: number;
  status: "ACCUMULATING" | "UNDERWATER";
  notes: string;
}

export default function InsidersPage() {
  const [data, setData] = useState<InsiderEntry[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch("/data/insiders.json")
      .then((res) => res.json())
      .then((d) => {
        setData(d);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  return (
    <div className="p-4 sm:p-6 pb-20 space-y-6 max-w-7xl mx-auto w-full">
      <div className="border-b border-slate-200 pb-4">
        <h1 className="text-lg sm:text-xl font-bold tracking-tight text-slate-900">Director & Sponsor Intelligence</h1>
        <p className="text-xs text-slate-500">Live re-valuation of regulatory insider filings tracked against active PSX closing tape.</p>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden">
        <div className="overflow-x-auto max-h-[600px] overflow-y-auto">
          <table className="w-full text-left border-collapse text-xs whitespace-nowrap sm:whitespace-normal">
            <thead className="sticky top-0 bg-slate-50 z-10 border-b border-slate-200 font-mono text-[10px] uppercase text-slate-500">
              <tr>
                <th className="py-3 px-3 sm:px-4">Filing Date</th>
                <th className="py-3 px-3 sm:px-4">Ticker</th>
                <th className="py-3 px-3 sm:px-4">Insider / Sponsor</th>
                <th className="py-3 px-3 sm:px-4">Action</th>
                <th className="py-3 px-3 sm:px-4">Volume</th>
                <th className="py-3 px-3 sm:px-4">Filed Rate</th>
                <th className="py-3 px-3 sm:px-4">Live Close</th>
                <th className="py-3 px-3 sm:px-4">Market Value</th>
                <th className="py-3 px-3 sm:px-4">Sponsor P&L</th>
                <th className="py-3 px-3 sm:px-4">Filing Note</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 font-mono text-[11px]">
              {data.map((row, idx) => (
                <tr key={idx} className="hover:bg-slate-50/80 transition-colors">
                  <td className="py-3 px-3 sm:px-4 text-slate-500">{row.filingDate}</td>
                  <td className="py-3 px-3 sm:px-4 font-bold text-slate-900">{row.ticker}</td>
                  <td className="py-3 px-3 sm:px-4 font-sans font-medium text-slate-800">{row.sponsor}</td>
                  <td className="py-3 px-3 sm:px-4">
                    <span className={`px-2 py-0.5 rounded text-[9px] font-bold ${row.action === "BUY" ? "bg-emerald-50 text-emerald-700 border border-emerald-200" : "bg-rose-50 text-rose-700 border border-rose-200"}`}>
                      {row.action}
                    </span>
                  </td>
                  <td className="py-3 px-3 sm:px-4 font-bold text-slate-700">{row.shares.toLocaleString()}</td>
                  <td className="py-3 px-3 sm:px-4 text-slate-600">PKR {row.filedRate.toFixed(2)}</td>
                  <td className="py-3 px-3 sm:px-4 font-bold text-slate-900">PKR {row.currentRate.toFixed(2)}</td>
                  <td className="py-3 px-3 sm:px-4 font-bold text-blue-700">PKR {row.marketValueM.toFixed(1)}M</td>
                  <td className={`py-3 px-3 sm:px-4 font-bold ${row.pnlPct >= 0 ? "text-emerald-600" : "text-rose-600"}`}>
                    {row.pnlPct >= 0 ? `+${row.pnlPct.toFixed(1)}%` : `${row.pnlPct.toFixed(1)}%`}
                  </td>
                  <td className="py-3 px-3 sm:px-4 font-sans text-slate-600 text-[11px] max-w-xs">{row.notes}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}