# /root/ricealert/trade_advisor.py
import os, json
from datetime import datetime
from typing import Dict, Tuple, Optional
from signal_logic import check_signal

# ==============================================================================
# =================== ⚙️ TRUNG TÂM CẤU HÌNH & TINH CHỈNH ⚙️ =====================
# ==============================================================================
FULL_CONFIG = {
    "NOTES": "v7.0 - Integrated News Score from rice_news",
    "SCORE_RANGE": 8.0,
    "WEIGHTS": { 'tech': 0.45, 'context': 0.2, 'ai': 0.35 }, # Tinh chỉnh lại trọng số một chút
    "DECISION_THRESHOLDS": { "buy": 6.0, "sell": 4.0 },
    "TRADE_PLAN_RULES": {
        "default_rr_ratio": 1.8, "high_score_rr_ratio": 2.2,
        "critical_score_rr_ratio": 2.8, "default_sl_percent": 0.03
    },
    # *** NÂNG CẤP 1: TINH GỌN CẤU HÌNH ***
    # Logic tính điểm tin tức đã được chuyển hoàn toàn sang rice_news.py.
    # Các từ khóa và điểm theo level ở đây không còn cần thiết nữa.
    "CONTEXT_SETTINGS": {
        # Hệ số này cho phép bạn tăng/giảm tầm ảnh hưởng của điểm tin tức một cách nhanh chóng.
        # > 1.0: Tăng ảnh hưởng của tin tức. < 1.0: Giảm ảnh hưởng.
        "NEWS_SCORE_MULTIPLIER": 1.0
    }
}

# ==============================================================================
# =================== 💻 LOGIC CHƯƠNG TRÌNH (ĐÃ NÂNG CẤP) 💻 ====================
# ==============================================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
NEWS_DIR = os.path.join(BASE_DIR, "ricenews/lognew")
AI_DIR = os.path.join(BASE_DIR, "ai_logs")
MARKET_CONTEXT_PATH = os.path.join(BASE_DIR, "ricenews/lognew/market_context.json")

def load_json(path: str, default):
    try:
        with open(path, "r", encoding="utf-8") as f: return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError): return default

# *** NÂNG CẤP 2: HÀM get_news_sentiment ĐÃ BỊ LOẠI BỎ ***
# Logic này giờ đây được xử lý hoàn toàn bên trong rice_news.py.

def analyze_market_trend(mc: dict) -> str:
    if not mc: return "NEUTRAL"
    up_score, down_score = 0, 0
    
    fear_greed_value = mc.get('fear_greed', 50)
    if fear_greed_value is None: fear_greed_value = 50

    btc_dominance_value = mc.get('btc_dominance', 50)
    if btc_dominance_value is None: btc_dominance_value = 50

    if fear_greed_value > 68: up_score += 1
    elif fear_greed_value < 35: down_score += 1

    if btc_dominance_value > 55: up_score += 1
    elif btc_dominance_value < 48: down_score += 1
    
    if up_score == 2: return "STRONG_UPTREND"
    if down_score == 2: return "STRONG_DOWNTREND"
    if up_score > down_score: return "UPTREND"
    if down_score > up_score: return "DOWNTREND"
    return "NEUTRAL"

# *** NÂNG CẤP 3: HÀM SỬ DỤNG TRỰC TIẾP ĐIỂM SỐ TỪ RICE_NEWS ***
def get_live_context_and_ai(symbol: str, interval: str, config: dict) -> Tuple[Dict, Dict]:
    market_context = load_json(MARKET_CONTEXT_PATH, {})
    market_trend = analyze_market_trend(market_context)
    today_path = os.path.join(NEWS_DIR, f"{datetime.now().strftime('%Y-%m-%d')}_news_signal.json")
    news_data = load_json(today_path, [])
    
    tag_clean = symbol.lower().replace("usdt", "").strip()
    
    # Lấy tin tức liên quan đến coin hoặc tin vĩ mô/chung
    relevant_news = [n for n in news_data if n.get("category_tag", "").lower() == tag_clean or n.get("category_tag") in {"MACRO", "GENERAL"}]
    
    # === LOGIC CỐT LÕI ĐƯỢC THAY ĐỔI TẠI ĐÂY ===
    # Thay vì tự tính toán phức tạp, nó chỉ cần cộng tổng trường 'news_score' đã có sẵn.
    news_factor = 0.0
    if relevant_news:
        news_factor = sum(n.get('news_score', 0.0) for n in relevant_news)

    # Áp dụng hệ số nhân để tinh chỉnh ảnh hưởng của tin tức nếu cần
    news_factor *= config['CONTEXT_SETTINGS'].get('NEWS_SCORE_MULTIPLIER', 1.0)
    
    final_context = market_context.copy()
    final_context["market_trend"] = market_trend
    final_context["news_factor"] = news_factor   # news_factor giờ là tổng điểm từ rice_news
    
    ai_data = load_json(os.path.join(AI_DIR, f"{symbol}_{interval}.json"), {})
    return final_context, ai_data

