import fs from "node:fs";
import path from "node:path";

/** Today's actionable PSX desk: what to buy, what to stay out of. */
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
      // try the next candidate
    }
  }
  return null;
}

const money = (value: number | null | undefined) =>
  value === null || value === undefined || Number.isNaN(value)
    ? "—"
    : value.toLocaleString("en-PK", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const pct = (value: number | null | undefined, digits = 2) =>
  value === null || value === undefined || Number.isNaN(value) ? "—" : value.toFixed(digits);

const RS_WATCH_FLOOR = 8.0; // only elite relative strength qualifies when no sweep fired
const CARRY_FLOOR = 18.0; // % annualised carry that beats the 11% policy rate by enough

function Tag({children}: {children: React.ReactNode}) {
  return (
    <span className="rounded border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[10px] font-semibold text-slate-600">
      {children}
    </span>
  );
}

function Stat({label, value, tone}: {label: string; value: string; tone?: string}) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white px-4 py-3 shadow-sm">
      <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">{label}</div>
      <div className={`mt-0.5 font-mono text-base font-bold ${tone ?? "text-slate-900"}`}>{value}</div>
    </div>
  );
}

export default function DailyDeskPage() {
  const latest = readLatest();
  const sweeps = latest?.liquiditySweeps ?? [];
  const traps = (latest?.carryTraps ?? []).filter(
    (trap) => (trap.annualizedCarryPct ?? 0) > CARRY_FLOOR && (trap.mansfieldRs ?? 0) < 0,
  );
  const watch = sweeps.length
    ? []
    : (latest?.rsLeaders ?? []).filter((lead) => (lead.mansfieldRs ?? 0) >= RS_WATCH_FLOOR);
  const sbpRate = latest?.sbpRate ?? 11;
  const kse = latest?.kse100;
  const kseUp = (kse?.changePct ?? 0) >= 0;

  return (
    <div className="space-y-5">
      {/* Session strip */}
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-slate-900">Today&apos;s Trade Desk</h1>
          <p className="text-xs text-slate-500">
            Buys and avoids are computed at the close — no settings, no charts, just the call.
          </p>
        </div>
        <div className="grid grid-cols-3 gap-2 sm:gap-3">
          <Stat label="Session" value={latest?.sessionDate ?? "—"} />
          <Stat
            label="KSE-100"
            value={`${money(kse?.close)}  ${(kse?.changePct ?? 0) >= 0 ? "+" : ""}${pct(kse?.changePct)}%`}
            tone={kseUp ? "text-emerald-700" : "text-rose-700"}
          />
          <Stat label="SBP Policy Rate" value={`${pct(sbpRate, 1)}%`} tone="text-slate-900" />
        </div>
      </div>

      {!latest && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
          No signal file yet — run <code className="font-mono">python backend/scripts/process_daily_tape.py</code>.
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {/* LEFT — BUY / ACCUMULATE */}
        <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <header className="border-b border-slate-200 pb-3">
            <div className="flex items-center justify-between gap-2">
              <h2 className="text-base font-bold text-slate-900">Buy / Accumulate Setups</h2>
              <span className="rounded border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-[10px] font-bold text-emerald-700">
                SPOT MARKET
              </span>
            </div>
            <p className="mt-0.5 text-[11px] text-slate-500">
              Enter near the volume point of control, hard stop inside 7%, target +12%.
            </p>
          </header>

          {sweeps.length === 0 && watch.length === 0 ? (
            <p className="px-1 py-6 text-center text-xs text-slate-400">
              No qualified long setup this session — stay in cash.
            </p>
          ) : (
            <ul className="divide-y divide-slate-200">
              {sweeps.map((item) => {
                const stop = Math.max(item.stopLoss, item.close * 0.93);
                return (
                  <li key={item.ticker} className="py-3">
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-sm font-bold text-slate-900">{item.ticker}</span>
                        <span className="rounded border border-blue-200 bg-blue-50 px-1.5 py-0.5 text-[10px] font-bold text-blue-700">
                          LIQUIDITY SWEEP BUY
                        </span>
                      </div>
                      <span className="font-mono text-sm font-bold text-slate-800">{money(item.close)}</span>
                    </div>

                    <div className="mt-2 grid grid-cols-3 gap-2 text-[11px]">
                      <div className="rounded border border-slate-200 bg-slate-50 px-2 py-1">
                        <div className="text-[9px] uppercase tracking-wide text-slate-400">Entry Zone</div>
                        <div className="font-mono font-bold text-slate-800">{money(item.poc)}</div>
                      </div>
                      <div className="rounded border border-rose-200 bg-rose-50 px-2 py-1">
                        <div className="text-[9px] uppercase tracking-wide text-rose-500">Hard Stop</div>
                        <div className="font-mono font-bold text-rose-700">{money(stop)}</div>
                      </div>
                      <div className="rounded border border-emerald-200 bg-emerald-50 px-2 py-1">
                        <div className="text-[9px] uppercase tracking-wide text-emerald-600">Target +12%</div>
                        <div className="font-mono font-bold text-emerald-700">{money(item.target)}</div>
                      </div>
                    </div>

                    <div className="mt-2 flex flex-wrap gap-1.5">
                      <Tag>POC {pct(item.poc)}</Tag>
                      <Tag>Vol Z {pct(item.volZScore)}</Tag>
                      <Tag>Mansfield RS +{pct(item.mansfieldRs)}%</Tag>
                      <Tag>{item.directorFootprint ? "Director footprint" : "No director filing"}</Tag>
                    </div>
                  </li>
                );
              })}

              {watch.map((item) => {
                const entry = item.poc || item.close;
                return (
                  <li key={item.ticker} className="py-3">
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-sm font-bold text-slate-900">{item.ticker}</span>
                        <span className="rounded border border-amber-200 bg-amber-50 px-1.5 py-0.5 text-[10px] font-bold text-amber-700">
                          RS ACCUMULATION WATCH
                        </span>
                      </div>
                      <span className="font-mono text-sm font-bold text-slate-800">{money(item.close)}</span>
                    </div>

                    <div className="mt-2 grid grid-cols-3 gap-2 text-[11px]">
                      <div className="rounded border border-slate-200 bg-slate-50 px-2 py-1">
                        <div className="text-[9px] uppercase tracking-wide text-slate-400">Entry Zone</div>
                        <div className="font-mono font-bold text-slate-800">{money(entry)}</div>
                      </div>
                      <div className="rounded border border-rose-200 bg-rose-50 px-2 py-1">
                        <div className="text-[9px] uppercase tracking-wide text-rose-500">Hard Stop</div>
                        <div className="font-mono font-bold text-rose-700">{money(item.close * 0.93)}</div>
                      </div>
                      <div className="rounded border border-emerald-200 bg-emerald-50 px-2 py-1">
                        <div className="text-[9px] uppercase tracking-wide text-emerald-600">Target +12%</div>
                        <div className="font-mono font-bold text-emerald-700">{money(item.close * 1.12)}</div>
                      </div>
                    </div>

                    <div className="mt-2 flex flex-wrap gap-1.5">
                      <Tag>POC {pct(item.poc)}</Tag>
                      <Tag>Vol Z {pct(item.volZScore)}</Tag>
                      <Tag>Mansfield RS +{pct(item.mansfieldRs)}%</Tag>
                    </div>
                    <p className="mt-2 text-[10px] text-slate-400">
                      No sweep fired today, so this is accumulation only — trim size, no chasing.
                    </p>
                  </li>
                );
              })}
            </ul>
          )}
        </section>

        {/* RIGHT — DO NOT BUY / SHORT TRAPS */}
        <section className="rounded-xl border border-rose-200 bg-white p-5 shadow-sm">
          <header className="border-b border-slate-200 pb-3">
            <div className="flex items-center justify-between gap-2">
              <h2 className="text-base font-bold text-slate-900">Do Not Buy / DFX Short Traps</h2>
              <span className="rounded border border-rose-200 bg-rose-50 px-2 py-0.5 text-[10px] font-bold text-rose-700">
                FUTURES ONLY
              </span>
            </div>
            <p className="mt-0.5 text-[11px] text-slate-500">
              Carry above {CARRY_FLOOR.toFixed(0)}% against the {pct(sbpRate, 1)}% SBP rate, with broken relative
              strength — never buy spot here.
            </p>
          </header>

          {traps.length === 0 ? (
            <p className="px-1 py-6 text-center text-xs text-slate-400">
              No contract is carrying hard enough to flag today.
            </p>
          ) : (
            <ul className="divide-y divide-slate-200">
              {traps.map((item) => {
                const spread = item.annualizedCarryPct - sbpRate;
                return (
                  <li key={item.ticker} className="py-3">
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-sm font-bold text-slate-900">{item.ticker}</span>
                        <span className="rounded border border-rose-200 bg-rose-50 px-1.5 py-0.5 text-[10px] font-bold text-rose-700">
                          AVOID SPOT
                        </span>
                      </div>
                      <span className="font-mono text-sm font-bold text-rose-700">
                        {pct(item.annualizedCarryPct)}%
                      </span>
                    </div>

                    <div className="mt-2 grid grid-cols-2 gap-2 text-[11px]">
                      <div className="rounded border border-slate-200 bg-slate-50 px-2 py-1">
                        <div className="text-[9px] uppercase tracking-wide text-slate-400">Spot</div>
                        <div className="font-mono font-bold text-slate-800">{money(item.spotClose)}</div>
                      </div>
                      <div className="rounded border border-slate-200 bg-slate-50 px-2 py-1">
                        <div className="text-[9px] uppercase tracking-wide text-slate-400">Futures</div>
                        <div className="font-mono font-bold text-slate-800">{money(item.futClose)}</div>
                      </div>
                    </div>

                    <div className="mt-2 flex flex-wrap items-center gap-1.5">
                      <Tag>Carry +{pct(spread)}% over SBP {pct(sbpRate, 1)}%</Tag>
                      <Tag>Mansfield RS {pct(item.mansfieldRs)}%</Tag>
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
