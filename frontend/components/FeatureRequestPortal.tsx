"use client";

import { useEffect, useMemo, useState } from "react";
import { Badge } from "@/components/ui/primitives";

/**
 * In-app feature request & upvote portal. Requests persist in localStorage
 * (single-desk install; a Supabase table swaps in with zero component
 * changes when multi-user is enabled). Seeded engineering items document the
 * roadmap so users can upvote real bottlenecks from day one.
 */
interface RequestItem {
  id: string;
  title: string;
  detail: string;
  category: "DESK" | "DATA" | "ALPHA" | "EXECUTION" | "UX";
  votes: number;
  createdAt: string;
  seeded: boolean;
}

const LS_KEY = "psx-terminal-feature-requests-v1";

const SEEDS: Omit<RequestItem, "id" | "createdAt" | "seeded">[] = [
  {
    title: "Live intraday feed (sub-minute polling)",
    detail:
      "Current terminal is EOD-bound by the pipeline cadence. Intraday NDM/flow polling would enable reaction desks.",
    category: "DATA",
    votes: 9,
  },
  {
    title: "Broker-code level flow attribution feed",
    detail:
      "PSX publishes broker-wise clearing data on paid feeds only — wiring it would unlock cluster accumulation detection.",
    category: "DATA",
    votes: 7,
  },
  {
    title: "Walk-forward automation for new alpha engines",
    detail:
      "Every new engine should auto-enter the 30-session edge evaluation instead of manual reseeding.",
    category: "ALPHA",
    votes: 5,
  },
];

function loadItems(): RequestItem[] {
  const seeds: RequestItem[] = SEEDS.map((s, i) => ({
    ...s,
    id: `seed-${i}`,
    createdAt: "2026-09-01",
    seeded: true,
  }));
  try {
    const raw = window.localStorage.getItem(LS_KEY);
    if (raw) {
      const userItems = JSON.parse(raw) as RequestItem[];
      return [...userItems, ...seeds];
    }
  } catch {
    /* fall through to seeds */
  }
  return seeds;
}

function persistUserItems(items: RequestItem[]) {
  try {
    window.localStorage.setItem(
      LS_KEY,
      JSON.stringify(items.filter((i) => !i.seeded))
    );
  } catch {
    /* storage unavailable — session-local */
  }
}

export default function FeatureRequestPortal({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const [items, setItems] = useState<RequestItem[]>([]);
  const [title, setTitle] = useState("");
  const [detail, setDetail] = useState("");
  const [category, setCategory] = useState<RequestItem["category"]>("DESK");
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    if (open) {
      setItems(loadItems());
      setHydrated(true);
    }
  }, [open]);

  const sorted = useMemo(
    () => items.slice().sort((a, b) => b.votes - a.votes),
    [items]
  );

  if (!open) return null;

  const submit = () => {
    if (!title.trim()) return;
    const item: RequestItem = {
      id: `req-${Date.now()}`,
      title: title.trim(),
      detail: detail.trim(),
      category,
      votes: 1,
      createdAt: new Date().toISOString().slice(0, 10),
      seeded: false,
    };
    const next = [item, ...items];
    setItems(next);
    persistUserItems(next);
    setTitle("");
    setDetail("");
  };

  const upvote = (id: string) => {
    const next = items.map((i) =>
      i.id === id ? { ...i, votes: i.votes + 1 } : i
    );
    setItems(next);
    persistUserItems(next);
  };

  return (
    <div
      className="fixed inset-0 z-40 bg-obsidian/80"
      onClick={onClose}
      role="presentation"
    >
      <div
        className="mx-auto mt-10 w-[min(640px,94vw)] border border-hairline bg-panel"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-label="Feature request portal"
      >
        <div className="flex items-center justify-between border-b border-hairline px-2.5 py-1.5">
          <h2 className="font-mono text-[10px] font-medium uppercase tracking-widest text-muted">
            Engineering Portal — Request & Upvote
          </h2>
          <button
            onClick={onClose}
            className="font-mono text-[10px] text-muted hover:text-ink"
          >
            ESC
          </button>
        </div>

        {/* New request */}
        <div className="border-b border-hairline px-2.5 py-2">
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="DESK / BOTTLENECK TITLE…"
            className="h-7 w-full rounded-[2px] border border-hairline bg-obsidian px-2 font-mono text-[11px] uppercase tracking-wider text-ink placeholder:text-ghost focus:border-info/50 focus:outline-none"
            aria-label="Request title"
          />
          <textarea
            value={detail}
            onChange={(e) => setDetail(e.target.value)}
            placeholder="WORKFLOW GAP — WHAT WOULD THIS UNLOCK FOR THE DESK?"
            rows={2}
            className="mt-1.5 w-full rounded-[2px] border border-hairline bg-obsidian px-2 py-1.5 font-mono text-[11px] text-ink placeholder:text-ghost focus:border-info/50 focus:outline-none"
            aria-label="Request detail"
          />
          <div className="mt-1.5 flex items-center gap-1">
            {(["DESK", "DATA", "ALPHA", "EXECUTION", "UX"] as const).map((c) => (
              <button
                key={c}
                onClick={() => setCategory(c)}
                className={`rounded-[2px] px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider ring-1 ${
                  c === category
                    ? "bg-info/10 text-info ring-info/30"
                    : "bg-panel text-muted ring-hairline hover:text-ink"
                }`}
              >
                {c}
              </button>
            ))}
            <button
              onClick={submit}
              className="ml-auto rounded-[2px] bg-bull/10 px-2 py-0.5 font-mono text-[10px] font-semibold uppercase tracking-wider text-bull ring-1 ring-bull/30 hover:bg-bull/20"
            >
              SUBMIT REQUEST
            </button>
          </div>
        </div>

        {/* List */}
        {!hydrated ? null : (
          <ol className="max-h-80 overflow-y-auto scroll-thin">
            {sorted.map((it) => (
              <li
                key={it.id}
                className="flex items-start gap-2 border-b border-hairline px-2.5 py-1.5 hover:bg-hoverline"
              >
                <button
                  onClick={() => upvote(it.id)}
                  className="flex w-10 shrink-0 flex-col items-center rounded-[2px] py-0.5 ring-1 ring-hairline hover:ring-info/40"
                  aria-label={`Upvote ${it.title}`}
                >
                  <span className="text-[10px] leading-none text-ghost">▲</span>
                  <span className="font-mono text-[11px] tabular-nums text-info">
                    {it.votes}
                  </span>
                </button>
                <div className="min-w-0">
                  <div className="flex items-center gap-1.5">
                    <span className="font-mono text-[11px] font-semibold text-ink">
                      {it.title}
                    </span>
                    <Badge tone="neutral">{it.category}</Badge>
                    {it.seeded && <Badge tone="ghost">ROADMAP</Badge>}
                  </div>
                  {it.detail && (
                    <p className="mt-0.5 text-[11px] leading-snug text-muted">
                      {it.detail}
                    </p>
                  )}
                </div>
              </li>
            ))}
          </ol>
        )}
      </div>
    </div>
  );
}
