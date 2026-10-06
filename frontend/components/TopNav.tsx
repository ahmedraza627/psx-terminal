"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import ConsoleRefresh from "@/components/ConsoleRefresh";

/**
 * Sticky executive navigation header.
 *
 * Left: brand + live session status pill. Center: the four desk tabs -
 * anchor jumps to the page's server-rendered sections (no data hiding, no
 * client fetch layer; scrollIntoView only). Right: active session badge,
 * quick ticker search (routes to the /ticker deep-dive) and the refresh
 * control. The only client JS is click/submit handlers.
 */

const TABS = [
  { id: "radar", label: "Overview · Radar" },
  { id: "flow", label: "Institutional Flow" },
  { id: "blocks", label: "Off-Market & Blocks" },
  { id: "breakouts", label: "Volume Breakouts" },
] as const;

export default function TopNav({
  sessionLabel,
  marketState,
}: {
  /** Certified session label shown in the badge (null = nothing stored). */
  sessionLabel: string | null;
  /** "ACTIVE" | "CLOSED" - resolved server-side, never guessed here. */
  marketState: "ACTIVE" | "CLOSED";
}) {
  const [active, setActive] = useState<string>("radar");
  const [draft, setDraft] = useState("");
  const router = useRouter();

  const jump = (id: string) => {
    setActive(id);
    document
      .getElementById(id)
      ?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const search = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const t = draft.trim().toUpperCase();
    if (t.length > 0) router.push(`/ticker/${encodeURIComponent(t)}`);
  };

  return (
    <header className="sticky top-0 z-30 border-b border-hairline bg-obsidian/95 backdrop-blur">
      <div className="mx-auto flex w-full max-w-[1600px] flex-wrap items-center gap-x-3 gap-y-2 px-3 py-2">
        {/* Brand + live status pill */}
        <div className="flex min-w-0 items-center gap-2.5">
          <h1 className="whitespace-nowrap font-mono text-[13px] font-bold tracking-[0.18em] text-ink">
            PSX<span className="text-info">·</span>QUANT TERMINAL
          </h1>
          <span
            className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 font-mono text-[9px] font-bold uppercase tracking-widest ring-1 ${
              marketState === "ACTIVE"
                ? "bg-bull/10 text-bull ring-bull/40"
                : "bg-panel text-muted ring-hairline"
            }`}
          >
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                marketState === "ACTIVE"
                  ? "animate-pulse bg-bull"
                  : "bg-ghost"
              }`}
            />
            {marketState === "ACTIVE" ? "Market Active" : "Market Closed"}
          </span>
        </div>

        {/* Session badge + quick search + refresh */}
        <div className="ml-auto flex items-center gap-2">
          {sessionLabel && (
            <span className="hidden rounded-[2px] border border-hairline bg-panel px-1.5 py-0.5 font-mono text-[10px] tabular-nums text-info sm:inline">
              SESSION {sessionLabel}
            </span>
          )}
          <form onSubmit={search}>
            <input
              type="text"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              maxLength={20}
              placeholder="SEARCH TICKER"
              aria-label="Quick ticker search"
              className="h-7 w-28 rounded-[2px] border border-hairline bg-panel px-2 font-mono text-[10px] uppercase tracking-widest text-ink placeholder:text-ghost/70 focus:border-info focus:outline-none sm:w-36"
            />
          </form>
          <ConsoleRefresh syncing={false} />
        </div>
      </div>

      {/* Desk tab rail - anchor navigation over server-rendered sections */}
      <nav className="mx-auto flex w-full max-w-[1600px] items-center gap-1 overflow-x-auto px-3">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => jump(t.id)}
            className={`whitespace-nowrap border-b-2 px-2.5 py-1.5 font-mono text-[10px] font-semibold uppercase tracking-widest transition-colors ${
              active === t.id
                ? "border-info text-info"
                : "border-transparent text-muted hover:text-ink"
            }`}
          >
            {t.label}
          </button>
        ))}
      </nav>
    </header>
  );
}
