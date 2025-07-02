# market_context.py
import requests
import json
import time
from datetime import datetime
from pathlib import Path

CACHE_PATH = "market_context_cache.json"
LOG_PATH = "log/market_context.log"

Path("log").mkdir(exist_ok=True)

def log(msg):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_PATH, "a") as f:
        f.write(f"[{now}] {msg}\n")

def get_btc_dominance():
    try:
        url = "https://api.binance.com/api/v3/global"
        r = requests.get(url, timeout=10)
        if r.status_code == 200 and "data" in r.json():
            # Binance doesn't expose DOM, fallback
            raise Exception("Binance không hỗ trợ BTC dominance")
    except:
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

def get_market_context():
    context = {
        "timestamp": datetime.now().isoformat(),
        "btc_dominance": get_btc_dominance(),
        "fear_greed": get_fear_greed_index()
    }
    with open(CACHE_PATH, "w") as f:
        json.dump(context, f, indent=2)
    log(f"✅ Cập nhật context: {context}")
    return context

if __name__ == "__main__":
    get_market_context()
