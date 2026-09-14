"use client";

import { useMemo } from "react";
import { Badge, DeskFrame, IdleState } from "@/components/ui/primitives";
import { fmtPct, fmtPkrB, fmtPkrM } from "@/components/ui/format";
import type {
  Barometer,
  DisclosureRow,
  KiborRow,
  MtsRow,
  RolloverRow,
  RotationRow,
  WhaleRow,
} from "@/lib/queries";

/**
 * Terminal wire: every item is DERIVED from stored, real data — NCCPL flows,
 * MTS leverage prints, futures basis inversions, insider filings, RRG
 * regimes and rate-sensitivity screens. No scraped headlines, no synthetic
 * news: PSX/SBP textual disclosures are not licensed to us, so the wire
 * speaks only in quant events the database actually contains.
 */
export interface WireItem {
  id: string;
  timeTag: string;
  impact: "BULLISH" | "BEARISH" | "NEUTRAL";
  headline: string;
  tickers: string[];
  sectors: string[];
  /** EPS sensitivity context when the item has rate/earnings math behind it. */
  sensitivity?: string;
  source: string;
}

interface Props {
  barometer: Barometer | null;
  whaleRows: WhaleRow[];
  mtsRows: MtsRow[];
  rolloverRows: RolloverRow[];
  disclosures: DisclosureRow[];
  rotation: RotationRow[];
  kibor: KiborRow[];
}

