"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

/**
 * Collapsible left navigation drawer - light SaaS style.
 *
 * Real Next.js sub-routes: every entry is a <Link> to a dedicated page
 * (/ /pulse /flow /breakouts), so navigation is a true route change, not
 * an anchor jump. Active state is path-derived.
 *
 * Desktop (md+): the drawer sits in the flex flow; the hamburger toggles
 * between the full rail (w-60) and an icon rail (w-[76px]). The choice
 * persists in localStorage.
 * Mobile: the drawer is off-canvas; a floating hamburger opens it over a
 * backdrop. One component owns all of it - no cross-tree state.
 */

const MENU = [
  { href: "/", label: "Action Desk", glyph: "sparkles" },
  { href: "/pulse", label: "Market Pulse", glyph: "chart" },
  { href: "/flow", label: "Institutional Flow", glyph: "building" },
  { href: "/breakouts", label: "Volume Anomalies", glyph: "trending-up" },
] as const;

const COLLAPSE_KEY = "psx-sidebar-collapsed";

export default function Sidebar() {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  // Restore the desktop collapse choice after mount (no SSR mismatch).
  useEffect(() => {
    try {
      setCollapsed(localStorage.getItem(COLLAPSE_KEY) === "1");
    } catch {
      /* private mode - default expanded */
    }
  }, []);

  const toggleCollapsed = () => {
    setCollapsed((c) => {
      try {
        localStorage.setItem(COLLAPSE_KEY, c ? "0" : "1");
      } catch {
        /* ignore */
      }
      return !c;
    });
  };

  const isActive = (href: string) =>
    href === "/" ? pathname === "/" : pathname.startsWith(href);

  return (
    <>
      {/* Mobile hamburger - floating, top-left, hidden on desktop */}
      {!mobileOpen && (
        <button
          type="button"
          onClick={() => setMobileOpen(true)}
          aria-label="Open navigation"
          className="fixed left-3 top-3 z-40 inline-flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-600 shadow-sm transition-colors hover:text-slate-900 md:hidden"
        >
          <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <path d="M4 6h16M4 12h16M4 18h16" />
          </svg>
        </button>
      )}

      {/* Mobile backdrop */}
      {mobileOpen && (
        <button
          type="button"
          aria-label="Close navigation"
          onClick={() => setMobileOpen(false)}
          className="fixed inset-0 z-40 bg-slate-900/40 md:hidden"
        />
      )}

      <aside
        className={`top-0 z-50 flex h-dvh shrink-0 flex-col border-r border-slate-200 bg-white transition-all duration-200 ${
          collapsed ? "w-[76px]" : "w-60"
        } ${
          mobileOpen
            ? "fixed inset-y-0 left-0 translate-x-0 shadow-xl"
            : "fixed -translate-x-full md:sticky md:translate-x-0"
        }`}
      >
        {/* Brand + hamburger */}
        <div className="flex items-center justify-between gap-2 border-b border-slate-200 px-3.5 py-3.5">
          {collapsed ? (
            <span className="mx-auto font-sans text-[13px] font-bold text-blue-600">
              PSX
            </span>
          ) : (
            <Link href="/" className="leading-tight">
              <span className="block font-sans text-[15px] font-bold tracking-tight text-slate-900">
                PSX Terminal
              </span>
              <span className="block text-[10px] font-medium tracking-[0.16em] text-slate-400">
                Equity Analytics
              </span>
            </Link>
          )}
          <button
            type="button"
            onClick={() =>
              window.innerWidth < 768
                ? setMobileOpen(false)
                : toggleCollapsed()
            }
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            title={collapsed ? "Expand" : "Collapse"}
            className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700"
          >
            <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M4 6h16M4 12h16M4 18h16" />
            </svg>
          </button>
        </div>

        {/* Menu */}
        <nav className="flex-1 space-y-1 px-2.5 py-3">
          {MENU.map((item) => {
            const active = isActive(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                onClick={() => setMobileOpen(false)}
                aria-current={active ? "page" : undefined}
                title={item.label}
                className={`flex items-center gap-3 rounded-lg px-2.5 py-2 text-[13px] font-medium transition-colors ${
                  active
                    ? "bg-blue-50 font-semibold text-blue-700"
                    : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
                } ${collapsed ? "justify-center" : ""}`}
              >
                <svg
                  viewBox="0 0 24 24"
                  className="h-4 w-4 shrink-0 text-slate-400"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth={1.8}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden
                >
                  {item.glyph === "sparkles" && (
                    <>
                      <path d="M12 3l2.5 5.5L20 11l-5.5 2.5L12 19l-2.5-5.5L4 11l5.5-2.5L12 3z" />
                      <path d="M19 15l.7 1.6L21.5 17.5l-1.6.7L19 20l-.7-1.6L16.5 17.5l1.6-.7L19 15z" />
                    </>
                  )}
                  {item.glyph === "chart" && (
                    <>
                      <path d="M4 19V5" />
                      <path d="M4 19h16" />
                      <path d="M8 15v-4" />
                      <path d="M12 15V8" />
                      <path d="M16 15v-6" />
                    </>
                  )}
                  {item.glyph === "building" && (
                    <>
                      <path d="M3 21h18" />
                      <path d="M5 21V5a2 2 0 012-2h6a2 2 0 012 2v16" />
                      <path d="M9 7h1" />
                      <path d="M9 11h1" />
                      <path d="M9 15h1" />
                      <path d="M14 7h1" />
                      <path d="M14 11h1" />
                      <path d="M14 15h1" />
                    </>
                  )}
                  {item.glyph === "trending-up" && (
                    <>
                      <path d="M3 17l6-6 4 4 8-8" />
                      <path d="M15 7h6v6" />
                    </>
                  )}
                </svg>
                {!collapsed && item.label}
              </Link>
            );
          })}
        </nav>

        {/* Footer stamp */}
        <div
          className={`border-t border-slate-200 px-3.5 py-3 ${
            collapsed ? "hidden md:block" : ""
          }`}
        >
          <p className="text-[10px] leading-relaxed tracking-[0.06em] text-slate-400">
            Certified EOD &amp; NCCPL Feed · Daily 16:30 PKT
          </p>
        </div>
      </aside>
    </>
  );
}
