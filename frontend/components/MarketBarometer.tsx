"use client";

import type { Barometer } from "@/lib/queries";

const PKR_MN = 1_000_000;

function fmtMn(value: number): string {
  const mn = value / PKR_MN;
  return `${mn >= 0 ? "+" : ""}${mn.toFixed(0)}M`;
}

function fmtSigned(value: number): string {
  return `${value >= 0 ? "+" : ""}${value.toFixed(0)}`;
}

export default function MarketBarometer({ data }: { data: Barometer | null }) {
  if (!data) {
    return (
      <div className="flex items-center gap-4 border-b border-zinc-800 bg-[#0c1017] px-3 py-2">
        <span className="text-[10px] uppercase tracking-widest text-zinc-600">
          NCCPL Flows
        </span>
        <span className="h-3 w-40 animate-pulse rounded bg-zinc-800" />
        <span className="h-3 w-40 animate-pulse rounded bg-zinc-800" />
      </div>
    );
  }

  const label =
    data.divergence === "SMART_MONEY_ACCUMULATION"
      ? "SMART MONEY ACCUMULATION"
      : data.divergence === "RETAIL_TRAP_RISK"
        ? "RETAIL TRAP RISK"
        : "FLOWS ALIGNED";
  const labelCls =
    data.divergence === "SMART_MONEY_ACCUMULATION"
      ? "text-emerald-400"
      : data.divergence === "RETAIL_TRAP_RISK"
        ? "text-rose-400"
        : "text-sky-300";

  return (
    <div className="flex items-center gap-x-4 gap-y-1 overflow-x-auto whitespace-nowrap border-b border-zinc-800 bg-[#0c1017] px-3 py-2 text-xs">
      <span className="text-[10px] font-medium uppercase tracking-widest text-zinc-600">
        NCCPL {data.tradeDate}
      </span>
      <span className="font-mono tabular-nums text-zinc-400">
        INST{" "}
        <span
          className={
            data.institutionalNet >= 0 ? "text-emerald-400" : "text-rose-400"
          }
        >
          {fmtMn(data.institutionalNet)}
        </span>
      </span>
      <span className="font-mono tabular-nums text-zinc-400">
        RETAIL{" "}
        <span
          className={data.retailNet >= 0 ? "text-emerald-400" : "text-rose-400"}
        >
          {fmtMn(data.retailNet)}
        </span>
      </span>
      <span className="font-mono tabular-nums text-zinc-400">
        DIV{" "}
        <span className="tabular-nums text-sky-300">
          {fmtSigned(data.institutionalNet - data.retailNet)}
        </span>
      </span>
      <span
        className={`text-[10px] font-semibold uppercase tracking-widest ${labelCls}`}
      >
        [{label}]
      </span>
    </div>
  );
}
