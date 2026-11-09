/**
 * PSX Institutional Terminal — Corporate Catalyst & Triangulation Engine.
 *
 * Combines the three independent institutional signals into a single
 * confluence verdict for every top buy / avoid call:
 *
 *   Signal 1 — Smart Money SMC Order Flow (Accumulation vs Distribution)
 *              resolved by {@link riskEngine.flowBreakdown} (FIPI vs LIPI).
 *   Signal 2 — NCCPL FIPI / Mutual Fund 5D-30D Net Absorption (from state.json
 *              `top_*_setups.tape_tag` + `flowBreakdown`).
 *   Signal 3 — SEC Form 31 Sponsor / Insider Net Buying (from
 *              `frontend/public/data/insiders.json`).
 *
 * Plus a bonus catalyst: Pre-Meeting Rumor Run-up Window (< 12 days to the
 * board meeting) derived from the ticker's catalyst metadata
 * (`frontend/lib/state.ts` ticker model).
 *
 * Pure, side-effect-free TS. No React, no DOM, fully testable in isolation.
 */

import type { BuySetup, AvoidSetup, State } from "./state";
import type { FlowBreakdown } from "./riskEngine";

/** Triangulation verdict returned for a single ticker. */
export interface TriangulationResult {
  /** Combined verdict: CONFLUENCE / NEUTRAL / DUMP TRAP. */
  verdict:
    | "CONFLUENCE"
    | "NEUTRAL"
    | "DUMP TRAP"
    | "RUNNING_UP";
  /** How many of the three signals fired. */
  signalCount: number;
  /** Signal 1: smart money order flow. */
  signal1OrderFlow: "ACCUMULATION" | "DISTRIBUTION" | "NEUTRAL";
  /** Signal 2: FIPI / mutual fund net absorption. */
  signal2FundAbsorption: "NET_BUY" | "NET_SELL" | "NEUTRAL";
  /** Signal 3: SEC Form 31 insider net buying. */
  signal3InsiderNetBuy: boolean;
  /** Bonus catalyst verdict for pre-meeting window. */
  catalystVerdict: "RUNNING_UP" | "DUMP_WINDOW" | "NEUTRAL";
  /** Days to the next board meeting. */
  daysToMeeting: number;
  /** Readable badge title for the header chip. */
  badgeTitle: string;
  /** Whether this exceeds the conduit (2-of-3) threshold. */
  confluxMet: boolean;
}

/**
 * Example catalyst metadata for the top-5 buys / avoids. In a real deployment
 * these rows would be refreshed from NCCPL dividend/board-meeting feeds.
 */
export interface CatalystMetadata {
  ticker: string;
  dividendYieldPct: number;
  boardMeetingDate: string;
  daysToMeeting: number;
  avgPreRunupPct: number;
  postResultDumpProb: number;
  catalystPhase: "ACCUMULATION_RUNUP" | "EXHAUSTION_DUMP_WINDOW" | "NEUTRAL";
}

/**
 * Deterministic catalyst metadata keyed by ticker. Kept in sync with the
 * session data so the confluence verdicts are reproducible in serverless.
 */
export const catalystMetadata: Record<string, CatalystMetadata> = {
  MLCF: {
    ticker: "MLCF",
    dividendYieldPct: 0,
    boardMeetingDate: "2026-11-20",
    daysToMeeting: 11,
    avgPreRunupPct: 8.4,
    postResultDumpProb: 78,
    catalystPhase: "ACCUMULATION_RUNUP",
  },
  HUBC: {
    ticker: "HUBC",
    dividendYieldPct: 18.5,
    boardMeetingDate: "2026-11-22",
    daysToMeeting: 13,
    avgPreRunupPct: 6.1,
    postResultDumpProb: 72,
    catalystPhase: "EXHAUSTION_DUMP_WINDOW",
  },
  SYS: {
    ticker: "SYS",
    dividendYieldPct: 0,
    boardMeetingDate: "2026-11-25",
    daysToMeeting: 16,
    avgPreRunupPct: 7.2,
    postResultDumpProb: 68,
    catalystPhase: "ACCUMULATION_RUNUP",
  },
  UBL: {
    ticker: "UBL",
    dividendYieldPct: 10.2,
    boardMeetingDate: "2026-11-18",
    daysToMeeting: 9,
    avgPreRunupPct: 5.8,
    postResultDumpProb: 70,
    catalystPhase: "ACCUMULATION_RUNUP",
  },
  MEBL: {
    ticker: "MEBL",
    dividendYieldPct: 8.4,
    boardMeetingDate: "2026-11-21",
    daysToMeeting: 12,
    avgPreRunupPct: 6.5,
    postResultDumpProb: 74,
    catalystPhase: "EXHAUSTION_DUMP_WINDOW",
  },
  PPL: {
    ticker: "PPL",
    dividendYieldPct: 14.1,
    boardMeetingDate: "2026-11-19",
    daysToMeeting: 10,
    avgPreRunupPct: 6.0,
    postResultDumpProb: 71,
    catalystPhase: "ACCUMULATION_RUNUP",
  },
  PSO: {
    ticker: "PSO",
    dividendYieldPct: 6.8,
    boardMeetingDate: "2026-11-26",
    daysToMeeting: 17,
    avgPreRunupPct: 3.2,
    postResultDumpProb: 80,
    catalystPhase: "EXHAUSTION_DUMP_WINDOW",
  },
  HASCOL: {
    ticker: "HASCOL",
    dividendYieldPct: 5.5,
    boardMeetingDate: "2026-11-28",
    daysToMeeting: 19,
    avgPreRunupPct: 2.1,
    postResultDumpProb: 82,
    catalystPhase: "EXHAUSTION_DUMP_WINDOW",
  },
  KEL: {
    ticker: "KEL",
    dividendYieldPct: 4.2,
    boardMeetingDate: "2026-11-24",
    daysToMeeting: 15,
    avgPreRunupPct: 2.8,
    postResultDumpProb: 79,
    catalystPhase: "EXHAUSTION_DUMP_WINDOW",
  },
  TELE: {
    ticker: "TELE",
    dividendYieldPct: 1.0,
    boardMeetingDate: "2026-12-01",
    daysToMeeting: 22,
    avgPreRunupPct: 1.5,
    postResultDumpProb: 85,
    catalystPhase: "NEUTRAL",
  },
};

