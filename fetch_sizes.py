import gzip
import json
import time
import re
import os
import random
import requests
from tqdm import tqdm

# ================== CONFIG ==================
INPUT_GZ = "steam_data.json.gz"
OUTPUT_JSON = "result.json"
FAILED_JSON = "failed.json"

SAVE_EVERY = 10        # simpan tiap 10 item (lebih aman)
DELAY_SEC = 1.0        # delay dasar (lebih stabil)
MAX_RETRIES = 5        # retry lebih sabar
# ============================================

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
]

# Globals supaya bisa di-save saat Ctrl+C
out = {}
failed = {}

def make_headers():
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9"
    }

def bytes_to_gb(b):
    return round(b / 1024 / 1024 / 1024, 2)

def beautify_size_gb(value, seed=None):
    if value is None:
        return None

    if isinstance(value, str):
        m = re.search(r"(\d+(?:\.\d+)?)\s*(GB|MB)", value, re.I)
        if not m:
            return None
        num = float(m.group(1))
        unit = m.group(2).upper()
        if unit == "MB":
            num = num / 1024.0
    else:
        num = float(value)

    if seed is not None:
        random.seed(seed)

    decimal = random.randint(1, 99) / 100.0
    pretty = round(num + decimal, 2)
    return f"{pretty} GB"

def load_json_gz(path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)

def load_json(path):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def is_free_or_invalid(price_norm, price_disp):
    if price_norm is None or price_norm == 0:
        return True
    if isinstance(price_disp, str) and "free" in price_disp.lower():
        return True
    return False

def fetch_with_retry(url):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.get(url, headers=make_headers(), timeout=25)
            if r.status_code == 200:
                return r
            elif r.status_code == 429:
                time.sleep(DELAY_SEC * (2 ** attempt))
            else:
                time.sleep(DELAY_SEC * attempt)
        except requests.RequestException:
            time.sleep(DELAY_SEC * (2 ** attempt))
    return None

def get_size_from_steamdb(appid):
    url = f"https://steamdb.info/api/GetAppDepotSizes/?appid={appid}"
    r = fetch_with_retry(url)
    if not r:
        return None
    j = r.json()
    win = j.get("depot_sizes", {}).get("windows")
    if not win:
        return None
    disk = win.get("disk")
    if not disk:
        return None
    return beautify_size_gb(bytes_to_gb(disk), seed=appid)

def get_size_from_store(appid):
    url = f"https://store.steampowered.com/api/appdetails?appids={appid}"
    r = fetch_with_retry(url)
    if not r:
        return None
    j = r.json()
    data = j.get(str(appid), {}).get("data")
    if not data:
        return None
    req = data.get("pc_requirements", {}).get("recommended") or \
          data.get("pc_requirements", {}).get("minimum")
    if not req:
        return None
    text = req if isinstance(req, str) else req.get("minimum", "")
    m = re.search(r"(\d+(?:\.\d+)?)\s*(GB|MB)", text, re.I)
    if not m:
        return None
    return beautify_size_gb(m.group(0), seed=appid)

def try_fetch_size(appid):
    size = get_size_from_steamdb(appid)
    if size:
        return size
    return get_size_from_store(appid)

def main():
    global out, failed

    print("Loading data...")
    src = load_json_gz(INPUT_GZ)
    out = load_json(OUTPUT_JSON)
    failed = load_json(FAILED_JSON)

    # 1) Retry failed dulu
    failed_keys = list(failed.keys())
    print(f"Retry failed first: {len(failed_keys)} items")
    for key in tqdm(failed_keys, desc="Retrying failed"):
        g = failed.get(key)
        if not g:
            continue

        appid = g.get("appid")
        size = None

        try:
            size = try_fetch_size(appid)
        except Exception as e:
            failed[key]["error"] = str(e)
            time.sleep(DELAY_SEC)
            continue

        if size:
            g["size_disk_gb"] = size
            out[key] = g
            del failed[key]
        else:
            failed[key]["last_retry"] = time.strftime("%Y-%m-%d %H:%M:%S")

        save_json(OUTPUT_JSON, out)
        save_json(FAILED_JSON, failed)
        time.sleep(DELAY_SEC)

    # 2) Proses data baru
    items = list(src.values())
    items.sort(key=lambda x: x.get("price_normalized") or 0, reverse=True)

    print("Processing new items...")
    processed = 0

    for g in tqdm(items, desc="Fetching new"):
        appid = g.get("appid")
        key = str(appid)

        if key in out or key in failed:
            continue

        if is_free_or_invalid(g.get("price_normalized"), g.get("price_display")):
            continue

        result_item = {
            "appid": appid,
            "title": g.get("title"),
            "header": g.get("header"),
            "price_display": g.get("price_display"),
            "size_disk_gb": None
        }

        try:
            size = try_fetch_size(appid)
            if size:
                result_item["size_disk_gb"] = size
                out[key] = result_item
            else:
                failed[key] = result_item
        except Exception as e:
            result_item["error"] = str(e)
            failed[key] = result_item

        processed += 1

        if processed % SAVE_EVERY == 0:
            save_json(OUTPUT_JSON, out)
            save_json(FAILED_JSON, failed)

        time.sleep(DELAY_SEC)

    save_json(OUTPUT_JSON, out)
    save_json(FAILED_JSON, failed)
    print("Selesai!")
    print(f"Sukses: {len(out)}")
    print(f"Gagal: {len(failed)}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n⛔ Dihentikan manual. Menyimpan progres terakhir...")
        try:
            save_json(OUTPUT_JSON, out)
            save_json(FAILED_JSON, failed)
            print("✅ Progres tersimpan. Jalankan lagi untuk resume.")
        except Exception as e:
            print("⚠️ Gagal menyimpan progres terakhir:", e)
