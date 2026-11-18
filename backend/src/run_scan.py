import time
from src.core.config import get_db_path
from src.ingestion.sqlite_adapter import load_validated_bars
from src.quant.engine import LiquidityQuantEngine


def main():
    db_path = get_db_path()
    print(f"Using DB       : {db_path}")

    t0 = time.perf_counter()
    bars_by_ticker, rejected = load_validated_bars(str(db_path))
    t_load = time.perf_counter()

    engine = LiquidityQuantEngine()
    signals = []
    for ticker, bars in bars_by_ticker.items():
        sig = engine.evaluate_ticker(bars)
        if sig:
            signals.append(sig)
    t_eval = time.perf_counter()

    print(f"Tickers loaded : {len(bars_by_ticker)} (Quarantined bad rows: {rejected})")
    print(f"DB Load Time   : {(t_load - t0)*1000:.2f} ms")
    print(f"Quant Eval Time: {(t_eval - t_load)*1000:.2f} ms")
    print(f"Signals Found  : {len(signals)}")
    for s in signals:
        print(f"  [{s.side}] {s.ticker} @ {s.entry_price} | SL: {s.stop_loss} | TP: {s.target_price} | {s.reason}")


if __name__ == "__main__":
    main()