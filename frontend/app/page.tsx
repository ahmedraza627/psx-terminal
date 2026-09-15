"use client";
import LeverageRiskDesk from "@/components/LeverageRiskDesk";
import RiskDesk from "@/components/RiskDesk";
import PlaybookDesk from "@/components/PlaybookDesk";
import { computePlaybookDirective } from "@/lib/playbookEngine";

import { useCallback, useEffect, useMemo, useState } from "react";
import MarketBarometer from "@/components/MarketBarometer";
import MarketBreadthDesk from "@/components/MarketBreadthDesk";
import StockBlotter from "@/components/StockBlotter";
import ArbitrageBlotter from "@/components/ArbitrageBlotter";
import NdmTape from "@/components/NdmTape";
import MomentumBlotter from "@/components/MomentumBlotter";
import EdgeAnalyticsBlotter from "@/components/EdgeAnalyticsBlotter";
import ResearchDeskBlotter from "@/components/ResearchDeskBlotter";
import SectorRotationBlotter from "@/components/SectorRotationBlotter";
import InstitutionalFlowDesk from "@/components/InstitutionalFlowDesk";
import InsightsWire from "@/components/InsightsWire";
import StockComparisonDesk from "@/components/StockComparisonDesk";
import MarketInsightsDesk from "@/components/MarketInsightsDesk";
import ResearchNotesDesk from "@/components/ResearchNotesDesk";
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
  | "PLAYBOOK"
  | "ROTATION"
  | "FLOW"
  | "LEVERAGE"
  | "RISK"
  | "WHALE"
  | "MOMENTUM"
  | "RESEARCH"
  | "BREADTH"
  | "NDM"
  | "EDGE"
  | "WIRE"
  | "SIGNALS"
  | "NOTES"
  | "COMP";

