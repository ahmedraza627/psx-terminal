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

  const buyFilings = filings.filter((f) => f.action === "BUY");
  const sellFilings = filings.filter((f) => f.action === "SELL");

  const renderTable = (rows: InsiderFiling[], emptyText: string) => (
    <div className="rounded-xl border border-slate-200 bg-white shadow-sm overflow-x-auto">
      <table className="w-full text-left border-collapse font-mono text-xs">
        <thead>
          <tr className="border-b border-slate-200 bg-slate-50/80 text-[10px] uppercase text-slate-500">
            <th className="py-3 px-4">Filing Date</th>
            <th className="py-3 px-4">Ticker</th>
            <th className="py-3 px-4">Insider / Sponsor</th>
            <th className="py-3 px-4 text-right">Volume</th>
            <th className="py-3 px-4 text-right">Filed Rate</th>
            <th className="py-3 px-4 text-right">Live Close</th>
            <th className="py-3 px-4 text-right">Market Value</th>
            <th className="py-3 px-4 text-right">Sponsor P&L</th>
            <th className="py-3 px-4">Filing Note</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.length === 0 ? (
            <tr>
              <td colSpan={9} className="py-6 px-4 text-center text-slate-400 font-sans">
                {emptyText}
              </td>
            </tr>
          ) : (
            rows.map((item, idx) => {
              const isPositive = (item.pnlPct ?? 0) >= 0;
              return (
                <tr key={`${item.ticker}-${item.filingDate}-${idx}`} className="hover:bg-slate-50/70 transition-colors">
                  <td className="py-3.5 px-4 text-slate-500 whitespace-nowrap">{item.filingDate}</td>
                  <td className="py-3.5 px-4 font-bold text-slate-900">{item.ticker}</td>
                  <td className="py-3.5 px-4 font-sans text-slate-700 font-medium">{item.sponsor}</td>
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
            })
          )}
        </tbody>
      </table>
    </div>
  );

  return (
    <div className="p-4 sm:p-6 pb-20 space-y-8 max-w-7xl mx-auto w-full">
      <div className="border-b border-slate-200 pb-4">
        <h1 className="text-lg sm:text-xl font-bold tracking-tight text-slate-900">
          Director & Sponsor Intelligence
        </h1>
        <p className="text-xs text-slate-500">
          PSX Clause 5.6.4 regulatory insider disclosures separated into Sponsor Accumulation (Buy) and Block Disposals (Sell).
        </p>
      </div>

      {/* SECTION 1: INSIDER BUYING */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-xs font-bold uppercase tracking-wider text-emerald-800 flex items-center gap-2">
            <span className="w-2.5 h-2.5 rounded-full bg-emerald-500"></span>
            Insider Buying & Sponsor Accumulation ({buyFilings.length})
          </h2>
          <span className="text-[10px] font-mono font-semibold text-emerald-700 bg-emerald-50 px-2.5 py-0.5 rounded border border-emerald-200">
            BULLISH CONVICTION
          </span>
        </div>
        {renderTable(buyFilings, "No recent director buy disclosures recorded.")}
      </div>

      {/* SECTION 2: INSIDER SELLING */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-xs font-bold uppercase tracking-wider text-rose-800 flex items-center gap-2">
            <span className="w-2.5 h-2.5 rounded-full bg-rose-500"></span>
            Insider Selling & Block Disposals ({sellFilings.length})
          </h2>
          <span className="text-[10px] font-mono font-semibold text-rose-700 bg-rose-50 px-2.5 py-0.5 rounded border border-rose-200">
            SUPPLY OVERHANG
          </span>
        </div>
        {renderTable(sellFilings, "No recent director sell disclosures recorded.")}
      </div>
    </div>
  );
}