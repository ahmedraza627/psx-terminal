from pathlib import Path

# Resolves D:\psx-smc\project-1\backend regardless of current working directory
BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_DIR.parent


def get_db_path() -> Path:
    """The ingestion store is fixed; falling back to a glob could pick any .db."""
    canonical = BACKEND_DIR / "psx_history.db"
    if canonical.exists():
        return canonical
    db_files = sorted(PROJECT_ROOT.rglob("*.db"))
    if not db_files:
        raise FileNotFoundError(f"No SQLite .db file found under {PROJECT_ROOT}")
    return db_files[0]