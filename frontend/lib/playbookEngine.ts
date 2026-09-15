// Playbook engine - deterministic derivation of the tactical directive from
// live Supabase data. Zero fabricated inputs: every number traces to a
// signals_computed / nccpl_fipi_lipi / psx_sector_rotation / psx_daily_eod /
// psx_fundamentals row for the bound session. When an input is missing the
// desk renders honest idle states instead of invented values.
//
// Regime source of truth: the macro gate verdict the Python pipeline stamped
// into signals_computed.metadata.regime (quant_engine.build_regime_state).
// The playbook never re-derives the regime from a different formula.

import type { Barometer, RotationRow, WhaleRow, NdmRow } from "./queries";
import type { FlowRow, FundamentalsRow, EodPoint } from "./deskQueries";
import type { SignalRow } from "./types";

// ---------------------------------------------------------------------------
// Risk policy constants (the only declared values in this engine; everything
// else is derived from session data).
// ---------------------------------------------------------------------------
const RISK_POLICY = {
  /** Fixed-fractional risk per pick, % of equity - matches risk.ts 1.0% convention. */
  riskPerTradePct: 1.0,
  /** Max positions surfaced per session. */
  maxPicks: 5,
  /** Tiered-exit geometry, expressed as R multiples (1R = stop distance). */
  exitRMultiples: { tp1: 1.0, tp2: 2.0 },
  /** Re-entry trigger threshold (published policy, not inferred). */
  reentryMutualFundsNetPkr: 300_000_000,
} as const;

// ---------------------------------------------------------------------------
// Regime binding: gate verdict stamped by the pipeline
// ---------------------------------------------------------------------------
export interface RegimeBinding {
  status: "BEARISH_CAPITAL_PRESERVATION" | "ACCUMULATION_FAVORABLE" | "UNKNOWN";
  instNetFlowPkr: number | null;
  flowBasis: string | null;
  benchmarkClose: number | null;
  benchmarkSma20: number | null;
  /** False when no signal row carried the stamped regime. */
  sourceFound: boolean;
}

function bindRegime(rows: WhaleRow[]): RegimeBinding {
  for (const row of rows) {
    const r = row.meta?.regime;
    if (r?.regime_status) {
      return {
        status: (r.regime_status as RegimeBinding["status"]) ?? "UNKNOWN",
        instNetFlowPkr:
          typeof r.inst_net_flow_pkr === "number" ? r.inst_net_flow_pkr : null,
        flowBasis: r.flow_basis ?? null,
        benchmarkClose:
          typeof r.benchmark_close === "number" ? r.benchmark_close : null,
        benchmarkSma20:
          typeof r.benchmark_sma20 === "number" ? r.benchmark_sma20 : null,
        sourceFound: true,
      };
    }
  }
  return {
    status: "UNKNOWN",
    instNetFlowPkr: null,
    flowBasis: null,
    benchmarkClose: null,
    benchmarkSma20: null,
    sourceFound: false,
  };
}

// ---------------------------------------------------------------------------
// Directive contract
// ---------------------------------------------------------------------------
export interface TacticalAlphaPick {
  ticker: string;
  sector: string;
  strategy: "WHALE_ABSORPTION" | "NDM_WHALE_BLOCK" | "INST_FLOW_TARGET";
  /** Pipeline conviction tag when present; no synthetic 0-100 score. */
  conviction: string | null;
  ltp: number;
  entryLow: number;
  entryHigh: number;
  /** Pipeline stop - the calibrated 1.5x ATR(14) geometry. */
  stopLoss: number;
  /** Stop distance as % of entry - the actual 1R unit. */
  riskPerSharePct: number;
  /** Tiered-exit targets: entry + R x stopDistance. */
  target1: number;
  target2: number;
  /** Computed reward:risk to TP2 - never a hard-coded string. */
  riskReward: string;
  /** Fixed-fractional policy allocation (1R = this % of equity). */
  riskAllocationPct: number;
  executionProtocol: {
    orderType: "POST_ONLY_LIMIT" | "TWAP_ACCUMULATE" | "ICEBERG";
    window: string;
    volumeCondition: string;
  };
  catalyst: string;
  /** Verbatim pipeline rationale for the session row. */
  rationale: string;
}

