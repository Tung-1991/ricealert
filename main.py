# -*- coding: utf-8 -*-
"""RiceAlert – main runner

* 08:00 & 20:00 (report time):
  - Always send Discord alerts for **all intervals** and a full portfolio report.
  - **Do not** write to CSV or trigger quality alerts.
* Every 30 minutes via crontab (non‑report time):
  - **Stream 1 (General Alerts):** Sends a summary of all interesting signals
    (WATCHLIST, ALERT, etc.) that are off cooldown to a general channel (#alert).
  - **Stream 2 (Quality Alerts):** Independently evaluates signals. If a signal
    shows a significant score (BUY/SELL opportunity) AND meets its own cooldown
    criteria (including bypassing general cooldown for major score changes),
    a high-priority alert is sent to an order channel (#order) and the event is logged to CSV.

This file is fully self‑contained and safe to run with `python -m py_compile`.
"""

from dotenv import load_dotenv
load_dotenv()

import os
import time
import json
import pandas as pd
from datetime import datetime, timedelta
# Import các module gốc của bạn
from portfolio import get_account_balances
from indicator import get_price_data, calculate_indicators
from signal_logic import check_signal
from alert_manager import send_discord_alert
from csv_logger import log_to_csv, write_named_log # Dùng bản gốc của bạn!

# --- TÍCH HỢP CÁC FILE MỚI ĐƯỢC TẠO ---
from trade_advisor import get_advisor_decision
from order_alerter import send_opportunity_alert
# --- KẾT THÚC TÍCH HỢP ---


# ---------------------------------------------------------------------------
# Constants & config ---------------------------------------------------------
# ---------------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Cooldown cho alert chung (Stream 1)
COOLDOWN_FILE = os.path.join(BASE_DIR, "cooldown_tracker.json")
# State & Cooldown cho alert chất lượng cao (Stream 2)
ADVISOR_STATE_FILE = os.path.join(BASE_DIR, "advisor_state.json")

COOLDOWN_LEVEL_MAP = {
    "1h":    {"WATCHLIST": 300,  "ALERT": 240,  "WARNING": 180,  "CRITICAL":  90},
    "4h":    {"WATCHLIST": 720,  "ALERT": 480,  "WARNING": 360,  "CRITICAL": 240},
    "1d":    {"WATCHLIST": 1800, "ALERT": 1560, "WARNING": 1500, "CRITICAL": 1380},
}

SEND_LEVELS = ["WATCHLIST", "ALERT", "WARNING", "CRITICAL"]

# ---------------------------------------------------------------------------
# Helper functions -----------------------------------------------------------
# ---------------------------------------------------------------------------

def load_json_helper(file_path: str) -> dict:
    """Loads a JSON file and returns a dictionary."""
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"⚠️ Không thể load file state {file_path}: {e}")
    return {}

def save_json_helper(file_path: str, data: dict) -> None:
    """Saves a dictionary to a JSON file."""
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except IOError as e:
        print(f"⚠️ Không thể lưu file state {file_path}: {e}")

def load_cooldown() -> dict[str, datetime]:
    """Loads general alert cooldowns (Stream 1)."""
    data = load_json_helper(COOLDOWN_FILE)
    now = datetime.now()
    return {
        key: datetime.fromisoformat(val)
        for key, val in data.items()
        if now - datetime.fromisoformat(val) < timedelta(days=2)
    }

def save_cooldown(cooldown: dict[str, datetime]) -> None:
    """Saves general alert cooldowns (Stream 1)."""
    save_json_helper(COOLDOWN_FILE, {k: v.isoformat() for k, v in cooldown.items()})

def load_advisor_state() -> dict:
    """Loads advisor state for quality alerts (Stream 2)."""
    return load_json_helper(ADVISOR_STATE_FILE)

def save_advisor_state(state: dict) -> None:
    """Saves advisor state for quality alerts (Stream 2)."""
    save_json_helper(ADVISOR_STATE_FILE, state)

