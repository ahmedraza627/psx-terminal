/**
 * Desk-level data feeds for the institutional expansion desks (rotation
 * persistence, comparison, portfolio analytics). Every fetcher is
 * settle-safe: failures return empty structures instead of rejecting, so
 * one dead table never takes down a desk (the desk renders its idle state).
 */
import { getSupabase } from "./supabase";

// --------------------------------------------------------------- //
// RRG history across sessions (regime persistence tracking).       //
// --------------------------------------------------------------- //
export interface RotationHistoryRow {
  tradeDate: string;
  sectorName: string;
  quadrant: string;
}

export async function fetchRotationHistory(): Promise<
  RotationHistoryRow[]
> {
  try {
    const supabase = getSupabase();
    const { data, error } = await supabase
      .from("psx_sector_rotation")
      .select("trade_date,sector_name,quadrant")
      .order("trade_date", { ascending: false })
      .limit(3000);
    if (error) throw error;
    return ((data ?? []) as unknown as Record<string, unknown>[]).map(
      (r) => ({
        tradeDate: r.trade_date as string,
        sectorName: (r.sector_name as string).toUpperCase(),
        quadrant: (r.quadrant as string) ?? "LAGGING",
      })
    );
  } catch {
    return [];
  }
}

// --------------------------------------------------------------- //
// NCCPL sector-level institutional flows (5-day flow bias).        //
// --------------------------------------------------------------- //
export interface SectorFlowRow {
  sectorName: string;
  /** 5-session net institutional PKR across the named sector. */
  net5dPkr: number;
  /** Latest-session net institutional PKR. */
  netLatestPkr: number;
}

const INST_TYPES = new Set(["MUTUAL FUNDS", "FIPI", "BANKS"]);

export async function fetchSectorFlows(
  sessionDate: string
): Promise<SectorFlowRow[]> {
  try {
    const supabase = getSupabase();
    const { data, error } = await supabase
      .from("nccpl_fipi_lipi")
      .select("trade_date,participant_type,sector_name,net_pkr")
      .order("trade_date", { ascending: false })
      .limit(1500);
    if (error) throw error;
    const rows = (data ?? []) as unknown as {
      trade_date: string;
      participant_type: string;
      sector_name: string;
      net_pkr: number | null;
    }[];
    const dates = Array.from(
      new Set(rows.map((r) => r.trade_date))
    )
      .sort()
      .reverse()
      .slice(0, 5);
    const window = new Set(dates);
    const perSector = new Map<string, { w: number; latest: number }>();
    for (const r of rows) {
      if (!window.has(r.trade_date)) continue;
      const sector = (r.sector_name ?? "ALL").toUpperCase();
      if (sector === "ALL" || sector === "") continue;
      if (!INST_TYPES.has((r.participant_type ?? "").toUpperCase().trim()))
        continue;
      const net = r.net_pkr ?? 0;
      const b = perSector.get(sector) ?? { w: 0, latest: 0 };
      b.w += net;
      if (r.trade_date === dates[0]) b.latest += net;
      perSector.set(sector, b);
    }
    void sessionDate; // flows bind to the newest stored session, not signals
    return Array.from(perSector.entries())
      .map(([sectorName, b]) => ({
        sectorName,
        net5dPkr: Math.round(b.w),
        netLatestPkr: Math.round(b.latest),
      }))
      .sort((a, b2) => b2.net5dPkr - a.net5dPkr);
  } catch {
    return [];
  }
}

// --------------------------------------------------------------- //
// Ticker -> sector map from the fundamentals snapshot.             //
// --------------------------------------------------------------- //
export async function fetchTickerSectorMap(): Promise<Map<string, string>> {
  try {
    const supabase = getSupabase();
    const { data, error } = await supabase
      .from("psx_fundamentals")
      .select("ticker,sector_name")
      .order("trade_date", { ascending: false })
      .limit(1200);
    if (error) throw error;
    const map = new Map<string, string>();
    for (const r of (data ?? []) as unknown as {
      ticker: string;
      sector_name: string | null;
    }[]) {
      const t = (r.ticker ?? "").toUpperCase().trim();
      const s = (r.sector_name ?? "").toUpperCase().trim();
      if (t && s && !map.has(t)) map.set(t, s);
    }
    return map;
  } catch {
    return new Map();
  }
}

