# -*- coding: utf-8 -*-
from dotenv import load_dotenv
load_dotenv()

import os
import time
import json
from datetime import datetime, timedelta
from portfolio import get_account_balances
from indicator import get_price_data, calculate_indicators
from signal_logic import check_signal
from alert_manager import send_discord_alert
from csv_logger import log_to_csv, write_named_log

COOLDOWN_FILE = "cooldown_tracker.json"
COOLDOWN_MAP = {
    "1h": 510,   # 8h30
    "4h": 750,    # 12h30
    "1d": 1470     # 24h30
}

def load_cooldown():
    if os.path.exists(COOLDOWN_FILE):
        try:
            with open(COOLDOWN_FILE, "r") as f:
                data = json.load(f)
                now = datetime.now()
                return {
                    k: datetime.fromisoformat(v)
                    for k, v in data.items()
                    if now - datetime.fromisoformat(v) < timedelta(hours=24)
                }
        except Exception as e:
            print(f"⚠️ Không thể load cooldown file: {e}")
    return {}

def save_cooldown(cooldown_dict):
    with open(COOLDOWN_FILE, "w") as f:
        data = {k: v.isoformat() for k, v in cooldown_dict.items()}
        json.dump(data, f)

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

def format_symbol_report(symbol, indicator_dict):
    blocks = []
    for interval, ind in indicator_dict.items():
        macd_cross = ind.get("macd_cross", "N/A")
        adx = ind.get("adx", "N/A")
        rsi_div = ind.get("rsi_divergence", "None")
        trade_plan = ind.get("trade_plan", {})
        doji_note = f"{ind['doji_type'].capitalize()} Doji" if ind.get("doji_type") else "No"
        trend = ind.get("trend", "unknown")
        cmf = ind.get("cmf", "N/A")
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
🔺 Trend: {trend}
💸 CMF: {cmf}
🧠 Signal: **{signal}** {f'→ {reason}' if reason else ''}"""

        if signal in ["ALERT", "CRITICAL"]:
            block += f"""
🎯 **Trade Plan**
- Entry: {trade_plan.get('entry')}
- TP:     {trade_plan.get('tp')}
- SL:     {trade_plan.get('sl')}"""
        blocks.append(block)

    return "\n\n".join(blocks)

def main():
    print("🔁 Bắt đầu vòng check...\n")
    symbols = os.getenv("SYMBOLS", "ETHUSDT,AVAXUSDT").split(",")
    intervals = [i.strip() for i in os.getenv("INTERVALS", "1h,4h").split(",")]
    should_report = is_report_time()
    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")

    last_alert_time = load_cooldown()
    all_logs = []

    if should_report:
        print(f"⏱️ {now_str} | Gửi portfolio lên Discord...")
        portfolio_lines = render_portfolio()
        message = f"⏱️ **Report Time: {now_str}**\n\n💰 **Portfolio**\n" + "\n".join(portfolio_lines)
        send_discord_alert(message)
    else:
        print("⏩ Không phải giờ gửi report, bỏ qua gửi portfolio")

    for symbol in symbols:
        try:
            indicator_dict = {}
            sendable_intervals = []
            alert_levels = []

            for interval in intervals:
                df = get_price_data(symbol, interval)
                ind = calculate_indicators(df, symbol, interval)
                indicator_dict[interval] = ind
                ind["interval"] = interval
                sig, _ = check_signal(ind)
                key = f"{symbol}_{interval}"

                if sig in ["ALERT", "CRITICAL"]:
                    last_time = last_alert_time.get(key)
                    cooldown_minutes = COOLDOWN_MAP.get(interval, 90)
                    if not last_time or now - last_time >= timedelta(minutes=cooldown_minutes):
                        log_to_csv(
                            symbol=symbol,
                            interval=interval,
                            signal=sig,
                            tag=ind.get("tag", "swing"),
                            price=ind["price"] if ind["price"] is not None else 0,
                            trade_plan=ind.get("trade_plan", {}),
                            timestamp=now_str
                        )
                        print(f"📤 Đã lưu vào CSV: {symbol} - {interval} ({sig})")
                        sendable_intervals.append(interval)
                        alert_levels.append(sig)
                        last_alert_time[key] = now
                    else:
                        print(f"⏳ {symbol} - {interval} trong cooldown, không gửi Discord và không ghi CSV")

            report_text = format_symbol_report(symbol, indicator_dict)
            print(report_text + "\n" + "-"*50)
            all_logs.append(report_text)

            if should_report or sendable_intervals:
                if sendable_intervals:
                    level = "CRITICAL" if "CRITICAL" in alert_levels else "ALERT"
                    icon = "🚨" if level == "CRITICAL" else "📣"
                    title = f"{icon} [{symbol}] **{level}** từ khung {', '.join(sendable_intervals)} | ⏱️ {now_str}"
                    report_text = f"{title}\n\n{report_text}"
                send_discord_alert(report_text)
                time.sleep(3)

        except Exception as e:
            print(f"❌ Lỗi xử lý {symbol}: {e}")

    if all_logs:
        full_log = "\n\n" + ("\n" + "="*60 + "\n\n").join(all_logs)
        write_named_log(full_log, f"{now.strftime('%H%M')}.txt")

    save_cooldown(last_alert_time)

if __name__ == "__main__":
    main()

