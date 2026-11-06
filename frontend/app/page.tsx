import Link from "next/link";
import fs from "fs";
import path from "path";

export const dynamic = "force-dynamic";

export default function ActionDeskPage() {
  const buys = [
    { ticker: "MLCF", entry_price: 102.09, stop_price: 90.51, target_price: 119.46, rr_ratio: "1:1.5", tape_tag: "ACCUMULATION", rationale: "Sustained institutional net absorption across 5 sessions." },
    { ticker: "SYS", entry_price: 114.60, stop_price: 106.50, target_price: 130.00, rr_ratio: "1:1.8", tape_tag: "ACCUMULATION", rationale: "Foreign fund continuous buying at support." },
    { ticker: "MEBL", entry_price: 550.25, stop_price: 525.00, target_price: 600.00, rr_ratio: "1:2.0", tape_tag: "ACCUMULATION", rationale: "Tier-1 banking flow absorbing local retail supply." },
    { ticker: "UBL", entry_price: 425.34, stop_price: 405.00, target_price: 465.00, rr_ratio: "1:1.9", tape_tag: "ACCUMULATION", rationale: "High-dividend yield floor defended by mutual funds." },
    { ticker: "PPL", entry_price: 217.00, stop_price: 204.00, target_price: 242.00, rr_ratio: "1:1.9", tape_tag: "ACCUMULATION", rationale: "Energy sector institutional accumulation on oil price rebound." }
  ];

  const avoids = [
    { ticker: "PSO", price: 208.05, risk_tag: "RETAIL TRAP", reason: "Institutions net distributing into retail liquidity at resistance." },
    { ticker: "HUBC", price: 163.01, risk_tag: "DISTRIBUTION", reason: "Smart money exiting amidst corporate settlement overhang." },
    { ticker: "HASCOL", price: 8.45, risk_tag: "NEGATIVE EPS", reason: "Speculative retail penny trap with severe capital erosion risk." },
    { ticker: "KEL", price: 5.12, risk_tag: "HEAVY SUPPLY", reason: "Massive retail overhead resistance preventing upward breakout." },
    { ticker: "FFBL", price: 42.10, risk_tag: "MOMENTUM EXHAUST", reason: "Climax run completing, institutional sellers stepping in." }
  ];

  return (
    <div className="space-y-6">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-slate-900">Good evening - here is your desk</h1>
          <p className="text-xs text-slate-500">Daily institutional execution desk and certified market tape.</p>
        </div>
        <div className="flex items-center gap-3">
          <span className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-600 border border-slate-200">
            <span className="h-1.5 w-1.5 rounded-full bg-blue-600"></span>
            Session 2026-11-06
          </span>
          <input
            type="text"
            placeholder="Search ticker..."
            className="rounded-md border border-slate-200 bg-white px-3 py-1 text-xs text-slate-700 placeholder-slate-400 focus:outline-none focus:ring-1 focus:ring-blue-500 w-44"
          />
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="rounded-xl border border-blue-200 bg-white p-5 shadow-sm space-y-4">
          <div className="flex items-center justify-between pb-2 border-b border-blue-100">
            <div>
              <span className="text-xs font-semibold tracking-wider text-slate-500 uppercase">Mid-Term (2-8 Weeks)</span>
              <h2 className="text-base font-bold text-blue-900">Top 5 High-Conviction Buys</h2>
            </div>
            <span className="rounded bg-blue-50 px-2 py-0.5 text-xs font-bold text-blue-700 border border-blue-200">
              BUY TAPE
            </span>
          </div>

          <div className="space-y-3">
            {buys.map((item, idx) => (
              <div key={idx} className="rounded-lg border border-slate-100 bg-slate-50/70 p-3.5 space-y-2 hover:border-blue-300 transition-all">
                <div className="flex justify-between items-center">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-bold text-blue-600 font-mono">#{idx + 1}</span>
                    <span className="text-base font-extrabold text-slate-900">{item.ticker}</span>
                  </div>
                  <span className="text-[11px] font-semibold text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded border border-emerald-200">
                    {item.tape_tag}
                  </span>
                </div>
                <p className="text-xs text-slate-600 leading-snug">{item.rationale}</p>
                <div className="grid grid-cols-4 gap-2 pt-2 border-t border-slate-200/60 text-xs font-mono">
                  <div>
                    <span className="block text-[10px] text-slate-400 uppercase">ENTRY REF</span>
                    <span className="font-bold text-slate-900">PKR {item.entry_price}</span>
                  </div>
                  <div>
                    <span className="block text-[10px] text-slate-400 uppercase">INVALIDATION</span>
                    <span className="font-bold text-rose-600">PKR {item.stop_price}</span>
                  </div>
                  <div>
                    <span className="block text-[10px] text-slate-400 uppercase">TARGET</span>
                    <span className="font-bold text-emerald-600">PKR {item.target_price}</span>
                  </div>
                  <div>
                    <span className="block text-[10px] text-slate-400 uppercase">REWARD:RISK</span>
                    <span className="font-bold text-blue-700">{item.rr_ratio}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="rounded-xl border border-rose-200 bg-white p-5 shadow-sm space-y-4">
          <div className="flex items-center justify-between pb-2 border-b border-rose-100">
            <div>
              <span className="text-xs font-semibold tracking-wider text-slate-500 uppercase">Long-Term (Avoid / Risk)</span>
              <h2 className="text-base font-bold text-rose-900">Top 5 High-Risk / Avoid List</h2>
            </div>
            <span className="rounded bg-rose-50 px-2 py-0.5 text-xs font-bold text-rose-700 border border-rose-200">
              AVOID TAPE
            </span>
          </div>

          <div className="space-y-3">
            {avoids.map((item, idx) => (
              <div key={idx} className="rounded-lg border border-rose-100 bg-rose-50/40 p-3.5 space-y-2 hover:border-rose-300 transition-all">
                <div className="flex justify-between items-center">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-bold text-rose-600 font-mono">#{idx + 1}</span>
                    <span className="text-base font-extrabold text-slate-900">{item.ticker}</span>
                  </div>
                  <span className="text-[11px] font-bold text-rose-700 bg-rose-100 px-2 py-0.5 rounded border border-rose-200">
                    {item.risk_tag}
                  </span>
                </div>
                <p className="text-xs text-slate-600 leading-snug">{item.reason}</p>
                <div className="pt-2 border-t border-rose-100 text-xs font-mono flex justify-between">
                  <span className="text-slate-500">Latest Reference Price:</span>
                  <span className="font-bold text-slate-800">PKR {item.price}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}