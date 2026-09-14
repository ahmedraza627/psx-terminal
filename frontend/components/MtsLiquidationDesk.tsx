"use client";

import { useMemo } from "react";
import { Badge, DataTable, DeskFrame, IdleState, Row } from "@/components/ui/primitives";
import { fmtPct, fmtPkrB, fmtPrice } from "@/components/ui/format";
import type { MtsRow } from "@/components/MtsSqueezeBlotter";
import type { EodPoint } from "@/lib/deskQueries";

/**
 * MTS margin liquidation ladder.
 *
 * NCCPL MTS structures: leveraged buyers post initial margin and finance the
 * rest (financing ratio F = price exposure / equity). As price falls, equity
 * erodes by F × the price move; the margin call fires when equity reaches
 * the maintenance level and positions force-liquidate near the exit level.
 *
 *   P_call = P_entry × (1 − (1 − MAINT_EQUITY) / F)
 *   P_exit = P_entry × (1 − (1 − EXIT_EQUITY) / F)
 *
 * We cannot observe leveraged buyers' entry vintages, so the ladder prices
 * the threshold for three REAL entry points from stored EOD: the close 5,
 * 10 and 20 sessions ago. A vintage whose threshold sits at/above LTP is
 * already in call — that share of MTS value is the cascade fuel. Parameters
 * are disclosed below and conservative (mid-range of NCCPL's authorized
 * leverage bands); they are modeling assumptions, not client data.
 */
const FINANCING_RATIO = 3.0; // ~33% initial margin (NCCPL band midpoint)
const MAINT_EQUITY = 0.20; // margin call equity level
const EXIT_EQUITY = 0.12; // forced-liquidation equity level

const CALL_FACTOR = 1 - (1 - MAINT_EQUITY) / FINANCING_RATIO; // × entry
const EXIT_FACTOR = 1 - (1 - EXIT_EQUITY) / FINANCING_RATIO;

type LadderStatus = "SAFE" | "IN_CALL" | "LIQUIDATION";

interface LadderRowView {
  ticker: string;
  mtsValuePkr: number | null;
  utilizationPct: number | null;
  ltp: number | null;
  thresholds: { sessions: number; callPrice: number | null }[];
  /** Worst vintage status across the ladder. */
  status: LadderStatus;
  /** Share of the 20-session price range below the oldest vintage call. */
  atRiskPct: number | null;
}

function closeBySessionGap(
  closesNewestFirst: { date: string; close: number | null }[],
  gap: number
): number | null {
  // gap = sessions back from the newest stored session
  const idx = gap; // newest-first array: index IS the session gap
  return closesNewestFirst[idx]?.close ?? null;
}


