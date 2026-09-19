"use client";

import { useEffect, useRef, useState, useTransition } from "react";
import { addWatchlistTicker } from "@/app/actions/watchlist";

/**
 * The watchlist ADD form as a client island.
 *
 * React 18.3.1 exports neither useActionState (React 19) nor useFormState
 * (canary) in this pinned stack - verified at runtime - so this implements
 * the exact same contract with useTransition:
 *
 *   - the server action's result state renders below the input
 *     (red error line for RLS/duplicate/unauthorized/DB failures),
 *   - the input clears automatically on SUCCESS,
 *   - failures keep the typed value so the operator can correct it.
 *
 * Without JS the form degrades to a no-op GET on itself - the no-JS add
 * path was removed deliberately: silent failure is the bug being fixed,
 * and an unfeedback'd no-JS submit is silent failure by definition.
 */
export default function WatchlistAddForm() {
  const [isPending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  // Focus the field after a failed attempt so the operator can fix it fast.
  useEffect(() => {
    if (error != null) inputRef.current?.focus();
  }, [error]);

  function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const symbol = input.trim();
    if (symbol === "" || isPending) return;

    setError(null);
    startTransition(async () => {
      const result = await addWatchlistTicker(symbol);
      if (result.ok) {
        setInput(""); // auto-clear on success only
      } else {
        setError(result.message ?? "Unknown error");
      }
    });
  }

  return (
    <form onSubmit={onSubmit} className="flex items-start gap-2">
      <div className="min-w-0">
        <input
          ref={inputRef}
          type="text"
          name="ticker"
          value={input}
          onChange={(e) => {
            setInput(e.target.value);
            if (error != null) setError(null); // clear error as they retype
          }}
          required
          maxLength={20}
          placeholder="ADD TICKER (E.G. OGDC)"
          className="w-52 border border-hairline bg-obsidian px-2 py-1 font-mono text-[11px] uppercase tracking-wider text-ink outline-none placeholder:text-ghost/60 focus:border-info"
        />
        {/* Explicit failure surface - never silent again. */}
        {error != null && (
          <p
            role="alert"
            className="pt-1 font-mono text-[10px] uppercase tracking-wider text-bear"
          >
            ▲ {error}
          </p>
        )}
      </div>
      <button
        type="submit"
        disabled={isPending}
        className="border border-info/40 bg-info/10 px-2 py-1 font-mono text-[10px] font-bold uppercase tracking-widest text-info hover:bg-info/20 disabled:cursor-wait disabled:opacity-50"
      >
        {isPending ? "···" : "Add"}
      </button>
    </form>
  );
}
