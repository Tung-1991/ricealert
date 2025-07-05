# /root/ricealert/trainer.py (Đã cập nhật)
import os, json, joblib, warnings, requests
import pandas as pd, numpy as np, lightgbm as lgb, ta
from datetime import datetime, timedelta, timezone
from time import sleep
from dotenv import load_dotenv
from sklearn.model_selection import train_test_split

warnings.filterwarnings("ignore", category=UserWarning)
load_dotenv()

SYMBOLS   = os.getenv("SYMBOLS",  "LINKUSDT,TAOUSDT,ETHUSDT,AVAXUSDT,INJUSDT,SUIUSDT,FETUSDT").split(",")
INTERVALS = os.getenv("INTERVALS", "1h,4h,1d").split(",")

# ... (Các hàm helper như write_json, _load_map không đổi) ...
def write_json(path: str, data: dict):
    with open(path, "w") as f: json.dump(data, f, indent=2)

def _load_map(name: str, fallback: dict) -> dict:
    raw = os.getenv(name)
    if raw:
        try: return json.loads(raw)
        except json.JSONDecodeError: print(f"[WARN] Failed to parse {name} from .env, using fallback.")
    return fallback

HIST_MAP = _load_map("HISTORY_LENGTH_MAP", {"1h":3500, "4h":2500, "1d":1500})
OFFS_MAP = _load_map("FUTURE_OFFSET_MAP",  {"1h":6,    "4h":4,    "1d":2})
LABEL_MAP= _load_map("LABEL_ATR_FACTOR_MAP",{"1h":0.65, "4h":0.75,"1d":0.85})
STEP_MAP = _load_map("STEP_MAP",           {"1h":1000, "4h":1000, "1d":1000})
MIN_MAP  = _load_map("MIN_SAMPLE_MAP",     {"1h":1000,  "4h":800,  "1d":400})

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)


def get_price_data(symbol: str, interval: str, limit: int, end_time: datetime = None) -> pd.DataFrame:
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    if end_time:
        params["endTime"] = int(end_time.timestamp() * 1000)
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list) or not data:
            return pd.DataFrame()
        df = pd.DataFrame(data, columns=["timestamp", "open", "high", "low", "close", "volume", "close_time", "quote_asset_volume", "number_of_trades", "taker_buy_base_asset_volume", "taker_buy_quote_asset_volume", "ignore"])
        df = df.iloc[:, :6]
        df.columns = ["timestamp", "open", "high", "low", "close", "volume"]
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df.set_index("timestamp", inplace=True)
        df = df.astype(float)
        return df
    except Exception as e:
        print(f"[ERROR] Exception in get_price_data for {symbol} {interval}: {e}")
        return pd.DataFrame()

def get_full_price_history(symbol: str, interval: str, total: int, step: int) -> pd.DataFrame:
    chunks, rows_fetched = [], 0
    end_time = datetime.now(timezone.utc)
    while rows_fetched < total:
        part = get_price_data(symbol, interval, step, end_time)
        if part.empty: break
        chunks.insert(0, part)
        rows_fetched += len(part)
        end_time = part.index[0] - timedelta(milliseconds=1)
        sleep(0.25)
    if not chunks: return pd.DataFrame()
    return pd.concat(chunks).drop_duplicates().sort_index().iloc[-total:]

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
    
    # 🔥 THAY ĐỔI 3: Đồng bộ logic Trend về EMA 20/50
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

    # Xử lý One-Hot Encoding
    original_macd_cross = out['macd_cross'].copy()
    original_trend = out['trend'].copy()
    categorical_cols = ['macd_cross', 'trend']
    out = pd.get_dummies(out, columns=categorical_cols, prefix=categorical_cols, dtype=float)
    out['macd_cross'] = original_macd_cross
    out['trend'] = original_trend
    
    # Dọn dẹp cuối cùng
    out.replace([np.inf, -np.inf], np.nan, inplace=True)
    out.bfill(inplace=True)
    out.ffill(inplace=True)
    out.fillna(0, inplace=True)

    return out

def create_labels_and_targets(df: pd.DataFrame, fut_off: int, atr_factor: float):
    # ... (Hàm này không thay đổi) ...
    df_copy = df.copy()
    future_price = df_copy['close'].shift(-fut_off)
    atr_threshold = atr_factor * df_copy['atr']
    df_copy['label'] = 1
    df_copy.loc[(future_price - df_copy['close']) > atr_threshold, 'label'] = 2
    df_copy.loc[(df_copy['close'] - future_price) > atr_threshold, 'label'] = 0
    atr_smooth = df_copy['atr'].rolling(window=fut_off).mean() + 1e-9
    df_copy['reg_target'] = (future_price - df_copy['close']) / atr_smooth
    df_copy['reg_target'] = df_copy['reg_target'].clip(lower=-10, upper=10)
    return df_copy.dropna()

