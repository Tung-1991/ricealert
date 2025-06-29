import time
import os
import json
import joblib
import requests
import pandas as pd
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from indicator import get_price_data, calculate_indicators

# ===== LOAD ENV =====
load_dotenv()
SYMBOLS = os.getenv("SYMBOLS", "LINKUSDT").split(",")
INTERVALS = os.getenv("INTERVALS", "1h,4h,1d").split(",")
WEBHOOK_URL = os.getenv("DISCORD_AI_WEBHOOK")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
LOG_DIR = os.path.join(BASE_DIR, "ai_logs")
COOLDOWN_FILE = os.path.join(BASE_DIR, "cooldown_tracker_ml.json")  # Tách riêng file cooldown cho ML
os.makedirs(LOG_DIR, exist_ok=True)

LEVEL_COOLDOWN = {
    "PANIC_SELL": 3,
    "SELL": 4,
    "AVOID": 5,
    "HOLD": 6,
    "WEAK_BUY": 5,
    "BUY": 4,
    "STRONG_BUY": 3
}

# ===== LOAD & SAVE COOLDOWN =====
def load_cooldown():
    if os.path.exists(COOLDOWN_FILE):
        with open(COOLDOWN_FILE) as f:
            return json.load(f)
    return {}

def save_cooldown(data):
    with open(COOLDOWN_FILE, "w") as f:
        json.dump(data, f, indent=2)

# ===== ALERT TO DISCORD =====
def send_discord_alert(msg: str):
    if not WEBHOOK_URL:
        print("[ERROR] DISCORD_AI_WEBHOOK not set in .env")
        return
    try:
        print("[DISCORD] Sending alert:")
        print(msg)
        requests.post(WEBHOOK_URL, json={"content": msg}, timeout=10)
    except Exception as e:
        print(f"[ERROR] Discord alert failed: {e}")

# ===== LOAD MODEL & META =====
def load_model_and_meta(symbol, interval):
    try:
        clf_model = joblib.load(os.path.join(DATA_DIR, f"model_{symbol}_clf_{interval}.pkl"))
        reg_model = joblib.load(os.path.join(DATA_DIR, f"model_{symbol}_reg_{interval}.pkl"))
        with open(os.path.join(DATA_DIR, f"meta_{symbol}_{interval}.json")) as f:
            meta = json.load(f)
        return clf_model, reg_model, meta
    except Exception as e:
        print(f"[ERROR] Loading model/meta for {symbol} [{interval}]: {e}")
        return None, None, None

# ===== CLASSIFY LEVEL =====
def classify_suggestion(score, pct):
    if score >= 85 and pct > 4:
        return "STRONG_BUY"
    elif score >= 75 and pct > 2:
        return "BUY"
    elif score >= 60 and pct > 0.5:
        return "WEAK_BUY"
    elif score < 30 and pct < -4:
        return "PANIC_SELL"
    elif score < 40 and pct < -1:
        return "SELL"
    elif score < 50 and -1 < pct < 0.5:
        return "AVOID"
    else:
        return "HOLD"

LEVEL_ICONS = {
    "STRONG_BUY": "🔥 STRONG BUY",
    "BUY": "✅ BUY",
    "WEAK_BUY": "🟡 WEAK BUY",
    "HOLD": "🔍 HOLD",
    "AVOID": "🚧 AVOID",
    "SELL": "❌ SELL",
    "PANIC_SELL": "🚨 PANIC SELL"
}

# ===== ANALYZE PER SYMBOL+INTERVAL =====
def analyze_symbol(symbol, interval, cooldown_data):
    clf_model, reg_model, meta = load_model_and_meta(symbol, interval)
    if not clf_model or not reg_model or not meta:
        return None
    try:
        df = get_price_data(symbol, interval, limit=100)
        indi = calculate_indicators(df, symbol, interval)
        X = pd.DataFrame([{k: indi[k] for k in meta["features"] if k in indi}])
        prob = clf_model.predict_proba(X)[0][1]
        pct = reg_model.predict(X)[0] * 100

        price = indi.get("price")
        trade_plan = indi.get("trade_plan", {})
        entry = trade_plan.get("entry", price)
        tp = trade_plan.get("tp", price * (1 + pct / 100))
        sl = trade_plan.get("sl", price * 0.97)

        level = classify_suggestion(prob * 100, pct)
        level_icon = LEVEL_ICONS.get(level, level)
        now = datetime.now(timezone.utc)
        cooldown_key = f"{symbol}_{interval}_{level}"
        cooldown_hours = LEVEL_COOLDOWN.get(level, 6)

        last_time_str = cooldown_data.get(cooldown_key)
        if last_time_str:
            last_time = datetime.fromisoformat(last_time_str)
            if now - last_time < timedelta(hours=cooldown_hours):
                print(f"[COOLDOWN] Skipping {cooldown_key}")
                return None

        result = {
            "symbol": symbol,
            "interval": interval,
            "score": round(prob * 100, 2),
            "pct": round(pct, 2),
            "price": round(price, 8),
            "entry": round(entry, 8),
            "tp": round(tp, 8),
            "sl": round(sl, 8),
            "level": level,
            "level_icon": level_icon,
            "timestamp": now.isoformat(),
            "summary": (
                f"ML dự đoán: {pct:.2f}% ({'tăng' if pct > 0 else 'giảm'}), xác suất: {prob*100:.2f}% trong khung {interval}.\n"
                f"Giá hiện tại {price:.4f}, Entry: {entry:.4f}, TP: {tp:.4f}, SL: {sl:.4f}."
            )
        }

        json_path = os.path.join(LOG_DIR, f"{symbol}_{interval}.json")
        with open(json_path, "w") as f:
            json.dump(result, f, indent=2)

        cooldown_data[cooldown_key] = now.isoformat()
        return result
    except Exception as e:
        print(f"[ERROR] analyze {symbol} {interval}: {e}")
        return None

# ===== MAIN ENTRY =====
def generate_report():
    cooldown_data = load_cooldown()
    for sym in SYMBOLS:
        report_lines = [f"\n📊 **AI ML Dự báo cho {sym}**"]
        updated = False
        for iv in INTERVALS:
            result = analyze_symbol(sym, iv, cooldown_data)
            if result:
                updated = True
                line = (
                    f"➡️ {result['symbol']} [{result['interval']}] {result['level_icon']}\n"
                    f"🧠 Score: {result['score']}%\n"
                    f"📊 Dự đoán: {result['pct']}%\n"
                    f"💰 Giá: {result['price']:.8f} | Entry: {result['entry']:.8f}\n"
                    f"🎯 TP: {result['tp']:.8f} | 🛡️ SL: {result['sl']:.8f}\n"
                    f"📝 {result['summary']}\n"
                )
                report_lines.append(line)

        if updated:
            full_msg = "\n".join(report_lines)
            print(full_msg)
            if len(full_msg) <= 1900:
                send_discord_alert(full_msg)
                time.sleep(3)
            else:
                chunks = ["\n".join(report_lines[i:i+5]) for i in range(0, len(report_lines), 5)]
                for chunk in chunks:
                    send_discord_alert(chunk)
                    time.sleep(3)
    save_cooldown(cooldown_data)

if __name__ == "__main__":
    generate_report()
