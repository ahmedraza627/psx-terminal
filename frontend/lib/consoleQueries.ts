// ---------------------------------------------------------------------------
// CONSOLE DATA LAYER - certified facts only.
//
// Every function returns exactly what the pipeline stored: no derived
// signals, no targets, no conviction tags. Failures degrade to null/[]
// (settle-safe) so the console renders honest empty states instead of
// crashing.
//
// BREADTH FIX: the session date is pulled from psx_daily_eod itself
// (MAX(trade_date)), and the full EOD session is fetched in ONE query -
// one trading day is only ~500-600 rows, so the old 9-ticker slice is
// structurally impossible here.
// ---------------------------------------------------------------------------

import type { SupabaseClient } from "@supabase/supabase-js";
import { createClient } from "./supabase/public";

// --------------------------------------------------------------- //
// Session anchor: the latest populated EOD session.               //
// --------------------------------------------------------------- //

export async function fetchLatestEodSession(): Promise<string | null> {
  try {
    const supabase = createClient();
    const { data, error } = await supabase
      .from("psx_daily_eod")
      .select("trade_date")
      .order("trade_date", { ascending: false })
      .limit(1);
    if (error) throw error;
    const rows = data as { trade_date: string }[] | null;
    return rows && rows.length > 0 ? rows[0].trade_date : null;
  } catch {
    return null;
  }
}

// --------------------------------------------------------------- //
// Panel C - Verified Universe Breadth (full stored universe).     //
// --------------------------------------------------------------- //

export interface EodMove {
  ticker: string;
  close: number | null;
  /** Close-over-close vs the prior stored session (%). Null = no prior. */
  changePct: number | null;
  volume: number | null;
  /** close x volume (PKR) - the certified product of stored fields. */
  turnoverPkr: number | null;
}

export interface BreadthData {
  sessionDate: string;
  priorDate: string | null;
  advancers: number;
  decliners: number;
  unchanged: number;
  /** adv / dec; null when decliners == 0. */
  ratio: number | null;
  /** Tickers with a computable close-over-close verdict. */
  verdicts: number;
  /** Session mean of live volumes - the divergence strip's volume baseline. */
  avgVolume: number;
  /** The full verified move set (gainers/losers are slices of this). */
  moves: EodMove[];
  gainers: EodMove[];
  losers: EodMove[];
}

// --------------------------------------------------------------- //
// Certified EOD session-pair resolver (T and T-1), shared by the  //
// breadth panel and the volume-dislocation scanner so a single    //
// render resolves the sessions exactly once.                      //
// --------------------------------------------------------------- //

/** Minimal certified row shape shared by both EOD reads. */
export interface EodSessionRow {
  ticker: string;
  close_price: number | null;
  volume: number | null;
}

export interface CertifiedEodPair {
  /** Latest date carrying >= MIN_CERTIFIED_CLOSES live closes. */
  sessionDate: string;
  /** The next certified session below T (null when none stored). */
  priorDate: string | null;
  /** Certified dates found, newest first (T first, up to 5). */
  recentDates: string[];
  /** T's full stored rows (breadth applies its own verdict gates). */
  todayRows: EodSessionRow[];
  /** T-1's full stored rows. */
  priorRows: EodSessionRow[];
}

export async function resolveCertifiedEodPair(): Promise<CertifiedEodPair | null> {
  try {
    const supabase = createClient();
    const MIN_CERTIFIED_CLOSES = 50;
    const { data: dateRows, error: datesErr } = await supabase
      .from("psx_daily_eod")
      .select("trade_date")
      .order("trade_date", { ascending: false })
      .limit(2000);
    if (datesErr) throw datesErr;
    const candidates: string[] = [];
    for (const r of (dateRows ?? []) as { trade_date: string }[]) {
      if (!candidates.includes(r.trade_date)) candidates.push(r.trade_date);
      if (candidates.length >= 6) break;
    }
    if (candidates.length === 0) return null;

    const fetchSession = async (d: string): Promise<EodSessionRow[]> => {
      const { data, error } = await supabase
        .from("psx_daily_eod")
        .select("ticker,close_price,volume")
        .eq("trade_date", d);
      if (error) throw error;
      return (data ?? []) as EodSessionRow[];
    };

    const certifiedCount = (rows: EodSessionRow[]) =>
      rows.filter(
        (r) =>
          r.close_price != null && r.close_price > 0 && (r.volume ?? 0) > 0,
      ).length;

    let sessionDate: string | null = null;
    let priorDate: string | null = null;
    let todayRows: EodSessionRow[] = [];
    let priorRows: EodSessionRow[] = [];
    const certifiedDates: string[] = [];
    for (let i = 0; i < candidates.length; i++) {
      const rows = await fetchSession(candidates[i]);
      if (certifiedCount(rows) < MIN_CERTIFIED_CLOSES) continue; // dead/restamped
      certifiedDates.push(candidates[i]);
      if (sessionDate == null) {
        sessionDate = candidates[i];
        todayRows = rows;
        continue;
      }
      // First certified candidate below T becomes the prior session.
      if (priorDate == null) {
        priorDate = candidates[i];
        priorRows = rows;
      }
      if (certifiedDates.length >= 5) break; // insider-trading window depth
    }
    if (sessionDate == null) return null;
    return {
      sessionDate,
      priorDate,
      recentDates: certifiedDates,
      todayRows,
      priorRows,
    };
  } catch {
    return null;
  }
}

