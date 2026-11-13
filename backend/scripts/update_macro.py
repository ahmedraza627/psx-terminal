import os
import sys
import sqlite3
from datetime import datetime

DB_PATH = os.path.join("backend", "psx_history.db")

def init_macro(conn):
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS macro_yields (
            updated_date TEXT PRIMARY KEY,
            policy_rate REAL,
            tbill_6m REAL,
            prev_tbill_6m REAL
        )
    """)
    cur.execute("SELECT COUNT(*) FROM macro_yields")
    if cur.fetchone()[0] == 0:
        cur.execute("""
            INSERT INTO macro_yields (updated_date, policy_rate, tbill_6m, prev_tbill_6m)
            VALUES (?, 11.00, 10.85, 11.20)
        """, (datetime.now().strftime("%Y-%m-%d"),))
    conn.commit()

if __name__ == "__main__":
    conn = sqlite3.connect(DB_PATH)
    init_macro(conn)
    cur = conn.cursor()
    if len(sys.argv) >= 4:
        p_rate = float(sys.argv[1])
        curr_6m = float(sys.argv[2])
        prev_6m = float(sys.argv[3])
        dt = datetime.now().strftime("%Y-%m-%d")
        cur.execute("""
            INSERT OR REPLACE INTO macro_yields (updated_date, policy_rate, tbill_6m, prev_tbill_6m)
            VALUES (?, ?, ?, ?)
        """, (dt, p_rate, curr_6m, prev_6m))
        conn.commit()
        print(f"[MACRO UPDATED] Date: {dt} | SBP Policy: {p_rate}% | 6M T-Bill: {curr_6m}% (Prev: {prev_6m}%)")
    else:
        cur.execute("SELECT updated_date, policy_rate, tbill_6m, prev_tbill_6m FROM macro_yields ORDER BY updated_date DESC LIMIT 1")
        row = cur.fetchone()
        print(f"[CURRENT MACRO] Date: {row[0]} | Policy Rate: {row[1]}% | 6M T-Bill: {row[2]}% (Prev: {row[3]}%)")
        print("Update usage: python backend\\scripts\\update_macro.py <PolicyRate> <New6MYield> <Prev6MYield>")
    conn.close()