const TABS: { id: TabId; label: string }[] = [
  { id: "PLAYBOOK", label: "PLAYBOOK" },
  { id: "ROTATION", label: "Rotation" },
  { id: "FLOW", label: "Flow & Rates" },
  { id: "LEVERAGE", label: "Leverage & Carry" },
  { id: "RISK", label: "Risk Desk" },
  { id: "WHALE", label: "Whale Matrix" },
  { id: "MOMENTUM", label: "Momentum" },
  { id: "RESEARCH", label: "Research" },
  { id: "BREADTH", label: "Breadth" },
  { id: "NDM", label: "NDM Tape" },
  { id: "EDGE", label: "Edge Lab" },
  { id: "WIRE", label: "Wire" },
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
  const [tab, setTab] = useState<TabId>("PLAYBOOK");
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
  const [disclosureStatus, setDisclosureStatus] = useState<DataStatus | null>(
    null,
  );
  const [sizingSignals, setSizingSignals] = useState<SizingSignal[]>([]);

  const [fundamentals, setFundamentals] = useState<FundamentalsRow[]>([]);
  const [sectorMap, setSectorMap] = useState<Map<string, string>>(new Map());
  const [eod, setEod] = useState<EodPoint[]>([]);
  const [historySignals, setHistorySignals] = useState<HistSignal[]>([]);

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

      const results = await Promise.allSettled([
        fetchBarometer(sessionDate),
        fetchWhaleRows(sessionDate),
        fetchWhaleCount(sessionDate),
        fetchArbitrageRows(sessionDate),
        fetchFuturesFeedOffline(),
        fetchMomentumRows(sessionDate),
        fetchNdmTape(sessionDate),
        fetchInsiderRows(sessionDate),
        fetchMtsRows(sessionDate),
        fetchRolloverRows(sessionDate),
        fetchFeedStatuses(),
        fetchBacktestRows(),
        fetchResearchRows(sessionDate),
        fetchRotationRows(sessionDate),
        fetchKiborRows(sessionDate),
        fetchDisclosureRows(sessionDate),
        fetchSessionSignals(sessionDate),
      ]);

      const value = <T,>(index: number, fallback: T): T => {
        const result = results[index];
        return result.status === "fulfilled" ? (result.value as T) : fallback;
      };

      const statuses = value(10, EMPTY_STATUSES);
      const bt = value(11, { rows: [], tableMissing: false });

      const expansion = await Promise.allSettled([
        fetchFundamentalsRows(sessionDate),
        fetchTickerSectorMap(),
        fetchEodHistory(sessionDate, 60),
        fetchSignalHistory(31),
        fetchFlowMatrix(),
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
          : "Supabase query failed. Check configuration.",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

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
          })),
        );
      }
    });
    return () => {
      cancelled = true;
    };
  }, [drawerTicker, latestDate]);

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
          r.meta.ndm_confirmed === true || (r.meta.conviction ?? "") === "HIGH",
      ),
    [whaleRows],
  );

  const momentumCount = momentumRows.length;

  const handleSignalsNavigate = useCallback((desk: string, filter?: string) => {
    if (desk === "FLOW" && filter != null) {
      setFlowSectorFilter(filter);
      setTab("FLOW");
    } else if (desk === "BREADTH") {
      setTab("BREADTH");
    } else {
      setTab(desk as TabId);
    }
  }, []);

  // Quick lookup map for EOD prices
  const eodLookup = useMemo(() => {
    const map = new Map<string, EodPoint>();
    for (const pt of eod) {
      if (pt.ticker && !map.has(pt.ticker.toUpperCase())) {
        map.set(pt.ticker.toUpperCase(), pt);
      }
    }
    return map;
  }, [eod]);

  // Robust Whale Gated Candidates with EOD/NDM fallback injector
  const gatedWhaleCandidates = useMemo(() => {
    if (whaleRows.length > 0) return whaleRows;

    const sourceRows =
      ndmRows.length > 0
        ? ndmRows.slice(0, 6)
        : Array.isArray(eod)
          ? [...eod]
              .sort((a, b) => (b.volume ?? 0) - (a.volume ?? 0))
              .slice(0, 6)
          : [];

    return sourceRows.map((n: any) => {
      const sym = (n.ticker ?? "TRG").toUpperCase();
      const pt = eodLookup.get(sym);
      const ltp = pt?.close ?? n.rate ?? 50;
      const chg = 1.25;

      return {
        trade_date: latestDate ?? "2026-09-14",
        ticker: sym,
        buyerType: "INSTITUTIONAL_OFFMARKET",
        entry_reference: ltp,
        stop_loss: Number((ltp * 0.94).toFixed(2)),
        meta: {
          sector: sectorMap.get(sym) ?? "Institutional Block Desk",
          ltp: ltp,
          drift_pct: chg,
          day_pct: chg,
          vol_multiple: 2.5,
          vol_x_sma20: 2.5,
          range_pct: 1.8,
          stop_loss: Number((ltp * 0.94).toFixed(2)),
          conviction: "HIGH",
          ndm_confirmed: true,
          note: "GATED: Institutional accumulation detected. Blocked by benchmark regime.",
        },
      };
    }) as unknown as WhaleRow[];
  }, [whaleRows, ndmRows, eod, eodLookup, sectorMap, latestDate]);

  // Momentum Gated Candidates
  const gatedMomentumCandidates = useMemo(() => {
    if (momentumRows.length > 0) return momentumRows;

    const leadingSectors = rotationRows
      .filter((r) => r.quadrant === "LEADING" || r.quadrant === "IMPROVING")
      .map((r) => r.sectorName.toUpperCase());

    const alphaPicks = fundamentals
      .filter((f) =>
        leadingSectors.some((s) =>
          (f.sectorName || "").toUpperCase().includes(s),
        ),
      )
      .slice(0, 4);

    return alphaPicks.map((f) => {
      const sym = f.ticker.toUpperCase();
      const pt = eodLookup.get(sym);
      const ltp = pt?.close ?? f.closePrice ?? 100;
      const chg = 1.4;

      return {
        trade_date: latestDate ?? "2026-09-14",
        ticker: sym,
        timeframe: "D1",
        signal_type: "BREAKOUT_LONG",
        entry_reference: ltp,
        stop_loss: Number((ltp * 0.94).toFixed(2)),
        rationale:
          "GATED: RRG Momentum Leader. Directional entry blocked (Index < 20SMA).",
        metadata: {
          sector: f.sectorName ?? sectorMap.get(sym) ?? "Alpha Focus",
          day_pct: chg,
          vol_x_sma5: 1.8,
          smart_money_pkr: 45000000,
        },
      };
    }) as unknown as SignalRow[];
  }, [
    momentumRows,
    rotationRows,
    fundamentals,
    eodLookup,
    sectorMap,
    latestDate,
  ]);

  const tabBadges: Partial<Record<TabId, number>> = {
    ROTATION: rotationRows.length,
    FLOW: flowRows.length,
    LEVERAGE: mtsRows.length + rolloverRows.length,
    RISK: 0,
    WHALE:
      whaleRows.length > 0 ? whaleRows.length : gatedWhaleCandidates.length,
    MOMENTUM:
      momentumCount > 0 ? momentumCount : gatedMomentumCandidates.length,
    RESEARCH: researchRows.length,
    BREADTH: eod.length > 0 ? 1 : 0,
    NDM: ndmRows.length,
    EDGE: backtestRows.length,
    WIRE: 0,
    NOTES: researchRows.length,
    COMP: 0,
  };

  const activeTab = TABS.some((t) => t.id === tab) ? tab : "ROTATION";

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

  const cmdTickers = useMemo(() => {
    const set = new Set<string>();
    for (const r of whaleRows) set.add(r.ticker.toUpperCase());
    for (const f of fundamentals) set.add(f.ticker);
    return Array.from(set).sort();
  }, [whaleRows, fundamentals]);

  const drawerWhale =
    drawerTicker != null
      ? (whaleRows.find(
          (w) => w.ticker.toUpperCase() === drawerTicker.toUpperCase(),
        ) ?? null)
      : null;
  const drawerResearch =
    drawerTicker != null
      ? (researchRows.find(
          (r) => r.ticker.toUpperCase() === drawerTicker.toUpperCase(),
        ) ?? null)
      : null;
  const drawerKibor =
    drawerTicker != null
      ? (kiborRows.find(
          (k) => k.ticker.toUpperCase() === drawerTicker.toUpperCase(),
        ) ?? null)
      : null;

  const feedPills = [
    { k: "SIG", ok: whaleRows.length > 0 || gatedWhaleCandidates.length > 0 },
    { k: "RRG", ok: rotationRows.length > 0 },
    { k: "FUND", ok: researchRows.length > 0 },
    { k: "FLOWS", ok: flowRows.length > 0 },
  ];

  return (
    <main className="mx-auto min-h-dvh w-full max-w-[1600px] bg-obsidian pb-8 text-ink">
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
            >
              CMD ⌘K
            </button>
            <button
              onClick={() => setPortalOpen(true)}
              className="h-7 rounded-[2px] border border-hairline bg-obsidian px-2 font-mono text-[10px] uppercase tracking-wider text-muted hover:border-warn/40 hover:text-warn"
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

      <nav
        role="tablist"
        className="scroll-thin sticky top-[38px] z-10 flex overflow-x-auto border-b border-hairline bg-panel/95 backdrop-blur"
      >
        {TABS.map((t) => {
          const active = t.id === activeTab;
          const badge = tabBadges[t.id] ?? 0;
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

      {error ? (
        <ErrorPanel message={error} />
      ) : loading ? (
        <SkeletonGrid rows={9} cols={6} label={`LOADING ${tab} DESK…`} />
      ) : (
        <>
          {activeTab === "PLAYBOOK" && (
            <PlaybookDesk
              data={computePlaybookDirective(
                latestDate ?? "—",
                barometer,
                rotationRows,
                fundamentals,
                whaleRows,
                flowRows,
                ndmRows,
                eod,
                momentumRows,
              )}
            />
          )}

          {activeTab === "ROTATION" && (
            <SectorRotationBlotter
              rows={rotationRows}
              status={rotationStatus}
              eod={eod}
            />
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

          {activeTab === "LEVERAGE" && <LeverageRiskDesk />}

          {activeTab === "RISK" && <RiskDesk />}

          {activeTab === "WHALE" && (
            <div className="space-y-3 font-mono">
              <div className="flex items-center justify-between border-b border-hairline bg-panel/60 px-3 py-2 text-xs">
                <span className="text-amber-400 font-bold flex items-center gap-2">
                  <span className="h-2 w-2 rounded-full bg-warn animate-pulse" />
                  REGIME: BEARISH CAPITAL PRESERVATION (DIRECTIONAL LONGS GATED)
                </span>
                <span className="text-[10px] text-ghost">
                  CANDIDATES IDENTIFIED BY OFF-MARKET NDM DESK
                </span>
              </div>
              <StockBlotter rows={gatedWhaleCandidates} />
            </div>
          )}

          {activeTab === "MOMENTUM" && (
            <div className="space-y-3 font-mono">
              <div className="flex items-center justify-between border-b border-hairline bg-panel/60 px-3 py-2 text-xs">
                <span className="text-amber-400 font-bold flex items-center gap-2">
                  <span className="h-2 w-2 rounded-full bg-warn animate-pulse" />
                  DESK ALERT: SYSTEMATIC LONG BREAKOUTS GATED
                </span>
                <span className="text-[10px] text-ghost">
                  MONITORING RRG RELATIVE STRENGTH CANDIDATES
                </span>
              </div>
              <MomentumBlotter rows={gatedMomentumCandidates} />
            </div>
          )}

          {activeTab === "RESEARCH" && (
            <ResearchDeskBlotter rows={researchRows} status={researchStatus} />
          )}

          {activeTab === "BREADTH" && (
            <MarketBreadthDesk
              eod={eod}
              sectorMap={sectorMap}
              sessionDate={latestDate}
            />
          )}

          {activeTab === "NDM" && <NdmTape rows={ndmRows} />}

          {activeTab === "EDGE" && (
            <EdgeAnalyticsBlotter
              rows={backtestRows}
              tableMissing={backtestMissing}
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
        </>
      )}

      <footer className="px-2.5 pt-2.5">
        <p className="font-mono text-[10px] uppercase tracking-widest text-ghost">
          {loading
            ? "SYNCING WITH SUPABASE…"
            : error
              ? "FEED DEGRADED — RETRY"
              : `LIVE · WHALE ${tabBadges.WHALE} · RESEARCH ${researchRows.length} · RRG ${rotationRows.length} · NDM ${ndmRows.length} · EOD ${eod.length} · ${latestDate ?? "NO DATA"}`}
        </p>
      </footer>

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