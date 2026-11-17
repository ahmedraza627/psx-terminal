import time
from src.core.config import get_db_path
from src.ingestion.context_loader import load_institutional_context
from src.ingestion.sqlite_adapter import load_validated_bars
from src.quant.backtester import LinearBacktester


def main():
    db_path = str(get_db_path())
    bars_by_ticker, _ = load_validated_bars(db_path)
    smart_flow, ndm_activity = load_institutional_context(db_path)

    t0 = time.perf_counter()
    report = LinearBacktester().run(bars_by_ticker, smart_flow=smart_flow, ndm_activity=ndm_activity)
    elapsed_ms = (time.perf_counter() - t0) * 1000

    print(f"O(N) Backtest Time : {elapsed_ms:.2f} ms")
    print(f"Total Signals      : {report.total_signals}")
    print(f"Wins / Losses / Open: {report.wins} / {report.losses} / {report.open_trades}")
    print(f"Win Rate (Resolved): {report.win_rate_pct}%")
    print(f"Avg PnL per Trade  : {report.avg_pnl_pct}%")


if __name__ == "__main__":
    main()