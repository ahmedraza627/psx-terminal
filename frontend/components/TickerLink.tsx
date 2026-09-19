"use client";

import Link from "next/link";

/**
 * The one interactive wrapper for ticker symbols across the console.
 * A client-side Link to /ticker/[ticker] (the deep-dive slide-over) - no
 * state, no handlers, just navigation, so the client cost is nil. Colors
 * inherit from the wrapping cell (Tailwind preflight); hover adds the
 * info-blue affordance.
 */
export default function TickerLink({
  ticker,
  className = "",
  title = "Open deep-dive",
}: {
  ticker: string;
  className?: string;
  title?: string;
}) {
  return (
    <Link
      href={`/ticker/${encodeURIComponent(ticker)}`}
      title={title}
      className={`hover:text-info ${className}`}
    >
      {ticker}
    </Link>
  );
}
