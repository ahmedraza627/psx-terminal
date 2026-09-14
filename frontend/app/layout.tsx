import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "PSX QUANT TERMINAL",
  description:
    "Institutional PSX & NCCPL intelligence: smart-money flows, tiered edge analytics, fundamental alpha and microstructure desks.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#090A0C",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-dvh bg-obsidian font-sans text-ink antialiased">
        {children}
      </body>
    </html>
  );
}
