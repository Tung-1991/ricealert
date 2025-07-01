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

# Load environment
dotenv_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')
load_dotenv(dotenv_path=dotenv_path)

# Config
VN_TZ = timezone(timedelta(hours=7))
BASE_DIR = "/root/ricealert/ricenews"
LOG_DIR = os.path.join(BASE_DIR, "lognew")
COOLDOWN_TRACKER = os.path.join(BASE_DIR, "cooldown_tracker.json")
DISCORD_WEBHOOK = os.getenv("DISCORD_NEWS_WEBHOOK")
os.makedirs(LOG_DIR, exist_ok=True)

# Watchlist coins from .env
WATCHED_COINS = set([s.replace("USDT", "").lower() for s in os.getenv("SYMBOLS", "").split(",")])
WATCHED_COINS.update(["btc", "eth"])

# Cooldown (phút)
COOLDOWN_LEVEL = {
    "CRITICAL": 60,
    "WARNING": 120,
    "ALERT": 240,
    "WATCHLIST": 360,
    "INFO": 480
}
SUMMARY_COOLDOWN = 60 * 60

KEYWORDS = {
    "CRITICAL": ["will list", "etf approval", "halving", "fomc", "interest rate hike", "cpi", "war", "approved", "regulatory approval"],
    "WARNING": ["delist", "unlock", "hack", "exploit", "sec", "lawsuit", "regulation", "maintenance", "downtime", "outage"],
    "ALERT": ["upgrade", "partnership", "margin", "futures launch", "mainnet launch", "testnet launch"],
    "WATCHLIST": ["airdrop", "voting", "ama", "token burn", "governance"]
}

RSS_SOURCES = {
    "CoinDesk": "https://www.coindesk.com/arc/outboundfeeds/rss",
    "Cointelegraph": "https://cointelegraph.com/rss"
}

STOPWORDS = {"the", "of", "in", "to", "on", "and", "for", "with", "will", "from", "this", "that", "a", "an", "is", "by", "as"}

MACRO_KEYWORDS = ["fomc", "interest rate", "cpi", "inflation", "sec", "lawsuit", "regulation", "fed", "market", "imf", "war"]

def detect_category_tag(title):
    title_l = title.lower()
    for coin in WATCHED_COINS:
        if coin in title_l:
            return coin
    if any(kw in title_l for kw in MACRO_KEYWORDS):
        return "macro"
    return "general"


def extract_trending_keywords(news_items, topk=3):
    words = []
    for item in news_items:
        tokens = item['title'].lower().translate(str.maketrans('', '', string.punctuation)).split()
        words += [w for w in tokens if w not in STOPWORDS and len(w) > 2]
    most_common = Counter(words).most_common(topk)
    return [kw for kw, _ in most_common]

def fetch_binance_announcements(limit=5):
    url = f"https://www.binance.com/bapi/composite/v1/public/cms/article/catalog/list/query?catalogId=48&pageSize={limit}&pageNo=1"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        res.raise_for_status()
        data = res.json().get("data", {}).get("articles", [])
        return [
            {
                "id": f"binance_{item.get('code')}",
                "title": item.get("title"),
                "url": f"https://www.binance.com/en/support/announcement/{item.get('code')}",
                "source_name": "Binance",
                "published_at": datetime.now(VN_TZ).isoformat(),
                "tags": ["binance", "exchange"]
            } for item in data
        ]
    except Exception as e:
        print(f"[ERROR] Binance: {e}")
        return []

def fetch_rss(feed_url, tag):
    news = []
    try:
        feed = feedparser.parse(feed_url)
        for entry in feed.entries[:5]:
            dupe_key = hashlib.md5(
                (entry.link.lower().strip() + entry.title.lower()).encode()
            ).hexdigest()[:12]
            news.append({
                "id": f"{tag}_{dupe_key}",
                "title": entry.title,
                "url": entry.link,
                "source_name": tag,
                "published_at": entry.get("published", datetime.now(timezone.utc).isoformat()),
                "tags": [tag.lower()]
            })
    except Exception as e:
        print(f"[ERROR] RSS {tag}: {e}")
    return news


def classify_news_level(title: str) -> str:
    title_l = title.lower()
    for level, keys in KEYWORDS.items():
        for key in keys:
            # match đúng từ (word-boundary) thay vì substring
            if re.search(rf"\b{re.escape(key)}\b", title_l):
                return level
    return "INFO"

