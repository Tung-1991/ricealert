# -*- coding: utf-8 -*-
"""
paper_trade.py - Quản lý Danh mục & Rủi ro Thông minh
Version: 2.7.0 - "Chiến Binh Giàu Kinh Nghiệm"
Date: 2025-07-26

Description:
Phiên bản 2.7.0 là một cuộc đại tu chiến lược dựa trên kinh nghiệm thực chiến.
- Tích hợp logic "Tìm kiếm Toàn cục" để chọn ra cơ hội tốt nhất tuyệt đối.
- Nâng cấp hệ thống quản lý lệnh với cơ chế Chốt lời từng phần (Partial TP)
  và Trailing Stop-loss (TSL) linh hoạt, được cấu hình riêng cho từng Tactic.
- Giải quyết triệt để vấn đề "từ lãi thành lỗ" và tối ưu hóa hành vi của
  tất cả các Tactic để phù hợp hơn với vai trò của chúng.
"""
import os
import sys
import json
import uuid
import time
import requests
import pytz
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Any, Tuple
from dotenv import load_dotenv
import traceback
import numpy as np # Thêm import numpy để xử lý NaN

# --- Tải và Thiết lập ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
dotenv_path = os.path.join(PROJECT_ROOT, '.env')
load_dotenv(dotenv_path=dotenv_path)

sys.path.append(PROJECT_ROOT)
PAPER_DATA_DIR = os.path.join(BASE_DIR, "paper_data")
os.makedirs(PAPER_DATA_DIR, exist_ok=True)

try:
    from indicator import get_price_data, calculate_indicators
    from trade_advisor import get_advisor_decision, FULL_CONFIG as ADVISOR_BASE_CONFIG
except ImportError:
    sys.exit("Lỗi: Thiếu module 'indicator' hoặc 'trade_advisor'. Hãy chắc chắn chúng ở đúng vị trí.")

# ==============================================================================
# ================== ⚙️ TRUNG TÂM CẤU HÌNH (v2.7.0) ⚙️ ==================
# ==============================================================================

INITIAL_CAPITAL = 10000.0

GENERAL_CONFIG = {
    "DATA_FETCH_LIMIT": 300,
    "DAILY_SUMMARY_TIMES": ["08:05", "20:05"],
    "TRADE_COOLDOWN_HOURS": 1
}

DYNAMIC_ALERT_CONFIG = {
    "ENABLED": True, "COOLDOWN_HOURS": 4,
    "FORCE_UPDATE_HOURS": 10, "PNL_CHANGE_THRESHOLD_PCT": 1.5
}

RISK_RULES_CONFIG = {
    "MAX_ACTIVE_TRADES": 10,
    "STALE_TRADE_RULES": {
        "1h": {"HOURS": 48,  "PROGRESS_THRESHOLD": 0.25, "MIN_RISK_BUFFER_PCT": 0.2},
        "4h": {"HOURS": 96,  "PROGRESS_THRESHOLD": 0.25, "MIN_RISK_BUFFER_PCT": 0.2},
        "1d": {"HOURS": 240, "PROGRESS_THRESHOLD": 0.20, "MIN_RISK_BUFFER_PCT": 0.1}
    }
}

CAPITAL_MANAGEMENT_CONFIG = {
    "MAX_TOTAL_EXPOSURE_PCT": 0.75
}

DCA_CONFIG = {
    "ENABLED": True, "MAX_DCA_ENTRIES": 2, "TRIGGER_DROP_PCT": -5.0,
    "SCORE_MIN_THRESHOLD": 4.5, "CAPITAL_MULTIPLIER": 1.5, "DCA_COOLDOWN_HOURS": 8
}

ALERT_CONFIG = {
    "DISCORD_WEBHOOK_URL": os.getenv("DISCORD_PAPER_WEBHOOK"),
    "DISCORD_CHUNK_DELAY_SECONDS": 2,
}

