"use client";

import { Badge, DeskFrame, IdleState } from "@/components/ui/primitives";
import { fmtPkrM } from "@/components/ui/format";
import type { WhaleRow, NdmRow } from "@/lib/queries";

/**
 * Brokerage-house order-flow attribution.
 *
 * PSX/NCCPL do not publish broker-code settlement data on any free feed we
 * ingest, so the desk has no live source yet. Rather than fabricate broker
 * codes, the desk renders its production-ready cluster-accumulation logic in
 * AWAITING state and surfaces the strongest free-feed proxy available: NDM
 * (negotiated/off-market) prints, which are institution-shaped flows, plus
 * whale convictions from the signal engine.
 *
 * When a broker table lands (psx_broker_clearing: trade_date, broker_code,
 * ticker, shares, value_pkr, side), CLUSTER ACCUMULATION ALERTS fire from
 * detectClusters() unchanged — the contract below is the schema.
 */
export interface BrokerClearingRow {
  tradeDate: string;
  brokerCode: string;
  ticker: string;
  shares: number;
  valuePkr: number;
  side: "BUY" | "SELL";
}

export interface ClusterAlert {
  ticker: string;
  brokers: string[];
  windowSessions: number;
  netValuePkr: number;
}

/** Production cluster detector — 3-session same-stock co-accumulation. */
export function detectClusters(
  rows: BrokerClearingRow[],
  windowSessions = 3,
  minBrokers = 3,
  minValuePkr = 25_000_000
): ClusterAlert[] {
  const dates = Array.from(new Set(rows.map((r) => r.tradeDate)))
    .sort()
    .reverse()
    .slice(0, windowSessions);
  const win = new Set(dates);
  const byTicker = new Map<
    string,
    { brokers: Set<string>; net: number }
  >();
  for (const r of rows) {
    if (!win.has(r.tradeDate) || r.side !== "BUY") continue;
    const b = byTicker.get(r.ticker.toUpperCase()) ?? {
      brokers: new Set<string>(),
      net: 0,
    };
    b.brokers.add(r.brokerCode);
    b.net += r.valuePkr;
    byTicker.set(r.ticker.toUpperCase(), b);
  }
  return Array.from(byTicker.entries())
    .filter(
      ([, b]) => b.brokers.size >= minBrokers && b.net >= minValuePkr
    )
    .map(([ticker, b]) => ({
      ticker,
      brokers: Array.from(b.brokers).sort(),
      windowSessions: dates.length,
      netValuePkr: b.net,
    }))
    .sort((a, b) => b.netValuePkr - a.netValuePkr);
}

interface Props {
  ndmRows: NdmRow[];
  whaleRows: WhaleRow[];
  /** Reserved for psx_broker_clearing when the feed lands. */
  brokerRows?: BrokerClearingRow[];
}

export default function BrokerFlowDesk({ ndmRows, whaleRows, brokerRows }: Props) {
  const hasBrokerFeed = brokerRows != null && brokerRows.length > 0;
  const clusters = hasBrokerFeed ? detectClusters(brokerRows) : [];

  const ndmByTicker = new Map<string, { count: number; value: number }>();
  for (const n of ndmRows) {
    const b = ndmByTicker.get(n.ticker.toUpperCase()) ?? { count: 0, value: 0 };
    b.count += 1;
    b.value += n.value ?? 0;
    ndmByTicker.set(n.ticker.toUpperCase(), b);
  }
  const ndmLeaders = Array.from(ndmByTicker.entries())
    .sort((a, b) => b[1].value - a[1].value)
    .slice(0, 8);

  return (
    <DeskFrame
      title="Broker Flow Attribution — Cluster Accumulation"
      right={
        hasBrokerFeed ? (
          <Badge tone="bull">{clusters.length} CLUSTERS</Badge>
        ) : (
          <Badge tone="ghost">FEED PENDING</Badge>
        )
      }
      footer={
        <p className="font-mono text-[10px] leading-relaxed text-ghost">
          Cluster rule: ≥3 distinct broker codes accumulating the same ticker
          within a 3-session window, net ≥ PKR 25M. Requires broker-code
          clearing data (paid NCCPL feed) — displayed proxies are NDM
          off-market prints and whale-conviction signals, both real stored
          flows. Detector is live and fires the moment psx_broker_clearing
          populates.
        </p>
      }
    >
      {!hasBrokerFeed && (
        <div className="border-b border-hairline px-2.5 py-2">
          <p className="font-mono text-[10px] uppercase tracking-widest text-warn">
            [BROKER FEED: AWAITING NCCPL CLEARING DATA]
          </p>
          <p className="mt-0.5 text-[11px] text-ghost">
            Cluster-accumulation detection is armed. Until the clearing feed
            lands, the desk shows the nearest institutional proxies.
          </p>
        </div>
      )}

      {clusters.length > 0 && (
        <div className="border-b border-hairline px-2.5 py-2">
          <p className="font-mono text-[9px] uppercase tracking-widest text-ghost">
            CLUSTER ACCUMULATION ALERTS
          </p>
          <ol className="mt-1 space-y-1">
            {clusters.map((c) => (
              <li
                key={c.ticker}
                className="flex flex-wrap items-center gap-2 rounded-[2px] bg-bull/5 px-2 py-1 ring-1 ring-bull/20"
              >
                <span className="font-mono text-[11px] font-semibold text-ink">
                  {c.ticker}
                </span>
                <Badge tone="bull">
                  {c.brokers.length} BROKERS · {c.windowSessions}S
                </Badge>
                <span className="font-mono text-[11px] tabular-nums text-bull">
                  {fmtPkrM(c.netValuePkr, 1)}
                </span>
                <span className="font-mono text-[9px] text-ghost">
                  {c.brokers.join(" ")}
                </span>
              </li>
            ))}
          </ol>
        </div>
      )}

      {/* NDM proxy: institution-shaped off-market flow */}
      <div className="px-2.5 py-2">
        <p className="font-mono text-[9px] uppercase tracking-widest text-ghost">
          NDM OFF-MARKET PRINT LEADERS (PROXY)
        </p>
        {ndmLeaders.length === 0 ? (
          <p className="mt-1 font-mono text-[10px] text-ghost">
            NO NDM PRINTS THIS SESSION
          </p>
        ) : (
          <ol className="mt-1 space-y-0.5">
            {ndmLeaders.map(([ticker, s]) => (
              <li
                key={ticker}
                className="flex items-center gap-2 font-mono text-[11px] tabular-nums"
              >
                <span className="w-16 font-semibold text-ink">{ticker}</span>
                <span className="text-muted">{s.count} prints</span>
                <span className="ml-auto text-info">
                  {fmtPkrM(s.value, 1)}
                </span>
              </li>
            ))}
          </ol>
        )}
      </div>

      {whaleRows.length > 0 && (
        <div className="border-t border-hairline px-2.5 py-2">
          <p className="font-mono text-[9px] uppercase tracking-widest text-ghost">
            WHALE-CONVICTION OVERLAP
          </p>
          <p className="mt-0.5 font-mono text-[11px] text-muted">
            {whaleRows
              .filter((w) => w.meta.conviction === "HIGH")
              .slice(0, 8)
              .map((w) => w.ticker)
              .join(" · ") || "NO HIGH-CONVICTION NAMES TODAY"}
          </p>
        </div>
      )}
    </DeskFrame>
  );
}
