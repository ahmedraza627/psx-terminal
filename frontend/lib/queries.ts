import { getSupabase } from "./supabase";
import type {
  EodRow,
  FlowRow,
  OffmarketRow,
  SignalRow,
  SignalMetadata,
  Timeframe,
} from "./types";
import type { InsiderRow } from "@/components/InsiderRadarBlotter";
import type { MtsRow } from "@/components/MtsSqueezeBlotter";
import type { RolloverRow } from "@/components/RolloverDeskBlotter";
import type { ResearchRow } from "@/components/ResearchDeskBlotter";
import type { RotationRow } from "@/components/SectorRotationBlotter";
import type { SizingSignal } from "@/lib/risk";

export interface Barometer {
  tradeDate: string;
  institutionalNet: number;
  retailNet: number;
  divergence: "SMART_MONEY_ACCUMULATION" | "RETAIL_TRAP_RISK" | "ALIGNED";
}

/**
 * Explicit feed status for optional desks whose upstream sources are gated
 * (NCCPL MTS portal, PSX company-announcement insider disclosures). Rendered
 * as institutional status pills instead of silent blank states.
 */
export interface DataStatus {
  /** Table exists in Supabase but has no rows yet. */
  feedPending: boolean;
  /** Table itself is missing (schema migration not yet applied). */
  tableMissing: boolean;
  /** Probe/query failed for a non-schema reason (network / auth / 4xx-5xx). */
  unreachable?: boolean;
}

const OPTIONAL_TABLES = ["psx_insider_trades", "nccpl_mts_leverage"] as const;

/** True when a Supabase error is the missing-table / un-migrated-schema case. */
function isTableMissing(err: unknown): boolean {
  const code = (err as { code?: string } | null)?.code;
  const message = err instanceof Error ? err.message : String(err);
  return (
    code === "PGRST205" ||
    /schema cache|Could not find the table/i.test(message)
  );
}

export interface WhaleRow extends SignalRow {
  meta: SignalMetadata;
}

export interface ArbitrageRow {
  tradeDate: string;
  ticker: string;
  readyClose: number | null;
  futuresClose: number | null;
  futuresSymbol: string | null;
  spreadPct: number | null;
  annualizedSimplePct: number | null;
  annualizedCompoundPct: number | null;
  order: string | null;
  rationale: string;
}

export interface NdmRow {
  tradeDate: string;
  ticker: string;
  quantity: number | null;
  rate: number | null;
  value: number | null;
  marketLtp: number | null;
  ltpDiffPct: number | null;
}

// ------------------------------------------------------------------ //
// Active session date: MAX(trade_date) from psx_daily_eod.           //
// The single source of truth for every downstream query - never the  //
// browser wall clock (weekends/holidays would otherwise query an     //
// empty session and render 0 rows everywhere).                       //
// ------------------------------------------------------------------ //
export async function fetchActiveSessionDate(): Promise<string | null> {
  const supabase = getSupabase();
  const { data, error } = await supabase
    .from("signals_computed")
    .select("trade_date")
    .order("trade_date", { ascending: false })
    .limit(1);
  if (error) throw error;
  const rows = data as { trade_date: string }[] | null;
  return rows && rows.length > 0 ? rows[0].trade_date : null;
}

