# /root/ricealert/trade_advisor.py

import os
import json
from datetime import datetime
from typing import Dict, Tuple, List, Set

# --- Các hàm tiện ích & Hằng số ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
NEWS_DIR = os.path.join(BASE_DIR, "ricenews/lognew")
AI_DIR = os.path.join(BASE_DIR, "ai_logs")
MARKET_CONTEXT_PATH = os.path.join(BASE_DIR, "ricenews/lognew/market_context.json")

# CẢI TIẾN: Định nghĩa trọng số cho mức độ tin tức
NEWS_LEVEL_SCORE = {
    "CRITICAL": 2.0,
    "WARNING": 1.5,
    "ALERT": 1.0,
    "WATCHLIST": 0.5,
    "INFO": 0.2
}

# CẢI TIẾN: Từ khóa được giữ nguyên
POSITIVE_NEWS_KEYWORDS = ["etf", "niêm yết", "listing", "adoption", "partnership", "approved", "upgrade", "launch", "mainnet", "burn", "available on", "will add"]
NEGATIVE_NEWS_KEYWORDS = ["kiện", "hacker", "scam", "bị điều tra", "tether", "sec sues", "sec charges", "hack", "exploit", "lawsuit", "delist", "downtime", "outage"]

def load_json(path: str, default):
    try:
        with open(path, "r", encoding="utf-8") as f: return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError): return default

# ======================= BẮT ĐẦU MÃ SỬA LỖI =======================
def get_news_sentiment(title: str) -> float:
    """
    Phân tích tiêu đề tin tức để xác định xu hướng dựa trên từ khóa.
    Trả về 1 cho tích cực, -1 cho tiêu cực, 0 cho trung tính.
    """
    title_lower = title.lower()
    # Logic đơn giản: tin tiêu cực sẽ ghi đè tin tích cực nếu có cả hai
    if any(keyword in title_lower for keyword in NEGATIVE_NEWS_KEYWORDS):
        return -1.0
    if any(keyword in title_lower for keyword in POSITIVE_NEWS_KEYWORDS):
        return 1.0
    return 0.0
# ======================== KẾT THÚC MÃ SỬA LỖI =========================

# --- Các hàm logic đã được cải tiến ---

def analyze_market_trend(mc: dict) -> str:
    if not mc: return "NEUTRAL"
    up_score, down_score = 0, 0
    if mc.get('fear_greed', 50) > 68: up_score += 1
    elif mc.get('fear_greed', 50) < 35: down_score += 1
    if mc.get('btc_dominance', 50) > 55: up_score += 1
    elif mc.get('btc_dominance', 50) < 48: down_score += 1
    if up_score == 2: return "STRONG_UPTREND"
    if down_score == 2: return "STRONG_DOWNTREND"
    if up_score > down_score: return "UPTREND"
    if down_score > down_score: return "DOWNTREND"
    return "NEUTRAL"

# CẢI TIẾN: Logic phân tích tin tức tinh vi hơn
def get_news_and_context_info(symbol: str) -> Tuple[Dict, str]:
    """
    Tính toán điểm tin tức tổng hợp thay vì chỉ chọn một tin.
    """
    market_context = load_json(MARKET_CONTEXT_PATH, {})
    market_trend = analyze_market_trend(market_context)

    today_path = os.path.join(NEWS_DIR, f"{datetime.now().strftime('%Y-%m-%d')}_news_signal.json")
    news_data = load_json(today_path, [])

    tag_clean = symbol.lower().replace("usdt", "").strip()

    # Lọc tin tức liên quan
    coin_news = [n for n in news_data if n.get("category_tag", "").lower() == tag_clean]

    news_factor = 0.0
    processed_news = coin_news

    # Nếu không có tin riêng, mới xét đến tin vĩ mô
    if not coin_news:
        processed_news = [n for n in news_data if n.get("category_tag") in {"MACRO", "GENERAL"}]

    # Tính điểm tổng hợp từ các tin đã lọc
    if processed_news:
        total_score = 0.0
        for news_item in processed_news:
            level = news_item.get('level', 'INFO')
            title = news_item.get('title', '')

            base_score = NEWS_LEVEL_SCORE.get(level, 0.1)
            sentiment_multiplier = get_news_sentiment(title) # 1, -1, hoặc 0

            total_score += (base_score * sentiment_multiplier)

        news_factor = total_score

    # Giới hạn giá trị của news_factor trong khoảng hợp lý, ví dụ [-3, 3]
    news_factor = max(-3.0, min(news_factor, 3.0))

    return {"market_trend": market_trend, "news_factor": news_factor}, market_trend

# TỐI ƯU HÓA: Hàm này giờ nhận dữ liệu đã được tính toán sẵn
def get_multi_timeframe_info(symbol: str, current_interval: str, all_indicators: Dict) -> str:
    """
    Sử dụng dữ liệu chỉ báo đã được tính toán trước để phân tích đa khung thời gian.
    """
    mta_text_lines = ["📊 **Phân tích Đa Khung thời gian:**"]

    for tf in ["1h", "4h", "1d"]:
        if tf == current_interval: continue

        # Lấy dữ liệu đã tính, không tính lại
        ind_tf = all_indicators.get(symbol, {}).get(tf)
        if not ind_tf: continue

        try:
            # Tải dữ liệu AI tương ứng
            ai_path_tf = os.path.join(AI_DIR, f"{symbol}_{tf}.json")
            ml_tf_data = load_json(ai_path_tf, {})

            icon = "🔼" if ind_tf.get("trend") == "uptrend" else "🔽" if ind_tf.get("trend") == "downtrend" else "↔️"
            ai_level = ml_tf_data.get('level', 'HOLD').replace('_', ' ')
            trend_text = f"Trend {ind_tf.get('trend', '?')}"

            mta_text_lines.append(f"{icon} {tf}: {trend_text:<18} | RSI: {round(ind_tf.get('rsi_14', 0), 1):<4.1f} | AI: {ai_level}")
        except Exception:
            pass

    if len(mta_text_lines) > 1:
        return "\n".join(mta_text_lines)
    return ""

