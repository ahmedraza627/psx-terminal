"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import DeskNav from "./DeskNav";

/** App frame: static sidebar on desktop, slide-over drawer with a hamburger below lg. */
export default function DeskShell({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();

  // Route change closes the drawer (covers back/forward as well as taps).
  useEffect(() => {
    setOpen(false);
  }, [pathname]);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [open]);

  return (
    <div className="min-h-screen lg:flex">
      {/* Mobile top bar — hidden once the sidebar has room */}
      <header className="sticky top-0 z-30 flex h-14 items-center justify-between gap-3 border-b border-slate-200 bg-white px-4 lg:hidden">
        <div className="flex min-w-0 items-center gap-2">
          <button
            type="button"
            onClick={() => setOpen(true)}
            aria-label="Open navigation"
            aria-expanded={open}
            aria-controls="desk-sidebar"
            className="-ml-1 rounded-lg border border-slate-200 bg-white p-2 text-slate-700 transition-colors hover:bg-slate-50 active:bg-slate-100"
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
              <path d="M4 6h16M4 12h16M4 18h16" />
            </svg>
          </button>
          <div className="min-w-0 leading-tight">
            <span className="block truncate text-sm font-extrabold tracking-tight text-slate-900">
              PSX Quant Fund
            </span>
            <span className="block truncate text-[10px] font-medium text-slate-500">Institutional Desk</span>
          </div>
        </div>
        <span className="shrink-0 rounded border border-slate-200 bg-slate-50 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
          EOD
        </span>
      </header>

      {/* Scrim */}
      {open && (
        <button
          type="button"
          aria-label="Close navigation"
          onClick={() => setOpen(false)}
          className="fixed inset-0 z-40 bg-slate-900/50 lg:hidden"
        />
      )}

      <aside
        id="desk-sidebar"
        className={`fixed inset-y-0 left-0 z-50 flex w-72 max-w-[85vw] flex-col border-r border-slate-200 bg-white shadow-xl transition-transform duration-200 ease-out lg:static lg:z-auto lg:w-64 lg:max-w-none lg:shrink-0 lg:translate-x-0 lg:shadow-none ${
          open ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="flex h-14 items-center justify-between gap-2 border-b border-slate-200 px-4">
          <div className="flex min-w-0 flex-col justify-center">
            <span className="truncate text-sm font-extrabold tracking-tight text-slate-900">PSX Quant Fund</span>
            <span className="truncate text-[11px] font-medium text-slate-500">Institutional Desk</span>
          </div>
          <button
            type="button"
            onClick={() => setOpen(false)}
            aria-label="Close navigation"
            className="rounded-lg border border-slate-200 bg-white p-1.5 text-slate-600 transition-colors hover:bg-slate-50 lg:hidden"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
              <path d="M6 6l12 12M18 6L6 18" />
            </svg>
          </button>
        </div>

        <DeskNav onNavigate={() => setOpen(false)} />

        <div className="space-y-1 border-t border-slate-200 px-4 py-4 text-[11px] text-slate-400">
          <div className="truncate">Signals computed at close</div>
          <div className="truncate">Spot buys · DFX carry traps</div>
        </div>
      </aside>

      <main className="min-w-0 flex-1">
        <div className="mx-auto w-full max-w-7xl px-4 py-5 sm:px-6 sm:py-6">{children}</div>
      </main>
    </div>
  );
}