// ------------------------------------------------------------------ //
// Barometer: institutional vs retail net flows for the resolved        //
// session. NCCPL FIPI/LIPI layout (verified against live data):        //
//   - participant rows (MUTUAL FUNDS, BANKS, INDIVIDUALS, ...) carry   //
//     real sector names ("CEMENT", "ALL OTHER SECTORS", ...)          //
//   - the only sector_name='ALL' rows are FOREIGN TOTAL / LOCAL TOTAL  //
//     grand totals (opposite signs) which cancel to ~0                 //
// Therefore: exclude sector 'ALL', then aggregate per participant:     //
//   Institutions = MUTUAL FUNDS + FIPI (foreign portfolio) + BANKS     //
//   Retail       = INDIVIDUALS                                         //
// ------------------------------------------------------------------ //
export async function fetchBarometer(
  sessionDate: string
): Promise<Barometer | null> {
  const supabase = getSupabase();
  // Pull a generous window of recent rows in one request, then slice to the
  // bound session client-side (row count is small: ~12 participants x 11
  // sectors x ~5 sessions).
  const { data, error } = await supabase
    .from("nccpl_fipi_lipi")
    .select("trade_date,participant_type,sector_name,net_pkr")
    .order("trade_date", { ascending: false })
    .limit(600);
  if (error) throw error;
  const rows = (data ?? []) as FlowRow[];
  if (rows.length === 0) return null;

  // Bind to the active session when flows exist for it; otherwise the
  // most recent flow session present in the table.
  const hasActiveSession = rows.some((r) => r.trade_date === sessionDate);
  const boundDate = hasActiveSession
    ? sessionDate
    : rows[0].trade_date;

  const INSTITUTIONAL = new Set(["MUTUAL FUNDS", "FIPI", "BANKS"]);
  let institutionalNet = 0;
  let retailNet = 0;
  for (const row of rows) {
    if (row.trade_date !== boundDate) continue;
    if ((row.sector_name ?? "ALL").toUpperCase() === "ALL") continue; // totals cancel
    const type = (row.participant_type ?? "").toUpperCase().trim();
    const net = row.net_pkr ?? 0;
    if (INSTITUTIONAL.has(type)) institutionalNet += net;
    else if (type === "INDIVIDUALS") retailNet += net;
  }

  const divergence: Barometer["divergence"] =
    institutionalNet > 0 && retailNet < 0
      ? "SMART_MONEY_ACCUMULATION"
      : retailNet > 0 && institutionalNet < 0
        ? "RETAIL_TRAP_RISK"
        : "ALIGNED";

  return { tradeDate: boundDate, institutionalNet, retailNet, divergence };
}

// ------------------------------------------------- //
// Whale Radar: STEALTH_ACCUMULATION blotter + count  //
// ------------------------------------------------- //
export async function fetchWhaleRows(
  sessionDate: string
): Promise<WhaleRow[]> {
  const supabase = getSupabase();
  const { data, error } = await supabase
    .from("signals_computed")
    .select(
      "trade_date,ticker,timeframe,signal_type,entry_reference,stop_loss,rationale,metadata"
    )
    .eq("timeframe", "WHALE_RADAR")
    .eq("trade_date", sessionDate)
    .order("ticker")
    .limit(200);
  if (error) throw error;
  return ((data ?? []) as SignalRow[])
    .filter((r) => r.metadata != null)
    .map((r) => ({ ...r, meta: r.metadata as SignalMetadata }));
}

export async function fetchWhaleCount(
  sessionDate: string
): Promise<number> {
  const supabase = getSupabase();
  const { count, error } = await supabase
    .from("signals_computed")
    .select("id", { count: "exact", head: true })
    .eq("timeframe", "WHALE_RADAR")
    .eq("trade_date", sessionDate);
  if (error) throw error;
  return count ?? 0;
}

/**
 * True when psx_futures_eod has no contract rows at all - i.e. the PSX
 * futures feed never delivered closes, so the desk shows its offline
 * banner instead of an empty scan result.
 */
export async function fetchFuturesFeedOffline(): Promise<boolean> {
  const supabase = getSupabase();
  const { count, error } = await supabase
    .from("psx_futures_eod")
    .select("id", { count: "exact", head: true });
  if (error) throw error;
  return (count ?? 0) === 0;
}

