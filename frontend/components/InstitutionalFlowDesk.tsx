"use client";

import { useMemo } from "react";
import {
  Badge,
  DataTable,
  DeskFrame,
  DivergeBar,
  IdleState,
  Row,
  type Tone,
} from "@/components/ui/primitives";
import { fmtPct, fmtPkrM } from "@/components/ui/format";
import type { EodPoint, FlowRow } from "@/lib/deskQueries";
import type { KiborRow } from "@/lib/queries";

/**
 * Institutional Flow & Rate Shock Desk.
 *
 * PANEL A — NCCPL FIPI/LIPI participant matrix: net PKR per participant
 * category over the latest session plus trailing 5/15/30-session windows.
 * Aggregate rows (ALL / FOREIGN TOTAL / LOCAL TOTAL) are excluded so
 * per-sector detail is never double-counted.
 *
 * PANEL B — Sector smart money: institutional-only nets per sector over the
 * same windows, a persistence score (5D/30D + 15D/30D, 0..2), and the
 * absorption-accumulation divergence: institutions net-buying a sector whose
 * equal-weight price fell >1% over the window.
 *
 * PANEL C — KIBOR rate-shock model: floating debt, interest-coverage proxy
 * (EPS ÷ annual interest per share at the 11% 6M-KIBOR stand-in), tiered
 * vulnerability (HIGH < 1.5x, MODERATE ≤ 3x, RESISTANT > 3x) and EPS deltas
 * under +100/+200/+300bps stress. Zero synthetic inputs: names without
 * published debt or EPS render as unclassified "—".
 */

// --------------------------------------------------------------- //
// Contract (page.tsx): flows / kibor / eod / sectorMap — all       //
// optional; every panel degrades to its own institutional idle.    //
// --------------------------------------------------------------- //
interface Props {
  flows?: FlowRow[];
  kibor?: KiborRow[];
  eod?: EodPoint[];
  sectorMap?: Map<string, string>;
}

/** Aggregate rows that would double-count the per-sector detail. */
const AGGREGATE_TYPES = new Set([
  "ALL",
  "FOREIGN TOTAL",
  "LOCAL TOTAL",
  "GRAND TOTAL",
  "TOTAL",
]);

/** Participant categories in FIPI/LIPI publication order. */
const FLOW_CATEGORIES: { label: string; types: ReadonlySet<string> }[] = [
  { label: "MUTUAL FUNDS", types: new Set(["MUTUAL FUNDS"]) },
  { label: "FOREIGN (FIPI)", types: new Set(["FIPI", "FOREIGN CORPORATES"]) },
  { label: "BANKS / DFIs", types: new Set(["BANKS", "BANKS/DFIS", "DFI"]) },
  { label: "COMPANIES", types: new Set(["COMPANIES"]) },
  { label: "INSURANCE", types: new Set(["INSURANCE"]) },
  { label: "BROKER PROPRIETARY", types: new Set(["BROKER PROPRIETARY"]) },
  { label: "NBFC", types: new Set(["NBFC"]) },
  { label: "INDIVIDUALS", types: new Set(["INDIVIDUALS"]) },
  { label: "OTHER ORGS", types: new Set(["OTHER ORGANIZATIONS"]) },
];

/** Institutional set for sector smart money (matches queries.ts convention). */
const INSTITUTIONAL = new Set([
  "MUTUAL FUNDS",
  "FIPI",
  "FOREIGN CORPORATES",
  "BANKS",
  "BANKS/DFIS",
  "DFI",
]);

/** KIBOR stand-in for the annual-interest coverage proxy (fraction). */
const KIBOR_RATE = 0.11;

interface WindowAgg {
  latest: number;
  s5: number;
  s15: number;
  s30: number;
}

function emptyAgg(): WindowAgg {
  return { latest: 0, s5: 0, s15: 0, s30: 0 };
}