# === TACTICS_LAB ĐÃ ĐƯỢC ĐẠI TU (v2.7.0) ===
TACTICS_LAB = {
    "AI_Aggressor": {
        "NOTES": "Tin vào AI, tự động gồng lời với Trailing SL",
        "WEIGHTS": {'tech': 0.1, 'context': 0.1, 'ai': 0.8},
        "ENTRY_SCORE": 6.5, "RR": 2.5, "USE_ATR_SL": True, "ATR_SL_MULTIPLIER": 3.0,
        "USE_TRAILING_SL": True, "TRAIL_ACTIVATION_RR": 1.0, "TRAIL_DISTANCE_RR": 0.8,
        "ENABLE_PARTIAL_TP": True, "TP1_RR_RATIO": 0.8, "TP1_PROFIT_PCT": 0.5
    },
    "Balanced_Trader": {
        "NOTES": "Cân bằng, chốt lời sớm, bảo vệ lợi nhuận",
        "WEIGHTS": {'tech': 0.4, 'context': 0.2, 'ai': 0.4},
        "ENTRY_SCORE": 6.0, "RR": 2.2, "USE_ATR_SL": True, "ATR_SL_MULTIPLIER": 2.5,
        "USE_TRAILING_SL": True, "TRAIL_ACTIVATION_RR": 1.2, "TRAIL_DISTANCE_RR": 1.0,
        "ENABLE_PARTIAL_TP": True, "TP1_RR_RATIO": 1.0, "TP1_PROFIT_PCT": 0.5
    },
    "Dip_Hunter": {
        "NOTES": "Bắt đáy khi sợ hãi, chốt lời nhanh gọn",
        "WEIGHTS": {'tech': 0.5, 'context': 0.3, 'ai': 0.2},
        "ENTRY_SCORE": 6.5, "RR": 3.0, "USE_ATR_SL": True, "ATR_SL_MULTIPLIER": 2.0,
        "USE_TRAILING_SL": False,
        "ENABLE_PARTIAL_TP": True, "TP1_RR_RATIO": 1.0, "TP1_PROFIT_PCT": 0.6
    },
    "Breakout_Hunter": {
        "NOTES": "Săn đột biến giá/volume, gồng lời mạnh mẽ",
        "WEIGHTS": {'tech': 0.7, 'context': 0.1, 'ai': 0.2},
        "ENTRY_SCORE": 7.0, "RR": 2.8, "USE_ATR_SL": True, "ATR_SL_MULTIPLIER": 2.0,
        "USE_TRAILING_SL": True, "TRAIL_ACTIVATION_RR": 1.0, "TRAIL_DISTANCE_RR": 0.8,
        "ENABLE_PARTIAL_TP": False
    },
    "Cautious_Observer": {
        "NOTES": "Bảo toàn vốn, đánh chắc thắng chắc",
        "WEIGHTS": {'tech': 0.5, 'context': 0.5, 'ai': 0.0},
        "ENTRY_SCORE": 8.5,
        "RR": 1.5, "USE_ATR_SL": True, "ATR_SL_MULTIPLIER": 1.5,
        "USE_TRAILING_SL": True, "TRAIL_ACTIVATION_RR": 0.7, "TRAIL_DISTANCE_RR": 0.5,
        "ENABLE_PARTIAL_TP": False
    },
}

SYMBOLS_TO_SCAN_STRING = os.getenv("SYMBOLS_TO_SCAN", "ETHUSDT,BTCUSDT")
SYMBOLS_TO_SCAN = [symbol.strip() for symbol in SYMBOLS_TO_SCAN_STRING.split(',')]
INTERVALS_TO_SCAN = ["1h", "4h", "1d"]
ALL_TIME_FRAMES = ["1h", "4h", "1d"]
VIETNAM_TZ = pytz.timezone('Asia/Ho_Chi_Minh')

LOG_FILE = os.path.join(PAPER_DATA_DIR, "paper_trade_log.txt")
STATE_FILE = os.path.join(PAPER_DATA_DIR, "paper_trade_state.json")
TRADE_HISTORY_CSV_FILE = os.path.join(PAPER_DATA_DIR, "trade_history.csv")

all_indicators: Dict[str, Any] = {}

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
    with open(path, "w", encoding="utf-8") as f: json.dump(data, f, indent=4, ensure_ascii=False)

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

def get_current_pnl(trade: Dict) -> Tuple[float, float]:
    current_data = all_indicators.get(trade["symbol"], {}).get(trade["interval"])
    if not (current_data and current_data.get('price', 0) > 0 and trade.get('entry_price', 0) > 0):
        return 0.0, 0.0
    pnl_percent = (current_data['price'] - trade['entry_price']) / trade['entry_price']
    return trade.get('total_invested_usd', 0.0) * pnl_percent, pnl_percent * 100

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

def safe_get_price_data(symbol: str, interval: str, limit: int):
    try:
        df = get_price_data(symbol, interval, limit=limit)
        if df is None or getattr(df, "empty", True):
            log_message(f"⚠️ Không có dữ liệu cho {symbol}-{interval}")
            return None
        return df
    except Exception as e:
        log_message(f"❌ Lỗi fetch dữ liệu {symbol}-{interval}: {e}")
        return None

def calculate_total_equity(state: Dict) -> float:
    return state.get('cash', INITIAL_CAPITAL) + sum(t.get('total_invested_usd', 0.0) + get_current_pnl(t)[0] for t in state.get('active_trades', []))

def determine_dynamic_capital_pct(atr_percent: float) -> float:
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

