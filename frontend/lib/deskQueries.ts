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
  /** Forward-compatible: rendered once a feed publishes book value. */
  pbRatio?: number | null;
  /** Forward-compatible: rendered once a feed publishes EBITDA + net debt. */
  evEbitda?: number | null;
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
// --------------------------------------------------------------- //
// NCCPL FIPI/LIPI flow matrix for the Institutional Flow desk.     //
// Columns mirror the live table exactly (no PGRST204 risk).        //
// --------------------------------------------------------------- //
export interface FlowRow {
  tradeDate: string;
  participantType: string;
  sectorName: string;
  netPkr: number | null;
}

export async function fetchFlowMatrix(): Promise<FlowRow[]> {
  try {
    const supabase = getSupabase();
    const { data, error } = await supabase
      .from("nccpl_fipi_lipi")
      .select("trade_date,participant_type,sector_name,net_pkr")
      .order("trade_date", { ascending: false })
      .limit(3000);
    if (error) throw error;
    return ((data ?? []) as unknown as Record<string, unknown>[]).map((r) => ({
      tradeDate: String(r.trade_date),
      participantType: String(r.participant_type ?? "").toUpperCase().trim(),
      sectorName: String(r.sector_name ?? "ALL").toUpperCase().trim(),
      netPkr: (r.net_pkr as number | null) ?? null,
    }));
  } catch {
    return [];
  }
}

/**
 * Amihud illiquidity from a chronological close/volume series:
 * mean(|daily return| / PKR turnover) x1e6 over the trailing `window`
 * sessions. Shared by the Market Breadth desk and the command-bar quote HUD
 * so both surfaces rank liquidity identically. Returns null when fewer than
 * `minValid` sessions carry a positive turnover — never imputed.
 */
export function computeAmihudStats(
  rows: { close: number | null; volume: number | null }[],
  window = 20,
  minValid = 10
): { amihud: number | null; medianTurnoverPkr: number | null } {
  const tail = rows.slice(-(window + 1));
  const vals: number[] = [];
  const turnovers: number[] = [];
  for (let i = 1; i < tail.length; i++) {
    const prevClose = tail[i - 1].close;
    const onClose = tail[i].close;
    const vol = tail[i].volume;
    if (prevClose == null || prevClose <= 0 || onClose == null) continue;
    const turnover = vol != null ? vol * onClose : null;
    if (turnover == null || turnover <= 0) continue;
    const ret = Math.abs((onClose - prevClose) / prevClose);
    vals.push((ret / turnover) * 1e6);
    turnovers.push(turnover);
  }
  const amihud =
    vals.length >= minValid
      ? vals.reduce((a, b) => a + b, 0) / vals.length
      : null;
  const medianTurnoverPkr =
    turnovers.length > 0
      ? turnovers.slice().sort((a, b) => a - b)[Math.floor(turnovers.length / 2)]
      : null;
  return { amihud, medianTurnoverPkr };
}

/**
 * Sector smart-money engine — shared by the Institutional Flow desk and the
 * Insights Wire signal engine (one formula source, never divergent).
 *
 * Rolls nccpl_fipi_lipi institutional nets per sector across trailing
 * windows and pairs them with equal-weight sector price returns computed
 * from stored EOD closes, enabling absorption-accumulation detection:
 * institutions net-buying a sector whose price is falling.
 */
export interface SectorSmartMoneyRow {
  sector: string;
  /** Net institutional PKR, newest stored flow session. */
  latestPkr: number;
  net5dPkr: number;
  net15dPkr: number;
  net30dPkr: number;
  /** Persistence score: 5D/30D + 15D/30D (±2 cap when 30D is flat). */
  score: number;
  /** Equal-weight sector price return over the 5 newest EOD sessions (%). */
  price5dPct: number | null;
  /** Institutional 5D net > 0 while price5d < -1% — absorption pattern. */
  absorption: boolean;
}

