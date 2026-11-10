import fs from "node:fs";
import path from "node:path";

import {
  flowBreakdown,
  getSectorWarning,
  buildLedgerRows,
  computeForwardTestSummary,
  fmtPkr,
  fmtInt,
} from "@/lib/riskEngine";
import type { BuySetup, AvoidSetup, State } from "@/lib/riskEngine";
import { BuyCard, AvoidCard } from "@/components/action-desk-cards";
import {
  buildTriangulation,
  catalystMetadata,
  type TriangulationResult,
} from "@/lib/catalystEngine";
import { resolveLivePrices, computeAvoidBand } from "@/lib/psxLiveFeed";

/** PSX Institutional Terminal — Action Desk (Home Page). */

export const dynamic = "force-dynamic";

const BUY_TICKERS = ["MLCF", "SYS", "MEBL", "UBL", "PPL"];
const AVOID_TICKERS = ["PSO", "HUBC", "HASCOL", "KEL", "TELE"];

async function loadTriangulations(buys: BuySetup[], avoids: AvoidSetup[]) {
  const tickerSetups = [...buys.map((b) => ({ ticker: b.ticker, setup: b, isBuy: true })), ...avoids.map((a) => ({ ticker: a.ticker, setup: a, isBuy: false }))];
  const lookup = new Map(tickerSetups.map((t) => [t.ticker.toUpperCase(), t]));
  const results = new Map<string, TriangulationResult>();
  for (const [ticker] of lookup) {
    const t = lookup.get(ticker)!;
    const flow = flowBreakdown(t.ticker, t.setup);
    results.set(t.ticker, await buildTriangulation(t.ticker, t.setup, t.isBuy, flow));
  }
  return results;
}

