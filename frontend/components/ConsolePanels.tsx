"use client";

import { useMemo, useState } from "react";
import TickerLink from "@/components/TickerLink";
import { fmtInt, fmtPct } from "@/components/ui/format";
import type {
  BreadthData,
  EodMove,
  FlowMatrixData,
  NdmBlock,
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
  letter: "A" | "B" | "C";
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

export function NdmTapePanel({
  blocks,
  id,
}: {
  blocks: NdmBlock[] | null;
  id?: string;
}) {
  const tape = blocks ?? [];
  const distCount = tape.filter((b) => b.distribution).length;
  return (
    <Panel
      id={id}
      letter="B"
      title="NDM Block Tape"
      meta={
        blocks == null
          ? undefined
          : `${tape.length} BLOCKS ≥ 100K · ${distCount} DISTRIBUTION`
      }
    >
      {blocks == null ? (
        <Idle text="NDM FEED UNAVAILABLE" />
      ) : tape.length === 0 ? (
        <Idle text="NO OFF-MARKET BLOCKS ≥ 100K SHARES THIS SESSION" />
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
