"use client";

import { useState } from "react";
import { DeskFrame } from "@/components/ui/primitives";

export default function RiskDesk() {
  const [portfolioSize, setPortfolioSize] = useState<number>(5000000); // 5M PKR default
  const [riskPct, setRiskPct] = useState<number>(1.5); // 1.5% max risk per trade
  const [entryPrice, setEntryPrice] = useState<number>(100);
  const [stopLoss, setStopLoss] = useState<number>(94);

  // Calculations
  const maxRiskAmount = (portfolioSize * riskPct) / 100;
  const riskPerShare = Math.max(0.01, entryPrice - stopLoss);
  const recommendedShares = Math.floor(maxRiskAmount / riskPerShare);
  const totalAllocation = recommendedShares * entryPrice;
  const allocationPct = (totalAllocation / portfolioSize) * 100;

  return (
    <DeskFrame title="Position Sizing & Portfolio Risk Engine — Fixed Fractional Model">
      <div className="grid gap-6 lg:grid-cols-2 font-mono p-4">
        {/* Left: Input Controls */}
        <div className="space-y-4 rounded border border-hairline bg-panel/40 p-4">
          <h3 className="text-[11px] font-bold uppercase tracking-widest text-info">Trade & Account Parameters</h3>
          
          <div>
            <label className="block text-[10px] text-muted uppercase">Total Portfolio Capital (PKR)</label>
            <input
              type="number"
              value={portfolioSize}
              onChange={(e) => setPortfolioSize(Number(e.target.value))}
              className="mt-1 w-full rounded border border-hairline bg-obsidian px-3 py-1.5 text-sm text-ink focus:border-info focus:outline-none"
            />
          </div>

          <div>
            <label className="block text-[10px] text-muted uppercase">Max Risk Per Trade (%)</label>
            <input
              type="number"
              step="0.1"
              value={riskPct}
              onChange={(e) => setRiskPct(Number(e.target.value))}
              className="mt-1 w-full rounded border border-hairline bg-obsidian px-3 py-1.5 text-sm text-ink focus:border-info focus:outline-none"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-[10px] text-muted uppercase">Entry Price (PKR)</label>
              <input
                type="number"
                step="0.1"
                value={entryPrice}
                onChange={(e) => setEntryPrice(Number(e.target.value))}
                className="mt-1 w-full rounded border border-hairline bg-obsidian px-3 py-1.5 text-sm text-ink focus:border-info focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-[10px] text-muted uppercase">Stop-Loss (PKR)</label>
              <input
                type="number"
                step="0.1"
                value={stopLoss}
                onChange={(e) => setStopLoss(Number(e.target.value))}
                className="mt-1 w-full rounded border border-hairline bg-obsidian px-3 py-1.5 text-sm text-ink focus:border-info focus:outline-none"
              />
            </div>
          </div>
        </div>

        {/* Right: Output Recommendations */}
        <div className="flex flex-col justify-between rounded border border-hairline bg-obsidian p-5">
          <h3 className="text-[11px] font-bold uppercase tracking-widest text-ghost">Execution Directive</h3>
          
          <div className="space-y-3 my-auto">
            <div className="flex items-center justify-between border-b border-hairline pb-2">
              <span className="text-xs text-muted uppercase">Maximum Capital Risk:</span>
              <span className="text-sm font-bold text-bear">Rs. {maxRiskAmount.toLocaleString(undefined, { maximumFractionDigits: 0 })}</span>
            </div>

            <div className="flex items-center justify-between border-b border-hairline pb-2">
              <span className="text-xs text-muted uppercase">Risk Per Share:</span>
              <span className="text-sm font-semibold text-ink">Rs. {riskPerShare.toFixed(2)}</span>
            </div>

            <div className="flex items-center justify-between border-b border-hairline pb-2">
              <span className="text-xs text-muted uppercase">Recommended Shares:</span>
              <span className="text-base font-bold text-bull">{recommendedShares.toLocaleString()} Units</span>
            </div>

            <div className="flex items-center justify-between border-b border-hairline pb-2">
              <span className="text-xs text-muted uppercase">Total Capital Allocation:</span>
              <span className="text-sm font-bold text-info">Rs. {totalAllocation.toLocaleString(undefined, { maximumFractionDigits: 0 })} ({allocationPct.toFixed(1)}% of Portfolio)</span>
            </div>
          </div>

          <p className="text-[10px] text-ghost leading-relaxed border-t border-hairline pt-3">
            RULE: Position size is strictly sized so that a stop-loss hit results in exactly {riskPct}% drawdown of total portfolio equity. Zero emotional over-leveraging.
          </p>
        </div>
      </div>
    </DeskFrame>
  );
}