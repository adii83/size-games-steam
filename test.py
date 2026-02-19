import requests
import random
import time
import json

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]

def make_headers():
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "application/json,*/*;q=0.9",
        "Referer": "https://steamdb.info/"
    }

def test_appid(appid):
    url = f"https://steamdb.info/api/GetAppDepotSizes/?appid={appid}"
    print(f"\n🔎 Testing AppID: {appid}")
    try:
        r = requests.get(url, headers=make_headers(), timeout=20)
        print("Status:", r.status_code)

        if r.status_code != 200:
            print("Body:", r.text[:300])
            return

        data = r.json()
        print("Keys:", list(data.keys()))

        win = data.get("depot_sizes", {}).get("windows")
        if not win:
            print("❌ No windows depot found")
            print(json.dumps(data, indent=2)[:500])
            return

        disk = win.get("disk")
        download = win.get("download")
        print(f"✅ Disk size (bytes): {disk}")
        print(f"⬇️ Download size (bytes): {download}")

    except Exception as e:
        print("❌ Error:", e)

if __name__ == "__main__":
    test_ids = [
        1174180,  # Red Dead Redemption 2
        570,      # Dota 2
        730,      # CS2
        271590,  # GTA V
        1245620  # Elden Ring
    ]

    for appid in test_ids:
        test_appid(appid)
        time.sleep(2)  # jeda kecil biar nggak spam
