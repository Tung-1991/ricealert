# portfolio.py (v2.4 - Robust & Correct: Fixes USDT bug, handles instability and pagination)
# -*- coding: utf-8 -*-
import os
import time
import hmac
import hashlib
import requests
from urllib.parse import urlencode
from dotenv import load_dotenv
import traceback

load_dotenv()

API_KEY = os.getenv("BINANCE_API_KEY")
SECRET_KEY = os.getenv("BINANCE_SECRET_KEY")

def sign_request(params: dict, secret: str) -> str:
    query_string = urlencode(params)
    signature = hmac.new(secret.encode(), query_string.encode(), hashlib.sha256).hexdigest()
    return f"{query_string}&signature={signature}"

def get_prices(session):
    url = "https://api.binance.com/api/v3/ticker/price"
    try:
        res = session.get(url, timeout=15)
        res.raise_for_status()
        data = res.json()
        return {item["symbol"]: float(item["price"]) for item in data}
    except requests.exceptions.RequestException as e:
        print(f"❌ Lỗi nghiêm trọng khi lấy giá: {e}")
        return {}

def get_simple_earn(product_type, prices, session):
    endpoint_map = {
        "FLEXIBLE": "/sapi/v1/simple-earn/flexible/position",
        "LOCKED": "/sapi/v1/simple-earn/locked/position"
    }
    source_map = { "FLEXIBLE": "Earn Flexible", "LOCKED": "Earn Locked" }
    
    all_rows = []
    page = 1
    while True:
        timestamp = int(time.time() * 1000)
        params = {"timestamp": timestamp, "recvWindow": 60000, "current": page, "size": 100}
        headers = {"X-MBX-APIKEY": API_KEY}
        signed = sign_request(params, SECRET_KEY)
        url = f"https://api.binance.com{endpoint_map[product_type]}?{signed}"

        try:
            res = session.get(url, headers=headers, timeout=15)
            res.raise_for_status()
            data = res.json()
            
            if "rows" in data and data["rows"]:
                all_rows.extend(data["rows"])
                if len(data["rows"]) < 100: break
                page += 1
            else:
                if page == 1 and "rows" not in data:
                     print(f"❌ Lỗi hoặc không có dữ liệu {source_map[product_type]}: {data}")
                break
        except requests.exceptions.RequestException as e:
            print(f"❌ Lỗi khi gọi API {source_map[product_type]} trang {page}: {e}")
            return []

    balances = []
    for item in all_rows:
        asset = item["asset"]
        amount = float(item.get("totalAmount", item.get("amount", 0)))
        symbol = asset + "USDT"
        price = prices.get(symbol)
        if price:
            value = amount * price
            if value >= 1:
                balances.append({"asset": asset, "amount": amount, "value": value, "source": source_map[product_type]})
    return balances

def get_spot_balances(prices, session):
    timestamp = int(time.time() * 1000)
    params = {"timestamp": timestamp, "recvWindow": 60000}
    headers = {"X-MBX-APIKEY": API_KEY}
    signed = sign_request(params, SECRET_KEY)
    url = f"https://api.binance.com/api/v3/account?{signed}"

    try:
        res = session.get(url, headers=headers, timeout=15)
        res.raise_for_status()
        data = res.json()
        if "balances" not in data:
            print(f"❌ Lỗi spot: {data}")
            return []
    except requests.exceptions.RequestException as e:
        print(f"❌ Lỗi khi gọi API Spot: {e}")
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
    if not API_KEY or not SECRET_KEY:
        print("❌ Thiếu API key/secret")
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
        print(f"❌ Lỗi nghiêm trọng khi xử lý portfolio: {e}")
        print(traceback.format_exc())
        return []

if __name__ == "__main__":
    import json
    print("Chạy kiểm tra trực tiếp file portfolio.py...")
    balances = get_account_balances()
    if balances:
        print(json.dumps(balances, indent=2))
