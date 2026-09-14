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
  if (value == null) return "text-ghost";
  if (value > 0.0005) return "text-bull";
  if (value < -0.0005) return "text-bear";
  return "text-muted";
}
