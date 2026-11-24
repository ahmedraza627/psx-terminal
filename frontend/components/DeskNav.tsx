"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "Daily Recommendations", hint: "What to trade today" },
  { href: "/seasonality", label: "Seasonal Playbook", hint: "Cyclical windows & timing" },
  { href: "/history", label: "Historical Performance", hint: "Audited signal ledger" },
] as const;

export default function DeskNav({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();

  return (
    <nav className="flex-1 space-y-1 px-3 py-4">
      {LINKS.map((link) => {
        const active = link.href === "/" ? pathname === "/" : pathname.startsWith(link.href);
        return (
          <Link
            key={link.href}
            href={link.href}
            onClick={onNavigate}
            aria-current={active ? "page" : undefined}
            className={`block rounded-lg border px-3 py-2 transition-colors ${
              active
                ? "border-emerald-500/30 bg-emerald-500/10"
                : "border-transparent hover:bg-slate-900/80"
            }`}
          >
            <span
              className={`block text-[13px] font-semibold tracking-tight ${
                active ? "text-emerald-300" : "text-slate-300"
              }`}
            >
              {link.label}
            </span>
            <span className={`block text-[10px] ${active ? "text-emerald-500/80" : "text-slate-500"}`}>
              {link.hint}
            </span>
          </Link>
        );
      })}
    </nav>
  );
}
