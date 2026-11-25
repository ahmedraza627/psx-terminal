import fs from "node:fs";
import path from "node:path";

/** Institutional event & flow desk: posture, top setups, distribution alerts. */
export const dynamic = "force-dynamic";

type Seasonality = {
  status: string;
  month: string | null;
  tailwind: boolean;
  winRate60Pct: number | null;
  avgForward60Pct: number | null;
  rangePositionPct?: number | null;
};

type SetupMetrics = {
  institutionalNetPkr?: number;
  flowSessions?: number;
  flowStreak?: number;
  ret20dPct?: number | null;
  volumeRatio20?: number | null;
  freeFloatPct?: number | null;
  peRatio?: number | null;
  catalyst?: string | null;
};

type InstitutionalSetup = {
  ticker: string;
  sector: string;
  strategy: string;
  tags: string[];
  close: number;
  trigger: string;
  entryZone: { low: number; high: number };
  invalidation: string;
  invalidationPrice: number;
  seasonality: Seasonality;
  score: number;
  metrics: SetupMetrics;
};

type DistributionAlert = {
  ticker: string;
  sector: string;
  alert: string;
  detail: string;
  sellStreak: number;
  instNetPkr: number;
  ret20dPct: number | null;
  seasonality: Seasonality;
  score: number;
};

type DeskSummary = {
  flowSession: string | null;
  flowSessions: number;
  sectorsTracked: number;
  institutionalNetPkr: number;
  catalystWindowDays: number;
  catalystEvents: number;
  rightsTracked: number;
  seasonalityMonth: string | null;
};

type AlphaBrief = {
  sessionDate: string;
  marketRegime: { regime: string; posture: string };
};

type Latest = {
  sessionDate: string;
  kse100?: { close: number | null; changePct: number | null };
  sbpRate?: number;
  institutionalSetups?: InstitutionalSetup[];
  distributionAlerts?: DistributionAlert[];
  institutionalDesk?: DeskSummary;
};

