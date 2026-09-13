// PSX Institutional Valuation Multi-Factor Model (PSX_MF_V1) — client mirror
// of pipeline/analytics/fundamental_engine.py. The pipeline persists the
// computed intrinsic value; this module documents the formula the desk
// displays and lets the UI recompute leg values for explanation panels.
// Keep in sync with the pipeline env defaults (.env.example ALPHA_* block).

export const SECTOR_TARGET_PES = {
  EP: 6.0, // E&P / Oil & Gas Exploration
  FERTILIZER: 7.5,
  CEMENT: 7.0,
  TECH: 12.0,
  BANKS: 5.0, // Commercial Banks
} as const;

export const DEFAULT_TARGET_PE = 6.5;

// Dividend floor hurdle: K_e = PIB yield − dividend growth = 9.5%
export const PIB_YIELD_PCT = 13.5;
export const DIV_GROWTH_PCT = 4.0;
export const KE_REQUIRED = (PIB_YIELD_PCT - DIV_GROWTH_PCT) / 100; // 0.095

// Composite blend for regular dividend payers
export const W_PE_VALUE = 0.6;
export const W_DIV_FLOOR = 0.4;

export type SectorKey = keyof typeof SECTOR_TARGET_PES | "DEFAULT";

export function sectorKey(sectorName?: string | null): SectorKey {
  const s = (sectorName ?? "").toUpperCase();
  if (s.includes("EXPLORATION") || s.includes("E&P") || s.includes("OIL & GAS"))
    return "EP";
  if (s.includes("FERTILIZER")) return "FERTILIZER";
  if (s.includes("CEMENT")) return "CEMENT";
  if (s.includes("TECHNOLOGY") || s.includes("SOFTWARE")) return "TECH";
  if (s.includes("BANK")) return "BANKS";
  return "DEFAULT";
}

export function sectorTargetPe(sectorName?: string | null): number {
  const key = sectorKey(sectorName);
  return key === "DEFAULT" ? DEFAULT_TARGET_PE : SECTOR_TARGET_PES[key];
}

export interface IntrinsicBreakdown {
  peLeg: number; // TTM EPS × sector normal P/E
  divFloor: number | null; // TTM DPS / K_e (null for non-payers)
  composite: number; // blended intrinsic value
}

export function compositeIntrinsic(
  ttmEps: number,
  targetPe: number,
  ttmDps: number | null
): IntrinsicBreakdown {
  const peLeg = ttmEps * targetPe;
  const divFloor =
    ttmDps != null && ttmDps > 0 ? ttmDps / KE_REQUIRED : null;
  const composite =
    divFloor != null
      ? W_PE_VALUE * peLeg + W_DIV_FLOOR * divFloor
      : peLeg;
  return { peLeg, divFloor, composite };
}
