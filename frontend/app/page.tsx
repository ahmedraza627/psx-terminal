import fs from "node:fs";
import path from "node:path";

/** Six-layer pre-breakout desk: posture, top setups, distribution alerts. */
export const dynamic = "force-dynamic";

type Seasonality = {
  status: string;
  coverage?: "TICKER" | "SECTOR" | null;
  month: string | null;
  tailwind: boolean;
  winRate60Pct: number | null;
  avgForward60Pct: number | null;
  rangePositionPct?: number | null;
};

type ConfluenceLayer = { key: string; label: string; met: boolean };

type TimeStop = {
  limit: number;
  sessionsHeld: number;
  sessionsRemaining: number;
  deadCapital: boolean;
  deadline: string;
  note: string;
};

type SetupMetrics = {
  institutionalNetPkr?: number;
  flowSessions?: number;
  flowStreak?: number;
  ret20dPct?: number | null;
  volumeRatio20?: number | null;
  volumeRatio50?: number | null;
  dryUpRatio?: number | null;
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
  ignition: string;
  confluence: { score: number; max: number; layers: ConfluenceLayer[] };
  entryZone: { low: number; high: number };
  invalidation: string;
  invalidationPrice: number;
  timeStop: TimeStop;
  floatTurnover: { pct: number | null; warning: boolean; freeFloatShares: number | null };
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
  floatTurnoverPct?: number;
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
  macroBreadthPct?: number | null;
  macroBreadthFloorPct?: number;
  minConfluence?: number;
  timeStopSessions?: number;
  dryUpBandPct?: number[];
  pocketPivotMultiple?: number;
  freeFloatDistributionPct?: number;
  carryTrapsSuppressed?: number;
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

const shortDate = (iso: string | null | undefined) => {
  if (!iso) return "—";
  const parsed = new Date(iso);
  return Number.isNaN(parsed.getTime())
    ? iso
    : parsed.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
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
  "INSIDER / FORM 31-32": "border-indigo-500/40 bg-indigo-500/10 text-indigo-300",
  "LOW-FLOAT SQUEEZE": "border-amber-500/40 bg-amber-500/10 text-amber-300",
  "LoR TRAP": "border-fuchsia-500/40 bg-fuchsia-500/10 text-fuchsia-300",
  "SEASONAL ALIGNED": "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
  "POCKET PIVOT": "border-cyan-500/40 bg-cyan-500/10 text-cyan-300",
  "VOLUME DRY-UP": "border-teal-500/40 bg-teal-500/10 text-teal-300",
};

const SEASONAL_TONE: Record<string, string> = {
  "ACCUMULATION WINDOW ACTIVE": "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
  "EXTENDED / WAIT PULLBACK": "border-amber-500/40 bg-amber-500/10 text-amber-300",
  WATCH: "border-sky-500/40 bg-sky-500/10 text-sky-300",
};

const ALERT_TONE: Record<string, string> = {
  "FREE-FLOAT DISTRIBUTION": "border-rose-500/40 bg-rose-500/10 text-rose-300",
  "INSTITUTIONAL DISTRIBUTION": "border-orange-500/40 bg-orange-500/10 text-orange-300",
  "RETAIL-CHASED EXTENSION": "border-amber-500/40 bg-amber-500/10 text-amber-300",
  "LoR PREMIUM TRAP": "border-fuchsia-500/40 bg-fuchsia-500/10 text-fuchsia-300",
  "DEAD-CAPITAL TIME-STOP": "border-slate-500/40 bg-slate-500/10 text-slate-300",
  "STALE / NON-TRADED": "border-slate-600/40 bg-slate-600/10 text-slate-300",
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

function ConfluenceBar({ confluence }: { confluence: InstitutionalSetup["confluence"] }) {
  const ratio = confluence.max ? confluence.score / confluence.max : 0;
  const tone =
    ratio >= 5 / 6 ? "text-emerald-300" : ratio >= 3 / 6 ? "text-amber-300" : "text-slate-300";
  return (
    <div className="flex items-center gap-2">
      <span className={`font-mono text-[11px] font-bold tabular-nums ${tone}`}>
        {confluence.score}/{confluence.max}
      </span>
      <div className="flex gap-1">
        {confluence.layers.map((layer) => (
          <span
            key={layer.key}
            title={`${layer.label}: ${layer.met ? "met" : "missing"}`}
            className={`h-1.5 w-4 rounded-sm ${layer.met ? "bg-emerald-400/80" : "bg-slate-700"}`}
          />
        ))}
      </div>
      <span className="text-[9px] font-semibold uppercase tracking-[0.12em] text-slate-500">confluence</span>
    </div>
  );
}

function SeasonalityBadge({ seasonality }: { seasonality: Seasonality }) {
  const tone = SEASONAL_TONE[seasonality.status] ?? "border-slate-800 bg-slate-900/40 text-slate-400";
  return (
    <div className={`rounded-lg border px-2.5 py-2 ${tone}`}>
      <div className="text-[9px] font-bold uppercase tracking-[0.12em] opacity-80">
        Seasonality · {seasonality.month ?? "—"}
      </div>
      <div className="mt-0.5 text-[10px] font-semibold leading-snug">
        {seasonality.status}
        {seasonality.coverage === "SECTOR" ? " · sector" : ""}
      </div>
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
  const breadth = desk?.macroBreadthPct ?? null;
  const breadthOk = breadth !== null && breadth >= (desk?.macroBreadthFloorPct ?? 40);

  return (
    <div className="space-y-5">
      <header className="min-w-0">
        <span className="font-mono text-[10px] font-bold uppercase tracking-[0.18em] text-emerald-400/80">
          PSX · six-layer pre-breakout desk
        </span>
        <h1 className="mt-1 text-xl font-bold tracking-tight text-slate-50 sm:text-2xl">Today&apos;s Trade Desk</h1>
      </header>

      {!latest && (
        <div className="rounded-2xl border border-amber-500/30 bg-amber-500/10 p-4 text-sm text-amber-200">
          No signal file yet — run <code className="font-mono">python backend/scripts/process_daily_tape.py</code>.
        </div>
      )}

      {/* Layer 1 + macro posture */}
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
            At a {pct(sbpRate, 2)}% policy rate the desk only pays up when the six layers line up: a supportive
            macro tape, a current-month seasonal window, institutional absorption or an insider filing, a live
            corporate catalyst, volume dry-up into a pocket pivot, and a clean exit with no free-float distribution.
          </p>

          {desk ? (
            <div className="mt-2 flex flex-wrap gap-1.5">
              <Tag>
                breadth {breadth === null ? "—" : `${pct(breadth, 0)}%`} above 50d
                {breadthOk ? " ✓" : " ✗"}
              </Tag>
              <Tag>NCCPL flows {desk.flowSession ?? "not stored"}</Tag>
              <Tag>{desk.sectorsTracked} sectors · {desk.flowSessions} sessions</Tag>
              <Tag>Institutions {pkrM(desk.institutionalNetPkr)}</Tag>
              <Tag>{desk.catalystEvents} PUCARS / insider filings</Tag>
              <Tag>dry-up {desk.dryUpBandPct?.join("–") ?? "20–30"}% · pivot {desk.pocketPivotMultiple ?? 2}x</Tag>
              <Tag>time-stop {desk.timeStopSessions ?? 30} sessions</Tag>
              {desk.carryTrapsSuppressed ? (
                <Tag>{desk.carryTrapsSuppressed} carry trap{desk.carryTrapsSuppressed === 1 ? "" : "s"} suppressed · setup conflict</Tag>
              ) : null}
            </div>
          ) : null}
        </div>
      </section>

      {/* Top 5 institutional setups */}
      <section className="overflow-hidden rounded-2xl border border-slate-800/80 bg-slate-900/40">
        <SectionHeading
          title="Top 5 Institutional Setups"
          count={`${setups.length} / 5`}
          tone="border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
        />
        {setups.length === 0 ? (
          <p className="px-4 py-8 text-center text-xs text-slate-500 sm:px-5">
            No name clears three of the six framework layers this session — no flow, catalyst, dry-up or seasonal
            edge is stored for the tape.
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
                  <div className="flex flex-wrap items-center gap-3">
                    <ConfluenceBar confluence={setup.confluence} />
                    <span className="font-mono text-sm font-bold tabular-nums text-slate-200">
                      PKR {money(setup.close)}
                    </span>
                  </div>
                </div>

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
                        Ignition trigger
                      </div>
                      <p className="mt-0.5 text-[11px] leading-relaxed text-cyan-200/90">{setup.ignition}</p>
                    </div>
                    <div>
                      <div className="text-[9px] font-bold uppercase tracking-[0.14em] text-slate-500">
                        Entry zone
                      </div>
                      <div className="mt-0.5 flex flex-wrap items-center gap-1.5">
                        <span className="font-mono text-[11px] font-bold tabular-nums text-emerald-300">
                          PKR {money(setup.entryZone.low)} – {money(setup.entryZone.high)}
                        </span>
                        {setup.metrics.volumeRatio50 !== null && setup.metrics.volumeRatio50 !== undefined && (
                          <Tag>vol {pct(setup.metrics.volumeRatio50)}x 50d</Tag>
                        )}
                        {setup.metrics.dryUpRatio !== null && setup.metrics.dryUpRatio !== undefined && (
                          <Tag>dry-up {pct(setup.metrics.dryUpRatio * 100, 0)}%</Tag>
                        )}
                        {setup.metrics.freeFloatPct !== null && setup.metrics.freeFloatPct !== undefined && (
                          <Tag>float {pct(setup.metrics.freeFloatPct, 1)}%</Tag>
                        )}
                        {setup.floatTurnover.pct !== null && (
                          <Tag>turnover {pct(setup.floatTurnover.pct)}%</Tag>
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

                  <div className="space-y-2">
                    <SeasonalityBadge seasonality={setup.seasonality} />
                    <div className="rounded-lg border border-slate-700/70 bg-slate-950/40 px-2.5 py-2">
                      <div className="text-[9px] font-bold uppercase tracking-[0.12em] text-slate-500">
                        Time-stop · {setup.timeStop.limit} sessions
                      </div>
                      <div className="mt-0.5 font-mono text-[10px] tabular-nums text-slate-300">
                        exit by {shortDate(setup.timeStop.deadline)} if not working
                      </div>
                      <div className="mt-0.5 text-[10px] leading-snug text-slate-500">{setup.timeStop.note}</div>
                    </div>
                  </div>
                </div>
              </article>
            ))}
          </div>
        )}
      </section>

      {/* Avoid / distribution alerts */}
      <section className="overflow-hidden rounded-2xl border border-rose-500/30 bg-slate-900/40">
        <SectionHeading
          title="Avoid / Distribution Alerts"
          count={`${alerts.length} / 5`}
          tone="border-rose-500/30 bg-rose-500/10 text-rose-300"
        />
        {alerts.length === 0 ? (
          <p className="px-4 py-8 text-center text-xs text-slate-500 sm:px-5">
            No distribution, free-float turnover, dead-capital or stale-tape flag is stored for this session.
          </p>
        ) : (
          <div className="divide-y divide-slate-800/70">
            {alerts.map((alert) => (
              <article key={`${alert.alert}-${alert.ticker}`} className="px-4 py-3.5 sm:px-5">
                <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
                  <div className="flex min-w-0 flex-wrap items-center gap-2">
                    <span className="font-mono text-sm font-bold text-slate-50">{alert.ticker}</span>
                    <span className="font-mono text-[10px] text-slate-500">{alert.sector}</span>
                    <span
                      className={`rounded border px-1.5 py-0.5 font-mono text-[9px] font-bold ${
                        ALERT_TONE[alert.alert] ?? "border-rose-500/40 bg-rose-500/10 text-rose-300"
                      }`}
                    >
                      {alert.alert}
                    </span>
                  </div>
                  <span className="font-mono text-sm font-bold tabular-nums text-rose-300">
                    {alert.floatTurnoverPct !== undefined && alert.floatTurnoverPct !== null
                      ? `${pct(alert.floatTurnoverPct, 1)}% float`
                      : pkrM(alert.instNetPkr)}
                  </span>
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
          Alerts fire on stored data only: three or more straight sessions of insurance/mutual-fund net selling, a
          single session turning over 15%+ of the free float, retail chasing an extended tape, a rights entitlement
          priced above TERP, a 30-session dead-capital clock, or a name that printed no volume.
        </p>
      </section>
    </div>
  );
}