def generate_suggestion_and_trend(title, source=None):
    title_l = title.lower()

    if re.search(r"\b(will|to)?\s*list\b", title_l) or "etf" in title_l:
        return "Tin tức về niêm yết mới hoặc sản phẩm ETF – đây thường là chất xúc tác khiến giá biến động mạnh.", "UPTREND"

    if any(w in title_l for w in ["mainnet", "launch", "upgrade"]):
        return "Dự án đang triển khai cập nhật hoặc ra mắt sản phẩm mới – có thể tạo kỳ vọng tăng trưởng ngắn hạn.", "UPTREND"

    if any(w in title_l for w in ["hack", "exploit", "lawsuit"]):
        return "Thông tin tiêu cực: sự cố bảo mật hoặc kiện tụng – có khả năng gây áp lực bán trên thị trường.", "DOWNTREND"

    # ➡️ thêm đoạn này
    if any(w in title_l for w in ["fatf", "sec", "regulation", "stablecoin crime", "stablecoin regulation", "warning"]):
        return "Tin liên quan đến giám sát/pháp lý (FATF, SEC…) – thường gây áp lực giảm ngắn hạn do rủi ro tuân thủ.", "DOWNTREND"

    if "airdrop" in title_l:
        return "Thông báo về airdrop – thường kích thích cộng đồng tham gia nhưng ít ảnh hưởng trực tiếp đến giá.", "WATCH"

    if any(w in title_l for w in ["governance", "voting"]):
        return "Tin tức liên quan đến quản trị, biểu quyết – phản ánh thay đổi chiến lược nội bộ của dự án.", "WATCH"

    if source == "Cointelegraph" and "vitalik" in title_l:
        return "Vitalik đưa ra nhận định mới – có thể ảnh hưởng đến cộng đồng Ethereum.", "SIDEWAY"

    return "Không có nội dung mang tính định hướng rõ ràng – tin tức thiên về tổng hợp hoặc trung lập.", "SIDEWAY"

# Các phần còn lại của file nên bao gồm thêm logic sử dụng detect_category_tag và extract_trending_keywords trong các bước xử lý và gửi dữ liệu.


def load_cooldown():
    if os.path.exists(COOLDOWN_TRACKER):
        with open(COOLDOWN_TRACKER, 'r') as f:
            return json.load(f)
    return {"per_id": {}, "last_sent": {}}

def save_cooldown(cooldown):
    with open(COOLDOWN_TRACKER, 'w') as f:
        json.dump(cooldown, f)

def save_news(news, signal=False):
    fname = f"{datetime.now(VN_TZ).strftime('%Y-%m-%d')}_{'news_signal' if signal else 'news_all'}.json"
    path = os.path.join(LOG_DIR, fname)
    try:
        with open(path, 'r', encoding='utf-8') as f:
            logs = json.load(f)
    except:
        logs = []


    exists = any(news['id'] == i.get('id') or news['title'] == i.get('title') for i in logs)
    if not exists:
        news['agent_tracking'] = 'open'
        logs.insert(0, news)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(logs, f, indent=2, ensure_ascii=False)
        print(f"🆕 Lưu tin mới: {news['title']} ({news['level']})")
    else:
        print(f"⏩ Bỏ qua tin đã tồn tại: {news['title']}")

def send_discord_alert(message):
    if not DISCORD_WEBHOOK:
        print("[WARN] No DISCORD_WEBHOOK")
        return
    try:
        requests.post(DISCORD_WEBHOOK, json={"content": message}, timeout=10)
    except Exception as e:
        print(f"[ERROR] Discord send failed: {e}")

def summarize_trend(news_items):
    titles = [i['title'].lower() for i in news_items]
    suggestions = [i.get('suggestion', '') for i in news_items if i.get("suggestion")]
    if any("hack" in t for t in titles):
        return "Một số tin tiêu cực liên quan tới bảo mật hoặc exploit", "DOWNTREND"
    if any("etf" in t or "list" in t for t in titles):
        return "Xuất hiện tin về ETF hoặc niêm yết → thị trường có thể tích cực", "UPTREND"
    if suggestions:
        return suggestions[0], news_items[0].get("trend", "SIDEWAY")
    return "Không có tin tức nổi bật hoặc mang tính quyết định", "SIDEWAY"