// --------------------------------------------------------------- //
// Fundamentals snapshot (DPS screener) for the comparison desk.    //
// --------------------------------------------------------------- //
export interface FundamentalsRow {
  ticker: string;
  sectorName: string | null;
  marketCapPkr: number | null;
  closePrice: number | null;
  peRatio: number | null;
  dividendYield: number | null;
  freeFloat: number | null;
  volume30dAvg: number | null;
}

export async function fetchFundamentalsRows(
  sessionDate: string
): Promise<FundamentalsRow[]> {
  try {
    const supabase = getSupabase();
    const { data, error } = await supabase
      .from("psx_fundamentals")
      .select(
        "trade_date,ticker,sector_name,market_cap_pkr,close_price,"
        + "pe_ratio,dividend_yield,free_float,volume_30d_avg"
      )
      .order("trade_date", { ascending: false })
      .limit(1200);
    if (error) throw error;
    const rows = (data ?? []) as unknown as Record<string, unknown>[];
    // Newest snapshot per ticker (table holds one row per session).
    const seen = new Set<string>();
    const out: FundamentalsRow[] = [];
    for (const r of rows) {
      const ticker = String(r.ticker ?? "").toUpperCase();
      if (!ticker || seen.has(ticker)) continue;
      seen.add(ticker);
      out.push({
        ticker,
        sectorName: (r.sector_name as string | null) ?? null,
        marketCapPkr: (r.market_cap_pkr as number | null) ?? null,
        closePrice: (r.close_price as number | null) ?? null,
        peRatio: (r.pe_ratio as number | null) ?? null,
        dividendYield: (r.dividend_yield as number | null) ?? null,
        freeFloat: (r.free_float as number | null) ?? null,
        volume30dAvg: (r.volume_30d_avg as number | null) ?? null,
      });
    }
    void sessionDate;
    return out;
  } catch {
    return [];
  }
}

// --------------------------------------------------------------- //
// Signal history (per session) for the walk-forward portfolio NAV. //
// --------------------------------------------------------------- //
export interface HistSignal {
  tradeDate: string;
  ticker: string;
  signalType: string;
  entryReference: number | null;
  stopLoss: number | null;
  conviction: string | null;
}

const ACTIONABLE = new Set([
  "ACCUMULATION",
  "STEALTH_ACCUMULATION",
  "INSTITUTIONAL_TARGET",
  "MOMENTUM_BREAKOUT",
  "INSIDER_BUYING",
  "LEVERAGE_FLUSH_BOTTOM",
  "VALUE_YIELD",
  "HIGH_YIELD",
]);

export async function fetchSignalHistory(
  sessions = 31
): Promise<HistSignal[]> {
  try {
    const supabase = getSupabase();
    const { data, error } = await supabase
      .from("signals_computed")
      .select(
        "trade_date,ticker,signal_type,entry_reference,stop_loss,metadata"
      )
      .order("trade_date", { ascending: false })
      .limit(6000);
    if (error) throw error;
    const rows = (data ?? []) as unknown as Record<string, unknown>[];
    const dates = Array.from(new Set(rows.map((r) => String(r.trade_date))))
      .sort()
      .reverse()
      .slice(0, sessions);
    const keep = new Set(dates);
    const out: HistSignal[] = [];
    for (const r of rows) {
      if (!keep.has(String(r.trade_date))) continue;
      const type = String(r.signal_type ?? "");
      if (!ACTIONABLE.has(type)) continue;
      const meta = (r.metadata ?? {}) as Record<string, unknown>;
      out.push({
        tradeDate: String(r.trade_date),
        ticker: String(r.ticker ?? "").toUpperCase(),
        signalType: type,
        entryReference: (r.entry_reference as number | null) ?? null,
        stopLoss: (r.stop_loss as number | null) ?? null,
        conviction:
          (meta.conviction as string | null | undefined) ?? null,
      });
    }
    return out;
  } catch {
    return [];
  }
}

