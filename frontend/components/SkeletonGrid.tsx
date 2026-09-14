"use client";

export default function SkeletonGrid({
  rows = 8,
  cols = 6,
  label = "LOADING BLOTTER…",
}: {
  rows?: number;
  cols?: number;
  label?: string;
}) {
  return (
    <div aria-busy="true" aria-live="polite">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[600px] border-collapse text-xs">
          <thead>
            <tr className="border-b border-hairline bg-panel">
              {Array.from({ length: cols }).map((_, i) => (
                <th key={i} className="px-3 py-2 text-left">
                  <span className="block h-2 w-16 animate-pulse rounded-[2px] bg-panel" />
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {Array.from({ length: rows }).map((_, r) => (
              <tr key={r} className="border-b border-hairline">
                {Array.from({ length: cols }).map((_, c) => (
                  <td
                    key={c}
                    className={`px-3 py-1.5 ${c === 0 ? "" : "text-right"}`}
                  >
                    <span
                      className="block h-3 animate-pulse rounded-[2px] bg-panel/70"
                      style={{
                        width: c === 0 ? `${44 + ((r * 13) % 20)}px` : `${52 + ((r * 7 + c * 11) % 24)}px`,
                        animationDelay: `${(r * cols + c) * 40}ms`,
                      }}
                    />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="px-3 pt-2 font-mono text-[10px] uppercase tracking-widest text-ghost">
        {label}
      </p>
    </div>
  );
}
