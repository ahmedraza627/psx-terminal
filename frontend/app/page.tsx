"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import MarketBarometer from "@/components/MarketBarometer";
import MarketBreadthDesk from "@/components/MarketBreadthDesk";
import StockBlotter from "@/components/StockBlotter";
import ArbitrageBlotter from "@/components/ArbitrageBlotter";
import NdmTape from "@/components/NdmTape";
import MomentumBlotter from "@/components/MomentumBlotter";
import MtsSqueezeBlotter from "@/components/MtsSqueezeBlotter";
import RolloverDeskBlotter from "@/components/RolloverDeskBlotter";
import EdgeAnalyticsBlotter from "@/components/EdgeAnalyticsBlotter";
import ResearchDeskBlotter from "@/components/ResearchDeskBlotter";
import SectorRotationBlotter from "@/components/SectorRotationBlotter";
import InstitutionalFlowDesk from "@/components/InstitutionalFlowDesk";
import KiborSensitivityDesk from "@/components/KiborSensitivityDesk";
import InsiderConvictionDesk from "@/components/InsiderConvictionDesk";
import RiskDesk from "@/components/RiskDesk";
import StockComparisonDesk from "@/components/StockComparisonDesk";
import ModelPortfolioDesk from "@/components/ModelPortfolioDesk";
import MarketInsightsDesk from "@/components/MarketInsightsDesk";
import ResearchNotesDesk from "@/components/ResearchNotesDesk";
import WatchlistDesk from "@/components/WatchlistDesk";
import BrokerFlowDesk from "@/components/BrokerFlowDesk";
import MtsLiquidationDesk from "@/components/MtsLiquidationDesk";
import VwapExecutionDesk from "@/components/VwapExecutionDesk";
import TickerDrawer from "@/components/TickerDrawer";
import CommandBar, { type CommandAction } from "@/components/CommandBar";
import FeatureRequestPortal from "@/components/FeatureRequestPortal";
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
import {
  fetchEodHistory,
  fetchFlowMatrix,
  fetchFundamentalsRows,
  fetchSignalHistory,
  fetchSignalsForTicker,
  fetchTickerSectorMap,
  type EodPoint,
  type FlowRow,
  type FundamentalsRow,
  type HistSignal,
} from "@/lib/deskQueries";
import type { SizingSignal } from "@/lib/risk";
import type { SignalRow } from "@/lib/types";

type TabId =
  | "WHALE"
  | "RESEARCH"
  | "ROTATION"
  | "BREADTH"
  | "FLOW"
  | "KIBOR"
  | "LEDGER"
  | "ARB"
  | "MOMENTUM"
  | "MTS"
  | "ROLLOVER"
  | "NDM"
  | "EDGE"
  | "RISK"
  | "COMP"
  | "PORTFOLIO"
  | "WIRE"
  | "NOTES"
  | "WATCH"
  | "BROKER"
  | "LIQ"
  | "EXEC";

const TABS: { id: TabId; label: string }[] = [
  { id: "WHALE", label: "Whale Matrix" },
  { id: "MOMENTUM", label: "Momentum" },
  { id: "RESEARCH", label: "Research" },
  { id: "ROTATION", label: "Rotation" },
  { id: "BREADTH", label: "Market Breadth" },
  { id: "FLOW", label: "Flow & Rates" },
  { id: "KIBOR", label: "KIBOR" },
  { id: "LEDGER", label: "Insider" },
  { id: "ARB", label: "Cash Arb" },
  { id: "MTS", label: "MTS Lev" },
  { id: "ROLLOVER", label: "Rollover" },
  { id: "NDM", label: "NDM Tape" },
  { id: "EDGE", label: "Edge Lab" },
  { id: "RISK", label: "Risk Desk" },
  { id: "PORTFOLIO", label: "Portfolio" },
  { id: "WIRE", label: "Wire" },
  { id: "NOTES", label: "Notes" },
  { id: "COMP", label: "Compare" },
  { id: "WATCH", label: "Watchlists" },
  { id: "BROKER", label: "Broker Flow" },
  { id: "LIQ", label: "Liq Ladder" },
  { id: "EXEC", label: "Execution" },
];

const WHALE_BANNER_MIN = 1;