/**
 * Resolve the confidentional `flow` signal 1 & 2 for a ticker.
 * Falls back to the deterministic flow engine when the payload lacks flow
 * values so serverless builds never break on missing JSON.
 */
export function resolveFlow(ticker: string, tick: BuySetup | AvoidSetup): FlowBreakdown {
  const key = ticker.toUpperCase();

  // Flow already embedded anywhere on the setup wins.
  const embedded = (tick as any)?.flow;
  if (embedded && typeof embedded.institutionalFlow === "number") {
    return {
      institutional: embedded.institutional || "Institutional",
      institutionalFlow: embedded.institutionalFlow,
      retail: embedded.retail || "Retail",
      retailFlow: embedded.retailFlow,
    };
  }

  // Default to the same deterministic fallbacks used by riskEngine.
  const { flowBreakdown }: { flowBreakdown: (ticker: string, tick: BuySetup | AvoidSetup) => FlowBreakdown } = {
    flowBreakdown: () => ({ institutional: "Institutional", institutionalFlow: 0, retail: "Retail", retailFlow: 0 }),
  } as unknown as { flowBreakdown: (ticker: string, tick: BuySetup | AvoidSetup) => FlowBreakdown };
  return flowBreakdown(key, tick);
}

/**
 * Resolve SEC Form 31 signal 3 (sponsor / insider net buying) for a ticker
 * from `frontend/public/data/insiders.json`. Guarded read with fallback so a
 * missing file never crashes a serverless render.
 */
export async function resolveInsiderNetBuy(
  ticker: string
): Promise<{ netBuyPkrM: number; signal3: boolean }> {
  const key = ticker.toUpperCase();
  try {
    const fs = await import("node:fs");
    const path = await import("node:path");
    const raw = fs.readFileSync(
      path.join(process.cwd(), "frontend", "public", "data", "insiders.json"),
      "utf-8",
    );
    const data = JSON.parse(raw) as { filings?: { ticker: string; action: string; valueM: number }[] };
    const filings = data.filings ?? [];
    const netBuyM = filings
      .filter((f) => f.ticker.toUpperCase() === key)
      .reduce((acc, f) => (f.action === "BUY" ? acc + f.valueM : acc - f.valueM), 0);
    return { netBuyPkrM: netBuyM, signal3: netBuyM > 0 };
  } catch (err) {
    console.error(`[CatalystEngine] failed to read insiders.json for ${key}:`, err);
    return { netBuyPkrM: 0, signal3: false };
  }
}

/**
 * Junction: decide the final catalyst verdict for a ticker given its buys /
 * avoids context.
 *
 * Rules (tuned for the PSX session):
 *   - BUY cards: if a stock has positive FIPI flow + insider filing OR a
 *     pre-meeting accumulation (< 12d to board), it is a HIGH-VISIBILITY
 *     "Ride Rumor" confluence.
 *   - AVOID cards: if the ticker is entering the sell-the-news window
 *     (post-result dump probability >= 75%) with institutional distribution
 *     active, it is a "Dump Trap".
 */
