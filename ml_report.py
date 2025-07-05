# /root/ricealert/ml_report.py
import os, json, time, joblib, requests, sys
import pandas as pd, numpy as np, ta
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from typing import List, Dict
from itertools import groupby

# --- Thiết lập đường dẫn ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BASE_DIR)

# ==============================================================================
# SETUP & CONFIG
# ==============================================================================
load_dotenv()
SYMBOLS       = os.getenv("SYMBOLS", "LINKUSDT,TAOUSDT,ETHUSDT,AVAXUSDT,INJUSDT,SUIUSDT,FETUSDT").split(",")
INTERVALS     = os.getenv("INTERVALS", "1h,4h,1d").split(",")
WEBHOOK_URL   = os.getenv("DISCORD_AI_WEBHOOK")
ERROR_WEBHOOK = os.getenv("DISCORD_ERROR_WEBHOOK", "")

DATA_DIR   = os.path.join(BASE_DIR, "data")
LOG_DIR    = os.path.join(BASE_DIR, "ai_logs")
STATE_FILE = os.path.join(BASE_DIR, "ml_state.json")

os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

# ... (Các hằng số và map khác giữ nguyên) ...
COOLDOWN_BY_LEVEL = {
    "STRONG_BUY": 1 * 3600, "PANIC_SELL": 1 * 3600,
    "BUY": 2 * 3600, "SELL": 2 * 3600,
    "WEAK_BUY": 4 * 3600, "WEAK_SELL": 4 * 3600,
    "HOLD": 8 * 3600, "AVOID": 8 * 3600
}
LEVEL_MAP = {
    "STRONG_BUY": {"icon": "🚀", "name": "STRONG BUY"}, "BUY": {"icon": "✅", "name": "BUY"},
    "WEAK_BUY": {"icon": "🟢", "name": "WEAK BUY"}, "HOLD": {"icon": "🔍", "name": "HOLD"},
    "AVOID": {"icon": "🚧", "name": "AVOID"}, "WEAK_SELL": {"icon": "🔻", "name": "WEAK SELL"},
    "SELL": {"icon": "❌", "name": "SELL"}, "PANIC_SELL": {"icon": "🆘", "name": "PANIC SELL"},
}

# ==============================================================================
# HÀM TÍNH TOÁN
# ==============================================================================
def get_price_data(symbol: str, interval: str, limit: int) -> pd.DataFrame:
    # (Hàm này giữ nguyên)
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
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

