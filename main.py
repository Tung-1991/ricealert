# -*- coding: utf-8 -*-
"""
RiceAlert – main runner
Version: 3.1 (Revolution & Optimized)
Description: This version introduces significant performance optimizations
             by calculating all indicators once per run, and is fully
             compatible with the enhanced trade_advisor.
"""

from dotenv import load_dotenv
load_dotenv()

import os
import time
import json
import pandas as pd
from datetime import datetime, timedelta
from portfolio import get_account_balances
from indicator import get_price_data, calculate_indicators
from signal_logic import check_signal
from alert_manager import send_discord_alert
from csv_logger import log_to_csv, write_named_log
from trade_advisor import get_advisor_decision
from order_alerter import send_opportunity_alert

# --- Constants & Config (Không thay đổi) ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
COOLDOWN_FILE = os.path.join(BASE_DIR, "cooldown_tracker.json")
ADVISOR_STATE_FILE = os.path.join(BASE_DIR, "advisor_state.json")
COOLDOWN_LEVEL_MAP = {
    "1h":   {"WATCHLIST": 300, "ALERT": 240, "WARNING": 180, "CRITICAL": 90},
    "4h":   {"WATCHLIST": 720, "ALERT": 480, "WARNING": 360, "CRITICAL": 240},
    "1d":   {"WATCHLIST": 1800, "ALERT": 1560, "WARNING": 1500, "CRITICAL": 1380},
}
SEND_LEVELS = ["WATCHLIST", "ALERT", "WARNING", "CRITICAL"]

# --- Helper functions (Không thay đổi) ---
def load_json_helper(file_path: str) -> dict:
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"⚠️ Không thể load file state {file_path}: {e}")
    return {}

def save_json_helper(file_path: str, data: dict) -> None:
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except IOError as e:
        print(f"⚠️ Không thể lưu file state {file_path}: {e}")

def load_cooldown() -> dict:
    data = load_json_helper(COOLDOWN_FILE)
    now = datetime.now()
    loaded_data = {}
    for key, value in data.items():
        if key == "last_general_report_timestamp":
            loaded_data[key] = value
            continue
        try:
            if isinstance(value, str):
                dt_value = datetime.fromisoformat(value)
                if now - dt_value < timedelta(days=2):
                    loaded_data[key] = dt_value
        except (TypeError, ValueError):
            print(f"⚠️ Bỏ qua cooldown không hợp lệ: {key}={value}")
            continue
    return loaded_data

def save_cooldown(cooldown: dict) -> None:
    data_to_save = {}
    for key, value in cooldown.items():
        if isinstance(value, datetime):
            data_to_save[key] = value.isoformat()
        else:
            data_to_save[key] = value
    save_json_helper(COOLDOWN_FILE, data_to_save)

def load_advisor_state() -> dict:
    return load_json_helper(ADVISOR_STATE_FILE)

def save_advisor_state(state: dict) -> None:
    save_json_helper(ADVISOR_STATE_FILE, state)

def should_send_report(cooldowns: dict) -> bool:
    last_ts = cooldowns.get("last_general_report_timestamp", 0)
    now_dt = datetime.now()
    target_times = [now_dt.replace(hour=8, minute=0, second=0, microsecond=0),
                    now_dt.replace(hour=20, minute=0, second=0, microsecond=0)]
    for target_dt in target_times:
        if now_dt.timestamp() >= target_dt.timestamp() and last_ts < target_dt.timestamp():
            return True
    return False

# --- Portfolio & Report Rendering (Không thay đổi) ---
def render_portfolio() -> list[str]:
    # ... (Giữ nguyên code của bạn)
    balances = get_account_balances()
    spot = [b for b in balances if b["source"] == "Spot"]
    flexible = [b for b in balances if b["source"] == "Earn Flexible"]
    locked = [b for b in balances if b["source"] == "Earn Locked"]
    total = [b for b in balances if b["source"] == "All"]
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
    for l in lines: print(l)
    if total:
        total_line = f"\n💵 Tổng tài sản: ${total[0]['value']}"
        print(total_line)
        lines.append(total_line.replace("💵", "\n💵"))
    return lines