# === HANDLE_TRADE_CLOSURE ĐÃ ĐƯỢC ĐẠI TU (v2.7.0) ===
def handle_trade_closure(portfolio_state: Dict) -> List[Dict]:
    closed_trades, newly_closed_details = [], []
    now_vn = datetime.now(VIETNAM_TZ)

    for trade in portfolio_state["active_trades"][:]:
        data = all_indicators.get(trade['symbol'], {}).get(trade['interval'], {})
        current_price = data.get('price', 0)
        if not current_price > 0:
            continue

        tactic_cfg = TACTICS_LAB.get(trade['opened_by_tactic'], {})
        status, exit_p = None, None
        
        if 'initial_risk_dist' not in trade or trade['initial_risk_dist'] <= 0:
            trade['initial_risk_dist'] = trade['entry_price'] - trade['initial_sl']
        
        initial_risk_dist = trade.get('initial_risk_dist', 0)
        if initial_risk_dist <= 0: continue

        pnl_ratio_from_entry = (current_price - trade['entry_price']) / initial_risk_dist

        # 1. LOGIC CHỐT LỜI MỘT PHẦN (TP1)
        if tactic_cfg.get("ENABLE_PARTIAL_TP", False) and not trade.get('tp1_taken', False):
            tp1_rr_ratio = tactic_cfg.get("TP1_RR_RATIO", 1.0)
            if pnl_ratio_from_entry >= tp1_rr_ratio:
                profit_taken_pct = tactic_cfg.get("TP1_PROFIT_PCT", 0.5)
                invested_to_close = trade.get('total_invested_usd', 0.0) * profit_taken_pct
                tp1_price = trade['entry_price'] + (initial_risk_dist * tp1_rr_ratio)
                partial_pnl_usd = (tp1_price - trade['entry_price']) / trade['entry_price'] * invested_to_close
                
                portfolio_state['cash'] += (invested_to_close + partial_pnl_usd)
                trade['total_invested_usd'] -= invested_to_close
                trade['tp1_taken'] = True
                trade['sl'] = trade['entry_price'] 
                trade['trailing_sl'] = max(trade.get('trailing_sl', 0), trade['entry_price'])

                if "Partial_TP_Taken" not in trade.get('tactic_used', []):
                    trade.setdefault('tactic_used', []).append(f"Partial_TP_{tp1_rr_ratio}RR")

                log_message(f"💰 Đã chốt lời TP1 cho {trade['symbol']} (${invested_to_close:,.2f}) | PnL TP1: ${partial_pnl_usd:,.2f}. SL dời về hòa vốn.")
                newly_closed_details.append(f"💰 {trade['symbol']} (TP1): PnL ${partial_pnl_usd:,.2f}")

        # 2. LOGIC TRAILING STOP-LOSS (TSL)
        if tactic_cfg.get("USE_TRAILING_SL", False):
            if pnl_ratio_from_entry >= tactic_cfg.get("TRAIL_ACTIVATION_RR", 999):
                trail_dist_rr = tactic_cfg.get("TRAIL_DISTANCE_RR", 0.8)
                new_trailing_sl = current_price - (initial_risk_dist * trail_dist_rr)
                
                if new_trailing_sl > trade.get('trailing_sl', trade['sl']):
                    if "Trailing_SL_Active" not in trade.get('tactic_used', []):
                        trade.setdefault('tactic_used', []).append("Trailing_SL_Active")
                    trade['trailing_sl'] = new_trailing_sl
                    trade['sl'] = new_trailing_sl
        
        # 3. LOGIC ĐÓNG LỆNH CHÍNH THỨC
        final_sl = trade.get('trailing_sl', trade['sl'])
        if current_price <= final_sl:
            status, exit_p = "SL", final_sl
        elif current_price >= trade['tp']:
            status, exit_p = "TP", trade['tp']

        if status:
            pnl_ratio = (exit_p - trade['entry_price']) / trade['entry_price']
            pnl_usd = trade.get('total_invested_usd', 0.0) * pnl_ratio
            portfolio_state['cash'] += (trade.get('total_invested_usd', 0.0) + pnl_usd)
            trade.update({
                'status': f'Closed ({status})', 'exit_price': exit_p, 'exit_time': now_vn.isoformat(),
                'pnl_usd': pnl_usd, 'pnl_percent': pnl_ratio * 100
            })
            cooldown_duration = timedelta(hours=GENERAL_CONFIG.get("TRADE_COOLDOWN_HOURS", 1))
            cooldown_end_time = now_vn + cooldown_duration
            portfolio_state.setdefault('cooldown_until', {})[trade['symbol']] = cooldown_end_time.isoformat()
            
            portfolio_state['active_trades'].remove(trade)
            portfolio_state['trade_history'].append(trade)
            closed_trades.append(trade)
            icon = '✅' if status == 'TP' else ('❌' if pnl_usd < 0 else '🤝')
            log_message(f"{icon} Đã đóng lệnh {status}: {trade['symbol']} | PnL: ${pnl_usd:,.2f}")
            newly_closed_details.append(f"{icon} {trade['symbol']} ({status}): PnL ${pnl_usd:,.2f}")

    if newly_closed_details:
        portfolio_state.setdefault('temp_newly_closed_trades', []).extend(newly_closed_details)
        
    return closed_trades

