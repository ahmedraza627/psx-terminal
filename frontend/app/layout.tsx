import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "PSX Intelligence",
  description:
    "Daily PSX & NCCPL quantitative signals: smart-money flows, momentum and dividend screens.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#020617",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-dvh bg-slate-950 text-slate-100 antialiased">
        {children}
      </body>
    </html>
  );
}
