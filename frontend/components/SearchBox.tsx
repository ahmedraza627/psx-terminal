"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";

/**
 * Quick ticker search - the Action Desk header's only interactive control.
 * Submitting routes to the /ticker/[ticker] deep-dive. The only client JS
 * is the submit handler.
 */
export default function SearchBox() {
  const [draft, setDraft] = useState("");
  const router = useRouter();

  const submit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const t = draft.trim().toUpperCase();
    if (t.length > 0) router.push(`/ticker/${encodeURIComponent(t)}`);
  };

  return (
    <form onSubmit={submit} role="search">
      <input
        type="text"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        maxLength={20}
        placeholder="Search ticker…"
        aria-label="Quick ticker search"
        className="h-9 w-40 rounded-lg border border-slate-200 bg-white px-3 text-[13px] text-slate-900 placeholder:text-slate-500 outline-none transition-shadow focus:border-blue-500 focus:ring-2 focus:ring-blue-100 sm:w-56"
      />
    </form>
  );
}