def should_send_report(cooldowns: dict) -> bool:
    """Kiểm tra xem có nên gửi báo cáo chung không, chống gửi lặp."""
    last_ts = cooldowns.get("last_general_report_timestamp", 0)
    now_dt = datetime.now()
    # Các mốc thời gian mục tiêu trong ngày
    target_times = [now_dt.replace(hour=8, minute=0, second=0, microsecond=0),
                    now_dt.replace(hour=20, minute=0, second=0, microsecond=0)]

    for target_dt in target_times:
        if now_dt >= target_dt and last_ts < target_dt.timestamp():
            return True
    return False

# ----------------------------- Portfolio & Report Rendering -------------------------
# (Các hàm này giữ nguyên từ bản gốc của bạn)

def render_portfolio() -> list[str]:
    balances = get_account_balances()
    spot      = [b for b in balances if b["source"] == "Spot"]
    flexible  = [b for b in balances if b["source"] == "Earn Flexible"]
    locked    = [b for b in balances if b["source"] == "Earn Locked"]
    total     = [b for b in balances if b["source"] == "All"]

    def section(title: str, rows: list[dict]) -> list[str]:
        lines: list[str] = []
        if rows:
            lines.append(f"\n{title}")
            for r in rows:
                lines.append(f"🪙 {r['asset']}: {r['amount']} ≈ ${r['value']}")
            subtotal = sum(r["value"] for r in rows)
            lines.append(f"🔢 Tổng ({title.strip()}): ${round(subtotal, 2)}")
        return lines

    print("\n💰 Portfolio hiện tại:")
    lines: list[str] = []
    lines += section("📦 Spot:", spot)
    lines += section("🪴 Earn Flexible:", flexible)
    lines += section("🔒 Earn Locked:", locked)
    for l in lines:
        print(l)
    if total:
        total_line = f"\n💵 Tổng tài sản: ${total[0]['value']}"
        print(total_line)
        lines.append(total_line.replace("💵", "\n💵"))
    return lines

def send_portfolio_report() -> None:
    send_discord_alert(
        "📊 **BÁO CÁO TỔNG TÀI SẢN**\n" + "\n".join(render_portfolio())
    )
    time.sleep(3)

