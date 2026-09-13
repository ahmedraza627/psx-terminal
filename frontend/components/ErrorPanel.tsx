"use client";

export default function ErrorPanel({ message }: { message: string }) {
  return (
    <div
      role="alert"
      className="border-b border-rose-900/40 bg-rose-950/20 px-3 py-6 text-center"
    >
      <p className="font-mono text-xs uppercase tracking-widest text-rose-400">
        FEED ERROR
      </p>
      <p className="mx-auto mt-2 max-w-md font-mono text-[11px] text-rose-300/80">
        {message}
      </p>
      <p className="mt-2 text-[11px] text-zinc-600">
        Verify Supabase env vars and that the pipeline has run at least once.
      </p>
    </div>
  );
}
