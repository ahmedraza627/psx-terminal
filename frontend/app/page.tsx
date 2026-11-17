"use client";

import React, { useEffect, useState } from "react";
import {
  fetchV2LiveDeskData,
  V2BacktestSummary,
  V2TradeSignal,
} from "../lib/v2QuantClient";

interface SweepItem {
  ticker: string;
  close: number;
  poc: number;
  volZScore: number;
  mansfieldRs: number;
  stopLoss: number;
  target: number;
  directorFootprint?: boolean;
  reason?: string;
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
  stopLoss?: number;
  target?: number;
  reason?: string;
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
  const [v2Signals, setV2Signals] = useState<V2TradeSignal[]>([]);
  const [backtest, setBacktest] = useState<V2BacktestSummary | null>(null);
  const [apiOnline, setApiOnline] = useState<boolean>(false);

  useEffect(() => {
    Promise.all([
      fetch("/data/latest.json", { cache: "no-store" })
        .then((r) => r.json())
        .catch(() => null),
      fetchV2LiveDeskData(),
    ]).then(([staticJson, v2]) => {
      if (staticJson) setData(staticJson);
      setV2Signals(v2.signals);
      setBacktest(v2.backtest);
      setApiOnline(v2.apiOnline);
    });
  }, []);

  if (!data) {
    return (
      <div className="p-8 text-center font-mono text-xs text-slate-500">
        Loading Institutional Market Desk...
      </div>
    );
  }

  // Merge live FastAPI v2 BUY signals with static fallback sweeps
  const v2Buys: SweepItem[] = v2Signals
    .filter((s) => s.side === "BUY")
    .map((s) => ({
      ticker: s.ticker,
      close: s.entry_price,
      poc: s.entry_price,
      volZScore: +(s.confidence_score * 2.5).toFixed(1),
      mansfieldRs: +(s.confidence_score * 10).toFixed(1),
      stopLoss: s.stop_loss,
      target: s.target_price,
      reason: s.reason,
    }));

  // Merge live FastAPI v2 SHORT bull-traps with static fallback traps
  const v2Shorts: CarryTrap[] = v2Signals
    .filter((s) => s.side === "SHORT")
    .map((s) => ({
      ticker: s.ticker,
      spotClose: s.entry_price,
      futClose: s.stop_loss,
      mansfieldRs: -(s.confidence_score * 10),
      annualizedCarryPct: +(s.confidence_score * 25).toFixed(1),
      stopLoss: s.stop_loss,
      target: s.target_price,
      reason: s.reason,
    }));

  const sweeps = v2Buys.length > 0 ? v2Buys : (data.liquiditySweeps ?? []);
  const leaders = (data.rsLeaders ?? []).filter(
    (x) => x.mansfieldRs >= 6.0 && (x.close - x.poc) / x.poc <= 0.08
  );
  const traps = v2Shorts.length > 0 ? v2Shorts : (data.carryTraps ?? []);
  const kse = data.kse100;
  const sbp = data.sbpRate ?? 11.0;

