# -*- coding: utf-8 -*-
# ricenews_v9.0.py
# Version: 9.0 (Flexible Combo Scoring Logic)

import os
import json
import requests
import feedparser
import hashlib
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
import time
import re
from typing import List, Dict, Tuple, Optional
from collections import defaultdict, Counter
import sys

# ==============================================================================
# DEPENDENCY & MODULE SETUP
# ==============================================================================
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
try:
    from market_context import get_market_context_data, get_market_context
except ImportError:
    print("[WARN] Không thể import 'market_context'. Sử dụng hàm giả.")
    def get_market_context_data(): return {}
    def get_market_context(): return {}

try:
    import google.generativeai as genai
except ImportError:
    print("[ERROR] Thư viện 'google-generativeai' chưa được cài đặt.")
    genai = None

# ==============================================================================
# CONFIG & CONSTANTS
# ==============================================================================
dotenv_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
load_dotenv(dotenv_path=dotenv_path, override=True)

# --- General Config ---
VN_TZ = timezone(timedelta(hours=7))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, "lognew")
COOLDOWN_TRACKER = os.path.join(BASE_DIR, "cooldown_tracker.json")
DISCORD_WEBHOOK = os.getenv("DISCORD_NEWS_WEBHOOK")
os.makedirs(LOG_DIR, exist_ok=True)

# --- AI & API Config ---
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
if GOOGLE_API_KEY and genai:
    genai.configure(api_key=GOOGLE_API_KEY)

GEMINI_MODEL_NAME = "gemini-2.0-flash-lite"
DAILY_API_LIMIT = 100 # Đã tăng lên vì chi phí rẻ
AI_ANALYSIS_THRESHOLD = 7

# --- News Analysis Config ---
WATCHED_COINS = set([s.replace("USDT", "").lower() for s in os.getenv("SYMBOLS", "").split(",")])
WATCHED_COINS.update(["btc", "eth", "xrp", "sol", "bnb"])
RSS_SOURCES = {"CoinDesk": "https://www.coindesk.com/arc/outboundfeeds/rss", "Cointelegraph": "https://cointelegraph.com/rss"}

# ==============================================================================
# NEW SCORING SYSTEM (V9.0)
# ==============================================================================

# COMBO_SCORES: Tìm TẤT CẢ các từ trong bộ, bất kể thứ tự hay từ nào ở giữa.
# Đây là trái tim của logic mới, giúp hệ thống trở nên linh hoạt.
COMBO_SCORES = {
    # --- POSITIVE COMBOS ---
    frozenset({"etf", "approved"}): 10,
    frozenset({"etf", "approval"}): 10,
    frozenset({"listing", "binance"}): 9,
    frozenset({"listing", "coinbase"}): 9,
    frozenset({"mainnet", "launch"}): 8,
    frozenset({"buyback", "program"}): 7,
    frozenset({"strategic", "partnership"}): 7,
    frozenset({"ecosystem", "fund"}): 7,
    frozenset({"token", "burn"}): 5,
    frozenset({"funding", "round"}): 5,

    # --- NEGATIVE COMBOS ---
    frozenset({"sec", "charges"}): -9,
    frozenset({"doj", "investigation"}): -9,
    frozenset({"halts", "withdrawals"}): -10,
    frozenset({"security", "breach"}): -9,
    frozenset({"security", "vulnerability"}): -8,
    frozenset({"sec", "lawsuit"}): -8,
    frozenset({"regulatory", "crackdown"}): -7,
    frozenset({"etf", "denied"}): -9,
    frozenset({"etf", "delayed"}): -5,
    frozenset({"approved", "investigation"}): -7, # Xử lý ngữ cảnh "approved" nhưng là xấu

    # --- "LẬT KÈO" COMBOS (Quan trọng nhất) ---
    # Điểm cao để lật ngược điểm của combo xấu
    frozenset({"sec", "lawsuit", "settled"}): 10,
    frozenset({"lawsuit", "settled"}): 9,
    frozenset({"investigation", "resolved"}): 8,
    frozenset({"funds", "safe"}): 6,
}

# KEYWORD_SCORES: Các từ khóa đơn lẻ hoặc cụm từ rất đặc thù.
# Dùng cho các trường hợp không cần logic combo phức tạp.
KEYWORD_SCORES = {
    "halving": 8, "acquires": 10, "merges": 10, "airdrop": 3, "testnet": 3, "ama": 1,
    "hack": -10, "exploited": -10, "insolvent": -10, "delisting": -8, "delisted": -8,
    "downtime": -5, "unlock": -5, "delay": -4,
    "fomc": 6, "cpi": 6, "interest rate": 6,
    "major": 1, "massive": 2
}

