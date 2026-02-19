import gzip
import json
import time
import os
import random
import subprocess
import requests
import re
from tqdm import tqdm

# ================== CONFIG ==================
INPUT_GZ = "steam_data.json.gz"
FX_GAMES_JSON = "fx_games.json"
OUTPUT_JSON = "result.json"
FAILED_JSON = "failed.json"
SKIPPED_JSON = "skipped_protected.json"
COOKIES_FILE = ".env.json"

SAVE_EVERY = 10
PUSH_EVERY = 1000
DELAY_SEC = 1.5
MAX_RETRIES = 5
# ============================================

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
]

out = {}
failed = {}
skipped = {}
COOKIES = {}

# ================== HELPERS ==================

def load_cookies(path):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def make_headers():
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://store.steampowered.com/"
    }

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

def load_fx_games_appids(path):
    if not os.path.exists(path):
        return set()
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return set(str(g.get("appid")) for g in data.get("games", []) if g.get("appid"))

def is_free_or_invalid(price_norm, price_disp):
    if price_norm is None or price_norm == 0:
        return True
    if isinstance(price_disp, str) and "free" in price_disp.lower():
        return True
    return False

def randomize_decimal_only(size_str, seed=None):
    try:
        num = float(size_str.replace("GB", "").strip())
    except:
        return size_str

    base = int(num)
    if seed:
        random.seed(seed)
    decimal = random.randint(1, 99) / 100.0
    return f"{round(base + decimal, 2)} GB"

# ================== FETCH ==================

def fetch_with_retry(url):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.get(url, headers=make_headers(), cookies=COOKIES if COOKIES else None, timeout=30)

            if r.status_code == 200:
                return r
            elif r.status_code == 429:
                wait = DELAY_SEC * (2 ** attempt)
                print(f"⏳ [429] Rate limit. Sleep {round(wait,1)}s")
                time.sleep(wait)
            elif r.status_code in (401, 403):
                print("🔐 [AUTH] Cookie invalid/expired. Update .env.json")
                return None
            else:
                print(f"⚠️ HTTP {r.status_code} - retry {attempt}/{MAX_RETRIES}")
                time.sleep(DELAY_SEC * attempt)
        except requests.RequestException as e:
            print("❌ Request error:", e)
            time.sleep(DELAY_SEC * (2 ** attempt))
    return None

def get_size_from_store_recommended(appid):
    url = f"https://store.steampowered.com/app/{appid}/"
    r = fetch_with_retry(url)
    if not r:
        return None

    html = r.text
    rec_block = re.search(r"<strong>Recommended:</strong>.*?</ul>\s*</ul>", html, re.I | re.S)
    if not rec_block:
        return None

    block = rec_block.group(0)
    m = re.search(r"<strong>Storage:</strong>\s*(\d+(?:\.\d+)?)\s*(GB|MB)", block, re.I)
    if not m:
        return None

    size = float(m.group(1))
    if m.group(2).upper() == "MB":
        size = size / 1024.0

    return f"{round(size, 2)} GB"

def git_push(message):
    try:
        subprocess.run(["git", "add", OUTPUT_JSON, FAILED_JSON, SKIPPED_JSON], check=True)
        subprocess.run(["git", "commit", "-m", message], check=True)
        subprocess.run(["git", "push"], check=True)
        print("🚀 Auto-pushed to GitHub")
    except subprocess.CalledProcessError as e:
        print("⚠️ Git push failed:", e)

# ================== MAIN ==================

def main():
    global out, failed, skipped, COOKIES

    print("Loading data...")
    src = load_json_gz(INPUT_GZ)
    fx_appids = load_fx_games_appids(FX_GAMES_JSON)
    COOKIES = load_cookies(COOKIES_FILE)

    out = load_json(OUTPUT_JSON)
    failed = load_json(FAILED_JSON)
    skipped = load_json(SKIPPED_JSON)

    print(f"Progress global: {len(out)+len(failed)+len(skipped)}/{len(src)}")

    # Retry failed first
    for key in tqdm(list(failed.keys()), desc="Retrying failed"):
        g = failed[key]
        size = get_size_from_store_recommended(g["appid"])
        if size:
            g["size_disk_gb"] = randomize_decimal_only(size, seed=g["appid"])
            out[key] = g
            del failed[key]
        else:
            failed[key]["last_retry"] = time.strftime("%Y-%m-%d %H:%M:%S")
        save_json(OUTPUT_JSON, out)
        save_json(FAILED_JSON, failed)
        time.sleep(DELAY_SEC)

    items = sorted(src.values(), key=lambda x: x.get("price_normalized") or 0, reverse=True)

    pending = [g for g in items if str(g["appid"]) not in out and str(g["appid"]) not in failed and str(g["appid"]) not in skipped]

    print(f"Processing new items (pending: {len(pending)})...")

    processed = 0
    for g in tqdm(pending, desc="Fetching new"):
        appid = g["appid"]
        key = str(appid)

        if is_free_or_invalid(g.get("price_normalized"), g.get("price_display")):
            continue

        if g.get("protection") is True and key not in fx_appids:
            skipped[key] = {
                "appid": appid,
                "title": g.get("title"),
                "genre": g.get("genre"),
                "header": g.get("header"),
                "price_display": g.get("price_display"),
                "reason": "protected_not_in_fx"
            }
            continue

        result_item = {
            "appid": appid,
            "title": g.get("title"),
            "genre": g.get("genre"),
            "header": g.get("header"),
            "price_display": g.get("price_display"),
        }

        size = get_size_from_store_recommended(appid)
        if size:
            result_item["size_disk_gb"] = randomize_decimal_only(size, seed=appid)
            out[key] = result_item
        else:
            failed[key] = result_item

        processed += 1

        if processed % SAVE_EVERY == 0:
            save_json(OUTPUT_JSON, out)
            save_json(FAILED_JSON, failed)
            save_json(SKIPPED_JSON, skipped)

        if processed % PUSH_EVERY == 0:
            git_push(f"Auto update sizes: +{processed}")

        time.sleep(DELAY_SEC)

    save_json(OUTPUT_JSON, out)
    save_json(FAILED_JSON, failed)
    save_json(SKIPPED_JSON, skipped)
    git_push("Final update sizes")

    print("Selesai!")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n⛔ Dihentikan manual. Menyimpan progres terakhir...")
        save_json(OUTPUT_JSON, out)
        save_json(FAILED_JSON, failed)
        save_json(SKIPPED_JSON, skipped)
        git_push("Stopped manually - progress saved")
        print("✅ Progres tersimpan & dipush. Jalankan lagi untuk resume.")
