# live_trade.py
# -*- coding: utf-8 -*-
"""
Live Trade - Phiên bản Hoàn Chỉnh & Sẵn Sàng Triển Khai
Version: 5.1 - "The Guardian"
Date: 2025-07-31

Description:
Phiên bản 5.1 sửa hai lỗi quan trọng:
- FIX: Tích hợp chốt chặn an toàn MAX_SL_PERCENT_BY_TIMEFRAME vào logic mở lệnh,
  ngăn chặn các lệnh có rủi ro quá lớn.
- FIX: Sửa lỗi TypeError trong hàm should_send_dynamic_alert do thiếu tham số.
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
from typing import Dict, List, Any, Tuple, Optional
from dotenv import load_dotenv
import traceback
import numpy as np

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
    sys.exit(f"Lỗi: Không thể import module cần thiết: {e}. Hãy đảm bảo các file binance_connector.py, indicator.py, trade_advisor.py tồn tại.")

# --- CẬP NHẬT ĐƯỜNG DẪN FILE ---
LIVE_DATA_DIR = os.path.join(PROJECT_ROOT, "livetrade", "data")
os.makedirs(LIVE_DATA_DIR, exist_ok=True)

# Sử dụng cache từ backtest để tăng tốc độ khởi động
CACHE_DIR = os.path.join(LIVE_DATA_DIR, "indicator_cache")
os.makedirs(CACHE_DIR, exist_ok=True)


# ==============================================================================
# ================== ⚙️ TRUNG TÂM CẤU HÌNH (ĐỒNG BỘ 1:1 VỚI PAPER_TRADE v4.5.1) ⚙️ ==================
# ==============================================================================

# --- VỐN & CẤU HÌNH CHUNG ---
INITIAL_CAPITAL = 0.0 # Sẽ được tự động ghi nhận trong lần chạy đầu tiên.

GENERAL_CONFIG = {
    "DATA_FETCH_LIMIT": 300,
    "DAILY_SUMMARY_TIMES": ["08:05", "20:05"],
    "TRADE_COOLDOWN_HOURS": 1,
    "CRON_JOB_INTERVAL_MINUTES": 15
}

# --- PHÂN TÍCH ĐA KHUNG THỜI GIAN (MTF) ---
MTF_ANALYSIS_CONFIG = {
    "ENABLED": True,
    "BONUS_COEFFICIENT": 1.15,
    "PENALTY_COEFFICIENT": 0.85,
    "SEVERE_PENALTY_COEFFICIENT": 0.70,
    "SIDEWAYS_PENALTY_COEFFICIENT": 0.90
}

# --- QUẢN LÝ LỆNH ĐANG CHẠY ---
ACTIVE_TRADE_MANAGEMENT_CONFIG = {
    "EARLY_CLOSE_SCORE_THRESHOLD": 4.2,
    "PROFIT_PROTECTION": {
        "ENABLED": True,
        "MIN_PEAK_PNL_TRIGGER": 3.5,
        "PNL_DROP_TRIGGER_PCT": 2.0,
        "PARTIAL_CLOSE_PCT": 0.7
    }
}

# --- CẢNH BÁO ĐỘNG ---
DYNAMIC_ALERT_CONFIG = {
    "ENABLED": True,
    "COOLDOWN_HOURS": 4.5,
    "FORCE_UPDATE_HOURS": 10,
    "PNL_CHANGE_THRESHOLD_PCT": 2.0
}

# --- QUY TẮC QUẢN LÝ RỦI RO ---
RISK_RULES_CONFIG = {
    "MAX_ACTIVE_TRADES": 12,
    "MAX_SL_PERCENT_BY_TIMEFRAME": {
        "1h": 0.06, "4h": 0.08, "1d": 0.10
    },
    "STALE_TRADE_RULES": {
        "1h": {"HOURS": 48, "PROGRESS_THRESHOLD_PCT": 25.0, "MIN_RISK_BUFFER_PCT": 0.2},
        "4h": {"HOURS": 72, "PROGRESS_THRESHOLD_PCT": 25.0, "MIN_RISK_BUFFER_PCT": 0.2},
        "1d": {"HOURS": 168, "PROGRESS_THRESHOLD_PCT": 20.0, "MIN_RISK_BUFFER_PCT": 0.1},
        "STAY_OF_EXECUTION_SCORE": 6.8
    }
}

# --- QUẢN LÝ VỐN TỔNG ---
CAPITAL_MANAGEMENT_CONFIG = {
    "MAX_TOTAL_EXPOSURE_PCT": 0.75
}

# --- TRUNG BÌNH GIÁ (DCA) ---
DCA_CONFIG = {
    "ENABLED": True,
    "MAX_DCA_ENTRIES": 2,
    "TRIGGER_DROP_PCT": -5.0,
    "SCORE_MIN_THRESHOLD": 6.5,
    "CAPITAL_MULTIPLIER": 0.75,
    "DCA_COOLDOWN_HOURS": 8,
    "DCA_REINVEST_RATIO": 0.5
}

# --- CẤU HÌNH THÔNG BÁO ---
ALERT_CONFIG = {
    "DISCORD_WEBHOOK_URL": os.getenv("DISCORD_LIVE_WEBHOOK"),
    "DISCORD_CHUNK_DELAY_SECONDS": 2,
}

# --- PHÒNG THÍ NGHIỆM CHIẾN THUẬT (TACTICS LAB) ---
TACTICS_LAB = {
    "AI_Aggressor": {"NOTES": "Tin vào AI, nhưng vẫn cần sự xác nhận mạnh từ kỹ thuật.", "WEIGHTS": {'tech': 0.3, 'context': 0.1, 'ai': 0.6}, "ENTRY_SCORE": 6.8, "RR": 2.0, "USE_ATR_SL": True, "ATR_SL_MULTIPLIER": 2.8, "USE_TRAILING_SL": True, "TRAIL_ACTIVATION_RR": 1.2, "TRAIL_DISTANCE_RR": 0.8, "ENABLE_PARTIAL_TP": True, "TP1_RR_RATIO": 1.0, "TP1_PROFIT_PCT": 0.4},
    "Balanced_Trader": {"NOTES": "Chiến binh chủ lực, cân bằng giữa kỹ thuật và AI.", "WEIGHTS": {'tech': 0.4, 'context': 0.2, 'ai': 0.4}, "ENTRY_SCORE": 6.2, "RR": 1.8, "USE_ATR_SL": True, "ATR_SL_MULTIPLIER": 2.2, "USE_TRAILING_SL": True, "TRAIL_ACTIVATION_RR": 1.2, "TRAIL_DISTANCE_RR": 1.0, "ENABLE_PARTIAL_TP": True, "TP1_RR_RATIO": 1.0, "TP1_PROFIT_PCT": 0.6},
    "Dip_Hunter": {"NOTES": "Bắt đáy/bắt sóng hồi, dựa nhiều vào tín hiệu kỹ thuật và bối cảnh.", "WEIGHTS": {'tech': 0.6, 'context': 0.2, 'ai': 0.2}, "ENTRY_SCORE": 6.5, "RR": 1.8, "USE_ATR_SL": True, "ATR_SL_MULTIPLIER": 2.0, "USE_TRAILING_SL": False, "TRAIL_ACTIVATION_RR": None, "ENABLE_PARTIAL_TP": True, "TP1_RR_RATIO": 0.7, "TP1_PROFIT_PCT": 0.7},
    "Breakout_Hunter": {"NOTES": "Săn đột phá, ưu tiên tuyệt đối tín hiệu kỹ thuật.", "WEIGHTS": {'tech': 0.7, 'context': 0.1, 'ai': 0.2}, "ENTRY_SCORE": 7.0, "RR": 2.0, "USE_ATR_SL": True, "ATR_SL_MULTIPLIER": 1.8, "USE_TRAILING_SL": True, "TRAIL_ACTIVATION_RR": 1.0, "TRAIL_DISTANCE_RR": 0.8, "ENABLE_PARTIAL_TP": True, "TP1_RR_RATIO": 1.2, "TP1_PROFIT_PCT": 0.5},
    "Cautious_Observer": {"NOTES": "Chỉ đánh khi có cơ hội VÀNG, siêu an toàn, dựa chủ yếu vào kỹ thuật và bối cảnh.", "WEIGHTS": {'tech': 0.7, 'context': 0.2, 'ai': 0.1}, "ENTRY_SCORE": 8.0, "RR": 1.5, "USE_ATR_SL": True, "ATR_SL_MULTIPLIER": 1.5, "USE_TRAILING_SL": True, "TRAIL_ACTIVATION_RR": 0.7, "TRAIL_DISTANCE_RR": 0.5, "ENABLE_PARTIAL_TP": True, "TP1_RR_RATIO": 0.8, "TP1_PROFIT_PCT": 0.5},
}

# --- BỘ LỌC CHIẾN THUẬT ---
STATE_TO_TACTICS_MAP = {
    "STATE_DIP_HUNTING": ["Dip_Hunter", "Balanced_Trader", "Cautious_Observer"],
    "STATE_BREAKOUT_WAITING": ["Breakout_Hunter", "AI_Aggressor"],
    "STATE_STRONG_TREND": ["Breakout_Hunter", "AI_Aggressor", "Balanced_Trader"],
    "STATE_CHOPPY": ["Cautious_Observer"],
    "STATE_UNCERTAIN": []
}

# ==============================================================================
# CÁC BIẾN TOÀN CỤC VÀ HẰNG SỐ
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

# ==============================================================================
# === CÁC HÀM TIỆN ÍCH, QUẢN LÝ & BÁO CÁO ===
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
    data_to_save.pop('temp_newly_opened_trades', None)
    data_to_save.pop('temp_newly_closed_trades', None)
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(data_to_save, f, indent=4, ensure_ascii=False)
    os.replace(temp_path, path)

def send_discord_message_chunks(full_content: str):
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
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        return float(response.json()['price'])
    except Exception:
        return None

def get_current_pnl(trade: Dict, realtime_price: Optional[float] = None) -> Tuple[float, float]:
    if not (trade and trade.get('entry_price', 0) > 0): return 0.0, 0.0
    
    current_price = realtime_price
    if current_price is None: # Fallback to indicator price if no realtime price
        current_data = indicator_results.get(trade["symbol"], {}).get(trade["interval"])
        if current_data and current_data.get('price', 0) > 0:
            current_price = current_data['price']

    if current_price is None or current_price <= 0: return 0.0, 0.0
    
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
        
        cols = ["trade_id", "symbol", "interval", "status", "opened_by_tactic", "tactic_used","trade_type", "entry_price", "exit_price", "tp", "sl", "total_invested_usd","pnl_usd", "pnl_percent", "entry_time", "exit_time", "holding_duration_hours","entry_score", "dca_entries"]
        df = df[[c for c in cols if c in df.columns]]
        
        header_mismatch = False
        if os.path.exists(TRADE_HISTORY_CSV_FILE):
            try:
                if set(pd.read_csv(TRADE_HISTORY_CSV_FILE, nrows=0).columns.tolist()) != set(df.columns.tolist()): header_mismatch = True
            except Exception: header_mismatch = True
        
        df.to_csv(TRADE_HISTORY_CSV_FILE, mode='a' if os.path.exists(TRADE_HISTORY_CSV_FILE) and not header_mismatch else 'w', header=not os.path.exists(TRADE_HISTORY_CSV_FILE) or header_mismatch, index=False, encoding="utf-8")
        log_message(f"✅ Đã xuất {len(df)} lệnh đã đóng vào {TRADE_HISTORY_CSV_FILE}")
    except Exception as e:
        log_message(f"❌ Lỗi khi xuất lịch sử giao dịch ra CSV: {e}")

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

def get_usdt_fund(bnc: BinanceConnector) -> Tuple[float, float]:
    """Lấy số dư USDT khả dụng và tổng số dư từ Binance."""
    try:
        balance_info = bnc.get_account_balance()
        usdt_balance = next((b for b in balance_info.get("balances", []) if b["asset"] == "USDT"), None)
        if usdt_balance:
            available_usdt = float(usdt_balance['free'])
            total_usdt = float(usdt_balance['free']) + float(usdt_balance['locked'])
            return available_usdt, total_usdt
    except Exception as e:
        log_message(f"❌ Không thể lấy số dư USDT từ Binance: {e}")
    return 0.0, 0.0

def determine_dynamic_capital_pct(atr_percent: float) -> float:
    if pd.isna(atr_percent): return 0.03
    if atr_percent <= 1.5: return 0.10
    elif atr_percent <= 3: return 0.07
    elif atr_percent <= 5: return 0.05
    else: return 0.03

def calculate_average_price(trade: Dict) -> float:
    entries = [trade['initial_entry']] + trade.get('dca_entries', [])
    total_cost = sum(e.get('invested_usd', 0.0) for e in entries)
    total_qty = sum(e.get('quantity', 0.0) for e in entries)
    return total_cost / total_qty if total_qty > 0 else 0

# ==============================================================================
# === LOGIC TƯƠNG TÁC BINANCE & QUẢN LÝ LỆNH ===
# ==============================================================================
def close_trade_on_binance(bnc: BinanceConnector, trade: Dict, reason: str, state: Dict, exit_price: Optional[float] = None):
    """Quy trình chuẩn để đóng một vị thế trên Binance và cập nhật state (đã cải tiến)."""
    log_message(f"🎬 Bắt đầu quy trình đóng lệnh cho {trade['symbol']} vì: {reason}")
    try:
        # Hủy OCO trước để tránh lỗi
        bnc.cancel_order(trade['symbol'], trade['binance_oco_order_list_id'])
        log_message(f"  -> ✅ Đã hủy OCO ID: {trade['binance_oco_order_list_id']}")
    except Exception as e:
        log_message(f"  -> ⚠️ Cảnh báo: Không thể hủy OCO (có thể đã bị hit hoặc không tồn tại): {e}")

    try:
        side = "SELL" if trade['trade_type'] == 'LONG' else "BUY"
        market_close_order = bnc.place_market_order(symbol=trade['symbol'], side=side, quantity=trade['quantity'])
        
        if not (market_close_order and float(market_close_order.get('executedQty', 0)) > 0):
            raise Exception(f"Lệnh Market đóng không khớp. Status: {market_close_order.get('status')}, ExecutedQty: {market_close_order.get('executedQty')}")

        final_exit_price = float(market_close_order['cummulativeQuoteQty']) / float(market_close_order['executedQty'])
        
        pnl_usd = (final_exit_price - trade['entry_price']) * float(trade['quantity']) * (1 if trade['trade_type'] == 'LONG' else -1)
        pnl_percent = (final_exit_price - trade['entry_price']) / trade['entry_price'] * 100 * (1 if trade['trade_type'] == 'LONG' else -1)

        trade.update({
            'status': f'Closed ({reason})', 'exit_price': final_exit_price,
            'exit_time': datetime.now(VIETNAM_TZ).isoformat(),
            'pnl_usd': pnl_usd, 'pnl_percent': pnl_percent
        })
        
        state['active_trades'].remove(trade)
        state['trade_history'].append(trade)
        cooldown_end = datetime.now(VIETNAM_TZ) + timedelta(hours=GENERAL_CONFIG["TRADE_COOLDOWN_HOURS"])
        state.setdefault('cooldown_until', {})[trade['symbol']] = cooldown_end.isoformat()
        
        export_trade_history_to_csv([trade])
        icon = '🐌' if 'Stale' in reason else ('🛡️' if 'Protect' in reason else ('🚨' if 'Early' in reason else ('✅' if pnl_usd >= 0 else '❌')))
        msg = f"{icon} {trade['symbol']} ({reason}): PnL ${pnl_usd:,.2f}"
        state.setdefault('temp_newly_closed_trades', []).append(msg)
        log_message(f"  -> ✅ Đã đóng thành công {trade['symbol']}. PnL: ${pnl_usd:,.2f}")

    except Exception as e:
        log_message(f"🔥🔥🔥 LỖI NGHIÊM TRỌNG: Đã hủy OCO nhưng không thể đóng vị thế {trade['symbol']}. CẦN CAN THIỆP THỦ CÔNG! Lỗi: {e}")
        send_discord_message_chunks(f"🔥🔥🔥 LỖI ĐÓNG LỆNH NGHIÊM TRỌNG 🔥🔥🔥\nĐã hủy OCO nhưng không thể đóng vị thế `{trade['symbol']}`. **CẦN CAN THIỆP THỦ CÔNG NGAY!**")

def sync_state_with_binance(bnc: BinanceConnector, local_state: Dict) -> Dict:
    """Đồng bộ state cục bộ với các lệnh thực tế trên sàn."""
    log_message("🔄 Bắt đầu đồng bộ trạng thái với Binance...")
    synced_state = local_state.copy()
    active_local_trades = synced_state.get('active_trades', [])
    if not active_local_trades:
        log_message("✅ Không có lệnh nào trong state cục bộ để đồng bộ.")
        return synced_state

    try:
        open_orders_on_binance = bnc.get_open_orders()
        if open_orders_on_binance is None:
            log_message("⚠️ Không thể lấy danh sách lệnh đang mở. Bỏ qua đồng bộ.")
            return synced_state

        open_oco_ids = {order['orderListId'] for order in open_orders_on_binance if order.get('orderListId', -1) != -1}

        for trade in active_local_trades[:]:
            oco_id = trade.get('binance_oco_order_list_id')
            if oco_id not in open_oco_ids:
                log_message(f"🔍 Phát hiện OCO cho {trade['symbol']} (ID: {oco_id}) không còn trên sàn. Điều tra...")
                trade['status'] = 'Closed (SYNC_OCO_MISSING)'
                trade['exit_time'] = datetime.now(VIETNAM_TZ).isoformat()
                trade['pnl_usd'], trade['pnl_percent'] = 0.0, 0.0
                synced_state['active_trades'].remove(trade)
                synced_state.setdefault('trade_history', []).append(trade)
                export_trade_history_to_csv([trade])
                log_message(f"➡️ Đã di chuyển lệnh {trade['symbol']} vào lịch sử. Cần xác minh PnL thủ công.")
                send_discord_message_chunks(f"🔔 **Cần chú ý:** Lệnh OCO cho `{trade['symbol']}` không còn trên sàn. Bot đã tự động đóng vị thế trong state. Vui lòng kiểm tra và cập nhật PnL thủ công nếu cần.")
        log_message("✅ Đồng bộ trạng thái hoàn tất.")
    except Exception as e:
        log_message(f"❌ Lỗi trong quá trình đồng bộ: {e}")
    return synced_state

# ==============================================================================
# === LOGIC GIAO DỊCH CỐT LÕI (TÍCH HỢP TỪ PAPER_TRADE) ===
# ==============================================================================

def manage_active_trades(bnc: BinanceConnector, state: Dict):
    """Quản lý các lệnh đang chạy: Cắt sớm, Bảo vệ lợi nhuận, Trailing SL."""
    log_message("🧠 Bắt đầu chu trình Quản lý Lệnh Chủ động...")
    for trade in state.get("active_trades", [])[:]:
        indicators = indicator_results.get(trade['symbol'], {}).get(trade['interval'])
        if not (indicators and indicators.get('price')): continue

        decision = get_advisor_decision(trade['symbol'], trade['interval'], indicators, ADVISOR_BASE_CONFIG)
        new_score = decision.get("final_score", 0.0)
        trade['last_score'] = new_score
        
        pnl_usd, pnl_percent = get_current_pnl(trade, realtime_price=indicators.get('price'))
        trade['peak_pnl_percent'] = max(trade.get('peak_pnl_percent', 0.0), pnl_percent)

        if new_score < ACTIVE_TRADE_MANAGEMENT_CONFIG['EARLY_CLOSE_SCORE_THRESHOLD']:
            log_message(f"🚨 CẮT LỖ SỚM cho {trade['symbol']}. Điểm mới ({new_score:.2f}) quá thấp.")
            close_trade_on_binance(bnc, trade, f"Early_Close_@{new_score:.1f}", state)
            continue

        pp_config = ACTIVE_TRADE_MANAGEMENT_CONFIG.get("PROFIT_PROTECTION", {})
        if (pp_config.get("ENABLED", False) and not trade.get('profit_taken', False) and
            trade['peak_pnl_percent'] >= pp_config.get("MIN_PEAK_PNL_TRIGGER", 3.5)):
            
            pnl_drop = trade['peak_pnl_percent'] - pnl_percent
            if pnl_drop >= pp_config.get("PNL_DROP_TRIGGER_PCT", 2.0):
                log_message(f"🛡️ BẢO VỆ LỢI NHUẬN cho {trade['symbol']}. PnL giảm {pnl_drop:.2f}% từ đỉnh.")
                try:
                    bnc.cancel_order(trade['symbol'], trade['binance_oco_order_list_id'])
                    
                    close_pct = pp_config.get("PARTIAL_CLOSE_PCT", 0.7)
                    qty_to_close = float(trade['quantity']) * close_pct
                    side = "SELL" if trade['trade_type'] == 'LONG' else "BUY"
                    market_partial_close = bnc.place_market_order(symbol=trade['symbol'], side=side, quantity=qty_to_close)
                    if not (market_partial_close and market_partial_close.get('status') == 'FILLED'):
                        raise Exception("Lệnh market chốt lời một phần thất bại.")
                    
                    closed_qty = float(market_partial_close['executedQty'])
                    closed_value = float(market_partial_close['cummulativeQuoteQty'])
                    realized_pnl = (closed_value / closed_qty - trade['entry_price']) * closed_qty * (1 if trade['trade_type'] == 'LONG' else -1)
                    
                    trade['realized_pnl_usd'] = trade.get('realized_pnl_usd', 0.0) + realized_pnl
                    trade['quantity'] = float(trade['quantity']) - closed_qty
                    trade['total_invested_usd'] -= (trade['total_invested_usd'] / (float(trade['quantity']) + closed_qty)) * closed_qty
                    trade['profit_taken'] = True
                    trade['sl'] = trade['entry_price']

                    new_oco = bnc.create_oco_order(symbol=trade['symbol'], side=side, quantity=trade['quantity'], price=trade['tp'], stop_price=trade['sl'], stop_limit_price=trade['sl'])
                    if not (new_oco and new_oco.get('orderListId', -1) != -1):
                        raise Exception("Không thể đặt lại OCO mới sau khi chốt lời một phần.")
                    
                    trade['binance_oco_order_list_id'] = new_oco['orderListId']
                    log_message(f"✅ Chốt lời một phần và đặt lại OCO (ID: {new_oco['orderListId']}) cho {trade['symbol']} thành công.")
                    state.setdefault('temp_newly_closed_trades', []).append(f"🛡️ {trade['symbol']} (Bảo vệ LN): PnL ${realized_pnl:,.2f}")
                except Exception as e:
                     log_message(f"🔥🔥🔥 LỖI NGHIÊM TRỌNG KHI BẢO VỆ LỢI NHUẬN {trade['symbol']}. CẦN CAN THIỆP THỦ CÔNG! Lỗi: {e}")
                     send_discord_message_chunks(f"🔥🔥🔥 LỖI BẢO VỆ LỢI NHUẬN 🔥🔥🔥\nBot gặp lỗi khi chốt lời một phần cho `{trade['symbol']}`. **CẦN CAN THIỆP THỦ CÔNG NGAY!**")
                     close_trade_on_binance(bnc, trade, "EMERGENCY_PROTECT_FAIL", state)
                continue

        tactic_cfg = TACTICS_LAB.get(trade.get('opened_by_tactic', trade.get('controlling_tactic')), {})
        if tactic_cfg.get("USE_TRAILING_SL", False):
            realtime_price = get_realtime_price(trade['symbol'])
            if not realtime_price: continue

            initial_risk_dist = abs(trade['initial_entry']['price'] - trade['initial_sl'])
            if initial_risk_dist <= 0: continue

            pnl_ratio = (realtime_price - trade['entry_price']) / initial_risk_dist * (1 if trade['trade_type'] == 'LONG' else -1)
            
            trail_activation_rr = tactic_cfg.get("TRAIL_ACTIVATION_RR")
            if trail_activation_rr is not None and pnl_ratio >= trail_activation_rr:
                trail_dist_rr = tactic_cfg.get("TRAIL_DISTANCE_RR", 0.8)
                new_sl = realtime_price - (initial_risk_dist * trail_dist_rr * (1 if trade['trade_type'] == 'LONG' else -1))
                
                is_better_tsl = (new_sl > trade['sl']) if trade['trade_type'] == 'LONG' else (new_sl < trade['sl'])
                if is_better_tsl:
                    log_message(f"📈 Kích hoạt TSL cho {trade['symbol']}! SL mới: {new_sl:.4f} (cũ: {trade['sl']:.4f})")
                    try:
                        bnc.cancel_order(trade['symbol'], trade['binance_oco_order_list_id'])
                        time.sleep(1)
                        side = "SELL" if trade['trade_type'] == 'LONG' else "BUY"
                        new_oco = bnc.create_oco_order(symbol=trade['symbol'], side=side, quantity=trade['quantity'], price=trade['tp'], stop_price=new_sl, stop_limit_price=new_sl)
                        if not (new_oco and new_oco.get('orderListId', -1) != -1):
                            raise Exception("Không thể đặt lại OCO mới cho TSL.")
                        
                        trade['sl'] = new_sl
                        trade['binance_oco_order_list_id'] = new_oco['orderListId']
                        trade.setdefault('tactic_used', []).append("Trailing_SL_Active")
                        log_message(f"✅ Cập nhật TSL cho {trade['symbol']} thành công. OCO ID mới: {new_oco['orderListId']}")
                    except Exception as e:
                        log_message(f"🔥🔥🔥 LỖI NGHIÊM TRỌNG KHI CẬP NHẬT TSL CHO {trade['symbol']}. CẦN CAN THIỆP THỦ CÔNG! Lỗi: {e}")
                        send_discord_message_chunks(f"🔥🔥🔥 LỖI TSL 🔥🔥🔥\nBot gặp lỗi khi cập nhật TSL cho `{trade['symbol']}`. **Vị thế có thể không được bảo vệ bởi SL! CẦN CAN THIỆP THỦ CÔNG NGAY!**")

def handle_stale_trades(bnc: BinanceConnector, state: Dict):
    """Xử lý các lệnh bị 'ì' (giữ quá lâu mà không có tiến triển)."""
    log_message("⏳ Bắt đầu kiểm tra các lệnh bị 'ì'...")
    now_aware = datetime.now(VIETNAM_TZ)
    for trade in state.get("active_trades", [])[:]:
        rules = RISK_RULES_CONFIG["STALE_TRADE_RULES"].get(trade.get("interval"))
        if not rules: continue

        entry_time = datetime.fromisoformat(trade['entry_time'])
        holding_hours = (now_aware - entry_time).total_seconds() / 3600

        if holding_hours > rules["HOURS"]:
            _, pnl_pct = get_current_pnl(trade)
            latest_score = trade.get('last_score', 5.0)
            
            if pnl_pct < rules["PROGRESS_THRESHOLD_PCT"] and latest_score < RISK_RULES_CONFIG["STALE_TRADE_RULES"]["STAY_OF_EXECUTION_SCORE"]:
                log_message(f"🐌 Phát hiện lệnh 'ì': {trade['symbol']} ({trade['interval']}) giữ {holding_hours:.1f}h không có tiến triển.")
                close_trade_on_binance(bnc, trade, "Stale", state)
            elif pnl_pct < rules["PROGRESS_THRESHOLD_PCT"]:
                 log_message(f"⏳ Lệnh {trade['symbol']} đã quá hạn nhưng được GIA HẠN do tín hiệu mới tốt (Điểm: {latest_score:.2f})")

def handle_dca_opportunities(bnc: BinanceConnector, state: Dict, available_usdt: float, total_usdt_fund: float):
    """Tìm và thực hiện các cơ hội Trung bình giá (DCA)."""
    if not DCA_CONFIG["ENABLED"]: return
    log_message("🎯 Bắt đầu quét cơ hội DCA...")
    
    current_exposure_usd = total_usdt_fund - available_usdt
    exposure_limit = total_usdt_fund * CAPITAL_MANAGEMENT_CONFIG["MAX_TOTAL_EXPOSURE_PCT"]

    for trade in state.get("active_trades", [])[:]:
        if len(trade.get("dca_entries", [])) >= DCA_CONFIG["MAX_DCA_ENTRIES"]: continue

        current_data = indicator_results.get(trade["symbol"], {}).get(trade["interval"], {})
        current_price = current_data.get('price', 0)
        if not current_price > 0: continue
        
        last_entry_price = trade['dca_entries'][-1]['price'] if trade.get('dca_entries') else trade['initial_entry']['price']
        price_drop_pct = ((current_price - last_entry_price) / last_entry_price) * 100
        
        if price_drop_pct > DCA_CONFIG["TRIGGER_DROP_PCT"]: continue
        
        decision = get_advisor_decision(trade['symbol'], trade['interval'], current_data, ADVISOR_BASE_CONFIG)
        if decision.get("final_score", 0.0) < DCA_CONFIG["SCORE_MIN_THRESHOLD"]: continue

        dca_investment = 0
        if trade.get('profit_taken', False) and trade.get('realized_pnl_usd', 0.0) > 0:
            reinvest_ratio = DCA_CONFIG.get("DCA_REINVEST_RATIO", 0.5)
            dca_investment = min(trade['realized_pnl_usd'], trade['initial_entry']['invested_usd'] * reinvest_ratio)
            log_message(f"🎯 THỰC HIỆN DCA TÁI ĐẦU TƯ LỢI NHUẬN cho {trade['symbol']} với ${dca_investment:,.2f}...")
        else:
            last_investment = trade['dca_entries'][-1]['invested_usd'] if trade.get('dca_entries') else trade['initial_entry']['invested_usd']
            dca_investment = last_investment * DCA_CONFIG["CAPITAL_MULTIPLIER"]
            log_message(f"🎯 THỰC HIỆN DCA GỐC cho {trade['symbol']} với ${dca_investment:,.2f}...")

        if dca_investment <= 0: continue
        if dca_investment > available_usdt or (current_exposure_usd + dca_investment) > exposure_limit:
            log_message(f"⚠️ Muốn DCA cho {trade['symbol']} nhưng không đủ vốn hoặc vượt ngưỡng rủi ro.")
            continue

        try:
            side = "BUY" if trade['trade_type'] == 'LONG' else "SELL"
            market_dca_order = bnc.place_market_order(symbol=trade['symbol'], side=side, quote_order_qty=round(dca_investment, 2))
            if not (market_dca_order and market_dca_order.get('status') == 'FILLED'):
                raise Exception("Lệnh Market DCA không khớp.")
            
            bnc.cancel_order(trade['symbol'], trade['binance_oco_order_list_id'])
            
            dca_qty = float(market_dca_order['executedQty'])
            dca_cost = float(market_dca_order['cummulativeQuoteQty'])
            dca_price = dca_cost / dca_qty
            
            new_total_qty = float(trade['quantity']) + dca_qty
            new_total_cost = trade['total_invested_usd'] + dca_cost
            new_avg_price = new_total_cost / new_total_qty
            
            initial_risk_dist = abs(trade['initial_entry']['price'] - trade['initial_sl'])
            new_sl = new_avg_price - initial_risk_dist * (1 if trade['trade_type'] == 'LONG' else -1)
            new_tp = new_avg_price + (initial_risk_dist * TACTICS_LAB[trade['opened_by_tactic']]['RR'] * (1 if trade['trade_type'] == 'LONG' else -1))
            
            new_oco = bnc.create_oco_order(symbol=trade['symbol'], side="SELL", quantity=new_total_qty, price=new_tp, stop_price=new_sl, stop_limit_price=new_sl)
            if not (new_oco and new_oco.get('orderListId', -1) != -1):
                raise Exception("Không thể đặt lại OCO mới sau khi DCA.")

            trade['dca_entries'].append({"price": dca_price, "quantity": dca_qty, "invested_usd": dca_cost, "timestamp": datetime.now(VIETNAM_TZ).isoformat()})
            trade.update({
                'entry_price': new_avg_price, 'total_invested_usd': new_total_cost, 'quantity': new_total_qty,
                'sl': new_sl, 'tp': new_tp, 'binance_oco_order_list_id': new_oco['orderListId'],
                'profit_taken': False, 'peak_pnl_percent': 0.0
            })
            trade.setdefault('tactic_used', []).append(f"DCA_{len(trade.get('dca_entries', []))}")
            log_message(f"✅ DCA thành công. Vị thế mới của {trade['symbol']}: Qty={new_total_qty}, Giá TB={new_avg_price:.4f}")

        except Exception as e:
            log_message(f"🔥🔥🔥 LỖI NGHIÊM TRỌNG KHI DCA {trade['symbol']}. CẦN CAN THIỆP THỦ CÔNG! Lỗi: {e}")
            send_discord_message_chunks(f"🔥🔥🔥 LỖI DCA NGHIÊM TRỌNG 🔥🔥🔥\nBot gặp lỗi khi DCA cho `{trade['symbol']}`. **CẦN CAN THIỆP THỦ CÔNG NGAY!**")
            close_trade_on_binance(bnc, trade, "EMERGENCY_DCA_FAIL", state)

def find_and_open_new_trades(bnc: BinanceConnector, state: Dict, available_usdt: float, total_usdt_fund: float):
    """
    Tìm và mở lệnh mới. Ép SL/TP về đúng trần an toàn nếu ATR quá lớn.
    """
    active_trades = state.get('active_trades', [])
    if len(active_trades) >= RISK_RULES_CONFIG["MAX_ACTIVE_TRADES"]:
        log_message(f"ℹ️ Đã đạt giới hạn {len(active_trades)}/{RISK_RULES_CONFIG['MAX_ACTIVE_TRADES']} lệnh.")
        return

    current_exposure_usd = total_usdt_fund - available_usdt
    exposure_limit = total_usdt_fund * CAPITAL_MANAGEMENT_CONFIG["MAX_TOTAL_EXPOSURE_PCT"]
    log_message(f"🏦 Quỹ USDT: ${total_usdt_fund:,.2f} | Vốn đã dùng: ${current_exposure_usd:,.2f} | Hạn mức: ${exposure_limit:,.2f}")

    potential_opportunities = []
    log_message(f"🔎 Bắt đầu quét cơ hội lệnh LONG...")
    now_vn = datetime.now(VIETNAM_TZ)

    try:
        all_open_orders_on_binance = bnc.get_open_orders()
        if all_open_orders_on_binance is None: return
    except Exception as e:
        log_message(f"❌ Lỗi lấy danh sách lệnh mở: {e}. Tạm dừng.")
        return

    # Quét cơ hội (logic này giữ nguyên)
    for symbol in SYMBOLS_TO_SCAN:
        if any(t['symbol'] == symbol for t in active_trades): continue
        cooldown_map = state.get('cooldown_until', {})
        if symbol in cooldown_map and now_vn < datetime.fromisoformat(cooldown_map[symbol]): continue
        if any(order['symbol'] == symbol for order in all_open_orders_on_binance):
            log_message(f"🛡️ CẢNH BÁO: Đã phát hiện lệnh đang mở cho {symbol} trên Binance nhưng không có trong state. Bỏ qua.")
            continue
        for interval in INTERVALS_TO_SCAN:
            indicators = indicator_results.get(symbol, {}).get(interval)
            df_data = price_dataframes.get(symbol, {}).get(interval)
            if not (indicators and indicators.get('price', 0) > 0 and df_data is not None): continue
            market_state = determine_market_state(symbol, interval, df_data)
            allowed_tactics = STATE_TO_TACTICS_MAP.get(market_state, [])
            if not allowed_tactics: continue
            for tactic_name in allowed_tactics:
                tactic_cfg = TACTICS_LAB[tactic_name]
                decision = get_advisor_decision(symbol, interval, indicators, ADVISOR_BASE_CONFIG, weights_override=tactic_cfg.get("WEIGHTS"))
                adjusted_score = decision.get("final_score", 0.0) * get_mtf_adjustment_coefficient(symbol, interval, "LONG")
                if adjusted_score >= tactic_cfg.get("ENTRY_SCORE", 9.9):
                    potential_opportunities.append({"decision": decision, "tactic_name": tactic_name, "tactic_cfg": tactic_cfg, "score": adjusted_score, "symbol": symbol, "interval": interval, "trade_type": "LONG"})

    if not potential_opportunities:
        log_message("ℹ️ Phiên này không tìm thấy cơ hội nào đủ điều kiện.")
        return

    best_opportunity = sorted(potential_opportunities, key=lambda x: x['score'], reverse=True)[0]
    decision_data, tactic_name, tactic_cfg = best_opportunity['decision'], best_opportunity['tactic_name'], best_opportunity['tactic_cfg']
    symbol, interval, score, trade_type = best_opportunity['symbol'], best_opportunity['interval'], best_opportunity['score'], best_opportunity['trade_type']

    log_message(f"🏆 CƠ HỘI TỐT NHẤT: {symbol}-{interval} | Tactic: {tactic_name} | Điểm: {score:.2f}")

    full_indicators = decision_data.get('full_indicators', {})
    entry_price_estimate = full_indicators.get('price')
    if not entry_price_estimate or entry_price_estimate <= 0: return

    # ========= 🔥 ĐOẠN SỬA LỖI TRỰC TIẾP & NGẮN GỌN 🔥 =========
    # 1. Tính risk_dist dựa trên ATR như bình thường
    risk_dist_from_atr = full_indicators.get('atr', 0) * tactic_cfg.get("ATR_SL_MULTIPLIER", 2.0)

    # 2. Tính risk_dist tối đa cho phép theo %
    max_sl_pct = RISK_RULES_CONFIG["MAX_SL_PERCENT_BY_TIMEFRAME"].get(interval)
    if max_sl_pct is None:
        log_message(f"⚠️ Không có cấu hình MAX_SL_PERCENT cho {interval}. Bỏ qua.")
        return
    max_risk_dist_allowed = entry_price_estimate * max_sl_pct
    
    # 3. Chọn risk_dist cuối cùng: Lấy cái NHỎ HƠN giữa 2 cái trên
    final_risk_dist = min(risk_dist_from_atr, max_risk_dist_allowed)
    
    if final_risk_dist == max_risk_dist_allowed and risk_dist_from_atr > max_risk_dist_allowed:
        log_message(f"  -> 🛡️ ATR quá lớn! Ép rủi ro về mức trần an toàn ({max_sl_pct:.2%}).")
    
    if final_risk_dist <= 0: return
    # =============================================================

    # Tính vốn và kiểm tra (giữ nguyên)
    capital_pct = determine_dynamic_capital_pct(full_indicators.get('atr_percent', 3.0))
    invested_amount = total_usdt_fund * capital_pct
    if invested_amount > available_usdt: invested_amount = available_usdt * 0.98
    if (current_exposure_usd + invested_amount) > exposure_limit or invested_amount < 10:
        log_message(f"⚠️ Vào lệnh ${invested_amount:,.2f} sẽ vượt ngưỡng hoặc quá nhỏ. Bỏ qua.")
        return

    # Thực thi lệnh
    try:
        log_message(f"🔥 THỰC THI LỆNH MỚI: {trade_type} {symbol} với ${invested_amount:,.2f}")
        market_order = bnc.place_market_order(symbol=symbol, side="BUY", quote_order_qty=round(invested_amount, 2))
        if not (market_order and float(market_order.get('executedQty', 0)) > 0): raise Exception("Lệnh Market không khớp")

        filled_qty = float(market_order['executedQty'])
        avg_price = float(market_order['cummulativeQuoteQty']) / filled_qty
        
        # Dùng final_risk_dist đã được "ép" để tính SL/TP
        sl_p = avg_price - final_risk_dist
        tp_p = avg_price + (final_risk_dist * tactic_cfg.get("RR", 2.0))

        log_message(f"🛡️ Chuẩn bị đặt OCO: Qty={filled_qty}, TP={tp_p:.4f}, SL={sl_p:.4f}")
        oco_order = bnc.create_oco_order(symbol=symbol, side="SELL", quantity=filled_qty, price=tp_p, stop_price=sl_p, stop_limit_price=sl_p)
        if not (oco_order and oco_order.get('orderListId', -1) != -1): raise Exception("Không đặt được OCO")

        # Lưu state (giữ nguyên)
        new_trade = {
            "trade_id": str(uuid.uuid4()), "symbol": symbol, "interval": interval, "status": "ACTIVE",
            "opened_by_tactic": tactic_name, "trade_type": trade_type, "entry_price": avg_price,
            "quantity": filled_qty, "tp": tp_p, "sl": sl_p, "initial_sl": sl_p,
            "total_invested_usd": float(market_order['cummulativeQuoteQty']),
            "initial_entry": {"price": avg_price, "quantity": filled_qty, "invested_usd": float(market_order['cummulativeQuoteQty'])},
            "entry_time": now_vn.isoformat(), "entry_score": score,
            "binance_market_order_id": market_order['orderId'],
            "binance_oco_order_list_id": oco_order['orderListId'],
            "dca_entries": [], "profit_taken": False, "peak_pnl_percent": 0.0, "realized_pnl_usd": 0.0
        }
        state['active_trades'].append(new_trade)
        log_message(f"💾 Đã lưu lệnh mới vào state. OCO ID: {oco_order['orderListId']}")
        state.setdefault('temp_newly_opened_trades', []).append(f"🔥 {symbol}-{interval} ({tactic_name}): Vốn ${float(market_order['cummulativeQuoteQty']):,.2f}")

    except Exception as e:
        log_message(f"❌ LỖI NGHIÊM TRỌNG khi thực thi lệnh {symbol}: {e}\n{traceback.format_exc()}")
        send_discord_message_chunks(f"🔥🔥🔥 LỖI THỰC THI LỆNH 🔥🔥🔥\nBot gặp lỗi khi cố gắng mở lệnh cho `{symbol}`. Chi tiết:\n```python\n{traceback.format_exc()}\n```")

def determine_market_state(symbol: str, interval: str, df: pd.DataFrame) -> str:
    """Xác định bối cảnh thị trường (đã sửa lỗi KeyError)."""
    indicators = indicator_results.get(symbol, {}).get(interval, {})
    if not indicators or df.empty:
        return "STATE_UNCERTAIN"

    if 'bb_width' not in df.columns:
        try:
            window = 20; std_dev = 2
            close_prices = df['close']
            rolling_mean = close_prices.rolling(window=window).mean()
            rolling_std = close_prices.rolling(window=window).std()
            upper_band = rolling_mean + (rolling_std * std_dev)
            lower_band = rolling_mean - (rolling_std * std_dev)
            df = df.copy()
            df.loc[:, 'bb_width'] = (upper_band - lower_band) / (rolling_mean + 1e-9)
        except Exception as e:
            log_message(f"⚠️ Không thể tính bb_width cho {symbol}-{interval}: {e}")
            pass

    if 'bb_width' in indicators and pd.notna(indicators['bb_width']) and 'bb_width' in df.columns:
        bb_width_current = indicators['bb_width']
        recent_bbw = df['bb_width'].dropna().tail(100)
        if not recent_bbw.empty:
            squeeze_threshold = recent_bbw.quantile(0.25)
            if bb_width_current < squeeze_threshold:
                return "STATE_BREAKOUT_WAITING"

    trend = indicators.get('trend')
    adx = indicators.get('adx', 0)
    if trend in ["uptrend", "downtrend"] and adx > 25:
        return "STATE_STRONG_TREND"

    rsi = indicators.get('rsi_14', 50)
    higher_tf = '4h' if interval == '1h' else '1d'
    higher_tf_trend = indicator_results.get(symbol, {}).get(higher_tf, {}).get('trend')
    if higher_tf_trend == "uptrend" and rsi < 40:
        return "STATE_DIP_HUNTING"

    if adx < 20:
        return "STATE_CHOPPY"

    return "STATE_UNCERTAIN"

def get_mtf_adjustment_coefficient(symbol: str, target_interval: str, trade_type: str = "LONG") -> float:
    if not MTF_ANALYSIS_CONFIG["ENABLED"]: return 1.0
    trends = {tf: indicator_results.get(symbol, {}).get(tf, {}).get("trend", "sideways") for tf in ALL_TIME_FRAMES}
    cfg, fav, unfav = MTF_ANALYSIS_CONFIG, "uptrend" if trade_type == "LONG" else "downtrend", "downtrend" if trade_type == "LONG" else "uptrend"
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
# === HỆ THỐNG BÁO CÁO (ĐÃ SỬA LỖI & NÂNG CẤP ĐẦY ĐỦ) ===
# ==============================================================================

def calculate_total_equity(state: Dict, total_usdt_on_binance: float, realtime_prices: Dict[str, float]) -> float:
    unrealized_pnl = 0.0
    for trade in state.get('active_trades', []):
        price = realtime_prices.get(trade['symbol'])
        pnl_usd, _ = get_current_pnl(trade, realtime_price=price)
        unrealized_pnl += pnl_usd
    return total_usdt_on_binance + unrealized_pnl

def build_report_header(state: Dict, equity: float, total_usdt: float) -> str:
    initial_capital = state.get('initial_capital', total_usdt)
    if initial_capital == 0: initial_capital = total_usdt
    pnl_since_start = equity - initial_capital
    pnl_percent = (pnl_since_start / initial_capital) * 100 if initial_capital > 0 else 0
    pnl_icon = "🟢" if pnl_since_start >= 0 else "🔴"
    return (
        f"🏦 Vốn BĐ: **${initial_capital:,.2f}** | 📊 Tổng TS: **${equity:,.2f}**\n"
        f"📈 PnL Tổng: {pnl_icon} **${pnl_since_start:,.2f} ({pnl_percent:+.2f}%)**"
    )

def build_trade_details_for_report(trade: Dict, realtime_price: float) -> str:
    pnl_usd, pnl_pct = get_current_pnl(trade, realtime_price=realtime_price)
    icon = "🟢" if pnl_usd >= 0 else "🔴"
    holding_h = (datetime.now(VIETNAM_TZ) - datetime.fromisoformat(trade['entry_time'])).total_seconds() / 3600
    dca_info = f" (DCA: {len(trade.get('dca_entries',[]))})" if trade.get('dca_entries') else ""
    tsl_info = f" TSL:{trade['sl']:.4f}" if "Trailing_SL_Active" in trade.get('tactic_used', []) else ""
    tp1_info = " TP1✅" if trade.get('profit_taken') else ""
    controlling_tactic_info = f" ({trade.get('controlling_tactic', trade.get('opened_by_tactic'))} | {trade.get('last_score', trade.get('entry_score')):,.1f})"
    trade_type_str = f" [{trade.get('trade_type', 'LONG')}]"

    return (
        f"  {icon} **{trade['symbol']}-{trade['interval']}**{trade_type_str}{controlling_tactic_info} PnL: **${pnl_usd:,.2f} ({pnl_pct:+.2f}%)** | Giữ:{holding_h:.1f}h{dca_info}{tp1_info}\n"
        f"    Vốn:${trade.get('total_invested_usd', 0.0):,.2f} | Entry:{trade['entry_price']:.4f} Cur:{realtime_price:.4f} SL:{trade['sl']:.4f}{tsl_info}"
    )

def build_pnl_summary_line(state: Dict, equity: float, total_usdt: float) -> str:
    trade_history = state.get('trade_history', [])
    if not trade_history and not state.get('active_trades'): return "Chưa có giao dịch."

    df_history = pd.DataFrame(trade_history) if trade_history else pd.DataFrame()
    total_trades = len(df_history)
    win_rate_str = "N/A"
    if total_trades > 0:
        winning_trades = len(df_history[df_history['pnl_usd'] > 0])
        win_rate_str = f"{winning_trades / total_trades * 100:.2f}% ({winning_trades}/{total_trades})"

    total_pnl_closed = df_history['pnl_usd'].sum() if total_trades > 0 else 0.0
    realized_partial_pnl = sum(t.get('realized_pnl_usd', 0.0) for t in state.get('active_trades', []))
    unrealized_pnl = equity - total_usdt
    
    return (
        f"🏆 Win Rate: **{win_rate_str}** | "
        f"✅ PnL Đóng: **${total_pnl_closed:,.2f}** | "
        f"💎 PnL TP1: **${realized_partial_pnl:,.2f}** | "
        f"📈 PnL Mở: **{'+' if unrealized_pnl >= 0 else ''}${unrealized_pnl:,.2f}**"
    )

def build_report_text(state: Dict, total_usdt: float, realtime_prices: Dict[str, float], report_type: str) -> str:
    now_vn_str = datetime.now(VIETNAM_TZ).strftime('%H:%M %d-%m-%Y')
    title = f"📊 **BÁO CÁO TỔNG KẾT HÀNG NGÀY (LIVE)** - `{now_vn_str}`" if report_type == "daily" else f"💡 **CẬP NHẬT ĐỘNG (LIVE)** - `{now_vn_str}`"
    
    lines = [title, ""]
    equity = calculate_total_equity(state, total_usdt, realtime_prices)
    lines.append(build_report_header(state, equity, total_usdt))
    lines.append("\n" + build_pnl_summary_line(state, equity, total_usdt))

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
            if current_price: lines.append(build_trade_details_for_report(trade, current_price))
    
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

def should_send_dynamic_alert(state: Dict, equity: float, total_usdt: float) -> bool:
    if not DYNAMIC_ALERT_CONFIG["ENABLED"]: return False
    now = datetime.now(VIETNAM_TZ)
    last_alert = state.get('last_dynamic_alert', {})
    if not last_alert.get('timestamp'): return bool(state.get('active_trades'))

    last_alert_dt = datetime.fromisoformat(last_alert.get('timestamp')).astimezone(VIETNAM_TZ)
    hours_since = (now - last_alert_dt).total_seconds() / 3600

    if hours_since >= DYNAMIC_ALERT_CONFIG["FORCE_UPDATE_HOURS"]: return True
    if hours_since < DYNAMIC_ALERT_CONFIG["COOLDOWN_HOURS"]: return False

    initial_capital = state.get('initial_capital', total_usdt)
    if initial_capital == 0: return False
    current_pnl_pct = ((equity - initial_capital) / initial_capital) * 100
    pnl_change = abs(current_pnl_pct - last_alert.get('total_pnl_percent', 0.0))
    
    return pnl_change >= DYNAMIC_ALERT_CONFIG["PNL_CHANGE_THRESHOLD_PCT"]

# ==============================================================================
# === VÒNG LẶP CHÍNH ===
# ==============================================================================
def run_session():
    session_id = datetime.now(VIETNAM_TZ).strftime('%Y%m%d_%H%M%S')
    log_message(f"====== 🚀 BẮT ĐẦU PHIÊN LIVE (v5.1) (ID: {session_id}) 🚀 ======")
    try:
        with BinanceConnector(network="testnet") as bnc:
            if not bnc.test_connection(): return

            state = load_json_file(STATE_FILE, {"active_trades": [], "trade_history": [], "initial_capital": 0.0, "cooldown_until": {}})
            state['temp_newly_opened_trades'], state['temp_newly_closed_trades'] = [], []
            
            state = sync_state_with_binance(bnc, state)
            
            available_usdt, total_usdt = get_usdt_fund(bnc)
            if state.get('initial_capital', 0.0) == 0.0 and total_usdt > 0:
                state['initial_capital'] = total_usdt
                log_message(f" Lần chạy đầu tiên, ghi nhận vốn ban đầu là: ${total_usdt:,.2f}")
            log_message(f"💵 USDT Khả dụng: ${available_usdt:,.2f} | 🏦 Tổng quỹ USDT: ${total_usdt:,.2f}")

            log_message("⏳ Đang tải và tính toán indicators...")
            indicator_results.clear(); price_dataframes.clear()
            symbols_to_load = list(set(SYMBOLS_TO_SCAN + [t['symbol'] for t in state.get('active_trades', [])] + ["BTCUSDT"]))
            for symbol in symbols_to_load:
                indicator_results[symbol] = {}; price_dataframes[symbol] = {}
                for interval in ALL_TIME_FRAMES:
                    df = get_price_data_with_cache(symbol, interval, GENERAL_CONFIG["DATA_FETCH_LIMIT"])
                    if df is not None:
                        indicator_results[symbol][interval] = calculate_indicators(df, symbol, interval)
                        price_dataframes[symbol][interval] = df
            log_message("✅ Đã tải xong indicators.")

            manage_active_trades(bnc, state)
            handle_stale_trades(bnc, state)
            
            available_usdt, total_usdt = get_usdt_fund(bnc)
            handle_dca_opportunities(bnc, state, available_usdt, total_usdt)
            
            available_usdt, total_usdt = get_usdt_fund(bnc)
            find_and_open_new_trades(bnc, state, available_usdt, total_usdt)

            # --- PHẦN BÁO CÁO ---
            active_symbols = [t['symbol'] for t in state.get('active_trades', [])]
            realtime_prices = {sym: get_realtime_price(sym) for sym in active_symbols if sym}
            
            final_available_usdt, final_total_usdt = get_usdt_fund(bnc)
            final_equity = calculate_total_equity(state, final_total_usdt, realtime_prices)

            now_vn = datetime.now(VIETNAM_TZ)
            cron_interval_minutes = GENERAL_CONFIG.get("CRON_JOB_INTERVAL_MINUTES", 15)
            for daily_time_str in GENERAL_CONFIG["DAILY_SUMMARY_TIMES"]:
                h, m = map(int, daily_time_str.split(':'))
                report_time_today = now_vn.replace(hour=h, minute=m, second=0, microsecond=0)
                last_sent_iso = state.get('last_daily_reports_sent', {}).get(daily_time_str)
                sent_today = last_sent_iso and datetime.fromisoformat(last_sent_iso).date() == now_vn.date()
                if not sent_today and 0 <= (now_vn - report_time_today).total_seconds() < cron_interval_minutes * 60:
                    log_message(f"🔔 Gửi báo cáo hàng ngày cho khung giờ {daily_time_str}.")
                    report_content = build_report_text(state, final_total_usdt, realtime_prices, "daily")
                    send_discord_message_chunks(report_content)
                    state.setdefault('last_daily_reports_sent', {})[daily_time_str] = now_vn.isoformat()

            ### <<< SỬA LỖI >>> ### Thêm `final_total_usdt` vào lời gọi hàm
            if should_send_dynamic_alert(state, final_equity, final_total_usdt):
                log_message("🔔 Gửi alert động.")
                report_content = build_report_text(state, final_total_usdt, realtime_prices, "dynamic")
                send_discord_message_chunks(report_content)
                initial_capital = state.get('initial_capital', 1)
                pnl_percent_for_alert = ((final_equity - initial_capital) / initial_capital) * 100 if initial_capital > 0 else 0
                state['last_dynamic_alert'] = {"timestamp": now_vn.isoformat(), "total_pnl_percent": pnl_percent_for_alert}
            
            save_json_file(STATE_FILE, state)

    except Exception:
        error_details = traceback.format_exc()
        log_message(f"!!!!!! ❌ LỖI NGHIÊM TRỌNG NGOÀI DỰ KIẾN ❌ !!!!!!\n{error_details}")
        send_discord_message_chunks(f"🔥🔥🔥 BOT GẶP LỖI NGHIÊM TRỌNG 🔥🔥🔥\n```python\n{error_details}\n```")
    log_message(f"====== ✅ KẾT THÚC PHIÊN LIVE (ID: {session_id}) ✅ ======\n")

if __name__ == "__main__":
    run_session()
