"use client";

/**
 * Shared institutional status pill for optional desks whose data feed failed
 * for a non-schema reason (network / auth / 4xx-5xx). Rendered inside the
 * desk's empty state so one dead table never takes down the terminal.
 */
export default function FeedErrorPill() {
  return (
    <p className="font-mono text-xs uppercase tracking-widest text-rose-400">
      [FEED UNREACHABLE: CHECK SUPABASE CONNECTION]
    </p>
  );
}
