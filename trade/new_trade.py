# new_trade.py (VERSION ID = TIMESTAMP-SYMBOL-INTERVAL)
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
    date_str = trade["in_time"].split(" ")[0]
    path = os.path.join(TRADELOG_DIR, f"{date_str}.json")
    data = []
    if os.path.exists(path):
        with open(path, "r", encoding='utf-8') as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                data = []
    data.append(trade)
    with open(path, "w", encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def update_trade_to_closed(trade_id_to_close):
    found_trade = None
    target_filepath = ""
    all_trades_in_file = []

    for filename in sorted(os.listdir(TRADELOG_DIR)):
        if not filename.endswith(".json"): continue
        filepath = os.path.join(TRADELOG_DIR, filename)
        with open(filepath, "r", encoding='utf-8') as f:
            try:
                trades = json.load(f)
            except json.JSONDecodeError:
                continue
        
        for i, trade in enumerate(trades):
            if trade.get("id") == trade_id_to_close and trade.get("status") == "open":
                found_trade = trade
                target_filepath = filepath
                all_trades_in_file = trades
                break
        if found_trade:
            break

    if not found_trade:
        print(f"❌ Không tìm thấy lệnh mở với ID: {trade_id_to_close}")
        return

    price = get_price(found_trade["symbol"])
    if price is None:
        print("❌ Không lấy được giá market.")
        return
        
    real_entry = float(found_trade["real_entry"])
    pnl = round((price - real_entry) / real_entry * 100, 2)
    found_trade["real_exit"] = price
    found_trade["pnl_percent"] = pnl
    found_trade["entry_exit_pnl"] = f"{real_entry}/{price}/{pnl:+}"
    found_trade["status"] = "closed"

    for i, t in enumerate(all_trades_in_file):
        if t["id"] == trade_id_to_close:
            all_trades_in_file[i] = found_trade
            break
    
    with open(target_filepath, "w", encoding='utf-8') as f:
        json.dump(all_trades_in_file, f, indent=2, ensure_ascii=False)

    print(f"✅ Đã đóng lệnh {found_trade['symbol']} ({found_trade['id']}) với giá market: {price}")

def send_discord_log(trade):
    coin_qty = round(trade["amount"] / trade["real_entry"], 4)
    csv_line = f"{trade['real_entry']}/0/0"
    status = trade.get("status", "open").upper()
    in_time = trade.get("in_time")

    content = (
        f"🆕 [{status}] Lệnh mới\n"
        f"📌 ID: {trade['id']}\n"
        f"🪙 Symbol: {trade['symbol']} ({trade['interval']})\n"
        f"📆 In time: {in_time}\n"
        f"📊 Plan: Entry {trade['entry']:.8f} → TP {trade['tp']:.8f} → SL {trade['sl']:.8f}\n"
        f"💰 Entry: {trade['real_entry']:.8f} | Vốn: {trade['amount']} USD\n"
        f"🧮 Khối lượng: {coin_qty} {trade['symbol'].replace('USDT','')}\n"
        f"📥 CSV: {csv_line}"
    )
    requests.post(WEBHOOK_URL, json={"content": content})

if __name__ == "__main__":
    print("=== Trade CLI ===")
    print("1️⃣ Tạo lệnh mới từ CSV")
    print("2️⃣ Đóng lệnh thủ công (dựa vào CSV)")
    choice = input("👉 Chọn option (1/2): ").strip()

    if choice == "1":
        try:
            print("📥 Dán dòng từ CSV (timestamp<TAB>symbol<TAB>interval):")
            line1 = input(">>> ")
            parts = re.split(r'\s+', line1.strip())
            if len(parts) < 4:
                print("❌ Dòng nhập không hợp lệ, cần định dạng: YYYY-MM-DD HH:MM:SS SYMBOL interval")
                exit(1)
            
            timestamp_from_csv = parts[0] + " " + parts[1]
            symbol = parts[2].upper()
            interval = parts[3]

            # --- TẠO ID DUY NHẤT THEO ĐÚNG YÊU CẦU ---
            unique_id = f"{timestamp_from_csv}-{symbol}-{interval}"
            # ------------------------------------------

            plan = input("📥 Dán dòng 2: trade_plan (entry/tp/sl):\n>>> ").strip()
            entry, tp, sl = [float(x.strip()) for x in plan.split("/")]

            real_entry = float(input("📥 Dán dòng 3: giá mua thật (real_entry):\n>>> ").strip())
            amount = float(input("📥 Nhập số tiền vào lệnh (USD):\n>>> ").strip())
            
            in_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            trade = {
                "id": unique_id, # <-- SỬ DỤNG ID MỚI
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
                "status": "open",
                "entry_exit_pnl": f"{real_entry}/0/0",
                "in_time": in_time
            }

            append_to_json_file(trade)
            send_discord_log(trade)
            print(f"✅ Đã tạo lệnh với ID duy nhất: {unique_id}")

        except Exception as e:
            print(f"❌ Lỗi: {e}")

    elif choice == "2":
        try:
            print("📥 Dán dòng từ CSV của lệnh cần đóng (timestamp<TAB>symbol<TAB>interval):")
            line = input(">>> ").strip()
            parts = re.split(r'\s+', line.strip())
            if len(parts) < 4:
                print("❌ Dòng nhập không hợp lệ, cần định dạng: YYYY-MM-DD HH:MM:SS SYMBOL interval")
                exit(1)
            
            timestamp_to_close = parts[0] + " " + parts[1]
            symbol_to_close = parts[2].upper()
            interval_to_close = parts[3]
            
            # Tạo lại ID để tìm kiếm
            trade_id_to_close = f"{timestamp_to_close}-{symbol_to_close}-{interval_to_close}"
            print(f"Đang tìm và đóng lệnh có ID: {trade_id_to_close}")
            update_trade_to_closed(trade_id_to_close)

        except Exception as e:
            print(f"❌ Lỗi: {e}")

    else:
        print("❌ Lựa chọn không hợp lệ.")
