def check_signal(indicators: dict) -> tuple:
    rsi = indicators.get('rsi_14')
    macd = indicators.get('macd_line')
    macd_signal = indicators.get('macd_signal')
    bb_upper = indicators.get('bb_upper')
    bb_lower = indicators.get('bb_lower')
    price = indicators.get('price')
    ema = indicators.get('ema_20')
    volume = indicators.get('volume')
    vol_ma = indicators.get('vol_ma20')
    doji_raw = indicators.get('doji_type')
    doji = doji_raw.lower() if isinstance(doji_raw, str) else ""

    macd_cross = indicators.get('macd_cross')
    adx = indicators.get('adx')
    rsi_div = indicators.get('rsi_divergence')
    trend = indicators.get('trend')
    cmf = indicators.get('cmf')
    candle = indicators.get('candle_pattern')
    interval = indicators.get("interval")
    rsi_1h = indicators.get("rsi_1h")
    rsi_4h = indicators.get("rsi_4h")
    fibo_0618 = indicators.get("fibo_0618")

    required_fields = [rsi, macd, macd_signal, bb_upper, bb_lower, price, ema, volume, vol_ma,
                       macd_cross, adx, rsi_1h, rsi_4h, trend, cmf]
    if any(v is None for v in required_fields):
        indicators["tag"] = "avoid"
        return "HOLD", "Thiếu dữ liệu"

    reasons = []
    signal_type = "HOLD"

    # ========== CRITICAL ========== (nới nhẹ điều kiện)
    if rsi_1h < 32 and rsi_4h < 32:
        reasons.append("RSI 1h và 4h cùng < 32 → BUY đảo chiều mạnh")
        signal_type = "CRITICAL"
    elif rsi_1h > 68 and rsi_4h > 68:
        reasons.append("RSI 1h và 4h cùng > 68 → SELL đảo chiều mạnh")
        signal_type = "CRITICAL"
    elif (
        rsi < 32 and macd_cross == "bullish"
        and doji in ["dragonfly", "long_legged"] and adx > 20
        and price < bb_lower and volume > vol_ma
    ):
        reasons.append("RSI < 32 + MACD bullish + Doji + BB dưới + volume tốt")
        signal_type = "CRITICAL"
    elif (
        rsi > 68 and macd_cross == "bearish"
        and doji in ["gravestone", "long_legged"] and adx > 20
        and price > bb_upper and volume > vol_ma
    ):
        reasons.append("RSI > 68 + MACD bearish + Doji + BB trên + volume cao")
        signal_type = "CRITICAL"

    # ========== WARNING ========== (nới volume, RSI, ADX)
    elif (
        rsi_div in ["bullish", "bearish"]
        and abs(volume - vol_ma) > vol_ma
        and trend
        and (rsi < 45 or rsi > 55)
    ):
        reasons.append(f"Phân kỳ RSI {rsi_div} + volume bất thường + trend rõ ràng")
        signal_type = "WARNING"
    elif (
        volume > 1.5 * vol_ma and macd_cross in ["bullish", "bearish"]
        and (rsi > 55 or rsi < 45)
    ):
        reasons.append("Breakout volume + MACD cross + RSI mạnh")
        signal_type = "WARNING"

    # ========== ALERT ========== (nới RSI, BB, ADX)
    elif rsi > 68 and price >= bb_upper * 0.995 and adx > 18:
        reasons.append("RSI cao + BB gần trên + ADX > 18")
        signal_type = "ALERT"
    elif rsi < 32 and price <= bb_lower * 1.005 and adx > 18:
        reasons.append("RSI thấp + BB gần dưới + ADX > 18")
        signal_type = "ALERT"
    elif rsi > 68 and macd_cross == "bearish" and price >= bb_upper * 0.995:
        reasons.append("RSI cao + MACD bearish + BB gần trên")
        signal_type = "ALERT"
    elif rsi < 32 and macd_cross == "bullish" and price <= bb_lower * 1.005:
        reasons.append("RSI thấp + MACD bullish + BB gần dưới")
        signal_type = "ALERT"

    # ========== WATCHLIST ==========
    elif doji in ["long_legged", "common"] and abs(volume - vol_ma) > 1.2 * vol_ma:
        reasons.append("Doji + Volume khác biệt")
        signal_type = "WATCHLIST"
    elif fibo_0618 and abs(price - fibo_0618) / fibo_0618 < 0.01:
        reasons.append("Giá gần Fibo 0.618")
        signal_type = "WATCHLIST"
    elif adx < 15:
        reasons.append("ADX < 15 → sideway")
        signal_type = "WATCHLIST"
    elif trend == "uptrend" and rsi > 60:
        reasons.append("Trend tăng + RSI cao")
        signal_type = "WATCHLIST"
    elif trend == "downtrend" and rsi < 40:
        reasons.append("Trend giảm + RSI thấp")
        signal_type = "WATCHLIST"
    elif cmf > 0.05:
        reasons.append("CMF > 0.05 → dòng tiền vào")
        signal_type = "WATCHLIST"
    elif cmf < -0.05:
        reasons.append("CMF < -0.05 → dòng tiền rút")
        signal_type = "WATCHLIST"
    elif abs(price - ema) / ema < 0.005:
        reasons.append("Giá gần EMA20 → theo dõi")
        signal_type = "WATCHLIST"

    # ========== Lọc tín hiệu yếu theo khung 1h ==========
    if signal_type != "HOLD" and interval == "1h" and volume < 0.6 * vol_ma:
        indicators["tag"] = "avoid"
        return "HOLD", "Volume thấp hơn 60% MA20 → bỏ cảnh báo"

    # ========== Gán tag ==========
    tag = "hold"
    if trend == "downtrend" and rsi > 70 and rsi_div == "bearish":
        tag = "short_strong"
    elif trend == "downtrend" and rsi > 60:
        tag = "short_soft"
    elif trend == "uptrend" and rsi > 60 and cmf > 0.05:
        tag = "buy_strong"
    elif adx > 25 and rsi_1h > 50 and rsi_4h > 50:
        tag = "swing_trade"
    elif volume > 1.5 * vol_ma:
        tag = "scalp"
    elif fibo_0618 and abs(price - fibo_0618) / fibo_0618 < 0.01:
        tag = "fibo_retest"
    elif adx < 15 or cmf < -0.05:
        tag = "avoid"
    elif trend == "uptrend" and volume > 2 * vol_ma and rsi > 70 and macd_cross == "bullish":
        tag = "fomo_breakout"

    indicators["tag"] = tag
    return signal_type, " + ".join(reasons)
