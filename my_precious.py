# -*- coding: utf-8 -*-
"""my_precious.py – position advisor
Clean version after news‑block patch. 2025‑07‑01
"""
import os
import json
import time
import string
from datetime import datetime
from collections import Counter
from typing import List, Dict, Any
import math, time, requests, html


import requests
from dotenv import load_dotenv

from indicator import get_price_data, calculate_indicators
from signal_logic import check_signal

load_dotenv()
WEBHOOK_URL = os.getenv("DISCORD_PRECIOUS")

# ---------------------------------------------------------------------------
# CONFIG & PATHS -------------------------------------------------------------
# ---------------------------------------------------------------------------
COOLDOWN_STATE_PATH = "/root/ricealert/advisor_log/cooldown_state.json"

LEVEL_COOLDOWN_MINUTES: Dict[str, int] = {
    "PANIC_SELL": 180,
    "SELL":       240,
    "AVOID":      300,
    "HOLD":       360,
    "WEAK_BUY":   300,
    "BUY":        240,
    "STRONG_BUY": 180,
}


ICON = {"PANIC_SELL":"🆘","SELL":"🔻","AVOID":"⛔",
        "HOLD":"💎","WEAK_BUY":"🟢","BUY":"🛒","STRONG_BUY":"🚀"}

def level_from_score(sc: int) -> str:
    """Map score 0-10 bất kỳ → 7-level (PANIC_SELL … STRONG_BUY)."""
    if   sc < 1:  return "PANIC_SELL"
    elif sc < 3:  return "SELL"
    elif sc < 4:  return "AVOID"
    elif sc < 5:  return "HOLD"
    elif sc < 6:  return "WEAK_BUY"
    elif sc < 8:  return "BUY"
    else:         return "STRONG_BUY"


TRADELOG_DIR = "/root/ricealert/trade/tradelog"
ADVISOR_DIR  = "/root/ricealert/advisor_log"
LOG_DIR      = os.path.join(ADVISOR_DIR, "log")
NEWS_DIR     = "/root/ricealert/ricenews/lognew"
AI_DIR       = "/root/ricealert/ai_logs"

