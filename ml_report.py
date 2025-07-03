# -*- coding: utf-8 -*-
"""
ml_report.py - AI Trading Signal Assistant (Event-Driven & Integrated)
Version: 5.5 (Adaptive & Refined Cooldown)
Date: 2025-07-03
Description: This version features an adaptive classification logic that uses
             different thresholds for each timeframe (1h, 4h, 1d). It also reverts
             to a universal, consistent cooldown mechanism for all signal changes
             to control alert frequency effectively.
"""
import os
import json
import time
import joblib
import requests
import pandas as pd
import numpy as np
import ta
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from typing import List, Dict
from itertools import groupby

# ==============================================================================
# SETUP & CONFIG
# ==============================================================================
load_dotenv()
SYMBOLS       = os.getenv("SYMBOLS", "BTCUSDT,ETHUSDT,LINKUSDT,SUIUSDT").split(",")
INTERVALS     = os.getenv("INTERVALS", "1h,4h,1d").split(",")
WEBHOOK_URL   = os.getenv("DISCORD_AI_WEBHOOK")
ERROR_WEBHOOK = os.getenv("DISCORD_ERROR_WEBHOOK", "")

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
DATA_DIR   = os.path.join(BASE_DIR, "data")
LOG_DIR    = os.path.join(BASE_DIR, "ai_logs")
STATE_FILE = os.path.join(BASE_DIR, "ml_state.json")

os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

COOLDOWN_BY_LEVEL = {
    "STRONG_BUY": 2 * 3600,   # 🔥 Cho lặp lại sau 2h, đừng bỏ lỡ
    "PANIC_SELL": 2 * 3600,   # 🚨 Để nhắc lại nếu cần
    "BUY": 3 * 3600,          # ❇️ Tín hiệu đẹp nhưng vẫn cần kiểm soát
    "SELL": 3 * 3600,         # ❌ Bán gọn nhưng không lặp lại nhiều

    "WEAK_BUY": 4 * 3600,     # 🟡 Lập lại ít hơn
    "WEAK_SELL": 4 * 3600,    # 🔻 Tránh spam tin bán yếu

    "HOLD": 6 * 3600,         # 🔍 Trạng thái chờ → nên giữ im lặng lâu
    "AVOID": 6 * 3600         # 🚧 Không đáng giao dịch → không cần nói nhiều
}



LEVEL_MAP = {
    "STRONG_BUY": {"icon": "🔥", "name": "STRONG BUY"},
    "BUY":        {"icon": "✅", "name": "BUY"},
    "WEAK_BUY":   {"icon": "🟡", "name": "WEAK BUY"},
    "HOLD":       {"icon": "🔍", "name": "HOLD"},
    "AVOID":      {"icon": "🚧", "name": "AVOID"},
    "WEAK_SELL":  {"icon": "🔻", "name": "WEAK SELL"},
    "SELL":       {"icon": "❌", "name": "SELL"},
    "PANIC_SELL": {"icon": "🚨", "name": "PANIC SELL"},
}


# ==============================================================================
# HÀM TÍNH TOÁN (Đồng bộ với trainer.py)
# ==============================================================================
def get_price_data(symbol: str, interval: str, limit: int) -> pd.DataFrame:
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    try:
        data = requests.get(url, params=params, timeout=10).json()
        if not isinstance(data, list) or not data: return pd.DataFrame()
        df = pd.DataFrame(data, columns=["timestamp", "open", "high", "low", "close", "volume", "close_time", "quote_asset_volume", "number_of_trades", "taker_buy_base_asset_volume", "taker_buy_quote_asset_volume", "ignore"])
        df = df.iloc[:, :6]
        df.columns = ["timestamp", "open", "high", "low", "close", "volume"]
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df.set_index("timestamp", inplace=True)
        for col in df.columns: df[col] = pd.to_numeric(df[col])
        return df
    except Exception as e:
        print(f"[ERROR] Exception in get_price_data for {symbol} {interval}: {e}")
        return pd.DataFrame()

