import type { TickerDeepDiveData } from "@/lib/consoleQueries";
import { fmtInt } from "@/components/ui/format";

/**
 * TICKER DEEP-DIVE - server-rendered dossier for ONE ticker. Zero client
 * JS. Every number is a certified stored fact; empty sections say so
 * instead of inventing content.
 *
 * Attribution discipline: the flow section header states exactly what the
 * rows are (SECTOR via psx_fundamentals mapping, or MARKET-WIDE when the
 * ticker is unmapped) - NCCPL has no per-ticker flow, and this UI never
 * pretends otherwise.
 */

function flowTone(v: number | null): string {
  return v == null
    ? "text-ghost"
    : v > 0
      ? "text-bull"
      : v < 0
        ? "text-bear"
        : "text-muted";
}

function flowTxt(v: number | null): string {
  return v == null ? "—" : `${v > 0 ? "+" : ""}${(v / 1e6).toFixed(1)}M`;
}

/** Mini flow table: one row per session, FIPI and Mutual Funds columns. */
function FlowHistory({
  data,
}: {
  data: TickerDeepDiveData["flow"];
}) {
  if (data.points.length === 0) {
    return (
      <p className="font-sans text-[10px] tracking-widest text-ghost">
        No NCCPL flow sessions in the 30-day window
      </p>
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse">
        <thead>
          <tr className="border-b border-hairline">
            <th className="border-b border-hairline px-2 py-1 text-left font-sans text-[9px] font-semibold tracking-[0.15em] text-ghost">
              Session
            </th>
            <th className="border-b border-hairline px-2 py-1 text-right font-sans text-[9px] font-semibold tracking-[0.15em] text-ghost">
              FIPI Net
            </th>
            <th className="border-b border-hairline px-2 py-1 text-right font-sans text-[9px] font-semibold tracking-[0.15em] text-ghost">
              Mutual Funds Net
            </th>
          </tr>
        </thead>
        <tbody>
          {data.points.map((p) => (
            <tr key={p.tradeDate} className="border-b border-hairline/60">
              <td className="px-2 py-1 font-sans text-[10px] tabular-nums text-muted">
                {p.tradeDate}
              </td>
              <td
                className={`px-2 py-1 text-right font-sans text-[10px] tabular-nums ${flowTone(p.fipiNetPkr)}`}
              >
                {flowTxt(p.fipiNetPkr)}
              </td>
              <td
                className={`px-2 py-1 text-right font-sans text-[10px] tabular-nums ${flowTone(p.mutualFundsNetPkr)}`}
              >
                {flowTxt(p.mutualFundsNetPkr)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function TickerDeepDiveView({
  data,
}: {
  data: TickerDeepDiveData;
}) {
  const maxVol = Math.max(...data.bars.map((b) => b.volume ?? 0), 1);

  return (
    <div className="space-y-3">
      {/* Identification strip */}
      <div className="flex flex-wrap items-baseline gap-2 border-b border-hairline pb-2">
        <span className="font-sans text-[15px] font-bold tracking-[0.14em] text-ink">
          {data.ticker}
        </span>
        <span className="font-sans text-[9px] tracking-[0.2em] text-ghost">
          Deep-dive · {data.sessions.length} certified sessions ·{" "}
          {data.sessions[data.sessions.length - 1]} →{" "}
          {data.sessions[0]}
        </span>
        {data.closeIdx != null && (
          <span className="rounded-[2px] border border-info/40 px-1.5 py-px font-sans text-[9px] tracking-widest text-info">
            On today&apos;s tape
          </span>
        )}
        {!data.known && (
          <span className="font-sans text-[9px] tracking-widest text-warn">
            No certified EOD bars - symbol unverified
          </span>
        )}
      </div>

      {/* A) 30-session price/volume bars */}
      <section>
        <h3 className="pb-1 font-sans text-[10px] font-bold tracking-[0.18em] text-muted">
          Close &amp; Volume - last {data.bars.length} certified sessions
        </h3>
        {data.bars.length === 0 ? (
          <p className="font-sans text-[10px] tracking-widest text-ghost">
            No EOD bars stored for this symbol
          </p>
        ) : (
          <div className="space-y-px">
            {data.bars.map((b) => (
              <div
                key={b.tradeDate}
                className="flex items-center gap-2 font-sans text-[10px] tabular-nums"
              >
                <span className="w-20 shrink-0 text-muted">{b.tradeDate}</span>
                <span className="w-16 shrink-0 text-right text-ink">
                  {b.closePrice == null ? "—" : b.closePrice.toFixed(2)}
                </span>
                <div className="h-1.5 flex-1 bg-hairline/60">
                  <div
                    className="h-1.5 bg-info/70"
                    style={{
                      width: `${Math.max(1, ((b.volume ?? 0) / maxVol) * 100)}%`,
                    }}
                  />
                </div>
                <span className="w-20 shrink-0 text-right text-ghost">
                  {fmtInt(b.volume)}
                </span>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* B) Flow history - attribution labeled exactly as stored */}
      <section>
        <h3 className="pb-1 font-sans text-[10px] font-bold tracking-[0.18em] text-muted">
          FIPI / Mutual Funds Net -{" "}
          {data.flow.kind === "SECTOR" && data.flow.sectorName != null
            ? `SECTOR: ${data.flow.sectorName}`
            : "Market-wide (no per-ticker flow published)"}
        </h3>
        <FlowHistory data={data.flow} />
      </section>

      {/* C) Insider disclosures */}
      <section>
        <h3 className="pb-1 font-sans text-[10px] font-bold tracking-[0.18em] text-muted">
          Insider Disclosures - last {data.sessions.length} sessions
        </h3>
        {data.insider.length === 0 ? (
          <p className="font-sans text-[10px] tracking-widest text-ghost">
            No insider disclosures stored in the window
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full border-collapse">
              <thead>
                <tr>
                  {["Date", "Name", "Designation", "Type", "Qty", "Rate"].map(
                    (l, i) => (
                      <th
                        key={l}
                        className={`border-b border-hairline px-2 py-1 font-sans text-[9px] font-semibold tracking-[0.15em] text-ghost ${i <= 2 ? "text-left" : "text-right"}`}
                      >
                        {l}
                      </th>
                    ),
                  )}
                </tr>
              </thead>
              <tbody>
                {data.insider.map((r, i) => (
                  <tr key={`${r.tradeDate}-${r.insiderName}-${i}`} className="border-b border-hairline/60">
                    <td className="px-2 py-1 font-sans text-[10px] tabular-nums text-muted">
                      {r.tradeDate}
                    </td>
                    <td className="px-2 py-1 font-sans text-[10px] text-ink">
                      {r.insiderName}
                    </td>
                    <td className="px-2 py-1 font-sans text-[10px] text-muted">
                      {r.designation}
                    </td>
                    <td
                      className={`px-2 py-1 text-right font-sans text-[10px] font-bold ${r.tradeType.toUpperCase() === "BUY" ? "text-bull" : "text-bear"}`}
                    >
                      {r.tradeType}
                    </td>
                    <td className="px-2 py-1 text-right font-sans text-[10px] tabular-nums text-ink">
                      {fmtInt(r.quantity)}
                    </td>
                    <td className="px-2 py-1 text-right font-sans text-[10px] tabular-nums text-muted">
                      {r.rate == null ? "—" : r.rate.toFixed(2)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
