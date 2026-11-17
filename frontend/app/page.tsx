"use client";

import React, { useEffect, useState } from "react";

interface SweepItem {
  ticker: string;
  close: number;
  poc: number;
  volZScore: number;
  mansfieldRs: number;
  stopLoss: number;
  target: number;
  directorFootprint?: boolean;
}

interface RsLeader {
  ticker: string;
  close: number;
  mansfieldRs: number;
  volZScore: number;
  poc: number;
}

interface CarryTrap {
  ticker: string;
  spotClose: number;
  futClose: number;
  mansfieldRs: number;
  annualizedCarryPct: number;
}

interface LatestData {
  sessionDate: string;
  kse100?: { close: number; changePct: number };
  sbpRate?: number;
  liquiditySweeps?: SweepItem[];
  rsLeaders?: RsLeader[];
  carryTraps?: CarryTrap[];
}

export default function DashboardPage() {
  const [data, setData] = useState<LatestData | null>(null);

  useEffect(() => {
    fetch("/data/latest.json", { cache: "no-store" })
      .then((r) => r.json())
      .then(setData)
      .catch(() => {});
  }, []);

  if (!data) {
    return (
      <div className="p-8 text-center font-mono text-xs text-slate-500">
        Loading PSX Institutional session...
      </div>
    );
  }

  const sweeps = data.liquiditySweeps ?? [];
  const leaders = (data.rsLeaders ?? []).filter(
    (x) => x.mansfieldRs >= 6.0 && ((x.close - x.poc) / x.poc) <= 0.08
  );
  const traps = data.carryTraps ?? [];
  const kse = data.kse100;
  const sbp = data.sbpRate ?? 11.0;

  return (
    <div className="p-4 sm:p-6 max-w-6xl mx-auto space-y-5">
      {/* HEADER */}
      <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-sm flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-lg font-bold text-slate-900">PSX Daily Action Desk</h1>
            <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-emerald-50 text-emerald-700 border border-emerald-200">
              SESSION {data.sessionDate}
            </span>
          </div>
          <p className="text-xs text-slate-500 mt-0.5">
            Filtered by 15-Day VPVR POC, Liquidity Sweeps, Mansfield RS vs KSE-100 &amp; DFX Cost-of-Carry.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2 font-mono text-xs">
          {kse && (
            <div className="px-3 py-1.5 rounded-lg bg-slate-50 border border-slate-200">
              <span className="text-slate-500">KSE-100: </span>
              <span className="font-bold text-slate-900">{kse.close.toLocaleString()}</span>{" "}
              <span className={kse.changePct >= 0 ? "text-emerald-600 font-bold" : "text-rose-600 font-bold"}>
                ({kse.changePct >= 0 ? "+" : ""}
                {kse.changePct.toFixed(2)}%)
              </span>
            </div>
          )}
          <div className="px-3 py-1.5 rounded-lg bg-slate-50 border border-slate-200">
            <span className="text-slate-500">SBP Rate: </span>
            <span className="font-bold text-slate-900">{sbp.toFixed(1)}%</span>
          </div>
        </div>
      </div>

      {/* 2-COLUMN ACTION GRID */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {/* LEFT: BUY / ACCUMULATE */}
        <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-sm space-y-3">
          <div className="flex items-center justify-between border-b border-slate-100 pb-2.5">
            <div>
              <h2 className="text-xs font-mono font-bold uppercase tracking-wider text-emerald-800">
                BUY / ACCUMULATE SETUPS (SPOT)
              </h2>
              <p className="text-[11px] text-slate-500">
                Liquidity sweeps reclaiming 15D POC + high Mansfield RS institutional leaders
              </p>
            </div>
            <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-emerald-100 text-emerald-800">
              {sweeps.length + leaders.length} ACTIVE
            </span>
          </div>

          {sweeps.map((s) => (
            <div key={s.ticker} className="p-3.5 rounded-lg border border-emerald-200 bg-emerald-50/40 space-y-2">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-bold text-slate-900">{s.ticker}</span>
                  <span className="px-1.5 py-0.5 rounded text-[10px] font-mono font-bold bg-emerald-600 text-white">
                    LIQUIDITY SWEEP BUY
                  </span>
                  {s.directorFootprint && (
                    <span className="px-1.5 py-0.5 rounded text-[10px] font-mono font-bold bg-slate-900 text-amber-300">
                      DIRECTOR 5.6.4
                    </span>
                  )}
                </div>
                <span className="font-mono text-xs font-bold text-emerald-700">
                  RS +{s.mansfieldRs.toFixed(1)}%
                </span>
              </div>
              <div className="grid grid-cols-3 gap-2 text-center font-mono text-xs">
                <div className="p-2 rounded bg-white border border-slate-200">
                  <div className="text-[10px] text-slate-500">ENTRY / POC</div>
                  <div className="font-bold text-slate-900">PKR {s.poc.toFixed(2)}</div>
                </div>
                <div className="p-2 rounded bg-white border border-rose-200">
                  <div className="text-[10px] text-rose-600">HARD STOP</div>
                  <div className="font-bold text-rose-700">PKR {s.stopLoss.toFixed(2)}</div>
                </div>
                <div className="p-2 rounded bg-white border border-emerald-200">
                  <div className="text-[10px] text-emerald-600">TARGET (+12%)</div>
                  <div className="font-bold text-emerald-700">PKR {s.target.toFixed(2)}</div>
                </div>
              </div>
              <div className="text-[11px] font-mono text-slate-600">
                Close: PKR {s.close.toFixed(2)} • Vol Z-Score: {s.volZScore.toFixed(2)}σ
              </div>
            </div>
          ))}

          {leaders.length > 0 ? (
            leaders.map((l) => {
              const stop = +(l.poc * 0.93).toFixed(2);
              const target = +(l.poc * 1.12).toFixed(2);
              return (
                <div key={l.ticker} className="p-3.5 rounded-lg border border-slate-200 bg-slate-50/70 space-y-2">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-bold text-slate-900">{l.ticker}</span>
                      <span className="px-1.5 py-0.5 rounded text-[10px] font-mono font-bold bg-indigo-100 text-indigo-800">
                        RS ACCUMULATION WATCH
                      </span>
                    </div>
                    <span className="font-mono text-xs font-bold text-emerald-700">
                      RS +{l.mansfieldRs.toFixed(1)}%
                    </span>
                  </div>
                  <div className="grid grid-cols-3 gap-2 text-center font-mono text-xs">
                    <div className="p-2 rounded bg-white border border-slate-200">
                      <div className="text-[10px] text-slate-500">LIMIT DIP (15D POC)</div>
                      <div className="font-bold text-slate-900">PKR {l.poc.toFixed(2)}</div>
                    </div>
                    <div className="p-2 rounded bg-white border border-rose-200">
                      <div className="text-[10px] text-rose-600">MAX STOP (-7%)</div>
                      <div className="font-bold text-rose-700">PKR {stop.toFixed(2)}</div>
                    </div>
                    <div className="p-2 rounded bg-white border border-emerald-200">
                      <div className="text-[10px] text-emerald-600">SWING TARGET</div>
                      <div className="font-bold text-emerald-700">PKR {target.toFixed(2)}</div>
                    </div>
                  </div>
                  <div className="text-[11px] font-mono text-slate-500">
                    Spot Close: PKR {l.close.toFixed(2)} • Vol Z-Score: {l.volZScore.toFixed(2)}σ
                  </div>
                </div>
              );
            })
          ) : (
            sweeps.length === 0 && (
              <div className="p-6 text-center rounded-lg border border-dashed border-slate-200 text-xs font-mono text-slate-500">
                No qualified sweep or RS setups today — preserve cash.
              </div>
            )
          )}
        </div>

        {/* RIGHT: DO NOT BUY / DFX SHORT TRAPS */}
        <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-sm space-y-3">
          <div className="flex items-center justify-between border-b border-slate-100 pb-2.5">
            <div>
              <h2 className="text-xs font-mono font-bold uppercase tracking-wider text-rose-800">
                DO NOT BUY (AVOID) • DFX OVERHEATED TRAPS
              </h2>
              <p className="text-[11px] text-slate-500">
                Retail paying &gt;18% annualized carry while stock underperforms KSE-100 (RS &lt; 0)
              </p>
            </div>
            <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-rose-100 text-rose-800">
              {traps.length} TRAPS
            </span>
          </div>

          {traps.length > 0 ? (
            traps.map((t) => (
              <div key={t.ticker} className="p-3.5 rounded-lg border border-rose-200 bg-rose-50/40 space-y-2">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-bold text-slate-900">{t.ticker}</span>
                    <span className="px-1.5 py-0.5 rounded text-[10px] font-mono font-bold bg-rose-600 text-white">
                      SPOT AVOID • DFX SHORT ONLY
                    </span>
                  </div>
                  <span className="font-mono text-xs font-bold text-rose-700">
                    {t.annualizedCarryPct.toFixed(1)}% CARRY
                  </span>
                </div>
                <div className="grid grid-cols-3 gap-2 text-center font-mono text-xs">
                  <div className="p-2 rounded bg-white border border-slate-200">
                    <div className="text-[10px] text-slate-500">SPOT CLOSE</div>
                    <div className="font-bold text-slate-900">PKR {t.spotClose.toFixed(2)}</div>
                  </div>
                  <div className="p-2 rounded bg-white border border-slate-200">
                    <div className="text-[10px] text-slate-500">DFX FUTURES</div>
                    <div className="font-bold text-slate-900">PKR {t.futClose.toFixed(2)}</div>
                  </div>
                  <div className="p-2 rounded bg-white border border-rose-200">
                    <div className="text-[10px] text-rose-600">MANSFIELD RS</div>
                    <div className="font-bold text-rose-700">{t.mansfieldRs.toFixed(2)}%</div>
                  </div>
                </div>
                <div className="text-[11px] font-mono text-rose-800">
                  Spread premium +{(t.annualizedCarryPct - sbp).toFixed(1)}% above {sbp.toFixed(1)}% SBP policy rate — trapped leveraged longs.
                </div>
              </div>
            ))
          ) : (
            <div className="p-6 text-center rounded-lg border border-dashed border-slate-200 text-xs font-mono text-slate-500">
              No overheated DFX carry traps detected in this session.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
