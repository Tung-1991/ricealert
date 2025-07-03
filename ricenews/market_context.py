import requests
import json
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
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

def get_fear_greed_index():
    try:
        r = requests.get("https://api.alternative.me/fng/", timeout=10)
        r.raise_for_status()
        data = r.json()
        return int(data['data'][0]['value'])
    except Exception as e:
        log(f"[FearGreed] Lỗi: {e}")
        return None

def get_global_market_data():
    """
    SỬA LỖI: Gộp 3 lệnh gọi API CoinGecko thành 1 để tăng hiệu quả.
    """
    try:
        r = requests.get("https://api.coingecko.com/api/v3/global", timeout=10)
        r.raise_for_status()
        data = r.json()['data']
        
        btc_dom = data.get('market_cap_percentage', {}).get('btc')
        total_cap = data.get('total_market_cap', {}).get('usd')
        total_vol = data.get('total_volume', {}).get('usd')

        return {
            "btc_dominance": round(btc_dom, 2) if btc_dom is not None else None,
            "total_market_cap_usd_bil": round(total_cap / 1e9, 2) if total_cap is not None else None,
            "total_volume_usd_bil": round(total_vol / 1e9, 2) if total_vol is not None else None,
        }
    except Exception as e:
        log(f"[GLOBAL_DATA] Lỗi: {e}")
        return {
            "btc_dominance": None,
            "total_market_cap_usd_bil": None,
            "total_volume_usd_bil": None,
        }

def get_market_context():
    global_data = get_global_market_data()
    
    context = {
        "timestamp": datetime.now().isoformat(),
        "btc_dominance": global_data["btc_dominance"],
        "fear_greed": get_fear_greed_index(),
        "total_market_cap_usd_bil": global_data["total_market_cap_usd_bil"],
        "total_volume_usd_bil": global_data["total_volume_usd_bil"]
    }
    
    with open(LOGNEW_PATH, "w") as f:
        json.dump(context, f, indent=2)
        
    # Chỉ log những giá trị lấy được thành công
    valid_context = {k: v for k, v in context.items() if v is not None}
    log(f"✅ Cập nhật context: {valid_context}")
    
    return context

def get_market_context_data():
    try:
        with open(LOGNEW_PATH, "r") as f:
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
