"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import MarketBarometer from "@/components/MarketBarometer";
import StockBlotter from "@/components/StockBlotter";
import ArbitrageBlotter from "@/components/ArbitrageBlotter";
import NdmTape from "@/components/NdmTape";
import MomentumBlotter from "@/components/MomentumBlotter";
import MtsSqueezeBlotter from "@/components/MtsSqueezeBlotter";
import RolloverDeskBlotter from "@/components/RolloverDeskBlotter";
import EdgeAnalyticsBlotter from "@/components/EdgeAnalyticsBlotter";
import ResearchDeskBlotter from "@/components/ResearchDeskBlotter";
import SectorRotationBlotter from "@/components/SectorRotationBlotter";
import KiborSensitivityDesk from "@/components/KiborSensitivityDesk";
import InsiderConvictionDesk from "@/components/InsiderConvictionDesk";
import RiskDesk from "@/components/RiskDesk";
import SkeletonGrid from "@/components/SkeletonGrid";
import ErrorPanel from "@/components/ErrorPanel";
import {
  fetchActiveSessionDate,
  fetchArbitrageRows,
  fetchBacktestRows,
  fetchBarometer,
  fetchDisclosureRows,
  fetchFeedStatuses,
  fetchFuturesFeedOffline,
  fetchInsiderRows,
  fetchKiborRows,
  fetchMomentumRows,
  fetchMtsRows,
  fetchNdmTape,
  fetchResearchRows,
  fetchRolloverRows,
  fetchRotationRows,
  fetchSessionSignals,
  fetchWhaleCount,
  fetchWhaleRows,
  type ArbitrageRow,
  type BacktestRow,
  type Barometer,
  type DataStatus,
  type DisclosureRow,
  type InsiderRow,
  type KiborRow,
  type MtsRow,
  type NdmRow,
  type ResearchRow,
  type RolloverRow,
  type RotationRow,
  type WhaleRow,
} from "@/lib/queries";
import type { SizingSignal } from "@/lib/risk";
import type { SignalRow } from "@/lib/types";

type TabId =
  | "WHALE"
  | "RESEARCH"
  | "ROTATION"
  | "KIBOR"
  | "LEDGER"
  | "ARB"
  | "MOMENTUM"
  | "MTS"
  | "ROLLOVER"
  | "NDM"
  | "EDGE"
  | "RISK";

const TABS: { id: TabId; label: string }[] = [
  { id: "WHALE", label: "Whale Matrix" },
  { id: "RESEARCH", label: "Research" },
  { id: "ROTATION", label: "Rotation" },
  { id: "KIBOR", label: "📉 KIBOR Easing" },
  { id: "LEDGER", label: "👔 Insider Radar" },
  { id: "ARB", label: "Cash Arbitrage" },
  { id: "MOMENTUM", label: "Momentum" },
  { id: "MTS", label: "MTS Lev" },
  { id: "ROLLOVER", label: "Rollover" },
  { id: "NDM", label: "NDM Tape" },
  { id: "EDGE", label: "Edge Lab" },
  { id: "RISK", label: "Risk Desk" },
];

const WHALE_BANNER_MIN = 1;