def format_symbol_report(symbol: str, ind_map: dict[str, dict]) -> str:
    parts: list[str] = []
    for interval, ind in ind_map.items():
        macd_cross = ind.get("macd_cross", "N/A")
        adx        = ind.get("adx", "N/A")
        rsi_div    = ind.get("rsi_divergence", "None")
        trade_plan = ind.get("trade_plan", {})
        doji_note  = f"{ind['doji_type'].capitalize()} Doji" if ind.get("doji_type") else "No"
        trend      = ind.get("trend", "unknown")
        cmf        = ind.get("cmf", "N/A")
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
            entry = trade_plan.get("entry", 0); tp = trade_plan.get("tp", 0); sl = trade_plan.get("sl", 0)
            block += f"""
🎯 **Trade Plan**
- Entry: {entry:.8f}
- TP:     {tp:.8f}
- SL:     {sl:.8f}"""
        parts.append(block)
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Main loop ------------------------------------------------------------------
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Main loop ------------------------------------------------------------------
# ---------------------------------------------------------------------------
def main() -> None:
    print("🔁 Bắt đầu vòng check hai cửa...\n")

    # --- Setup & Khởi tạo ---
    symbols = os.getenv("SYMBOLS", "ETHUSDT,AVAXUSDT").split(",")
    intervals = [i.strip() for i in os.getenv("INTERVALS", "1h,4h").split(",")]
    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")

    # Tạo thư mục log theo ngày
    log_date_dir = os.path.join(BASE_DIR, "log", now.strftime("%Y-%m-%d"))
    os.makedirs(log_date_dir, exist_ok=True)
    
    # Load state một lần duy nhất ở đầu
    general_cooldowns = load_cooldown()
    advisor_state = load_advisor_state()
    log_lines = []

    # --- Xử lý Báo cáo Hàng ngày ---
    should_report = should_send_report(general_cooldowns)
    force_daily = should_report # Nếu là giờ báo cáo, sẽ quét tất cả các khung

    if should_report:
        send_portfolio_report()
        # Cập nhật timestamp ngay sau khi xác định gửi báo cáo
        general_cooldowns["last_general_report_timestamp"] = now.timestamp()

    # --- Lấy dữ liệu giá trước để tối ưu ---
    cached: dict[str, dict[str, pd.DataFrame]] = {"1h": {}, "4h": {}, "1d": {}}
    for sym in symbols:
        for itv in ["1h", "4h", "1d"]:
            df_raw = get_price_data(sym, itv)
            if not df_raw.empty and 'close_time' in df_raw.columns:
                if not pd.api.types.is_datetime64_any_dtype(df_raw['close_time']):
                    df_raw["close_time"] = pd.to_datetime(df_raw["close_time"], unit="ms")
                cached[itv][sym] = df_raw
    
    # --- Vòng lặp xử lý chính ---
    for symbol in symbols:
        try:
            indic_map_general: dict[str, dict] = {}
            send_intervals_general: list[str] = []
            alert_levels_general: list[str] = []

            general_alert_intervals_to_check = intervals if not force_daily else ["1h", "4h", "1d"]

            for interval in general_alert_intervals_to_check:
                df_for_indicators = cached[interval].get(symbol)
                if df_for_indicators is None or df_for_indicators.empty:
                    print(f"⚠️ [Data] Không tìm thấy dữ liệu cache cho {symbol} - {interval}. Bỏ qua.")
                    continue

                df_filtered = df_for_indicators[df_for_indicators["close_time"] < now - timedelta(minutes=1)]
                if df_filtered.empty:
                    print(f"⚠️ [Data] Không có nến đã đóng cho {symbol} - {interval}. Bỏ qua.")
                    continue

                ind = calculate_indicators(df_filtered, symbol, interval)
                ind["interval"] = interval
                ind["rsi_1h"] = calculate_indicators(cached["1h"][symbol], symbol, "1h")["rsi_14"] if cached["1h"].get(symbol) is not None and not cached["1h"].get(symbol).empty else ind.get("rsi_14", 50)
                ind["rsi_4h"] = calculate_indicators(cached["4h"][symbol], symbol, "4h")["rsi_14"] if cached["4h"].get(symbol) is not None and not cached["4h"].get(symbol).empty else ind.get("rsi_14", 50)
                ind["rsi_1d"] = calculate_indicators(cached["1d"][symbol], symbol, "1d")["rsi_14"] if cached["1d"].get(symbol) is not None and not cached["1d"].get(symbol).empty else ind.get("rsi_14", 50)

                # --- CỬA 1: XỬ LÝ ALERT CHUNG ---
                signal, _ = check_signal(ind)
                indic_map_general[interval] = ind

                if force_daily or (signal in SEND_LEVELS):
                    cd_key_general = f"{symbol}_{interval}_{signal}"
                    last_time_general = general_cooldowns.get(cd_key_general)
                    cd_minutes_general = COOLDOWN_LEVEL_MAP.get(interval, {}).get(signal, 90)

                    if force_daily:
                        print(f"🔔 [Cửa 1 - Báo cáo] Tín hiệu chung: {symbol}-{interval} ({signal}).")
                        send_intervals_general.append(interval)
                        alert_levels_general.append(signal)
                    elif not last_time_general or (now - last_time_general >= timedelta(minutes=cd_minutes_general)):
                        print(f"🔔 [Cửa 1] Tín hiệu chung: {symbol}-{interval} ({signal}).")
                        send_intervals_general.append(interval)
                        alert_levels_general.append(signal)
                        general_cooldowns[cd_key_general] = now
                    else:
                        remain = cd_minutes_general - int((now - last_time_general).total_seconds() // 60)
                        print(f"⏳ [Cửa 1] {symbol}-{interval} ({signal}) Cooldown {remain}′. (Bỏ qua)")

                # --- CỬA 2: XỬ LÝ ALERT CHẤT LƯỢNG CAO ---
                if not force_daily and interval in intervals:
                    decision_data = get_advisor_decision(symbol, interval, ind, cached)
                    final_score = decision_data.get('final_score', 5.0)
                    decision_type = decision_data.get('decision_type', 'NEUTRAL')

                    if decision_type == "NEUTRAL":
                        print(f"⚖️ [Cửa 2] {symbol}-{interval}: Điểm {final_score:.2f} (Neutral) → Bỏ qua.")
                        continue

                    state_key_advisor = f"{symbol}-{interval}"
                    last_state_advisor = advisor_state.get(state_key_advisor, {})
                    last_alert_score_advisor = last_state_advisor.get("last_alert_score", 5.0)
                    last_alert_time_str_advisor = last_state_advisor.get("last_alert_timestamp")
                    score_change_threshold = 1.5
                    cooldown_hours_advisor = 2.0
                    is_significant_change = abs(final_score - last_alert_score_advisor) > score_change_threshold
                    is_cooldown_passed_advisor = True
                    
                    if last_alert_time_str_advisor:
                        last_alert_time_advisor = datetime.fromisoformat(last_alert_time_str_advisor)
                        hours_since_last_advisor = (now - last_alert_time_advisor).total_seconds() / 3600
                        if hours_since_last_advisor < cooldown_hours_advisor:
                            is_cooldown_passed_advisor = False
                    
                    if is_cooldown_passed_advisor or is_significant_change:
                        print(f"🔥 [Cửa 2] {symbol}-{interval}: Tín hiệu {decision_type} (Điểm: {final_score:.2f}).")
                        send_opportunity_alert(decision_data)
                        log_to_csv(
                            symbol=symbol,
                            interval=interval,
                            signal=signal,
                            tag=ind.get("tag", "hold"),
                            price=ind.get("price", 0),
                            trade_plan=decision_data.get("combined_trade_plan", {}),
                            timestamp=now_str,
                            recommendation=decision_data
                        )
                        advisor_state[state_key_advisor] = {
                            "last_alert_score": final_score,
                            "last_alert_timestamp": now.isoformat()
                        }
                        time.sleep(3)
                    else:
                        reason = f"đang trong cooldown ({hours_since_last_advisor:.1f}/{cooldown_hours_advisor}h)"
                        if not is_significant_change:
                            reason += ", thay đổi điểm không đủ lớn."
                        print(f"⏳ [Cửa 2] {symbol}-{interval}: Bỏ qua ({reason}). Điểm: {final_score:.2f}")

            if send_intervals_general:
                filtered_map = {iv: indic_map_general[iv] for iv in send_intervals_general}
                report = format_symbol_report(symbol, filtered_map)
                print("\n" + report + "\n" + "-" * 50); log_lines.append(report)
                highest = ("CRITICAL" if "CRITICAL" in alert_levels_general else
                           "WARNING" if "WARNING" in alert_levels_general else
                           "ALERT" if "ALERT" in alert_levels_general else "WATCHLIST")
                icon = {"CRITICAL": "🚨", "WARNING": "⚠️", "ALERT": "📣", "WATCHLIST": "👀"}[highest]
                title = f"{icon} [{symbol}] **{highest}** từ khung {', '.join(send_intervals_general)} | ⏱️ {now_str}"
                ids = "\n".join([f"🆔 ID: {now_str}\t{symbol}\t{iv}" for iv in send_intervals_general])
                send_discord_alert(f"{title}\n{ids}\n\n{report}")
                msg = f"📨 [Cửa 1] Gửi Discord (#alert): {symbol} - {', '.join(send_intervals_general)} ({highest})"
                print(msg); log_lines.append(msg)
                time.sleep(3)

        except Exception as exc:
            import traceback
            print(f"❌ Lỗi nghiêm trọng khi xử lý {symbol}: {exc}")
            traceback.print_exc()
            log_lines.append(f"❌ Lỗi nghiêm trọng khi xử lý {symbol}: {exc}\n{traceback.format_exc()}")

    # --- Lưu lại toàn bộ state và log ---
    if log_lines:
        content = "\n\n" + ("\n" + "=" * 60 + "\n\n").join(log_lines)
        write_named_log(content, os.path.join(log_date_dir, f"{now.strftime('%H%M')}.txt"))

    save_cooldown(general_cooldowns)
    save_advisor_state(advisor_state)
    print("\n✅ Hoàn thành vòng check.")

# ---------------------------------------------------------------------------
if __name__ == "__main__":
    main()
