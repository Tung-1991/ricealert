# -*- coding: utf-8 -*-
"""
Live Trade - The 4-Zone Strategy
Version: 9.2.0 - Enhanced Reporting & Statistics Engine
Date: 2025-09-29

CHANGELOG (v9.2.0):
- REPORTING (Intuitive Capital Display): Reports for active trades now display the initial invested capital instead of the remaining capital after partial closures. This provides a clearer view of the original trade's performance.
- STATISTICS (Partial PnL Integration): The `trade_stats` engine is now fully complete.
  - It now tracks historical `total_tp1_pnl` and `total_pp_pnl` directly within the state file.
  - The one-time initialization from CSV now correctly calculates and includes these historical partial PnL values.
  - The reporting function `build_pnl_summary_line` now reads from the persistent `trade_stats`, ensuring 100% accuracy and consistency across the entire trade history, not just the last 100 trades.
- REFACTOR: Modified `build_daily_summary_text` and related report functions for the new capital display logic.
- REFACTOR: Modified `run_session` and `close_trade_on_binance` to support the enhanced `trade_stats` object.

CHANGELOG (v9.1.0):
- PERFORMANCE (Scalable Statistics): Replaced on-the-fly statistics calculation with a persistent `trade_stats` object.
- AUTOMATION (Auto-Initialization): Automatically initializes `trade_stats` from the full CSV history on first run.

CHANGELOG (v9.0.0):
- FEATURE (Price Action Momentum): Integrated the PAM module.
"""
import os
import sys
import json
import uuid
import time
import requests
import pytz
import pandas as pd
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Tuple, Optional, Literal
from dotenv import load_dotenv
import traceback
import numpy as np
import ta

# --- Tải và Thiết lập ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
dotenv_path = os.path.join(PROJECT_ROOT, '.env')
load_dotenv(dotenv_path=dotenv_path)
sys.path.append(PROJECT_ROOT)
try:
    from binance_connector import BinanceConnector
    from indicator import calculate_indicators
    from trade_advisor import get_advisor_decision, FULL_CONFIG as ADVISOR_BASE_CONFIG
except ImportError as e:
    sys.exit(f"Lỗi: Không thể import module cần thiết: {e}.")

LIVE_DATA_DIR = os.path.join(PROJECT_ROOT, "livetrade", "data")
os.makedirs(LIVE_DATA_DIR, exist_ok=True)
CACHE_DIR = os.path.join(LIVE_DATA_DIR, "indicator_cache")
os.makedirs(CACHE_DIR, exist_ok=True)

# ==============================================================================
# ================== ⚙️ TRUNG TÂM CẤU HÌNH ⚙️ ===================
# ==============================================================================
TRADING_MODE: Literal["live", "testnet"] = "live" # Chế độ chạy: "live" (tiền thật) hoặc "testnet" (tiền ảo)

# --- CẤU HÌNH CHUNG ---
GENERAL_CONFIG = {
    # --- Cấu hình cốt lõi & hệ thống ---
    "DATA_FETCH_LIMIT": 300,                  # [Hệ thống] - Số lượng nến tối đa để tải về.
    "CRON_JOB_INTERVAL_MINUTES": 1,           # [Hệ thống] - Tần suất chạy bot, phải khớp với crontab của bạn.
    "PENDING_TRADE_RETRY_LIMIT": 3,           # [Hệ thống] - Số lần thử lại nếu lệnh MUA thất bại.
    "CLOSE_TRADE_RETRY_LIMIT": 3,             # [Hệ thống] - Số lần thử lại nếu lệnh BÁN thất bại.
    "CRITICAL_ERROR_ALERT_COOLDOWN_MINUTES": 45, # [Hệ thống] - Chờ 45p trước khi báo lại lỗi nghiêm trọng giống nhau.
    "RECONCILIATION_QTY_THRESHOLD": 0.95,     # [Hệ thống] - Ngưỡng phát hiện lệnh bị đóng thủ công.
    "MIN_ORDER_VALUE_USDT": 11.0,             # [Sàn giao dịch] - Giá trị lệnh tối thiểu của Binance.
    "ORPHAN_ASSET_MIN_VALUE_USDT": 10.0,       # [Hệ thống] - Cảnh báo tài sản "mồ côi" > 10$.
    "HEAVY_REFRESH_MINUTES": 15,              # [Chiến lược] - Quét lại toàn bộ thị trường sau mỗi 15 phút để tìm cơ hội.
    "TOP_N_OPPORTUNITIES_TO_CHECK": 7,        # [Chống FOMO] - So sánh 5 cơ hội tốt nhất, tránh vồ vập cơ hội đầu tiên.
    "TRADE_COOLDOWN_HOURS": 1.5,              # [Quản lý] - Nghỉ 1.5 giờ sau khi đóng lệnh để thị trường ổn định.
    "OVERRIDE_COOLDOWN_SCORE": 7.5,           # [Linh hoạt] - Tín hiệu thật sự xuất sắc (>7.5) mới được phá vỡ thời gian nghỉ.

    # --- Bộ lọc nhiễu & Xác nhận động lượng (Vệ sĩ gác cổng) ---
    "MOMENTUM_FILTER_CONFIG": {
        "ENABLED": True,                      # [An toàn] - Bật lớp bảo vệ này để tránh các tín hiệu yếu, thiếu động lượng.
        "RULES_BY_TIMEFRAME": {
            "1h": {"WINDOW": 5, "REQUIRED_CANDLES": 3},
            "4h": {"WINDOW": 5, "REQUIRED_CANDLES": 2},
            "1d": {"WINDOW": 4, "REQUIRED_CANDLES": 1}
        }
    },

    # --- Động cơ Vốn Năng động ---
    "DEPOSIT_DETECTION_MIN_USD": 10.0,
    "DEPOSIT_DETECTION_THRESHOLD_PCT": 0.01,
    "AUTO_COMPOUND_THRESHOLD_PCT": 10.0,      # [Tăng trưởng] - Tự động tái đầu tư khi lãi > 10%.
    "AUTO_DELEVERAGE_THRESHOLD_PCT": -10.0,     # [Bảo vệ vốn] - Tự động giảm rủi ro khi lỗ > 10%.
    "CAPITAL_ADJUSTMENT_COOLDOWN_HOURS": 48,
    "DAILY_SUMMARY_TIMES": ["08:10", "20:10"],  # [Báo cáo] - Các mốc thời gian gửi báo cáo tổng kết.
}

# --- PHÂN TÍCH ĐA KHUNG THỜI GIAN (MTF) ---
MTF_ANALYSIS_CONFIG = {
    "ENABLED": True,                      # [An toàn] - Bật để bot "nhìn" xu hướng lớn, tránh đi ngược dòng.
    "BONUS_COEFFICIENT": 1.05,            # [Thưởng] - Thưởng điểm nhẹ khi các khung lớn đồng thuận.
    "PENALTY_COEFFICIENT": 0.95,            # [Phạt] - Phạt điểm nhẹ khi có khung lớn đi ngược.
    "SEVERE_PENALTY_COEFFICIENT": 0.93,     # [Phạt nặng] - Phạt nặng khi tất cả khung lớn đều chống lại.
    "SIDEWAYS_PENALTY_COEFFICIENT": 0.97,     # [Phạt nhẹ] - Phạt nhẹ khi khung lớn đi ngang.
}

# --- BỘ LỌC ĐIỀU CHỈNH VÙNG CỰC ĐOAN (EZ) - PHIÊN BẢN NÂNG CẤP ---
EXTREME_ZONE_ADJUSTMENT_CONFIG = {
    "ENABLED": True,

    # --- Giới Hạn An Toàn ---
    "MAX_BONUS_COEFF": 1.15,                      # [Tuning] Hạ trần bonus xuống +15% để an toàn hơn.
    "MIN_PENALTY_COEFF": 0.90,                      # Giữ nguyên sàn phạt -10%.

    # --- Trọng Số Các Yếu Tố ---
    "SCORING_WEIGHTS": {
        "RSI": 0.4,                                 # Độ quan trọng của RSI.
        "BB_POS": 0.4,                              # Độ quan trọng của vị trí giá trong BB.
        "CANDLE": 0.35,                               # Độ quan trọng của mẫu nến.
        "SR_LEVEL": 0.35                              # Độ quan trọng của mức Hỗ trợ/Kháng cự.
    },

    # --- Sức Mạnh Của Điểm Thưởng/Phạt ---
    "BASE_IMPACT": {
        "BONUS_PER_POINT": 0.15,                      # [Tuning] Giảm sức mạnh bonus để điểm tăng ôn hòa hơn.
        "PENALTY_PER_POINT": -0.08                      # Giữ nguyên sức mạnh của điểm phạt.
    },

    # --- Thưởng Combo Đặc Biệt ---
    "CONFLUENCE_MULTIPLIER": 2.0,                     # Nhân đôi tác động khi RSI và BB cùng đồng thuận.

    # --- Ngưỡng Kích Hoạt ---
    "RULES_BY_TIMEFRAME": {
        "1h": {"OVERBOUGHT": {"RSI_ABOVE": 78, "BB_POS_ABOVE": 0.98}, "OVERSOLD": {"RSI_BELOW": 35, "BB_POS_BELOW": 0.15}}, # [Tuning] Siết chặt ngưỡng 1h, yêu cầu tín hiệu rõ ràng hơn.
        "4h": {"OVERBOUGHT": {"RSI_ABOVE": 75, "BB_POS_ABOVE": 0.95}, "OVERSOLD": {"RSI_BELOW": 40, "BB_POS_BELOW": 0.22}},
        "1d": {"OVERBOUGHT": {"RSI_ABOVE": 72, "BB_POS_ABOVE": 0.95}, "OVERSOLD": {"RSI_BELOW": 42, "BB_POS_BELOW": 0.25}}
    },

    # --- Yếu Tố Xác Nhận Bổ Sung ---
    "CONFIRMATION_BOOST": {
        "ENABLED": True,
        "BEARISH_CANDLES": ["shooting_star", "bearish_engulfing", "gravestone"],
        "BULLISH_CANDLES": ["hammer", "bullish_engulfing", "dragonfly"],
        "RESISTANCE_PROXIMITY_PCT": 0.015,
        "SUPPORT_PROXIMITY_PCT": 0.015
    },

    # --- [NÂNG CẤP] PHÂN TÍCH BỐI CẢNH BB SQUEEZE ---
    "SQUEEZE_ANALYSIS": {
        "ENABLED": True,
        "LOOKBACK_PERIOD": 200,                       # Lịch sử quét: 200 nến.
        "SQUEEZE_PERCENTILE": 10.0,                     # Ngưỡng "hẹp": độ rộng BB nằm trong 10% thấp nhất.
        "IMPACT_MULTIPLIER": 1.25                       # Khuếch đại bonus/penalty lên 25% khi có Squeeze.
    },

    # --- Phân Tích Hành Động Giá & Volume ---
    "PRICE_ACTION_VOL_ANALYSIS": {
        "ENABLED": True,
        "RULES_BY_TIMEFRAME": {
            "1h": { "BREAKOUT_CANDLE_ATR_RATIO": 3.0, "BREAKOUT_VOLUME_MA_RATIO": 3.5, "BREAKOUT_PENALTY_REDUCTION_COEFF": 0.3, "EXHAUSTION_CANDLE_ATR_RATIO": 2.5, "EXHAUSTION_VOLUME_MA_RATIO": 4.0, "EXHAUSTION_BONUS_MULTIPLIER": 1.4 },
            "4h": { "BREAKOUT_CANDLE_ATR_RATIO": 2.5, "BREAKOUT_VOLUME_MA_RATIO": 3.0, "BREAKOUT_PENALTY_REDUCTION_COEFF": 0.2, "EXHAUSTION_CANDLE_ATR_RATIO": 2.2, "EXHAUSTION_VOLUME_MA_RATIO": 3.5, "EXHAUSTION_BONUS_MULTIPLIER": 1.5 },
            "1d": { "BREAKOUT_CANDLE_ATR_RATIO": 2.0, "BREAKOUT_VOLUME_MA_RATIO": 2.5, "BREAKOUT_PENALTY_REDUCTION_COEFF": 0.1, "EXHAUSTION_CANDLE_ATR_RATIO": 2.0, "EXHAUSTION_VOLUME_MA_RATIO": 3.0, "EXHAUSTION_BONUS_MULTIPLIER": 1.6 }
        }
    }
}

# --- PRICE ACTION MOMENTUM (PAM) ---
PRICE_ACTION_MOMENTUM_CONFIG = {
    "ENABLED": True,
    "MAX_BONUS_COEFF": 1.10,
    "MIN_PENALTY_COEFF": 0.95,

    "SCORING_WEIGHTS": {
        "CONSECUTIVE_GREENS": 0.30,
        "PRICE_VS_MA": 0.25,
        "VOLUME_SURGE": 0.25,
        "HIGHER_LOWS": 0.20
    },

    "RULES_BY_TIMEFRAME": {
        "1h": {"LOOKBACK_CANDLES": 10, "MIN_GREEN_STREAK": 3, "VOLUME_SURGE_RATIO": 1.5, "MIN_HIGHER_LOWS": 5},
        "4h": {"LOOKBACK_CANDLES": 8, "MIN_GREEN_STREAK": 3, "VOLUME_SURGE_RATIO": 1.3, "MIN_HIGHER_LOWS": 4},
        "1d": {"LOOKBACK_CANDLES": 6, "MIN_GREEN_STREAK": 2, "VOLUME_SURGE_RATIO": 1.2, "MIN_HIGHER_LOWS": 3}
    }
}

# --- QUẢN LÝ LỆNH ĐANG MỞ ---
ACTIVE_TRADE_MANAGEMENT_CONFIG = {
    "EARLY_CLOSE_ABSOLUTE_THRESHOLD": 4.5,       # [Thoát hiểm] - Nếu điểm số tụt dưới 4.8 (tín hiệu cực xấu), đóng lệnh ngay.
    "EARLY_CLOSE_RELATIVE_DROP_PCT": 0.25,      # [Cảnh báo] - Nếu điểm số sụt 25% so với lúc vào, xem xét đóng một phần.
    "PARTIAL_EARLY_CLOSE_PCT": 0.4,             # [Hành động] - Đóng 50% nếu điểm sụt giảm mạnh.
    "PROFIT_PROTECTION": {
        "ENABLED": True,                      # [Bảo vệ lãi] - Bật tính năng khóa một phần lợi nhuận.
        "MIN_PEAK_PNL_TRIGGER": 4.5,            # [Kích hoạt] - Khi lãi đạt 4.5% thì bắt đầu canh chừng.
        "PNL_DROP_TRIGGER_PCT": 2.0,            # [Hành động] - Nếu lãi sụt 2.0% từ đỉnh, bán một phần để bảo vệ thành quả.
        "PARTIAL_CLOSE_PCT": 0.5              # [Tỷ lệ] - Bán 50% để khóa lợi nhuận.
    }
}

# --- CẢNH BÁO ĐỘNG ---
DYNAMIC_ALERT_CONFIG = {
    "ENABLED": True,
    "COOLDOWN_HOURS": 2.5,
    "FORCE_UPDATE_HOURS": 10,
    "PNL_CHANGE_THRESHOLD_PCT": 2.0
}


# --- LUẬT RỦI RO ---
RISK_RULES_CONFIG = {
    "MAX_ACTIVE_TRADES": 7,                   # [Quản lý rủi ro] - Giới hạn số lệnh mở cùng lúc để tránh rủi ro quá mức.
    "MAX_SL_PERCENT_BY_TIMEFRAME": {"1h": 0.10, "4h": 0.15, "1d": 0.20}, # [Phanh khẩn cấp] - Mức lỗ TỐI ĐA cho phép, đủ rộng cho các Tactic.
    "MAX_TP_PERCENT_BY_TIMEFRAME": {"1h": 0.15, "4h": 0.25, "1d": 0.30}, # [Thực tế hóa] - Mức lãi TỐI ĐA, tránh các mục tiêu viển vông.
    "MIN_RISK_DIST_PERCENT_BY_TIMEFRAME": {"1h": 0.08, "4h": 0.10, "1d": 0.15}, # [SÀN AN TOÀN] - Mức lỗ TỐI THIỂU, tránh SL quá gần khi ATR thấp.
    "STALE_TRADE_RULES": {                    # [GỒNG LỆNH] - Cho các lệnh "ì", không chạy thêm thời gian.
        "1h": {"HOURS": 72, "PROGRESS_THRESHOLD_PCT": 2.0},
        "4h": {"HOURS": 144, "PROGRESS_THRESHOLD_PCT": 3.0},
        "1d": {"HOURS": 240, "PROGRESS_THRESHOLD_PCT": 5.0},
        "STAY_OF_EXECUTION_SCORE": 6.5        # [Ân xá] - Điểm số tối thiểu để "ân xá", không đóng lệnh "ì".
    }
}

