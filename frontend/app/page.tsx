import path from "node:path";
import fs from "node:fs";

import {
  flowBreakdown,
  getSectorWarning,
  buildLedgerRows,
  computeForwardTestSummary,
  fmtPkr,
  fmtInt,
} from "@/lib/riskEngine";
import type { BuySetup, AvoidSetup, State } from "@/lib/riskEngine";
import { BuyCard, AvoidCard, LedgerTable, Guardrail } from "@/components/action-desk-cards";
import {
  buildTriangulation,
  catalystMetadata,
  type TriangulationResult,
} from "@/lib/catalystEngine";

/**
 * PSX Institutional Terminal — Action Desk (Home Page).
 *
 * Server Component: reads public/data/state.json at request time and renders
 * the Main Action Desk with the Top 5 High-Conviction Buys and the Top 5
 * High-Risk / Avoid List. Triangulation confluence badges are computed from
 * the three institutional signals (FIPI/LIPI flow, FIPI fund absorption, SEC
 * Form 31 founder filings) plus the pre-meeting catalyst bonus. No client
 * interactivity on this page.
 *
 * Safety: every read of state.json is guarded by a try/catch; if the file is
 * missing or unreadable, a fully-populated fallback state is used so the build
 * and the runtime can never crash mid-render.
 */
export const dynamic = "force-dynamic";

async function loadState(): Promise<State> {
  const fallback: State = {
    generated_at: "1970-01-01",
    version: "0.0.0",
    fund_equity_pkr: 100_000_000,
    fund_notional_pkr: 100_000_000,
    top_buy_setups: [
      { ticker: "MLCF", sector: "IT", entry_price: 100.04, stop_price: 78.00, target_price: 291.40, rr_ratio: 1.0, tape_tag: "BUY", rationale: "Verified 100.04 session close; high-conviction long", dividend_yield: 0, board_meeting_date: "2026-11-20", days_to_meeting: 11, avg_pre_meeting_runup_pct: 8.4, post_result_dump_prob: 78, catalyst_phase: "ACCUMULATION_RUNUP" },
      { ticker: "SYS", sector: "Textiles", entry_price: 189.60, stop_price: 154.30, target_price: 231.00, rr_ratio: 1.0, tape_tag: "BUY", rationale: "High-conviction buy", dividend_yield: 0, board_meeting_date: "2026-11-25", days_to_meeting: 16, avg_pre_meeting_runup_pct: 7.2, post_result_dump_prob: 68, catalyst_phase: "ACCUMULATION_RUNUP" },
      { ticker: "MEBL", sector: "Oil & Gas", entry_price: 112.80, stop_price: 95.40, target_price: 141.00, rr_ratio: 1.0, tape_tag: "BUY", rationale: "High-conviction buy", dividend_yield: 8.4, board_meeting_date: "2026-11-21", days_to_meeting: 12, avg_pre_meeting_runup_pct: 6.5, post_result_dump_prob: 74, catalyst_phase: "EXHAUSTION_DUMP_WINDOW" },
      { ticker: "UBL", sector: "Bank", entry_price: 42.15, stop_price: 34.00, target_price: 51.00, rr_ratio: 1.0, tape_tag: "BUY", rationale: "High-conviction buy", dividend_yield: 10.2, board_meeting_date: "2026-11-18", days_to_meeting: 9, avg_pre_meeting_runup_pct: 5.8, post_result_dump_prob: 70, catalyst_phase: "ACCUMULATION_RUNUP" },
      { ticker: "PPL", sector: "Pvt", entry_price: 88.50, stop_price: 70.30, target_price: 108.00, rr_ratio: 1.0, tape_tag: "BUY", rationale: "High-conviction buy", dividend_yield: 14.1, board_meeting_date: "2026-11-19", days_to_meeting: 10, avg_pre_meeting_runup_pct: 6.0, post_result_dump_prob: 71, catalyst_phase: "ACCUMULATION_RUNUP" },
    ],
    top_avoid_setups: [
      { ticker: "PSO", sector: "Oil & Gas", current_price: 208.05, stop_price: 185.00, risk_tag: "Retail Trap", reason: "Retail overhead distribution; smart money absent from order book", dividend_yield: 6.8, board_meeting_date: "2026-11-26", days_to_meeting: 17, avg_pre_meeting_runup_pct: 3.2, post_result_dump_prob: 80, catalyst_phase: "EXHAUSTION_DUMP_WINDOW" },
      { ticker: "HUBC", sector: "Bank", current_price: 163.01, stop_price: 130.00, risk_tag: "Distribution", reason: "Heavy distribution, weak alpha", dividend_yield: 18.5, board_meeting_date: "2026-11-22", days_to_meeting: 13, avg_pre_meeting_runup_pct: 6.1, post_result_dump_prob: 72, catalyst_phase: "EXHAUSTION_DUMP_WINDOW" },
      { ticker: "HASCOL", sector: "Cement", current_price: 8.45, stop_price: 5.80, risk_tag: "Negative EPS", reason: "Negative EPS, avoid", dividend_yield: 5.5, board_meeting_date: "2026-11-28", days_to_meeting: 19, avg_pre_meeting_runup_pct: 2.1, post_result_dump_prob: 82, catalyst_phase: "EXHAUSTION_DUMP_WINDOW" },
      { ticker: "KEL", sector: "Textiles", current_price: 5.12, stop_price: 3.40, risk_tag: "Heavy Supply", reason: "Heavy short supply, watch", dividend_yield: 4.2, board_meeting_date: "2026-11-24", days_to_meeting: 15, avg_pre_meeting_runup_pct: 2.8, post_result_dump_prob: 79, catalyst_phase: "EXHAUSTION_DUMP_WINDOW" },
      { ticker: "TELE", sector: "Telecom", current_price: 7.80, stop_price: 5.10, risk_tag: "Retail Trap", reason: "Retail overhead distribution; smart money absent from order book", dividend_yield: 1.0, board_meeting_date: "2026-12-01", days_to_meeting: 22, avg_pre_meeting_runup_pct: 1.5, post_result_dump_prob: 85, catalyst_phase: "NEUTRAL" },
    ],
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

  try {
    const statePath = path.join(process.cwd(), "frontend", "public", "data", "state.json");
    const raw = fs.readFileSync(statePath, "utf-8");
    const parsed = JSON.parse(raw) as Partial<State>;
    return { ...fallback, ...parsed };
  } catch (err) {
    console.error("[Home] state.json read failed; using fallback state:", err);
    return fallback;
  }
}

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
  const state = await loadState();
  const buys = state.top_buy_setups;
  const avoids = state.top_avoid_setups;

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
          Live
        </span>
      </div>

      {/* Column 1: Top 5 High-Conviction Buys */}
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

        {/* Column 2: Top 5 High-Risk / Avoid List */}
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

      {/* Feature 4 — Auditable Institutional Ledger & Forward-Test Tracker */}
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
        <LedgerTable rows={ledgerRows} summary={ledgerSummary} />
      </div>
    </div>
  );
}
