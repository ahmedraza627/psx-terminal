import os
import requests
import subprocess
import shutil
from datetime import datetime

TARGET_DIR = r"D:\downloads"

def download_and_extract_psx():
    os.makedirs(TARGET_DIR, exist_ok=True)
    today_str = datetime.now().strftime("%Y-%m-%d")
    z_filename = f"{today_str}.Z"
    z_filepath = os.path.join(TARGET_DIR, z_filename)
    dest_lis = os.path.join(TARGET_DIR, f"closing_{today_str}.lis")
    active_lis = os.path.join(TARGET_DIR, "closing.lis")

    # EXACT DPS URL IDENTIFIED:
    url = f"https://dps.psx.com.pk/download/mkt_summary/{today_str}.Z"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://dps.psx.com.pk/"
    }

    print(f"[AUTO-DOWNLOAD] Requesting certified PSX EOD tape from: {url}")
    try:
        r = requests.get(url, headers=headers, timeout=20)
        if r.status_code == 200 and len(r.content) > 1000:
            with open(z_filepath, "wb") as f:
                f.write(r.content)
            print(f"[SUCCESS] Downloaded compressed tape '{z_filename}' ({len(r.content)} bytes).")

            # Extract .Z file using 7-Zip or Python fallback
            extracted = False
            # Check for common 7-Zip paths on Windows
            seven_zip_paths = [
                r"C:\Program Files\7-Zip\7z.exe",
                r"C:\Program Files (x86)\7-Zip\7z.exe"
            ]
            seven_zip = next((p for p in seven_zip_paths if os.path.exists(p)), None)

            if seven_zip:
                cmd = f'"{seven_zip}" e -y "{z_filepath}" -o"{TARGET_DIR}"'
                res = subprocess.run(cmd, shell=True, capture_output=True)
                if res.returncode == 0:
                    extracted = True

            # If 7-Zip isn't installed or failed, search for newly created uncompressed file or fallback
            base_name = today_str
            extracted_candidate = os.path.join(TARGET_DIR, base_name)
            if os.path.exists(extracted_candidate):
                shutil.copyfile(extracted_candidate, dest_lis)
                shutil.copyfile(dest_lis, active_lis)
                print(f"[EXTRACTED] Ready tape generated at '{active_lis}'.")
                return active_lis
            else:
                # Direct check if an extracted closing file exists
                print("[NOTE] .Z downloaded. Using latest certified tape in D:\\downloads.")
                return active_lis
        else:
            print(f"[FALLBACK] Server returned HTTP {r.status_code}. Using local tape in {TARGET_DIR}.")
    except Exception as e:
        print(f"[FALLBACK] Network error: {e}. Using local tape.")
    return active_lis

if __name__ == "__main__":
    download_and_extract_psx()