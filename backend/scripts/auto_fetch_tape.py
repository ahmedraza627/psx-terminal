import os
import requests
import subprocess
import shutil
from datetime import datetime

TARGET_DIR = r"D:\downloads"

def decompress_unix_z(data: bytes) -> bytes:
    if len(data) < 3 or data[0] != 0x1F or data[1] != 0x9D:
        raise ValueError("Invalid .Z header")
    flags = data[2]
    maxbits = flags & 0x1F
    block_mode = bool(flags & 0x80)
    if maxbits < 9 or maxbits > 16:
        raise ValueError(f"Unsupported maxbits: {maxbits}")

    nbits = 9
    maxcode = (1 << nbits) - 1
    clear_code = 256 if block_mode else -1
    next_code = 257 if block_mode else 256

    prefix = [0] * (1 << maxbits)
    suffix = [0] * (1 << maxbits)
    for i in range(256):
        suffix[i] = i

    out = bytearray()
    pos = 3
    buf = b""
    bit_offset = 0

    def next_lzw_code():
        nonlocal pos, buf, bit_offset, nbits
        if bit_offset >= len(buf) * 8:
            if pos >= len(data):
                return -1
            buf = data[pos : pos + nbits]
            pos += len(buf)
            bit_offset = 0
        if bit_offset + nbits > len(buf) * 8:
            return -1
        byte_idx = bit_offset >> 3
        bit_off = bit_offset & 7
        val = buf[byte_idx]
        if byte_idx + 1 < len(buf):
            val |= buf[byte_idx + 1] << 8
        if byte_idx + 2 < len(buf):
            val |= buf[byte_idx + 2] << 16
        code = (val >> bit_off) & ((1 << nbits) - 1)
        bit_offset += nbits
        return code

    old_code = next_lzw_code()
    if old_code == -1:
        return bytes(out)
    fin_char = old_code
    out.append(fin_char)

    while True:
        code = next_lzw_code()
        if code == -1:
            break
        if block_mode and code == clear_code:
            buf = b""
            bit_offset = 0
            nbits = 9
            maxcode = (1 << nbits) - 1
            next_code = 257
            old_code = next_lzw_code()
            if old_code == -1:
                break
            fin_char = old_code
            out.append(fin_char)
            continue

        in_code = code
        stack = []
        if code >= next_code:
            stack.append(fin_char)
            code = old_code

        while code >= 256:
            stack.append(suffix[code])
            code = prefix[code]

        fin_char = suffix[code]
        stack.append(fin_char)
        out.extend(reversed(stack))

        if next_code < (1 << maxbits):
            prefix[next_code] = old_code
            suffix[next_code] = fin_char
            next_code += 1
            if next_code > maxcode and nbits < maxbits:
                nbits += 1
                maxcode = (1 << nbits) - 1
                buf = b""
                bit_offset = 0

        old_code = in_code

    return bytes(out)

def download_and_extract_psx():
    os.makedirs(TARGET_DIR, exist_ok=True)
    today_str = datetime.now().strftime("%Y-%m-%d")
    z_filename = f"{today_str}.Z"
    z_filepath = os.path.join(TARGET_DIR, z_filename)
    dest_lis = os.path.join(TARGET_DIR, f"closing_{today_str}.lis")
    active_lis = os.path.join(TARGET_DIR, "closing.lis")

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

            # Method 1: Pure-Python Unix .Z LZW Decompressor
            try:
                raw_bytes = decompress_unix_z(r.content)
                if len(raw_bytes) > 5000:
                    with open(dest_lis, "wb") as out_f:
                        out_f.write(raw_bytes)
                    shutil.copyfile(dest_lis, active_lis)
                    print(f"[EXTRACTED] Decompressed {len(raw_bytes)} bytes -> '{dest_lis}'.")
                    return dest_lis
            except Exception as decomp_err:
                print(f"[WARN] Native LZW fallback ({decomp_err}), trying Windows tar...")

            # Method 2: Windows 10 built-in tar
            subprocess.run(f'tar -xf "{z_filepath}" -C "{TARGET_DIR}"', shell=True, capture_output=True)
            extracted_candidate = os.path.join(TARGET_DIR, today_str)
            if os.path.exists(extracted_candidate):
                shutil.copyfile(extracted_candidate, dest_lis)
                shutil.copyfile(dest_lis, active_lis)
                print(f"[EXTRACTED] Ready tape generated at '{dest_lis}'.")
                return dest_lis
        else:
            print(f"[FALLBACK] Server returned HTTP {r.status_code}. Using local tape in {TARGET_DIR}.")
    except Exception as e:
        print(f"[FALLBACK] Network error: {e}. Using local tape.")
    return active_lis

if __name__ == "__main__":
    download_and_extract_psx()