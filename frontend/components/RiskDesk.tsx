"use client";

import { useMemo, useState } from "react";
import {
  RISK_DEFAULTS,
  sizeBook,
  type SizingSignal,
} from "@/lib/risk";

function fmtPkr(value: number): string {
  if (Math.abs(value) >= 1e6) return `${(value / 1e6).toFixed(2)}M`;
  if (Math.abs(value) >= 1e3) return `${(value / 1e3).toFixed(0)}K`;
  return value.toFixed(0);
}

function fmtPct(value: number, digits = 2): string {
  return `${value >= 0 ? "" : ""}${value.toFixed(digits)}%`;
}

export default function RiskDesk({
  signals,
}: {
  signals: SizingSignal[];
}) {
  const [equityMn, setEquityMn] = useState(5);
  const [riskPct, setRiskPct] = useState(RISK_DEFAULTS.riskPerTradePct);

  const equityPkr = Math.max(0, equityMn) * 1_000_000;

  const book = useMemo(
    () =>
      sizeBook(signals, equityPkr, {
        ...RISK_DEFAULTS,
        riskPerTradePct: riskPct,
      }),
    [signals, equityPkr, riskPct]
  );

  const heat = book.totals.portfolioHeatPct;
  const heatPctOfCap = Math.min(
    100,
    (heat / RISK_DEFAULTS.maxPortfolioHeatPct) * 100
  );

  return (
    <section>
      <div className="flex items-center justify-between border-b border-hairline px-3 py-2">
        <h2 className="text-[10px] font-medium uppercase tracking-widest text-ghost">
          Risk Desk - Fixed-Fractional Position Sizing
        </h2>
        <span className="font-mono text-[11px] tabular-nums text-muted">
          {book.totals.positions} SIZED · {book.rejected.length} REJ
        </span>
      </div>

      {/* Inputs */}
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2 border-b border-hairline bg-panel px-3 py-2">
        <label className="flex items-center gap-2 font-mono text-[11px] text-muted">
          EQUITY
          <span className="font-mono text-ghost">PKR</span>
          <input
            type="number"
            min={0}
            step={0.5}
            value={equityMn}
            onChange={(e) => setEquityMn(Number(e.target.value) || 0)}
            className="w-20 rounded-[2px] border border-hairline bg-obsidian px-1.5 py-0.5 font-mono tabular-nums text-ink outline-none focus:border-info/40"
          />
          <span className="text-ghost">M</span>
        </label>
        <label className="flex items-center gap-2 font-mono text-[11px] text-muted">
          RISK/TRADE
          <input
            type="number"
            min={0.1}
            max={5}
            step={0.1}
            value={riskPct}
            onChange={(e) => setRiskPct(Number(e.target.value) || 0)}
            className="w-14 rounded-[2px] border border-hairline bg-obsidian px-1.5 py-0.5 font-mono tabular-nums text-ink outline-none focus:border-info/40"
          />
          <span className="text-ghost">%</span>
        </label>
        <span className="font-mono text-[10px] uppercase tracking-wider text-ghost">
          HEAT CAP {RISK_DEFAULTS.maxPortfolioHeatPct}% · POS CAP{" "}
          {RISK_DEFAULTS.maxPositionPct}% · MAX {RISK_DEFAULTS.maxPositions}
        </span>
      </div>

      {/* Heat gauge */}
      <div className="border-b border-hairline px-3 py-2">
        <div className="flex items-center justify-between font-mono text-[10px] uppercase tracking-widest">
          <span className="text-ghost">Portfolio heat</span>
          <span
            className={`tabular-nums ${
              heat >= RISK_DEFAULTS.maxPortfolioHeatPct
                ? "text-bear"
                : heat >= RISK_DEFAULTS.maxPortfolioHeatPct * 0.7
                  ? "text-warn"
                  : "text-bull"
            }`}
          >
            {fmtPct(heat, 2)} / {RISK_DEFAULTS.maxPortfolioHeatPct}%
          </span>
        </div>
        <div className="mt-1 h-1.5 w-full overflow-hidden rounded-[2px] bg-obsidian">
          <div
            className={`h-full ${
              heatPctOfCap >= 100
                ? "bg-rose-500"
                : heatPctOfCap >= 70
                  ? "bg-amber-500"
                  : "bg-emerald-500"
            }`}
            style={{ width: `${heatPctOfCap}%` }}
          />
        </div>
        <div className="mt-1 flex justify-between font-mono text-[10px] tabular-nums text-ghost">
          <span>
            DEPLOYED {fmtPkr(book.totals.deployedValuePkr)} (
            {fmtPct(book.totals.deployedPctOfEquity, 1)} EQ)
          </span>
          <span>
            OPEN RISK {fmtPkr(book.totals.totalRiskPkr)}
          </span>
        </div>
      </div>

      {/* Book table */}
      {book.positions.length === 0 ? (
        <div className="px-3 py-6 text-center">
          <p className="font-mono text-xs text-muted">
            NO SIZABLE SETUPS THIS SESSION
          </p>
          <p className="mt-1 text-[11px] text-ghost">
            Sizing requires actionable long signals with a valid protective
            stop (≥ {RISK_DEFAULTS.minStopDistancePct}% stop distance).
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[700px] border-collapse text-xs">
            <thead>
              <tr className="border-b border-hairline bg-panel text-left text-[10px] uppercase tracking-widest text-ghost">
                <th className="px-3 py-2 font-medium">Ticker</th>
                <th className="px-2 py-2 text-right font-medium">Entry</th>
                <th className="px-2 py-2 text-right font-medium">Stop</th>
                <th className="px-2 py-2 text-right font-medium">Stop Dist</th>
                <th className="px-2 py-2 text-right font-medium">Shares</th>
                <th className="px-2 py-2 text-right font-medium">Value</th>
                <th className="px-2 py-2 text-right font-medium">Risk</th>
                <th className="px-3 py-2 text-right font-medium">Conv</th>
              </tr>
            </thead>
            <tbody>
              {book.positions.map((p) => (
                <tr
                  key={p.ticker}
                  className="border-b border-hairline hover:bg-hoverline"
                >
                  <td className="px-3 py-1.5 font-mono font-semibold text-ink">
                    {p.ticker}
                    {p.clampedByMaxPosition && (
                      <span className="ml-1 rounded-[2px] bg-warn/10 px-1 font-mono text-[9px] uppercase text-warn ring-1 ring-warn/30">
                        capped
                      </span>
                    )}
                  </td>
                  <td className="px-2 py-1.5 text-right font-mono tabular-nums text-ink">
                    {p.entryReference.toFixed(2)}
                  </td>
                  <td className="px-2 py-1.5 text-right font-mono tabular-nums text-bear">
                    {p.stopLoss.toFixed(2)}
                  </td>
                  <td className="px-2 py-1.5 text-right font-mono tabular-nums text-muted">
                    {fmtPct(p.stopDistancePct, 1)}
                  </td>
                  <td className="px-2 py-1.5 text-right font-mono tabular-nums text-ink">
                    {p.shares.toLocaleString()}
                  </td>
                  <td className="px-2 py-1.5 text-right font-mono tabular-nums text-ink">
                    {fmtPkr(p.positionValuePkr)}
                  </td>
                  <td className="px-2 py-1.5 text-right font-mono tabular-nums text-warn">
                    {fmtPct(p.riskPctOfEquity, 2)}
                  </td>
                  <td className="px-3 py-1.5 text-right font-mono text-[10px] uppercase text-muted">
                    {p.conviction ?? "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Rejections trail */}
      {book.rejected.length > 0 && (
        <div className="border-t border-hairline px-3 py-2">
          <p className="font-mono text-[10px] leading-relaxed text-ghost">
            Filter log:
            {book.rejected.slice(0, 4).map((r, i) => (
              <span key={`${r.ticker}-${i}`} className="ml-2 text-muted">
                {r.ticker ?? "—"}[{r.reason}]
              </span>
            ))}
            {book.rejected.length > 4 && (
              <span className="ml-2 text-ghost">
                +{book.rejected.length - 4} more
              </span>
            )}
          </p>
        </div>
      )}
    </section>
  );
}
