(venv) root@ricealert:~/ricealert$cat ml_report.py
# /root/ricealert/ml_report.py
# PHIÊN BẢN ULTIMATE (ĐÃ SỬA LỖI): "Hội Đồng Chuyên Gia AI"
# Tác giả: Đối tác lập trình & [Tên của bạn]
#
# CHANGELOG (Bản sửa lỗi):
# - SỬA LỖI TẢI MODEL: Viết lại hoàn toàn hàm `load_all_models`. Giờ đây nó sẽ tải
#   từng loại model (LGBM, LSTM, Transformer) một cách độc lập. Nếu một loại model
#   bị thiếu file, nó sẽ bỏ qua loại đó nhưng vẫn tiếp tục tải các loại khác,
#   đảm bảo hệ thống không bị dừng lại một cách vô lý.
# - TÍNH ĐỘC LẬP: Sao chép trực tiếp các hàm `add_features` và `create_sequences`
#   vào file này và xóa bỏ dòng `from trainer import ...`. Điều này làm cho
#   ml_report.py trở nên hoàn toàn độc lập, tránh các lỗi tiềm ẩn liên quan đến import.
# - CẢI THIỆN LOG: Thêm các dòng print chi tiết hơn để bạn biết chính xác model nào
#   được tải thành công hoặc bị bỏ qua.

import os
import sys
import json
import warnings
import requests
import joblib
import pandas as pd
import numpy as np
import ta
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from typing import Dict, List, Any

# --- Cấu hình để giảm log rác của TensorFlow ---
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
warnings.filterwarnings("ignore", category=UserWarning)

# --- Tải các thư viện cần thiết ---
import tensorflow as tf
tf.get_logger().setLevel("ERROR")
import lightgbm as lgb
from tensorflow.keras.models import load_model

# ==============================================================================
# ⚙️ CẤU HÌNH & HẰNG SỐ
# ==============================================================================
load_dotenv()

SYMBOLS = os.getenv("SYMBOLS", "ETHUSDT,BTCUSDT").split(",")
INTERVALS = os.getenv("INTERVALS", "1h,4h,1d").split(",")
WEBHOOK_URL = os.getenv("DISCORD_AI_WEBHOOK")

ENSEMBLE_WEIGHTS = {
    "lightgbm": 0.25,
    "lstm": 0.35,
    "transformer": 0.40
}

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
LOG_DIR = os.path.join(BASE_DIR, "ai_logs")
os.makedirs(LOG_DIR, exist_ok=True)

# ==============================================================================
# (MỚI) CÁC HÀM HELPER ĐƯỢC SAO CHÉP VÀO ĐỂ ĐẢM BẢO TÍNH ĐỘC LẬP
# ==============================================================================

def add_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    close, high, low, volume = out["close"], out["high"], out["low"], out["volume"]
    out['price'] = close
    out['vol_ma20'] = volume.rolling(window=20).mean()
    bb = ta.volatility.BollingerBands(close, window=20)
    out['bb_upper'], out['bb_lower'] = bb.bollinger_hband(), bb.bollinger_lband()
    out['bb_width'] = (out['bb_upper'] - out['bb_lower']) / (bb.bollinger_mavg() + 1e-9)
    macd = ta.trend.MACD(close)
    out['macd'], out['macd_signal'], out["macd_diff"] = macd.macd(), macd.macd_signal(), macd.macd_diff()
    for n in [14, 28, 50]:
        out[f'rsi_{n}'] = ta.momentum.rsi(close, window=n)
        out[f'ema_{n}'] = ta.trend.ema_indicator(close, window=n)
        out[f'dist_ema_{n}'] = (close - out[f'ema_{n}']) / (out[f'ema_{n}'] + 1e-9)
    out["adx"] = ta.trend.adx(high, low, close)
    out['atr'] = ta.volatility.average_true_range(high, low, close, window=14)
    out['cmf'] = ta.volume.chaikin_money_flow(high, low, close, volume, window=20)
    for n in [1, 2, 3, 5, 8, 13, 21]: out[f'pct_change_lag_{n}'] = close.pct_change(periods=n)
    out.replace([np.inf, -np.inf], np.nan, inplace=True)
    out.bfill(inplace=True); out.ffill(inplace=True); out.fillna(0, inplace=True)
    return out

def create_sequences(data: pd.DataFrame, feature_cols: list, seq_length: int):
    X = []
    # Chỉ cần tạo X, không cần y cho việc dự đoán
    for i in range(len(data) - seq_length + 1):
        X.append(data[feature_cols].iloc[i:(i + seq_length)].values)
    return np.array(X)

# ==============================================================================
# 📚 LỚP QUẢN LÝ "HỘI ĐỒNG CHUYÊN GIA AI" (ĐÃ SỬA LỖI)
# ==============================================================================