function readJson<T>(name: string): T | null {
  const candidates = [
    path.join(process.cwd(), "public", "data", name),
    path.join(process.cwd(), "frontend", "public", "data", name),
  ];
  for (const file of candidates) {
    try {
      return JSON.parse(fs.readFileSync(file, "utf-8")) as T;
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

const signedPct = (value: number | null | undefined, digits = 1) =>
  value === null || value === undefined || Number.isNaN(value)
    ? "—"
    : `${value >= 0 ? "+" : ""}${value.toFixed(digits)}%`;

const pkrM = (value: number | null | undefined) => {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const millions = value / 1_000_000;
  return `PKR ${millions >= 0 ? "+" : "−"}${Math.abs(millions).toLocaleString("en-PK", {
    maximumFractionDigits: 0,
  })}M`;
};

const REGIME_TONE: Record<string, string> = {
  TRENDING: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
  CHOPPY: "border-amber-500/30 bg-amber-500/10 text-amber-300",
  STRESS: "border-rose-500/30 bg-rose-500/10 text-rose-300",
  UNKNOWN: "border-slate-800 bg-slate-900/40 text-slate-400",
};

const STRATEGY_TONE: Record<string, string> = {
  "FIPI/LIPI ABSORPTION": "border-blue-500/40 bg-blue-500/10 text-blue-300",
  "PUCARS CATALYST": "border-violet-500/40 bg-violet-500/10 text-violet-300",
  "LOW-FLOAT SQUEEZE": "border-amber-500/40 bg-amber-500/10 text-amber-300",
  "LoR TRAP": "border-fuchsia-500/40 bg-fuchsia-500/10 text-fuchsia-300",
  "SEASONAL ALIGNED": "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
};

const SEASONAL_TONE: Record<string, string> = {
  "ACCUMULATION WINDOW ACTIVE": "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
  "EXTENDED / WAIT PULLBACK": "border-amber-500/40 bg-amber-500/10 text-amber-300",
  "WATCH": "border-sky-500/40 bg-sky-500/10 text-sky-300",
};

function Tag({ children }: { children: React.ReactNode }) {
  return (
    <span className="rounded border border-slate-700/70 bg-slate-800/50 px-1.5 py-0.5 font-mono text-[10px] font-semibold tabular-nums text-slate-400">
      {children}
    </span>
  );
}

function Metric({ label, value, hint, tone }: { label: string; value: string; hint?: string; tone?: string }) {
  return (
    <div className="rounded-xl border border-slate-800/80 bg-slate-950/40 px-4 py-3">
      <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">{label}</div>
      <div className={`mt-1 font-mono text-sm font-bold tabular-nums sm:text-base ${tone ?? "text-slate-100"}`}>
        {value}
      </div>
      {hint ? <div className="mt-0.5 text-[10px] leading-snug text-slate-500">{hint}</div> : null}
    </div>
  );
}

function SectionHeading({ title, count, tone }: { title: string; count?: string; tone?: string }) {
  return (
    <header className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-800 px-4 py-3 sm:px-5">
      <h2 className="text-base font-bold text-slate-100">{title}</h2>
      {count ? (
        <span className={`rounded border px-2 py-0.5 text-[10px] font-bold ${tone ?? "border-slate-800 bg-slate-900/40 text-slate-400"}`}>
          {count}
        </span>
      ) : null}
    </header>
  );
}

function SeasonalityBadge({ seasonality }: { seasonality: Seasonality }) {
  const tone = SEASONAL_TONE[seasonality.status] ?? "border-slate-800 bg-slate-900/40 text-slate-400";
  return (
    <div className={`rounded-lg border px-2.5 py-2 ${tone}`}>
      <div className="text-[9px] font-bold uppercase tracking-[0.12em] opacity-80">
        Seasonality · {seasonality.month ?? "—"}
      </div>
      <div className="mt-0.5 text-[10px] font-semibold leading-snug">{seasonality.status}</div>
      <div className="mt-0.5 font-mono text-[10px] tabular-nums opacity-80">
        {seasonality.winRate60Pct === null ? "60d win —" : `60d win ${pct(seasonality.winRate60Pct, 0)}%`}
        {" · "}
        {seasonality.avgForward60Pct === null ? "avg —" : `avg ${signedPct(seasonality.avgForward60Pct)}`}
      </div>
    </div>
  );
}

export default function DailyDeskPage() {
  const latest = readJson<Latest>("latest.json");
  const alpha = readJson<AlphaBrief>("daily_alpha_brief.json");
  const setups = latest?.institutionalSetups ?? [];
  const alerts = latest?.distributionAlerts ?? [];
  const desk = latest?.institutionalDesk;
  const sbpRate = latest?.sbpRate ?? 12;
  const regime = alpha?.marketRegime.regime ?? "UNKNOWN";
  const kse = latest?.kse100;
  const kseUp = (kse?.changePct ?? 0) >= 0;

  return (
    <div className="space-y-5">
      <header className="min-w-0">
        <span className="font-mono text-[10px] font-bold uppercase tracking-[0.18em] text-emerald-400/80">
          PSX · institutional event &amp; flow desk
        </span>
        <h1 className="mt-1 text-xl font-bold tracking-tight text-slate-50 sm:text-2xl">Today&apos;s Trade Desk</h1>
      </header>

      {!latest && (
        <div className="rounded-2xl border border-amber-500/30 bg-amber-500/10 p-4 text-sm text-amber-200">
          No signal file yet — run <code className="font-mono">python backend/scripts/process_daily_tape.py</code>.
        </div>
      )}

      {/* (a) MARKET & RATE POSTURE */}
      <section className="overflow-hidden rounded-2xl border border-slate-800/80 bg-slate-900/40">
        <SectionHeading title="Market &amp; Rate Posture" />
        <div className="p-4 sm:p-5">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <Metric
              label="SBP Policy Rate"
              value={`${pct(sbpRate, 2)}%`}
              hint="Ceiling 13.00% · Floor 11.00%"
              tone="text-slate-50"
            />
            <Metric label="Session" value={latest?.sessionDate ?? "—"} hint="Last processed close" />
            <Metric
              label="KSE-100"
              value={`${money(kse?.close)}  ${(kse?.changePct ?? 0) >= 0 ? "+" : ""}${pct(kse?.changePct)}%`}
              hint="Index close"
              tone={kseUp ? "text-emerald-300" : "text-rose-300"}
            />
          </div>

          <div className="mt-3 flex flex-wrap items-center gap-2">
            <span
              className={`rounded border px-2 py-0.5 text-[10px] font-bold tracking-wide ${
                REGIME_TONE[regime] ?? REGIME_TONE.UNKNOWN
              }`}
            >
              {regime}
            </span>
            <p className="text-[11px] leading-relaxed text-slate-400">
              {alpha?.marketRegime.posture ?? "Regime read unavailable for this session."}
            </p>
          </div>

          <p className="mt-2 text-[11px] leading-relaxed text-slate-400">
            At a {pct(sbpRate, 2)}% policy rate the desk only pays up for supply that institutions are actually
            absorbing, a filed corporate event with a hard exit, or a float too thin to resist demand — plus a
            current-month seasonal tailwind where the calendar supports it.
          </p>
          {desk ? (
            <div className="mt-2 flex flex-wrap gap-1.5">
              <Tag>NCCPL flows {desk.flowSession ?? "not stored"}</Tag>
              <Tag>{desk.sectorsTracked} sectors · {desk.flowSessions} sessions</Tag>
              <Tag>Institutions {pkrM(desk.institutionalNetPkr)}</Tag>
              <Tag>{desk.catalystEvents} PUCARS catalysts / {desk.catalystWindowDays}d</Tag>
              {desk.rightsTracked > 0 && <Tag>{desk.rightsTracked} rights issues with TERP</Tag>}
            </div>
          ) : null}
        </div>
      </section>

      {/* (b) TOP 5 INSTITUTIONAL SETUPS */}
      <section className="overflow-hidden rounded-2xl border border-slate-800/80 bg-slate-900/40">
        <SectionHeading
          title="Top 5 Institutional Setups"
          count={`${setups.length} / 5`}
          tone="border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
        />
        {setups.length === 0 ? (
          <p className="px-4 py-8 text-center text-xs text-slate-500 sm:px-5">
            No name clears the institutional gates this session — no flow absorption, live catalyst, low-float value
            case or rights edge is stored for the tape.
          </p>
        ) : (
          <div className="divide-y divide-slate-800/70">
            {setups.map((setup) => (
              <article key={`${setup.strategy}-${setup.ticker}`} className="px-4 py-3.5 sm:px-5">
                <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
                  <div className="flex min-w-0 flex-wrap items-center gap-2">
                    <span className="font-mono text-sm font-bold text-slate-50">{setup.ticker}</span>
                    <span className="font-mono text-[10px] text-slate-500">{setup.sector}</span>
                    <span
                      className={`rounded border px-1.5 py-0.5 font-mono text-[9px] font-bold ${
                        STRATEGY_TONE[setup.strategy] ?? "border-slate-700 bg-slate-800/60 text-slate-300"
                      }`}
                    >
                      {setup.strategy}
                    </span>
                  </div>
                  <span className="font-mono text-sm font-bold tabular-nums text-slate-200">PKR {money(setup.close)}</span>
                </div>

                {setup.tags.length > 1 ? (
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    {setup.tags.map((tag) => (
                      <span
                        key={tag}
                        className={`rounded border px-1.5 py-0.5 text-[9px] font-semibold ${
                          STRATEGY_TONE[tag] ?? "border-slate-800 bg-slate-900/40 text-slate-400"
                        }`}
                      >
                        {tag}
                      </span>
                    ))}
                  </div>
                ) : null}

                <div className="mt-2 grid grid-cols-1 gap-2 lg:grid-cols-[1fr_17rem]">
                  <div className="space-y-1.5">
                    <div>
                      <div className="text-[9px] font-bold uppercase tracking-[0.14em] text-slate-500">
                        Trigger condition
                      </div>
                      <p className="mt-0.5 text-[11px] leading-relaxed text-slate-300">{setup.trigger}</p>
                    </div>
                    <div>
                      <div className="text-[9px] font-bold uppercase tracking-[0.14em] text-slate-500">
                        Entry zone
                      </div>
                      <div className="mt-0.5 flex flex-wrap items-center gap-1.5">
                        <span className="font-mono text-[11px] font-bold tabular-nums text-emerald-300">
                          PKR {money(setup.entryZone.low)} – {money(setup.entryZone.high)}
                        </span>
                        {setup.metrics.peRatio !== null && setup.metrics.peRatio !== undefined && (
                          <Tag>P/E {pct(setup.metrics.peRatio, 1)}</Tag>
                        )}
                        {setup.metrics.freeFloatPct !== null && setup.metrics.freeFloatPct !== undefined && (
                          <Tag>float {pct(setup.metrics.freeFloatPct, 1)}%</Tag>
                        )}
                        {setup.metrics.volumeRatio20 !== null && setup.metrics.volumeRatio20 !== undefined && (
                          <Tag>vol {pct(setup.metrics.volumeRatio20)}x</Tag>
                        )}
                        {setup.metrics.ret20dPct !== null && setup.metrics.ret20dPct !== undefined && (
                          <Tag>20D {signedPct(setup.metrics.ret20dPct)}</Tag>
                        )}
                      </div>
                    </div>
                    <div>
                      <div className="text-[9px] font-bold uppercase tracking-[0.14em] text-slate-500">
                        Hard invalidation
                      </div>
                      <p className="mt-0.5 text-[11px] leading-relaxed text-rose-300/90">{setup.invalidation}</p>
                    </div>
                  </div>
                  <SeasonalityBadge seasonality={setup.seasonality} />
                </div>
              </article>
            ))}
          </div>
        )}
      </section>

      {/* (c) AVOID / DISTRIBUTION ALERTS */}
      <section className="overflow-hidden rounded-2xl border border-rose-500/30 bg-slate-900/40">
        <SectionHeading
          title="Avoid / Distribution Alerts"
          count={`${alerts.length} / 5`}
          tone="border-rose-500/30 bg-rose-500/10 text-rose-300"
        />
        {alerts.length === 0 ? (
          <p className="px-4 py-8 text-center text-xs text-slate-500 sm:px-5">
            No institutional distribution or retail-chased extension is stored for this session.
          </p>
        ) : (
          <div className="divide-y divide-slate-800/70">
            {alerts.map((alert) => (
              <article key={`${alert.alert}-${alert.ticker}`} className="px-4 py-3.5 sm:px-5">
                <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
                  <div className="flex min-w-0 flex-wrap items-center gap-2">
                    <span className="font-mono text-sm font-bold text-slate-50">{alert.ticker}</span>
                    <span className="font-mono text-[10px] text-slate-500">{alert.sector}</span>
                    <span className="rounded border border-rose-500/40 bg-rose-500/10 px-1.5 py-0.5 font-mono text-[9px] font-bold text-rose-300">
                      {alert.alert}
                    </span>
                  </div>
                  <span className="font-mono text-sm font-bold tabular-nums text-rose-300">{pkrM(alert.instNetPkr)}</span>
                </div>
                <div className="mt-2 grid grid-cols-1 gap-2 lg:grid-cols-[1fr_17rem]">
                  <div>
                    <p className="text-[11px] leading-relaxed text-slate-300">{alert.detail}</p>
                    <div className="mt-1.5 flex flex-wrap gap-1.5">
                      {alert.sellStreak > 0 && <Tag>funds sold {alert.sellStreak} sessions</Tag>}
                      {alert.ret20dPct !== null && <Tag>20D {signedPct(alert.ret20dPct)}</Tag>}
                    </div>
                  </div>
                  <SeasonalityBadge seasonality={alert.seasonality} />
                </div>
              </article>
            ))}
          </div>
        )}
        <p className="border-t border-slate-800 px-4 py-2 text-[10px] leading-snug text-slate-500 sm:px-5">
          Distribution alerts fire only on stored NCCPL sector flows: insurance and mutual funds net selling three or
          more straight sessions, retail chasing an extended tape, or a rights entitlement priced above its TERP.
        </p>
      </section>
    </div>
  );
}
