import type { Metadata } from "next";
import DeskShell from "@/components/DeskShell";
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
        <DeskShell>{children}</DeskShell>
      </body>
    </html>
  );
}