# === CODE MERGED START ===
def add_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    close = out["close"]
    volume = out["volume"]

    # Bổ sung các chỉ báo cần thiết cho signal_logic
    out['price'] = close
    out['vol_ma20'] = volume.rolling(window=20).mean()
    bb = ta.volatility.BollingerBands(close, window=20)
    out['bb_upper'] = bb.bollinger_hband()
    out['bb_lower'] = bb.bollinger_lband()
    out['bb_width'] = (out['bb_upper'] - out['bb_lower']) / (bb.bollinger_mavg() + 1e-9)
    
    macd_indicator = ta.trend.MACD(close)
    out['macd'] = macd_indicator.macd()
    out['macd_signal'] = macd_indicator.macd_signal()
    out["macd_diff"] = macd_indicator.macd_diff()
    macd_cross_cond = [
        (out['macd'].shift(1) < out['macd_signal'].shift(1)) & (out['macd'] > out['macd_signal']),
        (out['macd'].shift(1) > out['macd_signal'].shift(1)) & (out['macd'] < out['macd_signal'])
    ]
    macd_cross_choices = ['bullish', 'bearish']
    out['macd_cross'] = np.select(macd_cross_cond, macd_cross_choices, default='neutral')
    
    # Đồng bộ logic Trend về EMA 20/50
    ema_fast = ta.trend.ema_indicator(close, window=20)
    ema_slow = ta.trend.ema_indicator(close, window=50)
    trend_cond = [ema_fast > ema_slow, ema_fast < ema_slow]
    trend_choices = ['uptrend', 'downtrend']
    out['trend'] = np.select(trend_cond, trend_choices, default='sideway')
    
    # Các chỉ báo cũ cho AI
    for n in [14, 28, 50]:
        out[f'rsi_{n}'] = ta.momentum.rsi(close, window=n)
        out[f'ema_{n}'] = ta.trend.ema_indicator(close, window=n)
        out[f'dist_ema_{n}'] = (close - out[f'ema_{n}']) / (out[f'ema_{n}'] + 1e-9)
    out["adx"] = ta.trend.adx(out["high"], out["low"], close)
    out['atr'] = ta.volatility.average_true_range(out["high"], out["low"], close, window=14)
    out['cmf'] = ta.volume.chaikin_money_flow(out["high"], out["low"], close, volume, window=20)
    for n in [1, 2, 3, 5, 8, 13, 21]:
        out[f'pct_change_lag_{n}'] = close.pct_change(periods=n)
        out[f'rsi_14_lag_{n}'] = out['rsi_14'].shift(n)
        out[f'bb_width_lag_{n}'] = out['bb_width'].shift(n)
    log_return = np.log(close / close.shift(1))
    out['volatility_20'] = log_return.rolling(window=20).std() * np.sqrt(20)
    out['volatility_50'] = log_return.rolling(window=50).std() * np.sqrt(50)
    out['hour_of_day'] = out.index.hour
    out['day_of_week'] = out.index.dayofweek
    out['vol_x_rsi'] = volume * out['rsi_14']
    out['adx_x_cmf'] = out['adx'] * out['cmf']

    # Không cần One-Hot Encoding ở đây vì model sẽ dùng các feature đã được train
    
    # Dọn dẹp cuối cùng
    out.replace([np.inf, -np.inf], np.nan, inplace=True)
    out.bfill(inplace=True)
    out.ffill(inplace=True)
    out.fillna(0, inplace=True)
    return out
# === CODE MERGED END ===


# ==============================================================================
# UTILITY & HELPER FUNCTIONS
# ==============================================================================
def write_json(path: str, data: dict):
    with open(path, "w") as f: json.dump(data, f, indent=2)

def send_discord_alert(payload: Dict) -> None:
    if not WEBHOOK_URL: return
    try:
        requests.post(WEBHOOK_URL, json=payload, timeout=10).raise_for_status()
        time.sleep(2)
    except Exception as exc: print(f"[ERROR] Discord alert failed: {exc}")

def send_error_alert(msg: str) -> None:
    ts = datetime.now(timezone.utc).isoformat()
    with open(os.path.join(LOG_DIR, "error_ml.log"), "a") as f: f.write(f"{ts} | {msg}\n")
    if ERROR_WEBHOOK:
        try: requests.post(ERROR_WEBHOOK, json={"content": f"⚠️ ML_REPORT ERROR: {msg}"}, timeout=10)
        except Exception: pass

def load_state() -> dict:
    if not os.path.exists(STATE_FILE): return {}
    try:
        with open(STATE_FILE, "r") as f: return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError): return {}

def save_state(data: dict) -> None:
    with open(STATE_FILE, "w") as f: json.dump(data, f, indent=2)

def load_model_and_meta(symbol: str, interval: str):
    try:
        clf = joblib.load(os.path.join(DATA_DIR, f"model_{symbol}_clf_{interval}.pkl"))
        reg = joblib.load(os.path.join(DATA_DIR, f"model_{symbol}_reg_{interval}.pkl"))
        with open(os.path.join(DATA_DIR, f"meta_{symbol}_{interval}.json")) as f: meta = json.load(f)
        return clf, reg, meta
    except Exception as exc:
        send_error_alert(f"Failed to load model/meta for {symbol} {interval}: {exc}")
        return None, None, None

