# -*- coding: utf-8 -*-
# rice_news.py
# Version: 5.3 (Stability & Readability First)
# Description: This version provides the definitive fix for the message splitting
#              loop and formatting issues. The send_discord_alert function is now
#              robust and non-recursive. The output format is clean and readable.
#              All other logic from the last stable build is maintained.

import os
import json
import requests
import feedparser
import hashlib
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
import time
import re
from typing import List, Dict, Tuple
from collections import defaultdict, Counter

# Import market_context functions
from market_context import get_market_context_data, get_market_context

# ==============================================================================
# CONFIG & SETUP
# ==============================================================================
dotenv_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')
load_dotenv(dotenv_path=dotenv_path)

VN_TZ = timezone(timedelta(hours=7))
BASE_DIR = os.getenv("RICENEWS_BASE_DIR", "/root/ricealert/ricenews")
LOG_DIR = os.path.join(BASE_DIR, "lognew")
COOLDOWN_TRACKER = os.path.join(BASE_DIR, "cooldown_tracker.json")
DISCORD_WEBHOOK = os.getenv("DISCORD_NEWS_WEBHOOK")
os.makedirs(LOG_DIR, exist_ok=True)

WATCHED_COINS = set([s.replace("USDT", "").lower() for s in os.getenv("SYMBOLS", "").split(",")])
WATCHED_COINS.update(["btc", "eth"])

LEVEL_COOLDOWN_MINUTES = {
    "CRITICAL": 30, "WARNING": 60, "ALERT": 120,
    "WATCHLIST": 240, "INFO": 480
}
SUMMARY_COOLDOWN_SECONDS = 6 * 60 * 60

KEYWORDS = {
    "CRITICAL": ["will list", "etf approval", "halving", "fomc", "interest rate", "cpi", "war", "approved", "regulatory approval"],
    "WARNING": ["delist", "unlock", "hack", "exploit", "sec", "lawsuit", "regulation", "maintenance", "downtime", "outage", "bị điều tra", "kiện"],
    "ALERT": ["upgrade", "partnership", "margin", "futures", "mainnet", "testnet", "available on", "will add"],
    "WATCHLIST": ["airdrop", "voting", "ama", "token burn", "governance"]
}
POSITIVE_KEYWORDS = ["etf", "niêm yết", "listing", "adoption", "partnership", "approved", "upgrade", "launch", "mainnet", "burn", "available on", "will add"]
NEGATIVE_KEYWORDS = ["kiện", "hacker", "scam", "bị điều tra", "tether", "sec sues", "sec charges", "hack", "exploit", "lawsuit", "delist", "downtime", "outage"]
MACRO_KEYWORDS = ["fomc", "interest rate", "cpi", "inflation", "sec", "lawsuit", "regulation", "fed", "market", "imf", "war"]

RSS_SOURCES = {"CoinDesk": "https://www.coindesk.com/arc/outboundfeeds/rss", "Cointelegraph": "https://cointelegraph.com/rss"}

# ==============================================================================
# HELPER & UTILITY FUNCTIONS
# ==============================================================================
def load_json(file_path, default_value):
    if not os.path.exists(file_path): return default_value
    try:
        with open(file_path, 'r', encoding='utf-8') as f: return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError): return default_value

def should_send_summary(last_summary_ts: float) -> bool:
    now_dt = datetime.now(VN_TZ)
    target_times = [(8, 2), (20, 2)]
    for hour, minute in target_times:
        target_dt_today = now_dt.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if now_dt >= target_dt_today and last_summary_ts < target_dt_today.timestamp():
            return True
    return False

# ==============================================================================
# CORE ANALYSIS
# ==============================================================================
def analyze_market_context_trend(mc: dict) -> str:
    if not mc: return "NEUTRAL"
    up_score, down_score = 0, 0
    btc_dom, fear_greed = mc.get('btc_dominance'), mc.get('fear_greed')
    if btc_dom is not None:
        if btc_dom > 55: up_score += 1
        elif btc_dom < 48: down_score += 1
    if fear_greed is not None:
        if fear_greed > 70: up_score += 1
        elif fear_greed < 30: down_score += 1
    if up_score > down_score: return "UPTREND"
    if down_score > up_score: return "DOWNTREND"
    return "NEUTRAL"

def classify_news_level(title: str) -> str:
    title_l = title.lower()
    for level, keys in KEYWORDS.items():
        if any(re.search(rf"\b{re.escape(key)}\b", title_l) for key in keys):
            return level
    return "INFO"

