from datetime import date
from src.core.models import DailyBar
from src.ingestion.wal_adapter import WALIngestionManager


def test_wal_upsert_idempotency(tmp_path):
    db_file = tmp_path / "wal_test.db"
    manager = WALIngestionManager(str(db_file))

    bar1 = DailyBar(
        ticker="LUCK",
        trade_date=date(2026, 11, 16),
        open_price=100.0,
        high_price=105.0,
        low_price=98.0,
        close_price=103.0,
        volume=100_000,
    )

    # First insert
    inserted1, q1 = manager.upsert_bars([bar1])
    assert inserted1 == 1
    assert q1 == 0

    # Second insert with updated close price (Idempotent UPSERT test)
    bar1_updated = DailyBar(
        ticker="LUCK",
        trade_date=date(2026, 11, 16),
        open_price=100.0,
        high_price=105.0,
        low_price=98.0,
        close_price=104.5,
        volume=120_000,
    )
    inserted2, q2 = manager.upsert_bars([bar1_updated])
    assert inserted2 == 1
    assert q2 == 0