def handle_stale_trades(portfolio_state: Dict) -> List[Dict]:
    closed_trades, newly_closed_details = [], []
    now_aware = datetime.now(VIETNAM_TZ)
    for trade in portfolio_state.get("active_trades", [])[:]:
        rules = RISK_RULES_CONFIG["STALE_TRADE_RULES"].get(trade.get("interval"))
        if not rules: continue
        entry_time = datetime.fromisoformat(trade['entry_time'])
        holding_duration_hours = (now_aware - entry_time).total_seconds() / 3600
        if holding_duration_hours > rules["HOURS"]:
            _, pnl_pct = get_current_pnl(trade)
            current_price = all_indicators.get(trade['symbol'], {}).get(trade['interval'], {}).get('price', 0)
            if not current_price > 0: continue
            
            progress_made = pnl_pct >= rules["PROGRESS_THRESHOLD"] * 100
            current_sl_buffer_pct = (current_price - trade['sl']) / trade['entry_price'] * 100
            if current_sl_buffer_pct >= rules["MIN_RISK_BUFFER_PCT"] * 100:
                progress_made = True

            if not progress_made:
                exit_price = current_price
                pnl_ratio = (exit_price - trade['entry_price']) / trade['entry_price']
                pnl_usd_final = trade.get('total_invested_usd', 0.0) * pnl_ratio
                portfolio_state['cash'] += (trade.get('total_invested_usd', 0.0) + pnl_usd_final)
                trade.setdefault('tactic_used', []).append("Stale_Closure")
                trade.update({
                    'status': 'Closed (Stale)', 'exit_price': exit_price, 'exit_time': now_aware.isoformat(),
                    'pnl_usd': pnl_usd_final, 'pnl_percent': pnl_ratio * 100
                })
                portfolio_state['active_trades'].remove(trade)
                portfolio_state['trade_history'].append(trade)
                closed_trades.append(trade)
                log_message(f"🐌 Đã đóng lệnh ì (Stale): {trade['symbol']} ({trade['interval']}) sau {holding_duration_hours:.1f}h | PnL: ${pnl_usd_final:,.2f}")
                newly_closed_details.append(f"🐌 {trade['symbol']} (Stale): PnL ${pnl_usd_final:,.2f}")
    
    if newly_closed_details:
        portfolio_state.setdefault('temp_newly_closed_trades', []).extend(newly_closed_details)
    return closed_trades

def handle_dca_opportunities(state: Dict, equity: float):
    if not DCA_CONFIG["ENABLED"]: return
    current_exposure_usd = sum(t.get('total_invested_usd', 0.0) for t in state.get('active_trades', []))
    for trade in state.get("active_trades", []):
        if len(trade.get("dca_entries", [])) >= DCA_CONFIG["MAX_DCA_ENTRIES"]: continue
        
        current_data = all_indicators.get(trade["symbol"], {}).get(trade["interval"], {})
        current_price = current_data.get('price', 0)
        if not current_price > 0: continue
        
        last_entry_price = trade['dca_entries'][-1]['entry_price'] if trade.get('dca_entries') else trade['initial_entry']['price']
        price_drop_pct = ((current_price - last_entry_price) / last_entry_price) * 100
        if price_drop_pct > DCA_CONFIG["TRIGGER_DROP_PCT"]: continue

        if trade.get('dca_entries'):
            last_dca_time = datetime.fromisoformat(trade['dca_entries'][-1]["timestamp"])
            if (datetime.now(VIETNAM_TZ) - last_dca_time).total_seconds() / 3600 < DCA_CONFIG["DCA_COOLDOWN_HOURS"]:
                continue

        decision = get_advisor_decision(trade['symbol'], trade['interval'], current_data, ADVISOR_BASE_CONFIG)
        if decision.get("final_score", 0.0) < DCA_CONFIG["SCORE_MIN_THRESHOLD"]: continue

        last_investment = trade['dca_entries'][-1]['invested_usd'] if trade.get('dca_entries') else trade['initial_entry']['invested_usd']
        dca_investment = last_investment * DCA_CONFIG["CAPITAL_MULTIPLIER"]
        
        if (current_exposure_usd + dca_investment) / equity > CAPITAL_MANAGEMENT_CONFIG["MAX_TOTAL_EXPOSURE_PCT"] or dca_investment > state['cash']:
            log_message(f"⚠️ Muốn DCA cho {trade['symbol']} nhưng vượt ngưỡng rủi ro hoặc không đủ tiền. Bỏ qua.")
            continue

        log_message(f"🎯 THỰC HIỆN DCA Lần {len(trade.get('dca_entries', [])) + 1} cho {trade['symbol']}...")
        state['cash'] -= dca_investment
        trade.setdefault('dca_entries', []).append({
            "entry_price": current_price, "invested_usd": dca_investment, "timestamp": datetime.now(VIETNAM_TZ).isoformat()
        })
        
        trade['total_invested_usd'] += dca_investment
        new_avg_price = calculate_average_price(trade)
        trade['entry_price'] = new_avg_price
        
        tactic_cfg = TACTICS_LAB.get(trade['opened_by_tactic'], {})
        initial_risk_dist = trade['initial_entry']['price'] - trade['initial_sl']
        trade['sl'] = new_avg_price - initial_risk_dist
        trade['tp'] = new_avg_price + (initial_risk_dist * tactic_cfg.get('RR', 2.0))
        trade['trailing_sl'] = trade['sl']
        trade['tp1_taken'] = False
        trade.setdefault('tactic_used', []).append(f"DCA_{len(trade.get('dca_entries', []))}")

        log_message(f"✅ DCA thành công. Vốn mới cho {trade['symbol']}: ${trade['total_invested_usd']:,.2f}. Giá TB mới: {new_avg_price:.4f}")