// --------------------------------------------------- //
// Arbitrage desk: CASH_CARRY rows mapped from metadata //
// --------------------------------------------------- //
export async function fetchArbitrageRows(
  sessionDate: string
): Promise<ArbitrageRow[]> {
  const supabase = getSupabase();
  const { data, error } = await supabase
    .from("signals_computed")
    .select(
      "trade_date,ticker,timeframe,signal_type,entry_reference,stop_loss,rationale,metadata"
    )
    .eq("timeframe", "ARBITRAGE")
    .eq("trade_date", sessionDate)
    .order("ticker")
    .limit(200);
  if (error) throw error;
  return ((data ?? []) as SignalRow[]).map((r) => {
    const meta = r.metadata ?? {};
    return {
      tradeDate: r.trade_date,
      ticker: r.ticker,
      readyClose: meta.ready_close ?? r.entry_reference,
      futuresClose: meta.futures_close ?? null,
      futuresSymbol: meta.futures_symbol ?? null,
      spreadPct: meta.spread_pct ?? null,
      annualizedSimplePct: meta.annualized_simple_pct ?? null,
      annualizedCompoundPct: meta.annualized_compound_pct ?? null,
      order: meta.order ?? null,
      rationale: r.rationale,
    };
  });
}

// --------------------------------------------------------- //
// Institutional momentum: INSTITUTIONAL_TARGET signals.       //
// Covers BOTH engine paths: strict sector-aligned rows        //
// (sector_smart_net_pkr populated) and the market-wide        //
// top-relative-volume fallback (fallback:true, smart-net      //
// null). Rows are returned as-is - the blotter renders the    //
// metadata it finds - so neither path can collapse to 0.      //
// --------------------------------------------------------- //
export async function fetchMomentumRows(
  sessionDate: string
): Promise<SignalRow[]> {
  const supabase = getSupabase();
  const { data, error } = await supabase
    .from("signals_computed")
    .select(
      "trade_date,ticker,timeframe,signal_type,entry_reference,stop_loss,rationale,metadata"
    )
    .eq("timeframe", "MOMENTUM")
    .eq("trade_date", sessionDate)
    .order("ticker")
    .limit(200);
  if (error) throw error;
  return (data ?? []).filter(
    (r): r is SignalRow =>
      r != null &&
      typeof r.ticker === "string" &&
      r.ticker.length > 0
  );
}

export async function fetchMomentumCount(
  sessionDate: string
): Promise<number> {
  const supabase = getSupabase();
  const { count, error } = await supabase
    .from("signals_computed")
    .select("id", { count: "exact", head: true })
    .eq("timeframe", "MOMENTUM")
    .eq("trade_date", sessionDate);
  if (error) throw error;
  return count ?? 0;
}

// --------------------------------------------------- //
// NDM block tape for the active session, joined with  //
// same-session market LTP for the executed-rate diff  //
// --------------------------------------------------- //
export async function fetchNdmTape(
  sessionDate: string,
  minShares = 50_000
): Promise<NdmRow[]> {
  const supabase = getSupabase();
  const { data, error } = await supabase
    .from("psx_offmarket_deals")
    .select("trade_date,ticker,quantity,rate,value")
    .eq("trade_date", sessionDate)
    .gte("quantity", minShares)
    .order("value", { ascending: false })
    .limit(300);
  if (error) throw error;
  const rows = (data ?? []) as OffmarketRow[];
  if (rows.length === 0) return [];

  const tickers = Array.from(new Set(rows.map((r) => r.ticker)));
  const { data: eodData, error: eodError } = await supabase
    .from("psx_daily_eod")
    .select("trade_date,ticker,close_price")
    .eq("trade_date", sessionDate)
    .in("ticker", tickers)
    .limit(2000);
  if (eodError) throw eodError;

  const ltp = new Map<string, number>();
  for (const row of (eodData ?? []) as EodRow[]) {
    if (row.close_price != null && !ltp.has(row.ticker)) {
      ltp.set(row.ticker, row.close_price);
    }
  }

  return rows.map((r) => {
    const marketLtp = ltp.get(r.ticker) ?? null;
    const ltpDiffPct =
      marketLtp != null && r.rate != null && marketLtp > 0
        ? (r.rate - marketLtp) / marketLtp * 100
        : null;
    return {
      tradeDate: r.trade_date,
      ticker: r.ticker,
      quantity: r.quantity,
      rate: r.rate,
      value: r.value,
      marketLtp,
      ltpDiffPct,
    };
  });
}

