# signal_logic.py

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

    # Nếu thiếu dữ liệu → HOLD
    if any(v is None for v in [rsi, macd, macd_signal, bb_upper, bb_lower, price, ema, volume, vol_ma]):
        return "HOLD", "Thiếu dữ liệu"

    reasons = []

    # ====== Rule CRITICAL ======
    if rsi < 30 and macd > macd_signal and doji == "dragonfly":
        reasons.append("RSI < 30 + MACD cắt lên + Dragonfly Doji")
    if rsi > 70 and macd < macd_signal and doji == "gravestone":
        reasons.append("RSI > 70 + MACD cắt xuống + Gravestone Doji")

    # ====== Rule ALERT ======
    if rsi > 70 and price >= bb_upper:
        reasons.append("RSI quá cao + giá chạm biên BB trên")
    if rsi < 30 and price <= bb_lower:
        reasons.append("RSI quá thấp + giá chạm biên BB dưới")
    if doji in ["long-legged", "common"] and abs(volume - vol_ma) > 1.5 * vol_ma:
        reasons.append("Doji + Volume spike bất thường")

    # ====== Tổng hợp kết luận ======
    if any("RSI" in r for r in reasons if "Doji" in r or "MACD" in r):
        return "CRITICAL", " + ".join(reasons)
    elif reasons:
        return "ALERT", " + ".join(reasons)
    else:
        return "HOLD", "Không tín hiệu rõ ràng"

