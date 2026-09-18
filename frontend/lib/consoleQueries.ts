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

import { createClient } from "./supabase/server";

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
// BUY disclosures (trailing 5 certified sessions) and NDM blocks  //
// on T. Certified facts only; the strip renders what qualifies.   //
// --------------------------------------------------------------- //

export interface DislocatedTicker {
  ticker: string;
  /** T session volume (shares). */
  volume: number | null;
  /** Close-over-close vs T-1 (%), null when no prior verdict exists. */
  changePct: number | null;
  /** Insider BUY disclosure within the trailing 5 certified sessions. */
  insiderBuy: boolean;
  /** NDM block on T: spread >= 0% vs the T close, or >= 100k shares. */
  ndmAccumulation: boolean;
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

    // T closes (change% + NDM spread math) and T-1 closes (reference).
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

    // Step C2 - NDM blocks on T for the dislocated names. A block
    // qualifies as accumulation evidence ONLY when its spread vs the T
    // close is verified >= 0% - unverifiable blocks (no stored close)
    // stay untagged. The >= 100k-share floor is enforced by the query.
    const ndmSet = new Set<string>();
    if (dislocated.length > 0) {
      const { data, error } = await supabase
        .from("psx_offmarket_deals")
        .select("ticker,quantity,rate")
        .eq("trade_date", sessionDate)
        .gte("quantity", 100_000)
        .in("ticker", dislocated);
      if (!error && data != null) {
        for (const b of data as {
          ticker: string;
          quantity: number | null;
          rate: number | null;
        }[]) {
          const t = b.ticker.toUpperCase();
          const close = closes.get(t) ?? null;
          const spreadPct =
            b.rate != null && close != null && close > 0
              ? ((b.rate - close) / close) * 100
              : null;
          if (spreadPct != null && spreadPct >= 0) ndmSet.add(t);
        }
      }
    }

    // Footprints first (insider outranks NDM), then by volume.
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
          ndmAccumulation: ndmSet.has(t),
        };
      })
      .sort((a, b) => {
        const wa = (a.insiderBuy ? 2 : 0) + (a.ndmAccumulation ? 1 : 0);
        const wb = (b.insiderBuy ? 2 : 0) + (b.ndmAccumulation ? 1 : 0);
        if (wa !== wb) return wb - wa;
        return (b.volume ?? 0) - (a.volume ?? 0);
      });

    return { sessionDate, priorDate, names };
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
    const supabase = createClient();
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

// --------------------------------------------------------------- //
// Smart-money outperformer strip (top-of-page).                   //
//                                                                 //
// Pure factual intersection across the SAME certified session the  //
// three panels already render - no new queries, no scoring, no     //
// signal language. A ticker qualifies only when it satisfies AT    //
// LEAST TWO of these three facts:                                  //
//   1. NDM: on the latest tape, spread flat-or-positive with a     //
//      known market close (>= 100k blocks arrive pre-filtered).    //
//   2. BREADTH: a Top-10 Gainer for the certified session.         //
//   3. VOLUME DIVERGENCE: positive change on >= 2x session-average //
//      volume while breadth is negative/mixed (A/D ratio <= 1).    //
// --------------------------------------------------------------- //

export interface DivergenceName {
  ticker: string;
  changePct: number | null;
  /** Which of the three certified facts matched (2 or 3 of them). */
  facts: string[];
}

export function findIsolatedAccumulation(
  breadth: BreadthData | null,
  ndm: NdmBlock[] | null,
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

  // Fact 1 - NDM flat-or-positive blocks (certified market close present).
  for (const b of ndm ?? []) {
    if (b.spreadPct != null && b.spreadPct >= 0) {
      touch(b.ticker).facts.push("NDM");
    }
  }

  // Fact 2 - top-10 gainers, straight from the certified move set.
  for (const g of breadth.gainers) touch(g.ticker).facts.push("TOP10");

  // Fact 3 - positive move on >= 2x avg volume while breadth <= 1.
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
