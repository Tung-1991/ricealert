# /root/ricealert/indicator.py (PHIÊN BẢN 5.0 - NÂNG CẤP CHO TACTIC MỚI - BẢN ĐẦY ĐỦ)
import pandas as pd
import ta
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import numpy as np
from datetime import datetime

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
def get_price_data(symbol: str, interval: str, limit: int = 200) -> pd.DataFrame:
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
        
        if df.empty:
            print(f"[WARN] indicator.py: get_price_data returned empty DataFrame for {symbol}-{interval}.")
        return df
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] indicator.py: Network or API error for {symbol}-{interval}: {e}")
        return pd.DataFrame()
    except Exception as e:
        print(f"[ERROR] indicator.py: An unexpected error occurred while fetching data for {symbol}-{interval}: {e}")
        return pd.DataFrame()

# ---------- Tính indicator ---------- #
def calculate_indicators(df: pd.DataFrame, symbol: str, interval: str) -> dict:
    closed_candle_idx = -2

    if len(df) < 51:
        print(f"[WARN] indicator.py: Not enough data for {symbol}-{interval} ({len(df)} candles), needs 51.")
        # Trả về cấu trúc đầy đủ với giá trị mặc định để đảm bảo tương thích
        return {
            "symbol": symbol, "interval": interval, "price": df["close"].iloc[-1] if not df.empty else 0.0,
            "ema_9": 0.0, "ema_20": 0.0, "ema_50": 0.0, "ema_200": 0.0, "trend": "sideway",
            "rsi_14": 50.0, "rsi_divergence": "none",
            "bb_upper": 0.0, "bb_lower": 0.0, "bb_middle": 0.0, "bb_width": 0.0,
            "macd_line": 0.0, "macd_signal": 0.0, "macd_hist": 0.0, "macd_cross": "neutral",
            "adx": 20.0, "volume": 0.0, "vol_ma20": 0.0,
            "cmf": 0.0, "fib_0_618": 0.0, "trade_plan": {"entry": 0, "tp": 0, "sl": 0},
            "is_doji": False, "doji_type": "none", "candle_pattern": "none", "tag": "no_data",
            "atr": 0.0, "atr_percent": 2.0,
            "support_level": 0.0, "resistance_level": 0.0,
            "breakout_signal": "none",
            "reason": "Thiếu dữ liệu"
        }

    # ---- Các tính toán cơ bản ----
    current_live_price = df["close"].iloc[-1]
    price = df["close"].iloc[closed_candle_idx]
    volume = df["volume"].iloc[closed_candle_idx]

    # ---- EMA & Trend (Giữ nguyên) ----
    ema_20 = ta.trend.ema_indicator(df["close"], window=20).iloc[closed_candle_idx]
    ema_50 = ta.trend.ema_indicator(df["close"], window=50).iloc[closed_candle_idx]
    ema_9 = ta.trend.ema_indicator(df["close"], window=9).iloc[closed_candle_idx]
    ema_200 = ta.trend.ema_indicator(df["close"], window=200).iloc[closed_candle_idx] if len(df) >= 200 else np.nan
    trend = "sideway"
    if not np.isnan(ema_9) and not np.isnan(ema_20) and not np.isnan(ema_50):
        if ema_9 > ema_20 > ema_50: trend = "uptrend"
        elif ema_9 < ema_20 < ema_50: trend = "downtrend"

    # ---- RSI & Divergence (Giữ nguyên) ----
    rsi_series = ta.momentum.rsi(df["close"], window=14)
    rsi_14 = rsi_series.iloc[closed_candle_idx]
    rsi_divergence = "none"
    if len(df) >= abs(closed_candle_idx) + 1:
        current_closed_price = df['close'].iloc[closed_candle_idx]
        prev_closed_price = df['close'].iloc[closed_candle_idx - 1]
        current_closed_rsi = rsi_series.iloc[closed_candle_idx]
        prev_closed_rsi = rsi_series.iloc[closed_candle_idx - 1]
        if current_closed_price < prev_closed_price and current_closed_rsi > prev_closed_rsi and current_closed_rsi < 50: rsi_divergence = "bullish"
        elif current_closed_price > prev_closed_price and current_closed_rsi < prev_closed_rsi and current_closed_rsi > 50: rsi_divergence = "bearish"

    # ---- Bollinger Bands (Giữ nguyên) ----
    bb = ta.volatility.BollingerBands(df["close"], window=20, window_dev=2)
    bb_upper = bb.bollinger_hband().iloc[closed_candle_idx]
    bb_lower = bb.bollinger_lband().iloc[closed_candle_idx]
    bb_middle = bb.bollinger_mavg().iloc[closed_candle_idx]
    bb_width = bb.bollinger_wband().iloc[closed_candle_idx]

    # ---- MACD (Giữ nguyên) ----
    macd = ta.trend.MACD(df["close"])
    macd_line = macd.macd().iloc[closed_candle_idx]
    macd_signal = macd.macd_signal().iloc[closed_candle_idx]
    macd_hist = macd.macd_diff().iloc[closed_candle_idx]
    macd_cross = "neutral"
    if len(macd.macd()) > abs(closed_candle_idx):
        prev_macd_line = macd.macd().iloc[closed_candle_idx - 1]
        prev_macd_signal = macd.macd_signal().iloc[closed_candle_idx - 1]
        if prev_macd_line < prev_macd_signal and macd_line > macd_signal: macd_cross = "bullish"
        elif prev_macd_line > prev_macd_signal and macd_line < macd_signal: macd_cross = "bearish"
    
    # ---- ADX, Volume MA, CMF (Giữ nguyên) ----
    adx = ta.trend.adx(df["high"], df["low"], df["close"], window=14).iloc[closed_candle_idx]
    vol_ma20 = df["volume"].rolling(window=20).mean().iloc[closed_candle_idx]
    cmf = ta.volume.chaikin_money_flow(df["high"], df["low"], df["close"], df["volume"], window=20).iloc[closed_candle_idx] if len(df) >= 20 else np.nan

    # ---- ATR (Đã sửa lỗi) ----
    atr_series = ta.volatility.average_true_range(df["high"], df["low"], df["close"], window=14)
    atr_value = atr_series.iloc[closed_candle_idx]
    atr_percent = (atr_value / price) * 100 if price > 0 and not pd.isna(atr_value) else 2.0

    # ---- Fibonacci & Trade Plan (Giữ nguyên) ----
    fib_0_618 = np.nan
    if len(df) >= 50:
        recent_low = df["low"].iloc[-50:].min()
        recent_high = df["high"].iloc[-50:].max()
        if recent_high > recent_low:
            fib_0_618 = recent_high - (recent_high - recent_low) * 0.618
    entry_plan_price = price
    if not np.isnan(fib_0_618) and abs(fib_0_618 - price) / price < 0.02: entry_plan_price = fib_0_618
    sl_plan = price * 0.98
    tp_plan = price * 1.05
    if not np.isnan(bb_lower) and bb_lower > 0: sl_plan = min(bb_lower, price * 0.98)
    if not np.isnan(bb_upper) and bb_upper > 0: tp_plan = max(bb_upper, price * 1.05)
    trade_plan = {"entry": round(entry_plan_price, 8), "tp": round(tp_plan, 8), "sl": round(sl_plan, 8)}

    # ---- Doji & Candle Pattern (Giữ nguyên) ----
    doji_type = "none"; candle_pattern = "none"
    if len(df) >= abs(closed_candle_idx):
        c = df.iloc[closed_candle_idx]
        o, cl, h, l = c["open"], c["close"], c["high"], c["low"]
        body = abs(cl - o); candle_range = h - l
        if candle_range > 0 and body <= 0.1 * candle_range:
            upper_shadow = h - max(o, cl); lower_shadow = min(o, cl) - l
            if upper_shadow < 0.1 * candle_range and lower_shadow > 0.6 * candle_range: doji_type = "dragonfly"
            elif lower_shadow < 0.1 * candle_range and upper_shadow > 0.6 * candle_range: doji_type = "gravestone"
            elif body == 0 and upper_shadow == 0 and lower_shadow == 0: doji_type = "four_price"
            elif upper_shadow > 0.4 * candle_range and lower_shadow > 0.4 * candle_range: doji_type = "long_legged"
            else: doji_type = "common"
    if len(df) >= abs(closed_candle_idx) + 1:
        prev_c = df.iloc[closed_candle_idx - 1]; curr_c = df.iloc[closed_candle_idx]
        if (curr_c["close"] > curr_c["open"] and curr_c["open"] < prev_c["close"] and curr_c["close"] > prev_c["open"] and prev_c["close"] < prev_c["open"]): candle_pattern = "bullish_engulfing"
        elif (curr_c["close"] < curr_c["open"] and curr_c["open"] > prev_c["close"] and curr_c["close"] < prev_c["open"] and prev_c["close"] > prev_c["open"]): candle_pattern = "bearish_engulfing"
        elif (curr_c["close"] > curr_c["open"] and (curr_c["high"] - max(curr_c["open"], curr_c["close"])) < (max(curr_c["open"], curr_c["close"]) - curr_c["low"]) * 0.1 and (max(curr_c["open"], curr_c["close"]) - curr_c["low"]) > 2 * (abs(curr_c["close"] - curr_c["open"]))): candle_pattern = "hammer"
        elif (curr_c["close"] < curr_c["open"] and (min(curr_c["open"], curr_c["close"]) - curr_c["low"]) < (curr_c["high"] - min(curr_c["open"], curr_c["close"])) * 0.1 and (curr_c["high"] - min(curr_c["open"], curr_c["close"])) > 2 * (abs(curr_c["close"] - curr_c["open"]))): candle_pattern = "shooting_star"

    # ---- TAG (Giữ nguyên) ----
    tag = "swing"
    if rsi_divergence != "none": tag = "rsi_div"
    elif doji_type != "none": tag = "doji_pattern"
    elif candle_pattern != "none": tag = "candle_pattern_detected"
    elif volume > 2 * vol_ma20 and vol_ma20 > 0: tag = "vol_spike"
    elif trend == "downtrend": tag = "trend_down"
    elif trend == "uptrend": tag = "trend_up"
    elif macd_cross in ("bullish", "bearish"): tag = "macd_cross"

    # ==============================================================================
    # ================= 🚀 NÂNG CẤP V5.0 - CHỈ BÁO MỚI 🚀 ======================
    # ==============================================================================

    # ---- 1. Hỗ Trợ & Kháng Cự (Support & Resistance) ----
    recent_data = df.iloc[-51:-1] 
    support_level = recent_data["low"].min()
    resistance_level = recent_data["high"].max()

    # ---- 2. Tín hiệu Đột Phá (Breakout Signal) ----
    breakout_signal = "none"
    avg_bb_width = bb.bollinger_wband().rolling(50).mean().iloc[closed_candle_idx]
    is_squeezing = bb_width < avg_bb_width * 0.85
    closed_price = df["close"].iloc[closed_candle_idx]
    price_breaks_upper = closed_price > bb_upper
    price_breaks_lower = closed_price < bb_lower
    volume_confirmed = vol_ma20 > 0 and volume > vol_ma20 * 1.8

    if is_squeezing and price_breaks_upper and volume_confirmed:
        breakout_signal = "bullish"
    elif is_squeezing and price_breaks_lower and volume_confirmed:
        breakout_signal = "bearish"
    
    # ==============================================================================
    # ======================= KẾT QUẢ TRẢ VỀ (Đầy đủ) ==========================
    # ==============================================================================
    result = {
        # --- Dữ liệu cũ ---
        "symbol": symbol, "interval": interval, "price": current_live_price, "closed_candle_price": price,
        "ema_9": ema_9, "ema_20": ema_20, "ema_50": ema_50, "ema_200": ema_200, "trend": trend,
        "rsi_14": rsi_14, "rsi_divergence": rsi_divergence,
        "bb_upper": bb_upper, "bb_lower": bb_lower, "bb_middle": bb_middle, "bb_width": bb_width,
        "macd_line": macd_line, "macd_signal": macd_signal, "macd_hist": macd_hist, "macd_cross": macd_cross,
        "adx": adx, "volume": volume, "vol_ma20": vol_ma20, "cmf": cmf,
        "atr": atr_value, "atr_percent": atr_percent,
        "fib_0_618": fib_0_618, "trade_plan": trade_plan,
        "doji_type": doji_type, "candle_pattern": candle_pattern, "tag": tag, "is_doji": doji_type != "none",
        
        # --- Dữ liệu mới V5.0 ---
        "support_level": support_level,
        "resistance_level": resistance_level,
        "breakout_signal": breakout_signal,
    }

    # Dọn dẹp giá trị NaN/inf để đảm bảo an toàn
    for k, v in result.items():
        if isinstance(v, (int, float)) and (pd.isna(v) or np.isinf(v)):
            result[k] = 0.0
    result["entry_price"] = result.get("closed_candle_price", result["price"])
    return result

if __name__ == "__main__":
    sample_symbol = "ETHUSDT"; sample_interval = "1h"
    print(f"Đang lấy dữ liệu cho {sample_symbol} - {sample_interval}...")
    df_sample = get_price_data(sample_symbol, sample_interval, limit=200)
    
    if not df_sample.empty:
        print("Đang tính toán chỉ báo...")
        calculated_results = calculate_indicators(df_sample, sample_symbol, sample_interval)
        print("\n=== Kết quả chỉ báo cho nến đã đóng gần nhất ===")
        for key, value in calculated_results.items():
            if key in ["support_level", "resistance_level", "breakout_signal"]:
                 print(f"**{key.upper()}**: {value}")
