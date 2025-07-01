import os
import json
import time
import joblib
import requests
import pandas as pd
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from indicator import get_price_data, calculate_indicators

# ---------- LOAD ENV ----------
load_dotenv()
SYMBOLS        = os.getenv("SYMBOLS", "LINKUSDT").split(",")
INTERVALS      = os.getenv("INTERVALS", "1h,4h,1d").split(",")
WEBHOOK_URL    = os.getenv("DISCORD_AI_WEBHOOK")
ERROR_WEBHOOK  = os.getenv("DISCORD_ERROR_WEBHOOK", "")

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
DATA_DIR   = os.path.join(BASE_DIR, "data")
LOG_DIR    = os.path.join(BASE_DIR, "ai_logs")
ERROR_LOG  = os.path.join(LOG_DIR, "error_ml.log")
COOLDOWN_FILE = os.path.join(BASE_DIR, "cooldown_tracker_ml.json")

os.makedirs(LOG_DIR, exist_ok=True)

# ---------- CONSTANTS ----------
LEVEL_COOLDOWN = {
    "PANIC_SELL": 3,
    "SELL": 4,
    "AVOID": 5,
    "HOLD": 6,
    "WEAK_BUY": 5,
    "BUY": 4,
    "STRONG_BUY": 3,
}
LEVEL_ICONS = {
    "STRONG_BUY": "🔥 STRONG BUY",
    "BUY": "✅ BUY",
    "WEAK_BUY": "🟡 WEAK BUY",
    "HOLD": "🔍 HOLD",
    "AVOID": "🚧 AVOID",
    "SELL": "❌ SELL",
    "PANIC_SELL": "🚨 PANIC SELL",
}

# ---------- UTIL ----------

def is_overview_time() -> bool:
    """Return True if current VN time is 08:00 or 20:00."""
    return datetime.now(ZoneInfo("Asia/Bangkok")).strftime("%H:%M") in {"08:00", "20:00"}


def send_discord_alert(msg: str) -> None:
    if not WEBHOOK_URL:
        print("[ERROR] DISCORD_AI_WEBHOOK not set")
        return
    try:
        print("[DISCORD] ⇢\n" + msg)
        requests.post(WEBHOOK_URL, json={"content": msg}, timeout=10)
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] Discord alert failed: {exc}")


def send_error_alert(msg: str) -> None:
    ts = datetime.utcnow().isoformat()
    with open(ERROR_LOG, "a") as f:
        f.write(f"{ts} | {msg}\n")
    if ERROR_WEBHOOK:
        try:
            requests.post(ERROR_WEBHOOK, json={"content": f"⚠️ {msg}"}, timeout=10)
        except Exception:
            pass  # tránh vòng lặp lỗi

# ---------- COOLDOWN ----------

def load_cooldown() -> dict:
    if not os.path.exists(COOLDOWN_FILE):
        return {}
    with open(COOLDOWN_FILE, "r") as f:
        data = json.load(f)
    now = datetime.now(timezone.utc)
    return {
        k: v
        for k, v in data.items()
        if now - datetime.fromisoformat(v) < timedelta(days=30)
    }


def save_cooldown(data: dict) -> None:
    with open(COOLDOWN_FILE, "w") as f:
        json.dump(data, f, indent=2)

# ---------- MODEL ----------

def load_model_and_meta(symbol: str, interval: str):
    try:
        clf = joblib.load(os.path.join(DATA_DIR, f"model_{symbol}_clf_{interval}.pkl"))
        reg = joblib.load(os.path.join(DATA_DIR, f"model_{symbol}_reg_{interval}.pkl"))
        with open(os.path.join(DATA_DIR, f"meta_{symbol}_{interval}.json")) as f:
            meta = json.load(f)
        return clf, reg, meta
    except Exception as exc:  # noqa: BLE001
        send_error_alert(f"Load model/meta {symbol} {interval}: {exc}")
        return None, None, None

# ---------- LEVEL ----------

def classify_suggestion(score: float, pct: float) -> str:
    if score >= 85 and pct > 4:
        return "STRONG_BUY"
    if score >= 75 and pct > 2:
        return "BUY"
    if score >= 60 and pct > 0.5:
        return "WEAK_BUY"
    if score < 30 and pct < -4:
        return "PANIC_SELL"
    if score < 40 and pct < -1:
        return "SELL"
    if score < 50 and -1 < pct < 0.5:
        return "AVOID"
    return "HOLD"

