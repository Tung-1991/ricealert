# -*- coding: utf-8 -*-
import os
import json
import re
from datetime import datetime
from dotenv import load_dotenv
import requests

load_dotenv(dotenv_path="../.env")
WEBHOOK_URL = os.getenv("DISCORD_TRADE_WEBHOOK")
TRADELOG_DIR = "tradelog"
os.makedirs(TRADELOG_DIR, exist_ok=True)

def get_price(symbol):
    url = f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={symbol}"
    try:
        res = requests.get(url, timeout=10)
        return float(res.json()["price"])
    except:
        return None

def append_to_json_file(trade):
    date_str = trade["id"].split(" ")[0]
    path = os.path.join(TRADELOG_DIR, f"{date_str}.json")
    data = []
    if os.path.exists(path):
        with open(path, "r") as f:
            data = json.load(f)
    data.append(trade)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

def update_trade_to_closed(timestamp, symbol, interval):
    date_str = timestamp.split(" ")[0]
    path = os.path.join(TRADELOG_DIR, f"{date_str}.json")
    if not os.path.exists(path):
        print("❌ Không tìm thấy file JSON.")
        return

    with open(path, "r") as f:
        data = json.load(f)

    found = False
    for trade in data:
        if (
            trade.get("id") == timestamp and
            trade.get("symbol") == symbol and
            trade.get("interval") == interval and
            trade.get("status") == "open"
        ):
            price = get_price(trade["symbol"])
            if price is None:
                print("❌ Không lấy được giá market.")
                return
            real_entry = float(trade["real_entry"])
            pnl = round((price - real_entry) / real_entry * 100, 2)
            trade["real_exit"] = price
            trade["pnl_percent"] = pnl
            trade["entry_exit_pnl"] = f"{real_entry}/{price}/{pnl:+}"
            trade["status"] = "closed"
            found = True
            break

    if found:
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        print(f"✅ Đã đóng lệnh {timestamp} | {symbol} ({interval}) với giá market: {price}")
    else:
        print("❌ Không tìm thấy lệnh cần đóng.")

def send_discord_log(trade):
    coin_qty = round(trade["amount"] / trade["real_entry"], 4)
    csv_line = f"{trade['real_entry']}/0/0"
    status = trade.get("status", "open").upper()
    in_time = trade.get("in_time", trade["id"])

    content = (
        f"🆕 [{status}] Lệnh mới\n"
        f"📌 ID: {trade['id']}\t{trade['symbol']}\t{trade['interval']}\n"
        f"📆 In time: {in_time}\n"
        f"📊 Plan: Entry {trade['entry']} → TP {trade['tp']} → SL {trade['sl']}\n"
        f"💰 Entry: {trade['real_entry']} | Vốn: {trade['amount']} USD\n"
        f"🧮 Khối lượng: {coin_qty} {trade['symbol'].replace('USDT','')}\n"
        f"📥 CSV: {csv_line}"
    )
    requests.post(WEBHOOK_URL, json={"content": content})

if __name__ == "__main__":
    print("=== Trade CLI ===")
    print("1️⃣ Tạo lệnh mới")
    print("2️⃣ Đóng lệnh thủ công (tự động lấy giá market)")
    choice = input("👉 Chọn option (1/2): ").strip()

    if choice == "1":
        try:
            print("📥 Dán dòng 1 từ Excel (timestamp<TAB>symbol<TAB>interval):")
            line1 = input(">>> ")
            parts = re.split(r"\s+", line1.strip())
            if len(parts) != 3:
                print("❌ Dòng nhập không hợp lệ, cần định dạng: timestamp    SYMBOL    interval")
                exit(1)
            timestamp, symbol, interval = parts

            plan = input("📥 Dán dòng 2: trade_plan (entry/tp/sl):\n>>> ").strip()
            entry, tp, sl = [float(x.strip()) for x in plan.split("/")]

            real_entry = float(input("📥 Dán dòng 3: giá mua thật (real_entry):\n>>> ").strip())
            amount = float(input("📥 Nhập số tiền vào lệnh (USD):\n>>> ").strip())
            in_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            trade = {
                "id": timestamp,
                "symbol": symbol.upper(),
                "interval": interval,
                "trade_plan": plan,
                "entry": entry,
                "tp": tp,
                "sl": sl,
                "real_entry": real_entry,
                "amount": amount,
                "real_exit": None,
                "pnl_percent": None,
                "status": "open",
                "entry_exit_pnl": f"{real_entry}/0/0",
                "in_time": in_time
            }

            append_to_json_file(trade)
            send_discord_log(trade)
            print(f"✅ Đã lưu vào tradelog/{timestamp.split()[0]}.json")
        except Exception as e:
            print(f"❌ Lỗi: {e}")

    elif choice == "2":
        try:
            print("📥 Dán dòng từ Excel: timestamp<TAB>symbol<TAB>interval:")
            line = input(">>> ").strip()
            parts = re.split(r"\s+", line)
            if len(parts) != 3:
                print("❌ Dòng nhập không hợp lệ, cần định dạng: timestamp    SYMBOL    interval")
                exit(1)
            timestamp, symbol, interval = parts
            update_trade_to_closed(timestamp, symbol.upper(), interval)
        except Exception as e:
            print(f"❌ Lỗi: {e}")

    else:
        print("❌ Lựa chọn không hợp lệ.")

