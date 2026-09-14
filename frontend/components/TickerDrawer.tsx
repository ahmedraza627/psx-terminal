"use client";

import { useMemo } from "react";
import { Badge, DeskFrame } from "@/components/ui/primitives";
import { fmtPct, fmtPkrB, fmtPrice, fmtX, tonePct } from "@/components/ui/format";
import type { WhaleRow, KiborRow } from "@/lib/queries";
import type { ResearchRow } from "@/components/ResearchDeskBlotter";
import type { SignalRow } from "@/lib/types";
import type { EodPoint } from "@/lib/deskQueries";

interface Props {
  ticker: string | null;
  onClose: () => void;
  whale: WhaleRow | null;
  signals: SignalRow[];
  research: ResearchRow | null;
  kibor: KiborRow | null;
  eod: EodPoint[];
  onCompare: (ticker: string) => void;
}

function Spark({ closes }: { closes: number[] }) {
  if (closes.length < 2) return null;
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const range = max - min || 1;
  const w = 340;
  const h = 48;
  const pts = closes
    .map((c, i) => {
      const x = (i / (closes.length - 1)) * w;
      const y = h - ((c - min) / range) * (h - 4) - 2;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  const up = closes[closes.length - 1] >= closes[0];
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="h-12 w-full" aria-hidden>
      <polyline
        points={pts}
        fill="none"
        stroke={up ? "#26A69A" : "#F23645"}
        strokeWidth="1.2"
      />
    </svg>
  );
}

export default function TickerDrawer({
  ticker,
  onClose,
  whale,
  signals,
  research,
  kibor,
  eod,
  onCompare,
}: Props) {
  const hist = useMemo(() => {
    if (!ticker) return [];
    return eod
      .filter((r) => r.ticker.toUpperCase() === ticker.toUpperCase())
      .sort((a, b) => (a.tradeDate < b.tradeDate ? 1 : -1))
      .slice(0, 30)
      .reverse();
  }, [eod, ticker]);

  if (!ticker) return null;

  const ltp = whale?.entry_reference ?? research?.intrinsicValuePkr ?? null;
  const drift = whale?.meta.drift_pct ?? null;
  const volX = whale?.meta.vol_multiple ?? null;
  const stop = whale?.stop_loss ?? null;
  const closes = hist.map((h) => h.close).filter((c): c is number => c != null);
  const hi20 = closes.length ? Math.max(...closes) : null;
  const lo20 = closes.length ? Math.min(...closes) : null;
  const rangePos =
    hi20 != null && lo20 != null && hi20 > lo20 && ltp != null
      ? ((ltp - lo20) / (hi20 - lo20)) * 100
      : null;
  const avgVol =
    hist.length > 0
      ? hist.reduce((a, h) => a + (h.volume ?? 0), 0) / hist.length
      : null;
  const turnover = avgVol != null && ltp != null ? avgVol * ltp : null;
  const target2R =
    ltp != null && stop != null && ltp > stop ? ltp + 2 * (ltp - stop) : null;
  const tickerSignals = signals.filter(
    (s) => s.ticker.toUpperCase() === ticker.toUpperCase()
  );

  return (
    <div
      className="fixed inset-y-0 right-0 z-30 w-[min(400px,94vw)] overflow-y-auto scroll-thin border-l border-hairline bg-panel shadow-none wire-in"
      role="dialog"
      aria-label={`Inspection drawer ${ticker}`}
    >
      <div className="sticky top-0 z-10 flex items-center justify-between border-b border-hairline bg-panel px-2.5 py-1.5">
        <div className="flex items-center gap-2">
          <span className="font-mono text-sm font-bold tracking-widest text-ink">
            {ticker.toUpperCase()}
          </span>
          {whale?.meta.sector && (
            <Badge tone="neutral">{whale.meta.sector.toUpperCase()}</Badge>
          )}
        </div>
        <div className="flex items-center gap-1.5">
          <button
            onClick={() => onCompare(ticker.toUpperCase())}
            className="rounded-[2px] px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-info ring-1 ring-info/30 hover:bg-info/10"
          >
            COMP+
          </button>
          <button
            onClick={onClose}
            aria-label="Close drawer"
            className="rounded-[2px] px-1.5 py-0.5 font-mono text-[10px] text-muted ring-1 ring-hairline hover:text-ink"
          >
            ESC
          </button>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-px bg-hairline">
        {[
          { k: "LTP", v: fmtPrice(ltp), t: "" },
          { k: "DAY %", v: fmtPct(drift), t: tonePct(drift) },
          { k: "VOL x20", v: fmtX(volX), t: "text-info" },
          { k: "STOP", v: fmtPrice(stop), t: "text-bear" },
          { k: "TARGET 2R", v: fmtPrice(target2R), t: "text-bull" },
          {
            k: "RANGE POS",
            v: rangePos != null ? `${rangePos.toFixed(0)}%` : "—",
            t: "text-muted",
          },
          {
            k: "20D HI",
            v: fmtPrice(hi20),
            t: "",
          },
          { k: "20D LO", v: fmtPrice(lo20), t: "" },
          {
            k: "20D TURNOVER",
            v: turnover != null ? fmtPkrB(turnover) : "—",
            t: "",
          },
        ].map((s) => (
          <div key={s.k} className="bg-panel px-2 py-1">
            <p className="font-mono text-[9px] uppercase tracking-widest text-ghost">
              {s.k}
            </p>
            <p className={`font-mono text-[12px] tabular-nums ${s.t || "text-ink"}`}>
              {s.v}
            </p>
          </div>
        ))}
      </div>

      {closes.length > 1 && (
        <div className="border-b border-hairline px-2.5 py-1.5">
          <p className="font-mono text-[9px] uppercase tracking-widest text-ghost">
            30-SESSION CLOSE
          </p>
          <Spark closes={closes} />
        </div>
      )}

      <DeskFrame title="Session Signals">
        {tickerSignals.length === 0 ? (
          <p className="px-2.5 py-2 font-mono text-[10px] uppercase tracking-widest text-ghost">
            NO SIGNALS THIS SESSION
          </p>
        ) : (
          tickerSignals.map((s) => (
            <div
              key={`${s.timeframe}-${s.signal_type}`}
              className="border-b border-hairline px-2.5 py-1.5"
            >
              <div className="flex items-center justify-between">
                <span className="font-mono text-[11px] font-semibold text-ink">
                  {s.signal_type.replace(/_/g, " ")}
                </span>
                <Badge tone="neutral">{s.timeframe.replace(/_/g, " ")}</Badge>
              </div>
              <p className="mt-0.5 text-[11px] leading-snug text-muted">
                {s.rationale}
              </p>
            </div>
          ))
        )}
      </DeskFrame>

      {research && (
        <DeskFrame title="Research (PSX-MF)">
          <div className="grid grid-cols-2 gap-px bg-hairline">
            {[
              { k: "ALPHA SCORE", v: research.alphaScore.toFixed(0), t: "text-info" },
              {
                k: "INTRINSIC",
                v: fmtPrice(research.intrinsicValuePkr),
                t: "",
              },
              {
                k: "SPREAD",
                v: fmtPct(research.valuationDiscountPct, 1),
                t: tonePct(research.valuationDiscountPct),
              },
              {
                k: "STATUS",
                v: research.valuationStatus.replace(/_/g, " "),
                t: "text-muted",
              },
              {
                k: "TGT P/E",
                v: research.targetPeUsed != null ? fmtX(research.targetPeUsed, 1) : "—",
                t: "",
              },
              {
                k: "DIV FLOOR",
                v: fmtPrice(research.dividendFloorPkr),
                t: "",
              },
            ].map((s) => (
              <div key={s.k} className="bg-panel px-2 py-1">
                <p className="font-mono text-[9px] uppercase tracking-widest text-ghost">
                  {s.k}
                </p>
                <p className={`font-mono text-[12px] tabular-nums ${s.t}`}>
                  {s.v}
                </p>
              </div>
            ))}
          </div>
        </DeskFrame>
      )}

      {kibor && (
        <DeskFrame title="Rate Sensitivity">
          <div className="px-2.5 py-1.5">
            <p className="font-mono text-[11px] tabular-nums text-muted">
              FLOATING DEBT{" "}
              <span className="text-ink">
                {fmtPkrB(kibor.floatingDebtPkr, 1)}
              </span>
            </p>
            <p className="font-mono text-[11px] tabular-nums text-muted">
              ΔEPS / 100BPS{" "}
              <span className="text-ink">
                {fmtPrice(kibor.epsImpact100bpsPkr)}
              </span>
            </p>
            <p className="font-mono text-[11px] tabular-nums text-muted">
              EPS @300BPS CUT{" "}
              <span className="text-bull">
                {fmtPct(kibor.epsExpansion300bpsPct, 1)}
              </span>
            </p>
          </div>
        </DeskFrame>
      )}

      {whale?.meta.ndm_confirmed && (
        <div className="border-t border-bull/20 bg-bull/5 px-2.5 py-1.5">
          <p className="font-mono text-[10px] uppercase tracking-widest text-bull">
            NDM CONFIRMED · OFF-MARKET ACCUMULATION
          </p>
        </div>
      )}
    </div>
  );
}
