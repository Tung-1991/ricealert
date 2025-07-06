# my_precious.py
# -*- coding: utf-8 -*-
"""my_precious.py – position advisor
Version: 6.0 (Integrated & Streamlined)
Date: 2025-07-04
Description: This version is fully integrated with the main system. It no longer
             re-calculates indicators or scores. Instead, it leverages the
             powerful `trade_advisor.get_advisor_decision` to get a unified score,
             making it consistent, maintainable, and smarter. The output structure
             is preserved but now powered by the new, centralized logic.
"""
import os
import json
import time
import sys
from datetime import datetime
from collections import Counter
from typing import List, Dict, Any, Tuple
import requests

from dotenv import load_dotenv

# --- THAY ĐỔI 1: Thiết lập đường dẫn và Import ---
# Giữ nguyên phần thiết lập sys.path để đảm bảo import hoạt động
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BASE_DIR)
sys.path.append(os.path.join(BASE_DIR, "ricenews"))

# Import trực tiếp các module cần thiết từ hệ thống
from indicator import get_price_data, calculate_indicators # Sẽ dùng hàm gốc
from trade_advisor import get_advisor_decision, FULL_CONFIG # Đây là "bộ não" mới!
from signal_logic import check_signal # Vẫn cần để hiển thị lý do của tín hiệu kỹ thuật

load_dotenv()
WEBHOOK_URL = os.getenv("DISCORD_PRECIOUS")

# ==============================================================================
# CONFIG & PATHS (Giữ nguyên)
# ==============================================================================
COOLDOWN_STATE_PATH = os.path.join(BASE_DIR, "advisor_log/cooldown_state.json")
TRADELOG_DIR = os.path.join(BASE_DIR, "trade/tradelog")
ADVISOR_DIR  = os.path.join(BASE_DIR, "advisor_log")
LOG_DIR      = os.path.join(ADVISOR_DIR, "log")
AI_DIR       = os.path.join(BASE_DIR, "ai_logs")
NEWS_DIR     = os.path.join(BASE_DIR, "ricenews/lognew")

os.makedirs(LOG_DIR, exist_ok=True)

ICON = {"PANIC_SELL":"🆘","SELL":"🔻","AVOID":"⛔",
        "HOLD":"💎","WEAK_BUY":"🟢","BUY":"🛒","STRONG_BUY":"🚀"}

# ==============================================================================
# LOẠI BỎ CÁC HÀM TRÙNG LẶP
# ==============================================================================
# ### THAY ĐỔI 2: LOẠI BỎ HOÀN TOÀN CÁC HÀM SAU ĐÂY ###
# - `calculate_indicators`: Sẽ import và dùng bản gốc từ `indicator.py`.
# - `analyze_market_trend`: Logic này đã có trong `trade_advisor.py`.
# - `get_news_sentiment`: Logic này đã có trong `trade_advisor.py`.
# - `generate_news_and_context_block`: Sẽ được thay thế bằng output từ `trade_advisor`.
# - `calculate_technical_score`: Sẽ dùng điểm `tech_score` từ `trade_advisor`.
# ==============================================================================

# ==============================================================================
# UTILITY FUNCTIONS (Giữ nguyên, không thay đổi)
# ==============================================================================
def load_json(path: str, default):
    try:
        with open(path, "r", encoding="utf-8") as f: return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError): return default

def write_json(path: str, data) -> None:
    with open(path, "w", encoding="utf-8") as f: json.dump(data, f, indent=2, ensure_ascii=False)

