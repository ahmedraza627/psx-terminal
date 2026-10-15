import type { SectorMatrixData } from "@/lib/consoleQueries";

const STATUS_CHIP: Record<
  SectorMatrixData["rows"][number]["status"],
  { cls: string; label: string }
> = {
  LEADING: {
    cls: "border-emerald-300 bg-emerald-100 text-emerald-900",
    label: "LEADING",
  },
  NEUTRAL: {
    cls: "border-slate-300 bg-slate-100 text-slate-800",
    label: "NEUTRAL",
  },
  DISTRIBUTION: {
    cls: "border-rose-300 bg-rose-100 text-rose-900",
    label: "DISTRIBUTION",
  },
};

export default function SectorMatrixTable({
  data,
}: {
  data: SectorMatrixData | null;
}) {
  if (!data || data.rows.length === 0) {
    return (
      <div className="rounded-xl border border-slate-200 bg-white p-6 text-center shadow-sm">
        <p className="text-[13px] font-medium text-slate-700">
          No sector matrix computed for this session yet.
        </p>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-xs">
        <thead>
          <tr className="border-b-2 border-slate-300 bg-slate-100 text-xs font-bold uppercase tracking-wider text-slate-800">
            <th className="px-3 py-2 text-left font-medium">Rank</th>
            <th className="px-3 py-2 text-left font-medium">Sector</th>
            <th className="px-3 py-2 text-right font-medium">5D Return (%)</th>
            <th className="px-3 py-2 text-right font-medium">Smart Money</th>
          </tr>
        </thead>
        <tbody>
          {data.rows.map((row) => {
            const chip = STATUS_CHIP[row.status];
            const ret = row.ewReturn5dPct;
            return (
              <tr
                key={row.sector}
                className="border-b border-slate-200 transition-colors hover:bg-sky-50/50"
              >
                <td className="px-3 py-2 text-right font-mono text-[13px] font-bold text-slate-900">
                  {row.rank}
                </td>
                <td className="px-3 py-2 text-left font-bold text-slate-900">
                  {row.sector}
                </td>
                <td className="px-3 py-2 text-right font-mono text-[13px] font-bold text-slate-900">
                  {ret == null ? "—" : `${ret >= 0 ? "+" : ""}${ret.toFixed(2)}%`}
                </td>
                <td className="px-3 py-2 text-right">
                  <span
                    className={`inline-block rounded-[2px] border px-2.5 py-0.5 text-[11px] font-bold tracking-wider ${chip.cls}`}
                  >
                    {chip.label}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