def send_portfolio_report() -> None:
    send_discord_alert("📊 **BÁO CÁO TỔNG TÀI SẢN**\n" + "\n".join(render_portfolio()))
    time.sleep(3)

def format_symbol_report(symbol: str, ind_map: dict[str, dict]) -> str:
    # ... (Giữ nguyên code của bạn)
    parts: list[str] = []
    for interval, ind in ind_map.items():
        trade_plan = ind.get("trade_plan", {})
        signal, reason = check_signal(ind)
        block = (f"📊 **{symbol} ({interval})**\n"
                 f"🔹 Price: {ind['price']:.8f}\n"
                 f"📈 EMA20: {ind['ema_20']}\n"
                 f"💪 RSI14: {ind['rsi_14']} ({ind.get('rsi_divergence', 'None')})\n"
                 f"📉 MACD Line: {ind['macd_line']}\n"
                 f"📊 MACD Signal: {ind['macd_signal']} → {ind.get('macd_cross', 'N/A')}\n"
                 f"📊 ADX: {ind.get('adx', 'N/A')}\n"
                 f"🔺 Trend: {ind.get('trend', 'unknown')}\n"
                 f"💸 CMF: {ind.get('cmf', 'N/A')}\n"
                 f"🧠 Signal: **{signal}** {f'→ {reason}' if reason else ''}")
        if trade_plan:
            entry, tp, sl = trade_plan.get("entry", 0), trade_plan.get("tp", 0), trade_plan.get("sl", 0)
            block += (f"\n🎯 **Trade Plan**\n"
                      f"- Entry: {entry:.8f}\n"
                      f"- TP:    {tp:.8f}\n"
                      f"- SL:    {sl:.8f}")
        parts.append(block)
    return "\n\n".join(parts)

