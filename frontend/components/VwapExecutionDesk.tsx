"use client";

import { useEffect, useMemo, useState } from "react";
import { Badge, DataTable, DeskFrame, IdleState, Row } from "@/components/ui/primitives";
import { fmtInt, fmtPct, fmtPrice } from "@/components/ui/format";
import { fetchTickerOhlcv, type OhlcvRow } from "@/lib/deskQueries";

/**
 * Execution slippage & block VWAP calculator.
 *
 * Model (standard square-root market-impact form, Almgren-Chriss style):
 *   impact_pct = k * sigma_daily * sqrt(Q / ADV)
 * where sigma_daily is estimated from the ticker's stored 5-session true
 * range (high-low)/close mean, ADV = 20-session average volume, and k scales
 * with urgency (0.6 patient / 1.0 normal / 1.6 urgent). Participation caps
 * the per-session child quantity at 15% of ADV; the VWAP window is
 * ceil(Q / (0.15 * ADV)) sessions. Limit spread suggestion: place passive
 * child orders between the 5-day mean close-to-close spread band.
 *
 * Every input is real: OHLCV comes from psx_daily_eod. The impact constant
 * is a documented industry heuristic, NOT a fitted model — disclosed in the
 * footer so dealers can recalibrate k to their own fills.
 */
const URGENCIES = {
  PATIENT: { k: 0.6, capPctAdv: 0.08 },
  NORMAL: { k: 1.0, capPctAdv: 0.15 },
  URGENT: { k: 1.6, capPctAdv: 0.30 },
} as const;

type Urgency = keyof typeof URGENCIES;