export async function fetchUniverseBreadth(
  resolved?: CertifiedEodPair | null,
): Promise<BreadthData | null> {
  try {
    const pair =
      resolved !== undefined ? resolved : await resolveCertifiedEodPair();
    if (pair == null) return null;
    const sessionDate = pair.sessionDate;
    const priorDate = pair.priorDate;
    const todayRows: EodSessionRow[] = pair.todayRows;
    const priorCloses = new Map<string, number>(
      pair.priorRows
        .filter(
          (r) =>
            r.close_price != null && r.close_price > 0 && (r.volume ?? 0) > 0,
        )
        .map((r) => [r.ticker.toUpperCase(), r.close_price as number]),
    );

    const moves: EodMove[] = [];
    let advancers = 0;
    let decliners = 0;
    let unchanged = 0;
    let verdicts = 0;
    let volumeSum = 0;

    for (const raw of todayRows) {
      const r = raw as {
        ticker: string;
        close_price: number | null;
        volume: number | null;
      };
      const close = r.close_price != null && r.close_price > 0 ? r.close_price : null;
      const prev = priorCloses.get(r.ticker.toUpperCase()) ?? null;
      const changePct =
        close != null && prev != null && prev > 0
          ? ((close - prev) / prev) * 100
          : null;
      if (changePct != null) {
        verdicts += 1;
        if (changePct > 0) advancers += 1;
        else if (changePct < 0) decliners += 1;
        else unchanged += 1;
      }
      moves.push({
        ticker: r.ticker.toUpperCase(),
        close,
        changePct,
        volume: r.volume ?? null,
        turnoverPkr:
          close != null && r.volume != null ? close * r.volume : null,
      });
      if (r.volume != null && r.volume > 0) volumeSum += r.volume;
    }

    const byMove = (a: EodMove, b: EodMove) =>
      (b.changePct ?? -Infinity) - (a.changePct ?? -Infinity);
    const gainers = moves
      .filter((m) => (m.changePct ?? 0) > 0)
      .sort(byMove)
      .slice(0, 10);
    const losers = moves
      .filter((m) => (m.changePct ?? 0) < 0)
      .sort((a, b) => (a.changePct ?? Infinity) - (b.changePct ?? Infinity))
      .slice(0, 10);

    return {
      sessionDate,
      priorDate,
      advancers,
      decliners,
      unchanged,
      ratio: decliners > 0 ? advancers / decliners : null,
      verdicts,
      avgVolume: verdicts > 0 ? volumeSum / verdicts : 0,
      moves,
      gainers,
      losers,
    };
  } catch {
    return null;
  }
}

// --------------------------------------------------------------- //
// Volume dislocation scanner - today's top-25 volume names that   //
// were NOT in yesterday's top-25, cross-referenced with insider   //
// BUY disclosures (trailing 5 certified sessions). Certified      //
// facts only; the strip renders what qualifies.                   //
// --------------------------------------------------------------- //

export interface DislocatedTicker {
  ticker: string;
  /** T session volume (shares). */
  volume: number | null;
  /** Close-over-close vs T-1 (%), null when no prior verdict exists. */
  changePct: number | null;
  /** Insider BUY disclosure within the trailing 5 certified sessions. */
  insiderBuy: boolean;
}

export interface VolumeDislocationData {
  sessionDate: string;
  priorDate: string | null;
  names: DislocatedTicker[];
}

const DISLOCATION_DEPTH = 25;

