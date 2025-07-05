# main.py (đã sửa lỗi thiếu RSI cho Advisor - v3.8)

# -*- coding: utf-8 -*-
from dotenv import load_dotenv
load_dotenv()

import os
import time
import json
import pandas as pd
from datetime import datetime, timedelta, timezone
from portfolio import get_account_balances
from indicator import get_price_data, calculate_indicators
from signal_logic import check_signal
from alert_manager import send_discord_alert
from csv_logger import log_to_csv, write_named_log
from trade_advisor import get_advisor_decision, FULL_CONFIG
from order_alerter import send_opportunity_alert

# --- Constants & Config ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
COOLDOWN_FILE = os.path.join(BASE_DIR, "cooldown_tracker.json")
ADVISOR_STATE_FILE = os.path.join(BASE_DIR, "advisor_state.json")

COOLDOWN_LEVEL_MAP = {
    "1h":   {"WATCHLIST": 300, "ALERT": 240, "WARNING": 180, "CRITICAL": 90},
    "4h":   {"WATCHLIST": 720, "ALERT": 480, "WARNING": 360, "CRITICAL": 240},
    "1d":   {"WATCHLIST": 1800, "ALERT": 1560, "WARNING": 1500, "CRITICAL": 1380},
}
SEND_LEVELS = ["WATCHLIST", "ALERT", "WARNING", "CRITICAL"]
ADVISOR_CONFIG = { "SCORE_CHANGE_THRESHOLD": 1.0, "COOLDOWN_HOURS": 6.0 }

# --- Helper functions ---
def load_json_helper(file_path: str) -> dict:
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f: return json.load(f)
        except (json.JSONDecodeError, IOError): pass
    return {}

def save_json_helper(file_path: str, data: dict) -> None:
    try:
        with open(file_path, "w", encoding="utf-8") as f: json.dump(data, f, indent=2)
    except IOError: pass

