# /root/ricealert/order_alerter.py
import os
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
WEBHOOK_URL = os.getenv("DISCORD_TRADE_WEBHOOK")

def send_opportunity_alert(decision_data: dict):
    if not WEBHOOK_URL:
        print("LỖI: DISCORD_TRADE_WEBHOOK chưa được cài đặt.")
        return

    ind = decision_data['full_indicators']
    symbol = ind['symbol']
    interval = ind['interval']
    price = ind['price']
    
    # CÁCH MẠNG: Lấy trade plan đã kết hợp AI
    trade_plan = decision_data.get('combined_trade_plan', {})
    
    score = decision_data['final_score']
    decision_type = decision_data['decision_type']

    if decision_type == "OPPORTUNITY_BUY":
        icon = "🚀"
        title_text = "CƠ HỘI MUA"
    elif decision_type == "OPPORTUNITY_SELL":
        icon = "📉"
        title_text = "CẢNH BÁO BÁN / TRÁNH"
    else:
        return

    title = f"{icon} **{title_text}: {symbol} ({interval})**"
    news_map = {1: 'Tích cực', -1: 'Tiêu cực', 0: 'Trung lập'}
    news_text = news_map.get(decision_data.get('news_factor', 0))

    summary_block = (
        f"🌟 **Điểm đánh giá: {score:.1f}/10**\n"
        f"├─ Kỹ thuật: `{decision_data.get('tech_score', 0):.1f}/10` (Tag: `{ind.get('tag', 'N/A')}`)\n"
        f"├─ AI Dự đoán: `{decision_data.get('ai_pct_change', 0):.2f}%`\n"
        f"└─ Bối cảnh: `{decision_data.get('market_trend', 'N/A')}` (Tin tức: `{news_text}`)"
    )

    # CÁCH MẠNG: Thay đổi tiêu đề để cho biết đây là plan đã có AI
    plan_block = (
        f"🎯 **Kế hoạch Giao dịch (AI-Enhanced):**\n"
        f"├─ Entry: `{trade_plan.get('entry', 0):.8f}`\n"
        f"├─ Take Profit: `{trade_plan.get('tp', 0):.8f}`\n"
        f"└─ Stop Loss: `{trade_plan.get('sl', 0):.8f}`"
    )

    mta_block = decision_data.get('mta_block', '')
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    footer = f"Generated at: {timestamp} | Signal Price: {price:.8f}"

    full_message = "\n\n".join(filter(None, [title, summary_block, plan_block, mta_block, footer]))

    try:
        requests.post(WEBHOOK_URL, json={"content": full_message}, timeout=10).raise_for_status()
        print(f"✅ Đã gửi thông báo '{title_text}' cho {symbol} đến kênh Order.")
    except requests.exceptions.RequestException as e:
        print(f"❌ Lỗi khi gửi thông báo đến Discord: {e}")