export async function fetchVolumeDislocation(
  resolved?: CertifiedEodPair | null,
): Promise<VolumeDislocationData | null> {
  try {
    const pair =
      resolved !== undefined ? resolved : await resolveCertifiedEodPair();
    if (pair == null) return null;
    const supabase = createClient();
    const { sessionDate, priorDate, recentDates, todayRows, priorRows } = pair;

    // Steps A/B - top-25 volume sets, then the set difference.
    const top25 = (rows: EodSessionRow[]) =>
      rows
        .filter((r) => (r.volume ?? 0) > 0)
        .sort((a, b) => (b.volume ?? 0) - (a.volume ?? 0))
        .slice(0, DISLOCATION_DEPTH)
        .map((r) => r.ticker.toUpperCase());
    const todayTop = new Set(top25(todayRows));
    if (todayTop.size === 0) return null;
    const priorTop = new Set(top25(priorRows));
    const dislocated = Array.from(todayTop).filter((t) => !priorTop.has(t));

    // T closes (change%) and T-1 closes (reference).
    const closes = new Map<string, number>();
    const volumes = new Map<string, number | null>();
    for (const r of todayRows) {
      const t = r.ticker.toUpperCase();
      if (!closes.has(t) && r.close_price != null && r.close_price > 0)
        closes.set(t, r.close_price);
      if (!volumes.has(t)) volumes.set(t, r.volume ?? null);
    }
    const priorCloses = new Map<string, number>();
    for (const r of priorRows) {
      const t = r.ticker.toUpperCase();
      if (!priorCloses.has(t) && r.close_price != null && r.close_price > 0)
        priorCloses.set(t, r.close_price);
    }

    // Step C1 - insider BUY footprint in the trailing 5 certified sessions.
    const insiderSet = new Set<string>();
    if (dislocated.length > 0 && recentDates.length > 0) {
      const windowStart = recentDates[Math.min(4, recentDates.length - 1)];
      const { data, error } = await supabase
        .from("psx_insider_trades")
        .select("ticker,trade_date,trade_type")
        .in("ticker", dislocated)
        .eq("trade_type", "BUY")
        .gte("trade_date", windowStart);
      if (!error && data != null) {
        for (const row of data as { ticker: string }[])
          insiderSet.add(row.ticker.toUpperCase());
      }
    }

    // Footprints first (insider outranks the rest), then by volume.
    const names: DislocatedTicker[] = dislocated
      .map((t) => {
        const close = closes.get(t) ?? null;
        const prev = priorCloses.get(t) ?? null;
        const changePct =
          close != null && prev != null && prev > 0
            ? ((close - prev) / prev) * 100
            : null;
        return {
          ticker: t,
          volume: volumes.get(t) ?? null,
          changePct,
          insiderBuy: insiderSet.has(t),
        };
      })
      .sort((a, b) => {
        const wa = a.insiderBuy ? 1 : 0;
        const wb = b.insiderBuy ? 1 : 0;
        if (wa !== wb) return wb - wa;
        return (b.volume ?? 0) - (a.volume ?? 0);
      });

    return { sessionDate, priorDate, names };
  } catch {
    return null;
  }
}

// --------------------------------------------------------------- //
// Quant Action Radar — daily certified-signal snapshot.            //
//                                                                  //
// One row per (session, ticker, signal_type) from the pipeline's   //
// daily screener (pipeline/analytics/quant_signals.py).           //
// --------------------------------------------------------------- //

export interface QuantSignal {
  tradeDate: string;
  ticker: string;
  signalType: string;
  confidenceScore: number | null;
  catalystReason: string | null;
  sector: string | null;
  /** Market close for the signal's session (null when not stored). */
  marketClose: number | null;
  /** Session volume (shares) for the signal's ticker (null when absent). */
  volume: number | null;
}

export interface QuantRadarData {
  sessionDate: string | null;
  signals: QuantSignal[];
}

export async function fetchQuantRadar(
  sessionDate: string | null,
  nthHighest = 3,
): Promise<QuantRadarData> {
  try {
    const supabase = createClient();
    if (sessionDate == null) return { sessionDate: null, signals: [] };

    const { data, error } = await supabase
      .from("psx_daily_quant_signals")
      .select(
        "trade_date,ticker,signal_type,confidence_score,catalyst_reason,sector"
      )
      .eq("trade_date", sessionDate)
      .order("confidence_score", { ascending: false })
      .limit(nthHighest);
    if (error) throw error;

    const rows = (data ?? []) as {
      trade_date: string;
      ticker: string;
      signal_type: string;
      confidence_score: number | null;
      catalyst_reason: string | null;
      sector: string | null;
    }[];

    if (rows.length === 0) return { sessionDate, signals: [] };

    const tickers = Array.from(new Set(rows.map((r) => r.ticker.toUpperCase())));
    const closeMap = new Map<string, number | null>();
    const volMap = new Map<string, number | null>();
    if (tickers.length > 0) {
      const { data: eod, error: eodErr } = await supabase
        .from("psx_daily_eod")
        .select("ticker,close_price,volume")
        .eq("trade_date", sessionDate)
        .in("ticker", tickers);
      if (!eodErr && eod != null) {
        for (const r of eod as {
          ticker: string;
          close_price: number | null;
          volume: number | null;
        }[]) {
          const t = r.ticker.toUpperCase();
          if (!closeMap.has(t)) closeMap.set(t, r.close_price);
          if (!volMap.has(t)) volMap.set(t, r.volume);
        }
      }
    }

    return {
      sessionDate,
      signals: rows.map((r) => ({
        tradeDate: r.trade_date,
        ticker: r.ticker.toUpperCase(),
        signalType: r.signal_type,
        confidenceScore: r.confidence_score,
        catalystReason: r.catalyst_reason,
        sector: r.sector,
        marketClose: closeMap.get(r.ticker.toUpperCase()) ?? null,
        volume: volMap.get(r.ticker.toUpperCase()) ?? null,
      })),
    };
  } catch {
    return { sessionDate, signals: [] };
  }
}

