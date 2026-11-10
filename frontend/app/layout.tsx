"use client";

import React, { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import "./globals.css";

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  const navItems = [
    { href: "/", label: "Daily Recommendations" },
    { href: "/history", label: "Historical Performance" },
    { href: "/insiders", label: "Director & Sponsor Filings" },
  ];

  return (
    <html lang="en">
      <body className="bg-slate-50 text-slate-900 min-h-screen flex flex-col md:flex-row">
        {/* Mobile Top Header */}
        <div className="md:hidden bg-slate-900 border-b border-slate-800 px-4 py-3 flex items-center justify-between sticky top-0 z-50">
          <div className="flex items-center gap-2">
            <span className="font-mono font-black text-white text-base tracking-wider">PSX</span>
            <span className="text-xs font-semibold text-slate-400">Trading Desk</span>
          </div>
          <button
            onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
            className="p-1.5 text-slate-300 hover:text-white rounded bg-slate-800"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d={mobileMenuOpen ? "M6 18L18 6M6 6l12 12" : "M4 6h16M4 12h16M4 18h16"} />
            </svg>
          </button>
        </div>

        {/* Mobile Dropdown Menu */}
        {mobileMenuOpen && (
          <div className="md:hidden bg-slate-900 border-b border-slate-800 p-3 space-y-1 z-40 sticky top-12">
            {navItems.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                onClick={() => setMobileMenuOpen(false)}
                className={`block px-3 py-2 rounded-lg text-xs font-medium ${
                  pathname === item.href
                    ? "bg-blue-600 text-white font-semibold"
                    : "text-slate-400 hover:bg-slate-800 hover:text-slate-200"
                }`}
              >
                {item.label}
              </Link>
            ))}
          </div>
        )}

        {/* Desktop Sidebar */}
        <aside className="hidden md:flex w-60 bg-slate-900 border-r border-slate-800 text-slate-300 flex-col shrink-0 min-h-screen sticky top-0 h-screen">
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
            Session 2026 Certified Tape
          </div>
        </aside>

        {/* Main Content Area */}
        <main className="flex-1 bg-slate-50 min-h-screen overflow-x-hidden">
          {children}
        </main>
      </body>
    </html>
  );
}