/** Roll flows into per-key nets across windows; latest = newest session. */
function rollFlows(
  flows: FlowRow[],
  keyOf: (r: FlowRow) => string | null,
  matchType: (participantType: string) => boolean
): { latestDate: string | null; sessionCount: number; rows: Map<string, WindowAgg> } {
  const dates = Array.from(new Set(flows.map((r) => r.tradeDate))).sort().reverse();
  const latestDate = dates[0] ?? null;
  const w5 = new Set(dates.slice(0, 5));
  const w15 = new Set(dates.slice(0, 15));
  const w30 = new Set(dates.slice(0, 30));
  const rows = new Map<string, WindowAgg>();
  for (const r of flows) {
    if (!matchType(r.participantType)) continue;
    const key = keyOf(r);
    if (key == null) continue;
    const net = r.netPkr ?? 0;
    const b = rows.get(key) ?? emptyAgg();
    if (r.tradeDate === latestDate) b.latest += net;
    if (w5.has(r.tradeDate)) b.s5 += net;
    if (w15.has(r.tradeDate)) b.s15 += net;
    if (w30.has(r.tradeDate)) b.s30 += net;
    rows.set(key, b);
  }
  return { latestDate, sessionCount: dates.length, rows };
}

/** Equal-weight sector price change over the 5 newest EOD sessions. */
function sectorPrice5d(
  eod: EodPoint[],
  sectorMap: Map<string, string>
): Map<string, number> {
  const out = new Map<string, number>();
  if (eod.length === 0 || sectorMap.size === 0) return out;
  const dates = Array.from(new Set(eod.map((r) => r.tradeDate)))
    .sort()
    .reverse()
    .slice(0, 5);
  if (dates.length < 2) return out;
  const first = dates[dates.length - 1];
  const last = dates[0];
  const firstClose = new Map<string, number>();
  const lastClose = new Map<string, number>();
  for (const r of eod) {
    if (r.close == null) continue;
    if (r.tradeDate === first) firstClose.set(r.ticker, r.close);
    if (r.tradeDate === last) lastClose.set(r.ticker, r.close);
  }
  const acc = new Map<string, { sum: number; n: number }>();
  for (const [ticker, close] of lastClose) {
    const base = firstClose.get(ticker);
    if (base == null || base <= 0) continue;
    const sector = sectorMap.get(ticker);
    if (!sector) continue;
    const b = acc.get(sector) ?? { sum: 0, n: 0 };
    b.sum += ((close - base) / base) * 100;
    b.n += 1;
    acc.set(sector, b);
  }
  for (const [sector, v] of acc) out.set(sector, v.sum / v.n);
  return out;
}

function netTone(v: number): string {
  return v > 0 ? "text-bull" : v < 0 ? "text-bear" : "text-muted";
}

/** Interest-coverage proxy: EPS ÷ annual interest per share (KIBOR 11%). */
function coverageProxy(row: KiborRow): number | null {
  if (
    row.currentEps == null ||
    row.epsImpact100bpsPkr == null ||
    row.epsImpact100bpsPkr <= 0
  ) {
    return null;
  }
  const annualInterestPerShare = row.epsImpact100bpsPkr * (KIBOR_RATE * 100);
  if (annualInterestPerShare <= 0) return null;
  return row.currentEps / annualInterestPerShare;
}

function coverageTier(coverage: number | null): {
  label: string;
  tone: Tone;
} {
  if (coverage == null) return { label: "UNCLASSIFIED", tone: "ghost" };
  if (coverage < 1.5) return { label: "HIGH VULNERABILITY", tone: "bear" };
  if (coverage <= 3) return { label: "MODERATE", tone: "warn" };
  return { label: "RESISTANT", tone: "bull" };
}

function fmtBn(v: number | null): string {
  if (v == null) return "—";
  return `${(v / 1e9).toFixed(1)}B`;
}

function fmtEpsShock(v: number): string {
  return `${v >= 0 ? "+" : ""}${v.toFixed(2)}`;
}

/** Sub-panel header strip (inside the desk frame). */
function PanelHeader({ label, right }: { label: string; right?: string }) {
  return (
    <div className="flex items-center justify-between border-b border-hairline bg-panel px-2.5 py-1">
      <span className="font-mono text-[9px] font-semibold uppercase tracking-[0.2em] text-ghost">
        {label}
      </span>
      {right && (
        <span className="font-mono text-[9px] uppercase tracking-wider text-ghost">
          {right}
        </span>
      )}
    </div>
  );
}