// --------------------------------------------------------------------------- //
// INSIDER_RADAR: aggregated SECP/sponsor net buying for the session            //
// --------------------------------------------------------------------------- //
export async function fetchInsiderRows(
  sessionDate: string
): Promise<InsiderRow[]> {
  const supabase = getSupabase();
  const { data, error } = await supabase
    .from("signals_computed")
    .select(
      "trade_date,ticker,timeframe,signal_type,entry_reference,stop_loss,rationale,metadata"
    )
    .eq("timeframe", "INSIDER_RADAR")
    .eq("trade_date", sessionDate)
    .order("ticker")
    .limit(200);
  if (error) throw error;
  return ((data ?? []) as SignalRow[]).map((r) => {
    const meta = r.metadata ?? {};
    return {
      tradeDate: r.trade_date,
      ticker: r.ticker,
      entryReference: r.entry_reference,
      netNotionalPkr: meta.net_notional_pkr ?? null,
      disclosureCount: meta.disclosure_count ?? null,
      seniorDisclosures: meta.senior_disclosures ?? null,
      conviction: meta.conviction ?? null,
      rationale: r.rationale,
    };
  });
}

// --------------------------------------------------------------------------- //
// MTS_SQUEEZE: margin cascade risk & leverage flush bottoms                    //
// --------------------------------------------------------------------------- //
export async function fetchMtsRows(sessionDate: string): Promise<MtsRow[]> {
  const supabase = getSupabase();
  const { data, error } = await supabase
    .from("signals_computed")
    .select(
      "trade_date,ticker,timeframe,signal_type,entry_reference,stop_loss,rationale,metadata"
    )
    .eq("timeframe", "MTS_SQUEEZE")
    .eq("trade_date", sessionDate)
    .order("ticker")
    .limit(200);
  if (error) throw error;
  return ((data ?? []) as SignalRow[]).map((r) => {
    const meta = r.metadata ?? {};
    return {
      tradeDate: r.trade_date,
      ticker: r.ticker,
      entryReference: r.entry_reference,
      signalType: r.signal_type,
      utilizationPct: meta.mts_utilization_pct ?? null,
      valueDropPct: meta.mts_value_drop_pct ?? null,
      priceDropPct: meta.price_drop_pct ?? null,
      mtsValuePkr: meta.mts_value_pkr ?? null,
      stance: meta.stance ?? null,
      rationale: r.rationale,
    };
  });
}

// --------------------------------------------------------------------------- //
// ROLLOVER_DESK: futures basis inversion & short squeeze watch                 //
// --------------------------------------------------------------------------- //
export async function fetchRolloverRows(
  sessionDate: string
): Promise<RolloverRow[]> {
  const supabase = getSupabase();
  const { data, error } = await supabase
    .from("signals_computed")
    .select(
      "trade_date,ticker,timeframe,signal_type,entry_reference,stop_loss,rationale,metadata"
    )
    .eq("timeframe", "ROLLOVER_DESK")
    .eq("trade_date", sessionDate)
    .order("ticker")
    .limit(200);
  if (error) throw error;
  return ((data ?? []) as SignalRow[]).map((r) => {
    const meta = r.metadata ?? {};
    return {
      tradeDate: r.trade_date,
      ticker: r.ticker,
      entryReference: r.entry_reference,
      signalType: r.signal_type,
      futuresSymbol: meta.futures_symbol ?? null,
      futuresClose: meta.futures_close ?? null,
      spotClose: meta.spot_close ?? null,
      basisPct: meta.basis_pct ?? null,
      basisPrevPct: meta.basis_prev_pct ?? null,
      stance: meta.stance ?? null,
      rationale: r.rationale,
    };
  });
}

