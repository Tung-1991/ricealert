# -*- coding: utf-8 -*-
from dotenv import load_dotenv
load_dotenv()

import os
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

def main():
    print("🔁 Bắt đầu vòng check...\n")

    symbols = os.getenv("SYMBOLS", "ETHUSDT").split(",")
    intervals = os.getenv("INTERVALS", "1h").split(",")
    should_report = is_report_time()
    portfolio_lines = render_portfolio() if should_report else ["(ẩn - chỉ hiển thị lúc gửi report)"]

    for symbol in symbols:
        for interval in intervals:
            try:
                df = get_price_data(symbol, interval)
                indicators = calculate_indicators(df, symbol, interval)
                signal, reason = check_signal(indicators)

                print(f"\n📊 {symbol} ({interval}) Indicator Report")
                print(f"🔹 Price: {indicators['price']}")
                print(f"📈 EMA20: {indicators['ema_20']}")
                print(f"💪 RSI14: {indicators['rsi_14']}")
                print(f"🔺 BB Upper: {indicators['bb_upper']}")
                print(f"🔻 BB Lower: {indicators['bb_lower']}")
                print(f"📉 MACD Line: {indicators['macd_line']}")
                print(f"📊 MACD Signal: {indicators['macd_signal']}")
                print(f"🔊 Volume: {indicators['volume']} / MA20: {indicators['vol_ma20']}")
                print(f"🌀 Fibo 0.618: {indicators['fib_0_618']}")
                doji_note = f"{indicators['doji_type'].capitalize()} Doji" if indicators.get("doji_type") else "No"
                print(f"🕯️ Doji: {doji_note}")
                print(f"🧠 Signal: {signal} {'→ ' + reason if reason else ''}")

                # Quyết định có gửi hay không
                if should_report or signal in ["ALERT", "CRITICAL"]:
                    message = f"""📊 **{symbol} ({interval}) Report**
🔹 Price: {indicators['price']}
📈 EMA20: {indicators['ema_20']}
💪 RSI14: {indicators['rsi_14']}
🔺 BB Upper: {indicators['bb_upper']}
🔻 BB Lower: {indicators['bb_lower']}
📉 MACD Line: {indicators['macd_line']}
📊 MACD Signal: {indicators['macd_signal']}
🔊 Volume: {indicators['volume']} / MA20: {indicators['vol_ma20']}
🌀 Fibo 0.618: {indicators['fib_0_618']}
🕯️ Doji: {doji_note}
🧠 Signal: **{signal}** {f"→ {reason}" if reason else ""}

💰 **Portfolio**
""" + "\n".join(portfolio_lines)

                    send_discord_alert(message)

            except Exception as e:
                print(f"❌ Lỗi {symbol} ({interval}): {e}")

if __name__ == "__main__":
    main()

