"use client";

import { useEffect, useMemo, useRef, useState } from "react";

export type CommandAction =
  | { kind: "TAB"; tabId: string }
  | { kind: "COMPARE"; tickers: string[] }
  | { kind: "INSPECT"; ticker: string };

const DESK_COMMANDS: { cmd: string; label: string; tabId: string }[] = [
  { cmd: "WHALE", label: "Whale Matrix", tabId: "WHALE" },
  { cmd: "RESEARCH", label: "Research Desk", tabId: "RESEARCH" },
  { cmd: "ROTATION", label: "Sector Rotation", tabId: "ROTATION" },
  { cmd: "KIBOR", label: "KIBOR Easing Desk", tabId: "KIBOR" },
  { cmd: "LEDGER", label: "Insider Conviction Ledger", tabId: "LEDGER" },
  { cmd: "MOMENTUM", label: "Momentum Blotter", tabId: "MOMENTUM" },
  { cmd: "MTS", label: "MTS Squeeze Desk", tabId: "MTS" },
  { cmd: "NDM", label: "NDM Tape", tabId: "NDM" },
  { cmd: "EDGE", label: "Edge Lab", tabId: "EDGE" },
  { cmd: "RISK", label: "Risk Desk", tabId: "RISK" },
  { cmd: "PORTFOLIO", label: "Model Portfolio Desk", tabId: "PORTFOLIO" },
  { cmd: "WIRE", label: "Market Insights Wire", tabId: "WIRE" },
  { cmd: "NOTES", label: "Companies Explained", tabId: "NOTES" },
  { cmd: "WATCH", label: "Watchlists", tabId: "WATCH" },
];

/**
 * Bloomberg-style command bar (Cmd+K or `/`).
 * Grammar:  COMP <SYM> <SYM> [SYM]  -> comparison desk
 *           <DESK-VERB>             -> switch desk
 *           <TICKER>                -> inspection drawer
 */
export default function CommandBar({
  open,
  onClose,
  onAction,
  tickers,
}: {
  open: boolean;
  onClose: () => void;
  onAction: (a: CommandAction) => void;
  tickers: string[];
}) {
  const [text, setText] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) {
      setText("");
      // Focus after paint so the slide-in doesn't swallow the click.
      const t = setTimeout(() => inputRef.current?.focus(), 30);
      return () => clearTimeout(t);
    }
  }, [open]);

  const suggestions = useMemo(() => {
    const raw = text.trim().toUpperCase();
    if (!raw) {
      return [
        { kind: "hint" as const, text: "COMP <SYM> <SYM> — head-to-head" },
        { kind: "hint" as const, text: "<TICKER> — inspect symbol" },
        ...DESK_COMMANDS.slice(0, 6).map((d) => ({
          kind: "desk" as const,
          text: d.cmd,
          label: d.label,
          tabId: d.tabId,
        })),
      ];
    }
    if (raw.startsWith("COMP ")) {
      const parts = raw.slice(5).split(/\s+/).filter(Boolean);
      return [
        {
          kind: "compare" as const,
          text: `COMP ${parts.join(" ")}`,
          label:
            parts.length >= 2
              ? `COMPARE ${parts.join(" · ")}`
              : "ADD A SECOND SYMBOL",
        },
      ];
    }
    const deskHits = DESK_COMMANDS.filter((d) => d.cmd.startsWith(raw));
    const tickerHits = tickers
      .filter((t) => t.startsWith(raw))
      .slice(0, 8)
      .map((t) => ({ kind: "ticker" as const, text: t, label: "INSPECT" }));
    return [
      ...deskHits.map((d) => ({
        kind: "desk" as const,
        text: d.cmd,
        label: d.label,
        tabId: d.tabId,
      })),
      ...tickerHits,
    ];
  }, [text, tickers]);

  const execute = () => {
    const raw = text.trim().toUpperCase();
    if (!raw) return;
    if (raw.startsWith("COMP ")) {
      const parts = raw.slice(5).split(/\s+/).filter(Boolean);
      if (parts.length >= 2) {
        onAction({ kind: "COMPARE", tickers: parts.slice(0, 3) });
        onClose();
      }
      return;
    }
    const desk = DESK_COMMANDS.find((d) => d.cmd === raw);
    if (desk) {
      onAction({ kind: "TAB", tabId: desk.tabId });
      onClose();
      return;
    }
    const ticker =
      tickers.find((t) => t === raw) ??
      tickers.find((t) => t.startsWith(raw)) ??
      raw;
    onAction({ kind: "INSPECT", ticker });
    onClose();
  };

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-40 bg-obsidian/80"
      onClick={onClose}
      role="presentation"
    >
      <div
        className="mx-auto mt-16 w-[min(560px,92vw)] border border-hairline bg-panel"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-label="Terminal command bar"
      >
        <div className="flex items-center gap-2 border-b border-hairline px-2.5 py-1.5">
          <span className="font-mono text-[10px] uppercase tracking-widest text-info">
            CMD
          </span>
          <input
            ref={inputRef}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") execute();
              if (e.key === "Escape") onClose();
            }}
            placeholder="WHALE · COMP SYS NETSOL · <TICKER>"
            className="h-7 w-full bg-transparent font-mono text-xs uppercase tracking-wider text-ink placeholder:text-ghost focus:outline-none"
          />
          <span className="font-mono text-[9px] text-ghost">ESC</span>
        </div>
        <div className="max-h-64 overflow-y-auto scroll-thin">
          {suggestions.map((s, i) => (
            <button
              key={`${s.text}-${i}`}
              onClick={() => {
                if (s.kind === "hint") return;
                if (s.kind === "desk") {
                  onAction({ kind: "TAB", tabId: s.tabId });
                  onClose();
                } else if (s.kind === "ticker") {
                  onAction({ kind: "INSPECT", ticker: s.text });
                  onClose();
                } else if (s.kind === "compare") {
                  setText(s.text);
                }
              }}
              className="flex w-full items-center justify-between border-b border-hairline px-2.5 py-1.5 text-left hover:bg-hoverline"
            >
              <span className="font-mono text-[11px] text-ink">{s.text}</span>
              <span className="font-mono text-[9px] uppercase tracking-widest text-ghost">
                {"label" in s ? s.label : ""}
              </span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
