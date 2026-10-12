import type { Metadata, Viewport } from "next";
import Sidebar from "@/components/Sidebar";
import "./globals.css";

export const metadata: Metadata = {
  title: "PSX Terminal - Equity Analytics",
  description:
    "Institutional equity analytics for PSX: short, mid, and long-term verdicts, market pulse, and institutional flow.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#F1F5F9",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-dvh bg-slate-50 font-sans text-ink antialiased">
        <div className="flex min-h-dvh">
          <Sidebar />
          <main className="min-w-0 flex-1 overflow-x-hidden">{children}</main>
        </div>
      </body>
    </html>
  );
}