# ==============================================================================
# ================== BỘ NÃO & RA QUYẾT ĐỊNH (v2.7.0) ===========================
# ==============================================================================

def find_and_open_new_trades(state: Dict, equity: float, context: Dict):
    active_trades = state.get('active_trades', [])
    if len(active_trades) >= RISK_RULES_CONFIG["MAX_ACTIVE_TRADES"]:
        log_message(f"ℹ️ Đã đạt giới hạn {len(active_trades)}/{RISK_RULES_CONFIG['MAX_ACTIVE_TRADES']} lệnh. Không tìm lệnh mới.")
        return

    potential_opportunities = []
    now_vn = datetime.now(VIETNAM_TZ)

    log_message("🔎 Bắt đầu quét tất cả các cặp coin, khung thời gian và tactic...")
    for symbol in SYMBOLS_TO_SCAN:
        if any(t['symbol'] == symbol for t in active_trades): continue
        cooldown_map = state.get('cooldown_until', {})
        if symbol in cooldown_map and now_vn < datetime.fromisoformat(cooldown_map[symbol]): continue

        for interval in INTERVALS_TO_SCAN:
            indicators = all_indicators.get(symbol, {}).get(interval)
            if not (indicators and indicators.get('price', 0) > 0): continue
            
            for tactic_name, tactic_cfg in TACTICS_LAB.items():
                if not tactic_cfg.get("WEIGHTS"): continue
                decision = get_advisor_decision(symbol, interval, indicators, ADVISOR_BASE_CONFIG, weights_override=tactic_cfg.get("WEIGHTS"))
                score = decision.get("final_score", 0.0)
                entry_req = tactic_cfg.get("ENTRY_SCORE", 9.9)

                if score >= entry_req:
                    log_message(f"✅ Ứng viên tiềm năng: {symbol}-{interval} | Tactic: {tactic_name} | Điểm: {score:.2f} (>= {entry_req})")
                    potential_opportunities.append({
                        "decision": decision, "tactic_name": tactic_name, "tactic_cfg": tactic_cfg,
                        "score": score, "symbol": symbol, "interval": interval
                    })

    if not potential_opportunities:
        log_message("ℹ️ Phiên này không tìm thấy cơ hội nào đủ điều kiện sau khi quét toàn bộ.")
        return

    best_opportunity = sorted(potential_opportunities, key=lambda x: x['score'], reverse=True)[0]
    decision_data, tactic_name, tactic_cfg = best_opportunity['decision'], best_opportunity['tactic_name'], best_opportunity['tactic_cfg']
    symbol, interval, score = best_opportunity['symbol'], best_opportunity['interval'], best_opportunity['score']

    log_message(f"🏆 CƠ HỘI TỐT NHẤT PHIÊN: {symbol}-{interval} | Tactic: {tactic_name} | Điểm: {score:.2f}")

    full_indicators = decision_data.get('full_indicators', {})
    entry_p = full_indicators.get('price')
    capital_pct = determine_dynamic_capital_pct(full_indicators.get('atr_percent', 3.0))
    invested_amount = equity * capital_pct
    
    current_exposure_usd = sum(t.get('total_invested_usd', 0.0) for t in active_trades)
    if (current_exposure_usd + invested_amount) / equity > CAPITAL_MANAGEMENT_CONFIG["MAX_TOTAL_EXPOSURE_PCT"] or invested_amount > state['cash']:
        log_message(f"⚠️ Mở lệnh {symbol} sẽ vượt ngưỡng rủi ro hoặc không đủ tiền. Bỏ qua.")
        return

    use_atr_sl = tactic_cfg.get("USE_ATR_SL", False)
    risk_dist = (full_indicators.get('atr', 0) * tactic_cfg.get("ATR_SL_MULTIPLIER", 2.0)) if use_atr_sl else entry_p * 0.05
    sl_p = entry_p - risk_dist
    tp_p = entry_p + (risk_dist * tactic_cfg.get("RR", 2.0))
    if tp_p <= entry_p or sl_p <= 0 or risk_dist <= 0:
        log_message(f"⚠️ SL/TP không hợp lệ cho {symbol} ({tactic_name}). Bỏ qua.")
        return

    new_trade = {
        "trade_id": str(uuid.uuid4()), "symbol": symbol, "interval": interval, "status": "ACTIVE",
        "opened_by_tactic": tactic_name, "trade_type": "LONG", "entry_price": entry_p,
        "tp": round(tp_p, 8), "sl": round(sl_p, 8), "initial_sl": round(sl_p, 8),
        "initial_risk_dist": risk_dist, "total_invested_usd": invested_amount,
        "initial_entry": {"price": entry_p, "invested_usd": invested_amount},
        "entry_time": now_vn.isoformat(), "entry_score": score,
        "dca_entries": [], "tp1_taken": False, "trailing_sl": round(sl_p, 8),
        "tactic_used": [tactic_name]
    }
    state["cash"] -= invested_amount
    state["active_trades"].append(new_trade)
    log_message(f"🔥 Lệnh Mới: {symbol}-{interval} | Vốn: ${invested_amount:,.2f} | SL: {sl_p:.4f} | TP: {tp_p:.4f}")
    state.setdefault('temp_newly_opened_trades', []).append(f"🔥 {symbol}-{interval} ({tactic_name}): Vốn ${invested_amount:,.2f}")