// --------------------------------------------------------------- //
// Panel A - Institutional Flow Matrix (NCCPL reality).            //
// --------------------------------------------------------------- //

export interface ParticipantFlow {
  participantType: string;
  /** 1-day net (PKR), latest stored flow session. */
  net1dPkr: number | null;
  /** 5-session rolling net (PKR). */
  net5dPkr: number | null;
  /** 30-session rolling net (PKR). */
  net30dPkr: number | null;
}

export interface FlowMatrixData {
  /** Latest stored flow session. */
  asOfDate: string;
  /** Distinct flow sessions covered by the 30-day window. */
  sessions: number;
  participants: ParticipantFlow[];
  /** FIPI + MUTUAL FUNDS, latest session (the panel's KPI). */
  institutions1dPkr: number | null;
  /** INDIVIDUALS, latest session. */
  retail1dPkr: number | null;
  /** Institutions < 0 while retail > 0 - the divergence tag. */
  retailTrapped: boolean;
}

const INSTITUTIONS = new Set(["FIPI", "MUTUAL FUNDS"]);
const RETAIL = "INDIVIDUALS";
/** Display order for the known participant cut. */
const DISPLAY_ORDER = [
  "FIPI",
  "MUTUAL FUNDS",
  "BANKS",
  "INSURANCE",
  "INDIVIDUALS",
  "BROKERS",
  "COMPANIES",
];

export async function fetchFlowMatrix(): Promise<FlowMatrixData | null> {
  try {
    const supabase = createClient();
    // ~12 participants x ~12 sectors x ~40 sessions - one bounded pull.
    const { data, error } = await supabase
      .from("nccpl_fipi_lipi")
      .select("trade_date,participant_type,sector_name,net_pkr")
      .order("trade_date", { ascending: false })
      .limit(6000);
    if (error) throw error;
    const rows = (data ?? []) as {
      trade_date: string;
      participant_type: string | null;
      sector_name: string | null;
      net_pkr: number | null;
    }[];
    if (rows.length === 0) return null;

    // Distinct sessions, newest first. Sector 'ALL' rows are NCCPL grand
    // totals that cancel to ~0 - excluded from every aggregation.
    const dates: string[] = [];
    const seen = new Set<string>();
    for (const r of rows) {
      if ((r.sector_name ?? "ALL").toUpperCase() === "ALL") continue;
      if (!seen.has(r.trade_date)) {
        seen.add(r.trade_date);
        dates.push(r.trade_date);
      }
    }
    if (dates.length === 0) return null;
    const asOf = dates[0];
    const win5 = new Set(dates.slice(0, 5));
    const win30 = new Set(dates.slice(0, 30));

    const nets = new Map<
      string,
      { d1: number; d5: number; d30: number; has: boolean }
    >();
    const touch = (p: string) => {
      let e = nets.get(p);
      if (!e) {
        e = { d1: 0, d5: 0, d30: 0, has: false };
        nets.set(p, e);
      }
      return e;
    };

    for (const r of rows) {
      if ((r.sector_name ?? "ALL").toUpperCase() === "ALL") continue;
      const p = (r.participant_type ?? "").toUpperCase().trim();
      if (p === "") continue;
      const net = r.net_pkr ?? 0;
      const e = touch(p);
      if (r.trade_date === asOf) {
        e.d1 += net;
        e.has = true;
      }
      if (win5.has(r.trade_date)) e.d5 += net;
      if (win30.has(r.trade_date)) e.d30 += net;
    }

    const participants: ParticipantFlow[] = Array.from(nets.entries())
      .map(([participantType, e]) => ({
        participantType,
        net1dPkr: e.has ? e.d1 : null,
        net5dPkr: e.d5,
        net30dPkr: e.d30,
      }))
      .sort((a, b) => {
        const ia = DISPLAY_ORDER.indexOf(a.participantType);
        const ib = DISPLAY_ORDER.indexOf(b.participantType);
        if (ia !== -1 && ib !== -1) return ia - ib;
        if (ia !== -1) return -1;
        if (ib !== -1) return 1;
        return a.participantType.localeCompare(b.participantType);
      });

    const inst1d = participants
      .filter((p) => INSTITUTIONS.has(p.participantType))
      .reduce((a, p) => a + (p.net1dPkr ?? 0), 0);
    const retail1d =
      participants.find((p) => p.participantType === RETAIL)?.net1dPkr ?? null;

    return {
      asOfDate: asOf,
      sessions: Math.min(dates.length, 30),
      participants,
      institutions1dPkr: participants.some((p) => INSTITUTIONS.has(p.participantType))
        ? inst1d
        : null,
      retail1dPkr: retail1d,
      retailTrapped: inst1d < 0 && (retail1d ?? 0) > 0,
    };
  } catch {
    return null;
  }
}
// Smart-money outperformer strip (top-of-page).                   //
//                                                                 //
// Pure factual intersection within the SAME certified session's    //
// breadth data - no new queries, no scoring, no signal language.   //
// A ticker qualifies only when it satisfies AT LEAST TWO of these  //
// two facts:                                                       //
//   1. BREADTH: a Top-10 Gainer for the certified session.         //
//   2. VOLUME DIVERGENCE: positive change on >= 2x session-average //
//      volume while breadth is negative/mixed (A/D ratio <= 1).    //
// --------------------------------------------------------------- //

