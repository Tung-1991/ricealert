# -*- coding: utf-8 -*-
# rice_news.py
# Version: 2.0 (Restored & Upgraded)
# Description: This version restores the Daily Summary functionality,
#              improves the summary content with market context, and ensures
#              all necessary helper functions are present and correct.

import os
import json
import requests
import feedparser
import hashlib
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
import time
import re
from collections import Counter
import string

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

COOLDOWN_LEVEL = {"CRITICAL": 60, "WARNING": 120, "ALERT": 240, "WATCHLIST": 360, "INFO": 480}
SUMMARY_COOLDOWN_SECONDS = 60 * 60  # 1 giờ

KEYWORDS = {
    "CRITICAL": ["will list", "etf approval", "halving", "fomc", "interest rate", "cpi", "war", "approved", "regulatory approval"],
    "WARNING": ["delist", "unlock", "hack", "exploit", "sec", "lawsuit", "regulation", "maintenance", "downtime", "outage", "bị điều tra", "kiện"],
    "ALERT": ["upgrade", "partnership", "margin", "futures", "mainnet", "testnet"],
    "WATCHLIST": ["airdrop", "voting", "ama", "token burn", "governance"]
}
POSITIVE_KEYWORDS = ["etf", "niêm yết", "listing", "adoption", "partnership", "approved", "upgrade", "launch", "mainnet", "burn"]
NEGATIVE_KEYWORDS = ["kiện", "hacker", "scam", "bị điều tra", "tether", "sec sues", "sec charges", "hack", "exploit", "lawsuit", "delist", "downtime", "outage"]
MACRO_KEYWORDS = ["fomc", "interest rate", "cpi", "inflation", "sec", "lawsuit", "regulation", "fed", "market", "imf", "war"]

RSS_SOURCES = {"CoinDesk": "https://www.coindesk.com/arc/outboundfeeds/rss", "Cointelegraph": "https://cointelegraph.com/rss"}

# ==============================================================================
# CORE FUNCTIONS
# ==============================================================================

def get_news_sentiment(title: str) -> str:
    lowered = title.lower()
    if any(keyword in lowered for keyword in POSITIVE_KEYWORDS): return "positive"
    if any(keyword in lowered for keyword in NEGATIVE_KEYWORDS): return "negative"
    return "neutral"

def analyze_market_context_trend(mc: dict) -> str:
    if not mc: return "NEUTRAL"
    up_score, down_score = 0, 0
    if mc.get('btc_dominance', 50) > 55: up_score += 1
    elif mc.get('btc_dominance', 50) < 48: down_score += 1
    if mc.get('fear_greed', 50) > 60: up_score += 1
    elif mc.get('fear_greed', 50) < 40: down_score += 1
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
            return coin
    if any(kw in title_l for kw in MACRO_KEYWORDS):
        return "macro"
    return "general"

# ==============================================================================
# DATA FETCHING & PERSISTENCE
# ==============================================================================

def fetch_binance_announcements(limit=5):
    url = f"https://www.binance.com/bapi/composite/v1/public/cms/article/catalog/list/query?catalogId=48&pageSize={limit}&pageNo=1"
    try:
        res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        res.raise_for_status()
        articles = res.json().get("data", {}).get("articles", [])
        return [{
            "id": f"binance_{item.get('code')}", "title": item.get("title"),
            "url": f"https://www.binance.com/en/support/announcement/{item.get('code')}",
            "source_name": "Binance", "published_at": datetime.now(VN_TZ).isoformat()
        } for item in articles]
    except Exception as e:
        print(f"[ERROR] Binance fetch failed: {e}")
        return []

def fetch_rss(feed_url, tag):
    try:
        feed = feedparser.parse(feed_url)
        return [{
            "id": f"{tag}_{hashlib.md5((entry.link + entry.title).encode()).hexdigest()[:12]}",
            "title": entry.title, "url": entry.link, "source_name": tag,
            "published_at": entry.get("published", datetime.now(timezone.utc).isoformat())
        } for entry in feed.entries[:5]]
    except Exception as e:
        print(f"[ERROR] RSS {tag} fetch failed: {e}")
        return []