export type {
  Timeframe,
  InsiderRow,
  MtsRow,
  RolloverRow,
  ResearchRow,
  RotationRow,
};

// --------------------------------------------------------------------------- //
// RISK DESK: every signal for the session, mapped for the position sizer       //
// --------------------------------------------------------------------------- //
export async function fetchSessionSignals(
  sessionDate: string
): Promise<SizingSignal[]> {
  const supabase = getSupabase();
  const { data, error } = await supabase
    .from("signals_computed")
    .select(
      "trade_date,ticker,timeframe,signal_type,entry_reference,stop_loss,metadata"
    )
    .eq("trade_date", sessionDate)
    .order("ticker")
    .limit(1000);
  if (error) throw error;
  return ((data ?? []) as SignalRow[]).map((r) => ({
    ticker: r.ticker,
    signalType: r.signal_type,
    entryReference: r.entry_reference,
    stopLoss: r.stop_loss,
    conviction: r.metadata?.conviction ?? null,
  }));
}

// --------------------------------------------------------------------------- //
// EDGE ANALYTICS: forward performance of evaluated signals (2R convention).    //
// expectancyR = hitRate*2 - (1-hitRate); winners bank +2R, losers pay -1R.     //
// --------------------------------------------------------------------------- //
export interface BacktestRow {
  signalId: number;
  ticker: string;
  tradeDate: string;
  signalType: string;
  entryPrice: number | null;
  stopLoss: number | null;
  returnT5Pct: number | null;
  returnT10Pct: number | null;
  returnT20Pct: number | null;
  mfePct: number | null;
  maePct: number | null;
  hitTarget: boolean | null;
  stoppedOut: boolean | null;
}

export interface EdgeSummary {
  signalType: string;
  signals: number;
  resolved: number;
  hitRatePct: number | null;
  stoppedPct: number | null;
  avgT5Pct: number | null;
  avgT10Pct: number | null;
  avgT20Pct: number | null;
  avgMfePct: number | null;
  avgMaePct: number | null;
  expectancyR: number | null;
  /** Gross wins / gross losses in R units (winners +2R, losers -1R).
   *  Infinity when resolved winners exist but no stop-out ever fired. */
  profitFactor: number | null;
}

export async function fetchBacktestRows(): Promise<{
  rows: BacktestRow[];
  tableMissing: boolean;
}> {
  const supabase = getSupabase();
  try {
    const { data, error } = await supabase
      .from("signal_backtest_performance")
      .select(
        "signal_id,ticker,trade_date,signal_type,entry_price,stop_loss,"
        + "return_t5_pct,return_t10_pct,return_t20_pct,"
        + "max_favorable_excursion_pct,max_adverse_excursion_pct,"
        + "hit_target,stopped_out"
      )
      .order("trade_date", { ascending: false })
      .limit(2000);
    if (error) throw error;
    const rows = ((data ?? []) as unknown as Record<string, unknown>[]).map((r) => ({
      signalId: r.signal_id as number,
      ticker: r.ticker as string,
      tradeDate: r.trade_date as string,
      signalType: r.signal_type as string,
      entryPrice: (r.entry_price as number | null) ?? null,
      stopLoss: (r.stop_loss as number | null) ?? null,
      returnT5Pct: (r.return_t5_pct as number | null) ?? null,
      returnT10Pct: (r.return_t10_pct as number | null) ?? null,
      returnT20Pct: (r.return_t20_pct as number | null) ?? null,
      mfePct: (r.max_favorable_excursion_pct as number | null) ?? null,
      maePct: (r.max_adverse_excursion_pct as number | null) ?? null,
      hitTarget: (r.hit_target as boolean | null) ?? null,
      stoppedOut: (r.stopped_out as boolean | null) ?? null,
    }));
    return { rows, tableMissing: false };
  } catch {
    // Never reject: Edge Lab degrades to its empty state and the health
    // pill comes from fetchFeedStatuses().unreachable instead.
    return { rows: [], tableMissing: false };
  }
}