export interface DivergenceName {
  ticker: string;
  changePct: number | null;
  /** Which certified facts matched (both of them). */
  facts: string[];
}

export function findIsolatedAccumulation(
  breadth: BreadthData | null,
): DivergenceName[] {
  if (breadth == null) return [];

  const m = new Map<string, DivergenceName>();
  const touch = (t: string) => {
    let e = m.get(t);
    if (!e) {
      e = { ticker: t, changePct: null, facts: [] };
      m.set(t, e);
    }
    return e;
  };

  // Fact 1 - top-10 gainers, straight from the certified move set.
  for (const g of breadth.gainers) touch(g.ticker).facts.push("TOP10");

  // Fact 2 - positive move on >= 2x avg volume while breadth <= 1.
  const breadthWeak = breadth.ratio == null || breadth.ratio <= 1;
  if (breadthWeak && breadth.avgVolume > 0) {
    for (const mv of breadth.moves) {
      if (
        (mv.changePct ?? 0) > 0 &&
        mv.volume != null &&
        mv.volume >= 2 * breadth.avgVolume
      ) {
        touch(mv.ticker).facts.push("VOL");
      }
    }
  }

  // Keep names matching >= 2 facts; stamp the move; sort by fact count,
  // then magnitude. changePct comes only from the certified verdict.
  return Array.from(m.values())
    .filter((e) => e.facts.length >= 2)
    .map((e) => ({
      ...e,
      changePct:
        breadth.moves.find((mv) => mv.ticker === e.ticker)?.changePct ?? null,
    }))
    .sort(
      (a, b) =>
        b.facts.length - a.facts.length || (b.changePct ?? 0) - (a.changePct ?? 0),
    );
}

// --------------------------------------------------------------- //
// "My Portfolio" watchlist - per-user saved tickers.              //
// --------------------------------------------------------------- //

export async function fetchUserWatchlist(): Promise<string[]> {
  try {
    const supabase = createClient();
    const { data, error } = await supabase
      .from("user_watchlist")
      .select("ticker")
      .order("created_at", { ascending: false })
      .limit(100);
    if (error) return []; // RLS denies unauthenticated reads -> empty list
    return Array.from(
      new Set(
        ((data ?? []) as { ticker: string }[])
          .map((r) => r.ticker.trim().toUpperCase())
          .filter((t) => t !== ""),
      ),
    ).sort();
  } catch {
    return [];
  }
}

// --------------------------------------------------------------- //
// Ticker deep-dive - the certified 30-session dossier for ONE     //
// ticker. EOD bars and insider disclosures are per-ticker facts.  //
// per-ticker facts. Institutional flow is NOT published per       //
// ticker by NCCPL (participant x sector only): when the ticker's  //
// sector is mapped via psx_fundamentals we show that sector's     //
// FIPI/MF history and label it SECTOR; otherwise the market-wide  //
// participant cut, labeled MARKET-WIDE. Never invented.           //
// --------------------------------------------------------------- //

