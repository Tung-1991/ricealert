# /root/ricealert/indicator.py (PHIÊN BẢN FINAL - ĐÃ ĐIỀU CHỈNH)
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
    """
    Lấy dữ liệu giá nến từ Binance API.
    """
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
    # Để tính toán các chỉ báo cho nến ĐÃ ĐÓNG gần nhất
    # index -1 là nến hiện tại (đang hình thành), index -2 là nến đã đóng gần nhất
    closed_candle_idx = -2 

    # Nếu không đủ dữ liệu để lấy nến đã đóng hoặc tính toán (ví dụ: cần 51 nến cho EMA50)
    if len(df) < 51:
        print(f"[WARN] indicator.py: Not enough data for {symbol}-{interval} ({len(df)} candles), needs 51.")
        # Trả về một dict với các giá trị mặc định để tránh lỗi ở các module gọi
        return {
            "symbol": symbol, "interval": interval, "price": df["close"].iloc[-1] if not df.empty else 0.0, # Giá hiện tại
            "ema_20": np.nan, "ema_50": np.nan, "trend": "sideway",
            "rsi_14": 50.0, "rsi_divergence": "none",
            "bb_upper": np.nan, "bb_lower": np.nan, "bb_middle": np.nan, "bb_width": np.nan,
            "macd_line": np.nan, "macd_signal": np.nan, "macd_hist": np.nan, "macd_cross": "neutral",
            "adx": 20.0, "volume": np.nan, "vol_ma20": np.nan,
            "cmf": np.nan, "fib_0_618": np.nan, 
            "trade_plan": {"entry": 0, "tp": 0, "sl": 0}, # Giá trị mặc định cho trade_plan
            "is_doji": False, "doji_type": "none",
            "candle_pattern": "none", "tag": "no_data",
            "atr_percent": 2.0, # Giá trị mặc định mới
            "reason": "Thiếu dữ liệu" # Thêm lý do cho debug
        }

    # ---- Basic giá & volume ----
    # 'price' là giá hiện tại (của nến đang hình thành) để kiểm tra SL/TP real-time
    current_live_price = df["close"].iloc[-1] 
    # Các chỉ báo khác dựa trên nến đã đóng
    price = df["close"].iloc[closed_candle_idx] 
    volume = df["volume"].iloc[closed_candle_idx]

    # ---- EMA & Trend ----
    ema_20 = ta.trend.ema_indicator(df["close"], window=20).iloc[closed_candle_idx]
    ema_50 = ta.trend.ema_indicator(df["close"], window=50).iloc[closed_candle_idx]
    # EMA 9 và EMA 200 (nếu có đủ dữ liệu)
    ema_9 = ta.trend.ema_indicator(df["close"], window=9).iloc[closed_candle_idx]
    ema_200 = ta.trend.ema_indicator(df["close"], window=200).iloc[closed_candle_idx] if len(df) >= 200 else np.nan

    # Trend (dựa trên EMA)
    if not np.isnan(ema_9) and not np.isnan(ema_20) and not np.isnan(ema_50):
        if ema_9 > ema_20 > ema_50:
            trend = "uptrend"
        elif ema_9 < ema_20 < ema_50:
            trend = "downtrend"
        else:
            trend = "sideway"
    else:
        trend = "sideway" # Mặc định nếu không đủ EMA

    # ---- RSI & Divergence ----
    rsi_series = ta.momentum.rsi(df["close"], window=14)
    rsi_14 = rsi_series.iloc[closed_candle_idx]
    
    rsi_divergence = "none" # Mặc định
    # Cần đủ dữ liệu để so sánh đỉnh/đáy cho divergence
    if len(df) >= abs(closed_candle_idx) + 1: # Ít nhất 1 nến trước đó cho rsi_divergence
        # Lấy giá trị và RSI của nến hiện tại và nến trước đó (dựa trên nến đóng)
        current_closed_price = df['close'].iloc[closed_candle_idx]
        prev_closed_price = df['close'].iloc[closed_candle_idx - 1]
        current_closed_rsi = rsi_series.iloc[closed_candle_idx]
        prev_closed_rsi = rsi_series.iloc[closed_candle_idx - 1]

        # Simplified Bullish Divergence (Higher Low in RSI, Lower Low in Price)
        if current_closed_price < prev_closed_price and current_closed_rsi > prev_closed_rsi and current_closed_rsi < 50:
            rsi_divergence = "bullish"
        # Simplified Bearish Divergence (Lower High in RSI, Higher High in Price)
        elif current_closed_price > prev_closed_price and current_closed_rsi < prev_closed_rsi and current_closed_rsi > 50:
            rsi_divergence = "bearish"


    # ---- Bollinger Bands ----
    bb = ta.volatility.BollingerBands(df["close"], window=20, window_dev=2)
    bb_upper = bb.bollinger_hband().iloc[closed_candle_idx]
    bb_lower = bb.bollinger_lband().iloc[closed_candle_idx]
    bb_middle = bb.bollinger_mavg().iloc[closed_candle_idx] # Đường giữa (MA)
    bb_width = bb.bollinger_wband().iloc[closed_candle_idx] # Độ rộng dải BB

    # ---- MACD ----
    macd = ta.trend.MACD(df["close"])
    macd_line = macd.macd().iloc[closed_candle_idx]
    macd_signal = macd.macd_signal().iloc[closed_candle_idx]
    macd_hist = macd.macd_diff().iloc[closed_candle_idx] # Histogram

    macd_cross = "neutral"
    if len(macd.macd()) > abs(closed_candle_idx):
        prev_macd_line = macd.macd().iloc[closed_candle_idx - 1]
        prev_macd_signal = macd.macd_signal().iloc[closed_candle_idx - 1]
        if prev_macd_line < prev_macd_signal and macd_line > macd_signal:
            macd_cross = "bullish"
        elif prev_macd_line > prev_macd_signal and macd_line < macd_signal:
            macd_cross = "bearish"
    
    # ---- ADX, Volume MA, CMF ----
    adx = ta.trend.adx(df["high"], df["low"], df["close"], window=14).iloc[closed_candle_idx]
    vol_ma20 = df["volume"].rolling(window=20).mean().iloc[closed_candle_idx]
    
    # CMF cần đủ dữ liệu (window=20)
    if len(df) >= 20:
        cmf = ta.volume.chaikin_money_flow(df["high"], df["low"], df["close"], df["volume"], window=20).iloc[closed_candle_idx]
    else:
        cmf = np.nan

    # ---- ATR (Average True Range) - Đo biến động, dưới dạng phần trăm ----
    atr_percent = 2.0 # Mặc định
    try:
        # ATR cần window. Sử dụng window=14.
        atr_series = ta.volatility.average_true_range(df["high"], df["low"], df["close"], window=14)
        atr_value = atr_series.iloc[closed_candle_idx] # Lấy giá trị ATR cho nến đã đóng gần nhất
        if not pd.isna(atr_value) and price > 0:
            atr_percent = (atr_value / price) * 100
    except Exception as e:
        print(f"[ERROR] indicator.py: Lỗi khi tính ATR: {e}")
    

    # ---- Fibonacci Retracement ----
    fib_0_618 = np.nan # Mặc định
    if len(df) >= 50: # Cần đủ dữ liệu để tìm đỉnh/đáy gần đây
        recent_low = df["low"].iloc[-50:].min()
        recent_high = df["high"].iloc[-50:].max()
        if recent_high > recent_low:
            fib_0_618 = recent_high - (recent_high - recent_low) * 0.618

    # ---- Trade Plan cơ bản (Fibonacci/BB dựa trên nến đã đóng) ----
    entry_plan_price = price
    # Nếu fib có giá trị hợp lệ và nằm gần giá hiện tại, có thể dùng làm entry
    if not np.isnan(fib_0_618) and abs(fib_0_618 - price) / price < 0.02: # trong 2% giá
         entry_plan_price = fib_0_618

    # TP/SL cơ bản dựa trên BB và ATR (từ nến đã đóng)
    # Đây là TP/SL đề xuất của indicator, không phải của Portfolio Manager
    sl_plan = price * 0.98 # Mặc định SL 2%
    tp_plan = price * 1.05 # Mặc định TP 5%
    if not np.isnan(bb_lower) and bb_lower > 0: sl_plan = min(bb_lower, price * 0.98)
    if not np.isnan(bb_upper) and bb_upper > 0: tp_plan = max(bb_upper, price * 1.05)
    
    trade_plan = {"entry": round(entry_plan_price, 8), "tp": round(tp_plan, 8), "sl": round(sl_plan, 8)}


    # ---- Doji & Candle pattern ----
    doji_type = "none" # Mặc định
    candle_pattern = "none" # Mặc định
    
    # Kiểm tra các mẫu hình trên nến đã đóng gần nhất (idx = -2)
    if len(df) >= abs(closed_candle_idx):
        c = df.iloc[closed_candle_idx]
        o, cl, h, l = c["open"], c["close"], c["high"], c["low"]
        body = abs(cl - o)
        candle_range = h - l

        # Nhận diện Doji
        if candle_range > 0 and body <= 0.1 * candle_range: # Điều kiện cơ bản của Doji
            upper_shadow = h - max(o, cl)
            lower_shadow = min(o, cl) - l
            
            if upper_shadow < 0.1 * candle_range and lower_shadow > 0.6 * candle_range:
                doji_type = "dragonfly"
            elif lower_shadow < 0.1 * candle_range and upper_shadow > 0.6 * candle_range:
                doji_type = "gravestone"
            elif body == 0 and upper_shadow == 0 and lower_shadow == 0: # Nến 4 giá
                doji_type = "four_price"
            elif upper_shadow > 0.4 * candle_range and lower_shadow > 0.4 * candle_range:
                doji_type = "long_legged"
            else:
                doji_type = "common"
        
        # Nhận diện các mẫu hình nến khác (cần ít nhất 3 nến)
        if len(df) >= abs(closed_candle_idx) + 1: # Cần nến -3 và -2
            prev_prev_c = df.iloc[closed_candle_idx - 2]
            prev_c = df.iloc[closed_candle_idx - 1]
            curr_c = df.iloc[closed_candle_idx] # Nến đang xét là nến -2

            # Bullish Engulfing
            if (curr_c["close"] > curr_c["open"] and # Nến hiện tại là xanh
                curr_c["open"] < prev_c["close"] and # Mở cửa hiện tại thấp hơn đóng cửa trước đó
                curr_c["close"] > prev_c["open"] and # Đóng cửa hiện tại cao hơn mở cửa trước đó (bao trùm thân nến)
                prev_c["close"] < prev_c["open"]): # Nến trước đó là đỏ
                candle_pattern = "bullish_engulfing"
            # Bearish Engulfing
            elif (curr_c["close"] < curr_c["open"] and # Nến hiện tại là đỏ
                  curr_c["open"] > prev_c["close"] and # Mở cửa hiện tại cao hơn đóng cửa trước đó
                  curr_c["close"] < prev_c["open"] and # Đóng cửa hiện tại thấp hơn mở cửa trước đó (bao trùm thân nến)
                  prev_c["close"] > prev_c["open"]): # Nến trước đó là xanh
                candle_pattern = "bearish_engulfing"
            # Hammer (Chỉ đơn giản hóa, cần thêm logic xác nhận xu hướng giảm)
            elif (curr_c["close"] > curr_c["open"] and # Nến xanh
                  (curr_c["high"] - max(curr_c["open"], curr_c["close"])) < (max(curr_c["open"], curr_c["close"]) - curr_c["low"]) * 0.1 and # Bóng trên nhỏ
                  (max(curr_c["open"], curr_c["close"]) - curr_c["low"]) > 2 * (abs(curr_c["close"] - curr_c["open"]))): # Bóng dưới dài
                candle_pattern = "hammer"
            # Shooting Star (Chỉ đơn giản hóa, cần thêm logic xác nhận xu hướng tăng)
            elif (curr_c["close"] < curr_c["open"] and # Nến đỏ
                  (min(curr_c["open"], curr_c["close"]) - curr_c["low"]) < (curr_c["high"] - min(curr_c["open"], curr_c["close"])) * 0.1 and # Bóng dưới nhỏ
                  (curr_c["high"] - min(curr_c["open"], curr_c["close"])) > 2 * (abs(curr_c["close"] - curr_c["open"]))): # Bóng trên dài
                candle_pattern = "shooting_star"


    # ---- TAG (Tổng hợp trạng thái) ----
    tag = "swing" # Mặc định
    if rsi_divergence != "none": tag = "rsi_div"
    elif doji_type != "none": tag = "doji_pattern" # Đổi tên cho rõ ràng hơn
    elif candle_pattern != "none": tag = "candle_pattern_detected"
    elif volume > 2 * vol_ma20 and vol_ma20 > 0: tag = "vol_spike"
    elif trend == "downtrend": tag = "trend_down"
    elif trend == "uptrend": tag = "trend_up"
    elif macd_cross in ("bullish", "bearish"): tag = "macd_cross"

    result = {
        "symbol": symbol, "interval": interval, 
        "price": current_live_price, # <-- Đây là giá hiện tại (live price)
        "closed_candle_price": price, # <-- Giá đóng cửa của nến đã hoàn thành
        "ema_9": ema_9, "ema_20": ema_20, "ema_50": ema_50, "ema_200": ema_200, "trend": trend,
        "rsi_14": rsi_14, "rsi_divergence": rsi_divergence,
        "bb_upper": bb_upper, "bb_lower": bb_lower, "bb_middle": bb_middle, "bb_width": bb_width,
        "macd_line": macd_line, "macd_signal": macd_signal, "macd_hist": macd_hist, "macd_cross": macd_cross,
        "adx": adx, "volume": volume, "vol_ma20": vol_ma20,
        "cmf": cmf, "atr_percent": atr_percent, # Đã thêm ATR
        "fib_0_618": fib_0_618, "trade_plan": trade_plan, # trade_plan cơ bản của indicator
        "doji_type": doji_type, "candle_pattern": candle_pattern, "tag": tag,
        "is_doji": doji_type != "none"
		
    }

    # ---- Clean NaN / Inf values in result dict ----
    # Đảm bảo không có NaN/Inf trong kết quả trả về
    for k, v in result.items():
        if isinstance(v, float) and (pd.isna(v) or np.isinf(v)):
            result[k] = 0.0 # Thay thế bằng 0.0 hoặc giá trị mặc định phù hợp
    result["entry_price"] = result.get("closed_candle_price", result["price"])
    return result

if __name__ == "__main__":
    # Ví dụ sử dụng:
    sample_symbol = "ETHUSDT" # Hoặc bất kỳ cặp nào bạn muốn thử
    sample_interval = "1h"
    
    print(f"Đang lấy dữ liệu cho {sample_symbol} - {sample_interval}...")
    df_sample = get_price_data(sample_symbol, sample_interval, limit=200)
    
    if not df_sample.empty:
        print("Đang tính toán chỉ báo...")
        calculated_results = calculate_indicators(df_sample, sample_symbol, sample_interval)
        
        print("\n=== Kết quả chỉ báo cho nến cuối cùng ===")
        for key, value in calculated_results.items():
            if isinstance(value, (int, float)):
                # Kiểm tra NaN/Inf trước khi format
                if pd.isna(value) or np.isinf(value):
                    print(f"{key}: NaN/Inf (set to 0.0 by cleaning)")
                else:
                    print(f"{key}: {value:.4f}") # Tăng độ chính xác khi hiển thị
            else:
                print(f"{key}: {value}")
    else:
        print("Không thể lấy dữ liệu để tính chỉ báo.")
