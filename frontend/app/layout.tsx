import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "PSX Terminal - Stock Intelligence Desk",
  description: "Institutional execution desk for Pakistan Stock Exchange",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="bg-slate-50 text-slate-900 min-h-screen flex">
        {/* Sleek Minimal Sidebar */}
        <aside className="w-60 bg-slate-900 border-r border-slate-800 text-slate-300 flex flex-col shrink-0 min-h-screen">
          <div className="p-4 border-b border-slate-800 flex items-center gap-2">
            <span className="font-mono font-black text-white text-base tracking-wider">PSX</span>
            <span className="text-xs font-semibold text-slate-400">Trading Desk</span>
          </div>
          <nav className="p-3 space-y-2 flex-1 text-xs font-medium">
            <Link href="/" className="flex items-center gap-2.5 px-3 py-2.5 rounded-lg bg-blue-600 text-white font-semibold">
              <span>Daily Recommendations</span>
            </Link>
            <Link href="/history" className="flex items-center gap-2.5 px-3 py-2.5 rounded-lg hover:bg-slate-800 text-slate-400 hover:text-slate-200 transition-colors">
              <span>Historical Performance</span>
            </Link>
            <Link href="/insiders" className="flex items-center gap-2.5 px-3 py-2.5 rounded-lg hover:bg-slate-800 text-slate-400 hover:text-slate-200 transition-colors">
              <span>Director & Sponsor Filings</span>
            </Link>
          </nav>
          <div className="p-3 border-t border-slate-800 text-[10px] text-slate-500 font-mono">
            Session 2026 Certified
          </div>
        </aside>

        {/* Clean Light Main Workspace */}
        <main className="flex-1 bg-slate-50 min-h-screen overflow-y-auto">
          {children}
        </main>
      </body>
    </html>
  );
}