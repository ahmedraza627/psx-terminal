/**
 * Staged desk state payload for the PSX Quant Fund institutional dashboard.
 *
 * Written by {@link pipeline.cli.export_state} into `frontend/public/data/state.json`
 * and read server-side at request time (no Next.js `public/` asset fetch needed,
 * since this page is generated as a Server Component via `fs.readFileSync`).
 *
 * The shape below is the *minimal* surface consumed by the new analytics
 * features; everything is optional so the CLI may omit FIPI/LIPI blocks for a
 * lighter payload without breaking the desk.
 */

export interface BuySetup {
  ticker: string;
  sector: string;
  entry_price: number;
  stop_price: number;
  target_price: number;
  rr_ratio: number;
  tape_tag: string;
  rationale: string;
  // Catalyst metadata (see catalystEngine.ts).
  dividend_yield?: number;
  board_meeting_date?: string;
  days_to_meeting?: number;
  avg_pre_meeting_runup_pct?: number;
  post_result_dump_prob?: number;
  catalyst_phase?: "ACCUMULATION_RUNUP" | "EXHAUSTION_DUMP_WINDOW" | "NEUTRAL";
}

export interface AvoidSetup {
  ticker: string;
  sector: string;
  current_price: number;
  stop_price?: number;
  risk_tag: string;
  reason: string;
  // Catalyst metadata (see catalystEngine.ts).
  dividend_yield?: number;
  board_meeting_date?: string;
  days_to_meeting?: number;
  avg_pre_meeting_runup_pct?: number;
  post_result_dump_prob?: number;
  catalyst_phase?: "ACCUMULATION_RUNUP" | "EXHAUSTION_DUMP_WINDOW" | "NEUTRAL";
}

export interface FipiTickerFlow {
  fipi_flow: number;
}

export interface LipiTickerFlow {
  lipi_flow: number;
}

export interface MacroCash {
  cash_reserve_pct: number;
  cash_reserve_pkr: number;
  ticker: string;
  sector: string;
  par_navigation: number;
  pkrv_t_bill_yield: number;
  yield_basis: string;
  base_weight: number;
  caution_weight: number;
  bearish_weight: number;
  invested_budget: number;
  regime: "BULLISH" | "CAUTION" | "BEARISH";
  regime_rationale: string;
  capital: number;
}

export interface State {
  generated_at: string;
  version: string;
  fund_equity_pkr: number;
  fund_notional_pkr: number;
  top_buy_setups: BuySetup[];
  top_avoid_setups: AvoidSetup[];
  macro_cash: MacroCash;
}

export interface FlowPayload {
  fipi_flow?: number;
  lipi_flow?: number;
}
