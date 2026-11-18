import type { Metadata } from "next";
import DeskNav from "@/components/DeskNav";
import "./globals.css";

export const metadata: Metadata = {
  title: "PSX Quant Fund - Institutional Desk",
  description:
    "Two screens only: today's PSX buy and avoid calls, plus the audited performance history behind them.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="bg-slate-50 text-slate-900 antialiased">
        <div className="min-h-screen flex">
          <aside className="w-64 shrink-0 border-r border-slate-200 bg-white flex flex-col">
            <div className="px-4 h-14 flex flex-col justify-center border-b border-slate-200">
              <span className="text-sm font-extrabold tracking-tight text-slate-900">PSX Quant Fund</span>
              <span className="text-[11px] font-medium text-slate-500">Institutional Desk</span>
            </div>

            <DeskNav />

            <div className="px-4 py-4 border-t border-slate-200 text-[11px] text-slate-400 space-y-1">
              <div className="truncate">Signals computed at close</div>
              <div className="truncate">Spot buys · DFX carry traps</div>
            </div>
          </aside>

          <main className="flex-1 min-w-0 overflow-auto">
            <div className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6">{children}</div>
          </main>
        </div>
      </body>
    </html>
  );
}
