# trade_advisor.py (Cập nhật - Phiên bản 5.3 - Debug Output)

# -*- coding: utf-8 -*-
# PHIÊN BẢN 5.3 - Debug Output
# Mô tả: Thêm các điểm thành phần đã chuẩn hóa vào debug_info để hiển thị.

import os
import json
from datetime import datetime
from typing import Dict, Tuple
from signal_logic import check_signal

# ==============================================================================
# =================== ⚙️ TRUNG TÂM CẤU HÌNH & TINH CHỈNH ⚙️ =====================
# ==============================================================================
FULL_CONFIG = {
    "NOTES": "Cấu hình được tinh chỉnh để tăng độ nhạy.",
    "WEIGHTS": { 'tech': 0.40, 'context': 0.30, 'ai': 0.30 }, # Trọng số mới của bạn
    "BASE_SCORE_MAP": {
        ("buy_high", "CRITICAL"): 8.5, ("buy_low", "CRITICAL"): 8.5,
        ("buy_high", "WARNING"): 7.5, ("buy_low", "WARNING"): 7.5,
        ("buy_high", "ALERT"): 6.5, ("buy_low", "ALERT"): 6.5,
        ("canbuy", "CRITICAL"): 7.0, ("canbuy", "WARNING"): 7.0,
        ("canbuy", "ALERT"): 6.0,
        ("neutral", "ANY"): 5.0,
        ("avoid", "ANY"): 4.0,
        ("sell_high", "ANY"): 2.5, ("sell_low", "ANY"): 2.5,
    },
    "SCORE_MODIFIERS": {
        "rsi_bullish_div": 1.5, "rsi_bearish_div": -2.0,
        "cmf_strong_pos": 1.0, "cmf_strong_neg": -1.0,
    },
    "DECISION_THRESHOLDS": {
        "buy": 5.95,
        "sell": 3.95
    },
    "TRADE_PLAN_RULES": {
        "default_rr_ratio": 1.8, "high_score_rr_ratio": 2.0,
        "critical_score_rr_ratio": 2.5, "default_sl_percent": 0.03
    },
    "CONTEXT_SETTINGS": {
        "NEWS_LEVEL_SCORE": {"CRITICAL": 2.0, "WARNING": 1.5, "ALERT": 1.0, "WATCHLIST": 0.5, "INFO": 0.2},
        "POSITIVE_NEWS_KEYWORDS": ["etf", "niêm yết", "listing", "adoption", "partnership", "approved", "upgrade", "launch", "mainnet", "burn", "available on", "will add"],
        "NEGATIVE_NEWS_KEYWORDS": ["kiện", "hacker", "scam", "bị điều tra", "tether", "sec sues", "sec charges", "hack", "exploit", "lawsuit", "delist", "downtime", "outage"]
    }
}

# Các hàm logic bên dưới không cần thay đổi...
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
NEWS_DIR = os.path.join(BASE_DIR, "ricenews/lognew")
AI_DIR = os.path.join(BASE_DIR, "ai_logs")
MARKET_CONTEXT_PATH = os.path.join(BASE_DIR, "ricenews/lognew/market_context.json")

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
    if mc.get('fear_greed', 50) > 68: up_score += 1
    elif mc.get('fear_greed', 50) < 35: down_score += 1
    if mc.get('btc_dominance', 50) > 55: up_score += 1
    elif mc.get('btc_dominance', 50) < 48: down_score += 1
    if up_score == 2: return "STRONG_UPTREND"
    if down_score == 2: return "STRONG_DOWNTREND"
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
    final_context = {"market_trend": market_trend, "news_factor": news_factor}
    ai_data = load_json(os.path.join(AI_DIR, f"{symbol}_{interval}.json"), {})
    return final_context, ai_data

def generate_combined_trade_plan(base_plan: dict, score: float, config: dict) -> dict:
    entry = base_plan.get('entry', 0)
    if entry == 0: return base_plan
    rules = config['TRADE_PLAN_RULES']
    risk_distance = entry - base_plan.get('sl', entry * (1 - rules['default_sl_percent']))
    if risk_distance <= 0: risk_distance = entry * rules['default_sl_percent']
    if score >= 8.5: reward_ratio = rules['critical_score_rr_ratio']
    elif score >= 7.0: reward_ratio = rules['high_score_rr_ratio']
    else: reward_ratio = rules['default_rr_ratio']
    reward_distance = risk_distance * reward_ratio
    new_tp = entry + reward_distance
    new_sl = entry - risk_distance
    return {"entry": entry, "tp": new_tp, "sl": new_sl}

