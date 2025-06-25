# portfolio.py (final version with Earn Flexible + Earn Locked)
# -*- coding: utf-8 -*-
import os
import time
import hmac
import hashlib
import requests
from urllib.parse import urlencode
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("BINANCE_API_KEY")
SECRET_KEY = os.getenv("BINANCE_SECRET_KEY")

def sign_request(params: dict, secret: str) -> str:
    query_string = urlencode(params)
    signature = hmac.new(secret.encode(), query_string.encode(), hashlib.sha256).hexdigest()
    return f"{query_string}&signature={signature}"

def get_prices():
    url = "https://api.binance.com/api/v3/ticker/price"
    res = requests.get(url, timeout=10)
    data = res.json()
    return {item["symbol"]: float(item["price"]) for item in data}

def get_earn_flexible(prices):
    timestamp = int(time.time() * 1000)
    params = {"timestamp": timestamp, "recvWindow": 60000}
    headers = {"X-MBX-APIKEY": API_KEY}
    signed = sign_request(params, SECRET_KEY)
    url = f"https://api.binance.com/sapi/v1/simple-earn/flexible/position?{signed}"

    res = requests.get(url, headers=headers, timeout=10)
    data = res.json()
    if "rows" not in data:
        print(f"❌ Lỗi earn flexible: {data}")
        return []

    data = data["rows"]

    balances = []
    for item in data:
        asset = item["asset"]
        amount = float(item["totalAmount"])
        symbol = asset + "USDT"
        price = prices.get(symbol)
        if price:
            value = amount * price
            if value >= 1:
                balances.append({"asset": asset, "amount": round(amount, 8), "value": round(value, 2), "source": "Earn Flexible"})
    return balances

def get_earn_locked(prices):
    timestamp = int(time.time() * 1000)
    params = {"timestamp": timestamp, "recvWindow": 60000}
    headers = {"X-MBX-APIKEY": API_KEY}
    signed = sign_request(params, SECRET_KEY)
    url = f"https://api.binance.com/sapi/v1/simple-earn/locked/position?{signed}"

    res = requests.get(url, headers=headers, timeout=10)
    data = res.json()
    if "rows" not in data:
        print(f"❌ Lỗi earn locked: {data}")
        return []
    data = data["rows"]


    balances = []
    for item in data:
        asset = item["asset"]
        amount = float(item["amount"])
        symbol = asset + "USDT"
        price = prices.get(symbol)
        if price:
            value = amount * price
            if value >= 1:
                balances.append({"asset": asset, "amount": round(amount, 8), "value": round(value, 2), "source": "Earn Locked"})
    return balances

def get_spot_balances(prices):
    timestamp = int(time.time() * 1000)
    params = {"timestamp": timestamp, "recvWindow": 60000}
    headers = {"X-MBX-APIKEY": API_KEY}
    signed = sign_request(params, SECRET_KEY)
    url = f"https://api.binance.com/api/v3/account?{signed}"

    res = requests.get(url, headers=headers, timeout=10)
    data = res.json()
    if "balances" not in data:
        print(f"❌ Lỗi spot: {data}")
        return []

    balances = []
    for item in data["balances"]:
        asset = item["asset"]
        total = float(item["free"]) + float(item["locked"])
        if total == 0:
            continue
        symbol = asset + "USDT"
        price = prices.get(symbol)
        if price:
            value = total * price
            if value >= 1:
                balances.append({"asset": asset, "amount": round(total, 8), "value": round(value, 2), "source": "Spot"})
    return balances

def get_account_balances():
    if not API_KEY or not SECRET_KEY:
        print("❌ Thiếu API key/secret")
        return []

    try:
        prices = get_prices()
        spot = get_spot_balances(prices)
        earn_flexible = get_earn_flexible(prices)
        earn_locked = get_earn_locked(prices)

        all_balances = spot + earn_flexible + earn_locked
        total_usd = sum(item["value"] for item in all_balances)
        all_balances.sort(key=lambda x: -x["value"])

        all_balances.append({"asset": "TOTAL", "amount": "-", "value": round(total_usd, 2), "source": "All"})

        return all_balances

    except Exception as e:
        print(f"❌ Lỗi khi xử lý portfolio: {e}")
        return []
