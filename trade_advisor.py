# /root/ricealert/trade_advisor.py
# PHIÊN BẢN NÂNG CẤP: "Tổng Tư lệnh Thông thái"
#
# CHANGELOG:
# - TƯƠNG THÍCH HOÀN TOÀN: Cập nhật để đọc và hiểu cấu trúc file JSON mới
#   do ml_report.py phiên bản "Ultimate" tạo ra.
# - TRÍ TUỆ TỔNG HỢP: Sử dụng các giá trị `prob_buy`, `prob_sell` và `pct` đã được
#   tổng hợp (ensemble) từ cả 3 model, giúp quyết định cuối cùng trở nên
#   chất lượng và đáng tin cậy hơn.
# - TĂNG CƯỜNG MINH BẠCH: Lấy thêm thông tin chi tiết từ `expert_opinions`
#   và đính kèm vào dictionary trả về. Điều này cho phép các module khác
#   (như live_trade.py) có thể ghi log hoặc hiển thị chi tiết "ý kiến"
#   của từng chuyên gia AI.

import os
import json
from datetime import datetime
from typing import Dict, Tuple, Optional
from signal_logic import check_signal

# ==============================================================================
# ⚙️ TRUNG TÂM CẤU HÌNH & TINH CHỈNH (Không thay đổi)
# ==============================================================================
FULL_CONFIG = {
    "NOTES": "v7.0 - Ensemble AI Compatible",
    "SCORE_RANGE": 8.0,
    "WEIGHTS": { 'tech': 0.4, 'context': 0.2, 'ai': 0.4 },
    "DECISION_THRESHOLDS": { "buy": 6.0, "sell": 4.0 },
    "TRADE_PLAN_RULES": {
        "default_rr_ratio": 1.8, "high_score_rr_ratio": 2.2,
        "critical_score_rr_ratio": 2.8, "default_sl_percent": 0.03
    },
    "CONTEXT_SETTINGS": {
        "NEWS_LEVEL_SCORE": {"CRITICAL": 2.0, "WARNING": 1.5, "ALERT": 1.0, "WATCHLIST": 0.5, "INFO": 0.2},
        "POSITIVE_NEWS_KEYWORDS": ["etf", "niêm yết", "listing", "adoption", "partnership", "approved", "upgrade", "launch", "mainnet", "burn", "available on", "will add"],
        "NEGATIVE_NEWS_KEYWORDS": ["kiện", "hacker", "scam", "bị điều tra", "tether", "sec sues", "sec charges", "hack", "exploit", "lawsuit", "delist", "downtime", "outage"]
    }
}

# --- Các đường dẫn (Không thay đổi) ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Giả sử các file news và context vẫn nằm ở vị trí cũ
NEWS_DIR = os.path.join(BASE_DIR, "ricenews", "lognew")
AI_DIR = os.path.join(BASE_DIR, "ai_logs")
MARKET_CONTEXT_PATH = os.path.join(BASE_DIR, "ricenews", "lognew", "market_context.json")

# --- Các hàm helper (Không thay đổi) ---
def load_json(path: str, default):
    try:
        with open(path, "r", encoding="utf-8") as f: return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError): return default

def get_news_sentiment(title: str, config: dict) -> float:
    title_lower = title.lower()
    keywords = config['CONTEXT_SETTINGS']
    if any(f" {kw} " in f" {title_lower} " for kw in keywords['NEGATIVE_NEWS_KEYWORDS']): return -1.0
    if any(f" {kw} " in f" {title_lower} " for kw in keywords['POSITIVE_NEWS_KEYWORDS']): return 1.0
    return 0.0

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
    if up_score > down_score: return "UPTREND"
    if down_score > up_score: return "DOWNTREND"
    return "NEUTRAL"