  return (
    <div className="p-3 sm:p-6 max-w-6xl mx-auto space-y-4 sm:space-y-5">
      {/* HEADER */}
      <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-sm flex flex-col md:flex-row md:items-center md:justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-base sm:text-lg font-bold text-slate-900">Daily Market Desk</h1>
            <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-emerald-50 text-emerald-700 border border-emerald-200">
              {data.sessionDate}
            </span>
            <span
              className={`px-2 py-0.5 rounded text-[10px] font-mono font-bold border ${
                apiOnline
                  ? "bg-indigo-50 text-indigo-700 border-indigo-200"
                  : "bg-slate-100 text-slate-600 border-slate-200"
              }`}
            >
              {apiOnline ? "QUANT ENGINE V2 LIVE" : "STATIC SNAPSHOT"}
            </span>
            {backtest && backtest.win_rate_pct > 0 && (
              <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-amber-50 text-amber-800 border border-amber-200">
                WIN RATE {backtest.win_rate_pct}% ({backtest.avg_pnl_pct >= 0 ? "+" : ""}
                {backtest.avg_pnl_pct}% AVG)
              </span>
            )}
          </div>
          <p className="text-xs text-slate-500 mt-0.5">
            ATR-adjusted institutional liquidity sweeps, momentum leaders, and bull-trap rejections.
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
            <span className="text-slate-500">Interest Rate: </span>
            <span className="font-bold text-slate-900">{sbp.toFixed(1)}%</span>
          </div>
        </div>
      </div>

      {/* 2-COLUMN RESPONSIVE GRID */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 sm:gap-5">
        {/* LEFT: BUY / ACCUMULATE */}
        <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-sm space-y-3">
          <div className="flex items-center justify-between border-b border-slate-100 pb-2.5">
            <div>
              <h2 className="text-xs font-mono font-bold uppercase tracking-wider text-emerald-800">
                BEST BUY OPPORTUNITIES (ACCUMULATION)
              </h2>
              <p className="text-[11px] text-slate-500">
                Institutional dip absorption &amp; strong market-leading momentum
              </p>
            </div>
            <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-emerald-100 text-emerald-800">
              {sweeps.length + leaders.length} ACTIVE
            </span>
          </div>

          {sweeps.map((s) => (
            <div key={s.ticker} className="p-3.5 rounded-lg border border-emerald-200 bg-emerald-50/40 space-y-2.5">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-bold text-slate-900">{s.ticker}</span>
                  <span className="px-1.5 py-0.5 rounded text-[10px] font-mono font-bold bg-emerald-600 text-white">
                    STRONG DIP BUY
                  </span>
                </div>
                <span className="font-mono text-xs font-bold text-emerald-700">
                  Conf +{s.mansfieldRs.toFixed(1)}%
                </span>
              </div>
              <div className="grid grid-cols-3 gap-2 text-center font-mono text-xs">
                <div className="p-2 rounded bg-white border border-slate-200">
                  <div className="text-[10px] text-slate-500">IDEAL ENTRY</div>
                  <div className="font-bold text-slate-900">PKR {s.poc.toFixed(2)}</div>
                </div>
                <div className="p-2 rounded bg-white border border-rose-200">
                  <div className="text-[10px] text-rose-600">ATR STOP</div>
                  <div className="font-bold text-rose-700">PKR {s.stopLoss.toFixed(2)}</div>
                </div>
                <div className="p-2 rounded bg-white border border-emerald-200">
                  <div className="text-[10px] text-emerald-600">ATR TARGET</div>
                  <div className="font-bold text-emerald-700">PKR {s.target.toFixed(2)}</div>
                </div>
              </div>
              <div className="text-[11px] font-mono text-slate-600">
                {s.reason ?? `Current Close: PKR ${s.close.toFixed(2)} | Volume Surge: ${s.volZScore.toFixed(1)}x`}
              </div>
            </div>
          ))}

          {leaders.length > 0 ? (
            leaders.map((l) => {
              const stop = +(l.poc * 0.93).toFixed(2);
              const target = +(l.poc * 1.12).toFixed(2);
              return (
                <div key={l.ticker} className="p-3.5 rounded-lg border border-slate-200 bg-slate-50/70 space-y-2.5">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-bold text-slate-900">{l.ticker}</span>
                      <span className="px-1.5 py-0.5 rounded text-[10px] font-mono font-bold bg-indigo-100 text-indigo-800">
                        MOMENTUM WATCH
                      </span>
                    </div>
                    <span className="font-mono text-xs font-bold text-emerald-700">
                      Mom +{l.mansfieldRs.toFixed(1)}%
                    </span>
                  </div>
                  <div className="grid grid-cols-3 gap-2 text-center font-mono text-xs">
                    <div className="p-2 rounded bg-white border border-slate-200">
                      <div className="text-[10px] text-slate-500">IDEAL ENTRY</div>
                      <div className="font-bold text-slate-900">PKR {l.poc.toFixed(2)}</div>
                    </div>
                    <div className="p-2 rounded bg-white border border-rose-200">
                      <div className="text-[10px] text-rose-600">STOP LOSS</div>
                      <div className="font-bold text-rose-700">PKR {stop.toFixed(2)}</div>
                    </div>
                    <div className="p-2 rounded bg-white border border-emerald-200">
                      <div className="text-[10px] text-emerald-600">TARGET (+12%)</div>
                      <div className="font-bold text-emerald-700">PKR {target.toFixed(2)}</div>
                    </div>
                  </div>
                </div>
              );
            })
          ) : (
            sweeps.length === 0 && (
              <div className="p-6 text-center rounded-lg border border-dashed border-slate-200 text-xs font-mono text-slate-500">
                No high-probability buy setups today — preserving cash is profitable.
              </div>
            )
          )}
        </div>

        {/* RIGHT: DO NOT BUY / REJECTION & LEVERAGE TRAPS */}
        <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-sm space-y-3">
          <div className="flex items-center justify-between border-b border-slate-100 pb-2.5">
            <div>
              <h2 className="text-xs font-mono font-bold uppercase tracking-wider text-rose-800">
                AVOID / INSTITUTIONAL REJECTION TRAPS
              </h2>
              <p className="text-[11px] text-slate-500">
                False breakouts above 15-day highs &amp; overcrowded retail longs
              </p>
            </div>
            <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-rose-100 text-rose-800">
              {traps.length} TRAPS
            </span>
          </div>

          {traps.length > 0 ? (
            traps.map((t) => (
              <div key={t.ticker} className="p-3.5 rounded-lg border border-rose-200 bg-rose-50/40 space-y-2.5">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-bold text-slate-900">{t.ticker}</span>
                    <span className="px-1.5 py-0.5 rounded text-[10px] font-mono font-bold bg-rose-600 text-white">
                      STAY AWAY / SHORT TRAP
                    </span>
                  </div>
                  <span className="font-mono text-xs font-bold text-rose-700">
                    {t.target ? `TP PKR ${t.target.toFixed(2)}` : `${t.annualizedCarryPct.toFixed(1)}% INTEREST`}
                  </span>
                </div>
                <div className="grid grid-cols-3 gap-2 text-center font-mono text-xs">
                  <div className="p-2 rounded bg-white border border-slate-200">
                    <div className="text-[10px] text-slate-500">SPOT CLOSE</div>
                    <div className="font-bold text-slate-900">PKR {t.spotClose.toFixed(2)}</div>
                  </div>
                  <div className="p-2 rounded bg-white border border-rose-200">
                    <div className="text-[10px] text-rose-600">{t.stopLoss ? "INVALIDATION" : "FUTURES"}</div>
                    <div className="font-bold text-rose-700">
                      PKR {(t.stopLoss ?? t.futClose).toFixed(2)}
                    </div>
                  </div>
                  <div className="p-2 rounded bg-white border border-emerald-200">
                    <div className="text-[10px] text-emerald-600">{t.target ? "DOWNSIDE TP" : "STRENGTH"}</div>
                    <div className="font-bold text-emerald-700">
                      {t.target ? `PKR ${t.target.toFixed(2)}` : `${t.mansfieldRs.toFixed(1)}%`}
                    </div>
                  </div>
                </div>
                <div className="text-[11px] font-mono text-rose-800">
                  {t.reason ??
                    "Retail buyers trapped above resistance while institutional flow distributes."}
                </div>
              </div>
            ))
          ) : (
            <div className="p-6 text-center rounded-lg border border-dashed border-slate-200 text-xs font-mono text-slate-500">
              No dangerous traps detected in this session.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}