# ===================================================================
# ml_report.py - PHIÊN BẢN TỐI ƯU CHO VPS CẤU HÌNH YẾU
# ===================================================================
# Thay đổi chính:
# - Chạy tuần tự từng cặp Symbol/Interval thay vì tải tất cả model cùng lúc.
# - Chủ động giải phóng bộ nhớ (RAM) sau mỗi lần phân tích bằng cách
#   xóa đối tượng model và gọi bộ thu gom rác của Python & Keras.
# ===================================================================

import os, sys, json, time, requests, joblib, gc # <--- Thêm import gc
import pandas as pd, numpy as np, ta
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from typing import List, Dict, Optional
from itertools import groupby

# --- TF & Keras Imports (Yên lặng) ---
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
import warnings
warnings.filterwarnings("ignore", category=UserWarning)
import tensorflow as tf
tf.get_logger().setLevel("ERROR")
from keras.models import load_model

# --------------------------------------------------
# CONFIG & CONSTANTS (Không thay đổi)
# --------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BASE_DIR)
load_dotenv()

SYMBOLS = os.getenv("SYMBOLS", "ETHUSDT,BTCUSDT,SOLUSDT").split(",")
INTERVALS = os.getenv("INTERVALS", "1h,4h,1d").split(",")
WEBHOOK_URL = os.getenv("DISCORD_AI_WEBHOOK")
ERROR_WEBHOOK = os.getenv("DISCORD_ERROR_WEBHOOK")
ENSEMBLE_WEIGHTS = {"lightgbm": 0.25, "lstm": 0.35, "transformer": 0.40}
SEQUENCE_LENGTH = 60
API_LIMIT = SEQUENCE_LENGTH + 200

DATA_DIR = os.path.join(BASE_DIR, "data")
LOG_DIR = os.path.join(BASE_DIR, "ai_logs")
STATE_FILE = os.path.join(BASE_DIR, "ml_state.json")
os.makedirs(LOG_DIR, exist_ok=True)

COOLDOWN_BY_LEVEL = {"STRONG_BUY": 3600, "PANIC_SELL": 3600, "BUY": 7200, "SELL": 7200, "WEAK_BUY": 14400, "WEAK_SELL": 14400, "HOLD": 28800, "AVOID": 28800}
LEVEL_MAP = {"STRONG_BUY": {"icon": "🚀", "name": "STRONG BUY"}, "BUY": {"icon": "✅", "name": "BUY"}, "WEAK_BUY": {"icon": "🟢", "name": "WEAK BUY"}, "HOLD": {"icon": "🔍", "name": "HOLD"}, "AVOID": {"icon": "🚧", "name": "AVOID"}, "WEAK_SELL": {"icon": "🔻", "name": "WEAK SELL"}, "SELL": {"icon": "❌", "name": "SELL"}, "PANIC_SELL": {"icon": "🆘", "name": "PANIC SELL"}}
SUB_LEVEL_INFO = {"HOLD_BULLISH": {"icon": "📈", "name": "HOLD (Thiên Tăng)", "desc": "Thị trường tích lũy, thiên tăng."}, "HOLD_BEARISH": {"icon": "📉", "name": "HOLD (Thiên Giảm)", "desc": "Thị trường phân phối, thiên giảm."}, "HOLD_NEUTRAL": {"icon": "🤔", "name": "HOLD (Trung Lập)", "desc": "Biên động quá nhỏ."}, "AVOID_UNCERTAIN": {"icon": "❓", "name": "AVOID (Không Chắc)", "desc": "Tín hiệu nhiễu."}, "AVOID_CONFLICT": {"icon": "⚔️", "name": "AVOID (Xung Đột)", "desc": "Tín hiệu các model trái chiều."}, "DEFAULT": {"icon": "", "name": "", "desc": ""}}

# --------------------------------------------------
# CÁC HÀM HELPER (Không thay đổi)
# --------------------------------------------------
def get_sub_info(key: str) -> dict: return SUB_LEVEL_INFO.get(key, SUB_LEVEL_INFO["DEFAULT"])
def get_price_data(symbol: str, interval: str, limit: int) -> pd.DataFrame:
    try:
        r = requests.get("https://api.binance.com/api/v3/klines", params={"symbol": symbol, "interval": interval, "limit": limit}, timeout=10)
        r.raise_for_status()
        df = pd.DataFrame(r.json(), columns=["timestamp", "open", "high", "low", "close", "volume", "c1", "c2", "c3", "c4", "c5", "c6"]).iloc[:, :6]
        df.columns = ["timestamp", "open", "high", "low", "close", "volume"]
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        return df.set_index("timestamp").apply(pd.to_numeric, errors="coerce")
    except Exception as e: print(f"[ERROR] get_price_data {symbol}-{interval}: {e}"); return pd.DataFrame()