# ---------- ANALYZE ----------

def analyze_symbol(symbol: str, interval: str, cooldown: dict, *, force: bool = False):
    """Return analysis dict or None. When *force* is True, ignore cooldown."""
    clf, reg, meta = load_model_and_meta(symbol, interval)
    if not clf or not reg or not meta:
        return None
    try:
        df = get_price_data(symbol, interval, limit=100)
        indi = calculate_indicators(df, symbol, interval)

        X = pd.DataFrame([
            {f: indi.get(f, 0.0) for f in meta["features"]}
        ]).fillna(0.0)

        prob = float(clf.predict_proba(X)[0][1])
        pct  = float(reg.predict(X)[0]) * 100

        prob_cut = meta.get("threshold", 0.6)
        level = classify_suggestion(prob * 100, pct)
        if prob < prob_cut and level.startswith(("BUY", "STRONG_BUY", "WEAK_BUY")):
            level = "HOLD"

        price = indi.get("price", 0)
        plan  = indi.get("trade_plan", {})
        entry = plan.get("entry", price)
        tp    = plan.get("tp", price * (1 + pct / 100))
        sl    = plan.get("sl", price * 0.97)

        now = datetime.now(timezone.utc)
        key = f"{symbol}_{interval}_{level}"
        if not force:
            last = cooldown.get(key)
            if last and now - datetime.fromisoformat(last) < timedelta(hours=LEVEL_COOLDOWN.get(level, 6)):
                print(f"[COOLDOWN] Skip {key}")
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
            "level_icon": LEVEL_ICONS.get(level, level),
            "timestamp": now.isoformat(),
            "summary": (
                f"ML dự đoán: {pct:+.2f}% ({'tăng' if pct > 0 else 'giảm'}), χsuất: {prob*100:.2f}% khung {interval}.\n"
                f"Giá {price:.4f}, Entry {entry:.4f}, TP {tp:.4f}, SL {sl:.4f}."
            ),
        }

        with open(os.path.join(LOG_DIR, f"{symbol}_{interval}.json"), "w") as f:
            json.dump(result, f, indent=2)

        if not force:
            cooldown[key] = now.isoformat()

        return result

    except Exception as exc:  # noqa: BLE001
        send_error_alert(f"Analyze {symbol} {interval}: {exc}")
        return None

# ---------- MAIN ----------

def generate_report() -> None:
    overview_lines: list[str] = []
    cooldown = load_cooldown()

    force_daily = is_overview_time()       # True at 08:00 / 20:00 VN

    for sym in SYMBOLS:
        lines: list[str] = [f"\n📊 **AI ML Dự báo cho {sym}**"]
        updated = False

        for iv in INTERVALS:
            res = analyze_symbol(sym, iv, cooldown, force=force_daily)
            if not res:
                continue
            updated = True

            overview_lines.append(
                f"➡️ {res['symbol']} [{res['interval']}] {res['level_icon']} | "
                f"🧠 {res['score']}% | 📈 {res['pct']:+.2f}% | 💰 {res['price']:.8f} | "
                f"🎯 {res['entry']:.8f}/{res['tp']:.8f}/{res['sl']:.8f}"
            )

            lines.append(
                f"➡️ {res['symbol']} [{res['interval']}] {res['level_icon']}\n"
                f"🧠 Score: {res['score']}%\n"
                f"📊 Dự đoán: {res['pct']}%\n"
                f"💰 Giá: {res['price']:.8f} | Entry: {res['entry']:.8f}\n"
                f"🎯 TP: {res['tp']:.8f} | 🛡️ SL: {res['sl']:.8f}\n"
                f"📝 {res['summary']}\n"
            )

        # Gửi chi tiết chỉ ngoài 08h/20h
        if updated and not force_daily:
            full = "\n".join(lines)
            if len(full) <= 1900:
                send_discord_alert(full)
                time.sleep(3)
            else:
                for i in range(0, len(lines), 5):
                    send_discord_alert("\n".join(lines[i : i + 5]))
                    time.sleep(3)

    # Gửi tổng hợp vào 08h / 20h
    if force_daily and overview_lines:
        header = f"🔥 **Tổng hợp AI ML {datetime.now(ZoneInfo('Asia/Bangkok')).strftime('%H:%M')}**"
        send_discord_alert(header + "\n" + "\n".join(overview_lines))

    save_cooldown(cooldown)


if __name__ == "__main__":
    generate_report()
