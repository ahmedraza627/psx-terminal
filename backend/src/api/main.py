import time
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from src.core.config import get_db_path
from src.core.models import TradeSignal
from src.ingestion.sqlite_adapter import load_validated_bars
from src.quant.backtester import BacktestReport, LinearBacktester
from src.quant.engine import LiquidityQuantEngine

app = FastAPI(
    title="PSX Institutional Terminal API",
    version="2.0.0",
    description="Deterministic quant engine with O(1) monotonic sliding windows and Pydantic validation.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


class TTLCache:
    def __init__(self, ttl_seconds: int = 300):
        self.ttl = ttl_seconds
        self._store: Dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Optional[Any]:
        item = self._store.get(key)
        if not item:
            return None
        expires_at, value = item
        if time.time() > expires_at:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        self._store[key] = (time.time() + self.ttl, value)


cache = TTLCache(ttl_seconds=300)


def _get_dataset():
    cached = cache.get("dataset")
    if cached is not None:
        return cached
    db_path = get_db_path()
    data = load_validated_bars(str(db_path))
    cache.set("dataset", data)
    return data


@app.get("/health")
def health_check():
    t0 = time.perf_counter()
    bars_by_ticker, rejected = _get_dataset()
    latency_ms = round((time.perf_counter() - t0) * 1000, 2)
    return {
        "status": "healthy",
        "tickers_indexed": len(bars_by_ticker),
        "quarantined_rows": rejected,
        "read_latency_ms": latency_ms,
    }


@app.get("/api/v1/signals", response_model=List[TradeSignal])
def get_live_signals(
    side: Optional[str] = Query(None, pattern="^(BUY|SHORT)$"),
    min_confidence: float = Query(0.0, ge=0.0, le=1.0),
):
    bars_by_ticker, _ = _get_dataset()
    engine = LiquidityQuantEngine()
    results: List[TradeSignal] = []

    for bars in bars_by_ticker.values():
        sig = engine.evaluate_ticker(bars)
        if sig and sig.confidence_score >= min_confidence:
            if side is None or sig.side == side:
                results.append(sig)

    results.sort(key=lambda s: s.confidence_score, reverse=True)
    return results


@app.get("/api/v1/backtest", response_model=BacktestReport)
def get_backtest_summary():
    cached = cache.get("backtest")
    if cached is not None:
        return cached
    bars_by_ticker, _ = _get_dataset()
    report = LinearBacktester().run(bars_by_ticker)
    cache.set("backtest", report)
    return report