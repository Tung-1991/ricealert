import os
import pandas as pd
import lightgbm as lgb
from datetime import datetime, timedelta, timezone
from indicator import get_price_data as original_get_price_data, calculate_indicators
import requests
from time import sleep

# ===== CẤU HÌNH =====
SYMBOLS = ["ETHUSDT", "BTCUSDT", "SOLUSDT", "INJUSDT", "LINKUSDT"]
INTERVAL = "4h"
HISTORY_LENGTH = 3000
FUTURE_OFFSET = 4
LABEL_THRESHOLD = 0.0075
STEP = 1000  # mỗi lần gọi lấy tối đa 1000 nến

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

# ===== PATCH GET PRICE DATA TẠI CHỖ =====
def get_price_data(symbol: str, interval: str, limit: int = 1000, end_time: datetime = None) -> pd.DataFrame:
    url = "https://api.binance.com/api/v3/klines"
    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit
    }
    if end_time:
        params["endTime"] = int(end_time.timestamp() * 1000)

    resp = requests.get(url, params=params)
    data = resp.json()

    df = pd.DataFrame(data, columns=[
        "timestamp", "open", "high", "low", "close", "volume",
        "close_time", "quote_asset_volume", "number_of_trades",
        "taker_buy_base_vol", "taker_buy_quote_vol", "ignore"
    ])

    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df.set_index("timestamp", inplace=True)

    cols = ["open", "high", "low", "close", "volume"]
    df[cols] = df[cols].astype(float)

    return df

# ===== HÀM GET FULL PRICE HISTORY =====
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

# ===== HÀM XÂY DỰNG DATASET =====
def build_dataset(symbol):
    df = get_full_price_history(symbol, INTERVAL, HISTORY_LENGTH + FUTURE_OFFSET)
    X, y, timestamps = [], [], []

    for i in range(HISTORY_LENGTH):
        past_df = df.iloc[:i + 1 + FUTURE_OFFSET]
        if len(past_df) < FUTURE_OFFSET + 50:
            continue

        try:
            indi = calculate_indicators(past_df.iloc[:-FUTURE_OFFSET], symbol, INTERVAL)
        except Exception:
            continue

        current_price = past_df["close"].iloc[-FUTURE_OFFSET - 1]
        future_price = past_df["close"].iloc[-1]
        pct_change = (future_price - current_price) / current_price
        label = 1 if pct_change >= LABEL_THRESHOLD else 0

        row = {
            "price": indi["price"],
            "ema_20": indi["ema_20"],
            "ema_50": indi["ema_50"],
            "rsi_14": indi["rsi_14"],
            "bb_upper": indi["bb_upper"],
            "bb_lower": indi["bb_lower"],
            "macd_line": indi["macd_line"],
            "macd_signal": indi["macd_signal"],
            "adx": indi["adx"],
            "volume": indi["volume"],
            "vol_ma20": indi["vol_ma20"],
            "cmf": indi["cmf"],
            "fib_0_618": indi["fib_0_618"],
            "entry": indi["trade_plan"]["entry"],
            "tp": indi["trade_plan"]["tp"],
            "sl": indi["trade_plan"]["sl"],
            "is_doji": int(indi["is_doji"])
        }

        X.append(row)
        y.append(label)
        timestamps.append(past_df["timestamp"].iloc[-FUTURE_OFFSET - 1])

    df_X = pd.DataFrame(X)
    df_X["timestamp"] = timestamps
    df_y = pd.Series(y, name="label")
    return df_X, df_y

# ===== TRAIN & SAVE MODEL =====
def train_and_save(symbol, X, y):
    model = lgb.LGBMClassifier(
        n_jobs=-1,
        class_weight='balanced',
        verbose=-1
    )
    model.fit(X.drop(columns=["timestamp"]), y)
    model_path = os.path.join(DATA_DIR, f"model_{symbol}.txt")
    model.booster_.save_model(model_path)
    print(f"✅ {symbol}: Model saved to {model_path}")

    df = X.copy()
    df["label"] = y
    csv_path = os.path.join(DATA_DIR, f"train_data_{symbol}.csv")
    df.to_csv(csv_path, index=False)
    print(f"📁 {symbol}: Data saved to {csv_path}")

# ===== MAIN =====
if __name__ == "__main__":
    for symbol in SYMBOLS:
        print(f"\n🔄 Processing {symbol}...")
        X, y = build_dataset(symbol)
        if len(X) < 50:
            print(f"⚠️  {symbol}: Not enough data to train. Skipped.")
            continue
        train_and_save(symbol, X, y)
    print("\n🎯 Training completed for all symbols.")
