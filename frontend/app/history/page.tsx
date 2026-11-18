"use client";

import { useEffect, useMemo, useState } from "react";

type LedgerEntry = {
  date: string;
  ticker: string;
  call: "BUY" | "AVOID";
  label: string;
  entry: number | null;
  stop: number | null;
  target: number | null;
  latestClose: number | null;
  pnlPct: number;
  status: string;
  notes: string;
};

type HistoryFile = { sessionDate?: string; entries?: LedgerEntry[] };

const money = (value: number | null) =>
  value === null || value === undefined ? "–" : value.toFixed(2);

const statusTone = (status: string) => {
  if (status === "TARGET HIT" || status === "AVOID WORKED") {
    return "border-emerald-300 bg-emerald-50 text-emerald-700";
  }
  if (status === "STOPPED OUT" || status === "AVOID FAILED") {
    return "border-rose-300 bg-rose-50 text-rose-700";
  }
  return "border-slate-200 bg-slate-50 text-slate-600";
};

function Card({ label, value, hint, tone }: { label: string; value: string; hint: string; tone: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-3 shadow-sm sm:p-4">
      <span className="block text-[10px] font-semibold uppercase tracking-wider text-slate-400">{label}</span>
      <span className={`mt-1 block font-mono text-xl font-black sm:text-2xl ${tone}`}>{value}</span>
      <span className="mt-0.5 block text-[10px] text-slate-500">{hint}</span>
    </div>
  );
}

