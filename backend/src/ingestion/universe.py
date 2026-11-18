"""universe.py - which PSX symbols the research store actually tracks.

The live tape carries hundreds of symbols, most of which are thin, suspended or
newly listed and therefore useless for a multi-year replay. The research universe
is the liquid core plus anything the store already proves it can price day after
day (a long bar history), which keeps a 5-year backfill to symbols that can
actually produce signals.
"""
from __future__ import annotations

import sqlite3
from typing import List

CORE_TICKERS: List[str] = [
    # Banking
    "UBL", "MCB", "MEBL", "HBL", "BAHL", "BAFL", "NBP", "BOP", "AKBL", "FABL",
    # Cement
    "MLCF", "LUCK", "DGKC", "FCCL", "PIOC", "CHCC", "ACPL", "BWCL", "KOHC",
    # Oil, gas & E&P
    "OGDC", "PPL", "MARI", "POL", "PSO", "SHEL", "SNGP", "SSGC", "HASCOL",
    # Fertiliser
    "FFC", "ENGRO", "EFERT", "FATIMA", "FFBL",
    # Technology
    "SYS", "TRG", "AIRLINK", "AVN", "NETSOL", "OCTOPUS",
    # Refineries
    "PRL", "NRL", "ATRL", "CNERGY",
    # Power, chemicals, pharma & manufacturing
    "HUBC", "KAPCO", "KEL", "EPCL", "LOTCHEM", "SEARL", "AGP", "ABOT", "ILP",
    "NML", "PAEL", "UNITY", "INIL", "ISL", "MTL", "INDU", "HCAR", "PSMC",
    "THALL", "GTYR", "TREET", "AICL",
]

MIN_HISTORY_BARS = 240


def active_universe(db_path: str, min_bars: int = MIN_HISTORY_BARS) -> List[str]:
    """Core names plus every symbol the store already holds a long history for."""
    symbols = set(CORE_TICKERS)
    try:
        conn = sqlite3.connect(db_path)
        try:
            rows = conn.execute(
                "SELECT ticker FROM daily_eod GROUP BY ticker HAVING COUNT(*) >= ?",
                (min_bars,),
            ).fetchall()
        finally:
            conn.close()
        symbols.update(row[0].strip().upper() for row in rows if row[0])
    except sqlite3.Error:
        pass  # a missing/empty store just means the core list is the universe
    return sorted(symbols)
