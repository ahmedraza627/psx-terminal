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
  downside?: string;
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
      .catch((err) => console.error("Error loading data:", err));
  }, []);

  if (!data) {
    return (
      <div className="p-8 text-center text-xs text-slate-500 font-mono">
        Loading PSX daily session data...
      </div>
    );
  }

  return (
    <div className="p-4 sm:p-6 pb-20 space-y-6 max-w-7xl mx-auto w-full">
      {/* HEADER */}
      <div className="border-b border-slate-200 pb-4 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
        <div>
          <h1 className="text-lg sm:text-xl font-bold tracking-tight text-slate-900">
            PSX Daily Trade Desk
          </h1>
          <p className="text-xs text-slate-500">
            Daily high-volume swing setups with realistic targets and clear risk limits.
          </p>
        </div>
        <div className="text-right">
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] font-mono font-medium bg-slate-100 text-slate-700 border border-slate-200">
            Session: {data.sessionDate} ({data.sessionTime})
          </span>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* BUY COLUMN */}
        <div className="space-y-4">
          <div className="flex items-center justify-between pb-2 border-b border-slate-200">
            <h2 className="text-xs font-bold text-slate-800 uppercase tracking-wider flex items-center gap-2">
              <span className="w-2.5 h-2.5 rounded-full bg-emerald-500"></span>
              Top 5 Buy Opportunities (Swing)
            </h2>
            <span className="text-[10px] font-mono font-semibold text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded border border-emerald-200">
              HIGH VOLUME BUYS
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
                    <span className="text-base font-black text-slate-900 font-mono">{stock.ticker}</span>
                  </div>
                  <div className="flex items-center gap-1.5 font-mono text-[11px]">
                    <span className="px-2 py-0.5 rounded bg-emerald-50 text-emerald-700 border border-emerald-200 font-semibold">
                      Prob: {stock.probability}
                    </span>
                    <span className="px-2 py-0.5 rounded bg-slate-100 text-slate-700 border border-slate-200 font-medium">
                      Vol: {stock.rvol}
                    </span>
                  </div>
                </div>

                <div className="grid grid-cols-3 gap-2 pt-2 border-t border-slate-100 font-mono text-center">
                  <div className="bg-slate-50 p-2 rounded">
                    <span className="text-[10px] uppercase text-slate-500 block font-medium">Entry Rate</span>
                    <span className="text-xs font-bold text-slate-900">{stock.entry}</span>
                  </div>
                  <div className="bg-rose-50/60 p-2 rounded border border-rose-100">
                    <span className="text-[10px] uppercase text-rose-600 block font-medium">Stop Loss</span>
                    <span className="text-xs font-bold text-rose-700">{stock.stop}</span>
                  </div>
                  <div className="bg-emerald-50/60 p-2 rounded border border-emerald-100">
                    <span className="text-[10px] uppercase text-emerald-700 block font-medium">Take Profit</span>
                    <span className="text-xs font-bold text-emerald-700">{stock.target}</span>
                  </div>
                </div>

                <p className="text-[11px] text-slate-600 pt-1 leading-relaxed">
                  {stock.notes}
                </p>
              </div>
            ))}
          </div>
        </div>

        {/* AVOID COLUMN */}
        <div className="space-y-4">
          <div className="flex items-center justify-between pb-2 border-b border-slate-200">
            <h2 className="text-xs font-bold text-slate-800 uppercase tracking-wider flex items-center gap-2">
              <span className="w-2.5 h-2.5 rounded-full bg-rose-500"></span>
              Top 5 Stocks To Avoid (Selling Pressure)
            </h2>
            <span className="text-[10px] font-mono font-semibold text-rose-700 bg-rose-50 px-2 py-0.5 rounded border border-rose-200">
              CAPITAL PROTECTION
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
                    <span className="text-base font-black text-slate-900 font-mono">{stock.ticker}</span>
                  </div>
                  <div className="flex items-center gap-1.5 font-mono text-[11px]">
                    <span className="px-2 py-0.5 rounded bg-rose-100 text-rose-800 border border-rose-200 font-semibold">
                      Risk: {stock.probability}
                    </span>
                    <span className="px-2 py-0.5 rounded bg-slate-100 text-slate-700 border border-slate-200 font-medium">
                      Vol: {stock.rvol}
                    </span>
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-2 pt-2 border-t border-rose-100 font-mono text-center">
                  <div className="bg-white p-2 rounded border border-rose-100">
                    <span className="text-[10px] uppercase text-slate-500 block font-medium">Last Close</span>
                    <span className="text-xs font-bold text-slate-900">{stock.price}</span>
                  </div>
                  <div className="bg-rose-100/50 p-2 rounded border border-rose-200">
                    <span className="text-[10px] uppercase text-rose-700 block font-medium">Potential Drop</span>
                    <span className="text-xs font-bold text-rose-700">{stock.downside}</span>
                  </div>
                </div>

                <p className="text-[11px] text-slate-600 pt-1 leading-relaxed">
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