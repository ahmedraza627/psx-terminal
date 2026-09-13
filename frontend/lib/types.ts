export type Timeframe =
  | "SHORT_TERM"
  | "MEDIUM_TERM"
  | "LONG_TERM"
  | "WHALE_RADAR"
  | "ARBITRAGE"
  | "MOMENTUM"
  | "INSIDER_RADAR"
  | "MTS_SQUEEZE"
  | "ROLLOVER_DESK";

export type SignalType =
  | "ACCUMULATION"
  | "DISTRIBUTION_TRAP"
  | "VALUE_YIELD"
  | "HIGH_YIELD"
  | "STEALTH_ACCUMULATION"
  | "CASH_CARRY"
  | "INSTITUTIONAL_TARGET"
  | "MOMENTUM_BREAKOUT"
  | "INSIDER_BUYING"
  | "MARGIN_CASCADE_RISK"
  | "LEVERAGE_FLUSH_BOTTOM"
  | "BASIS_INVERSION_SHORT"
  | "ROLLOVER_SQUEEZE";

export interface SignalMetadata {
  vol_multiple?: number | null;
  drift_pct?: number | null;
  range_pct?: number | null;
  range_position?: number | null;
  conviction?:
    | "HIGH"
    | "ELEVATED"
    | "MODERATE"
    | "NOTABLE_VOLUME_SPIKE"
    | null;
  fallback?: boolean | null;
  sector?: string | null;
  ndm_confirmed?: boolean | null;
  breakout_multiple?: number | null;
  day_change_pct?: number | null;
  sector_smart_net_pkr?: number | null;
  ready_close?: number | null;
  futures_close?: number | null;
  futures_symbol?: string | null;
  spread_pct?: number | null;
  annualized_simple_pct?: number | null;
  annualized_compound_pct?: number | null;
  leg_date?: string | null;
  order?: string | null;
  ema50?: number | null;
  yield_pct?: number | null;
  pe?: number | null;
  net_notional_pkr?: number | null;
  disclosure_count?: number | null;
  senior_disclosures?: number | null;
  mts_utilization_pct?: number | null;
  mts_value_pkr?: number | null;
  mts_value_drop_pct?: number | null;
  price_drop_pct?: number | null;
  stance?: string | null;
  spot_close?: number | null;
  basis_pct?: number | null;
  basis_prev_pct?: number | null;
}

export interface SignalRow {
  trade_date: string;
  ticker: string;
  timeframe: Timeframe;
  signal_type: SignalType;
  entry_reference: number | null;
  stop_loss: number | null;
  rationale: string;
  metadata: SignalMetadata | null;
}

export interface FlowRow {
  trade_date: string;
  participant_type: string;
  sector_name: string;
  net_pkr: number | null;
}

export interface OffmarketRow {
  trade_date: string;
  ticker: string;
  quantity: number | null;
  rate: number | null;
  value: number | null;
}

export interface EodRow {
  trade_date: string;
  ticker: string;
  close_price: number | null;
  volume: number | null;
}
