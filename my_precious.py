# -*- coding: utf-8 -*-
"""my_precious.py – position advisor
Version: 3.9 (Definitive Fix)
Date: 2025-07-03
Description: This version definitively fixes all formatting and logic issues.
             - All NameErrors are resolved.
             - Market Context is correctly placed within the News block.
             - Redundant news display is eliminated.
             - The periodic overview summary feature (08:02, 20:02) is present and correct.
"""
import os
import json
import time
from datetime import datetime
from collections import Counter
from typing import List, Dict, Any
import math
import requests
import html
import re

from dotenv import load_dotenv

# These are assumed to be in the same directory or accessible via PYTHONPATH
from indicator import get_price_data, calculate_indicators
from signal_logic import check_signal

load_dotenv()
WEBHOOK_URL = os.getenv("DISCORD_PRECIOUS")

# ==============================================================================
# CONFIG & PATHS
# ==============================================================================
BASE_DIR = "/root/ricealert"
COOLDOWN_STATE_PATH = os.path.join(BASE_DIR, "advisor_log/cooldown_state.json")
MARKET_CONTEXT_PATH = os.path.join(BASE_DIR, "ricenews/lognew/market_context.json")
TRADELOG_DIR = os.path.join(BASE_DIR, "trade/tradelog")
ADVISOR_DIR  = os.path.join(BASE_DIR, "advisor_log")
LOG_DIR      = os.path.join(ADVISOR_DIR, "log")
NEWS_DIR     = os.path.join(BASE_DIR, "ricenews/lognew")
AI_DIR       = os.path.join(BASE_DIR, "ai_logs")

os.makedirs(LOG_DIR, exist_ok=True)

LEVEL_COOLDOWN_MINUTES: Dict[str, int] = {
    "PANIC_SELL": 180, "SELL": 240, "AVOID": 300,
    "HOLD": 360, "WEAK_BUY": 300, "BUY": 240, "STRONG_BUY": 180,
}

ICON = {"PANIC_SELL":"🆘","SELL":"🔻","AVOID":"⛔",
        "HOLD":"💎","WEAK_BUY":"🟢","BUY":"🛒","STRONG_BUY":"🚀"}

# ==============================================================================
# NEWS & MARKET CONTEXT LOGIC
# ==============================================================================
POSITIVE_NEWS_KEYWORDS = ["etf", "niêm yết", "listing", "adoption", "partnership", "approved", "upgrade", "launch", "mainnet", "burn"]
NEGATIVE_NEWS_KEYWORDS = ["kiện", "hacker", "scam", "bị điều tra", "tether", "sec sues", "sec charges", "hack", "exploit", "lawsuit", "delist", "downtime", "outage"]
NEWS_KEYWORDS_BY_LEVEL = {
    "CRITICAL": ["will list", "etf approval", "halving", "fomc", "interest rate", "cpi", "war", "approved", "regulatory approval"],
    "WARNING": ["delist", "unlock", "hack", "exploit", "sec", "lawsuit", "regulation", "maintenance", "downtime", "outage", "bị điều tra", "kiện"],
}

def analyze_market_trend(mc: dict) -> str:
    if not mc: return "NEUTRAL"
    up_score, down_score = 0, 0
    if mc.get('btc_dominance', 50) > 55: up_score += 1
    elif mc.get('btc_dominance', 50) < 48: down_score += 1
    if mc.get('fear_greed', 50) > 60: up_score += 1
    elif mc.get('fear_greed', 50) < 40: down_score += 1
    if up_score > down_score: return "UPTREND"
    if down_score > up_score: return "DOWNTREND"
    return "NEUTRAL"

def get_news_sentiment(title: str) -> str:
    lowered = title.lower()
    if any(keyword in lowered for keyword in POSITIVE_NEWS_KEYWORDS): return "positive"
    if any(keyword in lowered for keyword in NEGATIVE_NEWS_KEYWORDS): return "negative"
    return "neutral"