def train_and_save(symbol: str, interval: str, df: pd.DataFrame):
    # ... (Hàm này được cập nhật với is_unbalance=True) ...
    base_features = ['open', 'high', 'low', 'close', 'volume', 'macd_cross', 'trend']
    label_cols = ['label', 'reg_target']
    all_possible_features = [col for col in df.columns if col not in base_features + label_cols]
    features_to_use = [f for f in all_possible_features if df[f].var() > 1e-6]
    
    X = df[features_to_use]
    y_clf = df['label']
    y_reg = df['reg_target']
    
    X_train, X_test, y_train_clf, y_test_clf, y_train_reg, y_test_reg = train_test_split(
        X, y_clf, y_reg, test_size=0.15, shuffle=False
    )
    
    # 🔥 THAY ĐỔI 0: Thêm 'is_unbalance': True để xử lý mất cân bằng dữ liệu
    clf_params = {
        'objective': 'multiclass', 'num_class': 3, 'metric': 'multi_logloss',
        'n_estimators': 1500, 'learning_rate': 0.03, 'feature_fraction': 0.8,
        'bagging_fraction': 0.8, 'bagging_freq': 1, 'lambda_l1': 0.1, 'lambda_l2': 0.1,
        'num_leaves': 31, 'verbose': -1, 'n_jobs': -1, 'seed': 42, 'boosting_type': 'gbdt',
        'is_unbalance': True 
    }
    clf = lgb.LGBMClassifier(**clf_params)
    clf.fit(X_train, y_train_clf, eval_set=[(X_test, y_test_clf)], callbacks=[lgb.early_stopping(100, verbose=False)])
    
    reg_params = { 'objective': 'regression_l1', 'metric': 'mae', 'n_estimators': 1500, 'learning_rate': 0.03, 'feature_fraction': 0.8, 'bagging_fraction': 0.8, 'bagging_freq': 1, 'num_leaves': 31, 'verbose': -1, 'n_jobs': -1, 'seed': 42 }
    reg = lgb.LGBMRegressor(**reg_params)
    reg.fit(X_train, y_train_reg, eval_set=[(X_test, y_test_reg)], callbacks=[lgb.early_stopping(100, verbose=False)])
    
    joblib.dump(clf, os.path.join(DATA_DIR, f"model_{symbol}_clf_{interval}.pkl"), compress=3)
    joblib.dump(reg, os.path.join(DATA_DIR, f"model_{symbol}_reg_{interval}.pkl"), compress=3)
    
    meta = { "features": features_to_use, "trained_at": datetime.now(timezone.utc).isoformat(), "atr_factor_threshold": LABEL_MAP.get(interval, 0.75), "future_offset": OFFS_MAP.get(interval, 4) }
    write_json(os.path.join(DATA_DIR, f"meta_{symbol}_{interval}.json"), meta)
    
    counts = y_clf.value_counts()
    print(f"✅ {symbol} [{interval}] | Trained with {len(features_to_use)} features on {len(df)} samples (S:{counts.get(0,0)}, H:{counts.get(1,0)}, B:{counts.get(2,0)})")

if __name__ == "__main__":
    # ... (Vòng lặp main không thay đổi) ...
    for sym in SYMBOLS:
        for iv in INTERVALS:
            hist_len = HIST_MAP.get(iv, 3000)
            fut_off = OFFS_MAP.get(iv, 4)
            atr_factor = LABEL_MAP.get(iv, 0.75)
            step_size = STEP_MAP.get(iv, 1000)
            min_rows = MIN_MAP.get(iv, 500)
            print(f"\n🔄 Building dataset for {sym} [{iv}]...")
            try:
                df_raw = get_full_price_history(sym, iv, hist_len + fut_off, step_size)
                if len(df_raw) < min_rows:
                    print(f"❌ Skipping {sym} [{iv}] – chỉ có {len(df_raw)} rows, dưới ngưỡng tối thiểu {min_rows}.")
                    continue
                df_features = add_features(df_raw)
                df_dataset = create_labels_and_targets(df_features, fut_off, atr_factor)
                if len(df_dataset) < min_rows / 2:
                    print(f"⚠️  Not enough usable samples for {sym} [{iv}] after creating labels → skipping.")
                    continue
                print(f"🔬 Training models for {sym} [{iv}]...")
                train_and_save(sym, iv, df_dataset)
            except Exception as e:
                print(f"[CRITICAL] Failed to train {sym} [{iv}]: {e}")
                import traceback
                print(traceback.format_exc())
    print("\n🎯 Training completed.")
