# main.py (PHIÊN BẢN 6.0 - HOÀN CHỈNH CUỐI CÙNG)

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
    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, 'w', encoding='utf-8') as f:
            f.write(content)
    except Exception as e:
        print(f"❌ Lỗi nghiêm trọng khi ghi file log: {e}")

def send_summary_report(report_lines: list[str]):
    """Gửi báo cáo dạng danh sách tự do, chia tin nhắn nếu cần."""
    main_header = "📝 **BÁO CÁO TÍN HIỆU ĐỊNH KỲ**"
    if not report_lines:
        send_discord_alert(f"{main_header}\nKhông có dữ liệu để báo cáo.")
        return

    # Nối tất cả các dòng lại thành một chuỗi duy nhất để xử lý
    full_content = "\n".join(report_lines)

    chunks = []
    current_chunk = ""
    for line in full_content.split('\n'):
        if len(current_chunk) + len(line) + 1 > 1950:
            chunks.append(current_chunk)
            current_chunk = ""
        current_chunk += line + "\n"
    
    if current_chunk:
        chunks.append(current_chunk)

    # Gửi lần lượt các chunk
    for i, chunk in enumerate(chunks):
        header_to_send = main_header if i == 0 else f"**(Báo cáo phần {i+1}/{len(chunks)})**"
        send_discord_alert(f"{header_to_send}\n{chunk}")
        time.sleep(2)

# --- Portfolio & Report Rendering ---
def format_symbol_report(symbol: str, ind_map: dict[str, dict]) -> str:
    """Tạo định dạng chi tiết cho một symbol, lấy lại format từ phiên bản cũ."""
    parts: list[str] = []
    for interval, ind in ind_map.items():
        def f(val, precision=4):
            return f"{val:.{precision}f}" if isinstance(val, (int, float)) else str(val)

        price = ind.get('price', 0.0)
        ema_20 = ind.get('ema_20', 'N/A')
        rsi_14 = ind.get('rsi_14', 'N/A')
        rsi_div = ind.get('rsi_divergence') or 'None'
        macd_line = ind.get('macd_line', 'N/A')
        macd_signal_val = ind.get('macd_signal', 'N/A')
        macd_cross = ind.get('macd_cross', 'N/A')
        adx = ind.get('adx', 'N/A')
        bb_upper = ind.get('bb_upper', 'N/A')
        bb_lower = ind.get('bb_lower', 'N/A')
        volume = ind.get('volume', 'N/A')
        vol_ma20 = ind.get('vol_ma20', 'N/A')
        fib_0_618 = ind.get('fib_0_618', 'N/A')
        doji_note = f"{ind['doji_type'].replace('_', ' ').title()} Doji" if ind.get("doji_type") else "No"
        trend = ind.get("trend", "unknown")
        cmf = ind.get("cmf", 'N/A')

        signal_details = check_signal(ind)
        signal = signal_details.get("level", "HOLD")
        reason = signal_details.get("reason", "")
        tag = signal_details.get("tag", "")

        advisor_score = ind.get("advisor_score")
        signal_line = f"🧠 Signal: **{signal}** {f'→ {reason}' if reason else ''} {f'(🏷️ {tag})' if tag else ''}"
        if advisor_score is not None:
            signal_line += f" | (Score: {advisor_score:.1f}/10)"

        block = f"""📊 **{symbol} ({interval})**
🔹 Price: {f(price, 8)}
📈 EMA20: {f(ema_20)}
💪 RSI14: {f(rsi_14, 2)} ({rsi_div})
📉 MACD Line: {f(macd_line)}
📊 MACD Signal: {f(macd_signal_val)} → {macd_cross.capitalize()}
🧭 ADX: {f(adx, 2)}
🔺 BB Upper: {f(bb_upper)}
🔻 BB Lower: {f(bb_lower)}
🔊 Volume: {f(volume, 2)} / MA20: {f(vol_ma20, 2)}
🌀 Fibo 0.618: {f(fib_0_618)}
🕯️ Doji: {doji_note}
📈 Trend: {trend.capitalize()}
💸 CMF: {f(cmf)}
{signal_line}"""

        parts.append(block)
    return "\n\n".join(parts)


