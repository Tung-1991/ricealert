# -*- coding: utf-8 -*-
"""
paper_trade.py - Quản lý Danh mục & Rủi ro Thông minh
Version: 2.6.0 - "Tướng Kiểm Soát"
Date: 2025-07-21

Description:
Phiên bản "Tướng Kiểm Soát" được nâng cấp trực tiếp từ v2.5.2,
hiện thực hóa ý tưởng về khả năng truy vết và kiểm soát hành vi của bot.
Bổ sung 2 trường dữ liệu quan trọng vào mỗi giao dịch:
- tactic_used: Một danh sách ghi lại tất cả các chiến thuật đã tác động đến lệnh (Mở lệnh, DCA, TSL, Chốt lời TP1...).
- tactic_overridden: Ghi lại trường hợp một chiến thuật bị ghi đè bởi một chiến thuật khác an toàn hơn.
Điều này mang lại khả năng phân tích và gỡ lỗi sâu sắc chưa từng có.
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
# ================== ⚙️ TRUNG TÂM CẤU HÌNH (v2.6.0) ⚙️ ==================
# ==============================================================================

INITIAL_CAPITAL = 10000.0

GENERAL_CONFIG = {
    "DATA_FETCH_LIMIT": 300,
    "DAILY_SUMMARY_TIMES": ["08:05", "20:05"],
    "TRADE_COOLDOWN_HOURS": 1
}

TACTIC_OVERRIDE_CONFIG = {
    "ENABLED": True,
    "MIN_SCORE_TO_OVERRIDE": 7.8,
    "OVERRIDE_TACTIC_NAME": "Cautious_Observer"
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
    "TACTIC_TO_TIER_MAP": {
        "AI_Aggressor": "LOW_RISK", "Breakout_Hunter": "LOW_RISK",
        "Balanced_Trader": "MEDIUM_RISK", "Market_Mirror": "MEDIUM_RISK",
        "Dip_Hunter": "HIGH_RISK", "Range_Trader": "HIGH_RISK", "Cautious_Observer": "HIGH_RISK",
    },
    "MAX_TOTAL_EXPOSURE_PCT": 0.75
}

DCA_CONFIG = {
    "ENABLED": True,
    "MAX_DCA_ENTRIES": 2,
    "TRIGGER_DROP_PCT": -5.0,
    "SCORE_MIN_THRESHOLD": 4.5,
    "CAPITAL_MULTIPLIER": 1.5,
    "DCA_COOLDOWN_HOURS": 8
}

ALERT_CONFIG = {
    "DISCORD_WEBHOOK_URL": os.getenv("DISCORD_PAPER_WEBHOOK"),
    "DISCORD_CHUNK_DELAY_SECONDS": 2,
}

TACTICS_LAB = {
    "AI_Aggressor": {
        "NOTES": "Tin vào AI, tự động gồng lời với Trailing SL",
        "WEIGHTS": {'tech': 0.1, 'context': 0.1, 'ai': 0.8},
        "ENTRY_SCORE": 6.5, "RR": 2.5, "USE_ATR_SL": True, "ATR_SL_MULTIPLIER": 3.0,
        "USE_TRAILING_SL": True, "TRAIL_ACTIVATION_RR": 1.0, "TRAIL_DISTANCE_RR": 0.8,
        "ENABLE_PARTIAL_TP": True, "TP1_RR_RATIO": 0.8, "TP1_PROFIT_PCT": 0.5
    },
    "Balanced_Trader": {
        "NOTES": "Cân bằng, có chốt lời sớm",
        "WEIGHTS": {'tech': 0.4, 'context': 0.2, 'ai': 0.4},
        "ENTRY_SCORE": 6.0, "RR": 2.2, "USE_ATR_SL": True, "ATR_SL_MULTIPLIER": 2.5,
        "ENABLE_PARTIAL_TP": True, "TP1_RR_RATIO": 0.8, "TP1_PROFIT_PCT": 0.5
    },
    "Dip_Hunter": {
        "NOTES": "Bắt đáy khi sợ hãi...",
        "WEIGHTS": {'tech': 0.5, 'context': 0.3, 'ai': 0.2},
        "ENTRY_SCORE": 6.5, "RR": 3.0, "USE_ATR_SL": True, "ATR_SL_MULTIPLIER": 2.0,
        "ENABLE_PARTIAL_TP": True, "TP1_RR_RATIO": 0.7, "TP1_PROFIT_PCT": 0.4
    },
    "Breakout_Hunter": {
        "NOTES": "Săn đột biến giá/volume, có Trailing SL",
        "WEIGHTS": {'tech': 0.7, 'context': 0.1, 'ai': 0.2},
        "ENTRY_SCORE": 7.0, "RR": 2.8, "USE_ATR_SL": True, "ATR_SL_MULTIPLIER": 2.0,
        "USE_TRAILING_SL": True, "TRAIL_ACTIVATION_RR": 1.0, "TRAIL_DISTANCE_RR": 0.8,
        "ENABLE_PARTIAL_TP": False
    },
    "Cautious_Observer": {
        "NOTES": "Bảo toàn vốn...",
        "WEIGHTS": {'tech': 0.5, 'context': 0.5, 'ai': 0.0},
        "ENTRY_SCORE": 8.5, "ENABLE_PARTIAL_TP": False
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
        
        # ✨ CẬP NHẬT v2.6: Thêm các cột truy vết tactic
        cols = ["trade_id", "symbol", "interval", "status", "opened_by_tactic",
                "tactic_used", "tactic_overridden",
                "trade_type", "entry_price", "exit_price", "tp", "sl", "total_invested_usd",
                "pnl_usd", "pnl_percent", "entry_time", "exit_time", "holding_duration_hours",
                "entry_score", "dca_entries"]
        
        df = df[[c for c in cols if c in df.columns]]
        
        # ✨ CẬP NHẬT v2.6: Xử lý định dạng cho các cột mới
        if 'dca_entries' in df.columns:
            df['dca_entries'] = df['dca_entries'].apply(lambda x: json.dumps(x) if x else '[]')
        if 'tactic_used' in df.columns:
            df['tactic_used'] = df['tactic_used'].apply(lambda x: json.dumps(x) if x else '[]')
            
        df.to_csv(TRADE_HISTORY_CSV_FILE, mode='a' if os.path.exists(TRADE_HISTORY_CSV_FILE) else 'w', header=not os.path.exists(TRADE_HISTORY_CSV_FILE), index=False, encoding="utf-8")
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
    initial_investment = trade['initial_entry'].get('invested_usd', 0.0)
    initial_price = trade['initial_entry'].get('price', 0.0)
    total_invested_value = initial_investment
    total_cost = initial_investment * initial_price
    for dca in trade.get('dca_entries', []):
        total_invested_value += dca.get('invested_usd', 0.0)
        total_cost += dca.get('invested_usd', 0.0) * dca.get('entry_price', 0.0)
    return total_cost / total_invested_value if total_invested_value > 0 else 0

def handle_trade_closure(portfolio_state: Dict) -> List[Dict]:
    closed_trades, newly_closed_details = [], []
    now_vn = datetime.now(VIETNAM_TZ)
    for trade in portfolio_state["active_trades"][:]:
        data = all_indicators.get(trade['symbol'], {}).get(trade['interval'], {})
        current_price = data.get('price', 0)
        if not current_price > 0: continue
        status, exit_p = (None, None)
        tactic_cfg = TACTICS_LAB.get(trade['opened_by_tactic'], {})
        
        # Trailing SL
        if tactic_cfg.get("USE_TRAILING_SL", False) and 'initial_risk_dist' in trade and trade['initial_risk_dist'] > 0:
            pnl_ratio_from_entry = (current_price - trade['entry_price']) / trade['initial_risk_dist']
            if pnl_ratio_from_entry >= tactic_cfg["TRAIL_ACTIVATION_RR"]:
                new_trailing_sl = current_price - (trade['initial_risk_dist'] * tactic_cfg.get("TRAIL_DISTANCE_RR", 0.8))
                if new_trailing_sl > trade.get('trailing_sl', trade['sl']):
                    # ✨ CẬP NHẬT v2.6: Ghi nhận hành động Trailing SL
                    if "Trailing_SL_Active" not in trade.get('tactic_used', []):
                        trade.setdefault('tactic_used', []).append("Trailing_SL_Active")
                    trade['trailing_sl'] = new_trailing_sl
                    trade['sl'] = new_trailing_sl
        
        # Partial TP
        if tactic_cfg.get("ENABLE_PARTIAL_TP", False) and not trade.get('tp1_taken', False) and 'initial_risk_dist' in trade and trade['initial_risk_dist'] > 0:
            tp1_price = trade['entry_price'] + (trade['initial_risk_dist'] * tactic_cfg.get("TP1_RR_RATIO", 0.8))
            if current_price >= tp1_price:
                profit_taken_pct = tactic_cfg.get("TP1_PROFIT_PCT", 0.5)
                invested_to_close = trade.get('total_invested_usd', 0.0) * profit_taken_pct
                partial_pnl_usd = (tp1_price - trade['entry_price']) / trade['entry_price'] * invested_to_close
                portfolio_state['cash'] += (invested_to_close + partial_pnl_usd)
                trade['total_invested_usd'] -= invested_to_close
                trade['tp1_taken'] = True
                trade['sl'] = trade['entry_price']
                trade['trailing_sl'] = max(trade.get('trailing_sl', trade['sl']), trade['entry_price'])
                
                # ✨ CẬP NHẬT v2.6: Ghi nhận hành động Chốt lời từng phần
                if "Partial_TP_Taken" not in trade.get('tactic_used', []):
                    trade.setdefault('tactic_used', []).append("Partial_TP_Taken")
                    
                log_message(f"💰 Đã chốt lời TP1 cho {trade['symbol']} (${invested_to_close:,.2f}) | PnL TP1: ${partial_pnl_usd:,.2f}. SL dời về hòa vốn.")
                newly_closed_details.append(f"💰 {trade['symbol']} (TP1): PnL ${partial_pnl_usd:,.2f}")
        
        # Check SL/TP
        if current_price <= trade['sl']: status, exit_p = "SL", trade['sl']
        elif current_price >= trade['tp']: status, exit_p = "TP", trade['tp']
        
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
            log_message(f"❄️ Đặt Cooldown cho {trade['symbol']} đến {cooldown_end_time.strftime('%H:%M %d-%m-%Y')}")
            portfolio_state['active_trades'].remove(trade)
            portfolio_state['trade_history'].append(trade)
            closed_trades.append(trade)
            icon = '✅' if status == 'TP' else '❌'
            log_message(f"{icon} Đã đóng lệnh {status}: {trade['symbol']} | PnL: ${pnl_usd:,.2f}")
            newly_closed_details.append(f"{icon} {trade['symbol']} ({status}): PnL ${pnl_usd:,.2f}")
    if newly_closed_details:
        portfolio_state['temp_newly_closed_trades'] = newly_closed_details
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
            progress_made = pnl_pct >= rules["PROGRESS_THRESHOLD"] * 100
            current_price = all_indicators.get(trade['symbol'], {}).get(trade['interval'], {}).get('price', 0)
            if current_price > 0 and trade.get('entry_price', 0) > 0 and trade.get('sl', 0) > 0:
                current_sl_buffer_pct = (current_price - trade['sl']) / trade['entry_price'] * 100
                if current_sl_buffer_pct >= rules["MIN_RISK_BUFFER_PCT"] * 100:
                    progress_made = True
            if not progress_made:
                exit_price = current_price or trade['entry_price']
                pnl_ratio = (exit_price - trade['entry_price']) / trade['entry_price']
                pnl_usd_final = trade.get('total_invested_usd', 0.0) * pnl_ratio
                portfolio_state['cash'] += (trade.get('total_invested_usd', 0.0) + pnl_usd_final)
                
                # ✨ CẬP NHẬT v2.6: Ghi nhận hành động đóng lệnh Stale
                trade.setdefault('tactic_used', []).append("Stale_Closure")
                
                trade.update({
                    'status': 'Closed (Stale)', 'exit_price': exit_price, 'exit_time': now_aware.isoformat(),
                    'pnl_usd': pnl_usd_final, 'pnl_percent': pnl_ratio * 100
                })
                cooldown_duration = timedelta(hours=GENERAL_CONFIG.get("TRADE_COOLDOWN_HOURS", 1))
                cooldown_end_time = now_aware + cooldown_duration
                portfolio_state.setdefault('cooldown_until', {})[trade['symbol']] = cooldown_end_time.isoformat()
                log_message(f"❄️ Đặt Cooldown cho {trade['symbol']} đến {cooldown_end_time.strftime('%H:%M %d-%m-%Y')}")
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
        last_entry_price = trade['dca_entries'][-1].get('entry_price', trade['entry_price']) if trade.get('dca_entries') else trade['entry_price']
        price_drop_pct = ((current_price - last_entry_price) / last_entry_price) * 100
        if price_drop_pct > DCA_CONFIG["TRIGGER_DROP_PCT"]: continue
        if trade.get('dca_entries'):
            last_dca_time_iso = trade['dca_entries'][-1].get("timestamp")
            if last_dca_time_iso:
                last_dca_time = datetime.fromisoformat(last_dca_time_iso)
                hours_since_last_dca = (datetime.now(VIETNAM_TZ) - last_dca_time).total_seconds() / 3600
                if hours_since_last_dca < DCA_CONFIG.get("DCA_COOLDOWN_HOURS", 24):
                    continue
        decision = get_advisor_decision(trade['symbol'], trade['interval'], current_data, ADVISOR_BASE_CONFIG)
        current_score = decision.get("final_score", 0.0)
        if current_score < DCA_CONFIG["SCORE_MIN_THRESHOLD"]: continue
        last_investment = trade['dca_entries'][-1].get('invested_usd', 0.0) if trade.get('dca_entries') else trade.get('total_invested_usd', 0.0)
        dca_investment = last_investment * DCA_CONFIG["CAPITAL_MULTIPLIER"]
        potential_exposure_usd = current_exposure_usd + dca_investment
        if potential_exposure_usd / equity > CAPITAL_MANAGEMENT_CONFIG["MAX_TOTAL_EXPOSURE_PCT"]:
            log_message(f"⚠️ Muốn DCA cho {trade['symbol']} nhưng sẽ vượt ngưỡng exposure. Bỏ qua.")
            continue
        if dca_investment > state['cash']:
            log_message(f"⚠️ Muốn DCA cho {trade['symbol']} nhưng không đủ tiền mặt. Cần ${dca_investment:,.2f}, còn ${state['cash']:,.2f}")
            continue

        dca_count = len(trade.get('dca_entries', [])) + 1
        log_message(f"🎯 THỰC HIỆN DCA Lần {dca_count} cho {trade['symbol']}...")
        
        # ✨ CẬP NHẬT v2.6: Ghi nhận hành động DCA
        trade.setdefault('tactic_used', []).append(f"DCA_{dca_count}")

        state['cash'] -= dca_investment
        trade.setdefault('dca_entries', []).append({
            "entry_price": current_price, "invested_usd": dca_investment, "timestamp": datetime.now(VIETNAM_TZ).isoformat()
        })
        new_total_invested = trade.get('total_invested_usd', 0.0) + dca_investment
        new_avg_price = calculate_average_price(trade)
        trade['entry_price'] = new_avg_price
        trade['total_invested_usd'] = new_total_invested
        initial_risk_dist_original = trade['initial_entry'].get('price', trade['entry_price']) - trade['initial_sl']
        if initial_risk_dist_original <= 0: initial_risk_dist_original = new_avg_price * 0.02
        tactic_cfg = TACTICS_LAB.get(trade['opened_by_tactic'], {})
        trade['sl'] = new_avg_price - initial_risk_dist_original
        trade['tp'] = new_avg_price + (initial_risk_dist_original * tactic_cfg.get('RR', 2.0))
        if tactic_cfg.get("USE_TRAILING_SL", False):
            if 'trailing_sl' in trade and trade.get('initial_entry', {}).get('price', 0) > 0 and trade.get('trailing_sl', 0) > 0:
                original_tsl_dist_from_entry = trade['initial_entry']['price'] - trade['trailing_sl']
                trade['trailing_sl'] = new_avg_price - original_tsl_dist_from_entry
                trade['sl'] = trade['trailing_sl']
            else:
                trade['trailing_sl'] = trade['sl']
            trade['tp1_taken'] = False
        log_message(f"✅ DCA thành công. Vốn mới cho {trade['symbol']}: ${new_total_invested:,.2f}. Giá TB mới: {new_avg_price:.4f}")

# ==============================================================================
# ================== BỘ NÃO & RA QUYẾT ĐỊNH ====================================
# ==============================================================================

def select_best_tactic_for_symbol(market_context: Dict, coin_indicators: Dict) -> str:
    scores = {"AI_Aggressor": 0, "Balanced_Trader": 0, "Dip_Hunter": 0, "Breakout_Hunter": 0, "Cautious_Observer": 0.5}
    fear_greed = market_context.get("fear_greed", 50)
    btc_adx = market_context.get("btc_d1_adx", 20.0)

    if fear_greed >= 68 and btc_adx > 25:
        scores["AI_Aggressor"] += 2.5; scores["Breakout_Hunter"] += 2; scores["Dip_Hunter"] -= 1.5
    elif fear_greed <= 30:
        scores["Dip_Hunter"] += 3; scores["Cautious_Observer"] += 1.5; scores["AI_Aggressor"] -= 1; scores["Breakout_Hunter"] -= 1
    elif 40 <= fear_greed <= 60 and btc_adx < 20:
        scores["Balanced_Trader"] += 2
    else:
        scores["Balanced_Trader"] += 1

    coin_rsi = coin_indicators.get('rsi_14', 50); coin_adx = coin_indicators.get("adx", 20)
    coin_vol = coin_indicators.get("volume", 0); coin_vol_ma = max(coin_indicators.get('vol_ma20', 1), 1)
    price = coin_indicators.get("price", 0); ema200 = coin_indicators.get("ema_200", price)

    if coin_rsi < 32: scores["Dip_Hunter"] += 2.5
    if coin_rsi > 70: scores["AI_Aggressor"] -= 1
    if coin_adx > 28 and price > ema200:
        scores["AI_Aggressor"] += 1.5; scores["Breakout_Hunter"] += 1; scores["Dip_Hunter"] -= 2
    if coin_vol > coin_vol_ma * 2.5:
        scores["Breakout_Hunter"] += 3; scores["AI_Aggressor"] += 1
    if coin_adx < 20 and 40 < coin_rsi < 60:
        scores["Balanced_Trader"] += 1.5; scores["AI_Aggressor"] -= 1; scores["Breakout_Hunter"] -= 1

    for k in scores: scores[k] = max(0, scores[k])
    if all(s == 0 for s in scores.values()):
        return "Balanced_Trader"
    return max(scores, key=scores.get)

def find_and_open_new_trades(state: Dict, equity: float, context: Dict):
    active_trades = state.get('active_trades', [])
    if len(active_trades) >= RISK_RULES_CONFIG["MAX_ACTIVE_TRADES"]:
        log_message(f"ℹ️ Đã đạt giới hạn {len(active_trades)}/{RISK_RULES_CONFIG['MAX_ACTIVE_TRADES']} lệnh. Không tìm lệnh mới.")
        return

    potential_opportunities = []
    now_vn = datetime.now(VIETNAM_TZ)

    for symbol in SYMBOLS_TO_SCAN:
        if any(t['symbol'] == symbol for t in active_trades): continue
        
        cooldown_map = state.get('cooldown_until', {})
        if symbol in cooldown_map and now_vn < datetime.fromisoformat(cooldown_map[symbol]): continue
        
        primary_indicators = all_indicators.get(symbol, {}).get("4h") or all_indicators.get(symbol, {}).get("1d")
        if not primary_indicators: continue

        original_chosen_tactic = select_best_tactic_for_symbol(context, primary_indicators)

        for interval in INTERVALS_TO_SCAN:
            indicators = all_indicators.get(symbol, {}).get(interval)
            if not (indicators and indicators.get('price', 0) > 0): continue

            base_decision = get_advisor_decision(symbol, interval, indicators, ADVISOR_BASE_CONFIG)
            base_score = base_decision.get("final_score", 0.0)
            
            tactic_to_use_name = original_chosen_tactic
            is_override = False

            if (TACTIC_OVERRIDE_CONFIG["ENABLED"] and base_score >= TACTIC_OVERRIDE_CONFIG["MIN_SCORE_TO_OVERRIDE"]):
                override_tactic_name = TACTIC_OVERRIDE_CONFIG["OVERRIDE_TACTIC_NAME"]
                tactic_to_use_name = override_tactic_name
                is_override = True
                log_message(f"🔥 VƯỢT RÀO: {symbol}-{interval} có điểm gốc {base_score:.2f}, ưu tiên dùng Tactic '{override_tactic_name}'")
            
            tactic_to_use_cfg = TACTICS_LAB.get(tactic_to_use_name, {})
            final_decision = get_advisor_decision(symbol, interval, indicators, ADVISOR_BASE_CONFIG, weights_override=tactic_to_use_cfg.get("WEIGHTS"))
            final_score = final_decision.get("final_score", 0.0)
            entry_req = tactic_to_use_cfg.get("ENTRY_SCORE", 9.9)

            if final_score >= entry_req:
                potential_opportunities.append({
                    "decision": final_decision, "tactic_name": tactic_to_use_name,
                    "tactic_cfg": tactic_to_use_cfg, "is_override": is_override,
                    "original_tactic": original_chosen_tactic
                })
            elif final_score > 5.0:
                log_message(
                    f"⚠️  Loại bỏ {symbol}-{interval}. Lý do: Tactic '{tactic_to_use_name}'. "
                    f"Điểm cuối: {final_score:.2f} (Yêu cầu: >={entry_req})"
                )

    if not potential_opportunities:
        log_message("ℹ️ Phiên này không tìm thấy cơ hội nào đủ điều kiện.")
        return

    best_opportunity = sorted(potential_opportunities, key=lambda x: (x['is_override'], x['decision']['final_score']), reverse=True)[0]
    decision_data = best_opportunity['decision']
    tactic_name, tactic_cfg = best_opportunity['tactic_name'], best_opportunity['tactic_cfg']
    is_override, original_tactic = best_opportunity['is_override'], best_opportunity['original_tactic']
    
    full_indicators = decision_data.get('full_indicators', {})
    symbol, interval, score, entry_p = full_indicators.get('symbol'), full_indicators.get('interval'), decision_data.get('final_score'), full_indicators.get('price')

    log_message(f"🏆 Cơ hội tốt nhất: {symbol}-{interval} | Tactic: {tactic_name} | Điểm: {score:.2f}")

    capital_pct = determine_dynamic_capital_pct(full_indicators.get('atr_percent', 3.0))
    invested_amount = equity * capital_pct
    current_exposure_usd = sum(t.get('total_invested_usd', 0.0) for t in active_trades)
    potential_exposure_pct = (current_exposure_usd + invested_amount) / equity
    
    if potential_exposure_pct > CAPITAL_MANAGEMENT_CONFIG["MAX_TOTAL_EXPOSURE_PCT"]:
        log_message(f"⚠️ Mở lệnh {symbol} sẽ vượt ngưỡng exposure ({potential_exposure_pct*100:.1f}% > {CAPITAL_MANAGEMENT_CONFIG['MAX_TOTAL_EXPOSURE_PCT']*100:.1f}%). Bỏ qua.")
        return
    if invested_amount > state['cash']:
        log_message(f"⚠️ Không đủ tiền mặt để mở lệnh {symbol}. Cần ${invested_amount:,.2f}, còn ${state['cash']:,.2f}")
        return

    risk_dist = (full_indicators.get('atr', 0) * tactic_cfg.get("ATR_SL_MULTIPLIER", 2.0)) if tactic_cfg.get("USE_ATR_SL") else entry_p * 0.05
    sl_p, tp_p = entry_p - risk_dist, entry_p + (risk_dist * tactic_cfg.get("RR", 2.0))
    if tp_p <= entry_p or sl_p <= 0:
        log_message(f"⚠️ SL/TP không hợp lệ cho {symbol}. Bỏ qua.")
        return

    new_trade = {
        "trade_id": str(uuid.uuid4()), "symbol": symbol, "interval": interval, "status": "ACTIVE",
        "opened_by_tactic": tactic_name, "trade_type": "LONG", "entry_price": entry_p,
        "tp": round(tp_p, 8), "sl": round(sl_p, 8), "initial_sl": round(sl_p, 8),
        "initial_risk_dist": risk_dist, "total_invested_usd": invested_amount,
        "initial_entry": {"price": entry_p, "invested_usd": invested_amount},
        "entry_time": now_vn.isoformat(), "entry_score": score,
        "dca_entries": [], "tp1_taken": False, "trailing_sl": round(sl_p, 8),
        
        # ✨ CẬP NHẬT v2.6: Thêm các trường truy vết
        "tactic_used": [tactic_name],
        "tactic_overridden": f"{original_tactic} -> {tactic_name}" if is_override else ""
    }
    state["cash"] -= invested_amount
    state["active_trades"].append(new_trade)
    log_message(f"🔥 Lệnh Mới: {symbol}-{interval} | Vốn: ${invested_amount:,.2f} | SL: {sl_p:.4f} | TP: {tp_p:.4f}")
    state.setdefault('temp_newly_opened_trades', []).append(f"🔥 {symbol}-{interval} ({tactic_name}): Vốn ${invested_amount:,.2f}")

# ==============================================================================
# ==================== BÁO CÁO & VÒNG LẶP CHÍNH ================================
# ==============================================================================

def build_report_header(state: Dict) -> List[str]:
    total_equity = calculate_total_equity(state)
    cash = state.get('cash', INITIAL_CAPITAL)
    pnl_since_start = total_equity - INITIAL_CAPITAL
    pnl_percent = (pnl_since_start / INITIAL_CAPITAL) * 100 if INITIAL_CAPITAL > 0 else 0
    pnl_icon = "🟢" if pnl_since_start >= 0 else "🔴"
    return [
        f"💰 Vốn ban đầu: **${INITIAL_CAPITAL:,.2f}**",
        f"💵 Tiền mặt hiện có: **${cash:,.2f}**",
        f"📊 Tổng tài sản (Equity): **${total_equity:,.2f}**",
        f"📈 PnL Tổng cộng: {pnl_icon} **${pnl_since_start:,.2f} ({pnl_percent:+.2f}%)**"
    ]

def build_trade_details_for_report(trade: Dict, current_price: float) -> str:
    pnl_usd, pnl_pct = get_current_pnl(trade)
    icon = "🟢" if pnl_usd >= 0 else "🔴"
    holding_h = (datetime.now(VIETNAM_TZ) - datetime.fromisoformat(trade['entry_time'])).total_seconds() / 3600
    dca_info = f" (DCA: {len(trade.get('dca_entries',[]))})" if trade.get('dca_entries') else ""
    tsl_info = f" TSL:{trade['trailing_sl']:.4f}" if TACTICS_LAB.get(trade.get('opened_by_tactic'), {}).get("USE_TRAILING_SL") and 'trailing_sl' in trade else ""
    return (
        f"  {icon} **{trade['symbol']}-{trade.get('interval', 'N/A')}** ({trade.get('opened_by_tactic', 'N/A')} | Score:{trade.get('entry_score', 0.0):.1f}) "
        f"PnL: ${pnl_usd:,.2f} ({pnl_pct:+.2f}%) | Giữ:{holding_h:.1f}h{dca_info}\n"
        f"    Entry:{trade['entry_price']:.4f} Cur:{current_price:.4f} SL:{trade['sl']:.4f} TP:{trade['tp']:.4f}{tsl_info} "
        f"Vốn:${trade.get('total_invested_usd', 0.0):,.2f}"
    )

def build_daily_summary_text(state: Dict) -> str:
    now_vn_str = datetime.now(VIETNAM_TZ).strftime('%H:%M %d-%m-%Y')
    lines = [f"📊 **BÁO CÁO TỔNG KẾT HÀNG NGÀY** - `{now_vn_str}` 📊", ""]
    lines.extend(build_report_header(state))
    lines.append("\n--- **Chi tiết trong phiên** ---")
    lines.append(f"✨ Lệnh mới mở: {len(state.get('temp_newly_opened_trades', []))}")
    if state.get('temp_newly_opened_trades'): lines.extend([f"    - {msg}" for msg in state['temp_newly_opened_trades']])
    lines.append(f"\n⛔ Lệnh đã đóng: {len(state.get('temp_newly_closed_trades', []))}")
    if state.get('temp_newly_closed_trades'): lines.extend([f"    - {msg}" for msg in state['temp_newly_closed_trades']])
    lines.append("\n--- **Vị thế đang mở** ---")
    active_trades = state.get('active_trades', [])
    lines.append(f"💼 Tổng vị thế đang mở: **{len(active_trades)}**")
    if not active_trades: lines.append("    (Không có vị thế nào)")
    else:
        for trade in active_trades:
            current_data = all_indicators.get(trade["symbol"], {}).get(trade["interval"], {})
            current_price = current_data.get('price', 0)
            lines.append(build_trade_details_for_report(trade, current_price) if current_price > 0 else f"⚠️ {trade['symbol']} - Không có dữ liệu giá.")
    lines.append("\n--- **Tổng kết lịch sử giao dịch** ---")
    trade_history = state.get('trade_history', [])
    if trade_history:
        df_history = pd.DataFrame(trade_history)
        df_history['pnl_usd'] = df_history['pnl_usd'].astype(float)
        total_trades = len(df_history)
        winning_trades = df_history[df_history['pnl_usd'] > 0]
        losing_trades = df_history[df_history['pnl_usd'] < 0]
        breakeven_trades = df_history[df_history['pnl_usd'] == 0]
        win_rate = (len(winning_trades) / total_trades * 100) if total_trades > 0 else 0
        total_pnl_history = df_history['pnl_usd'].sum()
        avg_win_pnl = winning_trades['pnl_usd'].mean() if not winning_trades.empty else 0
        avg_loss_pnl = losing_trades['pnl_usd'].mean() if not losing_trades.empty else 0
        lines.append(f"📊 Tổng lệnh: {total_trades} | ✅ Thắng: {len(winning_trades)} | 🤝 Hòa vốn: {len(breakeven_trades)} | ❌ Thua: {len(losing_trades)}")
        lines.append(f"🏆 Win Rate: **{win_rate:.2f}%** | 💰 Tổng PnL: **${total_pnl_history:,.2f}**")
        lines.append(f"Avg Win: ${avg_win_pnl:,.2f} | Avg Loss: ${avg_loss_pnl:,.2f}")
        def format_closed_trade_line(trade_data):
            entry_time = datetime.fromisoformat(trade_data['entry_time'])
            exit_time = datetime.fromisoformat(trade_data['exit_time'])
            hold_duration_h = (exit_time - entry_time).total_seconds() / 3600
            # Hiển thị các tactic đã sử dụng
            tactics_str = ', '.join(trade_data.get('tactic_used', ['N/A']))
            info_str = f"{trade_data.get('opened_by_tactic','?')} > {tactics_str}"
            time_str = exit_time.astimezone(VIETNAM_TZ).strftime('%H:%M %d-%m')
            symbol_with_interval = f"{trade_data['symbol']}-{trade_data.get('interval', 'N/A')}"
            pnl_info = f"${trade_data.get('pnl_usd', 0):.2f} ({trade_data.get('pnl_percent', 0):+.2f}%)"
            return f"  • **{symbol_with_interval}** | PnL: `{pnl_info}` | Tactics: `{info_str}` | Hold: {hold_duration_h:.1f}h"

        lines.append("\n--- Top 5 lệnh lãi gần nhất ---")
        if not winning_trades.empty:
            for _, trade in winning_trades.nlargest(5, 'pnl_usd').iterrows():
                try: lines.append(format_closed_trade_line(trade))
                except Exception as e: lines.append(f"  • {trade.get('symbol')} - Lỗi báo cáo: {e}")
        else: lines.append("  (Chưa có lệnh lãi)")
        lines.append("\n--- Top 5 lệnh lỗ gần nhất ---")
        if not losing_trades.empty:
            for _, trade in losing_trades.nsmallest(5, 'pnl_usd').iterrows():
                try: lines.append(format_closed_trade_line(trade))
                except Exception as e: lines.append(f"  • {trade.get('symbol')} - Lỗi báo cáo: {e}")
        else:
            lines.append("  (Chưa có lệnh lỗ thực sự)")
    else:
        lines.append("    (Chưa có lịch sử giao dịch)")
    lines.append("\n====================================")
    return "\n".join(lines)

def build_dynamic_alert_text(state: Dict) -> str:
    now_vn_str = datetime.now(VIETNAM_TZ).strftime('%H:%M %d-%m-%Y')
    lines = [f"💡 **CẬP NHẬT ĐỘNG** - `{now_vn_str}` 💡", ""]
    lines.extend(build_report_header(state))
    lines.append("\n--- **Vị thế đang mở** ---")
    active_trades = state.get('active_trades', [])
    lines.append(f"💼 Tổng vị thế đang mở: **{len(active_trades)}**")
    if not active_trades: lines.append("    (Không có vị thế nào)")
    else:
        for trade in active_trades:
            current_data = all_indicators.get(trade["symbol"], {}).get(trade["interval"], {})
            current_price = current_data.get('price', 0)
            lines.append(build_trade_details_for_report(trade, current_price) if current_price > 0 else f"⚠️ {trade['symbol']} - Không có dữ liệu giá.")
    lines.append("\n====================================")
    return "\n".join(lines)

def should_send_dynamic_alert(state: Dict) -> bool:
    if not DYNAMIC_ALERT_CONFIG["ENABLED"]: return False
    now = datetime.now(VIETNAM_TZ)
    last_alert = state.get('last_dynamic_alert', {})
    last_alert_time_iso = last_alert.get('timestamp')
    if not last_alert_time_iso: return bool(state.get('active_trades'))
    last_alert_dt = datetime.fromisoformat(last_alert_time_iso).astimezone(VIETNAM_TZ)
    hours_since = (now - last_alert_dt).total_seconds() / 3600
    if hours_since >= DYNAMIC_ALERT_CONFIG["FORCE_UPDATE_HOURS"]: return True
    if hours_since < DYNAMIC_ALERT_CONFIG["COOLDOWN_HOURS"]: return False
    current_equity = calculate_total_equity(state)
    current_pnl_pct = ((current_equity - INITIAL_CAPITAL) / INITIAL_CAPITAL) * 100 if INITIAL_CAPITAL > 0 else 0
    pnl_change = abs(current_pnl_pct - last_alert.get('total_pnl_percent', 0.0))
    return pnl_change >= DYNAMIC_ALERT_CONFIG["PNL_CHANGE_THRESHOLD_PCT"]

def run_session():
    session_id = datetime.now(VIETNAM_TZ).strftime('%Y%m%d_%H%M%S')
    log_message(f"====== 🚀 BẮT ĐẦU PHIÊN (v2.6.0 - Tướng Kiểm Soát) (ID: {session_id}) 🚀 ======")
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

        fg_path = os.path.join(PROJECT_ROOT, "ricenews", "lognew", "market_context.json")
        market_context = {
            "fear_greed": load_json_file(fg_path, {}).get("fear_greed", 50),
            "btc_d1_adx": all_indicators.get("BTCUSDT", {}).get("1d", {}).get("adx", 20.0)
        }
        find_and_open_new_trades(state, total_equity, market_context)

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
