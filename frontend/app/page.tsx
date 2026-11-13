"use client";

import React, { useState, useEffect } from "react";

interface StockSetup {
  rank: number;
  ticker: string;
  entry?: string;
  entryZone?: string;
  stop?: string;
  target?: string;
  rr?: string;
  price?: string;
  downside?: string;
  probability?: string;
  rvol?: string;
  dfxSignal?: string;
  catalystTag?: string | null;
  tag?: string;
  notes: string;
}

interface MarketRegime {
  status: string;
  kseChange: string;
  breadth: string;
  note: string;
  isDefensive: boolean;
}

interface InstitutionalFlow {
  sentiment: string;
  mutualFundsM: number;
  foreignUsdK: number;
  individualsM: number;
  smartMoneyDeltaM: number;
  isSmartMoneyBuying: boolean;
}

interface LatestData {
  sessionDate: string;
  sessionTime: string;
  regime?: MarketRegime;
  flow?: InstitutionalFlow;
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
        Loading PSX institutional session data...
      </div>
    );
  }

  const isDefensive = data.regime?.isDefensive ?? false;
  const flow = data.flow;

  return (
    <div className="p-4 sm:p-6 pb-20 space-y-6 max-w-7xl mx-auto w-full">
      {/* HEADER */}
      <div className="border-b border-slate-200 pb-4 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
        <div>
          <h1 className="text-lg sm:text-xl font-bold tracking-tight text-slate-900">
            PSX Daily Trade Desk
          </h1>
          <p className="text-xs text-slate-500">
            Tier-1 institutional swing setups backed by 1-year historical bars, PSX event catalysts & smart money flow.
          </p>
        </div>
        <div className="text-right">
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] font-mono font-medium bg-slate-100 text-slate-700 border border-slate-200">
            Session: {data.sessionDate} ({data.sessionTime})
          </span>
        </div>
      </div>

      {/* MACRO REGIME BANNER */}
      {data.regime && (
        <div
          className={`p-3.5 rounded-xl border flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 text-xs font-mono ${
            isDefensive
              ? "bg-rose-50 border-rose-200 text-rose-900"
              : "bg-emerald-50/70 border-emerald-200 text-emerald-950"
          }`}
        >
          <div className="flex items-center gap-2">
            <span
              className={`w-2.5 h-2.5 rounded-full ${
                isDefensive ? "bg-rose-600 animate-pulse" : "bg-emerald-600"
              }`}
            ></span>
            <span className="font-bold uppercase tracking-wide">
              Market Regime: {data.regime.status}
            </span>
            <span className="text-[11px] px-2 py-0.5 rounded bg-white/80 border border-current font-bold">
              KSE-100: {data.regime.kseChange}
            </span>
            <span className="text-[11px] px-2 py-0.5 rounded bg-white/80 border border-current">
              {data.regime.breadth}
            </span>
          </div>
          <p className="text-[11px] font-sans opacity-90 sm:text-right">
            {data.regime.note}
          </p>
        </div>
      )}

      {/* SMART MONEY FLOW STRIP */}
      {flow && (
        <div
          className={`p-3.5 rounded-xl border shadow-sm flex flex-col md:flex-row md:items-center md:justify-between gap-3 font-mono text-xs ${
            flow.isSmartMoneyBuying
              ? "border-blue-200 bg-blue-50/30"
              : "border-rose-200 bg-rose-50/30"
          }`}
        >
          <div className="flex items-center gap-2">
            <span
              className={`w-2.5 h-2.5 rounded-full animate-pulse ${
                flow.isSmartMoneyBuying ? "bg-blue-600" : "bg-rose-600"
              }`}
            ></span>
            <span className="text-[11px] font-bold text-slate-600 uppercase">
              NCCPL Smart Money:
            </span>
            <span
              className={`font-bold ${
                flow.isSmartMoneyBuying ? "text-blue-900" : "text-rose-900"
              }`}
            >
              {flow.sentiment}
            </span>
          </div>
          <div className="flex flex-wrap items-center gap-2.5 text-[11px]">
            <span className="bg-white px-2.5 py-1 rounded border border-slate-200 shadow-2xs">
              Mutual Funds:{" "}
              <strong
                className={
                  flow.mutualFundsM >= 0 ? "text-emerald-700" : "text-rose-700"
                }
              >
                {flow.mutualFundsM >= 0
                  ? `+${flow.mutualFundsM}`
                  : flow.mutualFundsM}
                M PKR
              </strong>
            </span>
            <span className="bg-white px-2.5 py-1 rounded border border-slate-200 shadow-2xs">
              Foreign:{" "}
              <strong
                className={
                  flow.foreignUsdK >= 0 ? "text-emerald-700" : "text-rose-700"
                }
              >
                {flow.foreignUsdK >= 0
                  ? `+$${flow.foreignUsdK}`
                  : `-$${Math.abs(flow.foreignUsdK)}`}
                K
              </strong>
            </span>
            <span className="bg-white px-2.5 py-1 rounded border border-slate-200 shadow-2xs">
              Retail:{" "}
              <strong
                className={
                  flow.individualsM >= 0 ? "text-emerald-700" : "text-rose-700"
                }
              >
                {flow.individualsM >= 0
                  ? `+${flow.individualsM}`
                  : flow.individualsM}
                M PKR
              </strong>
            </span>
            <span
              className={`text-white px-2.5 py-1 rounded font-bold shadow-2xs ${
                flow.smartMoneyDeltaM >= 0 ? "bg-blue-600" : "bg-rose-600"
              }`}
            >
              Net Flow:{" "}
              {flow.smartMoneyDeltaM >= 0
                ? `+${flow.smartMoneyDeltaM}`
                : flow.smartMoneyDeltaM}
              M
            </span>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* BUY COLUMN */}
        <div className="space-y-4">
          <div className="flex items-center justify-between pb-2 border-b border-slate-200">
            <h2 className="text-xs font-bold text-slate-800 uppercase tracking-wider flex items-center gap-2">
              <span className="w-2.5 h-2.5 rounded-full bg-emerald-500"></span>
              Top 5 Buy Opportunities (Swing)
            </h2>
            <span className="text-[10px] font-mono font-semibold text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded border border-emerald-200">
              TIER-1 ACCUMULATION
            </span>
          </div>

          {isDefensive && (
            <div className="p-6 rounded-xl border border-dashed border-rose-200 bg-rose-50/30 text-center space-y-1">
              <span className="text-xs font-mono font-bold text-rose-800 block">
                CASH MODE ACTIVE — NO NEW BUYS TRIGGERED
              </span>
              <p className="text-[11px] text-slate-500">
                Index distribution exceeds risk threshold. Stay in cash until macro regime normalizes.
              </p>
            </div>
          )}

          {!isDefensive && (
            <div className="space-y-3">
              {data.buys.map((stock) => (
                <div
                  key={stock.ticker}
                  className="p-4 rounded-xl border border-slate-200 bg-white shadow-sm hover:border-slate-300 transition-all space-y-3"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-mono font-bold text-slate-400">#{stock.rank}</span>
                      <span className="text-base font-black text-slate-900 font-mono">{stock.ticker}</span>
                      {stock.catalystTag && (
                        <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-amber-50 text-amber-800 border border-amber-300">
                          {stock.catalystTag}
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-1.5 font-mono text-[11px]">
                      <span className="px-2 py-0.5 rounded bg-emerald-50 text-emerald-700 border border-emerald-200 font-semibold">
                        Prob: {stock.probability}
                      </span>
                      <span className="px-2 py-0.5 rounded bg-slate-100 text-slate-700 border border-slate-200 font-medium">
                        RVOL: {stock.rvol}
                      </span>
                      {stock.dfxSignal && (
                        <span className="px-2 py-0.5 rounded bg-blue-50 text-blue-700 border border-blue-200 font-bold">
                          DFX: {stock.dfxSignal}
                        </span>
                      )}
                    </div>
                  </div>

                  <div className="grid grid-cols-3 gap-2 pt-2 border-t border-slate-100 font-mono text-center">
                    <div className="bg-slate-50 p-2 rounded flex flex-col justify-center">
                      <span className="text-[10px] uppercase text-slate-500 block font-medium">Entry Rate</span>
                      <span className="text-xs font-bold text-slate-900">{stock.entry}</span>
                      {stock.entryZone && (
                        <span className="text-[9px] text-slate-400 block font-mono mt-0.5">
                          Zone: {stock.entryZone.replace("PKR ", "")}
                        </span>
                      )}
                    </div>
                    <div className="bg-rose-50/60 p-2 rounded border border-rose-100 flex flex-col justify-center">
                      <span className="text-[10px] uppercase text-rose-600 block font-medium">Stop Loss</span>
                      <span className="text-xs font-bold text-rose-700">{stock.stop}</span>
                    </div>
                    <div className="bg-emerald-50/60 p-2 rounded border border-emerald-100 flex flex-col justify-center">
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
          )}
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
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-mono font-bold text-slate-400">#{stock.rank}</span>
                    <span className="text-base font-black text-slate-900 font-mono">{stock.ticker}</span>
                    {stock.catalystTag && (
                      <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-rose-600 text-white">
                        {stock.catalystTag}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-1.5 font-mono text-[11px]">
                    <span className="px-2 py-0.5 rounded bg-rose-100 text-rose-800 border border-rose-200 font-semibold">
                      Risk: {stock.probability}
                    </span>
                    <span className="px-2 py-0.5 rounded bg-slate-100 text-slate-700 border border-slate-200 font-medium">
                      RVOL: {stock.rvol}
                    </span>
                    {stock.dfxSignal && (
                      <span className="px-2 py-0.5 rounded bg-rose-50 text-rose-700 border border-rose-200 font-bold">
                        DFX: {stock.dfxSignal}
                      </span>
                    )}
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