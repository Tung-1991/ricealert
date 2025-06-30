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


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
COOLDOWN_FILE = os.path.join(BASE_DIR, "cooldown_tracker.json")
COOLDOWN_LEVEL_MAP = {
    "1h":    {"WATCHLIST": 300,  "ALERT": 240,  "WARNING": 180,  "CRITICAL": 90},
    "4h":    {"WATCHLIST": 720,  "ALERT": 480,  "WARNING": 360,  "CRITICAL": 240},
    "1d":    {"WATCHLIST": 1800, "ALERT": 1560, "WARNING": 1500, "CRITICAL": 1380}
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
                    if now - datetime.fromisoformat(v) < timedelta(days=2)
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
🔹 Price: {ind['price']:.8f}
📈 EMA20: {ind['ema_20']}
💪 RSI14: {ind['rsi_14']} ({rsi_div})
📉 MACD Line: {ind['macd_line']}
📊 MACD Signal: {ind['macd_signal']} → {macd_cross}
📊 ADX: {adx}
🔺 BB Upper: {ind['bb_upper']}
🔻 BB Lower: {ind['bb_lower']}
🔊 Volume: {ind['volume']} / MA20: {ind['vol_ma20']}
🌀 Fibo 0.618: {ind.get('fib_0_618')}
🕯️ Doji: {doji_note}
🔺 Trend: {trend}
💸 CMF: {cmf}
🧠 Signal: **{signal}** {f'→ {reason}' if reason else ''}"""

        if trade_plan:
            entry = trade_plan.get("entry", 0)
            tp = trade_plan.get("tp", 0)
            sl = trade_plan.get("sl", 0)

            block += f"""
🎯 **Trade Plan**
- Entry: {entry:.8f}
- TP:     {tp:.8f}
- SL:     {sl:.8f}"""

        blocks.append(block)

    return "\n\n".join(blocks)

def send_portfolio_report():
    lines = render_portfolio()
    send_discord_alert("📊 **BÁO CÁO TỔNG TÀI SẢN**\n" + "\n".join(lines))
    time.sleep(3)


def main():
    print("🔁 Bắt đầu vòng check...\n")
    log_lines = []
    symbols = os.getenv("SYMBOLS", "ETHUSDT,AVAXUSDT").split(",")
    intervals = [i.strip() for i in os.getenv("INTERVALS", "1h,4h").split(",")]
    should_report = is_report_time()
    #should_report = True
    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    log_date_dir = os.path.join("log", now.strftime("%Y-%m-%d"))
    os.makedirs(log_date_dir, exist_ok=True)

    cached_data = {"1h": {}, "4h": {}, "1d": {}}
    if "4h" in intervals or "1d" in intervals:
        for symbol in symbols:
            cached_data["1h"][symbol] = get_price_data(symbol, "1h")
    if "1d" in intervals:
        for symbol in symbols:
            cached_data["4h"][symbol] = get_price_data(symbol, "4h")
            cached_data["1d"][symbol] = get_price_data(symbol, "1d")


    last_alert_time = load_cooldown()

    if should_report:
        send_portfolio_report()

    for symbol in symbols:
        try:
            indicator_dict = {}
            sendable_intervals = []
            alert_levels = []

            for interval in intervals:
                if interval in cached_data and symbol in cached_data[interval]:
                    df = cached_data[interval][symbol]
                else:
                    df = get_price_data(symbol, interval)
                ind = calculate_indicators(df, symbol, interval)
                ind["interval"] = interval

                if interval == "1h":
                    ind["rsi_1h"] = ind["rsi_14"]
                    ind["rsi_4h"] = None
                elif interval == "4h":
                    ind_1h = calculate_indicators(cached_data["1h"][symbol], symbol, "1h")
                    ind["rsi_1h"] = ind_1h["rsi_14"]
                    ind["rsi_4h"] = ind["rsi_14"]
                elif interval == "1d":
                    ind_1h = calculate_indicators(cached_data["1h"][symbol], symbol, "1h")
                    ind_4h = calculate_indicators(cached_data["4h"][symbol], symbol, "4h")
                    ind["rsi_1h"] = ind_1h["rsi_14"]
                    ind["rsi_4h"] = ind_4h["rsi_14"]

                signal, _ = check_signal(ind)
                indicator_dict[interval] = ind

                if signal not in ["WATCHLIST", "ALERT", "WARNING", "CRITICAL"]:
                    print(f"🔇 {symbol} - {interval} → {signal} → KHÔNG lưu CSV, KHÔNG gửi Discord")
                    log_lines.append(f"🔇 {symbol} - {interval} → {signal} → KHÔNG lưu CSV, KHÔNG gửi Discord")
                    continue

                cooldown_key = f"{symbol}_{interval}_{signal}"
                cooldown_minutes = COOLDOWN_LEVEL_MAP.get(interval, {}).get(signal, 90)
                last_time = last_alert_time.get(cooldown_key)

                if not last_time or now - last_time >= timedelta(minutes=cooldown_minutes):
                    log_to_csv(
                        symbol=symbol,
                        interval=interval,
                        signal=signal,
                        tag=ind.get("tag", "hold"),
                        price=ind.get("price", 0),
                        trade_plan=ind.get("trade_plan", {}),
                        timestamp=now_str
                    )

                    if signal != "WATCHLIST":
                        print(f"📤 Ghi CSV + chờ gửi Discord: {symbol} - {interval} ({signal})")
                        log_lines.append(f"📤 Ghi CSV + chờ gửi Discord: {symbol} - {interval} ({signal})")
                    else:
                        print(f"👀 {symbol} - {interval} → WATCHLIST → GHI CSV + GỬI DISCORD")
                        log_lines.append(f"👀 {symbol} - {interval} → WATCHLIST → GHI CSV + GỬI DISCORD")

                    sendable_intervals.append(interval)
                    alert_levels.append(signal)
                    last_alert_time[cooldown_key] = now

                else:
                    remaining = cooldown_minutes - int((now - last_time).total_seconds() / 60)
                    print(f"⏳ {symbol} - {interval} ({signal}) → Cooldown còn {remaining} phút → KHÔNG gửi, KHÔNG lưu")
                    log_lines.append(f"⏳ {symbol} - {interval} ({signal}) → Cooldown còn {remaining} phút → KHÔNG gửi, KHÔNG lưu")
                    continue


            filtered_indicator_dict = (
                {iv: indicator_dict[iv] for iv in sendable_intervals}
                if sendable_intervals        # có tín hiệu cần gửi
                else indicator_dict          # chỉ log, không gửi
            )


            report_text = format_symbol_report(symbol, filtered_indicator_dict)
            print(report_text + "\n" + "-" * 50)
            log_lines.append(report_text)

            if sendable_intervals:
                highest = "CRITICAL" if "CRITICAL" in alert_levels else \
                          "WARNING" if "WARNING" in alert_levels else \
                          "ALERT" if "ALERT" in alert_levels else "WATCHLIST"
                icon = {"CRITICAL": "🚨", "WARNING": "⚠️", "ALERT": "📣", "WATCHLIST": "👀"}.get(highest, "📌")
                title = f"{icon} [{symbol}] **{highest}** từ khung {', '.join(sendable_intervals)} | ⏱️ {now_str}"
                order_id_lines = "\n".join([f"🆔 ID: {now_str}\t{symbol}\t{iv}" for iv in sendable_intervals])
                report_text = f"{title}\n{order_id_lines}\n\n{report_text}"
                print(f"📨 Gửi Discord: {symbol} - {', '.join(sendable_intervals)} ({highest})")
                log_lines.append(f"📨 Gửi Discord: {symbol} - {', '.join(sendable_intervals)} ({highest})")
                send_discord_alert(report_text)
                time.sleep(3)

        except Exception as e:
            msg = f"❌ Lỗi xử lý {symbol}: {e}"
            print(msg)
            log_lines.append(msg)

    if log_lines:
        final_log = "\n\n" + ("\n" + "=" * 60 + "\n\n").join(log_lines)
        write_named_log(final_log, os.path.join(log_date_dir, f"{now.strftime('%H%M')}.txt"))

    save_cooldown(last_alert_time)

if __name__ == "__main__":
    main()