# --- QUẢN LÝ VỐN TỔNG THỂ ---
CAPITAL_MANAGEMENT_CONFIG = {
    "MAX_TOTAL_EXPOSURE_PCT": 0.80            # [Phanh an toàn] - Tổng vốn đã vào lệnh không được vượt quá 80% tiền mặt.
}

# --- TRUNG BÌNH GIÁ (DCA) ---
DCA_CONFIG = {
    "ENABLED": True,                      # [Sửa sai] - Bật DCA như một công cụ sửa sai chiến lược.
    "MAX_DCA_ENTRIES": 2,                   # Tối đa 2 lần DCA cho một lệnh.
    "TRIGGER_DROP_PCT_BY_TIMEFRAME": {        # [Logic] - Ngưỡng DCA luôn "nông" hơn Min SL để bot có cơ hội hành động.
        "1h": -6.0,
        "4h": -8.0,
        "1d": -10.0
    },
    "SCORE_MIN_THRESHOLD": 6.5,             # [Logic] - Hạ ngưỡng để DCA có thể hoạt động cho các lệnh có điểm vào thấp.
    "CAPITAL_MULTIPLIER": 0.5,              # [Quản lý rủi ro] - Giảm vốn DCA để tránh "lỗ kép".
    "DCA_COOLDOWN_HOURS": 8
}

# --- CẢNH BÁO ---
ALERT_CONFIG = {
    "DISCORD_WEBHOOK_URL": os.getenv("DISCORD_LIVE_WEBHOOK"),
    "DISCORD_CHUNK_DELAY_SECONDS": 2
}

# ==============================================================================
# ================= 🚀 CORE STRATEGY: 4-ZONE MODEL 🚀 =================
# ==============================================================================
LEADING_ZONE = "LEADING"
COINCIDENT_ZONE = "COINCIDENT"
LAGGING_ZONE = "LAGGING"
NOISE_ZONE = "NOISE"
ZONES = [LEADING_ZONE, COINCIDENT_ZONE, LAGGING_ZONE, NOISE_ZONE]

# --- QUẢN LÝ VỐN THEO VÙNG ---
ZONE_BASED_POLICIES = {
    # Giảm nhẹ vốn trên mỗi lệnh để quản lý rủi ro tốt hơn khi SL rộng hơn.
    LEADING_ZONE: {"NOTES": "Dò mìn cơ hội tiềm năng.", "CAPITAL_PCT": 0.025},
    COINCIDENT_ZONE: {"NOTES": "Vùng tốt nhất, quyết đoán vào lệnh.", "CAPITAL_PCT": 0.040},
    LAGGING_ZONE: {"NOTES": "An toàn, đi theo trend đã rõ.", "CAPITAL_PCT": 0.035},
    NOISE_ZONE: {"NOTES": "Nguy hiểm, vốn siêu nhỏ.", "CAPITAL_PCT": 0.020}
}

# --- PHÒNG THÍ NGHIỆM CHIẾN THUẬT (TACTICS LAB) ---
TACTICS_LAB = {
    # == TACTIC 1: Chiến Binh Chủ Lực ==
    "Balanced_Trader": {
        "OPTIMAL_ZONE": [LAGGING_ZONE, COINCIDENT_ZONE],
        "NOTES": "Chiến binh SWING TRADE chủ lực. Vào lệnh sớm hơn, gồng lệnh lì đòn qua các đợt điều chỉnh.",
        "WEIGHTS": {'tech': 0.4, 'context': 0.2, 'ai': 0.4},
        "ENTRY_SCORE": 6.5,                         # [NỚI LỎNG] - Chấp nhận tín hiệu sớm hơn vì hệ thống phòng thủ đã mạnh.
        "RR": 2.0,                                  # [TỐI ƯU] - Kỳ vọng RR cao hơn vì vào sớm và gồng được lệnh.
        "ATR_SL_MULTIPLIER": 2.5,                   # [CHỊU ĐÒN] - "Khiên" cực dày, cốt lõi của việc gồng lệnh.
        "USE_TRAILING_SL": True, "TRAIL_ACTIVATION_RR": 1.3, "TRAIL_DISTANCE_RR": 1.1,
        "ENABLE_PARTIAL_TP": True, "TP1_RR_RATIO": 1.0, "TP1_PROFIT_PCT": 0.5,
        "USE_MOMENTUM_FILTER": True,
        "USE_EXTREME_ZONE_FILTER": True,
        "USE_PRICE_ACTION_MOMENTUM": True,
    },
    # == TACTIC 2: Kẻ Săn Mồi Bùng Nổ ==
    "Breakout_Hunter": {
        "OPTIMAL_ZONE": [LEADING_ZONE, COINCIDENT_ZONE],
        "NOTES": "Chuyên săn các điểm PHÁ VỠ đã được xác nhận. SL rộng để sống sót qua cú retest.",
        "WEIGHTS": {'tech': 0.6, 'context': 0.1, 'ai': 0.3},
        "ENTRY_SCORE": 7.0,                         # [NỚI LỎNG] - Vào lệnh ngay khi breakout vừa xảy ra, không cần đợi quá lâu.
        "RR": 2.5,                                  # [TỐI ƯU] - Breakout thật thường có tiềm năng lợi nhuận lớn.
        "ATR_SL_MULTIPLIER": 2.4,                   # [CHỊU ĐÒN] - SL đủ rộng để không bị cú retest đá ra khỏi lệnh.
        "USE_TRAILING_SL": True, "TRAIL_ACTIVATION_RR": 1.5, "TRAIL_DISTANCE_RR": 1.0,
        "ENABLE_PARTIAL_TP": True, "TP1_RR_RATIO": 1.0, "TP1_PROFIT_PCT": 0.5,
        "USE_MOMENTUM_FILTER": True,                # [BẮT BUỘC] - Breakout không có momentum là breakout chết.
        "USE_EXTREME_ZONE_FILTER": False,
        "USE_PRICE_ACTION_MOMENTUM": True,
    },
    # == TACTIC 3: Bậc Thầy Bắt Sóng Hồi ==
    "Dip_Hunter": {
        "OPTIMAL_ZONE": [LEADING_ZONE, COINCIDENT_ZONE],
        "NOTES": "Bắt đáy/sóng hồi với một cái lưới an toàn CỰC RỘNG. Ăn nhanh, thoát nhanh.",
        "WEIGHTS": {'tech': 0.5, 'context': 0.2, 'ai': 0.3},
        "ENTRY_SCORE": 6.8,                         # [NỚI LỎNG] - Chấp nhận tín hiệu bắt đáy chưa hoàn hảo.
        "RR": 1.5,                                  # [AN TOÀN] - Bắt đáy rủi ro, không nên tham lam.
        "ATR_SL_MULTIPLIER": 3.2,                   # [CHỊU ĐÒN] - "Lưới an toàn" dày nhất, cho phép giá quét sâu trước khi đảo chiều.
        "USE_TRAILING_SL": False,                   # [LOGIC] - Không kéo SL vì dễ bị quét khi giá hồi.
        "ENABLE_PARTIAL_TP": True, "TP1_RR_RATIO": 0.7, "TP1_PROFIT_PCT": 0.6, # Chốt phần lớn ở TP1.
        "USE_MOMENTUM_FILTER": False,                 # [LOGIC] - Khi bắt đáy, động lượng thường đang yếu.
        "USE_EXTREME_ZONE_FILTER": True,
        "USE_PRICE_ACTION_MOMENTUM": True,
    },
    # == TACTIC 4: Chuyên Gia Chớp Nhoáng ==
    "AI_Aggressor": {
        "OPTIMAL_ZONE": [COINCIDENT_ZONE],
        "NOTES": "Chuyên gia chớp nhoáng: Tận dụng điểm AI siêu cao để vào nhanh, ăn ngắn, thoát nhanh.",
        "WEIGHTS": {'tech': 0.3, 'context': 0.1, 'ai': 0.6},
        "ENTRY_SCORE": 6.8,                         # [SIẾT CHẶT] - Đã dựa vào AI thì tín hiệu phải thực sự xuất sắc.
        "RR": 1.8,                                  # [CHIẾN LƯỢC] - Đánh nhanh, ăn ngắn.
        "ATR_SL_MULTIPLIER": 2.2,                   # [CHIẾN LƯỢC] - SL chặt hơn, phù hợp với việc đánh nhanh.
        "USE_TRAILING_SL": True, "TRAIL_ACTIVATION_RR": 1.1, "TRAIL_DISTANCE_RR": 0.7,
        "ENABLE_PARTIAL_TP": True, "TP1_RR_RATIO": 0.7, "TP1_PROFIT_PCT": 0.6,
        "USE_MOMENTUM_FILTER": True,
        "USE_EXTREME_ZONE_FILTER": False,
        "USE_PRICE_ACTION_MOMENTUM": True,
    },
    # == TACTIC 5: Tay Bắn Tỉa ==
    "Cautious_Observer": {
        "OPTIMAL_ZONE": NOISE_ZONE,
        "NOTES": "Bắn tỉa cơ hội VÀNG trong vùng nhiễu. SL chặt, ăn nhanh, sai là cắt.",
        "WEIGHTS": {'tech': 0.6, 'context': 0.2, 'ai': 0.2},
        "ENTRY_SCORE": 7.5,                         # [SIẾT CHẶT] - Ngưỡng CỰC CAO để giao dịch an toàn trong vùng nguy hiểm.
        "RR": 1.5,                                  # [CHIẾN LƯỢC] - RR thấp, bản chất "ăn nhanh".
        "ATR_SL_MULTIPLIER": 1.8,                   # [CHIẾN LƯỢC] - SL hẹp hơn, sai trong vùng nhiễu là phải cắt ngay.
        "USE_TRAILING_SL": True, "TRAIL_ACTIVATION_RR": 1.0, "TRAIL_DISTANCE_RR": 0.7,
        "ENABLE_PARTIAL_TP": True, "TP1_RR_RATIO": 0.6, "TP1_PROFIT_PCT": 0.8,
        "USE_MOMENTUM_FILTER": True,
        "USE_EXTREME_ZONE_FILTER": True,
        "USE_PRICE_ACTION_MOMENTUM": True,
    },
}

# ==============================================================================
# BIẾN TOÀN CỤC & HẰNG SỐ
# ==============================================================================
SYMBOLS_TO_SCAN = [symbol.strip() for symbol in os.getenv("SYMBOLS_TO_SCAN", "ETHUSDT,BTCUSDT").split(',')]
INTERVALS_TO_SCAN, ALL_TIME_FRAMES = ["1h", "4h", "1d"], ["1h", "4h", "1d"]
VIETNAM_TZ = pytz.timezone('Asia/Ho_Chi_Minh')
LOG_FILE = os.path.join(LIVE_DATA_DIR, "live_trade_log.txt")
ERROR_LOG_FILE = os.path.join(LIVE_DATA_DIR, "error_log.txt")
STATE_FILE = os.path.join(LIVE_DATA_DIR, "live_trade_state.json")
LOCK_FILE = STATE_FILE + ".lock"
TRADE_HISTORY_CSV_FILE = os.path.join(LIVE_DATA_DIR, "live_trade_history.csv")
indicator_results, price_dataframes = {}, {}
SESSION_TEMP_KEYS = ['temp_newly_opened_trades', 'temp_newly_closed_trades', 'temp_money_spent_on_trades', 'temp_pnl_from_closed_trades', 'session_has_events']

# --- CÁC HÀM KHÓA FILE (FILE LOCKING) ---
def acquire_lock(timeout=55):
    LOCK_STALE_MINUTES = 5
    if os.path.exists(LOCK_FILE):
        try:
            file_mod_time = os.path.getmtime(LOCK_FILE)
            if (time.time() - file_mod_time) / 60 > LOCK_STALE_MINUTES:
                log_message(f"⚠️ Phát hiện file lock tồn tại hơn {LOCK_STALE_MINUTES} phút. Tự động xóa.")
                release_lock()
        except Exception as e:
            log_error(f"Lỗi khi kiểm tra file lock bị kẹt: {e}")
    start_time = time.time()
    while os.path.exists(LOCK_FILE):
        if time.time() - start_time > timeout:
            timestamp = datetime.now(VIETNAM_TZ).strftime('%Y-%m-%d %H:%M:%S')
            log_entry = f"[{timestamp}] (LiveTrade) ⏳ Bỏ qua phiên này, file trạng thái đang được khóa."
            print(log_entry)
            with open(LOG_FILE, "a", encoding="utf-8") as f: f.write(log_entry + "\n")
            return False
        time.sleep(1)
    try:
        with open(LOCK_FILE, 'w') as f: f.write(str(os.getpid()))
        return True
    except IOError: return False

def release_lock():
    try:
        if os.path.exists(LOCK_FILE): os.remove(LOCK_FILE)
    except OSError as e: log_error(f"Lỗi khi giải phóng file lock: {e}")

# --- CÁC HÀM TIỆN ÍCH ---
def format_price_dynamically(price: Optional[float]) -> str:
    """Định dạng giá một cách linh hoạt dựa trên giá trị của nó."""
    if price is None:
        return "N/A"
    if price >= 1.0:
        return f"{price:,.4f}"
    else:
        return f"{price:,.8f}"

def log_message(message: str, state: Optional[Dict] = None):
    if state is not None: state['session_has_events'] = True
    timestamp = datetime.now(VIETNAM_TZ).strftime('%Y-%m-%d %H:%M:%S')
    log_entry = f"[{timestamp}] (LiveTrade) {message}"
    print(log_entry)
    with open(LOG_FILE, "a", encoding="utf-8") as f: f.write(log_entry + "\n")

def log_error(message: str, error_details: str = "", send_to_discord: bool = False, force_discord: bool = False, state: Optional[Dict] = None):
    timestamp = datetime.now(VIETNAM_TZ).strftime('%Y-%m-%d %H:%M:%S')
    log_entry = f"[{timestamp}] (LiveTrade-ERROR) {message}\n"
    if error_details: log_entry += f"--- TRACEBACK ---\n{error_details}\n------------------\n"
    with open(ERROR_LOG_FILE, "a", encoding="utf-8") as f: f.write(log_entry)
    log_message(f"!!!!!! ❌ LỖI: {message}. Chi tiết trong error.log ❌ !!!!!!", state=state)
    if send_to_discord:
        discord_message = f"🔥🔥🔥 LỖI NGHIÊM TRỌNG 🔥🔥🔥\n**{message}**\n```python\n{error_details if error_details else 'N/A'}\n```"
        send_discord_message_chunks(discord_message, force=force_discord)

def load_json_file(path: str, default: Any = None) -> Any:
    if not os.path.exists(path): return default if default is not None else {}
    try:
        with open(path, "r", encoding="utf-8") as f: return json.load(f)
    except json.JSONDecodeError:
        log_error(f"File JSON hỏng: {path}. Sử dụng giá trị mặc định.", send_to_discord=True)
        return default if default is not None else {}

def save_json_file(path: str, data: Any):
    temp_path, data_to_save = path + ".tmp", data.copy()
    for key in SESSION_TEMP_KEYS: data_to_save.pop(key, None)
    with open(temp_path, "w", encoding="utf-8") as f: json.dump(data_to_save, f, indent=4, ensure_ascii=False)
    os.replace(temp_path, path)

_last_discord_send_time = None
def can_send_discord_now(force: bool = False) -> bool:
    global _last_discord_send_time
    if force: return True
    now = datetime.now()
    if _last_discord_send_time is None or (now - _last_discord_send_time).total_seconds() > 120:
        _last_discord_send_time = now
        return True
    return False

def send_discord_message_chunks(full_content: str, force: bool = False):
    if not can_send_discord_now(force): return
    webhook_url = ALERT_CONFIG.get("DISCORD_WEBHOOK_URL")
    if not webhook_url: return
    max_len, lines, chunks, current_chunk = 1900, full_content.split('\n'), [], ""
    for line in lines:
        if len(current_chunk) + len(line) + 1 > max_len:
            if current_chunk: chunks.append(current_chunk)
            current_chunk = line
        else: current_chunk += ("\n" + line) if current_chunk else line
    if current_chunk: chunks.append(current_chunk)
    for i, chunk in enumerate(chunks):
        content_to_send = f"*(Phần {i+1}/{len(chunks)})*\n{chunk}" if len(chunks) > 1 else chunk
        try:
            requests.post(webhook_url, json={"content": content_to_send}, timeout=15).raise_for_status()
            if i < len(chunks) - 1: time.sleep(ALERT_CONFIG["DISCORD_CHUNK_DELAY_SECONDS"])
        except requests.exceptions.RequestException as e:
            log_error(f"Lỗi gửi chunk Discord {i+1}/{len(chunks)}: {e}")
            break