SCORE_THRESHOLDS = {"CRITICAL": 8, "WARNING": 5, "ALERT": 4, "WATCHLIST": 2}
LEVEL_COOLDOWN_MINUTES = {"CRITICAL": 90, "WARNING": 180, "ALERT": 240, "WATCHLIST": 300, "INFO": 350}

# ==============================================================================
# UTILITY FUNCTIONS
# ==============================================================================
def load_json(file_path, default_value):
    if not os.path.exists(file_path): return default_value
    try:
        with open(file_path, 'r', encoding='utf-8') as f: return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError): return default_value

def save_json(file_path, data):
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# ==============================================================================
# CORE ANALYSIS & DATA PROCESSING
# ==============================================================================
def analyze_market_context_trend(mc: dict) -> str:
    if not mc: return "NEUTRAL"
    up_score, down_score = 0, 0
    if mc.get('btc_dominance', 0) > 55: up_score += 1
    elif mc.get('btc_dominance', 100) < 48: down_score += 1
    if mc.get('fear_greed', 50) > 70: up_score += 1
    elif mc.get('fear_greed', 50) < 30: down_score += 1
    if up_score > down_score: return "UPTREND"
    if down_score > up_score: return "DOWNTREND"
    return "NEUTRAL"

def classify_and_score_news(title: str) -> Tuple[str, int]:
    """
    (V9.0) Phân loại và chấm điểm tin tức bằng cách tìm các từ khóa đơn lẻ
    và các combo từ khóa linh hoạt.
    """
    title_l = title.lower()
    # Chuyển tiêu đề thành một tập hợp các từ để kiểm tra hiệu quả
    title_words = set(re.findall(r'\b\w+\b', title_l))
    score = 0
    matched_combos = []

    # 1. Ưu tiên kiểm tra các combo trước
    for combo_keys, combo_score in COMBO_SCORES.items():
        if combo_keys.issubset(title_words):
            score += combo_score
            matched_combos.append(combo_keys)

    # 2. Kiểm tra các từ khóa đơn lẻ (chỉ các chuỗi cứng)
    for keyword, keyword_score in KEYWORD_SCORES.items():
        if keyword in title_l:
            # Kiểm tra để tránh tính điểm kép nếu từ khóa đã là một phần của combo lớn hơn
            is_part_of_larger_combo = False
            for combo in matched_combos:
                if keyword in combo:
                    is_part_of_larger_combo = True
                    break
            if not is_part_of_larger_combo:
                 score += keyword_score

    # 3. Phân loại mức độ dựa trên tổng điểm cuối cùng
    for level, threshold in SCORE_THRESHOLDS.items():
        if abs(score) >= threshold:
            return level, score
    
    return "INFO", score

def detect_category_tag(title: str) -> str:
    title_l = title.lower()
    for coin in WATCHED_COINS:
        if re.search(rf"\b{coin}\b", title_l): return coin.upper()
    
    # SỬA Ở ĐÂY: Thay {3,6} thành {2,10} để bắt được các ticker ngắn và dài hơn
    # Nó sẽ tìm các chuỗi ký tự IN HOA có từ 2 đến 10 ký tự, nằm trong ngoặc đơn hoặc đứng một mình.
    match = re.search(r'\(([A-Z]{2,10})\)|\b([A-Z]{2,10})\b', title)
    if match and (tag := (match.group(1) or match.group(2))) and tag.lower() not in ['usdt', 'ceo', 'cto', 'tvl', 'will', 'add']:
        return tag.upper()

    if any(kw in title_l for kw in ["fomc", "interest", "cpi", "inflation", "sec", "fed", "market", "war"]): return "MACRO"
    return "GENERAL"


def generate_specific_suggestion(score: int, market_trend: str) -> str:
    if score == 0: return "Tin tức tham khảo, tác động không đáng kể."
    if score > 0:
        return "Tác động TÍCH CỰC, có thể tạo sóng hồi ngắn. 👉 Cân nhắc lướt sóng." if market_trend != "UPTREND" else "Tác động TÍCH CỰC, củng cố xu hướng tăng. 👉 Ưu tiên các lệnh MUA."
    return "Tác động TIÊU CỰC, có thể gây điều chỉnh. 👉 Thận trọng, cân nhắc chốt lời." if market_trend != "DOWNTREND" else "Tác động TIÊU CỰC, củng cố xu hướng giảm. 👉 Ưu tiên các lệnh BÁN."

