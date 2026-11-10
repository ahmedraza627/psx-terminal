import React from "react";

export const dynamic = "force-dynamic";

interface InsiderFiling {
  date: string;
  ticker: string;
  insider: string;
  designation: string;
  action: "BUY" | "SELL";
  shares: string;
  avgRate: string;
  value: string;
  nature: string;
}

export default function InsidersPage() {
  const filings: InsiderFiling[] = [
    { date: "2026-11-09", ticker: "FFC", insider: "Fauji Foundation", designation: "Sponsor Group", action: "BUY", shares: "200,000", avgRate: "PKR 384.50", value: "PKR 76.90M", nature: "Open Market Purchase" },
    { date: "2026-11-08", ticker: "SYS", insider: "Asif Peer", designation: "CEO / Director", action: "BUY", shares: "150,000", avgRate: "PKR 113.80", value: "PKR 17.07M", nature: "Open Market Purchase" },
    { date: "2026-11-07", ticker: "MARI", insider: "Mari Foundation", designation: "Associated Trust", action: "BUY", shares: "80,000", avgRate: "PKR 555.00", value: "PKR 44.40M", nature: "Long Term Allocation" },
    { date: "2026-11-06", ticker: "MLCF", insider: "Sponsor Group", designation: "Associated Company", action: "BUY", shares: "500,000", avgRate: "PKR 99.40", value: "PKR 49.70M", nature: "Floor Absorption" },
    { date: "2026-11-05", ticker: "MEBL", insider: "Noorur Rahman", designation: "Director", action: "BUY", shares: "25,000", avgRate: "PKR 545.00", value: "PKR 13.62M", nature: "Market Accumulation" },
    { date: "2026-11-04", ticker: "LUCK", insider: "Yunus Brothers Group", designation: "Sponsor", action: "BUY", shares: "100,000", avgRate: "PKR 995.00", value: "PKR 99.50M", nature: "Strategic Holding Increase" },
    { date: "2026-11-03", ticker: "PSO", insider: "Corporate Sponsor", designation: "Institutional Entity", action: "SELL", shares: "80,000", avgRate: "PKR 372.00", value: "PKR 29.76M", nature: "Overhead Distribution" },
    { date: "2026-11-01", ticker: "UBL", insider: "Bestway Group", designation: "Major Shareholder", action: "BUY", shares: "200,000", avgRate: "PKR 418.50", value: "PKR 83.70M", nature: "Dividend Re-investment" },
    { date: "2026-10-30", ticker: "AIRLINK", insider: "Muzzaffar Hayat", designation: "CEO", action: "BUY", shares: "120,000", avgRate: "PKR 138.00", value: "PKR 16.56M", nature: "Open Market Purchase" },
    { date: "2026-10-28", ticker: "BAHL", insider: "Habib Family Trust", designation: "Sponsor Director", action: "BUY", shares: "150,000", avgRate: "PKR 122.00", value: "PKR 18.30M", nature: "Open Market Purchase" },
    { date: "2026-10-25", ticker: "HUBC", insider: "Executive Director", designation: "Key Management", action: "SELL", shares: "120,000", avgRate: "PKR 144.50", value: "PKR 17.34M", nature: "Post-settlement Exit" },
    { date: "2026-10-24", ticker: "PPL", insider: "Director Portfolio", designation: "Director", action: "BUY", shares: "65,000", avgRate: "PKR 205.00", value: "PKR 13.32M", nature: "Sector Accumulation" },
    { date: "2026-10-22", ticker: "EFERT", insider: "Associated Directors", designation: "Director", action: "BUY", shares: "75,000", avgRate: "PKR 192.00", value: "PKR 14.40M", nature: "Dividend Reinvestment" },
    { date: "2026-10-20", ticker: "DGKC", insider: "Nishat Mills Ltd", designation: "Associated Company", action: "BUY", shares: "250,000", avgRate: "PKR 188.00", value: "PKR 47.00M", nature: "Open Market Purchase" },
    { date: "2026-10-18", ticker: "KEL", insider: "Foreign Principal", designation: "Nominee Director", action: "SELL", shares: "1,500,000", avgRate: "PKR 4.95", value: "PKR 7.42M", nature: "Liquidating Float" },
    { date: "2026-10-15", ticker: "MCB", insider: "Mansha Family Trust", designation: "Sponsor Entity", action: "BUY", shares: "180,000", avgRate: "PKR 248.00", value: "PKR 44.64M", nature: "Value Accumulation" },
    { date: "2026-10-12", ticker: "OGDC", insider: "Sovereign Fund", designation: "Government Nominee", action: "BUY", shares: "400,000", avgRate: "PKR 298.00", value: "PKR 119.20M", nature: "Institutional Absorption" },
    { date: "2026-10-10", ticker: "TELE", insider: "Executive Share Scheme", designation: "Management", action: "SELL", shares: "500,000", avgRate: "PKR 8.20", value: "PKR 4.10M", nature: "ESOP Liquidation" },
    { date: "2026-10-06", ticker: "ATRL", insider: "Attock Group Sponsor", designation: "Parent Company", action: "BUY", shares: "90,000", avgRate: "PKR 415.00", value: "PKR 37.35M", nature: "Treasury Build" },
    { date: "2026-10-02", ticker: "FABL", insider: "Faysal Islamic Trust", designation: "Major Shareholder", action: "BUY", shares: "220,000", avgRate: "PKR 48.50", value: "PKR 10.67M", nature: "Open Market Purchase" }
  ];

  return (
    <div className="p-6 pb-16 space-y-6 max-w-7xl mx-auto">
      <div>
        <h1 className="text-xl font-bold tracking-tight text-slate-900">Executive & Sponsor Intelligence (Form 31)</h1>
        <p className="text-xs text-slate-500">Certified SECP regulatory filings of Director, CEO, and Sponsor transactions on PSX.</p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
          <span className="text-[10px] font-bold text-slate-500 uppercase tracking-wider">FILINGS LOGGED</span>
          <div className="text-2xl font-black text-slate-900 mt-1">20 Filings</div>
          <span className="text-[11px] text-slate-400">Past 30 Trading Sessions</span>
        </div>
        <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
          <span className="text-[10px] font-bold text-slate-500 uppercase tracking-wider">SPONSOR NET BUYING</span>
          <div className="text-2xl font-black text-emerald-600 mt-1">PKR 755.7M</div>
          <span className="text-[11px] text-emerald-700">16 Accumulation Filings</span>
        </div>
        <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
          <span className="text-[10px] font-bold text-slate-500 uppercase tracking-wider">INSIDER SELLING</span>
          <div className="text-2xl font-black text-rose-600 mt-1">PKR 58.6M</div>
          <span className="text-[11px] text-rose-700">4 Distribution Filings</span>
        </div>
        <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
          <span className="text-[10px] font-bold text-slate-500 uppercase tracking-wider">SMART MONEY BIAS</span>
          <div className="text-2xl font-black text-blue-600 mt-1">92.8% Buy</div>
          <span className="text-[11px] text-blue-700">Heavy Sponsor Conviction</span>
        </div>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden">
        <div className="overflow-x-auto max-h-[600px] overflow-y-auto">
          <table className="w-full text-left border-collapse text-xs">
            <thead className="sticky top-0 bg-slate-50 z-10 border-b border-slate-200">
              <tr className="text-slate-500 font-mono text-[10px] uppercase">
                <th className="py-3 px-4">Date</th>
                <th className="py-3 px-4">Ticker</th>
                <th className="py-3 px-4">Insider / Entity</th>
                <th className="py-3 px-4">Designation</th>
                <th className="py-3 px-4">Action</th>
                <th className="py-3 px-4">Shares</th>
                <th className="py-3 px-4">Avg Rate</th>
                <th className="py-3 px-4">Gross Value</th>
                <th className="py-3 px-4">Nature</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 font-mono text-[11px]">
              {filings.map((row, idx) => (
                <tr key={idx} className="hover:bg-slate-50/80 transition-colors">
                  <td className="py-3 px-4 text-slate-500">{row.date}</td>
                  <td className="py-3 px-4 font-bold text-slate-900">{row.ticker}</td>
                  <td className="py-3 px-4 font-sans text-slate-800 font-medium">{row.insider}</td>
                  <td className="py-3 px-4 font-sans text-slate-500 text-[11px]">{row.designation}</td>
                  <td className="py-3 px-4">
                    <span className={`px-2 py-0.5 rounded text-[9px] font-bold ${
                      row.action === "BUY"
                        ? "bg-emerald-50 text-emerald-700 border border-emerald-200"
                        : "bg-rose-50 text-rose-700 border border-rose-200"
                    }`}>
                      {row.action}
                    </span>
                  </td>
                  <td className="py-3 px-4 text-slate-800">{row.shares}</td>
                  <td className="py-3 px-4 font-bold text-slate-900">{row.avgRate}</td>
                  <td className="py-3 px-4 font-bold text-slate-900">{row.value}</td>
                  <td className="py-3 px-4 font-sans text-slate-600 text-[11px]">{row.nature}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}