os.makedirs(LOG_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# BASIC UTILITIES ------------------------------------------------------------
# ---------------------------------------------------------------------------

def load_json(path: str, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def write_json(path: str, data) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_cooldown_state() -> Dict[str, Dict[str, str]]:
    return load_json(COOLDOWN_STATE_PATH, {})


def save_cooldown_state(state: dict) -> None:
    write_json(COOLDOWN_STATE_PATH, state)


def is_cooldown_passed(last_sent: str, level: str, now: datetime) -> bool:
    try:
        minutes = LEVEL_COOLDOWN_MINUTES.get(level.replace(" ", "_").upper(), 180)
        delta   = (now - datetime.strptime(last_sent, "%Y-%m-%d %H:%M:%S")).total_seconds() / 60
        return delta >= minutes
    except Exception:
        return True


def smart_chunk(text: str, limit: int = 1900) -> List[str]:
    """Split long text into Discord‑safe chunks."""
    parts, buf = [], ""
    for ln in text.split("\n"):
        if len(buf) + len(ln) + 1 < limit:
            buf += "\n" + ln
        else:
            parts.append(buf.strip())
            buf = ln
    if buf:
        parts.append(buf.strip())
    return parts


def send_discord_alert(msg: str) -> None:
    if not WEBHOOK_URL:
        print("[ERROR] DISCORD_AI_WEBHOOK not set")
        return

    def _post(chunk: str):
        r = requests.post(WEBHOOK_URL, json={"content": chunk}, timeout=10)
        r.raise_for_status()          # <- thấy lỗi là biết liền
        time.sleep(1.5)               # tránh spam rate-limit

    try:
        if len(msg) > 1900:           # 1900 để trừ hao escape
            for i in range(0, len(msg), 1900):
                _post(msg[i : i + 1900])
        else:
            _post(msg)
    except Exception as exc:
        print(f"[ERROR] Discord alert failed: {exc}")
        send_error_alert(f"Discord alert failed: {exc}")

# ---------------------------------------------------------------------------
# VERBOSE ML SUMMARY ---------------------------------------------------------
# ---------------------------------------------------------------------------

def format_ml_summary_verbose(ml: Dict[str, Any]) -> str:
    """Return a detailed human‑friendly summary of an AI‑ML prediction dict."""
    level = ml.get("level", "").upper()
    pct   = ml.get("pct", 0)
    score = ml.get("score", 0)
    price = ml.get("price", 0)
    entry = ml.get("entry", 0)
    tp    = ml.get("tp", 0)
    sl    = ml.get("sl", 0)

    lines = [
        f"🤖 AI ML ({level})",
        f"📊 Dự đoán: {pct:+.2f}% {'(tăng)' if pct > 0 else '(giảm)'} 🧠 Xác suất: {score:.2f}%",
        f"💰 Giá hiện tại: {price} Entry: {entry}",
        f"🎯 TP: {tp} 🛡️ SL: {sl}",
    ]

    reasons = {
        "PANIC SELL": "📉 Mô hình cảnh báo rủi ro cao – nên ưu tiên cắt lệnh",
        "AVOID":      "⚠️ Không có edge rõ ràng – hạn chế giao dịch",
    }
    if level in {"BUY", "STRONG_BUY", "WEAK_BUY", "HOLD"}:
        reasons[level] = "✅ AI kỳ vọng tăng giá – có thể giữ hoặc mở vị thế"
    if level == "SHORT_STRONG":
        reasons[level] = "📉 Xu hướng giảm rõ rệt – cân nhắc đảo chiều"

    lines.append(reasons.get(level, "🤖 Lý do: Không xác định rõ"))
    return "\n".join(lines)

# ---------------------------------------------------------------------------
# NEWS -----------------------------------------------------------------------
# ---------------------------------------------------------------------------

def load_news_for_symbol(symbol: str) -> str:
    """Return formatted news lines for a coin symbol or macro context."""
    today_path = os.path.join(NEWS_DIR, f"{datetime.now().strftime('%Y-%m-%d')}_news_signal.json")
    if not os.path.exists(today_path):
        return "⚪ Hiện chưa có tin tức cụ thể liên quan đến đồng coin này hoặc thị trường chung."  # noqa: E501

    news_data = load_json(today_path, [])

    tag = symbol.lower().replace("usdt", "").strip()

    coin_news = [n for n in news_data if n.get("category_tag") == tag]

    macro_news = [
        n for n in news_data
        if n.get("category_tag") in {"macro", "general"}
        and n.get("level") in {"CRITICAL", "ALERT", "WATCHLIST"}
    ]

    # --- coin‑specific news ---
    if coin_news:
        lines = [f"📰 Tin tức liên quan {symbol.upper()}:"]
        for n in coin_news[:2]:
            prefix = "🔴 " if n.get("level") == "CRITICAL" else ""
            lines.append(f"- {prefix}[{n['source_name']}] {n['title']} → {n.get('suggestion', '')}")
        return "\n".join(lines)

    # --- macro fallback ---
    if macro_news:
        macro_news.sort(
            key=lambda n: (
                0 if n["level"] == "CRITICAL" else 1 if n["level"] == "ALERT" else 2,
                n.get("published_at", ""),
            )
        )
        lines = ["🌐 Tin vĩ mô đáng chú ý:"]
        for n in macro_news[:2]:
            prefix = "🔴 " if n.get("level") == "CRITICAL" else ""
            lines.append(f"- {prefix}[{n['source_name']}] {n['title']} → {n.get('suggestion', '')}")
        return "\n".join(lines)

    return "⚪ Hiện chưa có tin tức cụ thể liên quan đến đồng coin này hoặc thị trường chung."

# ---------------------------------------------------------------------------
#  (rest of file: indicator calc, advice gen, main loop) – UNCHANGED
# ---------------------------------------------------------------------------



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
    if ind.get('trend_alignment_bonus'):        # <-- thêm dòng này
        score += ind['trend_alignment_bonus']    # +1 khi đủ điều kiện

    if ind["rsi_14"] < 30 or ind["rsi_14"] > 70: score += 1
    if ind["macd_cross"] in ["bullish", "bearish"]: score += 1
    if abs(ind["cmf"]) > 0.05: score += 1
    if ind["volume"] > 1.5 * ind["vol_ma20"]: score += 1
    if ind["adx"] > 20: score += 1
    if abs(ind["price"] - ind["fib_0_618"]) / ind["price"] < 0.01:
        score += 1
    if ind["doji_type"]: score += 1
    if ind.get("tag") in ["buy_strong", "short_strong", "swing_trade"]: score += 2
    return min(score, 10)

def format_price(price):
    if not isinstance(price, (int, float)):
        return price
    return f"{price:.8f}" if price < 0.1 else f"{price:.4f}"

def generate_indicator_text(ind: dict) -> str:
    """
    Trả về block phân tích kỹ thuật.
    Nếu ind có 'level_key' (PANIC_SELL … STRONG_BUY) thì gắn icon tương ứng.
    """
    icon = ICON.get(ind.get("level_key", ""), "")   # "" nếu chưa có level_key

    lines = [
        f"{icon} Giá hiện tại: {format_price(ind['price'])}  |  "
        f"Entry {format_price(ind['trade_plan']['entry'])}  |  "
        f"TP {format_price(ind['trade_plan']['tp'])}  |  "
        f"SL {format_price(ind['trade_plan']['sl'])}",

        f"📈 EMA20: {round_num(ind['ema_20'])}   "
        f"💪 RSI14: {round_num(ind['rsi_14'])} → "
        f"{'quá mua' if ind['rsi_14']>70 else 'quá bán' if ind['rsi_14']<30 else 'trung tính'}",

        f"📉 MACD: {round_num(ind['macd_line'],3)} vs "
        f"Signal: {round_num(ind['macd_signal'],3)} → {ind['macd_cross']}",

        f"📊 ADX: {round_num(ind['adx'],1)} → {'rõ' if ind['adx']>20 else 'yếu'}",
        f"🔊 Volume: {int(ind['volume']):,} / MA20: {int(ind['vol_ma20']):,}",
        f"💸 CMF: {round_num(ind['cmf'],3)}",
        f"🌀 Fibo 0.618: {round_num(ind['fib_0_618'],4)}",
        f"🔧 Nến: {ind.get('doji_type') or 'None'}",
        f"⬆️ Trend: {ind['trend']}",
    ]
    return "\n".join(lines)


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
    
    
def analyze_multi_timeframe(extra_tf: dict) -> str:
    """
    Phân tích đa khung dựa trên trend + CMF + AI để đưa ra nhận định tổng thể.
    """
    from collections import Counter

    trends = Counter()
    ai_biases = Counter()
    lines = []

    for tf, tfdata in sorted(extra_tf.items()):
        trend = tfdata.get("trend", "unknown")
        cmf = tfdata.get("cmf", 0)
        rsi = tfdata.get("rsi", "?")
        ai_score = tfdata.get("ai_score", "?")
        ai_bias = tfdata.get("ai_bias", "neutral")

        trends[trend] += 1
        ai_biases[ai_bias] += 1

        icon = "⬆️" if trend == "uptrend" else "⬇️" if trend == "downtrend" else "➡️"
        lines.append(
            f"{icon} {tf}: Trend: {trend:<9} | RSI: {rsi:<5} | CMF: {round_num(cmf,3):<6} | AI: {ai_score}% ({ai_bias})"
        )

    summary = []

    # Tổng hợp xu hướng
    if trends["uptrend"] >= 2:
        summary.append("🔼 Đa khung xác nhận xu hướng tăng.")
    elif trends["downtrend"] >= 2:
        summary.append("🔽 Đa khung xác nhận xu hướng giảm.")
    else:
        summary.append("🌀 Xu hướng các khung không đồng thuận.")

    # Tổng hợp AI bias
    if ai_biases["bullish"] >= 2:
        summary.append("🤖 AI nghiêng về tăng giá ở nhiều khung.")
    elif ai_biases["bearish"] >= 2:
        summary.append("🤖 AI cảnh báo xu hướng giảm.")
    else:
        summary.append("🤖 AI chưa rõ xu hướng chung.")

    return "\n".join(summary + [""] + lines)
    
def generate_final_strategy(
    score: int,
    ai_score: float,
    news_factor: int,
    pnl: float,
    ind: dict,
    extra_tf: dict,
) -> str:
    reco = []
    reasons = []
    alerts = []

    lvl = ind.get("level_key", "")
    fib = ind.get("fib_0_618")
    sl = ind["trade_plan"]["sl"]
    tp = ind["trade_plan"]["tp"]
    price = ind["price"]
    trend = ind["trend"]
    cmf = ind["cmf"]
    macd = ind["macd_cross"]
    rsi = ind.get("rsi_14", 0)

    # 🎯 KẾT LUẬN CHÍNH
    if lvl in {"PANIC_SELL", "SELL"}:
        reco.append("🔻 **Cân nhắc giảm vị thế hoặc đóng lệnh để bảo toàn vốn.**")
    elif lvl == "AVOID":
        reco.append("⛔ **Thị trường không rõ ràng – tránh giao dịch, đứng ngoài.**")
    elif lvl == "HOLD":
        reco.append("💎 **Giữ lệnh hiện tại, chưa nên mở thêm.** Theo dõi phản ứng giá vùng hỗ trợ.")
    elif lvl == "WEAK_BUY":
        reco.append("🟢 **Có thể mở vị thế nhỏ khi giá điều chỉnh/pullback.**")
    elif lvl == "BUY":
        reco.append("🛒 **Mua từng phần tại vùng hỗ trợ, ưu tiên vùng gần Fibo 0.618 hoặc breakout trend.**")
    elif lvl == "STRONG_BUY":
        reco.append("🚀 **Xu hướng mạnh, đồng thuận – có thể scale-in quyết đoán.** Ưu tiên khi giá vượt mốc quan trọng.")

    # 📌 LÝ DO
    if score >= 7:
        reasons.append(f"– Kỹ thuật ủng hộ: Score {score}/10")
    elif score <= 3:
        reasons.append(f"– Kỹ thuật yếu: Score {score}/10")

    if ai_score >= 70:
        reasons.append(f"– AI dự báo tăng mạnh (xác suất {ai_score}%)")
    elif ai_score >= 60:
        reasons.append(f"– AI thiên về tăng (xác suất {ai_score}%)")
    elif ai_score <= 40:
        reasons.append(f"– AI thiên về giảm (xác suất {ai_score}%)")

    if news_factor == 1:
        reasons.append("– Tin tức tích cực hỗ trợ thị trường")
    elif news_factor == -1:
        reasons.append("– Tin tức tiêu cực – cần thận trọng")

    if cmf > 0.05:
        reasons.append("– CMF dương → dòng tiền đang vào thị trường")
    elif cmf < -0.05:
        reasons.append("– CMF âm → dòng tiền bị rút ra")

    if macd == "bullish":
        reasons.append("– MACD xác nhận xu hướng tăng")
    elif macd == "bearish":
        reasons.append("– MACD đảo chiều giảm")

    if rsi >= 70:
        alerts.append("⚠️ RSI cao – có thể đã quá mua, dễ điều chỉnh")
    elif rsi <= 30:
        alerts.append("⚠️ RSI thấp – thị trường có thể bị bán quá mức")

    # 📊 ĐA KHUNG THỜI GIAN
    if extra_tf:
        tf_up = sum(1 for tf in extra_tf.values() if tf["trend"] == "uptrend")
        tf_down = sum(1 for tf in extra_tf.values() if tf["trend"] == "downtrend")
        if tf_up >= 2:
            reasons.append("– Đa khung thời gian xác nhận xu hướng tăng")
        elif tf_down >= 2:
            reasons.append("– Đa khung cảnh báo xu hướng giảm")

    # 🔍 PHÂN TÍCH GIÁ & FIBO
    if trend == "uptrend" and price > fib * 1.01:
        reasons.append("– Giá đã vượt vùng Fibo 0.618 → khả năng breakout.")
    elif trend == "uptrend" and abs(price - fib) / fib < 0.01:
        reasons.append("– Giá đang retest Fibo 0.618 – vùng đáng theo dõi để vào lệnh.")

    # 📌 GỢI Ý HÀNH ĐỘNG THEO PHONG CÁCH TRADER
    if lvl in {"STRONG_BUY", "BUY"} and score >= 7 and ai_score >= 60:
        reco.append("📌 Gợi ý theo phong cách:")
        reco.append("– Scalper: Có thể entry sớm ở pullback nhỏ.")
        reco.append("– Swing trader: Chờ breakout xác nhận, vào lệnh theo trend.")
        reco.append("– Holder: Xem xét mở vị thế tích lũy nếu xác định đây là vùng hỗ trợ mạnh.")

    # 💰 HÀNH ĐỘNG THEO PNL
    if pnl > 5:
        reco.append(f"👉 Đang lời {pnl}% – cân nhắc *chốt 50%*, kéo SL lên vùng {round_num(fib)} hoặc hòa vốn.")
    elif pnl <= -3:
        reco.append(f"❌ Lỗ sâu ({pnl}%) – cân nhắc giảm vị thế, tránh bình quân giá.")
    elif -3 < pnl < 0:
        reco.append(f"⏳ Đang lỗ nhẹ ({pnl}%) – giữ SL chặt ở {round_num(sl)} để tránh rủi ro sâu hơn.")
    elif 0 <= pnl < 2:
        reco.append(f"🔍 PnL thấp ({pnl}%) – tiếp tục theo dõi, cân nhắc dời TP/SL nếu cần.")

    # 🛡️ SL DYNAMIC
    dynamic_sl = min(round_num(price * 0.98), round_num(sl))
    reco.append(f"🎯 Gợi ý SL động: {dynamic_sl} – đặt dưới vùng hỗ trợ gần nhất.")

    # 🧠 ĐÁNH GIÁ TỔNG THỂ
    def overall_sentiment(score, ai_score, news_factor, extra_tf):
        pos = 0
        if score >= 7: pos += 1
        if score <= 3: pos -= 1
        if ai_score >= 70: pos += 1
        elif ai_score <= 40: pos -= 1
        if news_factor == 1: pos += 1
        elif news_factor == -1: pos -= 1
        if sum(1 for tf in extra_tf.values() if tf["trend"] == "uptrend") >= 2: pos += 1
        if sum(1 for tf in extra_tf.values() if tf["trend"] == "downtrend") >= 2: pos -= 1

        # Đánh giá từ -3 đến +3
        if pos <= -3:
            return "💀 Tổng thể cực kỳ **tiêu cực** – nên tránh xa hoặc đóng lệnh."
        elif pos == -2:
            return "📉 Tổng thể thiên về **giảm** – cần thận trọng."
        elif pos == -1:
            return "🔻 Dấu hiệu hơi tiêu cực – ưu tiên phòng thủ."
        elif pos == 0:
            return "🔄 Tín hiệu **hỗn hợp** – chưa rõ xu hướng, cần quan sát thêm."
        elif pos == 1:
            return "🔸 Xu hướng hơi tích cực – có thể chuẩn bị cơ hội."
        elif pos == 2:
            return "📈 Tổng thể thiên về **tăng** – có thể mở vị thế thăm dò."
        else:  # pos >= 3
            return "🚀 Xu hướng **cực kỳ tích cực** – đồng thuận nhiều yếu tố, nên tận dụng cơ hội."


    # 🧠 FORMAT
    reco = [r for r in reco if r.strip()]
    out = []
    out.append("🧠 **Chiến lược cuối cùng:**")
    out.extend([f"• {line}" for line in reco])
    if reasons:
        out.append("📌 Lý do:")
        out.extend(reasons)
    if alerts:
        out.append("⚠️ Lưu ý:")
        out.extend(alerts)
    out.append("📉 Đánh giá tổng hợp:")
    out.append(overall_sentiment(score, ai_score, news_factor, extra_tf))
    return "\n".join(out)




# ---------------------------------------------------------------------------
# SMART ADVICE, 7-LEVEL AWARE ----------------------------------------------
# ---------------------------------------------------------------------------
def generate_advice(
        pnl: float,
        ind: Dict[str, Any],
        ai_bias: str | None = None,
        news_factor: int = 0,
        extra_tf: dict = None
) -> str:
    """
    Trả về gợi ý chiến lược bằng tiếng Việt, đã biết 7 cấp độ level_key.
    Với PANIC_SELL / SELL / AVOID → trả về ngắn gọn, dứt khoát.
    Với HOLD … STRONG_BUY → phân tích chi tiết + đề xuất SL/TP.
    """
    lvl   = ind.get("level_key", "").upper()          # PANIC_SELL…STRONG_BUY
    price = ind["price"]
    tp    = ind["trade_plan"]["tp"]
    sl    = ind["trade_plan"]["sl"]
    fib   = ind["fib_0_618"]
    cmf   = ind["cmf"]

    # ===== 1. Các cấp độ “cực đoan” – trả lời ngay, không cần phân tích dài ====
    if lvl == "PANIC_SELL":
        return (
            "⚠️ **Panic-Sell** → ưu tiên *thoát lệnh ngay*, tránh trượt giá.\n"
            f"Đặt SL sát {round_num(price*0.995)} hoặc đóng toàn bộ vị thế."
        )
    if lvl == "SELL":
        return (
            "🔻 **Sell** → xu hướng xấu, ưu tiên chốt lời/thu hẹp vị thế.\n"
            f"Giữ SL dưới {round_num(sl)} – *không* scale-in."
        )
    if lvl == "AVOID":
        return "⛔ **Avoid** → Tín hiệu nhiễu, đứng ngoài quan sát thêm."

    # ===== 2. Phần còn lại: HOLD - WEAK_BUY - BUY - STRONG_BUY ===============
    reco: List[str] = [describe_market(ind)]          # khung cảnh chung

    # ---- Money-flow & MACD ---------------------------------------------------
    if cmf >  0.05: reco.append("CMF dương → dòng tiền đang *vào*")
    if cmf < -0.05: reco.append("CMF âm → dòng tiền đang *ra*")

    macd_cross = ind["macd_cross"]
    if macd_cross == "bullish":
        reco.append("MACD giao cắt *lên* → tín hiệu mua hỗ trợ")
    elif macd_cross == "bearish":
        reco.append("MACD giao cắt *xuống* → chú ý điều chỉnh")

    # ---- AI / News cue  ------------------------------------------------------
    if ai_bias == "bullish":
        reco.append("🤖 AI *lạc quan* – có thể scale-in khi *pullback nhẹ*")
    elif ai_bias == "bearish":
        reco.append("🤖 AI *bi quan* – giảm vị thế / SL chặt")

    if news_factor ==  1:  reco.append("📰 Tin tức *tích cực* – giá dễ bật nhanh")
    if news_factor == -1:  reco.append("📰 Tin **xấu / CRITICAL** – nên SL sát")

    reco.append("")                                         # ngắt dòng đẹp

    # ---- Trailing-SL (ATR) ---------------------------------------------------
    try:
        import ta
        atr = ta.volatility.average_true_range(
                ind['df']['high'], ind['df']['low'], ind['df']['close'],
                window=14).iloc[-2]
        trail = max(fib, price - 1.5*atr)
        reco.append(f"🔄 Trail SL ≈ {round_num(trail,4)}")
    except Exception:
        pass

    # ---- Chiến lược theo PnL & Level ----------------------------------------
    reco.append("✅ **Chiến lược:**")

    if lvl == "HOLD":
        reco.append("💎 Giữ vị thế, theo dõi volume & news – chưa nên mua thêm.")
    elif lvl == "WEAK_BUY":
        reco.append(f"🟢 Có thể *mua thăm dò* (<25%) nếu giá > {round_num(sl)}.")
    elif lvl == "BUY":
        reco.append(f"🛒 *Mua từng phần* khi retest {round_num(fib)} – TP {tp}.")
    elif lvl == "STRONG_BUY":
        reco.append("🚀 *Mua mạnh/Scale-in* – xu hướng đồng thuận đa khung.")
        reco.append(f"Đặt TP1 {tp}, TP2 {round_num(tp*1.06)} – SL động trên Fib.")

    # ---- Điều chỉnh theo lợi nhuận thực tế ----------------------------------
    if pnl > 5:
        reco.append(f"👉 Đang lời {pnl}% – cân nhắc *chốt 50%*, kéo SL lên {round_num(fib)}.")
    elif -3 < pnl <= 0:
        reco.append(f"⏳ Lỗ nhẹ {pnl}% – theo dõi sát, thủng {round_num(sl)} thì cắt.")
    elif pnl <= -3:
        reco.append("❌ Lỗ sâu – giảm vị thế ngay, *đừng* bình quân giá!")

    if extra_tf:
        reco.append("")  # dòng trống
        reco.append("📊 Nhận định đa khung:")
        reco.append(analyze_multi_timeframe(extra_tf))

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
    return now in ["08:02", "20:02"]
    #return True

def rr_ratio(entry, tp, sl):
    try:
        return round(abs(tp-entry) / abs(entry-sl), 2)
    except ZeroDivisionError:
        return "-"

# ========= HELPER: gói & gửi tin chi tiết ==============
def build_and_send_alert(*, alert_tag, symbol, interval, trade_id,
                         in_time, held, real_entry, coin_amount,
                         current_value, amount, pnl_usd, pnl,
                         merged_summary, ind_text, advice_text,
                         extra_tf, ICON, level_from_score,
                         news_summary, send_discord_alert):
    """Dựng chuỗi Discord và bắn webhook – giữ file chính gọn hơn."""
    msg = f"""{alert_tag} Đánh giá lệnh: {symbol} ({interval})
📌 ID: {trade_id} {symbol} {interval}
📆 In time: {in_time} | Đã giữ: {held} h | RealEntry: {real_entry}
💰 PnL: {pnl_usd} USD ({pnl}%) | 📦 {coin_amount} | 💵 {current_value}/{amount}

📊 Phân tích kỹ thuật chi tiết:
{ind_text}

{merged_summary}

🗞️ Tin tức:
{news_summary}"""

    if extra_tf:
        tf_lines = []
        for tf, tfdata in sorted(extra_tf.items(), key=lambda kv: -kv[1]["score"]):
            lvl = level_from_score(tfdata["score"])
            tf_lines.append(
                f"{ICON[lvl]} {tf}: Trend: {tfdata['trend']:<9} | RSI: {tfdata['rsi']}  | CMF: {round(tfdata['cmf'], 3)}  | AI: {tfdata.get('ai_score','-')}% ({tfdata.get('ai_bias','-')})"
            )
        msg += "\n\n📊 Đa khung:\n" + "\n".join(tf_lines)

    msg = msg.rstrip() + "\n\n" + advice_text.strip()

    send_discord_alert(msg)

# ========= HẾT HELPER =================================



def main():
    cooldown_state = load_cooldown_state()
    now = datetime.now()
    advisor_file = os.path.join(ADVISOR_DIR, f"{now.strftime('%Y-%m-%d')}.json")
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
    level_counter  = Counter()     # đếm số lệnh / cấp
    pnl_bucket     = Counter()     # cộng PnL USD / cấp
    watch_list     = []            # AI-Tech conflict

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
        indicators["df"] = df
        indicators["trade_plan"] = plan
        indicators["price"] = price_now

        # 1) Lấy thêm chỉ báo đa khung
        extra_tf = {}
        for tf in ["1h", "4h", "1d"]:
            if tf != interval:
                try:
                    df_tf = get_price_data(symbol, tf)
                    ind_tf = calculate_indicators(df_tf, symbol, tf)

                    ai_path = os.path.join(AI_DIR, f"{symbol}_{tf}.json")
                    ml_tf = {}
                    if os.path.exists(ai_path):
                        try:
                            with open(ai_path, "r") as f:
                                ml_tf = json.load(f)
                        except:
                            pass

                    extra_tf[tf] = {
                        "rsi":   round_num(ind_tf["rsi_14"]),
                        "macd":  ind_tf["macd_cross"],
                        "trend": ind_tf["trend"],
                        "score": calc_score(ind_tf),
                        "volume": ind_tf["volume"],
                        "vol_ma": ind_tf["vol_ma20"],
                        "cmf": ind_tf["cmf"],
                        "ai_score": ml_tf.get("score", None),
                        "ai_level": ml_tf.get("level", None),
                        "ai_bias": "bullish" if ml_tf.get("score", 0) >= 60 else "bearish" if ml_tf.get("score", 0) <= 40 else "neutral"
                    }
                except Exception as e:
                    log_to_txt(f"[ERROR] Lỗi xử lý đa khung {tf} của {symbol}: {e}")

        # 2) Bonus 1 điểm nếu ≥2 khung cùng trend
        same_dir = sum(
            1 for tf_data in extra_tf.values()
            if tf_data["trend"] == indicators["trend"]
        )
        indicators["trend_alignment_bonus"] = 1 if same_dir >= 2 else 0

        # 3) Tính lại score sau khi đã có bonus
        score = calc_score(indicators)

        # 4) Tạo text / gợi ý / news sau khi đã có score mới
        news_summary = load_news_for_symbol(symbol)

        ml_score = 0
        ml_level = ""
        ml_summary = ""

        ai_path = os.path.join(AI_DIR, f"{symbol}_{interval}.json")
        if os.path.exists(ai_path):
            try:
                with open(ai_path, "r") as f:
                    ml = json.load(f)
                    ml_score      = ml.get("score", 0)
                    ml_level_raw  = ml.get("level", "")
                    ml_level      = ml_level_raw.replace("_", " ")
                    ml_summary    = f"{ml.get('level_icon', '')} – {ml.get('summary', '')}"
            except Exception as e:
                print(f"[ERROR] Không đọc được AI JSON: {ai_path} → {e}")
        else:
            print(f"[DEBUG] Không tìm thấy AI JSON: {symbol}_{interval}")

        ai_bias     = "bullish" if ml_score >= 60 else "bearish" if ml_score <= 40 else "neutral"
        news_factor = -1 if "critical" in news_summary.lower() else 1 if "tin tức" in news_summary.lower() else 0

        ind_text    = generate_indicator_text(indicators)
        advice_text = generate_final_strategy(score, ml_score, news_factor, pnl, indicators, extra_tf)



        tech  = score / 10
        ai    = ml_score / 100
        news  = (news_factor + 1) / 2
        pnl_norm  = max(-10, min(10, pnl))
        pnl_score = (pnl_norm + 10) / 20
        final_rating = round(0.45*tech + 0.35*ai + 0.1*pnl_score + 0.1*news, 3)

        prev = advisor_map.get(trade_id)
        should_send = False
        send_reason = ""

        if not prev:
            should_send = True
            send_reason = "Lệnh mới"
        elif abs(prev.get("score", 0) - score) >= 2:
            should_send = True
            send_reason = f"Score đổi: {prev.get('score')} → {score}"
        elif prev.get("strategy") != advice_text:
            should_send = True
            send_reason = "Chiến lược đổi"
        elif abs(prev.get("ml_score", 0) - ml_score) >= 5:
            should_send = True
            send_reason = f"AI score đổi: {prev.get('ml_score', 0)} → {ml_score}"
        elif prev.get("ml_level", "") != ml_level:
            should_send = True
            send_reason = f"AI level đổi: {prev.get('ml_level')} → {ml_level}"


        if not should_send:
            send_reason = send_reason or "Không rõ lý do"
            log_to_txt(f"[SKIP] Không gửi lại {symbol} ({interval}) vì không có thay đổi đáng kể. Lý do: {send_reason}")

        log_to_txt(f"[{now.strftime('%H:%M:%S')}] Score: {score} | {'SEND' if should_send else 'SKIP'} | {symbol} {interval} | Lý do: {send_reason}")


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
            "status": "open",
            "ml_score": ml_score,
            "ml_level": ml_level,
        }

        coin_amount = round(amount / real_entry, 2)
        current_value = round(amount + pnl_usd, 2)



        if should_send:
            # ---- chuẩn hóa & final_rating -----------------
            # ---- map ra level / icon ----------------------
            if   final_rating < 0.05: alert_tag, level_key = "🆘 [Panic Sell]",  "PANIC_SELL"
            elif final_rating < 0.15: alert_tag, level_key = "🔻 [Sell]",        "SELL"
            elif final_rating < 0.30: alert_tag, level_key = "⛔ [Avoid]",       "AVOID"
            elif final_rating < 0.45: alert_tag, level_key = "💎 [Hold]",        "HOLD"
            elif final_rating < 0.60: alert_tag, level_key = "🟢 [Weak Buy]",    "WEAK_BUY"
            elif final_rating < 0.80: alert_tag, level_key = "🛒 [Buy]",         "BUY"
            else:                         alert_tag, level_key = "🚀 [Strong Buy]","STRONG_BUY"

            # ---- CHECK COOLDOWN ---------------------------
            symbol_key    = f"{symbol}_{interval}"
            last_sent_str = cooldown_state.get(symbol_key, {}).get(level_key)
            cooldown_skip = bool(last_sent_str and not is_cooldown_passed(last_sent_str, level_key, now))

            # Luôn cộng dồn thống kê cho báo cáo tổng quan
            level_counter[level_key] += 1
            pnl_bucket[level_key]    += pnl_usd

            if not cooldown_skip:
                # ---- update cooldown ----------------------
                cooldown_state.setdefault(symbol_key, {})[level_key] = now.strftime("%Y-%m-%d %H:%M:%S")
            else:
                log_to_txt(f"[COOLDOWN] Skip alert for {symbol} ({interval}) – {level_key}")

            # Mâu thuẫn AI-Tech?
            if abs(tech - ai) > 0.4:
                watch_list.append(f"{symbol}/{interval}")

            # ---- refresh advice ---------------------------
            indicators["level_key"] = level_key
            advice_text = generate_final_strategy(score, ml_score, news_factor, pnl, indicators, extra_tf)


            # ---- gộp summary ngắn -------------------------
            merged_summary = f"""📌 Tổng hợp đánh giá: {symbol} ({interval}) | PnL: {pnl}% | Final: {round(final_rating*100,2)}%
🔹 Kỹ thuật: Score {score}/10 → {'Thị trường không rõ ràng, cần quan sát thêm' if score<=3 else ('Tích cực' if score>=7 else 'Trung tính')}
🔹 AI: {ml_summary if ml_summary else '– Không có dữ liệu AI'}
🔹 Tin tức: {news_summary.splitlines()[0] if news_summary else '– Trung lập'}"""

            # ---- gửi tin qua helper -----------------------
            if not cooldown_skip:
                build_and_send_alert(
                    alert_tag=alert_tag, symbol=symbol, interval=interval,
                    trade_id=trade_id, in_time=in_time, held=held,
                    real_entry=real_entry, coin_amount=coin_amount,
                    current_value=current_value, amount=amount,
                    pnl_usd=pnl_usd, pnl=pnl,
                    merged_summary=merged_summary,
                    ind_text=ind_text, advice_text=advice_text,
                     news_summary=news_summary,
                    extra_tf=extra_tf, ICON=ICON,
                    level_from_score=level_from_score,
                    send_discord_alert=send_discord_alert
                )


        advisor_map[trade_id] = new_entry

        if is_overview_time():
            in_dt = datetime.strptime(in_time, "%Y-%m-%d %H:%M:%S")
            in_hour = in_dt.strftime("%H:%M")
            in_date = in_dt.strftime("%Y-%m-%d")
            score_icon = ICON.get(indicators.get("level_key", ""), "⬜")

            line0 = f"📌 ID: {trade_id} {symbol} {interval}"
            line1 = f"🔹 {symbol} {interval} | 🎯 {real_entry} | 💰 {pnl}% | 📦 {coin_amount} | 💵 {current_value}/{amount} | 🧠 {score} {score_icon}"
            line2 = f"🕒 In: {in_hour} | Giữ: {held}h | Vào: {in_date}"
            line3 = f"🎯 Entry: {real_entry} | 🎯 TP: {plan['tp']} | 🛡 SL: {plan['sl']}"
            rr = rr_ratio(real_entry, plan['tp'], plan['sl'])
            line3 += f" | ℹ️ R/R: {rr}"
            line4 = f"🟡 Giá hiện tại: {price_now}"
            line5 = f"🧠 Score kỹ thuật: {score}/10"
            if ml_score:
                line5 += f" | 🤖 AI: {ml_score}% ({ml_level}) | 🏁 Final: {round(final_rating*100)}%"

            overview_lines.append("\n".join([line0, line1, line2, line3, line4, line5]))

    if is_overview_time() and overview_lines:
        total_start = round(sum(t["amount"] for t in advisor_map.values()
                                if t.get("status")=="open"), 2)
        total_now   = round(sum(t["amount"]+t["pnl_usd"] for t in advisor_map.values()
                                if t.get("status")=="open"), 2)
        total_count = len(overview_lines)

        # ----- biến Counter ra chuỗi gọn -----
        lv_counts = ", ".join(f"{ICON[k]}{level_counter[k]}"
                              for k in LEVEL_COOLDOWN_MINUTES if k in level_counter)
        pnl_lines = ", ".join(f"{ICON[k]}{round(pnl_bucket[k],1)}$"
                              for k in LEVEL_COOLDOWN_MINUTES if k in pnl_bucket)

        header  = f"📊 **Tổng quan danh mục {now:%d-%m %H:%M}**"
        header += f"\nLệnh: {total_count} | PnL: {total_now}/{total_start}$"
        header += f"\nPhân bổ cấp: {lv_counts}"
        header += f"\nPnL theo cấp: {pnl_lines}"
        if watch_list:
            header += "\n⚠️ *Mâu thuẫn AI-Tech*: " + ", ".join(watch_list[:3])

        send_discord_alert(header + "\n\n" + "\n".join(overview_lines))


    log_file = os.path.join(LOG_DIR, f"{now.strftime('%Y-%m-%d')}.txt")
    sent_count = 0
    skip_count = 0
    if os.path.exists(log_file):
        with open(log_file, "r") as f:
            for line in f:
                if "SEND" in line:
                    sent_count += 1
                elif "SKIP" in line or "COOLDOWN" in line:
                    skip_count += 1

    if sent_count:
        print(f"📤 Sent {sent_count} alerts | ⏳ Skipped {skip_count}")
    elif skip_count:
        print(f"📭 No alerts sent – all {skip_count} skipped")
    else:
        print("📭 No trades processed or no logs found.")


    save_daily_log(advisor_file, list(advisor_map.values()))
    save_cooldown_state(cooldown_state)

if __name__ == "__main__":
    main()
