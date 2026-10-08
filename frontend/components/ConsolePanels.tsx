"use client";

import { useMemo, useState } from "react";
import TickerLink from "@/components/TickerLink";
import { fmtInt, fmtPct } from "@/components/ui/format";
import type {
  BreadthData,
  EodMove,
  FlowMatrixData,
  QuantRadarData,
  QuantSignal,
  VolumeDislocationData,
} from "@/lib/consoleQueries";

// ---------------------------------------------------------------- //
// Shared chrome: crisp hairlines, Inter typography, tabular figures. //
// ---------------------------------------------------------------- //

/**
 * Title Case for display labels derived from stored enums (signal types
 * such as "NOTABLE_VOLUME_SPIKE" -> "Notable Volume Spike"). Raw stored
 * values are never mutated elsewhere — this only shapes display text.
 */
function titleCase(value: string): string {
  return value
    .toLowerCase()
    .split(/([\s_/-]+)/)
    .map((part, i) => (i % 2 === 1 ? part : part.charAt(0).toUpperCase() + part.slice(1)))
    .join("");
}

function Panel({
  letter,
  title,
  meta,
  id,
  children,
}: {
  letter: "A" | "B" | "C" | "R" | "V";
  title: string;
  meta?: string;
  id?: string;
  children: React.ReactNode;
}) {
  return (
    <section
      id={id}
      className="flex min-w-0 flex-col overflow-hidden rounded-xl border border-hairline bg-panel shadow-sm"
    >
      <header className="flex items-center justify-between gap-2 border-b border-hairline bg-slate-50/80 px-4 py-2.5">
        <h2 className="flex items-center gap-2 text-[13px] font-semibold tracking-tight text-ink">
          <span className="inline-flex h-5 w-5 items-center justify-center rounded-md bg-blue-50 font-sans text-[10px] font-bold text-info">
            {letter}
          </span>
          {title}
        </h2>
        {meta && (
          <span className="font-sans text-[10px] tabular-nums text-ghost">
            {meta}
          </span>
        )}
      </header>
      <div className="min-w-0 flex-1">{children}</div>
    </section>
  );
}

function Kpi({
  label,
  value,
  tone = "text-ink",
  sub,
}: {
  label: string;
  value: string;
  tone?: string;
  sub?: string;
}) {
  return (
    <div className="rounded-lg border border-hairline bg-slate-50/70 px-3 py-2">
      <p className="text-[11px] font-medium text-ghost">{label}</p>
      <p className={`font-sans text-[16px] font-bold tabular-nums ${tone}`}>
        {value}
      </p>
      {sub && (
        <p className="text-[10px] font-medium tracking-wide text-ghost">
          {sub}
        </p>
      )}
    </div>
  );
}

function Th({
  children,
  right = true,
}: {
  children: React.ReactNode;
  right?: boolean;
}) {
  return (
    <th
      className={`border-b border-hairline px-2 py-1.5 font-sans text-[9px] font-semibold tracking-[0.15em] text-ghost ${
        right ? "text-right" : "text-left"
      }`}
    >
      {children}
    </th>
  );
}

function Td({
  children,
  right = true,
  bold = false,
  tone,
}: {
  children: React.ReactNode;
  right?: boolean;
  bold?: boolean;
  tone?: string;
}) {
  return (
    <td
      className={`whitespace-nowrap border-b border-hairline/60 px-2 py-1.5 font-sans text-[11px] tabular-nums ${
        right ? "text-right" : "text-left"
      } ${bold ? "font-bold" : ""} ${tone ?? "text-ink"}`}
    >
      {children}
    </td>
  );
}

/** Signed PKR millions — the console's universal money unit. */
function M({ v }: { v: number | null }) {
  if (v == null) return <Td tone="text-ghost">—</Td>;
  return (
    <Td bold tone={v > 0 ? "text-bull" : v < 0 ? "text-bear" : "text-muted"}>
      {v > 0 ? "+" : ""}
      {(v / 1e6).toFixed(1)}M
    </Td>
  );
}

function Idle({ text }: { text: string }) {
  return (
    <p className="px-3 py-6 text-center font-sans text-[11px] tracking-widest text-ghost">
      {text}
    </p>
  );
}