export default function HistoryPage() {
  const [entries, setEntries] = useState<LedgerEntry[]>([]);
  const [sessionDate, setSessionDate] = useState<string>("");
  const [filter, setFilter] = useState<"ALL" | "BUY" | "AVOID">("ALL");
  const [query, setQuery] = useState("");
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    fetch("/data/history.json")
      .then((res) => res.json())
      .then((data: HistoryFile | LedgerEntry[]) => {
        if (Array.isArray(data)) {
          setEntries(data);
        } else {
          setEntries(data.entries ?? []);
          setSessionDate(data.sessionDate ?? "");
        }
      })
      .catch((err) => console.error("Error loading history:", err))
      .finally(() => setLoaded(true));
  }, []);

  const buys = entries.filter((entry) => entry.call === "BUY");
  const avoids = entries.filter((entry) => entry.call === "AVOID");
  const resolvedBuys = buys.filter(
    (entry) => entry.status === "TARGET HIT" || entry.status === "STOPPED OUT",
  );
  const winners = resolvedBuys.filter((entry) => entry.status === "TARGET HIT").length;
  const hitRate = resolvedBuys.length ? ((winners / resolvedBuys.length) * 100).toFixed(1) : "–";
  const avoidsWorked = avoids.filter((entry) => entry.status === "AVOID WORKED").length;
  const avoidRate = avoids.length ? ((avoidsWorked / avoids.length) * 100).toFixed(0) : "–";
  const closed = entries.filter((entry) => entry.status !== "IN PLAY");
  const avgPnl = closed.length
    ? (closed.reduce((sum, entry) => sum + entry.pnlPct, 0) / closed.length).toFixed(2)
    : "–";

  const rows = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return entries.filter((entry) => {
      if (filter !== "ALL" && entry.call !== filter) return false;
      if (!needle) return true;
      return [entry.ticker, entry.date, entry.status, entry.label, entry.notes].some((field) =>
        (field ?? "").toLowerCase().includes(needle),
      );
    });
  }, [entries, filter, query]);

  const isFiltered = filter !== "ALL" || query.trim().length > 0;

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div className="min-w-0">
          <h1 className="text-xl font-bold tracking-tight text-slate-900">Historical Performance</h1>
          <p className="text-xs text-slate-500">
            Every buy and avoid the desk issued, marked against the latest closing tape.
            {sessionDate ? ` Audited through ${sessionDate}.` : ""}
          </p>
        </div>
        <div className="flex items-center gap-1.5">
          {(["ALL", "BUY", "AVOID"] as const).map((tab) => (
            <button
              key={tab}
              type="button"
              onClick={() => setFilter(tab)}
              aria-pressed={filter === tab}
              className={`flex-1 rounded-md border px-3 py-1.5 text-xs font-semibold transition-colors sm:flex-none ${
                filter === tab
                  ? "border-slate-900 bg-slate-900 text-white"
                  : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
              }`}
            >
              {tab}
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:gap-4 md:grid-cols-4">
        <Card
          label="Signals Logged"
          value={String(entries.length)}
          hint="Auto-appended each session"
          tone="text-slate-900"
        />
        <Card
          label="Buy Hit Rate"
          value={hitRate === "–" ? "–" : `${hitRate}%`}
          hint={`${winners}W / ${resolvedBuys.length - winners}L resolved`}
          tone="text-emerald-600"
        />
        <Card
          label="Avoid Success"
          value={avoidRate === "–" ? "–" : `${avoidRate}%`}
          hint={`${avoidsWorked} of ${avoids.length} traps worked`}
          tone="text-amber-600"
        />
        <Card
          label="Avg P&L (closed)"
          value={avgPnl === "–" ? "–" : `${avgPnl}%`}
          hint="Live against entry reference"
          tone="text-blue-600"
        />
      </div>

      <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
        {/* Search + result count */}
        <div className="flex flex-col gap-2 border-b border-slate-200 p-3 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
          <div className="relative w-full sm:max-w-xs">
            <span className="pointer-events-none absolute inset-y-0 left-3 flex items-center text-slate-400">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
                <circle cx="11" cy="11" r="7" />
                <path d="M20 20l-3.5-3.5" />
              </svg>
            </span>
            <input
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search ticker, date, status…"
              aria-label="Search the audit ledger"
              className="w-full rounded-lg border border-slate-200 bg-white py-2 pl-9 pr-3 font-sans text-xs text-slate-900 placeholder:text-slate-400 focus:border-slate-400 focus:outline-none focus:ring-1 focus:ring-slate-300"
            />
          </div>
          <div className="flex items-center gap-2 text-[11px] text-slate-500">
            <span className="font-mono font-semibold text-slate-700">
              {rows.length} {rows.length === 1 ? "row" : "rows"}
            </span>
            {isFiltered && (
              <button
                type="button"
                onClick={() => {
                  setQuery("");
                  setFilter("ALL");
                }}
                className="rounded border border-slate-200 px-2 py-0.5 font-semibold text-slate-600 transition-colors hover:bg-slate-50"
              >
                Reset
              </button>
            )}
          </div>
        </div>

        {/* Horizontal scroll on small screens, full table on desktop */}
        <div className="overflow-x-auto overscroll-x-contain [-webkit-overflow-scrolling:touch]">
          <table className="w-full min-w-[880px] text-left font-mono text-xs">
            <thead className="border-b border-slate-200 bg-slate-50 text-[10px] uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-3 py-3 sm:px-4">Date</th>
                <th className="px-3 py-3 sm:px-4">Ticker</th>
                <th className="px-3 py-3 sm:px-4">Call</th>
                <th className="px-3 py-3 text-right sm:px-4">Entry</th>
                <th className="px-3 py-3 text-right sm:px-4">Stop</th>
                <th className="px-3 py-3 text-right sm:px-4">Target</th>
                <th className="px-3 py-3 text-right sm:px-4">Live Close</th>
                <th className="px-3 py-3 text-right sm:px-4">P&L</th>
                <th className="px-3 py-3 text-center sm:px-4">Status</th>
                <th className="px-3 py-3 font-sans sm:px-4">Basis</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {rows.map((entry, index) => (
                <tr key={`${entry.date}-${entry.ticker}-${entry.call}-${index}`} className="hover:bg-slate-50">
                  <td className="whitespace-nowrap px-3 py-3 text-[11px] text-slate-500 sm:px-4">{entry.date}</td>
                  <td className="whitespace-nowrap px-3 py-3 text-sm font-bold text-slate-900 sm:px-4">{entry.ticker}</td>
                  <td className="whitespace-nowrap px-3 py-3 sm:px-4">
                    <span
                      className={`rounded border px-2 py-0.5 text-[10px] font-bold ${
                        entry.call === "BUY"
                          ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                          : "border-rose-200 bg-rose-50 text-rose-700"
                      }`}
                    >
                      {entry.call}
                    </span>
                  </td>
                  <td className="whitespace-nowrap px-3 py-3 text-right font-semibold text-slate-700 sm:px-4">
                    {money(entry.entry)}
                  </td>
                  <td className="whitespace-nowrap px-3 py-3 text-right font-semibold text-rose-600 sm:px-4">
                    {money(entry.stop)}
                  </td>
                  <td className="whitespace-nowrap px-3 py-3 text-right font-semibold text-emerald-600 sm:px-4">
                    {money(entry.target)}
                  </td>
                  <td className="whitespace-nowrap px-3 py-3 text-right font-bold text-slate-900 sm:px-4">
                    {money(entry.latestClose)}
                  </td>
                  <td
                    className={`whitespace-nowrap px-3 py-3 text-right font-bold sm:px-4 ${
                      entry.pnlPct >= 0 ? "text-emerald-600" : "text-rose-600"
                    }`}
                  >
                    {entry.pnlPct >= 0 ? "+" : ""}
                    {entry.pnlPct.toFixed(1)}%
                  </td>
                  <td className="whitespace-nowrap px-3 py-3 text-center sm:px-4">
                    <span
                      className={`inline-block rounded-full border px-2.5 py-1 text-[10px] font-bold ${statusTone(entry.status)}`}
                    >
                      {entry.status}
                    </span>
                  </td>
                  <td
                    className="max-w-xs truncate px-3 py-3 font-sans text-[11px] text-slate-500 sm:px-4"
                    title={entry.notes}
                  >
                    {entry.notes}
                  </td>
                </tr>
              ))}
              {loaded && rows.length === 0 && (
                <tr>
                  <td colSpan={10} className="px-4 py-8 text-center font-sans text-xs text-slate-400">
                    {isFiltered
                      ? "No calls match this filter — clear the search to see the full ledger."
                      : "No audited signals yet — the ledger fills each time the close is processed."}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <p className="border-t border-slate-200 px-3 py-2 text-center text-[10px] text-slate-400 lg:hidden">
          Swipe the table sideways to see every column.
        </p>
      </div>
    </div>
  );
}
