"use client";

import { useMemo, useState } from "react";
import {
  Badge,
  DataTable,
  DeskFrame,
  DivergeBar,
  IdleState,
  Row,
  type Tone,
} from "@/components/ui/primitives";
import { fmtPct } from "@/components/ui/format";
import { computeAmihudStats, type EodPoint } from "@/lib/deskQueries";

interface Props {
  eod?: EodPoint[];
  sectorMap?: Map<string, string>;
  sessionDate?: string | null;
}

const MIN_SESSIONS = 30;
const AMIHUD_WINDOW = 20;
const EPSILON = 1e-9;

interface SessionBreadth {
  tradeDate: string;
  adv: number;
  dec: number;
  unch: number;
  advPkr: number;
  decPkr: number;
}

function fmtIntSmart(v: number | null): string {
  return v == null ? "—" : Math.round(v).toLocaleString("en-US");
}

function fmtPkrAdaptive(v: number | null): string {
  if (v == null) return "—";
  const b = Math.abs(v) / 1e9;
  if (b >= 1) return `${(v / 1e9).toFixed(2)}B`;
  const m = Math.abs(v) / 1e6;
  if (m >= 1) return `${(v / 1e6).toFixed(1)}M`;
  return `${Math.round(v).toLocaleString("en-US")}`;
}

function fmtAmihud(v: number | null): string {
  if (v == null) return "—";
  return v >= 100 ? v.toFixed(0) : v >= 10 ? v.toFixed(1) : v.toFixed(2);
}

function chgTone(v: number | null): string {
  if (v == null) return "text-ghost";
  return v > EPSILON ? "text-bull" : v < -EPSILON ? "text-bear" : "text-muted";
}

function tierTone(tier: string): Tone {
  if (tier.startsWith("ILLIQUID")) return "bear";
  if (tier.startsWith("THIN")) return "warn";
  if (tier.startsWith("TRAP")) return "bear";
  if (tier.startsWith("INSTITUTIONAL")) return "bull";
  return "neutral";
}

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

function Gauge({ frac, positive }: { frac: number; positive: boolean }) {
  const w = Math.max(0, Math.min(1, frac)) * 100;
  return (
    <div className="h-1 w-full bg-hairline">
      <div
        className={`h-1 ${positive ? "bg-bull" : "bg-bear"}`}
        style={{ width: `${w}%` }}
      />
    </div>
  );
}

function netToneCls(v: number): string {
  return v > 0 ? "text-bull" : v < 0 ? "text-bear" : "text-muted";
}

