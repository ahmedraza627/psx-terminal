import React from "react";

interface BuyCardProps {
  rank: number;
  ticker: string;
  entry: string;
  stop: string;
  target: string;
  rr: string;
  notes: string;
}

export function BuyCard({ rank, ticker, entry, stop, target, rr, notes }: BuyCardProps) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm hover:border-blue-300 transition-all">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-xs font-bold text-slate-400">#{rank}</span>
          <span className="text-sm font-extrabold text-slate-900">{ticker}</span>
        </div>
        <span className="px-2 py-0.5 text-[10px] font-bold bg-emerald-50 text-emerald-700 border border-emerald-200 rounded">
          ACCUMULATION
        </span>
      </div>
      <p className="text-xs text-slate-600 mt-2 font-medium">{notes}</p>
      <div className="grid grid-cols-4 gap-2 mt-3 pt-3 border-t border-slate-100 font-mono text-[10px]">
        <div>
          <span className="text-slate-400 block text-[9px]">ENTRY REF</span>
          <span className="font-bold text-slate-900">{entry}</span>
        </div>
        <div>
          <span className="text-slate-400 block text-[9px]">INVALIDATION</span>
          <span className="font-bold text-rose-600">{stop}</span>
        </div>
        <div>
          <span className="text-slate-400 block text-[9px]">TARGET</span>
          <span className="font-bold text-emerald-600">{target}</span>
        </div>
        <div>
          <span className="text-slate-400 block text-[9px]">REWARD:RISK</span>
          <span className="font-bold text-slate-800">{rr}</span>
        </div>
      </div>
    </div>
  );
}

interface AvoidCardProps {
  rank: number;
  ticker: string;
  price: string;
  avoidRef: string;
  downside: string;
  invalidation: string;
  tag: string;
  notes: string;
}

export function AvoidCard({ rank, ticker, avoidRef, downside, price, invalidation, tag, notes }: AvoidCardProps) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm hover:border-rose-300 transition-all">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-xs font-bold text-slate-400">#{rank}</span>
          <span className="text-sm font-extrabold text-slate-900">{ticker}</span>
        </div>
        <span className="px-2 py-0.5 text-[10px] font-bold bg-rose-50 text-rose-700 border border-rose-200 rounded">
          {tag}
        </span>
      </div>
      <p className="text-xs text-slate-700 mt-2 font-semibold">{notes}</p>
      <div className="grid grid-cols-4 gap-2 mt-3 pt-3 border-t border-slate-100 font-mono text-[10px]">
        <div>
          <span className="text-slate-400 block text-[9px]">AVOID REF</span>
          <span className="font-bold text-slate-900">{avoidRef}</span>
        </div>
        <div>
          <span className="text-slate-400 block text-[9px]">DOWNSIDE</span>
          <span className="font-bold text-rose-600">{downside}</span>
        </div>
        <div>
          <span className="text-slate-400 block text-[9px]">LATEST CLOSE</span>
          <span className="font-bold text-slate-900">{price}</span>
        </div>
        <div>
          <span className="text-slate-400 block text-[9px]">INVALIDATION</span>
          <span className="font-bold text-amber-600">{invalidation}</span>
        </div>
      </div>
    </div>
  );
}