export interface DeepDiveBar {
  tradeDate: string;
  closePrice: number | null;
  volume: number | null;
}

export interface FlowHistoryPoint {
  tradeDate: string;
  fipiNetPkr: number | null;
  mutualFundsNetPkr: number | null;
}

export interface DeepDiveInsiderRow {
  tradeDate: string;
  insiderName: string;
  designation: string;
  tradeType: string;
  quantity: number | null;
  rate: number | null;
}

export interface TickerDeepDiveData {
  ticker: string;
  /** Certified EOD sessions used for the 30-day windows. */
  sessions: string[];
  /** True when the ticker has stored EOD bars. */
  known: boolean;
  closeIdx: number | null;
  bars: DeepDiveBar[];
  flow: {
    /** SECTOR when mapped via psx_fundamentals, else MARKET-WIDE. */
    kind: "SECTOR" | "MARKET-WIDE";
    sectorName: string | null;
    points: FlowHistoryPoint[];
  };
  insider: DeepDiveInsiderRow[];
}

const FLOW_PARTICIPANTS = ["FIPI", "MUTUAL FUNDS"];

/**
 * FIPI + Mutual Funds net per session for one ticker's mapped sector
 * (psx_fundamentals), or the market-wide cut when unmapped. Exported so
 * other surfaces can reuse the exact same attribution rules.
 */
export async function fetchFlowHistoryForTicker(
  supabase: SupabaseClient,
  ticker: string,
  windowDates: string[],
): Promise<TickerDeepDiveData["flow"]> {
  const pointsFor = async (
    sector: string | null,
  ): Promise<FlowHistoryPoint[]> => {
    try {
      let q = supabase
        .from("nccpl_fipi_lipi")
        .select("trade_date,participant_type,net_pkr")
        .in("participant_type", FLOW_PARTICIPANTS)
        .in("trade_date", windowDates)
        .order("trade_date", { ascending: false })
        .limit(3000);
      if (sector != null) q = q.eq("sector_name", sector);
      const { data, error } = await q;
      if (error) return [];
      const acc = new Map<
        string,
        { f: number | null; m: number | null }
      >();
      for (const r of (data ?? []) as {
        trade_date: string;
        participant_type: string | null;
        net_pkr: number | null;
      }[]) {
        const p = (r.participant_type ?? "").toUpperCase();
        if (p !== "FIPI" && p !== "MUTUAL FUNDS") continue;
        const e = acc.get(r.trade_date) ?? { f: null, m: null };
        if (p === "FIPI") e.f = (e.f ?? 0) + (r.net_pkr ?? 0);
        else e.m = (e.m ?? 0) + (r.net_pkr ?? 0);
        acc.set(r.trade_date, e);
      }
      return windowDates
        .filter((d) => acc.has(d))
        .map((d) => ({
          tradeDate: d,
          fipiNetPkr: acc.get(d)!.f,
          mutualFundsNetPkr: acc.get(d)!.m,
        }));
    } catch {
      return [];
    }
  };

  // Sector attribution: latest stored mapping for this ticker.
  let sector: string | null = null;
  try {
    const { data } = await supabase
      .from("psx_fundamentals")
      .select("sector_name")
      .eq("ticker", ticker)
      .order("trade_date", { ascending: false })
      .limit(1);
    const s = (data as { sector_name: string | null }[] | null)?.[0]
      ?.sector_name;
    // 'ALL' rows are NCCPL grand totals, not a sector attribution.
    if (s != null && s.trim() !== "" && s.toUpperCase() !== "ALL") sector = s;
  } catch {
    sector = null;
  }

  return {
    kind: sector != null ? "SECTOR" : "MARKET-WIDE",
    sectorName: sector,
    points: await pointsFor(sector),
  };
}

