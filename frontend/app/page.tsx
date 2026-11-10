import React from "react";
import { BuyCard, AvoidCard } from "@/components/action-desk-cards";

export const dynamic = "force-dynamic";

export default function ActionDeskPage() {
  const topBuys = [
    { rank: 1, ticker: "MLCF", entry: "PKR 100.04", stop: "PKR 92.50", target: "PKR 115.00", rr: "1:1.5", notes: "Sustained institutional net absorption across 5 sessions." },
    { rank: 2, ticker: "SYS", entry: "PKR 114.60", stop: "PKR 106.50", target: "PKR 130.00", rr: "1:1.8", notes: "Foreign fund continuous buying at support." },
    { rank: 3, ticker: "MEBL", entry: "PKR 550.25", stop: "PKR 525.00", target: "PKR 600.00", rr: "1:2.0", notes: "Tier 1 banking flow absorbing local retail supply." },
    { rank: 4, ticker: "UBL", entry: "PKR 425.34", stop: "PKR 405.00", target: "PKR 465.00", rr: "1:1.9", notes: "High dividend yield floor defended by mutual funds." },
    { rank: 5, ticker: "PPL", entry: "PKR 217.00", stop: "PKR 204.00", target: "PKR 242.00", rr: "1:1.9", notes: "Energy sector institutional accumulation on oil price rebound." }
  ];

  const topAvoids = [
    { rank: 1, ticker: "PSO", avoidRef: "PKR 214.50", downside: "PKR 185.00", price: "PKR 208.05", invalidation: "PKR 221.00", tag: "RETAIL TRAP", notes: "Institutions net distributing into retail liquidity at resistance." },
    { rank: 2, ticker: "HUBC", avoidRef: "PKR 172.00", downside: "PKR 145.00", price: "PKR 163.01", invalidation: "PKR 175.00", tag: "DISTRIBUTION", notes: "Smart money exiting amidst corporate settlement overhang." },
    { rank: 3, ticker: "HASCOL", avoidRef: "PKR 9.80", downside: "PKR 6.00", price: "PKR 8.45", invalidation: "PKR 10.20", tag: "NEGATIVE EPS", notes: "Speculative retail penny trap with severe capital erosion risk." },
    { rank: 4, ticker: "KEL", avoidRef: "PKR 5.60", downside: "PKR 4.20", price: "PKR 5.12", invalidation: "PKR 5.85", tag: "HEAVY SUPPLY", notes: "Massive retail overhead resistance preventing upward breakout." },
    { rank: 5, ticker: "TELE", avoidRef: "PKR 8.40", downside: "PKR 6.20", price: "PKR 7.80", invalidation: "PKR 8.70", tag: "RETAIL TRAP", notes: "Retail overhead distribution; smart money absent from order book." }
  ];

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      <div className="flex items-center justify-between border-b border-slate-200 pb-4">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-slate-900">Good evening - here is your desk</h1>
          <p className="text-xs text-slate-500">Daily institutional execution desk and certified market tape.</p>
        </div>
        <div className="flex items-center gap-2">
          <span className="flex h-2 w-2 rounded-full bg-emerald-500 animate-pulse"></span>
          <span className="text-[11px] font-mono font-semibold text-slate-600">Certified Live Tape</span>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* BUYS */}
        <div className="rounded-xl border border-blue-100 bg-blue-50/20 p-5 space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <span className="text-[10px] font-bold uppercase tracking-wider text-blue-600">MID-TERM (2-8 WEEKS)</span>
              <h2 className="text-base font-bold text-slate-900">Top 5 High-Conviction Buys</h2>
            </div>
            <span className="px-2 py-0.5 text-[10px] font-mono font-bold bg-blue-100 text-blue-800 rounded">BUY TAPE</span>
          </div>

          <div className="space-y-3">
            {topBuys.map((item) => (
              <BuyCard key={item.ticker} {...item} />
            ))}
          </div>
        </div>

        {/* AVOIDS */}
        <div className="rounded-xl border border-rose-100 bg-rose-50/20 p-5 space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <span className="text-[10px] font-bold uppercase tracking-wider text-rose-600">LONG-TERM (AVOID / RISK)</span>
              <h2 className="text-base font-bold text-slate-900">Top 5 High-Risk / Avoid List</h2>
            </div>
            <span className="px-2 py-0.5 text-[10px] font-mono font-bold bg-rose-100 text-rose-800 rounded">AVOID TAPE</span>
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