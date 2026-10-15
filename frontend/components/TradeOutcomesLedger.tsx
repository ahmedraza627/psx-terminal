import type {
  OutcomeStatus,
  TradeOutcomesLedgerData,
} from "@/lib/consoleQueries";
import { fmtPct, fmtPf } from "@/components/ui/format";
import TickerLink from "@/components/TickerLink";

const STATUS_BADGE: Record<
  OutcomeStatus,
  { cls: string; label: string }
> = {
  OPEN: { cls: "border-sky-300 bg-sky-100 text-sky-900", label: "OPEN" },
  WIN_TP1: {
    cls: "border-emerald-300 bg-emerald-100 text-emerald-900",
    label: "WIN_TP1",
  },
  LOSS_SL: {
    cls: "border-rose-300 bg-rose-100 text-rose-900",
    label: "LOSS_SL",
  },
  EXPIRED_TIME: {
    cls: "border-slate-300 bg-slate-100 text-slate-800",
    label: "EXPIRED_TIME",
  },
};

function HorizonLabel(horizon: string): string {
  return horizon
    .split("_")
    .map((w) => w.charAt(0) + w.slice(1).toLowerCase())
    .join(" ");
}

export default function TradeOutcomesLedger({
  data,
}: {
  data: TradeOutcomesLedgerData | null;
}) {
  const rows = data?.rows ?? [];
  const aggregate = data?.aggregate;

  return (
    <section className="mt-8 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="mb-4 flex items-baseline justify-between gap-4">
        <div>
          <h2 className="text-[15px] font-bold tracking-tight text-slate-900">
            Institutional Ledger &amp; Outcomes
          </h2>
          <p className="text-[12px] font-normal text-slate-700">
            Real-Time Forward Test
          </p>
        </div>
        {aggregate ? (
          <div className="flex flex-wrap items-center gap-3">
            <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
              <p className="text-[10px] font-medium uppercase tracking-wider text-slate-700">
                Total Resolved
              </p>
              <p className="font-mono text-[15px] font-bold text-slate-900 tabular-nums">
                {aggregate.totalResolved}
              </p>
            </div>
            <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
              <p className="text-[10px] font-medium uppercase tracking-wider text-slate-700">
                Net Win Rate
              </p>
              <p
                className={`font-mono text-[15px] font-bold tabular-nums ${
                  (aggregate.netWinRatePct ?? 0) >= 0.5
                    ? "text-emerald-700"
                    : "text-rose-700"
                }`}
              >
                {fmtPct(aggregate.netWinRatePct, 1, false)}
              </p>
            </div>
            <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
              <p className="text-[10px] font-medium uppercase tracking-wider text-slate-700">
                Avg R-Multiple
              </p>
              <p
                className={`font-mono text-[15px] font-bold tabular-nums ${
                  (aggregate.averageRMultiple ?? 0) >= 0
                    ? "text-emerald-700"
                    : "text-rose-700"
                }`}
              >
                {fmtPf(aggregate.averageRMultiple)}
                R
              </p>
            </div>
          </div>
        ) : (
          <p className="text-[12px] font-medium text-slate-700">
            Tracking live forward-test setups. Outcomes resolve automatically
            at session EOD.
          </p>
        )}
      </div>

      {rows.length === 0 ? (
        <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 py-8 text-center">
          <p className="text-[13px] font-medium text-slate-700">
            Tracking live forward-test setups. Outcomes resolve automatically
            at session EOD.
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-xs">
            <thead>
              <tr className="border-b-2 border-slate-300 bg-slate-100 text-xs font-bold uppercase tracking-wider text-slate-800">
                <th className="px-3 py-2 text-left font-medium">Date &amp; Horizon</th>
                <th className="px-3 py-2 text-left font-medium">Ticker</th>
                <th className="px-3 py-2 text-right font-medium">Entry</th>
                <th className="px-3 py-2 text-right font-medium">Stop / TP1</th>
                <th className="px-3 py-2 text-right font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const badge = STATUS_BADGE[row.status];
                const isResolved = row.status !== "OPEN";
                return (
                  <tr
                    key={`${row.verdictDate}-${row.horizon}-${row.ticker}`}
                    className="border-b border-slate-200 transition-colors hover:bg-sky-50/50"
                  >
                    <td className="px-3 py-2 text-left font-mono text-[12px] font-bold text-slate-900">
                      <div className="leading-tight">
                        <p className="font-bold">{row.verdictDate}</p>
                        <p className="font-normal text-slate-700">
                          {HorizonLabel(row.horizon)}
                        </p>
                      </div>
                    </td>
                    <td className="px-3 py-2 text-left">
                      <TickerLink ticker={row.ticker} />
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-[12px] font-bold text-slate-900">
                      {row.entryPrice == null ? "—" : `PKR ${row.entryPrice.toFixed(2)}`}
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-[12px] font-bold text-slate-900">
                      <div className="leading-tight">
                        <p className="text-rose-700">
                          {row.stopLoss == null ? "—" : `PKR ${row.stopLoss.toFixed(2)}`}
                        </p>
                        <p className="text-emerald-700">
                          {row.tp1Target == null ? "—" : `PKR ${row.tp1Target.toFixed(2)}`}
                        </p>
                      </div>
                    </td>
                    <td className="px-3 py-2 text-right">
                      <div className="inline-block text-right">
                        <span
                          className={`inline-block rounded-[2px] border px-2.5 py-0.5 text-[11px] font-bold tracking-wider ${badge.cls}`}
                        >
                          {badge.label}
                        </span>
                        {isResolved && (row.pnlPct != null || row.rMultiple != null) && (
                          <p className="mt-1 text-[11px] font-mono tabular-nums text-slate-700">
                            PnL {fmtPct(row.pnlPct, 2)} · {fmtPf(row.rMultiple)}R
                          </p>
                        )}
                        {row.status === "OPEN" && row.barsHeld != null && (
                          <p className="mt-1 text-[11px] font-mono tabular-nums text-slate-700">
                            Bars held: {row.barsHeld}
                          </p>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