export default function HomePage() {
  const [tab, setTab] = useState<TabId>("WHALE");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [barometer, setBarometer] = useState<Barometer | null>(null);
  const [latestDate, setLatestDate] = useState<string | null>(null);
  const [whaleRows, setWhaleRows] = useState<WhaleRow[]>([]);
  const [whaleCount, setWhaleCount] = useState(0);
  const [arbRows, setArbRows] = useState<ArbitrageRow[]>([]);
  const [futuresOffline, setFuturesOffline] = useState(false);
  const [momentumRows, setMomentumRows] = useState<SignalRow[]>([]);
  const [ndmRows, setNdmRows] = useState<NdmRow[]>([]);
  const [insiderRows, setInsiderRows] = useState<InsiderRow[]>([]);
  const [mtsRows, setMtsRows] = useState<MtsRow[]>([]);
  const [rolloverRows, setRolloverRows] = useState<RolloverRow[]>([]);
  const [insiderStatus, setInsiderStatus] = useState<DataStatus | null>(null);
  const [mtsStatus, setMtsStatus] = useState<DataStatus | null>(null);
  const [backtestRows, setBacktestRows] = useState<BacktestRow[]>([]);
  const [backtestMissing, setBacktestMissing] = useState(false);
  const [researchRows, setResearchRows] = useState<ResearchRow[]>([]);
  const [rotationRows, setRotationRows] = useState<RotationRow[]>([]);
  const [researchStatus, setResearchStatus] = useState<DataStatus | null>(null);
  const [rotationStatus, setRotationStatus] = useState<DataStatus | null>(null);
  const [kiborRows, setKiborRows] = useState<KiborRow[]>([]);
  const [disclosureRows, setDisclosureRows] = useState<DisclosureRow[]>([]);
  const [kiborStatus, setKiborStatus] = useState<DataStatus | null>(null);
  const [disclosureStatus, setDisclosureStatus] = useState<DataStatus | null>(null);
  const [sizingSignals, setSizingSignals] = useState<SizingSignal[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // Step 1: resolve the real trading session from stored data -
      // never the browser wall clock (weekends/holidays return 0 rows).
      const sessionDate = await fetchActiveSessionDate();
      if (!sessionDate) {
        setBarometer(null);
        setLatestDate(null);
        setWhaleRows([]);
        setWhaleCount(0);
        setArbRows([]);
        setMomentumRows([]);
        setNdmRows([]);
        setInsiderRows([]);
        setMtsRows([]);
        setRolloverRows([]);
        setInsiderStatus(null);
        setMtsStatus(null);
        setFuturesOffline(false);
        setBacktestRows([]);
        setBacktestMissing(false);
        setResearchRows([]);
        setRotationRows([]);
        setResearchStatus(null);
        setRotationStatus(null);
        setKiborRows([]);
        setDisclosureRows([]);
        setKiborStatus(null);
        setDisclosureStatus(null);
        setSizingSignals([]);
        return;
      }

      // Step 2: fan out every desk query, settled - one dead table never
      // takes down the terminal. Only the CORE probes (session date above,
      // whale rows below) may trip the global FEED ERROR screen; optional
      // desks render their own status pill on failure instead.
      const results = await Promise.allSettled([
        fetchBarometer(sessionDate), // 0
        fetchWhaleRows(sessionDate), // 1 core
        fetchWhaleCount(sessionDate), // 2 core
        fetchArbitrageRows(sessionDate), // 3
        fetchFuturesFeedOffline(), // 4
        fetchMomentumRows(sessionDate), // 5 core
        fetchNdmTape(sessionDate), // 6
        fetchInsiderRows(sessionDate), // 7
        fetchMtsRows(sessionDate), // 8
        fetchRolloverRows(sessionDate), // 9
        fetchFeedStatuses(), // 10
        fetchBacktestRows(), // 11
        fetchResearchRows(sessionDate), // 12
        fetchRotationRows(sessionDate), // 13
        fetchKiborRows(sessionDate), // 14
        fetchDisclosureRows(sessionDate), // 15
        fetchSessionSignals(sessionDate), // 16
      ]);

      const value = <T,>(index: number, fallback: T): T => {
        const result = results[index];
        return result.status === "fulfilled" ? (result.value as T) : fallback;
      };

      // Core feeds: whale/momentum rows come from signals_computed. If the
      // settled fetchers themselves rejected (auth/network), the terminal
      // cannot function - surface the global FEED ERROR.
      const coreFailures = [1, 2, 5].filter(
        (i) => results[i].status === "rejected"
      );
      if (coreFailures.length === 3) {
        const rejected = coreFailures
          .map((i) => results[i])
          .find((r): r is PromiseRejectedResult => r.status === "rejected");
        const reason = rejected?.reason;
        throw reason instanceof Error
          ? reason
          : new Error("Supabase query failed. Check configuration.");
      }

      const statuses = value(10, {
        insider: { feedPending: false, tableMissing: false, unreachable: true },
        mts: { feedPending: false, tableMissing: false, unreachable: true },
        research: { feedPending: false, tableMissing: false, unreachable: true },
        rotation: { feedPending: false, tableMissing: false, unreachable: true },
        kibor: { feedPending: false, tableMissing: false, unreachable: true },
        disclosures: { feedPending: false, tableMissing: false, unreachable: true },
      });
      const bt = value(11, { rows: [], tableMissing: false });

      setLatestDate(sessionDate);
      setBarometer(value(0, null));
      setWhaleRows(value(1, [] as WhaleRow[]));
      setWhaleCount(value(2, 0));
      setArbRows(value(3, [] as ArbitrageRow[]));
      setFuturesOffline(value(4, false));
      setMomentumRows(value(5, [] as SignalRow[]));
      setNdmRows(value(6, [] as NdmRow[]));
      setInsiderRows(value(7, [] as InsiderRow[]));
      setMtsRows(value(8, [] as MtsRow[]));
      setRolloverRows(value(9, [] as RolloverRow[]));
      setInsiderStatus(statuses.insider);
      setMtsStatus(statuses.mts);
      setBacktestRows(bt.rows);
      setBacktestMissing(bt.tableMissing);
      setResearchRows(value(12, [] as ResearchRow[]));
      setRotationRows(value(13, [] as RotationRow[]));
      setResearchStatus(statuses.research);
      setRotationStatus(statuses.rotation);
      setKiborRows(value(14, [] as KiborRow[]));
      setDisclosureRows(value(15, [] as DisclosureRow[]));
      setKiborStatus(statuses.kibor);
      setDisclosureStatus(statuses.disclosures);
      setSizingSignals(value(16, [] as SizingSignal[]));
      setError(null);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Supabase query failed. Check configuration."
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const whaleBannerRows = useMemo(
    () =>
      whaleRows.filter(
        (r) =>
          r.meta.ndm_confirmed === true ||
          (r.meta.conviction ?? "") === "HIGH"
      ),
    [whaleRows]
  );

  const momentumCount = momentumRows.length;
  const riskBadge = sizingSignals.filter((s) => s.stopLoss != null).length;

  const tabBadges: Record<TabId, number> = {
    WHALE: whaleRows.length,
    RESEARCH: researchRows.length,
    ROTATION: rotationRows.length,
    KIBOR: kiborRows.length,
    LEDGER: disclosureRows.length,
    ARB: arbRows.length,
    MOMENTUM: momentumCount,
    MTS: mtsRows.length,
    ROLLOVER: rolloverRows.length,
    NDM: ndmRows.length,
    EDGE: backtestRows.length,
    RISK: riskBadge,
  };

  // Consolidation: only render desks holding live data. The signals-derived
  // INSIDER tab is retired (the conviction LEDGER supersedes it), and the
  // LEDGER itself hides while its feed is empty. CASH ARBITRAGE, ROLLOVER
  // and MTS LEV appear only when their feed produced rows.
  const CONDITIONAL_TABS: ReadonlySet<TabId> = new Set<TabId>([
    "ARB",
    "ROLLOVER",
    "MTS",
    "LEDGER",
  ]);
  const visibleTabs = TABS.filter(
    (t) => !CONDITIONAL_TABS.has(t.id) || tabBadges[t.id] > 0
  );

  // Active tab fell back to a hidden desk (e.g. after REFRESH cleared its
  // rows) - snap back to the primary desk.
  const activeTab = visibleTabs.some((t) => t.id === tab) ? tab : "WHALE";

  return (
    <main className="mx-auto min-h-dvh w-full max-w-3xl bg-[#05070a] pb-10 text-zinc-200">
      {/* Command header */}
      <header className="border-b border-zinc-800 bg-[#0c1017] px-3 py-2">
        <div className="flex items-center justify-between gap-2">
          <h1 className="font-mono text-sm font-bold tracking-widest text-zinc-100">
            PSX QUANT TERMINAL
          </h1>
          <div className="flex items-center gap-2">
            {latestDate && (
              <span className="rounded border border-zinc-800 bg-[#05070a] px-1.5 py-0.5 font-mono text-[10px] tabular-nums text-sky-300">
                SESSION {latestDate}
              </span>
            )}
            <button
              onClick={() => void load()}
              className="rounded border border-zinc-800 bg-[#05070a] px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider text-zinc-400 hover:border-sky-500/50 hover:text-sky-300"
            >
              {loading ? "SYNC…" : "REFRESH"}
            </button>
          </div>
        </div>
      </header>

      <MarketBarometer data={barometer} />

      {/* Whale alert banner */}
      {whaleBannerRows.length >= WHALE_BANNER_MIN && (
        <div className="whale-pulse border-b border-emerald-900/50 bg-emerald-950/20 px-3 py-2">
          <p className="font-mono text-[11px] tracking-wide text-emerald-300">
            <span className="mr-1 inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-400 align-middle" />
            WHALE ALERT: {whaleBannerRows.length} stealth accumulation
            {whaleBannerRows.length === 1 ? "" : "s"} ·{" "}
            {whaleBannerRows
              .slice(0, 5)
              .map((r) => r.ticker)
              .join(" · ")}
            {whaleBannerRows.length > 5 && " …"}
          </p>
        </div>
      )}

      {/* Tab bar - thumb reachable, horizontal scroll on narrow screens */}
      <nav
        role="tablist"
        aria-label="Terminal desks"
        className="sticky top-0 z-10 flex overflow-x-auto border-b border-zinc-800 bg-[#0c1017]/95 backdrop-blur"
      >
        {visibleTabs.map((t) => {
          const active = t.id === activeTab;
          const badge = tabBadges[t.id];
          return (
            <button
              key={t.id}
              role="tab"
              aria-selected={active}
              onClick={() => setTab(t.id)}
              className={`flex shrink-0 items-center gap-1.5 border-b-2 px-3 py-2.5 font-mono text-[11px] uppercase tracking-wider ${
                active
                  ? "border-sky-400 text-sky-300"
                  : "border-transparent text-zinc-500 hover:text-zinc-300"
              }`}
            >
              {t.label}
              <span
                className={`rounded px-1 font-mono text-[10px] tabular-nums ${
                  active
                    ? "bg-sky-500/10 text-sky-300"
                    : "bg-zinc-900 text-zinc-500"
                }`}
              >
                {badge}
              </span>
            </button>
          );
        })}
      </nav>

      {/* Desk content */}
      {error ? (
        <ErrorPanel message={error} />
      ) : loading ? (
        <SkeletonGrid rows={9} cols={6} label={`LOADING ${tab} DESK…`} />
      ) : (
        <>
          {tab === "WHALE" && <StockBlotter rows={whaleRows} />}
          {tab === "ARB" && (
            <ArbitrageBlotter rows={arbRows} feedOffline={futuresOffline} />
          )}
          {tab === "RESEARCH" && (
            <ResearchDeskBlotter rows={researchRows} status={researchStatus} />
          )}
          {tab === "ROTATION" && (
            <SectorRotationBlotter rows={rotationRows} status={rotationStatus} />
          )}
          {tab === "KIBOR" && (
            <KiborSensitivityDesk rows={kiborRows} status={kiborStatus} />
          )}
          {tab === "LEDGER" && (
            <InsiderConvictionDesk rows={disclosureRows} status={disclosureStatus} />
          )}
          {tab === "MOMENTUM" && <MomentumBlotter rows={momentumRows} />}
          {tab === "MTS" && (
            <MtsSqueezeBlotter rows={mtsRows} status={mtsStatus} />
          )}
          {tab === "ROLLOVER" && <RolloverDeskBlotter rows={rolloverRows} />}
          {tab === "NDM" && <NdmTape rows={ndmRows} />}
          {tab === "EDGE" && (
            <EdgeAnalyticsBlotter rows={backtestRows} tableMissing={backtestMissing} />
          )}
          {tab === "RISK" && <RiskDesk signals={sizingSignals} />}
        </>
      )}

      {/* Status line */}
      <footer className="px-3 pt-3">
        <p className="font-mono text-[10px] uppercase tracking-widest text-zinc-700">
          {loading
            ? "SYNCING WITH SUPABASE…"
            : error
              ? "FEED DEGRADED - RETRY"
              : `LIVE · WHALE ${whaleCount} · RESEARCH ${researchRows.length} · RRG ${rotationRows.length} · KIBOR ${kiborRows.length} · FILINGS ${disclosureRows.length} · INSIDER ${insiderRows.length} · MTS ${mtsRows.length} · NDM ${ndmRows.length} · ${latestDate ?? "NO DATA"}`}
        </p>
      </footer>
    </main>
  );
}