def add_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    close = out["close"]
    for n in [14, 20, 50]:
        out[f'rsi_{n}'] = ta.momentum.rsi(close, window=n)
        out[f'ema_{n}'] = ta.trend.ema_indicator(close, window=n)
        out[f'dist_ema_{n}'] = (close - out[f'ema_{n}']) / (out[f'ema_{n}'] + 1e-9)
    macd = ta.trend.MACD(close)
    out["macd_diff"] = macd.macd_diff()
    out["adx"] = ta.trend.adx(out["high"], out["low"], close)
    out['atr'] = ta.volatility.average_true_range(out["high"], out["low"], close)
    bb = ta.volatility.BollingerBands(close)
    out['bb_width'] = (bb.bollinger_hband() - bb.bollinger_lband()) / (bb.bollinger_mavg() + 1e-9)
    out['cmf'] = ta.volume.chaikin_money_flow(out["high"], out["low"], close, out["volume"])
    out['candle_body'] = abs(close - out['open'])
    out['candle_range'] = out['high'] - out['low']
    out['body_to_range_ratio'] = out['candle_body'] / (out['candle_range'] + 1e-9)
    out['hour'] = out.index.hour
    out['day_of_week'] = out.index.dayofweek
    return out.dropna()

# ==============================================================================
# UTILITY & HELPER FUNCTIONS
# ==============================================================================
def write_json(path: str, data: dict):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

def send_discord_alert(payload: Dict) -> None:
    if not WEBHOOK_URL:
        print("[ERROR] DISCORD_AI_WEBHOOK not set")
        return
    try:
        requests.post(WEBHOOK_URL, json=payload, timeout=10).raise_for_status()
        time.sleep(3)
    except Exception as exc:
        print(f"[ERROR] Discord alert failed: {exc}")

def send_error_alert(msg: str) -> None:
    ts = datetime.now(timezone.utc).isoformat()
    with open(os.path.join(LOG_DIR, "error_ml.log"), "a") as f:
        f.write(f"{ts} | {msg}\n")
    if ERROR_WEBHOOK:
        try:
            requests.post(ERROR_WEBHOOK, json={"content": f"⚠️ ML_REPORT ERROR: {msg}"}, timeout=10)
        except Exception:
            pass

def load_state() -> dict:
    if not os.path.exists(STATE_FILE): return {}
    try:
        with open(STATE_FILE, "r") as f: return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError): return {}

def save_state(data: dict) -> None:
    with open(STATE_FILE, "w") as f:
        json.dump(data, f, indent=2)

def load_model_and_meta(symbol: str, interval: str):
    try:
        clf = joblib.load(os.path.join(DATA_DIR, f"model_{symbol}_clf_{interval}.pkl"))
        reg = joblib.load(os.path.join(DATA_DIR, f"model_{symbol}_reg_{interval}.pkl"))
        with open(os.path.join(DATA_DIR, f"meta_{symbol}_{interval}.json")) as f:
            meta = json.load(f)
        return clf, reg, meta
    except Exception as exc:
        send_error_alert(f"Failed to load model/meta for {symbol} {interval}: {exc}")
        return None, None, None

def should_send_overview(state: dict) -> bool:
    """Kiểm tra xem có nên gửi báo cáo tổng quan AI không."""
    last_ts = state.get("last_overview_timestamp", 0)
    now_dt = datetime.now(ZoneInfo("Asia/Bangkok"))
    target_times = [now_dt.replace(hour=8, minute=1, second=0, microsecond=0),
                    now_dt.replace(hour=20, minute=1, second=0, microsecond=0)]

    for target_dt in target_times:
        if now_dt.timestamp() >= target_dt.timestamp() and last_ts < target_dt.timestamp():
            return True
    return False

# ==============================================================================
# CORE LOGIC & ANALYSIS
# ==============================================================================
def classify_level(prob_buy: float, prob_sell: float, pct: float, interval: str) -> str:
    """
    Logic phân loại thông minh hơn, có khả năng thích ứng với từng khung thời gian.
    """
    # Ngưỡng linh hoạt theo khung thời gian
    # Khung 1h nhạy hơn, pct nhỏ đã là HOLD. Khung 1d cần pct lớn hơn mới coi là HOLD.
    THRESHOLDS = {
        "1h": {"hold_pct": 0.3, "strong_prob": 78},
        "4h": {"hold_pct": 0.6, "strong_prob": 75},
        "1d": {"hold_pct": 1.0, "strong_prob": 70}
    }
    # Lấy ngưỡng cho interval hiện tại, mặc định là 4h nếu không tìm thấy
    thresholds = THRESHOLDS.get(interval, THRESHOLDS["4h"])

    # Tín hiệu có độ chắc chắn cao (sử dụng strong_prob linh hoạt)
    if prob_buy > thresholds['strong_prob']: return "STRONG_BUY"
    if prob_sell > thresholds['strong_prob']: return "PANIC_SELL"

    # Các tín hiệu tiêu chuẩn
    if prob_buy > 65: return "BUY"
    if prob_sell > 65: return "SELL"

    # Tín hiệu sideway rõ ràng (sử dụng hold_pct linh hoạt)
    if abs(prob_buy - prob_sell) < 10 and abs(pct) < thresholds['hold_pct']:
        return "HOLD"

    # Tín hiệu yếu
    if prob_buy > 55: return "WEAK_BUY"
    if prob_sell > 55: return "WEAK_SELL"

    # Mặc định là TRÁNH nếu không rơi vào các trường hợp trên
    return "AVOID"

