"use client";

import React, { useState, useEffect } from "react";

interface InsiderDisclosure {
  filingDate: string;
  ticker: string;
  category: string;
  liveClose: number;
  headline: string;
  psxUrl: string;
}

export default function InsidersPage() {
  const [filings, setFilings] = useState<InsiderDisclosure[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch("/data/insiders.json")
      .then((res) => res.json())
      .then((d) => {
        setFilings(Array.isArray(d) ? d : []);
        setLoading(false);
      })
      .catch((err) => {
        console.error("Error loading insiders data:", err);
        setLoading(false);
      });
  }, []);

  if (loading) {
    return (
      <div className="p-8 text-center text-xs text-slate-500 font-mono">
        Loading verified PSX Clause 5.6.4 disclosures...
      </div>
    );
  }

  return (
    <div className="p-4 sm:p-6 pb-20 space-y-6 max-w-7xl mx-auto w-full">
      <div className="border-b border-slate-200 pb-4 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
        <div>
          <h1 className="text-lg sm:text-xl font-bold tracking-tight text-slate-900">
            Director & Sponsor Filings (PSX Clause 5.6.4)
          </h1>
          <p className="text-xs text-slate-500">
            Verified regulatory disclosures of insider & substantial shareholder transactions pulled directly from PSX DPS.
          </p>
        </div>
        <span className="text-[10px] font-mono font-semibold text-blue-700 bg-blue-50 px-2.5 py-1 rounded border border-blue-200">
          {filings.length} VERIFIED DISCLOSURES
        </span>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white shadow-sm overflow-x-auto">
        <table className="w-full text-left border-collapse font-mono text-xs">
          <thead>
            <tr className="border-b border-slate-200 bg-slate-50/80 text-[10px] uppercase text-slate-500">
              <th className="py-3 px-4">Filing Date</th>
              <th className="py-3 px-4">Ticker</th>
              <th className="py-3 px-4">Regulatory Category</th>
              <th className="py-3 px-4 text-right">Live Close</th>
              <th className="py-3 px-4">Official PSX Announcement</th>
              <th className="py-3 px-4 text-right">Source PDF</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {filings.length === 0 ? (
              <tr>
                <td colSpan={6} className="py-8 px-4 text-center text-slate-400 font-sans">
                  No verified Clause 5.6.4 disclosures recorded yet.
                </td>
              </tr>
            ) : (
              filings.map((item, idx) => (
                <tr key={`${item.ticker}-${item.filingDate}-${idx}`} className="hover:bg-slate-50/70 transition-colors">
                  <td className="py-3.5 px-4 text-slate-500 whitespace-nowrap">{item.filingDate}</td>
                  <td className="py-3.5 px-4 font-bold text-slate-900">{item.ticker}</td>
                  <td className="py-3.5 px-4">
                    <span className="px-2 py-0.5 rounded text-[10px] font-bold border bg-blue-50 text-blue-700 border-blue-200 whitespace-nowrap">
                      {item.category}
                    </span>
                  </td>
                  <td className="py-3.5 px-4 text-right font-bold text-slate-900 whitespace-nowrap">
                    {item.liveClose > 0 ? `PKR ${item.liveClose.toFixed(2)}` : "—"}
                  </td>
                  <td className="py-3.5 px-4 font-sans text-[11px] text-slate-700">
                    {item.headline}
                  </td>
                  <td className="py-3.5 px-4 text-right whitespace-nowrap">
                    <a
                      href={item.psxUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-[11px] font-semibold text-blue-600 hover:text-blue-800 underline"
                    >
                      Verify PDF ↗
                    </a>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}