# --- Main loop (ĐÃ ĐƯỢC TỐI ƯU HÓA) ---
def main() -> None:
    print("🔁 Bắt đầu vòng check hai cửa (phiên bản tối ưu)...")

    # --- Setup & Khởi tạo ---
    symbols = os.getenv("SYMBOLS", "ETHUSDT,AVAXUSDT").split(",")
    intervals = [i.strip() for i in os.getenv("INTERVALS", "1h,4h").split(",")]
    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")

    log_date_dir = os.path.join(BASE_DIR, "log", now.strftime("%Y-%m-%d"))
    os.makedirs(log_date_dir, exist_ok=True)

    general_cooldowns = load_cooldown()
    advisor_state = load_advisor_state()
    log_lines = []

    # --- Xử lý Báo cáo Hàng ngày ---
    should_report = should_send_report(general_cooldowns)
    force_daily = should_report
    if should_report:
        send_portfolio_report()
        general_cooldowns["last_general_report_timestamp"] = now.timestamp()

    # TỐI ƯU HÓA 1: TÍNH TOÁN TẤT CẢ CHỈ BÁO MỘT LẦN
    print("\n[1/3] Đang tính toán tất cả chỉ báo kỹ thuật...")
    all_indicators = {sym: {} for sym in symbols}
    all_timeframes = ["1h", "4h", "1d"]
    for sym in symbols:
        for itv in all_timeframes:
            try:
                df_raw = get_price_data(sym, itv)
                if df_raw.empty or 'close_time' not in df_raw.columns:
                    continue
                
                if not pd.api.types.is_datetime64_any_dtype(df_raw['close_time']):
                    df_raw["close_time"] = pd.to_datetime(df_raw["close_time"], unit="ms")
                
                # Lọc nến đã đóng để tính toán chính xác
                df_filtered = df_raw[df_raw["close_time"] < now - timedelta(minutes=1)]
                if not df_filtered.empty:
                    indicators = calculate_indicators(df_filtered, sym, itv)
                    all_indicators[sym][itv] = indicators
            except Exception as e:
                print(f"⚠️ Lỗi khi tính chỉ báo cho {sym}-{itv}: {e}")
    print("✅ Hoàn thành tính toán chỉ báo.")

    # --- Vòng lặp xử lý chính ---
    print("\n[2/3] Đang xử lý logic hai cửa...")
    for symbol in symbols:
        try:
            indic_map_general: dict[str, dict] = {}
            send_intervals_general: list[str] = []
            alert_levels_general: list[str] = []

            general_alert_intervals_to_check = intervals if not force_daily else all_timeframes

            for interval in general_alert_intervals_to_check:
                # TỐI ƯU HÓA 2: LẤY DỮ LIỆU ĐÃ TÍNH, KHÔNG TÍNH LẠI
                ind = all_indicators.get(symbol, {}).get(interval)
                if not ind:
                    # print(f"ℹ️ [Data] Không có dữ liệu chỉ báo đã tính cho {symbol}-{interval}. Bỏ qua.")
                    continue
                
                # Thêm thông tin RSI từ các khung khác vào `ind` để check_signal
                ind["rsi_1h"] = all_indicators.get(symbol, {}).get("1h", {}).get("rsi_14", 50)
                ind["rsi_4h"] = all_indicators.get(symbol, {}).get("4h", {}).get("rsi_14", 50)
                ind["rsi_1d"] = all_indicators.get(symbol, {}).get("1d", {}).get("rsi_14", 50)

                # --- CỬA 1: XỬ LÝ ALERT CHUNG ---
                signal, _ = check_signal(ind)
                indic_map_general[interval] = ind

                if force_daily or (signal in SEND_LEVELS):
                    cd_key_general = f"{symbol}_{interval}_{signal}"
                    last_time_general = general_cooldowns.get(cd_key_general)
                    cd_minutes_general = COOLDOWN_LEVEL_MAP.get(interval, {}).get(signal, 90)

                    if force_daily or not last_time_general or (now - last_time_general >= timedelta(minutes=cd_minutes_general)):
                        if not force_daily:
                            print(f"🔔 [Cửa 1] Tín hiệu chung: {symbol}-{interval} ({signal}).")
                            general_cooldowns[cd_key_general] = now
                        else:
                            print(f"🔔 [Cửa 1 - Báo cáo] Tín hiệu chung: {symbol}-{interval} ({signal}).")
                        
                        send_intervals_general.append(interval)
                        alert_levels_general.append(signal)
                    else:
                        remain = cd_minutes_general - int((now - last_time_general).total_seconds() // 60)
                        print(f"⏳ [Cửa 1] {symbol}-{interval} ({signal}) Cooldown {remain}′. (Bỏ qua)")

                # --- CỬA 2: XỬ LÝ ALERT CHẤT LƯỢNG CAO ---
                if not force_daily and interval in intervals:
                    # TỐI ƯU HÓA 3: TRUYỀN DỮ LIỆU ĐÃ TÍNH VÀO ADVISOR
                    decision_data = get_advisor_decision(symbol, interval, ind, all_indicators)
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
                            symbol=symbol, interval=interval, signal=signal,
                            tag=ind.get("tag", "hold"), price=ind.get("price", 0),
                            trade_plan=decision_data.get("combined_trade_plan", {}),
                            timestamp=now_str, recommendation=decision_data
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
            error_msg = f"❌ Lỗi nghiêm trọng khi xử lý {symbol}: {exc}"
            print(error_msg)
            traceback.print_exc()
            log_lines.append(f"{error_msg}\n{traceback.format_exc()}")
            
    # --- Lưu lại toàn bộ state và log ---
    print("\n[3/3] Đang lưu trạng thái và ghi log...")
    if log_lines:
        content = "\n\n" + ("\n" + "=" * 60 + "\n\n").join(log_lines)
        write_named_log(content, os.path.join(log_date_dir, f"{now.strftime('%H%M')}.txt"))

    save_cooldown(general_cooldowns)
    save_advisor_state(advisor_state)
    print("\n✅ Hoàn thành vòng check.")

if __name__ == "__main__":
    main()