# ==============================================================================
# ==================== BÁO CÁO & VÒNG LẶP CHÍNH ================================
# ==============================================================================

def build_report_header(state: Dict) -> str:
    total_equity = calculate_total_equity(state)
    cash = state.get('cash', INITIAL_CAPITAL)
    pnl_since_start = total_equity - INITIAL_CAPITAL
    pnl_percent = (pnl_since_start / INITIAL_CAPITAL) * 100 if INITIAL_CAPITAL > 0 else 0
    pnl_icon = "🟢" if pnl_since_start >= 0 else "🔴"
    return (
        f"💰 Vốn BĐ: **${INITIAL_CAPITAL:,.2f}** | 💵 Tiền mặt: **${cash:,.2f}**\n"
        f"📊 Tổng TS: **${total_equity:,.2f}** | 📈 PnL Tổng: {pnl_icon} **${pnl_since_start:,.2f} ({pnl_percent:+.2f}%)**"
    )

def build_trade_details_for_report(trade: Dict, current_price: float) -> str:
    pnl_usd, pnl_pct = get_current_pnl(trade)
    icon = "🟢" if pnl_usd >= 0 else "🔴"
    holding_h = (datetime.now(VIETNAM_TZ) - datetime.fromisoformat(trade['entry_time'])).total_seconds() / 3600
    dca_info = f" (DCA: {len(trade.get('dca_entries',[]))})" if trade.get('dca_entries') else ""
    tactic_cfg = TACTICS_LAB.get(trade.get('opened_by_tactic'), {})
    tsl_info = f" TSL:{trade['trailing_sl']:.4f}" if tactic_cfg.get("USE_TRAILING_SL") and 'trailing_sl' in trade and trade['trailing_sl'] > trade['initial_sl'] else ""
    tp1_info = " TP1✅" if trade.get('tp1_taken') else ""
    
    return (
        f"  {icon} **{trade['symbol']}-{trade['interval']}** ({trade['opened_by_tactic']} | {trade['entry_score']:.1f}) "
        f"PnL: **${pnl_usd:,.2f} ({pnl_pct:+.2f}%)** | Giữ:{holding_h:.1f}h{dca_info}{tp1_info}\n"
        f"    Entry:{trade['entry_price']:.4f} Cur:{current_price:.4f} SL:{trade['sl']:.4f} TP:{trade['tp']:.4f}{tsl_info} "
        f"Vốn:${trade.get('total_invested_usd', 0.0):,.2f}"
    )

def build_pnl_summary_line(state: Dict) -> str:
    trade_history = state.get('trade_history', [])
    active_trades = state.get('active_trades', [])
    if not trade_history and not active_trades: return "Chưa có giao dịch."

    df_history = pd.DataFrame(trade_history) if trade_history else pd.DataFrame()
    
    total_trades = len(df_history)
    winning_trades = len(df_history[df_history['pnl_usd'] > 0]) if total_trades > 0 else 0
    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
    
    total_pnl_closed = df_history['pnl_usd'].sum() if total_trades > 0 else 0.0
    unrealized_pnl = sum(get_current_pnl(trade)[0] for trade in active_trades)
    
    # PnL từ TP1 được tính bằng cách kiểm tra số tiền mặt tăng lên mà không phải do đóng lệnh hoàn toàn
    total_equity_pnl = calculate_total_equity(state) - INITIAL_CAPITAL
    partial_tp_pnl = total_equity_pnl - total_pnl_closed - unrealized_pnl
    
    unrealized_pnl_sign = '+' if unrealized_pnl >= 0 else ''
    return (
        f"🏆 Win Rate: **{win_rate:.2f}%** ({winning_trades}/{total_trades}) | "
        f"💰 PnL Đóng: **${total_pnl_closed:,.2f}** | "
        f"💵 PnL TP1: **${partial_tp_pnl:,.2f}** | "
        f"📈 PnL Mở: **{unrealized_pnl_sign}${unrealized_pnl:,.2f}**"
    )