class AIEnsemble:
    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self.models = {}
        self.scalers = {}
        self.metas = {}
        self.sequence_length = 0

    def load_all_models(self, symbols: List[str], intervals: List[str]):
        """(SỬA LỖI) Tải từng model một cách độc lập để tăng tính kiên cường."""
        print("🧠 Đang tải 'Hội đồng Chuyên gia AI' vào bộ nhớ...")
        loaded_count = 0
        total_pairs = 0
        for sym in symbols:
            for iv in intervals:
                total_pairs += 1
                key = f"{sym}_{iv}"
                self.models[key] = {}

                meta_path = os.path.join(self.data_dir, f"meta_{sym}_{iv}.json")
                scaler_path = os.path.join(self.data_dir, f"scaler_{sym}_{iv}.pkl")

                try:
                    with open(meta_path, 'r') as f:
                        self.metas[key] = json.load(f)
                    self.scalers[key] = joblib.load(scaler_path)
                    if not self.sequence_length:
                        self.sequence_length = self.metas[key].get('sequence_length', 60)
                except FileNotFoundError:
                    print(f"     - ⚠️ Không tìm thấy file nền tảng (meta/scaler) cho {key}. Bỏ qua.")
                    continue

                model_loaded_for_pair = False
                # LightGBM
                try:
                    self.models[key]['lgbm_clf'] = joblib.load(os.path.join(self.data_dir, f"model_{sym}_lgbm_clf_{iv}.pkl"))
                    self.models[key]['lgbm_reg'] = joblib.load(os.path.join(self.data_dir, f"model_{sym}_lgbm_reg_{iv}.pkl"))
                    model_loaded_for_pair = True
                except FileNotFoundError: pass

                # LSTM
                try:
                    self.models[key]['lstm_clf'] = load_model(os.path.join(self.data_dir, f"model_{sym}_lstm_clf_{iv}.h5"), compile=False)
                    self.models[key]['lstm_reg'] = load_model(os.path.join(self.data_dir, f"model_{sym}_lstm_reg_{iv}.h5"), compile=False)
                    model_loaded_for_pair = True
                except (FileNotFoundError, IOError): pass

                # Transformer
                try:
                    self.models[key]['transformer_clf'] = load_model(os.path.join(self.data_dir, f"model_{sym}_transformer_clf_{iv}.h5"), compile=False)
                    self.models[key]['transformer_reg'] = load_model(os.path.join(self.data_dir, f"model_{sym}_transformer_reg_{iv}.h5"), compile=False)
                    model_loaded_for_pair = True
                except (FileNotFoundError, IOError): pass

                if model_loaded_for_pair:
                    loaded_count += 1
                    print(f"  -> ✅ Đã tải model cho {key}")
                else:
                    print(f"  -> ❌ Không có file model nào cho {key}")


        print(f"✅ Đã tải thành công model cho {loaded_count}/{total_pairs} cặp coin/khung giờ.")

    def predict(self, symbol: str, interval: str, df: pd.DataFrame) -> Dict[str, Any]:
        key = f"{symbol}_{interval}"
        if key not in self.models or not self.models[key]:
            return None

        meta = self.metas[key]
        scaler = self.scalers[key]
        features_to_use = meta['features']

        df_features = add_features(df)
        current_data = df_features.reindex(columns=features_to_use, fill_value=0)
        current_data_scaled = scaler.transform(current_data)
        current_data_scaled_df = pd.DataFrame(current_data_scaled, columns=features_to_use, index=current_data.index)

        opinions = {}

        # LightGBM
        if 'lgbm_clf' in self.models[key]:
            latest_features_lgbm = current_data.iloc[[-1]]
            lgbm_clf_prob = self.models[key]['lgbm_clf'].predict_proba(latest_features_lgbm)[0]
            lgbm_reg_pred = self.models[key]['lgbm_reg'].predict(latest_features_lgbm)[0]
            opinions['lightgbm'] = self._format_prediction(lgbm_clf_prob, lgbm_reg_pred, meta, df_features.iloc[-1]['atr'])

        # Dữ liệu chuỗi cho LSTM & Transformer
        seq_to_predict = None
        if 'lstm_clf' in self.models[key] or 'transformer_clf' in self.models[key]:
            # Chỉ tạo chuỗi nếu cần
            latest_sequence_scaled = create_sequences(current_data_scaled_df, features_to_use, self.sequence_length)
            if len(latest_sequence_scaled) > 0:
                seq_to_predict = latest_sequence_scaled[[-1]]

        if seq_to_predict is not None:
            # LSTM
            if 'lstm_clf' in self.models[key]:
                lstm_clf_prob = self.models[key]['lstm_clf'].predict(seq_to_predict, verbose=0)[0]
                lstm_reg_pred = self.models[key]['lstm_reg'].predict(seq_to_predict, verbose=0)[0][0]
                opinions['lstm'] = self._format_prediction(lstm_clf_prob, lstm_reg_pred, meta, df_features.iloc[-1]['atr'])
            # Transformer
            if 'transformer_clf' in self.models[key]:
                trans_clf_prob = self.models[key]['transformer_clf'].predict(seq_to_predict, verbose=0)[0]
                trans_reg_pred = self.models[key]['transformer_reg'].predict(seq_to_predict, verbose=0)[0][0]
                opinions['transformer'] = self._format_prediction(trans_clf_prob, trans_reg_pred, meta, df_features.iloc[-1]['atr'])

        if not opinions: return None

        final_prob_buy, final_prob_sell, final_pct = 0.0, 0.0, 0.0
        valid_opinions = {k: v for k, v in opinions.items() if v is not None}
        total_weight = sum(ENSEMBLE_WEIGHTS[k] for k in valid_opinions)
        if total_weight == 0: return None # Không có model nào hợp lệ

        for name, opinion in valid_opinions.items():
            weight = ENSEMBLE_WEIGHTS[name] / total_weight
            final_prob_buy += opinion['prob_buy'] * weight
            final_prob_sell += opinion['prob_sell'] * weight
            final_pct += opinion['pct'] * weight

        final_result = {
            "symbol": symbol, "interval": interval,
            "prob_buy": round(final_prob_buy, 2), "prob_sell": round(final_prob_sell, 2),
            "pct": round(final_pct, 4), "price": df_features.iloc[-1]['price'],
            "debug_info": {
                "ensemble_method": "Weighted Average", "weights": ENSEMBLE_WEIGHTS,
                "expert_opinions": opinions
            }
        }
        final_result.update(self._classify_level(final_result))
        return final_result

    def _format_prediction(self, prob, reg_pred, meta, current_atr):
        # prob[0] = sell, prob[1] = hold, prob[2] = buy
        prob_sell = prob[0] * 100
        prob_buy = prob[2] * 100
        pct = (reg_pred * current_atr / meta.get('atr_factor_threshold', 0.75)) * 100
        return {"prob_buy": prob_buy, "prob_sell": prob_sell, "pct": pct}

    def _classify_level(self, result: Dict) -> Dict:
        pb, ps, pct = result['prob_buy'], result['prob_sell'], result['pct']
        if pb > 70 and pb > ps * 2: return {"level": "STRONG_BUY", "sub_level": "STRONG_BUY"}
        if ps > 70 and ps > pb * 2: return {"level": "PANIC_SELL", "sub_level": "PANIC_SELL"}
        if pb > 60 and pb > ps * 1.5: return {"level": "BUY", "sub_level": "BUY"}
        if ps > 60 and ps > pb * 1.5: return {"level": "SELL", "sub_level": "SELL"}
        if pb > 55: return {"level": "WEAK_BUY", "sub_level": "WEAK_BUY"}
        if ps > 55: return {"level": "WEAK_SELL", "sub_level": "WEAK_SELL"}
        dz = {"1h": 0.4, "4h": 0.8, "1d": 1.2}.get(result['interval'], 0.8)
        if abs(pct) < dz:
            sub = "HOLD_NEUTRAL"
            if pb > ps + 5: sub = "HOLD_BULLISH"
            elif ps > pb + 5: sub = "HOLD_BEARISH"
            return {"level": "HOLD", "sub_level": sub}
        sub = "AVOID_UNCERTAIN"
        if pb > 35 and ps > 35: sub = "AVOID_CONFLICT"
        return {"level": "AVOID", "sub_level": sub}