def get_realtime_price(symbol: str) -> Optional[float]:
    if symbol == "USDT": return 1.0
    url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        return float(response.json()['price'])
    except requests.exceptions.RequestException as e:
        if 'timeout' not in str(e).lower() and 'failed to resolve' not in str(e).lower():
            log_error(f"Lỗi API khi lấy giá {symbol}: {e}")
        return None
    except Exception as e:
        log_error(f"Lỗi không xác định khi lấy giá {symbol}", error_details=traceback.format_exc())
        return None

def get_usdt_fund(bnc: BinanceConnector) -> Tuple[float, float]:
    try:
        balance_info = bnc.get_account_balance()
        usdt_balance = next((b for b in balance_info.get("balances", []) if b["asset"] == "USDT"), None)
        if usdt_balance: return float(usdt_balance['free']), float(usdt_balance['free']) + float(usdt_balance['locked'])
    except Exception as e:
        log_error(f"Không thể lấy số dư USDT từ Binance", error_details=traceback.format_exc())
    return 0.0, 0.0

def get_current_pnl(trade: Dict, realtime_price: Optional[float] = None) -> Tuple[float, float]:
    entry_price = trade.get('entry_price', 0) # Lấy giá entry ra biến riêng
    if not (trade and entry_price > 0 and realtime_price and realtime_price > 0): return 0.0, 0.0 # Kiểm tra entry_price > 0 là đủ

    pnl_multiplier = 1.0
    pnl_percent = (realtime_price - entry_price) / entry_price * 100 * pnl_multiplier
    pnl_usd = trade.get('total_invested_usd', 0.0) * (pnl_percent / 100)
    return pnl_usd, pnl_percent

def export_trade_history_to_csv(closed_trades: List[Dict]):
    if not closed_trades: return
    try:
        df = pd.DataFrame(closed_trades)

        # Thêm 'partial_pnl_details' vào danh sách cột
        full_columns_list = [
            "trade_id", "symbol", "interval", "status", "opened_by_tactic",
            "tactic_used", "trade_type", "entry_price", "exit_price", "tp", "sl",
            "initial_sl", "total_invested_usd", "pnl_usd", "pnl_percent",
            "entry_time", "exit_time", "holding_duration_hours", "entry_score",
            "last_score", "dca_entries", "partial_pnl_details", # Thêm vào đây
            "realized_pnl_usd", # Giữ lại để tương thích
            "binance_market_order_id", "entry_zone", "last_zone", "initial_entry"
        ]

        for col in full_columns_list:
            if col not in df.columns:
                df[col] = None

        # Chuyển đổi partial_pnl_details thành chuỗi JSON
        if 'partial_pnl_details' in df.columns:
            df['partial_pnl_details'] = df['partial_pnl_details'].apply(lambda x: json.dumps(x) if x else None)

        df = df[full_columns_list]

        entry_time_dt = pd.to_datetime(df['entry_time'], errors='coerce', utc=True).dt.tz_convert(VIETNAM_TZ)
        exit_time_dt = pd.to_datetime(df['exit_time'], errors='coerce', utc=True).dt.tz_convert(VIETNAM_TZ)
        valid_times = entry_time_dt.notna() & exit_time_dt.notna()
        df.loc[valid_times, 'holding_duration_hours'] = round((exit_time_dt[valid_times] - entry_time_dt[valid_times]).dt.total_seconds() / 3600, 2)
        df['entry_time'] = entry_time_dt.apply(lambda x: x.isoformat() if pd.notna(x) else None)
        df['exit_time'] = exit_time_dt.apply(lambda x: x.isoformat() if pd.notna(x) else None)

        for col in ['dca_entries', 'initial_entry', 'tactic_used']:
             if col in df.columns:
                 df[col] = df[col].apply(lambda x: json.dumps(x) if x else None)

        file_exists = os.path.exists(TRADE_HISTORY_CSV_FILE) and os.path.getsize(TRADE_HISTORY_CSV_FILE) > 0
        df.to_csv(TRADE_HISTORY_CSV_FILE, mode='a', header=not file_exists, index=False, encoding="utf-8")
        log_message(f"💾 Đã ghi {len(df)} giao dịch vào file live_trade_history.csv")
    except Exception as e:
        log_error(f"Lỗi xuất lịch sử giao dịch ra CSV", error_details=traceback.format_exc())


def get_interval_in_milliseconds(interval: str) -> Optional[int]:
    try:
        unit, value = interval[-1], int(interval[:-1])
        if unit == 'm': return value * 60 * 1000
        if unit == 'h': return value * 3600 * 1000
        if unit == 'd': return value * 86400 * 1000
    except (ValueError, IndexError): return None
    return None