def analyze_single_interval(symbol: str, interval: str) -> dict or None:
    clf, reg, meta = load_model_and_meta(symbol, interval)
    if not clf or not reg or not meta: return None
    try:
        df_raw = get_price_data(symbol, interval, limit=200)
        features_df = add_features(df_raw)
        if features_df.empty: return None

        latest = features_df.iloc[-1]
        X = pd.DataFrame([latest], columns=features_df.columns)[meta["features"]]
        if X.isnull().values.any(): return None

        probs = clf.predict_proba(X)[0]
        prob_sell, prob_buy = probs[0] * 100, probs[2] * 100
        norm_change = float(reg.predict(X)[0])
        atr, price = latest.get('atr'), latest.get('close')

        if not price or not np.isfinite(price) or price <= 0 or not atr or atr <= 0: return None

        pct = norm_change * atr * 100 / price
        level = classify_level(prob_buy, prob_sell, pct, interval) # Truyền interval vào

        # risk_ratio thông minh hơn dựa trên cấp độ tín hiệu
        risk_map = {
            "STRONG_BUY": 1/3,   # TP gấp 3 SL
            "BUY": 1/2.5,        # TP gấp 2.5 SL
            "WEAK_BUY": 1/2,     # TP gấp 2 SL
            "HOLD": 1/1.5,
            "AVOID": 1/1.5,
            "WEAK_SELL": 1/2,
            "SELL": 1/2.5,
            "PANIC_SELL": 1/3
        }
        risk_ratio = risk_map.get(level, 1/1.5) # Mặc định R:R là 1:1.5
        direction = 1 if pct >= 0 else -1
        tp_pct = abs(pct) if abs(pct) > 0.2 else 0.5 # Tăng ngưỡng pct tối thiểu
        sl_pct = tp_pct * risk_ratio

        return {
            "symbol": symbol, "interval": interval,
            "prob_buy": round(prob_buy, 2),
            "prob_sell": round(prob_sell, 2),
            "pct": round(pct, 2), "price": price,
            "tp": price * (1 + direction * (tp_pct / 100)),
            "sl": price * (1 - direction * (sl_pct / 100)),
            "level": level,
        }
    except Exception as e:
        send_error_alert(f"Analysis failed for {symbol} {interval}: {e}")
        return None

# ==============================================================================
# ALERT GENERATION & FILE WRITING
# ==============================================================================
def generate_instant_alert(result: Dict, old_level: str) -> None:
    level_info = LEVEL_MAP.get(result['level'], {"icon": "❓", "name": "KHÔNG XÁC ĐỊNH"})
    old_level_info = LEVEL_MAP.get(old_level, {"icon": "❓", "name": "KHÔNG RÕ"})

    from_str = f"Từ {old_level_info.get('name', 'N/A')} ({old_level_info.get('icon', '❓')})" if old_level else "Tín hiệu mới"
    to_str = f"chuyển sang {level_info['name']} {level_info['icon']}"
    header = f"🔔 Thay đổi Tín hiệu AI: {result['symbol']} ({result['interval']})\n➡️ {from_str} {to_str}"

    strategy = (f"🧠 **Chiến lược Đề xuất:**\n"
                f"Một cơ hội giao dịch tiềm năng đang xuất hiện trên biểu đồ {result['interval']}. "
                f"Xác suất của mô hình đã có sự thay đổi đáng chú ý.\n\n"
                f"- **Tín hiệu chính:** Dựa trên khung {result['interval']} ({level_info['name']}).\n"
                f"- **Mục tiêu (TP) đề xuất:** `{result['tp']:.4f}`\n"
                f"- **Cắt lỗ (SL) đề xuất:** `{result['sl']:.4f}`")

    details = (f"📋 **Chi tiết Dự báo (Khung {result['interval']}):**\n"
               f"- **Giá hiện tại:** {result['price']:.4f}\n"
               f"- **Xác suất Mua:** {result['prob_buy']:.2f}%\n"
               f"- **Xác suất Bán:** {result['prob_sell']:.2f}%\n"
               f"- **Dự đoán thay đổi:** {result['pct']:+.2f}%")

    full_message = f"{header}\n\n{strategy}\n\n{details}"
    send_discord_alert({"content": full_message})
    print(f"✅ Alert sent for {result['symbol']}-{result['interval']}: {old_level} -> {result['level']}")