def add_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy(); close, high, low, volume = out["close"], out["high"], out["low"], out["volume"]
    out['price'] = close; out['vol_ma20'] = volume.rolling(window=20).mean()
    bb = ta.volatility.BollingerBands(close, window=20); out['bb_upper'], out['bb_lower'] = bb.bollinger_hband(), bb.bollinger_lband(); out['bb_width'] = (out['bb_upper'] - out['bb_lower']) / (bb.bollinger_mavg() + 1e-9)
    macd = ta.trend.MACD(close); out['macd'], out['macd_signal'], out["macd_diff"] = macd.macd(), macd.macd_signal(), macd.macd_diff()
    for n in [14, 28, 50]: out[f'rsi_{n}'] = ta.momentum.rsi(close, window=n); out[f'ema_{n}'] = ta.trend.ema_indicator(close, window=n); out[f'dist_ema_{n}'] = (close - out[f'ema_{n}']) / (out[f'ema_{n}'] + 1e-9)
    out["adx"] = ta.trend.adx(high, low, close); out['atr'] = ta.volatility.average_true_range(high, low, close, window=14); out['cmf'] = ta.volume.chaikin_money_flow(high, low, close, volume, window=20)
    for n in [1, 2, 3, 5, 8, 13, 21]: out[f'pct_change_lag_{n}'] = close.pct_change(periods=n)
    out.replace([np.inf, -np.inf], np.nan, inplace=True); out.bfill(inplace=True); out.ffill(inplace=True); out.fillna(0, inplace=True)
    return out
def create_sequences(data: pd.DataFrame, feature_cols: list, seq_length: int) -> np.ndarray:
    X = []; num_features = len(feature_cols)
    values = data[feature_cols].values
    for i in range(len(data) - seq_length + 1): X.append(values[i:(i + seq_length)])
    return np.array(X).reshape(-1, seq_length, num_features)
class AIModelBundle:
    def __init__(self, symbol: str, interval: str):
        self.clf_lgbm, self.reg_lgbm, self.clf_lstm, self.reg_lstm, self.clf_trans, self.reg_trans = (None,) * 6
        self.scaler, self.meta = None, None
        try:
            self.meta = json.load(open(os.path.join(DATA_DIR, f"meta_{symbol}_{interval}.json")))
            self.scaler = joblib.load(os.path.join(DATA_DIR, f"scaler_{symbol}_{interval}.pkl"))
            self.clf_lgbm = joblib.load(os.path.join(DATA_DIR, f"model_{symbol}_lgbm_clf_{interval}.pkl"))
            self.reg_lgbm = joblib.load(os.path.join(DATA_DIR, f"model_{symbol}_lgbm_reg_{interval}.pkl"))
            self.clf_lstm = load_model(os.path.join(DATA_DIR, f"model_{symbol}_lstm_clf_{interval}.keras"), compile=False)
            self.reg_lstm = load_model(os.path.join(DATA_DIR, f"model_{symbol}_lstm_reg_{interval}.keras"), compile=False)
            self.clf_trans = load_model(os.path.join(DATA_DIR, f"model_{symbol}_transformer_clf_{interval}.keras"), compile=False)
            self.reg_trans = load_model(os.path.join(DATA_DIR, f"model_{symbol}_transformer_reg_{interval}.keras"), compile=False)
        except Exception: self.meta = None
    def is_valid(self): return self.meta is not None
