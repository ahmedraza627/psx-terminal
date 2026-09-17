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

import { getSupabase } from "./supabase";

// --------------------------------------------------------------- //
// Session anchor: the latest populated EOD session.               //
// --------------------------------------------------------------- //

export async function fetchLatestEodSession(): Promise<string | null> {
  try {
    const supabase = getSupabase();
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
  gainers: EodMove[];
  losers: EodMove[];
}

export async function fetchUniverseBreadth(): Promise<BreadthData | null> {
  try {
    const supabase = getSupabase();
    // ---------------------------------------------------------------
    // CERTIFIED-SESSION RESOLUTION.
    // psx_daily_eod rows are one per (trade_date, ticker): a small
    // `limit` returns ONLY the newest date's rows - which is exactly
    // the bug that pinned priorDate to null and verdicts to 0. Dedupe
    // a bounded pull into candidate DATES, then walk newest-first:
    //   T     = first date carrying >= MIN_CERTIFIED_CLOSES tickers
    //           with a live close AND volume > 0 (a restamped/partial
    //           date can never masquerade as breadth again)
    //   T-1   = the next candidate below T with any certified rows
    // Verdicts count only traded names; coverage is surfaced verbatim.
    // ---------------------------------------------------------------
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

    type SessionRows = {
      ticker: string;
      close_price: number | null;
      volume: number | null;
    }[];
    const fetchSession = async (d: string): Promise<SessionRows> => {
      const { data, error } = await supabase
        .from("psx_daily_eod")
        .select("ticker,close_price,volume")
        .eq("trade_date", d);
      if (error) throw error;
      return (data ?? []) as SessionRows;
    };

    let sessionDate: string | null = null;
    let todayRows: SessionRows = [];
    let priorDate: string | null = null;
    let priorCloses = new Map<string, number>();
    for (let i = 0; i < candidates.length; i++) {
      const rows = await fetchSession(candidates[i]);
      const certified = rows.filter(
        (r) =>
          r.close_price != null && r.close_price > 0 && (r.volume ?? 0) > 0,
      );
      if (sessionDate == null) {
        if (certified.length < MIN_CERTIFIED_CLOSES) continue; // dead/restamped
        sessionDate = candidates[i];
        todayRows = rows;
        continue;
      }
      // First certified candidate below T becomes the prior session.
      if (certified.length > 0) {
        priorDate = candidates[i];
        priorCloses = new Map(
          certified.map((r) => [
            r.ticker.toUpperCase(),
            r.close_price as number,
          ]),
        );
        break;
      }
    }
    if (sessionDate == null) return null;

    const moves: EodMove[] = [];
    let advancers = 0;
    let decliners = 0;
    let unchanged = 0;
    let verdicts = 0;

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
      gainers,
      losers,
    };
  } catch {
    return null;
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
    const supabase = getSupabase();
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

// --------------------------------------------------------------- //
// Panel B - NDM Block Tape (off-market liquidity, >= 100k).       //
// --------------------------------------------------------------- //

export interface NdmBlock {
  ticker: string;
  tradeDate: string;
  quantity: number | null;
  rate: number | null;
  value: number | null;
  /** Market close for the block's session (null = not stored). */
  marketPrice: number | null;
  /** (rate - market) / market x 100; negative = block below market. */
  spreadPct: number | null;
  /** >= 1M shares crossed below market - distribution evidence. */
  distribution: boolean;
  /** >= 1M shares crossed above market - accumulation evidence. */
  accumulation: boolean;
}

export async function fetchNdmBlocks(
  minShares = 100_000
): Promise<NdmBlock[] | null> {
  try {
    const supabase = getSupabase();
    const { data, error } = await supabase
      .from("psx_offmarket_deals")
      .select("trade_date,ticker,quantity,rate,value")
      .gte("quantity", minShares)
      .order("trade_date", { ascending: false })
      .order("value", { ascending: false })
      .limit(400);
    if (error) throw error;
    const rows = (data ?? []) as {
      trade_date: string;
      ticker: string;
      quantity: number | null;
      rate: number | null;
      value: number | null;
    }[];
    if (rows.length === 0) return null;

    // Bind to the latest NDM session present (the tape may lead or lag EOD).
    const asOf = rows[0].trade_date;
    const latest = rows.filter((r) => r.trade_date === asOf);

    // Market closes for the crossed names, from stored EOD (no estimation).
    const tickers = Array.from(new Set(latest.map((r) => r.ticker.toUpperCase())));
    let closes = new Map<string, number>();
    if (tickers.length > 0) {
      const { data: eod, error: eodErr } = await supabase
        .from("psx_daily_eod")
        .select("ticker,close_price")
        .eq("trade_date", asOf)
        .in("ticker", tickers);
      if (!eodErr && eod != null) {
        closes = new Map(
          (eod as { ticker: string; close_price: number | null }[])
            .filter((r) => r.close_price != null && r.close_price > 0)
            .map((r) => [r.ticker.toUpperCase(), r.close_price as number]),
        );
      }
    }

    return latest.map((r) => {
      const ticker = r.ticker.toUpperCase();
      const marketPrice = closes.get(ticker) ?? null;
      const spreadPct =
        r.rate != null && marketPrice != null && marketPrice > 0
          ? ((r.rate - marketPrice) / marketPrice) * 100
          : null;
      return {
        ticker,
        tradeDate: r.trade_date,
        quantity: r.quantity,
        rate: r.rate,
        value: r.value,
        marketPrice,
        spreadPct,
        distribution:
          (r.quantity ?? 0) >= 1_000_000 && spreadPct != null && spreadPct < 0,
        accumulation:
          (r.quantity ?? 0) >= 1_000_000 && spreadPct != null && spreadPct > 0,
      };
    });
  } catch {
    return null;
  }
}
