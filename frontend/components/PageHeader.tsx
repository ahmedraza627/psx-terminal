import type { ReactNode } from "react";

/**
 * Shared light page header for the sub-route desks: title, one-line
 * subtitle, and an optional right slot (session pill, search, actions).
 * Pure server component.
 */
export default function PageHeader({
  title,
  subtitle,
  right,
}: {
  title: string;
  subtitle?: string;
  right?: ReactNode;
}) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-3 border-b border-slate-200 pb-4">
      <div className="min-w-0">
        <h1 className="text-[22px] font-bold tracking-tight text-slate-800">
          {title}
        </h1>
        {subtitle && (
          <p className="pt-0.5 text-[13px] font-normal text-slate-700">{subtitle}</p>
        )}
      </div>
      {right && (
        <div className="flex flex-wrap items-center gap-2">{right}</div>
      )}
    </header>
  );
}