def analyze_ensemble(symbol: str, interval: str, bundle: AIModelBundle) -> Optional[Dict]:
    df = get_price_data(symbol, interval, API_LIMIT)
    if df.empty or len(df) < SEQUENCE_LENGTH + 50: return None
    features_df = add_features(df)
    features_to_use = bundle.meta['features']
    opinions = {}
    latest_row = features_df[features_to_use].iloc[[-1]]
    lgbm_clf_prob = bundle.clf_lgbm.predict_proba(latest_row)[0]
    lgbm_reg_pred = bundle.reg_lgbm.predict(latest_row)[0]
    lgbm_classes = bundle.clf_lgbm.classes_.tolist()
    prob_sell_lgbm = lgbm_clf_prob[lgbm_classes.index(0)] if 0 in lgbm_classes else 0
    prob_buy_lgbm = lgbm_clf_prob[lgbm_classes.index(2)] if 2 in lgbm_classes else 0
    opinions['lightgbm'] = {"prob_sell": prob_sell_lgbm * 100, "prob_buy": prob_buy_lgbm * 100, "pct": float(lgbm_reg_pred)}
    scaled_df = features_df.copy(); scaled_df[features_to_use] = bundle.scaler.transform(features_df[features_to_use])
    sequence = create_sequences(scaled_df, features_to_use, SEQUENCE_LENGTH)
    if len(sequence) > 0:
        seq_to_predict = sequence[[-1]]
        lstm_clf_prob = bundle.clf_lstm.predict(seq_to_predict, verbose=0)[0]
        lstm_reg_pred = bundle.reg_lstm.predict(seq_to_predict, verbose=0)[0][0]
        opinions['lstm'] = {"prob_sell": float(lstm_clf_prob[0]) * 100, "prob_buy": float(lstm_clf_prob[2]) * 100, "pct": float(lstm_reg_pred)}
        trans_clf_prob = bundle.clf_trans.predict(seq_to_predict, verbose=0)[0]
        trans_reg_pred = bundle.reg_trans.predict(seq_to_predict, verbose=0)[0][0]
        opinions['transformer'] = {"prob_sell": float(trans_clf_prob[0]) * 100, "prob_buy": float(trans_clf_prob[2]) * 100, "pct": float(trans_reg_pred)}
    if not opinions: return None
    final_prob_buy, final_prob_sell, final_pct, total_weight = 0.0, 0.0, 0.0, sum(ENSEMBLE_WEIGHTS[k] for k in opinions)
    if total_weight == 0: return None
    for name, op in opinions.items():
        weight = ENSEMBLE_WEIGHTS[name] / total_weight
        final_prob_buy += op['prob_buy'] * weight; final_prob_sell += op['prob_sell'] * weight; final_pct += op['pct'] * weight
    lv = classify_level(final_prob_buy, final_prob_sell, final_pct, interval)
    if len(opinions) > 2:
        buys = sum(1 for op in opinions.values() if op['pct'] > 0.1); sells = sum(1 for op in opinions.values() if op['pct'] < -0.1)
        if buys > 0 and sells > 0 and lv['level'] in ['BUY', 'SELL']: lv = {"level": "AVOID", "sub_level": "AVOID_CONFLICT"}
    price = features_df.iloc[-1]['close']
    risk = {"STRONG_BUY":1/3,"BUY":1/2.5,"WEAK_BUY":1/2,"HOLD":1/1.5,"AVOID":1/1.5,"WEAK_SELL":1/2,"SELL":1/2.5,"PANIC_SELL":1/3}.get(lv['level'],1/1.5)
    dir_ = 1 if final_pct >= 0 else -1; tp_pct = max(abs(final_pct), 0.5); sl_pct = tp_pct * risk
    return {
        "symbol": symbol, "interval": interval,
        "prob_buy": round(final_prob_buy, 1), "prob_sell": round(final_prob_sell, 1), "pct": final_pct,
        "price": price, "tp": price * (1 + dir_ * tp_pct / 100), "sl": price * (1 - dir_ * sl_pct / 100),
        "level": lv['level'], "sub_level": lv['sub_level'],
        "expert_opinions": {name: {"pct": round(op['pct'], 4), "prob_buy": round(op['prob_buy'], 1), "prob_sell": round(op['prob_sell'], 1)} for name, op in opinions.items()}
    }
def classify_level(pb: float, ps: float, pct: float, interval: str) -> Dict[str, str]:
    if pb > 70 and pb > ps * 2: return {"level": "STRONG_BUY", "sub_level": "STRONG_BUY"}
    if ps > 70 and ps > pb * 2: return {"level": "PANIC_SELL", "sub_level": "PANIC_SELL"}
    if pb > 60 and pb > ps * 1.5: return {"level": "BUY", "sub_level": "BUY"}
    if ps > 60 and ps > pb * 1.5: return {"level": "SELL", "sub_level": "SELL"}
    if pb > 55: return {"level": "WEAK_BUY", "sub_level": "WEAK_BUY"}
    if ps > 55: return {"level": "WEAK_SELL", "sub_level": "WEAK_SELL"}
    dz = {"1h": 0.4, "4h": 0.8, "1d": 1.2}.get(interval, 0.8)
    if abs(pct) < dz:
        sub = "HOLD_NEUTRAL";
        if pb > ps + 5: sub = "HOLD_BULLISH";
        elif ps > pb + 5: sub = "HOLD_BEARISH"
        return {"level": "HOLD", "sub_level": sub}
    return {"level": "AVOID", "sub_level": "AVOID_UNCERTAIN"}