export default function InstitutionalFlowDesk({
  flows = [],
  kibor = [],
  eod = [],
  sectorMap = new Map(),
}: Props) {
  // ---- Panel A: participant matrix, bucketed by participant type ---------
  const catAgg = useMemo(
    () =>
      rollFlows(
        flows,
        (r) => r.sectorName,
        (t) => !AGGREGATE_TYPES.has(t)
      ),
    [flows]
  );
  const categories = useMemo(() => {
    const byType = rollFlows(
      flows,
      (r) => r.participantType,
      () => true
    );
    return FLOW_CATEGORIES.map((cat) => {
      const agg = emptyAgg();
      for (const type of cat.types) {
        const b = byType.rows.get(type);
        if (!b) continue;
        agg.latest += b.latest;
        agg.s5 += b.s5;
        agg.s15 += b.s15;
        agg.s30 += b.s30;
      }
      return { label: cat.label, ...agg };
    }).sort((a, b) => b.s30 - a.s30);
  }, [flows]);

  // ---- Panel B: sector smart money + divergence --------------------------
  const sectorRows = useMemo(() => {
    const inst = rollFlows(
      flows,
      (r) => (r.sectorName === "ALL" ? null : r.sectorName),
      (t) => INSTITUTIONAL.has(t)
    );
    const prices = sectorPrice5d(eod, sectorMap);
    return inst.rows.size === 0
      ? []
      : Array.from(inst.rows.entries())
          .map(([sector, b]) => {
            const score =
              b.s30 !== 0 ? b.s5 / b.s30 + b.s15 / b.s30 : b.s5 + b.s15 > 0 ? 2 : b.s5 + b.s15 < 0 ? -2 : 0;
            const price5 = prices.get(sector) ?? null;
            let signal: { label: string; tone: Tone } = {
              label: "NEUTRAL",
              tone: "ghost",
            };
            if (b.s5 > 0 && score >= 0.5 && price5 != null && price5 < -1) {
              signal = { label: "ABSORPTION ACCUMULATION", tone: "bull" };
            } else if (b.s5 > 0 && score >= 0.5) {
              signal = { label: "ACCUMULATION", tone: "bull" };
            } else if (b.s5 < 0 && score <= -0.5) {
              signal = { label: "DISTRIBUTION", tone: "bear" };
            }
            return { sector, ...b, score, price5, signal };
          })
          .sort((a, b) => b.s5 - a.s5);
  }, [flows, eod, sectorMap]);

  const maxCat5d = Math.max(1, ...categories.map((c) => Math.abs(c.s5)));

  // ---- Panel C: KIBOR stress ladder --------------------------------------
  const stressRows = useMemo(
    () =>
      kibor
        .map((row) => {
          const coverage = coverageProxy(row);
          const impact = row.epsImpact100bpsPkr ?? null;
          return {
            row,
            coverage,
            tier: coverageTier(coverage),
            shock100: impact != null ? -impact * 1 : null,
            shock200: impact != null ? -impact * 2 : null,
            shock300: impact != null ? -impact * 3 : null,
            epsAt300:
              impact != null && row.currentEps != null
                ? row.currentEps - impact * 3
                : null,
          };
        })
        .sort((a, b) => {
          if (a.coverage == null && b.coverage == null) return 0;
          if (a.coverage == null) return 1;
          if (b.coverage == null) return -1;
          return a.coverage - b.coverage;
        }),
    [kibor]
  );

  if (flows.length === 0 && kibor.length === 0) {
    return (
      <DeskFrame title="Institutional Flow & Rate Shock Desk">
        <IdleState
          tone="warn"
          headline="[FLOW & RATE DESK: AWAITING NCCPL + KIBOR FEEDS]"
          detail="nccpl_fipi_lipi and psx_kibor_sensitivity are both empty — the desk populates the moment either feed lands."
        />
      </DeskFrame>
    );
  }

  return (
    <DeskFrame
      title="Institutional Flow & Rate Shock Desk"
      right={
        <span className="font-mono text-[10px] uppercase tracking-wider text-ghost">
          {catAgg.latestDate ?? "NO FLOW SESSION"} · {catAgg.sessionCount}S
        </span>
      }
      footer={
        <p className="font-mono text-[10px] leading-relaxed text-ghost">
          Participant matrix nets sum per-sector NCCPL FIPI/LIPI detail (ALL /
          FOREIGN TOTAL / LOCAL TOTAL aggregates excluded — no double count).
          Smart-money score = 5D/30D + 15D/30D institutional persistence (±2
          cap when 30D is flat). ABSORPTION ACCUMULATION = positive
          institutional 5D net into a sector whose equal-weight price fell
          &gt;1% over the same window. Coverage proxy = EPS ÷ annual interest
          per share at the 11% 6M-KIBOR stand-in; tiers: HIGH &lt;1.5x ·
          MODERATE ≤3x · RESISTANT &gt;3x. Stress ΔEPS = floating-debt
          sensitivity scaled linearly to +100/200/300bps — never extrapolated
          beyond published debt inputs.
        </p>
      }
    >
      {/* -------- Panel A: participant matrix -------- */}
      {flows.length === 0 ? (
        <IdleState
          headline="[FLOW MATRIX: AWAITING NCCPL CLEARING PUBLICATION]"
          tone="info"
        />
      ) : (
        <>
          <PanelHeader
            label="NCCPL PARTICIPANT MATRIX — NET PKR"
            right={`LATEST ${catAgg.latestDate ?? "—"}`}
          />
          <DataTable
            minWidth={720}
            columns={[
              { label: "Participant", width: "22%" },
              { label: "Latest", align: "right" },
              { label: "5D Net", align: "right" },
              { label: "15D Net", align: "right" },
              { label: "30D Net", align: "right" },
              { label: "5D Weight", align: "right", width: "18%" },
            ]}
          >
            {categories.map((c) => (
              <Row key={c.label}>
                <td className="px-2.5 py-1 font-mono text-[10px] uppercase tracking-wider text-muted">
                  {c.label}
                </td>
                <td className={`px-2 py-1 text-right font-mono text-[11px] tabular-nums ${netTone(c.latest)}`}>
                  {fmtPkrM(c.latest)}
                </td>
                <td className={`px-2 py-1 text-right font-mono text-[11px] tabular-nums ${netTone(c.s5)}`}>
                  {fmtPkrM(c.s5)}
                </td>
                <td className={`px-2 py-1 text-right font-mono text-[11px] tabular-nums ${netTone(c.s15)}`}>
                  {fmtPkrM(c.s15)}
                </td>
                <td className={`px-2 py-1 text-right font-mono text-[11px] tabular-nums ${netTone(c.s30)}`}>
                  {fmtPkrM(c.s30)}
                </td>
                <td className="px-2 py-1">
                  <DivergeBar value={c.s5} maxAbs={maxCat5d} />
                </td>
              </Row>
            ))}
          </DataTable>
        </>
      )}

      {/* -------- Panel B: sector smart money -------- */}
      {flows.length === 0 ? null : sectorRows.length === 0 ? (
        <IdleState
          headline="[SECTOR SMART MONEY: NO INSTITUTIONAL SECTOR DETAIL PUBLISHED]"
          tone="info"
        />
      ) : (
        <>
          <PanelHeader
            label="SECTOR SMART MONEY — INSTITUTIONAL NET PKR"
            right="SCORE = 5D/30D + 15D/30D"
          />
          <DataTable
            minWidth={780}
            columns={[
              { label: "Sector", width: "24%" },
              { label: "5D Net", align: "right" },
              { label: "15D Net", align: "right" },
              { label: "30D Net", align: "right" },
              { label: "Score", align: "right" },
              { label: "Price 5D %", align: "right" },
              { label: "Signal", align: "right", width: "20%" },
            ]}
          >
            {sectorRows.map((s) => (
              <Row key={s.sector}>
                <td
                  className="max-w-[220px] truncate px-2.5 py-1 font-mono text-[10px] uppercase tracking-wider text-ink"
                  title={s.sector}
                >
                  {s.sector}
                </td>
                <td className={`px-2 py-1 text-right font-mono text-[11px] tabular-nums ${netTone(s.s5)}`}>
                  {fmtPkrM(s.s5)}
                </td>
                <td className={`px-2 py-1 text-right font-mono text-[11px] tabular-nums ${netTone(s.s15)}`}>
                  {fmtPkrM(s.s15)}
                </td>
                <td className={`px-2 py-1 text-right font-mono text-[11px] tabular-nums ${netTone(s.s30)}`}>
                  {fmtPkrM(s.s30)}
                </td>
                <td className="px-2 py-1 text-right font-mono text-[11px] tabular-nums text-ink">
                  {s.score.toFixed(2)}
                </td>
                <td
                  className={`px-2 py-1 text-right font-mono text-[11px] tabular-nums ${
                    s.price5 == null ? "text-ghost" : netTone(s.price5)
                  }`}
                >
                  {s.price5 == null ? "—" : fmtPct(s.price5, 1)}
                </td>
                <td className="px-2 py-1 text-right">
                  <Badge tone={s.signal.tone}>{s.signal.label}</Badge>
                </td>
              </Row>
            ))}
          </DataTable>
        </>
      )}

      {/* -------- Panel C: KIBOR stress ladder -------- */}
      {kibor.length === 0 ? (
        <IdleState
          headline="[RATE SHOCK MODEL: AWAITING FLOATING-DEBT INPUTS]"
          detail="Supply floating debt via KIBOR_FLOATING_DEBT_MAP — the ladder populates without estimated balance sheets."
          tone="info"
        />
      ) : (
        <>
          <PanelHeader
            label="KIBOR RATE-SHOCK LADDER — EPS IMPACT UNDER STRESS"
            right={`${stressRows.length} NAMES · SORTED BY FRAGILITY`}
          />
          <DataTable
            minWidth={860}
            columns={[
              { label: "Ticker", width: "10%" },
              { label: "Sector", width: "16%" },
              { label: "Flt Debt", align: "right" },
              { label: "Base EPS", align: "right" },
              { label: "Coverage", align: "right" },
              { label: "Risk Tier", align: "right", width: "16%" },
              { label: "ΔEPS +100", align: "right" },
              { label: "ΔEPS +200", align: "right" },
              { label: "ΔEPS +300", align: "right" },
              { label: "EPS @+300", align: "right" },
            ]}
          >
            {stressRows.map((s) => (
              <Row key={s.row.ticker}>
                <td className="px-2.5 py-1 font-mono text-[11px] font-semibold text-ink">
                  {s.row.ticker}
                </td>
                <td
                  className="max-w-[150px] truncate px-2 py-1 font-mono text-[10px] uppercase tracking-wider text-muted"
                  title={s.row.sectorName ?? undefined}
                >
                  {s.row.sectorName ?? "—"}
                </td>
                <td className="px-2 py-1 text-right font-mono text-[11px] tabular-nums text-ink">
                  {fmtBn(s.row.floatingDebtPkr)}
                </td>
                <td className="px-2 py-1 text-right font-mono text-[11px] tabular-nums text-ink">
                  {s.row.currentEps == null ? "—" : s.row.currentEps.toFixed(2)}
                </td>
                <td
                  className={`px-2 py-1 text-right font-mono text-[11px] tabular-nums ${
                    s.coverage == null
                      ? "text-ghost"
                      : s.coverage < 1.5
                        ? "text-bear font-semibold"
                        : s.coverage <= 3
                          ? "text-warn"
                          : "text-bull"
                  }`}
                >
                  {s.coverage == null ? "—" : `${s.coverage.toFixed(2)}x`}
                </td>
                <td className="px-2 py-1 text-right">
                  <Badge tone={s.tier.tone}>{s.tier.label}</Badge>
                </td>
                {[s.shock100, s.shock200, s.shock300].map((v, i) => (
                  <td
                    key={i}
                    className={`px-2 py-1 text-right font-mono text-[11px] tabular-nums ${
                      v == null ? "text-ghost" : "text-bear"
                    }`}
                  >
                    {v == null ? "—" : fmtEpsShock(v)}
                  </td>
                ))}
                <td className="px-2 py-1 text-right font-mono text-[11px] tabular-nums text-ink">
                  {s.epsAt300 == null ? "—" : s.epsAt300.toFixed(2)}
                </td>
              </Row>
            ))}
          </DataTable>
        </>
      )}
    </DeskFrame>
  );
}
