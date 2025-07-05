# /root/ricealert/order_alerter.py (Cải tiến - Phiên bản 3.2 - Tinh gọn & Phân cấp)

import os
import requests
from datetime import datetime
from dotenv import load_dotenv

# Tải các biến môi trường
load_dotenv()
WEBHOOK_URL = os.getenv("DISCORD_TRADE_WEBHOOK")

# --- Hàm tiện ích: Format giá linh hoạt ---
def format_price(price):
    if not isinstance(price, (int, float)): return price
    return f"{price:.8f}" if price < 0.1 else f"{price:.4f}"

def send_opportunity_alert(decision_data: dict):
    """
    Gửi cảnh báo đến Discord với định dạng Chi tiết & Gọn gàng.
    v3.2: Chỉ tập trung vào việc định dạng và gửi, loại bỏ logic quyết định.
          Phân cấp tiêu đề dựa trên điểm số nhận được.
    """
    if not WEBHOOK_URL:
        print("LỖI: DISCORD_TRADE_WEBHOOK chưa được cài đặt.")
        return

    # --- 1. Lấy thông tin cơ bản ---
    decision_type = decision_data.get('decision_type')
    final_score = decision_data.get('final_score', 0)
    ind = decision_data.get('full_indicators', {})
    symbol = ind.get('symbol', '???')
    interval = ind.get('interval', '???')
    current_time_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    alert_id = f"ID: {current_time_str} {symbol} {interval}"
    price_str = format_price(ind.get('price', 0))

    # --- 2. Tạo Tiêu đề Động theo phân cấp điểm ---
    title = f"ℹ️ **THÔNG BÁO: {symbol} ({interval})**" # Tiêu đề mặc định

    if decision_type == "OPPORTUNITY_BUY":
        if final_score >= 8.5:
            title = f"💎 **MUA KIM CƯƠNG (SS): {symbol} ({interval})**"
        elif final_score >= 7.5:
            title = f"🚀 **MUA MẠNH (S): {symbol} ({interval})**"
        elif final_score >= 6.5:
            title = f"✅ **MUA TIÊU CHUẨN (A): {symbol} ({interval})**"
        else: # Điểm từ 5.95 đến 6.49
            title = f"🟢 **MUA XEM XÉT (B): {symbol} ({interval})**"
            
    elif decision_type == "OPPORTUNITY_SELL":
        if final_score <= 1.5:
            title = f"🚨 **BÁN KHẨN CẤP (SS-): {symbol} ({interval})**"
        elif final_score <= 2.5:
            title = f"🆘 **BÁN RỦI RO CAO (S-): {symbol} ({interval})**"
        elif final_score <= 3.5:
            title = f"🔻 **BÁN CẢNH BÁO (A-): {symbol} ({interval})**"
        else: # Điểm từ 3.51 đến 3.95
            title = f"🟠 **BÁN XEM XÉT (B-): {symbol} ({interval})**"

    # --- 3. Tạo dòng tóm tắt các yếu tố ---
    signal_details = decision_data.get('signal_details', {})
    tech_summary = f"PTKT `{signal_details.get('level', 'N/A').upper()}/{signal_details.get('tag', 'N/A')}`"

    market_trend = decision_data.get('market_trend', 'NEUTRAL')
    news_factor = decision_data.get('news_factor', 0)
    news_icon = " 🗞️+" if news_factor > 0.5 else " 🗞️-" if news_factor < -0.5 else ""
    context_summary = f"Bối cảnh `{market_trend}{news_icon}`"
    
    ai_pred = decision_data.get('ai_prediction', {})
    ai_predicted_pct = ai_pred.get('pct')
    if ai_predicted_pct is not None:
        ai_summary = f"AI `Dự đoán {ai_predicted_pct:+.2f}%`"
    else:
        prob_buy = ai_pred.get('prob_buy', 50.0)
        prob_sell = ai_pred.get('prob_sell', 0.0)
        ai_skew = prob_buy - prob_sell
        ai_summary = f"AI `Skew {ai_skew:+.1f}`"
    
    summary_line = f"📊 Tóm tắt: {tech_summary} | {context_summary} | {ai_summary}"

    # --- 4. Format kế hoạch giao dịch ---
    plan = decision_data.get('combined_trade_plan', {})
    entry, tp, sl = plan.get('entry', 0), plan.get('tp', 0), plan.get('sl', 0)
    trade_plan_formatted = "N/A"
    if entry and tp and sl:
        trade_plan_formatted = (
            f"Entry `{format_price(entry)}` › TP `{format_price(tp)}` › SL `{format_price(sl)}` "
            f"| `{format_price(entry)}/{format_price(tp)}/{format_price(sl)}`" # Thêm backtick để dễ copy
        )

    # --- 5. Dựng chuỗi thông báo cuối cùng ---
    full_message = (
        f"{title}\n"
        f"**{alert_id}**\n"
        f"⭐ **Tổng điểm: {final_score:.1f}/10** (Giá: {price_str})\n"
        f"{summary_line}\n"
        f"🎯 **Kế hoạch:** {trade_plan_formatted}"
    )

    # --- 6. Gửi thông báo ---
    try:
        response = requests.post(WEBHOOK_URL, json={"content": full_message}, timeout=10)
        response.raise_for_status()
        print(f"✅ Đã gửi thông báo Order '{title.split(':')[0]}' cho {symbol}.")
    except requests.exceptions.RequestException as e:
        print(f"❌ Lỗi khi gửi thông báo đến Discord: {e}")