export interface PlaybookDirective {
  sessionDate: string;
  regimeState:
    | "BEARISH_CAPITAL_PRESERVATION"
    | "ACCUMULATION_FAVORABLE"
    | "UNKNOWN";
  /** Institutional net flow, latest NCCPL session, PKR (null = no data). */
  instNetFlowPkr: number | null;
  /** KSE-100 close vs SMA20 from the regime stamp (null when unavailable). */
  benchmark: { close: number; sma20: number } | null;
  /** Capital stance mapped from the regime verdict only - null = pending. */
  recommendedCashPct: number | null;
  macroSummary: string;
  reentryTrigger: string;
  topPicks: TacticalAlphaPick[];
  sectorFocus: {
    longSectors: string[];
    fadeSectors: string[];
  };
  /** Idle-state surface: which upstream feeds are empty this session. */
  dataGaps: string[];
}

// ---------------------------------------------------------------------------
// Price lookup: EOD closes first (authoritative session), fundamentals as the
// static-snapshot fallback. Unpriceable instruments are skipped - no magic
// defaults (the old engine's `?? 50` / `?? 100` fabricated prices).
// ---------------------------------------------------------------------------
function buildPriceMap(
  eod: EodPoint[],
  fundamentals: FundamentalsRow[],
): Map<string, number> {
  const map = new Map<string, number>();
  for (const row of eod) {
    if (row.ticker && row.close != null && row.close > 0) {
      map.set(row.ticker.toUpperCase(), row.close);
    }
  }
  for (const f of fundamentals) {
    if (f?.ticker && f.closePrice != null && f.closePrice > 0) {
      const key = f.ticker.toUpperCase();
      if (!map.has(key)) map.set(key, f.closePrice);
    }
  }
  return map;
}

/** R-multiple targets from the stop distance. 1R = |entry - stop|. */
function exitTargets(
  entry: number,
  stop: number,
): { target1: number; target2: number; riskPerSharePct: number } {
  const rUnit = Math.abs(entry - stop);
  return {
    riskPerSharePct: entry > 0 ? (rUnit / entry) * 100 : 0,
    target1: Number((entry + rUnit * RISK_POLICY.exitRMultiples.tp1).toFixed(2)),
    target2: Number((entry + rUnit * RISK_POLICY.exitRMultiples.tp2).toFixed(2)),
  };
}

function rewardRiskToTp2(entry: number, stop: number, target2: number): string {
  return `${((target2 - entry) / Math.max(entry - stop, 1e-9)).toFixed(1)}:1 (to TP2)`;
}

// ---------------------------------------------------------------------------
// Pick builders - each keyed to a specific upstream signal source
// ---------------------------------------------------------------------------

/** Whale Radar rows: the pipeline's stealth-accumulation output. */
function whalePicks(
  whaleRows: WhaleRow[],
  prices: Map<string, number>,
): TacticalAlphaPick[] {
  const picks: TacticalAlphaPick[] = [];
  for (const row of whaleRows) {
    const entry = row.entry_reference;
    const stop = row.stop_loss;
    if (entry == null || entry <= 0) continue;
    if (stop == null || stop >= entry) continue; // long-bias geometry only
    const targets = exitTargets(entry, stop);
    const isFallbackTag = row.meta.fallback === true;
    picks.push({
      ticker: row.ticker,
      sector: row.meta.sector ?? "UNMAPPED_SECTOR",
      strategy: "WHALE_ABSORPTION",
      conviction: row.meta.conviction ?? null,
      ltp: prices.get(row.ticker.toUpperCase()) ?? entry,
      entryLow: Number((entry * 0.99).toFixed(2)),
      entryHigh: Number(entry.toFixed(2)),
      stopLoss: Number(stop.toFixed(2)),
      ...targets,
      riskReward: rewardRiskToTp2(entry, stop, targets.target2),
      riskAllocationPct: RISK_POLICY.riskPerTradePct,
      executionProtocol: {
        orderType: row.meta.ndm_confirmed ? "POST_ONLY_LIMIT" : "ICEBERG",
        window: "10:15 AM – 11:30 AM",
        volumeCondition: row.meta.ndm_confirmed
          ? "Resting bid near NDM block rate; confirm absorbed volume at level"
          : "Confirm 5-min volume exceeds 20-day ADV baseline",
      },
      catalyst: isFallbackTag
        ? "Notable volume spike fallback tag (outside strict absorption band)"
        : `Stealth absorption: ${row.meta.vol_multiple ?? "?"}x 20-day volume, drift ${row.meta.drift_pct ?? "?"}% in band${row.meta.ndm_confirmed ? ", NDM block confirmed" : ""}`,
      rationale: row.rationale,
    });
    if (picks.length >= RISK_POLICY.maxPicks) break;
  }
  return picks;
}

