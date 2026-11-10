"use client";

import React, { useState, useEffect } from "react";
import { BuyCard, AvoidCard } from "@/components/action-desk-cards";

interface BuyItem {
  rank: number;
  ticker: string;
  entry: string;
  stop: string;
  target: string;
  rr: string;
  notes: string;
}

interface AvoidItem {
  rank: number;
  ticker: string;
  avoidRef: string;
  downside: string;
  price: string;
  invalidation: string;
  tag: string;
  notes: string;
}

interface MarketPayload {
  sessionDate: string;
  sessionTime: string;
  buys: BuyItem[];
  avoids: AvoidItem[];
}

export default function ActionDeskPage() {
  const [data, setData] = useState<MarketPayload | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch("/data/latest.json?t=" + Date.now())
      .then((res) => res.json())
      .then((json: MarketPayload) => {
        setData(json);
        setLoading(false);
      })
      .catch((err) => {
        console.error("Failed to load live payload", err);
        setLoading(false);
      });
  }, []);

  if (loading || !data) {
    return (
      <div className="p-8 text-center text-xs font-mono text-slate-500">
        Loading live institutional tape...
      </div>
    );
  }

  return (
    <div className="p-4 sm:p-6 pb-20 space-y-6 max-w-7xl mx-auto w-full">
      {/* Header With Dynamic Scraped Session Date */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-200 pb-4">
        <div>
          <h1 className="text-lg sm:text-xl font-bold tracking-tight text-slate-900">Daily Stock Recommendations</h1>
          <p className="text-xs text-slate-500">Data-backed institutional setups with 80%+ historical resolution probability.</p>
        </div>
        <div className="flex flex-col sm:items-end gap-1">
          <div className="flex items-center gap-2">
            <span className="flex h-2 w-2 rounded-full bg-slate-400"></span>
            <span className="text-[11px] font-mono font-semibold text-slate-700">Official Close Tape</span>
          </div>
          <div className="text-[11px] font-mono text-slate-500">
            Session: <span className="font-bold text-slate-800">{data.sessionDate}</span> ({data.sessionTime})
          </div>
        </div>
      </div>

      {/* Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5 sm:gap-6">
        {/* BUYS */}
        <div className="rounded-xl border border-blue-100 bg-blue-50/20 p-4 sm:p-5 space-y-4 shadow-sm">
          <div className="flex items-center justify-between">
            <div>
              <span className="text-[10px] font-bold uppercase tracking-wider text-blue-600">HIGH PROBABILITY SWINGS</span>
              <h2 className="text-sm sm:text-base font-bold text-slate-900">Top 5 Recommended Buys</h2>
            </div>
            <span className="px-2 py-0.5 text-[10px] font-mono font-bold bg-blue-100 text-blue-800 rounded">BUY LIST</span>
          </div>

          <div className="space-y-3">
            {data.buys.map((item) => (
              <BuyCard key={item.ticker} {...item} />
            ))}
          </div>
        </div>

        {/* AVOIDS */}
        <div className="rounded-xl border border-rose-100 bg-rose-50/20 p-5 space-y-4 shadow-sm">
          <div className="flex items-center justify-between">
            <div>
              <span className="text-[10px] font-bold uppercase tracking-wider text-rose-600">CAPITAL RISK WARNING</span>
              <h2 className="text-sm sm:text-base font-bold text-slate-900">Top 5 Stocks to Avoid</h2>
            </div>
            <span className="px-2 py-0.5 text-[10px] font-mono font-bold bg-rose-100 text-rose-800 rounded">AVOID LIST</span>
          </div>

          <div className="space-y-3">
            {data.avoids.map((item) => (
              <AvoidCard key={item.ticker} {...item} />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}