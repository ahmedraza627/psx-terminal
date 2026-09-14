/**
 * Model-portfolio analytics over stored, real data only.
 *
 * Book construction (walk-forward, no look-ahead): for each of the trailing
 * sessions, equal-weight the actionable signals emitted THAT session and mark
 * each constituent with the NEXT stored session's close. This reproduces the
 * pipeline's gated daily book exactly as an institution would backtest it.
 * Benchmark: equal-weight mean of all stored closes that session (labelled a
 * proxy — PSX publishes no free index series in our tables).
 */
import type { SizingSignal } from "@/lib/risk";
import type { EodPoint } from "@/lib/deskQueries";

export interface NavPoint {
  tradeDate: string;
  /** Book equity index rebased to 1.0 at window start. */
  book: number;
  /** Equal-weight market proxy rebased to 1.0 at window start. */
  proxy: number;
}

export interface PortfolioStats {
  bookTotalPct: number;
  proxyTotalPct: number;
  alphaAnnPct: number | null;
  beta: number | null;
  sharpe: number | null;
  maxDrawdownPct: number;
  sessions: number;
}

const RF_ANNUAL = 0.11; // 6M KIBOR stand-in — constant, disclosed in the desk footer

interface PerDate {
  date: string;
  bookRet: number | null;
  proxyRet: number | null;
}

/** date -> ticker -> close */
function indexEod(eod: EodPoint[]): Map<string, Map<string, number>> {
  const byDate = new Map<string, Map<string, number>>();
  for (const r of eod) {
    if (r.close == null) continue;
    let m = byDate.get(r.tradeDate);
    if (!m) {
      m = new Map();
      byDate.set(r.tradeDate, m);
    }
    m.set(r.ticker.toUpperCase(), r.close);
  }
  return byDate;
}

/**
 * Daily returns of the equal-weight signal book vs the equal-weight market
 * proxy. Each session's constituents are that session's actionable signals;
 * the return is realized into the NEXT session (close-to-close).
 */
export function computeDailyReturns(
  signalsByDate: Map<string, SizingSignal[]>,
  eod: EodPoint[]
): PerDate[] {
  const byDate = indexEod(eod);
  const dates = Array.from(byDate.keys()).sort();
  const out: PerDate[] = [];
  for (let i = 0; i < dates.length - 1; i++) {
    const d0 = dates[i];
    const d1 = dates[i + 1];
    const m0 = byDate.get(d0) as Map<string, number>;
    const m1 = byDate.get(d1) as Map<string, number>;

    // Proxy: mean close-to-close across every name with both marks.
    let proxySum = 0;
    let proxyN = 0;
    for (const [t, c0] of m0) {
      const c1 = m1.get(t);
      if (c1 != null && c0 > 0) {
        proxySum += c1 / c0 - 1;
        proxyN += 1;
      }
    }
    const proxyRet = proxyN > 0 ? proxySum / proxyN : null;

    // Book: actionable signals emitted on d0, marked into d1.
    const sigs = (signalsByDate.get(d0) ?? []).filter(
      (s) => s.entryReference != null && s.entryReference > 0
    );
    let bookSum = 0;
    let bookN = 0;
    for (const s of sigs) {
      const c1 = m1.get(s.ticker.toUpperCase());
      if (c1 != null) {
        bookSum += c1 / (s.entryReference as number) - 1;
        bookN += 1;
      }
    }
    const bookRet = bookN > 0 ? bookSum / bookN : null;
    out.push({ date: d1, bookRet, proxyRet });
  }
  return out;
}

export function buildNavSeries(rets: PerDate[]): NavPoint[] {
  let book = 1;
  let proxy = 1;
  const out: NavPoint[] = [];
  for (const r of rets) {
    if (r.bookRet != null) book *= 1 + r.bookRet;
    if (r.proxyRet != null) proxy *= 1 + r.proxyRet;
    out.push({ tradeDate: r.date, book, proxy });
  }
  return out;
}