def log_to_txt(msg: str) -> None:
    log_file = os.path.join(LOG_DIR, f"{datetime.now().strftime('%Y-%m-%d')}.txt")
    with open(log_file, "a", encoding='utf-8') as f:
        f.write(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")

def send_discord_alert(msg: str) -> None:
    if not WEBHOOK_URL: return
    for i in range(0, len(msg), 1950):
        try:
            requests.post(WEBHOOK_URL, json={"content": msg[i:i+1950]}, timeout=10).raise_for_status()
            time.sleep(1)
        except Exception as e: log_to_txt(f"[ERROR] Discord alert failed: {e}")

def calc_held_hours(start_str: str) -> float:
    try:
        t = datetime.strptime(start_str, "%Y-%m-%d %H:%M:%S")
        return round((datetime.now() - t).total_seconds() / 3600, 1)
    except: return 0.0

def should_send_overview(state: dict) -> bool:
    last_ts = state.get("last_overview_timestamp", 0)
    now_dt = datetime.now()
    target_times = [now_dt.replace(hour=8, minute=2, second=0, microsecond=0),
                    now_dt.replace(hour=20, minute=2, second=0, microsecond=0)]
    for target_dt in target_times:
        if now_dt.timestamp() >= target_dt.timestamp() and last_ts < target_dt.timestamp():
            return True
    return False

def parse_trade_plan(plan_str: str) -> dict:
    try: e, t, s = map(float, plan_str.split("/")); return {"entry": e, "tp": t, "sl": s}
    except Exception: return {"entry": 0, "tp": 0, "sl": 0}

# ==============================================================================
# MAIN LOGIC & EXECUTION
# ==============================================================================
def main():
    print(f"💎 MyPrecious Advisor v6.0 (Integrated) starting at {datetime.now()}...")
    trades = []
    for fname in sorted(os.listdir(TRADELOG_DIR)):
        if fname.endswith(".json"):
            trades.extend([t for t in load_json(os.path.join(TRADELOG_DIR, fname), []) if t.get("status") == "open"])

    if not trades:
        print("✅ No open trades found. Exiting.")
        return

    # Tối ưu hóa: Thu thập và tính toán chỉ báo MỘT LẦN (Logic này vẫn rất tốt)
    unique_symbols = {trade['symbol'] for trade in trades}
    all_timeframes = ["1h", "4h", "1d"]

    print(f"[1/3] Pre-calculating indicators for {len(unique_symbols)} unique symbols...")
    all_indicators = {sym: {} for sym in unique_symbols}
    for sym in unique_symbols:
        for itv in all_timeframes:
            try:
                df_raw = get_price_data(sym, itv, limit=200) # Lấy 200 nến là đủ
                if not df_raw.empty and len(df_raw) >= 50:
                    # Dùng hàm calculate_indicators gốc
                    indicators_data = calculate_indicators(df_raw, sym, itv)
                    all_indicators[sym][itv] = indicators_data
            except Exception as e:
                log_to_txt(f"Error pre-calculating for {sym}-{itv}: {e}")
    print("✅ Pre-calculation complete.")

    # Tải state và context một lần
    cooldown_state = load_json(COOLDOWN_STATE_PATH, {})
    now = datetime.now()
    advisor_file = os.path.join(ADVISOR_DIR, f"{now.strftime('%Y-%m-%d')}.json")
    advisor_log = load_json(advisor_file, [])
    advisor_map = {t["id"]: t for t in advisor_log}
    overview_data = []
    level_counter = Counter()

    print(f"\n[2/3] Analyzing {len(trades)} open positions...")
    for trade in trades:
        try:
            trade_id, symbol, interval = trade["id"], trade["symbol"], trade["interval"]

            # Lấy dữ liệu chỉ báo của khung thời gian chính
            indicators = all_indicators.get(symbol, {}).get(interval)
            if not indicators:
                log_to_txt(f"Skipping {trade_id} - {symbol}-{interval} due to missing indicator data.")
                continue

            # ### THAY ĐỔI 3: GỌI TRADE ADVISOR ĐỂ LẤY QUYẾT ĐỊNH TỔNG HỢP ###
            # Gắn các chỉ báo đa khung thời gian vào indicators để check_signal bên trong get_advisor_decision có thể sử dụng
            for tf_key in ["1h", "4h", "1d"]:
                indicators[f"rsi_{tf_key}"] = all_indicators.get(symbol, {}).get(tf_key, {}).get("rsi_14", 50)

            # Đây là bước quan trọng nhất: gọi bộ não trung tâm
            # Chúng ta không cần truyền ai_data_override và context_override nữa
            # vì get_advisor_decision sẽ tự động đọc chúng từ file
            advisor_decision = get_advisor_decision(symbol, interval, indicators, FULL_CONFIG)

            # Lấy tất cả thông tin cần thiết từ quyết định của advisor
            base_score = advisor_decision.get("final_score", 5.0) # Lưu base_score trước khi điều chỉnh PnL
            tech_score = advisor_decision.get("tech_score", 5.0)
            ml_data = advisor_decision.get("ai_prediction", {})
            market_trend = advisor_decision.get("market_trend", "NEUTRAL")
            news_factor = advisor_decision.get("news_factor", 0.0)
            signal_details = advisor_decision.get("signal_details", {})
            full_indicators_from_advisor = advisor_decision.get("full_indicators", {})

            # Tính toán các thông tin đặc thù của my_precious
            real_entry = trade.get("real_entry") or parse_trade_plan(trade["trade_plan"])["entry"]
            price_now = full_indicators_from_advisor.get('entry_price', full_indicators_from_advisor.get('price', 0))

            # --- LOGIC MỚI: TÍNH TOÁN ĐIỂM ĐIỀU CHỈNH PNL ---
            pnl = round((price_now - real_entry) / real_entry * 100, 2) if real_entry else 0

            # Chuẩn hóa PnL về khoảng [-1, 1]. Coi PnL 25% là mức tối đa để có ảnh hưởng.
            # Điều này có nghĩa là lời 25% hay 100% đều có tác động như nhau.
            pnl_norm = max(-1.0, min(1.0, pnl / 25.0))

            # PnL có thể điều chỉnh tối đa +/- 0.75 điểm trên thang điểm 10.
            # Đây là "trọng số" của PnL. Bạn có thể thay đổi con số 0.75 này.
            PNL_ADJUSTMENT_WEIGHT = 0.75
            pnl_adjustment_score = pnl_norm * PNL_ADJUSTMENT_WEIGHT

            # Tính điểm cuối cùng của MyPrecious
            my_precious_score = base_score + pnl_adjustment_score
            my_precious_score = min(max(my_precious_score, 0), 10) # Kẹp lại trong khoảng 0-10

            # Ghi đè lại final_score trong advisor_decision để các hàm sau sử dụng
            advisor_decision['final_score'] = my_precious_score
            #--------------------------------------------------------------

            # Logic còn lại sẽ sử dụng my_precious_score (đã được cập nhật vào final_score)
            final_score = my_precious_score # Gán lại để các biến sau này dùng đúng

            # ### THAY ĐỔI 4: XÁC ĐỊNH LEVEL DỰA TRÊN FINAL_SCORE MỚI ###
            # Ngưỡng này có thể được tinh chỉnh cho phù hợp hơn
            level_key_map = [
                (3.0, "PANIC_SELL"), (4.0, "SELL"), (4.8, "AVOID"),
                (5.5, "HOLD"), (6.5, "WEAK_BUY"), (7.8, "BUY"), (10.1, "STRONG_BUY")
            ]
            level_key = next((lvl for thr, lvl in level_key_map if final_score < thr), "AVOID")

            # Gói dữ liệu để xây dựng báo cáo
            report_payload = {
                "trade": trade, "pnl": pnl, "advisor_decision": advisor_decision,
                "price_now": price_now, "real_entry": real_entry,
                "level_key": level_key, "all_indicators": all_indicators
            }
            overview_data.append(report_payload)
            level_counter[level_key] += 1

            # Logic kiểm tra thay đổi và gửi alert (giữ nguyên)
            prev = advisor_map.get(trade_id, {})
            pnl_change_significant = abs(prev.get("pnl_percent", 0) - pnl) > 3.0
            # Sử dụng final_score (đã điều chỉnh) để so sánh
            score_change_significant = abs(prev.get("final_score", 5.0) - final_score) > 0.8 # Tăng ngưỡng vì thang điểm 10

            if pnl_change_significant or score_change_significant:
                alert_msg = build_alert_message(report_payload)
                send_discord_alert(alert_msg)
                log_to_txt(f"SEND alert for {symbol} ({interval}) - Level: {level_key} | Score: {final_score:.1f} (Base: {base_score:.1f}, PnL Adj: {pnl_adjustment_score:+.2f})")

            # Cập nhật advisor_map với cả base_score và final_score
            advisor_map[trade_id] = {"id": trade_id, "pnl_percent": pnl, "final_score": final_score, "base_score": base_score}

        except Exception as e:
            log_to_txt(f"[CRITICAL ERROR] Failed to process trade {trade.get('id', 'N/A')}: {e}")
            import traceback
            log_to_txt(traceback.format_exc())

    print("\n[3/3] Generating overview report if needed...")
    if should_send_overview(cooldown_state) and overview_data:
        overview_msg = build_overview_report(overview_data, level_counter, now)
        send_discord_alert(overview_msg)
        cooldown_state["last_overview_timestamp"] = now.timestamp()
        print("✅ Overview report sent.")

    write_json(advisor_file, list(advisor_map.values()))
    write_json(COOLDOWN_STATE_PATH, cooldown_state)
    print(f"✅ Finished processing {len(trades)} open trades.")


# ==============================================================================
# ### THAY ĐỔI 5: CẬP NHẬT CÁC HÀM XÂY DỰNG MESSAGE ###
# Các hàm này giờ đây sẽ nhận `report_payload` và trích xuất dữ liệu từ đó
# ==============================================================================
def format_price(price):
    if not isinstance(price, (int, float)): return "N/A"
    return f"{price:.8f}" if price < 0.1 else f"{price:.4f}"

def generate_indicator_text_block(ind: dict) -> str:
    """
    Tạo khối hiển thị chỉ báo kỹ thuật chi tiết, đồng bộ với format của main.py.
    """
    # --- Helper để format số cho đẹp ---
    def f(val, precision=4):
        return f"{val:.{precision}f}" if isinstance(val, (int, float)) else str(val)

    # --- Trích xuất tất cả các chỉ số từ dict 'ind' ---
    price = ind.get('price', 0.0)
    trade_plan = ind.get('trade_plan', {})
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
    
    # Lấy thông tin tín hiệu kỹ thuật đã được gắn vào
    signal_details = ind.get("signal_details", {})
    signal_reason = signal_details.get('reason', '...')

    # --- Tạo khối hiển thị mới ---
    # Dòng đầu tiên vẫn giữ thông tin về trade plan
    header_line = f"Giá hiện tại: {format_price(price)} | Entry: {format_price(trade_plan.get('entry', 0))} | TP: {format_price(trade_plan.get('tp', 0))} | SL: {format_price(trade_plan.get('sl', 0))}"

    # Các dòng sau là chỉ báo chi tiết
    indicator_lines = f"""📈 EMA20: {f(ema_20)}
💪 RSI14: {f(rsi_14, 2)} ({rsi_div})
📉 MACD Line: {f(macd_line)}
📊 MACD Signal: {f(macd_signal_val)} → {str(macd_cross).capitalize()}
🧭 ADX: {f(adx, 2)}
🔺 BB Upper: {f(bb_upper)}
🔻 BB Lower: {f(bb_lower)}
🔊 Volume: {f(volume, 2)} / MA20: {f(vol_ma20, 2)}
🌀 Fibo 0.618: {f(fib_0_618)}
🕯️ Doji: {doji_note}
📈 Trend: {trend.capitalize()}
💸 CMF: {f(cmf)}
🔹 Tín hiệu KT: {signal_details.get('level', 'N/A')} ({signal_details.get('tag', 'N/A')}) – {signal_reason}"""

    return f"{header_line}\n{indicator_lines}"


def generate_summary_block(symbol: str, interval: str, pnl: float, advisor_decision: dict):
    final_score = advisor_decision.get('final_score', 5.0)
    tech_score = advisor_decision.get('tech_score', 5.0)
    ml_data = advisor_decision.get('ai_prediction', {})
    news_factor = advisor_decision.get('news_factor', 0)

    tech_desc = "Thị trường không rõ ràng"
    if tech_score >= 7: tech_desc = "Tín hiệu kỹ thuật ủng hộ"
    elif tech_score <= 3.5: tech_desc = "Tín hiệu kỹ thuật yếu, rủi ro"

    ai_desc = "Không có dữ liệu AI"
    if ml_data and 'prob_buy' in ml_data:
        ai_level = "AVOID" # Cần đọc level từ ml_report
        ml_log_path = os.path.join(AI_DIR, f"{symbol}_{interval}.json")
        if os.path.exists(ml_log_path):
           ai_level = load_json(ml_log_path, {}).get("level", "AVOID")

        ai_desc = f"🚧 {ai_level.replace('_', ' ')} – ML dự đoán: {ml_data.get('pct', 0):.2f}% ({ml_data.get('prob_buy', 0):.1f}%/{ml_data.get('prob_sell', 0):.1f}%)"

    news_desc = "Tích cực" if news_factor > 0 else "Tiêu cực" if news_factor < 0 else "Trung lập"
    return (f"📌 **Tổng hợp đánh giá:** {symbol} ({interval}) | PnL: {pnl:.2f}% | Final Score: {final_score:.1f}/10\n"
            f"🔹 **Kỹ thuật:** Score {tech_score:.1f}/10 → {tech_desc}\n"
            f"🔹 **AI:** {ai_desc}\n"
            f"🔹 **Tin tức & Bối cảnh:** {news_desc}")

def generate_news_and_context_block_v2(advisor_decision: dict) -> str:
    market_trend = advisor_decision.get("market_trend", "NEUTRAL")
    news_factor = advisor_decision.get("news_factor", 0.0)
    # Lấy lại market_context để hiển thị chi tiết hơn
    mc_data = advisor_decision.get("debug_info", {}).get("context_used", {}) # Cần thêm vào trade_advisor

    mc_text = (f"🌐 **Bối cảnh thị trường (Trend: {market_trend})** | "
               f"Fear & Greed: `{mc_data.get('fear_greed', 'N/A')}` | BTC.D: `{mc_data.get('btc_dominance', 'N/A')}%`")

    news_block = "⚪ Không có tin tức mới ảnh hưởng."
    if news_factor != 0.0:
        # Chúng ta không có sẵn tiêu đề tin tức ở đây, chỉ có điểm số
        # Đây là một sự đánh đổi khi tích hợp. Ta có thể diễn giải điểm số.
        if news_factor > 0:
            news_block = "🗞️ **Tin tức:** Có các tin tức mang tính tích cực."
        else:
            news_block = "🗞️ **Tin tức:** Có các tin tức mang tính tiêu cực."

    return f"{mc_text}\n{news_block}"

def generate_mta_block(symbol: str, current_interval: str, all_indicators: dict) -> str:
    lines = ["📊 **Phân tích Đa Khung thời gian:**"]
    for tf in ["1h", "4h", "1d"]:
        if tf == current_interval: continue
        ind_tf = all_indicators.get(symbol, {}).get(tf)
        if ind_tf:
            trend = ind_tf.get('trend', 'N/A')
            icon = "🔼" if trend == "uptrend" else "🔽" if trend == "downtrend" else "↔️"
            # Lấy dữ liệu AI cho khung thời gian phụ
            ai_data_tf = load_json(os.path.join(AI_DIR, f"{symbol}_{tf}.json"), {})
            ai_bias = "tăng" if ai_data_tf.get("prob_buy", 50) > 60 else "giảm" if ai_data_tf.get("prob_sell", 0) > 60 else "trung lập"

            lines.append(f"{icon} **{tf}**: Trend {trend:<9} | RSI: {ind_tf.get('rsi_14', 0):.1f} | AI: {ai_bias}")
    return "\n".join(lines) if len(lines) > 1 else ""

def generate_final_strategy_block(pnl: float, level_key: str, advisor_decision: dict) -> str:
    final_score = advisor_decision.get('final_score', 5.0)
    tech_score = advisor_decision.get('tech_score', 5.0)
    market_trend = advisor_decision.get('market_trend', "NEUTRAL")
    news_factor = advisor_decision.get("news_factor", 0)
    ml_data = advisor_decision.get("ai_prediction", {})

    reco_map = {
        "PANIC_SELL": "🔻 **Ưu tiên hàng đầu là thoát lệnh NGAY LẬP TỨC để bảo toàn vốn.**",
        "SELL": "🔻 **Tín hiệu tiêu cực chiếm ưu thế, cân nhắc giảm vị thế hoặc chốt lời/cắt lỗ.**",
        "AVOID": "⛔ **Thị trường rủi ro, không rõ ràng – nên đứng ngoài quan sát.**",
        "HOLD": "💎 **Giữ lệnh hiện tại.** Chưa nên mở thêm vị thế khi tín hiệu chưa đủ mạnh.",
        "WEAK_BUY": "🟢 **Có thể mua thăm dò với khối lượng nhỏ.** Cần quản lý rủi ro chặt chẽ.",
        "BUY": "🛒 **Tín hiệu MUA đang được củng cố.** Có thể xem xét vào lệnh tại các vùng hỗ trợ.",
        "STRONG_BUY": "🚀 **Tất cả các yếu tố đều ủng hộ xu hướng tăng.** Có thể tự tin gia tăng vị thế."
    }
    reco = [reco_map.get(level_key, "")]

    reasons = [
        f"**Cấp độ Lệnh:** {level_key} (dựa trên điểm tổng hợp {final_score:.1f}/10)",
        f"**Kỹ thuật:** Điểm {tech_score:.1f}/10. {'Tích cực.' if tech_score >= 7 else 'Tiêu cực.' if tech_score <= 3.5 else 'Trung lập.'}",
        f"**Bối cảnh:** {market_trend}. {'Hỗ trợ mạnh.' if 'UPTREND' in market_trend else 'Rủi ro lớn.' if 'DOWNTREND' in market_trend else 'Chưa rõ xu hướng.'}"
    ]
    if ml_data and 'prob_buy' in ml_data:
        reasons.append(f"**AI:** Dự báo có xu hướng {'tăng' if ml_data['prob_buy'] >= 60 else 'giảm' if ml_data['prob_buy'] <= 40 else 'trung lập'} (xác suất {ml_data['prob_buy']:.1f}%).")
    if news_factor != 0:
        reasons.append(f"**Tin tức:** Có yếu tố tin tức {'tích cực' if news_factor > 0 else 'tiêu cực'}.")

    summary_map = { "UPTREND": "bức tranh chung đang tích cực.", "DOWNTREND": "rủi ro từ thị trường chung là rất lớn.", "NEUTRAL": "thị trường chung đang đi ngang." }
    summary_text = f"Kết hợp các yếu tố, {summary_map.get(market_trend, '...')} Tín hiệu {level_key} nên được xem xét trong bối cảnh này."

    out = [f"🧠 **Chiến lược cuối cùng (Score: {final_score:.1f}):**"]
    out.extend([f"• {line}" for line in reco])
    out.append("📌 **Phân tích chi tiết:**")
    out.extend([f"– {r}" for r in reasons])
    out.append(f"📉 **Tổng kết:** {summary_text}")
    return "\n".join(out)

def build_alert_message(payload: dict) -> str:
    trade = payload["trade"]
    pnl = payload["pnl"]
    advisor_decision = payload["advisor_decision"]
    level_key = payload["level_key"]
    all_indicators = payload["all_indicators"]

    symbol, interval, trade_id = trade['symbol'], trade['interval'], trade['id']
    real_entry = payload["real_entry"]

    title_block = f"{ICON.get(level_key, ' ')} [{level_key.replace('_', ' ')}] Đánh giá lệnh: {symbol} ({interval})"

    info_block = (f"📌 ID: {trade_id}  {symbol}  {interval}\n"
                  f"📆 In time: {trade.get('in_time')}  |  Đã giữ: {calc_held_hours(trade.get('in_time'))} h  |  RealEntry: {format_price(real_entry)}\n"
                  f"💰 PnL: {round(trade.get('amount', 1000) * pnl / 100, 1):.1f} USD ({pnl:.2f}%)")

    # Lấy indicator của khung thời gian chính từ advisor_decision để hiển thị
    main_indicators = advisor_decision.get("full_indicators", {})
    main_indicators["trade_plan"] = parse_trade_plan(trade['trade_plan']) # Gắn tradeplan cũ vào
    main_indicators["signal_details"] = advisor_decision.get("signal_details", {})
    ind_text_block = generate_indicator_text_block(main_indicators)

    summary_block = generate_summary_block(symbol, interval, pnl, advisor_decision)

    # News block mới sẽ đơn giản hơn
    news_block = generate_news_and_context_block_v2(advisor_decision)

    mta_block = generate_mta_block(symbol, interval, all_indicators)
    final_strategy_block = generate_final_strategy_block(pnl, level_key, advisor_decision)

    return "\n\n".join(filter(None, [
        title_block, info_block, ind_text_block, summary_block,
        news_block, mta_block, final_strategy_block
    ]))

def build_overview_report(overview_data: list, level_counter: Counter, now: datetime) -> str:
    # Hàm này gần như không đổi, chỉ cần điều chỉnh cách lấy dữ liệu từ payload
    total_start = sum(t["trade"].get("amount", 1000) for t in overview_data)
    total_pnl_usd = sum(t["trade"].get("amount", 1000) * t["pnl"] / 100 for t in overview_data)

    lv_counts = ", ".join(f"{ICON[k]}{v}" for k, v in sorted(level_counter.items(), key=lambda item: list(ICON.keys()).index(item[0])))
    total_pnl_percent = (total_pnl_usd / total_start * 100) if total_start else 0.0

    header  = f"📊 **Tổng quan danh mục {now:%d-%m %H:%M}**\n"
    header += f"Lệnh: {len(overview_data)} | PnL Tổng: {total_pnl_usd:+.1f}$ ({total_pnl_percent:+.2f}%)\n"
    header += f"Phân bổ cấp: {lv_counts}"

    overview_lines = []
    # Sắp xếp theo điểm số cuối cùng
    for t_payload in sorted(overview_data, key=lambda x: x["advisor_decision"].get('final_score', 0)):
        t = t_payload["trade"]
        advisor_decision = t_payload["advisor_decision"]

        final_score = advisor_decision.get('final_score', 5.0)
        # Lấy base_score từ advisor_map nếu có, nếu không thì dùng final_score đã điều chỉnh
        # Điều này đảm bảo hiển thị đúng base_score ban đầu từ advisor
        trade_id = t_payload["trade"]["id"]
        base_score_from_log = load_json(os.path.join(ADVISOR_DIR, f"{now.strftime('%Y-%m-%d')}.json"), {})
        base_score_for_display = next((item.get("base_score", 5.0) for item in base_score_from_log if item.get("id") == trade_id), 5.0)

        tech_score = advisor_decision.get('tech_score', 5.0)
        ml_data = advisor_decision.get('ai_prediction', {})
        prob_buy = ml_data.get('prob_buy', 0)
        prob_sell = ml_data.get('prob_sell', 0)
        ai_icon = "🔼" if prob_buy > prob_sell else "🔽" if prob_sell > prob_buy else "↔️"
        ai_display_str = f"{prob_buy:.0f}/{prob_sell:.0f} {ai_icon}"

        line = (f"📌 **{t['symbol']} ({t['interval']})** | "
                f"PnL: {t_payload['pnl']:+.2f}% | "
                f"Entry: {format_price(t_payload.get('real_entry', 0))}\n"
                f"🧠 T:{tech_score:.1f} | AI:{ai_display_str} | **Score: {final_score:.1f}/10** (Base: {base_score_for_display:.1f}) {ICON.get(t_payload['level_key'], ' ')}")
        overview_lines.append(line)

    return header + "\n" + "-"*50 + "\n" + "\n".join(overview_lines)


if __name__ == "__main__":
    main()
