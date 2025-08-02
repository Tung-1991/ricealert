# -*- coding: utf-8 -*-
"""
paper_trade.py - Quản lý Danh mục & Rủi ro Thông minh
Version: 4.5.1 - "Nhà Quản lý Rủi ro Đa khung thời gian & Báo cáo Real-time"
Date: 2025-07-31

Description:
Phiên bản 4.5.1 sửa một lỗi nghiêm trọng trong việc báo cáo PnL.
- FIX: Các báo cáo gửi lên Discord (hàng ngày và động) giờ đây sẽ sử dụng
  giá thị trường real-time để tính toán PnL, đảm bảo dữ liệu luôn chính xác
  và khớp với bảng điều khiển. Logic giao dịch cốt lõi vẫn hoạt động dựa
  trên giá của nến đã đóng để đảm bảo tính nhất quán của chiến lược.
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
from typing import Dict, List, Any, Tuple
from dotenv import load_dotenv
import traceback
import numpy as np

# --- Tải và Thiết lập ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
dotenv_path = os.path.join(PROJECT_ROOT, '.env')
load_dotenv(dotenv_path=dotenv_path)

sys.path.append(PROJECT_ROOT)
PAPER_DATA_DIR = os.path.join(BASE_DIR, "paper_data")
os.makedirs(PAPER_DATA_DIR, exist_ok=True)

### --- CÀI ĐẶT THƯ VIỆN CHO CACHE --- ###
# Để sử dụng cơ chế cache mới, bạn cần cài đặt thư viện pyarrow:
# pip install pyarrow
# ----------------------------------------

### START: Nâng cấp v4.4.0 ###
# Tạo thư mục con để lưu trữ các file cache dữ liệu giá
CACHE_DIR = os.path.join(PAPER_DATA_DIR, "indicator_cache")
os.makedirs(CACHE_DIR, exist_ok=True)
### END: Nâng cấp v4.4.0 ###

try:
    ### START: Sửa lỗi v4.4.1 ###
    # Xóa import hàm không tồn tại từ module của người dùng
    from indicator import get_price_data, calculate_indicators
    ### END: Sửa lỗi v4.4.1 ###
    from trade_advisor import get_advisor_decision, FULL_CONFIG as ADVISOR_BASE_CONFIG
except ImportError:
    sys.exit("Lỗi: Thiếu module 'indicator' hoặc 'trade_advisor'. Hãy chắc chắn chúng ở đúng vị trí.")

# ==============================================================================
# ================== ⚙️ TRUNG TÂM CẤU HÌNH (v4.5.0) ⚙️ ==================
# ==============================================================================

# --- VỐN & CẤU HÌNH CHUNG ---
INITIAL_CAPITAL = 10000.0 # Vốn khởi điểm để mô phỏng.

GENERAL_CONFIG = { # Các thiết lập vận hành chung của bot.
    "DATA_FETCH_LIMIT": 300, # Số nến tối đa để tính toán chỉ báo (đã giảm từ 500 để hỗ trợ coin mới).
    "DAILY_SUMMARY_TIMES": ["08:05", "20:05"], # Các thời điểm trong ngày để gửi báo cáo tổng kết.
    "TRADE_COOLDOWN_HOURS": 1, # Số giờ "nghỉ" không mở lệnh mới cho một coin sau khi vừa đóng lệnh.
    "CRON_JOB_INTERVAL_MINUTES": 15 # Tần suất chạy bot (phút).
}

# --- PHÂN TÍCH ĐA KHUNG THỜI GIAN (MTF) ---
MTF_ANALYSIS_CONFIG = { # Logic "nhìn" các khung thời gian lớn hơn để cộng/trừ điểm tín hiệu.
    "ENABLED": True, # Bật/tắt tính năng này.
    "BONUS_COEFFICIENT": 1.15, # Nhân điểm với 1.15 (thưởng 15%) nếu xu hướng khung lớn đồng thuận.
    "PENALTY_COEFFICIENT": 0.85, # Nhân điểm với 0.85 (phạt 15%) nếu xu hướng khung lớn ngược chiều.
    "SEVERE_PENALTY_COEFFICIENT": 0.70, # Phạt nặng 30% nếu các khung lớn hơn đều ngược chiều.
    "SIDEWAYS_PENALTY_COEFFICIENT": 0.90 # Phạt nhẹ 10% nếu khung lớn đang đi ngang.
}

# --- QUẢN LÝ LỆNH ĐANG CHẠY ---
ACTIVE_TRADE_MANAGEMENT_CONFIG = { # Các quy tắc để quản lý các lệnh đang mở.
    "EARLY_CLOSE_SCORE_THRESHOLD": 4.2, # Nếu điểm tín hiệu của một lệnh đang chạy giảm xuống dưới ngưỡng này, đóng lệnh ngay lập tức.
    "PROFIT_PROTECTION": { # Cơ chế bảo vệ lợi nhuận khi giá đảo chiều.
        "ENABLED": True,
        "MIN_PEAK_PNL_TRIGGER": 3.5, # Lợi nhuận phải đạt đỉnh ít nhất 4% thì cơ chế này mới được kích hoạt.
        "PNL_DROP_TRIGGER_PCT": 2.0, # Nếu PnL giảm 2.0% từ đỉnh, thực hiện chốt lời một phần.
        "PARTIAL_CLOSE_PCT": 0.7 # Chốt 60% khối lượng lệnh khi bảo vệ lợi nhuận được kích hoạt.
    }
}

# --- CẢNH BÁO ĐỘNG ---
DYNAMIC_ALERT_CONFIG = { # Cấu hình cho các thông báo cập nhật trạng thái ra Discord.
    "ENABLED": True,
    "COOLDOWN_HOURS": 4.5, # Gửi thông báo tối đa 4 giờ một lần.
    "FORCE_UPDATE_HOURS": 10, # Bắt buộc gửi thông báo sau mỗi 10 giờ dù không có thay đổi lớn.
    "PNL_CHANGE_THRESHOLD_PCT": 2 # Gửi thông báo nếu tổng PnL của tài khoản thay đổi lớn hơn 1.5%.
}

# --- QUY TẮC QUẢN LÝ RỦI RO ---
RISK_RULES_CONFIG = {
    "MAX_ACTIVE_TRADES": 12, # Số lượng lệnh được phép mở cùng một lúc.

    # === THÊM MỚI v4.5.0: Giới hạn SL tối đa theo từng khung thời gian ===
    "MAX_SL_PERCENT_BY_TIMEFRAME": {
        "1h": 0.06,  # Trần an toàn 6% cho các lệnh lướt sóng ngắn
        "4h": 0.08,  # Trần an toàn 8% cho các lệnh trung hạn
        "1d": 0.10   # Trần an toàn 10% cho các lệnh dài hạn
    },
        "MAX_TP_PERCENT_BY_TIMEFRAME": {
        "1h": 0.12,  # Lợi nhuận tối đa 12% cho lệnh 1h
        "4h": 0.20,  # Lợi nhuận tối đa 20% cho lệnh 4h
        "1d": 0.35   # Lợi nhuận tối đa 35% cho lệnh 1d
    },
    # =================================================================

    "STALE_TRADE_RULES": { # Quy tắc xử lý các lệnh bị "ì" (giữ quá lâu mà không có tiến triển).
        # Cấu hình cho từng khung thời gian:
        "1h": {"HOURS": 48,  "PROGRESS_THRESHOLD_PCT": 25.0, "MIN_RISK_BUFFER_PCT": 0.2}, # Sau 48h, lệnh 1h phải có PnL > 25% RR hoặc cách SL 0.2% entry.
        "4h": {"HOURS": 72,  "PROGRESS_THRESHOLD_PCT": 25.0, "MIN_RISK_BUFFER_PCT": 0.2}, # Tương tự cho 4h.
        "1d": {"HOURS": 168, "PROGRESS_THRESHOLD_PCT": 20.0, "MIN_RISK_BUFFER_PCT": 0.1}, # Tương tự cho 1d.
        "STAY_OF_EXECUTION_SCORE": 6.8 # Điểm "ân xá": Nếu lệnh bị "ì" nhưng tín hiệu mới > 6.8, lệnh sẽ được giữ lại.
    }
}

# --- QUẢN LÝ VỐN TỔNG ---
CAPITAL_MANAGEMENT_CONFIG = {
    "MAX_TOTAL_EXPOSURE_PCT": 0.75 # Tổng số vốn đang dùng cho các lệnh không được vượt quá 75% tổng tài sản.
}

# --- TRUNG BÌNH GIÁ (DCA) ---
DCA_CONFIG = {
    "ENABLED": True,
    "MAX_DCA_ENTRIES": 2, # Số lần DCA tối đa cho một lệnh.
    "TRIGGER_DROP_PCT": -5.0, # Kích hoạt DCA khi giá giảm 5% so với lần vào lệnh cuối cùng.
    "SCORE_MIN_THRESHOLD": 6.5, # Điểm tín hiệu phải lớn hơn 6.5 thì mới được phép DCA.
    "CAPITAL_MULTIPLIER": 0.75, # Lần DCA sau sẽ dùng số vốn gấp 1.5 lần lần trước.
    "DCA_COOLDOWN_HOURS": 8, # Phải cách lần DCA trước ít nhất 8 giờ.
    "DCA_REINVEST_RATIO": 0.5 # Tỷ lệ vốn tái đầu tư (so với vốn gốc) khi DCA bằng lợi nhuận đã chốt.
}

# --- CẤU HÌNH THÔNG BÁO ---
ALERT_CONFIG = {
    "DISCORD_WEBHOOK_URL": os.getenv("DISCORD_PAPER_WEBHOOK"), # Lấy link webhook từ file .env.
    "DISCORD_CHUNK_DELAY_SECONDS": 2, # Thời gian chờ giữa các phần của tin nhắn dài.
}

# --- PHÒNG THÍ NGHIỆM CHIẾN THUẬT (TACTICS LAB) ---
TACTICS_LAB = { # Nơi định nghĩa chi tiết các chiến lược giao dịch.
    "AI_Aggressor": {
        "NOTES": "Tin vào AI, nhưng vẫn cần sự xác nhận mạnh từ kỹ thuật.",
        "WEIGHTS": {'tech': 0.3, 'context': 0.1, 'ai': 0.6}, # Trọng số điểm: AI chiếm 60%.
        "ENTRY_SCORE": 6.8, # Điểm tối thiểu để vào lệnh.
        "RR": 2.0, # Tỷ lệ Rủi ro:Lợi nhuận (Risk:Reward).
        "USE_ATR_SL": True, "ATR_SL_MULTIPLIER": 2.8, # Dùng ATR để đặt SL, khoảng cách bằng 2.8 lần ATR.
        "USE_TRAILING_SL": True, "TRAIL_ACTIVATION_RR": 1.2, "TRAIL_DISTANCE_RR": 0.8, # Kích hoạt Trailing Stop khi đạt 1.2R, giữ khoảng cách 0.8R.
        "ENABLE_PARTIAL_TP": True, "TP1_RR_RATIO": 1.0, "TP1_PROFIT_PCT": 0.4 # Chốt lời 40% vốn khi đạt 1R.
    },
    "Balanced_Trader": {
        "NOTES": "Chiến binh chủ lực, cân bằng giữa kỹ thuật và AI.",
        "WEIGHTS": {'tech': 0.4, 'context': 0.2, 'ai': 0.4},
        "ENTRY_SCORE": 6.2, "RR": 1.8, "USE_ATR_SL": True, "ATR_SL_MULTIPLIER": 2.2,
        "USE_TRAILING_SL": True, "TRAIL_ACTIVATION_RR": 1.2, "TRAIL_DISTANCE_RR": 1.0,
        "ENABLE_PARTIAL_TP": True, "TP1_RR_RATIO": 1.0, "TP1_PROFIT_PCT": 0.6
    },
    "Dip_Hunter": {
        "NOTES": "Bắt đáy/bắt sóng hồi, dựa nhiều vào tín hiệu kỹ thuật và bối cảnh.",
        "WEIGHTS": {'tech': 0.6, 'context': 0.2, 'ai': 0.2},
        "ENTRY_SCORE": 6.5, "RR": 1.8, "USE_ATR_SL": True, "ATR_SL_MULTIPLIER": 2.0,
        "USE_TRAILING_SL": False, "TRAIL_ACTIVATION_RR": None, # Không dùng Trailing Stop.
        "ENABLE_PARTIAL_TP": True, "TP1_RR_RATIO": 0.7, "TP1_PROFIT_PCT": 0.7
    },
    "Breakout_Hunter": {
        "NOTES": "Săn đột phá, ưu tiên tuyệt đối tín hiệu kỹ thuật.",
        "WEIGHTS": {'tech': 0.7, 'context': 0.1, 'ai': 0.2},
        "ENTRY_SCORE": 7.0, "RR": 2.0, "USE_ATR_SL": True, "ATR_SL_MULTIPLIER": 1.8,
        "USE_TRAILING_SL": True, "TRAIL_ACTIVATION_RR": 1.0, "TRAIL_DISTANCE_RR": 0.8,
        "ENABLE_PARTIAL_TP": True, "TP1_RR_RATIO": 1.2, "TP1_PROFIT_PCT": 0.5
    },
    "Cautious_Observer": {
        "NOTES": "Chỉ đánh khi có cơ hội VÀNG, siêu an toàn, dựa chủ yếu vào kỹ thuật và bối cảnh.",
        "WEIGHTS": {'tech': 0.7, 'context': 0.2, 'ai': 0.1},
        "ENTRY_SCORE": 8.0, "RR": 1.5, "USE_ATR_SL": True, "ATR_SL_MULTIPLIER": 1.5,
        "USE_TRAILING_SL": True, "TRAIL_ACTIVATION_RR": 0.7, "TRAIL_DISTANCE_RR": 0.5,
        "ENABLE_PARTIAL_TP": True, "TP1_RR_RATIO": 0.8, "TP1_PROFIT_PCT": 0.5
    },
}

# --- BỘ LỌC CHIẾN THUẬT ---
STATE_TO_TACTICS_MAP = { # Ánh xạ "Bối cảnh thị trường" với các Tactic được phép sử dụng.
    "STATE_DIP_HUNTING": ["Dip_Hunter", "Balanced_Trader", "Cautious_Observer"], # Khi thị trường điều chỉnh giảm, chỉ dùng các Tactic này.
    "STATE_BREAKOUT_WAITING": ["Breakout_Hunter", "AI_Aggressor"], # Khi thị trường tích lũy hẹp, sẵn sàng cho đột phá.
    "STATE_STRONG_TREND": ["Breakout_Hunter", "AI_Aggressor", "Balanced_Trader"], # Khi có xu hướng mạnh.
    "STATE_CHOPPY": ["Cautious_Observer"], # Khi thị trường đi ngang, chỉ cho phép Tactic an toàn nhất.
    "STATE_UNCERTAIN": [] # Khi không xác định, không vào lệnh.
}


SYMBOLS_TO_SCAN_STRING = os.getenv("SYMBOLS_TO_SCAN", "ETHUSDT,BTCUSDT")
SYMBOLS_TO_SCAN = [symbol.strip() for symbol in SYMBOLS_TO_SCAN_STRING.split(',')]
INTERVALS_TO_SCAN = ["1h", "4h", "1d"]
ALL_TIME_FRAMES = ["1h", "4h", "1d"]
VIETNAM_TZ = pytz.timezone('Asia/Ho_Chi_Minh')

LOG_FILE = os.path.join(PAPER_DATA_DIR, "paper_trade_log.txt")
STATE_FILE = os.path.join(PAPER_DATA_DIR, "paper_trade_state.json")
TRADE_HISTORY_CSV_FILE = os.path.join(PAPER_DATA_DIR, "trade_history.csv")

indicator_results: Dict[str, Any] = {}
price_dataframes: Dict[str, Any] = {}

# ==============================================================================
# CÁC HÀM TIỆN ÍCH & QUẢN LÝ VỊ THẾ
# ==============================================================================

def log_message(message: str):
    timestamp = datetime.now(VIETNAM_TZ).strftime('%Y-%m-%d %H:%M:%S')
    log_entry = f"[{timestamp}] {message}"
    print(log_entry)
    with open(LOG_FILE, "a", encoding="utf-8") as f: f.write(log_entry + "\n")

def load_json_file(path: str, default: Any = None) -> Any:
    if not os.path.exists(path): return default if default is not None else {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        log_message(f"⚠️ Cảnh báo: File {path} bị hỏng. Sử dụng giá trị mặc định.")
        return default if default is not None else {}

def save_json_file(path: str, data: Any):
    temp_path = path + ".tmp"
    data_to_save = data.copy()
    data_to_save.pop('temp_newly_opened_trades', None)
    data_to_save.pop('temp_newly_closed_trades', None)
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(data_to_save, f, indent=4, ensure_ascii=False)
    os.replace(temp_path, path)


def send_discord_message_chunks(full_content: str):
    webhook_url = ALERT_CONFIG.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        log_message("⚠️ Không có Discord Webhook URL. Bỏ qua gửi tin nhắn Discord.")
        return
    max_len = 1900
    lines = full_content.split('\n')
    chunks, current_chunk = [], ""
    for line in lines:
        if len(current_chunk) + len(line) + 1 > max_len:
            if current_chunk: chunks.append(current_chunk)
            current_chunk = line
        else:
            current_chunk += ("\n" + line) if current_chunk else line
    if current_chunk: chunks.append(current_chunk)
    total_chunks = len(chunks)
    for i, chunk in enumerate(chunks):
        content_to_send = f"*(Phần {i+1}/{total_chunks})*\n{chunk}" if total_chunks > 1 else chunk
        try:
            requests.post(webhook_url, json={"content": content_to_send}, timeout=15).raise_for_status()
            if i < total_chunks - 1:
                time.sleep(ALERT_CONFIG["DISCORD_CHUNK_DELAY_SECONDS"])
        except requests.exceptions.RequestException as e:
            log_message(f"❌ Lỗi gửi chunk Discord {i+1}/{total_chunks}: {e}")
            break

# <<< SỬA LỖI BÁO CÁO >>>: Thêm hàm lấy giá real-time
def get_realtime_price(symbol: str) -> float | None:
    """Lấy giá thị trường hiện tại cho một symbol từ API Binance Spot."""
    url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()
        return float(data['price'])
    except Exception as e:
        log_message(f"⚠️ Không thể lấy giá real-time cho {symbol}: {e}")
        return None

def get_current_pnl(trade: Dict, realtime_price: float | None = None) -> Tuple[float, float]:
    """
    Tính toán PnL.
    - Nếu `realtime_price` được cung cấp, nó sẽ được sử dụng.
    - Nếu không, sẽ sử dụng giá từ `indicator_results` (giá đóng nến).
    """
    if not (trade and trade.get('entry_price', 0) > 0):
        return 0.0, 0.0

    current_price = 0.0
    if realtime_price is not None:
        current_price = realtime_price
    else:
        # Fallback to indicator price if no realtime price is given
        current_data = indicator_results.get(trade["symbol"], {}).get(trade["interval"])
        if current_data and current_data.get('price', 0) > 0:
            current_price = current_data['price']

    if current_price <= 0:
        return 0.0, 0.0

    pnl_multiplier = 1.0 if trade.get('trade_type', 'LONG') == 'LONG' else -1.0
    pnl_percent = (current_price - trade['entry_price']) / trade['entry_price'] * 100 * pnl_multiplier
    pnl_usd = trade.get('total_invested_usd', 0.0) * (pnl_percent / 100)
    return pnl_usd, pnl_percent


def export_trade_history_to_csv(closed_trades: List[Dict]):
    if not closed_trades: return
    try:
        df = pd.DataFrame(closed_trades)
        df['entry_time'] = pd.to_datetime(df['entry_time']).dt.tz_convert(VIETNAM_TZ)
        if 'exit_time' in df.columns:
            df['exit_time'] = pd.to_datetime(df['exit_time']).dt.tz_convert(VIETNAM_TZ)
            df['holding_duration_hours'] = round((df['exit_time'] - df['entry_time']).dt.total_seconds() / 3600, 2)
        else:
            df['holding_duration_hours'] = None

        cols = ["trade_id", "symbol", "interval", "status", "opened_by_tactic", "tactic_used",
                "trade_type", "entry_price", "exit_price", "tp", "sl", "total_invested_usd",
                "pnl_usd", "pnl_percent", "entry_time", "exit_time", "holding_duration_hours",
                "entry_score", "dca_entries"]
        df = df[[c for c in cols if c in df.columns]]

        if 'dca_entries' in df.columns: df['dca_entries'] = df['dca_entries'].apply(lambda x: json.dumps(x) if isinstance(x, list) else '[]')
        if 'tactic_used' in df.columns: df['tactic_used'] = df['tactic_used'].apply(lambda x: json.dumps(x) if isinstance(x, list) else str(x))

        header_mismatch = False
        if os.path.exists(TRADE_HISTORY_CSV_FILE):
            try:
                existing_df_headers = pd.read_csv(TRADE_HISTORY_CSV_FILE, nrows=0).columns.tolist()
                if set(existing_df_headers) != set(df.columns.tolist()): header_mismatch = True
            except Exception: header_mismatch = True
        if header_mismatch: log_message("⚠️ CẢNH BÁO: Header của trade_history.csv không khớp. File sẽ được ghi đè.")

        df.to_csv(TRADE_HISTORY_CSV_FILE, mode='a' if os.path.exists(TRADE_HISTORY_CSV_FILE) and not header_mismatch else 'w',
                  header=not os.path.exists(TRADE_HISTORY_CSV_FILE) or header_mismatch, index=False, encoding="utf-8")
        log_message(f"✅ Đã xuất {len(df)} lệnh đã đóng vào {TRADE_HISTORY_CSV_FILE}")
    except Exception as e:
        log_message(f"❌ Lỗi khi xuất lịch sử giao dịch ra CSV: {e}")

### START: Sửa lỗi v4.4.1 - Tích hợp hàm bị thiếu vào file ###
def get_interval_in_milliseconds(interval: str) -> int | None:
    """Chuyển đổi chuỗi interval (ví dụ: '1h', '4h', '1d') sang milliseconds."""
    unit = interval[-1]
    try:
        value = int(interval[:-1])
    except (ValueError, IndexError):
        return None

    if unit == 'm':
        return value * 60 * 1000
    elif unit == 'h':
        return value * 60 * 60 * 1000
    elif unit == 'd':
        return value * 24 * 60 * 60 * 1000
    else:
        return None
### END: Sửa lỗi v4.4.1 ###
# Đây là hàm duy nhất bạn cần thay thế trong file backtest/paper_trade.py

def get_price_data_with_cache(symbol: str, interval: str, limit: int) -> pd.DataFrame | None:
    """
    Lấy dữ liệu giá với cơ chế cache để giảm thiểu số lần gọi API.
    - SỬA LỖI: Thêm .copy() để tắt hoàn toàn cảnh báo SettingWithCopyWarning.
    """
    cache_filename = f"{symbol}-{interval}.parquet"
    cache_filepath = os.path.join(CACHE_DIR, cache_filename)

    existing_df = None
    if os.path.exists(cache_filepath):
        try:
            existing_df = pd.read_parquet(cache_filepath)
        except Exception as e:
            log_message(f"⚠️ Lỗi đọc file cache {cache_filepath}: {e}. Sẽ tải lại từ đầu.")
            existing_df = None

    if existing_df is not None and not existing_df.empty:
        last_timestamp_ms = int(existing_df.index[-1].timestamp() * 1000)
        interval_ms = get_interval_in_milliseconds(interval)
        if not interval_ms:
                 log_message(f"⚠️ Khung thời gian không hợp lệ: {interval}")
                 return existing_df
        start_time_ms = last_timestamp_ms + interval_ms
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

        if now_ms > start_time_ms:
            # Gọi hàm get_price_data từ module indicator đã được sửa lỗi
            new_data_df = get_price_data(symbol, interval, limit=limit, startTime=start_time_ms)

            if new_data_df is not None and not new_data_df.empty:
                combined_df = pd.concat([existing_df, new_data_df])
                combined_df = combined_df[~combined_df.index.duplicated(keep='last')]
                # log_message(f"       => Tải thành công {len(new_data_df)} nến mới.")
            else:
                # log_message(f"       => Không có nến mới nào cho {symbol}-{interval}.")
                combined_df = existing_df
        else:
            combined_df = existing_df

        # <<< SỬA LỖI CHÍNH >>>: Thêm .copy() vào đây để tạo một DataFrame mới hoàn toàn
        final_df = combined_df.tail(limit).copy()
    else:
        log_message(f"  -> {symbol}-{interval}: Không có cache. Tải toàn bộ {limit} nến...")
        # Gọi hàm get_price_data từ module indicator
        final_df = get_price_data(symbol, interval, limit=limit)

    if final_df is not None and not final_df.empty:
        try:
            for col in final_df.select_dtypes(include=['float64']).columns:
                if col != 'close':
                    final_df[col] = final_df[col].astype('float32')
            final_df.to_parquet(cache_filepath)
        except Exception as e:
            log_message(f"❌ Lỗi lưu file cache {cache_filepath}: {e}")
        return final_df
    elif existing_df is not None:
         log_message(f"⚠️ Không thể tải dữ liệu mới cho {symbol}-{interval}, sử dụng dữ liệu cache cũ.")
         return existing_df
    else:
        log_message(f"❌ Không thể tải dữ liệu cho {symbol}-{interval} và cũng không có cache.")
        return None


def calculate_total_equity(state: Dict, realtime_prices: Dict[str, float] | None = None) -> float:
    # <<< SỬA LỖI BÁO CÁO >>>: Tính tổng tài sản với giá real-time nếu có
    cash = state.get('cash', INITIAL_CAPITAL)
    invested_capital = 0
    for t in state.get('active_trades', []):
        price = realtime_prices.get(t['symbol']) if realtime_prices else None
        pnl_usd, _ = get_current_pnl(t, realtime_price=price)
        invested_capital += t.get('total_invested_usd', 0.0) + pnl_usd
    return cash + invested_capital


def determine_dynamic_capital_pct(atr_percent: float) -> float:
    if pd.isna(atr_percent):
        log_message("⚠️ Cảnh báo: atr_percent là NaN. Sử dụng mức phân bổ vốn tối thiểu (3%) cho an toàn.")
        return 0.03

    if atr_percent <= 1.5: base = 0.10
    elif atr_percent <= 3: base = 0.07
    elif atr_percent <= 5: base = 0.05
    else: base = 0.03
    return max(0.03, min(base, 0.12))

def calculate_average_price(trade: Dict) -> float:
    entries = [trade['initial_entry']] + trade.get('dca_entries', [])
    total_cost = sum(e.get('invested_usd', 0.0) * e.get('price', e.get('entry_price', 0.0)) for e in entries)
    total_invested = sum(e.get('invested_usd', 0.0) for e in entries)
    return total_cost / total_invested if total_invested > 0 else 0

# ==============================================================================
# QUẢN LÝ VỊ THẾ CHỦ ĐỘNG
# ==============================================================================

def manage_active_trades(portfolio_state: Dict):
    log_message("🧠 Bắt đầu chu trình Quản lý Lệnh Chủ động...")
    newly_managed_details = []

    for trade in portfolio_state.get("active_trades", [])[:]:
        # QUAN TRỌNG: Logic quản lý lệnh vẫn dùng giá đóng nến từ indicator_results
        indicators = indicator_results.get(trade['symbol'], {}).get(trade['interval'])
        if not (indicators and indicators.get('price')):
            continue

        evaluations = []
        for tactic_name, tactic_cfg in TACTICS_LAB.items():
            if not tactic_cfg.get("WEIGHTS"): continue
            decision = get_advisor_decision(trade['symbol'], trade['interval'], indicators, ADVISOR_BASE_CONFIG, weights_override=tactic_cfg.get("WEIGHTS"))
            evaluations.append({"tactic": tactic_name, "score": decision.get("final_score", 0.0)})

        if not evaluations: continue

        best_eval = max(evaluations, key=lambda x: x['score'])
        controlling_tactic_name = best_eval['tactic']
        new_score = best_eval['score']

        trade['last_score'] = new_score
        trade['controlling_tactic'] = controlling_tactic_name

        # PnL ở đây cũng dùng giá đóng nến để check logic bảo vệ lợi nhuận
        pnl_usd, pnl_percent = get_current_pnl(trade)
        trade['peak_pnl_percent'] = max(trade.get('peak_pnl_percent', 0.0), pnl_percent)

        pp_config = ACTIVE_TRADE_MANAGEMENT_CONFIG.get("PROFIT_PROTECTION", {})
        if (pp_config.get("ENABLED", False) and not trade.get('profit_taken', False) and
            trade['peak_pnl_percent'] >= pp_config.get("MIN_PEAK_PNL_TRIGGER", 3.0)):

            pnl_drop = trade['peak_pnl_percent'] - pnl_percent
            score_drop = trade.get('entry_score', 5.0) - new_score

            if pnl_drop >= pp_config.get("PNL_DROP_TRIGGER_PCT", 2.5) and score_drop > 0.5:
                log_message(f"🛡️ BẢO VỆ LỢI NHUẬN cho {trade['symbol']}. PnL giảm {pnl_drop:.2f}% từ đỉnh.")
                close_pct = pp_config.get("PARTIAL_CLOSE_PCT", 0.6)
                invested_to_close = trade.get('total_invested_usd', 0.0) * close_pct
                partial_pnl_usd = (pnl_percent / 100) * invested_to_close

                portfolio_state['cash'] += (invested_to_close + partial_pnl_usd)
                trade['total_invested_usd'] -= invested_to_close
                trade['sl'] = trade['entry_price']
                trade['trailing_sl'] = max(trade.get('trailing_sl', 0), trade['entry_price'])
                trade.setdefault('tactic_used', []).append(f"Profit_Protect")

                # === CẢI TIẾN: LƯU LẠI LỢI NHUẬN ĐÃ CHỐT ===
                trade.setdefault('realized_pnl_usd', 0.0)
                trade['realized_pnl_usd'] += partial_pnl_usd
                trade['profit_taken'] = True
                # ============================================

                newly_managed_details.append(f"🛡️ {trade['symbol']} (Bảo vệ LN): PnL ${partial_pnl_usd:,.2f}")
                continue

        if new_score < ACTIVE_TRADE_MANAGEMENT_CONFIG['EARLY_CLOSE_SCORE_THRESHOLD']:
            log_message(f"🚨 CẮT LỖ SỚM cho {trade['symbol']}. Điểm số mới ({new_score:.2f}) quá thấp.")
            exit_price = indicators.get('price')

            pnl_usd_final, pnl_ratio_final = get_current_pnl(trade)

            portfolio_state['cash'] += (trade.get('total_invested_usd', 0.0) + pnl_usd_final)
            trade.setdefault('tactic_used', []).append(f"Early_Close_@{new_score:.1f}")
            trade.update({
                'status': 'Closed (Early)', 'exit_price': exit_price, 'exit_time': datetime.now(VIETNAM_TZ).isoformat(),
                'pnl_usd': pnl_usd_final, 'pnl_percent': pnl_ratio_final
            })
            portfolio_state['active_trades'].remove(trade)
            portfolio_state['trade_history'].append(trade)
            newly_managed_details.append(f"🚨 {trade['symbol']} (Cắt sớm): PnL ${pnl_usd_final:,.2f}")
            continue

    if newly_managed_details:
        portfolio_state.setdefault('temp_newly_closed_trades', []).extend(newly_managed_details)

# ==============================================================================
# CÁC HÀM XỬ LÝ GỐC
# ==============================================================================

def handle_trade_closure(portfolio_state: Dict) -> List[Dict]:
    closed_trades, newly_closed_details = [], []
    now_vn = datetime.now(VIETNAM_TZ)

    for trade in portfolio_state["active_trades"][:]:
        # QUAN TRỌNG: Logic đóng lệnh vẫn dùng giá đóng nến từ indicator_results
        data = indicator_results.get(trade['symbol'], {}).get(trade['interval'], {})
        current_price = data.get('price', 0)
        if not current_price > 0:
            continue

        controlling_tactic = trade.get('controlling_tactic', trade['opened_by_tactic'])
        tactic_cfg = TACTICS_LAB.get(controlling_tactic, {})
        trade_type = trade.get('trade_type', 'LONG')
        pnl_multiplier = 1.0 if trade_type == 'LONG' else -1.0

        status, exit_p = None, None

        if 'initial_risk_dist' not in trade or trade['initial_risk_dist'] <= 0:
            trade['initial_risk_dist'] = abs(trade['entry_price'] - trade['initial_sl'])

        initial_risk_dist = trade.get('initial_risk_dist', 0)
        if initial_risk_dist <= 0: continue

        pnl_ratio_from_entry = pnl_multiplier * (current_price - trade['entry_price']) / initial_risk_dist

        if tactic_cfg.get("ENABLE_PARTIAL_TP", False) and not trade.get('profit_taken', False):
            tp1_rr_ratio = tactic_cfg.get("TP1_RR_RATIO", 1.0)
            if pnl_ratio_from_entry >= tp1_rr_ratio:
                profit_taken_pct = tactic_cfg.get("TP1_PROFIT_PCT", 0.5)
                invested_to_close = trade.get('total_invested_usd', 0.0) * profit_taken_pct

                tp1_price = trade['entry_price'] + (initial_risk_dist * tp1_rr_ratio * pnl_multiplier)
                partial_pnl_usd = ((tp1_price - trade['entry_price']) / trade['entry_price']) * invested_to_close * pnl_multiplier

                portfolio_state['cash'] += (invested_to_close + partial_pnl_usd)
                trade['total_invested_usd'] -= invested_to_close
                trade['sl'] = trade['entry_price']
                trade['trailing_sl'] = max(trade.get('trailing_sl', 0), trade['entry_price']) if trade_type == 'LONG' else min(trade.get('trailing_sl', float('inf')), trade['entry_price'])

                if "Partial_TP_Taken" not in trade.get('tactic_used', []):
                    trade.setdefault('tactic_used', []).append(f"Partial_TP_{tp1_rr_ratio}RR")

                # === CẢI TIẾN: LƯU LẠI LỢI NHUẬN ĐÃ CHỐT ===
                trade.setdefault('realized_pnl_usd', 0.0)
                trade['realized_pnl_usd'] += partial_pnl_usd
                trade['profit_taken'] = True
                # ============================================

                log_message(f"💰 Đã chốt lời TP1 cho {trade['symbol']} (${invested_to_close:,.2f}) | PnL TP1: ${partial_pnl_usd:,.2f}. SL dời về hòa vốn.")
                newly_closed_details.append(f"💰 {trade['symbol']} (TP1): PnL ${partial_pnl_usd:,.2f}")

        trail_activation_rr = tactic_cfg.get("TRAIL_ACTIVATION_RR")
        if tactic_cfg.get("USE_TRAILING_SL", False) and trail_activation_rr is not None:
            if pnl_ratio_from_entry >= trail_activation_rr:
                trail_dist_rr = tactic_cfg.get("TRAIL_DISTANCE_RR", 0.8)
                new_trailing_sl = current_price - (initial_risk_dist * trail_dist_rr * pnl_multiplier)

                is_better_tsl = (new_trailing_sl > trade.get('trailing_sl', trade['sl'])) if trade_type == 'LONG' else (new_trailing_sl < trade.get('trailing_sl', trade['sl']))
                if is_better_tsl:
                    if "Trailing_SL_Active" not in trade.get('tactic_used', []):
                        trade.setdefault('tactic_used', []).append("Trailing_SL_Active")
                    trade['trailing_sl'] = new_trailing_sl
                    trade['sl'] = new_trailing_sl

        final_sl = trade.get('trailing_sl', trade['sl'])
        if (trade_type == 'LONG' and current_price <= final_sl) or \
           (trade_type == 'SHORT' and current_price >= final_sl):
            status, exit_p = "SL", final_sl
        elif (trade_type == 'LONG' and current_price >= trade['tp']) or \
             (trade_type == 'SHORT' and current_price <= trade['tp']):
            status, exit_p = "TP", trade['tp']

        if status:
            pnl_usd_final = (exit_p - trade['entry_price']) / trade['entry_price'] * trade.get('total_invested_usd', 0.0) * pnl_multiplier
            pnl_percent_final = (exit_p - trade['entry_price']) / trade['entry_price'] * 100 * pnl_multiplier

            portfolio_state['cash'] += (trade.get('total_invested_usd', 0.0) + pnl_usd_final)
            trade.update({
                'status': f'Closed ({status})', 'exit_price': exit_p, 'exit_time': now_vn.isoformat(),
                'pnl_usd': pnl_usd_final, 'pnl_percent': pnl_percent_final
            })
            cooldown_duration = timedelta(hours=GENERAL_CONFIG.get("TRADE_COOLDOWN_HOURS", 1))
            cooldown_end_time = now_vn + cooldown_duration
            portfolio_state.setdefault('cooldown_until', {})[trade['symbol']] = cooldown_end_time.isoformat()

            portfolio_state['active_trades'].remove(trade)
            portfolio_state['trade_history'].append(trade)
            closed_trades.append(trade)
            icon = '✅' if status == 'TP' else ('❌' if pnl_usd_final < 0 else '🤝')
            log_message(f"{icon} Đã đóng lệnh {status}: {trade['symbol']} | PnL: ${pnl_usd_final:,.2f}")
            newly_closed_details.append(f"{icon} {trade['symbol']} ({status}): PnL ${pnl_usd_final:,.2f}")

    if newly_closed_details:
        portfolio_state.setdefault('temp_newly_closed_trades', []).extend(newly_closed_details)

    return closed_trades

def handle_stale_trades(portfolio_state: Dict) -> List[Dict]:
    closed_trades, newly_closed_details = [], []
    now_aware = datetime.now(VIETNAM_TZ)
    for trade in portfolio_state.get("active_trades", [])[:]:
        override_until = trade.get("stale_override_until")
        if override_until:
            try:
                override_time = datetime.fromisoformat(override_until)
                if now_aware < override_time:
                    log_message(f"⏳ Lệnh {trade['symbol']} đang được gia hạn stale đến {override_time}. Bỏ qua.")
                    continue
            except Exception as e:
                log_message(f"⚠️ Lỗi khi đọc stale_override_until của {trade['symbol']}: {e}")
        rules = RISK_RULES_CONFIG["STALE_TRADE_RULES"].get(trade.get("interval"))
        if not rules: continue
        entry_time = datetime.fromisoformat(trade['entry_time'])
        holding_duration_hours = (now_aware - entry_time).total_seconds() / 3600

        if holding_duration_hours > rules["HOURS"]:
            # Logic stale trade cũng dùng giá đóng nến
            _, pnl_pct = get_current_pnl(trade)
            current_price = indicator_results.get(trade['symbol'], {}).get(trade['interval'], {}).get('price', 0)
            if not current_price > 0: continue

            progress_made = pnl_pct >= rules["PROGRESS_THRESHOLD_PCT"]

            current_sl_buffer_pct = (abs(current_price - trade['sl']) / trade['entry_price']) * 100
            if current_sl_buffer_pct >= rules["MIN_RISK_BUFFER_PCT"]:
                progress_made = True

            latest_score = trade.get('last_score', 5.0)
            stay_of_execution_score = RISK_RULES_CONFIG["STALE_TRADE_RULES"].get("STAY_OF_EXECUTION_SCORE", 6.8)

            if not progress_made and latest_score < stay_of_execution_score:
                exit_price = current_price
                pnl_usd_final, pnl_percent_final = get_current_pnl(trade)

                portfolio_state['cash'] += (trade.get('total_invested_usd', 0.0) + pnl_usd_final)
                trade.setdefault('tactic_used', []).append("Stale_Closure")
                trade.update({
                    'status': 'Closed (Stale)', 'exit_price': exit_price, 'exit_time': now_aware.isoformat(),
                    'pnl_usd': pnl_usd_final, 'pnl_percent': pnl_percent_final
                })
                portfolio_state['active_trades'].remove(trade)
                portfolio_state['trade_history'].append(trade)
                closed_trades.append(trade)
                log_message(f"🐌 Đã đóng lệnh ì (Stale): {trade['symbol']} ({trade['interval']}) sau {holding_duration_hours:.1f}h | PnL: ${pnl_usd_final:,.2f}")
                newly_closed_details.append(f"🐌 {trade['symbol']} (Stale): PnL ${pnl_usd_final:,.2f}")
            elif not progress_made and latest_score >= stay_of_execution_score:
                log_message(f"⏳ Lệnh {trade['symbol']} đã quá hạn nhưng được GIA HẠN do tín hiệu mới rất tốt (Điểm: {latest_score:.2f})")

    if newly_closed_details:
        portfolio_state.setdefault('temp_newly_closed_trades', []).extend(newly_closed_details)
    return closed_trades

def handle_dca_opportunities(state: Dict, equity: float):
    if not DCA_CONFIG["ENABLED"]: return

    if DCA_CONFIG["TRIGGER_DROP_PCT"] >= 0:
        log_message(f"⚠️ CẢNH BÁO: DCA_CONFIG['TRIGGER_DROP_PCT'] được đặt là {DCA_CONFIG['TRIGGER_DROP_PCT']}. "
                    f"Đây là một giá trị không an toàn. Tạm dừng chức năng DCA.")
        return

    current_exposure_usd = sum(t.get('total_invested_usd', 0.0) for t in state.get('active_trades', []))
    for trade in state.get("active_trades", []):
        if len(trade.get("dca_entries", [])) >= DCA_CONFIG["MAX_DCA_ENTRIES"]:
            continue

        # Logic DCA cũng dùng giá đóng nến
        current_data = indicator_results.get(trade["symbol"], {}).get(trade["interval"], {})
        current_price = current_data.get('price', 0)
        if not current_price > 0:
            continue

        pnl_multiplier = 1.0 if trade.get('trade_type', 'LONG') == 'LONG' else -1.0

        # === LOGIC KIỂM TRA ĐIỀU KIỆN DCA CHUNG ===
        last_entry_price = trade['dca_entries'][-1]['entry_price'] if trade.get('dca_entries') else trade['initial_entry']['price']
        price_drop_pct = ((current_price - last_entry_price) / last_entry_price) * 100 * pnl_multiplier
        if price_drop_pct > DCA_CONFIG["TRIGGER_DROP_PCT"]:
            continue

        if trade.get('dca_entries'):
            last_dca_time = datetime.fromisoformat(trade['dca_entries'][-1]["timestamp"])
            if (datetime.now(VIETNAM_TZ) - last_dca_time).total_seconds() / 3600 < DCA_CONFIG["DCA_COOLDOWN_HOURS"]:
                continue

        original_tactic_cfg = TACTICS_LAB.get(trade['opened_by_tactic'], {})
        if not original_tactic_cfg.get("WEIGHTS"): continue
        decision = get_advisor_decision(trade['symbol'], trade['interval'], current_data, ADVISOR_BASE_CONFIG, weights_override=original_tactic_cfg.get("WEIGHTS"))
        if decision.get("final_score", 0.0) < DCA_CONFIG["SCORE_MIN_THRESHOLD"]:
            log_message(f"⚠️ Muốn DCA cho {trade['symbol']} nhưng điểm theo Tactic gốc ({decision.get('final_score', 0.0):.2f}) quá thấp.")
            continue
        # ===============================================

        # === PHÂN LUỒNG LOGIC DCA MỚI ===
        if trade.get('profit_taken', False):
            # --- LOGIC DCA BẰNG LỢI NHUẬN ĐÃ CHỐT ---
            realized_pnl = trade.get('realized_pnl_usd', 0.0)
            if realized_pnl <= 0:
                continue

            reinvest_ratio = DCA_CONFIG.get("DCA_REINVEST_RATIO", 0.5)
            dca_investment = min(realized_pnl, trade['initial_entry']['invested_usd'] * reinvest_ratio)

            if (current_exposure_usd + dca_investment) / equity > CAPITAL_MANAGEMENT_CONFIG["MAX_TOTAL_EXPOSURE_PCT"] or dca_investment > state['cash']:
                log_message(f"⚠️ Muốn DCA tái đầu tư cho {trade['symbol']} nhưng vượt ngưỡng rủi ro hoặc không đủ tiền. Bỏ qua.")
                continue

            log_message(f"🎯 THỰC HIỆN DCA TÁI ĐẦU TƯ LỢI NHUẬN Lần {len(trade.get('dca_entries', [])) + 1} cho {trade['symbol']}...")
            trade['realized_pnl_usd'] -= dca_investment

        else:
            # --- LOGIC DCA GỐC (KHI CHƯA CHỐT LỜI) ---
            last_investment = trade['dca_entries'][-1]['invested_usd'] if trade.get('dca_entries') else trade['initial_entry']['invested_usd']
            dca_investment = last_investment * DCA_CONFIG["CAPITAL_MULTIPLIER"]

            if (current_exposure_usd + dca_investment) / equity > CAPITAL_MANAGEMENT_CONFIG["MAX_TOTAL_EXPOSURE_PCT"] or dca_investment > state['cash']:
                log_message(f"⚠️ Muốn DCA cho {trade['symbol']} nhưng vượt ngưỡng rủi ro hoặc không đủ tiền. Bỏ qua.")
                continue

            log_message(f"🎯 THỰC HIỆN DCA Lần {len(trade.get('dca_entries', [])) + 1} cho {trade['symbol']}...")

        # --- THỰC HIỆN DCA (LOGIC CHUNG) ---
        state['cash'] -= dca_investment
        trade.setdefault('dca_entries', []).append({
            "entry_price": current_price, "invested_usd": dca_investment, "timestamp": datetime.now(VIETNAM_TZ).isoformat()
        })

        trade['total_invested_usd'] += dca_investment
        new_avg_price = calculate_average_price(trade)
        trade['entry_price'] = new_avg_price

        initial_risk_dist = abs(trade['initial_entry']['price'] - trade['initial_sl'])
        trade['sl'] = new_avg_price - (initial_risk_dist * pnl_multiplier)
        trade['tp'] = new_avg_price + (initial_risk_dist * original_tactic_cfg.get('RR', 2.0) * pnl_multiplier)
        trade['trailing_sl'] = trade['sl']
        trade['profit_taken'] = False # Reset cờ profit_taken để có thể chốt lời lại sau DCA
        trade['peak_pnl_percent'] = 0.0 # Reset đỉnh PnL

        trade.setdefault('tactic_used', []).append(f"DCA_{len(trade.get('dca_entries', []))}")

        log_message(f"✅ DCA thành công. Vốn mới cho {trade['symbol']}: ${trade['total_invested_usd']:,.2f}. Giá TB mới: {new_avg_price:.4f}")

# ==============================================================================
# BỘ NÃO & RA QUYẾT ĐỊNH
# ==============================================================================

def determine_market_state(symbol: str, interval: str, df: pd.DataFrame) -> str:
    indicators = indicator_results.get(symbol, {}).get(interval, {})
    if not indicators or df.empty:
        return "STATE_UNCERTAIN"

    if 'bb_width' in indicators and pd.notna(indicators['bb_width']):
        bb_width = indicators['bb_width']
        if 'bb_width' in df.columns:
            recent_bbw = df['bb_width'].dropna().tail(100)
            if not recent_bbw.empty:
                squeeze_threshold = recent_bbw.quantile(0.25)
                if bb_width < squeeze_threshold:
                    return "STATE_BREAKOUT_WAITING"

    trend = indicators.get('trend')
    adx = indicators.get('adx', 0)
    if trend in ["uptrend", "downtrend"] and adx > 25:
        return "STATE_STRONG_TREND"

    rsi = indicators.get('rsi_14', 50)
    higher_tf = '1d' if interval != '1d' else '1d'
    higher_tf_trend = indicator_results.get(symbol, {}).get(higher_tf, {}).get('trend')
    if higher_tf_trend == "uptrend" and rsi < 40:
        return "STATE_DIP_HUNTING"

    if adx < 20:
        return "STATE_CHOPPY"

    return "STATE_UNCERTAIN"

def get_mtf_adjustment_coefficient(symbol: str, target_interval: str, trade_type: str = "LONG") -> float:
    if not MTF_ANALYSIS_CONFIG["ENABLED"]:
        return 1.0

    trends = {
        tf: indicator_results.get(symbol, {}).get(tf, {}).get("trend", "sideways")
        for tf in ALL_TIME_FRAMES
    }
    cfg = MTF_ANALYSIS_CONFIG

    favorable_trend = "uptrend" if trade_type == "LONG" else "downtrend"
    unfavorable_trend = "downtrend" if trade_type == "LONG" else "uptrend"

    if target_interval == "1h":
        htf1, htf2 = trends["4h"], trends["1d"]
        if htf1 == unfavorable_trend and htf2 == unfavorable_trend: return cfg["SEVERE_PENALTY_COEFFICIENT"]
        if htf1 == unfavorable_trend or htf2 == unfavorable_trend: return cfg["PENALTY_COEFFICIENT"]
        if htf1 == favorable_trend and htf2 == favorable_trend: return cfg["BONUS_COEFFICIENT"]
        if htf1 == "sideways" or htf2 == "sideways": return cfg["SIDEWAYS_PENALTY_COEFFICIENT"]

    elif target_interval == "4h":
        htf1 = trends["1d"]
        if htf1 == unfavorable_trend: return cfg["PENALTY_COEFFICIENT"]
        if htf1 == favorable_trend: return cfg["BONUS_COEFFICIENT"]
        if htf1 == "sideways": return cfg["SIDEWAYS_PENALTY_COEFFICIENT"]

    return 1.0


def find_and_open_new_trades(state: Dict, equity: float):
    """
    Tìm và mở lệnh mới. Ép SL/TP về đúng trần an toàn nếu ATR quá lớn.
    (Phiên bản cho paper_trade)
    """
    active_trades = state.get('active_trades', [])
    if len(active_trades) >= RISK_RULES_CONFIG["MAX_ACTIVE_TRADES"]:
        log_message(f"ℹ️ Đã đạt giới hạn {len(active_trades)}/{RISK_RULES_CONFIG['MAX_ACTIVE_TRADES']} lệnh. Không tìm lệnh mới.")
        return

    potential_opportunities = []
    now_vn = datetime.now(VIETNAM_TZ)

    trade_type_to_scan = "LONG"
    log_message(f"🔎 Bắt đầu quét cơ hội lệnh {trade_type_to_scan}...")

    for symbol in SYMBOLS_TO_SCAN:
        if any(t['symbol'] == symbol for t in active_trades): continue
        cooldown_map = state.get('cooldown_until', {})
        if symbol in cooldown_map and now_vn < datetime.fromisoformat(cooldown_map[symbol]): continue

        for interval in INTERVALS_TO_SCAN:
            indicators = indicator_results.get(symbol, {}).get(interval)
            df_data = price_dataframes.get(symbol, {}).get(interval)
            if not (indicators and indicators.get('price', 0) > 0 and df_data is not None): continue

            market_state = determine_market_state(symbol, interval, df_data)
            allowed_tactics = STATE_TO_TACTICS_MAP.get(market_state, [])
            if not allowed_tactics: continue
            
            for tactic_name in allowed_tactics:
                tactic_cfg = TACTICS_LAB[tactic_name]
                if not tactic_cfg.get("WEIGHTS"): continue

                decision = get_advisor_decision(symbol, interval, indicators, ADVISOR_BASE_CONFIG, weights_override=tactic_cfg.get("WEIGHTS"))
                adjusted_score = decision.get("final_score", 0.0) * get_mtf_adjustment_coefficient(symbol, interval, trade_type_to_scan)

                if adjusted_score >= tactic_cfg.get("ENTRY_SCORE", 9.9):
                    potential_opportunities.append({
                        "decision": decision, "tactic_name": tactic_name, "tactic_cfg": tactic_cfg,
                        "score": adjusted_score, "symbol": symbol, "interval": interval,
                        "trade_type": trade_type_to_scan
                    })

    if not potential_opportunities:
        log_message("ℹ️ Phiên này không tìm thấy cơ hội nào đủ điều kiện sau khi quét.")
        return

    best_opportunity = sorted(potential_opportunities, key=lambda x: x['score'], reverse=True)[0]
    decision_data, tactic_name, tactic_cfg = best_opportunity['decision'], best_opportunity['tactic_name'], best_opportunity['tactic_cfg']
    symbol, interval, score, trade_type = best_opportunity['symbol'], best_opportunity['interval'], best_opportunity['score'], best_opportunity['trade_type']

    log_message(f"🏆 CƠ HỘI TỐT NHẤT PHIÊN: {symbol}-{interval} | Tactic: {tactic_name} | Điểm (đã điều chỉnh): {score:.2f}")

    full_indicators = decision_data.get('full_indicators', {})
    entry_p = full_indicators.get('price')
    if not entry_p or entry_p <= 0: return

    # ========= 🔥 ĐOẠN SỬA LỖI TRỰC TIẾP & NGẮN GỌN (Tương tự live_trade) 🔥 =========
    # 1. Tính risk_dist dựa trên ATR như bình thường
    risk_dist_from_atr = full_indicators.get('atr', 0) * tactic_cfg.get("ATR_SL_MULTIPLIER", 2.0)

    # 2. Tính risk_dist tối đa cho phép theo %
    max_sl_pct = RISK_RULES_CONFIG["MAX_SL_PERCENT_BY_TIMEFRAME"].get(interval)
    if max_sl_pct is None:
        log_message(f"⚠️ Không có cấu hình MAX_SL_PERCENT cho {interval}. Bỏ qua.")
        return
    max_risk_dist_allowed = entry_p * max_sl_pct
    
    # 3. Chọn risk_dist cuối cùng: Lấy cái NHỎ HƠN giữa 2 cái trên
    final_risk_dist = min(risk_dist_from_atr, max_risk_dist_allowed)
    
    if final_risk_dist == max_risk_dist_allowed and risk_dist_from_atr > max_risk_dist_allowed:
        log_message(f"  -> 🛡️ ATR quá lớn! Ép rủi ro về mức trần an toàn ({max_sl_pct:.2%}).")

    if final_risk_dist <= 0:
        log_message(f"⚠️ Khoảng cách rủi ro cuối cùng không hợp lệ ({final_risk_dist:.4f}). Bỏ qua.")
        return
    # =================================================================================

    capital_pct = determine_dynamic_capital_pct(full_indicators.get('atr_percent', 3.0))
    invested_amount = equity * capital_pct

    current_exposure_usd = sum(t.get('total_invested_usd', 0.0) for t in active_trades)
    if (current_exposure_usd + invested_amount) / equity > CAPITAL_MANAGEMENT_CONFIG["MAX_TOTAL_EXPOSURE_PCT"] or invested_amount > state['cash']:
        log_message(f"⚠️ Mở lệnh {symbol} sẽ vượt ngưỡng rủi ro hoặc không đủ tiền. Bỏ qua.")
        return

    # Dùng final_risk_dist đã được "ép" để tính SL/TP
    # ========= BƯỚC 1: TÍNH TOÁN SL VÀ TP VỚI LOGIC ÁP TRẦN =========
    pnl_multiplier = 1.0 if trade_type == "LONG" else -1.0
    
    # Tính SL cuối cùng từ final_risk_dist đã được áp trần
    sl_p = entry_p - (final_risk_dist * pnl_multiplier)
    
    # --- Logic áp trần TP ---
    # 1. Tính TP theo Tỷ lệ R:R (Risk:Reward)
    tp_by_rr = entry_p + (final_risk_dist * tactic_cfg.get("RR", 2.0) * pnl_multiplier)
    
    # 2. Lấy cấu hình trần TP
    max_tp_pct = RISK_RULES_CONFIG.get("MAX_TP_PERCENT_BY_TIMEFRAME", {}).get(interval)
    
    # 3. Mặc định TP cuối cùng bằng TP tính theo RR
    tp_p = tp_by_rr 

    if max_tp_pct is not None:
        # Tính giá trị TP trần
        tp_capped = entry_p * (1 + (max_tp_pct * pnl_multiplier))
        
        # 4. So sánh và chọn TP cuối cùng
        if trade_type == "LONG":
            if tp_by_rr > tp_capped:
                log_message(f"  -> 🛡️ TP: RR quá cao! Ép lợi nhuận về mức trần an toàn ({max_tp_pct:.2%}).")
                tp_p = tp_capped
        else: # SHORT
            if tp_by_rr < tp_capped:
                log_message(f"  -> 🛡️ TP: RR quá cao! Ép lợi nhuận về mức trần an toàn ({max_tp_pct:.2%}).")
                tp_p = tp_capped
    
    # --- Kiểm tra tính hợp lệ cuối cùng của SL/TP ---
    if (trade_type == "LONG" and (tp_p <= entry_p or sl_p >= entry_p or sl_p <= 0)) or \
       (trade_type == "SHORT" and (tp_p >= entry_p or sl_p <= entry_p)):
        log_message(f"⚠️ SL/TP không hợp lệ sau khi tính toán. SL: {sl_p:.4f}, TP: {tp_p:.4f}. Bỏ qua.")
        return

    new_trade = {
        "trade_id": str(uuid.uuid4()), "symbol": symbol, "interval": interval, "status": "ACTIVE",
        "opened_by_tactic": tactic_name, "trade_type": trade_type, "entry_price": entry_p,
        "tp": round(tp_p, 8), "sl": round(sl_p, 8), "initial_sl": round(sl_p, 8),
        "initial_risk_dist": final_risk_dist, # Lưu lại risk_dist cuối cùng
        "total_invested_usd": invested_amount,
        "initial_entry": {"price": entry_p, "invested_usd": invested_amount},
        "entry_time": now_vn.isoformat(), "entry_score": score,
        "dca_entries": [], "profit_taken": False, "trailing_sl": round(sl_p, 8),
        "tactic_used": [tactic_name],
        "peak_pnl_percent": 0.0,
        "realized_pnl_usd": 0.0
    }
    state["cash"] -= invested_amount
    state["active_trades"].append(new_trade)
    log_message(f"🔥 Lệnh Mới ({trade_type}): {symbol}-{interval} | Vốn: ${invested_amount:,.2f} | SL: {sl_p:.4f} | TP: {tp_p:.4f}")
    state.setdefault('temp_newly_opened_trades', []).append(f"🔥 {symbol}-{interval} ({tactic_name}): Vốn ${invested_amount:,.2f}")

# ==============================================================================
# BÁO CÁO & VÒNG LẶP CHÍNH
# ==============================================================================

def build_report_header(state: Dict, realtime_prices: Dict[str, float]) -> str:
    # <<< SỬA LỖI BÁO CÁO >>>: Sử dụng realtime_prices để tính toán
    total_equity = calculate_total_equity(state, realtime_prices=realtime_prices)
    cash = state.get('cash', INITIAL_CAPITAL)
    pnl_since_start = total_equity - INITIAL_CAPITAL
    pnl_percent = (pnl_since_start / INITIAL_CAPITAL) * 100 if INITIAL_CAPITAL > 0 else 0
    pnl_icon = "🟢" if pnl_since_start >= 0 else "🔴"
    return (
        f"💰 Vốn BĐ: **${INITIAL_CAPITAL:,.2f}** | 💵 Tiền mặt: **${cash:,.2f}**\n"
        f"📊 Tổng TS: **${total_equity:,.2f}** | 📈 PnL Tổng: {pnl_icon} **${pnl_since_start:,.2f} ({pnl_percent:+.2f}%)**"
    )

def build_trade_details_for_report(trade: Dict, realtime_price: float) -> str:
    # <<< SỬA LỖI BÁO CÁO >>>: Sử dụng realtime_price được truyền vào
    pnl_usd, pnl_pct = get_current_pnl(trade, realtime_price=realtime_price)
    icon = "🟢" if pnl_usd >= 0 else "🔴"
    holding_h = (datetime.now(VIETNAM_TZ) - datetime.fromisoformat(trade['entry_time'])).total_seconds() / 3600
    dca_info = f" (DCA: {len(trade.get('dca_entries',[]))})" if trade.get('dca_entries') else ""
    tactic_cfg = TACTICS_LAB.get(trade.get('opened_by_tactic'), {})
    tsl_info = f" TSL:{trade['trailing_sl']:.4f}" if tactic_cfg.get("USE_TRAILING_SL") and 'trailing_sl' in trade and trade['trailing_sl'] != trade['initial_sl'] else ""
    tp1_info = " TP1✅" if trade.get('profit_taken') else ""

    controlling_tactic_info = f" ({trade.get('controlling_tactic', trade['opened_by_tactic'])} | {trade.get('last_score', trade['entry_score']):.1f})"
    trade_type_str = f" [{trade.get('trade_type', 'LONG')}]"

    return (
        f"  {icon} **{trade['symbol']}-{trade['interval']}**{trade_type_str}{controlling_tactic_info} "
        f"PnL: **${pnl_usd:,.2f} ({pnl_pct:+.2f}%)** | Giữ:{holding_h:.1f}h{dca_info}{tp1_info}\n"
        f"    Entry:{trade['entry_price']:.4f} Cur:{realtime_price:.4f} SL:{trade['sl']:.4f} TP:{trade['tp']:.4f}{tsl_info} "
        f"Vốn:${trade.get('total_invested_usd', 0.0):,.2f}"
    )

def build_pnl_summary_line(state: Dict, realtime_prices: Dict[str, float]) -> str:
    # <<< SỬA LỖI BÁO CÁO >>>: Sử dụng realtime_prices để tính toán
    trade_history = state.get('trade_history', [])
    active_trades = state.get('active_trades', [])
    if not trade_history and not active_trades: return "Chưa có giao dịch."

    df_history = pd.DataFrame(trade_history) if trade_history else pd.DataFrame()

    total_trades = len(df_history)
    if total_trades > 0:
        winning_trades = len(df_history[df_history['pnl_usd'] > 0])
        win_rate_str = f"{winning_trades / total_trades * 100:.2f}% ({winning_trades}/{total_trades})"
    else:
        win_rate_str = "N/A (0 trades)"

    total_pnl_closed = df_history['pnl_usd'].sum() if total_trades > 0 else 0.0
    unrealized_pnl = sum(get_current_pnl(trade, realtime_price=realtime_prices.get(trade['symbol']))[0] for trade in active_trades)

    # Tính toán chính xác hơn PnL từ chốt lời một phần
    total_equity_pnl = calculate_total_equity(state, realtime_prices=realtime_prices) - INITIAL_CAPITAL
    realized_partial_pnl = total_equity_pnl - total_pnl_closed - unrealized_pnl

    unrealized_pnl_sign = '+' if unrealized_pnl >= 0 else ''
    return (
        f"🏆 Win Rate: **{win_rate_str}** | "
        f"✅ PnL Đóng: **${total_pnl_closed:,.2f}** | "
        f"💎 PnL TP1: **${realized_partial_pnl:,.2f}** | "
        f"📈 PnL Mở: **{unrealized_pnl_sign}${unrealized_pnl:,.2f}**"
    )

def build_report_text(state: Dict, realtime_prices: Dict[str, float], report_type: str) -> str:
    # <<< SỬA LỖI BÁO CÁO >>>: Hàm tạo báo cáo chung, sử dụng realtime_prices
    now_vn_str = datetime.now(VIETNAM_TZ).strftime('%H:%M %d-%m-%Y')
    title = f"📊 **BÁO CÁO TỔNG KẾT HÀNG NGÀY** - `{now_vn_str}` 📊" if report_type == "daily" else f"💡 **CẬP NHẬT ĐỘNG** - `{now_vn_str}` 💡"

    lines = [title, ""]
    lines.append(build_report_header(state, realtime_prices))
    lines.append("\n" + build_pnl_summary_line(state, realtime_prices))

    if report_type == "daily":
        lines.append("\n--- **Chi tiết trong phiên** ---")
        lines.append(f"✨ Lệnh mới mở: {len(state.get('temp_newly_opened_trades', []))}")
        if state.get('temp_newly_opened_trades'): lines.extend([f"    - {msg}" for msg in state['temp_newly_opened_trades']])
        lines.append(f"⛔ Lệnh đã đóng/chốt lời: {len(state.get('temp_newly_closed_trades', []))}")
        if state.get('temp_newly_closed_trades'): lines.extend([f"    - {msg}" for msg in state['temp_newly_closed_trades']])

    active_trades = state.get('active_trades', [])
    lines.append("\n--- **Vị thế đang mở** ---")
    lines.append(f"💼 Tổng vị thế đang mở: **{len(active_trades)}**")
    if not active_trades: lines.append("    (Không có vị thế nào)")
    else:
        for trade in sorted(active_trades, key=lambda x: x['entry_time']):
            current_price = realtime_prices.get(trade["symbol"])
            if current_price:
                lines.append(build_trade_details_for_report(trade, current_price))
            else:
                lines.append(f"⚠️ {trade['symbol']} - Không có dữ liệu giá real-time.")

    if report_type == "daily":
        lines.append("\n--- **Lịch sử giao dịch gần nhất** ---")
        trade_history = state.get('trade_history', [])
        if trade_history:
            df_history = pd.DataFrame(trade_history)
            if 'exit_time' in df_history.columns and not df_history['exit_time'].isnull().all():
                df_history['exit_time_dt'] = pd.to_datetime(df_history['exit_time'])
                recent_trades = df_history.sort_values(by='exit_time_dt', ascending=False).head(5)
                for _, trade in recent_trades.iterrows():
                    icon = '✅' if trade.get('pnl_usd', 0) > 0 else '❌'
                    lines.append(f"  {icon} {trade['symbol']} | PnL: `${trade.get('pnl_usd', 0):.2f}` | {trade.get('status', 'N/A')}")
            else:
                lines.append(" (Lịch sử giao dịch chưa có thời gian đóng lệnh để sắp xếp.)")
        else:
            lines.append("  (Chưa có lịch sử giao dịch)")

    lines.append("\n====================================")
    return "\n".join(lines)


def should_send_dynamic_alert(state: Dict, realtime_prices: Dict[str, float]) -> bool:
    if not DYNAMIC_ALERT_CONFIG["ENABLED"]: return False
    now = datetime.now(VIETNAM_TZ)
    last_alert = state.get('last_dynamic_alert', {})
    if not last_alert.get('timestamp'): return bool(state.get('active_trades'))

    last_alert_dt = datetime.fromisoformat(last_alert.get('timestamp')).astimezone(VIETNAM_TZ)
    hours_since = (now - last_alert_dt).total_seconds() / 3600

    if hours_since >= DYNAMIC_ALERT_CONFIG["FORCE_UPDATE_HOURS"]: return True
    if hours_since < DYNAMIC_ALERT_CONFIG["COOLDOWN_HOURS"]: return False

    current_equity = calculate_total_equity(state, realtime_prices=realtime_prices)
    current_pnl_pct = ((current_equity - INITIAL_CAPITAL) / INITIAL_CAPITAL) * 100 if INITIAL_CAPITAL > 0 else 0
    pnl_change = abs(current_pnl_pct - last_alert.get('total_pnl_percent', 0.0))

    return pnl_change >= DYNAMIC_ALERT_CONFIG["PNL_CHANGE_THRESHOLD_PCT"]

def run_session():
    session_id = datetime.now(VIETNAM_TZ).strftime('%Y%m%d_%H%M%S')
    log_message(f"====== 🚀 BẮT ĐẦU PHIÊN (v4.5.1) (ID: {session_id}) 🚀 ======")
    try:
        state = load_json_file(STATE_FILE, {
            "cash": INITIAL_CAPITAL, "active_trades": [], "trade_history": [],
            "last_dynamic_alert": {}, "last_daily_reports_sent": {}, "cooldown_until": {}
        })
        state['temp_newly_opened_trades'] = []
        state['temp_newly_closed_trades'] = []

        log_message("⏳ Đang tải và tính toán indicators...")
        indicator_results.clear()
        price_dataframes.clear()
        symbols_to_load = list(set(SYMBOLS_TO_SCAN + [t['symbol'] for t in state.get('active_trades', [])] + ["BTCUSDT"]))

        for symbol in symbols_to_load:
            indicator_results[symbol] = {}
            price_dataframes[symbol] = {}
            for interval in ALL_TIME_FRAMES:
                df = get_price_data_with_cache(symbol, interval, GENERAL_CONFIG["DATA_FETCH_LIMIT"])
                if df is not None:
                    indicator_results[symbol][interval] = calculate_indicators(df, symbol, interval)
                    price_dataframes[symbol][interval] = df
        log_message("✅ Đã tải xong indicators.")

        manage_active_trades(state)

        all_closed_in_session = handle_trade_closure(state) + handle_stale_trades(state)
        if all_closed_in_session:
            export_trade_history_to_csv(all_closed_in_session)

        # Equity tính bằng giá đóng nến cho logic DCA và mở lệnh mới
        equity_for_logic = calculate_total_equity(state)
        handle_dca_opportunities(state, equity_for_logic)
        find_and_open_new_trades(state, equity_for_logic)

        # --- BẮT ĐẦU KHỐI BÁO CÁO ---
        # <<< SỬA LỖI BÁO CÁO >>>: Lấy giá real-time CHỈ DÀNH CHO VIỆC BÁO CÁO
        active_symbols_for_report = [t['symbol'] for t in state.get('active_trades', [])]
        realtime_prices_for_report = {sym: get_realtime_price(sym) for sym in active_symbols_for_report}

        now_vn = datetime.now(VIETNAM_TZ)
        cron_interval_minutes = GENERAL_CONFIG.get("CRON_JOB_INTERVAL_MINUTES", 15)
        for daily_time_str in GENERAL_CONFIG["DAILY_SUMMARY_TIMES"]:
            h, m = map(int, daily_time_str.split(':'))
            report_time_today = now_vn.replace(hour=h, minute=m, second=0, microsecond=0)

            last_sent_iso = state.get('last_daily_reports_sent', {}).get(daily_time_str)
            sent_today = last_sent_iso and datetime.fromisoformat(last_sent_iso).date() == now_vn.date()

            time_since_report = (now_vn - report_time_today).total_seconds()
            if not sent_today and 0 <= time_since_report < cron_interval_minutes * 60:
                log_message(f"🔔 Gửi báo cáo hàng ngày cho khung giờ {daily_time_str}.")
                report_content = build_report_text(state, realtime_prices_for_report, "daily")
                send_discord_message_chunks(report_content)
                state.setdefault('last_daily_reports_sent', {})[daily_time_str] = now_vn.isoformat()

        if should_send_dynamic_alert(state, realtime_prices_for_report):
            log_message("🔔 Gửi alert động.")
            report_content = build_report_text(state, realtime_prices_for_report, "dynamic")
            send_discord_message_chunks(report_content)

            # Cập nhật PnL cuối cùng bằng giá real-time
            equity_for_alert = calculate_total_equity(state, realtime_prices=realtime_prices_for_report)
            pnl_percent_for_alert = ((equity_for_alert - INITIAL_CAPITAL) / INITIAL_CAPITAL) * 100 if INITIAL_CAPITAL > 0 else 0

            state['last_dynamic_alert'] = {
                "timestamp": now_vn.isoformat(),
                "total_pnl_percent": pnl_percent_for_alert
            }

        save_json_file(STATE_FILE, state)
    except Exception:
        error_details = traceback.format_exc()
        log_message(f"!!!!!! ❌ LỖI NGHIÊM TRỌNG ❌ !!!!!!\n{error_details}")
        send_discord_message_chunks(f"🔥🔥🔥 BOT GẶP LỖI NGHIÊM TRỌNG 🔥🔥🔥\n```python\n{error_details}\n```")
    log_message(f"====== ✅ KẾT THÚC PHIÊN (ID: {session_id}) ✅ ======\n")

if __name__ == "__main__":
    run_session()
