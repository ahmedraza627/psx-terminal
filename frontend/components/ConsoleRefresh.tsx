"use client";

import { useRouter } from "next/navigation";

/** The console's only interactive element: re-run the server render. */
export default function ConsoleRefresh({ syncing }: { syncing: boolean }) {
  const router = useRouter();
  return (
    <button
      onClick={() => router.refresh()}
      className="h-7 rounded-[2px] border border-hairline bg-obsidian px-2 font-mono text-[10px] uppercase tracking-wider text-muted hover:border-info/40 hover:text-info"
    >
      {syncing ? "SYNC…" : "REFRESH"}
    </button>
  );
}
