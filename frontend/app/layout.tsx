import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "PSX DESK",
  description:
    "Single-page institutional console: certified NCCPL flows, NDM block tape, and verified universe breadth. No signals, no predictions.",
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