def generate_summary_report(all_results: List[Dict]) -> None:
    if not all_results: return
    embed_title = f"🔥 Tổng quan Thị trường AI - {datetime.now(ZoneInfo('Asia/Bangkok')).strftime('%H:%M (%d/%m/%Y)')}"
    embed = {"title": embed_title, "description": "*Tổng hợp tín hiệu và các mức giá quan trọng theo mô hình AI.*", "color": 3447003, "fields": [], "footer": {"text": "Dữ liệu được cung cấp bởi AI Model v5.5 (Adaptive & Refined Cooldown)"}}

    sorted_results = sorted(all_results, key=lambda x: x['symbol'])
    for symbol, group in groupby(sorted_results, key=lambda x: x['symbol']):
        field_value = ""
        sorted_group = sorted(list(group), key=lambda x: INTERVALS.index(x['interval']))
        for res in sorted_group:
            level_info = LEVEL_MAP.get(res['level'], {"icon": "❓", "name": "N/A"})
            price_str = f"{res['price']:.2f}" if res['price'] >= 1 else f"{res['price']:.4f}"
            tp_str = f"{res['tp']:.2f}" if res['tp'] >= 1 else f"{res['tp']:.4f}"
            sl_str = f"{res['sl']:.2f}" if res['sl'] >= 1 else f"{res['sl']:.4f}"
            line = (f"`{res['interval']:<2}` {level_info['icon']}**{level_info['name']}** `{res['pct']:+5.2f}%` | "
                    f"Giá:`{price_str}` TP:`{tp_str}` SL:`{sl_str}`\n")
            field_value += line
        embed["fields"].append({"name": f"➡️ {symbol}", "value": field_value, "inline": False})

    send_discord_alert({"embeds": [embed]})
    print("✅ Summary report sent.")

# ==============================================================================
# MAIN
# ==============================================================================
def main():
    print(f"🧠 Bắt đầu chu trình phân tích AI lúc {datetime.now()}...")
    state = load_state()
    all_current_results = []
    now_utc = datetime.now(timezone.utc)

    for symbol in SYMBOLS:
        for interval in INTERVALS:
            state_key = f"{symbol}-{interval}"
            current_result = analyze_single_interval(symbol, interval)
            if not current_result:
                print(f"❌ Analysis failed for {symbol} {interval}, skipping.")
                continue

            output_path = os.path.join(LOG_DIR, f"{symbol}_{interval}.json")
            write_json(output_path, current_result)
            all_current_results.append(current_result)

            previous_state = state.get(state_key, {})
            previous_level = previous_state.get("last_level")
            current_level = current_result["level"]

            # Logic cảnh báo và cooldown được áp dụng cho MỌI thay đổi
            if current_level != previous_level:
                last_alert_ts = previous_state.get("last_alert_timestamp", 0)
                # Lấy thời gian cooldown dựa trên MỨC TÍN HIỆU MỚI
                cooldown_duration = COOLDOWN_BY_LEVEL.get(current_level, 3600) # 1 giờ mặc định

                if now_utc.timestamp() - last_alert_ts > cooldown_duration:
                    # Nếu đã hết thời gian chờ, gửi cảnh báo và cập nhật trạng thái
                    generate_instant_alert(current_result, previous_level)
                    state[state_key] = {
                        "last_level": current_level,
                        "last_alert_timestamp": now_utc.timestamp()
                    }
                else:
                    # Nếu vẫn trong thời gian chờ, chỉ ghi log và không gửi cảnh báo
                    print(f"⏳ Cooldown active for {state_key}. Change from {previous_level} to {current_level} detected but no alert sent.")
                    # Vẫn cập nhật `last_level` để hệ thống biết trạng thái hiện tại
                    if state_key not in state: state[state_key] = {}
                    state[state_key]['last_level'] = current_level

    if should_send_overview(state):
        if all_current_results:
            generate_summary_report(all_current_results)
            state["last_overview_timestamp"] = now_utc.timestamp()
            print("✅ AI Summary report sent and timestamp updated.")

    save_state(state)
    print("✅ Phân tích AI hoàn tất.")

if __name__ == "__main__":
    main()
