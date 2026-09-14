"use client";

import { useMemo, useState } from "react";
import { DataTable, DeskFrame, IdleState, Row } from "@/components/ui/primitives";
import { fmtInt, fmtPct, fmtPrice, tonePct } from "@/components/ui/format";
import { sizeBook, RISK_DEFAULTS, type SizingSignal } from "@/lib/risk";
import {
  buildPortfolioNav,
  computeExposure,
  navSvg,
} from "@/lib/portfolio";
import type { EodPoint, HistSignal } from "@/lib/deskQueries";

const EQUITY_DEFAULT = 5_000_000;

interface Props {
  /** Active-session signals (drives the live holdings ledger). */
  sizingSignals: SizingSignal[];
  /** Trailing-session signals for the walk-forward NAV. */
  historySignals: HistSignal[];
  eod: EodPoint[];
  sectorMap: Map<string, string>;
  marketCapByTicker: Map<string, number>;
}

export default function ModelPortfolioDesk({
  sizingSignals,
  historySignals,
  eod,
  sectorMap,
  marketCapByTicker,
}: Props) {
  const [equity, setEquity] = useState(EQUITY_DEFAULT);

  // Active session book (risk-engine conventions).
  const book = useMemo(
    () => sizeBook(sizingSignals, equity, RISK_DEFAULTS),
    [sizingSignals, equity]
  );

  // Walk-forward NAV over stored history (no look-ahead: each session's
  // actionable signals are marked with the NEXT session's stored closes).
  const signalsByDate = useMemo(() => {
    const m = new Map<string, SizingSignal[]>();
    for (const h of historySignals) {
      const list = m.get(h.tradeDate) ?? [];
      list.push({
        ticker: h.ticker,
        signalType: h.signalType,
        entryReference: h.entryReference,
        stopLoss: h.stopLoss,
        conviction: h.conviction,
      });
      m.set(h.tradeDate, list);
    }
    return m;
  }, [historySignals]);

  const { nav, stats } = useMemo(
    () => buildPortfolioNav(signalsByDate, eod, 30),
    [signalsByDate, eod]
  );

  const exposure = useMemo(
    () =>
      computeExposure(
        book.positions.map((p) => ({
          positionValuePkr: p.positionValuePkr,
          ticker: p.ticker,
        })),
        sectorMap,
        marketCapByTicker
      ),
    [book.positions, sectorMap, marketCapByTicker]
  );

  const curve = navSvg(nav);
  const maxDelta = Math.max(
    1e-9,
    ...exposure.map((e) => Math.abs(e.deltaPct))
  );

  const lastCloseBy = useMemo(() => {
    // Latest stored close per ticker for ledger marks.
    const m = new Map<string, number>();
    for (const r of eod) {
      const t = r.ticker.toUpperCase();
      if (!m.has(t) && r.close != null) m.set(t, r.close);
    }
    return m;
  }, [eod]);

  if (historySignals.length === 0 && eod.length === 0) {
    return (
      <DeskFrame title="Model Portfolio vs Market">
        <IdleState
          tone="warn"
          headline="[PORTFOLIO DESK: INSUFFICIENT STORED HISTORY]"
          detail="The NAV walk needs trailing signals + EOD history (psx_daily_eod, signals_computed). Run the pipeline passes to populate."
        />
      </DeskFrame>
    );
  }

  return (
    <>
      <DeskFrame
        title="Model Portfolio — NAV vs Equal-Weight Market Proxy"
        right={
          <div className="flex items-center gap-1.5">
            <span className="font-mono text-[9px] uppercase tracking-widest text-ghost">
              EQUITY PKR
            </span>
            <input
              type="number"
              value={equity}
              min={100000}
              step={500000}
              onChange={(e) =>
                setEquity(Math.max(100000, Number(e.target.value) || 0))
              }
              className="h-5 w-28 rounded-[2px] border border-hairline bg-obsidian px-1.5 font-mono text-[11px] tabular-nums text-ink focus:border-info/50 focus:outline-none"
              aria-label="Portfolio equity PKR"
            />
          </div>
        }
        footer={
          <p className="font-mono text-[10px] leading-relaxed text-ghost">
            Walk-forward book: each stored session&apos;s actionable signals,
            equal-weight, marked at the next session&apos;s closes (no
            look-ahead). Benchmark is an equal-weight market proxy built from
            all stored closes — PSX publishes no free index series in our
            tables. Alpha = Jensen&apos;s (rf = 11% 6M-KIBOR stand-in) · Sharpe
            = (mean − rf) / σ, annualized √252.
          </p>
        }
      >
        {/* Stat strip */}
        <div className="grid grid-cols-3 gap-px border-b border-hairline bg-hairline sm:grid-cols-6">
          {[
            { k: "BOOK NAV", v: fmtPct(stats.bookTotalPct, 1), t: tonePct(stats.bookTotalPct) },
            { k: "PROXY NAV", v: fmtPct(stats.proxyTotalPct, 1), t: tonePct(stats.proxyTotalPct) },
            { k: "ALPHA ANN", v: fmtPct(stats.alphaAnnPct, 1), t: tonePct(stats.alphaAnnPct) },
            { k: "BETA", v: stats.beta != null ? stats.beta.toFixed(2) : "—", t: "text-ink" },
            { k: "SHARPE", v: stats.sharpe != null ? stats.sharpe.toFixed(2) : "—", t: stats.sharpe != null && stats.sharpe >= 1 ? "text-bull" : "text-ink" },
            { k: "MAX DD", v: fmtPct(stats.maxDrawdownPct, 1), t: "text-bear" },
          ].map((s) => (
            <div key={s.k} className="bg-panel px-2 py-1.5">
              <p className="font-mono text-[9px] uppercase tracking-widest text-ghost">
                {s.k}
              </p>
              <p className={`font-mono text-[12px] tabular-nums ${s.t}`}>
                {s.v}
              </p>
            </div>
          ))}
        </div>

        {/* NAV curve */}
        <div className="border-b border-hairline px-2.5 py-2">
          {curve.path ? (
            <svg
              viewBox={`0 0 ${curve.w} ${curve.h}`}
              className="h-28 w-full"
              aria-label="NAV equity curve vs market proxy"
            >
              <path
                d={curve.pathProxy}
                fill="none"
                stroke="#388BFD"
                strokeWidth="1"
                strokeDasharray="3 3"
              />
              <path d={curve.path} fill="none" stroke="#26A69A" strokeWidth="1.4" />
            </svg>
          ) : (
            <p className="py-6 text-center font-mono text-[10px] uppercase tracking-widest text-ghost">
              NAV CURVE BUILDS AS SESSIONS RESOLVE
            </p>
          )}
          <div className="flex items-center gap-4 pt-1">
            <span className="font-mono text-[9px] uppercase tracking-widest text-bull">
              — BOOK
            </span>
            <span className="font-mono text-[9px] uppercase tracking-widest text-info">
              -- MARKET PROXY
            </span>
            <span className="ml-auto font-mono text-[9px] tabular-nums text-ghost">
              {stats.sessions} SESSIONS
            </span>
          </div>
        </div>

        {/* Sector exposure vs market composition */}
        <div className="border-b border-hairline px-2.5 py-2">
          <p className="font-mono text-[9px] uppercase tracking-widest text-ghost">
            SECTOR EXPOSURE Δ vs MARKET WEIGHT
          </p>
          {exposure.length === 0 ? (
            <p className="py-2 font-mono text-[10px] text-ghost">
              NO OPEN POSITIONS — EXPOSURE FLAT
            </p>
          ) : (
            <div className="mt-1 space-y-1">
              {exposure.slice(0, 10).map((e) => (
                <div key={e.sector} className="flex items-center gap-2">
                  <span className="w-32 truncate font-mono text-[10px] uppercase tracking-wider text-muted">
                    {e.sector}
                  </span>
                  <div className="relative h-1.5 flex-1 bg-hairline">
                    <div className="absolute inset-y-0 left-1/2 w-px bg-ghost" />
                    <div
                      className={`absolute inset-y-0 ${e.deltaPct >= 0 ? "bg-bull" : "bg-bear"}`}
                      style={{
                        left:
                          e.deltaPct >= 0 ? "50%" : `${50 - (Math.abs(e.deltaPct) / maxDelta) * 50}%`,
                        width: `${(Math.abs(e.deltaPct) / maxDelta) * 50}%`,
                      }}
                    />
                  </div>
                  <span
                    className={`w-14 text-right font-mono text-[10px] tabular-nums ${e.deltaPct >= 0 ? "text-bull" : "text-bear"}`}
                  >
                    {e.deltaPct >= 0 ? "+" : ""}
                    {e.deltaPct.toFixed(1)}%
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </DeskFrame>

      {/* Holdings ledger */}
      <DeskFrame
        title="Holdings Ledger — Active Session Book"
        right={
          <span className="font-mono text-[10px] tabular-nums text-ghost">
            {book.positions.length} POSITIONS · HEAT{" "}
            {book.totals.portfolioHeatPct.toFixed(2)}% · DEPLOYED{" "}
            {book.totals.deployedPctOfEquity.toFixed(0)}%
          </span>
        }
        footer={
          <p className="font-mono text-[10px] leading-relaxed text-ghost">
            Sizing: fixed-fractional risk parity (1.0% risk/trade, 6% heat cap,
            20% max position) — identical conventions to the pipeline risk
            engine. Distance-to-stop marks the live capital at risk per name.
          </p>
        }
      >
        {book.positions.length === 0 ? (
          <IdleState
            headline="NO OPEN POSITIONS THIS SESSION"
            detail={
              book.rejected.length > 0
                ? `${book.rejected.length} signals rejected by risk guardrails (stop geometry / heat / exposure caps).`
                : "No actionable signals passed the regime gate."
            }
          />
        ) : (
          <DataTable
            minWidth={720}
            columns={[
              { label: "Ticker" },
              { label: "Signal" },
              { label: "Shares", align: "right" },
              { label: "Entry", align: "right" },
              { label: "Stop", align: "right" },
              { label: "Value PKR", align: "right" },
              { label: "Alloc %", align: "right" },
              { label: "Risk PKR", align: "right" },
              { label: "Dist to Stop", align: "right" },
            ]}
          >
            {book.positions.map((p) => {
              const mark = lastCloseBy.get(p.ticker.toUpperCase()) ?? p.entryReference;
              const allocPct = (p.positionValuePkr / equity) * 100;
              const distStopPct = p.stopDistancePct;
              return (
                <Row key={`${p.ticker}-${p.signalType}`}>
                  <td className="px-2.5 py-1 font-mono text-[11px] font-semibold text-ink">
                    {p.ticker}
                  </td>
                  <td className="px-2 py-1 font-mono text-[10px] text-muted">
                    {p.signalType.replace(/_/g, " ")}
                  </td>
                  <td className="px-2 py-1 text-right font-mono text-[11px] tabular-nums text-ink">
                    {fmtInt(p.shares)}
                  </td>
                  <td className="px-2 py-1 text-right font-mono text-[11px] tabular-nums text-ink">
                    {fmtPrice(p.entryReference)}
                  </td>
                  <td className="px-2 py-1 text-right font-mono text-[11px] tabular-nums text-bear">
                    {fmtPrice(p.stopLoss)}
                  </td>
                  <td className="px-2 py-1 text-right font-mono text-[11px] tabular-nums text-ink">
                    {fmtInt(p.positionValuePkr)}
                  </td>
                  <td className="px-2 py-1 text-right font-mono text-[11px] tabular-nums text-muted">
                    {allocPct.toFixed(1)}%
                  </td>
                  <td className="px-2 py-1 text-right font-mono text-[11px] tabular-nums text-warn">
                    {fmtInt(p.riskPkr)}
                  </td>
                  <td className="px-2 py-1 text-right">
                    <span
                      className={`font-mono text-[11px] tabular-nums ${
                        mark != null && mark <= p.stopLoss
                          ? "text-bear"
                          : "text-muted"
                      }`}
                    >
                      -{distStopPct.toFixed(1)}%
                    </span>
                  </td>
                </Row>
              );
            })}
          </DataTable>
        )}
      </DeskFrame>
    </>
  );
}