def fetch_news_sources() -> List[Dict]:
    all_news = []
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        url = "https://www.binance.com/bapi/composite/v1/public/cms/article/catalog/list/query?catalogId=48&pageSize=20&pageNo=1"
        res = requests.get(url, headers=headers, timeout=10)
        res.raise_for_status()
        articles = res.json().get("data", {}).get("articles", [])
        all_news.extend([{"id": f"binance_{item['code']}", "title": item["title"], "url": f"https://www.binance.com/en/support/announcement/{item['code']}", "source_name": "Binance"} for item in articles])
    except Exception as e: print(f"[ERROR] Binance fetch failed: {e}")
    for tag, url in RSS_SOURCES.items():
        try:
            feed = feedparser.parse(url)
            all_news.extend([{"id": f"{tag}_{hashlib.md5((e.link + e.title).encode()).hexdigest()[:12]}", "title": e.title, "url": e.link, "source_name": tag} for e in feed.entries[:20]])
        except Exception as e: print(f"[ERROR] RSS {tag} fetch failed: {e}")
    return all_news

def save_news_for_summary(news_item: Dict):
    fname = os.path.join(LOG_DIR, f"{datetime.now(VN_TZ).strftime('%Y-%m-%d')}_news_signal.json")
    logs = load_json(fname, [])
    if not any(item['id'] == news_item['id'] for item in logs):
        logs.insert(0, news_item)
        save_json(fname, logs)

# ==============================================================================
# DISCORD & SUMMARY FUNCTIONS
# ==============================================================================
def send_discord_alert(message: str):
    if not DISCORD_WEBHOOK:
        print("[WARN] DISCORD_WEBHOOK is not set.")
        return
    max_len = 2000
    if len(message) <= max_len:
        chunks = [message]
    else:
        chunks, current_chunk = [], ""
        for line in message.split('\n'):
            if len(current_chunk) + len(line) + 1 > max_len:
                chunks.append(current_chunk)
                current_chunk = line
            else:
                current_chunk += ("\n" if current_chunk else "") + line
        chunks.append(current_chunk)
    
    for i, chunk in enumerate(chunks):
        if not chunk.strip(): continue
        try:
            content = f"(Phần {i+1}/{len(chunks)})\n{chunk}" if len(chunks) > 1 and i > 0 else chunk
            requests.post(DISCORD_WEBHOOK, json={"content": content}, timeout=10).raise_for_status()
            if len(chunks) > 1: time.sleep(1)
        except requests.exceptions.RequestException as e:
            print(f"[ERROR] Failed to send chunk {i+1}: {e.response.text if e.response else e}")

def get_ai_analysis(prompt: str, timeout: int = 20) -> Optional[str]:
    if not GOOGLE_API_KEY or not genai: return None
    try:
        model = genai.GenerativeModel(GEMINI_MODEL_NAME)
        response = model.generate_content(prompt, request_options={'timeout': timeout})
        return response.text.strip()
    except Exception as e:
        print(f"[WARN] AI analysis call failed: {e}")
        return None

def should_send_summary(last_summary_ts: float) -> bool:
    now_dt = datetime.now(VN_TZ)
    target_times = [(8, 2), (20, 2)]
    for hour, minute in target_times:
        target_dt_today = now_dt.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if now_dt >= target_dt_today and last_summary_ts < target_dt_today.timestamp():
            return True
    return False