export function computeStats(rets: PerDate[]): PortfolioStats {
  const paired = rets.filter(
    (r) => r.bookRet != null && r.proxyRet != null
  ) as { date: string; bookRet: number; proxyRet: number }[];
  const bookRets = paired.map((r) => r.bookRet);
  const proxyRets = paired.map((r) => r.proxyRet);
  const rfD = RF_ANNUAL / 252;

  const mean = (xs: number[]) =>
    xs.length ? xs.reduce((a, v) => a + v, 0) / xs.length : 0;
  const varOf = (xs: number[], mu: number) =>
    xs.length > 1
      ? xs.reduce((a, v) => a + (v - mu) * (v - mu), 0) / (xs.length - 1)
      : 0;

  const muB = mean(bookRets);
  const muP = mean(proxyRets);
  const varB = varOf(bookRets, muB);
  const varP = varOf(proxyRets, muP);
  let cov = 0;
  if (paired.length > 1) {
    cov =
      paired.reduce(
        (a, r) => a + (r.bookRet - muB) * (r.proxyRet - muP),
        0
      ) /
      (paired.length - 1);
  }

  const beta = varP > 0 ? cov / varP : null;
  const jensenDaily =
    beta != null ? muB - rfD - beta * (muP - rfD) : null;
  const sd = Math.sqrt(varB);
  const sharpe = sd > 0 ? ((muB - rfD) / sd) * Math.sqrt(252) : null;

  // MDD from the cumulative book NAV.
  let nav = 1;
  let peak = 1;
  let mdd = 0;
  for (const r of rets) {
    if (r.bookRet != null) {
      nav *= 1 + r.bookRet;
      peak = Math.max(peak, nav);
      mdd = Math.min(mdd, nav / peak - 1);
    }
  }

  const bookTotal = rets.reduce((a, r) => a * (1 + (r.bookRet ?? 0)), 1) - 1;
  const proxyTotal =
    rets.reduce((a, r) => a * (1 + (r.proxyRet ?? 0)), 1) - 1;

  return {
    bookTotalPct: bookTotal * 100,
    proxyTotalPct: proxyTotal * 100,
    alphaAnnPct: jensenDaily != null ? jensenDaily * 252 * 100 : null,
    beta,
    sharpe,
    maxDrawdownPct: mdd * 100,
    sessions: rets.length,
  };
}

/** NAV curve (book vs proxy) over the trailing sessions. */
export function buildPortfolioNav(
  signalsByDate: Map<string, SizingSignal[]>,
  eod: EodPoint[],
  sessions = 30
): { nav: NavPoint[]; stats: PortfolioStats } {
  const rets = computeDailyReturns(signalsByDate, eod).slice(-sessions);
  return { nav: buildNavSeries(rets), stats: computeStats(rets) };
}

// ----------------------------------------------------------------- //
// Sector exposure: current book weights vs market composition.       //
// ----------------------------------------------------------------- //
export interface ExposureRow {
  sector: string;
  bookPct: number;
  marketPct: number;
  deltaPct: number;
}

export function computeExposure(
  positions: { positionValuePkr: number; ticker: string }[],
  sectorMap: Map<string, string>,
  marketCapByTicker: Map<string, number>
): ExposureRow[] {
  const totalBook = positions.reduce((a, p) => a + p.positionValuePkr, 0);
  const totalCap = Array.from(marketCapByTicker.values()).reduce(
    (a, v) => a + v,
    0
  );
  if (totalBook <= 0 || totalCap <= 0) return [];

  const bookBySector = new Map<string, number>();
  for (const p of positions) {
    const s = (sectorMap.get(p.ticker.toUpperCase()) ?? "UNCATEGORIZED")
      .toUpperCase();
    bookBySector.set(s, (bookBySector.get(s) ?? 0) + p.positionValuePkr);
  }
  const capBySector = new Map<string, number>();
  for (const [t, cap] of marketCapByTicker) {
    const s = (sectorMap.get(t) ?? "UNCATEGORIZED").toUpperCase();
    capBySector.set(s, (capBySector.get(s) ?? 0) + cap);
  }

  const sectors = new Set([...bookBySector.keys(), ...capBySector.keys()]);
  const rows: ExposureRow[] = [];
  for (const s of sectors) {
    const bookPct = ((bookBySector.get(s) ?? 0) / totalBook) * 100;
    const marketPct = ((capBySector.get(s) ?? 0) / totalCap) * 100;
    rows.push({
      sector: s,
      bookPct,
      marketPct,
      deltaPct: bookPct - marketPct,
    });
  }
  return rows.sort((a, b) => b.deltaPct - a.deltaPct);
}

// ----------------------------------------------------------------- //
// NAV sparkline SVG (dual line, book vs proxy).                      //
// ----------------------------------------------------------------- //
export function navSvg(nav: NavPoint[]): { path: string; pathProxy: string; w: number; h: number } {
  const w = 720;
  const h = 120;
  if (nav.length < 2) return { path: "", pathProxy: "", w, h };
  const all = nav.flatMap((n) => [n.book, n.proxy]);
  const min = Math.min(...all);
  const max = Math.max(...all);
  const range = max - min || 1;
  const px = (i: number) => (i / (nav.length - 1)) * w;
  const py = (v: number) => h - ((v - min) / range) * (h - 6) - 3;
  const path = nav
    .map((n, i) => `${i === 0 ? "M" : "L"}${px(i).toFixed(1)},${py(n.book).toFixed(1)}`)
    .join(" ");
  const pathProxy = nav
    .map((n, i) => `${i === 0 ? "M" : "L"}${px(i).toFixed(1)},${py(n.proxy).toFixed(1)}`)
    .join(" ");
  return { path, pathProxy, w, h };
}