def detect_category_tag(title: str) -> str:
    title_l = title.lower()
    for coin in WATCHED_COINS:
        if re.search(rf"\b{coin}\b", title_l):
            return coin.upper()
    match = re.search(r'\(([A-Z]{3,6})\)|\b([A-Z]{3,6}USDT)\b', title)
    if match:
        return (match.group(1) or match.group(2)).replace("USDT", "")
    if any(kw in title_l for kw in MACRO_KEYWORDS):
        return "MACRO"
    return "GENERAL"

def get_news_sentiment(title: str) -> str:
    lowered = title.lower()
    if any(keyword in lowered for keyword in POSITIVE_KEYWORDS): return "positive"
    if any(keyword in lowered for keyword in NEGATIVE_KEYWORDS): return "negative"
    return "neutral"

def generate_specific_suggestion(news: Dict, market_trend: str) -> Tuple[str, str]:
    title_l, level = news['title'].lower(), news['level']
    sentiment = get_news_sentiment(title_l)
    if level == "INFO":
        return "Tin tức tham khảo, tác động không đáng kể đến thị trường.", "⚪️ NEUTRAL"
    if sentiment == "positive":
        if market_trend == "UPTREND":
            return "Tác động TÍCH CỰC, củng cố xu hướng tăng. 👉 Ưu tiên các lệnh MUA.", "🚀 BULLISH"
        else:
            return "Tác động TÍCH CỰC, có thể tạo sóng hồi ngắn. 👉 Cân nhắc lướt sóng.", "📈 POSITIVE"
    elif sentiment == "negative":
        if market_trend == "DOWNTREND":
            return "Tác động TIÊU CỰC, củng cố xu hướng giảm. 👉 Ưu tiên các lệnh BÁN.", "📉 BEARISH"
        else:
            return "Tác động TIÊU CỰC, có thể gây điều chỉnh. 👉 Thận trọng, cân nhắc chốt lời.", "🚨 NEGATIVE"
    return "Tác động TRUNG LẬP, ít ảnh hưởng tới giá. 👉 Quan sát thêm.", "⚪️ NEUTRAL"

def generate_final_summary(alerts: List[Dict], market_trend: str) -> str:
    if not alerts:
        return "Không có tin tức mới đáng chú ý."
    level_counts = Counter(alert['level'] for alert in alerts)
    if level_counts['CRITICAL'] > 0:
        base_summary = "Thị trường có tin tức CỰC KỲ QUAN TRỌNG."
    elif level_counts['WARNING'] > 0:
        base_summary = "Xuất hiện các tin tức CẢNH BÁO có thể ảnh hưởng tiêu cực."
    elif level_counts['ALERT'] > 0:
        base_summary = "Có nhiều tin tức CẬP NHẬT về các dự án."
    else:
        base_summary = "Thị trường có một vài tin tức mới."
    if market_trend == "UPTREND":
        context_summary = "Bối cảnh thị trường chung đang TÍCH CỰC, các tin tốt sẽ được khuếch đại."
    elif market_trend == "DOWNTREND":
        context_summary = "Bối cảnh thị trường chung đang TIÊU CỰC, cần cẩn trọng với các tin xấu."
    else:
        context_summary = "Thị trường chung đang đi ngang, giá sẽ phản ứng chủ yếu theo từng tin riêng lẻ."
    return f"⚠️ **Đánh giá chung:** {base_summary} {context_summary}"

# ==============================================================================
# DATA FETCHING & PERSISTENCE
# ==============================================================================
def fetch_news_sources() -> List[Dict]:
    all_news = []
    try:
        url = "https://www.binance.com/bapi/composite/v1/public/cms/article/catalog/list/query?catalogId=48&pageSize=10&pageNo=1"
        res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        res.raise_for_status()
        articles = res.json().get("data", {}).get("articles", [])
        all_news.extend([{"id": f"binance_{item.get('code')}", "title": item.get("title"), "url": f"https://www.binance.com/en/support/announcement/{item.get('code')}", "source_name": "Binance"} for item in articles])
    except Exception as e: print(f"[ERROR] Binance fetch failed: {e}")
    for tag, url in RSS_SOURCES.items():
        try:
            feed = feedparser.parse(url)
            all_news.extend([{"id": f"{tag}_{hashlib.md5((entry.link + entry.title).encode()).hexdigest()[:12]}", "title": entry.title, "url": entry.link, "source_name": tag} for entry in feed.entries[:10]])
        except Exception as e: print(f"[ERROR] RSS {tag} fetch failed: {e}")
    return all_news

