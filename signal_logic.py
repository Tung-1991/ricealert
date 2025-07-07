# signal_logic.py – Version 10.0 “The Synthesizer”
"""
⚙️ **Mục tiêu phiên bản 10.0**
    • Kết hợp những gì tốt nhất của các phiên bản trước:
      1. Kiến trúc Module hóa (từ v9.0): Các quy tắc được tách thành hàm riêng.
      2. Trọng số Tập trung (từ v9.1): Toàn bộ điểm số được quản lý tại một nơi duy nhất.
      3. Kẹp điểm (Clamping): Tính điểm thô không giới hạn, sau đó kẹp lại trong khoảng an toàn
         để giữ cân bằng cho trade_advisor mà không làm mất thông tin "sự đồng thuận".
    • Tương thích 100% với toàn bộ hệ thống.
"""
from typing import Dict, List, Tuple, Callable

# ---------------------------------------------------------------------------
# 1. Cấu hình & Trọng số
# ---------------------------------------------------------------------------
# Lấy SCORE_RANGE động để tính ngưỡng level, nhưng điểm số sẽ được kẹp lại ở 8.0
try:
    from trade_advisor import FULL_CONFIG  # type: ignore
    SCORE_RANGE: float = float(FULL_CONFIG.get("SCORE_RANGE", 8.0))
except Exception:
    SCORE_RANGE = 8.0

# Điểm số sẽ được kẹp trong khoảng này. GIỮ NGUYÊN LÀ 8.0.
CLAMP_MAX_SCORE, CLAMP_MIN_SCORE = 8.0, -8.0


# TRUNG TÂM TINH CHỈNH: Chỉ cần sửa điểm ở đây để thay đổi toàn bộ hệ thống.
# Tổng các trọng số này có thể > 8.0, phản ánh sự đồng thuận của nhiều tín hiệu.
RULE_WEIGHTS = {
    # Tên hàm: Trọng số (Điểm)
    "score_rsi_div": 2.0,
    "score_breakout": 2.0,
    "score_trend": 1.5,
    "score_macd": 1.5,
    "score_doji": 1.5,
    "score_cmf": 1.0,
    "score_volume": 1.0,
    "score_support_resistance": 1.0,
    "score_candle_pattern": 1.0,
    "score_atr_vol": 1.0,
    "score_ema200": 0.5,
    "score_rsi_multi": 0.5, # Giảm trọng số vì nó khá nhiễu
    "score_adx": 0.5,
    "score_bb": 0.5,
}

# ---------------------------------------------------------------------------
# 2. Các hàm quy tắc (Rule Functions)
# Chỉ trả về hướng (1.0: tăng, -1.0: giảm) và lý do.
# ---------------------------------------------------------------------------

def score_trend(ind: Dict) -> Tuple[float, str]:
    t = ind.get("trend")
    if t == "uptrend": return 1.0, "Trend Tăng"
    if t == "downtrend": return -1.0, "Trend Giảm"
    return 0.0, ""

def score_ema200(ind: Dict) -> Tuple[float, str]:
    p, ema = ind.get("price"), ind.get("ema_200")
    if not ema or not p: return 0.0, ""
    return (1.0, "Giá > EMA200") if p > ema else (-1.0, "Giá < EMA200")

def score_rsi_multi(ind: Dict) -> Tuple[float, str]:
    r1h, r4h = ind.get("rsi_1h"), ind.get("rsi_4h")
    if r1h is None or r4h is None: return 0.0, ""
    # Đơn giản hóa: Cả 2 khung đều mạnh hoặc đều yếu
    if r1h > 60 and r4h > 55: return 1.0, "RSI đa khung mạnh"
    if r1h < 40 and r4h < 45: return -1.0, "RSI đa khung yếu"
    return 0.0, ""

def score_macd(ind: Dict) -> Tuple[float, str]:
    cross = ind.get("macd_cross")
    if cross == "bullish": return 1.0, "MACD cắt lên"
    if cross == "bearish": return -1.0, "MACD cắt xuống"
    return 0.0, ""

def score_rsi_div(ind: Dict) -> Tuple[float, str]:
    div = ind.get("rsi_divergence")
    if div == "bullish": return 1.0, "Phân kỳ RSI tăng"
    if div == "bearish": return -1.0, "Phân kỳ RSI giảm"
    return 0.0, ""

def score_cmf(ind: Dict) -> Tuple[float, str]:
    cmf = ind.get("cmf")
    if cmf is None: return 0.0, ""
    if cmf > 0.05: return 1.0, "Dòng tiền CMF dương"
    if cmf < -0.05: return -1.0, "Dòng tiền CMF âm"
    return 0.0, ""

def score_adx(ind: Dict) -> Tuple[float, str]:
    adx = ind.get("adx")
    if adx is None: return 0.0, ""
    if adx > 25: return 1.0, "ADX > 25 (Trend mạnh)"
    if adx < 20: return -1.0, "ADX < 20 (Trend yếu)"
    return 0.0, ""

def score_volume(ind: Dict) -> Tuple[float, str]:
    v, vma = ind.get("volume"), ind.get("vol_ma20")
    if not vma: return 0.0, ""
    if v > 1.8 * vma: return 1.0, "Volume đột biến"
    return 0.0, ""

