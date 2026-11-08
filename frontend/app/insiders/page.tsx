"use client";

import React, { useState, useEffect } from "react";

interface InsiderRecord {
  date: string;
  ticker: string;
  insiderName: string;
  action: "BUY" | "SELL";
  shares: number;
  avgPrice: number;
  valueM: number;
  market: string;
  signal: string;
  notes: string;
}

export default function InsidersPage() {
  const [data, setData] = useState<InsiderRecord[]>([]);
  const [filter, setFilter] = useState<"ALL" | "BUY" | "SELL">("ALL");

  useEffect(() => {
    fetch("/data/insiders.json")
      .then((res) => res.json())
      .then((items) => setData(items))
      .catch((err) => console.error("Error loading insider data:", err));
  }, []);

  const filtered = data.filter((item) =>
    filter === "ALL" ? true : item.action === filter
  );

  const totalBuyVolume = data
    .filter((d) => d.action === "BUY")
    .reduce((sum, d) => sum + d.valueM, 0);

  const totalSellVolume = data
    .filter((d) => d.action === "SELL")
    .reduce((sum, d) => sum + d.valueM, 0);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold tracking-tight text-slate-900">
          Executive &amp; Sponsor Intelligence (Form 31)
        </h1>
        <p className="text-xs text-slate-500">
          Certified SECP filings of Director, CEO, and Sovereign transactions on the Pakistan Stock Exchange.
        </p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <span className="text-[11px] font-semibold text-slate-400 uppercase">Filings Logged</span>
          <div className="text-2xl font-black text-slate-900 mt-1">{data.length} Filings</div>
          <span className="text-[10px] text-slate-500">Last 10 Trading Sessions</span>
        </div>
        <div className="rounded-xl border border-emerald-200 bg-white p-4 shadow-sm">
          <span className="text-[11px] font-semibold text-emerald-600 uppercase">Sponsor Net Buying</span>
          <div className="text-2xl font-black text-emerald-600 mt-1">PKR {totalBuyVolume.toFixed(1)}M</div>
          <span className="text-[10px] text-slate-500">Open &amp; Block Market</span>
        </div>
        <div className="rounded-xl border border-rose-200 bg-white p-4 shadow-sm">
          <span className="text-[11px] font-semibold text-rose-600 uppercase">Insider Selling</span>
          <div className="text-2xl font-black text-rose-600 mt-1">PKR {totalSellVolume.toFixed(1)}M</div>
          <span className="text-[10px] text-slate-500">Retail Trap Overhead</span>
        </div>
        <div className="rounded-xl border border-blue-200 bg-white p-4 shadow-sm">
          <span className="text-[11px] font-semibold text-blue-600 uppercase">Sponsor Buy Ratio</span>
          <div className="text-2xl font-black text-blue-700 mt-1">
            {((totalBuyVolume / (totalBuyVolume + totalSellVolume || 1)) * 100).toFixed(0)}%
          </div>
          <span className="text-[10px] text-slate-500">Net Smart Accumulation</span>
        </div>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden">
        <div className="flex flex-wrap items-center justify-between p-4 border-b border-slate-100 gap-3">
          <div className="flex items-center gap-2">
            {(["ALL", "BUY", "SELL"] as const).map((m) => (
              <button
                key={m}
                onClick={() => setFilter(m)}
                className={`px-3 py-1 text-xs font-semibold rounded-md transition-all ${
                  filter === m
                    ? "bg-slate-900 text-white shadow-sm"
                    : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                }`}
              >
                {m === "ALL" ? "All Filings" : m === "BUY" ? "Insider Buys" : "Insider Sells"}
              </button>
            ))}
          </div>
          <span className="text-xs text-slate-400 font-mono">SECP 5.6.1 Certified Audit</span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs font-mono">
            <thead className="bg-slate-50 text-[10px] text-slate-500 uppercase border-b border-slate-200">
              <tr>
                <th className="p-3">Filing Date</th>
                <th className="p-3">Ticker</th>
                <th className="p-3">Executive / Entity</th>
                <th className="p-3">Action</th>
                <th className="p-3">Quantity</th>
                <th className="p-3">Avg Rate</th>
                <th className="p-3">Value</th>
                <th className="p-3">Execution Signal</th>
                <th className="p-3">Institutional Context</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {filtered.map((item, idx) => (
                <tr key={idx} className="hover:bg-slate-50/80 transition-colors">
                  <td className="p-3 text-slate-500 whitespace-nowrap">{item.date}</td>
                  <td className="p-3 font-extrabold text-slate-900">{item.ticker}</td>
                  <td className="p-3 text-slate-700 font-sans">{item.insiderName}</td>
                  <td className="p-3">
                    <span
                      className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                        item.action === "BUY"
                          ? "bg-emerald-50 text-emerald-700 border border-emerald-200"
                          : "bg-rose-50 text-rose-700 border border-rose-200"
                      }`}
                    >
                      {item.action}
                    </span>
                  </td>
                  <td className="p-3 text-slate-800">{item.shares.toLocaleString()}</td>
                  <td className="p-3 text-slate-800">PKR {item.avgPrice.toFixed(2)}</td>
                  <td className="p-3 font-black text-slate-900">PKR {item.valueM.toFixed(1)}M</td>
                  <td className="p-3 whitespace-nowrap">
                    <span
                      className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                        item.action === "BUY"
                          ? "bg-amber-100 text-amber-900 border border-amber-300"
                          : "bg-rose-100 text-rose-800 border border-rose-200"
                      }`}
                    >
                      {item.signal}
                    </span>
                  </td>
                  <td className="p-3 text-slate-600 max-w-sm font-sans text-[11px]">{item.notes}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}