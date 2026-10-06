"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

/**
 * Fixed left sidebar - the Action-First shell's only navigation surface.
 *
 * Menu state is path-derived (no per-item useState): the active entry is
 * whichever route the router is currently on, so browser back/forward and
 * manual URL edits stay in sync for free. All entries are real routes;
 * Market Pulse / Institutional Tracker / Engine Rules render honest
 * "phase 2" stubs until their phases land.
 */

const MENU = [
  { href: "/", label: "Action Desk", glyph: "⚡" },
  { href: "/pulse", label: "Market Pulse", glyph: "📊" },
  { href: "/institutional", label: "Institutional Tracker", glyph: "🏢" },
  { href: "/engine", label: "Engine Rules", glyph: "⚙️" },
] as const;

export default function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="flex h-dvh w-56 shrink-0 flex-col border-r border-hairline bg-panel">
      {/* Brand block */}
      <div className="border-b border-hairline px-4 py-4">
        <p className="font-mono text-[13px] font-bold tracking-[0.18em] text-ink">
          PSX<span className="text-info">·</span>QUANT
        </p>
        <p className="pt-0.5 font-mono text-[9px] uppercase tracking-[0.28em] text-ghost">
          Decision Engine
        </p>
      </div>

      {/* Menu */}
      <nav className="flex-1 space-y-0.5 px-2 py-3">
        {MENU.map((item) => {
          const active =
            item.href === "/"
              ? pathname === "/"
              : pathname.startsWith(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={active ? "page" : undefined}
              className={`flex items-center gap-2.5 rounded-[2px] border-l-2 px-2.5 py-2 font-mono text-[11px] uppercase tracking-wider transition-colors ${
                active
                  ? "border-info bg-info/10 font-bold text-info"
                  : "border-transparent text-muted hover:bg-hoverline hover:text-ink"
              }`}
            >
              <span aria-hidden className="text-[13px] leading-none">
                {item.glyph}
              </span>
              {item.label}
            </Link>
          );
        })}
      </nav>

      {/* Footer stamp */}
      <div className="border-t border-hairline px-4 py-3">
        <p className="font-mono text-[9px] uppercase tracking-[0.2em] text-ghost">
          Certified pipeline data
        </p>
        <p className="font-mono text-[9px] uppercase tracking-[0.2em] text-ghost/70">
          The machine displays · the human decides
        </p>
      </div>
    </aside>
  );
}