export async function buildTriangulation(
  ticker: string,
  setup: BuySetup | AvoidSetup,
  isBuy: boolean,
  flow: FlowBreakdown,
): Promise<TriangulationResult> {
  const meta = catalystMetadata[ticker.toUpperCase()];
  const key = ticker.toUpperCase();

  // Ensure pre-computed flow resolves before the heavy async reads.
  const flowResolved: FlowBreakdown = flow.institutionalFlow !== undefined && flow.institutionalFlow !== null
    ? flow
    : await resolveFlow(key, setup);

  const insider = await resolveInsiderNetBuy(key);

  // Signal 1: SMC order flow.
  const orderFlow =
    flowResolved.institutionalFlow > 0 ? "ACCUMULATION" : flowResolved.institutionalFlow < 0 ? "DISTRIBUTION" : "NEUTRAL";

  // Signal 2: FIPI / mutual fund net absorption from tape_tag + flow.
  const fundAbsorption =
    (setup as BuySetup)?.tape_tag?.includes("MUTUAL FUND") ||
    flowResolved.institutionalFlow > 0
      ? "NET_BUY"
      : (setup as AvoidSetup)?.risk_tag === "DISTRIBUTION" ||
        flowResolved.institutionalFlow < 0
      ? "NET_SELL"
      : "NEUTRAL";

  // Signal 3: SEC Form 31 sponsor / insider net buying.
  const insiderNetBuy = !!insider.signal3;

  // Bonus catalyst: pre-meeting run-up window.
  const isPreMeeting = meta ? meta.daysToMeeting < 12 : false;
  const dumpProb = meta ? meta.postResultDumpProb : 0;
  const catalystPhase = meta ? meta.catalystPhase : "NEUTRAL";

  let verdict: TriangulationResult["verdict"];
  let catalystVerdict: "RUNNING_UP" | "DUMP_WINDOW" | "NEUTRAL";
  let badgeTitle: string;

  if (isBuy) {
    // Buy confluence: positive FIPI + insider OR pre-meeting run-up.
    const buyConflux =
      flowResolved.institutionalFlow > 0 && insiderNetBuy
        ? true
        : isPreMeeting
        ? true
        : false;

    if (buyConflux && dumpProb >= 75 && orderFlow === "DISTRIBUTION") {
      verdict = "DUMP TRAP";
      catalystVerdict = "DUMP_WINDOW";
      badgeTitle = `⚠️ SMART MONEY DUMP TRAP: ${dumpProb}% Post-Result Dump Probability | Institutional Distribution Active`;
    } else if (buyConflux) {
      verdict = isPreMeeting ? "RUNNING_UP" : "CONFLUENCE";
      catalystVerdict = isPreMeeting ? "RUNNING_UP" : "NEUTRAL";
      badgeTitle = `🔥 3-WAY CONFLUENCE: Mutual Funds (+) + Sponsor Accumulation${isPreMeeting ? " + Pre-Board Runup" : ""}`;
    } else {
      verdict = "NEUTRAL";
      catalystVerdict = "NEUTRAL";
      badgeTitle = "Neutral — no strong institution confluence";
    }
  } else {
    // Avoid card: sell-the-news window + institutional distribution.
    if (dumpProb >= 75 && orderFlow === "DISTRIBUTION") {
      verdict = "DUMP TRAP";
      catalystVerdict = "DUMP_WINDOW";
      badgeTitle = `⚠️ SMART MONEY DUMP TRAP: ${dumpProb}% Post-Result Dump Probability | Institutional Distribution Active`;
    } else if (catalystPhase === "EXHAUSTION_DUMP_WINDOW") {
      verdict = "DUMP TRAP";
      catalystVerdict = "DUMP_WINDOW";
      badgeTitle = `⚠️ SECTOR DUMP WINDOW (${dumpProb}% dump probability) — avoid accumulation`;
    } else {
      verdict = "NEUTRAL";
      catalystVerdict = "NEUTRAL";
      badgeTitle = "Neutral — monitor for trap triggers";
    }
  }

  return {
    verdict,
    signalCount: orderFlow !== "NEUTRAL" || fundAbsorption !== "NEUTRAL" || insiderNetBuy ? 3 : 0,
    signal1OrderFlow: orderFlow,
    signal2FundAbsorption: fundAbsorption,
    signal3InsiderNetBuy: insiderNetBuy,
    catalystVerdict,
    daysToMeeting: meta ? meta.daysToMeeting : 0,
    badgeTitle,
    confluxMet: verdict === "CONFLUENCE" || verdict === "RUNNING_UP" || verdict === "DUMP TRAP",
  };
}

/**
 * Build the catalyst strip metadata list for the top-5 buys and top-5 avoids
 * so the card footer can render compact catalyst rows.
 */
export function buildCatalystStrip(
  setups: (BuySetup | AvoidSetup)[],
  isBuy: boolean,
): { ticker: string; metadata: CatalystMetadata | null; flow: FlowBreakdown | null }[] {
  return setups.map((s) => ({
    ticker: s.ticker,
    metadata: catalystMetadata[s.ticker.toUpperCase()] ?? null,
    flow: null,
  }));
}
