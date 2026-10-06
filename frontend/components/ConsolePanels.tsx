"use client";

import { useMemo, useState } from "react";
import TickerLink from "@/components/TickerLink";
import {
  fmtInt,
  fmtPct,
  fmtPkrCompact,
  fmtSharesM,
} from "@/components/ui/format";
import type {
  BreadthData,
  EodMove,
  FlowMatrixData,
  NdmBlock,
  NdmSummary,
  QuantRadarData,
  QuantSignal,
  VolumeDislocationData,
} from "@/lib/consoleQueries";

// ---------------------------------------------------------------- //
// Shared chrome: high-contrast, crisp hairlines, monospace data.   //
// ---------------------------------------------------------------- //

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
    <section id={id} className="flex min-w-0 flex-col border border-hairline bg-panel">
      <header className="flex items-center justify-between gap-2 border-b border-hairline bg-obsidian/60 px-3 py-2">
        <h2 className="flex items-baseline gap-2 font-mono text-[11px] font-bold uppercase tracking-[0.18em] text-ink">
          <span className="text-info">{letter}</span>
          {title}
        </h2>
        {meta && (
          <span className="font-mono text-[10px] tabular-nums text-ghost">
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
    <div className="border border-hairline bg-obsidian/40 px-2.5 py-1.5">
      <p className="font-mono text-[9px] uppercase tracking-[0.2em] text-ghost">
        {label}
      </p>
      <p className={`font-mono text-[15px] font-bold tabular-nums ${tone}`}>
        {value}
      </p>
      {sub && (
        <p className="font-mono text-[9px] uppercase tracking-widest text-ghost">
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
      className={`border-b border-hairline px-2 py-1.5 font-mono text-[9px] font-semibold uppercase tracking-[0.15em] text-ghost ${
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
      className={`whitespace-nowrap border-b border-hairline/60 px-2 py-1.5 font-mono text-[11px] tabular-nums ${
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
    <p className="px-3 py-6 text-center font-mono text-[11px] uppercase tracking-widest text-ghost">
      {text}
    </p>
  );
}

function RadarEmpty({ sessionDate }: { sessionDate: string | null }) {
  return (
    <Idle
      text={
        sessionDate == null
          ? "NO SESSION OR SIGNALS STORED"
          : `NO QUANT SIGNALS COMPUTED FOR ${sessionDate}`
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
      className={`border-t border-hairline px-3 pt-2 mt-4 font-mono text-[10px] uppercase tracking-wider ${tone}`}
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
      <span className="rounded-[2px] bg-bull/15 px-1.5 py-px font-mono text-[9px] font-bold uppercase tracking-widest text-bull ring-1 ring-bull/40">
        {(signalType.match(/[A-Z][A-Z0-9_]+/g) || [signalType.toUpperCase()]).pop()}
      </span>
    );
  }
  if (isBear) {
    return (
      <span className="rounded-[2px] bg-bear/15 px-1.5 py-px font-mono text-[9px] font-bold uppercase tracking-widest text-bear ring-1 ring-bear/40">
        {(signalType.match(/[A-Z][A-Z0-9_]+/g) || [signalType.toUpperCase()]).pop()}
      </span>
    );
  }
  return (
    <span className="rounded-[2px] bg-hairline/60 px-1.5 py-px font-mono text-[9px] font-bold uppercase tracking-widest text-ghost ring-1 ring-hairline">
      {signalType.toUpperCase()}
    </span>
  );
}

function CatalystNode({ signal }: { signal: QuantSignal }) {
  const lines = (signal.catalystReason ?? "").split("\n");
  return (
    <div className="space-y-1">
      {lines.map((line, i) => (
        <p key={i} className="font-mono text-[10px] leading-relaxed text-ghost">
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
          ? `${data.asOfDate} · ${data.sessions} SESSIONS`
          : undefined
      }
    >
      {!data ? (
        <Idle text="NO NCCPL FLOW SESSIONS STORED" />
      ) : (
        <>
          {data.retailTrapped && (
            <div className="border-b border-bear/50 bg-bear/15 px-3 py-2">
              <p className="font-mono text-[11px] font-bold uppercase tracking-[0.18em] text-bear">
                <span className="mr-1.5 inline-block h-2 w-2 animate-pulse rounded-[2px] bg-bear align-middle" />
                Retail Trap Active: Smart Money Distributing
              </p>
              <p className="mt-0.5 font-mono text-[10px] leading-relaxed text-bear/80">
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
                      className={`inline-flex items-center gap-1 uppercase tracking-[0.15em] hover:text-ink ${
                        sort30d === false ? "text-ghost" : "text-info"
                      }`}
                      title="Sort by 30-day net (medium-term drift)"
                    >
                      30D Net
                      <span className="text-[8px]">
                        {sort30d === "desc" ? "▼" : sort30d === "asc" ? "▲" : "⇅"}
                      </span>
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
// PANEL B - NDM Block Tape (off-market liquidity >= 100k).         //
// ---------------------------------------------------------------- //

function HeadlineMetric({
  label,
  value,
  tone = "text-ink",
}: {
  label: string;
  value: string;
  tone?: string;
}) {
  return (
    <span className="flex items-baseline gap-1.5">
      <span className="font-mono text-[9px] uppercase tracking-[0.18em] text-ghost">
        {label}
      </span>
      <span className={`font-mono text-[13px] font-bold tabular-nums ${tone}`}>
        {value}
      </span>
    </span>
  );
}

export function NdmTapePanel({
  blocks,
  summary,
  id,
}: {
  blocks: NdmBlock[] | null;
  summary: NdmSummary | null;
  id?: string;
}) {
  const tape = blocks ?? [];
  const distCount = tape.filter((b) => b.distribution).length;
  const retiredTape = blocks != null && tape.length === 0;
  return (
    <Panel
      id={id}
      letter="B"
      title="NDM Block Tape"
      meta={
        blocks == null
          ? undefined
          : retiredTape
            ? "CERTIFIED AGGREGATES ONLY"
            : `${tape.length} BLOCKS ≥ 100K · ${distCount} DISTRIBUTION`
      }
    >
      {/* Certified session aggregates - the NDM headline that stays live
          after PSX retired the per-symbol board (psx_offmarket_summary). */}
      {summary != null && (
        <div className="border-b border-hairline bg-obsidian/40 px-3 py-2">
          <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
            <HeadlineMetric label="Deals" value={fmtInt(summary.trades)} />
            <HeadlineMetric
              label="Shares"
              value={fmtSharesM(summary.volume)}
              tone="text-info"
            />
            <HeadlineMetric
              label="Turnover"
              value={fmtPkrCompact(summary.value)}
              tone="text-info"
            />
            <HeadlineMetric
              label="State"
              value={(summary.state ?? "—").toUpperCase()}
              tone="text-ghost"
            />
          </div>
          <p className="pt-1 font-mono text-[9px] uppercase tracking-[0.2em] text-ghost">
            {`CERTIFIED NDM SESSION AGGREGATE · ${summary.tradeDate}`}
          </p>
        </div>
      )}
      {blocks == null ? (
        <Idle text="NDM FEED UNAVAILABLE" />
      ) : retiredTape ? (
        summary != null ? (
          <div className="px-3 py-4">
            <p className="border border-info/40 bg-info/10 px-2.5 py-2 font-mono text-[10px] font-bold uppercase leading-relaxed tracking-[0.15em] text-info">
              Per-symbol ticker tape retired by PSX — showing certified
              session aggregates
            </p>
          </div>
        ) : (
          <Idle text="NO CERTIFIED NDM AGGREGATE FOR THIS SESSION" />
        )
      ) : (
        <>
        <div className="overflow-x-auto">
          <table className="w-full border-collapse">
            <thead>
              <tr>
                <Th right={false}>Ticker</Th>
                <Th>Volume</Th>
                <Th>Negotiated Rate</Th>
                <Th>Market Price</Th>
                <Th>Spread %</Th>
                <Th>Flag</Th>
              </tr>
            </thead>
            <tbody>
              {tape.map((b, i) => (
                <tr
                  key={`${b.ticker}-${b.quantity}-${i}`}
                  className={
                    b.distribution
                      ? "bg-bear/10"
                      : b.accumulation
                        ? "bg-bull/10"
                        : "hover:bg-hoverline"
                  }
                >
                  <Td
                    right={false}
                    bold
                    tone={
                      b.distribution
                        ? "text-bear"
                        : b.accumulation
                          ? "text-bull"
                          : "text-ink"
                    }
                  >
                    <TickerLink ticker={b.ticker} />
                  </Td>
                  <Td
                    bold
                    tone={
                      b.distribution
                        ? "text-bear"
                        : b.accumulation
                          ? "text-bull"
                          : undefined
                    }
                  >
                    {fmtInt(b.quantity)}
                  </Td>
                  <Td>{b.rate == null ? "—" : b.rate.toFixed(2)}</Td>
                  <Td tone="text-muted">
                    {b.marketPrice == null ? "—" : b.marketPrice.toFixed(2)}
                  </Td>
                  <Td
                    bold={b.distribution || b.accumulation}
                    tone={
                      b.spreadPct == null
                        ? "text-ghost"
                        : b.spreadPct < 0
                          ? "text-bear"
                          : b.spreadPct > 0
                            ? "text-bull"
                            : "text-muted"
                    }
                  >
                    {fmtPct(b.spreadPct, 1)}
                  </Td>
                  <Td>
                    {b.distribution ? (
                      <span className="rounded-[2px] bg-bear/20 px-1.5 py-px font-mono text-[9px] font-bold uppercase tracking-widest text-bear ring-1 ring-bear/40">
                        Distribution
                      </span>
                    ) : b.accumulation ? (
                      <span className="rounded-[2px] bg-bull/20 px-1.5 py-px font-mono text-[9px] font-bold uppercase tracking-widest text-bull ring-1 ring-bull/40">
                        Accumulation
                      </span>
                    ) : (
                      <span className="font-mono text-[9px] text-ghost">—</span>
                    )}
                  </Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Footer: heaviest accumulation sweep (fact, short-term). */}
        <PanelFooter
          text={
            (() => {
              const sweeps = tape
                .filter((b) => b.accumulation)
                .sort((a, b) => (b.quantity ?? 0) - (a.quantity ?? 0));
              return sweeps.length > 0
                ? `Heaviest NDM Accumulation Sweep: ${sweeps[0].ticker} - ${fmtInt(sweeps[0].quantity)} shares @ ${fmtPct(sweeps[0].spreadPct, 1)} premium`
                : "No major accumulation blocks detected";
            })()
          }
          tone={
            tape.some((b) => b.accumulation) ? "text-bull/70" : "text-ghost"
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
      meta={data.sessionDate ? `SIGNALS · ${data.sessionDate}` : undefined}
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
                  <span className="font-mono text-[13px] font-bold tabular-nums">
                    <TickerLink ticker={signal.ticker} />
                  </span>
                  <span className="flex items-center gap-2">
                    <SignalBadge signalType={signal.signalType} />
                    <span className="font-mono text-[10px] tabular-nums text-ghost">
                      {signal.confidenceScore != null
                        ? `${signal.confidenceScore}%`
                        : "—"}
                    </span>
                  </span>
                  <div className="ml-auto flex items-center gap-2">
                    {signal.sector ? (
                      <span className="font-mono text-[9px] uppercase tracking-wider text-ghost">
                        {signal.sector}
                      </span>
                    ) : (
                      <span className="font-mono text-[9px] text-ghost">—</span>
                    )}
                  </div>
                </div>
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                  {signal.marketClose != null && (
                    <span className="font-mono text-[10px] tabular-nums text-muted">
                      LTP {signal.marketClose.toFixed(2)}
                    </span>
                  )}
                  {signal.volume != null && (
                    <span className="font-mono text-[10px] tabular-nums text-muted">
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
        <Idle text="NO EOD SESSIONS STORED" />
      </Panel>
    );
  }

  return (
    <Panel
      id={id}
      letter="V"
      title="Volume Breakouts"
      meta={`TOP TURNOVER · ${breadth.sessionDate}`}
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
                      <Idle text="NO CERTIFIED TURNOVER ROWS THIS SESSION" />
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
            <Idle text="TOP 25 VOLUME RUNNERS STABLE — NO NEW DISLOCATIONS" />
          ) : (
            <div className="divide-y divide-hairline/60">
              {disloc.map((n) => (
                <div
                  key={n.ticker}
                  className="flex min-w-0 flex-wrap items-center gap-x-2.5 gap-y-1 px-3 py-2"
                >
                  <span className="font-mono text-[12px] font-bold text-ink">
                    <TickerLink ticker={n.ticker} />
                  </span>
                  <span className="font-mono text-[10px] tabular-nums text-muted">
                    {`VOL ${n.volume == null ? "—" : fmtInt(n.volume)} · CHG ${
                      n.changePct == null
                        ? "—"
                        : `${n.changePct > 0 ? "+" : ""}${n.changePct.toFixed(1)}%`
                    }`}
                  </span>
                  {n.insiderBuy && (
                    <span className="rounded-[2px] bg-warn/15 px-1.5 py-px font-mono text-[9px] font-bold uppercase tracking-widest text-warn ring-1 ring-warn/40">
                      Insider Buy
                    </span>
                  )}
                  {n.ndmAccumulation && (
                    <span className="rounded-[2px] bg-info/15 px-1.5 py-px font-mono text-[9px] font-bold uppercase tracking-widest text-info ring-1 ring-info/40">
                      NDM Accumulation
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
        className={`border-b border-hairline px-2 py-1 font-mono text-[10px] font-bold uppercase tracking-[0.18em] ${
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
      meta={data ? `SESSION ${data.sessionDate}` : undefined}
    >
      {!data ? (
        <Idle text="NO EOD SESSIONS STORED" />
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
              sub={`${data.verdicts} VERDICTS${data.priorDate ? ` VS ${data.priorDate}` : ""}`}
            />
          </div>

          {data.verdicts === 0 ? (
            <Idle text="NO CLOSE-OVER-CLOSE VERDICTS COMPUTABLE THIS SESSION" />
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