export interface SmartMoneyInputs {
  /** Flow rows keyed by participant_type / sector_name / net_pkr. */
  flows: {
    tradeDate: string;
    participantType: string;
    sectorName: string;
    netPkr: number | null;
  }[];
  /** Stored EOD closes (any window ≥ 5 sessions). */
  eod: { tradeDate: string; ticker: string; close: number | null }[];
  /** Ticker -> sector map (psx_fundamentals). */
  sectorMap: Map<string, string>;
}

/** Institutional participant set (matches queries.ts convention). */
const SMART_MONEY_TYPES = new Set([
  "MUTUAL FUNDS",
  "FIPI",
  "FOREIGN CORPORATES",
  "BANKS",
  "BANKS/DFIS",
  "DFI",
]);

export function computeSectorSmartMoney(
  inputs: SmartMoneyInputs
): SectorSmartMoneyRow[] {
  const { flows, eod, sectorMap } = inputs;
  const dates = Array.from(new Set(flows.map((r) => r.tradeDate))).sort().reverse();
  if (dates.length === 0) return [];
  const latestDate = dates[0];
  const w5 = new Set(dates.slice(0, 5));
  const w15 = new Set(dates.slice(0, 15));
  const w30 = new Set(dates.slice(0, 30));

  // Per-sector institutional nets across windows.
  const agg = new Map<string, { latest: number; s5: number; s15: number; s30: number }>();
  for (const r of flows) {
    if (!SMART_MONEY_TYPES.has(r.participantType)) continue;
    const sector = r.sectorName.toUpperCase().trim();
    if (sector === "ALL" || sector === "") continue; // aggregates cancel
    const net = r.netPkr ?? 0;
    const b = agg.get(sector) ?? { latest: 0, s5: 0, s15: 0, s30: 0 };
    if (r.tradeDate === latestDate) b.latest += net;
    if (w5.has(r.tradeDate)) b.s5 += net;
    if (w15.has(r.tradeDate)) b.s15 += net;
    if (w30.has(r.tradeDate)) b.s30 += net;
    agg.set(sector, b);
  }

  // Equal-weight sector price return over the 5 newest EOD sessions.
  const eodDates = Array.from(new Set(eod.map((r) => r.tradeDate)))
    .sort()
    .reverse()
    .slice(0, 5);
  const price5 = new Map<string, number>();
  if (eodDates.length >= 2) {
    const first = eodDates[eodDates.length - 1];
    const last = eodDates[0];
    const firstClose = new Map<string, number>();
    const lastClose = new Map<string, number>();
    for (const r of eod) {
      if (r.close == null) continue;
      if (r.tradeDate === first) firstClose.set(r.ticker, r.close);
      if (r.tradeDate === last) lastClose.set(r.ticker, r.close);
    }
    const acc = new Map<string, { sum: number; n: number }>();
    for (const [ticker, close] of lastClose) {
      const base = firstClose.get(ticker);
      if (base == null || base <= 0) continue;
      const sector = sectorMap.get(ticker);
      if (!sector) continue;
      const b = acc.get(sector) ?? { sum: 0, n: 0 };
      b.sum += ((close - base) / base) * 100;
      b.n += 1;
      acc.set(sector, b);
    }
    for (const [sector, v] of acc) price5.set(sector, v.sum / v.n);
  }

  return Array.from(agg.entries())
    .map(([sector, b]) => {
      const score =
        b.s30 !== 0
          ? b.s5 / b.s30 + b.s15 / b.s30
          : b.s5 + b.s15 > 0
            ? 2
            : b.s5 + b.s15 < 0
              ? -2
              : 0;
      const price5dPct = price5.get(sector) ?? null;
      const absorption =
        b.s5 > 0 && price5dPct != null && price5dPct < -1;
      return {
        sector,
        latestPkr: b.latest,
        net5dPkr: b.s5,
        net15dPkr: b.s15,
        net30dPkr: b.s30,
        score,
        price5dPct,
        absorption,
      };
    })
    .sort((a, b) => b.net5dPkr - a.net5dPkr);
}

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