def get_live_context_and_ai(symbol: str, interval: str, config: dict) -> Tuple[Dict, Dict]:
    market_context = load_json(MARKET_CONTEXT_PATH, {})
    market_trend = analyze_market_trend(market_context)
    today_path = os.path.join(NEWS_DIR, f"{datetime.now().strftime('%Y-%m-%d')}_news_signal.json")
    news_data = load_json(today_path, [])
    tag_clean = symbol.lower().replace("usdt", "").strip()
    coin_news = [n for n in news_data if n.get("category_tag", "").lower() == tag_clean]
    processed_news = coin_news if coin_news else [n for n in news_data if n.get("category_tag") in {"MACRO", "GENERAL"}]
    news_factor = 0.0
    if processed_news:
        news_level_score = config['CONTEXT_SETTINGS']['NEWS_LEVEL_SCORE']
        total_score = sum(news_level_score.get(n.get('level', 'INFO'), 0.1) * get_news_sentiment(n.get('title', ''), config) for n in processed_news)
        news_factor = total_score
    news_factor = max(-3.0, min(news_factor, 3.0))
    final_context = market_context.copy()
    final_context["market_trend"] = market_trend
    final_context["news_factor"] = news_factor
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

# ==============================================================================
# 🚀 HÀM QUYẾT ĐỊNH CHÍNH (ĐÃ NÂNG CẤP)
# ==============================================================================

def get_advisor_decision(
    symbol: str, interval: str, indicators: dict, config: dict,
    weights_override: Optional[Dict] = None,
) -> Dict:
    # --- Phần lấy context và AI không đổi ---
    context, ai_data = get_live_context_and_ai(symbol, interval, config)
    market_trend = context.get("market_trend", "NEUTRAL")
    news_factor = context.get("news_factor", 0)

    # --- 1. Tính điểm Phân tích Kỹ thuật (Không đổi) ---
    signal_details = check_signal(indicators)
    raw_tech_score = signal_details.get("raw_tech_score", 0.0)
    score_range = config.get("SCORE_RANGE", 8.0)
    tech_score_10 = round(min(max(5.0 + (raw_tech_score * 5.0 / score_range), 0), 10), 1)
    tech_scaled = (tech_score_10 / 5.0) - 1.0

    # --- 2. Tính điểm Bối cảnh (Không đổi) ---
    market_score_map = {"UPTREND": 0.5, "DOWNTREND": -0.5}
    market_score = market_score_map.get(market_trend, 0)
    normalized_news_factor = news_factor / 3.0
    context_scaled = round(min(max((market_score + normalized_news_factor) / 2, -1.0), 1.0), 2)

    # --- 3. (NÂNG CẤP) Tính điểm AI từ kết quả tổng hợp ---
    # Giờ đây, các giá trị này là kết quả từ "Hội đồng Chuyên gia AI"
    prob_buy = ai_data.get("prob_buy", 50.0)
    prob_sell = ai_data.get("prob_sell", 0.0)
    ai_skew = (prob_buy - prob_sell) / 100.0

    # --- 4. Tính điểm tổng hợp cuối cùng (Không đổi) ---
    weights = weights_override if weights_override is not None else config['WEIGHTS']
    final_rating = (weights['tech'] * tech_scaled) + \
                   (weights['context'] * context_scaled) + \
                   (weights['ai'] * ai_skew)
    final_score = round(min(max((final_rating + 1) * 5, 0), 10), 1)

    # --- 5. Ra quyết định (Không đổi) ---
    thresholds = config['DECISION_THRESHOLDS']
    decision_type = "NEUTRAL"
    if final_score >= thresholds['buy']:
        decision_type = "OPPORTUNITY_BUY"
    elif final_score <= thresholds['sell']:
        decision_type = "OPPORTUNITY_SELL"

    base_trade_plan = {"price": indicators.get("price", 0)}
    combined_trade_plan = generate_combined_trade_plan(base_trade_plan, final_score, config)

    # --- 6. (NÂNG CẤP) Đóng gói dictionary trả về ---
    # Thêm `expert_opinions` để tăng cường minh bạch
    return {
        "decision_type": decision_type,
        "final_score": final_score,
        "tech_score": tech_score_10,
        "signal_details": signal_details,
        "ai_prediction": {
            "prob_buy": prob_buy,
            "prob_sell": prob_sell,
            "pct": ai_data.get('pct', None),
            # (MỚI) Đính kèm ý kiến của từng chuyên gia
            "expert_opinions": ai_data.get('expert_opinions', {})
        },
        "market_trend": market_trend,
        "news_factor": news_factor,
        "full_indicators": indicators,
        "combined_trade_plan": combined_trade_plan,
        "debug_info": {
            "weights_used": weights,
            "config_notes": config.get("NOTES", "N/A"),
            "tech_scaled_value": tech_scaled,
            "context_scaled_value": context_scaled,
            "ai_skew_value": ai_skew,
            "context_used": context
        }
    }
