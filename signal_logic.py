def check_signal(indicators: dict) -> tuple:
    rsi = indicators.get('rsi_14')
    rsi_1h = indicators.get("rsi_1h")
    rsi_4h = indicators.get("rsi_4h")
    rsi_1d = indicators.get("rsi_1d")
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
    fib_0_618 = indicators.get("fib_0_618")

    required_fields = [rsi, rsi_1h, rsi_4h, rsi_1d, macd, macd_signal, bb_upper, bb_lower, price, ema, volume, vol_ma,
                       macd_cross, adx, trend, cmf]
    if any(v is None for v in required_fields):
        indicators["tag"] = "avoid"
        return "HOLD", "Thiếu dữ liệu [Tag: avoid]"

    reasons = []
    signal_type = "HOLD"
    tag = "neutral"

    # ================= TAG: buy_high =================
    if (
        trend == "uptrend" and
        rsi_1h > 68 and rsi_4h > 65 and rsi_1d > 60 and
        macd_cross == "bullish" and
        price > bb_upper * 0.995 and cmf > 0.05 and volume > vol_ma
    ):
        tag = "buy_high"
        if adx > 40:
            signal_type = "CRITICAL"
            reasons.append("Breakout mạnh: RSI cao đa timeframe + MACD bullish + volume lớn + CMF dương + ADX cao")
        elif adx > 25:
            signal_type = "WARNING"
            reasons.append("Đà tăng mạnh: RSI cao + BB trên + ADX > 25")
        elif cmf > 0:
            signal_type = "ALERT"
            reasons.append("RSI cao + MACD bullish + CMF dương")
        else:
            signal_type = "WATCHLIST"
            reasons.append("Trend tăng + RSI cao, theo dõi breakout")

    # ================= TAG: sell_high =================
    elif (
        trend == "downtrend" and
        rsi_1h > 70 and rsi_4h > 65 and rsi_1d > 65 and
        cmf < -0.03 and
        price > bb_upper * 0.995
    ):
        tag = "sell_high"
        if macd_cross == "bearish" and volume > 1.2 * vol_ma:
            signal_type = "CRITICAL"
            reasons.append("Đỉnh mạnh: RSI cao + MACD bearish + volume lớn")
        elif rsi_div == "bearish":
            signal_type = "WARNING"
            reasons.append("Phân kỳ RSI giảm giá")
        elif doji in ["gravestone"] and volume > vol_ma:
            signal_type = "ALERT"
            reasons.append("Doji đỉnh + volume xác nhận")
        elif cmf < 0:
            signal_type = "WATCHLIST"
            reasons.append("RSI cao + CMF âm nhẹ")
        else:
            signal_type = "WATCHLIST"
            reasons.append("Có dấu hiệu tạo đỉnh, cần theo dõi")

    # ================= TAG: buy_low =================
    elif (
        trend == "uptrend" and
        rsi_1h < 35 and rsi_4h < 40 and rsi_1d < 45 and
        macd_cross == "bullish" and
        price < bb_lower * 1.01
    ):
        tag = "buy_low"
        if cmf > 0 and volume > 1.2 * vol_ma:
            signal_type = "CRITICAL"
            reasons.append("Vùng mua mạnh: RSI thấp + MACD bullish + volume lớn")
        elif fib_0_618 and abs(price - fib_0_618) / fib_0_618 < 0.01:
            signal_type = "WARNING"
            reasons.append("RSI thấp + gần Fibo 0.618")
        elif doji in ["dragonfly", "long_legged"] and volume > vol_ma:
            signal_type = "ALERT"
            reasons.append("Doji đảo chiều + volume xác nhận")
        else:
            signal_type = "WATCHLIST"
            reasons.append("Giá thấp + RSI thấp cần theo dõi")

    # ================= TAG: sell_low =================
    elif (
        trend == "downtrend" and
        rsi_1h < 30 and rsi_4h < 35 and rsi_1d < 40 and
        cmf < -0.05 and
        price < bb_lower
    ):
        tag = "sell_low"
        if macd_cross == "bearish" and volume > vol_ma:
            signal_type = "CRITICAL"
            reasons.append("Bán tháo: RSI thấp + MACD bearish + volume cao")
        elif rsi_div == "bearish":
            signal_type = "WARNING"
            reasons.append("Phân kỳ RSI giảm giá")
        elif doji in ["common"] and volume > vol_ma:
            signal_type = "ALERT"
            reasons.append("Giảm mạnh nhưng có thể hồi nhẹ + volume xác nhận")
        elif cmf < 0:
            signal_type = "WATCHLIST"
            reasons.append("Lực bán mạnh dần, CMF âm")
        else:
            signal_type = "WATCHLIST"
            reasons.append("Giá giảm nhưng tín hiệu chưa rõ")

    # ================= TAG: canbuy =================
    elif (
        rsi_1h > 55 and rsi_4h > 50 and trend == "uptrend" and cmf > 0
    ):
        tag = "canbuy"
        if rsi_div == "bullish" and volume > 1.3 * vol_ma:
            signal_type = "CRITICAL"
            reasons.append("Breakout sớm: phân kỳ RSI + volume cao")
        elif macd_cross == "bullish" and cmf > 0.05:
            signal_type = "WARNING"
            reasons.append("MACD bullish + CMF dương")
        elif macd_cross == "bullish":
            signal_type = "ALERT"
            reasons.append("MACD bullish, tín hiệu tăng nhẹ")
        else:
            signal_type = "WATCHLIST"
            reasons.append("Tín hiệu tích cực, cần theo dõi thêm")

    # ================= TAG: neutral =================
    elif (
        abs(price - ema) / ema < 0.005 and 45 <= rsi <= 55 and not trend
    ):
        tag = "neutral"
        if adx > 25:
            signal_type = "WARNING"
            reasons.append("Sideway mạnh + ADX cao")
        elif doji:
            signal_type = "ALERT"
            reasons.append("Sideway + Doji xuất hiện")
        elif trend:
            signal_type = "WATCHLIST"
            reasons.append("Giá dao động quanh EMA, xu hướng chưa rõ")
        else:
            signal_type = "HOLD"
            reasons.append("Chưa có xu hướng rõ ràng")

    # ================= TAG: avoid =================
    else:
        tag = "avoid"
        if (rsi_div == "bearish" and cmf < -0.03 and adx < 15):
            signal_type = "CRITICAL"
            reasons.append("Tín hiệu nhiễu cực mạnh, xung đột đa chỉ báo")
        elif volume < 0.6 * vol_ma and adx < 10:
            signal_type = "WARNING"
            reasons.append("Volume thấp + ADX yếu")
        elif adx < 10 or cmf == 0:
            signal_type = "ALERT"
            reasons.append("Không có động lượng + CMF trung tính")
        elif rsi and 45 <= rsi <= 55:
            signal_type = "WATCHLIST"
            reasons.append("RSI trung tính, không rõ xu hướng")
        else:
            signal_type = "HOLD"
            reasons.append("Tín hiệu yếu, nên đứng ngoài")

    indicators["tag"] = tag
    return signal_type, " + ".join(reasons) + f" [Tag: {tag}]"