function RadarEmpty({ sessionDate }: { sessionDate: string | null }) {
  return (
    <Idle
      text={
        sessionDate == null
          ? "No session or signals stored"
          : `No quant signals computed for ${sessionDate}`
      }
    />
  );
}

/**
 * Panel footer: single-line factual aggregation of the data already shown
 * above it. NEVER a prediction - only reads what the panel rendered.
 */
function PanelFooter({
  text,
  tone = "text-bull/70",
}: {
  text: string;
  tone?: string;
}) {
  return (
    <p
      className={`border-t border-hairline px-3 pt-2 mt-4 font-sans text-[10px] tracking-wider ${tone}`}
    >
      {text}
    </p>
  );
}

function SignalBadge({
  signalType,
}: {
  signalType: string;
}) {
  const key = signalType.toUpperCase();
  const isBull = key.includes("ACCUMULATION") || key.includes("INSTITUTIONAL");
  const isBear =
    key.includes("TRAP") ||
    key.includes("DISTRIBUTION") ||
    key.includes("SHORT") ||
    key.includes("TRAP_SHORT");
  if (isBull) {
    return (
      <span className="rounded-[2px] bg-bull/15 px-1.5 py-px font-sans text-[9px] font-bold tracking-widest text-bull ring-1 ring-bull/40">
        {titleCase((signalType.match(/[A-Z][A-Z0-9_]+/g) || [signalType]).pop() ?? signalType)}
      </span>
    );
  }
  if (isBear) {
    return (
      <span className="rounded-[2px] bg-bear/15 px-1.5 py-px font-sans text-[9px] font-bold tracking-widest text-bear ring-1 ring-bear/40">
        {titleCase((signalType.match(/[A-Z][A-Z0-9_]+/g) || [signalType]).pop() ?? signalType)}
      </span>
    );
  }
  return (
    <span className="rounded-[2px] bg-hairline/60 px-1.5 py-px font-sans text-[9px] font-bold tracking-widest text-ghost ring-1 ring-hairline">
      {titleCase(signalType)}
    </span>
  );
}