/** Client-side per-signal-type aggregation over stored backtest rows. */
export function summarizeEdge(rows: BacktestRow[]): EdgeSummary[] {
  const buckets = new Map<
    string,
    {
      n: number;
      resolved: number;
      hits: number;
      stops: number;
      t5: number[];
      t10: number[];
      t20: number[];
      mfe: number[];
      mae: number[];
    }
  >();
  for (const row of rows) {
    const b = buckets.get(row.signalType) ?? {
      n: 0,
      resolved: 0,
      hits: 0,
      stops: 0,
      t5: [],
      t10: [],
      t20: [],
      mfe: [],
      mae: [],
    };
    b.n += 1;
    if (row.hitTarget != null) {
      b.resolved += 1;
      if (row.hitTarget) b.hits += 1;
      else if (row.stoppedOut) b.stops += 1;
    }
    if (row.returnT5Pct != null) b.t5.push(row.returnT5Pct);
    if (row.returnT10Pct != null) b.t10.push(row.returnT10Pct);
    if (row.returnT20Pct != null) b.t20.push(row.returnT20Pct);
    if (row.mfePct != null) b.mfe.push(row.mfePct);
    if (row.maePct != null) b.mae.push(row.maePct);
    buckets.set(row.signalType, b);
  }

  const avg = (values: number[]): number | null =>
    values.length === 0
      ? null
      : Math.round((values.reduce((a, v) => a + v, 0) / values.length) * 100) / 100;

  const summary: EdgeSummary[] = [];
  for (const [signalType, b] of Array.from(buckets.entries())) {
    const hitRatePct =
      b.resolved === 0 ? null : Math.round((b.hits / b.resolved) * 1000) / 10;
    const expectancyR =
      hitRatePct == null
        ? null
        : Math.round(((hitRatePct / 100) * 2 - (1 - hitRatePct / 100)) * 100) / 100;
    const profitFactor =
      b.resolved === 0
        ? null
        : b.stops === 0
          ? b.hits > 0
            ? Number.POSITIVE_INFINITY
            : null
          : Math.round((b.hits * 2) / b.stops * 100) / 100;
    summary.push({
      signalType,
      signals: b.n,
      resolved: b.resolved,
      hitRatePct,
      stoppedPct:
        b.resolved === 0 ? null : Math.round((b.stops / b.resolved) * 1000) / 10,
      avgT5Pct: avg(b.t5),
      avgT10Pct: avg(b.t10),
      avgT20Pct: avg(b.t20),
      avgMfePct: avg(b.mfe),
      avgMaePct: avg(b.mae),
      expectancyR,
      profitFactor,
    });
  }
  summary.sort(
    (a, b) => (b.expectancyR ?? -9) - (a.expectancyR ?? -9)
  );
  return summary;
}

// --------------------------------------------------------------------------- //
// Optional-feed status: distinguish "feed pending" (table exists, empty) from  //
// "table missing" (migration not applied) for the MTS / insider desks.         //
// --------------------------------------------------------------------------- //
export async function fetchFeedStatuses(): Promise<{
  insider: DataStatus;
  mts: DataStatus;
  research: DataStatus;
  rotation: DataStatus;
  kibor: DataStatus;
  disclosures: DataStatus;
}> {
  const supabase = getSupabase();
  const read = async (table: string): Promise<DataStatus> => {
    try {
      const { count, error } = await supabase
        .from(table)
        .select("id", { count: "exact", head: true });
      if (error) {
        if (
          (error as { code?: string }).code === "PGRST205" ||
          /schema cache|Could not find the table/i.test(error.message ?? "")
        ) {
          return { feedPending: false, tableMissing: true };
        }
        return { feedPending: true, tableMissing: false, unreachable: true };
      }
      return { feedPending: (count ?? 0) === 0, tableMissing: false };
    } catch {
      // Network / auth failure - NOT a missing table.
      return { feedPending: false, tableMissing: false, unreachable: true };
    }
  };
  const [insider, mts, research, rotation, kibor, disclosures] =
    await Promise.all([
      read(OPTIONAL_TABLES[0]),
      read(OPTIONAL_TABLES[1]),
      read("psx_equity_research"),
      read("psx_sector_rotation"),
      read("psx_kibor_sensitivity"),
      read("psx_insider_disclosures"),
    ]);
  return { insider, mts, research, rotation, kibor, disclosures };
}

