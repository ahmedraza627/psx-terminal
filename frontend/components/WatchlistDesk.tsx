"use client";

import { useEffect, useMemo, useState } from "react";
import { Badge, DataTable, DeskFrame, Row } from "@/components/ui/primitives";
import { fmtPct, fmtPrice, fmtX, tonePct } from "@/components/ui/format";
import type { WhaleRow } from "@/lib/queries";

/**
 * Multi-tier watchlists persisted in localStorage. Breakout flags come from
 * the live session signals: a ticker holding a WHALE_RADAR / MOMENTUM row
 * with volume >= 2x SMA20 prints BREAKOUT; else quiet.
 */
export const DEFAULT_LISTS: Record<string, string[]> = {
  "ACTIVE PROP IDEAS": [],
  "DIVIDEND YIELD": [],
  "KIBOR PLAYS": [],
};

const LS_KEY = "psx-terminal-watchlists-v1";

function loadLists(): Record<string, string[]> {
  try {
    const raw = window.localStorage.getItem(LS_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as Record<string, string[]>;
      return { ...DEFAULT_LISTS, ...parsed };
    }
  } catch {
    /* first run */
  }
  return { ...DEFAULT_LISTS };
}

function saveLists(lists: Record<string, string[]>) {
  try {
    window.localStorage.setItem(LS_KEY, JSON.stringify(lists));
  } catch {
    /* storage unavailable (private mode) — lists stay session-local */
  }
}

interface Props {
  whaleRows: WhaleRow[];
  kiborTickers: string[];
  dividendTickers: string[];
  onInspect: (ticker: string) => void;
}

export default function WatchlistDesk({
  whaleRows,
  kiborTickers,
  dividendTickers,
  onInspect,
}: Props) {
  const [lists, setLists] = useState<Record<string, string[]>>(DEFAULT_LISTS);
  const [active, setActive] = useState<string>("ACTIVE PROP IDEAS");
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    setLists(loadLists());
    setHydrated(true);
  }, []);

  // Seed the curated tiers once from live data (only when still empty).
  useEffect(() => {
    if (!hydrated) return;
    const seeds: Record<string, string[]> = {
      "KIBOR PLAYS": kiborTickers.slice(0, 12),
      "DIVIDEND YIELD": dividendTickers.slice(0, 12),
    };
    const next = { ...lists };
    let changed = false;
    for (const [name, seed] of Object.entries(seeds)) {
      if ((next[name] ?? []).length === 0 && seed.length > 0) {
        next[name] = seed;
        changed = true;
      }
    }
    if (changed) {
      setLists(next);
      saveLists(next);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hydrated, kiborTickers.join(","), dividendTickers.join(",")]);

  const whaleBy = useMemo(() => {
    const m = new Map<string, WhaleRow>();
    for (const r of whaleRows) m.set(r.ticker.toUpperCase(), r);
    return m;
  }, [whaleRows]);

  const update = (next: Record<string, string[]>) => {
    setLists(next);
    saveLists(next);
  };

  const addTicker = () => {
    const t = (window.prompt("ADD SYMBOL TO " + active) ?? "")
      .trim()
      .toUpperCase();
    if (!t) return;
    const list = lists[active] ?? [];
    if (list.includes(t)) return;
    update({ ...lists, [active]: [...list, t] });
  };

  const removeTicker = (t: string) => {
    update({
      ...lists,
      [active]: (lists[active] ?? []).filter((x) => x !== t),
    });
  };

  const activeList = lists[active] ?? [];

  return (
    <DeskFrame
      title="Institutional Watchlists"
      right={
        <div className="flex items-center gap-1">
          {Object.keys(lists).map((name) => (
            <button
              key={name}
              onClick={() => setActive(name)}
              className={`rounded-[2px] px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider ring-1 ${
                name === active
                  ? "bg-info/10 text-info ring-info/30"
                  : "bg-panel text-muted ring-hairline hover:text-ink"
              }`}
            >
              {name} {(lists[name] ?? []).length}
            </button>
          ))}
          <button
            onClick={addTicker}
            className="rounded-[2px] px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-info ring-1 ring-info/30 hover:bg-info/10"
          >
            + ADD
          </button>
        </div>
      }
      footer={
        <p className="font-mono text-[10px] leading-relaxed text-ghost">
          Breakout = live-session volume ≥ 2.0× SMA20 on a WHALE_RADAR or
          MOMENTUM signal row. Lists persist locally (localStorage) per desk
          terminal.
        </p>
      }
    >
      {activeList.length === 0 ? (
        <p className="px-2.5 py-4 text-center font-mono text-[10px] uppercase tracking-widest text-ghost">
          EMPTY LIST — + ADD TO BUILD IT
        </p>
      ) : (
        <DataTable
          minWidth={560}
          columns={[
            { label: "Ticker" },
            { label: "LTP", align: "right" },
            { label: "Day %", align: "right" },
            { label: "Vol x20", align: "right" },
            { label: "Stop", align: "right" },
            { label: "State", align: "right" },
            { label: "", align: "right" },
          ]}
        >
          {activeList.map((t) => {
            const w = whaleBy.get(t.toUpperCase());
            const volX = w?.meta.vol_multiple ?? null;
            const breakout =
              volX != null && volX >= 2.0 && w?.meta.conviction != null;
            return (
              <Row key={t}>
                <td className="px-2.5 py-1 font-mono text-[11px] font-semibold text-ink">
                  <button
                    onClick={() => onInspect(t)}
                    className="hover:text-info"
                  >
                    {t}
                  </button>
                </td>
                <td className="px-2 py-1 text-right font-mono text-[11px] tabular-nums text-ink">
                  {fmtPrice(w?.entry_reference ?? null)}
                </td>
                <td className="px-2 py-1 text-right">
                  <span
                    className={`font-mono text-[11px] tabular-nums ${tonePct(w?.meta.drift_pct ?? null)}`}
                  >
                    {fmtPct(w?.meta.drift_pct ?? null)}
                  </span>
                </td>
                <td className="px-2 py-1 text-right font-mono text-[11px] tabular-nums text-info">
                  {fmtX(volX)}
                </td>
                <td className="px-2 py-1 text-right font-mono text-[11px] tabular-nums text-bear">
                  {fmtPrice(w?.stop_loss ?? null)}
                </td>
                <td className="px-2 py-1 text-right">
                  {breakout ? (
                    <Badge tone="bull">BREAKOUT</Badge>
                  ) : w ? (
                    <Badge tone="neutral">QUIET</Badge>
                  ) : (
                    <Badge tone="ghost">NO SESSION DATA</Badge>
                  )}
                </td>
                <td className="px-2 py-1 text-right">
                  <button
                    onClick={() => removeTicker(t)}
                    className="font-mono text-[10px] text-ghost hover:text-bear"
                    aria-label={`Remove ${t}`}
                  >
                    ✕
                  </button>
                </td>
              </Row>
            );
          })}
        </DataTable>
      )}
    </DeskFrame>
  );
}
