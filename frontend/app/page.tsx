import React from "react";

export const dynamic = "force-dynamic";

export default function ActionDeskPage() {
  const topBuys = [
    { ticker: "MLCF", entry: "PKR 102.09", stop: "PKR 98.51", target: "PKR 119.46", rr: "1:1.5", notes: "Sustained institutional net absorption across 5 sessions." },
    { ticker: "SYS", entry: "PKR 114.6", stop: "PKR 106.5", target: "PKR 130", rr: "1:1.8", notes: "Foreign fund continuous buying at support." },
    { ticker: "MEBL", entry: "PKR 550.25", stop: "PKR 525", target: "PKR 600", rr: "1:2.0", notes: "Tier 1 banking flow absorbing local retail supply." },
    { ticker: "UBL", entry: "PKR 425.34", stop: "PKR 405", target: "PKR 465", rr: "1:1.9", notes: "High dividend yield floor defended by mutual funds." },
    { ticker: "PPL", entry: "PKR 217", stop: "PKR 204", target: "PKR 242", rr: "1:1.9", notes: "Energy sector institutional accumulation on oil price rebound." }
  ];

  const topAvoids = [
    { ticker: "PSO", price: "PKR 208.05", tag: "RETAIL TRAP", notes: "Institutions net distributing into retail liquidity at resistance." },
    { ticker: "HUBC", price: "PKR 163.01", tag: "DISTRIBUTION", notes: "Smart money exiting amidst corporate settlement overhang." },
    { ticker: "HASCOL", price: "PKR 8.45", tag: "NEGATIVE EPS", notes: "Speculative retail penny trap with severe capital erosion risk." },
    { ticker: "KEL", price: "PKR 5.12", tag: "HEAVY SUPPLY", notes: "Massive retail overhead resistance preventing upward breakout." },
    { ticker: "TELE", price: "PKR 7.80", tag: "RETAIL TRAP", notes: "Retail overhead distribution; smart money absent from order book." }
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between border-b border-slate-200 pb-4">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-slate-900">Good evening - here is your desk</h1>
          <p className="text-xs text-slate-500">Daily institutional execution desk and certified market tape.</p>
        </div>
        <div className="flex items-center gap-2">
          <span className="flex h-2 w-2 rounded-full bg-emerald-500 animate-pulse"></span>
          <span className="text-[11px] font-mono font-semibold text-slate-600">Session 2026 11:06</span>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* BUYS */}
        <div className="rounded-xl border border-blue-100 bg-white p-5 space-y-4 shadow-sm">
          <div className="flex items-center justify-between">
            <div>
              <span className="text-[10px] font-bold uppercase tracking-wider text-blue-600">MID-TERM (2-8 WEEKS)</span>
              <h2 className="text-base font-bold text-slate-900">Top 5 High-Conviction Buys</h2>
            </div>
            <span className="px-2 py-0.5 text-[10px] font-mono font-bold bg-blue-100 text-blue-800 rounded">BUY TAPE</span>
          </div>

          <div className="space-y-3">
            {topBuys.map((item, idx) => (
              <div key={item.ticker} className="rounded-lg border border-slate-100 bg-slate-50/50 p-4 hover:border-blue-200 transition-all">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-bold text-slate-400">#{idx + 1}</span>
                    <span className="text-sm font-extrabold text-slate-900">{item.ticker}</span>
                  </div>
                  <span className="px-2 py-0.5 text-[10px] font-bold bg-emerald-50 text-emerald-700 border border-emerald-200 rounded">ACCUMULATION</span>
                </div>
                <p className="text-xs text-slate-600 mt-2">{item.notes}</p>
                <div className="grid grid-cols-4 gap-2 mt-3 pt-3 border-t border-slate-200/60 font-mono text-[10px]">
                  <div>
                    <span className="text-slate-400 block">ENTRY REF</span>
                    <span className="font-bold text-slate-800">{item.entry}</span>
                  </div>
                  <div>
                    <span className="text-slate-400 block">INVALIDATION</span>
                    <span className="font-bold text-rose-600">{item.stop}</span>
                  </div>
                  <div>
                    <span className="text-slate-400 block">TARGET</span>
                    <span className="font-bold text-emerald-600">{item.target}</span>
                  </div>
                  <div>
                    <span className="text-slate-400 block">REWARD:RISK</span>
                    <span className="font-bold text-slate-800">{item.rr}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* AVOIDS */}
        <div className="rounded-xl border border-rose-100 bg-white p-5 space-y-4 shadow-sm">
          <div className="flex items-center justify-between">
            <div>
              <span className="text-[10px] font-bold uppercase tracking-wider text-rose-600">LONG-TERM (AVOID / RISK)</span>
              <h2 className="text-base font-bold text-slate-900">Top 5 High-Risk / Avoid List</h2>
            </div>
            <span className="px-2 py-0.5 text-[10px] font-mono font-bold bg-rose-100 text-rose-800 rounded">AVOID TAPE</span>
          </div>

          <div className="space-y-3">
            {topAvoids.map((item, idx) => (
              <div key={item.ticker} className="rounded-lg border border-slate-100 bg-slate-50/50 p-4 hover:border-rose-200 transition-all">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-bold text-slate-400">#{idx + 1}</span>
                    <span className="text-sm font-extrabold text-slate-900">{item.ticker}</span>
                  </div>
                  <span className="px-2 py-0.5 text-[10px] font-bold bg-rose-50 text-rose-700 border border-rose-200 rounded">{item.tag}</span>
                </div>
                <p className="text-xs text-slate-600 mt-2">{item.notes}</p>
                <div className="mt-3 pt-3 border-t border-slate-200/60 font-mono text-[10px] flex items-center justify-between">
                  <span className="text-slate-400">Latest Reference Price:</span>
                  <span className="font-bold text-slate-800">{item.price}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}