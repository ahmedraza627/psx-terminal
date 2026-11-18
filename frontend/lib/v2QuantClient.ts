export interface V2TradeSignal {
  ticker: string;
  signal_date: string;
  side: "BUY" | "SHORT";
  entry_price: number;
  stop_loss: number;
  target_price: number;
  confidence_score: number;
  reason: string;
}

export interface V2BacktestSummary {
  total_signals: number;
  wins: number;
  losses: number;
  open_trades: number;
  win_rate_pct: number;
  avg_pnl_pct: number;
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

async function fetchWithTimeout<T>(url: string, timeoutMs = 1500): Promise<T | null> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(url, { signal: controller.signal, cache: "no-store" });
    if (!res.ok) return null;
    return (await res.json()) as T;
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

export async function fetchV2LiveDeskData(): Promise<{
  signals: V2TradeSignal[];
  backtest: V2BacktestSummary | null;
  apiOnline: boolean;
}> {
  const [signals, backtest] = await Promise.all([
    fetchWithTimeout<V2TradeSignal[]>(`${API_BASE}/api/v1/signals`),
    fetchWithTimeout<V2BacktestSummary>(`${API_BASE}/api/v1/backtest`),
  ]);

  if (signals !== null) {
    return { signals, backtest, apiOnline: true };
  }
  return { signals: [], backtest: null, apiOnline: false };
}