def load_news_and_context_block(symbol: str, market_context: dict) -> (str, int):
    today_path = os.path.join(NEWS_DIR, f"{datetime.now().strftime('%Y-%m-%d')}_news_signal.json")
    news_data = load_json(today_path, [])
    tag = symbol.lower().replace("usdt", "").strip()
    
    mc_text = ""
    if market_context:
        trend = analyze_market_trend(market_context)
        mc_text = (f"🌐 **Bối cảnh thị trường (Trend: {trend})** | "
                   f"Fear & Greed: `{market_context.get('fear_greed', 'N/A')}` | BTC.D: `{market_context.get('btc_dominance', 'N/A')}%`")

    news_block, news_factor = "⚪ Hiện chưa có tin tức đáng chú ý.", 0
    coin_news = [n for n in news_data if n.get("category_tag") == tag]
    if coin_news:
        news_block = "🗞️ **Tin tức liên quan:**\n" + "\n".join(f"- [{n['source_name']}] {n['title']} → {n['suggestion'].split('👉')[0].strip()}" for n in coin_news[:2])
        news_factor = 1 if get_news_sentiment(coin_news[0]['title']) == 'positive' else -1 if get_news_sentiment(coin_news[0]['title']) == 'negative' else 0
    else:
        macro_news = [n for n in news_data if n.get("category_tag") in {"macro", "general"} and n.get("level") in NEWS_KEYWORDS_BY_LEVEL]
        if macro_news:
            news_block = "🌐 **Tin vĩ mô đáng chú ý:**\n" + "\n".join(f"- [{n['source_name']}] {n['title']} → {n['suggestion'].split('👉')[0].strip()}" for n in macro_news[:2])
            news_factor = 1 if get_news_sentiment(macro_news[0]['title']) == 'positive' else -1 if get_news_sentiment(macro_news[0]['title']) == 'negative' else 0

    return f"{mc_text}\n{news_block}" if mc_text else news_block, news_factor

# ==============================================================================
# UTILITY FUNCTIONS
# ==============================================================================
def load_json(path: str, default):
    try:
        with open(path, "r", encoding="utf-8") as f: return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError): return default

def write_json(path: str, data) -> None:
    with open(path, "w", encoding="utf-8") as f: json.dump(data, f, indent=2, ensure_ascii=False)

def load_cooldown_state() -> Dict[str, Dict[str, str]]:
    return load_json(COOLDOWN_STATE_PATH, {})

def save_cooldown_state(state: dict) -> None:
    write_json(COOLDOWN_STATE_PATH, state)

def is_cooldown_passed(last_sent: str, level: str, now: datetime) -> bool:
    try:
        minutes = LEVEL_COOLDOWN_MINUTES.get(level.replace(" ", "_").upper(), 180)
        delta = (now - datetime.strptime(last_sent, "%Y-%m-%d %H:%M:%S")).total_seconds() / 60
        return delta >= minutes
    except Exception: return True

def send_discord_alert(msg: str) -> None:
    if not WEBHOOK_URL:
        print("[ERROR] DISCORD_PRECIOUS webhook not set.")
        return
    for i in range(0, len(msg), 1950):
        chunk = msg[i:i+1950]
        try:
            requests.post(WEBHOOK_URL, json={"content": chunk}, timeout=10).raise_for_status()
            time.sleep(1)
        except Exception as e: print(f"[ERROR] Discord alert failed: {e}")

def calc_held_hours(start_str: str) -> float:
    try:
        t = datetime.strptime(start_str, "%Y-%m-%d %H:%M:%S")
        return round((datetime.now() - t).total_seconds() / 3600, 1)
    except: return 0.0

