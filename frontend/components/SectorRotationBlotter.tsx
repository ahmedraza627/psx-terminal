"use client";

import FeedErrorPill from "./FeedErrorPill";
import type { DataStatus } from "@/lib/queries";

export interface RotationRow {
  tradeDate: string;
  sectorName: string;
  rsRatio: number;
  rsMomentum: number;
  quadrant: "LEADING" | "IMPROVING" | "WEAKENING" | "LAGGING";
  topLeaderTicker: string | null;
  topDraggerTicker: string | null;
}

const QUADRANT_STYLE: Record<RotationRow["quadrant"], string> = {
  LEADING: "bg-emerald-500/10 text-emerald-300 ring-emerald-500/30",
  IMPROVING: "bg-sky-500/10 text-sky-300 ring-sky-500/30",
  WEAKENING: "bg-amber-500/10 text-amber-300 ring-amber-500/30",
  LAGGING: "bg-rose-500/10 text-rose-300 ring-rose-500/30",
};

export default function SectorRotationBlotter({
  rows,
  status,
}: {
  rows: RotationRow[];
  status?: DataStatus | null;
}) {
  if (rows.length === 0) {
    const missing = status?.tableMissing ?? false;
    const pending = status?.feedPending ?? false;
    const unreachable = status?.unreachable ?? false;
    return (
      <div className="px-3 py-6 text-center">
        {unreachable ? (
          <FeedErrorPill />
        ) : missing ? (
          <p className="font-mono text-xs uppercase tracking-widest text-amber-300">
            [SCHEMA PENDING: RUN SCHEMA.SQL IN SUPABASE]
          </p>
        ) : pending ? (
          <p className="font-mono text-xs uppercase tracking-widest text-sky-300">
            [RRG DESK: AWAITING FIRST ROTATION PASS]
          </p>
        ) : (
          <p className="font-mono text-xs text-zinc-500">
            NO SECTORS MET THE ROTATION THRESHOLD THIS SESSION
          </p>
        )}
        <p className="mt-1 text-[11px] text-zinc-600">
          Relative Rotation vs KSE-100: equal-weight sector indices, RS-Ratio
          and RS-Momentum rebased to 100; quadrants LEADING / IMPROVING /
          WEAKENING / LAGGING (psx_sector_rotation).
        </p>
      </div>
    );
  }

  const count = (q: RotationRow["quadrant"]) =>
    rows.filter((r) => r.quadrant === q).length;

  return (
    <section>
      <div className="flex items-center justify-between border-b border-zinc-800 px-3 py-2">
        <h2 className="text-[10px] font-medium uppercase tracking-widest text-zinc-600">
          Sector Rotation - RRG vs KSE-100
        </h2>
        <span className="font-mono text-[11px] tabular-nums text-zinc-500">
          {count("LEADING")} LEAD · {count("IMPROVING")} IMPR ·{" "}
          {count("WEAKENING")} WEAK · {count("LAGGING")} LAG
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] border-collapse text-xs">
          <thead>
            <tr className="border-b border-zinc-800 bg-[#0c1017] text-left text-[10px] uppercase tracking-widest text-zinc-600">
              <th className="px-3 py-2 font-medium">Sector</th>
              <th className="px-2 py-2 font-medium">Quadrant</th>
              <th className="px-2 py-2 text-right font-medium">RS-Ratio</th>
              <th className="px-2 py-2 text-right font-medium">RS-Mom</th>
              <th className="px-2 py-2 font-medium">Leader</th>
              <th className="px-3 py-2 font-medium">Dragger</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={`${row.tradeDate}-${row.sectorName}`}
                className="border-b border-zinc-900 hover:bg-zinc-900/40"
              >
                <td className="px-3 py-1.5 font-mono text-[11px] font-semibold text-zinc-100">
                  {row.sectorName}
                </td>
                <td className="px-2 py-1.5">
                  <span
                    className={`inline-block rounded px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider ring-1 ${
                      QUADRANT_STYLE[row.quadrant]
                    }`}
                  >
                    {row.quadrant}
                  </span>
                </td>
                <td
                  className={`px-2 py-1.5 text-right font-mono tabular-nums ${
                    row.rsRatio >= 100 ? "text-emerald-400" : "text-rose-400"
                  }`}
                >
                  {row.rsRatio.toFixed(2)}
                </td>
                <td
                  className={`px-2 py-1.5 text-right font-mono tabular-nums ${
                    row.rsMomentum >= 100 ? "text-emerald-400" : "text-rose-400"
                  }`}
                >
                  {row.rsMomentum.toFixed(2)}
                </td>
                <td className="px-2 py-1.5 font-mono text-emerald-300">
                  {row.topLeaderTicker ?? "—"}
                </td>
                <td className="px-3 py-1.5 font-mono text-rose-300">
                  {row.topDraggerTicker ?? "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="border-t border-zinc-900 px-3 py-2">
        <p className="font-mono text-[10px] leading-relaxed text-zinc-600">
          RS-Ratio &gt; 100 = outperforming KSE-100 · RS-Mom &gt; 100 = relative
          strength rising over the 5-session Jacob span · LEADING = strong and
          strengthening, LAGGING = weak and deteriorating.
        </p>
      </div>
    </section>
  );
}
