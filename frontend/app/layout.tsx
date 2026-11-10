"use client";

import React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import "./globals.css";

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();

  const navItems = [
    { href: "/", label: "Daily Recommendations" },
    { href: "/history", label: "Historical Performance" },
    { href: "/insiders", label: "Director & Sponsor Filings" },
  ];

  return (
    <html lang="en">
      <body className="bg-slate-50 text-slate-900 min-h-screen flex">
        <aside className="w-60 bg-slate-900 border-r border-slate-800 text-slate-300 flex flex-col shrink-0 min-h-screen">
          <div className="p-4 border-b border-slate-800 flex items-center gap-2">
            <span className="font-mono font-black text-white text-base tracking-wider">PSX</span>
            <span className="text-xs font-semibold text-slate-400">Trading Desk</span>
          </div>
          <nav className="p-3 space-y-2 flex-1 text-xs font-medium">
            {navItems.map((item) => {
              const isActive = pathname === item.href;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`flex items-center gap-2.5 px-3 py-2.5 rounded-lg transition-colors ${
                    isActive
                      ? "bg-blue-600 text-white font-semibold"
                      : "hover:bg-slate-800 text-slate-400 hover:text-slate-200"
                  }`}
                >
                  <span>{item.label}</span>
                </Link>
              );
            })}
          </nav>
          <div className="p-3 border-t border-slate-800 text-[10px] text-slate-500 font-mono">
            Session 2026-11-10 Certified
          </div>
        </aside>

        <main className="flex-1 bg-slate-50 min-h-screen overflow-y-auto">
          {children}
        </main>
      </body>
    </html>
  );
}