// --------------------------------------------------------------------------- //
// FUNDAMENTAL RESEARCH DESK: alpha scores + intrinsic valuation matrix.        //
// --------------------------------------------------------------------------- //
export async function fetchResearchRows(
  sessionDate: string
): Promise<ResearchRow[]> {
  const supabase = getSupabase();
  const base =
    "trade_date,ticker,alpha_score,intrinsic_value_pkr,"
    + "valuation_discount_pct,valuation_status,balance_sheet_risk_flag";
  const full = `${base},target_pe_used,dividend_floor_pkr,model_version`;
  const read = async (columns: string) => {
    const { data, error } = await supabase
      .from("psx_equity_research")
      .select(columns)
      .eq("trade_date", sessionDate)
      .order("alpha_score", { ascending: false })
      .limit(120);
    if (error) throw error;
    return (data ?? []) as unknown as Record<string, unknown>[];
  };
  try {
    let rows: Record<string, unknown>[];
    try {
      rows = await read(full);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      if (
        (err as { code?: string }).code === "PGRST204" ||
        /target_pe_used|model_version|column/i.test(message)
      ) {
        // Provenance columns not migrated yet - fall back to base columns.
        rows = await read(base);
      } else {
        // Never reject: the desk renders its error pill and the rest of the
        // terminal stays up.
        return [];
      }
    }
    return rows.map((r) => ({
      tradeDate: r.trade_date as string,
      ticker: r.ticker as string,
      alphaScore: Number(r.alpha_score ?? 0),
      intrinsicValuePkr: (r.intrinsic_value_pkr as number | null) ?? null,
      valuationDiscountPct: (r.valuation_discount_pct as number | null) ?? null,
      valuationStatus: (r.valuation_status as string) ?? "FAIR_VALUE",
      balanceSheetRiskFlag: (r.balance_sheet_risk_flag as string | null) ?? null,
      targetPeUsed: (r.target_pe_used as number | null) ?? null,
      dividendFloorPkr: (r.dividend_floor_pkr as number | null) ?? null,
      modelVersion: (r.model_version as string | null) ?? null,
    }));
  } catch (err) {
    if (isTableMissing(err)) return [];
    throw err;
  }
}

// --------------------------------------------------------------------------- //
// KIBOR EASING DESK: projected EPS expansion per rate cut per ticker.          //
// --------------------------------------------------------------------------- //
export interface KiborRow {
  tradeDate: string;
  ticker: string;
  sectorName: string | null;
  floatingDebtPkr: number | null;
  currentEps: number | null;
  epsImpact100bpsPkr: number | null;
  epsExpansion300bpsPct: number | null;
}

/** Projected EPS expansion % for an arbitrary rate cut (linear scaling). */
export function epsExpansionAtBps(row: KiborRow, bps: number): number | null {
  const base = row.epsExpansion300bpsPct;
  if (base == null) return null;
  return Math.round((base * bps) / 300 * 100) / 100;
}

