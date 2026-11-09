"use client";

import { useState } from "react";
import {
  calculatePositionSize,
  flowBreakdown,
  fmtPkr,
  fmtInt,
} from "@/lib/riskEngine";
import type { BuySetup, AvoidSetup, CalculatorState, FlowBreakdown } from "@/lib/riskEngine";
import type { TriangulationResult } from "@/lib/catalystEngine";

/** Position-sizing sub-component (collapsible micro-calculator). */
export interface BuyCardProps {
  setup: BuySetup;
  index: number;
  triangulation?: TriangulationResult;
}

export function BuyCard({ setup, index, triangulation }: BuyCardProps) {
  const [open, setOpen] = useState(false);
  const [calc, setCalc] = useState<CalculatorState>({
    accountCapital: 1_000_000,
    riskPercent: 1.5,
  });

  const flow = flowBreakdown(setup.ticker, setup);
  const size = calculatePositionSize({
    accountCapital: calc.accountCapital,
    riskPercent: calc.riskPercent,
    entryPrice: setup.entry_price,
    stopPrice: setup.stop_price,
  });

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm space-y-4 transition hover:border-blue-300/60">
      {/* Card header: rank, ticker, sector, accumulation tag + confluence badge */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="inline-flex items-center rounded-full bg-blue-50 px-2 py-0.5 text-[11px] font-bold text-blue-700">
            #{index + 1}
          </span>
          <span className="text-base font-extrabold text-slate-900">{setup.ticker}</span>
          <span className="rounded bg-slate-100 px-2 py-0.5 text-[10px] font-medium text-slate-500">
            {setup.sector}
          </span>
          <span
            className="rounded bg-emerald-50 px-2 py-0.5 text-[10px] font-bold text-emerald-700"
            style={{ border: "1px solid #bbf7d0" }}
          >
            {setup.tape_tag}
          </span>
        </div>
        {triangulation && triangulation.confluxMet && (
          <span
            className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[11px] font-bold border ${triangulation.verdict === "CONFLUENCE" || triangulation.verdict === "RUNNING_UP" ? "bg-emerald-100 text-emerald-700 border-emerald-300" : triangulation.verdict === "DUMP TRAP" ? "bg-rose-100 text-rose-700 border-rose-300" : "bg-slate-100 text-slate-600 border-slate-200"}`}
          >
            <span className="inline-block w-1.5 h-1.5 rounded-full" style={{ backgroundColor: triangulation.verdict === "CONFLUENCE" ? "#10b981" : triangulation.verdict === "DUMP TRAP" ? "#f43f5e" : "#6b7280" }}
            />
            {triangulation.verdict === "CONFLUENCE" ? "3-WAY CONFLUENCE" : triangulation.verdict === "RUNNING_UP" ? "PRE-MEETING RUN-UP" : triangulation.verdict === "DUMP TRAP" ? "DUMP TRAP" : "NEUTRAL"}
          </span>
        )}
      </div>

      {/* Subtitle under symbol: high-contrast, readable for traders */}
      <p className="text-xs leading-snug font-semibold text-slate-800">{setup.rationale}</p>

      {/* Reference grid - 4 boxes */}
      <div className="grid grid-cols-4 gap-2 pt-2 border-t border-slate-200/60 text-xs font-mono">
        <div>
          <span className="block text-[10px] text-slate-400 uppercase tracking-wider">
            ENTRY REF
          </span>
          <span className="font-bold text-slate-900">PKR {fmtPkr(setup.entry_price)}</span>
        </div>
        <div>
          <span className="block text-[10px] text-slate-400 uppercase tracking-wider">
            INVALIDATION
          </span>
          <span className="font-bold text-rose-600">PKR {fmtPkr(setup.stop_price)}</span>
        </div>
        <div>
          <span className="block text-[10px] text-slate-400 uppercase tracking-wider">
            TARGET
          </span>
          <span className="font-bold text-emerald-600">PKR {fmtPkr(setup.target_price)}</span>
        </div>
        <div>
          <span className="block text-[10px] text-slate-400 uppercase tracking-wider">
            R:R
          </span>
          <span className="font-bold text-blue-700">1:{fmtPkr(setup.rr_ratio)}</span>
        </div>
      </div>

      {/* FIPI vs LIPI flow badge bar */}
      <div className="flex items-center gap-3 border-t border-slate-200/60 pt-3 text-xs">
        <div className="flex -space-x-1.5">
          <span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-cyan-500/20 border-2 border-white text-[10px] font-bold text-cyan-700">
            {flow.institutional[0]}
          </span>
          <span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-rose-500/20 border-2 border-white text-[10px] font-bold text-rose-700">
            {flow.retail[0]}
          </span>
        </div>
        <div className="flex flex-wrap gap-x-3 gap-y-1 text-slate-600">
          <span className="font-semibold text-slate-800">INST</span>
          <span className="text-slate-500">
            {flow.institutionalFlow >= 0 ? "+" : ""}
            {fmtPkr(flow.institutionalFlow)}
          </span>
          <span className="font-semibold text-slate-800">RETAIL</span>
          <span className="text-slate-500">
            {flow.retailFlow >= 0 ? "+" : ""}
            {fmtPkr(flow.retailFlow)}
          </span>
        </div>
        <span className="ml-auto text-slate-400">
          {flow.institutionalFlow >= 0 ? "Accumulating" : "Distributing"}
        </span>
      </div>

      {/* Corporate catalyst strip: cash yield, board meeting, historical run-up */}
      {triangulation && triangulation.verdict !== "NEUTRAL" && (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded border border-slate-200 bg-slate-50/60 px-3 py-2 text-xs font-mono">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <span className="font-semibold text-slate-600">Cash Yield</span>
            <span className={`font-bold ${setup.dividend_yield ? (setup.dividend_yield >= 8 ? "text-emerald-700" : "text-amber-700") : "text-slate-400"}`}>
              {setup.dividend_yield !== undefined ? setup.dividend_yield.toFixed(1) + "%" : "—"}
            </span>
            <span className="font-semibold text-slate-600">Board</span>
            <span className="font-bold text-slate-800">
              {setup.board_meeting_date ? new Date(setup.board_meeting_date).toLocaleDateString("en-GB", { month: "short", day: "numeric" }) : "—"}
              <span className="text-slate-400">({setup.days_to_meeting ?? 0}d)</span>
            </span>
            <span className="font-semibold text-slate-600">Historic Run-up</span>
            <span className="font-bold text-slate-800">+{setup.avg_pre_meeting_runup_pct?.toFixed(1) ?? "—"}%</span>
            <span className="font-semibold text-slate-600">Dump Risk</span>
            <span className="font-bold text-rose-600">{setup.post_result_dump_prob ? setup.post_result_dump_prob.toFixed(0) + "%" : "—"}%</span>
          </div>
          <span className="text-slate-400">
            Catalyst: {triangulation.catalystVerdict}
          </span>
        </div>
      )}

      {/* Position sizing calculator (collapsible) */}
      <div className="border border-slate-200 rounded-lg bg-slate-50/80 p-3 space-y-3 transition">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="flex items-center justify-between w-full text-sm font-semibold text-slate-700 hover:text-slate-900"
        >
          <span>Calculate size</span>
          <span
            className={`text-xs transition ${
              open ? "text-blue-600" : "text-slate-400"
            }`}
          >
            {open ? "▲" : "▼"}
          </span>
        </button>
        {open && (
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-[10px] text-slate-400 mb-1">
                Account Capital (PKR)
              </label>
              <input
                type="number"
                value={calc.accountCapital}
                onChange={(e) =>
                  setCalc({ ...calc, accountCapital: Number(e.target.value) || 0 })
                }
                className="w-full rounded border border-slate-300 bg-white px-2 py-1 text-xs font-mono text-slate-800 focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
            </div>
            <div>
              <label className="block text-[10px] text-slate-400 mb-1">
                Max Risk per Trade %
              </label>
              <input
                type="number"
                value={calc.riskPercent}
                onChange={(e) =>
                  setCalc({ ...calc, riskPercent: Number(e.target.value) || 0 })
                }
                className="w-full rounded border border-slate-300 bg-white px-2 py-1 text-xs font-mono text-slate-800 focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
            </div>
          </div>
        )}
        <div className="border-t border-slate-200 pt-2 text-xs font-mono">
          <div className="flex justify-between text-slate-500">
            <span>Risk Amount</span>
            <span className="font-bold text-slate-800">PKR {fmtPkr(size.riskAmount)}</span>
          </div>
          <div className="flex justify-between text-slate-500">
            <span>Risk per share</span>
            <span className="font-bold text-slate-800">PKR {fmtPkr(size.riskPerShare)}</span>
          </div>
          <div className="flex justify-between text-slate-500">
            <span>Position size</span>
            <span className="font-bold text-blue-700">{fmtInt(size.shares)} shares</span>
          </div>
          <div className="flex justify-between text-slate-500">
            <span>Total exposure</span>
            <span className="font-bold text-emerald-600">PKR {fmtPkr(size.totalExposure)}</span>
          </div>
          <div className="flex justify-between text-slate-500">
            <span>Portfolio weight</span>
            <span className="font-bold text-amber-600">{size.weightPercent.toFixed(2)}%</span>
          </div>
        </div>
      </div>
    </div>
  );
}

/** Risk/avoid sub-component with FIPI/LIPI badge bar + retail-trap highlight. */
export interface AvoidCardProps {
  setup: AvoidSetup;
  index: number;
  triangulation?: TriangulationResult;
}

/**
 * Avoid Card — 4-box institutional metrics grid, capital-preservation view.
 *
 * Layout mirrors BuyCard's reference grid so senior traders can compare a
 * sell-side pressure call against a buy-side conviction call in the same
 * schema.
 *
 * Box 1:  AVOID CALL REF   -> current_price (the call reference price)
 * Box 2:  DOWNSIDE TARGET -> stop_price (the invalidation below which the
 *                            call is deemed invalid)
 * Box 3:  LATEST CLOSE    -> current_price  (latest session close)
 * Box 4:  INVALIDATION /  -> stop_price with a red "SQUEEZE" label when the
 *    SQUEEZE          retail flow has squeezed the trap
 * Reward:Risk / Capital preservation metric shown under the grid.
 */
export function AvoidCard({ setup, index, triangulation }: AvoidCardProps) {
  const flow = flowBreakdown(setup.ticker, setup);

  // Retail trap divergence: retail net buying while institutions net selling.
  const isRetailTrap = flow.retailFlow > 0 && flow.institutionalFlow < 0;

  // Capital-preservation reward: how far the latest close sits above the
  // downside invalidation as a percentage of the invalidation distance.
  const downsideTarget = setup.stop_price ?? setup.current_price;
  const preservationPct =
    Math.max(setup.current_price - downsideTarget, 1) / Math.max(downsideTarget, 1) * 100;

  return (
    <div className="rounded-xl border border-rose-200 bg-white p-5 shadow-sm space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="inline-flex items-center rounded-full bg-rose-50 px-2 py-0.5 text-[11px] font-bold text-rose-700">
            #{index + 1}
          </span>
          <span className="text-base font-extrabold text-slate-900">{setup.ticker}</span>
          <span className="rounded bg-slate-100 px-2 py-0.5 text-[10px] font-medium text-slate-500">
            {setup.sector}
          </span>
          <span className="rounded bg-rose-50 px-2 py-0.5 text-[10px] font-bold text-rose-700">
            {setup.risk_tag}
          </span>
        </div>
      </div>

      {/* Card header: confluence badge on avoid card */}
      {triangulation && triangulation.confluxMet && (
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span
            className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[11px] font-bold border ${triangulation.verdict === "DUMP TRAP" ? "bg-rose-100 text-rose-700 border-rose-300" : "bg-slate-100 text-slate-600 border-slate-200"}`}
          >
            <span className="inline-block w-1.5 h-1.5 rounded-full" style={{ backgroundColor: triangulation.verdict === "DUMP TRAP" ? "#f43f5e" : "#6b7280" }}
            />
            {triangulation.verdict}
          </span>
        </div>
      )}

      {/* Subtitle under symbol: high-contrast rose/slate for readability */}
      <p className="text-xs leading-snug font-semibold text-slate-800">{setup.reason}</p>
      <div className="grid grid-cols-4 gap-2 pt-2 border-t border-rose-200/60 text-xs font-mono">
        <div>
          <span className="block text-[10px] text-slate-400 uppercase tracking-wider">
            AVOID CALL REF
          </span>
          <span className="font-bold text-slate-900">PKR {fmtPkr(setup.current_price)}</span>
        </div>
        <div>
          <span className="block text-[10px] text-rose-500 uppercase tracking-wider">
            DOWNSIDE TARGET
          </span>
          <span className="font-bold text-rose-600">
            PKR {fmtPkr(setup.stop_price ?? setup.current_price)}
          </span>
        </div>
        <div>
          <span className="block text-[10px] text-slate-400 uppercase tracking-wider">
            LATEST CLOSE
          </span>
          <span className="font-bold text-slate-900">PKR {fmtPkr(setup.current_price)}</span>
        </div>
        <div>
          <span
            className={`block text-[10px] uppercase tracking-wider ${isRetailTrap ? "text-rose-500" : "text-slate-400"}`}
          >
            INVALIDATION / SQUEEZE
          </span>
          <span
            className={`font-bold ${isRetailTrap ? "text-rose-600" : "text-slate-800"}`}
          >
            PKR {fmtPkr(setup.stop_price ?? setup.current_price)}
          </span>
        </div>
      </div>

      {/* Reward:Risk / Capital preservation metric */}
      <div className="flex items-center justify-between rounded border border-rose-200 bg-rose-50/40 px-3 py-2 text-xs font-mono">
        <span className="text-rose-600 uppercase">Capital Preservation</span>
        <span className="font-bold text-rose-700">
          Preserves: +{preservationPct.toFixed(1)}% Capital
        </span>
      </div>

      {/* FIPI vs LIPI flow badge bar - retail trap divergence highlight */}
      <div
        className={`flex items-center gap-3 text-xs rounded border p-3 ${
          isRetailTrap
            ? "border-rose-300 bg-rose-50/30"
            : "border-slate-200/60 bg-slate-50/40"
        }`}
      >
        <div className="flex -space-x-1.5">
          <span
            className={`inline-flex h-6 w-6 items-center justify-center rounded-full border-2 border-white text-[10px] font-bold ${
              flow.institutionalFlow >= 0
                ? "bg-cyan-500/20 text-cyan-700"
                : "bg-rose-500/20 text-rose-700"
            }`}
          >
            {flow.institutional[0]}
          </span>
          <span
            className={`inline-flex h-6 w-6 items-center justify-center rounded-full border-2 border-white text-[10px] font-bold ${
              flow.retailFlow >= 0
                ? "bg-emerald-500/20 text-emerald-700"
                : "bg-rose-500/20 text-rose-700"
            }`}
          >
            {flow.retail[0]}
          </span>
        </div>
        <div className="flex flex-wrap gap-x-3 gap-y-1">
          <span
            className={`font-semibold ${
              flow.institutionalFlow >= 0 ? "text-slate-800" : "text-rose-600"
            }`}
          >
            INST
          </span>
          <span
            className={`${flow.institutionalFlow >= 0 ? "text-slate-500" : "text-rose-400"}`}
          >
            {flow.institutionalFlow >= 0 ? "+" : ""}
            {fmtPkr(flow.institutionalFlow)}
          </span>
          <span
            className={`font-semibold ${
              flow.retailFlow >= 0 ? "text-slate-800" : "text-rose-600"
            }`}
          >
            RETAIL
          </span>
          <span
            className={`${flow.retailFlow >= 0 ? "text-slate-500" : "text-rose-400"}`}
          >
            {flow.retailFlow >= 0 ? "+" : ""}
            {fmtPkr(flow.retailFlow)}
          </span>
        </div>
        {isRetailTrap && (
          <span className="ml-auto inline-flex items-center gap-1 rounded-full bg-rose-100 px-2.5 py-0.5 text-[10px] font-bold text-rose-700">
            RETAIL TRAP
          </span>
        )}
      </div>

      {/* Corporate catalyst strip: cash yield, board meeting, historical run-up */}
      {triangulation && triangulation.verdict !== "NEUTRAL" && (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded border border-slate-200 bg-slate-50/60 px-3 py-2 text-xs font-mono">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <span className="font-semibold text-slate-600">Cash Yield</span>
            <span className={`font-bold ${setup.dividend_yield ? (setup.dividend_yield >= 8 ? "text-emerald-700" : "text-amber-700") : "text-slate-400"}`}>
              {setup.dividend_yield !== undefined ? setup.dividend_yield.toFixed(1) + "%" : "—"}
            </span>
            <span className="font-semibold text-slate-600">Board</span>
            <span className="font-bold text-slate-800">
              {setup.board_meeting_date ? new Date(setup.board_meeting_date).toLocaleDateString("en-GB", { month: "short", day: "numeric" }) : "—"}
              <span className="text-slate-400">({setup.days_to_meeting ?? 0}d)</span>
            </span>
            <span className="font-semibold text-slate-600">Historic Run-up</span>
            <span className="font-bold text-slate-800">+{setup.avg_pre_meeting_runup_pct?.toFixed(1) ?? "—"}%</span>
            <span className="font-semibold text-slate-600">Dump Risk</span>
            <span className="font-bold text-rose-600">{setup.post_result_dump_prob ? setup.post_result_dump_prob.toFixed(0) + "%" : "—"}%</span>
          </div>
          <span className="text-slate-400">
            Catalyst: {triangulation.catalystVerdict}
          </span>
        </div>
      )}
    </div>
  );
}

