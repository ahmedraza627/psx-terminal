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
      <body className="bg-slate-50 text-slate-900 antialiased min-h-screen flex flex-col md:flex-row font-sans">
        {/* MOBILE & DESKTOP SIDEBAR */}
        <aside className="w-full md:w-64 bg-white border-b md:border-b-0 md:border-r border-slate-200 p-4 flex md:flex-col justify-between items-center md:items-stretch shrink-0 shadow-sm">
          <div className="flex md:flex-col items-center md:items-start justify-between w-full gap-3">
            <div className="flex items-center gap-2 px-1 pt-1">
              <span className="px-2.5 py-1 rounded bg-slate-900 text-emerald-400 font-mono text-xs font-black tracking-wider">
                PSX
              </span>
              <span className="font-extrabold text-sm tracking-tight text-slate-900">
                Institutional Desk
              </span>
            </div>
            
            {/* MOBILE & DESKTOP NAVIGATION TABS */}
            <nav className="flex md:flex-col gap-1.5 w-full md:w-auto">
              <Link
                href="/"
                className="flex-1 md:flex-none px-3 py-2 rounded-lg text-xs font-bold text-slate-800 bg-slate-100 hover:bg-slate-900 hover:text-white border border-slate-200/80 transition shadow-sm text-center md:text-left"
              >
                 Daily Signals
              </Link>
              <Link
                href="/history"
                className="flex-1 md:flex-none px-3 py-2 rounded-lg text-xs font-bold text-slate-800 bg-slate-100 hover:bg-slate-900 hover:text-white border border-slate-200/80 transition shadow-sm text-center md:text-left"
              >
                 Audit Log
              </Link>
            </nav>
          </div>
          
          <div className="hidden md:block px-1 pt-4 border-t border-slate-100 text-[11px] font-mono font-bold text-slate-400">
            Smart Money Quant Engine
          </div>
        </aside>
        
        <main className="flex-1 min-w-0 overflow-y-auto">{children}</main>
      </body>
    </html>
  );
}
