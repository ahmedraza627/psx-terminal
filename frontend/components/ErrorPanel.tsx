"use client";

export default function ErrorPanel({ message }: { message: string }) {
  return (
    <div
      role="alert"
      className="border-b border-rose-900/40 bg-rose-950/20 px-3 py-6 text-center"
    >
      <p className="font-mono text-xs uppercase tracking-widest text-bear">
        FEED ERROR
      </p>
      <p className="mx-auto mt-2 max-w-md font-mono text-[11px] text-bear/80">
        {message}
      </p>
      <p className="mt-2 text-[11px] text-ghost">
        Verify Supabase env vars and that the pipeline has run at least once.
      </p>
    </div>
  );
}
