# -*- coding: utf-8 -*-
import os
import json
from datetime import datetime
from dotenv import load_dotenv
import requests

load_dotenv(dotenv_path="../.env")
WEBHOOK_URL = os.getenv("DISCORD_TRADE_WEBHOOK")
TRADELOG_DIR = "tradelog"
os.makedirs(TRADELOG_DIR, exist_ok=True)

def parse_tabbed_line(line):
    parts = [x.strip() for x in line.split("\t")]
    if len(parts) != 3:
        raise ValueError("❌ Dòng 1 phải gồm 3 trường: timestamp, symbol, interval")
    return parts[0], parts[1].upper(), parts[2]

def parse_trade_plan(plan):
    entry, tp, sl = [float(x.strip()) for x in plan.split("/")]
    return entry, tp, sl

def append_to_json_file(trade):
    date_str = trade["id"].split(" ")[0]
    path = os.path.join(TRADELOG_DIR, f"{date_str}.json")
    if os.path.exists(path):
        with open(path, "r") as f:
            data = json.load(f)
    else:
        data = []

    data.append(trade)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

def send_discord_log(trade):
    coin_qty = round(trade["amount"] / trade["real_entry"], 4)
    content = (
        f"🆕 New Trade Added\n"
        f"📌 ID: {trade['id']}\n"
        f"🪙 Symbol: {trade['symbol']} | Interval: {trade['interval']}\n"
        f"📊 Plan: {trade['trade_plan'].replace('/', ' / ')}\n"
        f"💰 Entry thực tế: {trade['real_entry']}\n"
        f"💸 Vốn: {trade['amount']} USD\n"
        f"🧮 Số lượng: {coin_qty} {trade['symbol'].replace('USDT','')}"
    )
    requests.post(WEBHOOK_URL, json={"content": content})

if __name__ == "__main__":
    print("📥 Dán dòng 1 từ Excel (timestamp, symbol, interval):")
    try:
        line1 = input(">>> ")
        timestamp, symbol, interval = parse_tabbed_line(line1)

        plan = input("📥 Dán dòng 2: trade_plan (entry/tp/sl):\n>>> ").strip()
        entry, tp, sl = parse_trade_plan(plan)

        real_entry = float(input("📥 Dán dòng 3: giá mua thật (real_entry):\n>>> ").strip())

        amount = float(input("📥 Nhập số tiền vào lệnh (USD):\n>>> ").strip())

        trade = {
            "id": timestamp,
            "symbol": symbol,
            "interval": interval,
            "trade_plan": plan,
            "entry": entry,
            "tp": tp,
            "sl": sl,
            "real_entry": real_entry,
            "amount": amount,
            "real_exit": None,
            "pnl_percent": None,
            "status": "open"
        }

        append_to_json_file(trade)
        send_discord_log(trade)
        print(f"✅ Lưu vào tradelog/{timestamp.split()[0]}.json thành công.")

    except Exception as e:
        print(f"❌ Lỗi: {e}")
