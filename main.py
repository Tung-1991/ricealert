# main.py (phiên bản 4.3 - Khôi phục output chi tiết)

# -*- coding: utf-8 -*-
from dotenv import load_dotenv
load_dotenv()

import os
import time
import json
from datetime import datetime, timedelta, timezone
from portfolio import get_account_balances
from indicator import get_price_data, calculate_indicators
from signal_logic import check_signal
from alert_manager import send_discord_alert
from csv_logger import log_to_csv
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
    
def write_log_file(log_path, content):
    """Hàm ghi log đơn giản, tạo thư mục nếu chưa có."""
    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, 'w', encoding='utf-8') as f:
            f.write(content)
    except Exception as e:
        print(f"❌ Lỗi nghiêm trọng khi ghi file log: {e}")

# --- Portfolio & Report Rendering ---
def format_symbol_report(symbol: str, ind_map: dict[str, dict]) -> str:
    parts: list[str] = []
    for interval, ind in ind_map.items():
        signal_details = check_signal(ind)
        signal, reason, tag = signal_details.get("level", "HOLD"), signal_details.get("reason", ""), signal_details.get("tag", "")
        advisor_score = ind.get("advisor_score")
        signal_line = f"🧠 Signal: **{signal}** {f'→ {reason}' if reason else ''} {f'(🏷️ {tag})' if tag else ''}"
        if advisor_score is not None: signal_line += f" | (Score: {advisor_score:.1f}/10)"
        block = (f"📊 **{symbol} ({interval})**\n"
                 f"🔹 Price: {ind['price']:.8f}\n"
                 f"💪 RSI14: {ind['rsi_14']} | 1h: {ind.get('rsi_1h', 'N/A')} | 4h: {ind.get('rsi_4h', 'N/A')} | 1d: {ind.get('rsi_1d', 'N/A')}\n"
                 f"📉 MACD: {ind.get('macd_cross', 'N/A')}\n"
                 f"🔺 Trend: {ind.get('trend', 'unknown')} | ADX: {ind.get('adx', 'N/A')}\n"
                 f"{signal_line}")
        parts.append(block)
    return "\n\n".join(parts)

def format_daily_summary(symbols: list, all_indicators: dict, now_str: str) -> str:
    summary_parts = ["📝 **BÁO CÁO TÍN HIỆU ĐỊNH KỲ**"]
    for symbol in symbols:
        symbol_data = all_indicators.get(symbol, {})
        if not symbol_data: continue
        header = f"\n**{symbol.upper()}**"
        table_lines = ["```md"]
        table_lines.append(f"{'ID':<28} | {'Giá':<12} | {'Tín Hiệu':<20} | Score")
        table_lines.append(f"{'-'*28} | {'-'*12} | {'-'*20} | {'-'*5}")
        for interval in ["1h", "4h", "1d"]:
            ind = symbol_data.get(interval, {})
            if not ind: continue
            price = ind.get('price', 0)
            signal_details = check_signal(ind)
            level = signal_details.get("level", "HOLD")
            tag = signal_details.get("tag", "")
            score = ind.get("advisor_score")
            id_str = f"{now_str.split(' ')[0]} | {symbol.upper()} | {interval}"
            price_str = f"{price:.4f}"
            signal_str = f"{level}" + (f"-{tag}" if tag else "")
            score_str = f"{score:.1f}" if score is not None else "N/A"
            table_lines.append(f"{id_str:<28} | {price_str:<12} | {signal_str:<20} | {score_str}")
        table_lines.append("```")
        summary_parts.append(header + "\n" + "\n".join(table_lines))
    return "\n".join(summary_parts)

