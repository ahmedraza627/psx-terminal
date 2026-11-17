import fs from "node:fs";
import path from "node:path";

/** PSX Institutional Signal Desk — reads public/data/latest.json at request time. */

export const dynamic = "force-dynamic";

type Sweep = {
  ticker: string;
  close: number;
  poc: number;
  volZScore: number;
  mansfieldRs: number;
  stopLoss: number;
  target: number;
  directorFootprint: boolean;
};

type Leader = {
  ticker: string;
  close: number;
  mansfieldRs: number;
  volZScore: number;
  poc: number;
};

type Trap = {
  ticker: string;
  spotClose: number;
  futClose: number;
  annualizedCarryPct: number;
  mansfieldRs: number;
};

type Latest = {
  sessionDate: string;
  kse100?: { close: number | null; changePct: number | null };
  sbpRate?: number;
  liquiditySweeps?: Sweep[];
  rsLeaders?: Leader[];
  carryTraps?: Trap[];
};

function readLatest(): Latest | null {
  const candidates = [
    path.join(process.cwd(), "public", "data", "latest.json"),
    path.join(process.cwd(), "frontend", "public", "data", "latest.json"),
  ];
  for (const file of candidates) {
    try {
      return JSON.parse(fs.readFileSync(file, "utf-8")) as Latest;
    } catch {
      // try the next location
    }
  }
  return null;
}

const num = (value: number | null | undefined, digits = 2) =>
  value === null || value === undefined || Number.isNaN(value) ? "—" : value.toFixed(digits);

const pkr = (value: number | null | undefined) =>
  value === null || value === undefined ? "—" : value.toLocaleString("en-PK", { maximumFractionDigits: 2 });

function Empty({ message }: { message: string }) {
  return <div className="px-4 py-6 text-center text-xs text-slate-400">{message}</div>;
}

