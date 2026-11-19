import type { Metadata } from "next";
import DeskShell from "@/components/DeskShell";
import "./globals.css";

export const metadata: Metadata = {
  title: "PSX Quant Fund - Institutional Desk",
  description:
    "Today's PSX buy and avoid calls, the seasonal playbook behind them, and the audited performance history.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen bg-[#060A11] text-slate-200 antialiased">
        <DeskShell>{children}</DeskShell>
      </body>
    </html>
  );
}
