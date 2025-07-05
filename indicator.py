# indicator.py (PHIÊN BẢN HOÀN CHỈNH - CÓ SIDWAY & ĐỒNG BỘ)
import pandas as pd
import ta
import requests
from datetime import datetime
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import numpy as np

# ---------- Session + Retry ---------- #
retry_strategy = Retry(
    total=3,
    backoff_factor=0.3,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET"],
)
session = requests.Session()
session.mount("https://", HTTPAdapter(max_retries=retry_strategy))

# ---------- Fetch giá ---------- #
def get_price_data(symbol: str, interval: str, limit: int = 100) -> pd.DataFrame:
    # Giữ limit 100 vì trend 20/50 không cần nhiều dữ liệu như 50/200
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    try:
        resp = session.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        df = pd.DataFrame(data, columns=["timestamp","open","high","low","close","volume","close_time","quote_asset_volume","number_of_trades","taker_buy_base_vol","taker_buy_quote_vol","ignore"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df.set_index("timestamp", inplace=True)
        df[["open", "high", "low", "close", "volume"]] = df[["open", "high", "low", "close", "volume"]].astype(float)
        return df
    except Exception as e:
        print(f"[ERROR] indicator.py:get_price_data failed for {symbol}-{interval}: {e}")
        return pd.DataFrame()

# ---------- Tính indicator ---------- #
def calculate_indicators(df: pd.DataFrame, symbol: str, interval: str) -> dict:
    # Cập nhật điều kiện kiểm tra dữ liệu cho EMA 50
    if len(df) < 51:
        print(f"[WARN] indicator.py: Not enough data for {symbol}-{interval} ({len(df)} candles), needs 51.")
        price = df["close"].iloc[-1] if not df.empty else 0.0
        return { "symbol": symbol, "interval": interval, "price": price, "tag": "avoid" }

    idx = -2 # Lấy nến đã đóng gần nhất
    if len(df) < abs(idx): return {}

    # ---- Basic giá & volume ----
    price = df["close"].iloc[idx]
    volume = df["volume"].iloc[idx]

    # ---- EMA & Trend (ĐỒNG BỘ VỚI TRAINER.PY) ----
    # <<< SỬA LỖI: THÊM LẠI TRẠNG THÁI 'SIDEWAY' CHO NHẤT QUÁN VÀ MẠNH MẼ
    ema_20 = ta.trend.ema_indicator(df["close"], window=20).iloc[idx]
    ema_50 = ta.trend.ema_indicator(df["close"], window=50).iloc[idx]
    
    if ema_20 > ema_50:
        trend = "uptrend"
    elif ema_20 < ema_50:
        trend = "downtrend"
    else:
        trend = "sideway"
    # <<< KẾT THÚC SỬA LỖI

    # ---- RSI & Divergence (Giữ nguyên logic gốc chi tiết của bạn) ----
    rsi_series = ta.momentum.rsi(df["close"], window=14)
    rsi_14 = rsi_series.iloc[idx]

    lookback = 4
    rsi_divergence = None
    if len(rsi_series) >= abs(idx) + lookback:
        recent_prices = df["close"].iloc[idx - lookback + 1 : idx + 1]
        recent_rsis = rsi_series.iloc[idx - lookback + 1 : idx + 1]
        if len(recent_prices) == lookback and len(recent_rsis) == lookback:
            if recent_prices.iloc[-1] > recent_prices.iloc[0] and recent_rsis.iloc[-1] < recent_rsis.iloc[0]:
                rsi_divergence = "bearish"
            elif recent_prices.iloc[-1] < recent_prices.iloc[0] and recent_rsis.iloc[-1] > recent_rsis.iloc[0]:
                rsi_divergence = "bullish"

    # ---- Bollinger Bands (Giữ nguyên) ----
    bb = ta.volatility.BollingerBands(df["close"], window=20, window_dev=2)
    bb_upper = bb.bollinger_hband().iloc[idx]
    bb_lower = bb.bollinger_lband().iloc[idx]

    # ---- MACD (Giữ nguyên) ----
    macd = ta.trend.MACD(df["close"])
    macd_line = macd.macd().iloc[idx]
    macd_signal = macd.macd_signal().iloc[idx]

    if len(macd.macd()) > abs(idx):
        prev_macd_line = macd.macd().iloc[idx - 1]
        prev_macd_signal = macd.macd_signal().iloc[idx - 1]
        macd_cross = ("bullish" if prev_macd_line < prev_macd_signal and macd_line > macd_signal else "bearish" if prev_macd_line > prev_macd_signal and macd_line < macd_signal else "neutral")
    else:
        macd_cross = "neutral"

    # ---- ADX, Volume MA, CMF (Giữ nguyên) ----
    adx = ta.trend.adx(df["high"], df["low"], df["close"], window=14).iloc[idx]
    vol_ma20 = df["volume"].rolling(window=20).mean().iloc[idx]
    cmf = ta.volume.chaikin_money_flow(df["high"], df["low"], df["close"], df["volume"], window=20).iloc[idx]

    # ---- Fibonacci & Trade Plan (Giữ nguyên) ----
    if len(df) >= 50:
        recent_low = df["low"].iloc[-50:].min()
        recent_high = df["high"].iloc[-50:].max()
        fib_0_618 = recent_high - (recent_high - recent_low) * 0.618
    else:
        fib_0_618 = 0.0
    entry = fib_0_618 if 0 < fib_0_618 < price else price
    sl = min(bb_lower, entry * 0.98) if bb_lower > 0 else entry * 0.98
    tp = max(bb_upper, entry * 1.05) if bb_upper > 0 else entry * 1.05
    trade_plan = {"entry": round(entry, 8), "tp": round(tp, 8), "sl": round(sl, 8)}

    # ---- Doji & Candle pattern (Giữ nguyên) ----
    doji_type, candle_pattern = None, None
    if len(df) >= 6:
        for i in range(-6, -1):
            c = df.iloc[i]; o, cl, h, l = c["open"], c["close"], c["high"], c["low"]
            body, r = abs(cl - o), h - l
            if r and body <= 0.1 * r:
                upper, lower = h - max(o, cl), min(o, cl) - l
                if upper < 0.1 * r and lower > 0.6 * r: doji_type = "dragonfly"
                elif lower < 0.1 * r and upper > 0.6 * r: doji_type = "gravestone"
                break
        prev, curr = df.iloc[-3], df.iloc[-2]
        if (curr["close"] > curr["open"] < prev["close"] and curr["close"] > prev["open"] and curr["open"] < prev["close"]): candle_pattern = "bullish_engulfing"
        elif (curr["close"] < curr["open"] > prev["close"] and curr["open"] > prev["close"] and curr["close"] < prev["open"]): candle_pattern = "bearish_engulfing"
    
    # ---- TAG (Giữ nguyên) ----
    if rsi_divergence: tag = "rsi_div"
    elif doji_type and trend in ("uptrend", "downtrend"): tag = "doji_reversal"
    elif volume > 2 * vol_ma20 and vol_ma20 > 0: tag = "vol_spike"
    elif trend == "downtrend": tag = "trend_down"
    elif trend == "uptrend": tag = "trend_up"
    elif macd_cross in ("bullish", "bearish"): tag = "macd_cross"
    else: tag = "swing"

    result = {
        "symbol": symbol, "interval": interval, "price": price,
        "ema_20": ema_20, "ema_50": ema_50, "trend": trend,
        "rsi_14": rsi_14, "rsi_divergence": rsi_divergence,
        "bb_upper": bb_upper, "bb_lower": bb_lower,
        "macd_line": macd_line, "macd_signal": macd_signal, "macd_cross": macd_cross,
        "adx": adx, "volume": volume, "vol_ma20": vol_ma20,
        "cmf": cmf, "fib_0_618": fib_0_618, "trade_plan": trade_plan,
        "is_doji": doji_type is not None, "doji_type": doji_type,
        "candle_pattern": candle_pattern, "tag": tag,
    }

    # ---- Clean NaN / Inf values in result dict ----
    for k, v in result.items():
        if isinstance(v, float) and (pd.isna(v) or np.isinf(v)):
            result[k] = 0.0

    return result