export async function fetchTickerDeepDive(
  ticker: string,
  resolved?: CertifiedEodPair | null,
): Promise<TickerDeepDiveData | null> {
  try {
    const symbol = ticker.trim().toUpperCase();
    if (symbol === "") return null;
    const pair =
      resolved !== undefined ? resolved : await resolveCertifiedEodPair();
    if (pair == null) return null;
    const supabase = createClient();

    const closeIdx = pair.todayRows.findIndex(
      (r) => r.ticker.toUpperCase() === symbol,
    );

    // 30 certified sessions window (all recentDates are certified).
    const sessions = pair.recentDates.slice(0, 30);
    if (sessions.length === 0) return null;
    const windowStart = sessions[sessions.length - 1];

    // A) per-ticker EOD bars (certified rows only).
    let bars: DeepDiveBar[] = [];
    try {
      const { data, error } = await supabase
        .from("psx_daily_eod")
        .select("trade_date,close_price,volume")
        .eq("ticker", symbol)
        .gte("trade_date", windowStart)
        .order("trade_date", { ascending: false })
        .limit(120);
      if (!error) {
        bars = ((data ?? []) as {
          trade_date: string;
          close_price: number | null;
          volume: number | null;
        }[])
          .filter(
            (r) =>
              r.close_price != null &&
              r.close_price > 0 &&
              (r.volume ?? 0) > 0,
          )
          .map((r) => ({
            tradeDate: r.trade_date,
            closePrice: r.close_price,
            volume: r.volume,
          }));
      }
    } catch {
      bars = [];
    }

    // B) flow history for the mapped sector (or market-wide cut).
    const flow = await fetchFlowHistoryForTicker(
      supabase,
      symbol,
      sessions,
    );

    // C) Insider disclosures, bounded by the same certified window.
    let insider: DeepDiveInsiderRow[] = [];
    try {
      const { data, error } = await supabase
        .from("psx_insider_trades")
        .select(
          "trade_date,insider_name,designation,trade_type,quantity,rate",
        )
        .eq("ticker", symbol)
        .gte("trade_date", windowStart)
        .order("trade_date", { ascending: false })
        .limit(100);
      if (!error) {
        insider = ((data ?? []) as {
          trade_date: string;
          insider_name: string;
          designation: string;
          trade_type: string;
          quantity: number | null;
          rate: number | null;
        }[]).map((r) => ({
          tradeDate: r.trade_date,
          insiderName: r.insider_name,
          designation: r.designation,
          tradeType: r.trade_type,
          quantity: r.quantity,
          rate: r.rate,
        }));
      }
    } catch {
      insider = [];
    }

    return {
      ticker: symbol,
      sessions,
      known: bars.length > 0,
      closeIdx: closeIdx >= 0 ? closeIdx : null,
      bars,
      flow,
      insider,
    };
  } catch {
    return null;
  }
}

// --------------------------------------------------------------- //
// Action Desk - certified system verdicts (psx_system_verdicts).  //
// --------------------------------------------------------------- //

/** Certified verdict row written by the pipeline's decision engine. */
export interface SystemVerdict {
  tradeDate: string;
  /** SHORT_TERM | MID_TERM | LONG_TERM */
  horizon: string;
  /** BUY | AVOID | ACCUMULATE */
  direction: "BUY" | "AVOID" | "ACCUMULATE";
  ticker: string;
  /** The certified system-logic sentence exactly as stored. */
  logic: string;
  // -----------------------------------------------------------------
  // Institutional risk math (decision engine execution levels).
  // Null while migration 009_decision_risk_levels.sql is pending, or for
  // horizons without a certified entry (LONG_TERM is an AVOID verdict).
  // -----------------------------------------------------------------
  /** Entry reference price (PKR) - latest session close. */
  entryRef: number | null;
  /** Invalidation / stop-loss level (PKR). */
  stopLoss: number | null;
  /** Target zone price (PKR). */
  targetPrice: number | null;
  /** Reward-to-risk ratio, e.g. 2.4 -> displayed as 1:2.4 R:R. */
  riskReward: number | null;
  /** NORMAL | DEFENSIVE_CASH - the macro regime stamp. */
  regimeStatus: string | null;
  // -----------------------------------------------------------------
  // Institutional proof (decision engine backtest + fundamental gate).
  // Null while migration 010_backtest_fundamentals.sql is pending, when
  // history was too thin to simulate, or for AVOID verdicts.
  // -----------------------------------------------------------------
  /** 3-year walk-forward win rate (%) of the same entry/stop/target logic. */
  historicalWinRate: number | null;
  /** "PROFITABLE (PE > 0)" once the strict PE gate passed, else "UNVERIFIED". */
  fundamentalScore: string | null;
  // -----------------------------------------------------------------
  // Institutional alpha (Phase 2): dynamic position sizing from the 1.5%
  // risk budget + the macro tape state. Null while migration
  // 011_institutional_alpha_upgrade.sql is pending, for MID_TERM picks
  // (no fixed-fractional size on a sector-absorption call), and for
  // AVOID verdicts.
  // -----------------------------------------------------------------
  /** Suggested portfolio allocation (%), from the 1.5% risk model, cap 15%. */
  suggestedAllocPct: number | null;
  /** Order size capped at 2% of the 20D average volume (exit liquidity). */
  maxVolumeCapacityShares: number | null;
  /** RISK_ON | NEUTRAL | DEFENSIVE_CASH - the macro tape gate. */
  macroTapeState: string | null;
}