export default function MarketInsightsDesk({
  barometer,
  whaleRows,
  mtsRows,
  rolloverRows,
  disclosures,
  rotation,
  kibor,
}: Props) {
  const items = useMemo<WireItem[]>(() => {
    const out: WireItem[] = [];

    if (barometer) {
      const bull = barometer.institutionalNet > 0;
      out.push({
        id: "flows",
        timeTag: barometer.tradeDate,
        impact:
          barometer.institutionalNet === 0
            ? "NEUTRAL"
            : bull
              ? "BULLISH"
              : "BEARISH",
        headline: `NCCPL institutions net ${fmtPkrB(barometer.institutionalNet)} · retail ${fmtPkrB(barometer.retailNet)} — ${
          barometer.divergence === "SMART_MONEY_ACCUMULATION"
            ? "smart money accumulating against retail supply"
            : barometer.divergence === "RETAIL_TRAP_RISK"
              ? "retail buying into institutional distribution"
              : "flows aligned"
        }`,
        tickers: [],
        sectors: [],
        source: "nccpl_fipi_lipi",
      });
    }

    for (const w of whaleRows.slice(0, 6)) {
      out.push({
        id: `whale-${w.ticker}`,
        timeTag: w.trade_date,
        impact: "BULLISH",
        headline: `${w.meta.conviction ?? "MODERATE"}-conviction stealth accumulation · vol ${w.meta.vol_multiple?.toFixed(1) ?? "—"}× SMA20${w.meta.ndm_confirmed ? " · NDM-confirmed off-market prints" : ""}`,
        tickers: [w.ticker],
        sectors: w.meta.sector ? [w.meta.sector] : [],
        source: "signals_computed/WHALE_RADAR",
      });
    }

    for (const m of mtsRows.slice(0, 6)) {
      out.push({
        id: `mts-${m.ticker}`,
        timeTag: m.tradeDate,
        impact: "BEARISH",
        headline: `MTS leverage ${m.utilizationPct != null ? `${m.utilizationPct.toFixed(0)}% of cap` : "print"} on ${m.ticker} — value ${fmtPkrB(m.mtsValuePkr)}${m.valueDropPct != null ? ` · ${fmtPct(m.valueDropPct, 1)} unwind` : ""}: liquidation-cascade risk elevated`,
        tickers: [m.ticker],
        sectors: [],
        source: "nccpl_mts_leverage",
      });
    }

    for (const r of rolloverRows.slice(0, 5)) {
      out.push({
        id: `roll-${r.ticker}`,
        timeTag: r.tradeDate,
        impact: r.stance === "SHORT_BIAS" ? "BEARISH" : "NEUTRAL",
        headline: `Futures basis ${r.basisPct?.toFixed(2) ?? "—"}% on ${r.futuresSymbol ?? r.ticker}${r.basisPrevPct != null ? ` (prev ${r.basisPrevPct.toFixed(2)}%)` : ""} — ${r.stance === "SHORT_BIAS" ? "basis inversion: delivery pressure" : "rollover flow normal"}`,
        tickers: [r.ticker],
        sectors: [],
        source: "signals_computed/ROLLOVER_DESK",
      });
    }

    const ultra = disclosures.filter(
      (d) => d.conviction === "ULTRA_HIGH" && d.tradeType === "BUY"
    );
    for (const d of ultra.slice(0, 5)) {
      out.push({
        id: `disc-${d.ticker}-${d.insiderName}`,
        timeTag: d.tradeDate,
        impact: "BULLISH",
        headline: `${d.designation} ${d.insiderName} bought ${fmtPkrB(d.notionalPkr)} of ${d.ticker} — ULTRA_HIGH conviction filing`,
        tickers: [d.ticker],
        sectors: [],
        sensitivity: "Insider buys ≥ 10M PKR by sponsors/directors historically front-run re-ratings",
        source: "psx_insider_disclosures",
      });
    }

    const leading = rotation.filter((r) => r.quadrant === "LEADING").slice(0, 4);
    if (leading.length > 0) {
      out.push({
        id: "rrg",
        timeTag: leading[0].tradeDate,
        impact: "BULLISH",
        headline: `RRG leadership: ${leading.map((r) => r.sectorName).join(", ")} holding LEADING vs KSE-100`,
        tickers: leading
          .map((r) => r.topLeaderTicker)
          .filter((t): t is string => t != null),
        sectors: leading.map((r) => r.sectorName),
        source: "psx_sector_rotation",
      });
    }

    const topKibor = kibor.slice(0, 3);
    if (topKibor.length > 0) {
      out.push({
        id: "kibor",
        timeTag: topKibor[0].tradeDate,
        impact: "BULLISH",
        headline: `Rate-cut leverage screen: ${topKibor.map((k) => k.ticker).join(" · ")} lead EPS expansion on a 300bps easing cycle`,
        tickers: topKibor.map((k) => k.ticker),
        sectors: topKibor
          .map((k) => k.sectorName)
          .filter((s): s is string => s != null),
        sensitivity: `ΔEPS/100bps: ${topKibor
          .map((k) => `${k.ticker} ${k.epsImpact100bpsPkr != null ? fmtPkrM(k.epsImpact100bpsPkr * 1e6, 2) : "—"}`)
          .join(" · ")}`,
        source: "psx_kibor_sensitivity",
      });
    }

    return out;
  }, [barometer, whaleRows, mtsRows, rolloverRows, disclosures, rotation, kibor]);

  return (
    <DeskFrame
      title="Market Insights — EPS Impact Wire"
      right={
        <span className="font-mono text-[10px] uppercase tracking-widest text-ghost">
          {items.length} ITEMS · QUANT-EVENT FEED
        </span>
      }
      footer={
        <p className="font-mono text-[10px] leading-relaxed text-ghost">
          The wire publishes only events present in the terminal&apos;s own
          tables (flows, leverage, basis, filings, regimes, rate screens).
          Textual PSX/SBP releases are not ingested — nothing here is
          paraphrased or synthesized.
        </p>
      }
    >
      {items.length === 0 ? (
        <IdleState
          headline="[WIRE: NO QUANT EVENTS STORED YET]"
          detail="Items appear as pipeline passes populate flows, leverage, filings and rotation tables."
        />
      ) : (
        <ol>
          {items.map((it) => (
            <li
              key={it.id}
              className="wire-in border-b border-hairline px-2.5 py-1.5 hover:bg-hoverline"
            >
              <div className="flex items-center gap-2">
                <Badge
                  tone={
                    it.impact === "BULLISH"
                      ? "bull"
                      : it.impact === "BEARISH"
                        ? "bear"
                        : "neutral"
                  }
                >
                  {it.impact}
                </Badge>
                <span className="font-mono text-[10px] tabular-nums text-ghost">
                  {it.timeTag}
                </span>
                <span className="ml-auto font-mono text-[9px] uppercase tracking-widest text-ghost">
                  {it.source}
                </span>
              </div>
              <p className="mt-0.5 text-[12px] leading-snug text-ink">
                {it.headline}
              </p>
              {(it.tickers.length > 0 || it.sectors.length > 0) && (
                <p className="mt-0.5 font-mono text-[10px] uppercase tracking-wider text-muted">
                  {it.sectors.length > 0 && `SECTORS: ${it.sectors.join(", ")} `}
                  {it.tickers.length > 0 && `· TICKERS: ${it.tickers.join(" ")}`}
                </p>
              )}
              {it.sensitivity && (
                <p className="mt-0.5 font-mono text-[10px] text-warn">
                  {it.sensitivity}
                </p>
              )}
            </li>
          ))}
        </ol>
      )}
    </DeskFrame>
  );
}
