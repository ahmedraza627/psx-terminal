/** Institutional formatters — single source for every desk. */

export function fmtPkrM(value: number | null | undefined, digits = 0): string {
  if (value == null) return "—";
  const m = value / 1e6;
  const sign = m > 0 ? "+" : "";
  return `${sign}${m.toFixed(digits)}M`;
}

export function fmtPkrB(value: number | null | undefined, digits = 1): string {
  if (value == null) return "—";
  const b = value / 1e9;
  const sign = b > 0 ? "+" : "";
  return `${sign}${b.toFixed(digits)}B`;
}

/** Shares in millions, e.g. "42.5M" (null-safe, unsigned). */
export function fmtSharesM(
  value: number | null | undefined,
  digits = 1
): string {
  if (value == null) return "—";
  return `${(value / 1e6).toFixed(digits)}M`;
}

/** PKR compact: B at ≥ 1e9, M at ≥ 1e6, plain below (null-safe, unsigned). */
export function fmtPkrCompact(value: number | null | undefined): string {
  if (value == null) return "—";
  if (Math.abs(value) >= 1e9) return `PKR ${(value / 1e9).toFixed(2)}B`;
  if (Math.abs(value) >= 1e6) return `PKR ${(value / 1e6).toFixed(1)}M`;
  return `PKR ${value.toFixed(0)}`;
}

export function fmtPrice(value: number | null | undefined, digits = 2): string {
  return value == null ? "—" : value.toFixed(digits);
}

export function fmtPct(
  value: number | null | undefined,
  digits = 2,
  signed = true
): string {
  if (value == null) return "—";
  const sign = signed && value > 0 ? "+" : "";
  return `${sign}${value.toFixed(digits)}%`;
}

export function fmtX(value: number | null | undefined, digits = 1): string {
  return value == null ? "—" : `${value.toFixed(digits)}x`;
}

export function fmtInt(value: number | null | undefined): string {
  return value == null ? "—" : Math.round(value).toLocaleString("en-US");
}

export function fmtR(value: number | null | undefined): string {
  if (value == null) return "—";
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}R`;
}

export function fmtPf(value: number | null | undefined): string {
  if (value == null) return "—";
  if (!Number.isFinite(value)) return "∞";
  return value.toFixed(2);
}

export function tonePct(value: number | null | undefined): string {
  if (value == null) return "text-slate-700";
  if (value > 0.0005) return "text-emerald-700 font-semibold";
  if (value < -0.0005) return "text-rose-700 font-semibold";
  return "text-slate-700 font-semibold";
}
