import TickerLink from "@/components/TickerLink";
import type {
  DislocatedTicker,
  VolumeDislocationData,
} from "@/lib/consoleQueries";

/**
 * VOLUME DISLOCATION BREAKOUTS - pure server component (zero client JS).
 *
 * Single-line factual alert: tickers that entered today's top-25 volume
 * without being in yesterday's top-25, each stamped with only the
 * certified footprints found (insider BUY disclosure in the trailing 5
 * sessions, verified >= 0%-spread NDM block on T). No scoring, no
 * signals - the machine shows the intersection, the human reads it.
 */

/** Volume in PKR-console millions, one decimal: 12.4M. */
function volM(v: number | null): string {
  return v == null ? "—" : `${(v / 1e6).toFixed(1)}M`;
}

/** Signed change %: +3.2% / -1.1% / — when no prior verdict exists. */
function chg(c: number | null): string {
  return c == null ? "—" : `${c > 0 ? "+" : ""}${c.toFixed(1)}%`;
}

function Tag({
  kind,
  text,
}: {
  kind: "gold" | "cyan";
  text: string;
}) {
  return (
    <span
      className={`rounded-[2px] px-1.5 py-px font-mono text-[9px] font-bold uppercase tracking-widest ${
        kind === "gold"
          ? "bg-[#d4a017] text-black"
          : "bg-cyan-400 text-black"
      }`}
    >
      {text}
    </span>
  );
}

function Name({ n }: { n: DislocatedTicker }) {
  return (
    <span className="whitespace-nowrap">
      <TickerLink ticker={n.ticker} className="font-bold text-ink" />
      <span className="tabular-nums text-muted">
        {` (Vol: ${volM(n.volume)} · Chg: ${chg(n.changePct)})`}
      </span>{" "}
      {n.insiderBuy && <Tag kind="gold" text="Insider Buy" />}
      {n.insiderBuy && n.ndmAccumulation && <span> </span>}
      {n.ndmAccumulation && <Tag kind="cyan" text="NDM Accumulation" />}
    </span>
  );
}

export default function VolumeDislocationStrip({
  data,
}: {
  data: VolumeDislocationData | null;
}) {
  if (data == null) {
    return (
      <p className="border border-hairline bg-panel/60 px-3 py-1.5 font-mono text-[10px] uppercase tracking-[0.18em] text-ghost">
        VOLUME DISLOCATION FEED UNAVAILABLE
      </p>
    );
  }

  if (data.names.length === 0) {
    return (
      <p className="border border-hairline bg-panel/60 px-3 py-1.5 font-mono text-[10px] uppercase tracking-[0.18em] text-ghost">
        TOP 25 VOLUME RUNNERS STABLE — NO NEW UNUSUAL DISLOCATIONS
        {data.priorDate != null && (
          <span className="ml-2 normal-case tracking-normal">
            {`(${data.sessionDate} vs ${data.priorDate})`}
          </span>
        )}
      </p>
    );
  }

  return (
    <p className="border border-hairline bg-panel/60 px-3 py-1.5 font-mono text-[10px] uppercase tracking-[0.18em]">
      <span className="font-bold text-info">
        VOLUME DISLOCATION BREAKOUTS (NEW TOP-25 INFLOWS):
      </span>{" "}
      {data.names.map((n, i) => (
        <span key={n.ticker}>
          {i > 0 && <span className="text-ghost"> · </span>}
          <Name n={n} />
        </span>
      ))}
      {data.priorDate != null && (
        <span className="ml-2 text-ghost normal-case tracking-normal">
          {`[${data.sessionDate} vs ${data.priorDate}]`}
        </span>
      )}
    </p>
  );
}
