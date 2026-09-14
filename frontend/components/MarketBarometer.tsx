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
      <div className="flex items-center gap-4 border-b border-hairline bg-panel px-3 py-2">
        <span className="text-[10px] uppercase tracking-widest text-ghost">
          NCCPL Flows
        </span>
        <span className="h-3 w-40 animate-pulse rounded-[2px] bg-panel" />
        <span className="h-3 w-40 animate-pulse rounded-[2px] bg-panel" />
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
      ? "text-bull"
      : data.divergence === "RETAIL_TRAP_RISK"
        ? "text-bear"
        : "text-info";

  return (
    <div className="flex items-center gap-x-4 gap-y-1 overflow-x-auto whitespace-nowrap border-b border-hairline bg-panel px-3 py-2 text-xs">
      <span className="text-[10px] font-medium uppercase tracking-widest text-ghost">
        NCCPL {data.tradeDate}
      </span>
      <span className="font-mono tabular-nums text-muted">
        INST{" "}
        <span
          className={
            data.institutionalNet >= 0 ? "text-bull" : "text-bear"
          }
        >
          {fmtMn(data.institutionalNet)}
        </span>
      </span>
      <span className="font-mono tabular-nums text-muted">
        RETAIL{" "}
        <span
          className={data.retailNet >= 0 ? "text-bull" : "text-bear"}
        >
          {fmtMn(data.retailNet)}
        </span>
      </span>
      <span className="font-mono tabular-nums text-muted">
        DIV{" "}
        <span className="tabular-nums text-info">
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