# ==============================================================================
# 🚀 VÒNG LẶP CHÍNH & BÁO CÁO (Tương tự phiên bản trước)
# ==============================================================================

def get_price_data_for_prediction(symbol: str, interval: str, limit: int) -> pd.DataFrame:
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list) or not data: return pd.DataFrame()
        df = pd.DataFrame(data, columns=["timestamp","open","high","low","close","volume","c1","c2","c3","c4","c5","c6"]).iloc[:, :6]
        df.columns = ["timestamp","open","high","low","close","volume"]
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df.set_index("timestamp", inplace=True)
        return df.astype(float)
    except Exception as e:
        print(f"[ERROR] Lỗi get_price_data cho {symbol} {interval}: {e}")
        return pd.DataFrame()

def atomic_write_json(filepath: str, data: Dict):
    temp_filepath = filepath + ".tmp"
    with open(temp_filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(temp_filepath, filepath)

def format_discord_report(all_results: List[Dict]) -> str:
    if not all_results: return "Không có dữ liệu AI để báo cáo."
    results_by_symbol = {}
    for res in all_results:
        if res['symbol'] not in results_by_symbol:
            results_by_symbol[res['symbol']] = []
        results_by_symbol[res['symbol']].append(res)
    buy_signals = sum(1 for r in all_results if "BUY" in r.get('level', ''))
    sell_signals = sum(1 for r in all_results if "SELL" in r.get('level', ''))
    market_sentiment = "TRUNG LẬP 😐"
    if buy_signals > sell_signals * 1.5: market_sentiment = "LẠC QUAN 📈"
    elif sell_signals > buy_signals * 1.5: market_sentiment = "BI QUAN 📉"
    now_vn = datetime.now(timezone(timedelta(hours=7)))
    header = (f"📊 **Tổng quan Thị trường AI - {now_vn.strftime('%H:%M (%d/%m/%Y)')}**\n"
              f"Nhiệt kế thị trường: **{market_sentiment}**\n")
    level_icons = {"STRONG_BUY": "🚀", "BUY": "✅", "WEAK_BUY": "🟢", "PANIC_SELL": "🆘", "SELL": "❌", "WEAK_SELL": "🔻", "HOLD_BULLISH": "📈", "HOLD_BEARISH": "📉", "HOLD_NEUTRAL": "🤔", "AVOID_CONFLICT": "⚔️", "AVOID_UNCERTAIN": "❓"}
    chunks = []
    for symbol, results in sorted(results_by_symbol.items()):
        price = results[0].get('price', 0)
        chunk_header = f"\n--- **{symbol}** | Giá: `{price:,.4f}` ---"
        chunk_body = []
        for res in sorted(results, key=lambda x: ['1h', '4h', '1d'].index(x['interval'])):
            iv, sub_level, pct = res['interval'], res.get('sub_level', 'N/A'), res.get('pct', 0)
            icon = level_icons.get(sub_level, "❔")
            line1 = f"  • **[{iv}]** {icon} **{sub_level.replace('_', ' ')}** | Dự đoán: **{pct:+.2f}%**"
            opinions = res.get('debug_info', {}).get('expert_opinions', {})
            details = []
            if 'lightgbm' in opinions: details.append(f"LGBM: {opinions['lightgbm']['pct']:.2f}%")
            if 'lstm' in opinions: details.append(f"LSTM: {opinions['lstm']['pct']:.2f}%")
            if 'transformer' in opinions: details.append(f"Tran: {opinions['transformer']['pct']:.2f}%")
            line2 = f"    ```- {', '.join(details)}```" if details else ""
            chunk_body.append(f"{line1}\n{line2}" if line2 else line1)
        chunks.append(f"{chunk_header}\n" + "\n".join(chunk_body))
    return header + "".join(chunks)

def send_discord_message(content: str):
    if not WEBHOOK_URL: return
    max_len = 1900
    for i in range(0, len(content), max_len):
        chunk = content[i:i+max_len]
        try: requests.post(WEBHOOK_URL, json={"content": chunk}, timeout=10)
        except Exception as e: print(f"[ERROR] Lỗi gửi Discord: {e}")

if __name__ == "__main__":
    print("--- Bắt đầu chu trình ML Report (Ultimate Edition - Fixed) ---")
    ensemble = AIEnsemble(DATA_DIR)
    ensemble.load_all_models(SYMBOLS, INTERVALS)
    if not any(ensemble.models.values()):
        print("❌ Không có model nào được tải. Dừng chương trình.")
        sys.exit(1)
    all_predictions = []
    for sym in SYMBOLS:
        for iv in INTERVALS:
            print(f"  -> Đang dự đoán cho {sym} [{iv}]...")
            data_limit = ensemble.sequence_length + 200
            df_new = get_price_data_for_prediction(sym, iv, limit=data_limit)
            if df_new is None or len(df_new) < ensemble.sequence_length + 50:
                print(f"     - ⚠️ Thiếu dữ liệu mới cho {sym} [{iv}]. Bỏ qua.")
                continue
            prediction = ensemble.predict(sym, iv, df_new)
            if prediction:
                json_filepath = os.path.join(LOG_DIR, f"{sym}_{iv}.json")
                atomic_write_json(json_filepath, prediction)
                all_predictions.append(prediction)
    print("\n📊 Đang tạo báo cáo Discord...")
    discord_report = format_discord_report(all_predictions)
    send_discord_message(discord_report)
    print("✅ Đã gửi báo cáo lên Discord.")
    print("\n🎯🎯🎯 Chu trình ML Report đã hoàn tất. 🎯🎯🎯")