def should_send_overview(state: dict) -> bool:
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
    THRESHOLDS = {
        "1h": {"dead_zone_pct": 0.4}, "4h": {"dead_zone_pct": 0.8}, "1d": {"dead_zone_pct": 1.2}
    }
    thresholds = THRESHOLDS.get(interval, THRESHOLDS["4h"])
    if abs(pct) < thresholds['dead_zone_pct']: return "HOLD"
    if prob_buy > 75: return "STRONG_BUY"
    if prob_sell > 75: return "PANIC_SELL"
    if prob_buy > 65: return "BUY"
    if prob_sell > 65: return "SELL"
    if prob_buy > 55: return "WEAK_BUY"
    if prob_sell > 55: return "WEAK_SELL"
    return "AVOID"

def analyze_single_interval(symbol: str, interval: str) -> dict or None:
    clf, reg, meta = load_model_and_meta(symbol, interval)
    if not clf or not reg or not meta: return None
    try:
        df_raw = get_price_data(symbol, interval, limit=300)
        if df_raw.empty or len(df_raw) < 100: return None
        features_df = add_features(df_raw)
        latest = features_df.iloc[-1]
        model_features = meta["features"]
        latest_data_for_model = {feature: latest.get(feature, 0) for feature in model_features}
        X = pd.DataFrame([latest_data_for_model])
        X = X[model_features]
        if X.isnull().values.any():
            send_error_alert(f"NaNs found in X for {symbol} {interval} even after handling.")
            X.fillna(0, inplace=True)
        probs = clf.predict_proba(X)[0]
        classes = clf.classes_.tolist()
        prob_sell = probs[classes.index(0)] * 100 if 0 in classes else 0.0
        prob_buy = probs[classes.index(2)] * 100 if 2 in classes else 0.0
        norm_change = float(reg.predict(X)[0])
        atr, price = latest.get('atr'), latest.get('close')
        if not price or not np.isfinite(price) or price <= 0: return None
        if not atr or not np.isfinite(atr) or atr <= 0: atr = price * 0.01
        pct = norm_change * atr * 100 / price
        level = classify_level(prob_buy, prob_sell, pct, interval)
        risk_map = {"STRONG_BUY": 1/3, "BUY": 1/2.5, "WEAK_BUY": 1/2, "HOLD": 1/1.5, "AVOID": 1/1.5,
                    "WEAK_SELL": 1/2, "SELL": 1/2.5, "PANIC_SELL": 1/3}
        risk_ratio = risk_map.get(level, 1/1.5)
        direction = 1 if pct >= 0 else -1
        tp_pct = max(abs(pct), 0.5)
        sl_pct = tp_pct * risk_ratio
        return {
            "symbol": symbol, "interval": interval, "prob_buy": round(prob_buy, 2),
            "prob_sell": round(prob_sell, 2), "pct": round(pct, 2), "price": price,
            "tp": price * (1 + direction * (tp_pct / 100)),
            "sl": price * (1 - direction * (sl_pct / 100)),
            "level": level,
        }
    except Exception as e:
        send_error_alert(f"Analysis failed for {symbol} {interval}: {e}")
        import traceback
        send_error_alert(traceback.format_exc())
        return None

# ==============================================================================
# ALERT GENERATION & FILE WRITING
# ==============================================================================
def format_price(price):
    if not isinstance(price, (int, float)) or not np.isfinite(price): return "N/A"
    return f"{price:.8f}" if price < 0.1 else f"{price:.4f}"