def log_to_txt(msg: str) -> None:
    log_file = os.path.join(LOG_DIR, f"{datetime.now().strftime('%Y-%m-%d')}.txt")
    with open(log_file, "a", encoding='utf-8') as f:
        f.write(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")

def round_num(val, d=2) -> any:
    return round(val, d) if isinstance(val, (float, int)) else val

def is_overview_time() -> bool:
    return datetime.now().strftime("%H:%M") in ["08:02", "20:02"]
    #return True
# ==============================================================================
# CORE ANALYSIS & SCORING
# ==============================================================================
def parse_trade_plan(plan_str: str) -> dict:
    try: e, t, s = map(float, plan_str.split("/")); return {"entry": e, "tp": t, "sl": s}
    except Exception: return {"entry": 0, "tp": 0, "sl": 0}

def calc_score(ind: dict, market_trend: str) -> int:
    score = 5.0
    if ind.get("trend_alignment_bonus"): score += 1.0
    rsi = ind.get("rsi_14", 50)
    if rsi < 30 or rsi > 70: score += 1.0
    if ind.get("macd_cross") == "bullish": score += 0.5
    elif ind.get("macd_cross") == "bearish": score -= 0.5
    cmf = ind.get("cmf", 0)
    if cmf > 0.05: score += 1.0
    elif cmf < -0.05: score -= 1.0
    if ind.get("adx", 0) > 25: score += 1.0
    if ind.get("rsi_divergence") == "bullish": score += 1.5
    elif ind.get("rsi_divergence") == "bearish": score -= 1.5
    tag = ind.get("tag", "")
    if tag in ["buy_high", "buy_low"]: score += 1.0
    is_buy_signal = tag in ["buy_high", "buy_low", "canbuy"]
    is_sell_signal = tag in ["sell_high", "sell_low"]
    if market_trend == "UPTREND":
        if is_buy_signal: score += 1.5
        if is_sell_signal: score -= 1.0
    elif market_trend == "DOWNTREND":
        if is_buy_signal: score -= 2.0
        if is_sell_signal: score += 1.5
    return int(min(max(score, 0), 10))

# ==============================================================================
# OUTPUT GENERATION
# ==============================================================================
def format_price(price):
    if not isinstance(price, (int, float)): return price
    return f"{price:.8f}" if price < 0.1 else f"{price:.4f}"

def generate_indicator_text_block(ind: dict) -> str:
    lines = [
        f"Giá hiện tại: {format_price(ind['price'])}  |  Entry {format_price(ind['trade_plan']['entry'])}  |  TP {format_price(ind['trade_plan']['tp'])}  |  SL {format_price(ind['trade_plan']['sl'])}",
        f"📈 EMA20: {round_num(ind['ema_20'])}   💪 RSI14: {round_num(ind['rsi_14'])} → {'quá mua' if ind['rsi_14']>70 else 'quá bán' if ind['rsi_14']<30 else 'trung tính'}",
        f"📉 MACD: {round_num(ind['macd_line'],3)} vs Signal: {round_num(ind['macd_signal'],3)} → {ind['macd_cross']}",
        f"📊 ADX: {round_num(ind['adx'],1)} → {'có trend' if ind['adx']>20 else 'yếu'}",
        f"🔊 Volume: {int(ind['volume']):,} / MA20: {int(ind['vol_ma20']):,}",
        f"💸 CMF: {round_num(ind['cmf'],3)}",
        f"🌀 Fibo 0.618: {round_num(ind['fib_0_618'],4)}",
        f"⬆️ Trend cục bộ: {ind['trend']}",
    ]
    if ind.get("signal_level") and ind.get("signal_reason"):
        lines.append(f"🔹 Tín hiệu kỹ thuật: {ind['signal_level']} ({ind.get('tag', 'N/A')}) – {ind['signal_reason']}")
    return "\n".join(lines)

def generate_summary_block(symbol, interval, pnl, score, ml_data, news_factor, final_rating_normalized):
    tech_desc = "Thị trường không rõ ràng, cần quan sát thêm"
    if score >= 7: tech_desc = "Tín hiệu kỹ thuật ủng hộ"
    elif score <= 3: tech_desc = "Tín hiệu kỹ thuật yếu, rủi ro cao"
    ai_desc = "Không có dữ liệu AI"
    if ml_data:
        ai_desc = f"🚧 {ml_data.get('level', 'AVOID').replace('_', ' ')} – ML dự đoán: {ml_data.get('pct', 0):.2f}% (xác suất: {ml_data.get('score', 0):.1f}%)"
    news_desc = "Tích cực" if news_factor > 0 else "Tiêu cực" if news_factor < 0 else "Trung lập"
    return (f"📌 **Tổng hợp đánh giá:** {symbol} ({interval}) | PnL: {pnl:.2f}% | Final: {final_rating_normalized:.1%}\n"
            f"🔹 **Kỹ thuật:** Score {score}/10 → {tech_desc}\n"
            f"🔹 **AI:** {ai_desc}\n"
            f"🔹 **Tin tức:** {news_desc}")

def generate_mta_block(extra_tf: dict) -> str:
    if not extra_tf: return ""
    lines = ["📊 **Phân tích Đa Khung thời gian:**"]
    for tf, tfdata in sorted(extra_tf.items()):
        icon = "🔼" if tfdata.get("trend") == "uptrend" else "🔽" if tfdata.get("trend") == "downtrend" else "↔️"
        ai_bias = "tăng" if tfdata.get("ai_bias") == "bullish" else "giảm" if tfdata.get("ai_bias") == "bearish" else "trung lập"
        lines.append(f"{icon} **{tf}**: Trend {tfdata.get('trend', '?'):<9} | RSI: {tfdata.get('rsi', 0):.1f} | AI: {ai_bias}")
    return "\n".join(lines)

def generate_final_strategy_block(pnl: float, score: int, ml_data: dict, news_factor: int, ind: dict, market_context: dict) -> str:
    reco, reasons = [], []
    market_trend = analyze_market_trend(market_context)
    lvl = ind.get("level_key", "")
    if lvl == "PANIC_SELL": reco.append("🔻 **Ưu tiên hàng đầu là thoát lệnh NGAY LẬP TỨC để bảo toàn vốn.**")
    elif lvl == "SELL": reco.append("🔻 **Tín hiệu tiêu cực chiếm ưu thế, cân nhắc giảm vị thế hoặc chốt lời/cắt lỗ.**")
    elif lvl == "AVOID": reco.append("⛔ **Thị trường rủi ro, không rõ ràng – nên đứng ngoài quan sát.**")
    elif lvl == "HOLD": reco.append("💎 **Giữ lệnh hiện tại.** Chưa nên mở thêm vị thế khi tín hiệu chưa đủ mạnh.")
    elif lvl == "WEAK_BUY": reco.append("🟢 **Có thể mua thăm dò với khối lượng nhỏ.** Cần quản lý rủi ro chặt chẽ.")
    elif lvl == "BUY": reco.append("🛒 **Tín hiệu MUA đang được củng cố.** Có thể xem xét vào lệnh tại các vùng hỗ trợ.")
    elif lvl == "STRONG_BUY": reco.append("🚀 **Tất cả các yếu tố đều ủng hộ xu hướng tăng.** Có thể tự tin gia tăng vị thế.")
    
    reasons.append(f"**Cấp độ Lệnh:** {lvl} (dựa trên điểm tổng hợp)")
    reasons.append(f"**Kỹ thuật:** Điểm {score}/10. {'Tín hiệu tích cực.' if score >= 7 else 'Tín hiệu yếu/tiêu cực.' if score <= 3 else 'Tín hiệu trung lập.'}")
    reasons.append(f"**Bối cảnh Thị trường:** {market_trend}. {'Đây là yếu tố hỗ trợ mạnh mẽ.' if market_trend == 'UPTREND' else 'Đây là yếu tố rủi ro lớn.' if market_trend == 'DOWNTREND' else 'Thị trường chưa có xu hướng rõ ràng.'}")
    if ml_data: reasons.append(f"**AI:** Dự báo có xu hướng {'tăng' if ml_data.get('score', 0) >= 60 else 'giảm' if ml_data.get('score', 0) <= 40 else 'trung lập'} (xác suất {ml_data.get('score', 0):.1f}%).")
    if news_factor != 0: reasons.append(f"**Tin tức:** Có yếu tố tin tức {'tích cực' if news_factor > 0 else 'tiêu cực'} cần lưu ý.")
    
    summary_map = { "UPTREND": "bức tranh chung đang rất tích cực.", "DOWNTREND": "rủi ro từ thị trường chung là rất lớn.", "NEUTRAL": "thị trường chung đang đi ngang, cần tín hiệu rõ ràng hơn từ chính coin." }
    summary_text = f"Kết hợp các yếu tố, {summary_map.get(market_trend, '...')} Tín hiệu {lvl} nên được xem xét trong bối cảnh này."

    out = [f"🧠 **Chiến lược cuối cùng:**"]
    out.extend([f"• {line}" for line in reco])
    out.append("📌 **Phân tích chi tiết:**")
    out.extend([f"– {r}" for r in reasons])
    out.append(f"📉 **Tổng kết:** {summary_text}")
    return "\n".join(out)

# ==============================================================================
# MAIN EXECUTION
# ==============================================================================
def main():
    market_context = load_json(MARKET_CONTEXT_PATH, {})
    market_trend = analyze_market_trend(market_context)
    
    cooldown_state = load_cooldown_state()
    now = datetime.now()
    advisor_file = os.path.join(ADVISOR_DIR, f"{now.strftime('%Y-%m-%d')}.json")
    trades = []
    
    for fname in sorted(os.listdir(TRADELOG_DIR)):
        if fname.endswith(".json"):
            trades.extend([t for t in load_json(os.path.join(TRADELOG_DIR, fname), []) if t.get("status") == "open"])

    if not trades:
        print("❌ Không tìm thấy lệnh đang mở nào.")
        return

    advisor_log = load_json(advisor_file, [])
    advisor_map = {t["id"]: t for t in advisor_log}
    
    overview_data = []
    level_counter = Counter()

    for trade in trades:
        try:
            trade_id, symbol, interval = trade["id"], trade["symbol"], trade["interval"]
            real_entry = trade.get("real_entry") or parse_trade_plan(trade["trade_plan"])["entry"]
            if not real_entry: 
                log_to_txt(f"Skip {symbol} due to zero entry price.")
                continue

            df = get_price_data(symbol, interval)
            price_now = round(df.iloc[-2]["close"], 8)
            pnl = round((price_now - real_entry) / real_entry * 100, 2)
            
            indicators = calculate_indicators(df, symbol, interval)
            indicators.update({"df": df, "trade_plan": parse_trade_plan(trade['trade_plan']), "price": price_now})
            
            extra_tf = {}
            for tf in ["1h", "4h", "1d"]:
                if tf == interval: continue
                try:
                    df_tf = get_price_data(symbol, tf)
                    ind_tf = calculate_indicators(df_tf, symbol, tf)
                    ml_tf_score = 0
                    ai_path_tf = os.path.join(AI_DIR, f"{symbol}_{tf}.json")
                    if os.path.exists(ai_path_tf): ml_tf_score = load_json(ai_path_tf, {}).get('score', 0)
                    extra_tf[tf] = {"rsi": ind_tf["rsi_14"], "trend": ind_tf["trend"], "ai_score": ml_tf_score, "ai_bias": "bullish" if ml_tf_score >= 60 else "bearish" if ml_tf_score <= 40 else "neutral"}
                except Exception as e: log_to_txt(f"Error processing multi-timeframe {tf} for {symbol}: {e}")

            signal_level, signal_reason = check_signal(indicators)
            indicators.update({"signal_level": signal_level, "signal_reason": signal_reason, "tag": indicators.get("tag", "avoid")})
            
            score = calc_score(indicators, market_trend)
            news_and_context_text, news_factor = load_news_and_context_block(symbol, market_context)
            
            ml_data = load_json(os.path.join(AI_DIR, f"{symbol}_{interval}.json"), {})
            
            tech = score / 10.0
            ai = ml_data.get('score', 50) / 100.0
            pnl_norm = max(-1.0, min(1.0, pnl / 10.0))
            market_score_val = 1.0 if market_trend == "UPTREND" else -1.0 if market_trend == "DOWNTREND" else 0.0
            
            final_rating = (0.40 * tech + 0.30 * ai + 0.15 * market_score_val + 0.10 * pnl_norm + 0.05 * news_factor)
            final_rating_normalized = min(1.0, max(0.0, (final_rating + 1) / 2.5))
            
            level_key_map = [(0.15, "PANIC_SELL"), (0.30, "SELL"), (0.45, "AVOID"), (0.55, "HOLD"), (0.70, "WEAK_BUY"), (0.85, "BUY"), (1.01, "STRONG_BUY")]
            level_key = next((lvl for thr, lvl in level_key_map if final_rating_normalized < thr), "AVOID")
            
            overview_data.append({**trade, "pnl": pnl, "score": score, "ml_score": ml_data.get('score', 0), "final_rating": final_rating_normalized, "level_key": level_key, "price_now": price_now, "real_entry": real_entry})
            level_counter[level_key] += 1

            prev = advisor_map.get(trade_id, {})
            should_send = ( not prev or abs(prev.get("final_rating", 0) - final_rating_normalized) > 0.08 or abs(prev.get("pnl_percent", 0) - pnl) > 3.0)

            if should_send:
                alert_tag = f"{ICON[level_key]} [{level_key.replace('_', ' ')}]"
                indicators["level_key"] = level_key
                
                title_block = f"{alert_tag} Đánh giá lệnh: {symbol} ({interval})"
                info_block = (f"📌 ID: {trade_id} {symbol} {interval}\n"
                              f"📆 In time: {trade.get('in_time')} | Đã giữ: {calc_held_hours(trade.get('in_time'))} h | RealEntry: {real_entry}\n"
                              f"💰 PnL: {round(trade.get('amount', 1000) * pnl / 100, 1):.1f} USD ({pnl:.2f}%) | 📦 {round(trade.get('amount', 1000)/real_entry, 2)} | 💵 {round(trade.get('amount', 1000) + trade.get('amount', 1000) * pnl / 100, 1)}/{trade.get('amount', 1000):.1f}")
                
                ind_text_block = generate_indicator_text_block(indicators)
                summary_block = generate_summary_block(symbol, interval, pnl, score, ml_data, news_factor, final_rating_normalized)
                mta_block = generate_mta_block(extra_tf)
                final_strategy_block = generate_final_strategy_block(pnl, score, ml_data, news_factor, indicators, market_context)
                
                final_msg = "\n\n".join(filter(None, [title_block, info_block, ind_text_block, summary_block, news_and_context_text, mta_block, final_strategy_block]))
                
                symbol_key = f"{symbol}_{interval}"
                last_sent_str = cooldown_state.get(symbol_key, {}).get(level_key)
                if not last_sent_str or is_cooldown_passed(last_sent_str, level_key, now):
                    log_to_txt(f"SEND alert for {symbol} ({interval}) - Level: {level_key}")
                    send_discord_alert(final_msg)
                    cooldown_state.setdefault(symbol_key, {})[level_key] = now.strftime("%Y-%m-%d %H:%M:%S")
                else:
                    log_to_txt(f"COOLDOWN skip for {symbol} ({interval}) - Level: {level_key}")

            advisor_map[trade_id] = {"id": trade_id, "pnl_percent": pnl, "final_rating": final_rating_normalized}
        
        except Exception as e:
            log_to_txt(f"[CRITICAL ERROR] Failed to process trade {trade.get('id', 'N/A')}: {e}")
            import traceback
            log_to_txt(traceback.format_exc())
            
    if is_overview_time() and overview_data:
        total_start = sum(t.get("amount", 1000) for t in overview_data)
        total_pnl_usd = sum(t.get("amount", 1000) * t["pnl"] / 100 for t in overview_data)
        total_now = total_start + total_pnl_usd
        
        lv_counts = ", ".join(f"{ICON[k]}{v}" for k, v in sorted(level_counter.items(), key=lambda item: list(ICON.keys()).index(item[0])))
        pnl_by_level = {lvl: sum(t.get("amount", 1000) * t["pnl"] / 100 for t in overview_data if t["level_key"] == lvl) for lvl in level_counter}
        pnl_lines = ", ".join(f"{ICON[k]}{v:.1f}$" for k, v in sorted(pnl_by_level.items(), key=lambda item: list(ICON.keys()).index(item[0])))
        
        header  = f"📊 **Tổng quan danh mục {now:%d-%m %H:%M}**\n"
        header += f"Lệnh: {len(overview_data)} | PnL Tổng: {total_pnl_usd:+.1f}$ ({(total_pnl_usd/total_start*100 if total_start else 0):+.2f}%)\n"
        header += f"Phân bổ cấp: {lv_counts}\n"
        header += f"PnL theo cấp: {pnl_lines}"
        
        overview_lines = []
        for t in sorted(overview_data, key=lambda x: x.get('final_rating', 0)):
            line = (f"📌 **{t['symbol']} ({t['interval']})** | "
                    f"PnL: {t['pnl']:+.2f}% | "
                    f"Entry: {t.get('real_entry', 0)} | "
                    f"Hiện tại: {t['price_now']}\n"
                    f"🧠 Tech: {t['score']}/10 | AI: {t['ml_score']:.0f}% | **Final: {t['final_rating']:.1%}** {ICON.get(t['level_key'], ' ')}")
            overview_lines.append(line)
            
        send_discord_alert(header + "\n" + "-"*50 + "\n" + "\n\n".join(overview_lines))

    write_json(advisor_file, list(advisor_map.values()))
    save_cooldown_state(cooldown_state)
    print(f"✅ Finished processing {len(trades)} open trades.")

if __name__ == "__main__":
    main()