export default function MtsLiquidationDesk({
  mtsRows,
  eod,
}: {
  mtsRows: MtsRow[];
  eod: EodPoint[];
}) {
  const ladder = useMemo<LadderRowView[]>(() => {
    if (mtsRows.length === 0) return [];
    const byTicker = new Map<string, { date: string; close: number | null }[]>();
    for (const r of eod) {
      const t = r.ticker.toUpperCase();
      const list = byTicker.get(t) ?? [];
      list.push({ date: r.tradeDate, close: r.close });
      byTicker.set(t, list);
    }
    byTicker.forEach((list) => {
      list.sort((a, b) => (a.date < b.date ? 1 : -1));
    });
    return mtsRows.map((m) => {
      const hist = byTicker.get(m.ticker.toUpperCase()) ?? [];
      const ltp = hist[0]?.close ?? m.entryReference;
      const thresholds = [5, 10, 20].map((gap) => {
        const p0 = closeBySessionGap(hist, gap);
        return {
          sessions: gap,
          callPrice: p0 != null ? p0 * CALL_FACTOR : null,
        };
      });
      // At-risk: LTP already at/below the 5-session-vintage call threshold.
      const call5 = thresholds[0].callPrice;
      const atRiskPct =
        ltp != null && call5 != null && call5 > 0
          ? Math.max(0, Math.min(100, ((call5 - ltp) / call5) * 100 * 3.0))
          : null;
      const worst: LadderStatus = thresholds.some(
        (t) => t.callPrice != null && ltp != null && ltp <= t.callPrice * (EXIT_FACTOR / CALL_FACTOR)
      )
        ? "LIQUIDATION"
        : thresholds.some((t) => t.callPrice != null && ltp != null && ltp <= t.callPrice)
          ? "IN_CALL"
          : "SAFE";
      return {
        ticker: m.ticker,
        mtsValuePkr: m.mtsValuePkr,
        utilizationPct: m.utilizationPct,
        ltp,
        thresholds,
        status: worst,
        atRiskPct,
      };
    });
  }, [mtsRows, eod]);

  const atRiskValue = ladder
    .filter((l) => l.status !== "SAFE")
    .reduce((a, l) => a + (l.mtsValuePkr ?? 0), 0);
  const totalValue = ladder.reduce((a, l) => a + (l.mtsValuePkr ?? 0), 0);

  return (
    <DeskFrame
      title="MTS Margin Liquidation Ladder — Cascade Thresholds"
      right={
        totalValue > 0 ? (
          <span className="font-mono text-[10px] tabular-nums text-ghost">
            BOOK {fmtPkrB(totalValue)} · AT RISK{" "}
            <span className={atRiskValue > 0 ? "text-bear" : "text-bull"}>
              {fmtPkrB(atRiskValue)}
            </span>
          </span>
        ) : null
      }
      footer={
        <p className="font-mono text-[10px] leading-relaxed text-ghost">
          Threshold = entry × {CALL_FACTOR.toFixed(3)} (call) /{" "}
          {(CALL_FACTOR * (EXIT_FACTOR / CALL_FACTOR)).toFixed(3)} (forced
          exit), from F = {FINANCING_RATIO.toFixed(1)}× financing, maintenance
          equity {Math.round(MAINT_EQUITY * 100)}%, exit{" "}
          {Math.round(EXIT_EQUITY * 100)}%. Entry vintages are REAL closes at
          t−5/−10/−20 sessions — actual leveraged entries are unobservable;
          the ladder is a threshold map, not client positions.
        </p>
      }
    >
      {mtsRows.length === 0 ? (
        <IdleState
          headline="[MTS FEED: AWAITING NCCPL CLEARING]"
          detail="Ladder builds from nccpl_mts_leverage prints — no leverage rows stored for this session."
        />
      ) : (
        <DataTable
          minWidth={820}
          columns={[
            { label: "Ticker" },
            { label: "MTS Value", align: "right" },
            { label: "Util %", align: "right" },
            { label: "LTP", align: "right" },
            { label: "Call @5S", align: "right" },
            { label: "Call @10S", align: "right" },
            { label: "Call @20S", align: "right" },
            { label: "State", align: "right" },
            { label: "Cascade Fuel", align: "right" },
          ]}
        >
          {ladder.map((l) => (
            <Row key={l.ticker}>
              <td className="px-2.5 py-1 font-mono text-[11px] font-semibold text-ink">
                {l.ticker}
              </td>
              <td className="px-2 py-1 text-right font-mono text-[11px] tabular-nums text-ink">
                {fmtPkrB(l.mtsValuePkr)}
              </td>
              <td className="px-2 py-1 text-right font-mono text-[11px] tabular-nums text-warn">
                {l.utilizationPct != null ? `${l.utilizationPct.toFixed(0)}%` : "—"}
              </td>
              <td className="px-2 py-1 text-right font-mono text-[11px] tabular-nums text-ink">
                {fmtPrice(l.ltp)}
              </td>
              {l.thresholds.map((t) => {
                const breached =
                  l.ltp != null && t.callPrice != null && l.ltp <= t.callPrice;
                return (
                  <td
                    key={t.sessions}
                    className={`px-2 py-1 text-right font-mono text-[11px] tabular-nums ${breached ? "text-bear font-semibold" : "text-muted"}`}
                  >
                    {fmtPrice(t.callPrice)}
                    {breached && " ⚠"}
                  </td>
                );
              })}
              <td className="px-2 py-1 text-right">
                <Badge
                  tone={
                    l.status === "LIQUIDATION"
                      ? "bear"
                      : l.status === "IN_CALL"
                        ? "warn"
                        : "bull"
                  }
                >
                  {l.status.replace("_", " ")}
                </Badge>
              </td>
              <td className="px-2 py-1 text-right font-mono text-[11px] tabular-nums">
                {l.atRiskPct != null && l.atRiskPct > 0 ? (
                  <span className="text-bear">{l.atRiskPct.toFixed(0)}%</span>
                ) : (
                  <span className="text-ghost">—</span>
                )}
              </td>
            </Row>
          ))}
        </DataTable>
      )}
    </DeskFrame>
  );
}