def atomic_write_json(path: str, data: dict):
    temp_path = path + ".tmp";
    with open(temp_path, 'w', encoding='utf-8') as f: json.dump(data, f, indent=2)
    os.replace(temp_path, path)
def send_discord(payload: Dict):
    if not WEBHOOK_URL: return
    try:
        requests.post(WEBHOOK_URL, json=payload, timeout=15).raise_for_status()
        time.sleep(1)
    except Exception as e: print(f"[ERROR] Discord send failed: {e}")
def load_state():
    if not os.path.exists(STATE_FILE): return {}
    try: return json.load(open(STATE_FILE))
    except Exception: return {}
def should_send_overview(state: dict) -> bool:
    last = state.get("last_overview_timestamp", 0)
    now_vn = datetime.now(ZoneInfo("Asia/Bangkok"))
    for h in (8, 20):
        t_vn = now_vn.replace(hour=h, minute=1, second=0, microsecond=0).timestamp()
        if now_vn.timestamp() >= t_vn and last < t_vn: return True
    return False
def fmt_price(p): return f"{p:.8f}".rstrip('0').rstrip('.') if p < 1 else f"{p:.4f}".rstrip('0').rstrip('.')
def fmt_pct(x): return f"{x:+.4f}%" if abs(x) < 0.01 and x != 0 else f"{x:+.2f}%"
def instant_alert(res: Dict, old_lv: Optional[str], old_sub: Optional[str]):
    from_str = "Tín hiệu mới"
    if old_lv:
        old_info_map = get_sub_info(old_sub) if old_sub and ('HOLD' in old_lv or 'AVOID' in old_lv) else LEVEL_MAP.get(old_lv, {})
        from_str = f"Từ **{old_info_map.get('name', 'N/A')}** {old_info_map.get('icon', '❔')}"
    is_sub_level_alert = res['level'] in ["HOLD", "AVOID"]
    current_info_map = get_sub_info(res['sub_level']) if is_sub_level_alert else LEVEL_MAP.get(res['level'], {})
    to_str = f"chuyển sang **{current_info_map.get('name', 'N/A')}** {current_info_map.get('icon', '❔')}"
    desc = current_info_map.get('desc', '') if is_sub_level_alert else f"Một cơ hội giao dịch **{current_info_map.get('name', 'N/A')}** tiềm năng đã xuất hiện."
    fields = [
        {"name": "Giá hiện tại", "value": f"`{fmt_price(res['price'])}`", "inline": True},
        {"name": "Dự đoán thay đổi", "value": f"`{fmt_pct(res['pct'])}`", "inline": True},
        {"name": "Xác suất Mua/Bán", "value": f"`{res['prob_buy']:.1f}% / {res['prob_sell']:.1f}%`", "inline": True},
        {"name": "Mục tiêu (TP)", "value": f"`{fmt_price(res['tp'])}`", "inline": True},
        {"name": "Cắt lỗ (SL)", "value": f"`{fmt_price(res['sl'])}`", "inline": True},
        {"name": "\u200b", "value": "\u200b", "inline": True}
    ]
    embed = {
        "title": f"🔔 AI Alert: {res['symbol']} ({res['interval']})",
        "description": f"`{from_str} -> {to_str}`\n\n{desc}",
        "color": 3447003,
        "fields": fields,
        "footer": {"text": f"AI Model Ensemble | {datetime.now(ZoneInfo('Asia/Bangkok')).strftime('%Y-%m-%d %H:%M:%S')}"}
    }
    send_discord({"embeds": [embed]})
def summary_report(results: List[Dict]):
    counts = {"BUY": sum(1 for r in results if "BUY" in r['level']), "SELL": sum(1 for r in results if "SELL" in r['level'])}
    status = "TRUNG LẬP 🤔"; total = len(results)
    if counts['BUY'] > counts['SELL'] * 1.5 and counts['BUY'] / total > 0.3: status = "LẠC QUAN 📈"
    elif counts['SELL'] > counts['BUY'] * 1.5 and counts['SELL'] / total > 0.3: status = "BI QUAN 📉"
    now_vn_str = datetime.now(ZoneInfo('Asia/Bangkok')).strftime('%H:%M (%d/%m/%Y)')
    embed = {"title": f"📊 Tổng quan Thị trường AI - {now_vn_str}", "description": f"**Nhiệt kế thị trường: `{status}`**\n*Tổng hợp tín hiệu từ Hội đồng Chuyên gia AI.*", "color": 5814783, "fields": [], "footer": {"text": "AI Model Ensemble"}}
    sorted_results = sorted(results, key=lambda x: x['symbol'])
    for sym, group in groupby(sorted_results, key=lambda x: x['symbol']):
        group_list = list(group)
        price = group_list[0]['price']
        val = ""
        for r in sorted(group_list, key=lambda x: INTERVALS.index(x['interval'])):
            info = get_sub_info(r['sub_level']) if r['level'] in ["HOLD", "AVOID"] else LEVEL_MAP[r['level']]
            val += f"`{r['interval']:<3}` {info['icon']} **{info['name']}** `{fmt_pct(r['pct'])}`\n"
        embed['fields'].append({"name": f"**{sym}** | Giá: `{fmt_price(price)}`", "value": val, "inline": True})
    send_discord({"embeds": [embed]})

