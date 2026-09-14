/**
 * Shared institutional UI primitives — the only badge / pill / cell chrome
 * in the terminal. Machined geometry: rounded-[2px], hairline rings,
 * 10-11px uppercase tracking labels, tabular-nums data.
 */
import type { ReactNode } from "react";

export type Tone = "bull" | "bear" | "warn" | "info" | "neutral" | "ghost";

const TONE_TEXT: Record<Tone, string> = {
  bull: "text-bull",
  bear: "text-bear",
  warn: "text-warn",
  info: "text-info",
  neutral: "text-muted",
  ghost: "text-ghost",
};

const TONE_RING: Record<Tone, string> = {
  bull: "ring-bull/30",
  bear: "ring-bear/30",
  warn: "ring-warn/30",
  info: "ring-info/30",
  neutral: "ring-hairline",
  ghost: "ring-hairline",
};

const TONE_FILL: Record<Tone, string> = {
  bull: "bg-bull/10",
  bear: "bg-bear/10",
  warn: "bg-warn/10",
  info: "bg-info/10",
  neutral: "bg-panel",
  ghost: "bg-panel",
};

/** Compact uppercase badge — the single pill style across every desk. */
export function Badge({
  tone = "neutral",
  children,
  solid = false,
  className = "",
}: {
  tone?: Tone;
  children: ReactNode;
  solid?: boolean;
  className?: string;
}) {
  const cls = solid
    ? `${TONE_TEXT[tone]} ${TONE_FILL[tone]} ring-1 ${TONE_RING[tone]}`
    : `text-muted ring-1 ring-hairline bg-panel`;
  return (
    <span
      className={`inline-block rounded-[2px] px-1.5 py-px font-mono text-[10px] font-semibold uppercase tracking-wider ${cls} ${className}`}
    >
      {children}
    </span>
  );
}

/** Right-aligned monospace numeric cell. */
export function Num({
  value,
  digits = 2,
  signed = false,
  suffix = "",
  tone,
  className = "",
}: {
  value: number | null | undefined;
  digits?: number;
  signed?: boolean;
  suffix?: string;
  tone?: string;
  className?: string;
}) {
  const body =
    value == null
      ? "—"
      : `${signed && value > 0 ? "+" : ""}${value.toFixed(digits)}${suffix}`;
  return (
    <span
      className={`font-mono tabular-nums ${tone ?? (value == null ? "text-ghost" : "text-ink")} ${className}`}
    >
      {body}
    </span>
  );
}

/** Signed-percentage cell with the terminal's semantic coloring. */
export function PctCell({
  value,
  digits = 2,
  className = "",
}: {
  value: number | null | undefined;
  digits?: number;
  className?: string;
}) {
  const tone =
    value == null
      ? "text-ghost"
      : value > 0.0005
        ? "text-bull"
        : value < -0.0005
          ? "text-bear"
          : "text-muted";
  return <Num value={value} digits={digits} signed suffix="%" tone={tone} className={className} />;
}

/** Desk frame: hairline-bounded machined panel with a header strip. */
export function DeskFrame({
  title,
  right,
  children,
  footer,
}: {
  title: string;
  right?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <section className="border-b border-hairline">
      <div className="flex items-center justify-between gap-2 border-b border-hairline bg-panel px-2.5 py-1.5">
        <h2 className="font-mono text-[10px] font-medium uppercase tracking-widest text-muted">
          {title}
        </h2>
        {right}
      </div>
      {children}
      {footer && (
        <div className="border-t border-hairline px-2.5 py-1.5">{footer}</div>
      )}
    </section>
  );
}

/** Dense data table shell — hairline rows, compact cells, machined headers. */
export function DataTable({
  columns,
  minWidth = 640,
  children,
}: {
  columns: { label: string; align?: "left" | "right"; width?: string }[];
  minWidth?: number;
  children: ReactNode;
}) {
  return (
    <div className="scroll-thin overflow-x-auto">
      <table
        className="w-full border-collapse text-xs"
        style={{ minWidth: `${minWidth}px` }}
      >
        <thead>
          <tr className="border-b border-hairline bg-obsidian text-[10px] uppercase tracking-widest text-ghost">
            {columns.map((c, i) => (
              <th
                key={c.label}
                className={`px-2 py-1.5 font-medium first:pl-2.5 last:pr-2.5 ${c.align === "right" ? "text-right" : "text-left"}`}
                style={c.width ? { width: c.width } : undefined}
              >
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

/** Data row: hover lift to hoverline, hairline separator. */
export function Row({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <tr className={`border-b border-hairline hover:bg-hoverline ${className}`}>
      {children}
    </tr>
  );
}

/** Institutional idle / pending / unreachable states. */
export function IdleState({
  headline,
  detail,
  tone = "info",
}: {
  headline: string;
  detail?: string;
  tone?: Tone;
}) {
  return (
    <div className="px-2.5 py-5 text-center">
      <p className={`font-mono text-xs uppercase tracking-widest ${TONE_TEXT[tone]}`}>
        {headline}
      </p>
      {detail && <p className="mt-1 text-[11px] text-ghost">{detail}</p>}
    </div>
  );
}

/** Horizontal micro bar for delta / exposure visualization. */
export function MicroBar({
  pct,
  tone = "info",
}: {
  pct: number;
  tone?: Tone;
}) {
  const width = Math.min(Math.abs(pct), 100);
  const color =
    tone === "bull"
      ? "bg-bull"
      : tone === "bear"
        ? "bg-bear"
        : tone === "warn"
          ? "bg-warn"
          : "bg-info";
  return (
    <div className="h-1 w-full bg-hairline">
      <div className={`h-1 ${color}`} style={{ width: `${width}%` }} />
    </div>
  );
}

/** Diverging bar centered at zero — for net flows / over-under weights. */
export function DivergeBar({
  value,
  maxAbs,
}: {
  value: number;
  maxAbs: number;
}) {
  const frac = maxAbs > 0 ? Math.max(-1, Math.min(1, value / maxAbs)) : 0;
  const width = Math.abs(frac) * 50;
  return (
    <div className="relative h-1 w-full bg-hairline">
      <div className="absolute inset-y-0 left-1/2 w-px bg-ghost" />
      <div
        className={`absolute inset-y-0 ${frac >= 0 ? "bg-bull" : "bg-bear"}`}
        style={
          frac >= 0
            ? { left: "50%", width: `${width}%` }
            : { right: "50%", width: `${width}%` }
        }
      />
    </div>
  );
}
