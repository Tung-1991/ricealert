import requests
import json
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CACHE_PATH = BASE_DIR / "market_context_cache.json"
LOG_DIR = BASE_DIR / "log"
LOG_PATH = LOG_DIR / "market_context.log"
LOGNEW_DIR = BASE_DIR / "lognew"
LOGNEW_PATH = LOGNEW_DIR / "market_context.json"

LOG_DIR.mkdir(exist_ok=True)
LOGNEW_DIR.mkdir(exist_ok=True)

def log(msg):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_PATH, "a") as f:
        f.write(f"[{now}] {msg}\n")

def get_btc_dominance():
    try:
        r = requests.get("https://api.coingecko.com/api/v3/global", timeout=10)
        dom = r.json()['data']['market_cap_percentage']['btc']
        return round(dom, 2)
    except Exception as e:
        log(f"[BTC_DOM] Lỗi: {e}")
        return None

def get_fear_greed_index():
    try:
        r = requests.get("https://api.alternative.me/fng/", timeout=10)
        data = r.json()
        return int(data['data'][0]['value'])
    except Exception as e:
        log(f"[FearGreed] Lỗi: {e}")
        return None

def get_total_market_volume():
    try:
        r = requests.get("https://api.coingecko.com/api/v3/global", timeout=10)
        vol = r.json()['data']['total_volume']['usd']
        return round(vol / 1e9, 2)  # tỷ USD
    except Exception as e:
        log(f"[TOTAL_VOLUME] Lỗi: {e}")
        return None

def get_total_market_cap():
    try:
        r = requests.get("https://api.coingecko.com/api/v3/global", timeout=10)
        cap = r.json()['data']['total_market_cap']['usd']
        return round(cap / 1e9, 2)  # tỷ USD
    except Exception as e:
        log(f"[TOTAL_CAP] Lỗi: {e}")
        return None

def get_market_context():
    context = {
        "timestamp": datetime.now().isoformat(),
        "btc_dominance": get_btc_dominance(),
        "fear_greed": get_fear_greed_index(),
        "total_market_cap_usd_bil": get_total_market_cap(),
        "total_volume_usd_bil": get_total_market_volume()
    }
    with open(LOGNEW_PATH, "w") as f:
        json.dump(context, f, indent=2)
    log(f"✅ Cập nhật context: {context}")
    return context

def get_market_context_data():
    try:
        with open("lognew/market_context.json", "r") as f:
            data = json.load(f)
            # fallback nếu thiếu recent_volumes
            if "recent_volumes" not in data:
                data["recent_volumes"] = [70, 75, 80, 90, 85, 78, 92]
            return data
    except Exception as e:
        log(f"[GET_CONTEXT_DATA] Lỗi đọc file: {e}")
        return {
            "btc_dominance": 50,
            "fear_greed": 50,
            "total_market_cap_usd_bil": 1000,
            "total_volume_usd_bil": 50,
            "recent_volumes": [70, 75, 80, 90, 85, 78, 92]
        }

if __name__ == "__main__":
    print("=== 📊 MARKET CONTEXT UPDATE ===")
    context = get_market_context()
    print(f"{'timestamp':>25}: {context['timestamp']}")
    print(f"{'btc_dominance':>25}: {context['btc_dominance']}%")
    print(f"{'fear_greed':>25}: {context['fear_greed']}")
    print(f"{'total_market_cap_usd_bil':>25}: {context['total_market_cap_usd_bil']} B$")
    print(f"{'total_volume_usd_bil':>25}: {context['total_volume_usd_bil']} B$")
