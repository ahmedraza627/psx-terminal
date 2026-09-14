"use client";

import { useEffect, useMemo, useState } from "react";
import { Badge, DataTable, DeskFrame, IdleState, Row } from "@/components/ui/primitives";
import { fmtPct, fmtPkrB, fmtPrice, fmtX } from "@/components/ui/format";
import type { FundamentalsRow } from "@/lib/deskQueries";
import type { KiborRow } from "@/lib/queries";
import type { ResearchRow } from "@/components/ResearchDeskBlotter";

interface Props {
  fundamentals: FundamentalsRow[];
  kibor: KiborRow[];
  research: ResearchRow[];
}

interface Cell {
  text: string;
  /** Higher-is-better ranking direction; null = informational only. */
  rank: number | null;
}

/** Metric winner highlight: bull text on the best ranked value per row. */
function cellCls(cells: Cell[], idx: number): string {
  const ranked = cells
    .map((c, i) => ({ c, i }))
    .filter((x) => x.c.rank != null && x.c.text !== "—");
  if (ranked.length < 2) return "text-ink";
  const best = ranked.reduce((a, b) =>
    (b.c.rank as number) > (a.c.rank as number) ? b : a
  );
  return best.i === idx ? "text-bull font-semibold" : "text-ink";
}

export default function StockComparisonDesk({
  fundamentals,
  kibor,
  research,
  initialPicked,
}: Props & { initialPicked?: string[] }) {
  // Command bar preselection (COMP <SYM> <SYM>).
  const universe = useMemo(
    () =>
      fundamentals
        .slice()
        .sort((a, b) => (b.marketCapPkr ?? 0) - (a.marketCapPkr ?? 0)),
    [fundamentals]
  );
  const [q, setQ] = useState("");
  const [picked, setPicked] = useState<string[]>([]);

  useEffect(() => {
    if (initialPicked && initialPicked.length >= 2) {
      setPicked(initialPicked.slice(0, 3));
    }
  }, [initialPicked]);

  const matches = useMemo(() => {
    const needle = q.trim().toUpperCase();
    if (!needle) return universe.slice(0, 8);
    return universe
      .filter(
        (f) =>
          f.ticker.includes(needle) ||
          (f.sectorName ?? "").toUpperCase().includes(needle)
      )
      .slice(0, 8);
  }, [universe, q]);

  const toggle = (t: string) =>
    setPicked((prev) =>
      prev.includes(t)
        ? prev.filter((x) => x !== t)
        : prev.length >= 3
          ? prev
          : [...prev, t]
    );

  const columns = useMemo(() => {
    const rows = picked
      .map((t) => universe.find((f) => f.ticker === t))
      .filter((f): f is FundamentalsRow => f != null);
    const kiborBy = new Map(kibor.map((k) => [k.ticker.toUpperCase(), k]));
    const researchBy = new Map(research.map((r) => [r.ticker.toUpperCase(), r]));

    const cellsFor = (f: FundamentalsRow): Cell[] => {
      const k = kiborBy.get(f.ticker);
      const r = researchBy.get(f.ticker);
      const turnover20d =
        f.volume30dAvg != null && f.closePrice != null
          ? f.volume30dAvg * f.closePrice
          : null;
      const ffTurnover =
        f.volume30dAvg != null && f.freeFloat != null && f.freeFloat > 0
          ? (f.volume30dAvg / f.freeFloat) * 100
          : null;
      return [
        // Valuation block
        {
          text: f.peRatio != null ? fmtX(f.peRatio, 1) : "—",
          rank: f.peRatio != null && f.peRatio > 0 ? 1 / f.peRatio : null,
        },
        { text: f.dividendYield != null ? fmtPct(f.dividendYield, 1, false) : "—", rank: f.dividendYield ?? null },
        { text: r?.intrinsicValuePkr != null ? fmtPrice(r.intrinsicValuePkr) : "—", rank: null },
        {
          text: r?.valuationDiscountPct != null ? fmtPct(r.valuationDiscountPct, 1) : "—",
          rank: r?.valuationDiscountPct ?? null,
        },
        // Balance-sheet risk block (KIBOR +300bps EPS impact only — real data)
        {
          text: k?.epsExpansion300bpsPct != null ? fmtPct(k.epsExpansion300bpsPct, 1) : "—",
          rank: k?.epsExpansion300bpsPct ?? null,
        },
        { text: r?.balanceSheetRiskFlag ?? "—", rank: null },
        // Liquidity & flow block
        { text: f.marketCapPkr != null ? fmtPkrB(f.marketCapPkr) : "—", rank: f.marketCapPkr ?? null },
        { text: turnover20d != null ? fmtPkrB(turnover20d) : "—", rank: turnover20d },
        { text: ffTurnover != null ? `${ffTurnover.toFixed(2)}%` : "—", rank: ffTurnover },
      ];
    };

    return rows.map((f) => ({ ticker: f.ticker, sector: f.sectorName, cells: cellsFor(f) }));
  }, [picked, universe, kibor, research]);

  if (universe.length === 0) {
    return (
      <DeskFrame title="Head-to-Head Comparison Desk">
        <IdleState
          tone="warn"
          headline="[COMPARISON DESK: AWAITING FUNDAMENTALS SNAPSHOT]"
          detail="psx_fundamentals has no rows yet — run the research pipeline pass to enable side-by-side screens."
        />
      </DeskFrame>
    );
  }

  const metricRows: { label: string; group: string; idx: number }[] = [
    { label: "TTM P/E", group: "VALUATION", idx: 0 },
    { label: "Dividend Yield %", group: "VALUATION", idx: 1 },
    { label: "Intrinsic Floor (PSX-MF)", group: "VALUATION", idx: 2 },
    { label: "Valuation Spread", group: "VALUATION", idx: 3 },
    { label: "KIBOR +300bps EPS Impact", group: "RISK", idx: 4 },
    { label: "Balance-Sheet Flag", group: "RISK", idx: 5 },
    { label: "Market Cap", group: "LIQUIDITY & FLOW", idx: 6 },
    { label: "20D Avg Turnover", group: "LIQUIDITY & FLOW", idx: 7 },
    { label: "Free-Float Daily Turnover", group: "LIQUIDITY & FLOW", idx: 8 },
  ];

  return (
    <DeskFrame
      title="Head-to-Head Comparison Desk"
      right={
        <span className="font-mono text-[10px] uppercase tracking-wider text-ghost">
          PICK 2-3 · {picked.length}/3
        </span>
      }
      footer={
        <p className="font-mono text-[10px] leading-relaxed text-ghost">
          Green = quantitatively superior on the row (higher yield/turnover/
          EPS-impact/spread, lower P/E). P/B, EV/EBITDA, D/E and interest
          coverage render when a fundamentals feed publishes them — the desk
          never estimates balance-sheet items. Intrinsic floor and valuation
          spread come from psx_equity_research (PSX-MF model).
        </p>
      }
    >
      {/* Picker */}
      <div className="border-b border-hairline px-2.5 py-1.5">
        <input
          type="text"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="ADD SYMBOL / SECTOR…"
          aria-label="Add comparison ticker"
          className="h-7 w-full max-w-xs rounded-[2px] border border-hairline bg-obsidian px-2 font-mono text-[11px] uppercase tracking-wider text-ink placeholder:text-ghost focus:border-info/50 focus:outline-none"
        />
        <div className="mt-1.5 flex flex-wrap gap-1">
          {matches.map((f) => (
            <button
              key={f.ticker}
              onClick={() => toggle(f.ticker)}
              className={`rounded-[2px] px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider ring-1 ${
                picked.includes(f.ticker)
                  ? "bg-info/10 text-info ring-info/30"
                  : "bg-panel text-muted ring-hairline hover:text-ink"
              }`}
            >
              {f.ticker}
            </button>
          ))}
          {picked.length > 0 && (
            <button
              onClick={() => setPicked([])}
              className="rounded-[2px] px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-bear hover:underline"
            >
              CLEAR
            </button>
          )}
        </div>
      </div>

      {picked.length < 2 ? (
        <IdleState
          headline="SELECT AT LEAST TWO SYMBOLS"
          detail="Side-by-side metrics appear instantly — valuation, rate sensitivity and liquidity blocks."
        />
      ) : (
        <DataTable
          minWidth={560}
          columns={[
            { label: "Metric", width: "26%" },
            ...columns.map((c) => ({ label: c.ticker, align: "right" as const })),
          ]}
        >
          {metricRows.map((m) => (
            <Row key={m.label}>
              <td className="px-2.5 py-1">
                <span className="font-mono text-[10px] uppercase tracking-wider text-muted">
                  {m.group === "" ? m.label : m.label}
                </span>
              </td>
              {columns.map((c, i) => (
                <td
                  key={c.ticker}
                  className={`px-2 py-1 text-right font-mono text-[11px] tabular-nums ${cellCls(c.cells, m.idx)}`}
                >
                  {c.cells[m.idx]?.text ?? "—"}
                </td>
              ))}
            </Row>
          ))}
          <Row>
            <td className="px-2.5 py-1 font-mono text-[10px] uppercase tracking-wider text-muted">
              Sector
            </td>
            {columns.map((c) => (
              <td key={c.ticker} className="px-2 py-1 text-right">
                <Badge tone="neutral">{(c.sector ?? "—").toUpperCase()}</Badge>
              </td>
            ))}
          </Row>
        </DataTable>
      )}
    </DeskFrame>
  );
}
