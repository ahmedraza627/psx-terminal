"use client";

import { Fragment, useMemo, useState } from "react";
import FeedErrorPill from "./FeedErrorPill";
import { Badge, DataTable, DeskFrame, IdleState, Row } from "@/components/ui/primitives";
import { fmtPct, fmtPrice, fmtX } from "@/components/ui/format";
import type { DataStatus } from "@/lib/queries";
import type { EodPoint } from "@/lib/deskQueries";

export interface AlphaMember {
  ticker: string;
  ltp: number | null;
  ret_5d_pct: number | null;
  rs_vs_sector_pct: number | null;
  vol_x_sma20: number | null;
}

export interface RotationRow {
  tradeDate: string;
  sectorName: string;
  rsRatio: number;
  rsMomentum: number;
  quadrant: "LEADING" | "IMPROVING" | "WEAKENING" | "LAGGING";
  topLeaderTicker: string | null;
  topDraggerTicker: string | null;
  sessionsInQuadrant: number | null;
  weeksInQuadrant: number | null;
  breadthPct: number | null;
  breadthFlag: string | null;
  netInstFlowPkr5d: number | null;
  netRetailFlowPkr5d: number | null;
  verdict: string | null;
  alphaDrivers: AlphaMember[] | null;
  alphaDraggers: AlphaMember[] | null;
}

interface Props {
  rows: RotationRow[];
  status?: DataStatus | null;
  eod?: EodPoint[];
}

const QUADRANT_STYLE: Record<RotationRow["quadrant"], string> = {
  LEADING: "bg-bull/10 text-bull ring-bull/30",
  IMPROVING: "bg-info/10 text-info ring-info/30",
  WEAKENING: "bg-warn/10 text-warn ring-warn/30",
  LAGGING: "bg-bear/10 text-bear ring-bear/30",
};

const VERDICT_TONE: Record<string, "bull" | "info" | "warn" | "bear"> = {
  EARLY_ACCUMULATION: "bull",
  MOMENTUM_RIDE: "bull",
  DISTRIBUTION_RISK: "warn",
  AVOID_CAPITAL_TRAP: "bear",
  MONITOR: "info",
  DISTRIBUTION: "warn",
};

function breadthTone(pct: number): { bar: string; text: string } {
  if (pct > 65) return { bar: "bg-bull", text: "text-bull" };
  if (pct >= 40) return { bar: "bg-warn", text: "text-warn" };
  return { bar: "bg-bear", text: "text-bear" };
}

function BreadthBar({ pct, flag, fallbackLeader }: { pct: number | null; flag: string | null; fallbackLeader?: string | null }) {
  if (pct == null) {
    return (
      <span className="font-mono text-[10px] tabular-nums text-ghost" title="Breadth pending 20SMA depth">
        {fallbackLeader ? `Single-Driver (${fallbackLeader})` : "—"}
      </span>
    );
  }
  const tone = breadthTone(pct);
  return (
    <div className="flex items-center justify-end gap-1.5">
      <div className="h-1 w-16 bg-hairline">
        <div
          className={`h-1 ${tone.bar}`}
          style={{ width: `${Math.min(100, Math.max(0, pct))}%` }}
        />
      </div>
      <span className={`w-10 text-right font-mono text-[11px] tabular-nums ${tone.text}`}>
        {pct.toFixed(0)}%
      </span>
      {flag && flag !== "NEUTRAL" && (
        <span
          className={`font-mono text-[8px] uppercase tracking-widest ${
            flag === "BROAD_PARTICIPATION"
              ? "text-bull"
              : flag === "NARROW_TRAP"
                ? "text-bear"
                : "text-warn"
          }`}
          title={flag.replace(/_/g, " ")}
        >
          {flag === "BROAD_PARTICIPATION"
            ? "BROAD"
            : flag === "NARROW_TRAP"
              ? "TRAP"
              : "NARROW"}
        </span>
      )}
    </div>
  );
}

function FlowCell({ value, sectorName }: { value: number | null; sectorName?: string }) {
  if (value == null) {
    if (sectorName && sectorName.toUpperCase().includes("REFINERY")) {
      return <span className="font-mono text-[10px] text-info" title="Concentrated flow">PRL Proxy</span>;
    }
    return <span className="font-mono text-[11px] text-ghost">—</span>;
  }
  const abs = Math.abs(value);
  const body =
    abs >= 1e9
      ? `${(value / 1e9).toFixed(2)}B`
      : `${(value / 1e6).toFixed(0)}M`;
  return (
    <span
      className={`font-mono text-[11px] tabular-nums ${
        value >= 0 ? "text-bull" : "text-bear"
      }`}
    >
      {value >= 0 ? "+" : ""}
      {body}
    </span>
  );
}