def get_price_data(symbol: str, interval: str, limit: int = 200, startTime: int = None) -> Optional[pd.DataFrame]:
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    if startTime:
        params['startTime'] = startTime
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        if not data:
            return pd.DataFrame()
        df = pd.DataFrame(data, columns=["timestamp","open","high","low","close","volume","close_time","quote_asset_volume","number_of_trades","taker_buy_base_vol","taker_buy_quote_vol","ignore"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df.set_index("timestamp", inplace=True)
        cols_to_convert = ["open", "high", "low", "close", "volume"]
        df[cols_to_convert] = df[cols_to_convert].astype(float)
        return df
    except requests.exceptions.RequestException as e:
        log_error(f"Lỗi mạng khi lấy dữ liệu giá cho {symbol}-{interval}", error_details=str(e))
        return None
    except Exception as e:
        log_error(f"Lỗi không xác định khi lấy dữ liệu giá cho {symbol}-{interval}", error_details=traceback.format_exc())
        return None

def get_price_data_with_cache(symbol: str, interval: str, limit: int) -> Optional[pd.DataFrame]:
    cache_filepath = os.path.join(CACHE_DIR, f"{symbol}-{interval}.parquet")
    existing_df = None
    if os.path.exists(cache_filepath):
        try: existing_df = pd.read_parquet(cache_filepath)
        except Exception as e: log_error(f"Lỗi đọc file cache {cache_filepath}: {e}. Sẽ tải lại.")
    if existing_df is not None and not existing_df.empty:
        last_ts = int(existing_df.index[-1].timestamp() * 1000)
        interval_ms = get_interval_in_milliseconds(interval)
        if not interval_ms: return existing_df
        start_time = last_ts + interval_ms
        if int(datetime.now(timezone.utc).timestamp() * 1000) > start_time:
            new_data = get_price_data(symbol, interval, limit=limit, startTime=start_time)
            combined = pd.concat([existing_df, new_data]) if new_data is not None and not new_data.empty else existing_df
            combined = combined[~combined.index.duplicated(keep='last')]
        else:
            combined = existing_df
        final_df = combined.tail(limit).copy()
    else:
        final_df = get_price_data(symbol, interval, limit=limit)
    if final_df is not None and not final_df.empty:
        try:
            for col in final_df.select_dtypes(include=['float64']).columns:
                if col != 'close': final_df[col] = final_df[col].astype('float32')
            final_df.to_parquet(cache_filepath)
        except Exception as e:
            log_error(f"Lỗi lưu file cache {cache_filepath}: {e}")
        return final_df
    return existing_df if existing_df is not None else None

def close_trade_on_binance(bnc: BinanceConnector, trade: Dict, reason: str, state: Dict, close_pct: float = 1.0) -> bool:
    symbol = trade['symbol']
    side = "SELL"
    qty_in_state = float(trade.get('quantity', 0))
    final_quantity_to_sell = 0.0
    try:
        asset_code = symbol.replace("USDT", "")
        balances = bnc.get_account_balance().get("balances", [])
        asset_on_binance = next((b for b in balances if b["asset"] == asset_code), None)
        if not asset_on_binance or float(asset_on_binance.get('free', 0)) <= 0:
            log_error(f"Lỗi Đối soát: Không tìm thấy {asset_code} hoặc số dư = 0 trên sàn. Hủy đóng lệnh.", state=state)
            return False
        qty_on_binance = float(asset_on_binance['free'])
        log_message(f"ℹ️ Đối soát {symbol}: Bot ghi {qty_in_state:.8f}, Sàn có {qty_on_binance:.8f}", state)
        final_quantity_to_sell = min(qty_in_state, qty_on_binance) * close_pct
    except Exception as e:
        log_error(f"Lỗi API nghiêm trọng khi lấy số dư {symbol} để đóng lệnh. Hủy để đảm bảo an toàn.", error_details=str(e), state=state, send_to_discord=True)
        return False
    if final_quantity_to_sell <= 0:
        log_message(f"⚠️ Bỏ qua đóng lệnh {symbol} vì số lượng tính toán là zero hoặc âm.", state=state)
        return False
    trade.setdefault('close_retry_count', 0)
    try:
        market_close_order = bnc.place_market_order(symbol=symbol, side=side, quantity=final_quantity_to_sell)
        trade['close_retry_count'] = 0
    except Exception as e:
        trade['close_retry_count'] += 1
        log_error(f"Lỗi kết nối khi đóng lệnh {symbol} (Lần thử #{trade['close_retry_count']})", error_details=str(e), state=state)
        if trade['close_retry_count'] >= GENERAL_CONFIG.get("CLOSE_TRADE_RETRY_LIMIT", 3):
            log_error(message=f"Không thể đóng lệnh {symbol} sau {trade['close_retry_count']} lần thử. CẦN CAN THIỆP THỦ CÔNG!", error_details=traceback.format_exc(), send_to_discord=True, force_discord=True, state=state)
            trade['close_retry_count'] = 0
        return False
    if not (market_close_order and float(market_close_order.get('executedQty', 0)) > 0):
        log_error(f"Lệnh đóng {symbol} được gửi nhưng không khớp. Kiểm tra trên sàn.", state=state)
        return False
    closed_qty = float(market_close_order['executedQty'])
    money_gained = float(market_close_order['cummulativeQuoteQty'])
    exit_price = money_gained / closed_qty if closed_qty > 0 else trade['entry_price']
    state['money_gained_from_trades_last_session'] += money_gained
    pnl_usd_final_part = (exit_price - trade['entry_price']) * closed_qty
    state['temp_pnl_from_closed_trades'] += pnl_usd_final_part

    if 'partial_pnl_details' in trade:
        previous_realized_pnl = sum(trade['partial_pnl_details'].values())
    else:
        previous_realized_pnl = trade.get('realized_pnl_usd', 0.0)

    if close_pct >= 0.999:
        total_final_pnl_usd = previous_realized_pnl + pnl_usd_final_part
        initial_invested_usd = trade.get('initial_entry', {}).get('invested_usd', trade.get('total_invested_usd', 1))
        if initial_invested_usd <= 0: initial_invested_usd = 1
        pnl_percent = (total_final_pnl_usd / initial_invested_usd) * 100
        exit_time_dt = datetime.now(VIETNAM_TZ)
        entry_time_dt = datetime.fromisoformat(trade['entry_time'])
        holding_hours = round((exit_time_dt - entry_time_dt).total_seconds() / 3600, 2)
        trade.update({
            'status': f'Closed ({reason})', 'exit_price': exit_price, 'exit_time': exit_time_dt.isoformat(),
            'holding_duration_hours': holding_hours, 'pnl_usd': total_final_pnl_usd, 'pnl_percent': pnl_percent
        })
        state['active_trades'] = [t for t in state['active_trades'] if t['trade_id'] != trade['trade_id']]
        state['trade_history'].append(trade)
        state['trade_history'] = state['trade_history'][-100:]

        # --- [BẮT ĐẦU] CẬP NHẬT THỐNG KÊ GIAO DỊCH (v9.2) ---
        stats = state.setdefault('trade_stats', {
            "total_trades_closed": 0, "winning_trades": 0, "total_pnl_usd": 0.0,
            "total_win_pnl_usd": 0.0, "total_loss_pnl_usd": 0.0,
            "total_tp1_pnl": 0.0, "total_pp_pnl": 0.0
        })
        stats['total_trades_closed'] += 1
        stats['total_pnl_usd'] += total_final_pnl_usd
        if total_final_pnl_usd > 0:
            stats['winning_trades'] += 1
            stats['total_win_pnl_usd'] += total_final_pnl_usd
        else:
            stats['total_loss_pnl_usd'] += total_final_pnl_usd
        
        # Cập nhật PnL từ chốt lời một phần vào thống kê tổng
        if 'partial_pnl_details' in trade and isinstance(trade.get('partial_pnl_details'), dict):
             partial_details = trade['partial_pnl_details']
             stats.setdefault('total_tp1_pnl', 0.0)
             stats.setdefault('total_pp_pnl', 0.0)
             stats['total_tp1_pnl'] += partial_details.get('TP1', 0.0)
             stats['total_pp_pnl'] += partial_details.get('PP', 0.0)
        # --- [KẾT THÚC] CẬP NHẬT THỐNG KÊ GIAO DỊCH ---

        trade_interval = trade.get('interval', '1h')
        cooldown_dict = state.setdefault('cooldown_until', {})
        symbol_cooldowns = cooldown_dict.setdefault(symbol, {})
        symbol_cooldowns[trade_interval] = (datetime.now(VIETNAM_TZ) + timedelta(hours=GENERAL_CONFIG["TRADE_COOLDOWN_HOURS"])).isoformat()
        export_trade_history_to_csv([trade])
        state.setdefault('temp_newly_closed_trades', []).append(f"🎬 {'✅' if total_final_pnl_usd >= 0 else '❌'} {symbol} (Đóng toàn bộ - {reason}): PnL ${total_final_pnl_usd:,.2f}")
    else:
        trade.setdefault('partial_pnl_details', {'TP1': 0.0, 'PP': 0.0, 'Other': 0.0})
        pnl_category = 'Other'
        if reason.startswith("TP1"):
            pnl_category = 'TP1'
        elif reason.startswith("Protect_Profit"):
            pnl_category = 'PP'
        elif reason.startswith("EC_"):
            pnl_category = 'Other'
        trade['partial_pnl_details'][pnl_category] += pnl_usd_final_part
        if 'total_invested_usd' in trade and trade['total_invested_usd'] > 0:
            original_qty = qty_in_state
            closed_ratio = closed_qty / original_qty if original_qty > 0 else 0
            trade['total_invested_usd'] *= (1 - closed_ratio)
        trade['quantity'] -= closed_qty
        trade.setdefault('tactic_used', []).append(f"Partial_Close_{reason}")
        state.setdefault('temp_newly_closed_trades', []).append(f"💰 {symbol} (Đóng {close_pct*100:.0f}% - {reason}): PnL ${pnl_usd_final_part:,.2f}")
    return True

def check_and_manage_open_positions(bnc: BinanceConnector, state: Dict, realtime_prices: Dict[str, float]):
    active_trades = state.get("active_trades", [])[:]
    if not active_trades: return
    min_order_value = GENERAL_CONFIG.get("MIN_ORDER_VALUE_USDT", 11.0)
    for trade in active_trades:
        symbol, tactic_name = trade['symbol'], trade.get('opened_by_tactic')
        tactic_cfg = TACTICS_LAB.get(tactic_name, {})
        current_price = realtime_prices.get(symbol)
        if not current_price: continue
        precise_price_for_sl = get_realtime_price(symbol)
        if precise_price_for_sl is not None:
            current_price = precise_price_for_sl
        if current_price <= trade['sl']:
            if close_trade_on_binance(bnc, trade, "SL", state): continue
        if current_price >= trade['tp']:
            if close_trade_on_binance(bnc, trade, "TP", state): continue
        last_score, entry_score = trade.get('last_score', 5.0), trade.get('entry_score', 5.0)
        if last_score < ACTIVE_TRADE_MANAGEMENT_CONFIG['EARLY_CLOSE_ABSOLUTE_THRESHOLD']:
            if close_trade_on_binance(bnc, trade, f"EC_Abs_{last_score:.1f}", state): continue
        if last_score < entry_score and not trade.get('is_in_warning_zone', False):
            trade['is_in_warning_zone'] = True
        if trade.get('is_in_warning_zone', False) and not trade.get('partial_closed_by_score', False):
            if last_score < entry_score * (1 - ACTIVE_TRADE_MANAGEMENT_CONFIG.get('EARLY_CLOSE_RELATIVE_DROP_PCT', 0.35)):
                close_pct = ACTIVE_TRADE_MANAGEMENT_CONFIG.get("PARTIAL_EARLY_CLOSE_PCT", 0.5)
                remaining_value = (trade.get('quantity', 0) * (1 - close_pct)) * current_price
                if remaining_value < min_order_value:
                    log_message(f"⚠️ {symbol}: Giá trị còn lại ({remaining_value:.2f}$) quá nhỏ. Đóng toàn bộ thay vì một phần.", state)
                    close_pct = 1.0
                if close_trade_on_binance(bnc, trade, f"EC_Rel_{last_score:.1f}", state, close_pct=close_pct):
                    trade['partial_closed_by_score'] = True
        _, pnl_percent = get_current_pnl(trade, realtime_price=current_price)
        trade['peak_pnl_percent'] = max(trade.get('peak_pnl_percent', 0.0), pnl_percent)

        initial_risk_dist = trade.get('atr_risk_dist', 0)
        if initial_risk_dist <= 0:
            initial_risk_dist = abs(trade.get('initial_entry', {}).get('price', 0) - trade.get('initial_sl', 0))
            if initial_risk_dist <= 0: continue

        if tactic_cfg.get("ENABLE_PARTIAL_TP", False) and not trade.get("tp1_hit", False) and initial_risk_dist > 0:
            pnl_ratio = (current_price - trade['entry_price']) / initial_risk_dist
            if pnl_ratio >= tactic_cfg.get("TP1_RR_RATIO", 1.0):
                close_pct = tactic_cfg.get("TP1_PROFIT_PCT", 0.5)
                remaining_value = (trade.get('quantity', 0) * (1 - close_pct)) * current_price
                if remaining_value < min_order_value:
                    log_message(f"⚠️ {symbol}: Giá trị còn lại ({remaining_value:.2f}$) sau TP1 quá nhỏ. Đóng toàn bộ.", state)
                    close_pct = 1.0
                if close_trade_on_binance(bnc, trade, f"TP1_{tactic_cfg.get('TP1_RR_RATIO', 1.0):.1f}R", state, close_pct=close_pct):
                    trade['tp1_hit'] = True
                    if close_pct < 1.0: trade['sl'] = trade['entry_price']
        pp_config = ACTIVE_TRADE_MANAGEMENT_CONFIG.get("PROFIT_PROTECTION", {})
        if pp_config.get("ENABLED", False) and not trade.get('profit_taken', False) and trade['peak_pnl_percent'] >= pp_config.get("MIN_PEAK_PNL_TRIGGER", 3.5):
            if (trade['peak_pnl_percent'] - pnl_percent) >= pp_config.get("PNL_DROP_TRIGGER_PCT", 2.0):
                close_pct = pp_config.get("PARTIAL_CLOSE_PCT", 0.7)
                remaining_value = (trade.get('quantity', 0) * (1 - close_pct)) * current_price
                if remaining_value < min_order_value:
                    log_message(f"⚠️ {symbol}: Giá trị còn lại ({remaining_value:.2f}$) sau Profit-Protect quá nhỏ. Đóng toàn bộ.", state)
                    close_pct = 1.0
                if close_trade_on_binance(bnc, trade, "Protect_Profit", state, close_pct=close_pct):
                    trade['profit_taken'] = True
                    if close_pct < 1.0: trade['sl'] = trade['entry_price']
        if tactic_cfg.get("USE_TRAILING_SL", False) and initial_risk_dist > 0:
            pnl_ratio_from_entry = (current_price - trade['entry_price']) / initial_risk_dist
            if pnl_ratio_from_entry >= tactic_cfg.get("TRAIL_ACTIVATION_RR", float('inf')):
                new_sl = current_price - (initial_risk_dist * tactic_cfg.get("TRAIL_DISTANCE_RR", 0.8))
                if new_sl > trade['sl']:
                    state.setdefault('temp_newly_closed_trades', []).append(f"⚙️ TSL {symbol}: SL mới {new_sl:.4f} (cũ {trade['sl']:.4f})")
                    trade['sl'] = new_sl
                    if "Trailing_SL_Active" not in trade.get('tactic_used', []):
                        trade.setdefault('tactic_used', []).append("Trailing_SL_Active")


def handle_stale_trades(bnc: BinanceConnector, state: Dict, realtime_prices: Dict[str, float]):
    now_aware = datetime.now(VIETNAM_TZ)
    for trade in state.get("active_trades", [])[:]:
        if 'stale_override_until' in trade and now_aware < datetime.fromisoformat(trade['stale_override_until']):
            continue
        rules = RISK_RULES_CONFIG["STALE_TRADE_RULES"].get(trade.get("interval"))
        if not rules: continue
        holding_hours = (now_aware - datetime.fromisoformat(trade['entry_time'])).total_seconds() / 3600
        if holding_hours > rules["HOURS"]:
            _, pnl_pct = get_current_pnl(trade, realtime_price=realtime_prices.get(trade['symbol']))
            if pnl_pct < rules["PROGRESS_THRESHOLD_PCT"] and trade.get('last_score', 5.0) < RISK_RULES_CONFIG["STALE_TRADE_RULES"]["STAY_OF_EXECUTION_SCORE"]:
                close_trade_on_binance(bnc, trade, "Stale", state)

def handle_dca_opportunities(bnc: BinanceConnector, state: Dict, available_usdt: float, total_usdt_fund: float, realtime_prices: Dict[str, float]):
    if not DCA_CONFIG["ENABLED"]: return
    current_exposure_usd = sum(t.get('total_invested_usd', 0.0) for t in state.get("active_trades", []))
    exposure_limit = total_usdt_fund * CAPITAL_MANAGEMENT_CONFIG["MAX_TOTAL_EXPOSURE_PCT"]
    now = datetime.now(VIETNAM_TZ)
    min_order_value = GENERAL_CONFIG.get("MIN_ORDER_VALUE_USDT", 11.0)
    for trade in state.get("active_trades", [])[:]:
        symbol = trade.get("symbol")
        if not symbol: continue
        if len(trade.get("dca_entries", [])) >= DCA_CONFIG["MAX_DCA_ENTRIES"]: continue
        if trade.get('last_dca_time') and (now - datetime.fromisoformat(trade.get('last_dca_time'))).total_seconds() / 3600 < DCA_CONFIG['DCA_COOLDOWN_HOURS']: continue

        current_price = realtime_prices.get(symbol)
        if not current_price or current_price <= 0: continue

        last_entry_price = trade['dca_entries'][-1]['price'] if trade.get('dca_entries') else trade['initial_entry']['price']
        price_drop_pct = ((current_price - last_entry_price) / last_entry_price) * 100

        # --- LOGIC ĐỌC CẤU HÌNH DCA THEO KHUNG THỜI GIAN ---
        dca_trigger_map = DCA_CONFIG.get("TRIGGER_DROP_PCT_BY_TIMEFRAME", {})
        # Lấy ra ngưỡng DCA cho đúng khung thời gian của lệnh, mặc định là -4.5% nếu không có
        dca_trigger_for_interval = dca_trigger_map.get(trade.get('interval'), -4.5)

        if price_drop_pct > dca_trigger_for_interval:
            continue
        # --- KẾT THÚC LOGIC MỚI ---

        if get_advisor_decision(symbol, trade['interval'], indicator_results.get(symbol, {}).get(trade["interval"], {}), ADVISOR_BASE_CONFIG).get("final_score", 0.0) < DCA_CONFIG["SCORE_MIN_THRESHOLD"]: continue

        dca_investment = (trade['dca_entries'][-1]['invested_usd'] if trade.get('dca_entries') else trade['initial_entry']['invested_usd']) * DCA_CONFIG["CAPITAL_MULTIPLIER"]
        if dca_investment < min_order_value:
            log_message(f"⚠️ Bỏ qua DCA cho {symbol}: Vốn DCA dự tính ({dca_investment:,.2f}$) quá nhỏ.", state=state)
            continue

        if dca_investment <= 0 or dca_investment > available_usdt or (current_exposure_usd + dca_investment) > exposure_limit: continue

        try:
            state.setdefault('temp_newly_closed_trades', []).append(f"🎯 Thử DCA cho {symbol}...")
            market_dca_order = bnc.place_market_order(symbol=symbol, side="BUY", quote_order_qty=round(dca_investment, 2))
            if not (market_dca_order and market_dca_order.get('status') == 'FILLED'):
                raise Exception("Lệnh Market DCA không khớp.")
            dca_qty = float(market_dca_order['executedQty'])
            dca_cost = float(market_dca_order['cummulativeQuoteQty'])
            state['money_spent_on_trades_last_session'] += dca_cost
            dca_price = dca_cost / dca_qty if dca_qty > 0 else 0
            trade.setdefault('dca_entries', []).append({"price": dca_price, "quantity": dca_qty, "invested_usd": dca_cost, "timestamp": now.isoformat()})
            new_total_qty = float(trade['quantity']) + dca_qty
            new_total_cost = trade['total_invested_usd'] + dca_cost
            new_avg_price = new_total_cost / new_total_qty if new_total_qty > 0 else 0
            initial_risk_dist = abs(trade['initial_entry']['price'] - trade['initial_sl'])
            raw_new_sl = new_avg_price - initial_risk_dist
            raw_new_tp = new_avg_price + (initial_risk_dist * TACTICS_LAB[trade['opened_by_tactic']]['RR'])
            final_new_sl = float(bnc._format_price(symbol, raw_new_sl))
            final_new_tp = float(bnc._format_price(symbol, raw_new_tp))
            trade.update({
                'entry_price': new_avg_price,
                'total_invested_usd': new_total_cost,
                'quantity': new_total_qty,
                'sl': final_new_sl,
                'tp': final_new_tp,
                'last_dca_time': now.isoformat()
            })
            trade.setdefault('tactic_used', []).append(f"DCA_{len(trade.get('dca_entries', []))}")
            state.setdefault('temp_newly_closed_trades', []).append(f"  => ✅ DCA thành công {symbol} với ${dca_cost:,.2f}")
        except Exception as e:
            log_error(f"Lỗi nghiêm trọng khi DCA {symbol}", error_details=traceback.format_exc(), send_to_discord=True, state=state)

def is_momentum_confirmed(symbol: str, interval: str, direction: str = "LONG") -> bool:
    config = GENERAL_CONFIG.get("MOMENTUM_FILTER_CONFIG", {})
    if not config.get("ENABLED", False):
        return True

    rules = config.get("RULES_BY_TIMEFRAME", {}).get(interval, {"WINDOW": 3, "REQUIRED_CANDLES": 2})
    window = rules.get("WINDOW", 3)
    required_candles = rules.get("REQUIRED_CANDLES", 2)

    try:
        df = price_dataframes.get(symbol, {}).get(interval)
        if df is None or len(df) < window + 1:
            return True

        # Bỏ qua nến cuối cùng (chưa đóng)
        recent_candles = df.iloc[-(window+1):-1]

        good_candles_count = 0
        debug_info = []

        for idx, (timestamp, candle) in enumerate(recent_candles.iterrows()):
            candle_range = candle['high'] - candle['low']

            if candle_range <= 0:
                debug_info.append(f"Nến {idx+1}: SKIP (range=0)")
                continue

            is_green = candle['close'] >= candle['open']
            closing_position = (candle['close'] - candle['low']) / candle_range

            if is_green:
                good_candles_count += 1
                debug_info.append(f"Nến {idx+1}: ✅ XANH")
            elif closing_position > 0.6:
                good_candles_count += 1
                debug_info.append(f"Nến {idx+1}: ✅ ĐỎ-TỐT (đóng {closing_position:.1%})")
            else:
                debug_info.append(f"Nến {idx+1}: ❌ ĐỎ-XẤU (đóng {closing_position:.1%})")

        # Debug log khi KHÔNG ĐẠT
        passed = good_candles_count >= required_candles
        if not passed:
            log_message(f"⚠️ Momentum Filter - {symbol}-{interval}: {good_candles_count}/{required_candles} nến tốt")  # BỎ state
            for info in debug_info:
                log_message(f"     {info}")  # BỎ state

        return passed

    except Exception as e:
        log_error(f"Lỗi trong is_momentum_confirmed cho {symbol}-{interval}", error_details=str(e))
        return True


def determine_market_zone_with_scoring(symbol: str, interval: str) -> str:
    indicators = indicator_results.get(symbol, {}).get(interval, {})
    df = price_dataframes.get(symbol, {}).get(interval)
    if not indicators or df is None or df.empty: return NOISE_ZONE
    scores = {LEADING_ZONE: 0, COINCIDENT_ZONE: 0, LAGGING_ZONE: 0, NOISE_ZONE: 0}
    adx, bb_width, rsi_14, trend = indicators.get('adx', 20), indicators.get('bb_width', 0), indicators.get('rsi_14', 50), indicators.get('trend', "sideways")
    if adx < 20: scores[NOISE_ZONE] += 3
    if 'ema_50' in df.columns and np.sign(df['close'].iloc[-30:] - df['ema_50'].iloc[-30:]).diff().ne(0).sum() > 4:
        scores[NOISE_ZONE] += 2
    if adx > 25: scores[LAGGING_ZONE] += 2.5
    if trend == "uptrend": scores[LAGGING_ZONE] += 2
    if 'ema_20' in df.columns and 'ema_50' in df.columns and not df['ema_20'].isna().all() and not df['ema_50'].isna().all():
        if trend == "uptrend" and df['ema_20'].iloc[-1] > df['ema_50'].iloc[-1] and df['ema_20'].iloc[-10] > df['ema_50'].iloc[-10]:
            scores[LAGGING_ZONE] += 1.5
    if 'bb_width' in df.columns and not df['bb_width'].isna().all() and bb_width < df['bb_width'].iloc[-100:].quantile(0.20):
        scores[LEADING_ZONE] += 2.5
    htf_trend = indicator_results.get(symbol, {}).get('4h' if interval == '1h' else '1d', {}).get('trend', 'sideway')
    if htf_trend == 'uptrend' and rsi_14 < 45: scores[LEADING_ZONE] += 2
    if indicators.get('breakout_signal', "none") != "none": scores[COINCIDENT_ZONE] += 3
    if indicators.get('macd_cross', "neutral") not in ["neutral", "no_cross"]: scores[COINCIDENT_ZONE] += 2
    if indicators.get('vol_ma20', 1) > 0 and indicators.get('volume', 0) > indicators.get('vol_ma20', 1) * 2:
        scores[COINCIDENT_ZONE] += 1.5
    if adx > 28: scores[LEADING_ZONE] -= 2
    return max(scores, key=scores.get) if scores and any(v > 0 for v in scores.values()) else NOISE_ZONE

def find_and_open_new_trades(bnc: BinanceConnector, state: Dict, available_usdt: float, total_usdt_fund: float):
    if len(state.get("active_trades", [])) >= RISK_RULES_CONFIG["MAX_ACTIVE_TRADES"]: return
    potential_opportunities = []
    now_vn = datetime.now(VIETNAM_TZ)
    cooldown_map = state.get('cooldown_until', {})
    timeframe_levels = {"1h": 1, "4h": 2, "1d": 3}
    for symbol in SYMBOLS_TO_SCAN:
        if any(t['symbol'] == symbol for t in state.get("active_trades", [])): continue
        symbol_cooldowns = cooldown_map.get(symbol, {})
        for interval in INTERVALS_TO_SCAN:
            is_in_cooldown = False
            cooldown_source = None
            for source_tf, source_level in timeframe_levels.items():
                if source_level >= timeframe_levels[interval]:
                    if source_tf in symbol_cooldowns and now_vn < datetime.fromisoformat(symbol_cooldowns[source_tf]):
                        is_in_cooldown = True
                        cooldown_source = source_tf
                        break
            market_zone = determine_market_zone_with_scoring(symbol, interval)
            for tactic_name, tactic_cfg in TACTICS_LAB.items():
                optimal_zones = tactic_cfg.get("OPTIMAL_ZONE", [])
                if not isinstance(optimal_zones, list): optimal_zones = [optimal_zones]
                if market_zone in optimal_zones:
                    indicators = indicator_results.get(symbol, {}).get(interval)
                    if not (indicators and indicators.get('price', 0) > 0): continue

                    decision = get_advisor_decision(symbol, interval, indicators, ADVISOR_BASE_CONFIG, weights_override=tactic_cfg.get("WEIGHTS"))
                    raw_score = decision.get("final_score", 0.0)

                    mtf_coeff = get_mtf_adjustment_coefficient(symbol, interval)

                    ez_coeff = 1.0
                    if tactic_cfg.get("USE_EXTREME_ZONE_FILTER", False):
                        ez_coeff = get_extreme_zone_adjustment_coefficient(indicators, interval)

                    pam_coeff = 1.0
                    if tactic_cfg.get("USE_PRICE_ACTION_MOMENTUM", False):
                        pam_coeff = get_price_action_momentum_coefficient(symbol, interval)

                    contextual_score = raw_score * mtf_coeff * ez_coeff * pam_coeff

                    if is_in_cooldown:
                        if contextual_score >= GENERAL_CONFIG["OVERRIDE_COOLDOWN_SCORE"]:
                            log_message(f"🔥 {symbol}-{interval} có điểm {contextual_score:.2f}, phá vỡ cooldown từ {cooldown_source}.", state)
                        else: continue
                    potential_opportunities.append({"decision": decision, "tactic_name": tactic_name, "tactic_cfg": tactic_cfg, "score": contextual_score, "symbol": symbol, "interval": interval, "zone": market_zone})

    log_message("---[🔍 Quét Cơ Hội Mới 🔍]---", state=state)
    if not potential_opportunities:
        log_message("  => Không tìm thấy cơ hội tiềm năng nào.", state=state)
        return

    timeframe_priority = {"1h": 0, "4h": 1, "1d": 2}
    sorted_opportunities = sorted(potential_opportunities, key=lambda x: (x['score'], timeframe_priority.get(x['interval'], 0)), reverse=True)
    num_to_check = GENERAL_CONFIG.get("TOP_N_OPPORTUNITIES_TO_CHECK", 7)
    top_opportunities = sorted_opportunities[:num_to_check]
    log_message(f"---[🏆 Xem xét {len(top_opportunities)} cơ hội hàng đầu (tối đa {num_to_check})]--", state=state)

    found_executable_trade = False
    for i, opportunity in enumerate(top_opportunities):
        score = opportunity['score']
        entry_score_threshold = opportunity['tactic_cfg'].get("ENTRY_SCORE", 9.9)
        tactic_cfg = opportunity.get('tactic_cfg', {})
        tactic_name = opportunity.get('tactic_name', 'Unknown')

        raw_score_val = opportunity['decision'].get('final_score', 0.0)

        # Lấy lại hệ số để logging
        indicators_log = indicator_results.get(opportunity['symbol'], {}).get(opportunity['interval'], {})
        mtf_log_coeff = get_mtf_adjustment_coefficient(opportunity['symbol'], opportunity['interval'])
        ez_log_coeff = 1.0
        if tactic_cfg.get("USE_EXTREME_ZONE_FILTER", False) and indicators_log:
            ez_log_coeff = get_extreme_zone_adjustment_coefficient(indicators_log, opportunity['interval'])

        pam_log_coeff = 1.0
        if tactic_cfg.get("USE_PRICE_ACTION_MOMENTUM", False):
            pam_log_coeff = get_price_action_momentum_coefficient(opportunity['symbol'], opportunity['interval'])

        # Dòng log chính
        log_message(f"  #{i+1}: {opportunity['symbol']}-{opportunity['interval']} | Tactic: {tactic_name} | Gốc: {raw_score_val:.2f} | Bối cảnh: {score:.2f} (Ngưỡng: {entry_score_threshold})", state=state)
        # Dòng log chi tiết
        if mtf_log_coeff != 1.0 or ez_log_coeff != 1.0 or pam_log_coeff != 1.0:
            log_message(f"     Chi tiết điều chỉnh: [MTF: x{mtf_log_coeff:.2f}] [EZ: x{ez_log_coeff:.2f}] [PAM: x{pam_log_coeff:.2f}]", state)

        if score >= entry_score_threshold:
            if not tactic_cfg.get("USE_MOMENTUM_FILTER", False):
                log_message(f"     => ✅ Đạt ngưỡng! Tactic '{tactic_name}' không cần lọc động lượng. Đưa vào hàng chờ.", state=state)
                state['pending_trade_opportunity'] = opportunity
                state['pending_trade_opportunity']['retry_count'] = 0
                found_executable_trade = True
                break
            elif is_momentum_confirmed(opportunity['symbol'], opportunity['interval']):
                log_message(f"     => ✅ Đạt ngưỡng VÀ Tactic '{tactic_name}' đã được xác nhận động lượng! Đưa vào hàng chờ.", state=state)
                state['pending_trade_opportunity'] = opportunity
                state['pending_trade_opportunity']['retry_count'] = 0
                found_executable_trade = True
                break
            else:
                log_message(f"     => ⚠️ Đạt ngưỡng NHƯNG Tactic '{tactic_name}' không vượt qua bộ lọc động lượng. Bỏ qua.", state=state)
                continue
        else:
            log_message("     => 📉 Không đạt ngưỡng. Xem xét cơ hội tiếp theo...", state=state)

    if not found_executable_trade:
        log_message(f"  => Không có cơ hội nào trong top {len(top_opportunities)} đạt ngưỡng vào lệnh. Chờ phiên sau.", state=state)


def execute_trade_opportunity(bnc: BinanceConnector, state: Dict, available_usdt: float, total_usdt_fund: float):
    opportunity = state.get('pending_trade_opportunity')
    if not opportunity: return
    symbol, interval, tactic_name, zone = opportunity['symbol'], opportunity['interval'], opportunity['tactic_name'], opportunity['zone']
    log_message(f"---[⚡ Chuẩn bị thực thi {symbol}-{interval} ⚡]---", state=state)
    tactic_cfg = opportunity['tactic_cfg']
    full_indicators = opportunity['decision'].get('full_indicators', {})
    realtime_price = get_realtime_price(symbol)
    if not realtime_price or realtime_price <= 0:
        log_error(f"Không thể lấy giá realtime cho {symbol} để thực thi. Hủy cơ hội.", state=state)
        state.pop('pending_trade_opportunity', None)
        return
    entry_price_estimate = realtime_price

    risk_dist_from_atr = full_indicators.get('atr', 0) * tactic_cfg.get("ATR_SL_MULTIPLIER", 2.0)
    if risk_dist_from_atr <= 0:
        log_error(f"Tính toán risk_dist_from_atr cho {symbol} không hợp lệ. Hủy cơ hội.", state=state)
        state.pop('pending_trade_opportunity', None)
        return

    min_sl_dist = entry_price_estimate * RISK_RULES_CONFIG["MIN_RISK_DIST_PERCENT_BY_TIMEFRAME"].get(interval, 0.02)
    max_sl_dist = entry_price_estimate * RISK_RULES_CONFIG["MAX_SL_PERCENT_BY_TIMEFRAME"].get(interval, 0.10)

    sl_risk_dist = risk_dist_from_atr
    if sl_risk_dist < min_sl_dist:
        log_message(f"  ... 🛡️ SL theo ATR ({risk_dist_from_atr:.4f}) nhỏ hơn 'khiên' ({min_sl_dist:.4f}). Đặt theo 'khiên'.", state=state)
        sl_risk_dist = min_sl_dist

    if sl_risk_dist > max_sl_dist:
        log_message(f"  ... 🛑 SL ({sl_risk_dist:.4f}) quá rộng. Đặt theo Trần an toàn: {max_sl_dist:.4f}", state=state)
        sl_risk_dist = max_sl_dist

    capital_pct = ZONE_BASED_POLICIES.get(zone, {}).get("CAPITAL_PCT", 0.03)
    stable_capital_base = state.get('initial_capital', total_usdt_fund)
    invested_amount = stable_capital_base * capital_pct
    log_message(f"  ... Tính vốn dựa trên nền tảng Vốn BĐ năng động: ${stable_capital_base:,.2f}", state=state)
    current_exposure_usd = sum(t.get('total_invested_usd', 0.0) for t in state.get("active_trades", []))
    min_order_value = GENERAL_CONFIG.get("MIN_ORDER_VALUE_USDT", 11.0)
    if invested_amount < min_order_value:
        log_message(f"  ⚠️ Vốn tính toán (${invested_amount:.2f}) nhỏ hơn mức tối thiểu. Tăng lên mức tối thiểu là ${min_order_value}.", state=state)
        invested_amount = min_order_value
    if invested_amount > available_usdt or (current_exposure_usd + invested_amount) > total_usdt_fund * CAPITAL_MANAGEMENT_CONFIG["MAX_TOTAL_EXPOSURE_PCT"]:
        log_message(f"  => ❌ Không đủ vốn hoặc vượt ngưỡng rủi ro cho {symbol} (Sau khi điều chỉnh: ${invested_amount:.2f}). Hủy cơ hội.", state=state)
        state.pop('pending_trade_opportunity', None)
        return
    try:
        log_message(f"  => 🔥 Gửi lệnh MUA {symbol} với ${invested_amount:,.2f} (Vùng: {zone}, Vốn: {capital_pct*100:.1f}%)", state=state)
        market_order = bnc.place_market_order(symbol=symbol, side="BUY", quote_order_qty=round(invested_amount, 2))
        if not (market_order and float(market_order.get('executedQty', 0)) > 0):
            raise Exception("Lệnh Market không khớp hoặc không có thông tin trả về.")
        cost_of_trade = float(market_order['cummulativeQuoteQty'])
        state['money_spent_on_trades_last_session'] += cost_of_trade
        filled_qty = float(market_order['executedQty'])
        avg_price = float(market_order['cummulativeQuoteQty']) / filled_qty

        sl_p = avg_price - sl_risk_dist
        tp_p = avg_price + (risk_dist_from_atr * tactic_cfg.get("RR", 2.0))

        max_tp_pct_cfg = RISK_RULES_CONFIG["MAX_TP_PERCENT_BY_TIMEFRAME"].get(interval)
        if max_tp_pct_cfg is not None and tp_p > avg_price * (1 + max_tp_pct_cfg):
            tp_p = avg_price * (1 + max_tp_pct_cfg)
        if tp_p <= avg_price or sl_p >= avg_price or sl_p <= 0:
            raise Exception(f"SL/TP không hợp lệ: TP={tp_p}, SL={sl_p}, AvgPrice={avg_price}")
        new_trade = {
            "trade_id": str(uuid.uuid4()), "symbol": symbol, "interval": interval, "status": "ACTIVE",
            "opened_by_tactic": tactic_name, "trade_type": "LONG", "entry_price": avg_price,
            "quantity": filled_qty, "tp": tp_p, "sl": sl_p, "initial_sl": sl_p,
            "atr_risk_dist": risk_dist_from_atr,
            "initial_entry": {
                "price": avg_price,
                "quantity": filled_qty,
                "invested_usd": float(market_order['cummulativeQuoteQty'])
            },
            "total_invested_usd": float(market_order['cummulativeQuoteQty']),
            "entry_time": datetime.now(VIETNAM_TZ).isoformat(),
            "entry_score": opportunity['score'], "last_score": opportunity['score'],
            "entry_zone": zone, "last_zone": zone,
            "binance_market_order_id": market_order['orderId'], "dca_entries": [],
            "partial_pnl_details": {"TP1": 0.0, "PP": 0.0, "Other": 0.0},
            "peak_pnl_percent": 0.0, "tp1_hit": False, "profit_taken": False, "close_retry_count": 0
        }
        state['active_trades'].append(new_trade)
        state.setdefault('temp_newly_opened_trades', []).append(f"🔥 {symbol}-{interval} ({tactic_name}): Mua với vốn ${new_trade['total_invested_usd']:,.2f}")
        state.pop('pending_trade_opportunity', None)
    except Exception as e:
        retry_count = opportunity.get('retry_count', 0) + 1
        state['pending_trade_opportunity']['retry_count'] = retry_count
        log_error(f"Lỗi khi thực thi lệnh {symbol} (lần {retry_count})", error_details=traceback.format_exc(), state=state)
        if retry_count >= GENERAL_CONFIG["PENDING_TRADE_RETRY_LIMIT"]:
            log_error(f"Không thể mở lệnh {symbol} sau {retry_count} lần thử. Hủy bỏ.", send_to_discord=True, force_discord=True, state=state)
            state.pop('pending_trade_opportunity', None)

def get_mtf_adjustment_coefficient(symbol: str, target_interval: str, trade_type: str = "LONG") -> float:
    if not MTF_ANALYSIS_CONFIG["ENABLED"]:
        return 1.0
    trends = {tf: indicator_results.get(symbol, {}).get(tf, {}).get("trend", "sideways") for tf in ALL_TIME_FRAMES}
    cfg = MTF_ANALYSIS_CONFIG
    fav_trend = "uptrend" if trade_type == "LONG" else "downtrend"
    unfav_trend = "downtrend" if trade_type == "LONG" else "uptrend"

    if target_interval == "1h":
        trend_4h = trends.get("4h", "sideways")
        trend_1d = trends.get("1d", "sideways")
        if trend_4h == unfav_trend and trend_1d == unfav_trend:
            return cfg["SEVERE_PENALTY_COEFFICIENT"]
        if trend_4h == unfav_trend or trend_1d == unfav_trend:
            return cfg["PENALTY_COEFFICIENT"]
        # LUẬT MỚI: Chỉ thưởng khi CẢ HAI cùng ủng hộ
        if trend_4h == fav_trend and trend_1d == fav_trend:
            return cfg["BONUS_COEFFICIENT"]
        # Mặc định, nếu không rơi vào các trường hợp trên, nghĩa là có sự không chắc chắn -> PHẠT
        return cfg["SIDEWAYS_PENALTY_COEFFICIENT"]

    elif target_interval == "4h":
        trend_1d = trends.get("1d", "sideways")
        if trend_1d == unfav_trend:
            return cfg["PENALTY_COEFFICIENT"]
        if trend_1d == fav_trend:
            return cfg["BONUS_COEFFICIENT"]
        # Mặc định, nếu 1d không ủng hộ rõ ràng -> PHẠT
        return cfg["SIDEWAYS_PENALTY_COEFFICIENT"]

    elif target_interval == "1d":
        return cfg.get("BONUS_COEFFICIENT", 1.03)

    return 1.0

def get_extreme_zone_adjustment_coefficient(indicators: Dict, interval: str) -> float:
    """
    Tính toán hệ số điều chỉnh điểm số dựa trên các điều kiện thị trường cực đoan.
    Hàm này sẽ thưởng điểm (hệ số > 1.0) cho các tín hiệu mua trong vùng quá bán
    và phạt điểm (hệ số < 1.0) cho các tín hiệu mua trong vùng quá mua.
    PHIÊN BẢN NÂNG CẤP: Có khả năng nhận diện bối cảnh "BB Squeeze" để khuếch đại
    tác động của điểm thưởng/phạt, giúp bot hành động quyết đoán hơn khi thị trường
    sắp có biến động mạnh.
    """
    cfg = EXTREME_ZONE_ADJUSTMENT_CONFIG
    if not cfg.get("ENABLED", False) or not indicators:
        return 1.0

    # --- Lấy các cấu hình và chỉ báo cần thiết ---
    weights = cfg.get("SCORING_WEIGHTS", {})
    base_impact = cfg.get("BASE_IMPACT", {})
    confluence_multiplier = cfg.get("CONFLUENCE_MULTIPLIER", 1.5)
    rules = cfg.get("RULES_BY_TIMEFRAME", {}).get(interval)
    if not rules:
        return 1.0

    # Lấy giá trị các chỉ báo từ dictionary
    price = indicators.get("price", 0)
    bbu, bbm, bbl = indicators.get("bb_upper", 0), indicators.get("bb_middle", 0), indicators.get("bb_lower", 0)
    rsi = indicators.get("rsi_14", 50)
    candle = indicators.get("candle_pattern") or indicators.get("doji_type")
    sup_level, res_level = indicators.get("support_level", 0), indicators.get("resistance_level", 0)

    # Kiểm tra dữ liệu đầu vào có hợp lệ không
    if not all([price > 0, bbu > bbm, bbm > bbl]):
        return 1.0

    bonus_score, penalty_score = 0.0, 0.0
    confirmation_cfg = cfg.get("CONFIRMATION_BOOST", {})

    # --- 1. TÍNH TOÁN ĐIỂM THƯỞNG (CHO TÍN HIỆU QUÁ BÁN) ---
    oversold_rule = rules.get("OVERSOLD", {})
    bb_range_lower = bbm - bbl
    if bb_range_lower > 0:
        # Vị trí giá tương đối trong nửa dưới của dải BB (0-1)
        price_pos_lower = (price - bbl) / bb_range_lower
        if rsi < oversold_rule.get("RSI_BELOW", 1):
            bonus_score += weights.get("RSI", 0.4)
        if price_pos_lower < oversold_rule.get("BB_POS_BELOW", -0.1):
            bonus_score += weights.get("BB_POS", 0.4)

    # Yếu tố xác nhận bổ sung cho điểm thưởng
    if confirmation_cfg.get("ENABLED"):
        if candle in confirmation_cfg.get("BULLISH_CANDLES", []):
            bonus_score += weights.get("CANDLE", 0.2)
        is_near_support = sup_level > 0 and abs(price - sup_level) / price < confirmation_cfg.get("SUPPORT_PROXIMITY_PCT", 0.015)
        if is_near_support:
            bonus_score += weights.get("SR_LEVEL", 0.2)

    # --- 2. TÍNH TOÁN ĐIỂM PHẠT (CHO TÍN HIỆU QUÁ MUA) ---
    overbought_rule = rules.get("OVERBOUGHT", {})
    bb_range_upper = bbu - bbm
    if bb_range_upper > 0:
        # Vị trí giá tương đối trong nửa trên của dải BB (0-1)
        price_pos_upper = (price - bbm) / bb_range_upper
        if rsi > overbought_rule.get("RSI_ABOVE", 99):
            penalty_score += weights.get("RSI", 0.4)
        if price_pos_upper > overbought_rule.get("BB_POS_ABOVE", 1.1):
            penalty_score += weights.get("BB_POS", 0.4)

    # Yếu tố xác nhận bổ sung cho điểm phạt
    if confirmation_cfg.get("ENABLED"):
        if candle in confirmation_cfg.get("BEARISH_CANDLES", []):
            penalty_score += weights.get("CANDLE", 0.2)
        is_near_resistance = res_level > 0 and abs(price - res_level) / price < confirmation_cfg.get("RESISTANCE_PROXIMITY_PCT", 0.015)
        if is_near_resistance:
            penalty_score += weights.get("SR_LEVEL", 0.2)

    # --- 3. PHÂN TÍCH NÂNG CAO VỀ HÀNH ĐỘNG GIÁ & VOLUME ---
    pv_config = cfg.get("PRICE_ACTION_VOL_ANALYSIS", {})
    if pv_config.get("ENABLED"):
        pv_rules = pv_config.get("RULES_BY_TIMEFRAME", {}).get(interval)
        if pv_rules:
            atr = indicators.get("atr", 0)
            volume = indicators.get("volume", 0)
            volume_ma = indicators.get("vol_ma20", 0)
            candle_body_size = indicators.get("candle_body_size", 0)

            if atr > 1e-8 and volume_ma > 1:
                # Kịch bản 1: Giảm phạt nếu có breakout mạnh
                if penalty_score > 0 and indicators.get("closed_candle_price", 0) > indicators.get("open", 0):
                    is_strong_momentum_candle = candle_body_size > (atr * pv_rules.get("BREAKOUT_CANDLE_ATR_RATIO", 2.5))
                    is_volume_spike = volume > (volume_ma * pv_rules.get("BREAKOUT_VOLUME_MA_RATIO", 3.0))
                    if is_strong_momentum_candle and is_volume_spike:
                        penalty_score *= pv_rules.get("BREAKOUT_PENALTY_REDUCTION_COEFF", 0.2)

                # Kịch bản 2: Tăng thưởng nếu có tín hiệu kiệt sức
                elif bonus_score > 0 and indicators.get("closed_candle_price", 0) < indicators.get("open", 0):
                    is_strong_exhaust_candle = candle_body_size > (atr * pv_rules.get("EXHAUSTION_CANDLE_ATR_RATIO", 2.0))
                    is_exhaust_volume_spike = volume > (volume_ma * pv_rules.get("EXHAUSTION_VOLUME_MA_RATIO", 3.5))
                    if is_strong_exhaust_candle and is_exhaust_volume_spike:
                        bonus_score *= pv_rules.get("EXHAUSTION_BONUS_MULTIPLIER", 1.5)

    # --- 4. ÁP DỤNG HỆ SỐ THƯỞNG ĐỒNG THUẬN (CONFLUENCE) ---
    # Tăng mạnh bonus/penalty nếu cả 2 tín hiệu chính cùng xuất hiện
    if bonus_score >= (weights.get("RSI", 0.4) + weights.get("BB_POS", 0.4)):
        bonus_score *= confluence_multiplier
    if penalty_score >= (weights.get("RSI", 0.4) + weights.get("BB_POS", 0.4)):
        penalty_score *= confluence_multiplier

    # --- 5. TÍNH TOÁN SỰ THAY ĐỔI HỆ SỐ CƠ BẢN ---
    bonus_impact = base_impact.get("BONUS_PER_POINT", 0.05)
    penalty_impact = base_impact.get("PENALTY_PER_POINT", -0.07)
    coeff_change = (bonus_score * bonus_impact) + (penalty_score * penalty_impact)

    # --- 6. NÂNG CẤP: KHUẾCH ĐẠI TÁC ĐỘNG KHI CÓ BB SQUEEZE ---
    squeeze_cfg = cfg.get("SQUEEZE_ANALYSIS", {})
    if squeeze_cfg.get("ENABLED") and indicators.get("is_bb_squeeze"):
        multiplier = squeeze_cfg.get("IMPACT_MULTIPLIER", 1.0)
        # Khuếch đại cả tác động của bonus (dương) và penalty (âm)
        coeff_change *= multiplier
    # --- KẾT THÚC PHẦN NÂNG CẤP ---

    # --- 7. TÍNH TOÁN HỆ SỐ CUỐI CÙNG VÀ ÁP DỤNG GIỚI HẠN AN TOÀN ---
    calculated_coeff = 1.0 + coeff_change
    min_coeff = cfg.get("MIN_PENALTY_COEFF", 0.90)
    max_coeff = cfg.get("MAX_BONUS_COEFF", 1.15) # Sử dụng trần mới là 1.15

    return max(min_coeff, min(calculated_coeff, max_coeff))

def get_price_action_momentum_coefficient(symbol: str, interval: str) -> float:
    cfg = PRICE_ACTION_MOMENTUM_CONFIG
    if not cfg.get("ENABLED", False):
        return 1.0

    df = price_dataframes.get(symbol, {}).get(interval)
    if df is None or len(df) < 20:
        return 1.0

    rules = cfg.get("RULES_BY_TIMEFRAME", {}).get(interval)
    if not rules:
        return 1.0

    weights = cfg.get("SCORING_WEIGHTS", {})
    lookback = rules.get("LOOKBACK_CANDLES", 10)
    recent = df.tail(lookback)

    momentum_score = 0.0

    green_candles = (recent.tail(5)['close'] > recent.tail(5)['open']).sum()
    if green_candles >= rules.get("MIN_GREEN_STREAK", 3):
        momentum_score += weights.get("CONSECUTIVE_GREENS", 0.3)

    if 'ema_20' in recent.columns:
        above_ma_ratio = (recent['close'] > recent['ema_20']).sum() / len(recent)
        momentum_score += weights.get("PRICE_VS_MA", 0.25) * above_ma_ratio

    if 'volume' in df.columns and len(df) > 20:
        recent_vol = recent.tail(5)['volume'].mean()
        baseline_vol = df.tail(20).head(15)['volume'].mean()
        if baseline_vol > 0 and recent_vol > baseline_vol * rules.get("VOLUME_SURGE_RATIO", 1.5):
            momentum_score += weights.get("VOLUME_SURGE", 0.25)

    lows = recent['low'].values
    higher_lows = sum(lows[i] >= lows[i-1] for i in range(1, len(lows)))
    if higher_lows >= rules.get("MIN_HIGHER_LOWS", 5):
        momentum_score += weights.get("HIGHER_LOWS", 0.2)

    if momentum_score >= 0.7:
        coeff = 1.0 + (momentum_score * 0.12)
    elif momentum_score <= 0.2:
        coeff = 0.97
    else:
        coeff = 1.0

    max_coeff = cfg.get("MAX_BONUS_COEFF", 1.12)
    min_coeff = cfg.get("MIN_PENALTY_COEFF", 0.97)

    return max(min_coeff, min(coeff, max_coeff))

# ==============================================================================
# ==================== ĐỘNG CƠ VỐN NĂNG ĐỘNG (v8.6.1) =======================
# ==============================================================================
def calculate_total_equity(state: Dict, total_usdt_on_binance: float, realtime_prices: Dict[str, Optional[float]]) -> Optional[float]:
    """Tính toán tổng tài sản hiện tại (equity)."""
    value_of_open_positions = 0.0
    for trade in state.get('active_trades', []):
        price = realtime_prices.get(trade['symbol'])
        if price is None:
            log_message(f"⚠️ Không thể tính equity vì thiếu giá của {trade['symbol']}", state)
            return None
        value_of_open_positions += float(trade.get('quantity', 0)) * price
    return total_usdt_on_binance + value_of_open_positions

def manage_dynamic_capital(state: Dict, bnc: BinanceConnector, current_equity: Optional[float]):
    """
    Hàm quản lý vốn thông minh hơn, phân biệt Nạp/Rút và PnL.
    Version: 8.7.0
    """
    now_dt = datetime.now(VIETNAM_TZ)
    _, total_usdt_now = get_usdt_fund(bnc)
    if state.get('initial_capital', 0.0) <= 0:
        if current_equity and current_equity > 0:
            state['initial_capital'] = current_equity
            log_message(f"🌱 Thiết lập Vốn BĐ ban đầu: ${state['initial_capital']:,.2f}", state=state)
            state['last_capital_adjustment_time'] = now_dt.isoformat()
            state['usdt_balance_end_of_last_session'] = total_usdt_now
            state['money_spent_on_trades_last_session'] = 0.0
            state['money_gained_from_trades_last_session'] = 0.0
        return
    usdt_balance_prev_session = state.get("usdt_balance_end_of_last_session", 0.0)
    money_spent_prev_session = state.get("money_spent_on_trades_last_session", 0.0)
    money_gained_prev_session = state.get("money_gained_from_trades_last_session", 0.0)
    if usdt_balance_prev_session > 0:
        expected_usdt = usdt_balance_prev_session - money_spent_prev_session + money_gained_prev_session
        net_deposit = total_usdt_now - expected_usdt
        threshold = max(GENERAL_CONFIG["DEPOSIT_DETECTION_MIN_USD"], state.get("initial_capital", 1) * GENERAL_CONFIG["DEPOSIT_DETECTION_THRESHOLD_PCT"])
        if abs(net_deposit) > threshold:
            log_message(f"💵 Phát hiện Nạp/Rút ròng (dựa trên USDT): ${net_deposit:,.2f}", state=state)
            state["initial_capital"] = state.get("initial_capital", 0.0) + net_deposit
            state['last_capital_adjustment_time'] = now_dt.isoformat()
            log_message(f"   Vốn BĐ được cập nhật: ${state['initial_capital']:,.2f}", state=state)
    last_adj_str = state.get('last_capital_adjustment_time')
    cooldown_hours = GENERAL_CONFIG.get("CAPITAL_ADJUSTMENT_COOLDOWN_HOURS", 72)
    if not (last_adj_str and (now_dt - datetime.fromisoformat(last_adj_str)).total_seconds() / 3600 < cooldown_hours):
        if current_equity is not None:
            initial_capital = state.get("initial_capital", 0.0)
            if initial_capital > 0:
                growth_pct = (current_equity / initial_capital - 1) * 100
                compound_threshold = GENERAL_CONFIG.get("AUTO_COMPOUND_THRESHOLD_PCT", 10.0)
                deleverage_threshold = GENERAL_CONFIG.get("AUTO_DELEVERAGE_THRESHOLD_PCT", -10.0)
                if growth_pct >= compound_threshold or growth_pct <= deleverage_threshold:
                    log_message(f"💰 Hiệu suất đạt ngưỡng ({growth_pct:+.2f}%). Cập nhật Vốn BĐ bằng Tổng TS hiện tại.", state=state)
                    log_message(f"   Vốn BĐ cũ: ${initial_capital:,.2f}", state=state)
                    state["initial_capital"] = current_equity
                    state['last_capital_adjustment_time'] = now_dt.isoformat()
                    log_message(f"   Vốn BĐ MỚI: ${state['initial_capital']:,.2f}", state=state)
    state['usdt_balance_end_of_last_session'] = total_usdt_now
    state['money_spent_on_trades_last_session'] = 0.0
    state['money_gained_from_trades_last_session'] = 0.0

# ==============================================================================
# ==================== BÁO CÁO & HÀM TIỆN ÍCH KHÁC =======================
# ==============================================================================
def build_report_header(state: Dict, equity: float, total_usdt: float, available_usdt: float) -> str:
    initial_capital = state.get('initial_capital', total_usdt)
    if initial_capital <= 0: initial_capital = total_usdt
    pnl_since_start = equity - initial_capital
    pnl_percent = (pnl_since_start / initial_capital) * 100 if initial_capital > 0 else 0
    pnl_icon = "🟢" if pnl_since_start >= 0 else "🔴"
    return (f"💰 Vốn BĐ: **${initial_capital:,.2f}** | 💵 Tiền mặt (USDT): **${available_usdt:,.2f}**\n"
            f"📊 Tổng TS: **${equity:,.2f}** | 📈 PnL Tổng: {pnl_icon} **${pnl_since_start:,.2f} ({pnl_percent:+.2f}%)**")

def build_pnl_summary_line(state: Dict, realtime_prices: Dict[str, float]) -> str:
    stats = state.get('trade_stats', {})

    total_trades = stats.get('total_trades_closed', 0)
    num_wins = stats.get('winning_trades', 0)
    num_losses = total_trades - num_wins

    win_rate_str = f"{num_wins / total_trades * 100:.2f}% ({num_wins}/{total_trades})" if total_trades > 0 else "N/A"
    total_pnl_closed = stats.get('total_pnl_usd', 0.0)
    avg_win_str = f"${stats.get('total_win_pnl_usd', 0.0) / num_wins:,.2f}" if num_wins > 0 else "$0.00"
    avg_loss_str = f"${stats.get('total_loss_pnl_usd', 0.0) / num_losses:,.2f}" if num_losses > 0 else "$0.00"

    # [v9.2] Lấy PnL đã thực hiện từ các lệnh đang mở (chưa được ghi vào stats tổng)
    active_tp1_pnl, active_pp_pnl = 0.0, 0.0
    for t in state.get('active_trades', []):
        if 'partial_pnl_details' in t and isinstance(t.get('partial_pnl_details'), dict):
            details = t['partial_pnl_details']
            active_tp1_pnl += details.get('TP1', 0.0)
            active_pp_pnl += details.get('PP', 0.0)

    # [v9.2] Cộng dồn PnL từ lịch sử (stats) và PnL từ lệnh đang mở để có báo cáo chính xác nhất
    total_tp1_pnl = stats.get('total_tp1_pnl', 0.0) + active_tp1_pnl
    total_pp_pnl = stats.get('total_pp_pnl', 0.0) + active_pp_pnl

    unrealized_pnl = sum(get_current_pnl(trade, realtime_price=realtime_prices.get(trade['symbol']))[0] for trade in state.get('active_trades', []))

    pnl_line_1 = f"🏆 Win Rate: **{win_rate_str}** | ✅ PnL Đóng: **${total_pnl_closed:,.2f}** | 📈 PnL Mở: **{'+' if unrealized_pnl >= 0 else ''}${unrealized_pnl:,.2f}**"
    pnl_line_2 = f"🎯 AVG Lãi: **{avg_win_str}** | 🛡️ AVG Lỗ: **{avg_loss_str}** | 💎 PnL TP1: **${total_tp1_pnl:,.2f}** | 🛡️ PnL PP: **${total_pp_pnl:,.2f}**"

    return f"{pnl_line_1}\n{pnl_line_2}"

def build_trade_details_for_report(trade: Dict, realtime_price: float) -> str:
    pnl_usd, pnl_pct = get_current_pnl(trade, realtime_price=realtime_price)
    icon = "🟢" if pnl_usd >= 0 else "🔴"
    holding_h = (datetime.now(VIETNAM_TZ) - datetime.fromisoformat(trade['entry_time'])).total_seconds() / 3600
    dca_info = f" (DCA:{len(trade.get('dca_entries',[]))})" if trade.get('dca_entries') else ""
    sl_price = trade['sl']
    tsl_info = f" TSL:{format_price_dynamically(sl_price)}" if "Trailing_SL_Active" in trade.get('tactic_used', []) else ""
    tp1_info = " TP1✅" if trade.get('tp1_hit', False) or trade.get('profit_taken', False) else ""
    entry_score, last_score = trade.get('entry_score', 0.0), trade.get('last_score', 0.0)
    score_display = f"{entry_score:,.1f}→{last_score:,.1f}" + ("📉" if last_score < entry_score else "📈" if last_score > entry_score else "")
    entry_zone = trade.get('entry_zone', 'N/A')
    last_zone = trade.get('last_zone')
    zone_display = f"{entry_zone}→{last_zone}" if last_zone and last_zone != entry_zone else entry_zone
    tactic_info = f"({trade.get('opened_by_tactic')} | {score_display} | {zone_display})"
    
    # [v9.2] Hiển thị vốn ban đầu
    invested_usd = trade.get('initial_entry', {}).get('invested_usd', trade.get('total_invested_usd', 0))
    # Giá trị hiện tại vẫn tính trên vốn còn lại
    current_value = trade.get('total_invested_usd', 0.0) + pnl_usd
    
    line1 = f"  {icon} **{trade['symbol']}-{trade['interval']}** {tactic_info} PnL: **${pnl_usd:,.2f} ({pnl_pct:+.2f}%)** | Giữ:{holding_h:.1f}h{dca_info}{tp1_info}"
    line2 = f"   Vốn:${invested_usd:,.2f} -> **${current_value:,.2f}** | Entry:{format_price_dynamically(trade['entry_price'])} Cur:{format_price_dynamically(realtime_price)} TP:{format_price_dynamically(trade['tp'])} SL:{format_price_dynamically(sl_price)}{tsl_info}"
    return f"{line1}\n{line2}"

def format_closed_trade_line(trade_data: pd.Series) -> str:
    try:
        symbol_with_interval = f"{trade_data.get('symbol', 'N/A')}-{trade_data.get('interval', 'N/A')}"
        pnl_usd = trade_data.get('pnl_usd', 0)
        pnl_percent = trade_data.get('pnl_percent', 0)
        pnl_icon = "✅" if pnl_usd >= 0 else "❌"
        entry_price_str = format_price_dynamically(trade_data.get('entry_price'))
        exit_price_str = format_price_dynamically(trade_data.get('exit_price'))
        entry_time = pd.to_datetime(trade_data['entry_time']).tz_convert(VIETNAM_TZ)
        exit_time = pd.to_datetime(trade_data['exit_time']).tz_convert(VIETNAM_TZ)
        hold_duration_h = (exit_time - entry_time).total_seconds() / 3600
        entry_zone = trade_data.get('entry_zone', 'N/A')
        last_zone = trade_data.get('last_zone', 'N/A')
        zone_display = f"Zone: {entry_zone} -> {last_zone}"
        entry_score = trade_data.get('entry_score', 0.0)
        last_score = trade_data.get('last_score', 0.0)
        score_icon = "📉" if last_score < entry_score else ("📈" if last_score > entry_score else "")
        score_display = f"Score: {entry_score:.1f} -> {last_score:.1f}{score_icon}"
        main_tactic = trade_data.get('opened_by_tactic', 'N/A')
        reason_closed = trade_data.get('status', 'Closed').split('(')[-1].replace(')', '').strip()
        tactic_display = f"{main_tactic} -> {reason_closed}"
        line1 = f"  • {pnl_icon} **{symbol_with_interval}** | PnL: **${pnl_usd:,.2f} ({pnl_percent:+.2f}%)**"
        line2 = f"   `Entry: {entry_price_str} -> Exit: {exit_price_str} | Hold: {hold_duration_h:.1f}h`"
        line3 = f"   `{zone_display} | {score_display} | {tactic_display}`"
        return f"{line1}\n{line2}\n{line3}"
    except Exception as e:
        return f"  • {trade_data.get('symbol', 'N/A')} - Lỗi báo cáo lịch sử: {e}"

def build_dynamic_alert_text(state: Dict, total_usdt: float, available_usdt: float, realtime_prices: Dict[str, float], equity: float) -> str:
    now_vn_str = datetime.now(VIETNAM_TZ).strftime('%H:%M %d-%m-%Y')
    header = build_report_header(state, equity, total_usdt, available_usdt)
    pnl_summary = build_pnl_summary_line(state, realtime_prices)
    lines = [
        f"💡 **CẬP NHẬT ĐỘNG (LIVE)** - `{now_vn_str}`",
        header, "\n" + pnl_summary,
        f"\n--- **Vị thế đang mở ({len(state.get('active_trades', []))})** ---"
    ]
    if not state.get('active_trades'):
        lines.append("  (Không có vị thế nào)")
    else:
        for trade in sorted(state.get('active_trades', []), key=lambda x: x.get('entry_time', '')):
            current_price = realtime_prices.get(trade.get("symbol"))
            if current_price is None: continue
            lines.append(build_trade_details_for_report(trade, current_price))
    lines.append("\n====================================")
    return "\n".join(lines)

def build_daily_summary_text(state: dict, total_usdt: float, available_usdt: float, prices: dict, equity: float) -> str:
    def _format_price_internal(price, no_symbol=False):
        if price is None or pd.isna(price): return "N/A"
        prefix = "" if no_symbol else "$"
        try:
            price_f = float(price)
            if price_f >= 1.0: return f"{prefix}{price_f:,.4f}"
            return f"{prefix}{price_f:,.8f}"
        except (ValueError, TypeError): return "N/A"

    def _get_initial_capital_from_history(trade_dict):
        try:
            initial_entry_data = trade_dict.get('initial_entry')
            if isinstance(initial_entry_data, str) and initial_entry_data.strip():
                initial_entry_data = json.loads(initial_entry_data.replace("'", "\""))
            if isinstance(initial_entry_data, dict):
                return float(initial_entry_data.get('invested_usd', 0))
            return float(trade_dict.get('total_invested_usd', 0))
        except (json.JSONDecodeError, TypeError, KeyError, ValueError):
            return float(trade_dict.get('total_invested_usd', 0))

    initial_capital = state.get('initial_capital', 1.0)
    if initial_capital <= 0: initial_capital = 1.0
    pnl_total_usd = equity - initial_capital
    pnl_total_percent = (pnl_total_usd / initial_capital) * 100
    pnl_emote_total = '🟢' if pnl_total_usd >= 0 else '🔴'

    pnl_summary_lines = build_pnl_summary_line(state, prices)

    report = [
        f"📊 **BÁO CÁO TỔNG KẾT HÀNG NGÀY ({TRADING_MODE.upper()})** - `{datetime.now(VIETNAM_TZ).strftime('%H:%M %d-%m-%Y')}` 📊",
        f"💰 Vốn BĐ: **${initial_capital:,.2f}** | 💵 Tiền mặt (USDT): **${available_usdt:,.2f}**",
        f"📊 Tổng TS: **${equity:,.2f}** | 📈 PnL Tổng: {pnl_emote_total} **${pnl_total_usd:+.2f} ({pnl_total_percent:+.2f}%)**",
        "",
        pnl_summary_lines,
        "\n--- **Chi tiết trong phiên** ---"
    ]
    newly_opened = state.get('temp_newly_opened_trades', []); report.append(f"✨ Lệnh mới mở: {len(newly_opened)}")
    for msg in newly_opened: report.append(f"  {msg}")
    newly_closed = state.get('temp_newly_closed_trades', []); report.append(f"🎬 Lệnh đã đóng/chốt lời: {len(newly_closed)}")
    for msg in newly_closed: report.append(f"  {msg}")

    active_trades = state.get('active_trades', [])
    if active_trades:
        report.append("\n--- **Vị thế đang mở** ---")
        for trade in sorted(active_trades, key=lambda x: x.get('entry_time', '')):
            symbol = trade.get('symbol', 'N/A')
            current_price = prices.get(symbol)
            if current_price is None: continue

            pnl_usd, pnl_percent = get_current_pnl(trade, current_price)
            # [v9.2] Hiển thị vốn ban đầu
            invested_usd = trade.get('initial_entry', {}).get('invested_usd', trade.get('total_invested_usd', 0))
            pnl_emote_trade = "🟢" if pnl_usd >= 0 else "🔴"
            # [v9.2] Giá trị hiện tại vẫn tính trên vốn còn lại
            current_value = trade.get('total_invested_usd', 0.0) + pnl_usd

            try:
                entry_time = datetime.fromisoformat(trade.get('entry_time'))
                entry_time_str = entry_time.astimezone(VIETNAM_TZ).strftime('%d-%m %H:%M')
                holding_hours = (datetime.now(VIETNAM_TZ) - entry_time).total_seconds() / 3600
            except:
                entry_time_str = "N/A"; holding_hours = 0.0

            entry_score, last_score = trade.get('entry_score', 0.0), trade.get('last_score', 0.0)
            score_change_icon = "📉" if last_score < entry_score else ("📈" if last_score > entry_score else "")
            score_display = f"{entry_score:.1f}→{last_score:.1f}{score_change_icon}"

            entry_zone, last_zone = trade.get('entry_zone', 'N/A'), trade.get('last_zone', 'N/A')
            zone_display = f"{entry_zone}→{last_zone}" if last_zone != entry_zone else entry_zone
            tactic_info = f"({trade.get('opened_by_tactic', 'N/A')} | {score_display} | {zone_display})"

            status_tags = []
            if trade.get('tp1_hit', False): status_tags.append("TP1✅")
            if trade.get('profit_taken', False): status_tags.append("PP✅")
            status_display = " " + " ".join(status_tags) if status_tags else ""
            
            dca_info = f"(DCA:{len(trade.get('dca_entries',[]))})" if trade.get('dca_entries') else ""

            line1 = f"  {pnl_emote_trade} **{symbol}-{trade.get('interval', 'N/A')}** {tactic_info} PnL: **${pnl_usd:+.2f} ({pnl_percent:+.2f}%)**{status_display}"
            line2 = f"   Vốn:**${invested_usd:,.2f}** -> **${current_value:,.2f}** | Mở: `{entry_time_str}` | Giữ: `{holding_hours:.1f}h` {dca_info}"
            line3 = f"   Entry:{_format_price_internal(trade.get('entry_price'))} Cur:{_format_price_internal(current_price)} TP:{_format_price_internal(trade.get('tp'))} SL:{_format_price_internal(trade.get('sl'))}"
            report.extend([line1, line2, line3])

    trade_history = state.get('trade_history', [])
    closed_trades_in_history = [t for t in trade_history if t.get('status') and 'Closed' in t['status'] and 'Desynced' not in t['status']]
    if closed_trades_in_history:
        report.append("\n--- **Lịch sử giao dịch gần nhất** ---")
        all_sorted_by_time = sorted(closed_trades_in_history, key=lambda t: t.get('exit_time', '1970-01-01T00:00:00+00:00'), reverse=True)
        recent_wins = [t for t in all_sorted_by_time if float(t.get('pnl_usd', 0)) > 0][:5]
        recent_losses = [t for t in all_sorted_by_time if float(t.get('pnl_usd', 0)) <= 0][:5]

        def build_history_line(trade):
            tactic_used = trade.get('tactic_used', [])
            if isinstance(tactic_used, str) and tactic_used.strip():
                try: tactic_used = json.loads(tactic_used.replace("'", "\""))
                except: tactic_used = []
            status_tags = []
            if any("TP1" in s for s in tactic_used if isinstance(s, str)): status_tags.append("TP1✅")
            if any("Protect_Profit" in s for s in tactic_used if isinstance(s, str)): status_tags.append("PP✅")
            return " " + " ".join(status_tags) if status_tags else ""

        def get_hold_duration(trade):
            try:
                entry_dt = datetime.fromisoformat(trade.get('entry_time'))
                exit_dt = datetime.fromisoformat(trade.get('exit_time'))
                return (exit_dt - entry_dt).total_seconds() / 3600
            except (TypeError, ValueError):
                return float(trade.get('holding_duration_hours', 0.0))

        if recent_wins:
            report.append("\n**✅ 5 lệnh LÃI gần nhất**")
            for trade in recent_wins:
                capital = _get_initial_capital_from_history(trade)
                pnl_usd, pnl_percent = float(trade.get('pnl_usd', 0)), float(trade.get('pnl_percent', 0))
                status_display = build_history_line(trade)
                hold_display_h = get_hold_duration(trade)
                entry_score, last_score = trade.get('entry_score', 0.0), trade.get('last_score', 0.0)
                entry_zone, last_zone = trade.get('entry_zone', 'N/A'), trade.get('last_zone', 'N/A')
                zone_display = f"{entry_zone}→{last_zone}" if last_zone != entry_zone else entry_zone
                score_change_icon = "📉" if last_score < entry_score else ("📈" if last_score > entry_score else "")
                score_display = f"{entry_score:.1f}→{last_score:.1f}{score_change_icon}"
                try:
                    exit_dt = datetime.fromisoformat(trade.get('exit_time'))
                    time_str = exit_dt.astimezone(VIETNAM_TZ).strftime('%d-%m %H:%M')
                except:
                    time_str = "N/A"
                report.append(f"  • ✅ **{trade.get('symbol', 'N/A')}-{trade.get('interval', 'N/A')}** | Đóng: `{time_str}` | PnL: **${pnl_usd:+.2f} ({pnl_percent:+.2f}%)**{status_display}")
                report.append(f"   `Vốn: {_format_price_internal(capital)} | Entry: {_format_price_internal(trade.get('entry_price'), no_symbol=True)} -> Exit: {_format_price_internal(trade.get('exit_price'), no_symbol=True)} | Hold: {hold_display_h:.1f}h`")
                report.append(f"   `Zone: {zone_display} | Score: {score_display}`")

        if recent_losses:
            report.append("\n**❌ 5 lệnh LỖ gần nhất**")
            for trade in recent_losses:
                capital = _get_initial_capital_from_history(trade)
                pnl_usd, pnl_percent = float(trade.get('pnl_usd', 0)), float(trade.get('pnl_percent', 0))
                status_display = build_history_line(trade)
                hold_display_h = get_hold_duration(trade)
                entry_score, last_score = trade.get('entry_score', 0.0), trade.get('last_score', 0.0)
                entry_zone, last_zone = trade.get('entry_zone', 'N/A'), trade.get('last_zone', 'N/A')
                zone_display = f"{entry_zone}→{last_zone}" if last_zone != entry_zone else entry_zone
                score_change_icon = "📉" if last_score < entry_score else ("📈" if last_score > entry_score else "")
                score_display = f"{entry_score:.1f}→{last_score:.1f}{score_change_icon}"
                try:
                    exit_dt = datetime.fromisoformat(trade.get('exit_time'))
                    time_str = exit_dt.astimezone(VIETNAM_TZ).strftime('%d-%m %H:%M')
                except:
                    time_str = "N/A"
                report.append(f"  • ❌ **{trade.get('symbol', 'N/A')}-{trade.get('interval', 'N/A')}** | Đóng: `{time_str}` | PnL: **${pnl_usd:+.2f} ({pnl_percent:+.2f}%)**{status_display}")
                report.append(f"   `Vốn: {_format_price_internal(capital)} | Entry: {_format_price_internal(trade.get('entry_price'), no_symbol=True)} -> Exit: {_format_price_internal(trade.get('exit_price'), no_symbol=True)} | Hold: {hold_display_h:.1f}h`")
                report.append(f"   `Zone: {zone_display} | Score: {score_display}`")

    return '\n'.join(report)




def should_send_report(state: Dict, equity: Optional[float]) -> Optional[str]:
    if equity is None: return None
    now_vn = datetime.now(VIETNAM_TZ)
    last_summary_dt = None
    if state.get('last_summary_sent_time'):
        last_summary_dt = datetime.fromisoformat(state.get('last_summary_sent_time')).astimezone(VIETNAM_TZ)
    for time_str in GENERAL_CONFIG.get("DAILY_SUMMARY_TIMES", []):
        hour, minute = map(int, time_str.split(':'))
        scheduled_dt_today = now_vn.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if now_vn >= scheduled_dt_today and (last_summary_dt is None or last_summary_dt < scheduled_dt_today):
            return "daily"
    if not DYNAMIC_ALERT_CONFIG.get("ENABLED", False): return None
    last_alert = state.get('last_dynamic_alert', {})
    if not last_alert.get('timestamp'):
        if state.get('active_trades'): return "dynamic"
        return None
    last_alert_dt = datetime.fromisoformat(last_alert.get("timestamp")).astimezone(VIETNAM_TZ)
    hours_since = (now_vn - last_alert_dt).total_seconds() / 3600
    if hours_since >= DYNAMIC_ALERT_CONFIG["FORCE_UPDATE_HOURS"]: return "dynamic"
    if hours_since < DYNAMIC_ALERT_CONFIG["COOLDOWN_HOURS"]: return None
    initial_capital = state.get('initial_capital', 1)
    if initial_capital <= 0: return None
    current_pnl_pct = ((equity - initial_capital) / initial_capital) * 100
    if abs(current_pnl_pct - last_alert.get('total_pnl_percent', 0.0)) >= DYNAMIC_ALERT_CONFIG["PNL_CHANGE_THRESHOLD_PCT"]:
        return "dynamic"
    return None

def run_heavy_tasks(bnc: BinanceConnector, state: Dict, available_usdt: float, total_usdt: float):
    symbols_to_load = list(set(SYMBOLS_TO_SCAN + [t['symbol'] for t in state.get('active_trades', [])] + ["BTCUSDT"]))
    for symbol in symbols_to_load:
        indicator_results[symbol], price_dataframes[symbol] = {}, {}
        for interval in ALL_TIME_FRAMES:
            df = get_price_data_with_cache(symbol, interval, GENERAL_CONFIG["DATA_FETCH_LIMIT"])
            if df is not None and not df.empty:
                if 'ema_20' not in df.columns or 'ema_50' not in df.columns:
                    df['ema_20'] = ta.trend.ema_indicator(df["close"], window=20)
                    df['ema_50'] = ta.trend.ema_indicator(df["close"], window=50)
                if 'bb_width' not in df.columns:
                    df['bb_width'] = ta.volatility.BollingerBands(df["close"], window=20, window_dev=2).bollinger_wband()
                indicator_results[symbol][interval] = calculate_indicators(df.copy(), symbol, interval)
                price_dataframes[symbol][interval] = df
    for trade in state.get("active_trades", []):
        indicators = indicator_results.get(trade['symbol'], {}).get(trade['interval'])
        if indicators:
            tactic_cfg = TACTICS_LAB.get(trade.get('opened_by_tactic'), {})
            decision = get_advisor_decision(trade['symbol'], trade['interval'], indicators, ADVISOR_BASE_CONFIG, weights_override=tactic_cfg.get("WEIGHTS"))
            raw_score = decision.get("final_score", 0.0)
            mtf_coeff = get_mtf_adjustment_coefficient(trade['symbol'], trade['interval'])

            ez_coeff = 1.0
            if tactic_cfg.get("USE_EXTREME_ZONE_FILTER", False):
                ez_coeff = get_extreme_zone_adjustment_coefficient(indicators, trade['interval'])

            pam_coeff = 1.0
            if tactic_cfg.get("USE_PRICE_ACTION_MOMENTUM", False):
                pam_coeff = get_price_action_momentum_coefficient(trade['symbol'], trade['interval'])

            contextual_score = raw_score * mtf_coeff * ez_coeff * pam_coeff

            if trade.get('last_score') is not None and contextual_score != trade.get('last_score'):
                log_message(f"  (i) Cập nhật điểm {trade['symbol']}-{trade['interval']}: {trade.get('last_score', 0.0):.2f} -> {contextual_score:.2f} (Gốc: {raw_score:.2f}, MTF: x{mtf_coeff:.2f}, EZ: x{ez_coeff:.2f}, PAM: x{pam_coeff:.2f})", state)
            trade['last_score'] = contextual_score
            trade['last_zone'] = determine_market_zone_with_scoring(trade['symbol'], trade['interval'])
    find_and_open_new_trades(bnc, state, available_usdt, total_usdt)


def reconcile_positions_with_binance(bnc: BinanceConnector, state: Dict):
    try:
        balances = bnc.get_account_balance().get("balances", [])
        asset_balances = {item['asset']: float(item['free']) + float(item['locked']) for item in balances}
    except Exception as e:
        log_error("Không thể lấy số dư tài khoản để đối soát.", error_details=str(e), state=state)
        return
    active_trades = state.get("active_trades", [])
    trades_to_remove = []
    threshold = GENERAL_CONFIG.get("RECONCILIATION_QTY_THRESHOLD", 0.95)
    for trade in active_trades:
        symbol_asset = trade['symbol'].replace("USDT", "")
        bot_quantity = float(trade.get('quantity', 0))
        real_quantity = asset_balances.get(symbol_asset, 0.0)
        if real_quantity < bot_quantity * threshold:
            trades_to_remove.append(trade)
            log_message(f"⚠️ Đối soát: Lệnh {trade['symbol']} đã bị đóng/thay đổi thủ công. "
                        f"(Bot: {bot_quantity:.6f}, Sàn: {real_quantity:.6f}). Đang xóa.", state=state)
    if trades_to_remove:
        log_message(f"---[⚙️ Bắt đầu dọn dẹp {len(trades_to_remove)} lệnh bất đồng bộ ⚙️]---", state=state)
        trade_ids_to_remove = {t['trade_id'] for t in trades_to_remove}
        for trade in trades_to_remove:
            trade['status'] = 'Closed (Desynced)'
            trade['exit_time'] = datetime.now(VIETNAM_TZ).isoformat()
            trade['pnl_usd'] = 0
            trade['pnl_percent'] = 0
            state.setdefault('trade_history', []).append(trade)
        state['active_trades'] = [t for t in state['active_trades'] if t['trade_id'] not in trade_ids_to_remove]
        log_message(f"---[✅ Đã dọn dẹp xong]---", state=state)
    symbols_in_state = {t['symbol'] for t in state.get("active_trades", [])}
    min_orphan_value = GENERAL_CONFIG.get("ORPHAN_ASSET_MIN_VALUE_USDT", 10.0)
    now = datetime.now(VIETNAM_TZ)
    state.setdefault('orphan_asset_alerts', {})
    for asset_code, quantity in asset_balances.items():
        if asset_code in ["USDT", "BNB"] or quantity <= 0: continue
        symbol_usdt = f"{asset_code}USDT"
        if symbol_usdt in SYMBOLS_TO_SCAN and symbol_usdt not in symbols_in_state:
            price = get_realtime_price(symbol_usdt)
            if price:
                asset_value_usdt = quantity * price
                if asset_value_usdt > min_orphan_value:
                    last_alert_time_str = state['orphan_asset_alerts'].get(asset_code)
                    should_alert = True
                    if last_alert_time_str:
                        last_alert_time = datetime.fromisoformat(last_alert_time_str)
                        if (now - last_alert_time).total_seconds() < 6 * 3600:
                            should_alert = False
                    if should_alert:
                        msg = (f"⚠️ PHÁT HIỆN TÀI SẢN MỒ CÔI: **{quantity:.6f} {asset_code}** (trị giá ~${asset_value_usdt:,.2f}). "
                               f"Vui lòng dùng Control Panel (Chức năng 8) để bán hoặc xử lý thủ công.")
                        log_error(msg, send_to_discord=True, force_discord=True, state=state)
                        state['orphan_asset_alerts'][asset_code] = now.isoformat()

# ==============================================================================
# ==================== VÒNG LẶP CHÍNH =================================
# ==============================================================================
def run_session():
    if not acquire_lock():
        return
    state = {}
    try:
        with BinanceConnector(network=TRADING_MODE) as bnc:
            if not bnc.test_connection():
                log_error("Không thể kết nối đến Binance API.", send_to_discord=True)
                return
            state = load_json_file(STATE_FILE, {
                "active_trades": [], "trade_history": [], "initial_capital": 0.0,
                "money_spent_on_trades_last_session": 0.0, "pnl_closed_last_session": 0.0
            })

            # --- [BẮT ĐẦU] TỰ ĐỘNG KHỞI TẠO THỐNG KÊ (NẾU CẦN) (v9.2) ---
            if 'trade_stats' not in state:
                log_message("⚠️ Không tìm thấy 'trade_stats'. Đang khởi tạo từ file CSV...", state=state)
                try:
                    if os.path.exists(TRADE_HISTORY_CSV_FILE) and os.path.getsize(TRADE_HISTORY_CSV_FILE) > 0:
                        df = pd.read_csv(TRADE_HISTORY_CSV_FILE)
                        df_closed = df[df['status'].str.contains('Closed', na=False) & pd.to_numeric(df['pnl_usd'], errors='coerce').notna()].copy()
                        df_closed['pnl_usd'] = pd.to_numeric(df_closed['pnl_usd'])

                        # Logic tính PnL từ chốt lời một phần
                        total_tp1_pnl_init = 0.0
                        total_pp_pnl_init = 0.0
                        if 'partial_pnl_details' in df_closed.columns:
                            for details_str in df_closed['partial_pnl_details'].dropna():
                                try:
                                    details = json.loads(details_str)
                                    if isinstance(details, dict):
                                        total_tp1_pnl_init += details.get('TP1', 0.0)
                                        total_pp_pnl_init += details.get('PP', 0.0)
                                except (json.JSONDecodeError, TypeError):
                                    continue # Bỏ qua nếu dữ liệu JSON không hợp lệ

                        wins_df = df_closed[df_closed['pnl_usd'] > 0]
                        losses_df = df_closed[df_closed['pnl_usd'] <= 0]

                        state['trade_stats'] = {
                            "total_trades_closed": len(df_closed),
                            "winning_trades": len(wins_df),
                            "total_pnl_usd": df_closed['pnl_usd'].sum(),
                            "total_win_pnl_usd": wins_df['pnl_usd'].sum(),
                            "total_loss_pnl_usd": losses_df['pnl_usd'].sum(),
                            "total_tp1_pnl": total_tp1_pnl_init,
                            "total_pp_pnl": total_pp_pnl_init
                        }
                        log_message(f"✅ Đã khởi tạo thành công 'trade_stats' với {len(df_closed)} lệnh.", state=state)
                    else:
                        raise FileNotFoundError("File CSV không tồn tại hoặc trống.")
                except Exception as e:
                    log_error(f"Lỗi khi khởi tạo 'trade_stats' từ CSV: {e}. Sẽ bắt đầu với số liệu bằng 0.", state=state)
                    state['trade_stats'] = {
                        "total_trades_closed": 0, "winning_trades": 0, "total_pnl_usd": 0.0,
                        "total_win_pnl_usd": 0.0, "total_loss_pnl_usd": 0.0
                    }
            # --- [KẾT THÚC] TỰ ĐỘNG KHỞI TẠO THỐNG KÊ ---

            state['temp_newly_opened_trades'], state['temp_newly_closed_trades'] = [], []
            state['temp_money_spent_on_trades'], state['temp_pnl_from_closed_trades'] = 0.0, 0.0
            state['session_has_events'] = False
            state.setdefault('money_spent_on_trades_last_session', 0.0)
            state.setdefault('money_gained_from_trades_last_session', 0.0)
            state.setdefault('temp_pnl_from_closed_trades', 0.0)
            reconcile_positions_with_binance(bnc, state)
            available_usdt, total_usdt_at_start = get_usdt_fund(bnc)
            if total_usdt_at_start == 0.0 and not state.get("active_trades"):
                return
            active_symbols_for_equity = list(set([t['symbol'] for t in state.get('active_trades', [])]))
            realtime_prices_at_start = {sym: get_realtime_price(sym) for sym in active_symbols_for_equity if sym}
            current_equity = calculate_total_equity(state, total_usdt_at_start, realtime_prices_at_start)
            if current_equity is None:
                log_message("⚠️ Không thể tính Equity do lỗi API giá. Tạm dừng phiên để đảm bảo an toàn.", state=state)
                save_json_file(STATE_FILE, state)
                return
            manage_dynamic_capital(state, bnc, current_equity)
            now_vn = datetime.now(VIETNAM_TZ)
            last_refresh_str = state.get("last_indicator_refresh")
            current_minute = now_vn.minute
            safe_refresh_minutes = GENERAL_CONFIG["HEAVY_REFRESH_MINUTES"] - 1
            is_heavy_task_time = (current_minute in [5, 20, 35, 50]) and \
                     (not last_refresh_str or \
                     (now_vn - datetime.fromisoformat(last_refresh_str)).total_seconds() / 60 >= safe_refresh_minutes)
            if is_heavy_task_time:
                if not state.get('pending_trade_opportunity'):
                    run_heavy_tasks(bnc, state, available_usdt, total_usdt_at_start)
                    state["last_indicator_refresh"] = now_vn.isoformat()
                else:
                    log_message("⏳ Tạm hoãn tác vụ nặng do có lệnh đang chờ thực thi.", state=state)
            if state.get('pending_trade_opportunity'):
                execute_trade_opportunity(bnc, state, available_usdt, total_usdt_at_start)
            active_symbols = list(set([t['symbol'] for t in state.get('active_trades', [])]))
            if active_symbols:
                current_prices_for_mgmt = {s: realtime_prices_at_start.get(s) or get_realtime_price(s) for s in active_symbols if s}
                if all(price is not None for price in current_prices_for_mgmt.values()):
                    check_and_manage_open_positions(bnc, state, current_prices_for_mgmt)
                    handle_stale_trades(bnc, state, current_prices_for_mgmt)
                    handle_dca_opportunities(bnc, state, available_usdt, total_usdt_at_start, current_prices_for_mgmt)
                else:
                    missing_symbols = [s for s, p in current_prices_for_mgmt.items() if p is None]
                    log_message(f"⚠️ Tạm dừng quản lý vị thế do không lấy được giá cho: {', '.join(missing_symbols)}", state=state)
            if state.get('temp_newly_opened_trades') or state.get('temp_newly_closed_trades'):
                log_message(f"--- Cập nhật các sự kiện trong phiên ---", state=state)
                for msg in state.get('temp_newly_opened_trades', []): log_message(f"  {msg}", state=state)
                for msg in state.get('temp_newly_closed_trades', []): log_message(f"  {msg}", state=state)
            final_available_usdt, final_total_usdt = get_usdt_fund(bnc)
            final_realtime_prices = {t['symbol']: get_realtime_price(t['symbol']) for t in state.get('active_trades', []) if t.get('symbol')}
            final_equity = calculate_total_equity(state, final_total_usdt, final_realtime_prices)
            report_type_to_send = should_send_report(state, final_equity)
            if report_type_to_send:
                log_message(f"🔔 Gửi báo cáo loại: {report_type_to_send.upper()}", state=state)
                if report_type_to_send == "daily":
                    report_content = build_daily_summary_text(state, final_total_usdt, final_available_usdt, final_realtime_prices, final_equity)
                    state['last_summary_sent_time'] = now_vn.isoformat()
                else:
                    report_content = build_dynamic_alert_text(state, final_total_usdt, final_available_usdt, final_realtime_prices, final_equity)
                send_discord_message_chunks(report_content, force=True)
                pnl_percent_for_alert = ((final_equity - state.get('initial_capital', 1)) / state.get('initial_capital', 1)) * 100 if state.get('initial_capital', 1) > 0 else 0
                state['last_dynamic_alert'] = {"timestamp": now_vn.isoformat(), "total_pnl_percent": pnl_percent_for_alert}
            if 'last_critical_error' in state: state.pop('last_critical_error', None)
            state.pop('pnl_closed_last_session', None)
            state.pop('pnl_open_change_last_session', None)
            state.pop('equity_end_of_last_session', None)
            save_json_file(STATE_FILE, state)
    except Exception as e:
        error_msg = str(e)
        error_signature = error_msg.split(' for url:')[0] if ' for url:' in error_msg else error_msg[:100]
        last_error = state.get('last_critical_error', {})
        now_ts = time.time()
        cooldown_seconds = GENERAL_CONFIG.get("CRITICAL_ERROR_ALERT_COOLDOWN_MINUTES", 45) * 60
        should_alert_discord = True
        if last_error.get('signature') == error_signature:
            if (now_ts - last_error.get('timestamp', 0)) < cooldown_seconds:
                should_alert_discord = False
                log_message(f"ℹ️ Lỗi tương tự đã xảy ra gần đây. Tạm dừng gửi cảnh báo Discord.", state=state)
        log_error(f"LỖI TOÀN CỤC NGOÀI DỰ KIẾN", error_details=traceback.format_exc(), send_to_discord=should_alert_discord, state=state)
        if state:
            if should_alert_discord:
                 state['last_critical_error'] = {'signature': error_signature, 'timestamp': now_ts}
            save_json_file(STATE_FILE, state)
    finally:
        release_lock()
        if state and state.get('session_has_events', False):
            timestamp = datetime.now(VIETNAM_TZ).strftime('%Y-%m-%d %H:%M:%S')
            log_entry = f"[{timestamp}] (LiveTrade) ---[✅ Kết thúc phiên]---"
            print(log_entry)
            with open(LOG_FILE, "a", encoding="utf-8") as f: f.write(log_entry + "\n")

if __name__ == "__main__":
    run_session()