def format_daily_summary(symbols: list, all_indicators: dict, now_str: str) -> list[str]:
    """Tạo một danh sách báo cáo với ID đầy đủ và không dùng code block."""
    report_lines = []
    level_icons = {"CRITICAL": "🚨", "WARNING": "⚠️", "ALERT": "📣", "WATCHLIST": "👀", "HOLD": "⏸️"}

    for symbol in symbols:
        symbol_data = all_indicators.get(symbol, {})
        if not symbol_data: continue
        
        # Thêm dòng tên symbol để phân tách
        report_lines.append(f"\n**--- {symbol.upper()} ---**")

        for interval in ["1h", "4h", "1d"]:
            ind = symbol_data.get(interval, {})
            if not ind: continue
            
            # Trích xuất dữ liệu
            price = ind.get('price', 0)
            signal_details = check_signal(ind)
            level = signal_details.get("level", "HOLD")
            tag = signal_details.get("tag", "")
            score = ind.get("advisor_score")
            
            icon = level_icons.get(level, "ℹ️")
            
            # === THAY ĐỔI CHÍNH ===
            # Tạo lại ID đầy đủ và đưa vào dòng báo cáo
            id_str = f"**{now_str}  {symbol.upper()}  {interval}**"
            price_str = f"{price:.4f}"
            signal_str = f"**{level}**" + (f" ({tag})" if tag else "")
            score_str = f"**{score:.1f}**" if score is not None else "N/A"

            # Định dạng dòng mới kết hợp cả ID và thông tin tín hiệu
            line = f"{icon} {id_str}\n G-Signal: {signal_str} | Giá: *{price_str}* | Score: {score_str}"
            report_lines.append(line)

    return report_lines

# --- Main loop ---
def main() -> None:
    log_output_lines = []

    msg_start = "🔁 Bắt đầu vòng check (phiên bản 6.0 - Final)..."
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

                price = ind.get('price', 0)
                score = ind.get('advisor_score', 0)
                detail_msg = f"   - Khung {interval}: Giá={price:.4f}, Score={score:.1f}"
                print(detail_msg); log_output_lines.append(detail_msg)

                signal_details = check_signal(ind)
                signal = signal_details.get("level", "HOLD")
                if signal in SEND_LEVELS:
                    cd_key = f"{symbol}_{interval}_{signal}"
                    last_time = general_cooldowns.get(cd_key)
                    cd_minutes = COOLDOWN_LEVEL_MAP.get(interval, {}).get(signal, 90)
                    is_cooldown_passed = not last_time or (now - last_time >= timedelta(minutes=cd_minutes))
                    if is_cooldown_passed:
                        c1_msg = f"   => 🔔 TÍN HIỆU CỬA 1: {signal} | Score: {score:.1f}"
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

                title = f"[{symbol.upper()}] **{highest}** từ khung {', '.join(send_intervals_general)}"
                ids = "\n".join([f"🆔 ID: {now_str}  {symbol.upper()}  {iv}" for iv in send_intervals_general])
                send_discord_alert(f"{title}\n{ids}\n\n{report_content}")
                discord_msg = f"   => 📨 Đã gửi cảnh báo Cửa 1 qua Discord."
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
                        c2_msg = f"   => 🔥 TÍN HIỆU CỬA 2: Thay đổi điểm ({last_score:.2f}→{final_score:.2f})" if is_significant_change else f"   => ⏰ TÍN HIỆU CỬA 2: Hết cooldown"
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
        summary_lines = format_daily_summary(symbols, all_indicators, now_str)
        if summary_lines:
            send_summary_report(summary_lines)

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