def generate_instant_alert(result: Dict, old_level: str) -> None:
    level_info = LEVEL_MAP.get(result['level'], {"icon": "❓", "name": "UNKNOWN"})
    old_level_info = LEVEL_MAP.get(old_level, {"icon": "❓", "name": "N/A"})
    from_str = f"Từ {old_level_info.get('name', 'N/A')} ({old_level_info.get('icon', '❓')})" if old_level else "Tín hiệu mới"
    to_str = f"chuyển sang {level_info['name']} {level_info['icon']}"
    header = f"🔔 **AI Alert: {result['symbol']} ({result['interval']})**\n`{from_str} -> {to_str}`"
    price_fmt = format_price(result['price'])
    tp_fmt = format_price(result['tp'])
    sl_fmt = format_price(result['sl'])
    fields = [
        {"name": "Giá hiện tại", "value": f"`{price_fmt}`", "inline": True},
        {"name": "Dự đoán thay đổi", "value": f"`{result['pct']:+.2f}%`", "inline": True},
        {"name": "Xác suất Mua/Bán", "value": f"`{result['prob_buy']:.1f}% / {result['prob_sell']:.1f}%`", "inline": True}
    ]
    description = ""
    if result['level'] not in ["HOLD", "AVOID"]:
        description = f"Một cơ hội giao dịch **{level_info['name']}** tiềm năng đã xuất hiện."
        fields.extend([
            {"name": "Mục tiêu (TP) đề xuất", "value": f"`{tp_fmt}`", "inline": True},
            {"name": "Cắt lỗ (SL) đề xuất", "value": f"`{sl_fmt}`", "inline": True}
        ])
    else:
        if result['level'] == "HOLD":
            description = "Biến động dự đoán quá nhỏ, không đủ để tạo cơ hội giao dịch. Khuyến nghị quan sát thêm."
        elif result['level'] == "AVOID":
            description = "Tín hiệu nhiễu, không đáng tin cậy. Xác suất dự đoán thấp dù biến động có thể lớn. Khuyến nghị đứng ngoài."
    embed = {
        "title": header, "description": description, "color": 3447003,
        "fields": fields,
        "footer": {"text": f"AI Model v6.0 | {datetime.now(ZoneInfo('Asia/Bangkok')).strftime('%Y-%m-%d %H:%M:%S')}"}
    }
    send_discord_alert({"embeds": [embed]})
    print(f"✅ Alert sent for {result['symbol']}-{result['interval']}: {old_level} -> {result['level']}")

def generate_summary_report(all_results: List[Dict]) -> None:
    if not all_results: return
    embed_title = f"📊 Tổng quan Thị trường AI - {datetime.now(ZoneInfo('Asia/Bangkok')).strftime('%H:%M (%d/%m/%Y)')}"
    embed = {"title": embed_title, "description": "*Tổng hợp tín hiệu và các mức giá quan trọng theo mô hình AI.*", "color": 5814783, "fields": [], "footer": {"text": "AI Model v6.0"}}
    sorted_results = sorted(all_results, key=lambda x: x['symbol'])
    for symbol, group in groupby(sorted_results, key=lambda x: x['symbol']):
        field_value = ""
        sorted_group = sorted(list(group), key=lambda x: INTERVALS.index(x['interval']) if x['interval'] in INTERVALS else len(INTERVALS))
        for res in sorted_group:
            level_info = LEVEL_MAP.get(res['level'], {"icon": "❓", "name": "N/A"})
            line = f"`{res['interval']:<3}` {level_info['icon']} **{level_info['name']:<10}** `{res['pct']:>+6.2f}%` ({res['prob_buy']:.0f}/{res['prob_sell']:.0f})\n"
            field_value += line
        embed["fields"].append({"name": f"**{symbol}**", "value": field_value, "inline": True})
    send_discord_alert({"embeds": [embed]})
    print("✅ Summary report sent.")

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
            if current_level != previous_level:
                last_alert_ts = previous_state.get("last_alert_timestamp", 0)
                cooldown_duration = COOLDOWN_BY_LEVEL.get(current_level, 3600)
                if now_utc.timestamp() - last_alert_ts > cooldown_duration:
                    generate_instant_alert(current_result, previous_level)
                    state[state_key] = {"last_level": current_level, "last_alert_timestamp": now_utc.timestamp()}
                else:
                    print(f"⏳ Cooldown active for {state_key}. Change from {previous_level} to {current_level} detected but no alert sent.")
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
