# portfolio.py (v2.6 - Sửa lỗi 400 Bad Request & Ghi Log Chi Tiết)
# -*- coding: utf-8 -*-
import os
import time
import hmac
import hashlib
import requests
from urllib.parse import urlencode
from dotenv import load_dotenv
import traceback
from datetime import datetime # Thêm import

load_dotenv()

API_KEY = os.getenv("BINANCE_API_KEY")
SECRET_KEY = os.getenv("BINANCE_SECRET_KEY")

def log_error(message):
    """
    Logs error messages to the console and a specified log file.
    """
    print(message)
    with open("/root/ricealert/log/portfolio_error.log", "a", encoding="utf-8") as f:
        f.write(f"[{datetime.now()}] {message}\n")

def sign_request(params: dict, secret: str) -> str:
    """
    Signs the request parameters with the given secret key.
    """
    query_string = urlencode(params)
    signature = hmac.new(secret.encode(), query_string.encode(), hashlib.sha256).hexdigest()
    return f"{query_string}&signature={signature}"

def make_signed_request(session, base_url, endpoint, params):
    """
    Makes a signed request to the Binance API, handling common errors and logging details.
    """
    timestamp = int(time.time() * 1000)
    # Thêm timestamp và recvWindow vào params
    full_params = {"timestamp": timestamp, "recvWindow": 60000, **params}

    headers = {"X-MBX-APIKEY": API_KEY}
    signed_query = sign_request(full_params, SECRET_KEY)
    url = f"{base_url}{endpoint}?{signed_query}"

    try:
        res = session.get(url, headers=headers, timeout=15)
        res.raise_for_status() # Ném lỗi nếu status code là 4xx hoặc 5xx
        return res.json()
    except requests.exceptions.RequestException as e:
        if e.response is not None:
            log_error(f"❌ Lỗi API cho endpoint {endpoint}: Status {e.response.status_code}, Response: {e.response.text}")
        else:
            log_error(f"❌ Lỗi Request không có response cho endpoint {endpoint}: {e}")
        # log_error(traceback.format_exc()) # Bỏ comment nếu cần debug sâu hơn
        return None

def get_prices(session):
    """
    Fetches current prices from Binance.
    """
    url = "https://api.binance.com/api/v3/ticker/price"
    try:
        res = session.get(url, timeout=15)
        res.raise_for_status()
        data = res.json()
        return {item["symbol"]: float(item["price"]) for item in data}
    except requests.exceptions.RequestException as e:
        log_error(f"❌ Lỗi nghiêm trọng khi lấy giá: {e}")
        return {}

def get_simple_earn(product_type, prices, session):
    """
    Fetches Simple Earn (Flexible/Locked) balances from Binance.
    """
    endpoint_map = {
        "FLEXIBLE": "/sapi/v1/simple-earn/flexible/position",
        "LOCKED": "/sapi/v1/simple-earn/locked/position"
    }
    source_map = { "FLEXIBLE": "Earn Flexible", "LOCKED": "Earn Locked" }

    all_rows = []
    page = 1
    while True:
        data = make_signed_request(session, "https://api.binance.com", endpoint_map[product_type], {"current": page, "size": 100})

        if data is None:
            return []

        if "rows" in data and data["rows"]:
            all_rows.extend(data["rows"])
            if len(data["rows"]) < 100: break
            page += 1
        else:
            if page == 1 and "rows" not in data:
                log_error(f"❌ Lỗi hoặc không có dữ liệu {source_map[product_type]}: {data}")
            break

    balances = []
    for item in all_rows:
        asset = item["asset"]
        amount = float(item.get("totalAmount", item.get("amount", 0)))
        value = 0.0

        # === BẮT ĐẦU THAY ĐỔI ===
        if asset == 'USDT':
            value = amount  # Giá trị của USDT chính là số lượng của nó
        else:
            symbol = asset + "USDT"
            price = prices.get(symbol)
            if price:
                value = amount * price
        # === KẾT THÚC THAY ĐỔI ===

        if value >= 1:
            balances.append({"asset": asset, "amount": amount, "value": value, "source": source_map[product_type]})
            
    return balances

def get_spot_balances(prices, session):
    """
    Fetches Spot account balances from Binance.
    """
    data = make_signed_request(session, "https://api.binance.com", "/api/v3/account", {})
    if data is None or "balances" not in data:
        # make_signed_request đã log lỗi, chỉ cần return rỗng
        return []

    balances = []
    for item in data["balances"]:
        asset = item["asset"]
        total = float(item["free"]) + float(item["locked"])
        if total == 0: continue

        value = 0
        if asset == 'USDT':
            value = total
        else:
            symbol = asset + "USDT"
            price = prices.get(symbol)
            if price:
                value = total * price

        if value >= 1:
            balances.append({"asset": asset, "amount": total, "value": value, "source": "Spot"})
    return balances

def get_account_balances():
    """
    Main function to retrieve and aggregate all account balances (Spot and Earn).
    """
    if not API_KEY or not SECRET_KEY:
        log_error("❌ Thiếu API key/secret")
        return []

    try:
        with requests.Session() as session:
            prices = get_prices(session)
            if not prices: return []

            print("--- Bắt đầu lấy dữ liệu portfolio ---")
            spot = get_spot_balances(prices, session)
            print(f"✅ Tìm thấy {len(spot)} tài sản trong Spot.")

            earn_flexible = get_simple_earn("FLEXIBLE", prices, session)
            print(f"✅ Tìm thấy {len(earn_flexible)} tài sản trong Earn Flexible.")

            earn_locked = get_simple_earn("LOCKED", prices, session)
            print(f"✅ Tìm thấy {len(earn_locked)} tài sản trong Earn Locked.")

            all_balances = spot + earn_flexible + earn_locked

            merged_balances = {}
            for item in all_balances:
                asset = item['asset']
                if asset not in merged_balances:
                    merged_balances[asset] = {"asset": asset, "amount": 0.0, "value": 0.0, "sources": []}

                merged_balances[asset]['amount'] += item['amount']
                merged_balances[asset]['value'] += item['value']
                merged_balances[asset]['sources'].append(item['source'])

            final_balances = []
            for asset, data in merged_balances.items():
                amount_str = f"{data['amount']:.8f}".rstrip('0').rstrip('.')
                final_balances.append({
                    "asset": asset,
                    "amount": amount_str,
                    "value": round(data['value'], 2),
                    "source": ", ".join(sorted(list(set(data['sources']))))
                })

            if not final_balances:
                return [{"asset": "TOTAL", "amount": "-", "value": 0.00, "source": "All"}]

            total_usd = sum(item["value"] for item in final_balances)
            final_balances.sort(key=lambda x: -x["value"])

            final_balances.append({"asset": "TOTAL", "amount": "-", "value": round(total_usd, 2), "source": "All"})
            print("--- Hoàn thành lấy dữ liệu portfolio ---")
            return final_balances

    except Exception as e:
        log_error(f"❌ Lỗi không xác định trong get_account_balances: {e}\n{traceback.format_exc()}")
        return []

if __name__ == "__main__":
    import json
    print("Chạy kiểm tra trực tiếp file portfolio.py (v2.6)...")
    balances = get_account_balances()
    if balances:
        print(json.dumps(balances, indent=2))
