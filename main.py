# -*- coding: utf-8 -*-
from dotenv import load_dotenv
load_dotenv()

import os
import time
from datetime import datetime
from portfolio import get_account_balances
from indicator import get_price_data, calculate_indicators
from signal_logic import check_signal
from alert_manager import send_discord_alert

def is_report_time():
    now = datetime.now()
    current_time = now.strftime("%H:%M")
    report_times = os.getenv("REPORT_TIMES", "08:00,20:00").split(",")
    return current_time in report_times

def render_portfolio():
    balances = get_account_balances()
    spot = [b for b in balances if b["source"] == "Spot"]
    flexible = [b for b in balances if b["source"] == "Earn Flexible"]
    locked = [b for b in balances if b["source"] == "Earn Locked"]
    total = [b for b in balances if b["source"] == "All"]

    def render_section(title, data):
        section_lines = []
        if data:
            section_lines.append(f"\n{title}")
            for b in data:
                section_lines.append(f"🪙 {b['asset']}: {b['amount']} ≈ ${b['value']}")
            section_total = sum(b["value"] for b in data)
            section_lines.append(f"🔢 Tổng ({title.strip()}): ${round(section_total, 2)}")
        return section_lines

    print("\n💰 Portfolio hiện tại:")
    portfolio_lines = []
    portfolio_lines += render_section("📦 Spot:", spot)
    portfolio_lines += render_section("🪴 Earn Flexible:", flexible)
    portfolio_lines += render_section("🔒 Earn Locked:", locked)

    for line in portfolio_lines:
        print(line)

    if total:
        total_line = f"\n💵 Tổng tài sản: ${total[0]['value']}"
        print(total_line)
        portfolio_lines.append(total_line.replace("💵", "\n💵"))

    return portfolio_lines

def format_symbol_report(symbol, indicators_1h, indicators_4h):
    def format_block(ind, interval):
        macd_cross = ind.get("macd_cross", "N/A")
        adx = ind.get("adx", "N/A")
        rsi_div = ind.get("rsi_divergence", "None")
        trade_plan = ind.get("trade_plan", {})
        doji_note = f"{ind['doji_type'].capitalize()} Doji" if ind.get("doji_type") else "No"
        signal, reason = check_signal(ind)

        block = f"""📊 **{symbol} ({interval})**
🔹 Price: {ind['price']}
📈 EMA20: {ind['ema_20']}
💪 RSI14: {ind['rsi_14']} ({rsi_div})
📉 MACD Line: {ind['macd_line']}
📊 MACD Signal: {ind['macd_signal']} → {macd_cross}
📊 ADX: {adx}
🔺 BB Upper: {ind['bb_upper']}
🔻 BB Lower: {ind['bb_lower']}
🔊 Volume: {ind['volume']} / MA20: {ind['vol_ma20']}
🌀 Fibo 0.618: {ind['fib_0_618']}
🕯️ Doji: {doji_note}
🧠 Signal: **{signal}** {f"→ {reason}" if reason else ""}"""

        if signal in ["ALERT", "CRITICAL"]:
            block += f"""\n🎯 **Trade Plan**
- Entry: {trade_plan.get('entry')}
- TP:     {trade_plan.get('tp')}
- SL:     {trade_plan.get('sl')}"""
        return block

    return f"{format_block(indicators_1h, '1h')}\n\n{format_block(indicators_4h, '4h')}"

def main():
    print("🔁 Bắt đầu vòng check...\n")
    symbols = os.getenv("SYMBOLS", "ETHUSDT,AVAXUSDT,INJUSDT,LINKUSDT,SUIUSDT").split(",")
    should_report = is_report_time()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if should_report:
        print(f"⏱️ {now} | Gửi portfolio lên Discord...")
        portfolio_lines = render_portfolio()
        message = f"⏱️ **Report Time: {now}**\n\n💰 **Portfolio**\n" + "\n".join(portfolio_lines)
        send_discord_alert(message)
    else:
        print("⏩ Không phải giờ gửi report, bỏ qua gửi portfolio")

    for symbol in symbols:
        try:
            df_1h = get_price_data(symbol, "1h")
            ind_1h = calculate_indicators(df_1h, symbol, "1h")
            signal_1h, _ = check_signal(ind_1h)

            df_4h = get_price_data(symbol, "4h")
            ind_4h = calculate_indicators(df_4h, symbol, "4h")
            signal_4h, _ = check_signal(ind_4h)

            report_text = format_symbol_report(symbol, ind_1h, ind_4h)
            print(report_text + "\n" + "-" * 50)

            if should_report or signal_1h in ["ALERT", "CRITICAL"] or signal_4h in ["ALERT", "CRITICAL"]:
                title = ""
                if not should_report:
                    active_signal = signal_1h if signal_1h != "HOLD" else signal_4h
                    title = f"🚨 **[{symbol}] Cảnh báo {active_signal}** | ⏱️ {now}"
                report_text = f"{title}\n\n{report_text}" if title else report_text
                send_discord_alert(report_text)
                time.sleep(3)

        except Exception as e:
            print(f"❌ Lỗi xử lý {symbol}: {e}")

if __name__ == "__main__":
    main()