def get_advisor_decision(
    symbol: str, interval: str, indicators: dict, config: dict,
    ai_data_override: Dict = None, context_override: Dict = None,
) -> Dict:
    if context_override is not None and ai_data_override is not None:
        context, ai_data = context_override, ai_data_override
    else:
        context, ai_data = get_live_context_and_ai(symbol, interval, config)
    market_trend = context.get("market_trend", "NEUTRAL")
    news_factor = context.get("news_factor", 0)
    signal_details = check_signal(indicators)
    tag = signal_details.get("tag", "avoid")
    level = signal_details.get("level", "HOLD")
    raw_tech_score = config['BASE_SCORE_MAP'].get((tag, level), config['BASE_SCORE_MAP'].get((tag, "ANY"), 4.5))
    modifiers = config['SCORE_MODIFIERS']
    if indicators.get('rsi_divergence') == 'bullish': raw_tech_score += modifiers['rsi_bullish_div']
    elif indicators.get('rsi_divergence') == 'bearish': raw_tech_score -= modifiers['rsi_bearish_div']
    cmf = indicators.get('cmf', 0)
    if cmf > 0.05: raw_tech_score += modifiers['cmf_strong_pos']
    elif cmf < -0.05: raw_tech_score -= modifiers['cmf_strong_neg']
    tech_score_10 = round(min(max(raw_tech_score, 0), 10), 1)
    
    weights = config['WEIGHTS'] # Lấy trọng số ở đây

    prob_buy = ai_data.get("prob_buy", 50.0)
    prob_sell = ai_data.get("prob_sell", 0.0)
    ai_skew = (prob_buy - prob_sell) / 100.0 # Giá trị AI đã scale

    market_score_map = {"STRONG_UPTREND": 1.0, "UPTREND": 0.5, "STRONG_DOWNTREND": -1.0, "DOWNTREND": -0.5}
    market_score = market_score_map.get(market_trend, 0)
    normalized_news_factor = news_factor / 3.0
    context_scaled = round(min(max((market_score + normalized_news_factor) / 2, -1.0), 1.0), 2) # Giá trị Context đã scale
    
    tech_scaled = (tech_score_10 / 5.0) - 1.0 # Giá trị Tech đã scale
    
    final_rating = (weights['tech'] * tech_scaled) + \
                   (weights['context'] * context_scaled) + \
                   (weights['ai'] * ai_skew)
    
    final_score = round(min(max((final_rating + 1) * 5, 0), 10), 1)
    
    thresholds = config['DECISION_THRESHOLDS']
    decision_type = "NEUTRAL"
    if final_score >= thresholds['buy']: decision_type = "OPPORTUNITY_BUY"
    elif final_score <= thresholds['sell']: decision_type = "OPPORTUNITY_SELL"
    
    base_trade_plan = indicators.get("trade_plan", {"entry": indicators.get("price", 0)})
    combined_trade_plan = generate_combined_trade_plan(base_trade_plan, final_score, config)
    
    return {
        "decision_type": decision_type, 
        "final_score": final_score, 
        "tech_score": tech_score_10,
        "signal_details": signal_details, 
        "ai_prediction": {"prob_buy": prob_buy, "prob_sell": prob_sell, "pct": ai_data.get('pct', None)}, # Ensure pct is passed
        "market_trend": market_trend, 
        "news_factor": news_factor,
        "full_indicators": indicators, 
        "combined_trade_plan": combined_trade_plan,
        "debug_info": {
            "weights_used": weights, 
            "config_notes": config.get("NOTES", "N/A"),
            # THAY ĐỔI: Thêm các điểm thành phần đã scale vào debug_info
            "tech_scaled_value": tech_scaled,
            "context_scaled_value": context_scaled,
            "ai_skew_value": ai_skew
        }
    }
