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

    # New indicators
    macd_cross = indicators.get('macd_cross')
    adx = indicators.get('adx')
    rsi_div = indicators.get('rsi_divergence')
    trend = indicators.get('trend')
    cmf = indicators.get('cmf')
    candle = indicators.get('candle_pattern')
    interval = indicators.get("interval")
    rsi_1h = indicators.get("rsi_1h")
    rsi_4h = indicators.get("rsi_4h")

    if any(v is None for v in [rsi, macd, macd_signal, bb_upper, bb_lower, price, ema, volume, vol_ma, macd_cross, adx]):
        return "HOLD", "Thiếu dữ liệu"

    reasons = []

    # ====== Rule CRITICAL ======
    if rsi < 30 and macd_cross == "bullish" and doji == "dragonfly" and adx > 20:
        reasons.append("RSI < 30 + MACD crossover lên + Dragonfly Doji + Trend mạnh")
    if rsi > 70 and macd_cross == "bearish" and doji == "gravestone" and adx > 20:
        reasons.append("RSI > 70 + MACD crossover xuống + Gravestone Doji + Trend mạnh")
    if rsi_1h and rsi_4h and rsi_1h < 30 and rsi_4h < 30:
        reasons.append("RSI 1h và 4h cùng < 30 → xu hướng đảo chiều mạnh (BUY)")
    if rsi_1h and rsi_4h and rsi_1h > 70 and rsi_4h > 70:
        reasons.append("RSI 1h và 4h cùng > 70 → xu hướng đảo chiều mạnh (SELL)")

    # ====== Rule ALERT ======
    if rsi > 70 and price >= bb_upper and adx > 20:
        reasons.append("RSI quá cao + giá chạm BB trên + trend mạnh")
    if rsi < 30 and price <= bb_lower and adx > 20:
        reasons.append("RSI quá thấp + giá chạm BB dưới + trend mạnh")
    if doji in ["long_legged", "common"] and abs(volume - vol_ma) > 1.5 * vol_ma:
        reasons.append("Doji + Volume spike bất thường")
    if rsi_div == "bullish":
        reasons.append("Phân kỳ RSI dương → khả năng đảo chiều tăng")
    if rsi_div == "bearish":
        reasons.append("Phân kỳ RSI âm → khả năng đảo chiều giảm")
    if volume > 2 * vol_ma:
        reasons.append("Khối lượng tăng đột biến → breakout tiềm năng")
    if adx < 15:
        reasons.append("Trend yếu (ADX < 15) → thị trường sideway, dễ nhiễu")
    if rsi > 70 and macd_cross == "bearish" and price >= bb_upper:
        reasons.append("RSI cao + MACD bearish + giá chạm BB trên → đảo chiều giảm")
    if rsi < 30 and macd_cross == "bullish" and price <= bb_lower:
        reasons.append("RSI thấp + MACD bullish + giá chạm BB dưới → đảo chiều tăng")

    # ====== Trend + CMF confirm ======
    if trend == "downtrend" and rsi < 40:
        reasons.append("Xu hướng giảm → hạn chế vào lệnh BUY")
    if trend == "uptrend" and rsi > 60:
        reasons.append("Xu hướng tăng → xác nhận BUY mạnh")
    if cmf and cmf > 0.05:
        reasons.append("CMF > 0.05 → dòng tiền vào mạnh")
    if cmf and cmf < -0.05:
        reasons.append("CMF < -0.05 → dòng tiền rút mạnh")

    # ====== Candlestick xác nhận ======
    if candle == "bullish_engulfing":
        reasons.append("Bullish Engulfing → đảo chiều tăng")
    if candle == "bearish_engulfing":
        reasons.append("Bearish Engulfing → đảo chiều giảm")
    if candle == "hammer":
        reasons.append("Hammer → đáy tiềm năng")
    if candle == "shooting_star":
        reasons.append("Shooting Star → đỉnh tiềm năng")

    # ====== Tổng hợp kết luận ======
    signal_type = "HOLD"
    if any("RSI" in r or "MACD" in r or "Phân kỳ" in r for r in reasons if "Doji" in r or "trend" in r):
        signal_type = "CRITICAL"
    elif reasons:
        signal_type = "ALERT"
    else:
        return "HOLD", "Không tín hiệu rõ ràng"

    # ====== Lọc ALERT 1h nếu volume thấp ======
    if signal_type == "ALERT" and interval == "1h":
        if volume < 0.6 * vol_ma:
            return "HOLD", "Volume thấp hơn 60% MA20 → bỏ ALERT"

    # ====== Phân loại SCALP / SWING ======
    tag = "SCALP"
    if adx and adx > 25 and rsi_1h and rsi_4h:
        if (rsi_1h > 50 and rsi_4h > 50) or (rsi_1h < 50 and rsi_4h < 50):
            tag = "SWING"

    return signal_type, f"{tag} → {' + '.join(reasons)}"
