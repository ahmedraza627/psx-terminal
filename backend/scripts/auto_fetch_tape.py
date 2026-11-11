import os
import requests
import shutil
from datetime import datetime

TARGET_DIR = r"D:\downloads"
CLOSING_URL = "https://dps.psx.com.pk/download/closing/closing.lis"

def download_latest_psx_tape():
    os.makedirs(TARGET_DIR, exist_ok=True)
    today_str = datetime.now().strftime("%Y-%m-%d")
    dest_path = os.path.join(TARGET_DIR, f"closing_{today_str}.lis")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://dps.psx.com.pk/"
    }

    print(f"[AUTO-DOWNLOAD] Fetching live PSX EOD tape directly from DPS...")
    try:
        r = requests.get(CLOSING_URL, headers=headers, timeout=15)
        if r.status_code == 200 and len(r.text) > 2000:
            with open(dest_path, "w", encoding="utf-8") as f:
                f.write(r.text)
            
            shutil.copyfile(dest_path, os.path.join(TARGET_DIR, "closing.lis"))
            print(f"[SUCCESS] Downloaded certified tape ({len(r.text)} bytes).")
            return dest_path
        else:
            print(f"[FALLBACK] Server returned HTTP {r.status_code}. Using local tape in {TARGET_DIR}.")
    except Exception as e:
        print(f"[FALLBACK] Connection error ({e}). Using existing local tape.")
    return None

if __name__ == "__main__":
    download_latest_psx_tape()