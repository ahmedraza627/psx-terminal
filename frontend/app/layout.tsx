import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "PSX Institutional Trade Desk",
  description: "Quantitative Liquidity Sweep, Mansfield RS & Cost-of-Carry Desk",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-slate-50 text-slate-900 antialiased min-h-screen flex flex-col md:flex-row">
        <aside className="w-full md:w-60 bg-white border-b md:border-b-0 md:border-r border-slate-200 p-4 flex flex-col justify-between shrink-0">
          <div className="space-y-6">
            <div className="flex items-center gap-2 px-2 pt-1">
              <span className="px-2 py-0.5 rounded bg-slate-900 text-emerald-400 font-mono text-xs font-bold">
                PSX
              </span>
              <span className="font-bold text-sm tracking-tight text-slate-900">
                Institutional Desk
              </span>
            </div>
            <nav className="flex md:flex-col gap-1.5">
              <Link
                href="/"
                className="px-3 py-2 rounded-lg text-xs font-semibold text-slate-800 hover:bg-slate-100 border border-transparent hover:border-slate-200 transition"
              >
                Daily Recommendations
              </Link>
              <Link
                href="/history"
                className="px-3 py-2 rounded-lg text-xs font-semibold text-slate-800 hover:bg-slate-100 border border-transparent hover:border-slate-200 transition"
              >
                Audit &amp; History
              </Link>
            </nav>
          </div>
          <div className="hidden md:block px-2 pt-4 border-t border-slate-100 text-[11px] font-mono text-slate-400">
            V5 Quant Engine • Encapsulated
          </div>
        </aside>
        <main className="flex-1 min-w-0">{children}</main>
      </body>
    </html>
  );
}