# --------------------------------------------------
# MAIN LOOP (PHIÊN BẢN MỚI TỐI ƯU HÓA BỘ NHỚ)
# --------------------------------------------------
def main():
    print(f"--- 🧠 Bắt đầu chu trình phân tích TUẦN TỰ ({datetime.now(ZoneInfo('Asia/Bangkok')).strftime('%H:%M:%S')}) ---")
    
    # Bước 1: Load trạng thái và chuẩn bị
    state = load_state()
    all_tasks = [(s, i) for s in SYMBOLS for i in INTERVALS]
    results = []
    now_utc_ts = datetime.now(timezone.utc).timestamp()

    # Bước 2: Vòng lặp chính, xử lý từng tác vụ một
    for symbol, interval in all_tasks:
        key = f"{symbol}-{interval}"
        print(f"\n  -> Đang xử lý: {key}")
        
        # Tải model CHỈ cho tác vụ hiện tại
        bundle = AIModelBundle(symbol, interval)
        
        if not bundle.is_valid():
            print(f"     - Bỏ qua (Không tìm thấy model cho {key})")
            del bundle
            gc.collect()
            continue

        # Phân tích
        res = analyze_ensemble(symbol, interval, bundle)
        
        # Dọn dẹp bộ nhớ NGAY LẬP TỨC sau khi phân tích xong
        del bundle
        tf.keras.backend.clear_session()
        gc.collect()
        
        if not res:
            print(f"     - Bỏ qua (Không đủ dữ liệu giá cho {key})")
            continue

        print(f"     - Kết quả: {res['sub_level']} ({fmt_pct(res['pct'])})")
        
        # Lưu kết quả phân tích vào file log riêng
        atomic_write_json(os.path.join(LOG_DIR, f"{symbol}_{interval}.json"), res)
        results.append(res)

        # Xử lý logic gửi alert (giữ nguyên)
        prev = state.get(key, {})
        new_sub_level = res['sub_level']

        # Đoạn code sửa lại
        if new_sub_level != prev.get('last_sub_level'):
            
            # BƯỚC 1: Lưu lại trạng thái CŨ vào các biến tạm
            old_level_to_report = prev.get('last_level')
            old_sub_level_to_report = prev.get('last_sub_level')

            last_alert_ts = prev.get('last_alert_timestamp', 0)
            cooldown_duration = COOLDOWN_BY_LEVEL.get(res['level'], 3600)

            # BƯỚC 2: Cập nhật state với tín hiệu MỚI
            state.setdefault(key, {})
            state[key]['last_level'] = res['level']
            state[key]['last_sub_level'] = new_sub_level
            
            if now_utc_ts - last_alert_ts > cooldown_duration:
                print(f"     - Gửi ALERT cho {key} (Tín hiệu mới: {new_sub_level})")
                
                # BƯỚC 3: Gọi hàm alert với các biến tạm chứa trạng thái CŨ
                instant_alert(res, old_level_to_report, old_sub_level_to_report) 
                
                state[key]['last_alert_timestamp'] = now_utc_ts
            else:
                remaining = int(cooldown_duration - (now_utc_ts - last_alert_ts))
                print(f"     - Tín hiệu thay đổi nhưng đang trong cooldown (còn {remaining}s).")


    # Bước 3: Gửi báo cáo tổng quan (nếu đến giờ)
    if results and should_send_overview(state):
        print("\n--- 📊 Gửi báo cáo tổng quan ---")
        summary_report(results)
        state['last_overview_timestamp'] = now_utc_ts

    # Bước 4: Lưu lại toàn bộ trạng thái cuối cùng
    atomic_write_json(STATE_FILE, state)
    print("\n--- ✅ Hoàn tất chu trình phân tích tuần tự ---")

if __name__ == "__main__":
    main()