// --------------------------------------------------------------- //
// Session signals for one ticker (inspection drawer).              //
// --------------------------------------------------------------- //
export interface DrawerSignal {
  tradeDate: string;
  ticker: string;
  timeframe: string;
  signalType: string;
  entryReference: number | null;
  stopLoss: number | null;
  rationale: string;
}

export async function fetchSignalsForTicker(
  sessionDate: string,
  ticker: string
): Promise<DrawerSignal[]> {
  try {
    const supabase = getSupabase();
    const { data, error } = await supabase
      .from("signals_computed")
      .select(
        "trade_date,ticker,timeframe,signal_type,entry_reference,stop_loss,rationale"
      )
      .eq("trade_date", sessionDate)
      .eq("ticker", ticker.toUpperCase())
      .limit(20);
    if (error) throw error;
    return ((data ?? []) as unknown as Record<string, unknown>[]).map((r) => ({
      tradeDate: String(r.trade_date),
      ticker: String(r.ticker),
      timeframe: String(r.timeframe),
      signalType: String(r.signal_type),
      entryReference: (r.entry_reference as number | null) ?? null,
      stopLoss: (r.stop_loss as number | null) ?? null,
      rationale: String(r.rationale ?? ""),
    }));
  } catch {
    return [];
  }
}

// --------------------------------------------------------------- //
// Recent OHLCV for one ticker (execution desk).                    //
// --------------------------------------------------------------- //
export interface OhlcvRow {
  tradeDate: string;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  volume: number | null;
}

export async function fetchTickerOhlcv(
  ticker: string,
  sessions = 5
): Promise<OhlcvRow[]> {
  try {
    const supabase = getSupabase();
    const { data, error } = await supabase
      .from("psx_daily_eod")
      .select(
        "trade_date,open_price,high_price,low_price,close_price,volume"
      )
      .eq("ticker", ticker.toUpperCase())
      .order("trade_date", { ascending: false })
      .limit(sessions);
    if (error) throw error;
    return ((data ?? []) as unknown as Record<string, unknown>[]).map((r) => ({
      tradeDate: String(r.trade_date),
      open: (r.open_price as number | null) ?? null,
      high: (r.high_price as number | null) ?? null,
      low: (r.low_price as number | null) ?? null,
      close: (r.close_price as number | null) ?? null,
      volume: (r.volume as number | null) ?? null,
    }));
  } catch {
    return [];
  }
}

// --------------------------------------------------------------- //
// EOD history for portfolio analytics + comparison desk.           //
// --------------------------------------------------------------- //
export interface EodPoint {
  ticker: string;
  tradeDate: string;
  close: number | null;
  volume: number | null;
}

export async function fetchEodHistory(
  sessionDate: string,
  sessions = 90
): Promise<EodPoint[]> {
  try {
    const supabase = getSupabase();
    const { data, error } = await supabase
      .from("psx_daily_eod")
      .select("trade_date,ticker,close_price,volume")
      .order("trade_date", { ascending: false })
      .limit(sessions * 600);
    if (error) throw error;
    const rows = (data ?? []) as unknown as {
      trade_date: string;
      ticker: string;
      close_price: number | null;
      volume: number | null;
    }[];
    // Keep only rows within the trailing N distinct sessions.
    const dates = Array.from(new Set(rows.map((r) => r.trade_date)))
      .sort()
      .reverse()
      .slice(0, sessions);
    const keep = new Set(dates);
    return rows
      .filter((r) => keep.has(r.trade_date))
      .map((r) => ({
        ticker: r.ticker,
        tradeDate: r.trade_date,
        close: r.close_price,
        volume: r.volume,
      }));
  } catch {
    return [];
  }
}