def load_cooldown():
    if os.path.exists(COOLDOWN_TRACKER):
        with open(COOLDOWN_TRACKER, 'r') as f:
            try: return json.load(f)
            except json.JSONDecodeError: pass
    return {"per_id": {}, "last_sent_level": {}, "last_summary": 0}

def save_cooldown(cooldown):
    with open(COOLDOWN_TRACKER, 'w') as f:
        json.dump(cooldown, f, indent=2)

def save_news(news):
    is_signal = news['level'] != "INFO"
    fname = f"{datetime.now(VN_TZ).strftime('%Y-%m-%d')}_{'news_signal' if is_signal else 'news_all'}.json"
    path = os.path.join(LOG_DIR, fname)
    try:
        with open(path, 'r', encoding='utf-8') as f: logs = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError): logs = []
    
    if not any(news['id'] == i.get('id') for i in logs):
        logs.insert(0, news)
        with open(path, 'w', encoding='utf-8') as f: json.dump(logs, f, indent=2, ensure_ascii=False)
        print(f"🆕 Saved news: {news['title']} ({news['level']})")
    else:
        print(f"⏩ Skipped existing news: {news['title']}")

# ==============================================================================
# DISCORD & SUMMARY FUNCTIONS (RESTORED & UPGRADED)
# ==============================================================================

def send_discord_alert(message):
    if not DISCORD_WEBHOOK:
        print("[WARN] No DISCORD_WEBHOOK configured.")
        return
    try:
        if len(message) > 2000: message = message[:1997] + "..."
        requests.post(DISCORD_WEBHOOK, json={"content": message}, timeout=10)
    except Exception as e:
        print(f"[ERROR] Discord send failed: {e}")

def summarize_trend(news_items: List[Dict]) -> (str, str):
    titles = [i['title'].lower() for i in news_items]
    if any("hack" in t for t in titles):
        return "Một số tin tiêu cực liên quan tới bảo mật hoặc exploit", "DOWNTREND"
    if any("etf" in t or "list" in t for t in titles):
        return "Xuất hiện tin về ETF hoặc niêm yết → thị trường có thể tích cực", "UPTREND"
    
    important_news = next((item for item in news_items if item.get("level") in {"CRITICAL", "WARNING"}), None)
    if important_news:
        trend = "UPTREND" if get_news_sentiment(important_news['title']) == 'positive' else "DOWNTREND"
        return f"Tin tức quan trọng nhất trong ngày: {important_news['title']}", trend
        
    return "Không có tin tức nổi bật hoặc mang tính quyết định", "SIDEWAY"

def generate_context_summary(ctx: dict) -> str:
    try:
        fg = ctx.get("fear_greed", 50)
        vol = ctx.get("total_volume_usd_bil", 0)
        
        if fg < 30: mood = "Thị trường đang sợ hãi – dễ biến động theo tin xấu."
        elif fg > 70: mood = "Tâm lý tham lam chiếm ưu thế – có thể xuất hiện FOMO."
        else: mood = "Tâm lý thị trường trung lập."

        if vol > 100: vol_str = "Khối lượng giao dịch rất cao – thị trường có thể biến động mạnh."
        elif vol < 40: vol_str = "Khối lượng giao dịch thấp – thị trường kém nhạy tin."
        else: vol_str = "Khối lượng giao dịch ổn định."
        return f"{mood} {vol_str}"
    except Exception:
        return "Không xác định được trạng thái thị trường."
        
