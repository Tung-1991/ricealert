# check_data.py
# -*- coding: utf-8 -*-
"""
Công cụ độc lập để kiểm tra và so sánh dữ liệu giá giữa
môi trường Binance Live và Binance Testnet.

Cách dùng:
1. Lưu file này với tên check_data.py trong cùng thư mục dự án.
2. Chạy từ terminal: python check_data.py
"""
import requests
import pandas as pd
from datetime import datetime

def get_binance_data(symbol, interval, api_url):
    """Hàm lấy dữ liệu nến từ một endpoint API cụ thể."""
    url = f"{api_url}/api/v3/klines"
    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": 5  # Chỉ lấy 5 cây nến cuối cùng để so sánh
    }
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if not data:
            print(f"Không nhận được dữ liệu từ {api_url}")
            return None

        df = pd.DataFrame(data, columns=["timestamp", "open", "high", "low", "close", "volume", "close_time", "qav", "num_trades", "tbbav", "tbqav", "ignore"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df = df[["timestamp", "open", "high", "low", "close", "volume"]].astype({
            "open": float, "high": float, "low": float, "close": float, "volume": float
        })
        return df
    except Exception as e:
        print(f"Lỗi khi lấy dữ liệu từ {api_url}: {e}")
        return None

if __name__ == "__main__":
    SYMBOL = "TAOUSDT"
    INTERVAL = "4h"
    
    LIVE_URL = "https://api.binance.com"
    TESTNET_URL = "https://testnet.binance.vision"

    print("=============================================================")
    print(f"BẮT ĐẦU KIỂM TRA DỮ LIỆU CHO {SYMBOL} - {INTERVAL}")
    print(f"Thời gian hiện tại: {datetime.now()}")
    print("=============================================================\n")

    # Lấy dữ liệu từ môi trường LIVE (Thị trường thật)
    print("--- 1. Đang lấy dữ liệu từ API LIVE (api.binance.com) ---")
    live_data = get_binance_data(SYMBOL, INTERVAL, LIVE_URL)
    if live_data is not None:
        print("✅ Dữ liệu LIVE:")
        print(live_data)
        print("\n")

    # Lấy dữ liệu từ môi trường TESTNET (Thị trường ảo)
    print("--- 2. Đang lấy dữ liệu từ API TESTNET (testnet.binance.vision) ---")
    testnet_data = get_binance_data(SYMBOL, INTERVAL, TESTNET_URL)
    if testnet_data is not None:
        print("✅ Dữ liệu TESTNET:")
        print(testnet_data)
        print("\n")

    print("=============================================================")
    print("KẾT THÚC KIỂM TRA. Hãy so sánh cột 'close' của hai bảng trên.")
    print("=============================================================")


