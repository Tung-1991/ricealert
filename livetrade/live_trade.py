# live_trade.py
# -*- coding: utf-8 -*-
"""
Live Trade - The 4-Zone Strategy
Version: 8.0.0 - Major Upgrade
Date: 2025-08-07

Description:
Phiên bản 8.0.0 là một bản nâng cấp lớn, tái cấu trúc hoàn toàn triết lý giao dịch
cốt lõi sang mô hình "4 Vùng Phản Ứng" (4-Zone Strategy). Bot giờ đây có khả năng
phân tích bối cảnh thị trường sâu hơn, chọn chiến thuật chuyên dụng cho từng Vùng,
và phân bổ vốn một cách linh hoạt, thông minh hơn.

CHANGELOG (v8.0.0):
- STRATEGY CORE: Triển khai "4-Zone Strategy" (LEADING, COINCIDENT, LAGGING, NOISE).
    - Thêm hàm `determine_market_zone_with_scoring` sử dụng hệ thống chấm điểm đa chỉ báo
      để xác định Vùng thị trường một cách đáng tin cậy.
    - Loại bỏ hoàn toàn `STATE_TO_TACTICS_MAP` và hàm `determine_market_state` cũ.
- TACTICS LAB: Tái cấu trúc `TACTICS_LAB`. Mỗi chiến thuật giờ đây có một `OPTIMAL_ZONE`
  được chỉ định, biến chúng thành các "vũ khí chuyên dụng" cho từng loại địa hình.
- CAPITAL MANAGEMENT: Triển khai chính sách vốn động theo Vùng (`ZONE_BASED_POLICIES`).
  Bot sẽ tự động điều chỉnh lượng vốn vào lệnh dựa trên mức độ rủi ro và xác suất
  thành công của từng Vùng (ví dụ: vốn nhỏ cho LEADING, vốn lớn cho LAGGING).
- BACKWARD COMPATIBILITY: Giữ lại toàn bộ các tính năng cốt lõi và ổn định của v7.5.3
  (DCA Hotfix, 3-Layer Defense, Stale Trade, Reporting, etc.).
- ROBUSTNESS: Logic tìm kiếm lệnh mới (`find_and_open_new_trades`) được làm gọn và
  trở nên tường minh, dễ bảo trì hơn.

RESULT: Một phiên bản thông minh hơn, có triết lý giao dịch rõ ràng, khả năng thích ứng
cao với từng giai đoạn của thị trường, và quản lý rủi ro/vốn hiệu quả hơn.
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
    from indicator import get_price_data, calculate_indicators
    from trade_advisor import get_advisor_decision, FULL_CONFIG as ADVISOR_BASE_CONFIG
except ImportError as e:
    sys.exit(f"Lỗi: Không thể import module cần thiết: {e}.")

LIVE_DATA_DIR = os.path.join(PROJECT_ROOT, "livetrade", "data")
os.makedirs(LIVE_DATA_DIR, exist_ok=True)
CACHE_DIR = os.path.join(LIVE_DATA_DIR, "indicator_cache")
os.makedirs(CACHE_DIR, exist_ok=True)

# ==============================================================================
# ================== ⚙️ TRUNG TÂM CẤU HÌNH (v8.0.0) ⚙️ ===================
# ==============================================================================
TRADING_MODE: Literal["live", "testnet"] = "testnet"
INITIAL_CAPITAL = 0.0

GENERAL_CONFIG = {
    "DATA_FETCH_LIMIT": 300,
    "DAILY_SUMMARY_TIMES": ["08:05", "20:05"],
    "TRADE_COOLDOWN_HOURS": 1,
    "CRON_JOB_INTERVAL_MINUTES": 1,
    "HEAVY_REFRESH_MINUTES": 15
}

MTF_ANALYSIS_CONFIG = {
    "ENABLED": True,
    "BONUS_COEFFICIENT": 1.15,
    "PENALTY_COEFFICIENT": 0.85,
    "SEVERE_PENALTY_COEFFICIENT": 0.70,
    "SIDEWAYS_PENALTY_COEFFICIENT": 0.90
}

ACTIVE_TRADE_MANAGEMENT_CONFIG = {
    "EARLY_CLOSE_ABSOLUTE_THRESHOLD": 4.8,
    "EARLY_CLOSE_RELATIVE_DROP_PCT": 0.27,
    "PARTIAL_EARLY_CLOSE_PCT": 0.5,
    "PROFIT_PROTECTION": {
        "ENABLED": True,
        "MIN_PEAK_PNL_TRIGGER": 3.5,
        "PNL_DROP_TRIGGER_PCT": 2.0,
        "PARTIAL_CLOSE_PCT": 0.7
    }
}

DYNAMIC_ALERT_CONFIG = {
    "ENABLED": True,
    "COOLDOWN_HOURS": 3,
    "FORCE_UPDATE_HOURS": 10,
    "PNL_CHANGE_THRESHOLD_PCT": 2.0
}

RISK_RULES_CONFIG = {
    "MAX_ACTIVE_TRADES": 12,
    "MAX_SL_PERCENT_BY_TIMEFRAME": {"1h": 0.06, "4h": 0.08, "1d": 0.10},
    "MAX_TP_PERCENT_BY_TIMEFRAME": {"1h": 0.12, "4h": 0.20, "1d": 0.35},
    "STALE_TRADE_RULES": {
        "1h": {"HOURS": 48, "PROGRESS_THRESHOLD_PCT": 25.0},
        "4h": {"HOURS": 72, "PROGRESS_THRESHOLD_PCT": 25.0},
        "1d": {"HOURS": 168, "PROGRESS_THRESHOLD_PCT": 20.0},
        "STAY_OF_EXECUTION_SCORE": 6.8
    }
}

CAPITAL_MANAGEMENT_CONFIG = {
    "MAX_TOTAL_EXPOSURE_PCT": 0.75
}

DCA_CONFIG = {
    "ENABLED": True,
    "MAX_DCA_ENTRIES": 2,
    "TRIGGER_DROP_PCT": -5.0,
    "SCORE_MIN_THRESHOLD": 6.5,
    "CAPITAL_MULTIPLIER": 0.75,
    "DCA_COOLDOWN_HOURS": 8
}

ALERT_CONFIG = {
    "DISCORD_WEBHOOK_URL": os.getenv("DISCORD_LIVE_WEBHOOK"),
    "DISCORD_CHUNK_DELAY_SECONDS": 2
}

# ==============================================================================
# ================= 🚀 CORE STRATEGY v8.0.0: 4-ZONE MODEL 🚀 =================
# ==============================================================================

# --- Định nghĩa 4 Vùng Phản Ứng ---
LEADING_ZONE = "LEADING"         # Tín hiệu sớm, rủi ro cao, tiềm năng lớn (Breakout Squeeze, RSI Dip)
COINCIDENT_ZONE = "COINCIDENT"   # Tín hiệu đồng thời, "điểm ngọt" (Breakout + Vol, MACD Cross)
LAGGING_ZONE = "LAGGING"         # Tín hiệu trễ, an toàn, theo trend đã rõ (ADX > 25, MA stacking)
NOISE_ZONE = "NOISE"             # Vùng nhiễu, không có xu hướng (ADX < 20, giá đi ngang)
# Thêm dòng này
ZONES = [LEADING_ZONE, COINCIDENT_ZONE, LAGGING_ZONE, NOISE_ZONE]

# --- Chính sách Vốn & Rủi ro theo từng Vùng ---
ZONE_BASED_POLICIES = {
    LEADING_ZONE: {
        "NOTES": "Vốn nhỏ để 'dò mìn' cơ hội tiềm năng, chốt lời sớm để bảo toàn vốn.",
        "CAPITAL_PCT": 0.04 # Vốn NHỎ
    },
    COINCIDENT_ZONE: {
        "NOTES": "Vùng tốt nhất, quyết đoán vào lệnh với lượng vốn vừa phải.",
        "CAPITAL_PCT": 0.07 # Vốn LỚN
    },
    LAGGING_ZONE: {
        "NOTES": "An toàn, đi theo trend đã rõ, tối ưu hóa lợi nhuận trên con sóng.",
        "CAPITAL_PCT": 0.06 # Vốn VỪA
    },
    NOISE_ZONE: {
        "NOTES": "Cực kỳ nguy hiểm, chỉ vào lệnh với vốn siêu nhỏ khi có tín hiệu VÀNG.",
        "CAPITAL_PCT": 0.03 # Vốn SIÊU NHỎ
    }
}

# --- Phòng thí nghiệm Chiến thuật (Tactics Lab), tái cấu trúc theo 4 Vùng ---
TACTICS_LAB = {
    "Breakout_Hunter": {
        "OPTIMAL_ZONE": [LEADING_ZONE, COINCIDENT_ZONE],
        "NOTES": "Săn đột phá từ nền giá siết chặt. SL chặt, chốt lời TP1 sớm.",
        "WEIGHTS": {'tech': 0.7, 'context': 0.1, 'ai': 0.2}, "ENTRY_SCORE": 7.0, "RR": 2.5,
        "ATR_SL_MULTIPLIER": 1.8, "USE_TRAILING_SL": True, "TRAIL_ACTIVATION_RR": 1.0,
        "TRAIL_DISTANCE_RR": 0.8, "ENABLE_PARTIAL_TP": True, "TP1_RR_RATIO": 1.0, "TP1_PROFIT_PCT": 0.5
    },
    "Dip_Hunter": {
        "OPTIMAL_ZONE": [LEADING_ZONE, COINCIDENT_ZONE],
        "NOTES": "Bắt đáy/sóng hồi trong trend lớn. Không dùng TSL để tránh bị quét.",
        "WEIGHTS": {'tech': 0.6, 'context': 0.2, 'ai': 0.2}, "ENTRY_SCORE": 6.8, "RR": 2.2,
        "ATR_SL_MULTIPLIER": 2.0, "USE_TRAILING_SL": False, "TRAIL_ACTIVATION_RR": None,
        "ENABLE_PARTIAL_TP": True, "TP1_RR_RATIO": 0.8, "TP1_PROFIT_PCT": 0.6
    },
    "AI_Aggressor": {
        "OPTIMAL_ZONE": COINCIDENT_ZONE,
        "NOTES": "Tin vào AI khi có xác nhận mạnh mẽ từ hành động giá và volume.",
        "WEIGHTS": {'tech': 0.3, 'context': 0.1, 'ai': 0.6}, "ENTRY_SCORE": 7.2, "RR": 2.2,
        "ATR_SL_MULTIPLIER": 2.5, "USE_TRAILING_SL": True, "TRAIL_ACTIVATION_RR": 1.2,
        "TRAIL_DISTANCE_RR": 0.8, "ENABLE_PARTIAL_TP": True, "TP1_RR_RATIO": 1.0, "TP1_PROFIT_PCT": 0.5
    },
    "Balanced_Trader": {
        "OPTIMAL_ZONE": LAGGING_ZONE,
        "NOTES": "Chiến binh chủ lực, đi theo xu hướng đã rõ ràng, ưu tiên gồng lời.",
        "WEIGHTS": {'tech': 0.4, 'context': 0.2, 'ai': 0.4}, "ENTRY_SCORE": 6.5, "RR": 1.8,
        "ATR_SL_MULTIPLIER": 2.8, "USE_TRAILING_SL": True, "TRAIL_ACTIVATION_RR": 1.2,
        "TRAIL_DISTANCE_RR": 1.0, "ENABLE_PARTIAL_TP": True, "TP1_RR_RATIO": 1.2, "TP1_PROFIT_PCT": 0.5
    },
    "Cautious_Observer": {
        "OPTIMAL_ZONE": NOISE_ZONE,
        "NOTES": "Chỉ đánh khi có cơ hội VÀNG trong vùng nhiễu, siêu an toàn.",
        "WEIGHTS": {'tech': 0.7, 'context': 0.2, 'ai': 0.1}, "ENTRY_SCORE": 8.0, "RR": 1.5,
        "ATR_SL_MULTIPLIER": 1.5, "USE_TRAILING_SL": True, "TRAIL_ACTIVATION_RR": 0.7,
        "TRAIL_DISTANCE_RR": 0.5, "ENABLE_PARTIAL_TP": True, "TP1_RR_RATIO": 0.8, "TP1_PROFIT_PCT": 0.5
    },
}

# ==============================================================================
# BIẾN TOÀN CỤC & HẰNG SỐ
# ==============================================================================
SYMBOLS_TO_SCAN_STRING = os.getenv("SYMBOLS_TO_SCAN", "ETHUSDT,BTCUSDT")
SYMBOLS_TO_SCAN = [symbol.strip() for symbol in SYMBOLS_TO_SCAN_STRING.split(',')]
INTERVALS_TO_SCAN = ["1h", "4h", "1d"]
ALL_TIME_FRAMES = ["1h", "4h", "1d"]
VIETNAM_TZ = pytz.timezone('Asia/Ho_Chi_Minh')
LOG_FILE = os.path.join(LIVE_DATA_DIR, "live_trade_log.txt")
STATE_FILE = os.path.join(LIVE_DATA_DIR, "live_trade_state.json")
TRADE_HISTORY_CSV_FILE = os.path.join(LIVE_DATA_DIR, "live_trade_history.csv")
indicator_results: Dict[str, Any] = {}
price_dataframes: Dict[str, Any] = {}
SESSION_TEMP_KEYS = ['temp_newly_opened_trades', 'temp_newly_closed_trades', 'temp_money_spent_on_trades', 'temp_pnl_from_closed_trades']

# ==============================================================================
# HÀM TIỆN ÍCH
# ==============================================================================
def log_message(message: str):
    timestamp = datetime.now(VIETNAM_TZ).strftime('%Y-%m-%d %H:%M:%S')
    log_entry = f"[{timestamp}] (LiveTrade) {message}"
    print(log_entry)
    with open(LOG_FILE, "a", encoding="utf-8") as f: f.write(log_entry + "\n")

def load_json_file(path: str, default: Any = None) -> Any:
    if not os.path.exists(path): return default if default is not None else {}
    try:
        with open(path, "r", encoding="utf-8") as f: return json.load(f)
    except json.JSONDecodeError:
        log_message(f"⚠️ Cảnh báo: File {path} bị hỏng. Sử dụng giá trị mặc định.")
        return default if default is not None else {}

def save_json_file(path: str, data: Any):
    temp_path = path + ".tmp"
    data_to_save = data.copy()
    for key in SESSION_TEMP_KEYS:
        data_to_save.pop(key, None)
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(data_to_save, f, indent=4, ensure_ascii=False)
    os.replace(temp_path, path)

_last_discord_send_time = None
def can_send_discord_now(force: bool = False) -> bool:
    global _last_discord_send_time
    if force: return True
    now = datetime.now()
    if _last_discord_send_time is None or (now - _last_discord_send_time).total_seconds() > (GENERAL_CONFIG["HEAVY_REFRESH_MINUTES"] * 60):
        _last_discord_send_time = now
        return True
    return False

def send_discord_message_chunks(full_content: str, force: bool = False):
    if not can_send_discord_now(force):
        log_message("🤫 Bỏ qua gửi Discord do đang trong thời gian cooldown.")
        return
    webhook_url = ALERT_CONFIG.get("DISCORD_WEBHOOK_URL")
    if not webhook_url: return
    max_len = 1900; lines = full_content.split('\n'); chunks, current_chunk = [], ""
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
            log_message(f"❌ Lỗi gửi chunk Discord {i+1}/{len(chunks)}: {e}"); break

def get_realtime_price(symbol: str) -> Optional[float]:
    if symbol == "USDT": return 1.0
    url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
    try:
        response = requests.get(url, timeout=3)
        response.raise_for_status()
        return float(response.json()['price'])
    except Exception: return None

def get_current_pnl(trade: Dict, realtime_price: Optional[float] = None) -> Tuple[float, float]:
    if not (trade and trade.get('entry_price', 0) > 0 and realtime_price and realtime_price > 0): return 0.0, 0.0
    pnl_multiplier = 1.0 if trade.get('trade_type', 'LONG') == 'LONG' else -1.0
    pnl_percent = (realtime_price - trade['entry_price']) / trade['entry_price'] * 100 * pnl_multiplier
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
        cols = ["trade_id", "symbol", "interval", "status", "opened_by_tactic", "tactic_used", "trade_type", "entry_price", "exit_price", "tp", "sl", "total_invested_usd", "pnl_usd", "pnl_percent", "entry_time", "exit_time", "holding_duration_hours", "entry_score", "dca_entries"]
        df = df[[c for c in cols if c in df.columns]]
        header_mismatch = False
        if os.path.exists(TRADE_HISTORY_CSV_FILE):
            try:
                if set(pd.read_csv(TRADE_HISTORY_CSV_FILE, nrows=0).columns.tolist()) != set(df.columns.tolist()): header_mismatch = True
            except Exception: header_mismatch = True
        df.to_csv(TRADE_HISTORY_CSV_FILE, mode='a' if os.path.exists(TRADE_HISTORY_CSV_FILE) and not header_mismatch else 'w', header=not os.path.exists(TRADE_HISTORY_CSV_FILE) or header_mismatch, index=False, encoding="utf-8")
        log_message(f"✅ Đã xuất {len(df)} lệnh đã đóng vào {TRADE_HISTORY_CSV_FILE}")
    except Exception as e: log_message(f"❌ Lỗi khi xuất lịch sử giao dịch ra CSV: {e}")

def get_usdt_fund(bnc: BinanceConnector) -> Tuple[float, float]:
    try:
        balance_info = bnc.get_account_balance()
        usdt_balance = next((b for b in balance_info.get("balances", []) if b["asset"] == "USDT"), None)
        if usdt_balance:
            available_usdt = float(usdt_balance['free'])
            total_usdt = float(usdt_balance['free']) + float(usdt_balance['locked'])
            return available_usdt, total_usdt
    except Exception as e: log_message(f"❌ Không thể lấy số dư USDT từ Binance: {e}")
    return 0.0, 0.0

def get_interval_in_milliseconds(interval: str) -> Optional[int]:
    try:
        unit = interval[-1]; value = int(interval[:-1])
        if unit == 'm': return value * 60 * 1000
        if unit == 'h': return value * 3600 * 1000
        if unit == 'd': return value * 86400 * 1000
    except (ValueError, IndexError): return None
    return None

def get_price_data_with_cache(symbol: str, interval: str, limit: int) -> Optional[pd.DataFrame]:
    cache_filepath = os.path.join(CACHE_DIR, f"{symbol}-{interval}.parquet")
    existing_df = None
    if os.path.exists(cache_filepath):
        try: existing_df = pd.read_parquet(cache_filepath)
        except Exception as e: log_message(f"⚠️ Lỗi đọc file cache {cache_filepath}: {e}. Sẽ tải lại.")
    if existing_df is not None and not existing_df.empty:
        last_ts = int(existing_df.index[-1].timestamp() * 1000)
        interval_ms = get_interval_in_milliseconds(interval)
        if not interval_ms: return existing_df
        start_time = last_ts + interval_ms
        if int(datetime.now(timezone.utc).timestamp() * 1000) > start_time:
            new_data = get_price_data(symbol, interval, limit=limit, startTime=start_time)
            if new_data is not None and not new_data.empty:
                combined = pd.concat([existing_df, new_data])
                combined = combined[~combined.index.duplicated(keep='last')]
            else: combined = existing_df
        else: combined = existing_df
        final_df = combined.tail(limit).copy()
    else: final_df = get_price_data(symbol, interval, limit=limit)
    if final_df is not None and not final_df.empty:
        try:
            for col in final_df.select_dtypes(include=['float64']).columns:
                if col != 'close': final_df[col] = final_df[col].astype('float32')
            final_df.to_parquet(cache_filepath)
        except Exception as e: log_message(f"❌ Lỗi lưu file cache {cache_filepath}: {e}")
        return final_df
    return existing_df if existing_df is not None else None

# ==============================================================================
# LOGIC GIAO DỊCH CỐT LÕI
# ==============================================================================
def close_trade_on_binance(bnc: BinanceConnector, trade: Dict, reason: str, state: Dict, close_pct: float = 1.0) -> bool:
    symbol = trade['symbol']
    log_message(f"🎬 Đóng {close_pct*100:.0f}% lệnh {symbol} vì: {reason}")
    market_close_order = None
    side = "SELL" if trade['trade_type'] == 'LONG' else "BUY"
    original_quantity_to_close = float(trade['quantity']) * close_pct
    if original_quantity_to_close <= 0:
        log_message(f"⚠️ Số lượng đóng lệnh cho {symbol} quá nhỏ, không thể thực hiện.")
        return False
    try:
        log_message(f"   -> Kế hoạch A: Đóng {original_quantity_to_close:.8f} {symbol}")
        market_close_order = bnc.place_market_order(symbol=symbol, side=side, quantity=original_quantity_to_close)
    except Exception as e:
        error_string = str(e).lower()
        if "-2010" in error_string or "insufficient balance" in error_string:
            log_message(f"   -> ⚠️ Kế hoạch A thất bại do không đủ số dư. Thử Kế hoạch B...")
            try:
                balances = bnc.get_account_balance().get('balances', [])
                asset_to_sell = symbol.replace("USDT", "")
                asset_balance = next((b for b in balances if b['asset'] == asset_to_sell), None)
                if asset_balance and float(asset_balance['free']) > 0:
                    fallback_quantity = float(asset_balance['free'])
                    log_message(f"   -> Kế hoạch B: Bán toàn bộ số dư còn lại: {fallback_quantity:.8f} {asset_to_sell}")
                    market_close_order = bnc.place_market_order(symbol=symbol, side=side, quantity=fallback_quantity)
                else:
                    log_message(f"   -> ❌ Kế hoạch B thất bại: Không còn {asset_to_sell} trong ví. Coi như đã đóng.")
                    trade.update({
                        'status': f'Closed (Zero Balance)', 'exit_price': trade['entry_price'],
                        'pnl_usd': -trade['total_invested_usd'], 'exit_time': datetime.now(VIETNAM_TZ).isoformat()
                    })
                    state['active_trades'] = [t for t in state['active_trades'] if t['trade_id'] != trade['trade_id']]
                    state['trade_history'].append(trade)
                    export_trade_history_to_csv([trade])
                    return True
            except Exception as fallback_e: log_message(f"   -> ❌ Kế hoạch B cũng thất bại: {fallback_e}")
        else:
            log_message(f"🔥🔥🔥 LỖI NGHIÊM TRỌNG KHI ĐÓNG VỊ THẾ {symbol}. Lỗi: {e}")
            now = datetime.now(VIETNAM_TZ)
            error_cooldown_map = state.get('error_cooldown_until', {})
            if symbol in error_cooldown_map and now < datetime.fromisoformat(error_cooldown_map[symbol]): return False
            send_discord_message_chunks(f"🔥🔥🔥 LỖI ĐÓNG LỆNH NGHIÊM TRỌNG 🔥🔥🔥\nKhông thể đóng vị thế `{symbol}`. **CẦN CAN THIỆP THỦ CÔNG NGAY!**")
            cooldown_end = now + timedelta(minutes=15)
            state.setdefault('error_cooldown_until', {})[symbol] = cooldown_end.isoformat()
            return False
    if not (market_close_order and float(market_close_order.get('executedQty', 0)) > 0):
        log_message(f"   -> ❌ Đóng lệnh {symbol} không thành công sau tất cả các nỗ lực.")
        return False
    closed_qty = float(market_close_order['executedQty'])
    exit_price = float(market_close_order['cummulativeQuoteQty']) / closed_qty
    pnl_usd = (exit_price - trade['entry_price']) * closed_qty * (1 if trade['trade_type'] == 'LONG' else -1)
    state['temp_pnl_from_closed_trades'] += pnl_usd
    if close_pct >= 0.999:
        pnl_percent = (exit_price - trade['entry_price']) / trade['entry_price'] * 100 * (1 if trade['trade_type'] == 'LONG' else -1)
        trade.update({
            'status': f'Closed ({reason})', 'exit_price': exit_price, 'exit_time': datetime.now(VIETNAM_TZ).isoformat(),
            'pnl_usd': trade.get('realized_pnl_usd', 0.0) + pnl_usd, 'pnl_percent': pnl_percent
        })
        state['active_trades'] = [t for t in state['active_trades'] if t['trade_id'] != trade['trade_id']]
        state['trade_history'].append(trade)
        cooldown_end = datetime.now(VIETNAM_TZ) + timedelta(hours=GENERAL_CONFIG["TRADE_COOLDOWN_HOURS"])
        state.setdefault('cooldown_until', {})[symbol] = cooldown_end.isoformat()
        export_trade_history_to_csv([trade])
        icon = '✅' if pnl_usd >= 0 else '❌'
        msg = f"{icon} {symbol} (Đóng toàn bộ - {reason}): PnL ${pnl_usd:,.2f}"
        state.setdefault('temp_newly_closed_trades', []).append(msg)
        log_message(f" -> ✅ Đóng toàn bộ {symbol} thành công. PnL: ${pnl_usd:,.2f}")
    else:
        trade['realized_pnl_usd'] = trade.get('realized_pnl_usd', 0.0) + pnl_usd
        trade['total_invested_usd'] *= (1 - close_pct)
        trade['quantity'] -= closed_qty
        trade.setdefault('tactic_used', []).append(f"Partial_Close_{reason}")
        icon = '💰'
        msg = f"{icon} {symbol} (Đóng {close_pct*100:.0f}% - {reason}): PnL ${pnl_usd:,.2f}"
        state.setdefault('temp_newly_closed_trades', []).append(msg)
        log_message(f" -> ✅ Đóng {close_pct*100:.0f}% lệnh {symbol} thành công. PnL đã chốt: ${pnl_usd:,.2f}")
    return True

def check_and_manage_open_positions(bnc: BinanceConnector, state: Dict, realtime_prices: Dict[str, float]):
    active_trades = state.get("active_trades", [])[:]
    if not active_trades: return
    log_message(f"🧠 Quản lý {len(active_trades)} vị thế mở...")
    for trade in active_trades:
        symbol, tactic_name = trade['symbol'], trade.get('opened_by_tactic')
        tactic_cfg = TACTICS_LAB.get(tactic_name, {})
        current_price = realtime_prices.get(symbol)
        if not current_price: continue
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
            drop_pct_config = ACTIVE_TRADE_MANAGEMENT_CONFIG.get('EARLY_CLOSE_RELATIVE_DROP_PCT', 0.35)
            if last_score < entry_score * (1 - drop_pct_config):
                close_pct = ACTIVE_TRADE_MANAGEMENT_CONFIG.get("PARTIAL_EARLY_CLOSE_PCT", 0.5)
                if close_trade_on_binance(bnc, trade, f"EC_Rel_{last_score:.1f}", state, close_pct=close_pct):
                    trade['partial_closed_by_score'] = True
                    trade['sl'] = trade['entry_price']
        _, pnl_percent = get_current_pnl(trade, realtime_price=current_price)
        trade['peak_pnl_percent'] = max(trade.get('peak_pnl_percent', 0.0), pnl_percent)
        initial_risk_dist = abs(trade['initial_entry']['price'] - trade['initial_sl'])
        if tactic_cfg.get("ENABLE_PARTIAL_TP", False) and not trade.get("tp1_hit", False) and initial_risk_dist > 0:
            pnl_ratio = (current_price - trade['entry_price']) / initial_risk_dist * (1 if trade['trade_type'] == 'LONG' else -1)
            tp1_rr_ratio = tactic_cfg.get("TP1_RR_RATIO", 1.0)
            if pnl_ratio >= tp1_rr_ratio:
                close_pct = tactic_cfg.get("TP1_PROFIT_PCT", 0.5)
                if close_trade_on_binance(bnc, trade, f"TP1_{tp1_rr_ratio:.1f}R", state, close_pct=close_pct):
                    trade['tp1_hit'] = True
                    trade['sl'] = trade['entry_price']
        pp_config = ACTIVE_TRADE_MANAGEMENT_CONFIG.get("PROFIT_PROTECTION", {})
        if pp_config.get("ENABLED", False) and not trade.get('profit_taken', False) and trade['peak_pnl_percent'] >= pp_config.get("MIN_PEAK_PNL_TRIGGER", 3.5):
            if (trade['peak_pnl_percent'] - pnl_percent) >= pp_config.get("PNL_DROP_TRIGGER_PCT", 2.0):
                close_pct = pp_config.get("PARTIAL_CLOSE_PCT", 0.7)
                if close_trade_on_binance(bnc, trade, "Protect_Profit", state, close_pct=close_pct):
                    trade['profit_taken'] = True
                    trade['sl'] = trade['entry_price']
        if tactic_cfg.get("USE_TRAILING_SL", False) and initial_risk_dist > 0:
            pnl_ratio_from_entry = (current_price - trade['entry_price']) / initial_risk_dist * (1 if trade['trade_type'] == 'LONG' else -1)
            trail_activation_rr = tactic_cfg.get("TRAIL_ACTIVATION_RR")
            if trail_activation_rr is not None and pnl_ratio_from_entry >= trail_activation_rr:
                trail_dist_rr = tactic_cfg.get("TRAIL_DISTANCE_RR", 0.8)
                new_sl = current_price - (initial_risk_dist * trail_dist_rr * (1 if trade['trade_type'] == 'LONG' else -1))
                if (new_sl > trade['sl']) if trade['trade_type'] == 'LONG' else (new_sl < trade['sl']):
                    log_message(f"📈 TRAILING SL cho {symbol}: SL mới: {new_sl:.4f} (cũ: {trade['sl']:.4f})")
                    trade['sl'] = new_sl
                    if "Trailing_SL_Active" not in trade.get('tactic_used', []):
                        trade.setdefault('tactic_used', []).append("Trailing_SL_Active")

def handle_stale_trades(bnc: BinanceConnector, state: Dict, realtime_prices: Dict[str, float]):
    now_aware = datetime.now(VIETNAM_TZ)
    for trade in state.get("active_trades", [])[:]:
        rules = RISK_RULES_CONFIG["STALE_TRADE_RULES"].get(trade.get("interval"))
        if not rules: continue
        entry_time = datetime.fromisoformat(trade['entry_time'])
        holding_hours = (now_aware - entry_time).total_seconds() / 3600
        if holding_hours > rules["HOURS"]:
            _, pnl_pct = get_current_pnl(trade, realtime_price=realtime_prices.get(trade['symbol']))
            latest_score = trade.get('last_score', 5.0)
            if pnl_pct < rules["PROGRESS_THRESHOLD_PCT"] and latest_score < RISK_RULES_CONFIG["STALE_TRADE_RULES"]["STAY_OF_EXECUTION_SCORE"]:
                log_message(f"🐌 Phát hiện lệnh 'ì': {trade['symbol']} ({trade['interval']}) giữ {holding_hours:.1f}h không có tiến triển.")
                close_trade_on_binance(bnc, trade, "Stale", state)
            elif pnl_pct < rules["PROGRESS_THRESHOLD_PCT"]:
                log_message(f"⏳ Lệnh {trade['symbol']} đã quá hạn nhưng được GIA HẠN do tín hiệu mới tốt (Điểm: {latest_score:.2f})")

def handle_dca_opportunities(bnc: BinanceConnector, state: Dict, available_usdt: float, total_usdt_fund: float, realtime_prices: Dict[str, float]):
    if not DCA_CONFIG["ENABLED"]: return
    log_message("🎯 Quét cơ hội DCA...")
    current_exposure_usd = sum(t.get('total_invested_usd', 0.0) for t in state.get("active_trades", []))
    exposure_limit = total_usdt_fund * CAPITAL_MANAGEMENT_CONFIG["MAX_TOTAL_EXPOSURE_PCT"]
    now = datetime.now(VIETNAM_TZ)
    for trade in state.get("active_trades", [])[:]:
        if len(trade.get("dca_entries", [])) >= DCA_CONFIG["MAX_DCA_ENTRIES"]: continue
        if trade.get('last_dca_time'):
            if (now - datetime.fromisoformat(trade.get('last_dca_time'))).total_seconds() / 3600 < DCA_CONFIG['DCA_COOLDOWN_HOURS']: continue
        current_price = realtime_prices.get(trade["symbol"])
        if not current_price or current_price <= 0: continue
        last_entry_price = trade['dca_entries'][-1]['price'] if trade.get('dca_entries') else trade['initial_entry']['price']
        price_drop_pct = ((current_price - last_entry_price) / last_entry_price) * 100
        if price_drop_pct > DCA_CONFIG["TRIGGER_DROP_PCT"]: continue
        current_data = indicator_results.get(trade["symbol"], {}).get(trade["interval"], {})
        decision = get_advisor_decision(trade['symbol'], trade['interval'], current_data, ADVISOR_BASE_CONFIG)
        if decision.get("final_score", 0.0) < DCA_CONFIG["SCORE_MIN_THRESHOLD"]: continue
        dca_investment = (trade['dca_entries'][-1]['invested_usd'] if trade.get('dca_entries') else trade['initial_entry']['invested_usd']) * DCA_CONFIG["CAPITAL_MULTIPLIER"]
        if dca_investment <= 0 or dca_investment > available_usdt or (current_exposure_usd + dca_investment) > exposure_limit: continue
        try:
            log_message(f"🎯 THỰC HIỆN DCA cho {trade['symbol']} với ${dca_investment:,.2f}...")
            side = "BUY" if trade['trade_type'] == 'LONG' else "SELL"
            market_dca_order = bnc.place_market_order(symbol=trade['symbol'], side=side, quote_order_qty=round(dca_investment, 2))
            if not (market_dca_order and market_dca_order.get('status') == 'FILLED'): raise Exception("Lệnh Market DCA không khớp.")
            dca_qty = float(market_dca_order['executedQty']); dca_cost = float(market_dca_order['cummulativeQuoteQty']); dca_price = dca_cost / dca_qty
            trade.setdefault('dca_entries', []).append({"price": dca_price, "quantity": dca_qty, "invested_usd": dca_cost, "timestamp": now.isoformat()})
            new_total_qty = float(trade['quantity']) + dca_qty; new_total_cost = trade['total_invested_usd'] + dca_cost; new_avg_price = new_total_cost / new_total_qty
            initial_risk_dist = abs(trade['initial_entry']['price'] - trade['initial_sl'])
            new_sl = new_avg_price - initial_risk_dist
            new_tp = new_avg_price + (initial_risk_dist * TACTICS_LAB[trade['opened_by_tactic']]['RR'])
            trade.update({
                'entry_price': new_avg_price, 'total_invested_usd': new_total_cost, 'quantity': new_total_qty, 'sl': new_sl, 'tp': new_tp,
                'profit_taken': False, 'peak_pnl_percent': 0.0, 'tp1_hit': False, 'is_in_warning_zone': False, 'partial_closed_by_score': False
            })
            trade.setdefault('tactic_used', []).append(f"DCA_{len(trade.get('dca_entries', []))}")
            trade['last_dca_time'] = now.isoformat(); trade['initial_sl'] = new_sl
            trade['initial_entry'].update({"price": new_avg_price, "quantity": new_total_qty, "invested_usd": new_total_cost})
            log_message(f"✅ DCA thành công. Vị thế mới của {trade['symbol']}: Qty={new_total_qty:.4f}, Giá TB={new_avg_price:.4f}")
        except Exception as e: log_message(f"🔥🔥🔥 LỖI NGHIÊM TRỌNG KHI DCA {trade['symbol']}. CẦN CAN THIỆP THỦ CÔNG! Lỗi: {e}")

# ==============================================================================
# ================= 🚀 CORE LOGIC v8.0.0: 4-ZONE FUNCTIONS 🚀 =================
# ==============================================================================

def determine_market_zone_with_scoring(symbol: str, interval: str) -> str:
    """Xác định Vùng thị trường bằng hệ thống chấm điểm đa chỉ báo."""
    indicators = indicator_results.get(symbol, {}).get(interval, {})
    df = price_dataframes.get(symbol, {}).get(interval)
    if not indicators or df is None or df.empty: return NOISE_ZONE

    scores = {LEADING_ZONE: 0, COINCIDENT_ZONE: 0, LAGGING_ZONE: 0, NOISE_ZONE: 0}
    
    # Lấy các chỉ báo cần thiết, có giá trị mặc định để tránh lỗi
    adx = indicators.get('adx', 20)
    bb_width = indicators.get('bb_width', 0)
    rsi_14 = indicators.get('rsi_14', 50)
    macd_cross = indicators.get('macd_cross', "neutral")
    trend = indicators.get('trend', "sideway")
    breakout_signal = indicators.get('breakout_signal', "none")
    volume = indicators.get('volume', 0)
    vol_ma20 = indicators.get('vol_ma20', 1)

    # 1. Chấm điểm cho Vùng Nhiễu (NOISE_ZONE)
    if adx < 20: scores[NOISE_ZONE] += 3
    if 'ema_50' in df.columns:
        crossings = np.sign(df['close'].iloc[-30:] - df['ema_50'].iloc[-30:]).diff().ne(0).sum()
        if crossings > 4: scores[NOISE_ZONE] += 2 # Giá cắt qua lại MA50 nhiều lần

    # 2. Chấm điểm cho Vùng Tín hiệu Trễ (LAGGING_ZONE)
    if adx > 25: scores[LAGGING_ZONE] += 2.5
    if trend in ["uptrend", "downtrend"]: scores[LAGGING_ZONE] += 2
    if 'ema_20' in df.columns and 'ema_50' in df.columns and not df['ema_20'].isna().all() and not df['ema_50'].isna().all():
        if trend == "uptrend" and df['ema_20'].iloc[-1] > df['ema_50'].iloc[-1] and df['ema_20'].iloc[-10] > df['ema_50'].iloc[-10]:
            scores[LAGGING_ZONE] += 1.5 # MA đã xếp chồng và duy trì một thời gian
        elif trend == "downtrend" and df['ema_20'].iloc[-1] < df['ema_50'].iloc[-1] and df['ema_20'].iloc[-10] < df['ema_50'].iloc[-10]:
            scores[LAGGING_ZONE] += 1.5
    
    # 3. Chấm điểm cho Vùng Tín hiệu Sớm (LEADING_ZONE)
    if 'bb_width' in df.columns and not df['bb_width'].isna().all():
        if bb_width < df['bb_width'].iloc[-100:].quantile(0.20): scores[LEADING_ZONE] += 2.5 # BBW siết chặt
    
    htf_interval = '4h' if interval == '1h' else '1d'
    htf_trend = indicator_results.get(symbol, {}).get(htf_interval, {}).get('trend', 'sideway')
    if htf_trend == 'uptrend' and rsi_14 < 45: scores[LEADING_ZONE] += 2 # Dip trong uptrend
    if htf_trend == 'downtrend' and rsi_14 > 55: scores[LEADING_ZONE] += 2 # Rally trong downtrend

    # 4. Chấm điểm cho Vùng Tín hiệu Đồng thời (COINCIDENT_ZONE)
    if breakout_signal != "none": scores[COINCIDENT_ZONE] += 3
    if macd_cross not in ["neutral"]: scores[COINCIDENT_ZONE] += 2
    if vol_ma20 > 0 and volume > vol_ma20 * 2: scores[COINCIDENT_ZONE] += 1.5 # Volume spike

    # 5. Quy tắc trừ điểm để loại trừ
    if adx > 28: scores[LEADING_ZONE] -= 2 # Không thể là tín hiệu sớm nếu trend đã quá mạnh

    # Trả về Vùng có điểm cao nhất
    if not scores or all(v == 0 for v in scores.values()): return NOISE_ZONE
    return max(scores, key=scores.get)

def get_capital_allocation_for_zone(zone: str) -> float:
    """Lấy tỷ lệ phân bổ vốn dựa trên Vùng thị trường."""
    return ZONE_BASED_POLICIES.get(zone, {"CAPITAL_PCT": 0.03})["CAPITAL_PCT"]
    
def find_and_open_new_trades(bnc: BinanceConnector, state: Dict, available_usdt: float, total_usdt_fund: float):
    if len(state.get("active_trades", [])) >= RISK_RULES_CONFIG["MAX_ACTIVE_TRADES"]: return
    
    potential_opportunities = []
    now_vn = datetime.now(VIETNAM_TZ)
    log_message("🔎 Bắt đầu quét cơ hội lệnh mới theo mô hình 4 Vùng...")

    for symbol in SYMBOLS_TO_SCAN:
        if any(t['symbol'] == symbol for t in state.get("active_trades", [])): continue
        cooldown_map = state.get('cooldown_until', {})
        if symbol in cooldown_map and now_vn < datetime.fromisoformat(cooldown_map[symbol]): continue

        for interval in INTERVALS_TO_SCAN:
            market_zone = determine_market_zone_with_scoring(symbol, interval)
            log_message(f"  -> {symbol}-{interval}: Vùng xác định = {market_zone}")

            for tactic_name, tactic_cfg in TACTICS_LAB.items():
                if tactic_cfg.get("OPTIMAL_ZONE") == market_zone:
                    indicators = indicator_results.get(symbol, {}).get(interval)
                    if not (indicators and indicators.get('price', 0) > 0): continue
                    
                    decision = get_advisor_decision(symbol, interval, indicators, ADVISOR_BASE_CONFIG, weights_override=tactic_cfg.get("WEIGHTS"))
                    adjusted_score = decision.get("final_score", 0.0) * get_mtf_adjustment_coefficient(symbol, interval)
                    
                    if adjusted_score >= tactic_cfg.get("ENTRY_SCORE", 9.9):
                        potential_opportunities.append({
                            "decision": decision, "tactic_name": tactic_name, "tactic_cfg": tactic_cfg,
                            "score": adjusted_score, "symbol": symbol, "interval": interval, "zone": market_zone
                        })

    if not potential_opportunities: return
        
    best_opportunity = sorted(potential_opportunities, key=lambda x: x['score'], reverse=True)[0]
    decision_data, tactic_name, tactic_cfg = best_opportunity['decision'], best_opportunity['tactic_name'], best_opportunity['tactic_cfg']
    symbol, interval, score, zone = best_opportunity['symbol'], best_opportunity['interval'], best_opportunity['score'], best_opportunity['zone']
    
    log_message(f"🏆 Cơ hội tốt nhất: {symbol}-{interval} | Vùng: {zone} | Tactic: {tactic_name} | Điểm: {score:.2f}")

    full_indicators = decision_data.get('full_indicators', {})
    entry_price_estimate = full_indicators.get('price')
    if not entry_price_estimate or entry_price_estimate <= 0: return

    risk_dist_from_atr = full_indicators.get('atr', 0) * tactic_cfg.get("ATR_SL_MULTIPLIER", 2.0)
    max_sl_pct = RISK_RULES_CONFIG["MAX_SL_PERCENT_BY_TIMEFRAME"].get(interval)
    if max_sl_pct is None: return
    
    final_risk_dist = min(risk_dist_from_atr, entry_price_estimate * max_sl_pct)
    if final_risk_dist <= 0: return

    current_exposure_usd = sum(t.get('total_invested_usd', 0.0) for t in state.get("active_trades", []))
    exposure_limit = total_usdt_fund * CAPITAL_MANAGEMENT_CONFIG["MAX_TOTAL_EXPOSURE_PCT"]
    capital_pct = get_capital_allocation_for_zone(zone)
    invested_amount = total_usdt_fund * capital_pct
    
    FALLBACK_TOLERANCE_PCT = 0.90 
    if invested_amount > available_usdt:
        if available_usdt >= (invested_amount * FALLBACK_TOLERANCE_PCT):
            log_message(f"💡 {symbol}: Không đủ ${invested_amount:,.2f}, fallback mua với ${available_usdt * 0.98:,.2f}.")
            invested_amount = available_usdt * 0.98
        else:
            log_message(f"⚠️ {symbol}: Bỏ qua do không đủ vốn (cần ${invested_amount:,.2f}, có ${available_usdt:,.2f}).")
            return
            
    if (current_exposure_usd + invested_amount) > exposure_limit:
        log_message(f"⚠️ {symbol}: Bỏ qua do vượt ngưỡng rủi ro tổng.")
        return
        
    if invested_amount < 10:
        log_message(f"⚠️ {symbol}: Bỏ qua do giá trị lệnh (${invested_amount:,.2f}) quá nhỏ.")
        return

    try:
        log_message(f"🔥 Thực thi lệnh LONG {symbol} với ${invested_amount:,.2f} (Vùng: {zone}, Vốn: {capital_pct*100}%)")
        market_order = bnc.place_market_order(symbol=symbol, side="BUY", quote_order_qty=round(invested_amount, 2))
        if not (market_order and float(market_order.get('executedQty', 0)) > 0): raise Exception("Lệnh Market không khớp.")

        state['temp_money_spent_on_trades'] += float(market_order['cummulativeQuoteQty'])
        filled_qty = float(market_order['executedQty'])
        avg_price = float(market_order['cummulativeQuoteQty']) / filled_qty
        sl_p = avg_price - final_risk_dist
        tp_by_rr = avg_price + (final_risk_dist * tactic_cfg.get("RR", 2.0))
        max_tp_pct_cfg = RISK_RULES_CONFIG.get("MAX_TP_PERCENT_BY_TIMEFRAME", {}).get(interval)
        tp_p = tp_by_rr
        if max_tp_pct_cfg is not None and tp_by_rr > avg_price * (1 + max_tp_pct_cfg):
            tp_p = avg_price * (1 + max_tp_pct_cfg)
            log_message(f"  -> 🛡️ TP: RR quá cao! Ép lợi nhuận về trần an toàn ({max_tp_pct_cfg:.2%}).")

        if tp_p <= avg_price or sl_p >= avg_price or sl_p <= 0:
            raise Exception(f"SL/TP không hợp lệ sau khi tính toán. SL:{sl_p:.4f}, TP:{tp_p:.4f}")

        log_message(f"  -> ✅ Lệnh MARKET đã khớp. Entry:{avg_price:.4f}, Qty:{filled_qty}")
        log_message(f"  -> 📝 Lưu vào state: TP:{tp_p:.4f}, SL:{sl_p:.4f}")

        new_trade = {
            "trade_id": str(uuid.uuid4()), "symbol": symbol, "interval": interval, "status": "ACTIVE",
            "opened_by_tactic": tactic_name, "trade_type": "LONG", "entry_price": avg_price,
            "quantity": filled_qty, "tp": tp_p, "sl": sl_p, "initial_sl": sl_p,
            "initial_entry": {"price": avg_price, "quantity": filled_qty, "invested_usd": float(market_order['cummulativeQuoteQty'])},
            "total_invested_usd": float(market_order['cummulativeQuoteQty']),
            "entry_time": now_vn.isoformat(), "entry_score": score,
            # --- DÒNG MỚI ĐƯỢC THÊM ---
            "entry_zone": zone, # Lưu lại Vùng lúc vào lệnh
            "last_zone": zone,  # Vùng hiện tại, ban đầu bằng Vùng vào lệnh
            # --- KẾT THÚC DÒNG MỚI ---
            "binance_market_order_id": market_order['orderId'],
            "dca_entries": [], "profit_taken": False, "realized_pnl_usd": 0.0, "last_score": score,
            "peak_pnl_percent": 0.0, "tp1_hit": False, "is_in_warning_zone": False, "partial_closed_by_score": False
        }

        state['active_trades'].append(new_trade)
        state.setdefault('temp_newly_opened_trades', []).append(f"🔥 {symbol}-{interval} ({tactic_name}): Vốn ${new_trade['total_invested_usd']:,.2f}")
    
    except Exception as e:
        log_message(f"❌ LỖI NGHIÊM TRỌNG khi thực thi lệnh {symbol}: {e}")
        now = datetime.now(VIETNAM_TZ)
        error_cooldown_map = state.get('error_cooldown_until', {})
        if symbol in error_cooldown_map and now < datetime.fromisoformat(error_cooldown_map[symbol]): return
        error_details = traceback.format_exc()
        send_discord_message_chunks(f"❌ Lỗi khi mở lệnh {symbol}: ```\n{error_details}\n```", force=True)
        cooldown_end = now + timedelta(minutes=15)
        state.setdefault('error_cooldown_until', {})[symbol] = cooldown_end.isoformat()

def get_mtf_adjustment_coefficient(symbol: str, target_interval: str, trade_type: str = "LONG") -> float:
    if not MTF_ANALYSIS_CONFIG["ENABLED"]: return 1.0
    trends = {tf: indicator_results.get(symbol, {}).get(tf, {}).get("trend", "sideways") for tf in ALL_TIME_FRAMES}
    cfg, fav, unfav = MTF_ANALYSIS_CONFIG, "uptrend", "downtrend"
    if target_interval == "1h":
        htf1, htf2 = trends["4h"], trends["1d"]
        if htf1 == unfav and htf2 == unfav: return cfg["SEVERE_PENALTY_COEFFICIENT"]
        if htf1 == unfav or htf2 == unfav: return cfg["PENALTY_COEFFICIENT"]
        if htf1 == fav and htf2 == fav: return cfg["BONUS_COEFFICIENT"]
        if htf1 == "sideways" or htf2 == "sideways": return cfg["SIDEWAYS_PENALTY_COEFFICIENT"]
    elif target_interval == "4h":
        htf1 = trends["1d"]
        if htf1 == unfav: return cfg["PENALTY_COEFFICIENT"]
        if htf1 == fav: return cfg["BONUS_COEFFICIENT"]
        if htf1 == "sideways": return cfg["SIDEWAYS_PENALTY_COEFFICIENT"]
    return 1.0

# --- HỆ THỐNG BÁO CÁO ---
def calculate_total_equity(state: Dict, total_usdt_on_binance: float, realtime_prices: Dict[str, float]) -> float:
    value_of_open_positions = sum(float(trade.get('quantity', 0)) * realtime_prices.get(trade['symbol'], 0) for trade in state.get('active_trades', []))
    return total_usdt_on_binance + value_of_open_positions

def build_report_header(state: Dict, equity: float, total_usdt: float, available_usdt: float) -> str:
    initial_capital = state.get('initial_capital', total_usdt)
    if initial_capital <= 0: initial_capital = total_usdt
    pnl_since_start = equity - initial_capital
    pnl_percent = (pnl_since_start / initial_capital) * 100 if initial_capital > 0 else 0
    pnl_icon = "🟢" if pnl_since_start >= 0 else "🔴"
    return (f"💰 Vốn BĐ: **${initial_capital:,.2f}** | 💵 Tiền mặt (USDT): **${available_usdt:,.2f}**\n"
            f"📊 Tổng TS: **${equity:,.2f}** | 📈 PnL Tổng: {pnl_icon} **${pnl_since_start:,.2f} ({pnl_percent:+.2f}%)**")

def build_pnl_summary_line(state: Dict, realtime_prices: Dict[str, float]) -> str:
    trade_history, active_trades = state.get('trade_history', []), state.get('active_trades', [])
    df_history = pd.DataFrame(trade_history) if trade_history else pd.DataFrame()
    total_trades, win_rate_str = len(df_history), "N/A"
    if total_trades > 0:
        winning_trades = len(df_history[df_history['pnl_usd'] > 0])
        win_rate_str = f"{winning_trades / total_trades * 100:.2f}% ({winning_trades}/{total_trades})"
    total_pnl_closed = df_history['pnl_usd'].sum() if total_trades > 0 else 0.0
    realized_partial_pnl = sum(t.get('realized_pnl_usd', 0.0) for t in active_trades)
    unrealized_pnl = sum(get_current_pnl(trade, realtime_price=realtime_prices.get(trade['symbol']))[0] for trade in active_trades)
    return (f"🏆 Win Rate: **{win_rate_str}** | ✅ PnL Đóng: **${total_pnl_closed:,.2f}** | "
            f"💎 PnL TP1: **${realized_partial_pnl:,.2f}** | 📈 PnL Mở: **{'+' if unrealized_pnl >= 0 else ''}${unrealized_pnl:,.2f}**")

def build_trade_details_for_report(trade: Dict, realtime_price: float) -> str:
    pnl_usd, pnl_pct = get_current_pnl(trade, realtime_price=realtime_price)
    icon = "🟢" if pnl_usd >= 0 else "🔴"
    holding_h = (datetime.now(VIETNAM_TZ) - datetime.fromisoformat(trade['entry_time'])).total_seconds() / 3600
    dca_info = f" (DCA:{len(trade.get('dca_entries',[]))})" if trade.get('dca_entries') else ""
    tsl_info = f" TSL:{trade['sl']:.4f}" if "Trailing_SL_Active" in trade.get('tactic_used', []) else ""
    tp1_info = " TP1✅" if trade.get('tp1_hit', False) or trade.get('profit_taken', False) else ""

    # --- PHẦN THAY ĐỔI NẰM Ở ĐÂY ---
    entry_score = trade.get('entry_score', 0.0)
    last_score = trade.get('last_score', entry_score)
    score_display = f"{entry_score:,.1f}→{last_score:,.1f}"
    if last_score < entry_score: score_display += "📉"
    elif last_score > entry_score: score_display += "📈"

    entry_zone = trade.get('entry_zone', 'N/A')
    last_zone = trade.get('last_zone', entry_zone)
    zone_display = entry_zone
    if last_zone != entry_zone:
        zone_display = f"{entry_zone}→{last_zone}"

    tactic_info = f"({trade.get('opened_by_tactic')} | {score_display} | {zone_display})"
    # --- KẾT THÚC PHẦN THAY ĐỔI ---

    invested_usd = trade.get('total_invested_usd', 0.0)
    current_value = invested_usd + pnl_usd # Tính giá trị hiện tại của vị thế

    return (f"  {icon} **{trade['symbol']}-{trade['interval']}** {tactic_info} PnL: **${pnl_usd:,.2f} ({pnl_pct:+.2f}%)** | Giữ:{holding_h:.1f}h{dca_info}{tp1_info}\n"
            f"    Vốn:${invested_usd:,.2f} -> **${current_value:,.2f}** | Entry:{trade['entry_price']:.4f} Cur:{realtime_price:.4f} TP:{trade['tp']:.4f} SL:{trade['sl']:.4f}{tsl_info}")


def build_report_text(state: Dict, total_usdt: float, available_usdt: float, realtime_prices: Dict[str, float], report_type: str) -> str:
    now_vn_str = datetime.now(VIETNAM_TZ).strftime('%H:%M %d-%m-%Y')
    title = f"📊 **BÁO CÁO TỔNG KẾT (LIVE)** - `{now_vn_str}`" if report_type == "daily" else f"💡 **CẬP NHẬT ĐỘNG (LIVE)** - `{now_vn_str}`"
    lines = [title, ""]
    equity = calculate_total_equity(state, total_usdt, realtime_prices)
    lines.append(build_report_header(state, equity, total_usdt, available_usdt))
    lines.append("\n" + build_pnl_summary_line(state, realtime_prices))
    active_trades = state.get('active_trades', [])
    lines.append(f"\n--- **Vị thế đang mở ({len(active_trades)})** ---")
    if not active_trades: lines.append("    (Không có vị thế nào)")
    else:
        for trade in sorted(active_trades, key=lambda x: x['entry_time']):
            current_price = realtime_prices.get(trade["symbol"])
            if current_price: lines.append(build_trade_details_for_report(trade, current_price))
    lines.append("\n====================================")
    return "\n".join(lines)

def should_send_dynamic_alert(state: Dict, equity: float, total_usdt: float) -> bool:
    if not DYNAMIC_ALERT_CONFIG["ENABLED"]: return False
    now = datetime.now(VIETNAM_TZ)
    last_alert = state.get('last_dynamic_alert', {"timestamp": None, "total_pnl_percent": 0.0})
    if not last_alert.get('timestamp'): return bool(state.get('active_trades'))
    last_alert_dt = datetime.fromisoformat(last_alert.get('timestamp')).astimezone(VIETNAM_TZ)
    hours_since = (now - last_alert_dt).total_seconds() / 3600
    if hours_since >= DYNAMIC_ALERT_CONFIG["FORCE_UPDATE_HOURS"]: return True
    if hours_since < DYNAMIC_ALERT_CONFIG["COOLDOWN_HOURS"]: return False
    initial_capital = state.get('initial_capital', 1)
    if initial_capital <= 0: return False
    current_pnl_pct = ((equity - initial_capital) / initial_capital) * 100
    return abs(current_pnl_pct - last_alert.get('total_pnl_percent', 0.0)) >= DYNAMIC_ALERT_CONFIG["PNL_CHANGE_THRESHOLD_PCT"]

# --- CÁC HÀM TÁC VỤ CHÍNH ---
def run_heavy_tasks(bnc: BinanceConnector, state: Dict, available_usdt: float, total_usdt: float):
    log_message("---[⚙️ Bắt đầu chu kỳ tác vụ nặng ⚙️]---")
    log_message("⏳ Tải và tính toán indicators...")
    indicator_results.clear(); price_dataframes.clear()
    symbols_to_load = list(set(SYMBOLS_TO_SCAN + [t['symbol'] for t in state.get('active_trades', [])] + ["BTCUSDT"]))
    for symbol in symbols_to_load:
        indicator_results[symbol] = {}; price_dataframes[symbol] = {}
        for interval in ALL_TIME_FRAMES:
            df = get_price_data_with_cache(symbol, interval, GENERAL_CONFIG["DATA_FETCH_LIMIT"])
            if df is not None and not df.empty:
                # Bổ sung các cột cần thiết cho việc chấm điểm Vùng nếu chưa có
                if 'ema_20' not in df.columns or 'ema_50' not in df.columns:
                    df['ema_20'] = ta.trend.ema_indicator(df["close"], window=20)
                    df['ema_50'] = ta.trend.ema_indicator(df["close"], window=50)
                if 'bb_width' not in df.columns:
                    bb = ta.volatility.BollingerBands(df["close"], window=20, window_dev=2)
                    df['bb_width'] = bb.bollinger_wband()
                
                indicator_results[symbol][interval] = calculate_indicators(df.copy(), symbol, interval)
                price_dataframes[symbol][interval] = df
            else:
                indicator_results[symbol][interval] = {}
                price_dataframes[symbol][interval] = pd.DataFrame()

    # Đoạn code mới
    log_message("🧮 Cập nhật điểm & vùng cho các lệnh đang mở...")
    for trade in state.get("active_trades", []):
        indicators = indicator_results.get(trade['symbol'], {}).get(trade['interval'])
        if indicators:
            # Cập nhật điểm
            tactic_cfg = TACTICS_LAB.get(trade['opened_by_tactic'], {})
            decision = get_advisor_decision(trade['symbol'], trade['interval'], indicators, ADVISOR_BASE_CONFIG, weights_override=tactic_cfg.get("WEIGHTS"))
            trade['last_score'] = decision.get("final_score", 0.0)
            # --- DÒNG MỚI ĐƯỢC THÊM ---
            current_zone = determine_market_zone_with_scoring(trade['symbol'], trade['interval'])
            trade['last_zone'] = current_zone
            # --- KẾT THÚC DÒNG MỚI ---
    
    find_and_open_new_trades(bnc, state, available_usdt, total_usdt)
    log_message("---[✔️ Kết thúc chu kỳ tác vụ nặng ✔️]---")

# ==============================================================================
# VÒNG LẶP CHÍNH
# ==============================================================================
def run_session():
    session_id = datetime.now(VIETNAM_TZ).strftime('%Y%m%d_%H%M%S')
    log_message(f"====== 🚀 BẮT ĐẦU PHIÊN (v8.0.0 - 4-Zone Strategy) (ID: {session_id}) 🚀 ======")
    try:
        with BinanceConnector(network=TRADING_MODE) as bnc:
            if not bnc.test_connection(): return

            state = load_json_file(STATE_FILE, {
                "active_trades": [], "trade_history": [], "initial_capital": 0.0,
                "cooldown_until": {}, "last_indicator_refresh": None,
                "usdt_balance_end_of_last_session": 0.0,
                "pnl_closed_last_session": 0.0,
                "last_dynamic_alert": {"timestamp": None, "total_pnl_percent": 0.0}
            })
            state['temp_newly_opened_trades'] = []
            state['temp_newly_closed_trades'] = []
            state['temp_money_spent_on_trades'] = 0.0
            state['temp_pnl_from_closed_trades'] = 0.0

            available_usdt, total_usdt_at_start = get_usdt_fund(bnc)
            prev_usdt = state.get("usdt_balance_end_of_last_session", 0.0)
            if prev_usdt > 0:
                pnl_from_last_session = state.get("pnl_closed_last_session", 0.0)
                usdt_change = total_usdt_at_start - prev_usdt
                net_deposit = usdt_change - pnl_from_last_session
                if abs(net_deposit) > 1.0:
                    log_message(f"💵 Phát hiện Nạp/Rút ròng: ${net_deposit:,.2f}. Điều chỉnh initial_capital...")
                    state["initial_capital"] = state.get("initial_capital", 0.0) + net_deposit
            if state.get('initial_capital', 0.0) == 0.0 and total_usdt_at_start > 0:
                state['initial_capital'] = total_usdt_at_start
                log_message(f"Lần chạy đầu, ghi nhận vốn ban đầu: ${total_usdt_at_start:,.2f}")

            now_vn = datetime.now(VIETNAM_TZ)
            last_refresh_str = state.get("last_indicator_refresh")
            if not last_refresh_str or (now_vn - datetime.fromisoformat(last_refresh_str)).total_seconds() / 60 >= GENERAL_CONFIG["HEAVY_REFRESH_MINUTES"]:
                run_heavy_tasks(bnc, state, available_usdt, total_usdt_at_start)
                state["last_indicator_refresh"] = now_vn.isoformat()
            else:
                log_message("---[⚡ Bắt đầu chu kỳ tác vụ nhẹ ⚡]---")

            all_symbols_to_get_price = list(set([t['symbol'] for t in state.get('active_trades', [])]))
            realtime_prices = {sym: get_realtime_price(sym) for sym in all_symbols_to_get_price if sym}
            check_and_manage_open_positions(bnc, state, realtime_prices)
            handle_stale_trades(bnc, state, realtime_prices)
            handle_dca_opportunities(bnc, state, available_usdt, total_usdt_at_start, realtime_prices)

            final_available_usdt, final_total_usdt = get_usdt_fund(bnc)
            final_realtime_prices = {t['symbol']: get_realtime_price(t['symbol']) for t in state.get('active_trades', [])}
            final_equity = calculate_total_equity(state, final_total_usdt, final_realtime_prices)
            if should_send_dynamic_alert(state, final_equity, final_total_usdt):
                log_message("🔔 Gửi alert động.")
                report_content = build_report_text(state, final_total_usdt, final_available_usdt, final_realtime_prices, "dynamic")
                send_discord_message_chunks(report_content)
                initial_capital = state.get('initial_capital', 1)
                pnl_percent_for_alert = ((final_equity - initial_capital) / initial_capital) * 100 if initial_capital > 0 else 0
                state['last_dynamic_alert'] = {"timestamp": now_vn.isoformat(), "total_pnl_percent": pnl_percent_for_alert}

            state["usdt_balance_end_of_last_session"] = final_total_usdt
            state["pnl_closed_last_session"] = state['temp_pnl_from_closed_trades']
            save_json_file(STATE_FILE, state)

    except Exception:
        error_details = traceback.format_exc()
        log_message(f"!!!!!! ❌ LỖI NGHIÊM TRỌNG NGOÀI DỰ KIẾN ❌ !!!!!!\n{error_details}")
        send_discord_message_chunks(f"🔥🔥🔥 BOT GẶP LỖI NGHIÊM TRỌNG 🔥🔥🔥\n```python\n{error_details}\n```")
    log_message(f"====== ✅ KẾT THÚC PHIÊN (ID: {session_id}) ✅ ======\n")

if __name__ == "__main__":
    run_session()