def send_daily_summary():
    fname = os.path.join(LOG_DIR, f"{datetime.now(VN_TZ).strftime('%Y-%m-%d')}_news_signal.json")
    if not os.path.exists(fname): return
    logs = load_json(fname, [])
    if not logs: return

    summary_by_level = {level: [item for item in logs if item.get("level") == level] for level in KEYWORDS}
    count_summary = {k: len(v) for k, v in summary_by_level.items() if v}
    suggestion, trend = summarize_trend(logs)

    msg = f"\n📊 **Daily News Summary - {datetime.now(VN_TZ).strftime('%d/%m')}**\n"
    for lvl, count in count_summary.items():
        emoji = {"CRITICAL": "🔴", "WARNING": "⚠️", "ALERT": "📣", "WATCHLIST": "👀"}.get(lvl, "ℹ️")
        msg += f"- {emoji} {lvl}: {count} tin\n"
    
    try:
        context = get_market_context_data()
        msg += "\n🌐 Context: " + generate_context_summary(context)
    except Exception as e:
        print(f"[WARN] Cannot load market context for daily summary: {e}")

    msg += f"\n💡 Suggestion: {suggestion}\n📈 Trend: **{trend}**\n\n📰 Chi tiết:\n"
    for lvl, items in summary_by_level.items():
        if not items: continue
        emoji = {"CRITICAL": "🔴", "WARNING": "⚠️", "ALERT": "📣", "WATCHLIST": "👀"}.get(lvl, "ℹ️")
        msg += f"\n{emoji} **{lvl}**\n"
        for item in items[:3]:
            msg += f"- [{item['source_name']}] [{item['title']}](<{item['url']}>)\n"
    send_discord_alert(msg)
    print("✅ Daily summary sent.")


# ==============================================================================
# MAIN EXECUTION
# ==============================================================================
def main():
    # 1. Update & Load Market Context
    try:
        context = get_market_context() # Lấy dữ liệu mới nhất và lưu lại
    except Exception as e:
        print(f"[ERROR] Failed to update market context: {e}")
        context = get_market_context_data() # Thử đọc từ cache

    # 2. Fetch All News
    all_news = fetch_binance_announcements()
    for tag, url in RSS_SOURCES.items():
        all_news += fetch_rss(url, tag)
    print(f"📅 Fetched {len(all_news)} news items.")

    # 3. Process & Filter News
    cooldown = load_cooldown()
    now_ts = datetime.now(VN_TZ).timestamp()
    cooldown_per_id = cooldown.get("per_id", {})
    last_sent_level = cooldown.get("last_sent_level", {})
    
    new_alerts_to_send = {}

    for news in all_news:
        level = classify_news_level(news['title'])
        if level == "INFO": continue

        nid = news['id']
        if now_ts - cooldown_per_id.get(nid, 0) < COOLDOWN_LEVEL[level] * 60:
            continue

        cooldown_per_id[nid] = now_ts
        news['level'] = level
        news['category_tag'] = detect_category_tag(news['title'])
        save_news(news)

        if level not in new_alerts_to_send:
            new_alerts_to_send[level] = []
        new_alerts_to_send[level].append(news)

    # 4. Send Alerts by Level
    for level, items in new_alerts_to_send.items():
        if now_ts - last_sent_level.get(level, 0) < COOLDOWN_LEVEL[level] * 60:
            continue
        
        full_message_for_level = ""
        for item in items:
            sentiment = get_news_sentiment(item['title'])
            market_trend = analyze_market_context_trend(context)
            final_trend_tag = get_final_trend(sentiment, market_trend)
            emoji = {"CRITICAL": "🔴", "WARNING": "⚠️", "ALERT": "📣", "WATCHLIST": "👀"}.get(level, "ℹ️")
            full_message_for_level += f"{emoji} **{level}** News → {final_trend_tag}\n[{item['source_name']}] [{item['title']}](<{item['url']}>)\n\n"
        
        if full_message_for_level:
            send_discord_alert(full_message_for_level.strip())
            print(f"📤 Sent {len(items)} {level} news.")
            last_sent_level[level] = now_ts
            time.sleep(2)

    cooldown["per_id"] = cooldown_per_id
    cooldown["last_sent_level"] = last_sent_level

    # 5. Send Daily Summary
    last_summary_ts = cooldown.get("last_summary", 0)
    now_dt = datetime.now(VN_TZ)
    if (now_dt.hour, now_dt.minute) in [(8, 3), (20, 3)] and (now_ts - last_summary_ts > SUMMARY_COOLDOWN_SECONDS):
        print("⏰ Time for Daily Summary...")
        send_daily_summary()
        cooldown["last_summary"] = now_ts
        
    save_cooldown(cooldown)
    print("✅ Done.")

if __name__ == "__main__":
    main()
