# /root/ricealert/signal_logic.py (PHIÊN BẢN ĐÃ MERGE)
from typing import Dict

def check_signal(indicators: dict) -> Dict:
    """
    Kiểm tra các chỉ báo bằng hệ thống tính điểm linh hoạt để đưa ra tín hiệu
    thay vì các quy tắc if/elif cứng nhắc.
    """
    # Lấy dữ liệu, giữ nguyên như cũ
    rsi_1h = indicators.get("rsi_1h")
    rsi_4h = indicators.get("rsi_4h")
    rsi_1d = indicators.get("rsi_1d")
    price = indicators.get('price')
    volume = indicators.get('volume')
    vol_ma = indicators.get('vol_ma20')
    macd_cross = indicators.get('macd_cross')
    adx = indicators.get('adx')
    rsi_div = indicators.get('rsi_divergence')
    trend = indicators.get('trend')
    cmf = indicators.get('cmf')
    bb_upper = indicators.get('bb_upper')
    bb_lower = indicators.get('bb_lower')
    doji_raw = indicators.get('doji_type')
    doji = doji_raw.lower() if isinstance(doji_raw, str) else ""

    required_fields = [rsi_1h, rsi_4h, rsi_1d, price, volume, vol_ma, macd_cross, adx, trend, cmf, bb_upper, bb_lower]
    
    # *** BẮT ĐẦU THAY ĐỔI TỪ CODE UPDATE ***
    if any(v is None for v in required_fields):
        return {
            "level": "HOLD", 
            "tag": "avoid", 
            "reason": "Thiếu dữ liệu chỉ báo quan trọng.",
            "raw_tech_score": 0.0 # Thêm dòng này
        }
    # *** KẾT THÚC THAY ĐỔI ***

    # =======================================================================
    # === HỆ THỐNG TÍNH ĐIỂM LINH HOẠT (DYNAMIC SCORING SYSTEM) ===
    # =======================================================================
    scores = {}
    reasons = []

    # 1. Điểm Xu Hướng (Trend Score)
    if trend == "uptrend":
        scores['trend'] = 1.5
        reasons.append("Trend Tăng (+1.5)")
    elif trend == "downtrend":
        scores['trend'] = -1.5
        reasons.append("Trend Giảm (-1.5)")
    else:
        scores['trend'] = 0

    # 2. Điểm RSI Đa Khung Thời Gian (Multi-Timeframe RSI Score)
    rsi_score = 0
    if rsi_1h > 60: rsi_score += 0.5
    if rsi_1h > 70: rsi_score += 0.5 # Rất mạnh
    if rsi_4h > 55: rsi_score += 1.0
    if rsi_1d > 55: rsi_score += 1.0
    if rsi_1h < 40: rsi_score -= 0.5
    if rsi_1h < 30: rsi_score -= 0.5 # Rất yếu
    if rsi_4h < 45: rsi_score -= 1.0
    if rsi_1d < 45: rsi_score -= 1.0
    if rsi_score != 0:
        scores['rsi'] = rsi_score
        reasons.append(f"RSI đa khung ({rsi_score:+.1f})")

    # 3. Điểm MACD (MACD Score)
    if macd_cross == "bullish":
        scores['macd'] = 1.5
        reasons.append("MACD cắt lên (+1.5)")
    elif macd_cross == "bearish":
        scores['macd'] = -1.5
        reasons.append("MACD cắt xuống (-1.5)")

    # 4. Điểm Phân Kỳ RSI (Divergence Score) - Tín hiệu rất mạnh
    if rsi_div == "bullish":
        scores['rsi_div'] = 2.0
        reasons.append("Phân kỳ tăng RSI (+2.0)")
    elif rsi_div == "bearish":
        scores['rsi_div'] = -2.0
        reasons.append("Phân kỳ giảm RSI (-2.0)")

    # 5. Điểm Dòng Tiền CMF (Money Flow Score)
    if cmf > 0.05:
        scores['cmf'] = 1.0
        reasons.append("Dòng tiền dương mạnh (+1.0)")
    elif cmf < -0.05:
        scores['cmf'] = -1.0
        reasons.append("Dòng tiền âm mạnh (-1.0)")

    # 6. Điểm Sức Mạnh Xu Hướng ADX (Trend Strength Score)
    if adx > 25:
        # ADX cao củng cố cho xu hướng hiện tại
        scores['adx'] = 0.5 * (1 if scores.get('trend', 0) >= 0 else -1)
        reasons.append(f"ADX > 25 củng cố trend ({scores['adx']:+.1f})")
    elif adx < 20:
        # ADX yếu làm giảm độ tin cậy của các tín hiệu khác
        scores['adx'] = -0.5
        reasons.append("ADX < 20, trend yếu (-0.5)")

    # 7. Điểm Volume (Volume Score)
    if volume > 1.5 * vol_ma:
        scores['volume'] = 1.0
        reasons.append("Volume đột biến (+1.0)")
    elif volume < 0.7 * vol_ma:
        scores['volume'] = -0.5
        reasons.append("Volume thấp (-0.5)")

    # 8. Điểm Bollinger Bands (BB Score)
    if price > bb_upper * 0.995:
        scores['bb'] = 0.5 # Có thể là breakout hoặc quá mua
        reasons.append("Giá chạm BB trên (+0.5)")
    if price < bb_lower * 1.005:
        scores['bb'] = -0.5 # Có thể là breakdown hoặc quá bán
        reasons.append("Giá chạm BB dưới (-0.5)")

    # 9. Điểm Nến Doji Đảo Chiều (Reversal Doji Score)
    if trend == "uptrend" and doji in ["gravestone", "shooting_star"]:
        scores['doji'] = -1.5
        reasons.append(f"Doji đỉnh ({doji}) (-1.5)")
    elif trend == "downtrend" and doji in ["dragonfly", "hammer"]:
        scores['doji'] = 1.5
        reasons.append(f"Doji đáy ({doji}) (+1.5)")


    # === TỔNG HỢP ĐIỂM VÀ RA QUYẾT ĐỊNH ===
    total_score = sum(scores.values())

    signal_type = "HOLD"
    tag = "neutral"

    if total_score >= 4.0:
        signal_type = "CRITICAL"
        tag = "buy_high" if rsi_1h > 65 else "canbuy"
    elif total_score >= 2.5:
        signal_type = "WARNING"
        tag = "canbuy"
    elif total_score >= 1.0:
        signal_type = "ALERT"
        tag = "canbuy"
    elif total_score > -1.0:
        signal_type = "WATCHLIST"
        tag = "neutral"
    elif total_score <= -4.0:
        signal_type = "CRITICAL"
        tag = "sell_low"
    elif total_score <= -2.5:
        signal_type = "WARNING"
        tag = "sell_high"
    elif total_score <= -1.0:
        signal_type = "ALERT"
        tag = "avoid"

    # Trường hợp điểm gần 0, sideway, không rõ ràng
    if -1.0 < total_score < 1.0:
        signal_type = "HOLD"
        tag = "neutral"
        if adx < 15 and volume < 0.8 * vol_ma:
            tag = "avoid" # Thị trường chết
            reasons.append("Thị trường thanh khoản thấp, nên tránh")

    final_reason = f"Tổng điểm: {total_score:.1f} | " + " + ".join(reasons) if reasons else "Không có tín hiệu rõ ràng."

    return {
        "level": signal_type,
        "tag": tag,
        "reason": final_reason,
        "raw_tech_score": total_score
    }
