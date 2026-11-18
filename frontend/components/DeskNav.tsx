"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "Daily Recommendations", hint: "What to trade today" },
  { href: "/history", label: "Historical Performance", hint: "Audited signal ledger" },
  { href: "/backtest", label: "1Y Backtest Lab", hint: "Simulated equity curve" },
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
                ? "border-slate-200 bg-slate-50 text-slate-900"
                : "border-transparent text-slate-600 hover:bg-slate-50 hover:text-slate-900"
            }`}
          >
            <span className="block text-sm font-semibold">{link.label}</span>
            <span className="block text-[11px] text-slate-400">{link.hint}</span>
          </Link>
        );
      })}
    </nav>
  );
}