export default function MarketBreadthDesk({ eod = [], sectorMap = new Map(), sessionDate }: Props) {
  const [openExtremes, setOpenExtremes] = useState(false);
  const [openAmihud, setOpenAmihud] = useState(false);

  const model = useMemo(() => {
    if (eod.length === 0) return null;

    const byTicker = new Map<string, EodPoint[]>();
    for (const r of eod) {
      const arr = byTicker.get(r.ticker);
      if (arr) arr.push(r);
      else byTicker.set(r.ticker, [r]);
    }

    const allDates = Array.from(new Set(eod.map((r) => r.tradeDate)))
      .sort()
      .reverse();

    // 1. Raw Breadth Computation for every date
    const rawBreadth: SessionBreadth[] = allDates.map((d) => {
      const adv = { n: 0, pkr: 0 };
      const dec = { n: 0, pkr: 0 };
      let unch = 0;
      for (const rows of byTicker.values()) {
        const series = rows
          .filter((r) => r.tradeDate <= d && r.close != null)
          .sort((a, b) => (a.tradeDate < b.tradeDate ? -1 : 1));
        if (series.length < 2) continue;
        const onDate = series[series.length - 1];
        const base = series[series.length - 2].close;
        if (base == null || base <= EPSILON || onDate.close == null) continue;
        const chg = onDate.close - base;
        const pkr = (onDate.volume ?? 0) * onDate.close;
        if (chg > EPSILON) {
          adv.n += 1;
          adv.pkr += pkr;
        } else if (chg < -EPSILON) {
          dec.n += 1;
          dec.pkr += pkr;
        } else {
          unch += 1;
        }
      }
      return { tradeDate: d, adv: adv.n, dec: dec.n, unch, advPkr: adv.pkr, decPkr: dec.pkr };
    });

    // 2. HARD FILTER: Discard 15-Sep (adhoora 1-trade record) aur weekends (0 volume)
    // Rule: Session must have traded turnover > 20M PKR AND at least 2 active moving tickers (adv + dec >= 2)
    const validBreadth = rawBreadth.filter((b) => {
      if (sessionDate && b.tradeDate > sessionDate) return false;
      const totalVolumePkr = b.advPkr + b.decPkr;
      const activeTickers = b.adv + b.dec;
      return totalVolumePkr >= 20_000_000 && activeTickers >= 2;
    });

    const displayBreadth = (validBreadth.length > 0 ? validBreadth : rawBreadth).slice(0, 5).reverse();
    const today = displayBreadth[displayBreadth.length - 1];
    const latest = today ? today.tradeDate : allDates[0];

    const total = today ? today.adv + today.dec + today.unch : 0;
    const aDRatio = today && today.dec > 0 ? today.adv / today.dec : null;
    const advPct = total > 0 ? (today.adv / total) * 100 : null;
    const decPct = total > 0 ? (today.dec / total) * 100 : null;
    const vwAdv = today && today.advPkr + today.decPkr > 0
      ? (today.advPkr / (today.advPkr + today.decPkr)) * 100
      : null;

    const pumpDivergence = today != null && vwAdv != null && today.adv > today.dec && vwAdv <= 40;

    // 3. Per-ticker metrics up to the latest clean session
    interface TickerStat {
      ticker: string;
      sessions: number;
      latestClose: number | null;
      chg5dPct: number | null;
      hi200: number | null;
      lo200: number | null;
      atHigh: boolean;
      atLow: boolean;
      amihud: number | null;
      medTurnoverPkr: number | null;
    }
    const stats: TickerStat[] = [];
    for (const [ticker, rows] of byTicker) {
      const chrono = rows
        .filter((r) => r.tradeDate <= latest)
        .sort((a, b) => (a.tradeDate < b.tradeDate ? -1 : a.tradeDate > b.tradeDate ? 1 : 0));
      const withClose = chrono.filter((r) => r.close != null && r.close > 0);
      if (withClose.length < MIN_SESSIONS) continue;
      const closes = withClose.map((r) => r.close as number);
      const latestClose = closes[closes.length - 1];
      const hi200 = Math.max(...closes);
      const lo200 = Math.min(...closes);
      const base5 = closes.length >= 5 ? closes[closes.length - 5] : null;
      const chg5dPct =
        base5 != null && base5 > 0 ? ((latestClose - base5) / base5) * 100 : null;

      const { amihud, medianTurnoverPkr } = computeAmihudStats(
        withClose.map((r) => ({ close: r.close, volume: r.volume })),
        AMIHUD_WINDOW,
        10
      );

      stats.push({
        ticker,
        sessions: withClose.length,
        latestClose,
        chg5dPct,
        hi200,
        lo200,
        atHigh: latestClose >= hi200 - EPSILON,
        atLow: latestClose <= lo200 + EPSILON,
        amihud,
        medTurnoverPkr: medianTurnoverPkr,
      });
    }

    const newHighs = stats
      .filter((s) => s.atHigh)
      .sort((a, b) => (b.chg5dPct ?? 0) - (a.chg5dPct ?? 0));
    const newLows = stats
      .filter((s) => s.atLow)
      .sort((a, b) => (a.chg5dPct ?? 0) - (b.chg5dPct ?? 0));

    const ranked = stats.filter(
      (s): s is TickerStat & { amihud: number } => s.amihud != null
    );
    const amihudRows = ranked.map((s) => {
      const v = s.amihud as number;
      const tier =
        v >= 50
          ? "TRAP — BRUTAL SLIPPAGE"
          : v >= 10
            ? "ILLIQUID — HIGH IMPACT"
            : v >= 1
              ? "THIN — MODERATE IMPACT"
              : "INSTITUTIONAL — LIQUID";
      return { ...s, tier };
    });
    const liquidCount = amihudRows.filter((r) => r.amihud < 1).length;
    const trapCount = amihudRows.filter((r) => r.amihud >= 10).length;

    return {
      latest,
      sessionCount: displayBreadth.length,
      breadth: displayBreadth,
      today,
      total,
      aDRatio,
      advPct,
      decPct,
      vwAdv,
      pumpDivergence,
      newHighs,
      newLows,
      amihudRows,
      liquidCount,
      trapCount,
      rankedCount: ranked.length,
    };
  }, [eod, sessionDate]);

  if (eod.length === 0) {
    return (
      <DeskFrame title="Market Breadth & Liquidity Matrix">
        <IdleState
          tone="warn"
          headline="[BREADTH DESK: AWAITING EOD HISTORY]"
          detail="psx_daily_eod has no rows — run the pipeline EOD pass to light up breadth, extremes and Amihud ranks."
        />
      </DeskFrame>
    );
  }

  const m = model;
  if (m == null) return null;

  const maxSession5d = Math.max(
    1,
    ...m.breadth.map((b) => Math.abs(b.adv - b.dec))
  );

  return (
    <DeskFrame
      title="Market Breadth & Liquidity Matrix"
      right={
        <span className="font-mono text-[10px] uppercase tracking-wider text-ghost">
          SESSION {m.latest} · CLEAN HISTORICAL SESSIONS · {m.total} ACTIVE
        </span>
      }
      footer={
        <p className="font-mono text-[10px] leading-relaxed text-ghost">
          A/D/U = closes strictly above/below the prior session close across
          the active universe. VW A/D = PKR turnover share of advancing vs
          declining names; a price-advancing session with VW-advancing ≤40% is
          flagged SHALLOW-PUMP DIVERGENCE. Extremes = latest close at the
          highest/lowest level across all stored sessions. Amihud =
          mean(|daily return| ÷ PKR turnover) ×1e6 over trailing 20 sessions.
        </p>
      }
    >
      <PanelHeader
        label="ADVANCE / DECLINE / UNCHANGED — VOLUME-WEIGHTED"
        right={`5-SESSION TREND · ${m.latest}`}
      />
      <div className="grid grid-cols-2 gap-px bg-hairline sm:grid-cols-3 lg:grid-cols-6">
        <div className="bg-obsidian px-2.5 py-1.5">
          <p className="font-mono text-[9px] uppercase tracking-widest text-ghost">
            ADVANCING
          </p>
          <p className="font-mono text-lg font-bold tabular-nums text-bull">
            {fmtIntSmart(m.today?.adv ?? null)}
          </p>
          <p className="font-mono text-[10px] tabular-nums text-muted">
            {m.advPct == null ? "—" : `${m.advPct.toFixed(0)}%`} of universe
          </p>
        </div>
        <div className="bg-obsidian px-2.5 py-1.5">
          <p className="font-mono text-[9px] uppercase tracking-widest text-ghost">
            DECLINING
          </p>
          <p className="font-mono text-lg font-bold tabular-nums text-bear">
            {fmtIntSmart(m.today?.dec ?? null)}
          </p>
          <p className="font-mono text-[10px] tabular-nums text-muted">
            {m.decPct == null ? "—" : `${m.decPct.toFixed(0)}%`} of universe
          </p>
        </div>
        <div className="bg-obsidian px-2.5 py-1.5">
          <p className="font-mono text-[9px] uppercase tracking-widest text-ghost">
            UNCHANGED
          </p>
          <p className="font-mono text-lg font-bold tabular-nums text-muted">
            {fmtIntSmart(m.today?.unch ?? null)}
          </p>
          <p className="font-mono text-[10px] tabular-nums text-muted">
            flat vs prior close
          </p>
        </div>
        <div className="bg-obsidian px-2.5 py-1.5">
          <p className="font-mono text-[9px] uppercase tracking-widest text-ghost">
            A/D RATIO
          </p>
          <p
            className={`font-mono text-lg font-bold tabular-nums ${
              m.aDRatio == null ? "text-ghost" : m.aDRatio >= 1 ? "text-bull" : "text-bear"
            }`}
          >
            {m.aDRatio == null ? "—" : m.aDRatio.toFixed(2)}
          </p>
          <p className="font-mono text-[10px] tabular-nums text-muted">
            advancing per decliner
          </p>
        </div>
        <div className="bg-obsidian px-2.5 py-1.5">
          <p className="font-mono text-[9px] uppercase tracking-widest text-ghost">
            VW ADVANCING %
          </p>
          <p
            className={`font-mono text-lg font-bold tabular-nums ${
              m.vwAdv == null ? "text-ghost" : m.vwAdv >= 50 ? "text-bull" : "text-warn"
            }`}
          >
            {m.vwAdv == null ? "—" : `${m.vwAdv.toFixed(0)}%`}
          </p>
          <Gauge
            frac={(m.vwAdv ?? 0) / 100}
            positive={(m.vwAdv ?? 0) >= 50}
          />
        </div>
        <div className="bg-obsidian px-2.5 py-1.5">
          <p className="font-mono text-[9px] uppercase tracking-widest text-ghost">
            SIGNAL
          </p>
          <p
            className={`mt-1 font-mono text-[11px] font-bold uppercase tracking-wider ${
              m.pumpDivergence ? "text-warn" : "text-ghost"
            }`}
          >
            {m.pumpDivergence ? "SHALLOW-PUMP DIVERGENCE" : "BREADTH CONFIRMS"}
          </p>
          <p className="mt-1 font-mono text-[9px] leading-snug text-ghost">
            {m.pumpDivergence
              ? "Price advancing on weak volume-weighted breadth"
              : "Volume-weighted flow supports the tape"}
          </p>
        </div>
      </div>

      <DataTable
        minWidth={640}
        columns={[
          { label: "Session", width: "16%" },
          { label: "Adv", align: "right" },
          { label: "Dec", align: "right" },
          { label: "Unch", align: "right" },
          { label: "A/D", align: "right" },
          { label: "Net", align: "right" },
          { label: "Adv PKR Turnover", align: "right" },
          { label: "Dec PKR Turnover", align: "right" },
          { label: "Skew", align: "right", width: "18%" },
        ]}
      >
        {m.breadth.map((b) => {
          const net = b.adv - b.dec;
          const ratio = b.dec > 0 ? b.adv / b.dec : null;
          return (
            <Row key={b.tradeDate}>
              <td className="px-2.5 py-1 font-mono text-[11px] tabular-nums text-ink">
                {b.tradeDate}
              </td>
              <td className="px-2 py-1 text-right font-mono text-[11px] tabular-nums text-bull">
                {b.adv}
              </td>
              <td className="px-2 py-1 text-right font-mono text-[11px] tabular-nums text-bear">
                {b.dec}
              </td>
              <td className="px-2 py-1 text-right font-mono text-[11px] tabular-nums text-muted">
                {b.unch}
              </td>
              <td className="px-2 py-1 text-right font-mono text-[11px] tabular-nums text-ink">
                {ratio == null ? "—" : ratio.toFixed(2)}
              </td>
              <td
                className={`px-2 py-1 text-right font-mono text-[11px] font-semibold tabular-nums ${netToneCls(net)}`}
              >
                {net > 0 ? `+${net}` : net}
              </td>
              <td className="px-2 py-1 text-right font-mono text-[11px] tabular-nums text-muted">
                {fmtPkrAdaptive(b.advPkr)}
              </td>
              <td className="px-2 py-1 text-right font-mono text-[11px] tabular-nums text-muted">
                {fmtPkrAdaptive(b.decPkr)}
              </td>
              <td className="px-2 py-1">
                <DivergeBar value={net} maxAbs={maxSession5d} />
              </td>
            </Row>
          );
        })}
      </DataTable>

      <PanelHeader
        label="NEW 200-SESSION EXTREMES — 52-WEEK HIGHS / LOWS"
        right={`${m.newHighs.length} NEW HIGHS · ${m.newLows.length} NEW LOWS`}
      />
      {m.newHighs.length === 0 && m.newLows.length === 0 ? (
        <IdleState
          headline="[EXTREMES: NO NAMES AT STORED-HISTORY EXTREMES THIS SESSION]"
          tone="info"
        />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-px bg-hairline">
            <button
              onClick={() => setOpenExtremes((v) => !v)}
              className="flex items-center justify-between bg-obsidian px-2.5 py-1.5 text-left hover:bg-hoverline"
            >
              <span className="font-mono text-[10px] uppercase tracking-widest text-bull">
                NEW HIGHS ({m.newHighs.length})
              </span>
              <span className="font-mono text-[10px] text-ghost">
                {openExtremes ? "HIDE" : "SHOW"}
              </span>
            </button>
            <button
              onClick={() => setOpenExtremes((v) => !v)}
              className="flex items-center justify-between bg-obsidian px-2.5 py-1.5 text-left hover:bg-hoverline"
            >
              <span className="font-mono text-[10px] uppercase tracking-widest text-bear">
                NEW LOWS ({m.newLows.length})
              </span>
              <span className="font-mono text-[10px] text-ghost">
                {openExtremes ? "HIDE" : "SHOW"}
              </span>
            </button>
          </div>
          {openExtremes && (
            <DataTable
              minWidth={620}
              columns={[
                { label: "Ticker", width: "16%" },
                { label: "Sector", width: "30%" },
                { label: "LTP", align: "right" },
                { label: "Extreme", align: "right" },
                { label: "5D %", align: "right" },
                { label: "Type", align: "right" },
              ]}
            >
              {[
                ...m.newHighs.map((s) => ({ s, kind: "52W HIGH" as const })),
                ...m.newLows.map((s) => ({ s, kind: "52W LOW" as const })),
              ].map(({ s, kind }) => (
                <Row key={`${s.ticker}-${kind}`}>
                  <td className="px-2.5 py-1 font-mono text-[11px] font-semibold text-ink">
                    {s.ticker}
                  </td>
                  <td
                    className="max-w-[220px] truncate px-2 py-1 font-mono text-[10px] uppercase tracking-wider text-muted"
                    title={sectorMap.get(s.ticker) ?? undefined}
                  >
                    {sectorMap.get(s.ticker) ?? "—"}
                  </td>
                  <td className="px-2 py-1 text-right font-mono text-[11px] tabular-nums text-ink">
                    {s.latestClose?.toFixed(2) ?? "—"}
                  </td>
                  <td className="px-2 py-1 text-right font-mono text-[11px] tabular-nums text-ink">
                    {(kind === "52W HIGH" ? s.hi200 : s.lo200)?.toFixed(2) ?? "—"}
                  </td>
                  <td className={`px-2 py-1 text-right font-mono text-[11px] tabular-nums ${chgTone(s.chg5dPct)}`}>
                    {fmtPct(s.chg5dPct, 1)}
                  </td>
                  <td className="px-2 py-1 text-right">
                    <Badge tone={kind === "52W HIGH" ? "bull" : "bear"}>{kind}</Badge>
                  </td>
                </Row>
              ))}
            </DataTable>
          )}
        </>
      )}

      <PanelHeader
        label="AMIHUD ILLIQUIDITY MATRIX — |RET| / PKR TURNOVER"
        right={`${m.rankedCount} RANKED · ${m.liquidCount} INSTITUTIONAL · ${m.trapCount} TRAPS`}
      />
      {m.amihudRows.length === 0 ? (
        <IdleState
          headline="[AMIHUD: INSUFFICIENT VOLUME HISTORY FOR RANKING]"
          detail="Names need ≥10 sessions with positive turnover in the trailing 20 — none qualify yet."
          tone="info"
        />
      ) : (
        <>
          <button
            onClick={() => setOpenAmihud((v) => !v)}
            className="flex w-full items-center justify-between bg-obsidian px-2.5 py-1.5 text-left hover:bg-hoverline"
          >
            <span className="font-mono text-[10px] uppercase tracking-widest text-ghost">
              {openAmihud
                ? "HIDE FULL MATRIX"
                : `SHOW TOP SLIPPAGE TRAPS + INSTITUTIONAL NAMES (${m.rankedCount})`}
            </span>
            <span className="font-mono text-[10px] text-ghost">
              {openAmihud ? "COLLAPSE" : "EXPAND"}
            </span>
          </button>
          <DataTable
            minWidth={760}
            columns={[
              { label: "#", width: "6%" },
              { label: "Ticker", width: "12%" },
              { label: "Sector", width: "22%" },
              { label: "LTP", align: "right" },
              { label: "Amihud", align: "right" },
              { label: "Med Turnover", align: "right" },
              { label: "5D %", align: "right" },
              { label: "Tier", align: "right", width: "20%" },
            ]}
          >
            {(openAmihud ? m.amihudRows : m.amihudRows.slice(0, 8)).map((r, i) => (
              <Row key={r.ticker}>
                <td className="px-2.5 py-1 font-mono text-[10px] tabular-nums text-ghost">
                  {i + 1}
                </td>
                <td className="px-2 py-1 font-mono text-[11px] font-semibold text-ink">
                  {r.ticker}
                </td>
                <td
                  className="max-w-[200px] truncate px-2 py-1 font-mono text-[10px] uppercase tracking-wider text-muted"
                  title={sectorMap.get(r.ticker) ?? undefined}
                >
                  {sectorMap.get(r.ticker) ?? "—"}
                </td>
                <td className="px-2 py-1 text-right font-mono text-[11px] tabular-nums text-ink">
                  {r.latestClose?.toFixed(2) ?? "—"}
                </td>
                <td
                  className={`px-2 py-1 text-right font-mono text-[11px] font-semibold tabular-nums ${
                    (r.amihud ?? 0) >= 50
                      ? "text-bear"
                      : (r.amihud ?? 0) >= 10
                        ? "text-warn"
                        : (r.amihud ?? 0) >= 1
                          ? "text-muted"
                          : "text-bull"
                  }`}
                >
                  {fmtAmihud(r.amihud)}
                </td>
                <td className="px-2 py-1 text-right font-mono text-[11px] tabular-nums text-muted">
                  {fmtPkrAdaptive(r.medTurnoverPkr)}
                </td>
                <td className={`px-2 py-1 text-right font-mono text-[11px] tabular-nums ${chgTone(r.chg5dPct)}`}>
                  {fmtPct(r.chg5dPct, 1)}
                </td>
                <td className="px-2 py-1 text-right">
                  <Badge tone={tierTone(r.tier)}>{r.tier}</Badge>
                </td>
              </Row>
            ))}
          </DataTable>
        </>
      )}
    </DeskFrame>
  );
}