export default async function ActionDeskPage() {
  const { buys: liveBuys, avoids: liveAvoids } = await resolveLivePrices(BUY_TICKERS, AVOID_TICKERS);

  const statePath = path.join(process.cwd(), "frontend", "public", "data", "state.json");
  let jsonState: Record<string, unknown> = {};
  try {
    const raw = fs.readFileSync(statePath, "utf-8");
    jsonState = JSON.parse(raw) as Record<string, unknown>;
  } catch (err) {
    console.error("[Home] state.json read failed;", err);
  }

  const rawBuys = (jsonState.top_buy_setups as Array<Record<string, unknown>>) ?? [];
  const rawAvoids = (jsonState.top_avoid_setups as Array<Record<string, unknown>>) ?? [];

  const catalystPhaseMap: Record<string, "ACCUMULATION_RUNUP" | "EXHAUSTION_DUMP_WINDOW" | "NEUTRAL"> = {
    MLCF: "ACCUMULATION_RUNUP",
    SYS: "ACCUMULATION_RUNUP",
    MEBL: "EXHAUSTION_DUMP_WINDOW",
    UBL: "ACCUMULATION_RUNUP",
    PPL: "ACCUMULATION_RUNUP",
    PSO: "EXHAUSTION_DUMP_WINDOW",
    HUBC: "EXHAUSTION_DUMP_WINDOW",
    HASCOL: "EXHAUSTION_DUMP_WINDOW",
    KEL: "EXHAUSTION_DUMP_WINDOW",
    TELE: "NEUTRAL",
  };

  const buys: BuySetup[] = rawBuys.map((s, idx) => ({
    ticker: String((s.ticker ?? BUY_TICKERS[idx] ?? "UNKNOWN").toString().toUpperCase()),
    sector: String(s.sector ?? "Unknown"),
    entry_price: Number(s.entry_price ?? 0),
    stop_price: Number(s.stop_price ?? 0),
    target_price: Number(s.target_price ?? 0),
    rr_ratio: Number(s.rr_ratio ?? 1.0),
    tape_tag: String(s.tape_tag ?? "BUY"),
    rationale: String(s.rationale ?? ""),
    dividend_yield: Number(s.dividend_yield ?? 0),
    board_meeting_date: String(s.board_meeting_date ?? ""),
    days_to_meeting: Number(s.days_to_meeting ?? 0),
    avg_pre_meeting_runup_pct: Number(s.avg_pre_meeting_runup_pct ?? 0),
    post_result_dump_prob: Number(s.post_result_dump_prob ?? 0),
    catalyst_phase: catalystPhaseMap[String((s.ticker ?? BUY_TICKERS[idx] ?? "UNKNOWN").toString().toUpperCase())] ?? "NEUTRAL",
  }));

  const avoids: AvoidSetup[] = rawAvoids.map((s, idx) => ({
    ticker: String((s.ticker ?? AVOID_TICKERS[idx] ?? "UNKNOWN").toString().toUpperCase()),
    sector: String(s.sector ?? "Unknown"),
    current_price: Number(s.current_price ?? 0),
    stop_price: Number(s.stop_price ?? 0),
    risk_tag: String(s.risk_tag ?? ""),
    reason: String(s.reason ?? ""),
    dividend_yield: Number(s.dividend_yield ?? 0),
    board_meeting_date: String(s.board_meeting_date ?? ""),
    days_to_meeting: Number(s.days_to_meeting ?? 0),
    avg_pre_meeting_runup_pct: Number(s.avg_pre_meeting_runup_pct ?? 0),
    post_result_dump_prob: Number(s.post_result_dump_prob ?? 0),
    catalyst_phase: catalystPhaseMap[String((s.ticker ?? AVOID_TICKERS[idx] ?? "UNKNOWN").toString().toUpperCase())] ?? "NEUTRAL",
  }));

  liveBuys.forEach((lp, idx) => {
    if (idx < buys.length) {
      buys[idx].entry_price = lp.price;
    }
  });
  liveAvoids.forEach((lp, idx) => {
    if (idx < avoids.length) {
      avoids[idx].current_price = lp.price;
    }
  });

  avoids.forEach((a) => {
    const band = computeAvoidBand(a.ticker, a.current_price);
    a.stop_price = band.downsideTarget;
  });

  const state: State = {
    generated_at: "2026-11-10",
    version: "1.0.0",
    fund_equity_pkr: 100_000_000,
    fund_notional_pkr: 100_000_000,
    top_buy_setups: buys,
    top_avoid_setups: avoids,
    macro_cash: {
      cash_reserve_pct: 60,
      cash_reserve_pkr: 60_000_000,
      ticker: "PKR_TBILL_YIELD",
      sector: "Cash & Equivalents",
      par_navigation: 1,
      pkrv_t_bill_yield: 0.14,
      yield_basis: "annualized PKRV/T-Bill",
      base_weight: 0.15,
      caution_weight: 0.3,
      bearish_weight: 0.6,
      invested_budget: 0.9,
      regime: "BEARISH",
      regime_rationale: "KSE-100 below 200SMA",
      capital: 60_000_000,
    },
  };

  const triangulations = await loadTriangulations(buys, avoids);
  const ledgerRows = buildLedgerRows(state);
  const ledgerSummary = computeForwardTestSummary(ledgerRows);

  return (
    <div className="space-y-6">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-slate-900">
            PSX Institutional Terminal — Action Desk
          </h1>
          <p className="text-xs text-slate-500">
            30-Day Lookback | High-Conviction Buys &amp; High-Risk Avoids
          </p>
        </div>
        <span className="rounded-full bg-slate-100 px-3 py-1 text-[11px] font-semibold text-slate-600 border border-slate-200">
          Live Feed
        </span>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="rounded-xl border border-blue-200 bg-blue-50/30 p-5 shadow-sm space-y-3">
          <div className="flex items-center justify-between pb-2 border-b border-blue-100">
            <div>
              <span className="text-xs font-semibold tracking-wider text-blue-700 uppercase">
                Mid-Term (2-8 Weeks)
              </span>
              <h2 className="text-base font-bold text-blue-900">
                Top 5 High-Conviction Buys
              </h2>
            </div>
            <span className="rounded bg-blue-50 px-2 py-0.5 text-xs font-bold text-blue-700 border border-blue-200">
              BUY TAPE
            </span>
          </div>
          <div className="space-y-3">
            {buys.slice(0, 5).map((item, idx) => (
              <BuyCard
                key={item.ticker}
                setup={item}
                index={idx}
                triangulation={triangulations.get(item.ticker.toUpperCase())}
              />
            ))}
          </div>
        </div>

        <div className="rounded-xl border border-rose-200 bg-rose-50/30 p-5 shadow-sm space-y-3">
          <div className="flex items-center justify-between pb-2 border-b border-rose-100">
            <div>
              <span className="text-xs font-semibold tracking-wider text-rose-700 uppercase">
                Long-Term (Avoid / Risk)
              </span>
              <h2 className="text-base font-bold text-rose-900">
                Top 5 High-Risk / Avoid List
              </h2>
            </div>
            <span className="rounded bg-rose-50 px-2 py-0.5 text-xs font-bold text-rose-700 border border-rose-200">
              AVOID TAPE
            </span>
          </div>
          <div className="space-y-3">
            {avoids.slice(0, 5).map((item, idx) => (
              <AvoidCard
                key={item.ticker}
                setup={item}
                index={idx}
                triangulation={triangulations.get(item.ticker.toUpperCase())}
              />
            ))}
          </div>
        </div>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 px-4 py-3">
          <div>
            <h3 className="text-sm font-bold text-slate-700">
              Auditor / Forward-Test Ledger
            </h3>
            <p className="text-[11px] text-slate-400">
              Built from public/data/state.json (30-day forward test)
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
            <span className="font-mono text-blue-700">
              Win: {ledgerSummary.winRate.toFixed(1)}%
            </span>
            <span className="font-mono text-emerald-700">
              Alpha: +{ledgerSummary.totalRealizedAlpha.toFixed(2)}R
            </span>
          </div>
        </div>
        <div className="border-t border-slate-200/60 px-4 py-3 text-xs text-slate-500">
          Institutional ledger is available in the /history view.
        </div>
      </div>
    </div>
  );
}
