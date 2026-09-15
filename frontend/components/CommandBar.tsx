"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Badge } from "@/components/ui/primitives";
import { fmtPct, fmtPrice, fmtX } from "@/components/ui/format";
import {
  computeAmihudStats,
  type EodPoint,
  type FundamentalsRow,
} from "@/lib/deskQueries";
import type { KiborRow } from "@/lib/queries";

export type CommandAction =
  | { kind: "TAB"; tabId: string }
  | { kind: "COMPARE"; tickers: string[] }
  | { kind: "INSPECT"; ticker: string }
  | { kind: "FLOW_SECTOR"; sector: string };

const DESK_COMMANDS: { cmd: string; label: string; tabId: string }[] = [
  { cmd: "WHALE", label: "Whale Matrix", tabId: "WHALE" },
  { cmd: "RESEARCH", label: "Research Desk", tabId: "RESEARCH" },
  { cmd: "ROTATION", label: "Sector Rotation", tabId: "ROTATION" },
  { cmd: "BREADTH", label: "Market Breadth & Liquidity", tabId: "BREADTH" },
  { cmd: "FLOW", label: "Institutional Flow & Rate Shock", tabId: "FLOW" },
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

/** Amihud liquidity tier shared with the Market Breadth desk. */
function amihudTier(
  v: number | null
): { label: string; tone: "bull" | "warn" | "bear" | "neutral" } {
  if (v == null) return { label: "UNRANKED", tone: "neutral" };
  if (v >= 50) return { label: "ILLIQUID TRAP", tone: "bear" };
  if (v >= 10) return { label: "ILLIQUID — HIGH IMPACT", tone: "bear" };
  if (v >= 1) return { label: "THIN — MODERATE", tone: "warn" };
  return { label: "INSTITUTIONAL", tone: "bull" };
}

/** D/E risk tier (unknown until a balance-sheet feed publishes debt). */
function deTier(
  de: number | null
): { label: string; tone: "bull" | "warn" | "bear" | "neutral" } {
  if (de == null) return { label: "DE N/A", tone: "neutral" };
  if (de > 1.5) return { label: "GEARED", tone: "bear" };
  if (de > 0.75) return { label: "MODERATE GEAR", tone: "warn" };
  return { label: "LOW GEAR", tone: "bull" };
}

interface QuoteStat {
  ltp: number | null;
  chgSessionPct: number | null;
  chg5dPct: number | null;
  amihud: number | null;
  medianTurnoverPkr: number | null;
}

/**
 * Bloomberg-style command bar (Ctrl+K / Cmd+K or `/`).
 * Grammar:  COMP <SYM> <SYM> [SYM]  -> comparison desk
 *           <DESK-VERB>             -> switch desk
 *           <TICKER>                -> Quick-Quote HUD + inspection drawer
 *
 * The Quick-Quote HUD renders live from the terminal's pre-loaded state
 * (eod / fundamentals / kibor / sectorMap) — zero additional Supabase
 * roundtrips; incomplete data renders as honest "—".
 */
export default function CommandBar({
  open,
  onClose,
  onAction,
  tickers,
  eod = [],
  fundamentals = [],
  kibor = [],
  sectorMap = new Map(),
}: {
  open: boolean;
  onClose: () => void;
  onAction: (a: CommandAction) => void;
  tickers: string[];
  eod?: EodPoint[];
  fundamentals?: FundamentalsRow[];
  kibor?: KiborRow[];
  sectorMap?: Map<string, string>;
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

  // ---- Quote engine: HUD context for the best ticker match --------------
  const hud = useMemo(() => {
    const raw = text.trim().toUpperCase();
    if (!raw || raw.includes(" ")) return null;

    // Desk verbs never trigger the HUD.
    if (DESK_COMMANDS.some((d) => d.cmd.startsWith(raw) && raw.length >= 2)) {
      return null;
    }
    const exact = tickers.find((t) => t === raw);
    const prefix = tickers.find((t) => t.startsWith(raw));
    const ticker = exact ?? prefix;
    if (ticker == null) return null;

    const sector = sectorMap.get(ticker) ?? null;
    const fund = fundamentals.find((f) => f.ticker === ticker) ?? null;
    const k = kibor.find((x) => x.ticker === ticker) ?? null;

    // Chronological series from pre-loaded EOD history.
    const series = eod
      .filter((r) => r.ticker === ticker && r.close != null)
      .sort((a, b) => (a.tradeDate < b.tradeDate ? -1 : 1));
    const closes = series.map((r) => r.close as number);
    const ltp = closes.length > 0 ? closes[closes.length - 1] : null;
    const prevClose = closes.length >= 2 ? closes[closes.length - 2] : null;
    const base5 = closes.length >= 5 ? closes[closes.length - 5] : null;
    const chgSessionPct =
      prevClose != null && prevClose > 0
        ? ((ltp as number) - prevClose) / prevClose * 100
        : null;
    const chg5dPct =
      base5 != null && base5 > 0
        ? ((ltp as number) - base5) / base5 * 100
        : null;

    const { amihud, medianTurnoverPkr } = computeAmihudStats(
      series.map((r) => ({ close: r.close, volume: r.volume }))
    );

    const de =
      fund?.pbRatio != null && fund.peRatio != null && fund.peRatio > 0
        ? fund.pbRatio / fund.peRatio
        : null;

    const stat: QuoteStat = {
      ltp,
      chgSessionPct,
      chg5dPct,
      amihud,
      medianTurnoverPkr,
    };

    // Hotkeys: C = compare desk (needs one more name), F = flow filtered by
    // sector, B = breadth desk. Only when there is a real quote context.
    const actions: { key: string; label: string; run: () => void }[] = [];
    if (exact != null) {
      actions.push({
        key: "C",
        label: "COMPARE",
        run: () => {
          onAction({ kind: "COMPARE", tickers: [ticker] });
          onClose();
        },
      });
      if (sector != null) {
        actions.push({
          key: "F",
          label: "FLOW @ SECTOR",
          run: () => {
            onAction({ kind: "FLOW_SECTOR", sector });
            onClose();
          },
        });
      }
      actions.push({
        key: "B",
        label: "BREADTH",
        run: () => {
          onAction({ kind: "TAB", tabId: "BREADTH" });
          onClose();
        },
      });
    }

    return { ticker, sector, fund, kiborRow: k, stat, de, actions, exact: exact != null };
  }, [text, tickers, eod, fundamentals, kibor, sectorMap, onAction, onClose]);

  const suggestions = useMemo(() => {
    const raw = text.trim().toUpperCase();
    if (!raw) {
      return [
        { kind: "hint" as const, text: "COMP <SYM> <SYM> — head-to-head" },
        { kind: "hint" as const, text: "<TICKER> — quick quote + inspect" },
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
      .map((t) => ({ kind: "ticker" as const, text: t, label: "QUOTE" }));
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

  const pctCls = (v: number | null): string =>
    v == null
      ? "text-ghost"
      : v > 0.0005
        ? "text-bull"
        : v < -0.0005
          ? "text-bear"
          : "text-muted";

  return (
    <div
      className="fixed inset-0 z-40 bg-obsidian/80"
      onClick={onClose}
      role="presentation"
    >
      <div
        className="mx-auto mt-12 w-[min(620px,94vw)] border border-hairline bg-panel"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-label="Terminal command bar"
      >
        {/* Prompt row */}
        <div className="flex items-center gap-2 border-b border-hairline px-2.5 py-1.5">
          <span className="font-mono text-[10px] uppercase tracking-widest text-info">
            CMD
          </span>
          <input
            ref={inputRef}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                execute();
                return;
              }
              if (e.key === "Escape") {
                onClose();
                return;
              }
              // Institutional hotkeys fire only on an exact quote context,
              // so they never hijack normal typing of a longer symbol.
              if (
                e.key.length === 1 &&
                !e.metaKey &&
                !e.ctrlKey &&
                !e.altKey &&
                hud?.exact
              ) {
                const match = hud.actions.find(
                  (a) => a.key === e.key.toUpperCase()
                );
                if (match != null) {
                  e.preventDefault();
                  match.run();
                }
              }
            }}
            placeholder="WHALE · COMP SYS NETSOL · <TICKER>"
            className="h-7 w-full bg-transparent font-mono text-xs uppercase tracking-wider text-ink placeholder:text-ghost focus:outline-none"
          />
          <span className="font-mono text-[9px] text-ghost">ESC</span>
        </div>

        {/* Quick-Quote HUD */}
        {hud && (
          <div className="border-b border-hairline bg-obsidian px-2.5 py-2">
            <div className="flex items-baseline justify-between">
              <div className="flex items-baseline gap-2">
                <span className="font-mono text-sm font-bold tracking-wider text-ink">
                  {hud.ticker}
                </span>
                <span className="font-mono text-[10px] uppercase tracking-wider text-ghost">
                  {hud.sector ?? "SECTOR —"}
                </span>
              </div>
              <div className="flex items-baseline gap-2">
                <span className="font-mono text-sm font-bold tabular-nums text-ink">
                  {fmtPrice(hud.stat.ltp)}
                </span>
                <span
                  className={`font-mono text-[11px] font-semibold tabular-nums ${pctCls(
                    hud.stat.chgSessionPct
                  )}`}
                >
                  {fmtPct(hud.stat.chgSessionPct, 2)}
                </span>
              </div>
            </div>

            <div className="mt-1.5 grid grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-4">
              <div>
                <p className="font-mono text-[9px] uppercase tracking-widest text-ghost">
                  5D TREND
                </p>
                <p
                  className={`font-mono text-xs font-semibold tabular-nums ${pctCls(
                    hud.stat.chg5dPct
                  )}`}
                >
                  {fmtPct(hud.stat.chg5dPct, 1)}
                </p>
              </div>
              <div>
                <p className="font-mono text-[9px] uppercase tracking-widest text-ghost">
                  TTM P/E
                </p>
                <p className="font-mono text-xs tabular-nums text-ink">
                  {hud.fund?.peRatio != null && hud.fund.peRatio > 0
                    ? fmtX(hud.fund.peRatio, 1)
                    : "—"}
                </p>
              </div>
              <div>
                <p className="font-mono text-[9px] uppercase tracking-widest text-ghost">
                  DIV YIELD
                </p>
                <p className="font-mono text-xs tabular-nums text-ink">
                  {hud.fund?.dividendYield != null
                    ? fmtPct(hud.fund.dividendYield, 1, false)
                    : "—"}
                </p>
              </div>
              <div>
                <p className="font-mono text-[9px] uppercase tracking-widest text-ghost">
                  MKT CAP
                </p>
                <p className="font-mono text-xs tabular-nums text-ink">
                  {hud.fund?.marketCapPkr != null
                    ? `${(hud.fund.marketCapPkr / 1e9).toFixed(1)}B`
                    : "—"}
                </p>
              </div>
            </div>

            <div className="mt-1.5 flex flex-wrap items-center gap-1">
              <Badge tone={amihudTier(hud.stat.amihud).tone}>
                {amihudTier(hud.stat.amihud).label}
              </Badge>
              <Badge tone={deTier(hud.de).tone}>
                {hud.de != null ? `D/E ${hud.de.toFixed(2)}` : "D/E N/A"}
              </Badge>
              {hud.kiborRow?.epsExpansion300bpsPct != null ? (
                <Badge tone="warn">
                  {`KIBOR +300 → EPS ${
                    hud.kiborRow.epsExpansion300bpsPct >= 0 ? "+" : ""
                  }${hud.kiborRow.epsExpansion300bpsPct.toFixed(1)}%`}
                </Badge>
              ) : (
                <Badge tone="ghost">KIBOR IMPACT N/A</Badge>
              )}
              {hud.stat.medianTurnoverPkr != null && (
                <Badge tone="neutral">
                  {`MED TURNOVER ${(hud.stat.medianTurnoverPkr / 1e6).toFixed(1)}M`}
                </Badge>
              )}
            </div>

            {/* Action hotkey strip */}
            {hud.actions.length > 0 && (
              <div className="mt-1.5 flex flex-wrap gap-1 border-t border-hairline pt-1.5">
                {hud.actions.map((a) => (
                  <button
                    key={a.key}
                    onClick={a.run}
                    className="rounded-[2px] border border-hairline bg-obsidian px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-muted hover:border-info/40 hover:text-info"
                  >
                    <span className="mr-1 font-bold text-info">[{a.key}]</span>
                    {a.label}
                  </button>
                ))}
                <button
                  onClick={() => {
                    onAction({ kind: "INSPECT", ticker: hud.ticker });
                    onClose();
                  }}
                  className="rounded-[2px] border border-info/30 bg-info/10 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-info hover:border-info/60"
                >
                  <span className="mr-1 font-bold">[↵]</span>
                  INSPECT DRAWER
                </button>
              </div>
            )}
          </div>
        )}

        {/* Suggestions */}
        <div className="max-h-56 overflow-y-auto scroll-thin">
          {suggestions.map((s, i) => (
            <button
              key={`${s.text}-${i}`}
              onClick={() => {
                if (s.kind === "hint") return;
                if (s.kind === "desk") {
                  onAction({ kind: "TAB", tabId: s.tabId });
                  onClose();
                } else if (s.kind === "ticker") {
                  setText(s.text);
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
