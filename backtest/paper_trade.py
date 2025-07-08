# -*- coding: utf-8 -*-
"""
paper_trade.py - Quản lý Danh mục & Rủi ro Thông minh
Version: Final Pro Max (edge-case patched)
Date: 2025-07-08

Description:
Phiên bản hoàn thiện cuối cùng, tích hợp tất cả các tinh chỉnh về sự ổn định và logic:
- Xử lý lỗi đọc file JSON hỏng một cách an toàn.
- Ghi nhận đầy đủ pnl_percent vào lịch sử giao dịch.
- Logic "1 lệnh/phiên" được làm rõ, không bỏ lỡ cơ hội.
- Ghi nhận `initial_sl` ngay khi mở lệnh để Trailing Stop luôn chính xác.
- Tăng cường logging và các điều kiện bảo vệ để bot hoạt động bền bỉ.

Changelog (so với bản Final Pro Max trước đó)
------------------------------------------------
1. **Guard khi tải dữ liệu** – tránh AttributeError nếu `get_price_data` trả về `None`.
2. **Trailing SL gap-check** – đóng lệnh ngay nếu giá thấp nhất candle xuyên SL trước khi calc trailing.
3. **Session-ID logging** – mọi log đầu/cuối phiên kèm timestamp ID để grep.
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
load_dotenv()
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
sys.path.append(PROJECT_ROOT)
PAPER_DATA_DIR = os.path.join(BASE_DIR, "paper_data")
os.makedirs(PAPER_DATA_DIR, exist_ok=True)

try:
    from indicator import get_price_data, calculate_indicators
    from trade_advisor import get_advisor_decision, FULL_CONFIG as ADVISOR_BASE_CONFIG
except ImportError:
    sys.exit("Lỗi: Thiếu module 'indicator' hoặc 'trade_advisor'. Hãy chắc chắn chúng ở đúng vị trí.")

# ==============================================================================
# ================= ⚙️ TRUNG TÂM CẤU HÌNH (Final Pro Max (edge-case patched)) ⚙️ =
# ==============================================================================

INITIAL_CAPITAL = 10000.0

GENERAL_CONFIG = {
    "DATA_FETCH_LIMIT": 300,
    "DAILY_SUMMARY_TIMES": ["08:05", "20:05"],
}

DYNAMIC_ALERT_CONFIG = {
    "ENABLED": True,
    "COOLDOWN_HOURS": 4,
    "FORCE_UPDATE_HOURS": 10,
    "PNL_CHANGE_THRESHOLD_PCT": 1.5
}

RISK_RULES_CONFIG = {
    "MAX_ACTIVE_TRADES": 7,
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
    "MAX_TOTAL_EXPOSURE_PCT": 0.60
}

ALERT_CONFIG = {
    "DISCORD_WEBHOOK_URL": os.getenv("DISCORD_PAPER_WEBHOOK"),
    "DISCORD_CHUNK_DELAY_SECONDS": 2, # Giảm nhẹ delay
}

TACTICS_LAB = {
    "AI_Aggressor": {
        "NOTES": "Tin vào AI, tự động gồng lời với Trailing SL",
        "WEIGHTS": {'tech': 0.1, 'context': 0.1, 'ai': 0.8},
        "ENTRY_SCORE": 6.2, "RR": 2.5,
        "USE_ATR_SL": True, "ATR_SL_MULTIPLIER": 3.0,
        "USE_TRAILING_SL": True,
        "TRAIL_ACTIVATION_RR": 1.0,  # Kích hoạt Trailing SL khi giá đạt R:R 1:1
        "TRAIL_DISTANCE_RR": 0.8     # SL mới sẽ cách giá hiện tại 0.8R
    },
    "Balanced_Trader": {"NOTES": "Cân bằng...", "WEIGHTS": {'tech': 0.4, 'context': 0.2, 'ai': 0.4}, "ENTRY_SCORE": 5.8, "RR": 2.2, "USE_ATR_SL": True, "ATR_SL_MULTIPLIER": 2.5},
    "Dip_Hunter": {"NOTES": "Bắt đáy...", "WEIGHTS": {'tech': 0.5, 'context': 0.3, 'ai': 0.2}, "ENTRY_SCORE": 6.5, "RR": 3.0, "USE_ATR_SL": True, "ATR_SL_MULTIPLIER": 2.0},
    "Cautious_Observer": {"NOTES": "Bảo toàn vốn...", "WEIGHTS": {'tech': 0.5, 'context': 0.5, 'ai': 0.0}, "ENTRY_SCORE": 9.9},
    "Market_Mirror": {"NOTES": "Làm baseline...", "WEIGHTS": {'tech': 0.4, 'context': 0.2, 'ai': 0.4}, "ENTRY_SCORE": 5.5, "RR": 1.8, "USE_ATR_SL": True, "ATR_SL_MULTIPLIER": 2.5},
    "Range_Trader": {"NOTES": "Giao dịch kênh giá...", "WEIGHTS": {'tech': 0.8, 'context': 0.2, 'ai': 0.0}, "ENABLE_RANGE_TRADE": True, "RANGE_ENTRY_PROXIMITY": 0.015, "RANGE_ENTRY_MIN_SCORE": 6.0, "RR": 1.8, "SL_BELOW_SUPPORT_PCT": 0.02, "ENTRY_SCORE": 9.9},
    "Breakout_Hunter": {"NOTES": "Săn phá vỡ...", "WEIGHTS": {'tech': 0.7, 'context': 0.1, 'ai': 0.2}, "ENABLE_BREAKOUT_TRADE": True, "ENTRY_SCORE": 6.0, "RR": 2.8, "USE_ATR_SL": True, "ATR_SL_MULTIPLIER": 2.0}
}

SYMBOLS_TO_SCAN = ["ETHUSDT", "AVAXUSDT", "INJUSDT", "LINKUSDT", "SUIUSDT", "FETUSDT", "TAOUSDT"]
INTERVALS_TO_SCAN = ["1h", "4h", "1d"]
ALL_TIME_FRAMES = ["1h", "4h", "1d"]
VIETNAM_TZ = pytz.timezone('Asia/Ho_Chi_Minh')

LOG_FILE = os.path.join(PAPER_DATA_DIR, "paper_trade_log.txt")
STATE_FILE = os.path.join(PAPER_DATA_DIR, "paper_trade_state.json")
TRADE_HISTORY_CSV_FILE = os.path.join(PAPER_DATA_DIR, "trade_history.csv")

all_indicators: Dict[str, Any] = {}

# ==============================================================================
# ================= TIỆN ÍCH & CẢNH BÁO (Final Pro Max (edge-case patched)) =====
# ==============================================================================

def log_message(message: str):
    timestamp = datetime.now(VIETNAM_TZ).strftime('%Y-%m-%d %H:%M:%S')
    log_entry = f"[{timestamp}] {message}"
    print(log_entry)
    with open(LOG_FILE, "a", encoding="utf-8") as f: f.write(log_entry + "\n")

# Tinh chỉnh: Xử lý file JSON hỏng
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

# Tinh chỉnh: Thêm logging
def send_discord_message_chunks(full_content: str):
    webhook_url = ALERT_CONFIG.get("DISCORD_WEBHOOK_URL")
    if not webhook_url: return

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
                log_message(f"✅ Đã gửi chunk {i+1}/{total_chunks} lên Discord...")
                time.sleep(ALERT_CONFIG["DISCORD_CHUNK_DELAY_SECONDS"])
        except requests.exceptions.RequestException as e:
            log_message(f"❌ Lỗi gửi chunk Discord {i+1}/{total_chunks}: {e}")
            break

def get_current_pnl(trade: Dict) -> Tuple[float, float]:
    current_data = all_indicators.get(trade["symbol"], {}).get(trade["interval"])
    if not (current_data and current_data.get('price', 0) > 0 and trade.get('entry_price', 0) > 0):
        return 0.0, 0.0
    pnl_percent = (current_data['price'] - trade['entry_price']) / trade['entry_price']
    return trade.get('invested_usd', 0.0) * pnl_percent, pnl_percent * 100

def export_trade_history_to_csv(closed_trades: List[Dict]):
    if not closed_trades: return
    try:
        df = pd.DataFrame(closed_trades)
        df['entry_time'] = pd.to_datetime(df['entry_time']).dt.tz_convert(VIETNAM_TZ)
        df['exit_time'] = pd.to_datetime(df['exit_time']).dt.tz_convert(VIETNAM_TZ)
        df['holding_duration_hours'] = round((df['exit_time'] - df['entry_time']).dt.total_seconds() / 3600, 2)
        cols = ["trade_id", "symbol", "interval", "status", "opened_by_tactic", "trade_type", "entry_price", "exit_price", "tp", "sl", "invested_usd", "pnl_usd", "pnl_percent", "entry_time", "exit_time", "holding_duration_hours", "entry_score"]
        df = df[[c for c in cols if c in df.columns]]
        df.to_csv(TRADE_HISTORY_CSV_FILE, mode='a' if os.path.exists(TRADE_HISTORY_CSV_FILE) else 'w', header=not os.path.exists(TRADE_HISTORY_CSV_FILE), index=False, encoding="utf-8")
        log_message(f"✅ Đã xuất {len(df)} lệnh đã đóng vào {TRADE_HISTORY_CSV_FILE}")
    except Exception as e:
        log_message(f"❌ Lỗi khi xuất lịch sử giao dịch ra CSV: {e}")

# ----------------------------------------------------------------
# 🎯 PATCH 1 – Guard cho get_price_data()
# ----------------------------------------------------------------
def safe_get_price_data(symbol: str, interval: str, limit: int):
    """Wrapper có guard cho get_price_data trả None."""
    try:
        df = get_price_data(symbol, interval, limit=limit)
        if df is None or getattr(df, "empty", True):
            log_message(f"⚠️ No data {symbol}-{interval}")
            return None
        return df
    except Exception as e:
        log_message(f"❌ Fetch data fail {symbol}-{interval}: {e}")
        return None

# ==============================================================================
# ================== XỬ LÝ DANH MỤC & RỦI RO (Final Pro Max (edge-case patched)) =
# ==============================================================================

def calculate_total_equity(state: Dict) -> float:
    return state.get('cash', INITIAL_CAPITAL) + sum(t.get('invested_usd', 0) + get_current_pnl(t)[0] for t in state.get('active_trades', []))

def determine_dynamic_capital_pct(atr_percent: float) -> float:
    if atr_percent <= 1.5: base = 0.10
    elif atr_percent <= 3: base = 0.07
    elif atr_percent <= 5: base = 0.05
    else: base = 0.03
    return max(0.03, min(base, 0.12))

# Tinh chỉnh: Ghi nhận pnl_percent đầy đủ và Trailing-SL gap-check
def handle_trade_closure(portfolio_state: Dict) -> List[Dict]:
    closed_trades, newly_closed_details = [], []
    now_vn = datetime.now(VIETNAM_TZ)

    for trade in portfolio_state["active_trades"][:]:
        data = all_indicators.get(trade['symbol'], {}).get(trade['interval'], {})
        high_p, low_p, current_p = data.get('high', 0), data.get('low', 0), data.get('price', 0)
        if not all([high_p, low_p, current_p]): continue

        status, exit_p = (None, None)

        # --- GAP THROUGH STOP? – đóng ngay trước trailing ---
        if low_p <= trade['sl']:
            status, exit_p = "SL", trade['sl']
        else:
            # TP1 logic (giữ nguyên)
            if trade.get('stage') == 'initial' and high_p >= trade.get('tp1', 0):
                pnl_tp1 = trade['invested_usd'] * 0.5 * ((trade['tp1'] - trade['entry_price']) / trade['entry_price'])
                portfolio_state['cash'] += (trade['invested_usd'] * 0.5 + pnl_tp1)
                trade.update({'invested_usd': trade['invested_usd'] * 0.5, 'sl': trade['entry_price'], 'stage': 'tp1_hit'})
                log_message(f"🎯 TP1 ĐẠT cho {trade['symbol']}: Chốt 50% (+${pnl_tp1:,.2f}), SL dời về BE.")

            # Trailing SL update logic (giữ nguyên)
            tactic_cfg = TACTICS_LAB.get(trade.get('opened_by_tactic', ''), {})
            if tactic_cfg.get("USE_TRAILING_SL", False) and 'initial_sl' in trade:
                risk_dist = trade['entry_price'] - trade['initial_sl']
                if risk_dist > 0 and current_p > trade['entry_price'] + (risk_dist * tactic_cfg.get("TRAIL_ACTIVATION_RR", 1.0)):
                    new_sl = current_p - (risk_dist * tactic_cfg.get("TRAIL_DISTANCE_RR", 0.8))
                    if new_sl > trade['sl']:
                        log_message(f"📈 Trailing SL Update cho {trade['symbol']}: SL cũ {trade['sl']:.4f} -> SL mới {new_sl:.4f}")
                        trade['sl'] = new_sl
            
            # Sau trailing, đánh giá TP/SL
            if high_p >= trade['tp']:
                status, exit_p = "TP", trade['tp']
            elif low_p <= trade['sl']: # Re-check SL after trailing update
                status, exit_p = "SL", trade['sl']

        if status:
            pnl_ratio = (exit_p - trade['entry_price']) / trade['entry_price']
            pnl_usd = trade['invested_usd'] * pnl_ratio
            
            portfolio_state['cash'] += (trade['invested_usd'] + pnl_usd)
            
            final_status = f'Closed ({status})' + (' after TP1' if trade.get('stage') == 'tp1_hit' else '')
            trade.update({'status': final_status, 'exit_price': exit_p, 'exit_time': now_vn.isoformat(), 'pnl_usd': pnl_usd, 'pnl_percent': pnl_ratio * 100})
            
            portfolio_state['active_trades'].remove(trade)
            portfolio_state['trade_history'].append(trade)
            closed_trades.append(trade)
            icon = '✅' if status == 'TP' else '❌'
            log_message(f"{icon} {final_status}: {trade['symbol']} | PnL phần còn lại: ${pnl_usd:,.2f}")
            newly_closed_details.append(f"{icon} {trade['symbol']} ({status}): PnL ${pnl_usd:,.2f}")

    portfolio_state['temp_newly_closed_trades'] = newly_closed_details
    return closed_trades

def handle_stale_trades(portfolio_state: Dict) -> List[Dict]:
    closed_trades, now_aware = [], datetime.now(VIETNAM_TZ)
    for trade in portfolio_state.get("active_trades", [])[:]:
        rules = RISK_RULES_CONFIG["STALE_TRADE_RULES"].get(trade.get("interval"))
        if not rules: continue

        entry_time = datetime.fromisoformat(trade['entry_time'])
        if (now_aware - entry_time).total_seconds() / 3600 > rules["HOURS"]:
            entry, tp, sl = trade['entry_price'], trade.get('tp', 0), trade.get('sl', 0)
            current_p = all_indicators.get(trade['symbol'], {}).get(trade['interval'], {}).get('price', entry)
            if sl == 0 or tp == 0: continue
            
            progress = (current_p - entry) / (tp - entry) if (tp - entry) != 0 else 0
            risk_buffer_pct = (current_p - sl) / (entry - sl) if (entry - sl) != 0 else 1
            if progress < rules["PROGRESS_THRESHOLD"] or risk_buffer_pct < rules["MIN_RISK_BUFFER_PCT"]:
                pnl_pct = (current_p - entry) / entry
                pnl_usd = trade['invested_usd'] * pnl_pct
                portfolio_state['cash'] += (trade['invested_usd'] + pnl_usd)
                trade.update({'status': 'Closed (Stale)', 'exit_price': current_p, 'exit_time': now_aware.isoformat(), 'pnl_usd': pnl_usd, 'pnl_percent': pnl_pct * 100}) # Add pnl_percent
                portfolio_state['active_trades'].remove(trade)
                portfolio_state['trade_history'].append(trade)
                closed_trades.append(trade)
                log_message(f"⌛ Lệnh {trade['symbol']} không tiến triển. Đã đóng với PnL ${pnl_usd:,.2f}")
                portfolio_state.setdefault('temp_newly_closed_trades', []).append(f"⌛ {trade['symbol']} (Stale): PnL ${pnl_usd:,.2f}")
    return closed_trades

# ==============================================================================
# ================== CHỌN TACTIC & MỞ LỆNH (Final Pro Max (edge-case patched)) =
# ==============================================================================

def select_best_tactic_for_symbol(market_context: Dict) -> str:
    scores = {t: 0 for t in TACTICS_LAB}
    fg, adx = market_context.get("fear_greed", 50), market_context.get("btc_d1_adx", 20.0)
    if adx < 20: scores.update({'Range_Trader': 5, 'Cautious_Observer': 3, 'AI_Aggressor': -2})
    elif adx > 28: scores.update({'AI_Aggressor': 4, 'Breakout_Hunter': 3, 'Balanced_Trader': 2, 'Range_Trader': -5})
    if fg < 25: scores['Dip_Hunter'] += 5
    elif fg > 75: scores.update({'AI_Aggressor': 2, 'Breakout_Hunter': 2})
    scores['Balanced_Trader'] += 1
    return max(scores, key=scores.get)

# Tinh chỉnh: Logic "1 lệnh/phiên" và `initial_sl`
def find_and_open_new_trades(state: Dict, equity: float, context: Dict):
    active_trades = state.get('active_trades', [])
    if len(active_trades) >= RISK_RULES_CONFIG["MAX_ACTIVE_TRADES"]: return
    if sum(t['invested_usd'] for t in active_trades) / equity >= CAPITAL_MANAGEMENT_CONFIG["MAX_TOTAL_EXPOSURE_PCT"]: return

    trade_opened_this_session = False
    for symbol in SYMBOLS_TO_SCAN:
        if any(t['symbol'] == symbol for t in active_trades): continue
        
        tactic_name = select_best_tactic_for_symbol(context)
        tactic_cfg = TACTICS_LAB[tactic_name]
        
        for interval in INTERVALS_TO_SCAN:
            indicators = all_indicators.get(symbol, {}).get(interval)
            if not (indicators and indicators.get('price', 0) > 0): continue
            
            decision = get_advisor_decision(symbol, interval, indicators, ADVISOR_BASE_CONFIG, weights_override=tactic_cfg.get("WEIGHTS"))
            score, entry_p = decision.get("final_score", 0.0), indicators['price']
            trade_type = None

            if tactic_cfg.get("ENABLE_BREAKOUT_TRADE") and indicators.get("breakout_signal") == 'bullish' and score >= tactic_cfg.get("ENTRY_SCORE", 9.9):
                trade_type = "BREAKOUT_BUY"
            elif tactic_cfg.get("ENABLE_RANGE_TRADE") and indicators.get("support_level", 0) > 0 and abs(entry_p - indicators["support_level"]) / indicators["support_level"] < tactic_cfg.get("RANGE_ENTRY_PROXIMITY", 0.015) and score >= tactic_cfg.get("RANGE_ENTRY_MIN_SCORE", 6.0):
                trade_type = "RANGE_BUY"
            elif score >= tactic_cfg.get("ENTRY_SCORE", 9.9) and not any([tactic_cfg.get("ENABLE_BREAKOUT_TRADE"), tactic_cfg.get("ENABLE_RANGE_TRADE")]):
                trade_type = "TREND_FOLLOW"
            
            if trade_type:
                risk_tier = CAPITAL_MANAGEMENT_CONFIG["TACTIC_TO_TIER_MAP"].get(tactic_name, "HIGH_RISK")
                capital_pct = determine_dynamic_capital_pct(indicators.get('atr_percent', 3.0)) * {'LOW_RISK':1.2, 'MEDIUM_RISK':1.0, 'HIGH_RISK':0.8}.get(risk_tier, 1.0)
                invested = equity * min(0.12, max(0.03, capital_pct))
                if invested > state['cash'] or invested < 10: continue

                risk_dist = (indicators.get('atr', 0) * tactic_cfg.get("ATR_SL_MULTIPLIER", 2.0)) if tactic_cfg.get("USE_ATR_SL") and indicators.get('atr', 0) > 0 else entry_p * 0.05
                sl_p, tp1_p, tp2_p = entry_p - risk_dist, entry_p + risk_dist, entry_p + (risk_dist * tactic_cfg.get("RR", 2.0))
                if tp2_p <= entry_p or sl_p <= 0: continue

                new_trade = {
                    "trade_id": str(uuid.uuid4()),"symbol": symbol,"interval": interval,
                    "status": "ACTIVE", "stage": "initial", "opened_by_tactic": tactic_name,
                    "trade_type": trade_type,"entry_price": entry_p,
                    "tp1": round(tp1_p, 8), "tp": round(tp2_p, 8),
                    "sl": round(sl_p, 8), "initial_sl": round(sl_p, 8), # Ghi nhận initial_sl ngay lập tức
                    "invested_usd": invested, "entry_time": datetime.now(VIETNAM_TZ).isoformat(), "entry_score": score
                }
                state["cash"] -= invested
                active_trades.append(new_trade)
                log_message(f"🔥 Lệnh Mới ({tactic_name}/{trade_type}): {symbol} | Vốn: ${invested:,.2f} | SL: {sl_p:.4f} | TP1: {tp1_p:.4f} | TP2: {tp2_p:.4f}")
                state.setdefault('temp_newly_opened_trades', []).append(f"🔥 {symbol} ({tactic_name}): Vốn ${invested:,.2f}")
                
                trade_opened_this_session = True
                break # Thoát khỏi vòng lặp interval
        
        if trade_opened_this_session:
            break # Thoát khỏi vòng lặp symbol

# ==============================================================================
# ==================== BÁO CÁO & CẬP NHẬT (Final Pro Max (edge-case patched)) ==
# ==============================================================================
def build_report_header(state: Dict) -> List[str]:
    equity = calculate_total_equity(state)
    pnl_usd, pnl_pct = equity - INITIAL_CAPITAL, (equity / INITIAL_CAPITAL - 1) * 100
    icon = "🚀" if pnl_pct > 5 else "💥" if pnl_pct < -5 else "🧠"
    history = state.get('trade_history', [])
    wins = sum(1 for t in history if t.get('pnl_usd', 0) > 0)
    losses = sum(1 for t in history if t.get('pnl_usd', 0) < 0)
    winrate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0.0
    return [
        f"{icon} Tổng tài sản: ${equity:,.2f} ({pnl_pct:+.2f}%)",
        f"💰 Tiền mặt: ${state.get('cash', 0):,.2f}",
        f"📈 Tỉ lệ thắng: {winrate:.2f}% ({wins}W/{losses}L)",
    ]

def build_daily_summary_text(state: Dict) -> str:
    now_vn_str = datetime.now(VIETNAM_TZ).strftime('%H:%M %d-%m-%Y')
    lines = [f"📊 BÁO CÁO HÀNG NGÀY - {now_vn_str}", "===================================="]
    lines.extend(build_report_header(state))
    lines.append("------------------------------------")
    
    active_trades = state.get('active_trades', [])
    lines.append(f"💼 Vị thế đang mở ({len(active_trades)}):")
    if not active_trades: lines.append("    (Không có vị thế nào)")
    else:
        for trade in active_trades:
            pnl_usd, pnl_pct = get_current_pnl(trade)
            icon = "🟢" if pnl_usd >= 0 else "🔴"
            holding_h = (datetime.now(VIETNAM_TZ) - datetime.fromisoformat(trade['entry_time'])).total_seconds() / 3600
            stage_info = f" ({trade.get('stage')})" if trade.get('stage') != 'initial' else ""
            lines.append(f"    {icon} {trade['symbol']} | PnL: ${pnl_usd:,.2f} ({pnl_pct:+.2f}%) | Giữ: {holding_h:.1f}h{stage_info}")
    lines.append("====================================")
    return "\n".join(lines)

def build_dynamic_alert_text(state: Dict) -> str:
    now_vn_str = datetime.now(VIETNAM_TZ).strftime('%H:%M %d-%m-%Y')
    lines = [f"💡 CẬP NHẬT ĐỘNG - {now_vn_str}", "===================================="]
    lines.extend(build_report_header(state))
    lines.append("------------------------------------")
    
    opened = state.get('temp_newly_opened_trades', [])
    closed = state.get('temp_newly_closed_trades', [])
    if opened or closed:
        lines.append("🔔 Hoạt động gần đây:")
        lines.extend([f"    {item}" for item in opened + closed])
        lines.append("------------------------------------")

    active_trades = state.get('active_trades', [])
    lines.append(f"💼 Vị thế đang mở ({len(active_trades)}):")
    if not active_trades: lines.append("    (Không có vị thế nào)")
    else:
        for trade in active_trades:
            pnl_usd, pnl_pct = get_current_pnl(trade)
            lines.append(f"    {'🟢' if pnl_usd >= 0 else '🔴'} {trade['symbol']}: ${pnl_usd:,.2f} ({pnl_pct:+.2f}%)")
    lines.append("====================================")
    return "\n".join(lines)

# ==============================================================================
# ======================== PHIÊN GIAO DỊCH CHÍNH (Final Pro Max (edge-case patched)) =
# ==============================================================================

def run_session():
    session_id = datetime.now(VIETNAM_TZ).strftime('%Y%m%d_%H%M%S')
    log_message(f"====== 🚀 BẮT ĐẦU PHIÊN (Session {session_id}) 🚀 ======")
    try:
        state = load_json_file(STATE_FILE, {"cash": INITIAL_CAPITAL, "active_trades": [], "trade_history": [], "last_dynamic_alert": {}})

        all_indicators.clear()
        for symbol in list(set(SYMBOLS_TO_SCAN + ["BTCUSDT"])):
            all_indicators[symbol] = {}
            for interval in ALL_TIME_FRAMES:
                # Dùng safe_get_price_data để tránh lỗi khi dữ liệu trống
                df = safe_get_price_data(symbol, interval, GENERAL_CONFIG["DATA_FETCH_LIMIT"])
                if df is None:
                    continue # Bỏ qua khung thời gian này nếu không có dữ liệu hợp lệ
                all_indicators[symbol][interval] = calculate_indicators(df, symbol, interval)

        closed_tp_sl = handle_trade_closure(state)
        closed_stale = handle_stale_trades(state)
        if closed_tp_sl or closed_stale:
            export_trade_history_to_csv(closed_tp_sl + closed_stale)

        total_equity = calculate_total_equity(state)
        btc_d1_adx = all_indicators.get("BTCUSDT", {}).get("1d", {}).get("adx", 20.0)
        fg_path = os.path.join(PROJECT_ROOT, "ricenews", "lognew", "market_context.json")
        fear_greed = load_json_file(fg_path, {}).get("fear_greed")
        market_context = {"fear_greed": fear_greed, "btc_d1_adx": btc_d1_adx}
        find_and_open_new_trades(state, total_equity, market_context)

        now_vn = datetime.now(VIETNAM_TZ)
        for time_str in GENERAL_CONFIG["DAILY_SUMMARY_TIMES"]:
            h, m = map(int, time_str.split(':'))
            key = f"summary_{h:02d}_{now_vn.strftime('%Y-%m-%d')}"
            if (now_vn.hour > h or (now_vn.hour == h and now_vn.minute >= m)) and state.get('last_sent_summary_key') != key:
                log_message(f"Trigger Daily Summary cho mốc {time_str}...")
                send_discord_message_chunks(build_daily_summary_text(state))
                state['last_sent_summary_key'] = key
                break
            
        # Tinh chỉnh: Guard chống chia cho 0 và cải thiện điều kiện gửi alert
        if DYNAMIC_ALERT_CONFIG["ENABLED"]:
            last_alert = state.get("last_dynamic_alert", {})
            last_ts_str = last_alert.get("timestamp")
            last_equity = last_alert.get("equity", 0) # Lấy last_equity, mặc định 0
            should_send, reason = False, ""

            if state.get('temp_newly_opened_trades') or state.get('temp_newly_closed_trades'):
                should_send, reason = True, "Hoạt động mới"
            elif not last_ts_str:
                should_send, reason = True, "Gửi lần đầu"
            else:
                hours_passed = (now_vn - datetime.fromisoformat(last_ts_str)).total_seconds() / 3600
                if hours_passed >= DYNAMIC_ALERT_CONFIG["FORCE_UPDATE_HOURS"]:
                    should_send, reason = True, "Force-send"
                elif hours_passed >= DYNAMIC_ALERT_CONFIG["COOLDOWN_HOURS"]:
                    if last_equity > 1: # Điều kiện bảo vệ chống chia cho 0
                        equity_change_pct = abs(1 - total_equity / last_equity) * 100
                        if equity_change_pct >= DYNAMIC_ALERT_CONFIG["PNL_CHANGE_THRESHOLD_PCT"]:
                            should_send, reason = True, f"Thay đổi PnL > {DYNAMIC_ALERT_CONFIG['PNL_CHANGE_THRESHOLD_PCT']}%"
            
            if should_send:
                log_message(f"Trigger Dynamic Alert: {reason}")
                send_discord_message_chunks(build_dynamic_alert_text(state))
                state["last_dynamic_alert"] = {"timestamp": now_vn.isoformat(), "equity": total_equity}
                state.pop('temp_newly_opened_trades', None)
                state.pop('temp_newly_closed_trades', None)
            
        log_message(f"💰 Tiền Mặt: ${state['cash']:,.2f} | Tổng Tài Sản: ${calculate_total_equity(state):,.2f} | Lệnh Mở: {len(state['active_trades'])}")
        save_json_file(STATE_FILE, state)

    except Exception:
        error_details = traceback.format_exc()
        log_message(f"!!!!!! ❌ LỖI NGHIÊM TRỌNG TRONG PHIÊN LÀM VIỆC ❌ !!!!!!\n{error_details}")
        send_discord_message_chunks(f"🔥🔥🔥 BOT GẶP LỖI NGHIÊM TRỌNG 🔥🔥🔥\n`{error_details}`")

    log_message(f"====== ✅ KẾT THÚC PHIÊN (Session {session_id}) ✅ ======\n")

if __name__ == "__main__":
    run_session()