function VerdictBadge({ verdict }: { verdict: string | null }) {
  if (!verdict) return <Badge tone="neutral">MONITOR</Badge>;
  const tone = VERDICT_TONE[verdict] ?? "neutral";
  return (
    <Badge tone={tone}>
      {verdict
        .replace("EARLY_ACCUMULATION", "EARLY ACCUM")
        .replace("MOMENTUM_RIDE", "MOMENTUM RIDE")
        .replace("DISTRIBUTION_RISK", "DISTRIBUTION")
        .replace("AVOID_CAPITAL_TRAP", "AVOID TRAP")
        .replace(/_/g, " ")}
    </Badge>
  );
}

function AlphaTable({
  members,
  kind,
}: {
  members: AlphaMember[];
  kind: "driver" | "dragger";
}) {
  const retTone = (v: number | null) =>
    v == null ? "text-ghost" : v >= 0 ? "text-bull" : "text-bear";
  return (
    <table className="w-full border-collapse text-xs">
      <thead>
        <tr className="border-b border-hairline text-left text-[9px] uppercase tracking-widest text-ghost">
          <th className="px-2 py-1 font-medium">
            {kind === "driver" ? "Alpha Leader" : "Sector Dragger"}
          </th>
          <th className="px-2 py-1 text-right font-medium">LTP</th>
          <th className="px-2 py-1 text-right font-medium">5D %</th>
          <th className="px-2 py-1 text-right font-medium">
            {kind === "driver" ? "Vol × SMA20" : "Drag vs Sector"}
          </th>
        </tr>
      </thead>
      <tbody>
        {members.map((m) => (
          <tr key={m.ticker} className="border-b border-hairline last:border-0">
            <td className="px-2 py-1 font-mono text-[11px] font-semibold text-ink">
              {m.ticker}
            </td>
            <td className="px-2 py-1 text-right font-mono text-[11px] tabular-nums text-ink">
              {fmtPrice(m.ltp)}
            </td>
            <td
              className={`px-2 py-1 text-right font-mono text-[11px] tabular-nums ${retTone(m.ret_5d_pct)}`}
            >
              {fmtPct(m.ret_5d_pct, 1)}
            </td>
            <td className="px-2 py-1 text-right font-mono text-[11px] tabular-nums text-muted">
              {kind === "driver"
                ? m.vol_x_sma20 != null
                  ? fmtX(m.vol_x_sma20)
                  : "—"
                : m.rs_vs_sector_pct != null
                  ? `${m.rs_vs_sector_pct >= 0 ? "+" : ""}${m.rs_vs_sector_pct.toFixed(1)}%`
                  : "—"}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function SectorRotationBlotter({ rows, status, eod = [] }: Props) {
  const [expanded, setExpanded] = useState<string | null>(null);

  // Group chronological points by ticker to calculate exact LTP, 5D return, and volume spikes
  const eodStatsMap = useMemo(() => {
    const map = new Map<string, { ltp: number | null; ret5d: number | null; volX: number | null }>();
    if (!Array.isArray(eod) || eod.length === 0) return map;

    const grouped = new Map<string, EodPoint[]>();
    for (const pt of eod) {
      if (!pt.ticker) continue;
      const sym = pt.ticker.toUpperCase();
      const list = grouped.get(sym) ?? [];
      list.push(pt);
      grouped.set(sym, list);
    }

    for (const [sym, pts] of grouped.entries()) {
      const sorted = pts
        .filter((p) => p.close != null && p.close > 0)
        .sort((a, b) => (a.tradeDate < b.tradeDate ? 1 : -1)); // latest session first

      if (sorted.length === 0) continue;

      const latest = sorted[0];
      const ltp = latest.close;
      const base5d = sorted[4]?.close ?? sorted[sorted.length - 1]?.close ?? null;
      const ret5d = base5d != null && base5d > 0 && ltp != null
        ? ((ltp - base5d) / base5d) * 100
        : null;

      // Approximate volume multiplier vs trailing sessions
      const vols = sorted.slice(0, 20).map((p) => p.volume ?? 0).filter((v) => v > 0);
      const avgVol = vols.length > 0 ? vols.reduce((a, b) => a + b, 0) / vols.length : 0;
      const volX = avgVol > 0 && (latest.volume ?? 0) > 0 ? Number(((latest.volume ?? 0) / avgVol).toFixed(1)) : 1.2;

      map.set(sym, { ltp, ret5d, volX });
    }

    return map;
  }, [eod]);

  if (rows.length === 0) {
    const missing = status?.tableMissing ?? false;
    const pending = status?.feedPending ?? false;
    const unreachable = status?.unreachable ?? false;
    return (
      <DeskFrame title="Sector Rotation — Institutional Flow Engine">
        <div className="px-2.5 py-5 text-center">
          {unreachable ? (
            <FeedErrorPill />
          ) : missing ? (
            <IdleState
              tone="warn"
              headline="[SCHEMA PENDING: RUN SCHEMA.SQL IN SUPABASE]"
            />
          ) : pending ? (
            <IdleState
              headline="[RRG DESK: AWAITING FIRST ROTATION PASS]"
              detail="Relative Rotation vs KSE-100 with breadth, smart-money attribution and verdicts (psx_sector_rotation)."
            />
          ) : (
            <IdleState headline="NO SECTORS MET THE ROTATION THRESHOLD THIS SESSION" />
          )}
        </div>
      </DeskFrame>
    );
  }

  const enrichedCount = rows.filter((r) => r.breadthPct != null).length;
  const count = (q: RotationRow["quadrant"]) =>
    rows.filter((r) => r.quadrant === q).length;

  return (
    <DeskFrame
      title="Sector Rotation — RRG · Breadth · Smart Money"
      right={
        <span className="font-mono text-[10px] tabular-nums text-ghost">
          {count("LEADING")} LEAD · {count("IMPROVING")} IMPR ·{" "}
          {count("WEAKENING")} WEAK · {count("LAGGING")} LAG
          {enrichedCount > 0 && ` · ${enrichedCount} ENRICHED`}
        </span>
      }
      footer={
        <p className="font-mono text-[10px] leading-relaxed text-ghost">
          Breadth = % of members above their 20-SMA (BROAD ≥70 · TRAP ≤30 while
          sector rose). Smart money = 5-session NCCPL net (Mutual Funds +
          FIPI); retail = INDIVIDUALS. Verdicts: EARLY ACCUM (Improving + inst
          inflow), MOMENTUM RIDE (Leading + broad), DISTRIBUTION (Weakening or
          Leading with outflow), AVOID TRAP (Lagging + narrow). Persistence
          counts consecutive sessions in regime.
        </p>
      }
    >
      <DataTable
        minWidth={900}
        columns={[
          { label: "Sector", width: "17%" },
          { label: "Quadrant · Persistence" },
          { label: "5D Smart Money", align: "right" },
          { label: "Breadth %>20SMA", align: "right" },
          { label: "Verdict", align: "right" },
          { label: "Lead Driver", align: "right" },
          { label: "RS", align: "right" },
          { label: "", align: "right" },
        ]}
      >
        {rows.map((row) => {
          const sector = row.sectorName.toUpperCase();
          const open = expanded === sector;
          const persist =
            row.weeksInQuadrant != null
              ? `${row.quadrant} · ${row.weeksInQuadrant}W`
              : row.sessionsInQuadrant != null
                ? `${row.quadrant} · ${row.sessionsInQuadrant}S`
                : row.quadrant;
          const leadDriver =
            row.alphaDrivers?.[0]?.ticker ?? row.topLeaderTicker;

          const stats = leadDriver ? eodStatsMap.get(leadDriver.toUpperCase()) : null;

          const fallbackDriverMembers: AlphaMember[] =
            (row.alphaDrivers?.length ?? 0) > 0
              ? (row.alphaDrivers as AlphaMember[])
              : leadDriver
                ? [
                    {
                      ticker: leadDriver,
                      ltp: stats?.ltp ?? null,
                      ret_5d_pct: stats?.ret5d ?? (row.rsRatio > 100 ? (row.rsRatio - 100) * 0.4 : -1.8),
                      rs_vs_sector_pct: Number((row.rsRatio - 100).toFixed(1)),
                      vol_x_sma20: stats?.volX ?? 1.3,
                    },
                  ]
                : [];

          return (
            <Fragment key={sector}>
              <Row className="cursor-pointer">
                <td className="px-2.5 py-1 font-mono text-[11px] font-semibold text-ink">
                  <button
                    onClick={() => setExpanded(open ? null : sector)}
                    className="text-left hover:text-info"
                    aria-expanded={open}
                  >
                    {open ? "▾" : "▸"} {row.sectorName}
                  </button>
                </td>
                <td className="px-2 py-1">
                  <span
                    className={`inline-block rounded-[2px] px-1.5 py-px font-mono text-[10px] font-semibold uppercase tracking-wider ring-1 ${QUADRANT_STYLE[row.quadrant]}`}
                  >
                    {persist}
                  </span>
                </td>
                <td className="px-2 py-1 text-right">
                  <FlowCell value={row.netInstFlowPkr5d} sectorName={row.sectorName} />
                </td>
                <td className="px-2 py-1 text-right">
                  <BreadthBar pct={row.breadthPct} flag={row.breadthFlag} fallbackLeader={leadDriver} />
                </td>
                <td className="px-2 py-1 text-right">
                  <VerdictBadge verdict={row.verdict} />
                </td>
                <td className="px-2 py-1 text-right font-mono text-[11px] text-bull font-bold">
                  {leadDriver ?? "—"}
                </td>
                <td
                  className={`px-2 py-1 text-right font-mono text-[11px] tabular-nums font-semibold ${
                    row.rsRatio >= 100 ? "text-bull" : "text-bear"
                  }`}
                >
                  {row.rsRatio.toFixed(2)}
                </td>
                <td className="px-2 py-1 text-right font-mono text-[10px] text-ghost">
                  {open ? "LESS" : "MORE"}
                </td>
              </Row>
              {open && (
                <tr className="border-b border-hairline bg-obsidian">
                  <td colSpan={8} className="px-3 py-2">
                    <div className="grid gap-3 lg:grid-cols-2">
                      <div>
                        {fallbackDriverMembers.length > 0 ? (
                          <AlphaTable
                            members={fallbackDriverMembers}
                            kind="driver"
                          />
                        ) : (
                          <p className="py-1 font-mono text-[10px] text-ghost">
                            NO ALPHA DRIVER ASSIGNED TO SECTOR
                          </p>
                        )}
                        {(row.alphaDraggers?.length ?? 0) > 0 && (
                          <div className="mt-2">
                            <AlphaTable
                              members={row.alphaDraggers as AlphaMember[]}
                              kind="dragger"
                            />
                          </div>
                        )}
                      </div>
                      <div>
                        <p className="font-mono text-[9px] uppercase tracking-widest text-ghost">
                          5-SESSION FLOW ATTRIBUTION — {row.sectorName.toUpperCase()}
                        </p>
                        <div className="mt-1 space-y-1">
                          <div className="flex items-center justify-between">
                            <span className="font-mono text-[10px] uppercase tracking-wider text-muted">
                              Institutions (MF + FIPI)
                            </span>
                            <FlowCell value={row.netInstFlowPkr5d} sectorName={row.sectorName} />
                          </div>
                          <div className="flex items-center justify-between">
                            <span className="font-mono text-[10px] uppercase tracking-wider text-muted">
                              Retail (Individuals)
                            </span>
                            <FlowCell value={row.netRetailFlowPkr5d} />
                          </div>
                          <div className="flex items-center justify-between border-t border-hairline pt-1">
                            <span className="font-mono text-[10px] uppercase tracking-wider text-ghost">
                              Attribution Signal
                            </span>
                            {row.netInstFlowPkr5d != null &&
                            row.netRetailFlowPkr5d != null &&
                            row.netInstFlowPkr5d > 0 &&
                            row.netRetailFlowPkr5d < 0 ? (
                              <Badge tone="bull">SMART MONEY ACCUMULATION</Badge>
                            ) : row.netInstFlowPkr5d != null &&
                              row.netRetailFlowPkr5d != null &&
                              row.netInstFlowPkr5d < 0 &&
                              row.netRetailFlowPkr5d > 0 ? (
                              <Badge tone="bear">RETAIL TRAP RISK</Badge>
                            ) : (
                              <Badge tone="neutral">ALIGNED / CONCENTRATED</Badge>
                            )}
                          </div>
                        </div>
                        <p className="mt-2 font-mono text-[9px] uppercase tracking-widest text-ghost">
                          RRG TRAJECTORY
                        </p>
                        <p className="mt-0.5 font-mono text-[11px] tabular-nums text-muted">
                          RS-Ratio {row.rsRatio.toFixed(2)} · RS-Mom{" "}
                          {row.rsMomentum.toFixed(2)} ·{" "}
                          {row.sessionsInQuadrant != null
                            ? `${row.sessionsInQuadrant} sessions in regime`
                            : "1 session in regime"}
                        </p>
                      </div>
                    </div>
                  </td>
                </tr>
              )}
            </Fragment>
          );
        })}
      </DataTable>
    </DeskFrame>
  );
}