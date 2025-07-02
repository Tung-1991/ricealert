# -*- coding: utf-8 -*-
"""
ml_report.py - AI Trading Signal Assistant
Version: 4.2 (The Best of Both Worlds)
Date: 2025-07-03
Description: This definitive version combines the best of all previous iterations.
             - Delivers immediate, detailed, consolidated signal alerts per symbol.
             - Restores the periodic overview summary (08:01, 20:01) with a new,
               clean, and highly scannable format.
             - All logic is refined for maximum clarity and performance.
"""
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
from typing import List

# ==============================================================================
# SETUP & CONFIG
# ==============================================================================
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

COOLDOWN_HOURS = 4
RISK_REWARD_MAP = {
    "STRONG_BUY": 1 / 3, "BUY": 1 / 2.5, "WEAK_BUY": 1 / 2,
    "SELL": 1 / 2.5, "PANIC_SELL": 1 / 3,
    "HOLD": 1 / 4, "AVOID": 1 / 5,
}
LEVEL_ICONS = {
    "STRONG_BUY": "🔥", "BUY": "✅", "WEAK_BUY": "🟡",
    "HOLD": "🔍", "AVOID": "🚧",
    "SELL": "❌", "PANIC_SELL": "🚨",
}

# ==============================================================================
# UTILITY & HELPER FUNCTIONS
# ==============================================================================
def send_discord_alert(msg: str) -> None:
    if not WEBHOOK_URL:
        print("[ERROR] DISCORD_AI_WEBHOOK not set")
        return
    try:
        requests.post(WEBHOOK_URL, json={"content": msg}, timeout=10).raise_for_status()
    except Exception as exc:
        print(f"[ERROR] Discord alert failed: {exc}")

def send_error_alert(msg: str) -> None:
    ts = datetime.now(timezone.utc).isoformat()
    with open(ERROR_LOG, "a") as f: f.write(f"{ts} | {msg}\n")
    if ERROR_WEBHOOK:
        try: requests.post(ERROR_WEBHOOK, json={"content": f"⚠️ ML_REPORT ERROR: {msg}"}, timeout=10)
        except Exception: pass

def load_cooldown() -> dict:
    if not os.path.exists(COOLDOWN_FILE): return {}
    with open(COOLDOWN_FILE, "r") as f: data = json.load(f)
    now = datetime.now(timezone.utc)
    return {k: v for k, v in data.items() if now - datetime.fromisoformat(v) < timedelta(days=3)}

def save_cooldown(data: dict) -> None:
    with open(COOLDOWN_FILE, "w") as f: json.dump(data, f, indent=2)

def load_model_and_meta(symbol: str, interval: str):
    try:
        clf = joblib.load(os.path.join(DATA_DIR, f"model_{symbol}_clf_{interval}.pkl"))
        reg = joblib.load(os.path.join(DATA_DIR, f"model_{symbol}_reg_{interval}.pkl"))
        with open(os.path.join(DATA_DIR, f"meta_{symbol}_{interval}.json")) as f: meta = json.load(f)
        return clf, reg, meta
    except Exception as exc:
        send_error_alert(f"Failed to load model/meta for {symbol} {interval}: {exc}")
        return None, None, None
        
def is_overview_time() -> bool:
    return datetime.now(ZoneInfo("Asia/Bangkok")).strftime("%H:%M") in {"08:01", "20:01"}

# ==============================================================================
# NEW CORE LOGIC
# ==============================================================================

def classify_level(score: float, pct: float) -> str:
    # Score is the probability of class 2 (BUY)
    if score > 80: return "STRONG_BUY"
    if score < 20: return "PANIC_SELL"
    if score > 65: return "BUY"
    if score < 35: return "SELL"
    if score > 55: return "WEAK_BUY"
    if 45 <= score <= 55 and abs(pct) < 0.5: return "HOLD"
    return "AVOID"

def analyze_single_interval(symbol: str, interval: str) -> dict or None:
    clf, reg, meta = load_model_and_meta(symbol, interval)
    if not clf or not reg or not meta: return None

    try:
        df = get_price_data(symbol, interval, limit=200)
        features = calculate_indicators(df, symbol, interval).iloc[-1].to_dict()
        
        feature_names = meta["features"]
        X = pd.DataFrame([features])[feature_names].fillna(0.0)
        
        probabilities = clf.predict_proba(X)[0]
        prob_buy = probabilities[2] * 100
        
        predicted_norm_change = float(reg.predict(X)[0])
        atr = features.get('atr', 0.0)
        price = features.get('close', 0)
        if price == 0: return None # Avoid division by zero
        pct = predicted_norm_change * atr * 100 / price

        score_for_classification = prob_buy
        level = classify_level(score_for_classification, pct)
        
        direction = 1 if pct >= 0 else -1
        tp_pct = abs(pct) if abs(pct) > 0.1 else 0.5 # Ensure a minimum target
        risk_ratio = RISK_REWARD_MAP.get(level, 1/3)
        sl_pct = tp_pct * risk_ratio
        
        tp = price * (1 + direction * (tp_pct / 100))
        sl = price * (1 - direction * (sl_pct / 100))

        return {
            "symbol": symbol, "interval": interval, "score": round(prob_buy, 2),
            "pct": round(pct, 2), "price": price, "tp": tp, "sl": sl, "level": level,
        }
    except Exception as exc:
        send_error_alert(f"Analysis failed for {symbol} {interval}: {exc}")
        import traceback
        send_error_alert(traceback.format_exc())
        return None