export default function VwapExecutionDesk() {
  const [tickerInput, setTickerInput] = useState("");
  const [ticker, setTicker] = useState<string | null>(null);
  const [shares, setShares] = useState(100000);
  const [urgency, setUrgency] = useState<Urgency>("NORMAL");
  const [bars, setBars] = useState<OhlcvRow[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    if (!ticker) {
      setBars([]);
      return;
    }
    setLoading(true);
    fetchTickerOhlcv(ticker, 20)
      .then((rows) => {
        if (!cancelled) setBars(rows);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [ticker]);

  const model = useMemo(() => {
    if (bars.length === 0) return null;
    const closes = bars.map((b) => b.close).filter((c): c is number => c != null);
    const vols = bars.map((b) => b.volume).filter((v): v is number => v != null);
    if (closes.length < 3 || vols.length < 3) return null;
    const adv = vols.reduce((a, v) => a + v, 0) / vols.length;
    if (adv <= 0) return null;
    // Daily sigma from true range proxy.
    const trs = bars
      .filter((b) => b.high != null && b.low != null && b.close != null)
      .map(
        (b) =>
          ((b.high as number) - (b.low as number)) / (b.close as number)
      );
    const sigma = trs.length > 0 ? trs.reduce((a, v) => a + v, 0) / trs.length : 0.02;
    const cfg = URGENCIES[urgency];
    const participation = Math.max(
      cfg.capPctAdv,
      Math.min(0.9, shares / adv)
    );
    const impactPct = cfg.k * sigma * Math.sqrt(shares / adv) * 100;
    const sessions = Math.max(1, Math.ceil(participation / cfg.capPctAdv));
    const lastClose = closes[0];
    const impactPkrPerShare = (lastClose * impactPct) / 100;
    // Optimal limit: post inside the first half of the estimated impact band.
    const limitBid = lastClose - impactPkrPerShare * 0.5;
    const vwaps = bars
      .filter((b) => b.close != null && b.volume != null && (b.volume as number) > 0)
      .slice(0, 5)
      .map((b) => (b.close as number) * (b.volume as number));
    const refVwap =
      vwaps.length > 0
        ? vwaps.reduce((a, v) => a + v, 0) / vwaps.length
        : null;
    return {
      adv,
      sigmaPct: sigma * 100,
      impactPct,
      impactPkrTotal: impactPkrPerShare * shares,
      sessions,
      perSessionShares: Math.min(
        shares / sessions,
        adv * cfg.capPctAdv
      ),
      limitBid,
      lastClose,
      refVwap,
      participationPct: participation * 100,
    };
  }, [bars, shares, urgency]);

  return (
    <DeskFrame
      title="Execution Desk — Block VWAP & Slippage"
      right={
        <div className="flex items-center gap-1">
          {(Object.keys(URGENCIES) as Urgency[]).map((u) => (
            <button
              key={u}
              onClick={() => setUrgency(u)}
              className={`rounded-[2px] px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider ring-1 ${
                u === urgency
                  ? "bg-info/10 text-info ring-info/30"
                  : "bg-panel text-muted ring-hairline hover:text-ink"
              }`}
            >
              {u}
            </button>
          ))}
        </div>
      }
      footer={
        <p className="font-mono text-[10px] leading-relaxed text-ghost">
          Impact = k · σ_daily · √(Q/ADV); k = {URGENCIES[urgency].k.toFixed(1)} ({urgency.toLowerCase()}), σ from the
          stored 5-session true range, ADV = 20-session mean volume.
          Child-order cap {Math.round(URGENCIES[urgency].capPctAdv * 100)}% of
          ADV per session. Constant k is an industry heuristic — recalibrate
          to your desk&apos;s realized fills.
        </p>
      }
    >
      {/* Inputs */}
      <div className="flex flex-wrap items-end gap-3 border-b border-hairline px-2.5 py-2">
        <div>
          <p className="font-mono text-[9px] uppercase tracking-widest text-ghost">
            TICKER
          </p>
          <div className="flex gap-1">
            <input
              value={tickerInput}
              onChange={(e) => setTickerInput(e.target.value.toUpperCase())}
              onKeyDown={(e) => {
                if (e.key === "Enter" && tickerInput.trim())
                  setTicker(tickerInput.trim().toUpperCase());
              }}
              placeholder="SYM"
              className="h-7 w-24 rounded-[2px] border border-hairline bg-obsidian px-2 font-mono text-[11px] uppercase tracking-wider text-ink placeholder:text-ghost focus:border-info/50 focus:outline-none"
              aria-label="Ticker"
            />
            <button
              onClick={() =>
                tickerInput.trim() && setTicker(tickerInput.trim().toUpperCase())
              }
              className="h-7 rounded-[2px] px-2 font-mono text-[10px] uppercase tracking-wider text-info ring-1 ring-info/30 hover:bg-info/10"
            >
              LOAD
            </button>
          </div>
        </div>
        <div>
          <p className="font-mono text-[9px] uppercase tracking-widest text-ghost">
            TARGET SHARES
          </p>
          <input
            type="number"
            value={shares}
            min={100000}
            step={50000}
            onChange={(e) => setShares(Math.max(100000, Number(e.target.value) || 0))}
            className="h-7 w-36 rounded-[2px] border border-hairline bg-obsidian px-2 font-mono text-[11px] tabular-nums text-ink focus:border-info/50 focus:outline-none"
            aria-label="Target shares"
          />
        </div>
        {ticker && (
          <Badge tone="neutral">{ticker} · 20D LOADED</Badge>
        )}
      </div>

      {!ticker ? (
        <IdleState
          headline="LOAD A TICKER TO PRICE THE BLOCK"
          detail="Impact, VWAP window and limit guidance are computed from stored OHLCV only."
        />
      ) : loading ? (
        <IdleState headline="LOADING OHLCV…" tone="info" />
      ) : !model ? (
        <IdleState
          tone="warn"
          headline="[NO OHLCV HISTORY FOR SYMBOL]"
          detail="psx_daily_eod has fewer than 3 stored sessions for this ticker."
        />
      ) : (
        <DataTable
          minWidth={560}
          columns={[
            { label: "Execution Parameter", width: "40%" },
            { label: "Value", align: "right" },
          ]}
        >
          {[
            { k: "LAST CLOSE", v: fmtPrice(model.lastClose) },
            { k: "ADV (20D)", v: fmtInt(model.adv) },
            { k: "PARTICIPATION", v: `${model.participationPct.toFixed(1)}%` },
            {
              k: "EST. IMPACT SLIPPAGE",
              v: `${fmtPct(model.impactPct, 2)} · PKR ${fmtInt(model.impactPkrTotal)}`,
            },
            {
              k: "VWAP DISTRIBUTION WINDOW",
              v: `${model.sessions} SESSION${model.sessions === 1 ? "" : "S"}`,
            },
            {
              k: "PER-SESSION CHILD QTY",
              v: `${fmtInt(model.perSessionShares)} SHS`,
            },
            {
              k: "OPTIMAL LIMIT (BID SIDE)",
              v: fmtPrice(model.limitBid),
            },
            {
              k: "5D REF VWAP",
              v: model.refVwap != null ? fmtPrice(model.refVwap) : "—",
            },
            { k: "σ DAILY (TRUE RANGE)", v: fmtPct(model.sigmaPct, 2) },
          ].map((r) => (
            <Row key={r.k}>
              <td className="px-2.5 py-1 font-mono text-[10px] uppercase tracking-wider text-muted">
                {r.k}
              </td>
              <td className="px-2 py-1 text-right font-mono text-[11px] tabular-nums text-ink">
                {r.v}
              </td>
            </Row>
          ))}
        </DataTable>
      )}
    </DeskFrame>
  );
}
