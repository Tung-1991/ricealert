# indicator.py
import pandas as pd
import ta
import requests
from datetime import datetime

def get_price_data(symbol: str, interval: str, limit: int = 100) -> pd.DataFrame:
    url = f"https://api.binance.com/api/v3/klines"
    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit
    }
    response = requests.get(url, params=params)
    data = response.json()

    df = pd.DataFrame(data, columns=[
        "timestamp", "open", "high", "low", "close", "volume",
        "close_time", "quote_asset_volume", "number_of_trades",
        "taker_buy_base_vol", "taker_buy_quote_vol", "ignore"
    ])

    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df.set_index("timestamp", inplace=True)

    # Chuyển sang float
    cols = ["open", "high", "low", "close", "volume"]
    df[cols] = df[cols].astype(float)

    return df


def calculate_indicators(df: pd.DataFrame, symbol: str, interval: str) -> dict:
    df = df.copy()
    df.dropna(inplace=True)

    # ⚠️ Dùng nến -2 cho các chỉ báo phụ thuộc nến đóng
    price = df["close"].iloc[-2]
    volume = df["volume"].iloc[-2]

    # EMA20
    ema_20 = ta.trend.ema_indicator(df["close"], window=20).iloc[-1]

    # RSI14
    rsi_14 = ta.momentum.rsi(df["close"], window=14).iloc[-1]

    # Bollinger Bands
    bb = ta.volatility.BollingerBands(close=df["close"], window=20, window_dev=2)
    bb_upper = bb.bollinger_hband().iloc[-1]
    bb_lower = bb.bollinger_lband().iloc[-1]

    # MACD
    macd = ta.trend.MACD(close=df["close"], window_slow=26, window_fast=12, window_sign=9)
    macd_line = macd.macd().iloc[-1]
    macd_signal = macd.macd_signal().iloc[-1]

    # Volume MA20
    vol_ma20 = df["volume"].rolling(window=20).mean().iloc[-1]

    # Fibonacci Retracement (dựa trên toàn khung)
    recent_low = df["low"].min()
    recent_high = df["high"].max()
    fib_0_618 = recent_high - (recent_high - recent_low) * 0.618

    # Phát hiện loại Doji
    doji_type = None
    for i in range(-6, -1):
        c = df.iloc[i]
        open_price = c["open"]
        close_price = c["close"]
        high = c["high"]
        low = c["low"]
        body = abs(close_price - open_price)
        candle_range = high - low
        upper = high - max(open_price, close_price)
        lower = min(open_price, close_price) - low

        if candle_range != 0 and body <= 0.1 * candle_range:
            if upper < 0.1 * candle_range and lower > 0.6 * candle_range:
                doji_type = "dragonfly"
            elif lower < 0.1 * candle_range and upper > 0.6 * candle_range:
                doji_type = "gravestone"
            elif body == 0 and upper == 0 and lower == 0:
                doji_type = "four_price"
            elif upper > 0.4 * candle_range and lower > 0.4 * candle_range:
                doji_type = "long_legged"
            else:
                doji_type = "common"
            break

    return {
        "symbol": symbol,
        "interval": interval,
        "price": price,
        "ema_20": ema_20,
        "rsi_14": rsi_14,
        "bb_upper": bb_upper,
        "bb_lower": bb_lower,
        "macd_line": macd_line,
        "macd_signal": macd_signal,
        "volume": volume,
        "vol_ma20": vol_ma20,
        "fib_0_618": fib_0_618,
        "is_doji": doji_type is not None,
        "doji_type": doji_type
    }
# indicator.py
import pandas as pd
import ta
import requests
from datetime import datetime

def get_price_data(symbol: str, interval: str, limit: int = 100) -> pd.DataFrame:
    url = f"https://api.binance.com/api/v3/klines"
    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit
    }
    response = requests.get(url, params=params)
    data = response.json()

    df = pd.DataFrame(data, columns=[
        "timestamp", "open", "high", "low", "close", "volume",
        "close_time", "quote_asset_volume", "number_of_trades",
        "taker_buy_base_vol", "taker_buy_quote_vol", "ignore"
    ])

    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df.set_index("timestamp", inplace=True)

    # Chuyển sang float
    cols = ["open", "high", "low", "close", "volume"]
    df[cols] = df[cols].astype(float)

    return df


def calculate_indicators(df: pd.DataFrame, symbol: str, interval: str) -> dict:
    df = df.copy()
    df.dropna(inplace=True)

    # ⚠️ Dùng nến -2 cho các chỉ báo phụ thuộc nến đóng
    price = df["close"].iloc[-2]
    volume = df["volume"].iloc[-2]

    # EMA20
    ema_20 = ta.trend.ema_indicator(df["close"], window=20).iloc[-1]

    # RSI14
    rsi_14 = ta.momentum.rsi(df["close"], window=14).iloc[-1]

    # Bollinger Bands
    bb = ta.volatility.BollingerBands(close=df["close"], window=20, window_dev=2)
    bb_upper = bb.bollinger_hband().iloc[-1]
    bb_lower = bb.bollinger_lband().iloc[-1]

    # MACD
    macd = ta.trend.MACD(close=df["close"], window_slow=26, window_fast=12, window_sign=9)
    macd_line = macd.macd().iloc[-1]
    macd_signal = macd.macd_signal().iloc[-1]

    # Volume MA20
    vol_ma20 = df["volume"].rolling(window=20).mean().iloc[-1]

    # Fibonacci Retracement (dựa trên toàn khung)
    recent_low = df["low"].min()
    recent_high = df["high"].max()
    fib_0_618 = recent_high - (recent_high - recent_low) * 0.618

    # Phát hiện loại Doji
    doji_type = None
    for i in range(-6, -1):
        c = df.iloc[i]
        open_price = c["open"]
        close_price = c["close"]
        high = c["high"]
        low = c["low"]
        body = abs(close_price - open_price)
        candle_range = high - low
        upper = high - max(open_price, close_price)
        lower = min(open_price, close_price) - low

        if candle_range != 0 and body <= 0.1 * candle_range:
            if upper < 0.1 * candle_range and lower > 0.6 * candle_range:
                doji_type = "dragonfly"
            elif lower < 0.1 * candle_range and upper > 0.6 * candle_range:
                doji_type = "gravestone"
            elif body == 0 and upper == 0 and lower == 0:
                doji_type = "four_price"
            elif upper > 0.4 * candle_range and lower > 0.4 * candle_range:
                doji_type = "long_legged"
            else:
                doji_type = "common"
            break

    return {
        "symbol": symbol,
        "interval": interval,
        "price": price,
        "ema_20": ema_20,
        "rsi_14": rsi_14,
        "bb_upper": bb_upper,
        "bb_lower": bb_lower,
        "macd_line": macd_line,
        "macd_signal": macd_signal,
        "volume": volume,
        "vol_ma20": vol_ma20,
        "fib_0_618": fib_0_618,
        "is_doji": doji_type is not None,
        "doji_type": doji_type
    }

