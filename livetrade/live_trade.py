# live_trade.py
# -*- coding: utf-8 -*-
"""
Live Trade - The 4-Zone Strategy
Version: 8.6.0 - Ultimate Safety & Flexibility
Date: 2025-08-03

CHANGELOG (v8.6.0):
- ROBUSTNESS (Orphan Asset Detection): The reconciliation process now detects assets present on Binance but missing from the state file ("orphan trades"). It sends a Discord alert if the asset's value exceeds a configurable threshold, prompting manual intervention via the control panel.
- FLEXIBILITY (Dynamic Cooldown): Implemented a flexible cooldown mechanism. The bot can now override the standard trade cooldown period for a symbol if a new, exceptionally high-scoring opportunity (above `OVERRIDE_COOLDOWN_SCORE`) arises.
- SAFETY (Minimum Order Size): Integrated checks to prevent failed orders due to size being below Binance's minimum threshold.
  - DCA: Skips DCA attempts if the calculated investment amount is too small.
  - Partial Take-Profit: If the remaining position value after a partial close would be too small ("dust"), the bot intelligently closes 100% of the position instead to avoid stranded assets.
- PRECISION (SL Price Check): Added a real-time price fetch immediately before the Stop-Loss check to minimize intra-run latency, ensuring the most up-to-date price for critical exit decisions.
- CONFIG: Added `MIN_ORDER_VALUE_USDT`, `OVERRIDE_COOLDOWN_SCORE`, and `ORPHAN_ASSET_MIN_VALUE_USDT` to GENERAL_CONFIG for enhanced control.
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
# ================== ⚙️ TRUNG TÂM CẤU HÌNH (v8.6.0) ⚙️ ===================
# ==============================================================================
TRADING_MODE: Literal["live", "testnet"] = "testnet"
INITIAL_CAPITAL = 0.0
GENERAL_CONFIG = {
    "DATA_FETCH_LIMIT": 300,
    "DAILY_SUMMARY_TIMES": ["08:10", "20:10"],
    "TRADE_COOLDOWN_HOURS": 1,
    "CRON_JOB_INTERVAL_MINUTES": 1,
    "HEAVY_REFRESH_MINUTES": 15,
    "PENDING_TRADE_RETRY_LIMIT": 3,
    "CLOSE_TRADE_RETRY_LIMIT": 3,
    "DEPOSIT_DETECTION_MIN_USD": 5.0,
    "DEPOSIT_DETECTION_THRESHOLD_PCT": 0.005,
    "CRITICAL_ERROR_ALERT_COOLDOWN_MINUTES": 45,
    "RECONCILIATION_QTY_THRESHOLD": 0.95,
    # CÁC BIẾN MỚI CHO BẢN v8.6.0
    "MIN_ORDER_VALUE_USDT": 11.0, # Ngưỡng giá trị lệnh tối thiểu (để 11$ cho an toàn)
    "OVERRIDE_COOLDOWN_SCORE": 7.5, # Điểm số tối thiểu để phá vỡ cooldown
    "ORPHAN_ASSET_MIN_VALUE_USDT": 10.0, # Giá trị tối thiểu (USD) để báo cáo một tài sản mồ côi
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
    "MAX_TP_PERCENT_BY_TIMEFRAME": {"1h": 0.12, "4h": 0.16, "1d": 0.20},
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
LEADING_ZONE = "LEADING"
COINCIDENT_ZONE = "COINCIDENT"
LAGGING_ZONE = "LAGGING"
NOISE_ZONE = "NOISE"
ZONES = [LEADING_ZONE, COINCIDENT_ZONE, LAGGING_ZONE, NOISE_ZONE]
ZONE_BASED_POLICIES = {
    LEADING_ZONE: {"NOTES": "Vốn nhỏ để 'dò mìn' cơ hội tiềm năng.", "CAPITAL_PCT": 0.055},
    COINCIDENT_ZONE: {"NOTES": "Vùng tốt nhất, quyết đoán vào lệnh.", "CAPITAL_PCT": 0.065},
    LAGGING_ZONE: {"NOTES": "An toàn, đi theo trend đã rõ.", "CAPITAL_PCT": 0.06},
    NOISE_ZONE: {"NOTES": "Nguy hiểm, chỉ vào lệnh siêu nhỏ khi có tín hiệu VÀNG.", "CAPITAL_PCT": 0.05}
}
TACTICS_LAB = {
    "Breakout_Hunter": {
        "OPTIMAL_ZONE": [LEADING_ZONE, COINCIDENT_ZONE], "NOTES": "Săn đột phá từ nền giá siết chặt.",
        "WEIGHTS": {'tech': 0.7, 'context': 0.1, 'ai': 0.2}, "ENTRY_SCORE": 7.0, "RR": 2.5,
        "ATR_SL_MULTIPLIER": 1.8, "USE_TRAILING_SL": True, "TRAIL_ACTIVATION_RR": 1.0,
        "TRAIL_DISTANCE_RR": 0.8, "ENABLE_PARTIAL_TP": True, "TP1_RR_RATIO": 1.0, "TP1_PROFIT_PCT": 0.5
    },
    "Dip_Hunter": {
        "OPTIMAL_ZONE": [LEADING_ZONE, COINCIDENT_ZONE], "NOTES": "Bắt đáy/sóng hồi trong trend lớn.",
        "WEIGHTS": {'tech': 0.6, 'context': 0.2, 'ai': 0.2}, "ENTRY_SCORE": 6.8, "RR": 2.2,
        "ATR_SL_MULTIPLIER": 2.0, "USE_TRAILING_SL": False, "TRAIL_ACTIVATION_RR": None,
        "ENABLE_PARTIAL_TP": True, "TP1_RR_RATIO": 0.8, "TP1_PROFIT_PCT": 0.6
    },
    "AI_Aggressor": {
        "OPTIMAL_ZONE": COINCIDENT_ZONE, "NOTES": "Tin vào AI khi có xác nhận mạnh mẽ.",
        "WEIGHTS": {'tech': 0.3, 'context': 0.1, 'ai': 0.6}, "ENTRY_SCORE": 6.6, "RR": 2.2,
        "ATR_SL_MULTIPLIER": 2.5, "USE_TRAILING_SL": True, "TRAIL_ACTIVATION_RR": 1.2,
        "TRAIL_DISTANCE_RR": 0.8, "ENABLE_PARTIAL_TP": True, "TP1_RR_RATIO": 1.0, "TP1_PROFIT_PCT": 0.5
    },
    "Balanced_Trader": {
        "OPTIMAL_ZONE": LAGGING_ZONE, "NOTES": "Chiến binh chủ lực, đi theo xu hướng rõ ràng.",
        "WEIGHTS": {'tech': 0.4, 'context': 0.2, 'ai': 0.4}, "ENTRY_SCORE": 6.3, "RR": 1.8,
        "ATR_SL_MULTIPLIER": 2.8, "USE_TRAILING_SL": True, "TRAIL_ACTIVATION_RR": 1.2,
        "TRAIL_DISTANCE_RR": 1.0, "ENABLE_PARTIAL_TP": True, "TP1_RR_RATIO": 1.2, "TP1_PROFIT_PCT": 0.5
    },
    "Cautious_Observer": {
        "OPTIMAL_ZONE": NOISE_ZONE, "NOTES": "Chỉ đánh khi có cơ hội VÀNG trong vùng nhiễu.",
        "WEIGHTS": {'tech': 0.7, 'context': 0.2, 'ai': 0.1}, "ENTRY_SCORE": 8.0, "RR": 1.5,
        "ATR_SL_MULTIPLIER": 1.5, "USE_TRAILING_SL": True, "TRAIL_ACTIVATION_RR": 0.7,
        "TRAIL_DISTANCE_RR": 0.5, "ENABLE_PARTIAL_TP": True, "TP1_RR_RATIO": 0.8, "TP1_PROFIT_PCT": 0.5
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
    if not (trade and trade.get('entry_price', 0) > 0 and realtime_price and realtime_price > 0): return 0.0, 0.0
    pnl_multiplier = 1.0
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
    quantity_to_close = float(trade.get('quantity', 0)) * close_pct
    if quantity_to_close <= 0: return False

    trade.setdefault('close_retry_count', 0)
    try:
        market_close_order = bnc.place_market_order(symbol=symbol, side=side, quantity=quantity_to_close)
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
    exit_price = float(market_close_order['cummulativeQuoteQty']) / closed_qty if closed_qty > 0 else trade['entry_price']

    pnl_usd = (exit_price - trade['entry_price']) * closed_qty
    state['temp_pnl_from_closed_trades'] += pnl_usd

    if close_pct >= 0.999: # Full close
        pnl_percent = (exit_price - trade['entry_price']) / trade['entry_price'] * 100
        trade.update({
            'status': f'Closed ({reason})',
            'exit_price': exit_price,
            'exit_time': datetime.now(VIETNAM_TZ).isoformat(),
            'pnl_usd': trade.get('realized_pnl_usd', 0.0) + pnl_usd,
            'pnl_percent': pnl_percent
        })
        state['active_trades'] = [t for t in state['active_trades'] if t['trade_id'] != trade['trade_id']]
        state['trade_history'].append(trade)
        state.setdefault('cooldown_until', {})[symbol] = (datetime.now(VIETNAM_TZ) + timedelta(hours=GENERAL_CONFIG["TRADE_COOLDOWN_HOURS"])).isoformat()
        export_trade_history_to_csv([trade])
        state.setdefault('temp_newly_closed_trades', []).append(f"🎬 {'✅' if pnl_usd >= 0 else '❌'} {symbol} (Đóng toàn bộ - {reason}): PnL ${pnl_usd:,.2f}")
    else: # Partial close
        trade['realized_pnl_usd'] = trade.get('realized_pnl_usd', 0.0) + pnl_usd
        trade['total_invested_usd'] *= (1 - close_pct)
        trade['quantity'] -= closed_qty
        trade.setdefault('tactic_used', []).append(f"Partial_Close_{reason}")
        state.setdefault('temp_newly_closed_trades', []).append(f"💰 {symbol} (Đóng {close_pct*100:.0f}% - {reason}): PnL ${pnl_usd:,.2f}")

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

        # Lấy lại giá mới nhất ngay trước khi kiểm tra SL để tăng độ chính xác
        precise_price_for_sl = get_realtime_price(symbol)
        if precise_price_for_sl is not None:
            current_price = precise_price_for_sl # Cập nhật giá để các logic sau dùng giá mới nhất
        
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
                # Kiểm tra giá trị lệnh còn lại
                remaining_value = (trade.get('quantity', 0) * (1 - close_pct)) * current_price
                if remaining_value < min_order_value:
                    log_message(f"⚠️ {symbol}: Giá trị còn lại ({remaining_value:.2f}$) quá nhỏ. Đóng toàn bộ thay vì một phần.", state)
                    close_pct = 1.0 # Ghi đè để đóng 100%
                
                if close_trade_on_binance(bnc, trade, f"EC_Rel_{last_score:.1f}", state, close_pct=close_pct):
                    trade['partial_closed_by_score'] = True
                    if close_pct < 1.0: # Chỉ đặt SL về entry nếu không phải đóng toàn bộ
                        trade['sl'] = trade['entry_price']
        
        _, pnl_percent = get_current_pnl(trade, realtime_price=current_price)
        trade['peak_pnl_percent'] = max(trade.get('peak_pnl_percent', 0.0), pnl_percent)
        
        initial_risk_dist = abs(trade['initial_entry']['price'] - trade['initial_sl'])
        
        if tactic_cfg.get("ENABLE_PARTIAL_TP", False) and not trade.get("tp1_hit", False) and initial_risk_dist > 0:
            pnl_ratio = (current_price - trade['entry_price']) / initial_risk_dist
            if pnl_ratio >= tactic_cfg.get("TP1_RR_RATIO", 1.0):
                close_pct = tactic_cfg.get("TP1_PROFIT_PCT", 0.5)
                # Kiểm tra giá trị lệnh còn lại
                remaining_value = (trade.get('quantity', 0) * (1 - close_pct)) * current_price
                if remaining_value < min_order_value:
                    log_message(f"⚠️ {symbol}: Giá trị còn lại ({remaining_value:.2f}$) sau TP1 quá nhỏ. Đóng toàn bộ.", state)
                    close_pct = 1.0 # Ghi đè để đóng 100%

                if close_trade_on_binance(bnc, trade, f"TP1_{tactic_cfg.get('TP1_RR_RATIO', 1.0):.1f}R", state, close_pct=close_pct):
                    trade['tp1_hit'] = True
                    if close_pct < 1.0: # Chỉ đặt SL về entry nếu không phải đóng toàn bộ
                        trade['sl'] = trade['entry_price']

        pp_config = ACTIVE_TRADE_MANAGEMENT_CONFIG.get("PROFIT_PROTECTION", {})
        if pp_config.get("ENABLED", False) and not trade.get('profit_taken', False) and trade['peak_pnl_percent'] >= pp_config.get("MIN_PEAK_PNL_TRIGGER", 3.5):
            if (trade['peak_pnl_percent'] - pnl_percent) >= pp_config.get("PNL_DROP_TRIGGER_PCT", 2.0):
                close_pct = pp_config.get("PARTIAL_CLOSE_PCT", 0.7)
                # Kiểm tra giá trị lệnh còn lại
                remaining_value = (trade.get('quantity', 0) * (1 - close_pct)) * current_price
                if remaining_value < min_order_value:
                    log_message(f"⚠️ {symbol}: Giá trị còn lại ({remaining_value:.2f}$) sau Profit-Protect quá nhỏ. Đóng toàn bộ.", state)
                    close_pct = 1.0 # Ghi đè để đóng 100%

                if close_trade_on_binance(bnc, trade, "Protect_Profit", state, close_pct=close_pct):
                    trade['profit_taken'] = True
                    if close_pct < 1.0: # Chỉ đặt SL về entry nếu không phải đóng toàn bộ
                        trade['sl'] = trade['entry_price']

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
        if len(trade.get("dca_entries", [])) >= DCA_CONFIG["MAX_DCA_ENTRIES"]: continue
        if trade.get('last_dca_time') and (now - datetime.fromisoformat(trade.get('last_dca_time'))).total_seconds() / 3600 < DCA_CONFIG['DCA_COOLDOWN_HOURS']: continue

        current_price = realtime_prices.get(trade["symbol"])
        if not current_price or current_price <= 0: continue

        last_entry_price = trade['dca_entries'][-1]['price'] if trade.get('dca_entries') else trade['initial_entry']['price']
        price_drop_pct = ((current_price - last_entry_price) / last_entry_price) * 100

        if price_drop_pct > DCA_CONFIG["TRIGGER_DROP_PCT"]: continue
        if get_advisor_decision(trade['symbol'], trade['interval'], indicator_results.get(trade["symbol"], {}).get(trade["interval"], {}), ADVISOR_BASE_CONFIG).get("final_score", 0.0) < DCA_CONFIG["SCORE_MIN_THRESHOLD"]: continue

        dca_investment = (trade['dca_entries'][-1]['invested_usd'] if trade.get('dca_entries') else trade['initial_entry']['invested_usd']) * DCA_CONFIG["CAPITAL_MULTIPLIER"]
        
        if dca_investment < min_order_value:
            log_message(f"⚠️ Bỏ qua DCA cho {trade['symbol']}: Vốn DCA dự tính ({dca_investment:,.2f}$) quá nhỏ.", state=state)
            continue
        
        if dca_investment <= 0 or dca_investment > available_usdt or (current_exposure_usd + dca_investment) > exposure_limit: continue
        
        try:
            state.setdefault('temp_newly_closed_trades', []).append(f"🎯 Thử DCA cho {trade['symbol']}...")
            market_dca_order = bnc.place_market_order(symbol=trade['symbol'], side="BUY", quote_order_qty=round(dca_investment, 2))
            if not (market_dca_order and market_dca_order.get('status') == 'FILLED'):
                raise Exception("Lệnh Market DCA không khớp.")

            dca_qty, dca_cost = float(market_dca_order['executedQty']), float(market_dca_order['cummulativeQuoteQty'])
            dca_price = dca_cost / dca_qty
            trade.setdefault('dca_entries', []).append({"price": dca_price, "quantity": dca_qty, "invested_usd": dca_cost, "timestamp": now.isoformat()})
            
            new_total_qty = float(trade['quantity']) + dca_qty
            new_total_cost = trade['total_invested_usd'] + dca_cost
            new_avg_price = new_total_cost / new_total_qty if new_total_qty > 0 else 0
            
            initial_risk_dist = abs(trade['initial_entry']['price'] - trade['initial_sl'])
            trade.update({
                'entry_price': new_avg_price,
                'total_invested_usd': new_total_cost,
                'quantity': new_total_qty,
                'sl': new_avg_price - initial_risk_dist,
                'tp': new_avg_price + (initial_risk_dist * TACTICS_LAB[trade['opened_by_tactic']]['RR']),
                'last_dca_time': now.isoformat()
            })
            trade.setdefault('tactic_used', []).append(f"DCA_{len(trade.get('dca_entries', []))}")
            state.setdefault('temp_newly_closed_trades', []).append(f"  => ✅ DCA thành công {trade['symbol']} với ${dca_cost:,.2f}")
        except Exception as e:
            log_error(f"Lỗi nghiêm trọng khi DCA {trade['symbol']}", error_details=traceback.format_exc(), send_to_discord=True, state=state)


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

    for symbol in SYMBOLS_TO_SCAN:
        if any(t['symbol'] == symbol for t in state.get("active_trades", [])): continue
        
        is_in_cooldown = symbol in cooldown_map and now_vn < datetime.fromisoformat(cooldown_map[symbol])
        
        for interval in INTERVALS_TO_SCAN:
            market_zone = determine_market_zone_with_scoring(symbol, interval)
            for tactic_name, tactic_cfg in TACTICS_LAB.items():
                optimal_zones = tactic_cfg.get("OPTIMAL_ZONE", [])
                if not isinstance(optimal_zones, list): optimal_zones = [optimal_zones]
                
                if market_zone in optimal_zones:
                    indicators = indicator_results.get(symbol, {}).get(interval)
                    if not (indicators and indicators.get('price', 0) > 0): continue
                    
                    decision = get_advisor_decision(symbol, interval, indicators, ADVISOR_BASE_CONFIG, weights_override=tactic_cfg.get("WEIGHTS"))
                    adjusted_score = decision.get("final_score", 0.0) * get_mtf_adjustment_coefficient(symbol, interval)
                    
                    # Logic phá vỡ cooldown
                    if is_in_cooldown:
                        if adjusted_score >= GENERAL_CONFIG["OVERRIDE_COOLDOWN_SCORE"]:
                            log_message(f"🔥 {symbol} có điểm {adjusted_score:.2f}, vượt ngưỡng! Phá vỡ cooldown.", state)
                            # Cho phép đi tiếp
                        else:
                            continue # Bỏ qua tactic này nếu không đủ điểm phá cooldown
                    
                    potential_opportunities.append({"decision": decision, "tactic_name": tactic_name, "tactic_cfg": tactic_cfg, "score": adjusted_score, "symbol": symbol, "interval": interval, "zone": market_zone})
    
    log_message("---[🔍 Quét Cơ Hội Mới 🔍]---", state=state)
    if not potential_opportunities:
        log_message("  => Không tìm thấy cơ hội tiềm năng nào.", state=state)
        return

    best_opportunity = sorted(potential_opportunities, key=lambda x: x['score'], reverse=True)[0]
    entry_score_threshold = best_opportunity['tactic_cfg'].get("ENTRY_SCORE", 9.9)

    log_message(f"  🏆 Cơ hội tốt nhất: {best_opportunity['symbol']}-{best_opportunity['interval']} | Tactic: {best_opportunity['tactic_name']} | Điểm: {best_opportunity['score']:.2f} (Ngưỡng: {entry_score_threshold})", state=state)

    if best_opportunity['score'] >= entry_score_threshold:
        log_message("      => ✅ Đạt ngưỡng! Đưa vào hàng chờ thực thi...", state=state)
        state['pending_trade_opportunity'] = best_opportunity
        state['pending_trade_opportunity']['retry_count'] = 0
    else:
        log_message("      => 📉 Không đạt ngưỡng. Bỏ qua.", state=state)


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
    max_sl_pct = RISK_RULES_CONFIG["MAX_SL_PERCENT_BY_TIMEFRAME"].get(interval, 0.1)
    final_risk_dist = min(risk_dist_from_atr, entry_price_estimate * max_sl_pct)

    if final_risk_dist <= 0:
        log_error(f"Tính toán risk_dist cho {symbol} không hợp lệ. Hủy cơ hội.", state=state)
        state.pop('pending_trade_opportunity', None)
        return

    capital_pct = ZONE_BASED_POLICIES.get(zone, {}).get("CAPITAL_PCT", 0.03)
    invested_amount = total_usdt_fund * capital_pct
    current_exposure_usd = sum(t.get('total_invested_usd', 0.0) for t in state.get("active_trades", []))
    min_order_value = GENERAL_CONFIG.get("MIN_ORDER_VALUE_USDT", 11.0)
    
    if invested_amount > available_usdt or (current_exposure_usd + invested_amount) > total_usdt_fund * CAPITAL_MANAGEMENT_CONFIG["MAX_TOTAL_EXPOSURE_PCT"] or invested_amount < min_order_value:
        log_message(f"  => ❌ Không đủ vốn hoặc vượt ngưỡng rủi ro cho {symbol} (Dự tính: ${invested_amount:.2f}). Hủy cơ hội.", state=state)
        state.pop('pending_trade_opportunity', None)
        return

    try:
        log_message(f"  => 🔥 Gửi lệnh MUA {symbol} với ${invested_amount:,.2f} (Vùng: {zone}, Vốn: {capital_pct*100:.1f}%)", state=state)
        market_order = bnc.place_market_order(symbol=symbol, side="BUY", quote_order_qty=round(invested_amount, 2))

        if not (market_order and float(market_order.get('executedQty', 0)) > 0):
            raise Exception("Lệnh Market không khớp hoặc không có thông tin trả về.")

        state['temp_money_spent_on_trades'] += float(market_order['cummulativeQuoteQty'])
        filled_qty = float(market_order['executedQty'])
        avg_price = float(market_order['cummulativeQuoteQty']) / filled_qty
        sl_p = avg_price - final_risk_dist
        tp_p = avg_price + (final_risk_dist * tactic_cfg.get("RR", 2.0))
        
        max_tp_pct_cfg = RISK_RULES_CONFIG["MAX_TP_PERCENT_BY_TIMEFRAME"].get(interval)
        if max_tp_pct_cfg is not None and tp_p > avg_price * (1 + max_tp_pct_cfg):
            tp_p = avg_price * (1 + max_tp_pct_cfg)

        if tp_p <= avg_price or sl_p >= avg_price or sl_p <= 0:
            raise Exception(f"SL/TP không hợp lệ: TP={tp_p}, SL={sl_p}, AvgPrice={avg_price}")

        new_trade = {
            "trade_id": str(uuid.uuid4()), "symbol": symbol, "interval": interval, "status": "ACTIVE",
            "opened_by_tactic": tactic_name, "trade_type": "LONG", "entry_price": avg_price,
            "quantity": filled_qty, "tp": tp_p, "sl": sl_p, "initial_sl": sl_p,
            "initial_entry": {"price": avg_price, "quantity": filled_qty, "invested_usd": float(market_order['cummulativeQuoteQty'])},
            "total_invested_usd": float(market_order['cummulativeQuoteQty']),
            "entry_time": datetime.now(VIETNAM_TZ).isoformat(), "entry_score": opportunity['score'],
            "entry_zone": zone, "last_zone": zone, "binance_market_order_id": market_order['orderId'],
            "dca_entries": [], "realized_pnl_usd": 0.0, "last_score": opportunity['score'],
            "peak_pnl_percent": 0.0, "tp1_hit": False, "close_retry_count": 0
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

# ==============================================================================
# ==================== BÁO CÁO & VÒNG LẶP CHÍNH (v8.6.0) =======================
# ==============================================================================

def calculate_total_equity(state: Dict, total_usdt_on_binance: float, realtime_prices: Dict[str, Optional[float]]) -> Optional[float]:
    value_of_open_positions = 0.0
    for trade in state.get('active_trades', []):
        price = realtime_prices.get(trade['symbol'])
        if price is None:
            return None
        value_of_open_positions += float(trade.get('quantity', 0)) * price
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
    trade_history = state.get('trade_history', [])
    df_history = pd.DataFrame(trade_history) if trade_history else pd.DataFrame()
    total_trades, win_rate_str = len(df_history), "N/A"
    if total_trades > 0:
        winning_trades = len(df_history[df_history['pnl_usd'] > 0])
        win_rate_str = f"{winning_trades / total_trades * 100:.2f}% ({winning_trades}/{total_trades})"

    total_pnl_closed = df_history['pnl_usd'].sum() if total_trades > 0 else 0.0
    realized_partial_pnl = sum(t.get('realized_pnl_usd', 0.0) for t in state.get('active_trades', []))
    unrealized_pnl = sum(get_current_pnl(trade, realtime_price=realtime_prices.get(trade['symbol']))[0] for trade in state.get('active_trades', []))
    
    return f"🏆 Win Rate: **{win_rate_str}** | ✅ PnL Đóng: **${total_pnl_closed:,.2f}** | 💎 PnL TP1: **${realized_partial_pnl:,.2f}** | 📈 PnL Mở: **{'+' if unrealized_pnl >= 0 else ''}${unrealized_pnl:,.2f}**"

def build_trade_details_for_report(trade: Dict, realtime_price: float) -> str:
    pnl_usd, pnl_pct = get_current_pnl(trade, realtime_price=realtime_price)
    icon = "🟢" if pnl_usd >= 0 else "🔴"
    holding_h = (datetime.now(VIETNAM_TZ) - datetime.fromisoformat(trade['entry_time'])).total_seconds() / 3600
    dca_info = f" (DCA:{len(trade.get('dca_entries',[]))})" if trade.get('dca_entries') else ""
    tsl_info = f" TSL:{trade['sl']:.4f}" if "Trailing_SL_Active" in trade.get('tactic_used', []) else ""
    tp1_info = " TP1✅" if trade.get('tp1_hit', False) or trade.get('profit_taken', False) else ""
    
    entry_score, last_score = trade.get('entry_score', 0.0), trade.get('last_score', 0.0)
    score_display = f"{entry_score:,.1f}→{last_score:,.1f}" + ("📉" if last_score < entry_score else "📈" if last_score > entry_score else "")
    zone_display = f"{trade.get('entry_zone', 'N/A')}→{trade.get('last_zone', 'N/A')}" if trade.get('last_zone') != trade.get('entry_zone') else trade.get('entry_zone', 'N/A')
    tactic_info = f"({trade.get('opened_by_tactic')} | {score_display} | {zone_display})"
    
    invested_usd = trade.get('total_invested_usd', 0.0)
    current_value = trade.get('total_invested_usd', 0.0) + pnl_usd

    return (f"  {icon} **{trade['symbol']}-{trade['interval']}** {tactic_info} PnL: **${pnl_usd:,.2f} ({pnl_pct:+.2f}%)** | Giữ:{holding_h:.1f}h{dca_info}{tp1_info}\n"
            f"    Vốn:${invested_usd:,.2f} -> **${current_value:,.2f}** | Entry:{trade['entry_price']:.4f} Cur:{realtime_price:.4f} TP:{trade['tp']:.4f} SL:{trade['sl']:.4f}{tsl_info}")

def format_closed_trade_line(trade_data: pd.Series) -> str:
    """Helper function to format a single line for a closed trade in the history section."""
    try:
        entry_time = pd.to_datetime(trade_data['entry_time']).tz_convert(VIETNAM_TZ)
        exit_time = pd.to_datetime(trade_data['exit_time']).tz_convert(VIETNAM_TZ)
        hold_duration_h = (exit_time - entry_time).total_seconds() / 3600

        tactics_list_str = trade_data.get('tactic_used', '[]')
        try:
            tactics_list = json.loads(tactics_list_str) if isinstance(tactics_list_str, str) else tactics_list_str
            if isinstance(tactics_list, list) and tactics_list:
                tactics_str = ', '.join(map(str, [t for t in tactics_list if pd.notna(t)]))
            else:
                tactics_str = trade_data.get('opened_by_tactic', 'N/A')
        except (json.JSONDecodeError, TypeError):
             tactics_str = trade_data.get('opened_by_tactic', 'N/A')


        info_str = f"Tactic: {tactics_str}"
        symbol_with_interval = f"{trade_data['symbol']}-{trade_data.get('interval', 'N/A')}"
        pnl_info = f"${trade_data.get('pnl_usd', 0):.2f} ({trade_data.get('pnl_percent', 0):+.2f}%)"
        return f"  • **{symbol_with_interval}** | PnL: `{pnl_info}` | {info_str} | Hold: {hold_duration_h:.1f}h"
    except Exception as e:
        return f"  • {trade_data.get('symbol', 'N/A')} - Lỗi báo cáo lịch sử: {e}"

def build_dynamic_alert_text(state: Dict, total_usdt: float, available_usdt: float, realtime_prices: Dict[str, float], equity: float) -> str:
    """Builds the concise, dynamic alert for quick updates."""
    now_vn_str = datetime.now(VIETNAM_TZ).strftime('%H:%M %d-%m-%Y')
    lines = [f"💡 **CẬP NHẬT ĐỘNG (LIVE)** - `{now_vn_str}`"]
    lines.append(build_report_header(state, equity, total_usdt, available_usdt))
    lines.append("\n" + build_pnl_summary_line(state, realtime_prices))
    
    active_trades = state.get('active_trades', [])
    lines.append(f"\n--- **Vị thế đang mở ({len(active_trades)})** ---")
    if not active_trades:
        lines.append("  (Không có vị thế nào)")
    else:
        for trade in sorted(active_trades, key=lambda x: x['entry_time']):
            lines.append(build_trade_details_for_report(trade, realtime_prices[trade["symbol"]]))
            
    lines.append("\n====================================")
    return "\n".join(lines)

def build_daily_summary_text(state: Dict, total_usdt: float, available_usdt: float, realtime_prices: Dict[str, float], equity: float) -> str:
    """Builds the enhanced, detailed daily summary report."""
    now_vn_str = datetime.now(VIETNAM_TZ).strftime('%H:%M %d-%m-%Y')
    lines = [f"📊 **BÁO CÁO TỔNG KẾT HÀNG NGÀY (LIVE)** - `{now_vn_str}` 📊"]
    
    # 1. Header & PnL Summary
    lines.append(build_report_header(state, equity, total_usdt, available_usdt))
    lines.append("\n" + build_pnl_summary_line(state, realtime_prices))

    # 2. Session Details
    lines.append("\n--- **Chi tiết trong phiên** ---")
    opened_trades = state.get('temp_newly_opened_trades', [])
    closed_trades = state.get('temp_newly_closed_trades', [])
    lines.append(f"✨ Lệnh mới mở: {len(opened_trades)}")
    if opened_trades: lines.extend([f"  - {msg}" for msg in opened_trades])
    lines.append(f"🎬 Lệnh đã đóng/chốt lời: {len(closed_trades)}")
    if closed_trades: lines.extend([f"  - {msg}" for msg in closed_trades])

    # 3. Open Positions
    active_trades = state.get('active_trades', [])
    lines.append(f"\n--- **Vị thế đang mở ({len(active_trades)})** ---")
    if not active_trades:
        lines.append("  (Không có vị thế nào)")
    else:
        for trade in sorted(active_trades, key=lambda x: x['entry_time']):
            lines.append(build_trade_details_for_report(trade, realtime_prices[trade["symbol"]]))

    # 4. Recent Trade History
    lines.append("\n--- **Lịch sử giao dịch gần nhất** ---")
    trade_history = state.get('trade_history', [])
    if trade_history:
        df_history = pd.DataFrame(trade_history)
        if 'exit_time' in df_history.columns and not df_history['exit_time'].isnull().all():
            df_history['exit_time_dt'] = pd.to_datetime(df_history['exit_time'])
            df_history['pnl_usd'] = pd.to_numeric(df_history['pnl_usd'], errors='coerce').fillna(0.0)
            
            winning_trades = df_history[df_history['pnl_usd'] > 0]
            losing_trades = df_history[df_history['pnl_usd'] <= 0]

            lines.append("\n**✅ Top 5 lệnh lãi gần nhất**")
            if not winning_trades.empty:
                for _, trade in winning_trades.sort_values(by='exit_time_dt', ascending=False).head(5).iterrows():
                    lines.append(format_closed_trade_line(trade))
            else:
                lines.append("  (Chưa có lệnh lãi)")

            lines.append("\n**❌ Top 5 lệnh lỗ/hòa vốn gần nhất**")
            if not losing_trades.empty:
                for _, trade in losing_trades.sort_values(by='exit_time_dt', ascending=False).head(5).iterrows():
                    lines.append(format_closed_trade_line(trade))
            else:
                lines.append("  (Chưa có lệnh lỗ/hòa vốn)")
        else:
            lines.append("  (Lịch sử giao dịch chưa có thời gian đóng lệnh để sắp xếp.)")
    else:
        lines.append("  (Chưa có lịch sử giao dịch)")

    lines.append("\n====================================")
    return "\n".join(lines)


def should_send_report(state: Dict, equity: Optional[float]) -> Optional[str]:
    if equity is None:
        return None

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
            tactic_cfg = TACTICS_LAB.get(trade['opened_by_tactic'], {})
            decision = get_advisor_decision(trade['symbol'], trade['interval'], indicators, ADVISOR_BASE_CONFIG, weights_override=tactic_cfg.get("WEIGHTS"))
            trade['last_score'] = decision.get("final_score", 0.0)
            trade['last_zone'] = determine_market_zone_with_scoring(trade['symbol'], trade['interval'])

    find_and_open_new_trades(bnc, state, available_usdt, total_usdt)


def reconcile_positions_with_binance(bnc: BinanceConnector, state: Dict):
    """
    Đối soát trạng thái giữa bot và Binance.
    1. Dọn dẹp các lệnh trong state nhưng không còn trên sàn (đóng thủ công).
    2. Phát hiện các tài sản "mồ côi" (có trên sàn nhưng không có trong state).
    """
    try:
        balances = bnc.get_account_balance().get("balances", [])
        asset_balances = {item['asset']: float(item['free']) + float(item['locked']) for item in balances}
    except Exception as e:
        log_error("Không thể lấy số dư tài khoản để đối soát.", error_details=str(e), state=state)
        return

    # --- Phần 1: Dọn dẹp các lệnh không đồng bộ (Desynced Trades) ---
    active_trades = state.get("active_trades", [])
    trades_to_remove = []
    threshold = GENERAL_CONFIG["RECONCILIATION_QTY_THRESHOLD"]
    
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
            state['trade_history'].append(trade)

        state['active_trades'] = [t for t in state['active_trades'] if t['trade_id'] not in trade_ids_to_remove]
        log_message(f"---[✅ Đã dọn dẹp xong]---", state=state)

    # --- Phần 2: Phát hiện tài sản mồ côi (Orphan Assets) ---
    symbols_in_state = {t['symbol'] for t in state.get("active_trades", [])}
    min_orphan_value = GENERAL_CONFIG["ORPHAN_ASSET_MIN_VALUE_USDT"]
    
    for asset_code, quantity in asset_balances.items():
        if asset_code in ["USDT", "BNB"]: continue # Bỏ qua các coin cơ bản
        
        symbol_usdt = f"{asset_code}USDT"
        if symbol_usdt in SYMBOLS_TO_SCAN and symbol_usdt not in symbols_in_state:
            price = get_realtime_price(symbol_usdt)
            if price:
                asset_value_usdt = quantity * price
                if asset_value_usdt > min_orphan_value:
                    msg = (f"⚠️ PHÁT HIỆN TÀI SẢN MỒ CÔI: **{quantity:.6f} {asset_code}** (trị giá ~${asset_value_usdt:,.2f}). "
                           f"Tài sản này có trên sàn nhưng không được quản lý bởi bot. "
                           f"Vui lòng dùng Control Panel để 'nhận nuôi' hoặc xử lý thủ công.")
                    log_error(msg, send_to_discord=True, force_discord=True, state=state)


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
            state['temp_newly_opened_trades'], state['temp_newly_closed_trades'] = [], []
            state['temp_money_spent_on_trades'], state['temp_pnl_from_closed_trades'] = 0.0, 0.0
            state['session_has_events'] = False

            reconcile_positions_with_binance(bnc, state)

            available_usdt, total_usdt_at_start = get_usdt_fund(bnc)
            if total_usdt_at_start == 0.0 and available_usdt == 0.0:
                return
            
            prev_usdt = state.get("usdt_balance_end_of_last_session", 0.0)
            if prev_usdt > 0:
                money_spent = state.get("money_spent_on_trades_last_session", 0.0)
                pnl_closed = state.get("pnl_closed_last_session", 0.0)
                net_deposit = total_usdt_at_start - prev_usdt + money_spent - pnl_closed

                threshold_pct = GENERAL_CONFIG.get("DEPOSIT_DETECTION_THRESHOLD_PCT", 0.005)
                min_threshold_usd = GENERAL_CONFIG.get("DEPOSIT_DETECTION_MIN_USD", 5.0)
                dynamic_threshold = max(min_threshold_usd, total_usdt_at_start * threshold_pct)
                
                if abs(net_deposit) > dynamic_threshold:
                    log_message(f"💵 Phát hiện Nạp/Rút ròng: ${net_deposit:,.2f} (Đã tính toán chi phí giao dịch)", state=state)
                    state["initial_capital"] = state.get("initial_capital", 0.0) + net_deposit

            if state.get('initial_capital', 0.0) <= 0 and total_usdt_at_start > 0:
                state['initial_capital'] = total_usdt_at_start
                log_message(f"🌱 Thiết lập vốn ban đầu: ${state['initial_capital']:,.2f}", state=state)

            now_vn = datetime.now(VIETNAM_TZ)
            last_refresh_str = state.get("last_indicator_refresh")
            is_heavy_task_time = not last_refresh_str or \
                                 (now_vn - datetime.fromisoformat(last_refresh_str)).total_seconds() / 60 >= GENERAL_CONFIG["HEAVY_REFRESH_MINUTES"]

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
                realtime_prices = {sym: get_realtime_price(sym) for sym in active_symbols if sym}
                
                if all(price is not None for price in realtime_prices.values()):
                    check_and_manage_open_positions(bnc, state, realtime_prices)
                    handle_stale_trades(bnc, state, realtime_prices)
                    handle_dca_opportunities(bnc, state, available_usdt, total_usdt_at_start, realtime_prices)
                else:
                    missing_symbols = [s for s, p in realtime_prices.items() if p is None]
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
                else: # dynamic
                    report_content = build_dynamic_alert_text(state, final_total_usdt, final_available_usdt, final_realtime_prices, final_equity)
                
                send_discord_message_chunks(report_content, force=True)
                
                pnl_percent_for_alert = ((final_equity - state.get('initial_capital', 1)) / state.get('initial_capital', 1)) * 100 if state.get('initial_capital', 1) > 0 else 0
                state['last_dynamic_alert'] = {"timestamp": now_vn.isoformat(), "total_pnl_percent": pnl_percent_for_alert}

            if 'last_critical_error' in state:
                state['last_critical_error'] = {}

            state["usdt_balance_end_of_last_session"] = final_total_usdt
            state["pnl_closed_last_session"] = state['temp_pnl_from_closed_trades']
            state["money_spent_on_trades_last_session"] = state['temp_money_spent_on_trades']
            save_json_file(STATE_FILE, state)

    except Exception as e:
        error_msg = str(e)
        last_error = state.get('last_critical_error', {})
        now_ts = time.time()
        cooldown_seconds = GENERAL_CONFIG.get("CRITICAL_ERROR_ALERT_COOLDOWN_MINUTES", 30) * 60
        should_alert_discord = True
        if last_error.get('message') == error_msg:
            if (now_ts - last_error.get('timestamp', 0)) < cooldown_seconds:
                should_alert_discord = False

        log_error(f"LỖI TOÀN CỤC NGOÀI DỰ KIẾN", error_details=traceback.format_exc(), send_to_discord=should_alert_discord, state=state)

        if state:
            state['last_critical_error'] = {'message': error_msg, 'timestamp': now_ts}
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
