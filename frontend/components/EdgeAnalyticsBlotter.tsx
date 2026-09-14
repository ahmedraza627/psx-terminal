"use client";

import { useMemo } from "react";
import {
  summarizeEdge,
  type BacktestRow,
  type EdgeSummary,
} from "@/lib/queries";
import {
  Badge,
  DataTable,
  DeskFrame,
  IdleState,
  Row,
  type Tone,
} from "@/components/ui/primitives";
import { fmtPct, fmtPf, fmtR, tonePct } from "@/components/ui/format";

function pfTone(value: number | null): string {
  if (value == null) return "text-ghost";
  if (!Number.isFinite(value) || value >= 1.25) return "text-bull";
  if (value >= 1.0) return "text-info";
  return "text-bear";
}

function expectancyTone(value: number | null): Tone {
  if (value == null) return "ghost";
  return value > 0 ? "bull" : value < 0 ? "bear" : "neutral";
}

export default function EdgeAnalyticsBlotter({
  rows,
  tableMissing,
}: {
  rows: BacktestRow[];
  tableMissing: boolean;
}) {
  // 30-session realized window: only rows whose signal session falls in the
  // trailing 30 distinct trading sessions of stored evaluations.
  const windowRows: BacktestRow[] = useMemo(() => {
    const days = Array.from(new Set(rows.map((r) => r.tradeDate)))
      .sort()
      .reverse()
      .slice(0, 30);
    const daySet = new Set(days);
    return rows.filter((r) => daySet.has(r.tradeDate));
  }, [rows]);
  const summary: EdgeSummary[] = useMemo(
    () => summarizeEdge(windowRows),
    [windowRows]
  );

  if (tableMissing) {
    return (
      <DeskFrame title="Edge Lab — Walk-Forward Performance">
        <IdleState
          tone="warn"
          headline="[SCHEMA PENDING: RUN SCHEMA.SQL IN SUPABASE]"
          detail="signal_backtest_performance does not exist yet."
        />
      </DeskFrame>
    );
  }

  if (rows.length === 0) {
    return (
      <DeskFrame title="Edge Lab — Walk-Forward Performance">
        <IdleState
          headline="[EDGE LAB: ACCUMULATING FORWARD SESSIONS]"
          detail="Walk-forward seed re-simulates the quant engine over the trailing 30 sessions and resolves every signal against stored EOD history (tiered TP / BE-ratchet conventions)."
        />
      </DeskFrame>
    );
  }

  const totalEvaluated = windowRows.length;
  const totalResolved = summary.reduce((a, s) => a + s.resolved, 0);
  const totalTp1 = Math.round(
    (summary.reduce((a, s) => a + (s.tp1HitPct ?? 0) * s.resolved, 0)) / 100
  );
  const totalScratch = Math.round(
    (summary.reduce((a, s) => a + (s.scratchBePct ?? 0) * s.resolved, 0)) / 100
  );
  const totalFullStop = Math.round(
    (summary.reduce((a, s) => a + (s.fullStopPct ?? 0) * s.resolved, 0)) / 100
  );
  const windowDays = new Set(windowRows.map((r) => r.tradeDate)).size;

  const tail = windowRows
    .filter((r) => r.hitTarget != null || r.returnT5Pct != null)
    .slice(0, 3);

  return (
    <DeskFrame
      title="Edge Lab — Tiered Execution · 30-Session Realized Window"
      right={
        <span className="font-mono text-[10px] tabular-nums text-ghost">
          {totalEvaluated} EVAL · {totalResolved} RESOLVED · TP1{" "}
          {totalResolved ? Math.round((totalTp1 / totalResolved) * 100) : 0}% ·
          BE {totalResolved ? Math.round((totalScratch / totalResolved) * 100) : 0}
          % · STOP{" "}
          {totalResolved ? Math.round((totalFullStop / totalResolved) * 100) : 0}
          % · {windowDays}D
        </span>
      }
      footer={
        <p className="font-mono text-[10px] leading-relaxed text-ghost">
          Tiered plan: TP1 +1.0R banks 50% and ratchets the remaining stop to
          break-even (+0.2%) · TP2 +2.0R banks 30% · final 20% runs to +3R or a
          1.5×ATR trail. Same-session stop+target touch resolves as stop
          (conservative). PF = Σ realized wins ÷ Σ realized losses in R; E[R] =
          mean realized R. Scratch = stopped at the break-even ratchet after
          TP1 (~+0.1R).
          {tail.length > 0 && (
            <span className="mt-1 block">
              {tail.map((r) => (
                <span key={r.signalId} className="block">
                  ▸ {r.tradeDate} {r.ticker} [{r.signalType}]{" "}
                  {r.realizedR != null
                    ? fmtR(r.realizedR)
                    : r.hitTarget == null
                      ? "unresolved"
                      : r.fullStop
                        ? "FULL STOP"
                        : r.tp1Hit
                          ? "TP1+"
                          : "STOPPED"}{" "}
                  · t5 {fmtPct(r.returnT5Pct)}
                </span>
              ))}
            </span>
          )}
        </p>
      }
    >
      <DataTable
        minWidth={880}
        columns={[
          { label: "Signal" },
          { label: "N", align: "right" },
          { label: "Resolved", align: "right" },
          { label: "TP1 Hit % (+1R)", align: "right" },
          { label: "Scratch/BE %", align: "right" },
          { label: "Full Stop %", align: "right" },
          { label: "PF", align: "right" },
          { label: "E[R]", align: "right" },
          { label: "T+5", align: "right" },
          { label: "T+10", align: "right" },
          { label: "T+20", align: "right" },
          { label: "MFE/MAE", align: "right" },
        ]}
      >
        {summary.map((s) => (
          <Row key={s.signalType}>
            <td className="px-2.5 py-1 font-mono text-[11px] font-semibold text-ink">
              {s.signalType.replace(/_/g, " ")}
            </td>
            <td className="px-2 py-1 text-right font-mono text-[11px] tabular-nums text-muted">
              {s.signals}
            </td>
            <td className="px-2 py-1 text-right font-mono text-[11px] tabular-nums text-muted">
              {s.resolved}
            </td>
            <td className="px-2 py-1 text-right font-mono text-[11px] tabular-nums text-bull">
              {s.tp1HitPct == null ? "—" : `${s.tp1HitPct.toFixed(1)}%`}
            </td>
            <td className="px-2 py-1 text-right font-mono text-[11px] tabular-nums text-warn">
              {s.scratchBePct == null ? "—" : `${s.scratchBePct.toFixed(1)}%`}
            </td>
            <td className="px-2 py-1 text-right font-mono text-[11px] tabular-nums text-bear">
              {s.fullStopPct == null ? "—" : `${s.fullStopPct.toFixed(1)}%`}
            </td>
            <td
              className={`px-2 py-1 text-right font-mono text-[11px] font-semibold tabular-nums ${pfTone(s.profitFactor)}`}
            >
              {fmtPf(s.profitFactor)}
            </td>
            <td className="px-2 py-1 text-right">
              <Badge tone={expectancyTone(s.expectancyR)}>
                {fmtR(s.expectancyR)}
              </Badge>
            </td>
            <td className="px-2 py-1 text-right">
              <span className={`font-mono text-[11px] tabular-nums ${tonePct(s.avgT5Pct)}`}>
                {fmtPct(s.avgT5Pct)}
              </span>
            </td>
            <td className="px-2 py-1 text-right">
              <span className={`font-mono text-[11px] tabular-nums ${tonePct(s.avgT10Pct)}`}>
                {fmtPct(s.avgT10Pct)}
              </span>
            </td>
            <td className="px-2 py-1 text-right">
              <span className={`font-mono text-[11px] tabular-nums ${tonePct(s.avgT20Pct)}`}>
                {fmtPct(s.avgT20Pct)}
              </span>
            </td>
            <td className="px-2 py-1 text-right font-mono text-[11px] tabular-nums">
              <span className="text-bull/80">{fmtPct(s.avgMfePct, 0)}</span>
              <span className="text-ghost">/</span>
              <span className="text-bear/80">{fmtPct(s.avgMaePct, 0)}</span>
            </td>
          </Row>
        ))}
      </DataTable>
    </DeskFrame>
  );
}
