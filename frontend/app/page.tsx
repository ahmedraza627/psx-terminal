import React from "react";
import { BuyCard, AvoidCard } from "@/components/action-desk-cards";

export const dynamic = "force-dynamic";

export default function ActionDeskPage() {
  const topBuys = [
    { rank: 1, ticker: "MLCF", entry: "PKR 100.04", stop: "PKR 95.80", target: "PKR 108.50", rr: "1:2.0", notes: "84% historical swing probability defending 96 support into sector demand." },
    { rank: 2, ticker: "SYS", entry: "PKR 114.60", stop: "PKR 108.20", target: "PKR 124.00", rr: "1:1.5", notes: "82% rebound probability on institutional IT sector foreign absorption." },
    { rank: 3, ticker: "MEBL", entry: "PKR 550.25", stop: "PKR 532.00", target: "PKR 588.00", rr: "1:2.1", notes: "88% quarterly run-up probability backed by high-yield Islamic asset growth." },
    { rank: 4, ticker: "UBL", entry: "PKR 425.34", stop: "PKR 411.00", target: "PKR 455.00", rr: "1:2.1", notes: "86% dividend yield run-up consistency defending post-result book value." },
    { rank: 5, ticker: "PPL", entry: "PKR 217.00", stop: "PKR 208.50", target: "PKR 232.00", rr: "1:1.8", notes: "83% mean-reversion probability on institutional oil dividend capture." }
  ];

  const topAvoids = [
    { rank: 1, ticker: "PSO", avoidRef: "PKR 370.00", downside: "PKR 328.00", price: "PKR 360.50", invalidation: "PKR 382.00", tag: "RETAIL TRAP", notes: "Distributing into retail buyers at 52-week supply resistance." },
    { rank: 2, ticker: "HUBC", avoidRef: "PKR 208.00", downside: "PKR 184.00", price: "PKR 201.60", invalidation: "PKR 214.00", tag: "DISTRIBUTION", notes: "Institutional unwind near 205-210 resistance band post-runup." },
    { rank: 3, ticker: "HASCOL", avoidRef: "PKR 18.20", downside: "PKR 14.50", price: "PKR 17.10", invalidation: "PKR 19.40", tag: "SPECULATIVE TRAP", notes: "Negative equity overhang; speculative momentum fading at 18 resistance." },
    { rank: 4, ticker: "KEL", avoidRef: "PKR 6.60", downside: "PKR 5.20", price: "PKR 6.11", invalidation: "PKR 7.00", tag: "HEAVY SUPPLY", notes: "Retail floating supply dilution capping upside breakout above 6.50." },
    { rank: 5, ticker: "TELE", avoidRef: "PKR 8.40", downside: "PKR 6.20", price: "PKR 7.80", invalidation: "PKR 8.90", tag: "RETAIL TRAP", notes: "Retail pump-and-dump cycle without mutual fund sponsorship." }
  ];

  return (
    <div className="p-4 sm:p-6 pb-20 space-y-6 max-w-7xl mx-auto w-full">
      {/* Header - Fully Mobile Responsive */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-slate-200 pb-4">
        <div>
          <h1 className="text-lg sm:text-xl font-bold tracking-tight text-slate-900">Daily Stock Recommendations</h1>
          <p className="text-xs text-slate-500">Data-backed institutional setups with 80%+ historical resolution probability.</p>
        </div>
        <div className="flex items-center gap-2 self-start sm:self-auto">
          <span className="flex h-2 w-2 rounded-full bg-emerald-500 animate-pulse"></span>
          <span className="text-[11px] font-mono font-semibold text-slate-600">Active Market Tape</span>
        </div>
      </div>

      {/* Grid: 1 col on mobile, 2 col on large screens */}
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
            {topBuys.map((item) => (
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
            {topAvoids.map((item) => (
              <AvoidCard key={item.ticker} {...item} />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}