def generate_and_send_scheduled_summary(cooldown_data: Dict, context: Dict, market_trend: str):
    print("🚀 Generating scheduled summary report...")
    last_summary_ts = cooldown_data.get("last_summary", time.time() - 12 * 60 * 60)
    now_ts = time.time()

    all_past_news = []
    for i in range(2):
        date_str = (datetime.now(VN_TZ) - timedelta(days=i)).strftime('%Y-%m-%d')
        fname = os.path.join(LOG_DIR, f"{date_str}_news_signal.json")
        all_past_news.extend(load_json(fname, []))
    
    news_in_period = [news for news in all_past_news if last_summary_ts < datetime.fromisoformat(news['published_at']).timestamp() <= now_ts]

    context_block = f"```Bối cảnh thị trường | Fear & Greed: {context.get('fear_greed', 'N/A')} | BTC.D: {context.get('btc_dominance', 'N/A')}% | Trend: {market_trend}```"
    if not news_in_period:
        message = (f"**📈 BÁO CÁO TỔNG QUAN - {datetime.now(VN_TZ).strftime('%H:%M %d/%m')} 📈**\n\n"
                   f"{context_block}\n\nKhông có tin tức nào đáng chú ý được ghi nhận trong 12 giờ qua. Thị trường có thể đang trong giai đoạn đi ngang hoặc chờ đợi chất xúc tác mới.")
        send_discord_alert(message)
        print("✅ Sent scheduled summary: No significant news.")
        return

    news_in_period.sort(key=lambda x: abs(x['news_score']), reverse=True)
    top_5_news = news_in_period[:5]
    top_headlines = [news['title'] for news in top_5_news]
    category_counts = Counter(news['category_tag'] for news in news_in_period)
    top_3_tags = [tag for tag, count in category_counts.most_common(3)]
    trends_str = f"Chủ đề chính trong 12h qua xoay quanh: **{', '.join(top_3_tags)}**."

    ai_summary = None
    if cooldown_data['api_call_counter']['count'] < DAILY_API_LIMIT:
        prompt = f"""As a senior crypto market analyst, provide a strategic summary in Vietnamese for a trader. Based on the following market context and key news headlines from the last 12 hours, what is the overall sentiment, what are the key drivers, and what should a trader watch out for in the next few hours? Be concise, strategic, and professional.
        Market Context:
        - Fear & Greed Index: {context.get('fear_greed', 'N/A')}
        - BTC Dominance: {context.get('btc_dominance', 'N/A')}%
        - General Trend: {market_trend}
        Key News Headlines:
        {"\n".join([f"- {title}" for title in top_headlines])}
        Strategic Summary (Vietnamese):"""
        ai_summary = get_ai_analysis(prompt, timeout=45)
        if ai_summary:
            cooldown_data['api_call_counter']['count'] += 1
    else:
        print("[WARN] Daily API limit reached. Skipping AI for scheduled summary.")

    ai_block = f"**🧠 Nhận định từ AI:**\n*{ai_summary}*" if ai_summary else "*(Ghi chú: Đã đạt giới hạn phân tích AI trong ngày nên báo cáo không có nhận định sâu.)*"
    
    news_blocks = ["📰 **Tin tức nổi bật nhất (12h qua):**"]
    for alert in top_5_news:
        sentiment_emoji = '🚀' if alert['news_score'] > 0 else '🚨' if alert['news_score'] < 0 else 'ℹ️'
        news_blocks.append(f"- {sentiment_emoji} {alert['title']} *(Điểm: {alert['news_score']})*")

    final_message = (f"**📈 BÁO CÁO TỔNG QUAN - {datetime.now(VN_TZ).strftime('%H:%M %d/%m')} 📈**\n\n"
                     f"{context_block}\n\n{ai_block}\n\n{'\n'.join(news_blocks)}\n\n"
                     f"📊 **Xu hướng chính:** {trends_str}")

    send_discord_alert(final_message)
    print("✅ Sent scheduled summary report successfully.")