def generate_combined_trade_plan(base_plan: dict, score: float, config: dict) -> dict:
    entry = base_plan.get('price', 0)
    if entry == 0: return {"entry": 0, "tp": 0, "sl": 0}
    rules = config['TRADE_PLAN_RULES']
    risk_distance = entry * rules['default_sl_percent']
    reward_ratio = rules['default_rr_ratio']
    if score >= 8.5: reward_ratio = rules['critical_score_rr_ratio']
    elif score >= 7.0: reward_ratio = rules['high_score_rr_ratio']
    reward_distance = risk_distance * reward_ratio
    new_tp = entry + reward_distance
    new_sl = entry - risk_distance
    return {"entry": round(entry, 8), "tp": round(new_tp, 8), "sl": round(new_sl, 8)}

def get_advisor_decision(
    symbol: str, interval: str, indicators: dict, config: dict,
    ai_data_override: Optional[Dict] = None,
    context_override: Optional[Dict] = None,
    weights_override: Optional[Dict] = None,
) -> Dict:
    if context_override is not None and ai_data_override is not None:
        context, ai_data = context_override, ai_data_override
    else:
        context, ai_data = get_live_context_and_ai(symbol, interval, config)

    market_trend = context.get("market_trend", "NEUTRAL")
    news_factor = context.get("news_factor", 0)

    signal_details = check_signal(indicators)
    raw_tech_score = signal_details.get("raw_tech_score", 0.0)

    if raw_tech_score == 0.0 and "Thiếu dữ liệu" in signal_details.get("reason", ""):
        required_keys_from_logic = ["rsi_1h", "rsi_4h", "rsi_1d", "price", "volume", "vol_ma20", "macd_cross", "adx", "trend", "cmf", "bb_upper", "bb_lower"]
        missing_keys = [key for key in required_keys_from_logic if indicators.get(key) is None]
        print(f"[DEBUG-ADVISOR] 🕵️ Score thô=0. Lý do: '{signal_details.get('reason')}'. Các chỉ báo bị thiếu: {missing_keys}")

    score_range = config.get("SCORE_RANGE", 8.0)
    tech_score_10 = round(min(max(5.0 + (raw_tech_score * 5.0 / score_range), 0), 10), 1)
    tech_scaled = (tech_score_10 / 5.0) - 1.0

    prob_buy = ai_data.get("prob_buy", 50.0)
    prob_sell = ai_data.get("prob_sell", 0.0)
    ai_skew = (prob_buy - prob_sell) / 100.0

    market_score_map = {"STRONG_UPTREND": 1.0, "UPTREND": 0.5, "STRONG_DOWNTREND": -1.0, "DOWNTREND": -0.5}
    market_score = market_score_map.get(market_trend, 0)
    
    # Chuẩn hóa news_factor. Giả định rằng tổng điểm tin tức hiếm khi vượt quá 20.
    # Con số này có thể được điều chỉnh sau khi quan sát thực tế.
    normalized_news_factor = news_factor / 20.0 
    
    context_scaled = round(min(max((market_score + normalized_news_factor) / 2, -1.0), 1.0), 2)

    weights = weights_override if weights_override is not None else config['WEIGHTS']
    final_rating = (weights['tech'] * tech_scaled) + \
                   (weights['context'] * context_scaled) + \
                   (weights['ai'] * ai_skew)

    final_score = round(min(max((final_rating + 1) * 5, 0), 10), 1)

    thresholds = config['DECISION_THRESHOLDS']
    decision_type = "NEUTRAL"
    if final_score >= thresholds['buy']:
        decision_type = "OPPORTUNITY_BUY"
    elif final_score <= thresholds['sell']:
        decision_type = "OPPORTUNITY_SELL"

    base_trade_plan = {"price": indicators.get("price", 0)}
    combined_trade_plan = generate_combined_trade_plan(base_trade_plan, final_score, config)

    return {
        "decision_type": decision_type, "final_score": final_score, "tech_score": tech_score_10,
        "signal_details": signal_details,
        "ai_prediction": {"prob_buy": prob_buy, "prob_sell": prob_sell, "pct": ai_data.get('pct', None)},
        "market_trend": market_trend, "news_factor": news_factor,
        "full_indicators": indicators, "combined_trade_plan": combined_trade_plan,
        "debug_info": {
            "weights_used": weights, "config_notes": config.get("NOTES", "N/A"),
            "tech_scaled_value": tech_scaled, "context_scaled_value": context_scaled, "ai_skew_value": ai_skew,
            "context_used": context
        }
    }