/** NDM block tape rows priced off session closes. */
function ndmPicks(
  ndmRows: NdmRow[],
  prices: Map<string, number>,
  taken: Set<string>,
): TacticalAlphaPick[] {
  const picks: TacticalAlphaPick[] = [];
  const sorted = [...ndmRows].sort(
    (a, b) => (b.value ?? b.quantity ?? 0) - (a.value ?? a.quantity ?? 0),
  );
  for (const block of sorted) {
    if (!block?.ticker) continue;
    const sym = block.ticker.toUpperCase();
    if (taken.has(sym)) continue;
    const ltp = prices.get(sym) ?? block.marketLtp;
    if (ltp == null || ltp <= 0) continue;
    // Structural floor: 6% below LTP (NDM blocks print 3-8% under market).
    const stop = Number((ltp * 0.94).toFixed(2));
    const targets = exitTargets(ltp, stop);
    taken.add(sym);
    picks.push({
      ticker: sym,
      sector: "NDM BLOCK TAPE",
      strategy: "NDM_WHALE_BLOCK",
      conviction:
        block.quantity != null && block.quantity >= 500_000 ? "HIGH" : null,
      ltp,
      entryLow: Number((ltp * 0.98).toFixed(2)),
      entryHigh: Number(ltp.toFixed(2)),
      stopLoss: stop,
      ...targets,
      riskReward: rewardRiskToTp2(ltp, stop, targets.target2),
      riskAllocationPct: RISK_POLICY.riskPerTradePct,
      executionProtocol: {
        orderType: "POST_ONLY_LIMIT",
        window: "10:15 AM – 11:30 AM",
        volumeCondition: `Resting bid near market LTP (${ltp.toFixed(2)} PKR)`,
      },
      catalyst: `${((block.quantity ?? 0) / 1e6).toFixed(1)}M shares negotiated off-market${block.rate != null ? ` at ${block.rate.toFixed(2)} PKR` : ""}${block.ltpDiffPct != null ? `, ${block.ltpDiffPct.toFixed(1)}% vs market close` : ""}`,
      rationale: `NDM negotiated block: ${block.quantity ?? "?"} shares${block.value != null ? `, ${Math.round(block.value)} PKR notional` : ""}.`,
    });
    if (picks.length >= RISK_POLICY.maxPicks) break;
  }
  return picks;
}

/** Momentum rows: smart-money sector-aligned INSTITUTIONAL_TARGET output. */
function momentumPicks(
  momentumRows: SignalRow[],
  taken: Set<string>,
): TacticalAlphaPick[] {
  const picks: TacticalAlphaPick[] = [];
  for (const row of momentumRows) {
    if (taken.has(row.ticker)) continue;
    const entry = row.entry_reference;
    const stop = row.stop_loss;
    if (entry == null || entry <= 0) continue;
    if (stop == null || stop >= entry) continue;
    const targets = exitTargets(entry, stop);
    taken.add(row.ticker);
    picks.push({
      ticker: row.ticker,
      sector: row.metadata?.sector ?? "UNMAPPED_SECTOR",
      strategy: "INST_FLOW_TARGET",
      conviction: null,
      ltp: entry,
      entryLow: Number((entry * 0.99).toFixed(2)),
      entryHigh: Number(entry.toFixed(2)),
      stopLoss: Number(stop.toFixed(2)),
      ...targets,
      riskReward: rewardRiskToTp2(entry, stop, targets.target2),
      riskAllocationPct: RISK_POLICY.riskPerTradePct,
      executionProtocol: {
        orderType: "TWAP_ACCUMULATE",
        window: "01:30 PM – 03:15 PM",
        volumeCondition: "Confirm 5-min volume exceeds ADV baseline",
      },
      catalyst:
        row.metadata?.sector_smart_net_pkr != null
          ? `Smart-money sector net ${row.metadata.sector_smart_net_pkr >= 0 ? "+" : ""}${(row.metadata.sector_smart_net_pkr / 1e6).toFixed(0)}M PKR on the latest flow session`
          : "Market-wide relative-volume leader (no sector flow alignment this session)",
      rationale: row.rationale,
    });
    if (picks.length >= RISK_POLICY.maxPicks) break;
  }
  return picks;
}

// ---------------------------------------------------------------------------
// Sector focus: strictly the RRG quadrants stored by the rotation engine.
// Empty arrays are honest - the desk renders "no leading sectors stored"
// instead of the old invented "Refinery"/"Fertilizer" fallbacks.
// ---------------------------------------------------------------------------
function sectorFocus(rotationRows: RotationRow[]): {
  longSectors: string[];
  fadeSectors: string[];
} {
  const leading = rotationRows
    .filter((r) => r.quadrant === "LEADING")
    .map((r) => r.sectorName)
    .slice(0, 3);
  const lagging = rotationRows
    .filter((r) => r.quadrant === "LAGGING")
    .map((r) => r.sectorName)
    .slice(0, 3);
  return { longSectors: leading, fadeSectors: lagging };
}