# ==============================================================================
# MAIN EXECUTION
# ==============================================================================
def main():
    print(f"--- Running News Cycle v9.0 at {datetime.now(VN_TZ).strftime('%Y-%m-%d %H:%M:%S')} ---")
    
    cooldown_data = load_json(COOLDOWN_TRACKER, {"last_sent_id": []})
    now_ts = time.time()
    today_str = datetime.now(VN_TZ).strftime('%Y-%m-%d')
    
    api_counter = cooldown_data.get('api_call_counter', {})
    if api_counter.get('date') != today_str:
        api_counter = {'date': today_str, 'count': 0}
    cooldown_data['api_call_counter'] = api_counter

    try: context = get_market_context()
    except Exception: context = get_market_context_data()
    market_trend = analyze_market_context_trend(context)

    if should_send_summary(cooldown_data.get("last_summary", 0)):
        generate_and_send_scheduled_summary(cooldown_data, context, market_trend)
        cooldown_data["last_summary"] = now_ts
        save_json(COOLDOWN_TRACKER, cooldown_data)
        print("✅ Updated last summary timestamp and cooldown data.")
        return

    all_news = fetch_news_sources()
    new_alerts_this_cycle = []
    for news in all_news:
        if news['id'] in cooldown_data.get("last_sent_id", []): continue
        level, score = classify_and_score_news(news['title'])
        if level != "INFO" or score != 0:
            alert_item = {
                "id": news['id'], "title": news['title'], "url": news['url'], "source_name": news['source_name'],
                "published_at": datetime.now(VN_TZ).isoformat(), "level": level, "news_score": score,
                "category_tag": detect_category_tag(news['title']),
                "suggestion": generate_specific_suggestion(score, market_trend),
            }
            new_alerts_this_cycle.append(alert_item)

    if not new_alerts_this_cycle:
        print("✅ No new significant instant alerts to send.")
    else:
        new_alerts_this_cycle.sort(key=lambda x: abs(x['news_score']), reverse=True)
        highest_level_alert = new_alerts_this_cycle[0]
        highest_level = highest_level_alert['level']
        
        cooldown_minutes = LEVEL_COOLDOWN_MINUTES.get(highest_level, 120)
        last_sent_time_for_level = cooldown_data.get("last_sent_level", {}).get(highest_level, 0)

        if now_ts - last_sent_time_for_level < cooldown_minutes * 60:
            print(f"⏳ Instant alert skipped. Highest level '{highest_level}' is on cooldown.")
        else:
            print(f"🔥 Sending digest for {len(new_alerts_this_cycle)} new alerts. Highest level: {highest_level}.")

            if abs(highest_level_alert['news_score']) >= AI_ANALYSIS_THRESHOLD:
                if cooldown_data['api_call_counter']['count'] < DAILY_API_LIMIT:
                    prompt = f"""As a crypto trading analyst, what is the potential market impact of this headline? Is it bullish, bearish, or neutral, and why? Be very concise, one short Vietnamese sentence only.
                    Headline: "{highest_level_alert['title']}"
                    Analysis:"""
                    ai_suggestion = get_ai_analysis(prompt)
                    if ai_suggestion:
                        highest_level_alert['ai_suggestion'] = ai_suggestion
                        cooldown_data['api_call_counter']['count'] += 1
                else:
                    print(f"[WARN] Daily API limit reached. Skipping AI analysis for instant alert.")
            
            for alert in new_alerts_this_cycle:
                save_news_for_summary({k: v for k, v in alert.items() if k != 'ai_suggestion'})

            news_by_level = defaultdict(list)
            for alert in new_alerts_this_cycle: news_by_level[alert['level']].append(alert)

            news_blocks = []
            for level in ["CRITICAL", "WARNING", "ALERT", "WATCHLIST"]:
                if news_by_level[level]:
                    level_emoji = {"CRITICAL": "🔴", "WARNING": "⚠️", "ALERT": "📣", "WATCHLIST": "👀"}.get(level)
                    news_blocks.append(f"{level_emoji} **{level}**")
                    for alert in sorted(news_by_level[level], key=lambda x: abs(x['news_score']), reverse=True):
                        score = alert['news_score']
                        sentiment_emoji = '🚀' if score > 0 else '🚨'
                        part = f"- **[{alert['source_name']}] {alert['title']}** {sentiment_emoji} (Điểm: {score})\n  *↳ Nhận định:* {alert['suggestion']}"
                        if alert.get('ai_suggestion'):
                             part += f"\n  🧠 **AI Phân tích sâu:** *{alert['ai_suggestion']}*"
                        part += f" [Link](<{alert['url']}>)"
                        news_blocks.append(part)
            
            final_summary_text = f"⚠️ **Đánh giá chung:** Xuất hiện các tin tức CẢNH BÁO có thể ảnh hưởng đến thị trường. Bối cảnh thị trường chung đang {market_trend}, hãy giao dịch cẩn trọng."
            full_digest_message = (f"**🔥 BẢN TIN THỊ TRƯỜNG - {datetime.now(VN_TZ).strftime('%H:%M')} 🔥**\n\n"
                                   f"```Bối cảnh thị trường | Fear & Greed: {context.get('fear_greed', 'N/A')} | BTC.D: {context.get('btc_dominance', 'N/A')}% | Trend: {market_trend}```\n\n"
                                   + "\n".join(news_blocks) + f"\n\n{final_summary_text}")
            send_discord_alert(full_digest_message)

            cooldown_data["last_sent_id"] = (cooldown_data.get("last_sent_id", []) + [a['id'] for a in new_alerts_this_cycle])[-100:]
            cooldown_data.setdefault("last_sent_level", {})[highest_level] = now_ts
            save_json(COOLDOWN_TRACKER, cooldown_data)
            print("✅ Cooldown tracker file saved for instant alert.")

    print("--- Cycle Finished ---")

if __name__ == "__main__":
    main()
