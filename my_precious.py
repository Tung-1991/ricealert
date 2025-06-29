# -*- coding: utf-8 -*-
import os
import json
import requests
from datetime import datetime
from indicator import get_price_data, calculate_indicators
from signal_logic import check_signal
from dotenv import load_dotenv
import time


load_dotenv()

TRADELOG_DIR = "/root/ricealert/trade/tradelog"
ADVISOR_DIR = "/root/ricealert/advisor_log"
LOG_DIR = os.path.join(ADVISOR_DIR, "log")
os.makedirs(ADVISOR_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

NEWS_DIR = "/root/ricealert/ricenews/lognew"

def send_discord_alert(message, webhook_name="DISCORD_PRECIOUS"):
    url = os.getenv(webhook_name)
    if not url:
        print(f"[ERROR] Webhook {webhook_name} not found in .env")
        return
    chunks = [message[i:i+1900] for i in range(0, len(message), 1900)]
    for i, chunk in enumerate(chunks):
        try:
            requests.post(url, json={"content": chunk}, timeout=10)
            if i < len(chunks) - 1:
                time.sleep(3)
        except Exception as e:
            print(f"[ERROR] Discord send failed: {e}")


def load_news_for_symbol(symbol):
    today_file = os.path.join(NEWS_DIR, f"{datetime.now().strftime('%Y-%m-%d')}_news_signal.json")
    if not os.path.exists(today_file):
        return "⚪ Hiện chưa có tin tức cụ thể liên quan đến đồng coin này hoặc thị trường chung."

    with open(today_file, "r", encoding="utf-8") as f:
        news_data = json.load(f)

    symbol_tag = symbol.lower()
    coin_news = [n for n in news_data if n.get("category_tag") == symbol_tag]
    macro_news = [n for n in news_data if n.get("category_tag") == "macro"]

    if coin_news:
        lines = [f"📰 Tin tức liên quan {symbol.upper()}:"]
        for n in coin_news[:2]:
            prefix = "🔴 " if n.get("level") == "CRITICAL" else ""
            lines.append(f"- {prefix}[{n['source_name']}] {n['title']} → {n.get('suggestion', '')}")
        return "\n".join(lines)
    elif macro_news:
        lines = ["🌐 Có một số tin tức vĩ mô có thể ảnh hưởng chung đến thị trường:"]
        for n in macro_news[:2]:
            prefix = "🔴 " if n.get("level") == "CRITICAL" else ""
            lines.append(f"- {prefix}[{n['source_name']}] {n['title']} → {n.get('suggestion', '')}")
        return "\n".join(lines)
    else:
        return "⚪ Hiện chưa có tin tức cụ thể liên quan đến đồng coin này hoặc thị trường chung."


def parse_trade_plan(plan_str):
    try:
        e, t, s = map(float, plan_str.split("/"))
        return {"entry": e, "tp": t, "sl": s}
    except:
        return {"entry": 0, "tp": 0, "sl": 0}

def round_num(val, d=2):
    return round(val, d) if isinstance(val, (float, int)) else val

def calc_score(ind):
    score = 0
    if ind["rsi_14"] < 30 or ind["rsi_14"] > 70: score += 1
    if ind["macd_cross"] in ["bullish", "bearish"]: score += 1
    if abs(ind["cmf"]) > 0.05: score += 1
    if ind["volume"] > 1.5 * ind["vol_ma20"]: score += 1
    if ind["adx"] > 20: score += 1
    if abs(ind["price"] - ind["fib_0_618"]) < 0.5: score += 1
    if ind["doji_type"]: score += 1
    if ind.get("tag") in ["buy_strong", "short_strong", "swing_trade"]: score += 2
    return min(score, 10)

def generate_indicator_text(ind):
    return "\n".join([
        f"🔹 Giá hiện tại: {ind['price']} | Entry: {ind['trade_plan']['entry']} TP: {ind['trade_plan']['tp']} SL: {ind['trade_plan']['sl']}",
        f"📈 EMA20: {round_num(ind['ema_20'])}  💪 RSI14: {round_num(ind['rsi_14'])} → {'quá mua' if ind['rsi_14'] > 70 else 'quá bán' if ind['rsi_14'] < 30 else 'trung tính'}",
        f"📉 MACD: {round_num(ind['macd_line'],3)} vs Signal: {round_num(ind['macd_signal'],3)} → {ind['macd_cross']}",
        f"📊 ADX: {round_num(ind['adx'],1)} → {'rõ' if ind['adx'] > 20 else 'yếu'}",
        f"🔊 Volume: {int(ind['volume']):,} / MA20: {int(ind['vol_ma20']):,}",
        f"💸 CMF: {round_num(ind['cmf'],3)}",
        f"🌀 Fibo 0.618: {round_num(ind['fib_0_618'],4)}",
        f"🕯️ Nến: {ind.get('doji_type') or 'None'}",
        f"🔺 Trend: {ind['trend']}"
    ])

def describe_market(ind):
    rsi = ind["rsi_14"]
    adx = ind["adx"]
    cmf = ind["cmf"]
    trend = ind["trend"]
    macd = ind["macd_cross"]

    if rsi > 65 and cmf > 0.05 and adx > 20 and trend == "uptrend":
        return "Thị trường đang tăng mạnh, tín hiệu kỹ thuật đồng thuận"
    if 55 <= rsi <= 65 and cmf >= 0 and trend == "uptrend":
        return "Thị trường đang tăng nhẹ với hỗ trợ từ dòng tiền"
    if 45 <= rsi <= 55 and adx < 15:
        return "Thị trường sideway, chưa rõ xu hướng"
    if 35 <= rsi < 45 and cmf < 0 and trend == "downtrend":
        return "Thị trường đang giảm nhẹ, cần thận trọng"
    if rsi < 30 and macd == "bearish" and cmf < -0.05:
        return "Thị trường giảm mạnh, rủi ro cao"
    return "Thị trường không rõ ràng, cần quan sát thêm"

def generate_advice(pnl, ind):
    price = ind["price"]
    tp = ind["trade_plan"]["tp"]
    sl = ind["trade_plan"]["sl"]
    fib = ind["fib_0_618"]
    cmf = ind["cmf"]
    reco = []

    reco.append(describe_market(ind))

    if cmf > 0.05: reco.append("CMF dương → dòng tiền vào")
    if cmf < -0.05: reco.append("CMF âm → dòng tiền rút ra")
    if ind["macd_cross"] == "bullish": reco.append("MACD crossover lên → tín hiệu mua")
    if ind["macd_cross"] == "bearish": reco.append("MACD crossover xuống → cảnh báo điều chỉnh")

    reco.append("")
    reco.append("✅ Chiến lược:")

    if pnl > 5:
        reco.append(f"👉 Chốt lời một phần tại {round_num(price * 1.01)} – {tp}")
        reco.append(f"🛡️ Trailing SL tại vùng Fibo: {round_num(fib)}")
    elif pnl > 0:
        reco.append(f"📈 Giữ nếu chưa thủng {round_num(sl)} → mục tiêu {tp}")
        reco.append(f"🧲 SL động tại {round_num(fib)}")
    elif -3 < pnl <= 0:
        reco.append(f"⏳ Lệnh lỗ nhẹ → theo dõi sát, nếu thủng {round_num(sl)} thì cắt")
    else:
        reco.append("❌ Lệnh đang lỗ sâu, cân nhắc thoát để hạn chế rủi ro")

    return "\n".join(reco)

def calc_held_hours(start_str):
    try:
        t = datetime.strptime(start_str, "%Y-%m-%d %H:%M:%S")
        return round((datetime.now() - t).total_seconds() / 3600, 1)
    except:
        return "?"

def load_daily_log(path):
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return []

def save_daily_log(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

def log_to_txt(msg):
    log_file = os.path.join(LOG_DIR, f"{datetime.now().strftime('%Y-%m-%d')}.txt")
    with open(log_file, "a") as f:
        f.write(msg + "\n")

def is_overview_time():
    now = datetime.now().strftime("%H:%M")
    return now in ["08:00", "20:00"]

def main():
    advisor_file = os.path.join(ADVISOR_DIR, f"{datetime.now().strftime('%Y-%m-%d')}.json")
    trades = []

    for fname in sorted(os.listdir(TRADELOG_DIR)):
        if fname.endswith(".json"):
            fpath = os.path.join(TRADELOG_DIR, fname)
            try:
                with open(fpath, "r") as f:
                    data = json.load(f)
                    trades.extend([t for t in data if t.get("status") == "open"])
            except:
                print(f"[WARN] Lỗi đọc file: {fname}")

    if not trades:
        print("❌ Không tìm thấy lệnh đang mở nào")
        return

    advisor_log = load_daily_log(advisor_file)
    advisor_map = {t["id"]: t for t in advisor_log}
    overview_lines = []

    for trade in trades:
        trade_id = trade["id"]
        symbol = trade["symbol"]
        interval = trade["interval"]
        in_time = trade.get("in_time")
        amount = trade.get("amount", 1000)
        plan = parse_trade_plan(trade["trade_plan"])
        real_entry = trade.get("real_entry") or plan["entry"]

        if not real_entry:
            log_to_txt(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️ Bỏ qua lệnh {symbol} vì entry = 0")
            continue

        df = get_price_data(symbol, interval)
        price_now = round(df.iloc[-2]["close"], 4)
        pnl = round((price_now - real_entry) / real_entry * 100, 2)
        pnl_usd = round(amount * pnl / 100, 2)
        held = calc_held_hours(in_time)

        indicators = calculate_indicators(df, symbol, interval)
        indicators["trade_plan"] = plan
        indicators["price"] = price_now

        score = calc_score(indicators)
        ind_text = generate_indicator_text(indicators)
        advice_text = generate_advice(pnl, indicators)
        news_summary = load_news_for_symbol(symbol)


        # 👇 Thêm phân tích đa timeframe (1h + 1d)
        extra_tf = {}
        for tf in ["1h", "1d"]:
            if tf != interval:
                try:
                    df_tf = get_price_data(symbol, tf)
                    ind_tf = calculate_indicators(df_tf, symbol, tf)
                    extra_tf[tf] = {
                        "rsi": round_num(ind_tf["rsi_14"]),
                        "macd": ind_tf["macd_cross"],
                        "trend": ind_tf["trend"],
                        "score": calc_score(ind_tf)
                    }
                except:
                    pass

        prev = advisor_map.get(trade_id)
        should_send = False

        if not prev:
            should_send = True
        else:
            if abs(prev.get("score", 0) - score) >= 2:
                should_send = True
            elif prev.get("strategy") != advice_text:
                should_send = True

        log_to_txt(f"[{datetime.now().strftime('%H:%M:%S')}] Score: {score} | {'SEND' if should_send else 'SKIP'} | {symbol} {interval}")

        new_entry = {
            "id": trade_id,
            "symbol": symbol,
            "interval": interval,
            "in_time": in_time,
            "held_hours": held,
            "pnl_percent": pnl,
            "pnl_usd": pnl_usd,
            "amount": amount,
            "price": price_now,
            "score": score,
            "indicators_summary": ind_text,
            "strategy": advice_text,
            "last_sent": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": "open"
        }

        coin_amount = round(amount / real_entry, 2)
        current_value = round(amount + pnl_usd, 2)

        if should_send:
            # Phân loại alert
            if pnl > 2 or score >= 7:
                alert_tag = "🚀 [Opportunity]"
            elif pnl < -3 or score <= 3:
                alert_tag = "⚠️ [Risk]"
            else:
                alert_tag = "💎 [Neutral]"

            msg = f"""{alert_tag} Đánh giá lệnh: {symbol} ({interval})
📌 ID: {trade_id} {symbol} {interval}
📆 In time: {in_time} | Đã giữ: {held} giờ | RealEntry: {real_entry}
💰 PnL: {pnl_usd} USD ({pnl}%) | 📦 {coin_amount} | 💵 {current_value}/{amount}


📊 Phân tích kỹ thuật ({interval})
{ind_text}

🧠 Nhận định & Gợi ý
{advice_text}

🗞️ Tin tức liên quan:
{news_summary}
"""

            if extra_tf:
                tf_lines = []
                for tf, val in extra_tf.items():
                    tf_lines.append(f"🕒 {tf}: RSI {val['rsi']} | MACD {val['macd']} | Trend: {val['trend']} | Score: {val['score']}")
                msg += "\n📊 Khung khác:\n" + "\n".join(tf_lines)

            send_discord_alert(msg)

        advisor_map[trade_id] = new_entry

        if is_overview_time():
            coin_amount = round(amount / real_entry, 2)
            current_value = round(amount + pnl_usd, 2)
            in_dt = datetime.strptime(in_time, "%Y-%m-%d %H:%M:%S")
            in_hour = in_dt.strftime("%H:%M")
            in_date = in_dt.strftime("%Y-%m-%d")

            if score >= 8:
                score_icon = "🟦"
            elif score >= 6:
                score_icon = "🟩"
            elif score >= 3:
                score_icon = "🟨"
            else:
                score_icon = "🟥"

            line0 = f"📌 ID: {trade_id} {symbol} {interval}"
            line1 = f"🔹 {symbol} {interval} | 🎯 {real_entry} | 💰 {pnl}% | 📦 {coin_amount} | 💵 {current_value}/{amount} | 🧠 {score} {score_icon}"
            line2 = f"🕒 In: {in_hour} | Giữ: {held}h | Vào: {in_date}"
            line3 = f"🎯 Entry: {real_entry} | 🎯 TP: {plan['tp']} | 🛡 SL: {plan['sl']}"
            overview_lines.append("\n".join([line0, line1, line2, line3]))

    if is_overview_time() and overview_lines:
        total_start = sum([t["amount"] for t in advisor_map.values() if t.get("status") == "open"])
        total_now = sum([round(t["amount"] + t["pnl_usd"], 2) for t in advisor_map.values() if t.get("status") == "open"])
        total_count = len(overview_lines)

        # --- Thêm trending từ news
        trending_line = ""
        try:
            today_file = os.path.join(NEWS_DIR, f"{datetime.now().strftime('%Y-%m-%d')}_news_signal.json")
            with open(today_file, "r", encoding="utf-8") as f:
                news_items = json.load(f)
            from collections import Counter
            import string
            STOPWORDS = {"the", "of", "in", "to", "on", "and", "for", "with", "from", "this", "that", "will", "by", "as", "a", "an", "is"}
            words = []
            for item in news_items:
                title = item.get("title", "").lower().translate(str.maketrans("", "", string.punctuation)).split()
                words += [w for w in title if w not in STOPWORDS and len(w) > 2]
            top3 = [w for w, _ in Counter(words).most_common(3)]
            if top3:
                trending_line = "🔥 Từ khóa nóng: " + ", ".join(top3)
        except:
            pass

        header = f"📋 **Đang có {total_count} lệnh đang mở | Tổng: {total_now}/{total_start} USD**"
        if trending_line:
            header = trending_line + "\n" + header

        send_discord_alert(header + "\n" + "\n".join(overview_lines))



    save_daily_log(advisor_file, list(advisor_map.values()))

if __name__ == "__main__":
    main()
