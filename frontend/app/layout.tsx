import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "PSX Institutional Desk",
  description: "Smart Money Liquidity & Momentum Terminal",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-slate-50 text-slate-900 antialiased min-h-screen flex flex-col md:flex-row">
        {/* MOBILE & DESKTOP SIDEBAR */}
        <aside className="w-full md:w-64 bg-white border-b md:border-b-0 md:border-r border-slate-200 p-4 flex md:flex-col justify-between items-center md:items-stretch shrink-0 shadow-sm">
          <div className="flex md:flex-col items-center md:items-start justify-between w-full gap-4">
            <div className="flex items-center gap-2 px-1 pt-1">
              <span className="px-2 py-0.5 rounded bg-slate-900 text-emerald-400 font-mono text-xs font-bold">
                PSX
              </span>
              <span className="font-bold text-sm tracking-tight text-slate-900">
                Institutional Desk
              </span>
            </div>
            <nav className="flex md:flex-col gap-2">
              <Link
                href="/"
                className="px-3 py-2 rounded-lg text-xs font-semibold text-slate-800 hover:bg-slate-100 border border-slate-200/60 md:border-transparent md:hover:border-slate-200 transition"
              >
                Daily Signals
              </Link>
              <Link
                href="/history"
                className="px-3 py-2 rounded-lg text-xs font-semibold text-slate-800 hover:bg-slate-100 border border-slate-200/60 md:border-transparent md:hover:border-slate-200 transition"
              >
                Audit Log
              </Link>
            </nav>
          </div>
          <div className="hidden md:block px-1 pt-4 border-t border-slate-100 text-[11px] font-mono text-slate-400">
            Smart Money Quant Engine
          </div>
        </aside>
        <main className="flex-1 min-w-0 overflow-y-auto">{children}</main>
      </body>
    </html>
  );
}