/**
 * The active session's three system verdicts (or fewer - the engine only
 * stores horizons with a certified candidate, never fabricated rows).
 *
 * Graceful fallback: when the engine has not stamped the requested
 * session yet (a new session just opened, or the pipeline has not run),
 * the latest CERTIFIED session is returned instead of an empty list, so
 * the Action Desk never sticks on its awaiting state while real verdicts
 * exist. Every row carries its actual tradeDate - the UI labels the
 * cards with it and flags the one-session lag honestly.
 * Settle-safe by house convention: failures degrade to [].
 */
export async function fetchSystemVerdicts(
  sessionDate: string | null,
): Promise<SystemVerdict[]> {
  // Raw row shape: risk columns are optional because they only exist
  // once migration 009 has been applied to the live table.
  type VerdictRow = {
    trade_date: string;
    horizon: string;
    direction: SystemVerdict["direction"];
    ticker: string;
    logic_text: string;
    entry_ref?: number | null;
    stop_loss?: number | null;
    target_price?: number | null;
    risk_reward_ratio?: number | null;
    regime_status?: string | null;
    historical_win_rate?: number | null;
    fundamental_score?: string | null;
    suggested_alloc_pct?: number | null;
    max_volume_capacity_shares?: number | null;
    macro_tape_state?: string | null;
  };

  const BASE = "trade_date,horizon,direction,ticker,logic_text";
  const RISK =
    BASE +
    ",entry_ref,stop_loss,target_price,risk_reward_ratio,regime_status";
  const ALPHA = RISK + ",historical_win_rate,fundamental_score";
  const FULL =
    ALPHA +
    ",suggested_alloc_pct,max_volume_capacity_shares,macro_tape_state";

  // The engine only writes the three documented enums; the cast keeps the
  // display type honest without mutating stored values.
  const mapRows = (rows: VerdictRow[]): SystemVerdict[] =>
    rows.map((r) => ({
      tradeDate: r.trade_date,
      horizon: r.horizon,
      direction: r.direction,
      ticker: r.ticker,
      logic: r.logic_text,
      entryRef: r.entry_ref ?? null,
      stopLoss: r.stop_loss ?? null,
      targetPrice: r.target_price ?? null,
      riskReward: r.risk_reward_ratio ?? null,
      regimeStatus: r.regime_status ?? null,
      historicalWinRate: r.historical_win_rate ?? null,
      fundamentalScore: r.fundamental_score ?? null,
      suggestedAllocPct: r.suggested_alloc_pct ?? null,
      maxVolumeCapacityShares: r.max_volume_capacity_shares ?? null,
      macroTapeState: r.macro_tape_state ?? null,
    }));

  try {
    const supabase = createClient();

    // Widest projection first; PostgREST rejects unknown columns while a
    // migration is pending (PGRST204 / 42703), so degrade stepwise
    // (011 sizing/tape -> 010 metrics -> 009 risk levels -> base) instead of
    // dropping the desk's whole execution grid whenever the NEWEST
    // migration lags.
    const forSession = async (select: string): Promise<VerdictRow[] | null> => {
      const { data, error } = await supabase
        .from("psx_system_verdicts")
        .select(select)
        .eq("trade_date", sessionDate as string)
        .order("horizon", { ascending: true });
      // cast: dynamic select string defeats supabase-js's column parser
      return error ? null : ((data ?? []) as unknown as VerdictRow[]);
    };
    // Fallback: latest available trade_date, horizon asc, limit 3. Rows are
    // trimmed to the newest trade_date present so cards never mix two
    // sessions when the latest one stored only 1-2 horizons.
    const latestRows = async (select: string): Promise<VerdictRow[] | null> => {
      const { data, error } = await supabase
        .from("psx_system_verdicts")
        .select(select)
        .order("trade_date", { ascending: false })
        .order("horizon", { ascending: true })
        .limit(3);
      // cast: dynamic select string defeats supabase-js's column parser
      return error ? null : ((data ?? []) as unknown as VerdictRow[]);
    };

    if (sessionDate) {
      const rows =
        (await forSession(FULL)) ??
        (await forSession(ALPHA)) ??
        (await forSession(RISK)) ??
        (await forSession(BASE));
      if (rows && rows.length > 0) return mapRows(rows);
    }
    const fallback =
      (await latestRows(FULL)) ??
      (await latestRows(ALPHA)) ??
      (await latestRows(RISK)) ??
      (await latestRows(BASE));
    if (!fallback || fallback.length === 0) return [];
    const latest = fallback[0].trade_date;
    return mapRows(fallback.filter((r) => r.trade_date === latest));
  } catch {
    return [];
  }
}