def save_news_for_precious(news_item: Dict):
    fname = os.path.join(LOG_DIR, f"{datetime.now(VN_TZ).strftime('%Y-%m-%d')}_news_signal.json")
    logs = load_json(fname, [])
    if not any(item['id'] == news_item['id'] for item in logs):
        logs.insert(0, news_item)
        with open(fname, 'w', encoding='utf-8') as f:
            json.dump(logs, f, indent=2, ensure_ascii=False)

# ==============================================================================
# DISCORD & SUMMARY FUNCTIONS
# ==============================================================================
def send_discord_alert(message: str):
    """SỬA LỖI: Logic chia tin nhắn đúng đắn, không đệ quy."""
    if not DISCORD_WEBHOOK:
        print("[WARN] DISCORD_WEBHOOK is not set.")
        return
    
    max_len = 2000
    chunks = []
    if len(message) > max_len:
        print(f"Message is too long ({len(message)} chars). Splitting into chunks...")
        # Tách tin nhắn thành các dòng
        lines = message.split('\n')
        current_chunk = ""
        for line in lines:
            # Nếu thêm dòng mới vào sẽ vượt quá giới hạn
            if len(current_chunk) + len(line) + 1 > max_len:
                chunks.append(current_chunk)
                current_chunk = line
            else:
                if current_chunk:
                    current_chunk += "\n" + line
                else:
                    current_chunk = line
        chunks.append(current_chunk) # Thêm chunk cuối cùng
    else:
        chunks.append(message)

    # Gửi từng chunk
    for i, chunk in enumerate(chunks):
        # Đảm bảo chunk không rỗng
        if not chunk.strip():
            continue
            
        try:
            # Chỉ thêm (Part x/y) nếu có nhiều hơn 1 chunk
            content_to_send = f"(Phần {i+1}/{len(chunks)})\n{chunk}" if len(chunks) > 1 and i > 0 else chunk
            response = requests.post(DISCORD_WEBHOOK, json={"content": content_to_send}, timeout=10)
            response.raise_for_status()
            print(f"✅ Sent chunk {i+1}/{len(chunks)}.")
            if len(chunks) > 1:
                time.sleep(1) # Chờ 1 giây giữa các chunk để tránh rate limit
        except requests.exceptions.RequestException as e:
            print(f"[ERROR] Failed to send chunk {i+1}: {e.response.text if e.response else e}")


def send_daily_summary():
    fname = os.path.join(LOG_DIR, f"{datetime.now(VN_TZ).strftime('%Y-%m-%d')}_news_signal.json")
    logs = load_json(fname, [])
    if not logs:
        msg = f"**📊 BẢN TIN TỔNG QUAN - {datetime.now(VN_TZ).strftime('%H:%M %d/%m')}**\n\n_Không có tin tức tín hiệu nào được ghi nhận trong ngày hôm nay._"
        send_discord_alert(msg)
        return

    context = get_market_context_data()
    market_trend = analyze_market_context_trend(context)

    news_by_level = defaultdict(list)
    for item in logs:
        news_by_level[item['level']].append(item)

    msg = f"**📊 BẢN TIN TỔNG QUAN - {datetime.now(VN_TZ).strftime('%H:%M %d/%m')}**\n\n"
    msg += f"```Bối cảnh thị trường | Fear & Greed: {context.get('fear_greed', 'N/A')} | BTC.D: {context.get('btc_dominance', 'N/A')}% | Trend: {market_trend}```"

    level_order = ["CRITICAL", "WARNING", "ALERT", "WATCHLIST", "INFO"]
    for level in level_order:
        if level in news_by_level:
            emoji = {"CRITICAL": "🔴", "WARNING": "⚠️", "ALERT": "📣", "WATCHLIST": "👀", "INFO": "ℹ️"}.get(level, "ℹ️")
            msg += f"\n{emoji} **{level}** ({len(news_by_level[level])} tin):\n"
            for item in news_by_level[level][:5]:
                msg += f"- [{item['source_name']}] {item['title']} [Link](<{item['url']}>)\n"
    
    send_discord_alert(msg)
    print("✅ Daily Summary sent.")

