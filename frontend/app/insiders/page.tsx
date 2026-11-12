"use client";

import React, { useState, useEffect } from "react";

interface InsiderFiling {
  filingDate: string;
  ticker: string;
  sponsor: string;
  action: "BUY" | "SELL";
  shares: number;
  filedRate: number;
  liveClose: number;
  marketValueM: number;
  pnlPct: number;
  rationale: string;
}

export default function InsidersPage() {
  const [filings, setFilings] = useState<InsiderFiling[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch("/data/insiders.json")
      .then((res) => res.json())
      .then((d) => {
        setFilings(Array.isArray(d) ? d : []);
        setLoading(false);
      })
      .catch((err) => {
        console.error("Error loading insiders data:", err);
        setLoading(false);
      });
  }, []);

  if (loading) {
    return (
      <div className="p-8 text-center text-xs text-slate-500 font-mono">
        Loading regulatory insider filings...
      </div>
    );
  }

  return (
    <div className="p-4 sm:p-6 pb-20 space-y-6 max-w-7xl mx-auto w-full">
      <div className="border-b border-slate-200 pb-4">
        <h1 className="text-lg sm:text-xl font-bold tracking-tight text-slate-900">
          Director & Sponsor Intelligence
        </h1>
        <p className="text-xs text-slate-500">
          Live re-valuation of regulatory insider filings tracked against active PSX closing tape.
        </p>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white shadow-sm overflow-x-auto">
        <table className="w-full text-left border-collapse font-mono text-xs">
          <thead>
            <tr className="border-b border-slate-200 bg-slate-50/80 text-[10px] uppercase text-slate-500">
              <th className="py-3 px-4">Filing Date</th>
              <th className="py-3 px-4">Ticker</th>
              <th className="py-3 px-4">Insider / Sponsor</th>
              <th className="py-3 px-4">Action</th>
              <th className="py-3 px-4 text-right">Volume</th>
              <th className="py-3 px-4 text-right">Filed Rate</th>
              <th className="py-3 px-4 text-right">Live Close</th>
              <th className="py-3 px-4 text-right">Market Value</th>
              <th className="py-3 px-4 text-right">Sponsor P&L</th>
              <th className="py-3 px-4">Filing Note</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {filings.map((item, idx) => {
              const isPositive = (item.pnlPct ?? 0) >= 0;
              return (
                <tr key={`${item.ticker}-${idx}`} className="hover:bg-slate-50/70 transition-colors">
                  <td className="py-3.5 px-4 text-slate-500 whitespace-nowrap">{item.filingDate}</td>
                  <td className="py-3.5 px-4 font-bold text-slate-900">{item.ticker}</td>
                  <td className="py-3.5 px-4 font-sans text-slate-700 font-medium">{item.sponsor}</td>
                  <td className="py-3.5 px-4">
                    <span
                      className={`px-2 py-0.5 rounded text-[10px] font-bold border ${
                        item.action === "BUY"
                          ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                          : "bg-rose-50 text-rose-700 border-rose-200"
                      }`}
                    >
                      {item.action}
                    </span>
                  </td>
                  <td className="py-3.5 px-4 text-right text-slate-700">
                    {(item.shares ?? 0).toLocaleString()}
                  </td>
                  <td className="py-3.5 px-4 text-right text-slate-600">
                    PKR {(item.filedRate ?? 0).toFixed(2)}
                  </td>
                  <td className="py-3.5 px-4 text-right font-bold text-slate-900">
                    PKR {(item.liveClose ?? 0).toFixed(2)}
                  </td>
                  <td className="py-3.5 px-4 text-right font-bold text-blue-700">
                    PKR {(item.marketValueM ?? 0).toFixed(1)}M
                  </td>
                  <td
                    className={`py-3.5 px-4 text-right font-bold ${
                      isPositive ? "text-emerald-600" : "text-rose-600"
                    }`}
                  >
                    {isPositive ? `+${item.pnlPct}%` : `${item.pnlPct}%`}
                  </td>
                  <td className="py-3.5 px-4 font-sans text-[11px] text-slate-600">
                    {item.rationale}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}