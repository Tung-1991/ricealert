# paper_trade.py
# -*- coding: utf-8 -*-
"""
Paper Trade - The 4-Zone Strategy
Version: 8.3.1 - Clarity & Sync
Date: 2025-08-03

CHANGELOG (v8.3.1):
- FULL SYNC WITH LIVE v8.3.1: Đồng bộ toàn bộ cấu trúc config, logic chiến lược, quản lý lệnh,
  và các quy tắc (DCA, Stale Trades) để phản ánh chính xác 100% bot live.
- SIMPLIFIED OPERATIONS: Loại bỏ hoàn toàn BinanceConnector và các API call không cần thiết.
  Việc vào/ra lệnh được mô phỏng tức thời với giá đóng cửa của nến.
- INTELLIGENT LOGGING: Áp dụng cơ chế ghi log event-driven và chống "bão log" từ live_trade,
  giúp file log gọn nhẹ và chỉ chứa thông tin quan trọng.
- RELIABLE REPORTING: Nâng cấp hàm `should_send_report` để đảm bảo báo cáo hàng ngày
  luôn được gửi đúng hẹn, không bị bỏ lỡ do timing của cron job.
- CAPITAL MANAGEMENT: Làm rõ logic quản lý vốn. Vốn ban đầu chỉ lấy từ code ở lần chạy
  đầu tiên, sau đó sẽ luôn được quản lý qua file state.json.
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

PAPER_DATA_DIR = os.path.join(BASE_DIR, "paper_data")
os.makedirs(PAPER_DATA_DIR, exist_ok=True)
CACHE_DIR = os.path.join(PAPER_DATA_DIR, "indicator_cache")
os.makedirs(CACHE_DIR, exist_ok=True)

try:
    from indicator import get_price_data, calculate_indicators
    from trade_advisor import get_advisor_decision, FULL_CONFIG as ADVISOR_BASE_CONFIG
except ImportError as e:
    sys.exit(f"Lỗi: Không thể import module cần thiết: {e}.")

# ==============================================================================
# ================== ⚙️ TRUNG TÂM CẤU HÌNH (Đồng bộ v8.3.1) ⚙️ ==================
# ==============================================================================
# Hằng số này CHỈ được dùng cho lần chạy ĐẦU TIÊN khi file state chưa tồn tại.
INITIAL_CAPITAL = 10000.0

GENERAL_CONFIG = {
    "DATA_FETCH_LIMIT": 300,
    "DAILY_SUMMARY_TIMES": ["08:10", "20:10"],
    "TRADE_COOLDOWN_HOURS": 1,
    "CRON_JOB_INTERVAL_MINUTES": 15,
    "HEAVY_REFRESH_MINUTES": 15,
    "CRITICAL_ERROR_ALERT_COOLDOWN_MINUTES": 30
}
MTF_ANALYSIS_CONFIG = {"ENABLED": True,"BONUS_COEFFICIENT": 1.15,"PENALTY_COEFFICIENT": 0.85,"SEVERE_PENALTY_COEFFICIENT": 0.70,"SIDEWAYS_PENALTY_COEFFICIENT": 0.90}
ACTIVE_TRADE_MANAGEMENT_CONFIG = {"EARLY_CLOSE_ABSOLUTE_THRESHOLD": 4.8,"EARLY_CLOSE_RELATIVE_DROP_PCT": 0.27,"PARTIAL_EARLY_CLOSE_PCT": 0.5,"PROFIT_PROTECTION": {"ENABLED": True,"MIN_PEAK_PNL_TRIGGER": 3.5,"PNL_DROP_TRIGGER_PCT": 2.0,"PARTIAL_CLOSE_PCT": 0.7}}
DYNAMIC_ALERT_CONFIG = {"ENABLED": True,"COOLDOWN_HOURS": 3,"FORCE_UPDATE_HOURS": 10,"PNL_CHANGE_THRESHOLD_PCT": 2.0}
RISK_RULES_CONFIG = {"MAX_ACTIVE_TRADES": 12,"MAX_SL_PERCENT_BY_TIMEFRAME": {"1h": 0.06, "4h": 0.08, "1d": 0.10},"MAX_TP_PERCENT_BY_TIMEFRAME": {"1h": 0.12, "4h": 0.20, "1d": 0.35},"STALE_TRADE_RULES": {"1h": {"HOURS": 48, "PROGRESS_THRESHOLD_PCT": 25.0},"4h": {"HOURS": 72, "PROGRESS_THRESHOLD_PCT": 25.0},"1d": {"HOURS": 168, "PROGRESS_THRESHOLD_PCT": 20.0},"STAY_OF_EXECUTION_SCORE": 6.8}}
CAPITAL_MANAGEMENT_CONFIG = {"MAX_TOTAL_EXPOSURE_PCT": 0.75}
DCA_CONFIG = {"ENABLED": True,"MAX_DCA_ENTRIES": 2,"TRIGGER_DROP_PCT": -5.0,"SCORE_MIN_THRESHOLD": 6.5,"CAPITAL_MULTIPLIER": 0.75,"DCA_COOLDOWN_HOURS": 8}
ALERT_CONFIG = {"DISCORD_WEBHOOK_URL": os.getenv("DISCORD_PAPER_WEBHOOK"),"DISCORD_CHUNK_DELAY_SECONDS": 2}

# ==============================================================================
# ================= 🚀 CORE STRATEGY (Đồng bộ v8.3.1) 🚀 =================
# ==============================================================================
LEADING_ZONE, COINCIDENT_ZONE, LAGGING_ZONE, NOISE_ZONE = "LEADING", "COINCIDENT", "LAGGING", "NOISE"
ZONES = [LEADING_ZONE, COINCIDENT_ZONE, LAGGING_ZONE, NOISE_ZONE]
ZONE_BASED_POLICIES = {LEADING_ZONE: {"CAPITAL_PCT": 0.04},COINCIDENT_ZONE: {"CAPITAL_PCT": 0.07},LAGGING_ZONE: {"CAPITAL_PCT": 0.06},NOISE_ZONE: {"CAPITAL_PCT": 0.03}}
TACTICS_LAB = {"Breakout_Hunter": {"OPTIMAL_ZONE": [LEADING_ZONE, COINCIDENT_ZONE],"NOTES": "Săn đột phá.","WEIGHTS": {'tech': 0.7, 'context': 0.1, 'ai': 0.2}, "ENTRY_SCORE": 7.0, "RR": 2.5,"ATR_SL_MULTIPLIER": 1.8, "USE_TRAILING_SL": True, "TRAIL_ACTIVATION_RR": 1.0,"TRAIL_DISTANCE_RR": 0.8, "ENABLE_PARTIAL_TP": True, "TP1_RR_RATIO": 1.0, "TP1_PROFIT_PCT": 0.5},"Dip_Hunter": {"OPTIMAL_ZONE": [LEADING_ZONE, COINCIDENT_ZONE],"NOTES": "Bắt đáy/sóng hồi.","WEIGHTS": {'tech': 0.6, 'context': 0.2, 'ai': 0.2}, "ENTRY_SCORE": 6.8, "RR": 2.2,"ATR_SL_MULTIPLIER": 2.0, "USE_TRAILING_SL": False, "TRAIL_ACTIVATION_RR": None,"ENABLE_PARTIAL_TP": True, "TP1_RR_RATIO": 0.8, "TP1_PROFIT_PCT": 0.6},"AI_Aggressor": {"OPTIMAL_ZONE": COINCIDENT_ZONE,"NOTES": "Tin vào AI.","WEIGHTS": {'tech': 0.3, 'context': 0.1, 'ai': 0.6}, "ENTRY_SCORE": 7.2, "RR": 2.2,"ATR_SL_MULTIPLIER": 2.5, "USE_TRAILING_SL": True, "TRAIL_ACTIVATION_RR": 1.2,"TRAIL_DISTANCE_RR": 0.8, "ENABLE_PARTIAL_TP": True, "TP1_RR_RATIO": 1.0, "TP1_PROFIT_PCT": 0.5},"Balanced_Trader": {"OPTIMAL_ZONE": LAGGING_ZONE,"NOTES": "Đi theo xu hướng.","WEIGHTS": {'tech': 0.4, 'context': 0.2, 'ai': 0.4}, "ENTRY_SCORE": 6.5, "RR": 1.8,"ATR_SL_MULTIPLIER": 2.8, "USE_TRAILING_SL": True, "TRAIL_ACTIVATION_RR": 1.2,"TRAIL_DISTANCE_RR": 1.0, "ENABLE_PARTIAL_TP": True, "TP1_RR_RATIO": 1.2, "TP1_PROFIT_PCT": 0.5},"Cautious_Observer": {"OPTIMAL_ZONE": NOISE_ZONE,"NOTES": "Chỉ đánh khi có cơ hội VÀNG.","WEIGHTS": {'tech': 0.7, 'context': 0.2, 'ai': 0.1}, "ENTRY_SCORE": 8.0, "RR": 1.5,"ATR_SL_MULTIPLIER": 1.5, "USE_TRAILING_SL": True, "TRAIL_ACTIVATION_RR": 0.7,"TRAIL_DISTANCE_RR": 0.5, "ENABLE_PARTIAL_TP": True, "TP1_RR_RATIO": 0.8, "TP1_PROFIT_PCT": 0.5}}

# ==============================================================================
# BIẾN TOÀN CỤC & HẰNG SỐ
# ==============================================================================
SYMBOLS_TO_SCAN = [symbol.strip() for symbol in os.getenv("SYMBOLS_TO_SCAN", "ETHUSDT,BTCUSDT").split(',')]
INTERVALS_TO_SCAN, ALL_TIME_FRAMES = ["1h", "4h", "1d"], ["1h", "4h", "1d"]
VIETNAM_TZ = pytz.timezone('Asia/Ho_Chi_Minh')
LOG_FILE = os.path.join(PAPER_DATA_DIR, "paper_trade_log.txt")
ERROR_LOG_FILE = os.path.join(PAPER_DATA_DIR, "error_log.txt")
STATE_FILE = os.path.join(PAPER_DATA_DIR, "paper_trade_state.json")
TRADE_HISTORY_CSV_FILE = os.path.join(PAPER_DATA_DIR, "trade_history.csv")
indicator_results: Dict[str, Any] = {}
price_dataframes: Dict[str, Any] = {}
SESSION_TEMP_KEYS = ['temp_newly_opened_trades', 'temp_newly_closed_trades']

# ==============================================================================
# HÀM TIỆN ÍCH
# ==============================================================================
def log_message(message: str):
    timestamp = datetime.now(VIETNAM_TZ).strftime('%Y-%m-%d %H:%M:%S')
    log_entry = f"[{timestamp}] (PaperTrade) {message}"
    print(log_entry)
    with open(LOG_FILE, "a", encoding="utf-8") as f: f.write(log_entry + "\n")

def log_error(message: str, error_details: str = "", send_to_discord: bool = False):
    timestamp = datetime.now(VIETNAM_TZ).strftime('%Y-%m-%d %H:%M:%S')
    log_entry = f"[{timestamp}] (PaperTrade-ERROR) {message}\n"
    if error_details: log_entry += f"--- TRACEBACK ---\n{error_details}\n------------------\n"
    with open(ERROR_LOG_FILE, "a", encoding="utf-8") as f: f.write(log_entry)
    log_message(f"!!!!!! ❌ LỖI: {message}. Chi tiết trong error.log ❌ !!!!!!")
    if send_to_discord:
        discord_message = f"🔥🔥🔥 BOT MÔ PHỎNG GẶP LỖI 🔥🔥🔥\n**{message}**\n```python\n{error_details if error_details else 'N/A'}\n```"
        send_discord_message_chunks(discord_message)

def load_json_file(path: str) -> Optional[Dict]:
    if not os.path.exists(path): return None
    try:
        with open(path, "r", encoding="utf-8") as f: return json.load(f)
    except json.JSONDecodeError:
        log_error(f"File JSON hỏng: {path}. Không thể tiếp tục.", send_to_discord=True)
        return None

def save_json_file(path: str, data: Any):
    temp_path = path + ".tmp"
    data_to_save = data.copy()
    for key in SESSION_TEMP_KEYS: data_to_save.pop(key, None)
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
            log_error(f"Lỗi gửi chunk Discord {i+1}/{len(chunks)}: {e}"); break

def get_realtime_price(symbol: str) -> Optional[float]:
    if symbol == "USDT": return 1.0
    url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        return float(response.json()['price'])
    except: return None

def get_current_pnl(trade: Dict, current_price: Optional[float] = None) -> Tuple[float, float]:
    if not (trade and trade.get('entry_price', 0) > 0 and current_price and current_price > 0): return 0.0, 0.0
    pnl_percent = ((current_price - trade['entry_price']) / trade['entry_price']) * 100
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
        log_error(f"Lỗi xuất lịch sử giao dịch ra CSV: {e}")

def get_interval_in_milliseconds(interval: str) -> Optional[int]:
    try:
        unit, value = interval[-1], int(interval[:-1])
        if unit == 'h': return value * 3600 * 1000
        if unit == 'd': return value * 86400 * 1000
        return None
    except: return None

def get_price_data_with_cache(symbol: str, interval: str, limit: int) -> Optional[pd.DataFrame]:
    cache_filepath = os.path.join(CACHE_DIR, f"{symbol}-{interval}.parquet")
    existing_df = None
    if os.path.exists(cache_filepath):
        try: existing_df = pd.read_parquet(cache_filepath)
        except Exception as e: log_message(f"⚠️ Lỗi đọc cache {cache_filepath}: {e}. Sẽ tải lại.")
    
    if existing_df is not None and not existing_df.empty:
        last_ts, interval_ms = int(existing_df.index[-1].timestamp() * 1000), get_interval_in_milliseconds(interval)
        if not interval_ms: return existing_df
        start_time = last_ts + interval_ms
        if int(datetime.now(timezone.utc).timestamp() * 1000) > start_time:
            new_data = get_price_data(symbol, interval, limit=limit, startTime=start_time)
            combined = pd.concat([existing_df, new_data]) if new_data is not None and not new_data.empty else existing_df
            final_df = combined[~combined.index.duplicated(keep='last')].tail(limit).copy()
        else:
            final_df = existing_df.tail(limit).copy()
    else:
        final_df = get_price_data(symbol, interval, limit=limit)

    if final_df is not None and not final_df.empty:
        try:
            final_df.to_parquet(cache_filepath)
        except Exception as e: log_error(f"Lỗi lưu cache {cache_filepath}: {e}")
        return final_df
    return existing_df

# ==============================================================================
# LOGIC GIAO DỊCH CỐT LÕI (MÔ PHỎNG)
# ==============================================================================
def close_trade_simulated(trade: Dict, reason: str, state: Dict, close_price: float, close_pct: float = 1.0) -> bool:
    invested_to_close = trade['total_invested_usd'] * close_pct
    pnl_on_closed_part = ((close_price - trade['entry_price']) / trade['entry_price']) * invested_to_close if trade['entry_price'] > 0 else 0

    if close_pct >= 0.999:
        trade.update({
            'status': f'Closed ({reason})', 'exit_price': close_price, 'exit_time': datetime.now(VIETNAM_TZ).isoformat(),
            'pnl_usd': trade.get('realized_pnl_usd', 0.0) + pnl_on_closed_part,
            'pnl_percent': ((close_price - trade['entry_price']) / trade['entry_price']) * 100 if trade['entry_price'] > 0 else 0
        })
        state['cash'] += trade['total_invested_usd'] + pnl_on_closed_part
        state['active_trades'] = [t for t in state['active_trades'] if t['trade_id'] != trade['trade_id']]
        state['trade_history'].append(trade)
        state.setdefault('cooldown_until', {})[trade['symbol']] = (datetime.now(VIETNAM_TZ) + timedelta(hours=GENERAL_CONFIG["TRADE_COOLDOWN_HOURS"])).isoformat()
        export_trade_history_to_csv([trade])
        icon = '✅' if pnl_on_closed_part >= 0 else '❌'
        state.setdefault('temp_newly_closed_trades', []).append(f"🎬 {icon} {trade['symbol']} (Đóng toàn bộ - {reason}): PnL ${trade['pnl_usd']:,.2f}")
    else:
        trade['realized_pnl_usd'] = trade.get('realized_pnl_usd', 0.0) + pnl_on_closed_part
        trade['total_invested_usd'] *= (1 - close_pct)
        state['cash'] += invested_to_close + pnl_on_closed_part
        trade.setdefault('tactic_used', []).append(f"Partial_Close_{reason}")
        state.setdefault('temp_newly_closed_trades', []).append(f"💰 {trade['symbol']} (Đóng {close_pct*100:.0f}% - {reason}): PnL ${pnl_on_closed_part:,.2f}")
    return True

def check_and_manage_open_positions(state: Dict):
    for trade in state.get("active_trades", [])[:]:
        tactic_cfg = TACTICS_LAB.get(trade.get('opened_by_tactic'), {})
        indicators = indicator_results.get(trade['symbol'], {}).get(trade['interval'], {})
        current_price = indicators.get('price')
        if not current_price: continue

        if current_price <= trade['sl']:
            if close_trade_simulated(trade, "SL", state, trade['sl']): continue
        if current_price >= trade['tp']:
            if close_trade_simulated(trade, "TP", state, trade['tp']): continue

        last_score, entry_score = trade.get('last_score', 5.0), trade.get('entry_score', 5.0)
        if last_score < ACTIVE_TRADE_MANAGEMENT_CONFIG['EARLY_CLOSE_ABSOLUTE_THRESHOLD']:
            if close_trade_simulated(trade, f"EC_Abs_{last_score:.1f}", state, current_price): continue
        if last_score < entry_score and not trade.get('is_in_warning_zone', False): trade['is_in_warning_zone'] = True
        if trade.get('is_in_warning_zone', False) and not trade.get('partial_closed_by_score', False):
            if last_score < entry_score * (1 - ACTIVE_TRADE_MANAGEMENT_CONFIG.get('EARLY_CLOSE_RELATIVE_DROP_PCT', 0.35)):
                if close_trade_simulated(trade, f"EC_Rel_{last_score:.1f}", state, current_price, close_pct=ACTIVE_TRADE_MANAGEMENT_CONFIG.get("PARTIAL_EARLY_CLOSE_PCT", 0.5)):
                    trade['partial_closed_by_score'] = True; trade['sl'] = trade['entry_price']

        _, pnl_percent = get_current_pnl(trade, current_price=current_price)
        trade['peak_pnl_percent'] = max(trade.get('peak_pnl_percent', 0.0), pnl_percent)
        initial_risk_dist = abs(trade['initial_entry']['price'] - trade['initial_sl'])

        if tactic_cfg.get("ENABLE_PARTIAL_TP", False) and not trade.get("tp1_hit", False) and initial_risk_dist > 0:
            pnl_ratio = (current_price - trade['entry_price']) / initial_risk_dist
            if pnl_ratio >= tactic_cfg.get("TP1_RR_RATIO", 1.0):
                tp1_price = trade['initial_entry']['price'] + (initial_risk_dist * tactic_cfg.get("TP1_RR_RATIO", 1.0))
                if close_trade_simulated(trade, f"TP1_{tactic_cfg.get('TP1_RR_RATIO', 1.0):.1f}R", state, tp1_price, close_pct=tactic_cfg.get("TP1_PROFIT_PCT", 0.5)):
                    trade['tp1_hit'] = True; trade['sl'] = trade['entry_price']
        
        pp_config = ACTIVE_TRADE_MANAGEMENT_CONFIG.get("PROFIT_PROTECTION", {})
        if pp_config.get("ENABLED", False) and not trade.get('profit_taken', False) and trade['peak_pnl_percent'] >= pp_config.get("MIN_PEAK_PNL_TRIGGER", 3.5):
            if (trade['peak_pnl_percent'] - pnl_percent) >= pp_config.get("PNL_DROP_TRIGGER_PCT", 2.0):
                if close_trade_simulated(trade, "Protect_Profit", state, current_price, close_pct=pp_config.get("PARTIAL_CLOSE_PCT", 0.7)):
                    trade['profit_taken'] = True; trade['sl'] = trade['entry_price']

        if tactic_cfg.get("USE_TRAILING_SL", False) and initial_risk_dist > 0:
            pnl_ratio_from_entry = (current_price - trade['entry_price']) / initial_risk_dist
            if pnl_ratio_from_entry >= tactic_cfg.get("TRAIL_ACTIVATION_RR", float('inf')):
                new_sl = current_price - (initial_risk_dist * tactic_cfg.get("TRAIL_DISTANCE_RR", 0.8))
                if new_sl > trade['sl']:
                    state.setdefault('temp_newly_closed_trades', []).append(f"📈 TSL {trade['symbol']}: SL mới {new_sl:.4f} (cũ {trade['sl']:.4f})")
                    trade['sl'] = new_sl
                    if "Trailing_SL_Active" not in trade.get('tactic_used', []): trade.setdefault('tactic_used', []).append("Trailing_SL_Active")

def handle_stale_trades(state: Dict):
    now_aware = datetime.now(VIETNAM_TZ)
    for trade in state.get("active_trades", [])[:]:
        if 'stale_override_until' in trade and now_aware < datetime.fromisoformat(trade['stale_override_until']): continue
        rules = RISK_RULES_CONFIG["STALE_TRADE_RULES"].get(trade.get("interval"))
        if not rules: continue
        holding_hours = (now_aware - datetime.fromisoformat(trade['entry_time'])).total_seconds() / 3600
        if holding_hours > rules["HOURS"]:
            current_price = indicator_results.get(trade['symbol'], {}).get(trade['interval'], {}).get('price')
            _, pnl_pct = get_current_pnl(trade, current_price=current_price)
            if pnl_pct < rules["PROGRESS_THRESHOLD_PCT"] and trade.get('last_score', 5.0) < RISK_RULES_CONFIG["STALE_TRADE_RULES"]["STAY_OF_EXECUTION_SCORE"]:
                if current_price: close_trade_simulated(trade, "Stale", state, current_price)

def handle_dca_opportunities(state: Dict, equity: float):
    if not DCA_CONFIG["ENABLED"]: return
    current_exposure_usd = sum(t.get('total_invested_usd', 0.0) for t in state.get("active_trades", []))
    now = datetime.now(VIETNAM_TZ)
    for trade in state.get("active_trades", [])[:]:
        if len(trade.get("dca_entries", [])) >= DCA_CONFIG["MAX_DCA_ENTRIES"]: continue
        if trade.get('last_dca_time') and (now - datetime.fromisoformat(trade.get('last_dca_time'))).total_seconds() / 3600 < DCA_CONFIG['DCA_COOLDOWN_HOURS']: continue
        
        current_data = indicator_results.get(trade["symbol"], {}).get(trade["interval"], {})
        current_price = current_data.get('price')
        if not current_price or current_price <= 0: continue
        
        last_entry_price = trade['dca_entries'][-1]['price'] if trade.get('dca_entries') else trade['initial_entry']['price']
        price_drop_pct = ((current_price - last_entry_price) / last_entry_price) * 100
        if price_drop_pct > DCA_CONFIG["TRIGGER_DROP_PCT"]: continue

        if get_advisor_decision(trade['symbol'], trade['interval'], current_data, ADVISOR_BASE_CONFIG).get("final_score", 0.0) < DCA_CONFIG["SCORE_MIN_THRESHOLD"]: continue
        
        dca_investment = (trade['dca_entries'][-1]['invested_usd'] if trade.get('dca_entries') else trade['initial_entry']['invested_usd']) * DCA_CONFIG["CAPITAL_MULTIPLIER"]
        if dca_investment <= 0 or dca_investment > state['cash'] or (current_exposure_usd + dca_investment) > (equity * CAPITAL_MANAGEMENT_CONFIG["MAX_TOTAL_EXPOSURE_PCT"]): continue
        
        state['cash'] -= dca_investment
        trade.setdefault('dca_entries', []).append({"price": current_price, "invested_usd": dca_investment, "timestamp": now.isoformat()})
        
        all_entries = [trade['initial_entry']] + trade['dca_entries']
        new_total_cost = sum(e['invested_usd'] for e in all_entries)
        new_avg_price = sum(e['price'] * e['invested_usd'] for e in all_entries) / new_total_cost if new_total_cost > 0 else 0
        
        initial_risk_dist = abs(trade['initial_entry']['price'] - trade['initial_sl'])
        trade.update({
            'entry_price': new_avg_price, 'total_invested_usd': new_total_cost,
            'sl': new_avg_price - initial_risk_dist,
            'tp': new_avg_price + (initial_risk_dist * TACTICS_LAB[trade['opened_by_tactic']]['RR']),
            'last_dca_time': now.isoformat()
        })
        trade.setdefault('tactic_used', []).append(f"DCA_{len(trade.get('dca_entries', []))}")
        state.setdefault('temp_newly_closed_trades', []).append(f"🎯 DCA {trade['symbol']} với ${dca_investment:,.2f}")

def determine_market_zone_with_scoring(symbol: str, interval: str) -> str:
    indicators, df = indicator_results.get(symbol, {}).get(interval, {}), price_dataframes.get(symbol, {}).get(interval)
    if not indicators or df is None or df.empty: return NOISE_ZONE
    scores = {LEADING_ZONE: 0, COINCIDENT_ZONE: 0, LAGGING_ZONE: 0, NOISE_ZONE: 0}
    adx, bb_width, rsi_14, trend = indicators.get('adx', 20), indicators.get('bb_width', 0), indicators.get('rsi_14', 50), indicators.get('trend', "sideways")
    if adx < 20: scores[NOISE_ZONE] += 3
    if 'ema_50' in df.columns and np.sign(df['close'].iloc[-30:] - df['ema_50'].iloc[-30:]).diff().ne(0).sum() > 4: scores[NOISE_ZONE] += 2
    if adx > 25: scores[LAGGING_ZONE] += 2.5
    if trend == "uptrend": scores[LAGGING_ZONE] += 2
    if 'ema_20' in df.columns and 'ema_50' in df.columns and not df['ema_20'].isna().all() and not df['ema_50'].isna().all():
        if trend == "uptrend" and df['ema_20'].iloc[-1] > df['ema_50'].iloc[-1] and df['ema_20'].iloc[-10] > df['ema_50'].iloc[-10]: scores[LAGGING_ZONE] += 1.5
    if 'bb_width' in df.columns and not df['bb_width'].isna().all() and bb_width < df['bb_width'].iloc[-100:].quantile(0.20): scores[LEADING_ZONE] += 2.5
    htf_trend = indicator_results.get(symbol, {}).get('4h' if interval == '1h' else '1d', {}).get('trend', 'sideway')
    if htf_trend == 'uptrend' and rsi_14 < 45: scores[LEADING_ZONE] += 2
    if indicators.get('breakout_signal', "none") != "none": scores[COINCIDENT_ZONE] += 3
    if indicators.get('macd_cross', "neutral") not in ["neutral", "no_cross"]: scores[COINCIDENT_ZONE] += 2
    if indicators.get('vol_ma20', 1) > 0 and indicators.get('volume', 0) > indicators.get('vol_ma20', 1) * 2: scores[COINCIDENT_ZONE] += 1.5
    if adx > 28: scores[LEADING_ZONE] -= 2
    return max(scores, key=scores.get) if scores and any(v > 0 for v in scores.values()) else NOISE_ZONE

def get_mtf_adjustment_coefficient(symbol: str, target_interval: str) -> float:
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

def find_and_open_new_trades(state: Dict, equity: float):
    if len(state.get("active_trades", [])) >= RISK_RULES_CONFIG["MAX_ACTIVE_TRADES"]: return
    potential_opportunities = []
    now_vn = datetime.now(VIETNAM_TZ)
    for symbol in SYMBOLS_TO_SCAN:
        if any(t['symbol'] == symbol for t in state.get("active_trades", [])): continue
        cooldown_map = state.get('cooldown_until', {})
        if symbol in cooldown_map and now_vn < datetime.fromisoformat(cooldown_map[symbol]): continue
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
                    potential_opportunities.append({"decision": decision, "tactic_name": tactic_name, "tactic_cfg": tactic_cfg, "score": adjusted_score, "symbol": symbol, "interval": interval, "zone": market_zone})
    
    log_message("---[🔍 Quét Cơ Hội Mới 🔍]---")
    if not potential_opportunities:
        log_message("  => Không tìm thấy cơ hội tiềm năng nào.")
        return

    best_opportunity = sorted(potential_opportunities, key=lambda x: x['score'], reverse=True)[0]
    entry_score_threshold = best_opportunity['tactic_cfg'].get("ENTRY_SCORE", 9.9)
    log_message(f"  🏆 Cơ hội tốt nhất: {best_opportunity['symbol']}-{best_opportunity['interval']} | Tactic: {best_opportunity['tactic_name']} | Điểm: {best_opportunity['score']:.2f} (Ngưỡng: {entry_score_threshold})")

    if best_opportunity['score'] < entry_score_threshold:
        log_message("     => 📉 Không đạt ngưỡng. Bỏ qua.")
        return
    
    log_message("     => ✅ Đạt ngưỡng! Mô phỏng vào lệnh...")
    
    # Gộp logic thực thi vào đây
    decision_data, tactic_cfg = best_opportunity['decision'], best_opportunity['tactic_cfg']
    symbol, interval, zone = best_opportunity['symbol'], best_opportunity['interval'], best_opportunity['zone']
    full_indicators = decision_data.get('full_indicators', {})
    entry_price = full_indicators.get('price')
    if not entry_price or entry_price <= 0: return

    risk_dist_from_atr = full_indicators.get('atr', 0) * tactic_cfg.get("ATR_SL_MULTIPLIER", 2.0)
    max_sl_pct = RISK_RULES_CONFIG["MAX_SL_PERCENT_BY_TIMEFRAME"].get(interval, 0.1)
    final_risk_dist = min(risk_dist_from_atr, entry_price * max_sl_pct)
    if final_risk_dist <= 0: return

    capital_pct = ZONE_BASED_POLICIES.get(zone, {}).get("CAPITAL_PCT", 0.03)
    invested_amount = equity * capital_pct
    current_exposure_usd = sum(t.get('total_invested_usd', 0.0) for t in state.get("active_trades", []))
    if invested_amount > state['cash'] or (current_exposure_usd + invested_amount) > (equity * CAPITAL_MANAGEMENT_CONFIG["MAX_TOTAL_EXPOSURE_PCT"]) or invested_amount < 10:
        log_message(f"     => ❌ Không đủ vốn hoặc vượt ngưỡng rủi ro. Bỏ qua.")
        return

    sl_p = entry_price - final_risk_dist
    tp_p = entry_price + (final_risk_dist * tactic_cfg.get("RR", 2.0))
    max_tp_pct_cfg = RISK_RULES_CONFIG["MAX_TP_PERCENT_BY_TIMEFRAME"].get(interval)
    if max_tp_pct_cfg is not None and tp_p > entry_price * (1 + max_tp_pct_cfg): tp_p = entry_price * (1 + max_tp_pct_cfg)
    if tp_p <= entry_price or sl_p >= entry_price or sl_p <= 0: return

    new_trade = {
        "trade_id": str(uuid.uuid4()), "symbol": symbol, "interval": interval, "status": "ACTIVE",
        "opened_by_tactic": best_opportunity['tactic_name'], "trade_type": "LONG", "entry_price": entry_price,
        "quantity": invested_amount / entry_price, "tp": tp_p, "sl": sl_p, "initial_sl": sl_p,
        "initial_entry": {"price": entry_price, "invested_usd": invested_amount},
        "total_invested_usd": invested_amount, "entry_time": now_vn.isoformat(), "entry_score": best_opportunity['score'],
        "entry_zone": zone, "last_zone": zone, "dca_entries": [], "realized_pnl_usd": 0.0,
        "last_score": best_opportunity['score'], "peak_pnl_percent": 0.0, "tp1_hit": False,
        "is_in_warning_zone": False, "partial_closed_by_score": False, "profit_taken": False
    }
    state['cash'] -= invested_amount
    state['active_trades'].append(new_trade)
    state.setdefault('temp_newly_opened_trades', []).append(f"🔥 {symbol}-{interval} ({best_opportunity['tactic_name']}): Vốn ${new_trade['total_invested_usd']:,.2f}")

# ==============================================================================
# BÁO CÁO & VÒNG LẶP CHÍNH
# ==============================================================================
def calculate_total_equity(state: Dict, realtime_prices: Optional[Dict[str, float]] = None) -> float:
    cash = state.get('cash', 0)
    value_of_open_positions = 0
    for t in state.get('active_trades', []):
        price_to_use = realtime_prices.get(t['symbol']) if realtime_prices else indicator_results.get(t['symbol'], {}).get(t['interval'], {}).get('price', t['entry_price'])
        pnl_usd, _ = get_current_pnl(t, current_price=price_to_use)
        value_of_open_positions += t.get('total_invested_usd', 0.0) + pnl_usd
    return cash + value_of_open_positions

def build_report_header(state: Dict, equity: float) -> str:
    initial_capital = state.get('initial_capital', INITIAL_CAPITAL)
    pnl_since_start = equity - initial_capital
    pnl_percent = (pnl_since_start / initial_capital) * 100 if initial_capital > 0 else 0
    pnl_icon = "🟢" if pnl_since_start >= 0 else "🔴"
    return (f"💰 Vốn BĐ: **${initial_capital:,.2f}** | 💵 Tiền mặt: **${state.get('cash', 0):,.2f}**\n"
            f"📊 Tổng TS: **${equity:,.2f}** | 📈 PnL Tổng: {pnl_icon} **${pnl_since_start:,.2f} ({pnl_percent:+.2f}%)**")

def build_pnl_summary_line(state: Dict, realtime_prices: Dict[str, float]) -> str:
    df_history = pd.DataFrame(state.get('trade_history', []))
    total_trades = len(df_history)
    win_rate_str = "N/A"
    if total_trades > 0:
        winning_trades = len(df_history[df_history['pnl_usd'] > 0])
        win_rate_str = f"{winning_trades / total_trades * 100:.2f}% ({winning_trades}/{total_trades})"
    total_pnl_closed = df_history['pnl_usd'].sum() if total_trades > 0 else 0.0
    realized_partial_pnl = sum(t.get('realized_pnl_usd', 0.0) for t in state.get('active_trades', []))
    unrealized_pnl = sum(get_current_pnl(t, current_price=realtime_prices.get(t['symbol']))[0] for t in state.get('active_trades', []))
    return f"🏆 Win Rate: **{win_rate_str}** | ✅ PnL Đóng: **${total_pnl_closed:,.2f}** | 💎 PnL TP1: **${realized_partial_pnl:,.2f}** | � PnL Mở: **{'+' if unrealized_pnl >= 0 else ''}${unrealized_pnl:,.2f}**"

def build_trade_details_for_report(trade: Dict, realtime_price: float) -> str:
    pnl_usd, pnl_pct = get_current_pnl(trade, current_price=realtime_price)
    icon = "🟢" if pnl_usd >= 0 else "🔴"
    holding_h = (datetime.now(VIETNAM_TZ) - datetime.fromisoformat(trade['entry_time'])).total_seconds() / 3600
    dca_info = f" (DCA:{len(trade.get('dca_entries',[]))})" if trade.get('dca_entries') else ""
    tsl_info = f" TSL:{trade['sl']:.4f}" if "Trailing_SL_Active" in trade.get('tactic_used', []) else ""
    tp1_info = " TP1✅" if trade.get('tp1_hit', False) or trade.get('profit_taken', False) else ""
    entry_score, last_score = trade.get('entry_score', 0.0), trade.get('last_score', 0.0)
    score_display = f"{entry_score:,.1f}→{last_score:,.1f}" + ("📉" if last_score < entry_score else "📈" if last_score > entry_score else "")
    zone_display = f"{trade.get('entry_zone', 'N/A')}→{trade.get('last_zone', 'N/A')}" if trade.get('last_zone') != trade.get('entry_zone') else trade.get('entry_zone', 'N/A')
    tactic_info = f"({trade.get('opened_by_tactic')} | {score_display} | {zone_display})"
    invested_usd, current_value = trade.get('total_invested_usd', 0.0), trade.get('total_invested_usd', 0.0) + pnl_usd
    return (f"  {icon} **{trade['symbol']}-{trade['interval']}** {tactic_info} PnL: **${pnl_usd:,.2f} ({pnl_pct:+.2f}%)** | Giữ:{holding_h:.1f}h{dca_info}{tp1_info}\n"
            f"    Vốn:${invested_usd:,.2f} -> **${current_value:,.2f}** | Entry:{trade['entry_price']:.4f} Cur:{realtime_price:.4f} TP:{trade['tp']:.4f} SL:{trade['sl']:.4f}{tsl_info}")

def build_report_text(state: Dict, realtime_prices: Dict[str, float], report_type: str) -> str:
    now_vn_str = datetime.now(VIETNAM_TZ).strftime('%H:%M %d-%m-%Y')
    title = f"📊 **BÁO CÁO TỔNG KẾT (PAPER)** - `{now_vn_str}`" if report_type == "daily" else f"💡 **CẬP NHẬT ĐỘNG (PAPER)** - `{now_vn_str}`"
    lines = [title, ""]
    equity = calculate_total_equity(state, realtime_prices)
    lines.append(build_report_header(state, equity))
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

def should_send_report(state: Dict, equity: float) -> Optional[str]:
    now_vn = datetime.now(VIETNAM_TZ)
    last_summary_dt = datetime.fromisoformat(state.get('last_summary_sent_time')).astimezone(VIETNAM_TZ) if state.get('last_summary_sent_time') else None
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
    if abs(current_pnl_pct - last_alert.get('total_pnl_percent', 0.0)) >= DYNAMIC_ALERT_CONFIG["PNL_CHANGE_THRESHOLD_PCT"]: return "dynamic"
    
    return None

def run_heavy_tasks(state: Dict, equity: float):
    indicator_results.clear(); price_dataframes.clear()
    symbols_to_load = list(set(SYMBOLS_TO_SCAN + [t['symbol'] for t in state.get('active_trades', [])] + ["BTCUSDT"]))
    for symbol in symbols_to_load:
        indicator_results[symbol], price_dataframes[symbol] = {}, {}
        for interval in ALL_TIME_FRAMES:
            df = get_price_data_with_cache(symbol, interval, GENERAL_CONFIG["DATA_FETCH_LIMIT"])
            if df is not None and not df.empty:
                df['ema_20'] = ta.trend.ema_indicator(df["close"], window=20)
                df['ema_50'] = ta.trend.ema_indicator(df["close"], window=50)
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
            
    find_and_open_new_trades(state, equity)

def run_session():
    try:
        state = load_json_file(STATE_FILE)
        if state is None:
            log_message("Không tìm thấy file state, khởi tạo mới...")
            state = {"cash": INITIAL_CAPITAL,"initial_capital": INITIAL_CAPITAL,"active_trades": [], "trade_history": [], "cooldown_until": {},"last_indicator_refresh": None, "last_dynamic_alert": {},"last_summary_sent_time": None, "last_critical_error": {}}
        
        # Logic phát hiện nạp/rút tiền mô phỏng
        # Nếu vốn ban đầu và tiền mặt khác nhau VÀ không có lệnh mở, coi như người dùng đã sửa tay file state
        if 'initial_capital' in state and state.get('cash') != state.get('initial_capital') and not state.get('active_trades'):
             diff = state.get('cash', 0) - state.get('initial_capital', 0)
             log_message(f"💵 (Sim) Phát hiện thay đổi vốn: ${diff:,.2f}. Cập nhật vốn ban đầu.")
             state['initial_capital'] = state.get('cash')

        state['temp_newly_opened_trades'], state['temp_newly_closed_trades'] = [], []
        
        equity = calculate_total_equity(state)
        run_heavy_tasks(state, equity)
        
        check_and_manage_open_positions(state)
        handle_stale_trades(state)
        handle_dca_opportunities(state, equity)

        if state.get('temp_newly_opened_trades') or state.get('temp_newly_closed_trades'):
            log_message(f"--- Cập nhật các sự kiện trong phiên ---")
            for msg in state.get('temp_newly_opened_trades', []): log_message(f"  {msg}")
            for msg in state.get('temp_newly_closed_trades', []): log_message(f"  {msg}")
        
        realtime_prices_for_report = {sym: get_realtime_price(sym) for sym in list(set([t['symbol'] for t in state.get('active_trades', [])])) if sym}
        final_equity = calculate_total_equity(state, realtime_prices=realtime_prices_for_report)
        
        report_type_to_send = should_send_report(state, final_equity)
        if report_type_to_send:
            log_message(f"🔔 Gửi báo cáo loại: {report_type_to_send.upper()}")
            report_content = build_report_text(state, realtime_prices_for_report, report_type_to_send)
            send_discord_message_chunks(report_content)
            if report_type_to_send == "daily": state['last_summary_sent_time'] = datetime.now(VIETNAM_TZ).isoformat()
            current_pnl_pct = ((final_equity - state['initial_capital']) / state['initial_capital']) * 100 if state.get('initial_capital', 1) > 0 else 0
            state['last_dynamic_alert'] = {"timestamp": datetime.now(VIETNAM_TZ).isoformat(), "total_pnl_percent": current_pnl_pct}

        if 'last_critical_error' in state: state['last_critical_error'] = {}
        save_json_file(STATE_FILE, state)

    except Exception as e:
        state = load_json_file(STATE_FILE) or {}
        error_msg, now_ts = str(e), time.time()
        last_error = state.get('last_critical_error', {})
        cooldown_seconds = GENERAL_CONFIG.get("CRITICAL_ERROR_ALERT_COOLDOWN_MINUTES", 30) * 60
        should_alert_discord = True
        if last_error.get('message') == error_msg and (now_ts - last_error.get('timestamp', 0)) < cooldown_seconds:
            should_alert_discord = False
        log_error(f"LỖI TOÀN CỤC NGOÀI DỰ KIẾN", error_details=traceback.format_exc(), send_to_discord=should_alert_discord)
        state['last_critical_error'] = {'message': error_msg, 'timestamp': now_ts}
        save_json_file(STATE_FILE, state)

if __name__ == "__main__":
    run_session()
