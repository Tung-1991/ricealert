# /root/ricealert/trade_advisor.py
import os
import json
from datetime import datetime
from typing import Dict, Tuple

# --- Các hàm tiện ích (Không thay đổi) ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
NEWS_DIR = os.path.join(BASE_DIR, "ricenews/lognew")
AI_DIR = os.path.join(BASE_DIR, "ai_logs")
MARKET_CONTEXT_PATH = os.path.join(BASE_DIR, "ricenews/lognew/market_context.json")
POSITIVE_NEWS_KEYWORDS = ["etf", "niêm yết", "listing", "adoption", "partnership", "approved", "upgrade", "launch", "mainnet", "burn", "available on", "will add"]
NEGATIVE_NEWS_KEYWORDS = ["kiện", "hacker", "scam", "bị điều tra", "tether", "sec sues", "sec charges", "hack", "exploit", "lawsuit", "delist", "downtime", "outage"]

def load_json(path: str, default):
    try:
        with open(path, "r", encoding="utf-8") as f: return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError): return default

# --- Các hàm logic (Giữ nguyên logic đã cải tiến) ---
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
    if down_score > up_score: return "DOWNTREND"
    return "NEUTRAL"

def get_news_and_context_info(symbol: str) -> Tuple[Dict, str]:
    market_context = load_json(MARKET_CONTEXT_PATH, {})
    market_trend = analyze_market_trend(market_context)
    today_path = os.path.join(NEWS_DIR, f"{datetime.now().strftime('%Y-%m-%d')}_news_signal.json")
    news_data = load_json(today_path, [])
    tag_clean = symbol.lower().replace("usdt", "").strip()
    news_factor = 0
    coin_news = [n for n in news_data if n.get("category_tag", "").lower() == tag_clean]
    if coin_news:
        levels = ["CRITICAL", "WARNING", "ALERT", "WATCHLIST", "INFO"]
        coin_news.sort(key=lambda x: levels.index(x.get('level', 'INFO')))
        if "positive" in get_news_sentiment(coin_news[0]['title']): news_factor = 1
        elif "negative" in get_news_sentiment(coin_news[0]['title']): news_factor = -1
    else:
        macro_news = [n for n in news_data if n.get("category_tag") in {"MACRO", "GENERAL"}]
        if macro_news:
            if "positive" in get_news_sentiment(macro_news[0]['title']): news_factor = 1.0
            elif "negative" in get_news_sentiment(macro_news[0]['title']): news_factor = -1.0
    return {"market_trend": market_trend, "news_factor": news_factor}, market_trend

def get_multi_timeframe_info(symbol: str, current_interval: str, cached_data: Dict) -> str:
    from indicator import calculate_indicators
    mta_text_lines = ["📊 **Phân tích Đa Khung thời gian:**"]
    for tf in ["1h", "4h", "1d"]:
        if tf == current_interval: continue
        try:
            df_tf = cached_data.get(tf, {}).get(symbol)
            if df_tf is None or df_tf.empty: continue
            ind_tf = calculate_indicators(df_tf, symbol, tf)
            ai_path_tf = os.path.join(AI_DIR, f"{symbol}_{tf}.json")
            ml_tf_data = load_json(ai_path_tf, {})
            icon = "🔼" if ind_tf.get("trend") == "uptrend" else "🔽" if ind_tf.get("trend") == "downtrend" else "↔️"
            ai_level = ml_tf_data.get('level', 'HOLD').replace('_', ' ')
            trend_text = f"Trend {ind_tf.get('trend', '?')}"
            mta_text_lines.append(f"{icon} {tf}: {trend_text:<18} | RSI: {round(ind_tf.get('rsi_14', 0), 1):<4.1f} | AI: {ai_level}")
        except Exception: pass
    if len(mta_text_lines) > 1:
        last_line = mta_text_lines[-1]
        mta_text_lines[-1] = '└' + last_line[1:]
        return "\n".join(mta_text_lines)
    return ""

# CÁCH MẠNG: Hàm tạo trade plan thông minh
def generate_combined_trade_plan(base_plan: dict, ai_data: dict) -> dict:
    """Điều chỉnh Take Profit và Stop Loss dựa trên sự tự tin của AI."""
    entry = base_plan.get('entry', 0)
    tp = base_plan.get('tp', 0)
    sl = base_plan.get('sl', 0)

    prob_buy = ai_data.get("prob_buy", 50.0)
    prob_sell = ai_data.get("prob_sell", 0.0)
    ai_skew = prob_buy - prob_sell # Thang điểm -100 đến +100

    if ai_skew > 50: # AI rất tự tin mua
        tp *= 1.015 # Nới TP thêm 1.5%
        sl = (sl + entry) / 2 # Kéo SL về gần entry hơn
    elif ai_skew < -50: # AI rất tự tin bán
        tp = (tp + entry) / 2 # Kéo TP về gần entry
        sl *= 0.99 # Nới SL ra xa hơn 1%

    return {"entry": entry, "tp": tp, "sl": sl}

# --- HÀM CHÍNH ĐƯỢC CÁCH MẠNG HÓA ---
def get_advisor_decision(symbol: str, interval: str, indicators: dict, cached_data: Dict) -> Dict:
    # 1. Thu thập dữ liệu
    context_info, market_trend = get_news_and_context_info(symbol)
    ai_data = load_json(os.path.join(AI_DIR, f"{symbol}_{interval}.json"), {})
    mta_block = get_multi_timeframe_info(symbol, interval, cached_data)

    # 2. CÁCH MẠNG: Tính điểm theo trọng số, không cộng dồn
    # 2.1. Điểm kỹ thuật (Thang -1 đến +1)
    # Dựa trên signal_logic, chúng ta tính điểm thô trước
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
    tech_scaled = (tech_score_10 / 5.0) - 1.0 # Chuẩn hóa về thang -1 đến +1

    # 2.2. Điểm AI (Thang -1 đến +1)
    prob_buy = ai_data.get("prob_buy", 50.0)
    prob_sell = ai_data.get("prob_sell", 0.0)
    ai_skew = (prob_buy - prob_sell) / 100.0

    # 2.3. Điểm bối cảnh (Thang -1 đến +1)
    market_score = 0
    if market_trend == "STRONG_UPTREND": market_score = 1.0
    elif market_trend == "UPTREND": market_score = 0.5
    elif market_trend == "STRONG_DOWNTREND": market_score = -1.0
    elif market_trend == "DOWNTREND": market_score = -0.5
    news_score = context_info['news_factor'] * 0.5 # Giảm trọng số tin tức vĩ mô
    context_scaled = round(min(max(market_score + news_score, -1.0), 1.0), 2)
    
    # 3. CÁCH MẠNG: Công thức trọng số
    # Trọng số: Kỹ thuật 55%, AI 25%, Bối cảnh 20%
    final_rating = (0.55 * tech_scaled) + (0.25 * ai_skew) + (0.20 * context_scaled)
    final_score = (final_rating + 1) * 5 # Chuẩn hóa về thang 0-10
    final_score = round(min(max(final_score, 0), 10), 1)
    
    # 4. Xác định quyết định
    decision_type = "NEUTRAL"
    if final_score >= 6.5: decision_type = "OPPORTUNITY_BUY"
    elif final_score <= 3.5: decision_type = "OPPORTUNITY_SELL"

    # 5. CÁCH MẠNG: Tạo trade plan kết hợp AI
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
        "combined_trade_plan": combined_trade_plan, # Trả về plan mới
    }
