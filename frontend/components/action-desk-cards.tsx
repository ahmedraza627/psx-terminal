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

/** Position-sizing micro-calculator (collapsed by default). */
export interface BuyCardProps {
  /** @deprecated Removed from public API. */
  _legacyAction?: never;
  setup: BuySetup;
  index: number;
  triangulation?: TriangulationResult;
}

const ORDER_FLOW = ["CONFLUENCE", "NEUTRAL", "DUMP TRAP", "RUNNING_UP"] as const;
type Verdict = typeof ORDER_FLOW[number];

export function BuyCard({ setup, index, triangulation }: BuyCardProps) {
  const verdict: Verdict = triangulation?.verdict ?? "NEUTRAL";

  // Pre-compute all rendering values to avoid TS narrowing in JSX.
  const isConflux = verdict === "CONFLUENCE";
  const isRunningUp = verdict === "RUNNING_UP";
  const badgeTitle = isConflux || isRunningUp ? "3-WAY CONFLUENCE" : isRunningUp ? "PRE-MEETING RUN-UP" : verdict === "DUMP TRAP" ? "DUMP WINDOW" : "NEUTRAL";
  const badgeColor = isConflux || isRunningUp ? (isRunningUp ? "#10b981" : "#10b981") : verdict === "DUMP TRAP" ? "#f43f5e" : "#6b7280";

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
    <div className="rounded-xl border border-slate-200 bg-white p-3.5 shadow-sm transition hover:shadow-md hover:border-slate-300/60">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="inline-flex items-center rounded-full bg-slate-100 px-1.5 py-0.5 text-[10px] font-extrabold text-slate-600">
            #{index + 1}
          </span>
          <span className="text-sm font-extrabold text-slate-900">{setup.ticker}</span>
          <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[9px] font-bold text-slate-500 uppercase tracking-wider">
            {setup.sector}
          </span>
          <span
            className={`rounded px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider ${
              setup.tape_tag === "BUY"
                ? "bg-emerald-50 text-emerald-700 border border-emerald-200"
                : "bg-rose-50 text-rose-700 border border-rose-200"
            }`}
          >
            {setup.tape_tag === "BUY" ? "ACCUMULATION" : setup.tape_tag}
          </span>
        </div>
        {triangulation && triangulation.confluxMet && (
          <span
            className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-extrabold border ${
              isConflux || isRunningUp
                ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                : verdict === "DUMP TRAP"
                  ? "bg-rose-50 text-rose-700 border-rose-200"
                  : "bg-slate-100 text-slate-600 border-slate-200"
            }`}
          >
            <span
              className="inline-block w-1 h-1 rounded-full"
              style={{ backgroundColor: badgeColor }}
            />
            {badgeTitle}
          </span>
        )}
      </div>

      <p className="text-xs font-semibold leading-snug text-slate-800">{setup.rationale}</p>

      <div className="grid grid-cols-4 gap-1.5 pt-1.5 border-t border-slate-200/60 text-[10px] font-mono">
        <div>
          <span className="block text-[8px] text-slate-400 uppercase tracking-wider">ENTRY</span>
          <span className="font-extrabold text-slate-900">PKR {fmtPkr(setup.entry_price)}</span>
        </div>
        <div>
          <span className="block text-[8px] text-slate-400 uppercase tracking-wider">INVALIDATE</span>
          <span className="font-bold text-rose-600">PKR {fmtPkr(setup.stop_price)}</span>
        </div>
        <div>
          <span className="block text-[8px] text-slate-400 uppercase tracking-wider">TARGET</span>
          <span className="font-bold text-emerald-700">PKR {fmtPkr(setup.target_price)}</span>
        </div>
        <div>
          <span className="block text-[8px] text-slate-400 uppercase tracking-wider">R:R</span>
          <span className="font-bold text-blue-700">1:{fmtPkr(setup.rr_ratio)}</span>
        </div>
      </div>

      <div className="flex items-center gap-2 border-t border-slate-200/60 pt-1.5 text-[10px]">
        <div className="flex -space-x-1">
          <span className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-cyan-500/20 border-2 border-white text-[8px] font-extrabold text-cyan-700">
            {flow.institutional[0]}
          </span>
          <span className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-rose-500/20 border-2 border-white text-[8px] font-extrabold text-rose-700">
            {flow.retail[0]}
          </span>
        </div>
        <div className="flex flex-wrap gap-x-2 gap-y-0.5 text-slate-600">
          <span className="font-bold text-slate-800">INST</span>
          <span className="text-slate-500">{flow.institutionalFlow >= 0 ? "+" : ""}{fmtPkr(flow.institutionalFlow)}</span>
          <span className="font-bold text-slate-800">RET</span>
          <span className="text-slate-500">{flow.retailFlow >= 0 ? "+" : ""}{fmtPkr(flow.retailFlow)}</span>
        </div>
        <span className="ml-auto text-slate-400">{flow.institutionalFlow >= 0 ? "Accum." : "Dist."}</span>
      </div>

      {triangulation && verdict !== "NEUTRAL" && (
        <div className="flex flex-wrap items-center justify-between gap-1.5 rounded border border-slate-200/60 bg-slate-50/40 px-2 py-1 text-[10px] font-mono">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
            <span className="font-bold text-slate-600">Cash</span>
            <span className={`font-bold ${setup.dividend_yield ? (setup.dividend_yield >= 8 ? "text-emerald-700" : "text-amber-700") : "text-slate-400"}`}>
              {setup.dividend_yield !== undefined ? setup.dividend_yield.toFixed(1) + "%" : "—"}
            </span>
            <span className="font-bold text-slate-600">Board</span>
            <span className="font-bold text-slate-800">
              {setup.board_meeting_date ? new Date(setup.board_meeting_date).toLocaleDateString("en-GB", { month: "short", day: "numeric" }) : "—"}
              <span className="text-slate-400">({setup.days_to_meeting ?? 0}d)</span>
            </span>
            <span className="font-bold text-slate-600">Run-up</span>
            <span className="font-bold text-slate-800">+{setup.avg_pre_meeting_runup_pct?.toFixed(1) ?? "—"}%</span>
            <span className="font-bold text-slate-600">Dump</span>
            <span className="font-bold text-rose-600">{setup.post_result_dump_prob ? setup.post_result_dump_prob.toFixed(0) + "%" : "—"}%</span>
          </div>
          <span className="text-slate-400">{badgeTitle}</span>
        </div>
      )}
    </div>
  );
}

export interface AvoidCardProps {
  setup: AvoidSetup;
  index: number;
  triangulation?: TriangulationResult;
}
export function AvoidCard({ setup, index, triangulation }: AvoidCardProps) {
  const v: Verdict = triangulation?.verdict ?? "NEUTRAL";

  const isRetailTrap = flowBreakdown(setup.ticker, setup).retailFlow > 0 && flowBreakdown(setup.ticker, setup).institutionalFlow < 0;
  const flow = flowBreakdown(setup.ticker, setup);
  const downsideTarget = setup.stop_price ?? setup.current_price;
  const preservationPct = Math.max(setup.current_price - downsideTarget, 1) / Math.max(downsideTarget, 1) * 100;

  const isDumpTrap = v === "DUMP TRAP";
  const badgeTitle = isDumpTrap ? "DUMP WINDOW" : v === "CONFLUENCE" ? "3-WAY CONFLUENCE" : v === "RUNNING_UP" ? "PRE-MEETING RUN-UP" : "NEUTRAL";
  const badgeColor = isDumpTrap ? "#f43f5e" : v === "CONFLUENCE" || v === "RUNNING_UP" ? "#10b981" : "#6b7280";

  return (
    <div className="rounded-xl border border-rose-200 bg-white p-3.5 shadow-sm transition hover:shadow-md hover:border-rose-300/60">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="inline-flex items-center rounded-full bg-slate-100 px-1.5 py-0.5 text-[10px] font-extrabold text-slate-600">
            #{index + 1}
          </span>
          <span className="text-sm font-extrabold text-slate-900">{setup.ticker}</span>
          <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[9px] font-bold text-slate-500 uppercase tracking-wider">
            {setup.sector}
          </span>
          <span className={`rounded px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider ${isRetailTrap ? "bg-rose-50 text-rose-700 border border-rose-200" : "bg-slate-100 text-slate-500 border border-slate-200"}`}>
            {isRetailTrap ? "RETAIL TRAP" : setup.risk_tag}
          </span>
        </div>
        {triangulation && triangulation.confluxMet && (
          <span
            className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-extrabold border ${
              isDumpTrap
                ? "bg-rose-50 text-rose-700 border-rose-300"
                : "bg-slate-100 text-slate-600 border-slate-200"
            }`}
          >
            <span
              className="inline-block w-1 h-1 rounded-full"
              style={{ backgroundColor: badgeColor }}
            />
            {v}
          </span>
        )}
      </div>

      <p className="text-xs font-semibold leading-snug text-slate-800">{setup.reason}</p>

      <div className="grid grid-cols-4 gap-1.5 pt-1.5 border-t border-rose-200/60 text-[10px] font-mono">
        <div>
          <span className="block text-[8px] text-slate-400 uppercase tracking-wider">AVOID REF</span>
          <span className="font-extrabold text-slate-900">PKR {fmtPkr(setup.current_price)}</span>
        </div>
        <div>
          <span className="block text-[8px] text-rose-500 uppercase tracking-wider">DOWNSIDE TRAP</span>
          <span className="font-bold text-rose-600">PKR {fmtPkr(setup.stop_price ?? setup.current_price)}</span>
        </div>
        <div>
          <span className="block text-[8px] text-slate-400 uppercase tracking-wider">LATEST CLOSE</span>
          <span className="font-extrabold text-slate-900">PKR {fmtPkr(setup.current_price)}</span>
        </div>
        <div>
          <span className={`block text-[8px] uppercase tracking-wider ${isRetailTrap ? "text-rose-500" : "text-slate-400"}`}>
            INVALIDATION / SQUEEZE
          </span>
          <span className={`font-bold ${isRetailTrap ? "text-rose-600" : "text-slate-800"}`}>
            PKR {fmtPkr(setup.stop_price ?? setup.current_price)}
          </span>
        </div>
      </div>

      <div className="flex items-center justify-between rounded border border-rose-200/60 bg-rose-50/30 px-2 py-1.5 text-[10px] font-mono">
        <span className="text-rose-600 uppercase tracking-wider">Capital Preservation</span>
        <span className="font-bold text-rose-700">Preserves: +{preservationPct.toFixed(1)}% Capital</span>
      </div>

      <div className={`flex items-center gap-2 border-t border-slate-200/60 pt-1.5 text-[10px] ${isRetailTrap ? "border-rose-300 bg-rose-50/20" : "border-slate-200/60 bg-slate-50/30"}`}>
        <div className="flex -space-x-1">
          <span className={`inline-flex h-5 w-5 items-center justify-center rounded-full border-2 border-white text-[8px] font-extrabold ${flow.institutionalFlow >= 0 ? "bg-cyan-500/20 text-cyan-700" : "bg-rose-500/20 text-rose-700"}`}>
            {flow.institutional[0]}
          </span>
          <span className={`inline-flex h-5 w-5 items-center justify-center rounded-full border-2 border-white text-[8px] font-extrabold ${flow.retailFlow >= 0 ? "bg-emerald-500/20 text-emerald-700" : "bg-rose-500/20 text-rose-700"}`}>
            {flow.retail[0]}
          </span>
        </div>
        <div className="flex flex-wrap gap-x-2 gap-y-0.5">
          <span className={`font-bold ${flow.institutionalFlow >= 0 ? "text-slate-800" : "text-rose-600"}`}>INST</span>
          <span className={`${flow.institutionalFlow >= 0 ? "text-slate-500" : "text-rose-400"}`}>{flow.institutionalFlow >= 0 ? "+" : ""}{fmtPkr(flow.institutionalFlow)}</span>
          <span className={`font-bold ${flow.retailFlow >= 0 ? "text-slate-800" : "text-rose-600"}`}>RET</span>
          <span className={`${flow.retailFlow >= 0 ? "text-slate-500" : "text-rose-400"}`}>{flow.retailFlow >= 0 ? "+" : ""}{fmtPkr(flow.retailFlow)}</span>
        </div>
        {isRetailTrap && (
          <span className="ml-auto inline-flex items-center gap-1 rounded-full bg-rose-100 px-2 py-0.5 text-[9px] font-extrabold text-rose-700">RETAIL TRAP</span>
        )}
      </div>

      {triangulation && v !== "NEUTRAL" && (
        <div className="flex flex-wrap items-center justify-between gap-1.5 rounded border border-slate-200/60 bg-slate-50/40 px-2 py-1 text-[10px] font-mono">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
            <span className="font-bold text-slate-600">Cash</span>
            <span className={`font-bold ${setup.dividend_yield ? (setup.dividend_yield >= 8 ? "text-emerald-700" : "text-amber-700") : "text-slate-400"}`}>
              {setup.dividend_yield !== undefined ? setup.dividend_yield.toFixed(1) + "%" : "—"}
            </span>
            <span className="font-bold text-slate-600">Board</span>
            <span className="font-bold text-slate-800">
              {setup.board_meeting_date ? new Date(setup.board_meeting_date).toLocaleDateString("en-GB", { month: "short", day: "numeric" }) : "—"}
              <span className="text-slate-400">({setup.days_to_meeting ?? 0}d)</span>
            </span>
            <span className="font-bold text-slate-600">Run-up</span>
            <span className="font-bold text-slate-800">+{setup.avg_pre_meeting_runup_pct?.toFixed(1) ?? "—"}%</span>
            <span className="font-bold text-slate-600">Dump</span>
            <span className="font-bold text-rose-600">{setup.post_result_dump_prob ? setup.post_result_dump_prob.toFixed(0) + "%" : "—"}%</span>
          </div>
          <span className="text-slate-400">{badgeTitle}</span>
        </div>
      )}
    </div>
  );
}