const EMPTY_STATUSES = {
  insider: { feedPending: false, tableMissing: false, unreachable: true },
  mts: { feedPending: false, tableMissing: false, unreachable: true },
  research: { feedPending: false, tableMissing: false, unreachable: true },
  rotation: { feedPending: false, tableMissing: false, unreachable: true },
  kibor: { feedPending: false, tableMissing: false, unreachable: true },
  disclosures: { feedPending: false, tableMissing: false, unreachable: true },
};

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
  const [flowRows, setFlowRows] = useState<FlowRow[]>([]);
  const [disclosureRows, setDisclosureRows] = useState<DisclosureRow[]>([]);
  const [kiborStatus, setKiborStatus] = useState<DataStatus | null>(null);
  const [disclosureStatus, setDisclosureStatus] = useState<DataStatus | null>(null);
  const [sizingSignals, setSizingSignals] = useState<SizingSignal[]>([]);

  // Expansion-desk data (all settled, never throw).
  const [fundamentals, setFundamentals] = useState<FundamentalsRow[]>([]);
  const [sectorMap, setSectorMap] = useState<Map<string, string>>(new Map());
  const [eod, setEod] = useState<EodPoint[]>([]);
  const [historySignals, setHistorySignals] = useState<HistSignal[]>([]);

  // Command / drawer / portal state.
  const [cmdOpen, setCmdOpen] = useState(false);
  const [portalOpen, setPortalOpen] = useState(false);
  const [drawerTicker, setDrawerTicker] = useState<string | null>(null);
  const [drawerSignals, setDrawerSignals] = useState<SignalRow[]>([]);
  const [compareTickers, setCompareTickers] = useState<string[]>([]);
  const [flowSectorFilter, setFlowSectorFilter] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // Step 1: resolve the real trading session from stored data —
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
        setFlowRows([]);
        setDisclosureRows([]);
        setKiborStatus(null);
        setDisclosureStatus(null);
        setSizingSignals([]);
        setFundamentals([]);
        setEod([]);
        setHistorySignals([]);
        return;
      }

      // Step 2: fan out every desk query, settled — one dead table never
      // takes down the terminal. Only the CORE probes (whale rows, whale
      // count, momentum rows) may trip the global FEED ERROR screen when
      // they reject on auth/network; optional desks render their own
      // status pill instead.
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

      const statuses = value(10, EMPTY_STATUSES);
      const bt = value(11, { rows: [], tableMissing: false });

      // Step 3: expansion desks — secondary settled batch.
      const expansion = await Promise.allSettled([
        fetchFundamentalsRows(sessionDate), // 0
        fetchTickerSectorMap(), // 1
        fetchEodHistory(sessionDate, 60), // 2
        fetchSignalHistory(31), // 3
        fetchFlowMatrix(), // 4
      ]);
      const xv = <T,>(index: number, fallback: T): T => {
        const r = expansion[index];
        return r.status === "fulfilled" ? (r.value as T) : fallback;
      };

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
      setFundamentals(xv(0, [] as FundamentalsRow[]));
      setSectorMap(xv(1, new Map<string, string>()));
      setEod(xv(2, [] as EodPoint[]));
      setHistorySignals(xv(3, [] as HistSignal[]));
      setFlowRows(xv(4, [] as FlowRow[]));
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

  // Drawer signal fill when a ticker is opened.
  useEffect(() => {
    let cancelled = false;
    if (!drawerTicker || !latestDate) {
      setDrawerSignals([]);
      return;
    }
    fetchSignalsForTicker(latestDate, drawerTicker).then((rows) => {
      if (!cancelled) {
        setDrawerSignals(
          rows.map((r) => ({
            trade_date: r.tradeDate,
            ticker: r.ticker,
            timeframe: r.timeframe as unknown as SignalRow["timeframe"],
            signal_type: r.signalType as unknown as SignalRow["signal_type"],
            entry_reference: r.entryReference,
            stop_loss: r.stopLoss,
            rationale: r.rationale,
            metadata: null,
          }))
        );
      }
    });
    return () => {
      cancelled = true;
    };
  }, [drawerTicker, latestDate]);

  // Cmd+K / Ctrl+K / "/" command bar shortcut.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      const typing =
        target != null &&
        (target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.isContentEditable);
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setCmdOpen((v) => !v);
      } else if (e.key === "/" && !typing) {
        e.preventDefault();
        setCmdOpen(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

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
    BREADTH: eod.length > 0 ? 1 : 0,
    FLOW: flowRows.length,
    KIBOR: kiborRows.length,
    LEDGER: disclosureRows.length,
    ARB: arbRows.length,
    MOMENTUM: momentumCount,
    MTS: mtsRows.length,
    ROLLOVER: rolloverRows.length,
    NDM: ndmRows.length,
    EDGE: backtestRows.length,
    RISK: riskBadge,
    COMP: 0,
    PORTFOLIO: 0,
    WIRE: 0,
    NOTES: researchRows.length,
    WATCH: 0,
    BROKER: 0,
    LIQ: mtsRows.length,
    EXEC: 0,
  };

  // Consolidation: only render desks holding live data for feed-bound tabs.
  const CONDITIONAL_TABS: ReadonlySet<TabId> = new Set<TabId>([
    "ARB",
    "ROLLOVER",
    "MTS",
    "LEDGER",
  ]);
  const visibleTabs = TABS.filter(
    (t) => !CONDITIONAL_TABS.has(t.id) || tabBadges[t.id] > 0
  );

  // Active tab fell back to a hidden desk — snap back to the primary desk.
  const activeTab = visibleTabs.some((t) => t.id === tab) ? tab : "WHALE";

  const onCommand = (a: CommandAction) => {
    if (a.kind === "TAB") setTab(a.tabId as TabId);
    else if (a.kind === "COMPARE") {
      setCompareTickers(a.tickers.slice(0, 3));
      setTab("COMP");
    } else if (a.kind === "FLOW_SECTOR") {
      setFlowSectorFilter(a.sector);
      setTab("FLOW");
    } else setDrawerTicker(a.ticker);
  };

  // Command-bar universe: whales first (they are the tradeable names), then
  // the fundamentals universe.
  const cmdTickers = useMemo(() => {
    const set = new Set<string>();
    for (const r of whaleRows) set.add(r.ticker.toUpperCase());
    for (const f of fundamentals) set.add(f.ticker);
    return Array.from(set).sort();
  }, [whaleRows, fundamentals]);

  const drawerWhale =
    drawerTicker != null
      ? whaleRows.find(
          (w) => w.ticker.toUpperCase() === drawerTicker.toUpperCase()
        ) ?? null
      : null;
  const drawerResearch =
    drawerTicker != null
      ? researchRows.find(
          (r) => r.ticker.toUpperCase() === drawerTicker.toUpperCase()
        ) ?? null
      : null;
  const drawerKibor =
    drawerTicker != null
      ? kiborRows.find(
          (k) => k.ticker.toUpperCase() === drawerTicker.toUpperCase()
        ) ?? null
      : null;

  const marketCapByTicker = useMemo(() => {
    const m = new Map<string, number>();
    for (const f of fundamentals) {
      if (f.marketCapPkr != null) m.set(f.ticker, f.marketCapPkr);
    }
    return m;
  }, [fundamentals]);

  const dividendTickers = useMemo(
    () =>
      fundamentals
        .filter((f) => (f.dividendYield ?? 0) >= 5)
        .sort((a, b) => (b.dividendYield ?? 0) - (a.dividendYield ?? 0))
        .map((f) => f.ticker),
    [fundamentals]
  );

  const kiborTickers = useMemo(
    () => kiborRows.map((k) => k.ticker),
    [kiborRows]
  );

  const feedPills = [
    { k: "SIG", ok: whaleRows.length > 0 },
    { k: "RRG", ok: rotationRows.length > 0 },
    { k: "FUND", ok: researchRows.length > 0 },
    { k: "FLOWS", ok: flowRows.length > 0 },
    { k: "KIBOR", ok: kiborRows.length > 0 },
    { k: "FILINGS", ok: disclosureRows.length > 0 },
  ];

  return (
    <main className="mx-auto min-h-dvh w-full max-w-[1600px] bg-obsidian pb-8 text-ink">
      {/* Command header */}
      <header className="sticky top-0 z-20 border-b border-hairline bg-panel/95 backdrop-blur">
        <div className="flex items-center justify-between gap-2 px-2.5 py-1.5">
          <div className="flex items-center gap-2.5">
            <h1 className="font-mono text-[13px] font-bold tracking-[0.18em] text-ink">
              PSX<span className="text-info">·</span>QUANT
            </h1>
            {latestDate && (
              <span className="rounded-[2px] border border-hairline bg-obsidian px-1.5 py-0.5 font-mono text-[10px] tabular-nums text-info">
                SESSION {latestDate}
              </span>
            )}
            {/* Feed health strip */}
            <div className="hidden items-center gap-1 sm:flex">
              {feedPills.map((p) => (
                <span
                  key={p.k}
                  title={p.ok ? `${p.k} LIVE` : `${p.k} EMPTY`}
                  className={`rounded-[2px] px-1 py-0.5 font-mono text-[9px] uppercase tracking-widest ${
                    p.ok
                      ? "bg-bull/10 text-bull"
                      : "bg-panel text-ghost ring-1 ring-hairline"
                  }`}
                >
                  {p.k}
                </span>
              ))}
            </div>
          </div>
          <div className="flex items-center gap-1.5">
            <button
              onClick={() => setCmdOpen(true)}
              className="h-7 rounded-[2px] border border-hairline bg-obsidian px-2 font-mono text-[10px] uppercase tracking-wider text-muted hover:border-info/40 hover:text-info"
              aria-label="Open command bar"
            >
              CMD ⌘K
            </button>
            <button
              onClick={() => setPortalOpen(true)}
              className="h-7 rounded-[2px] border border-hairline bg-obsidian px-2 font-mono text-[10px] uppercase tracking-wider text-muted hover:border-warn/40 hover:text-warn"
              aria-label="Feature request portal"
            >
              REQ
            </button>
            <button
              onClick={() => void load()}
              className="h-7 rounded-[2px] border border-hairline bg-obsidian px-2 font-mono text-[10px] uppercase tracking-wider text-muted hover:border-info/40 hover:text-info"
            >
              {loading ? "SYNC…" : "REFRESH"}
            </button>
          </div>
        </div>
      </header>

      <MarketBarometer data={barometer} />

      {/* Whale alert banner */}
      {whaleBannerRows.length >= WHALE_BANNER_MIN && (
        <div className="whale-pulse border-b border-bull/20 bg-bull/5 px-2.5 py-1.5">
          <p className="font-mono text-[11px] tracking-wide text-bull">
            <span className="mr-1 inline-block h-1.5 w-1.5 animate-pulse rounded-[2px] bg-bull align-middle" />
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

      {/* Desk navigation — machined tabs, horizontal scroll on narrow screens */}
      <nav
        role="tablist"
        aria-label="Terminal desks"
        className="scroll-thin sticky top-[38px] z-10 flex overflow-x-auto border-b border-hairline bg-panel/95 backdrop-blur"
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
              className={`flex shrink-0 items-center gap-1 border-b-2 px-2.5 py-2 font-mono text-[10px] uppercase tracking-wider ${
                active
                  ? "border-info text-ink"
                  : "border-transparent text-muted hover:text-ink"
              }`}
            >
              {t.label}
              {badge > 0 && (
                <span
                  className={`rounded-[2px] px-1 font-mono text-[9px] tabular-nums ${
                    active ? "bg-info/10 text-info" : "bg-obsidian text-ghost"
                  }`}
                >
                  {badge}
                </span>
              )}
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
          {activeTab === "WHALE" && <StockBlotter rows={whaleRows} />}
          {activeTab === "MOMENTUM" && <MomentumBlotter rows={momentumRows} />}
          {activeTab === "RESEARCH" && (
            <ResearchDeskBlotter rows={researchRows} status={researchStatus} />
          )}
          {activeTab === "ROTATION" && (
            <SectorRotationBlotter rows={rotationRows} status={rotationStatus} />
          )}
          {activeTab === "BREADTH" && (
            <MarketBreadthDesk eod={eod} sectorMap={sectorMap} />
          )}
          {activeTab === "FLOW" && (
            <InstitutionalFlowDesk
              flows={flowRows}
              kibor={kiborRows}
              eod={eod}
              sectorMap={sectorMap}
              sectorFilter={flowSectorFilter}
              onClearSectorFilter={() => setFlowSectorFilter(null)}
            />
          )}
          {activeTab === "KIBOR" && (
            <KiborSensitivityDesk rows={kiborRows} status={kiborStatus} />
          )}
          {activeTab === "LEDGER" && (
            <InsiderConvictionDesk
              rows={disclosureRows}
              status={disclosureStatus}
            />
          )}
          {activeTab === "ARB" && (
            <ArbitrageBlotter rows={arbRows} feedOffline={futuresOffline} />
          )}
          {activeTab === "MTS" && (
            <MtsSqueezeBlotter rows={mtsRows} status={mtsStatus} />
          )}
          {activeTab === "ROLLOVER" && (
            <RolloverDeskBlotter rows={rolloverRows} />
          )}
          {activeTab === "NDM" && <NdmTape rows={ndmRows} />}
          {activeTab === "EDGE" && (
            <EdgeAnalyticsBlotter
              rows={backtestRows}
              tableMissing={backtestMissing}
            />
          )}
          {activeTab === "RISK" && <RiskDesk signals={sizingSignals} />}
          {activeTab === "PORTFOLIO" && (
            <ModelPortfolioDesk
              sizingSignals={sizingSignals}
              historySignals={historySignals}
              eod={eod}
              sectorMap={sectorMap}
              marketCapByTicker={marketCapByTicker}
            />
          )}
          {activeTab === "WIRE" && (
            <MarketInsightsDesk
              barometer={barometer}
              whaleRows={whaleRows}
              mtsRows={mtsRows}
              rolloverRows={rolloverRows}
              disclosures={disclosureRows}
              rotation={rotationRows}
              kibor={kiborRows}
            />
          )}
          {activeTab === "NOTES" && (
            <ResearchNotesDesk
              research={researchRows}
              fundamentals={fundamentals}
              whaleRows={whaleRows}
              onInspect={setDrawerTicker}
            />
          )}
          {activeTab === "COMP" && (
            <StockComparisonDesk
              fundamentals={fundamentals}
              kibor={kiborRows}
              research={researchRows}
              initialPicked={compareTickers}
            />
          )}
          {activeTab === "WATCH" && (
            <WatchlistDesk
              whaleRows={whaleRows}
              kiborTickers={kiborTickers}
              dividendTickers={dividendTickers}
              onInspect={setDrawerTicker}
            />
          )}
          {activeTab === "BROKER" && (
            <BrokerFlowDesk ndmRows={ndmRows} whaleRows={whaleRows} />
          )}
          {activeTab === "LIQ" && (
            <MtsLiquidationDesk mtsRows={mtsRows} eod={eod} />
          )}
          {activeTab === "EXEC" && <VwapExecutionDesk />}
        </>
      )}

      {/* Status line */}
      <footer className="px-2.5 pt-2.5">
        <p className="font-mono text-[10px] uppercase tracking-widest text-ghost">
          {loading
            ? "SYNCING WITH SUPABASE…"
            : error
              ? "FEED DEGRADED — RETRY"
              : `LIVE · WHALE ${whaleCount} · RESEARCH ${researchRows.length} · RRG ${rotationRows.length} · KIBOR ${kiborRows.length} · FILINGS ${disclosureRows.length} · MTS ${mtsRows.length} · NDM ${ndmRows.length} · EOD ${eod.length} · ${latestDate ?? "NO DATA"}`}
        </p>
      </footer>

      {/* Overlays */}
      <CommandBar
        open={cmdOpen}
        onClose={() => setCmdOpen(false)}
        onAction={onCommand}
        tickers={cmdTickers}
        eod={eod}
        fundamentals={fundamentals}
        kibor={kiborRows}
        sectorMap={sectorMap}
      />
      <FeatureRequestPortal
        open={portalOpen}
        onClose={() => setPortalOpen(false)}
      />
      <TickerDrawer
        ticker={drawerTicker}
        onClose={() => setDrawerTicker(null)}
        whale={drawerWhale}
        signals={drawerSignals}
        research={drawerResearch}
        kibor={drawerKibor}
        eod={eod}
        onCompare={(t) => {
          setCompareTickers((prev) => {
            const next = prev.includes(t) ? prev : [...prev, t].slice(0, 3);
            return next;
          });
          setTab("COMP");
        }}
      />
    </main>
  );
}
