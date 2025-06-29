import os
import pandas as pd
import lightgbm as lgb
import joblib
import json
from datetime import datetime, timedelta, timezone
from indicator import get_price_data as original_get_price_data, calculate_indicators
import requests
from time import sleep
from dotenv import load_dotenv

# ===== LOAD ENV =====
load_dotenv()

SYMBOLS = os.getenv("SYMBOLS", "LINKUSDT").split(",")
INTERVALS = os.getenv("INTERVALS", "1h,4h,1d").split(",")
HISTORY_LENGTH = int(os.getenv("HISTORY_LENGTH", 3000))
FUTURE_OFFSET = int(os.getenv("FUTURE_OFFSET", 4))
LABEL_THRESHOLD = float(os.getenv("LABEL_THRESHOLD", 0.0075))
STEP = int(os.getenv("STEP", 1000))

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

def get_price_data(symbol: str, interval: str, limit: int = 1000, end_time: datetime = None) -> pd.DataFrame:
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    if end_time:
        params["endTime"] = int(end_time.timestamp() * 1000)
    resp = requests.get(url, params=params)
    data = resp.json()
    df = pd.DataFrame(data, columns=[
        "timestamp", "open", "high", "low", "close", "volume",
        "close_time", "quote_asset_volume", "number_of_trades",
        "taker_buy_base_vol", "taker_buy_quote_vol", "ignore"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df.set_index("timestamp", inplace=True)
    cols = ["open", "high", "low", "close", "volume"]
    df[cols] = df[cols].astype(float)
    return df

def get_full_price_history(symbol, interval, total_candles):
    all_data = []
    end_time = datetime.now(timezone.utc)
    while len(all_data) * STEP < total_candles:
        df = get_price_data(symbol, interval, limit=STEP, end_time=end_time)
        if df.empty:
            break
        all_data.insert(0, df)
        end_time = df.index[0] - timedelta(minutes=1)
        sleep(0.1)
    return pd.concat(all_data).reset_index().iloc[-total_candles:]

def build_dataset(symbol, interval):
    df = get_full_price_history(symbol, interval, HISTORY_LENGTH + FUTURE_OFFSET)
    X, y_clf, y_reg, timestamps = [], [], [], []
    for i in range(HISTORY_LENGTH):
        past_df = df.iloc[:i + 1 + FUTURE_OFFSET]
        if len(past_df) < FUTURE_OFFSET + 50:
            continue
        try:
            indi = calculate_indicators(past_df.iloc[:-FUTURE_OFFSET], symbol, interval)
        except Exception:
            continue
        current_price = past_df["close"].iloc[-FUTURE_OFFSET - 1]
        future_price = past_df["close"].iloc[-1]
        pct_change = (future_price - current_price) / current_price
        label = 1 if pct_change >= LABEL_THRESHOLD else 0
        row = {
            "price": indi["price"], "ema_20": indi["ema_20"], "ema_50": indi["ema_50"],
            "rsi_14": indi["rsi_14"], "bb_upper": indi["bb_upper"], "bb_lower": indi["bb_lower"],
            "macd_line": indi["macd_line"], "macd_signal": indi["macd_signal"], "adx": indi["adx"],
            "volume": indi["volume"], "vol_ma20": indi["vol_ma20"], "cmf": indi["cmf"],
            "fib_0_618": indi["fib_0_618"], "entry": indi["trade_plan"]["entry"],
            "tp": indi["trade_plan"]["tp"], "sl": indi["trade_plan"]["sl"],
            "is_doji": int(indi["is_doji"])
        }
        X.append(row)
        y_clf.append(label)
        y_reg.append(pct_change)
        timestamps.append(past_df["timestamp"].iloc[-FUTURE_OFFSET - 1])
    df_X = pd.DataFrame(X)
    df_X["timestamp"] = timestamps
    return df_X, pd.Series(y_clf, name="label"), pd.Series(y_reg, name="reg_target")

def train_and_save(symbol, interval, X, y_clf, y_reg):
    features = X.drop(columns=["timestamp"]).columns.tolist()
    clf = lgb.LGBMClassifier(n_jobs=-1, class_weight='balanced', verbose=-1)
    clf.fit(X[features], y_clf)
    reg = lgb.LGBMRegressor(n_jobs=-1, verbose=-1)
    reg.fit(X[features], y_reg)

    joblib.dump(clf, os.path.join(DATA_DIR, f"model_{symbol}_clf_{interval}.pkl"))
    joblib.dump(reg, os.path.join(DATA_DIR, f"model_{symbol}_reg_{interval}.pkl"))

    meta_path = os.path.join(DATA_DIR, f"meta_{symbol}_{interval}.json")
    with open(meta_path, "w") as f:
        json.dump({"features": features, "threshold": 0.6}, f)

    df = X.copy()
    df["label"] = y_clf
    df["reg_target"] = y_reg
    df.to_csv(os.path.join(DATA_DIR, f"train_data_{symbol}_{interval}.csv"), index=False)
    print(f"✅ {symbol} [{interval}]: Models and data saved.")

if __name__ == "__main__":
    for symbol in SYMBOLS:
        for interval in INTERVALS:
            print(f"\n🔄 Processing {symbol} [{interval}]...")
            X, y_clf, y_reg = build_dataset(symbol, interval)
            if len(X) < 50:
                print(f"⚠️  {symbol} [{interval}]: Not enough data. Skipped.")
                continue
            train_and_save(symbol, interval, X, y_clf, y_reg)
    print("\n🎯 Training completed.")