export default function SignalDeskPage() {
  const latest = readLatest();
  const sweeps = latest?.liquiditySweeps ?? [];
  const leaders = latest?.rsLeaders ?? [];
  const traps = latest?.carryTraps ?? [];
  const sbpRate = latest?.sbpRate ?? 11;
  const kse = latest?.kse100;
  const kseUp = (kse?.changePct ?? 0) >= 0;

  return (
    <div className="space-y-6">
      <div className="flex flex-col justify-between gap-3 md:flex-row md:items-center">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-slate-900">
            PSX Institutional Signal Desk
          </h1>
          <p className="text-xs text-slate-500">
            Session {latest?.sessionDate ?? "unavailable"} · Liquid universe: close ≥ PKR 12,
            turnover ≥ PKR 20M
          </p>
        </div>
        <div className="flex items-center gap-3">
          <div className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-right shadow-sm">
            <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
              KSE-100
            </div>
            <div className="font-mono text-sm font-bold text-slate-800">{pkr(kse?.close)}</div>
          </div>
          <div
            className={`rounded-lg border px-3 py-1.5 font-mono text-sm font-bold shadow-sm ${
              kseUp
                ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                : "border-rose-200 bg-rose-50 text-rose-700"
            }`}
          >
            {(kse?.changePct ?? 0) >= 0 ? "+" : ""}
            {num(kse?.changePct)}%
          </div>
        </div>
      </div>

      {!latest && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
          No latest.json found. Run <code className="font-mono">python backend/scripts/process_daily_tape.py</code>{" "}
          to generate the signal file.
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <section className="rounded-xl border border-blue-200 bg-blue-50/30 p-5 shadow-sm">
          <header className="border-b border-blue-100 pb-3">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-blue-700">
              Liquidity Sweep Longs
            </span>
            <h2 className="text-base font-bold text-blue-900">Stop-hunt reclaim above POC</h2>
            <p className="text-[11px] text-blue-700/70">
              Low sweeps prior 3-session low, close reclaims POC, Vol Z ≥ 1.5
            </p>
          </header>
          {sweeps.length === 0 ? (
            <Empty message="No sweep reclaims passed the filter this session." />
          ) : (
            <ul className="divide-y divide-blue-100">
              {sweeps.map((item) => (
                <li key={item.ticker} className="py-3">
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-sm font-bold text-slate-900">{item.ticker}</span>
                        <span
                          className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${
                            item.directorFootprint
                              ? "border border-violet-200 bg-violet-50 text-violet-700"
                              : "border border-slate-200 bg-slate-50 text-slate-400"
                          }`}
                        >
                          {item.directorFootprint ? "DIRECTOR" : "NO FILING"}
                        </span>
                      </div>
                      <p className="mt-0.5 text-[11px] text-slate-500">
                        POC {num(item.poc)} · Vol Z {num(item.volZScore)} · Mansfield RS{" "}
                        <span className="font-semibold text-emerald-700">+{num(item.mansfieldRs)}%</span>
                      </p>
                    </div>
                    <div className="text-right">
                      <div className="font-mono text-sm font-bold text-slate-800">{num(item.close)}</div>
                      <div className="text-[10px] uppercase tracking-wide text-slate-400">close</div>
                    </div>
                  </div>
                  <div className="mt-2 grid grid-cols-2 gap-2 text-[11px]">
                    <div className="rounded bg-white px-2 py-1 shadow-sm">
                      <span className="text-rose-600 font-semibold">7% stop</span>
                      <span className="ml-1 font-mono text-slate-700">{num(item.stopLoss)}</span>
                    </div>
                    <div className="rounded bg-white px-2 py-1 shadow-sm">
                      <span className="text-emerald-600 font-semibold">target</span>
                      <span className="ml-1 font-mono text-slate-700">{num(item.target)}</span>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="rounded-xl border border-emerald-200 bg-emerald-50/30 p-5 shadow-sm">
          <header className="border-b border-emerald-100 pb-3">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-emerald-700">
              Institutional RS Leaders
            </span>
            <h2 className="text-base font-bold text-emerald-900">Relative strength vs KSE-100</h2>
            <p className="text-[11px] text-emerald-700/70">
              Positive Mansfield RS with Vol Z ≥ 1.0 — accumulation footprints
            </p>
          </header>
          {leaders.length === 0 ? (
            <Empty message="No stock is outperforming the index on expanding volume." />
          ) : (
            <ul className="divide-y divide-emerald-100">
              {leaders.map((item) => {
                const width = Math.min(Math.max(item.mansfieldRs, 0), 40);
                return (
                  <li key={item.ticker} className="py-3">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-mono text-sm font-bold text-slate-900">{item.ticker}</span>
                      <span className="font-mono text-xs text-slate-500">{num(item.close)}</span>
                    </div>
                    <div className="mt-1.5 flex items-center gap-2">
                      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-emerald-100">
                        <div
                          className="h-full rounded-full bg-emerald-500"
                          style={{ width: `${(width / 40) * 100}%` }}
                        />
                      </div>
                      <span className="w-16 text-right font-mono text-xs font-semibold text-emerald-700">
                        +{num(item.mansfieldRs)}%
                      </span>
                    </div>
                    <p className="mt-1 text-[11px] text-slate-500">
                      Vol Z {num(item.volZScore)} · POC {num(item.poc)}
                    </p>
                  </li>
                );
              })}
            </ul>
          )}
        </section>

        <section className="rounded-xl border border-rose-200 bg-rose-50/30 p-5 shadow-sm">
          <header className="border-b border-rose-100 pb-3">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-rose-700">
              DFX Cost-of-Carry Traps
            </span>
            <h2 className="text-base font-bold text-rose-900">Spot avoid / futures short only</h2>
            <p className="text-[11px] text-rose-700/70">
              Annualised carry above 18% vs the {num(sbpRate, 1)}% SBP policy rate
            </p>
          </header>
          {traps.length === 0 ? (
            <Empty message="No futures contract is carrying above the overheat threshold." />
          ) : (
            <ul className="divide-y divide-rose-100">
              {traps.map((item) => {
                const spread = (item.annualizedCarryPct ?? 0) - sbpRate;
                return (
                  <li key={item.ticker} className="py-3">
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <span className="font-mono text-sm font-bold text-slate-900">{item.ticker}</span>
                        <p className="mt-0.5 text-[11px] text-slate-500">
                          spot {num(item.spotClose)} · fut {num(item.futClose)} · RS{" "}
                          {num(item.mansfieldRs)}%
                        </p>
                      </div>
                      <div className="text-right">
                        <div className="font-mono text-sm font-bold text-rose-700">
                          {num(item.annualizedCarryPct)}%
                        </div>
                        <div className="text-[10px] uppercase tracking-wide text-slate-400">
                          annualised
                        </div>
                      </div>
                    </div>
                    <div className="mt-2 flex items-center justify-between gap-2 rounded bg-white px-2 py-1 text-[11px] shadow-sm">
                      <span className="font-semibold text-rose-600">
                        +{num(spread)}% over SBP {num(sbpRate, 1)}%
                      </span>
                      <span className="rounded bg-rose-600 px-1.5 py-0.5 text-[10px] font-bold text-white">
                        SHORT FUT ONLY
                      </span>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}
