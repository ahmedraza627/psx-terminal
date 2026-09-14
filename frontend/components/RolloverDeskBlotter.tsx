"use client";

export interface RolloverRow {
  tradeDate: string;
  ticker: string;
  entryReference: number | null;
  signalType: string;
  futuresSymbol: string | null;
  futuresClose: number | null;
  spotClose: number | null;
  basisPct: number | null;
  basisPrevPct: number | null;
  stance: string | null;
  rationale: string;
}

function fmtPrice(value: number | null): string {
  return value == null ? "—" : value.toFixed(2);
}

function fmtPct(value: number | null, digits = 2): string {
  return value == null
    ? "—"
    : `${value >= 0 ? "+" : ""}${value.toFixed(digits)}%`;
}

export default function RolloverDeskBlotter({ rows }: { rows: RolloverRow[] }) {
  if (rows.length === 0) {
    return (
      <div className="px-3 py-6 text-center">
        <p className="font-mono text-xs text-muted">
          NO BASIS INVERSIONS OR ROLLOVER SQUEEZES THIS SESSION
        </p>
        <p className="mt-1 text-[11px] text-ghost">
          The desk scans deliverable futures (XXX-FUT) vs spot around rollover
          windows; it fills automatically once the PSX futures feed stores
          contract closes (psx_futures_eod).
        </p>
      </div>
    );
  }

  const inversionCount = rows.filter(
    (r) => r.signalType === "BASIS_INVERSION_SHORT"
  ).length;

  return (
    <section>
      <div className="flex items-center justify-between border-b border-hairline px-3 py-2">
        <h2 className="text-[10px] font-medium uppercase tracking-widest text-ghost">
          Futures Rollover Basis - Inversion &amp; Short Squeeze Desk
        </h2>
        <span className="font-mono text-[11px] tabular-nums text-muted">
          {inversionCount} INVERSION · {rows.length - inversionCount} SQUEEZE
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[680px] border-collapse text-xs">
          <thead>
            <tr className="border-b border-hairline bg-panel text-left text-[10px] uppercase tracking-widest text-ghost">
              <th className="px-3 py-2 font-medium">Underlying</th>
              <th className="px-2 py-2 font-medium">Signal</th>
              <th className="px-2 py-2 text-right font-medium">Spot</th>
              <th className="px-2 py-2 text-right font-medium">Futures</th>
              <th className="px-2 py-2 text-right font-medium">Basis</th>
              <th className="px-3 py-2 text-right font-medium">Basis Prev</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const isInversion = row.signalType === "BASIS_INVERSION_SHORT";
              return (
                <tr
                  key={`${row.tradeDate}-${row.ticker}-${row.signalType}`}
                  className="border-b border-hairline hover:bg-hoverline"
                >
                  <td className="px-3 py-1.5 font-mono font-semibold text-ink">
                    <span className="block">{row.ticker}</span>
                    <span className="block text-[10px] font-normal text-ghost">
                      {row.futuresSymbol ?? "—"}
                    </span>
                  </td>
                  <td className="px-2 py-1.5">
                    <span
                      className={`inline-block rounded-[2px] px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider ring-1 ${
                        isInversion
                          ? "bg-cyan-500/10 text-cyan-300 ring-cyan-500/30"
                          : "bg-bull/10 text-bull ring-bull/30"
                      }`}
                    >
                      {isInversion ? "BASIS INVERSION" : "ROLLOVER SQUEEZE"}
                    </span>
                  </td>
                  <td className="px-2 py-1.5 text-right font-mono tabular-nums text-ink">
                    {fmtPrice(row.spotClose ?? row.entryReference)}
                  </td>
                  <td className="px-2 py-1.5 text-right font-mono tabular-nums text-ink">
                    {fmtPrice(row.futuresClose)}
                  </td>
                  <td
                    className={`px-2 py-1.5 text-right font-mono tabular-nums ${
                      row.basisPct != null && row.basisPct < 0
                        ? "text-cyan-300"
                        : "text-ink"
                    }`}
                  >
                    {fmtPct(row.basisPct)}
                  </td>
                  <td className="px-3 py-1.5 text-right font-mono tabular-nums text-ghost">
                    {fmtPct(row.basisPrevPct)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="border-t border-hairline px-3 py-2">
        <p className="font-mono text-[10px] leading-relaxed text-ghost">
          Stances:
          {rows.slice(0, 3).map((r) => (
            <span key={`${r.ticker}-${r.signalType}`} className="mt-1 block text-muted">
              ▸ {r.ticker} [{r.stance ?? "—"}] — {r.rationale}
            </span>
          ))}
        </p>
      </div>
    </section>
  );
}
