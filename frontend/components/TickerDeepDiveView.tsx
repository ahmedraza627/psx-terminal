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
    ? "text-slate-700"
    : v > 0
      ? "text-emerald-700"
      : v < 0
        ? "text-rose-700"
        : "text-slate-700";
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
      <p className="font-sans text-[10px] tracking-widest text-slate-700">
        No NCCPL flow sessions in the 30-day window
      </p>
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse">
        <thead>
          <tr className="border-b border-hairline">
            <th className="border-b border-hairline px-2 py-1 text-left font-sans text-[9px] font-semibold tracking-[0.15em] text-slate-700">
              Session
            </th>
            <th className="border-b border-hairline px-2 py-1 text-right font-sans text-[9px] font-semibold tracking-[0.15em] text-slate-700">
              FIPI Net
            </th>
            <th className="border-b border-hairline px-2 py-1 text-right font-sans text-[9px] font-semibold tracking-[0.15em] text-slate-700">
              Mutual Funds Net
            </th>
          </tr>
        </thead>
        <tbody>
          {data.points.map((p) => (
            <tr key={p.tradeDate} className="border-b border-hairline/60">
              <td className="px-2 py-1 font-sans text-[10px] tabular-nums text-slate-700">
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
        <span className="font-sans text-[9px] tracking-[0.2em] text-slate-700">
          Deep-dive · {data.sessions.length} certified sessions ·{" "}
          {data.sessions[data.sessions.length - 1]} →{" "}
          {data.sessions[0]}
        </span>
        {data.closeIdx != null && (
          <span className="rounded-[2px] border border-info/40 px-1.5 py-px font-sans text-[9px] tracking-widest text-blue-700">
            On today&apos;s tape
          </span>
        )}
        {!data.known && (
          <span className="font-sans text-[9px] tracking-widest text-amber-700">
            No certified EOD bars - symbol unverified
          </span>
        )}
      </div>

      {/* A) 30-session price/volume bars */}
      <section>
        <h3 className="pb-1 font-sans text-[10px] font-bold tracking-[0.18em] text-slate-700">
          Close &amp; Volume - last {data.bars.length} certified sessions
        </h3>
        {data.bars.length === 0 ? (
          <p className="font-sans text-[10px] tracking-widest text-slate-700">
            No EOD bars stored for this symbol
          </p>
        ) : (
          <div className="space-y-px">
            {data.bars.map((b) => (
              <div
                key={b.tradeDate}
                className="flex items-center gap-2 font-sans text-[10px] tabular-nums"
              >
                <span className="w-20 shrink-0 text-slate-700">{b.tradeDate}</span>
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
                <span className="w-20 shrink-0 text-right text-slate-700">
                  {fmtInt(b.volume)}
                </span>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* B) Flow history - attribution labeled exactly as stored */}
      <section>
        <h3 className="pb-1 font-sans text-[10px] font-bold tracking-[0.18em] text-slate-700">
          FIPI / Mutual Funds Net -{" "}
          {data.flow.kind === "SECTOR" && data.flow.sectorName != null
            ? `SECTOR: ${data.flow.sectorName}`
            : "Market-wide (no per-ticker flow published)"}
        </h3>
        <FlowHistory data={data.flow} />
      </section>

      {/* C) Insider disclosures */}
      <section>
        <h3 className="pb-1 font-sans text-[10px] font-bold tracking-[0.18em] text-slate-700">
          Insider Disclosures - last {data.sessions.length} sessions
        </h3>
        {data.insider.length === 0 ? (
          <p className="font-sans text-[10px] tracking-widest text-slate-700">
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
                        className={`border-b border-hairline px-2 py-1 font-sans text-[9px] font-semibold tracking-[0.15em] text-slate-700 ${i <= 2 ? "text-left" : "text-right"}`}
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
                    <td className="px-2 py-1 font-sans text-[10px] tabular-nums text-slate-700">
                      {r.tradeDate}
                    </td>
                    <td className="px-2 py-1 font-sans text-[10px] text-ink">
                      {r.insiderName}
                    </td>
                    <td className="px-2 py-1 font-sans text-[10px] text-slate-700">
                      {r.designation}
                    </td>
                    <td
                      className={`px-2 py-1 text-right font-sans text-[10px] font-bold ${r.tradeType.toUpperCase() === "BUY" ? "text-emerald-700" : "text-rose-700"}`}
                    >
                      {r.tradeType}
                    </td>
                    <td className="px-2 py-1 text-right font-sans text-[10px] tabular-nums text-ink">
                      {fmtInt(r.quantity)}
                    </td>
                    <td className="px-2 py-1 text-right font-sans text-[10px] tabular-nums text-slate-700">
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
