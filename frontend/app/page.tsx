"use client";

import React, { useState, useEffect } from "react";

interface StockSetup {
  rank: number;
  ticker: string;
  entry?: string;
  stop?: string;
  target?: string;
  rr?: string;
  price?: string;
  avoidRef?: string;
  downside?: string;
  invalidation?: string;
  probability?: string;
  rvol?: string;
  tag?: string;
  notes: string;
}

interface LatestData {
  sessionDate: string;
  sessionTime: string;
  buys: StockSetup[];
  avoids: StockSetup[];
}

export default function DashboardPage() {
  const [data, setData] = useState<LatestData | null>(null);

  useEffect(() => {
    fetch("/data/latest.json")
      .then((res) => res.json())
      .then((d) => setData(d))
      .catch((err) => console.error("Error loading tape:", err));
  }, []);

  if (!data) {
    return (
      <div className="p-8 text-center text-xs text-slate-500 font-mono">
        Loading live institutional tape...
      </div>
    );
  }

  return (
    <div className="p-4 sm:p-6 pb-20 space-y-6 max-w-7xl mx-auto w-full">
      <div className="border-b border-slate-200 pb-4 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
        <div>
          <h1 className="text-lg sm:text-xl font-bold tracking-tight text-slate-900">
            Quant Market Tape & Institutional Setups
          </h1>
          <p className="text-xs text-slate-500">
            Volatility-adjusted momentum & high-turnover accumulation matrix.
          </p>
        </div>
        <div className="text-right">
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-mono font-medium bg-emerald-50 text-emerald-700 border border-emerald-200">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></span>
            Official Close Tape: {data.sessionDate} ({data.sessionTime})
          </span>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* BUY COLUMN */}
        <div className="space-y-4">
          <div className="flex items-center justify-between pb-2 border-b border-slate-200">
            <h2 className="text-xs font-bold text-slate-700 uppercase tracking-wider flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-emerald-500"></span>
              Top 5 High-Probability Buys
            </h2>
            <span className="text-[10px] font-mono text-emerald-600 bg-emerald-50 px-2 py-0.5 rounded border border-emerald-200">
              SMART MONEY CONFLUENCE
            </span>
          </div>

          <div className="space-y-3">
            {data.buys.map((stock) => (
              <div
                key={stock.ticker}
                className="p-4 rounded-xl border border-slate-200 bg-white shadow-sm hover:border-slate-300 transition-all space-y-3"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-mono font-bold text-slate-400">#{stock.rank}</span>
                    <span className="text-base font-black text-slate-900 font-mono tracking-tight">{stock.ticker}</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    {stock.probability && (
                      <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-emerald-100 text-emerald-800 border border-emerald-200">
                        {stock.probability} Edge
                      </span>
                    )}
                    {stock.rvol && (
                      <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-blue-50 text-blue-700 border border-blue-200">
                        RVOL {stock.rvol}
                      </span>
                    )}
                  </div>
                </div>

                <div className="grid grid-cols-4 gap-2 pt-1 border-t border-slate-100 font-mono text-center">
                  <div>
                    <span className="text-[9px] uppercase text-slate-400 block">Entry Ref</span>
                    <span className="text-xs font-bold text-slate-800">{stock.entry}</span>
                  </div>
                  <div>
                    <span className="text-[9px] uppercase text-rose-500 block">Stop (ATR)</span>
                    <span className="text-xs font-bold text-rose-600">{stock.stop}</span>
                  </div>
                  <div>
                    <span className="text-[9px] uppercase text-emerald-600 block">Target (ATR)</span>
                    <span className="text-xs font-bold text-emerald-600">{stock.target}</span>
                  </div>
                  <div>
                    <span className="text-[9px] uppercase text-slate-400 block">Risk:Reward</span>
                    <span className="text-xs font-bold text-slate-700">{stock.rr}</span>
                  </div>
                </div>

                <p className="text-[11px] text-slate-600 font-sans pt-1 leading-relaxed border-t border-slate-50">
                  {stock.notes}
                </p>
              </div>
            ))}
          </div>
        </div>

        {/* AVOID COLUMN */}
        <div className="space-y-4">
          <div className="flex items-center justify-between pb-2 border-b border-slate-200">
            <h2 className="text-xs font-bold text-slate-700 uppercase tracking-wider flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-rose-500"></span>
              Top 5 Capital Risk Warnings (Avoid)
            </h2>
            <span className="text-[10px] font-mono text-rose-600 bg-rose-50 px-2 py-0.5 rounded border border-rose-200">
              SUPPLY OVERHANG
            </span>
          </div>

          <div className="space-y-3">
            {data.avoids.map((stock) => (
              <div
                key={stock.ticker}
                className="p-4 rounded-xl border border-rose-100 bg-rose-50/20 shadow-sm hover:border-rose-200 transition-all space-y-3"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-mono font-bold text-slate-400">#{stock.rank}</span>
                    <span className="text-base font-black text-slate-900 font-mono tracking-tight">{stock.ticker}</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    {stock.probability && (
                      <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-rose-100 text-rose-800 border border-rose-200">
                        {stock.probability} Downside Risk
                      </span>
                    )}
                    {stock.rvol && (
                      <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-slate-100 text-slate-700 border border-slate-200">
                        RVOL {stock.rvol}
                      </span>
                    )}
                  </div>
                </div>

                <div className="grid grid-cols-4 gap-2 pt-1 border-t border-rose-100 font-mono text-center">
                  <div>
                    <span className="text-[9px] uppercase text-slate-400 block">Close</span>
                    <span className="text-xs font-bold text-slate-800">{stock.price}</span>
                  </div>
                  <div>
                    <span className="text-[9px] uppercase text-rose-500 block">Avoid Ref</span>
                    <span className="text-xs font-bold text-rose-600">{stock.avoidRef}</span>
                  </div>
                  <div>
                    <span className="text-[9px] uppercase text-rose-600 block">Downside (ATR)</span>
                    <span className="text-xs font-bold text-rose-600">{stock.downside}</span>
                  </div>
                  <div>
                    <span className="text-[9px] uppercase text-slate-400 block">Invalidation</span>
                    <span className="text-xs font-bold text-slate-700">{stock.invalidation}</span>
                  </div>
                </div>

                <p className="text-[11px] text-slate-600 font-sans pt-1 leading-relaxed border-t border-rose-100">
                  {stock.notes}
                </p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}