def generate_report_for_symbol(symbol: str, all_results: List[dict], cooldown: dict) -> None:
    if not all_results: return
    
    strongest_signal = sorted(all_results, key=lambda x: (x['level'] not in ["STRONG_BUY", "PANIC_SELL"], abs(50 - x['score'])))[0]
    
    cooldown_key = f"{symbol}"
    last_sent_str = cooldown.get(cooldown_key)
    if last_sent_str and datetime.now(timezone.utc) - datetime.fromisoformat(last_sent_str) < timedelta(hours=COOLDOWN_HOURS):
        print(f"[COOLDOWN] Skip report for {symbol}")
        return
        
    header = f"{LEVEL_ICONS.get(strongest_signal['level'])} **AI Signal: {strongest_signal['level'].replace('_', ' ')} cho {symbol}**"
    summary_table = ["📊 **Tóm tắt các khung thời gian:**"]
    for res in sorted(all_results, key=lambda x: INTERVALS.index(x['interval'])):
        icon = LEVEL_ICONS.get(res['level'], '❓')
        summary_table.append(f"►  **{res['interval']}:** {icon} {res['level'].replace('_', ' '):<10} | 🧠 Score: {res['score']:.1f}% | 📈 Dự đoán: {res['pct']:+.2f}%")

    bullish_signals = sum(1 for r in all_results if r['level'] in ["STRONG_BUY", "BUY", "WEAK_BUY"])
    bearish_signals = sum(1 for r in all_results if r['level'] in ["PANIC_SELL", "SELL"])
    
    strategy_lines = ["🧠 **Chiến lược đề xuất:**"]
    if bullish_signals >= 2:
        strategy_lines.append(f"Tín hiệu MUA có sự đồng thuận cao trên {bullish_signals} khung thời gian. Đây là cơ hội tốt để xem xét mở vị thế MUA.")
    elif bearish_signals >= 2:
        strategy_lines.append(f"Tín hiệu BÁN có sự đồng thuận cao trên {bearish_signals} khung thời gian. Cần thận trọng và xem xét quản lý rủi ro/đóng vị thế MUA.")
    else:
        strategy_lines.append("Các khung thời gian đang có tín hiệu trái chiều hoặc không rõ ràng. Nên đứng ngoài và quan sát thêm.")
    
    strategy_lines.append(f"- **Tín hiệu chính:** Dựa trên khung **{strongest_signal['interval']}** ({strongest_signal['level']}).")
    strategy_lines.append(f"- **Mục tiêu (TP):** ~`{strongest_signal['tp']:.4f}`")
    strategy_lines.append(f"- **Cắt lỗ (SL):** ~`{strongest_signal['sl']:.4f}`")

    details_block = [f"📋 **Chi tiết Dự báo (Khung {strongest_signal['interval']}):**"]
    details_block.append(f"- **Giá hiện tại:** {strongest_signal['price']:.4f}")
    details_block.append(f"- **Xác suất Mua (Score):** {strongest_signal['score']:.2f}%")
    details_block.append(f"- **Dự đoán thay đổi:** {strongest_signal['pct']:.2f}%")

    full_message = "\n\n".join([header, "\n".join(summary_table), "\n".join(strategy_lines), "\n".join(details_block)])

    send_discord_alert(full_message)
    cooldown[cooldown_key] = datetime.now(timezone.utc).isoformat()
    time.sleep(3)

# ==============================================================================
# MAIN
# ==============================================================================
def main():
    cooldown = load_cooldown()
    print(f"Starting analysis at {datetime.now()}...")
    
    all_symbols_results = []
    
    for symbol in SYMBOLS:
        print(f"--- Analyzing {symbol} ---")
        results_for_this_symbol = []
        for iv in INTERVALS:
            result = analyze_single_interval(symbol, iv)
            if result:
                results_for_this_symbol.append(result)
        
        if results_for_this_symbol:
            all_symbols_results.extend(results_for_this_symbol)
            generate_report_for_symbol(symbol, results_for_this_symbol, cooldown)

    # RESTORED: Send periodic overview summary
    if is_overview_time() and all_symbols_results:
        print("--- Generating Overview Summary ---")
        header = f"🔥 **Tổng hợp AI ML {datetime.now(ZoneInfo('Asia/Bangkok')).strftime('%H:%M')}**"
        
        overview_blocks = []
        # Group results by symbol for the overview
        from itertools import groupby
        sorted_results = sorted(all_symbols_results, key=lambda x: x['symbol'])
        for symbol, group in groupby(sorted_results, key=lambda x: x['symbol']):
            block = [f"➡️ **{symbol}**"]
            for res in sorted(list(group), key=lambda x: INTERVALS.index(x['interval'])):
                 icon = LEVEL_ICONS.get(res['level'], '❓')
                 block.append(f"   [{res['interval']}]: {icon} {res['level'].replace('_', ' '):<10} | 🧠 Score: {res['score']:.1f}% | 📈 Dự đoán: {res['pct']:+.2f}%")
            overview_blocks.append("\n".join(block))

        full_message = header + "\n\n" + "\n\n".join(overview_blocks)
        send_discord_alert(full_message)

    save_cooldown(cooldown)
    print("Analysis complete.")

if __name__ == "__main__":
    main()