/** Institutional ledger table + forward-test summary. */
export interface LedgerTableProps {
  rows: ReturnType<typeof import("@/lib/riskEngine").buildLedgerRows>;
  summary: ReturnType<typeof import("@/lib/riskEngine").computeForwardTestSummary>;
}

export function LedgerTable({ rows, summary }: LedgerTableProps) {
  return (
    <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm">
      <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
        <h3 className="text-sm font-bold text-slate-700">Institutional Ledger</h3>
        <span className="text-xs text-slate-400">Paper trail · last 5 sessions</span>
      </div>
      <table className="w-full text-xs">
        <thead>
          <tr className="bg-slate-100 text-slate-500 uppercase text-[10px] tracking-wider">
            <th className="px-4 py-2 text-left">Date Issued</th>
            <th className="px-4 py-2 text-left">Ticker</th>
            <th className="px-4 py-2 text-left">Type</th>
            <th className="px-4 py-2 text-left">Entry Price</th>
            <th className="px-4 py-2 text-left">Current / Exit</th>
            <th className="px-4 py-2 text-left">Status</th>
            <th className="px-4 py-2 text-left">Realized R:R</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr
              key={`${r.date}-${r.ticker}`}
              className="border-t border-slate-100 transition hover:bg-slate-50/60"
            >
              <td className="px-4 py-2 font-mono text-slate-600">{r.date}</td>
              <td className="px-4 py-2 font-bold text-slate-900">{r.ticker}</td>
              <td className="px-4 py-2">
                <span
                  className={`inline-flex rounded-full px-2 py-0.5 text-[10px] font-bold ${
                    r.type === "BUY"
                      ? "bg-blue-50 text-blue-700"
                      : "bg-rose-50 text-rose-700"
                  }`}
                >
                  {r.type}
                </span>
              </td>
              <td className="px-4 py-2 font-mono text-slate-600">PKR {fmtPkr(r.entryPrice)}</td>
              <td className="px-4 py-2 font-mono text-slate-800">PKR {fmtPkr(r.currentPrice)}</td>
              <td className="px-4 py-2">
                <span
                  className={`inline-flex rounded-full px-2 py-0.5 text-[10px] font-bold ${
                    r.status === "ACTIVE"
                      ? "bg-slate-100 text-slate-600"
                      : r.status === "TARGET HIT"
                      ? "bg-emerald-50 text-emerald-700"
                      : "bg-rose-50 text-rose-700"
                  }`}
                >
                  {r.status}
                </span>
              </td>
              <td className="px-4 py-2 font-mono text-slate-600">1:{fmtPkr(r.realizedRR)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="flex items-center justify-between border-t border-slate-200 px-4 py-3 text-xs">
        <span className="text-slate-500">Forward-Test Win Rate</span>
        <span className="font-bold text-slate-800">{summary.winRate.toFixed(0)}%</span>
      </div>
      <div className="flex items-center justify-between border-t border-slate-200 px-4 py-3 text-xs">
        <span className="text-slate-500">Total Realized Alpha</span>
        <span className="font-bold text-emerald-600">+{summary.totalRealizedAlpha.toFixed(2)}R</span>
      </div>
    </div>
  );
}

/** Top-level sector guardrail banner. */
export interface GuardrailProps {
  message: string;
}

export function Guardrail({ message }: GuardrailProps) {
  if (!message) return null;
  return (
    <div className="flex items-center gap-3 rounded-xl border border-amber-300/60 bg-amber-50/40 px-4 py-3">
      <span className="text-lg font-bold text-amber-600">!</span>
      <div>
        <p className="text-xs font-bold text-amber-800">Sector Overweight Warning</p>
        <p className="text-[11px] text-amber-700">{message}</p>
      </div>
    </div>
  );
}