def build_daily_summary_text(state: Dict) -> str:
    now_vn_str = datetime.now(VIETNAM_TZ).strftime('%H:%M %d-%m-%Y')
    lines = [f"📊 **BÁO CÁO TỔNG KẾT HÀNG NGÀY** - `{now_vn_str}` 📊", ""]
    lines.append(build_report_header(state))
    lines.append("\n" + build_pnl_summary_line(state))
    
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
            current_price = all_indicators.get(trade["symbol"], {}).get(trade["interval"], {}).get('price', 0)
            lines.append(build_trade_details_for_report(trade, current_price) if current_price > 0 else f"⚠️ {trade['symbol']} - Không có dữ liệu giá.")

    # === KHÔI PHỤC LOGIC BỊ MẤT ===
    lines.append("\n--- **Lịch sử giao dịch gần nhất** ---")
    trade_history = state.get('trade_history', [])
    if trade_history:
        df_history = pd.DataFrame(trade_history)
        df_history['pnl_usd'] = df_history['pnl_usd'].astype(float)
        
        # Đảm bảo cột exit_time tồn tại và có định dạng đúng
        if 'exit_time' in df_history.columns:
            df_history['exit_time_dt'] = pd.to_datetime(df_history['exit_time'])
            winning_trades = df_history[df_history['pnl_usd'] > 0]
            losing_trades = df_history[df_history['pnl_usd'] <= 0] # Bao gồm cả hòa vốn

            def format_closed_trade_line(trade_data):
                entry_time = datetime.fromisoformat(trade_data['entry_time'])
                exit_time = datetime.fromisoformat(trade_data['exit_time'])
                hold_duration_h = (exit_time - entry_time).total_seconds() / 3600

                tactics_list = trade_data.get('tactic_used', [])
                if isinstance(tactics_list, list) and tactics_list:
                    tactics_str = ', '.join(map(str, [t for t in tactics_list if pd.notna(t)]))
                else:
                    tactics_str = trade_data.get('opened_by_tactic', 'N/A')

                info_str = f"Tactic: {tactics_str}"
                symbol_with_interval = f"{trade_data['symbol']}-{trade_data.get('interval', 'N/A')}"
                pnl_info = f"${trade_data.get('pnl_usd', 0):.2f} ({trade_data.get('pnl_percent', 0):+.2f}%)"
                return f"  • **{symbol_with_interval}** | PnL: `{pnl_info}` | {info_str} | Hold: {hold_duration_h:.1f}h"

            lines.append("\n**✅ Top 5 lệnh lãi gần nhất**")
            if not winning_trades.empty:
                recent_winning_trades = winning_trades.sort_values(by='exit_time_dt', ascending=False).head(5)
                for _, trade in recent_winning_trades.iterrows():
                    try: lines.append(format_closed_trade_line(trade))
                    except Exception as e: lines.append(f"  • {trade.get('symbol')} - Lỗi báo cáo: {e}")
            else:
                lines.append("  (Chưa có lệnh lãi)")

            lines.append("\n**❌ Top 5 lệnh lỗ/hòa vốn gần nhất**")
            if not losing_trades.empty:
                recent_losing_trades = losing_trades.sort_values(by='exit_time_dt', ascending=False).head(5)
                for _, trade in recent_losing_trades.iterrows():
                    try: lines.append(format_closed_trade_line(trade))
                    except Exception as e: lines.append(f"  • {trade.get('symbol')} - Lỗi báo cáo: {e}")
            else:
                lines.append("  (Chưa có lệnh lỗ/hòa vốn)")
        else:
            lines.append(" (Lịch sử giao dịch chưa có thời gian đóng lệnh để sắp xếp.)")
    else:
        lines.append("  (Chưa có lịch sử giao dịch)")
    # =================================

    lines.append("\n====================================")
    return "\n".join(lines)

def build_dynamic_alert_text(state: Dict) -> str:
    now_vn_str = datetime.now(VIETNAM_TZ).strftime('%H:%M %d-%m-%Y')
    lines = [f"💡 **CẬP NHẬT ĐỘNG** - `{now_vn_str}` 💡", ""]
    lines.append(build_report_header(state))
    lines.append("\n" + build_pnl_summary_line(state))
    
    lines.append("\n--- **Vị thế đang mở** ---")
    active_trades = state.get('active_trades', [])
    lines.append(f"💼 Tổng vị thế đang mở: **{len(active_trades)}**")
    if not active_trades: lines.append("    (Không có vị thế nào)")
    else:
        for trade in sorted(active_trades, key=lambda x: x['entry_time']):
            current_price = all_indicators.get(trade["symbol"], {}).get(trade["interval"], {}).get('price', 0)
            lines.append(build_trade_details_for_report(trade, current_price) if current_price > 0 else f"⚠️ {trade['symbol']} - Không có dữ liệu giá.")
            
    lines.append("\n====================================")
    return "\n".join(lines)