export async function fetchKiborRows(
  sessionDate: string
): Promise<KiborRow[]> {
  const supabase = getSupabase();
  try {
    // v1 live table columns (floating_debt / eps_impact_per_100bps /
    // eps_growth_300bps_pct). Mirrors pipeline emit in kibor_engine.py.
    const { data, error } = await supabase
      .from("psx_kibor_sensitivity")
      .select(
        "trade_date,ticker,sector_name,floating_debt,total_debt,"
        + "current_eps,eps_impact_per_100bps,eps_growth_300bps_pct"
      )
      .eq("trade_date", sessionDate)
      .order("eps_growth_300bps_pct", { ascending: false })
      .limit(200);
    if (error) throw error;
    return ((data ?? []) as unknown as Record<string, unknown>[]).map((r) => ({
      tradeDate: r.trade_date as string,
      ticker: r.ticker as string,
      sectorName: (r.sector_name as string | null) ?? null,
      floatingDebtPkr: (r.floating_debt as number | null) ??
        (r.total_debt as number | null) ??
        null,
      currentEps: (r.current_eps as number | null) ?? null,
      epsImpact100bpsPkr: (r.eps_impact_per_100bps as number | null) ?? null,
      epsExpansion300bpsPct: (r.eps_growth_300bps_pct as number | null) ?? null,
    }));
  } catch {
    return [];
  }
}

// --------------------------------------------------------------------------- //
// INSIDER CONVICTION DESK: parsed board-letter filings, conviction-tagged.     //
// --------------------------------------------------------------------------- //
export interface DisclosureRow {
  tradeDate: string;
  ticker: string;
  insiderName: string;
  designation: string;
  tradeType: string;
  quantity: number;
  rate: number | null;
  notionalPkr: number | null;
  conviction: string;
  disclosureUrl: string | null;
}

export async function fetchDisclosureRows(
  sessionDate: string
): Promise<DisclosureRow[]> {
  const supabase = getSupabase();
  try {
    const { data, error } = await supabase
      .from("psx_insider_disclosures")
      .select(
        "trade_date,ticker,insider_name,designation,trade_type,quantity,"
        + "rate,notional_pkr,conviction,disclosure_url"
      )
      .eq("trade_date", sessionDate)
      .order("notional_pkr", { ascending: false })
      .limit(200);
    if (error) throw error;
    return ((data ?? []) as unknown as Record<string, unknown>[]).map((r) => ({
      tradeDate: r.trade_date as string,
      ticker: r.ticker as string,
      insiderName: (r.insider_name as string) ?? "UNKNOWN",
      designation: (r.designation as string) ?? "UNKNOWN",
      tradeType: (r.trade_type as string) ?? "BUY",
      quantity: Number(r.quantity ?? 0),
      rate: (r.rate as number | null) ?? null,
      notionalPkr: (r.notional_pkr as number | null) ?? null,
      conviction: (r.conviction as string) ?? "STANDARD",
      disclosureUrl: (r.disclosure_url as string | null) ?? null,
    }));
  } catch {
    return [];
  }
}

// --------------------------------------------------------------------------- //
// SECTOR ROTATION (RRG): relative strength vs KSE-100, newest session first.   //
// --------------------------------------------------------------------------- //
export async function fetchRotationRows(
  sessionDate: string
): Promise<RotationRow[]> {
  const supabase = getSupabase();
  try {
    const { data, error } = await supabase
      .from("psx_sector_rotation")
      .select(
        "trade_date,sector_name,rs_ratio,rs_momentum,quadrant,"
        + "top_leader_ticker,top_dragger_ticker"
      )
      .eq("trade_date", sessionDate)
      .order("rs_ratio", { ascending: false })
      .limit(60);
    if (error) throw error;
    return ((data ?? []) as unknown as Record<string, unknown>[]).map((r) => ({
      tradeDate: r.trade_date as string,
      sectorName: r.sector_name as string,
      rsRatio: Number(r.rs_ratio ?? 100),
      rsMomentum: Number(r.rs_momentum ?? 100),
      quadrant: (r.quadrant as RotationRow["quadrant"]) ?? "LAGGING",
      topLeaderTicker: (r.top_leader_ticker as string | null) ?? null,
      topDraggerTicker: (r.top_dragger_ticker as string | null) ?? null,
    }));
  } catch {
    return [];
  }
}
