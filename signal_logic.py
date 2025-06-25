def check_signal(indicators: dict) -> tuple:
    """Phân tích kỹ thuật → trả về tín hiệu (HOLD, ALERT, CRITICAL) và lý do"""

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

    # For advanced signal
    rsi_1h = indicators.get("rsi_1h")
    rsi_4h = indicators.get("rsi_4h")

    # Nếu thiếu dữ liệu → HOLD
    if any(v is None for v in [rsi, macd, macd_signal, bb_upper, bb_lower, price, ema, volume, vol_ma, macd_cross, adx]):
        return "HOLD", "Thiếu dữ liệu"

    reasons = []

    # ====== Rule CRITICAL ======
    if rsi < 30 and macd_cross == "bullish" and doji == "dragonfly" and adx > 20:
        reasons.append("RSI < 30 + MACD crossover lên + Dragonfly Doji + Trend mạnh")
    if rsi > 70 and macd_cross == "bearish" and doji == "gravestone" and adx > 20:
        reasons.append("RSI > 70 + MACD crossover xuống + Gravestone Doji + Trend mạnh")

    # RSI cả 1h và 4h đều quá bán → tín hiệu mạnh
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

    # Breakout volume mạnh
    if volume > 2 * vol_ma:
        reasons.append("Khối lượng tăng đột biến → breakout tiềm năng")
    if adx < 15:
        reasons.append("Trend yếu (ADX < 15) → thị trường sideway, dễ nhiễu")

    # Hội tụ RSI + MACD + BB
    if rsi > 70 and macd_cross == "bearish" and price >= bb_upper:
        reasons.append("RSI cao + MACD bearish + giá chạm BB trên → đảo chiều giảm")
    if rsi < 30 and macd_cross == "bullish" and price <= bb_lower:
        reasons.append("RSI thấp + MACD bullish + giá chạm BB dưới → đảo chiều tăng")

    # ====== Tổng hợp kết luận ======
    if any("RSI" in r or "MACD" in r or "Phân kỳ" in r for r in reasons if "Doji" in r or "trend" in r):
        return "CRITICAL", " + ".join(reasons)
    elif reasons:
        return "ALERT", " + ".join(reasons)
    else:
        return "HOLD", "Không tín hiệu rõ ràng"