def ensure_utc_aware(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt

def load_cooldown() -> dict:
    data = load_json_helper(COOLDOWN_FILE)
    now = datetime.now(timezone.utc)
    loaded_data = {}
    for key, value in data.items():
        if key == "last_general_report_timestamp":
            loaded_data[key] = value
            continue
        try:
            if isinstance(value, str):
                dt_value = datetime.fromisoformat(value)
                if now - ensure_utc_aware(dt_value) < timedelta(days=2):
                    loaded_data[key] = ensure_utc_aware(dt_value)
        except (TypeError, ValueError): continue
    return loaded_data

def save_cooldown(cooldown: dict) -> None:
    data_to_save = {k: v.isoformat() if isinstance(v, datetime) else v for k, v in cooldown.items()}
    save_json_helper(COOLDOWN_FILE, data_to_save)

def load_advisor_state() -> dict: return load_json_helper(ADVISOR_STATE_FILE)
def save_advisor_state(state: dict) -> None: save_json_helper(ADVISOR_STATE_FILE, state)

def should_send_report(cooldowns: dict) -> bool:
    last_ts = cooldowns.get("last_general_report_timestamp", 0)
    now_utc = datetime.now(timezone.utc)
    now_vn = now_utc.astimezone(timezone(timedelta(hours=7)))
    target_times_vn = [
        now_vn.replace(hour=8, minute=0, second=0, microsecond=0),
        now_vn.replace(hour=20, minute=0, second=0, microsecond=0),
    ]
    for target_vn in target_times_vn:
        target_utc = target_vn.astimezone(timezone.utc)
        if now_utc >= target_utc and last_ts < target_utc.timestamp():
            return True
    return False

# --- Portfolio & Report Rendering ---
def render_portfolio() -> list[str]:
    balances = get_account_balances()
    def section(title: str, rows: list[dict]) -> list[str]:
        lines = []
        if not rows: return lines
        lines.append(f"\n{title}")
        for r in rows: lines.append(f"🪙 {r['asset']}: {r['amount']} ≈ ${r['value']}")
        subtotal = sum(r["value"] for r in rows)
        lines.append(f"🔢 Tổng ({title.strip()}): ${round(subtotal, 2)}")
        return lines
    print("\n💰 Portfolio hiện tại:")
    lines = []
    lines += section("📦 Spot:", [b for b in balances if b["source"] == "Spot"])
    lines += section("🪴 Earn Flexible:", [b for b in balances if b["source"] == "Earn Flexible"])
    lines += section("🔒 Earn Locked:", [b for b in balances if b["source"] == "Earn Locked"])
    for l in lines: print(l)
    total = [b for b in balances if b["source"] == "All"]
    if total:
        total_line = f"\n💵 Tổng tài sản: ${total[0]['value']}"
        print(total_line)
        lines.append(total_line.replace("💵", "\n💵"))
    return lines

def send_portfolio_report() -> None:
    send_discord_alert("📊 **BÁO CÁO TỔNG TÀI SẢN**\n" + "\n".join(render_portfolio()))
    time.sleep(3)

def format_symbol_report(symbol: str, ind_map: dict[str, dict]) -> str:
    parts: list[str] = []
    for interval, ind in ind_map.items():
        trade_plan = ind.get("trade_plan", {})
        signal_details = check_signal(ind)
        signal, reason, tag = signal_details.get("level", "HOLD"), signal_details.get("reason", ""), signal_details.get("tag", "")
        advisor_score = ind.get("advisor_score")
        signal_line = f"🧠 Signal: **{signal}** {f'→ {reason}' if reason else ''} {f'(🏷️ {tag})' if tag else ''}"
        if advisor_score is not None: signal_line += f" | (Score: {advisor_score:.1f}/10)"
        block = (f"📊 **{symbol} ({interval})**\n"
                 f"🔹 Price: {ind['price']:.8f}\n"
                 f"📈 EMA20: {ind['ema_20']}\n"
                 f"💪 RSI14: {ind['rsi_14']} ({ind.get('rsi_divergence', 'None')})\n"
                 f"📉 MACD Line: {ind['macd_line']}\n"
                 f"📊 MACD Signal: {ind['macd_signal']} → {ind.get('macd_cross', 'N/A')}\n"
                 f"📊 ADX: {ind.get('adx', 'N/A')}\n"
                 f"🔺 Trend: {ind.get('trend', 'unknown')}\n"
                 f"💸 CMF: {ind.get('cmf', 'N/A')}\n"
                 f"{signal_line}")
        if trade_plan:
            entry, tp, sl = trade_plan.get("entry", 0), trade_plan.get("tp", 0), trade_plan.get("sl", 0)
            block += f"\n🎯 **Trade Plan**\n- Entry: {entry:.8f}\n- TP:    {tp:.8f}\n- SL:    {sl:.8f}"
        parts.append(block)
    return "\n\n".join(parts)

# --- Main loop ---
def main() -> None:
    print("🔁 Bắt đầu vòng check hai cửa (phiên bản 3.8)...")

    # --- Setup & Khởi tạo ---
    symbols = os.getenv("SYMBOLS", "ETHUSDT,AVAXUSDT").split(",")
    intervals = [i.strip() for i in os.getenv("INTERVALS", "1h,4h").split(",")]
    now = datetime.now(timezone.utc)
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    log_date_dir = os.path.join(BASE_DIR, "log", now.strftime("%Y-%m-%d"))
    os.makedirs(log_date_dir, exist_ok=True)
    general_cooldowns = load_cooldown()
    advisor_state = load_advisor_state()
    log_lines, daily_summary_lines = [], []

    # --- Xử lý Báo cáo Hàng ngày ---
    force_daily = should_send_report(general_cooldowns)
    if force_daily:
        send_portfolio_report()

    # --- TÍNH TOÁN TẤT CẢ CHỈ BÁO MỘT LẦN ---
    print("\n[1/3] Đang tính toán tất cả chỉ báo kỹ thuật...")
    all_indicators = {sym: {} for sym in symbols}
    all_timeframes = ["1h", "4h", "1d"]
    for sym in symbols:
        for itv in all_timeframes:
            try:
                df_raw = get_price_data(sym, itv)
                if df_raw.empty: continue
                # Logic filter dataframe không cần thiết vì calculate_indicators đã xử lý idx = -2
                all_indicators[sym][itv] = calculate_indicators(df_raw, sym, itv)
            except Exception as e:
                print(f"⚠️ Lỗi khi tính chỉ báo cho {sym}-{itv}: {e}")
    print("✅ Hoàn thành tính toán chỉ báo.")

    # --- Vòng lặp xử lý chính ---
    print("\n[2/3] Đang xử lý logic hai cửa...")
    for symbol in symbols:
        try:
            # === Tính toán Advisor một lần cho tất cả các khung thời gian ===
            advisor_decisions = {}
            for interval in all_timeframes:
                ind = all_indicators.get(symbol, {}).get(interval, {}).copy() # Dùng .copy() để tránh thay đổi dict gốc
                if not ind: continue

                # 🔥 SỬA LỖI: Bổ sung RSI đa khung thời gian cho Advisor trước khi gọi get_advisor_decision
                ind["rsi_1h"] = all_indicators.get(symbol, {}).get("1h", {}).get("rsi_14", 50)
                ind["rsi_4h"] = all_indicators.get(symbol, {}).get("4h", {}).get("rsi_14", 50)
                ind["rsi_1d"] = all_indicators.get(symbol, {}).get("1d", {}).get("rsi_14", 50)
                
                advisor_decisions[interval] = get_advisor_decision(symbol, interval, ind, FULL_CONFIG)
                
                # Gắn điểm advisor vào dict chỉ báo gốc để Cửa 1 có thể sử dụng
                if all_indicators.get(symbol, {}).get(interval):
                     all_indicators[symbol][interval]['advisor_score'] = advisor_decisions[interval].get('final_score')

            # --- CỬA 1: XỬ LÝ ALERT CHUNG & BÁO CÁO HÀNG NGÀY ---
            indic_map_general, send_intervals_general, alert_levels_general = {}, [], []
            intervals_to_check = all_timeframes if force_daily else intervals
            for interval in intervals_to_check:
                ind = all_indicators.get(symbol, {}).get(interval, {}).copy()
                if not ind: continue

                # Logic thêm RSI đa khung đã được chuyển lên trên, nhưng để ở đây cho Cửa 1 vẫn không hại gì
                ind["rsi_1h"] = all_indicators.get(symbol, {}).get("1h", {}).get("rsi_14", 50)
                ind["rsi_4h"] = all_indicators.get(symbol, {}).get("4h", {}).get("rsi_14", 50)
                ind["rsi_1d"] = all_indicators.get(symbol, {}).get("1d", {}).get("rsi_14", 50)

                signal_details = check_signal(ind)
                signal = signal_details.get("level", "HOLD")
                indic_map_general[interval] = ind

                if force_daily or (signal in SEND_LEVELS):
                    cd_key = f"{symbol}_{interval}_{signal}"
                    last_time = general_cooldowns.get(cd_key)
                    cd_minutes = COOLDOWN_LEVEL_MAP.get(interval, {}).get(signal, 90)
                    is_cooldown_passed = not last_time or (now - last_time >= timedelta(minutes=cd_minutes))

                    if force_daily or is_cooldown_passed:
                        if not force_daily:
                            print(f"🔔 [Cửa 1 - Tín hiệu chung] {symbol}-{interval} ({signal}).")
                            general_cooldowns[cd_key] = now
                        send_intervals_general.append(interval)
                        alert_levels_general.append(signal)
                    else:
                        remain = cd_minutes - int((now - last_time).total_seconds() // 60)
                        print(f"⏳ [Cửa 1] {symbol}-{interval} ({signal}) Cooldown {remain}′. (Bỏ qua)")
            
            # Logic gửi tin nhắn cho Cửa 1
            if send_intervals_general:
                # ... (Logic này không đổi) ...

            # --- CỬA 2: SỬ DỤNG LOGIC HYBRID ---
            if not force_daily:
                for interval in intervals:
                    decision_data = advisor_decisions.get(interval)
                    if not decision_data or decision_data.get('decision_type') == "NEUTRAL": continue

                    final_score = decision_data.get('final_score', 5.0)
                    state_key = f"{symbol}-{interval}"
                    last_state = advisor_state.get(state_key, {})
                    last_score = last_state.get("last_alert_score", 5.0)
                    last_time_str = last_state.get("last_alert_timestamp")
                    
                    is_significant_change = abs(final_score - last_score) > ADVISOR_CONFIG["SCORE_CHANGE_THRESHOLD"]
                    is_cooldown_passed = True
                    if last_time_str:
                        last_time = ensure_utc_aware(datetime.fromisoformat(last_time_str))
                        if (now - last_time).total_seconds() / 3600 < ADVISOR_CONFIG["COOLDOWN_HOURS"]:
                            is_cooldown_passed = False
                    
                    if is_significant_change or is_cooldown_passed:
                        log_msg = f"🔥 [Cửa 2] {symbol}-{interval}: Thay đổi điểm ({last_score:.2f}→{final_score:.2f})" if is_significant_change else f"⏰ [Cửa 2] {symbol}-{interval}: Hết cooldown"
                        print(log_msg)
                        send_opportunity_alert(decision_data)
                        log_to_csv(symbol=symbol, interval=interval, price=decision_data.get('full_indicators', {}).get('price', 0), timestamp=now_str, recommendation=decision_data)
                        advisor_state[state_key] = {"last_alert_score": final_score, "last_alert_timestamp": now.isoformat()}
                        time.sleep(3)

        except Exception as exc:
            import traceback
            error_msg = f"❌ Lỗi nghiêm trọng khi xử lý {symbol}: {exc}"
            print(error_msg); traceback.print_exc()
            log_lines.append(f"{error_msg}\n{traceback.format_exc()}")
    
    # --- Xử lý gửi báo cáo tóm tắt hàng ngày ---
    if daily_summary_lines:
        # ... (Logic này không đổi) ...

    # --- Lưu lại toàn bộ state và log ---
    print("\n[3/3] Đang lưu trạng thái và ghi log...")
    if log_lines:
        # ... (Logic này không đổi) ...

    save_cooldown(general_cooldowns)
    save_advisor_state(advisor_state)
    print("\n✅ Hoàn thành vòng check.")

if __name__ == "__main__":
    main()