def send_daily_summary():
    fname = os.path.join(LOG_DIR, f"{datetime.now(VN_TZ).strftime('%Y-%m-%d')}_news_signal.json")
    if not os.path.exists(fname):
        return
    try:
        with open(fname, 'r', encoding='utf-8') as f:
            logs = json.load(f)
    except:
        return

    summary = {"CRITICAL": [], "WARNING": [], "ALERT": [], "WATCHLIST": []}
    for item in logs:
        if item.get("level") in summary:
            summary[item["level"].upper()].append(item)

    count_summary = {k: len(v) for k, v in summary.items()}
    all_items = sum(summary.values(), [])
    suggestion, trend = summarize_trend(all_items)

    msg = f"\n📊 **Daily News Summary - {datetime.now(VN_TZ).strftime('%d/%m')}**\n"
    for lvl, count in count_summary.items():
        if count:
            emoji = {"CRITICAL": "🔴", "WARNING": "⚠️", "ALERT": "📣", "WATCHLIST": "👀"}.get(lvl, "ℹ️")
            msg += f"- {emoji} {lvl}: {count} tin\n"
    msg += f"\n💡 Suggestion: {suggestion}\n📈 Trend: **{trend}**\n\n📰 Chi tiết:\n"
    for lvl, items in summary.items():
        if not items:
            continue
        emoji = "🔴" if lvl == "CRITICAL" else "⚠️" if lvl == "WARNING" else "📣"
        msg += f"\n{emoji} **{lvl}**\n"
        for item in items:
            msg += f"- [{item['source_name']}] [{item['title']}](<{item['url']}>) → 🔗\n"
    send_discord_alert(msg)

def main():
    all_news = fetch_binance_announcements()
    for tag, url in RSS_SOURCES.items():
        all_news += fetch_rss(url, tag)

    print(f"📅 Fetched {len(all_news)} news")
    cooldown = load_cooldown()
    now = datetime.now(VN_TZ).timestamp()
    cooldown_per_id = cooldown.get("per_id", {})
    last_sent = cooldown.get("last_sent", {})
    news_by_level = {level: [] for level in COOLDOWN_LEVEL}

    for news in all_news:
        level = classify_news_level(news['title'])
        news['level'] = level
        news["category_tag"] = detect_category_tag(news["title"])
        nid = news['id']

        if now - cooldown_per_id.get(nid, 0) < COOLDOWN_LEVEL[level] * 60:
            print(f"⏳ Cooldown: Bỏ qua {news['title']}")
            continue

        cooldown_per_id[nid] = now
        if level != "INFO":
            suggestion, trend = generate_suggestion_and_trend(news['title'], news.get("source_name"))
            news['suggestion'] = suggestion
            news['trend'] = trend
            save_news(news, signal=True)
        save_news(news)
        news_by_level[level].append(news)

    for level, items in news_by_level.items():
        if not items:
            continue
        if now - last_sent.get(level, 0) < COOLDOWN_LEVEL[level] * 60:
            continue

        last_sent[level] = now
        emoji = {
            "CRITICAL": "🔴",
            "WARNING": "⚠️",
            "ALERT": "📣",
            "WATCHLIST": "👀",
            "INFO": "ℹ️"
        }[level]

        msg = f"{emoji} **{level} News**\n"
        for item in items:
            msg += f"[{item['source_name']}] [{item['title']}](<{item['url']}>) → 🔗\n"
        if level != "INFO":
            msg += f"\n💡 Suggestion: {summarize_trend(items)[0]}"
        send_discord_alert(msg)
        print(f"📤 Sent {len(items)} {level} news")
        time.sleep(2)

    cooldown["per_id"] = cooldown_per_id
    cooldown["last_sent"] = last_sent
    save_cooldown(cooldown)
    summary_stamp = cooldown.get("daily_summary", 0)

    now_dt = datetime.now(VN_TZ)
    now_ts = int(now_dt.timestamp())

    print("🕐 Giờ hiện tại:", now_dt.hour, now_dt.minute)
    print("📊 Điều kiện:", (now_dt.hour, now_dt.minute) in [(8, 3), (20, 3)])
    print("⏳ Cooldown passed:", now_ts - summary_stamp, ">", SUMMARY_COOLDOWN)

    if (now_dt.hour, now_dt.minute) in [(8, 3), (20, 3)] and now_ts - summary_stamp > SUMMARY_COOLDOWN:
        print("🚨 Đủ điều kiện gửi daily summary")
        send_daily_summary()
        cooldown["daily_summary"] = now_ts
        save_cooldown(cooldown)

    print("✅ Done")

if __name__ == "__main__":
    main()
