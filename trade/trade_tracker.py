# -*- coding: utf-8 -*-
import os
import json
import requests
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

def send_discord_result(trade):
    status_icon = "✅ [TP HIT]" if trade["status"] == "tp" else "❌ [SL HIT]"
    pnl_usd = round(trade["amount"] * trade["pnl_percent"] / 100, 2)
    coin_qty = round(trade["amount"] / trade["real_entry"], 4)

    content = (
        f"{status_icon} {trade['symbol']} ({trade['interval']})\n"
        f"🆔 ID: {trade['id']}\n"
        f"💰 Entry: {trade['real_entry']} | 💸 Vốn: {trade['amount']} USD | 🧮 SL: {coin_qty} {trade['symbol'].replace('USDT','')}\n"
        f"{'📈' if trade['pnl_percent'] >= 0 else '📉'} PnL: {trade['pnl_percent']}% | 💸 {pnl_usd:+} USD"
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
            if trade["status"] != "open":
                continue

            price = get_price(trade["symbol"])
            if price is None:
                continue

            hit_tp = price >= trade["tp"]
            hit_sl = price <= trade["sl"]

            if hit_tp or hit_sl:
                trade["real_exit"] = price
                entry = trade["real_entry"]
                trade["pnl_percent"] = round((price - entry) / entry * 100, 2)
                trade["status"] = "tp" if hit_tp else "sl"
                send_discord_result(trade)
                updated = True

        if updated:
            update_trade_file(filepath, trades)

if __name__ == "__main__":
    check_trades()