def score_bb(ind: Dict) -> Tuple[float, str]:
    p, up, lo = ind.get("price"), ind.get("bb_upper"), ind.get("bb_lower")
    if not all([p, up, lo]): return 0.0, ""
    if p > up: return 1.0, "Giá vượt BB trên" # Tín hiệu breakout/quá mua
    if p < lo: return -1.0, "Giá dưới BB dưới" # Tín hiệu breakdown/quá bán
    return 0.0, ""

def score_doji(ind: Dict) -> Tuple[float, str]:
    t, d = ind.get("trend"), (ind.get("doji_type") or "").lower()
    if t == "uptrend" and d in {"gravestone", "shooting_star"}: return -1.0, f"Doji đỉnh ({d})"
    if t == "downtrend" and d in {"dragonfly", "hammer"}: return 1.0, f"Doji đáy ({d})"
    return 0.0, ""

def score_breakout(ind: Dict) -> Tuple[float, str]:
    bo = ind.get("breakout_signal")
    if bo == "bullish": return 1.0, "Tín hiệu Breakout tăng"
    if bo == "bearish": return -1.0, "Tín hiệu Breakout giảm"
    return 0.0, ""

def score_atr_vol(ind: Dict) -> Tuple[float, str]:
    atrp = ind.get("atr_percent", 2.0)
    if atrp > 5.0: return -1.0, "Biến động ATR% rất cao" # Rủi ro
    return 0.0, ""

def score_support_resistance(ind: Dict) -> Tuple[float, str]:
    p, sup, res = ind.get("price"), ind.get("support_level"), ind.get("resistance_level")
    if not all([p, sup, res]): return 0.0, ""
    if abs(p - sup) / p < 0.02: return 1.0, "Giá gần Hỗ trợ"
    if abs(p - res) / p < 0.02: return -1.0, "Giá gần Kháng cự"
    return 0.0, ""

def score_candle_pattern(ind: Dict) -> Tuple[float, str]:
    pat, t = ind.get("candle_pattern"), ind.get("trend")
    if pat == "bullish_engulfing" and t != "uptrend": return 1.0, "Nến Bullish Engulfing"
    if pat == "bearish_engulfing" and t != "downtrend": return -1.0, "Nến Bearish Engulfing"
    return 0.0, ""

# ---------------------------------------------------------------------------
# 3. Danh sách quy tắc, Ngưỡng và Hàm chính
# ---------------------------------------------------------------------------
RULE_FUNCS: List[Callable[[Dict], Tuple[float, str]]] = [
    score_trend, score_ema200, score_rsi_multi, score_macd, score_rsi_div,
    score_cmf, score_adx, score_volume, score_bb, score_doji, score_breakout,
    score_atr_vol, score_support_resistance, score_candle_pattern,
]

LEVEL_THRESHOLDS = {
    "CRITICAL": 0.625 * SCORE_RANGE,  # 5.0 khi SCORE_RANGE = 8.0
    "WARNING": 0.375 * SCORE_RANGE,   # 3.0 khi SCORE_RANGE = 8.0
    "ALERT": 0.125 * SCORE_RANGE,     # 1.0 khi SCORE_RANGE = 8.0
}

def _map_level_tag(score: float, rsi: float) -> Tuple[str, str]:
    level, tag = "HOLD", "neutral"
    abs_score = abs(score)

    if abs_score >= LEVEL_THRESHOLDS["CRITICAL"]: level = "CRITICAL"
    elif abs_score >= LEVEL_THRESHOLDS["WARNING"]: level = "WARNING"
    elif abs_score >= LEVEL_THRESHOLDS["ALERT"]: level = "ALERT"
    elif score > -LEVEL_THRESHOLDS["ALERT"]: level = "WATCHLIST"
    
    if score > 0:
        if level == "CRITICAL": tag = "buy_strong"
        elif level == "WARNING": tag = "canbuy"
        elif level == "ALERT": tag = "weak_buy"
        if level in ["CRITICAL", "WARNING"] and rsi > 70: tag = "buy_overheat"
    else:
        if level == "CRITICAL": tag = "sell_strong"
        elif level == "WARNING": tag = "cansell"
        elif level == "ALERT": tag = "avoid"
        
    return level, tag

def check_signal(indicators: dict) -> Dict:
    """Hàm chính, điều phối việc tính điểm dựa trên trọng số và kẹp điểm."""
    if not indicators or not indicators.get("price"):
        return {"level": "HOLD", "tag": "no_data", "reason": "Thiếu dữ liệu đầu vào.", "raw_tech_score": 0.0}

    total_score = 0.0
    reasons = []

    for func in RULE_FUNCS:
        direction, reason_text = func(indicators)
        if direction != 0:
            func_name = func.__name__
            weight = RULE_WEIGHTS.get(func_name, 0.0)
            rule_score = direction * weight
            total_score += rule_score
            reasons.append(f"{reason_text} ({rule_score:+.1f})")
    
    # Kẹp điểm số cuối cùng trong khoảng an toàn [-8.0, 8.0]
    final_score = max(CLAMP_MIN_SCORE, min(total_score, CLAMP_MAX_SCORE))
    
    level, tag = _map_level_tag(final_score, indicators.get("rsi_1h", 50.0))
    final_reason = f"Tổng điểm: {final_score:.1f} | " + " ".join(reasons) if reasons else "Không có tín hiệu rõ ràng."

    return {
        "level": level,
        "tag": tag,
        "reason": final_reason,
        "raw_tech_score": final_score
    }