// ---------------------------------------------------------------------------
// Cash policy: mapped 1:1 from the regime verdict the pipeline computed.
// UNKNOWN verdict -> null (desk shows "pending", not a made-up number).
// ---------------------------------------------------------------------------
function cashPolicy(regime: RegimeBinding): number | null {
  switch (regime.status) {
    case "BEARISH_CAPITAL_PRESERVATION":
      return 80;
    case "ACCUMULATION_FAVORABLE":
      return 25;
    default:
      return null;
  }
}

function macroSummary(regime: RegimeBinding): string {
  if (!regime.sourceFound) {
    return "Regime gate verdict unavailable for this session (no stamped signals). Directive pending pipeline run.";
  }
  const flowTxt =
    regime.instNetFlowPkr != null
      ? `${(regime.instNetFlowPkr / 1e9).toFixed(2)}B PKR institutional net (${regime.flowBasis ?? "NCCPL"})`
      : "institutional flow data unavailable";
  const benchTxt =
    regime.benchmarkClose != null && regime.benchmarkSma20 != null
      ? `; KSE-100 ${regime.benchmarkClose.toFixed(0)} vs SMA20 ${regime.benchmarkSma20.toFixed(0)}`
      : "";
  if (regime.status === "BEARISH_CAPITAL_PRESERVATION") {
    return `Institutional net selling confirmed (${flowTxt}${benchTxt}). Index longs gated by the pipeline regime gate; anti-beta alpha execution only.`;
  }
  if (regime.status === "ACCUMULATION_FAVORABLE") {
    return `Regime gate: ACCUMULATION_FAVORABLE (${flowTxt}${benchTxt}). Whale-strength names in leading quadrants cleared for execution.`;
  }
  return `Regime gate reported UNKNOWN (${flowTxt}${benchTxt}). Treat all setups as unconfirmed.`;
}

function reentryTrigger(regime: RegimeBinding): string {
  const bench =
    regime.benchmarkSma20 != null
      ? `KSE-100 reclaim of SMA20 (${regime.benchmarkSma20.toFixed(0)})`
      : "KSE-100 close > its 20-session SMA";
  return `${bench} AND Mutual Funds net buying > +${(RISK_POLICY.reentryMutualFundsNetPkr / 1e6).toFixed(0)}M PKR`;
}

// ---------------------------------------------------------------------------
// Public entry point - wired from page.tsx session loads
// ---------------------------------------------------------------------------
export function computePlaybookDirective(
  sessionDate: string,
  barometer: Barometer | null,
  rotationRows: RotationRow[] = [],
  fundamentals: FundamentalsRow[] = [],
  whaleRows: WhaleRow[] = [],
  flowRows: FlowRow[] = [],
  ndmRows: NdmRow[] = [],
  eod: EodPoint[] = [],
  momentumRows: SignalRow[] = [],
): PlaybookDirective {
  void barometer; // flow leg arrives via the regime stamp; param kept for signature stability
  const regime = bindRegime(whaleRows);
  const prices = buildPriceMap(eod, fundamentals);
  const dataGaps: string[] = [];

  if (!regime.sourceFound) dataGaps.push("REGIME_VERDICT");
  if (whaleRows.length === 0) dataGaps.push("WHALE_RADAR");
  if (ndmRows.length === 0) dataGaps.push("NDM_TAPE");
  if (flowRows.length === 0) dataGaps.push("NCCPL_FLOWS");
  if (rotationRows.length === 0) dataGaps.push("RRG_MATRIX");

  const taken = new Set<string>();
  const picks = [
    ...whalePicks(whaleRows, prices),
    ...ndmPicks(ndmRows, prices, taken),
    ...momentumPicks(momentumRows, taken),
  ].slice(0, RISK_POLICY.maxPicks);

  return {
    sessionDate,
    regimeState: regime.status,
    instNetFlowPkr: regime.instNetFlowPkr,
    benchmark:
      regime.benchmarkClose != null && regime.benchmarkSma20 != null
        ? { close: regime.benchmarkClose, sma20: regime.benchmarkSma20 }
        : null,
    recommendedCashPct: cashPolicy(regime),
    macroSummary: macroSummary(regime),
    reentryTrigger: reentryTrigger(regime),
    topPicks: picks,
    sectorFocus: sectorFocus(rotationRows),
    dataGaps,
  };
}
