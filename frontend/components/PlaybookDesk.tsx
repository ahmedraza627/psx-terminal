"use client";

import React, { useState, useMemo } from "react";
import type { PlaybookDirective, TacticalAlphaPick } from "@/lib/playbookEngine";

interface Props {
  data: PlaybookDirective;
}

export default function PlaybookDesk({ data }: Props) {
  // Interactive Capital Desk (Default: 10 Million PKR)
  const [portfolioCapital, setPortfolioCapital] = useState<number>(10000000);
  const [selectedPick, setSelectedPick] = useState<TacticalAlphaPick | null>(
    data.topPicks[0] ?? null
  );

  const cashPct = data.recommendedCashPct;
  const activeEquityPct = cashPct != null ? 100 - cashPct : null;

  // Real-time Sizing Calculator (Kelly-Risk parity)
  const calculatedPositions = useMemo(() => {
    return data.topPicks.map((pick) => {
      const riskAmountPkr = portfolioCapital * (pick.riskAllocationPct / 100);
      const riskPerShare = Math.max(0.1, pick.entryHigh - pick.stopLoss);
      const sharesToBuy = Math.floor(riskAmountPkr / riskPerShare);
      const totalCapitalExposure = sharesToBuy * pick.entryHigh;
      const exposurePct = (totalCapitalExposure / portfolioCapital) * 100;
      const projectedGainTP1 = sharesToBuy * (pick.target1 - pick.entryHigh);

      return {
        ...pick,
        riskAmountPkr,
        sharesToBuy,
        totalCapitalExposure,
        exposurePct,
        projectedGainTP1,
      };
    });
  }, [data.topPicks, portfolioCapital]);

  return (
    <div className="mx-auto max-w-[1580px] p-3 space-y-4 font-mono text-ink">
      {/* 1. Macro Regime & Interactive Sizing Toolbar */}
      <div className="border border-neutral-800 bg-neutral-950/95 rounded p-4">
        <div className="flex flex-wrap items-center justify-between gap-4 border-b border-neutral-800 pb-3">
          <div className="flex items-center gap-3">
            <span className="h-2.5 w-2.5 rounded-full bg-info animate-pulse" />
            <span className="text-info font-bold text-xs tracking-widest uppercase">
              ALPHA PLAYBOOK DESK · HIGH EXPECTANCY EXECUTION
            </span>
            <span className="text-[10px] bg-neutral-900 px-2 py-0.5 rounded border border-neutral-800 text-neutral-400">
              SESSION: {data.sessionDate}
            </span>
          </div>

          {/* Interactive Capital Input */}
          <div className="flex items-center gap-3 bg-neutral-900/80 px-3 py-1.5 rounded border border-neutral-800">
            <label className="text-[11px] text-neutral-400 uppercase tracking-wider">
              PORTFOLIO SIZE (PKR):
            </label>
            <input
              type="number"
              step={500000}
              min={100000}
              value={portfolioCapital}
              onChange={(e) => setPortfolioCapital(Number(e.target.value) || 0)}
              className="bg-obsidian border border-neutral-700 px-2 py-0.5 text-xs text-info font-bold w-36 rounded focus:outline-none focus:border-info"
            />
          </div>
        </div>

        {/* Tactical Macro Cards */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mt-3 text-xs">
          <div className="bg-neutral-900/50 p-3 rounded border border-neutral-800/80">
            <div className="flex justify-between items-center text-neutral-500 text-[10px] uppercase">
              <span>Capital Stance</span>
              <span className="text-info">
                {activeEquityPct != null ? `${activeEquityPct}% Risk Book` : "PENDING REGIME"}
              </span>
            </div>
            <div className="mt-1 font-bold text-amber-400">
              [{data.regimeState.replace(/_/g, " ")}]
            </div>
            {data.benchmark && (
              <div className="mt-1 text-[10px] text-neutral-500">
                KSE-100 {data.benchmark.close.toFixed(0)} · SMA20 {data.benchmark.sma20.toFixed(0)}
              </div>
            )}
            <p className="mt-1 text-[11px] text-neutral-400 leading-relaxed">
              {data.macroSummary}
            </p>
            {data.dataGaps.length > 0 && (
              <p className="mt-1 text-[10px] text-warn">
                DATA GAPS: {data.dataGaps.join(" · ")}
              </p>
            )}
          </div>

          <div className="bg-neutral-900/50 p-3 rounded border border-neutral-800/80">
            <div className="text-neutral-500 text-[10px] uppercase">Index Re-Entry Trigger</div>
            <div className="mt-1 text-neutral-200 font-semibold text-[11px] leading-relaxed">
              {data.reentryTrigger}
            </div>
            <div className="mt-2 text-[10px] text-neutral-500">
              {cashPct != null
                ? `Cash Shield: ${cashPct}% capital held in risk-free reserves.`
                : "Cash Shield: pending regime verdict (no stamped pipeline signals this session)."}
            </div>
          </div>

          <div className="bg-neutral-900/50 p-3 rounded border border-neutral-800/80">
            <div className="text-neutral-500 text-[10px] uppercase">Sector Rotation Vector</div>
            <div className="mt-1 text-[11px]">
              <span className="text-bull font-bold">LONG RELATIVE STRENGTH: </span>
              <span className="text-neutral-300">{data.sectorFocus.longSectors.join(", ")}</span>
            </div>
            <div className="mt-1 text-[11px]">
              <span className="text-warn font-bold">INSTITUTIONAL FADE: </span>
              <span className="text-neutral-300">{data.sectorFocus.fadeSectors.join(", ")}</span>
            </div>
          </div>
        </div>
      </div>

      {/* 2. Tactical Execution Grid */}
      <div className="border border-neutral-800 bg-neutral-950/90 rounded p-4">
        <div className="flex items-center justify-between mb-3">
          <div className="text-xs font-bold text-neutral-200 uppercase tracking-wider flex items-center gap-2">
            <span>Tactical Setups & Sizing Blotter</span>
            <span className="text-[10px] text-neutral-500 font-normal">
              (Click any row to inspect execution card)
            </span>
          </div>
          <span className="text-[10px] text-info font-mono">
            Kelly Risk Normalized · Realtime Quant Allocation
          </span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs border-collapse">
            <thead>
              <tr className="border-b border-neutral-800 text-[10px] uppercase text-neutral-500 tracking-wider">
                <th className="py-2 px-2">Ticker</th>
                <th className="py-2 px-2">Score</th>
                <th className="py-2 px-2">Strategy Model</th>
                <th className="py-2 px-2">Accumulation Zone</th>
                <th className="py-2 px-2">Stop Loss</th>
                <th className="py-2 px-2">Target 1 (+R)</th>
                <th className="py-2 px-2">Target 2 (Runner)</th>
                <th className="py-2 px-2 text-right">Shares To Size</th>
                <th className="py-2 px-2 text-right">Capital Exposure</th>
                <th className="py-2 px-2 text-right">Max Loss</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-neutral-900 font-mono">
              {calculatedPositions.map((pos) => {
                const isSelected = selectedPick?.ticker === pos.ticker;
                return (
                  <tr
                    key={pos.ticker}
                    onClick={() => setSelectedPick(pos)}
                    className={`cursor-pointer transition-colors ${
                      isSelected ? "bg-info/10 border-l-2 border-info" : "hover:bg-neutral-900/50"
                    }`}
                  >
                    <td className="py-3 px-2 font-bold text-info text-sm flex items-center gap-2">
                      {pos.ticker}
                      <span className="text-[9px] px-1 py-0.2 rounded bg-neutral-900 text-neutral-400">
                        {pos.sector}
                      </span>
                    </td>
                    <td className="py-3 px-2">
                      <span
                        className={`px-1.5 py-0.5 rounded text-[10px] font-bold border ${
                          pos.conviction === "HIGH"
                            ? "bg-bull/15 text-bull border-bull/20"
                            : "bg-neutral-900 text-neutral-400 border-neutral-800"
                        }`}
                      >
                        {pos.conviction ?? "UNTAGGED"}
                      </span>
                    </td>
                    <td className="py-3 px-2">
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-neutral-900 border border-neutral-800 text-neutral-300">
                        {pos.strategy.replace(/_/g, " ")}
                      </span>
                    </td>
                    <td className="py-3 px-2 font-semibold text-neutral-200">
                      {pos.entryLow.toFixed(2)} – {pos.entryHigh.toFixed(2)}
                    </td>
                    <td className="py-3 px-2 font-semibold text-warn">
                      {pos.stopLoss.toFixed(2)}
                    </td>
                    <td className="py-3 px-2 font-semibold text-bull">
                      {pos.target1.toFixed(2)}
                    </td>
                    <td className="py-3 px-2 font-semibold text-emerald-400">
                      {pos.target2.toFixed(2)}
                    </td>
                    <td className="py-3 px-2 text-right font-bold text-neutral-100">
                      {pos.sharesToBuy.toLocaleString()}
                    </td>
                    <td className="py-3 px-2 text-right text-info font-semibold">
                      {(pos.totalCapitalExposure / 1000000).toFixed(2)}M ({pos.exposurePct.toFixed(1)}%)
                    </td>
                    <td className="py-3 px-2 text-right text-warn">
                      -{(pos.riskAmountPkr / 1000).toFixed(0)}k
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* 3. Detailed Execution Card for Selected Stock */}
      {selectedPick && (
        <div className="border border-neutral-800 bg-neutral-950/95 rounded p-4">
          <div className="flex items-center justify-between border-b border-neutral-800 pb-2 mb-3">
            <span className="text-xs font-bold uppercase text-neutral-200 flex items-center gap-2">
              <span className="text-info">{selectedPick.ticker}</span> EXECUTION DIRECTIVE & ROUTING PROTOCOL
            </span>
            <span className="text-[11px] text-neutral-400">
              Risk/Reward: <strong className="text-bull">{selectedPick.riskReward}</strong>
            </span>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs">
            <div className="space-y-1">
              <div className="text-neutral-500 text-[10px] uppercase">Routing Order Type</div>
              <div className="text-neutral-100 font-bold bg-neutral-900 px-2 py-1 rounded border border-neutral-800 inline-block">
                {selectedPick.executionProtocol.orderType}
              </div>
              <div className="text-[11px] text-neutral-400 pt-1">
                Preferred Window: <strong className="text-neutral-200">{selectedPick.executionProtocol.window}</strong>
              </div>
            </div>

            <div className="space-y-1">
              <div className="text-neutral-500 text-[10px] uppercase">Execution Condition</div>
              <div className="text-[11px] text-neutral-300 leading-relaxed">
                {selectedPick.executionProtocol.volumeCondition}
              </div>
            </div>

            <div className="space-y-1">
              <div className="text-neutral-500 text-[10px] uppercase">Quant Alpha Catalyst</div>
              <div className="text-[11px] text-neutral-400 leading-relaxed">
                {selectedPick.catalyst}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}