def generate_combined_trade_plan(base_plan: dict, ai_data: dict) -> dict:
    # ... (Hàm này không thay đổi, giữ nguyên)
    entry = base_plan.get('entry', 0)
    tp = base_plan.get('tp', 0)
    sl = base_plan.get('sl', 0)

    prob_buy = ai_data.get("prob_buy", 50.0)
    prob_sell = ai_data.get("prob_sell", 0.0)
    ai_skew = prob_buy - prob_sell

    if ai_skew > 50:
        tp *= 1.015
        sl = (sl + entry) / 2
    elif ai_skew < -50:
        tp = (tp + entry) / 2
        sl *= 0.99

    return {"entry": entry, "tp": tp, "sl": sl}

# --- HÀM CHÍNH ĐƯỢC CÁCH MẠNG HÓA ---
# TỐI ƯU HÓA: Hàm này giờ nhận dữ liệu chỉ báo đã được tính toán trước
def get_advisor_decision(symbol: str, interval: str, indicators: dict, all_indicators: Dict, ai_data_override: Dict = None, context_override: Dict = None) -> Dict:
    if context_override:
        context_info = {"news_factor": context_override.get("news_factor", 0)}
        market_trend = context_override.get("market_trend", "NEUTRAL")
    else:
        context_info, market_trend = get_news_and_context_info(symbol)
    ai_data = ai_data_override if ai_data_override is not None else load_json(os.path.join(AI_DIR, f"{symbol}_{interval}.json"), {})
    # TỐI ƯU HÓA: Truyền dữ liệu đã tính vào hàm MTA
    mta_block = get_multi_timeframe_info(symbol, interval, all_indicators)
    # 2. Tính điểm theo trọng số (Logic không đổi)
    raw_tech_score = 5.0
    tag = indicators.get("tag", "neutral")
    if indicators.get('rsi_divergence') == 'bullish': raw_tech_score += 1.5
    if indicators.get('rsi_divergence') == 'bearish': raw_tech_score -= 1.5
    if indicators.get('macd_cross') == 'bullish': raw_tech_score += 1.0
    if indicators.get('macd_cross') == 'bearish': raw_tech_score -= 1.0
    if indicators.get('cmf', 0) > 0.1: raw_tech_score += 1.0
    if indicators.get('cmf', 0) < -0.1: raw_tech_score -= 1.0
    if tag in ["buy_high", "buy_low", "canbuy"]: raw_tech_score += 2.0
    if tag in ["sell_high", "sell_low", "avoid", "trend_down"]: raw_tech_score -= 2.0
    tech_score_10 = round(min(max(raw_tech_score, 0), 10), 1)
    tech_scaled = (tech_score_10 / 5.0) - 1.0

    prob_buy = ai_data.get("prob_buy", 50.0)
    prob_sell = ai_data.get("prob_sell", 0.0)
    ai_skew = (prob_buy - prob_sell) / 100.0

    market_score = 0
    if market_trend == "STRONG_UPTREND": market_score = 1.0
    elif market_trend == "UPTREND": market_score = 0.5
    elif market_trend == "STRONG_DOWNTREND": market_score = -1.0
    elif market_trend == "DOWNTREND": market_score = -0.5

    # CẢI TIẾN: Sử dụng news_factor đã được tính toán tinh vi hơn
    # Điểm bối cảnh giờ là trung bình của điểm thị trường và điểm tin tức
    # Chuẩn hóa news_factor bằng cách chia cho 3 (vì biên độ của nó là -3 đến +3)
    normalized_news_factor = context_info['news_factor'] / 3.0

    # Tính điểm bối cảnh với giá trị đã được chuẩn hóa
    context_scaled = round(min(max((market_score + normalized_news_factor) / 2, -1.0), 1.0), 2)

    # 3. Công thức trọng số (Không đổi)
    final_rating = (0.5 * tech_scaled) + (0.3 * ai_skew) + (0.2 * context_scaled)
    final_score = (final_rating + 1) * 5
    final_score = round(min(max(final_score, 0), 10), 1)

    # 4. Xác định quyết định (Không đổi)
    decision_type = "NEUTRAL"
    if final_score >= 6.5: decision_type = "OPPORTUNITY_BUY"
    elif final_score <= 3.5: decision_type = "OPPORTUNITY_SELL"

    # 5. Tạo trade plan kết hợp AI (Không đổi)
    base_trade_plan = indicators.get("trade_plan", {})
    combined_trade_plan = generate_combined_trade_plan(base_trade_plan, ai_data)

    return {
        "decision_type": decision_type,
        "final_score": final_score,
        "tech_score": tech_score_10,
        "ai_pct_change": ai_data.get('pct', 0),
        "market_trend": market_trend,
        "news_factor": context_info['news_factor'],
        "mta_block": mta_block,
        "full_indicators": indicators,
        "combined_trade_plan": combined_trade_plan,
    }
