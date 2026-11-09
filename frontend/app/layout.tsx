import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "PSX Quant Fund - Institutional Desk",
  description:
    "Institutional execution desk: Top 5 BUY / AVOID setups, macro cash defense, broker export and the audit & history log",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="bg-slate-950 text-slate-100">
        <div className="min-h-screen flex">
          {/* Sidebar: global terminal navigation */}
          <aside className="w-64 shrink-0 border-r border-slate-800 bg-slate-900/60 flex flex-col">
            <div className="flex items-center gap-2 px-4 h-14 border-b border-slate-800">
              <span className="text-sm font-extrabold tracking-tight text-slate-100">
                PSX
              </span>
              <span className="text-xs font-semibold text-slate-500">Quant Fund</span>
            </div>
            <nav className="flex-1 px-3 py-4 space-y-1">
              <SidebarLink href="/" label="Desk" active />
              <SidebarLink href="/pulse" label="Pulse" />
              <SidebarLink href="/flow" label="Flow" />
              <SidebarLink href="/catalysts" label="Catalyst & Dividend" />
              <SidebarLink href="/breakouts" label="Breakouts" />
              <SidebarLink href="/history" label="Audit & History" />
              <SidebarLink href="/insiders" label="Insider Tracking" />
            </nav>
            <div className="px-3 py-4 border-t border-slate-800 text-[11px] text-slate-500 space-y-1">
              <div className="truncate">Institutional Desk</div>
              <div className="truncate">Session 2026-11-06</div>
            </div>
          </aside>
          <main className="flex-1 overflow-auto p-6">{children}</main>
        </div>
      </body>
    </html>
  );
}

function SidebarLink({
  href,
  label,
  active,
}: {
  href: string;
  label: string;
  active?: boolean;
}) {
  return (
    <a
      href={href}
      className={`
        flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-semibold
        transition ${active
        ? "bg-blue-600/15 text-blue-400 border border-blue-600/30"
        : "text-slate-400 hover:text-slate-100 hover:bg-slate-800/60 border border-transparent"
      }`}
    >
      <svg
        className="h-4 w-4"
        fill="none"
        viewBox="0 0 24 24"
        stroke="currentColor"
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        {active ? (
          <path d="M5 13l4 4L19 7" />
        ) : (
          <path d="M3 12l9-9 9 9M9 21V9h6v12" />
        )}
      </svg>
      {label}
    </a>
  );
}