function CatalystNode({ signal }: { signal: QuantSignal }) {
  const lines = (signal.catalystReason ?? "").split("\n");
  return (
    <div className="space-y-1">
      {lines.map((line, i) => (
        <p key={i} className="font-sans text-[10px] leading-relaxed text-ghost">
          {line}
        </p>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------- //
// PANEL A - Institutional Flow Matrix (NCCPL reality).             //
// ---------------------------------------------------------------- //

export function FlowMatrixPanel({
  data,
  id,
}: {
  data: FlowMatrixData | null;
  id?: string;
}) {
  // 30D column sort: "net" (default display order) vs "drift" (largest
  // 30D accumulation first, signed). Client-side; no server round-trip.
  const [sort30d, setSort30d] = useState<false | "desc" | "asc">(false);

  const participants = useMemo(() => {
    if (!data) return [];
    if (sort30d === false) return data.participants;
    const rows = [...data.participants].sort(
      (a, b) => (b.net30dPkr ?? -Infinity) - (a.net30dPkr ?? -Infinity),
    );
    return sort30d === "desc" ? rows : rows.reverse();
  }, [data, sort30d]);

  const cycleSort = () =>
    setSort30d((s) => (s === false ? "desc" : s === "desc" ? "asc" : false));

  // 30D institutional vs retail aggregates for the KPI row.
  const inst30d =
    data?.participants
      .filter((p) => p.participantType === "FIPI" || p.participantType === "MUTUAL FUNDS")
      .reduce((a, p) => a + (p.net30dPkr ?? 0), 0) ?? null;
  const retail30d =
    data?.participants.find((p) => p.participantType === "INDIVIDUALS")
      ?.net30dPkr ?? null;

  return (
    <Panel
      id={id}
      letter="A"
      title="Institutional Flow Matrix"
      meta={
        data
          ? `${data.asOfDate} · ${data.sessions} sessions`
          : undefined
      }
    >
      {!data ? (
        <Idle text="No NCCPL flow sessions stored" />
      ) : (
        <>
          {data.retailTrapped && (
            <div className="border-b border-bear/50 bg-bear/15 px-3 py-2">
              <p className="font-sans text-[11px] font-bold tracking-[0.18em] text-bear">
                <span className="mr-1.5 inline-block h-2 w-2 animate-pulse rounded-[2px] bg-bear align-middle" />
                Retail Trap Active: Smart Money Distributing
              </p>
              <p className="mt-0.5 font-sans text-[10px] leading-relaxed text-bear/80">
                Individuals net-buying while institutions (FIPI + Mutual
                Funds) net-sell — retail is on the other side of
                institutional distribution.
              </p>
            </div>
          )}

          <div className="grid grid-cols-2 gap-px border-b border-hairline bg-hairline sm:grid-cols-4">
            <Kpi
              label="FIPI + Mutual Funds (1D)"
              value={`${data.institutions1dPkr != null && data.institutions1dPkr > 0 ? "+" : ""}${((data.institutions1dPkr ?? 0) / 1e6).toFixed(1)}M`}
              tone={
                (data.institutions1dPkr ?? 0) > 0
                  ? "text-bull"
                  : (data.institutions1dPkr ?? 0) < 0
                    ? "text-bear"
                    : "text-muted"
              }
            />
            <Kpi
              label="Retail / Individuals (1D)"
              value={`${data.retail1dPkr != null && data.retail1dPkr > 0 ? "+" : ""}${((data.retail1dPkr ?? 0) / 1e6).toFixed(1)}M`}
              tone={
                (data.retail1dPkr ?? 0) > 0
                  ? "text-bull"
                  : (data.retail1dPkr ?? 0) < 0
                    ? "text-bear"
                    : "text-muted"
              }
            />
            <Kpi
              label="FIPI + Mutual Funds (30D)"
              value={`${inst30d != null && inst30d > 0 ? "+" : ""}${((inst30d ?? 0) / 1e6).toFixed(0)}M`}
              tone={
                (inst30d ?? 0) > 0
                  ? "text-bull"
                  : (inst30d ?? 0) < 0
                    ? "text-bear"
                    : "text-muted"
              }
            />
            <Kpi
              label="Retail (30D)"
              value={`${retail30d != null && retail30d > 0 ? "+" : ""}${((retail30d ?? 0) / 1e6).toFixed(0)}M`}
              tone={
                (retail30d ?? 0) > 0
                  ? "text-bull"
                  : (retail30d ?? 0) < 0
                    ? "text-bear"
                    : "text-muted"
              }
            />
          </div>

          <div className="overflow-x-auto">
            <table className="w-full border-collapse">
              <thead>
                <tr>
                  <Th right={false}>Participant</Th>
                  <Th>1D Net</Th>
                  <Th>5D Net</Th>
                  <Th>
                    <button
                      type="button"
                      onClick={cycleSort}
                      className={`inline-flex items-center gap-1 tracking-[0.15em] hover:text-ink ${
                        sort30d === false ? "text-ghost" : "text-info"
                      }`}
                      title="Sort by 30-day net (medium-term drift)"
                    >
                      30D Net
                      <svg
                        viewBox="0 0 24 24"
                        className="h-4 w-4"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth={2}
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        aria-hidden
                      >
                        {sort30d === "desc" ? (
                          <path d="M12 5v14M19 12l-7 7-7-7" />
                        ) : sort30d === "asc" ? (
                          <path d="M12 19V5M5 12l7-7 7 7" />
                        ) : (
                          <>
                            <path d="M7 4v16M4 7l3-3 3 3" />
                            <path d="M17 20V4M14 17l3 3 3-3" />
                          </>
                        )}
                      </svg>
                    </button>
                  </Th>
                </tr>
              </thead>
              <tbody>
                {participants.map((p) => (
                  <tr key={p.participantType} className="hover:bg-hoverline">
                    <Td right={false} bold tone="text-ink">
                      {p.participantType}
                    </Td>
                    <M v={p.net1dPkr} />
                    <M v={p.net5dPkr} />
                    <M v={p.net30dPkr} />
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Footer: the strongest 30D institutional accumulator (fact). */}
          <PanelFooter
            text={
              (() => {
                const leaders = data.participants
                  .filter((p) =>
                    ["FIPI", "MUTUAL FUNDS", "INSURANCE"].includes(
                      p.participantType,
                    ),
                  )
                  .filter((p) => (p.net30dPkr ?? 0) > 0)
                  .sort((a, b) => (b.net30dPkr ?? 0) - (a.net30dPkr ?? 0));
                return leaders.length > 0
                  ? `30D Smart Money Accumulation Leader: ${leaders[0].participantType} (+${((leaders[0].net30dPkr ?? 0) / 1e6).toFixed(0)}M PKR)`
                  : "No positive 30D institutional net this window";
              })()
            }
            tone={
              data.participants.some(
                (p) =>
                  ["FIPI", "MUTUAL FUNDS", "INSURANCE"].includes(
                    p.participantType,
                  ) && (p.net30dPkr ?? 0) > 0,
              )
                ? "text-bull/70"
                : "text-ghost"
            }
          />
        </>
      )}
    </Panel>
  );
}

// ---------------------------------------------------------------- //
// QUANT ACTION RADAR — top conviction signals for the active session. //
// ---------------------------------------------------------------- //

export function QuantRadarPanel({
  data,
  id,
}: {
  data: QuantRadarData;
  id?: string;
}) {
  const top = data.signals.slice(0, 3);
  return (
    <Panel
      id={id}
      letter="R"
      title="Quant Action Radar"
      meta={data.sessionDate ? `Signals · ${data.sessionDate}` : undefined}
    >
      {top.length === 0 ? (
        <RadarEmpty sessionDate={data.sessionDate} />
      ) : (
        <div className="divide-y divide-hairline/60">
          {top.map((signal) => {
            const tickerTone =
              signal.signalType.toUpperCase().includes("ACCUMULATION") ||
              signal.signalType.toUpperCase().includes("INSTITUTIONAL")
                ? "text-bull"
                : signal.signalType.toUpperCase().includes("TRAP") ||
                  signal.signalType.toUpperCase().includes("DISTRIBUTION") ||
                  signal.signalType.toUpperCase().includes("SHORT")
                  ? "text-bear"
                  : "text-ink";
            return (
              <div
                key={`${signal.tradeDate}-${signal.ticker}-${signal.signalType}`}
                className="flex min-w-0 flex-col gap-2 px-3 py-2.5 first:pt-0 last:pb-0"
              >
                <div className="flex items-center gap-2">
                  <span className="font-sans text-[13px] font-bold tabular-nums">
                    <TickerLink ticker={signal.ticker} />
                  </span>
                  <span className="flex items-center gap-2">
                    <SignalBadge signalType={signal.signalType} />
                    <span className="font-sans text-[10px] tabular-nums text-ghost">
                      {signal.confidenceScore != null
                        ? `${signal.confidenceScore}%`
                        : "—"}
                    </span>
                  </span>
                  <div className="ml-auto flex items-center gap-2">
                    {signal.sector ? (
                      <span className="font-sans text-[9px] tracking-wider text-ghost">
                        {signal.sector}
                      </span>
                    ) : (
                      <span className="font-sans text-[9px] text-ghost">—</span>
                    )}
                  </div>
                </div>
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                  {signal.marketClose != null && (
                    <span className="font-sans text-[10px] tabular-nums text-muted">
                      LTP {signal.marketClose.toFixed(2)}
                    </span>
                  )}
                  {signal.volume != null && (
                    <span className="font-sans text-[10px] tabular-nums text-muted">
                      VOL {fmtInt(signal.volume)}
                    </span>
                  )}
                </div>
                <CatalystNode signal={signal} />
              </div>
            );
          })}
        </div>
      )}
    </Panel>
  );
}

// ---------------------------------------------------------------- //
// PANEL V - Volume Breakouts: top turnover movers + dislocations.  //
// (Derived strictly from the certified breadth set - no extra fetch.) //
// ---------------------------------------------------------------- //

export function VolumeBreakoutsPanel({
  breadth,
  dislocation,
  id,
}: {
  breadth: BreadthData | null;
  dislocation: VolumeDislocationData | null;
  id?: string;
}) {
  // Top 12 by session turnover (close x volume, the certified product).
  const movers = useMemo(() => {
    if (breadth == null) return [];
    return [...breadth.moves]
      .filter((m) => (m.turnoverPkr ?? 0) > 0)
      .sort((a, b) => (b.turnoverPkr ?? 0) - (a.turnoverPkr ?? 0))
      .slice(0, 12);
  }, [breadth]);

  const disloc = dislocation?.names ?? [];

  if (breadth == null) {
    return (
      <Panel id={id} letter="V" title="Volume Breakouts">
        <Idle text="No EOD sessions stored" />
      </Panel>
    );
  }

  return (
    <Panel
      id={id}
      letter="V"
      title="Volume Breakouts"
      meta={`Top turnover · ${breadth.sessionDate}`}
    >
      <div className="grid grid-cols-1 gap-px bg-hairline xl:grid-cols-2">
        <div className="bg-panel">
          <div className="overflow-x-auto">
            <table className="w-full border-collapse">
              <thead>
                <tr>
                  <Th right={false}>Ticker</Th>
                  <Th>Close</Th>
                  <Th>Chg %</Th>
                  <Th>Volume</Th>
                  <Th>Turnover (PKR)</Th>
                </tr>
              </thead>
              <tbody>
                {movers.length === 0 ? (
                  <tr>
                    <td colSpan={5}>
                      <Idle text="No certified turnover rows this session" />
                    </td>
                  </tr>
                ) : (
                  movers.map((m) => (
                    <tr key={m.ticker} className="hover:bg-hoverline">
                      <Td right={false} bold>
                        <TickerLink ticker={m.ticker} />
                      </Td>
                      <Td>{m.close == null ? "—" : m.close.toFixed(2)}</Td>
                      <Td
                        bold
                        tone={
                          m.changePct == null
                            ? "text-ghost"
                            : m.changePct > 0
                              ? "text-bull"
                              : m.changePct < 0
                                ? "text-bear"
                                : "text-muted"
                        }
                      >
                        {fmtPct(m.changePct, 2)}
                      </Td>
                      <Td tone="text-muted">{fmtInt(m.volume)}</Td>
                      <Td tone="text-info">
                        {m.turnoverPkr == null
                          ? "—"
                          : `${(m.turnoverPkr / 1e6).toFixed(1)}M`}
                      </Td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className="bg-panel">
          {disloc.length === 0 ? (
            <Idle text="Top 25 volume runners stable — no new dislocations" />
          ) : (
            <div className="divide-y divide-hairline/60">
              {disloc.map((n) => (
                <div
                  key={n.ticker}
                  className="flex min-w-0 flex-wrap items-center gap-x-2.5 gap-y-1 px-3 py-2"
                >
                  <span className="font-sans text-[12px] font-bold text-ink">
                    <TickerLink ticker={n.ticker} />
                  </span>
                  <span className="font-sans text-[10px] tabular-nums text-muted">
                    {`VOL ${n.volume == null ? "—" : fmtInt(n.volume)} · CHG ${
                      n.changePct == null
                        ? "—"
                        : `${n.changePct > 0 ? "+" : ""}${n.changePct.toFixed(1)}%`
                    }`}
                  </span>
                  {n.insiderBuy && (
                    <span className="rounded-[2px] bg-warn/15 px-1.5 py-px font-sans text-[9px] font-bold tracking-widest text-warn ring-1 ring-warn/40">
                      Insider Buy
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <PanelFooter
        text={
          dislocation != null && dislocation.priorDate != null
            ? `Dislocation set: new top-25 volume entrants, ${dislocation.sessionDate} vs ${dislocation.priorDate}`
            : "Dislocation feed unavailable — top-turnover table above is the certified fact"
        }
        tone="text-ghost"
      />
    </Panel>
  );
}

// ---------------------------------------------------------------- //
// PANEL C - Verified Universe Breadth (full stored universe).      //
// ---------------------------------------------------------------- //

function MoveTable({
  title,
  rows,
  tone,
}: {
  title: string;
  rows: EodMove[];
  tone: "bull" | "bear";
}) {
  return (
    <div className="min-w-0">
      <p
        className={`border-b border-hairline px-2 py-1 font-sans text-[10px] font-bold tracking-[0.18em] ${
          tone === "bull" ? "text-bull" : "text-bear"
        }`}
      >
        {title}
      </p>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse">
          <thead>
            <tr>
              <Th right={false}>Ticker</Th>
              <Th>Close</Th>
              <Th>Chg %</Th>
              <Th>Volume</Th>
              <Th>Turnover (PKR)</Th>
            </tr>
          </thead>
          <tbody>
            {rows.map((m) => (
              <tr key={m.ticker} className="hover:bg-hoverline">
                <Td right={false} bold>
                  <TickerLink ticker={m.ticker} />
                </Td>
                <Td>{m.close == null ? "—" : m.close.toFixed(2)}</Td>
                <Td
                  bold
                  tone={tone === "bull" ? "text-bull" : "text-bear"}
                >
                  {fmtPct(m.changePct, 2)}
                </Td>
                <Td tone="text-muted">{fmtInt(m.volume)}</Td>
                <Td tone="text-muted">
                  {m.turnoverPkr == null
                    ? "—"
                    : `${(m.turnoverPkr / 1e6).toFixed(1)}M`}
                </Td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function BreadthPanel({
  data,
  id,
  /** Panel B facts: tickers with >= 1M-share above-market blocks. */
  accumTickers = [],
  /** Panel A fact: institutional (FIPI + Mutual Funds) 1D net, PKR. */
  inst1dPkr = null,
}: {
  data: BreadthData | null;
  id?: string;
  accumTickers?: string[];
  inst1dPkr?: number | null;
}) {
  return (
    <Panel
      id={id}
      letter="C"
      title="Verified Universe Breadth"
      meta={data ? `Session ${data.sessionDate}` : undefined}
    >
      {!data ? (
        <Idle text="No EOD sessions stored" />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-px border-b border-hairline bg-hairline sm:grid-cols-4">
            <Kpi
              label="Advancers"
              value={String(data.advancers)}
              tone={data.advancers > 0 ? "text-bull" : "text-muted"}
            />
            <Kpi
              label="Decliners"
              value={String(data.decliners)}
              tone={data.decliners > 0 ? "text-bear" : "text-muted"}
            />
            <Kpi label="Unchanged" value={String(data.unchanged)} />
            <Kpi
              label="A/D Ratio"
              value={data.ratio == null ? "—" : data.ratio.toFixed(2)}
              tone={data.ratio != null && data.ratio < 1 ? "text-bear" : "text-bull"}
              sub={`${data.verdicts} verdicts${data.priorDate ? ` vs ${data.priorDate}` : ""}`}
            />
          </div>

          {data.verdicts === 0 ? (
            <Idle text="No close-over-close verdicts computable this session" />
          ) : (
            <div className="grid grid-cols-1 gap-px bg-hairline lg:grid-cols-2">
              <div className="bg-panel">
                <MoveTable title="Top 10 Gainers" rows={data.gainers} tone="bull" />
              </div>
              <div className="bg-panel">
                <MoveTable title="Top 10 Losers" rows={data.losers} tone="bear" />
              </div>
            </div>
          )}

          {/* Footer: macro posture - strict factual conditions, checked in
              order of specificity. Cross-panel facts arrive as props; no
              prediction, only the session's own numbers. */}
          {data.ratio != null && (
            <PanelFooter
              text={
                data.ratio < 0.2 && accumTickers.length > 0
                  ? `Macro Divergence: Extreme negative breadth met with institutional block accumulation in ${accumTickers.join(", ")}`
                  : data.ratio < 0.5 && inst1dPkr != null && inst1dPkr < 0
                    ? "Macro Posture: Cash/Defensive — Tape is negative and institutions are net sellers"
                    : data.ratio > 1.0 && inst1dPkr != null && inst1dPkr > 0
                      ? "Macro Posture: Trend Alignment — Broad participation with institutional backing"
                      : "Macro Posture: Mixed — No qualifying divergence or alignment in this session's facts"
              }
              tone={
                data.ratio < 0.2 && accumTickers.length > 0
                  ? "text-warn/80"
                  : data.ratio < 0.5 && inst1dPkr != null && inst1dPkr < 0
                    ? "text-bear/70"
                    : data.ratio > 1.0 && inst1dPkr != null && inst1dPkr > 0
                      ? "text-bull/70"
                      : "text-ghost"
              }
            />
          )}
        </>
      )}
    </Panel>
  );
}
