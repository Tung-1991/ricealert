# trainer.py - AI Model Trainer with fallback
import os, json, joblib, warnings, requests
import pandas as pd, numpy as np, lightgbm as lgb, ta
from datetime import datetime, timedelta, timezone
from time import sleep
from dotenv import load_dotenv
from sklearn.model_selection import train_test_split

warnings.filterwarnings("ignore", category=UserWarning)
load_dotenv()

SYMBOLS   = os.getenv("SYMBOLS",  "LINKUSDT,TAOUSDT").split(",")
INTERVALS = os.getenv("INTERVALS", "1h,4h,1d").split(",")

def write_json(path: str, data: dict):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

def _load_map(name: str, fallback: dict) -> dict:
    raw = os.getenv(name)
    if raw:
        try: return json.loads(raw)
        except json.JSONDecodeError: print(f"[WARN] Failed to parse {name} from .env, using fallback.")
    return fallback

HIST_MAP = _load_map("HISTORY_LENGTH_MAP", {"1h":3000, "4h":2000, "1d":1000})
OFFS_MAP = _load_map("FUTURE_OFFSET_MAP",  {"1h":4,    "4h":2,    "1d":1})
LABEL_MAP= _load_map("LABEL_THRESHOLD_MAP",{"1h":0.0075,"4h":0.01,"1d":0.015})
STEP_MAP = _load_map("STEP_MAP",           {"1h":1000, "4h":1000, "1d":1000})
MIN_MAP  = _load_map("MIN_SAMPLE_MAP",     {"1h":500,  "4h":400,  "1d":300})

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

def get_price_data(symbol: str, interval: str, limit: int, end_time: datetime = None) -> pd.DataFrame:
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    if end_time:
        params["endTime"] = int(end_time.timestamp() * 1000)

    try:
        data = requests.get(url, params=params, timeout=10).json()
        if not isinstance(data, list) or not data:
            msg = data['msg'] if isinstance(data, dict) and 'msg' in data else 'Empty or invalid response'
            print(f"[WARN] Failed to fetch data for {symbol} {interval}: {msg}")
            return pd.DataFrame()

        df = pd.DataFrame(data, columns=["timestamp", "open", "high", "low", "close", "volume",
                                         "close_time", "quote_asset_volume", "number_of_trades",
                                         "taker_buy_base_asset_volume", "taker_buy_quote_asset_volume", "ignore"])
        df = df.iloc[:, :6]
        df.columns = ["timestamp", "open", "high", "low", "close", "volume"]
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df.set_index("timestamp", inplace=True)
        for col in df.columns:
            df[col] = pd.to_numeric(df[col])
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
        sleep(0.2)
    if not chunks: return pd.DataFrame()
    return pd.concat(chunks).drop_duplicates().iloc[-total:]

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

def create_labels_and_targets(df: pd.DataFrame, fut_off: int, label_th: float):
    future_price = df['close'].shift(-fut_off)
    pct_change = (future_price - df['close']) / (df['close'] + 1e-9)
    df['label'] = 1
    df.loc[pct_change >= label_th, 'label'] = 2
    df.loc[pct_change <= -label_th, 'label'] = 0
    df['reg_target'] = pct_change / (df['atr'].rolling(window=fut_off).mean() + 1e-9)
    return df.dropna()

def train_and_save(symbol: str, interval: str, df: pd.DataFrame):
    base_features = ['open', 'high', 'low', 'close', 'volume']
    label_cols = ['label', 'reg_target']
    features_to_use = [col for col in df.columns if col not in base_features + label_cols]

    X = df[features_to_use]
    y_clf = df['label']
    y_reg = df['reg_target']
    X_train, X_test, y_train_clf, y_test_clf = train_test_split(X, y_clf, test_size=0.15, shuffle=False)

    clf = lgb.LGBMClassifier(objective='multiclass', num_class=3, metric='multi_logloss',
                             n_estimators=1000, learning_rate=0.05, feature_fraction=0.8,
                             bagging_fraction=0.8, bagging_freq=1, lambda_l1=0.1, lambda_l2=0.1,
                             num_leaves=31, verbose=-1, n_jobs=-1, seed=42)
    clf.fit(X_train, y_train_clf, eval_set=[(X_test, y_test_clf)],
            callbacks=[lgb.early_stopping(50, verbose=False)])

    reg = lgb.LGBMRegressor(objective='regression_l1', metric='mae', n_estimators=1000,
                            learning_rate=0.05, feature_fraction=0.8, bagging_fraction=0.8,
                            bagging_freq=1, num_leaves=31, verbose=-1, n_jobs=-1, seed=42)
    reg.fit(X, y_reg)

    joblib.dump(clf, os.path.join(DATA_DIR, f"model_{symbol}_clf_{interval}.pkl"), compress=3)
    joblib.dump(reg, os.path.join(DATA_DIR, f"model_{symbol}_reg_{interval}.pkl"), compress=3)

    meta = {"features": features_to_use, "trained_at": datetime.now(timezone.utc).isoformat(),
            "label_threshold": LABEL_MAP.get(interval, 0.01), "future_offset": OFFS_MAP.get(interval, 4)}
    write_json(os.path.join(DATA_DIR, f"meta_{symbol}_{interval}.json"), meta)

    counts = y_clf.value_counts()
    print(f"✅ {symbol} [{interval}] | {len(df)} samples (SELL:{counts.get(0,0)}, HOLD:{counts.get(1,0)}, BUY:{counts.get(2,0)})")

# ==============================================================================

if __name__ == "__main__":
    for sym in SYMBOLS:
        for iv in INTERVALS:
            hist_len = HIST_MAP.get(iv, 3000)
            fut_off = OFFS_MAP.get(iv, 4)
            label_th = LABEL_MAP.get(iv, 0.01)
            step_size = STEP_MAP.get(iv, 1000)
            min_rows = MIN_MAP.get(iv, 200)

            print(f"\n🔄 Building dataset for {sym} [{iv}]...")
            try:
                df_raw = get_full_price_history(sym, iv, hist_len + fut_off, step_size)
                if len(df_raw) < min_rows:
                    print(f"❌ Skipping {sym} [{iv}] – chỉ có {len(df_raw)} rows, dưới ngưỡng tối thiểu {min_rows}.")
                    continue
                elif len(df_raw) < hist_len:
                    print(f"⚠️  {sym} [{iv}] thiếu dữ liệu (chỉ có {len(df_raw)} / {hist_len}) → vẫn train.")

                df_features = add_features(df_raw)
                df_dataset = create_labels_and_targets(df_features, fut_off, label_th)
                if len(df_dataset) < 200:
                    print(f"⚠️  Not enough usable samples for {sym} [{iv}] → skipping.")
                    continue

                print(f"🔬 Training models for {sym} [{iv}]...")
                train_and_save(sym, iv, df_dataset)

            except Exception as e:
                print(f"[CRITICAL] Failed to train {sym} [{iv}]: {e}")
                import traceback
                print(traceback.format_exc())

    print("\n🎯 Training completed.")