# ==============================================================================
# MAIN EXECUTION
# ==============================================================================
def main():
    print(f"--- Running News Cycle at {datetime.now(VN_TZ).strftime('%Y-%m-%d %H:%M:%S')} ---")

    cooldown_data = load_json(COOLDOWN_TRACKER, {"last_sent_id": [], "last_sent_level": {}, "last_summary": 0})
    now_ts = time.time()

    if should_send_summary(cooldown_data.get("last_summary", 0)):
        print("⏰ Time for Daily Summary...")
        send_daily_summary()
        cooldown_data["last_summary"] = now_ts

    try:
        context = get_market_context()
    except Exception as e:
        print(f"[ERROR] Failed to update market context: {e}")
        context = get_market_context_data()
    market_trend = analyze_market_context_trend(context)

    all_news = fetch_news_sources()
    new_alerts_for_digest = []
    sent_ids_this_cycle = []
    updated_levels_this_cycle = set()

    for news in all_news:
        if news['id'] in cooldown_data.get("last_sent_id", []):
            continue

        level = classify_news_level(news['title'])
        news['level'] = level

        cooldown_minutes = LEVEL_COOLDOWN_MINUTES.get(level, 120)
        last_sent_time_for_level = cooldown_data.get("last_sent_level", {}).get(level, 0)

        if now_ts - last_sent_time_for_level < cooldown_minutes * 60:
            continue

        suggestion, impact_tag = generate_specific_suggestion(news, market_trend)

        alert_item = {
            "id": news['id'], "title": news['title'], "url": news['url'],
            "source_name": news['source_name'], "published_at": news.get('published_at', datetime.now().isoformat()),
            "level": level, "category_tag": detect_category_tag(news['title']), "suggestion": suggestion,
            "impact_tag": impact_tag
        }
        new_alerts_for_digest.append(alert_item)
        sent_ids_this_cycle.append(news['id'])
        updated_levels_this_cycle.add(level)

    if new_alerts_for_digest:
        print(f"🔥 Found {len(new_alerts_for_digest)} new alerts. Generating digest...")

        for alert in new_alerts_for_digest:
            json_to_save = {k: v for k, v in alert.items() if k != 'impact_tag'}
            save_news_for_precious(json_to_save)
        print(f"✅ Wrote/Updated {len(new_alerts_for_digest)} items to signal file.")

        news_by_level = defaultdict(list)
        for alert in new_alerts_for_digest:
            news_by_level[alert['level']].append(alert)

        context_block = f"```Bối cảnh thị trường | Fear & Greed: {context.get('fear_greed', 'N/A')} | BTC.D: {context.get('btc_dominance', 'N/A')}% | Trend: {market_trend}```"
        news_blocks = []

        level_order = ["CRITICAL", "WARNING", "ALERT", "WATCHLIST", "INFO"]
        for level in level_order:
            if level in news_by_level:
                emoji = {"CRITICAL": "🔴", "WARNING": "⚠️", "ALERT": "📣", "WATCHLIST": "👀", "INFO": "ℹ️"}.get(level, "ℹ️")
                
                # SỬA LỖI ĐỊNH DẠNG: Thêm một dòng cho tiêu đề level
                level_header = f"{emoji} **{level}**"
                news_blocks.append(level_header)
                
                for alert in news_by_level[level]:
                    # SỬA LỖI ĐỊNH DẠNG: Mỗi tin là một khối riêng, bắt đầu bằng gạch đầu dòng
                    part = (
                        f"- **[{alert['source_name']}] {alert['title']}**\n"
                        f"  *↳ Nhận định:* {alert['suggestion']} [Link](<{alert['url']}>)"
                    )
                    news_blocks.append(part)

        final_summary = generate_final_summary(new_alerts_for_digest, market_trend)
        
        full_digest_message = (f"**🔥 BẢN TIN THỊ TRƯỜE NG - {datetime.now(VN_TZ).strftime('%H:%M')} 🔥**\n\n"
                               + context_block + "\n\n"
                               + "\n".join(news_blocks) # Dùng \n để ghép các dòng
                               + f"\n\n{final_summary}")
        
        send_discord_alert(full_digest_message)

        for level in updated_levels_this_cycle:
            cooldown_data.get("last_sent_level", {})[level] = now_ts
    else:
        print("✅ No new alerts to send for this cycle.")

    cooldown_data["last_sent_id"] = (cooldown_data.get("last_sent_id", []) + sent_ids_this_cycle)[-50:]
    with open(COOLDOWN_TRACKER, 'w') as f:
        json.dump(cooldown_data, f, indent=2)

    print("--- Cycle Finished ---")

if __name__ == "__main__":
    main()