def should_send_dynamic_alert(state: Dict) -> bool:
    if not DYNAMIC_ALERT_CONFIG["ENABLED"]: return False
    now = datetime.now(VIETNAM_TZ)
    last_alert = state.get('last_dynamic_alert', {})
    if not last_alert.get('timestamp'): return bool(state.get('active_trades'))
    
    last_alert_dt = datetime.fromisoformat(last_alert.get('timestamp')).astimezone(VIETNAM_TZ)
    hours_since = (now - last_alert_dt).total_seconds() / 3600
    
    if hours_since >= DYNAMIC_ALERT_CONFIG["FORCE_UPDATE_HOURS"]: return True
    if hours_since < DYNAMIC_ALERT_CONFIG["COOLDOWN_HOURS"]: return False
    
    current_equity = calculate_total_equity(state)
    current_pnl_pct = ((current_equity - INITIAL_CAPITAL) / INITIAL_CAPITAL) * 100 if INITIAL_CAPITAL > 0 else 0
    pnl_change = abs(current_pnl_pct - last_alert.get('total_pnl_percent', 0.0))
    
    return pnl_change >= DYNAMIC_ALERT_CONFIG["PNL_CHANGE_THRESHOLD_PCT"]

def run_session():
    session_id = datetime.now(VIETNAM_TZ).strftime('%Y%m%d_%H%M%S')
    log_message(f"====== 🚀 BẮT ĐẦU PHIÊN (v2.7.0 - Chiến Binh Giàu Kinh Nghiệm) (ID: {session_id}) 🚀 ======")
    try:
        state = load_json_file(STATE_FILE, {
            "cash": INITIAL_CAPITAL, "active_trades": [], "trade_history": [],
            "last_dynamic_alert": {}, "last_daily_reports_sent": {}, "cooldown_until": {}
        })
        state.pop('temp_newly_opened_trades', None)
        state.pop('temp_newly_closed_trades', None)

        log_message("⏳ Đang tải và tính toán indicators...")
        all_indicators.clear()
        for symbol in list(set(SYMBOLS_TO_SCAN + ["BTCUSDT"])):
            all_indicators[symbol] = {}
            for interval in ALL_TIME_FRAMES:
                df = safe_get_price_data(symbol, interval, GENERAL_CONFIG["DATA_FETCH_LIMIT"])
                if df is not None:
                    all_indicators[symbol][interval] = calculate_indicators(df, symbol, interval)
        log_message("✅ Đã tải xong indicators.")

        all_closed_in_session = handle_trade_closure(state) + handle_stale_trades(state)
        if all_closed_in_session:
            export_trade_history_to_csv(all_closed_in_session)

        total_equity = calculate_total_equity(state)
        handle_dca_opportunities(state, total_equity)

        find_and_open_new_trades(state, total_equity, {})

        now_vn = datetime.now(VIETNAM_TZ)
        for daily_time in GENERAL_CONFIG["DAILY_SUMMARY_TIMES"]:
            last_sent_iso = state.get('last_daily_reports_sent', {}).get(daily_time)
            sent_today = last_sent_iso and datetime.fromisoformat(last_sent_iso).date() == now_vn.date()
            h, m = map(int, daily_time.split(':'))
            if now_vn.hour == h and now_vn.minute >= m and not sent_today:
                log_message(f"🔔 Gửi báo cáo hàng ngày cho khung giờ {daily_time}.")
                send_discord_message_chunks(build_daily_summary_text(state))
                state.setdefault('last_daily_reports_sent', {})[daily_time] = now_vn.isoformat()

        if should_send_dynamic_alert(state):
            log_message("🔔 Gửi alert động.")
            send_discord_message_chunks(build_dynamic_alert_text(state))
            state['last_dynamic_alert'] = {
                "timestamp": now_vn.isoformat(),
                "total_pnl_percent": ((calculate_total_equity(state) - INITIAL_CAPITAL) / INITIAL_CAPITAL) * 100 if INITIAL_CAPITAL > 0 else 0
            }
        save_json_file(STATE_FILE, state)
    except Exception:
        error_details = traceback.format_exc()
        log_message(f"!!!!!! ❌ LỖI NGHIÊM TRỌNG ❌ !!!!!!\n{error_details}")
        send_discord_message_chunks(f"🔥🔥🔥 BOT GẶP LỖI NGHIÊM TRỌNG 🔥🔥🔥\n```python\n{error_details}\n```")
    log_message(f"====== ✅ KẾT THÚC PHIÊN (ID: {session_id}) ✅ ======\n")

if __name__ == "__main__":
    run_session()