# --- Main loop ---
def main() -> None:
    log_output_lines = []
    
    msg_start = "🔁 Bắt đầu vòng check hai cửa (phiên bản 4.3 - Output chi tiết)..."
    print(msg_start); log_output_lines.append(msg_start)

    # --- Setup & Khởi tạo ---
    symbols = os.getenv("SYMBOLS", "ETHUSDT,AVAXUSDT").split(",")
    intervals = [i.strip() for i in os.getenv("INTERVALS", "1h,4h").split(",")]
    now = datetime.now(timezone.utc)
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    general_cooldowns = load_cooldown()
    advisor_state = load_advisor_state()
    
    force_daily = should_send_report(general_cooldowns)
    
    # --- TÍNH TOÁN TẤT CẢ CHỈ BÁO MỘT LẦN ---
    msg_calc = "\n[1/3] Đang tính toán tất cả chỉ báo kỹ thuật..."
    print(msg_calc); log_output_lines.append(msg_calc)
    all_indicators = {sym: {} for sym in symbols}
    all_timeframes = ["1h", "4h", "1d"]
    for sym in symbols:
        for itv in all_timeframes:
            try:
                df_raw = get_price_data(sym, itv)
                if df_raw.empty: continue
                all_indicators[sym][itv] = calculate_indicators(df_raw, sym, itv)
                calc_msg = f"   -> Đã tính toán cho {sym}-{itv}"
                print(calc_msg); log_output_lines.append(calc_msg)
            except Exception as e:
                err_msg = f"⚠️ Lỗi khi tính chỉ báo cho {sym}-{itv}: {e}"
                print(err_msg); log_output_lines.append(err_msg)
    msg_calc_done = "✅ Hoàn thành tính toán chỉ báo."
    print(msg_calc_done); log_output_lines.append(msg_calc_done)

    # --- LÀM GIÀU DỮ LIỆU GỐC ---
    for sym in symbols:
        rsi_1h = all_indicators.get(sym, {}).get("1h", {}).get("rsi_14", 50)
        rsi_4h = all_indicators.get(sym, {}).get("4h", {}).get("rsi_14", 50)
        rsi_1d = all_indicators.get(sym, {}).get("1d", {}).get("rsi_14", 50)
        for itv in all_timeframes:
            if all_indicators.get(sym, {}).get(itv):
                all_indicators[sym][itv]['rsi_1h'] = rsi_1h
                all_indicators[sym][itv]['rsi_4h'] = rsi_4h
                all_indicators[sym][itv]['rsi_1d'] = rsi_1d

    # --- Vòng lặp xử lý chính ---
    msg_main = "\n[2/3] Đang xử lý logic hai cửa..."
    print(msg_main); log_output_lines.append(msg_main)
    for symbol in symbols:
        try:
            symbol_msg = f"\n--- Đang xử lý: {symbol.upper()} ---"
            print(symbol_msg); log_output_lines.append(symbol_msg)
            
            # === Tính toán Advisor và gắn điểm vào all_indicators ===
            for interval in all_timeframes:
                ind = all_indicators.get(symbol, {}).get(interval, {})
                if not ind: continue
                advisor_decision = get_advisor_decision(symbol, interval, ind.copy(), FULL_CONFIG)
                if all_indicators.get(symbol, {}).get(interval):
                    all_indicators[symbol][interval]['advisor_score'] = advisor_decision.get('final_score')
                    all_indicators[symbol][interval]['advisor_decision'] = advisor_decision

            # --- CỬA 1: XỬ LÝ ALERT CHUNG ---
            indic_map_general, send_intervals_general, alert_levels_general = {}, [], []
            for interval in intervals:
                ind = all_indicators.get(symbol, {}).get(interval, {})
                if not ind: continue

                # In ra các chỉ số chính để theo dõi
                price = ind.get('price', 0)
                rsi = ind.get('rsi_14', 0)
                macd_cross = ind.get('macd_cross', 'N/A')
                score = ind.get('advisor_score', 0)
                detail_msg = f"   - Khung {interval}: Giá={price:.4f}, RSI={rsi:.1f}, MACD='{macd_cross}', Score={score:.1f}"
                print(detail_msg); log_output_lines.append(detail_msg)

                signal_details = check_signal(ind)
                signal = signal_details.get("level", "HOLD")
                if signal in SEND_LEVELS:
                    cd_key = f"{symbol}_{interval}_{signal}"
                    last_time = general_cooldowns.get(cd_key)
                    cd_minutes = COOLDOWN_LEVEL_MAP.get(interval, {}).get(signal, 90)
                    is_cooldown_passed = not last_time or (now - last_time >= timedelta(minutes=cd_minutes))
                    if is_cooldown_passed:
                        score_text = f" | Score: {score:.1f}" if score is not None else ""
                        c1_msg = f"   => 🔔 TÍN HIỆU: {signal}{score_text}"
                        print(c1_msg); log_output_lines.append(c1_msg)
                        general_cooldowns[cd_key] = now
                        send_intervals_general.append(interval)
                        alert_levels_general.append(signal)
                        indic_map_general[interval] = ind

            if send_intervals_general:
                report_content = format_symbol_report(symbol, indic_map_general)
                if "CRITICAL" in alert_levels_general: highest = "CRITICAL"
                elif "WARNING" in alert_levels_general: highest = "WARNING"
                elif "ALERT" in alert_levels_general: highest = "ALERT"
                else: highest = "WATCHLIST"
                icon = {"CRITICAL": "🚨", "WARNING": "⚠️", "ALERT": "📣", "WATCHLIST": "👀"}.get(highest, "ℹ️")
                title = f"{icon} [{symbol.upper()}] **{highest}** từ khung {', '.join(send_intervals_general)}"
                ids = "\n".join([f"🆔 ID: {now_str} | {symbol.upper()} | {iv}" for iv in send_intervals_general])
                send_discord_alert(f"{title}\n{ids}\n\n{report_content}")
                discord_msg = f"   => 📨 Đã gửi cảnh báo Discord."
                print(discord_msg); log_output_lines.append(discord_msg)
                time.sleep(3)

            # --- CỬA 2: SỬ DỤNG LOGIC HYBRID ---
            if not force_daily:
                for interval in intervals:
                    decision_data = all_indicators.get(symbol, {}).get(interval, {}).get('advisor_decision')
                    if not decision_data or decision_data.get('decision_type') == "NEUTRAL": continue
                    final_score = decision_data.get('final_score', 5.0)
                    state_key = f"{symbol}-{interval}"
                    last_state = advisor_state.get(state_key, {})
                    last_score = last_state.get("last_alert_score", 5.0)
                    last_time_str = last_state.get("last_alert_timestamp")
                    
                    c2_check_msg = f"   - Cửa 2 ({interval}): Đang check. Score hiện tại={final_score:.2f}, Score lần trước={last_score:.2f}"
                    print(c2_check_msg); log_output_lines.append(c2_check_msg)
                    
                    is_significant_change = abs(final_score - last_score) > ADVISOR_CONFIG["SCORE_CHANGE_THRESHOLD"]
                    is_cooldown_passed = True
                    if last_time_str:
                        last_time = ensure_utc_aware(datetime.fromisoformat(last_time_str))
                        if (now - last_time).total_seconds() / 3600 < ADVISOR_CONFIG["COOLDOWN_HOURS"]:
                            is_cooldown_passed = False
                    if is_significant_change or is_cooldown_passed:
                        c2_msg = f"   => 🔥 TÍN HIỆU CỬA 2: Thay đổi điểm ({last_score:.2f}→{final_score:.2f})" if is_significant_change else f"⏰ TÍN HIỆU CỬA 2: Hết cooldown"
                        print(c2_msg); log_output_lines.append(c2_msg)
                        send_opportunity_alert(decision_data)
                        log_to_csv(symbol=symbol, interval=interval, price=decision_data.get('full_indicators', {}).get('price', 0), timestamp=now_str, recommendation=decision_data)
                        advisor_state[state_key] = {"last_alert_score": final_score, "last_alert_timestamp": now.isoformat()}
                        time.sleep(3)

        except Exception as exc:
            import traceback
            error_msg = f"❌ Lỗi nghiêm trọng khi xử lý {symbol}: {exc}"
            print(error_msg); log_output_lines.append(error_msg)
            log_output_lines.append(traceback.format_exc())

    # --- Xử lý gửi báo cáo tóm tắt hàng ngày ---
    if force_daily:
        summary_report = format_daily_summary(symbols, all_indicators, now_str)
        send_discord_alert(summary_report)
        general_cooldowns["last_general_report_timestamp"] = now.timestamp()
        log_output_lines.append("\nĐã gửi Báo cáo tóm tắt hàng ngày.")

    # --- Lưu lại toàn bộ state và ghi log---
    msg_save = "\n[3/3] Đang lưu trạng thái và ghi log..."
    print(msg_save); log_output_lines.append(msg_save)
    save_cooldown(general_cooldowns)
    save_advisor_state(advisor_state)
    
    now_vn = now.astimezone(timezone(timedelta(hours=7)))
    log_dir = os.path.join(BASE_DIR, "log", now_vn.strftime("%Y-%m-%d"))
    log_filename = now_vn.strftime("%H-%M") + ".txt"
    log_file_path = os.path.join(log_dir, log_filename)
    write_log_file(log_file_path, "\n".join(log_output_lines))
    
    msg_log_done = f"✅ Đã ghi log vào file: {log_file_path}"
    print(msg_log_done)

    msg_done = "\n✅ Hoàn thành vòng check."
    print(msg_done)

if __name__ == "__main__":
    main()
