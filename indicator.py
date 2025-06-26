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

    cols = ["open", "high", "low", "close", "volume"]
    df[cols] = df[cols].astype(float)

    return df

def calculate_indicators(df: pd.DataFrame, symbol: str, interval: str) -> dict:
    df = df.copy()
    df.dropna(inplace=True)

    price = df["close"].iloc[-2]
    volume = df["volume"].iloc[-2]

    # EMA
    ema_20 = ta.trend.ema_indicator(df["close"], window=20).iloc[-1]
    ema_50 = ta.trend.ema_indicator(df["close"], window=50).iloc[-1]
    trend = "uptrend" if ema_20 > ema_50 else "downtrend"

    # RSI14
    rsi_series = ta.momentum.rsi(df["close"], window=14)
    rsi_14 = rsi_series.iloc[-1]

    # RSI Divergence
    rsi_divergence = None
    try:
        recent_prices = df["close"].iloc[-5:]
        recent_rsis = rsi_series.iloc[-5:]
        if recent_prices.iloc[-1] > recent_prices.iloc[0] and recent_rsis.iloc[-1] < recent_rsis.iloc[0]:
            rsi_divergence = "bearish"
        elif recent_prices.iloc[-1] < recent_prices.iloc[0] and recent_rsis.iloc[-1] > recent_rsis.iloc[0]:
            rsi_divergence = "bullish"
    except:
        pass

    # BB
    bb = ta.volatility.BollingerBands(close=df["close"], window=20, window_dev=2)
    bb_upper = bb.bollinger_hband().iloc[-1]
    bb_lower = bb.bollinger_lband().iloc[-1]

    # MACD
    macd = ta.trend.MACD(close=df["close"])
    macd_line = macd.macd().iloc[-1]
    macd_signal = macd.macd_signal().iloc[-1]
    prev_macd_line = macd.macd().iloc[-2]
    prev_macd_signal = macd.macd_signal().iloc[-2]
    if prev_macd_line < prev_macd_signal and macd_line > macd_signal:
        macd_cross = "bullish"
    elif prev_macd_line > prev_macd_signal and macd_line < macd_signal:
        macd_cross = "bearish"
    else:
        macd_cross = "neutral"

    # ADX
    adx = ta.trend.adx(df["high"], df["low"], df["close"], window=14).iloc[-1]

    # Volume MA20
    vol_ma20 = df["volume"].rolling(window=20).mean().iloc[-1]

    # CMF
    cmf = ta.volume.chaikin_money_flow(df["high"], df["low"], df["close"], df["volume"], window=20).iloc[-1]

    # Fibo
    recent_low = df["low"].min()
    recent_high = df["high"].max()
    fib_0_618 = recent_high - (recent_high - recent_low) * 0.618

    # Trade Plan
    current_price = df["close"].iloc[-2]
    entry = fib_0_618 if fib_0_618 < current_price else current_price
    sl = min(bb_lower, entry * 0.98)
    tp = max(bb_upper, entry * 1.05)

    trade_plan = {
        "entry": round(entry, 4),
        "tp": round(tp, 4),
        "sl": round(sl, 4)
    }

    # Doji Detection
    doji_type = None
    for i in range(-6, -1):
        c = df.iloc[i]
        o, cl, h, l = c["open"], c["close"], c["high"], c["low"]
        body = abs(cl - o)
        candle_range = h - l
        upper = h - max(o, cl)
        lower = min(o, cl) - l
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

    # Candlestick Pattern
    candle_pattern = None
    prev = df.iloc[-3]
    curr = df.iloc[-2]
    if curr["close"] > curr["open"] and prev["close"] < prev["open"] \
       and curr["close"] > prev["open"] and curr["open"] < prev["close"]:
        candle_pattern = "bullish_engulfing"
    elif curr["close"] < curr["open"] and prev["close"] > prev["open"] \
       and curr["open"] > prev["close"] and curr["close"] < prev["open"]:
        candle_pattern = "bearish_engulfing"
    elif curr["close"] > curr["open"] and (curr["low"] == min(curr["open"], curr["close"])) and (curr["high"] - curr["close"]) > 2 * (curr["close"] - curr["open"]):
        candle_pattern = "hammer"
    elif curr["close"] < curr["open"] and (curr["high"] == max(curr["open"], curr["close"])) and (curr["low"] - curr["close"]) > 2 * (curr["open"] - curr["close"]):
        candle_pattern = "shooting_star"

    # Gán TAG đại diện cho tín hiệu kỹ thuật
    if rsi_divergence:
        tag = "rsi_div"
    elif doji_type and trend in ["uptrend", "downtrend"]:
        tag = "doji_reversal"
    elif volume > 2 * vol_ma20:
        tag = "vol_spike"
    elif trend == "downtrend":
        tag = "trend_down"
    elif trend == "uptrend":
        tag = "trend_up"
    elif macd_cross in ["bullish", "bearish"]:
        tag = "macd_cross"
    else:
        tag = "swing"

    return {
        "symbol": symbol,
        "interval": interval,
        "price": price,
        "ema_20": ema_20,
        "ema_50": ema_50,
        "trend": trend,
        "rsi_14": rsi_14,
        "rsi_divergence": rsi_divergence,
        "bb_upper": bb_upper,
        "bb_lower": bb_lower,
        "macd_line": macd_line,
        "macd_signal": macd_signal,
        "macd_cross": macd_cross,
        "adx": adx,
        "volume": volume,
        "vol_ma20": vol_ma20,
        "cmf": cmf,
        "fib_0_618": fib_0_618,
        "trade_plan": trade_plan,
        "is_doji": doji_type is not None,
        "doji_type": doji_type,
        "candle_pattern": candle_pattern,
        "tag": tag
    }

