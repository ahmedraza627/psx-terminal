"use client";

import { useMemo, useState } from "react";
import { Badge, DeskFrame, IdleState } from "@/components/ui/primitives";
import { fmtPct, fmtPrice, fmtX } from "@/components/ui/format";
import type { ResearchRow, WhaleRow } from "@/lib/queries";
import type { FundamentalsRow } from "@/lib/deskQueries";

interface Props {
  research: ResearchRow[];
  fundamentals: FundamentalsRow[];
  whaleRows: WhaleRow[];
  onInspect: (ticker: string) => void;
}

/**
 * "Companies Explained" institutional note reader. Every figure is computed
 * from stored rows: target price = psx_equity_research intrinsic value
 * (PSX-MF relative P/E + dividend-floor model — the method badge renders the
 * stored model_version), LTP = fundamentals close, dated events = real
 * signal/disclosure sessions. Qualitative sections (moat scoring) render an
 * explicit pending state instead of invented prose.
 */
export default function ResearchNotesDesk({
  research,
  fundamentals,
  whaleRows,
  onInspect,
}: Props) {
  const [selected, setSelected] = useState<string | null>(null);

  const rowsByTicker = useMemo(() => {
    const m = new Map<string, ResearchRow>();
    for (const r of research) m.set(r.ticker.toUpperCase(), r);
    return m;
  }, [research]);

  const fundByTicker = useMemo(() => {
    const m = new Map<string, FundamentalsRow>();
    for (const f of fundamentals) m.set(f.ticker.toUpperCase(), f);
    return m;
  }, [fundamentals]);

  const candidates = useMemo(
    () =>
      research
        .slice()
        .sort((a, b) => b.alphaScore - a.alphaScore)
        .slice(0, 40),
    [research]
  );

  const active: ResearchRow | null =
    selected != null
      ? rowsByTicker.get(selected) ?? candidates[0] ?? null
      : candidates[0] ?? null;
  const fund = active
    ? fundByTicker.get(active.ticker.toUpperCase()) ?? null
    : null;
  const whale = active
    ? whaleRows.find((w) => w.ticker.toUpperCase() === active.ticker.toUpperCase()) ??
      null
    : null;

  if (research.length === 0) {
    return (
      <DeskFrame title="Companies Explained — Institutional Notes">
        <IdleState
          tone="warn"
          headline="[RESEARCH NOTES: NO EQUITY RESEARCH ROWS]"
          detail="Notes generate from psx_equity_research — run the fundamental pass to populate."
        />
      </DeskFrame>
    );
  }

  const ltp = fund?.closePrice ?? whale?.entry_reference ?? null;
  const target = active?.intrinsicValuePkr ?? null;
  const upside =
    target != null && ltp != null && ltp > 0
      ? ((target - ltp) / ltp) * 100
      : null;
  const method =
    active?.modelVersion != null
      ? `PSX-MF · ${active.modelVersion}`
      : "PSX-MF";
  const methodDetail =
    active?.targetPeUsed != null
      ? `Relative P/E: TTM EPS × ${fmtX(active.targetPeUsed, 1)} sector multiple${
          active.dividendFloorPkr != null
            ? " · blended 60/40 with dividend-yield floor (K_e = 13.5% − 4% g)"
            : ""
        }`
      : "Relative P/E: TTM EPS × sector-normal multiple";

  // Dated event tape: real stored rows only.
  const events: { date: string; label: string; tone: "bull" | "info" | "warn" | "bear" }[] = [];
  if (whale) {
    events.push({
      date: whale.trade_date,
      label: `WHALE_RADAR ${whale.signal_type} · vol ${whale.meta.vol_multiple?.toFixed(1) ?? "—"}×`,
      tone: "bull",
    });
  }
  if (active?.valuationStatus) {
    events.push({
      date: active.tradeDate,
      label: `Valuation pass: ${active.valuationStatus.replace(/_/g, " ")} (${fmtPct(active.valuationDiscountPct, 1)})`,
      tone:
        active.valuationStatus === "UNDERVALUED"
          ? "bull"
          : active.valuationStatus === "OVERVALUED"
            ? "bear"
            : "info",
    });
  }

  return (
    <DeskFrame
      title="Companies Explained — Institutional Research Notes"
      right={
        <span className="font-mono text-[10px] uppercase tracking-widest text-ghost">
          {candidates.length} COVERED · ALPHA-RANKED
        </span>
      }
      footer={
        <p className="font-mono text-[10px] leading-relaxed text-ghost">
          Target price = stored intrinsic value; the valuation method renders
          the exact model outputs (target P/E multiple, dividend floor). Moat
          scoring requires a qualitative ingestion feed — it is never
          synthesized. Catalysts list real stored events only.
        </p>
      }
    >
      {/* Coverage selector */}
      <div className="scroll-thin flex gap-1 overflow-x-auto border-b border-hairline px-2.5 py-1.5">
        {candidates.map((r) => (
          <button
            key={r.ticker}
            onClick={() => setSelected(r.ticker)}
            className={`shrink-0 rounded-[2px] px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider ring-1 ${
              active?.ticker === r.ticker
                ? "bg-info/10 text-info ring-info/30"
                : "bg-panel text-muted ring-hairline hover:text-ink"
            }`}
          >
            {r.ticker} {r.alphaScore.toFixed(0)}
          </button>
        ))}
      </div>

      {active && (
        <div className="wire-in">
          {/* Note header */}
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-hairline px-2.5 py-2">
            <button
              onClick={() => onInspect(active.ticker)}
              className="font-mono text-sm font-bold tracking-widest text-ink hover:text-info"
            >
              {active.ticker}
            </button>
            {fund?.sectorName && (
              <Badge tone="neutral">{fund.sectorName.toUpperCase()}</Badge>
            )}
            <span className="font-mono text-[11px] tabular-nums text-muted">
              LTP <span className="text-ink">{fmtPrice(ltp)}</span>
            </span>
            <span className="font-mono text-[11px] tabular-nums text-muted">
              TARGET <span className="text-bull">{fmtPrice(target)}</span>
            </span>
            <span
              className={`font-mono text-[11px] tabular-nums ${upside != null && upside >= 0 ? "text-bull" : "text-bear"}`}
            >
              UPSIDE {fmtPct(upside, 1)}
            </span>
            <span className="ml-auto flex items-center gap-1.5">
              <Badge tone="info">VALUATION: {method}</Badge>
              <Badge
                tone={active.alphaScore >= 70 ? "bull" : active.alphaScore >= 50 ? "info" : "warn"}
              >
                ALPHA {active.alphaScore.toFixed(0)}
              </Badge>
            </span>
          </div>

          <div className="grid gap-px bg-hairline md:grid-cols-2">
            {/* Valuation methodology */}
            <div className="bg-panel px-2.5 py-2">
              <p className="font-mono text-[9px] uppercase tracking-widest text-ghost">
                VALUATION METHOD
              </p>
              <p className="mt-1 text-[12px] leading-snug text-ink">
                {methodDetail}
              </p>
              <div className="mt-1.5 grid grid-cols-2 gap-px bg-hairline">
                {[
                  {
                    k: "TGT P/E MULTIPLE",
                    v: active.targetPeUsed != null ? fmtX(active.targetPeUsed, 1) : "—",
                  },
                  {
                    k: "DIVIDEND FLOOR",
                    v: fmtPrice(active.dividendFloorPkr),
                  },
                  {
                    k: "VALUATION SPREAD",
                    v: fmtPct(active.valuationDiscountPct, 1),
                  },
                  {
                    k: "STATUS",
                    v: active.valuationStatus.replace(/_/g, " "),
                  },
                ].map((s) => (
                  <div key={s.k} className="bg-panel px-1.5 py-1">
                    <p className="font-mono text-[9px] uppercase tracking-widest text-ghost">
                      {s.k}
                    </p>
                    <p className="font-mono text-[11px] tabular-nums text-ink">
                      {s.v}
                    </p>
                  </div>
                ))}
              </div>
            </div>

            {/* Catalyst timeline */}
            <div className="bg-panel px-2.5 py-2">
              <p className="font-mono text-[9px] uppercase tracking-widest text-ghost">
                CATALYST TIMELINE — STORED EVENTS
              </p>
              {events.length === 0 ? (
                <p className="mt-1 font-mono text-[11px] text-ghost">
                  NO STORED EVENTS FOR THIS NAME
                </p>
              ) : (
                <ol className="mt-1 space-y-1">
                  {events.map((e, i) => (
                    <li key={`${e.date}-${i}`} className="flex items-center gap-2">
                      <span className="font-mono text-[10px] tabular-nums text-ghost">
                        {e.date}
                      </span>
                      <Badge tone={e.tone}>{e.label}</Badge>
                    </li>
                  ))}
                </ol>
              )}
              <p className="mt-2 font-mono text-[9px] uppercase tracking-widest text-ghost">
                MOAT ANALYSIS
              </p>
              <p className="mt-0.5 font-mono text-[11px] text-warn">
                NOT SCORED — QUALITATIVE FEED PENDING (NEVER SYNTHESIZED)
              </p>
            </div>
          </div>

          {/* Signal narrative — real rationales */}
          {whale && (
            <div className="border-t border-hairline px-2.5 py-2">
              <p className="font-mono text-[9px] uppercase tracking-widest text-ghost">
                DESK NARRATIVE — LIVE SIGNAL RATIONALE
              </p>
              <p className="mt-0.5 text-[12px] leading-snug text-muted">
                {whale.rationale}
              </p>
            </div>
          )}
        </div>
      )}
    </DeskFrame>
  );
}
