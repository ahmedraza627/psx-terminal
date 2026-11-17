import sqlite3, pytest
from fastapi.testclient import TestClient
from src.api import main as api_main

@pytest.fixture()
def isolated_client(tmp_path, monkeypatch):
    db_file = tmp_path / "test_psx.db"
    conn = sqlite3.connect(db_file)
    conn.execute("CREATE TABLE daily_eod (date TEXT, ticker TEXT, sector TEXT, open REAL, high REAL, low REAL, close REAL, volume INTEGER, turnover REAL)")
    conn.execute("INSERT INTO daily_eod VALUES ('2026-11-16', 'SYS', 'TECH', 100.0, 102.0, 99.0, 101.0, 150000, 15150000)")
    conn.commit()
    conn.close()
    monkeypatch.setattr(api_main, "get_db_path", lambda: db_file)
    api_main.cache._store.clear()
    return TestClient(api_main.app)

def test_health_endpoint(isolated_client):
    res = isolated_client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "healthy"

def test_signals_endpoint_filtering(isolated_client):
    res = isolated_client.get("/api/v1/signals", params={"side": "SHORT", "min_confidence": 0.5})
    assert res.status_code == 200
