# -*- coding: utf-8 -*-
import os
import json
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv(dotenv_path="../.env")
WEBHOOK_URL = os.getenv("DISCORD_TRADE_WEBHOOK")
TRADELOG_DIR = "/root/ricealert/trade/tradelog"

def get_price(symbol):
    url = f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={symbol}"
    try:
        res = requests.get(url, timeout=10)
        return float(res.json()["price"])
    except:
        return None

def update_trade_file(filepath, trades):
    with open(filepath, "w") as f:
        json.dump(trades, f, indent=2)

def format_hold_time(start_time_str, end_time_str):
    fmt = "%Y-%m-%d %H:%M:%S"
    start = datetime.strptime(start_time_str, fmt)
    end = datetime.strptime(end_time_str, fmt)
    diff = (end - start).total_seconds()
    if diff < 60:
        return f"{int(diff)} giây"
    elif diff < 3600:
        return f"{int(diff // 60)} phút"
    elif diff < 86400:
        return f"{round(diff / 3600, 1)} giờ"
    else:
        return f"{round(diff / 86400, 1)} ngày"

def send_discord_result(trade, status_override=None):
    status_map = {
        "tp": "✅ [TP HIT]",
        "sl": "❌ [SL HIT]",
        "closed": "📦 [CLOSED]",
        "cancelled": "⚠️ [CANCELLED]"
    }
    status = status_override or trade.get("status", "unknown")
    icon = status_map.get(status, "📌")

    entry = float(trade["real_entry"])
    exit_price = float(trade["real_exit"])
    amount = float(trade["amount"])
    pnl = float(trade["pnl_percent"])
    pnl_usd = round(amount * pnl / 100, 2)
    final_amount = round(amount + pnl_usd, 2)
    coin_qty = round(amount / entry, 4)

    out_time = trade.get("out_time", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    hold_time = format_hold_time(trade.get("in_time", trade["id"]), out_time)

    content = (
        f"{icon} Lệnh đã đóng\n"
        f"📌 ID: {trade['id']}\t{trade['symbol']}\t{trade['interval']}\n"
        f"📆 Out time: {out_time} | ⏱️ Đã giữ: {hold_time}\n"
        f"💰 Entry: {entry:.8f} → Exit: {exit_price:.8f}\n"
        f"🧮 Khối lượng: {coin_qty} {trade['symbol'].replace('USDT','')} | Vốn: {amount} USD\n"
        f"{'📈' if pnl >= 0 else '📉'} PnL: {pnl:+}% → {pnl_usd:+} USD | Tiền: {final_amount} USD\n"
        f"📋 Result: {entry:.8f}/{exit_price:.8f}/{pnl:+}"
    )

    requests.post(WEBHOOK_URL, json={"content": content})

def check_trades():
    for filename in os.listdir(TRADELOG_DIR):
        if not filename.endswith(".json"):
            continue

        filepath = os.path.join(TRADELOG_DIR, filename)
        with open(filepath, "r") as f:
            trades = json.load(f)

        updated = False
        for trade in trades:
            if trade.get("reported"):
                continue

            status = trade.get("status", "")
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            if status == "open":
                price = get_price(trade["symbol"])
                if price is None:
                    continue

                hit_tp = price >= trade["tp"]
                hit_sl = price <= trade["sl"]

                if hit_tp or hit_sl:
                    entry = float(trade["real_entry"])
                    pnl = round((price - entry) / entry * 100, 2)
                    trade["real_exit"] = price
                    trade["pnl_percent"] = pnl
                    trade["status"] = "tp" if hit_tp else "sl"
                    trade["entry_exit_pnl"] = f"{entry}/{price}/{pnl:+}"
                    trade["out_time"] = now_str
                    trade["reported"] = True
                    send_discord_result(trade, status_override=trade["status"])
                    updated = True

            elif status == "closed":
                entry = float(trade["real_entry"])
                price = trade.get("real_exit") or get_price(trade["symbol"])
                if price:
                    price = float(price)
                    pnl = round((price - entry) / entry * 100, 2)
                    trade["real_exit"] = price
                    trade["pnl_percent"] = pnl
                    trade["entry_exit_pnl"] = f"{entry}/{price}/{pnl:+}"
                    trade["out_time"] = now_str
                trade["reported"] = True
                send_discord_result(trade, status_override="closed")
                updated = True

        if updated:
            update_trade_file(filepath, trades)

if __name__ == "__main__":
    check_trades()

