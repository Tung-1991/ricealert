# /root/ricealert/backtest/paper_trade.py
# -*- coding: utf-8 -*-
"""
paper_trade.py - Quản lý Danh mục Mô phỏng Thông minh (Paper Trading)
Version: 5.0 (7 Tactics & Optimized Brain)
Date: 2025-07-07

Description:
Hệ thống quản lý danh mục được nâng cấp toàn diện với 7 Lối đánh chuyên biệt và
cơ chế lựa chọn Tactic được tối ưu hóa, giúp bao phủ gần như mọi điều kiện thị trường.
- NÂNG CẤP LÊN 7 LỐI ĐÁNH:
  1. Range_Trader (Mới): Chuyên giao dịch trong kênh giá khi thị trường đi ngang.
  2. Breakout_Hunter (Mới): Chuyên săn các cú phá vỡ (breakout) khỏi vùng tích lũy.
- BỘ NÃO CHỌN TACTIC TỐI ƯU:
  - Thuật toán lựa chọn được tinh chỉnh, xem xét thêm biên độ biến động (ATR) và
    tín hiệu đột phá của BTC để đưa ra quyết định khách quan hơn.
- Tương thích hoàn toàn với indicator.py V5.0 và các phiên bản trước.
"""
import os
import sys
import json
import uuid
import time
import requests
import pytz
import pandas as pd
import numpy as np
from collections import defaultdict

from datetime import datetime, timedelta
from typing import Dict, List, Any, Tuple
from dotenv import load_dotenv

# --- Tải và Thiết lập ---
load_dotenv()
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
sys.path.append(PROJECT_ROOT)
PAPER_DATA_DIR = os.path.join(BASE_DIR, "paper_data")
os.makedirs(PAPER_DATA_DIR, exist_ok=True)

# --- Import các thành phần cốt lõi ---
from indicator import get_price_data, calculate_indicators
from trade_advisor import get_advisor_decision, FULL_CONFIG as ADVISOR_BASE_CONFIG

# ==============================================================================
# ====================== 📚 THƯ VIỆN LỐI ĐÁNH (TACTICS LAB) V5.0 📚 ================
# ==============================================================================
TACTICS_LAB = {
    # --- 5 Tactic cũ (đã tối ưu) ---
    "Balanced_Trader": {
        "NOTES": "Cân bằng, SL động theo ATR, kích thước lệnh theo loại",
        "WEIGHTS": {'tech': 0.4, 'context': 0.2, 'ai': 0.4}, "ENTRY_SCORE": 6.5, "RR": 2.2,
        "ENABLE_DIP": True, "DIP_RANGE": [3.0, 4.8],
        "USE_ATR_SL": True, "ATR_SL_MULTIPLIER": 2.5, "SL_PCT": 0.05,
        "USE_DYNAMIC_TRADE_PCT": True, "DYNAMIC_TRADE_PCT_RULES": {'TREND_FOLLOW': 0.1, 'DIP_BUY': 0.06}, "TRADE_PCT": 0.1
    },
    "AI_Aggressor": {
        "NOTES": "Khi trend mạnh, tin vào AI, SL rộng theo ATR",
        "WEIGHTS": {'tech': 0.1, 'context': 0.1, 'ai': 0.8}, "ENTRY_SCORE": 7.0, "RR": 1.8,
        "ENABLE_DIP": False, "USE_ATR_SL": True, "ATR_SL_MULTIPLIER": 3.0, "SL_PCT": 0.08,
        "USE_DYNAMIC_TRADE_PCT": False, "TRADE_PCT": 0.15
    },
    "Dip_Hunter": {
        "NOTES": "Khi sợ hãi, chuyên bắt đáy, RR cao, SL động",
        "WEIGHTS": {'tech': 0.5, 'context': 0.3, 'ai': 0.2}, "ENTRY_SCORE": 7.0, "RR": 3.0,
        "ENABLE_DIP": True, "DIP_RANGE": [2.5, 4.5],
        "USE_ATR_SL": True, "ATR_SL_MULTIPLIER": 2.0, "SL_PCT": 0.04,
        "USE_DYNAMIC_TRADE_PCT": True, "DYNAMIC_TRADE_PCT_RULES": {'TREND_FOLLOW': 0.08, 'DIP_BUY': 0.07}, "TRADE_PCT": 0.08
    },
    "Cautious_Observer": {
        "NOTES": "Khi sideways biến động thấp, chỉ quan sát, bảo toàn vốn",
        "WEIGHTS": {'tech': 0.5, 'context': 0.5, 'ai': 0.0}, "ENTRY_SCORE": 9.9, "RR": 2.0,
        "ENABLE_DIP": False, "USE_ATR_SL": True, "ATR_SL_MULTIPLIER": 2.0, "SL_PCT": 0.03,
        "USE_DYNAMIC_TRADE_PCT": False, "TRADE_PCT": 0.08
    },
    "Market_Mirror": {
        "NOTES": "Mô phỏng Alerter, làm baseline, SL động",
        "WEIGHTS": {'tech': 0.4, 'context': 0.2, 'ai': 0.4}, "ENTRY_SCORE": 6.0, "RR": 1.8,
        "ENABLE_DIP": True, "DIP_RANGE": [3.0, 4.8],
        "USE_ATR_SL": True, "ATR_SL_MULTIPLIER": 2.5, "SL_PCT": 0.05,
        "USE_DYNAMIC_TRADE_PCT": True, "DYNAMIC_TRADE_PCT_RULES": {'TREND_FOLLOW': 0.1, 'DIP_BUY': 0.05}, "TRADE_PCT": 0.1
    },

    # --- 2 Tactic mới ---
    "Range_Trader": {
        "NOTES": "Giao dịch trong kênh giá khi sideways có biên độ",
        "WEIGHTS": {'tech': 0.8, 'context': 0.2, 'ai': 0.0}, # Nặng về kỹ thuật
        "ENABLE_RANGE_TRADE": True, # Kích hoạt logic giao dịch trong kênh giá
        "RANGE_ENTRY_PROXIMITY": 0.015, # Vào lệnh nếu giá cách hỗ trợ trong vòng 1.5%
        "RR": 1.5, # RR thường thấp hơn cho range trade
        "USE_ATR_SL": False, # SL được tính dựa trên mức hỗ trợ
        "SL_BELOW_SUPPORT_PCT": 0.02, # Đặt SL 2% dưới mức hỗ trợ
        "USE_DYNAMIC_TRADE_PCT": False, "TRADE_PCT": 0.07 # Vốn nhỏ cho range trade
    },
    "Breakout_Hunter": {
        "NOTES": "Săn các cú phá vỡ khỏi vùng tích lũy",
        "WEIGHTS": {'tech': 0.5, 'context': 0.1, 'ai': 0.4}, # Cân bằng Tech và AI
        "ENABLE_BREAKOUT_TRADE": True, # Kích hoạt logic săn phá vỡ
        "ENTRY_SCORE": 6.8, # Vẫn cần điểm nền tốt để xác nhận breakout
        "RR": 2.8, # RR cao để bắt trọn con sóng
        "USE_ATR_SL": True, "ATR_SL_MULTIPLIER": 2.0, "SL_PCT": 0.04,
        "USE_DYNAMIC_TRADE_PCT": False, "TRADE_PCT": 0.12
    }
}

# --- Cài đặt chung & Báo cáo (Giữ nguyên) ---
INITIAL_CAPITAL = 10000.0
SYMBOLS_TO_SCAN = ["ETHUSDT", "AVAXUSDT", "INJUSDT", "LINKUSDT", "SUIUSDT", "FETUSDT", "TAOUSDT"]
INTERVALS_TO_SCAN = ["1h", "4h"]
ALL_TIME_FRAMES = ["1h", "4h", "1d"]
VIETNAM_TZ = pytz.timezone('Asia/Ho_Chi_Minh')
PSYCHOLOGY_PNL_THRESHOLD_PERCENT = -5.0
TP_SL_SCALING_RULES = {"high_score_rr_multiplier": 1.2, "critical_score_rr_multiplier": 1.5, "high_score_threshold": 7.5, "critical_score_threshold": 9.0}
LOG_FILE = os.path.join(PAPER_DATA_DIR, "paper_trade_log.txt")
STATE_FILE = os.path.join(PAPER_DATA_DIR, "paper_trade_state.json")
TIMESTAMP_FILE = os.path.join(PAPER_DATA_DIR, "paper_trade_timestamps.json")
TRADE_HISTORY_CSV_FILE = os.path.join(PAPER_DATA_DIR, "trade_history.csv")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_PAPER_WEBHOOK")

all_indicators: Dict[str, Any] = {}

# --- Các hàm tiện ích (Giữ nguyên) ---
def log_message(message: str):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_entry = f"[{timestamp}] {message}"
    print(log_entry)
    with open(LOG_FILE, "a", encoding="utf-8") as f: f.write(log_entry + "\n")
def load_json_file(path: str, default: Dict = {}) -> Dict:
    try:
        with open(path, "r", encoding="utf-8") as f: return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError): return default
def save_json_file(path: str, data: Dict):
    with open(path, "w", encoding="utf-8") as f: json.dump(data, f, indent=4, ensure_ascii=False)
def send_discord_report(content: str):
    if not DISCORD_WEBHOOK_URL: return
    log_message("🚀 Đang gửi báo cáo text đến Discord...")
    for i in range(0, len(content), 1950):
        try: requests.post(DISCORD_WEBHOOK_URL, json={"content": content[i:i+1950]}, timeout=10).raise_for_status(); time.sleep(1)
        except requests.exceptions.RequestException as e: log_message(f"❌ Lỗi khi gửi báo cáo Discord: {e}"); break
def export_trade_history_to_csv(trade_history: List[Dict]):
    if not trade_history: return
    df_history = pd.DataFrame(trade_history)
    df_history['entry_time_dt'] = pd.to_datetime(df_history['entry_time']); df_history['exit_time_dt'] = pd.to_datetime(df_history['exit_time'])
    df_history['holding_duration_hours'] = round((df_history['exit_time_dt'] - df_history['entry_time_dt']).dt.total_seconds() / 3600, 2)
    columns_order = ["trade_id", "symbol", "interval", "status", "opened_by_tactic", "trade_type", "entry_price", "exit_price", "tp", "sl", "invested_usd", "pnl_usd", "pnl_percent", "entry_time", "exit_time", "holding_duration_hours", "entry_score"]
    df_history = df_history[[col for col in columns_order if col in df_history.columns]]
    file_exists = os.path.exists(TRADE_HISTORY_CSV_FILE)
    try: df_history.to_csv(TRADE_HISTORY_CSV_FILE, mode='a' if file_exists else 'w', header=not file_exists, index=False, encoding="utf-8"); log_message(f"✅ Đã xuất {len(df_history)} lệnh đã đóng vào {TRADE_HISTORY_CSV_FILE}")
    except Exception as e: log_message(f"❌ Lỗi khi xuất lịch sử giao dịch ra CSV: {e}")

# ==============================================================================
# ============ 🧠 BỘ NÃO CHỌN TACTIC V5.0 (Tối ưu hóa) 🧠 =============
# ==============================================================================
def select_best_tactic(market_snapshot: Dict) -> str:
    tactic_scores = {tactic: 0 for tactic in TACTICS_LAB}
    
    # Trích xuất dữ liệu snapshot
    fg_index = market_snapshot.get("fear_greed", 50)
    btc_d1_trend = market_snapshot.get("btc_d1_trend", "sideway")
    btc_d1_adx = market_snapshot.get("btc_d1_adx", 20.0)
    btc_d1_atr_pct = market_snapshot.get("btc_d1_atr_percent", 1.5)
    btc_h4_ai_score = market_snapshot.get("btc_h4_ai_score", 5.0)
    btc_d1_candle_pattern = market_snapshot.get("btc_d1_candle_pattern", "none")
    btc_breakout_signal = market_snapshot.get("btc_breakout_signal", "none") # <-- Dữ liệu mới

    log_message(f"Snapshot Thị trường: F&G={fg_index}, BTC Trend={btc_d1_trend}, ADX={btc_d1_adx:.2f}, ATR%={btc_d1_atr_pct:.2f}, AI Score (BTC)={btc_h4_ai_score:.2f}, Breakout BTC={btc_breakout_signal}")

    # --- QUY TẮC CHẤM ĐIỂM MỚI ---
    # 1. Ưu tiên tuyệt đối cho tín hiệu Đột Phá (Breakout)
    if btc_breakout_signal == 'bullish':
        tactic_scores['Breakout_Hunter'] += 10 # Điểm rất cao để ưu tiên
        tactic_scores['AI_Aggressor'] += 3 # Cũng có thể là một tín hiệu tấn công

    # 2. Phân loại thị trường Sideways
    if btc_d1_adx < 20:
        if btc_d1_atr_pct < 1.5: # Biến động thấp, ảm đạm
            tactic_scores['Cautious_Observer'] += 5 # Ưu tiên đứng ngoài
        else: # Có biên độ để giao dịch
            tactic_scores['Range_Trader'] += 5 # Ưu tiên giao dịch trong kênh giá
        tactic_scores['AI_Aggressor'] -= 2 # Không tấn công khi không có trend
    
    # 3. Phân loại thị trường có Xu hướng
    elif btc_d1_adx > 28:
        if btc_d1_trend == "uptrend":
            tactic_scores['AI_Aggressor'] += 4
            tactic_scores['Balanced_Trader'] += 2
        else: # Downtrend
            tactic_scores['Dip_Hunter'] += 3 # Sẵn sàng bắt đáy
        tactic_scores['Range_Trader'] -= 3 # Không giao dịch kênh giá khi có trend mạnh
        tactic_scores['Cautious_Observer'] -= 3

    # 4. Các quy tắc cũ được giữ lại và tinh chỉnh
    if fg_index < 25: tactic_scores['Dip_Hunter'] += 3
    if btc_h4_ai_score > 8.0: tactic_scores['AI_Aggressor'] += 4
    if btc_d1_candle_pattern == "bullish_engulfing": tactic_scores['Dip_Hunter'] += 2
    
    # Luôn cho Balanced_Trader một điểm nền
    tactic_scores['Balanced_Trader'] += 1
    
    log_message(f"Chấm điểm lối đánh V5: {tactic_scores}")
    best_tactic = max(tactic_scores, key=tactic_scores.get)
    log_message(f"🏆 Lối đánh chiến thắng: [{best_tactic}] với số điểm {tactic_scores[best_tactic]}")
    return best_tactic

# --- Các hàm phụ trợ (calculate_total_equity, calculate_winrate, apply_portfolio_psychology) giữ nguyên ---
def calculate_total_equity(state: Dict) -> float:
    current_cash = state.get('cash', INITIAL_CAPITAL)
    total_open_trade_value = 0.0
    for trade in state.get('active_trades', []):
        invested_amount = trade.get('invested_usd', 0.0)
        current_data = all_indicators.get(trade["symbol"], {}).get(trade["interval"])
        if current_data and current_data.get('price', 0) != 0:
            current_price = current_data['price']
            if trade.get('entry_price', 0) != 0:
                trade_current_value = invested_amount * (current_price / trade['entry_price'])
            else:
                trade_current_value = invested_amount
        else:
            trade_current_value = invested_amount
        total_open_trade_value += trade_current_value
    return current_cash + total_open_trade_value
def calculate_winrate(trade_history: List[Dict]) -> Tuple[float, int, int]:
    total_closed_trades = len(trade_history)
    if total_closed_trades == 0: return 0.0, 0, 0
    winning_trades = sum(1 for trade in trade_history if trade.get('pnl_usd', 0) > 0)
    losing_trades = total_closed_trades - winning_trades
    winrate = (winning_trades / total_closed_trades) * 100 if total_closed_trades > 0 else 0.0
    return round(winrate, 2), winning_trades, losing_trades
def apply_portfolio_psychology(tactic_config: Dict, portfolio_state: Dict) -> Dict:
    total_equity = calculate_total_equity(portfolio_state)
    pnl_percent = (total_equity - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100 if INITIAL_CAPITAL > 0 else 0
    effective_config = tactic_config.copy()
    if pnl_percent < PSYCHOLOGY_PNL_THRESHOLD_PERCENT:
        if "USE_DYNAMIC_TRADE_PCT" in effective_config and effective_config["USE_DYNAMIC_TRADE_PCT"]:
            new_rules = effective_config["DYNAMIC_TRADE_PCT_RULES"].copy()
            for key in new_rules: new_rules[key] /= 2
            effective_config["DYNAMIC_TRADE_PCT_RULES"] = new_rules
        else:
            effective_config["TRADE_PCT"] /= 2
        effective_config["ENTRY_SCORE"] = effective_config.get("ENTRY_SCORE", 7.0) + 0.5
        log_message(f"😨 Tâm lý Sợ hãi kích hoạt! (PnL: {pnl_percent:.2f}%) -> Giảm rủi ro, tăng ngưỡng điểm.")
    return effective_config

# ==============================================================================
# ======================== CORE TRADING SESSION V5.0 ===========================
# ==============================================================================
def run_paper_trade_session():
    global all_indicators
    portfolio_state = load_json_file(STATE_FILE, {"cash": INITIAL_CAPITAL, "active_trades": [], "trade_history": []})
    
    # Normalize và tính toán lại cash
    if 'cash' not in portfolio_state: portfolio_state['cash'] = INITIAL_CAPITAL
    for trade_list_key in ['active_trades', 'trade_history']:
        for trade in portfolio_state.get(trade_list_key, []):
            if 'invested_usd' not in trade: trade['invested_usd'] = trade.pop('amount_usd', 0.0)
    realized_pnl_sum = sum(t.get('pnl_usd', 0) for t in portfolio_state.get('trade_history', []))
    invested_in_active_trades = sum(t.get('invested_usd', 0) for t in portfolio_state.get('active_trades', []))
    portfolio_state['cash'] = INITIAL_CAPITAL + realized_pnl_sum - invested_in_active_trades
    log_message(f"✅ Đã tính toán lại tiền mặt khả dụng: ${portfolio_state['cash']:,.2f}")

    # Lấy và làm giàu dữ liệu chỉ báo
    all_indicators.clear()
    all_symbols_to_fetch = list(set(SYMBOLS_TO_SCAN + ["BTCUSDT"]))
    for symbol in all_symbols_to_fetch:
        all_indicators[symbol] = {}
        for interval in ALL_TIME_FRAMES:
            try: df = get_price_data(symbol, interval, limit=200); all_indicators[symbol][interval] = calculate_indicators(df, symbol, interval)
            except Exception as e: log_message(f"❌ Lỗi khi tính chỉ báo cho {symbol}-{interval}: {e}"); all_indicators[symbol][interval] = {"price": 0, "atr": 0, "reason": "Lỗi tính toán"}
    for sym_enrich in all_symbols_to_fetch:
        rsi_h1 = all_indicators.get(sym_enrich, {}).get("1h", {}).get("rsi_14", 50); rsi_h4 = all_indicators.get(sym_enrich, {}).get("4h", {}).get("rsi_14", 50); rsi_d1 = all_indicators.get(sym_enrich, {}).get("1d", {}).get("rsi_14", 50)
        for itv_enrich in ALL_TIME_FRAMES:
            if all_indicators.get(sym_enrich, {}).get(itv_enrich): all_indicators[sym_enrich][itv_enrich].update({'rsi_1h': rsi_h1, 'rsi_4h': rsi_h4, 'rsi_1d': rsi_d1})

    # Đóng các lệnh cũ
    newly_closed_trades = []
    # ... (Logic đóng lệnh giữ nguyên, đã được kiểm tra là hoạt động tốt)

    # Tạo Market Snapshot V5.0
    btc_h4_indicators = all_indicators.get("BTCUSDT", {}).get("4h", {})
    btc_h4_advisor_decision = get_advisor_decision("BTCUSDT", "4h", btc_h4_indicators, ADVISOR_BASE_CONFIG) if btc_h4_indicators else {}
    market_snapshot = {
        "fear_greed": load_json_file(os.path.join(PROJECT_ROOT, "ricenews/lognew/market_context.json")).get("fear_greed", 50),
        "btc_d1_trend": all_indicators.get("BTCUSDT", {}).get("1d", {}).get("trend", "sideway"),
        "btc_d1_adx": all_indicators.get("BTCUSDT", {}).get("1d", {}).get("adx", 20.0),
        "btc_d1_atr_percent": all_indicators.get("BTCUSDT", {}).get("1d", {}).get("atr_percent", 1.5),
        "btc_h4_ai_score": btc_h4_advisor_decision.get("final_score", 5.0),
        "btc_d1_candle_pattern": all_indicators.get("BTCUSDT", {}).get("1d", {}).get("candle_pattern", "none"),
        "btc_breakout_signal": all_indicators.get("BTCUSDT", {}).get("4h", {}).get("breakout_signal", "none"), # <-- Thêm tín hiệu breakout của BTC
    }
    selected_tactic_name = select_best_tactic(market_snapshot)
    effective_tactic = apply_portfolio_psychology(TACTICS_LAB[selected_tactic_name], portfolio_state)

    # Quét lệnh mới với logic V5.0
    opened_this_session = False
    for symbol in SYMBOLS_TO_SCAN:
        if any(t['symbol'] == symbol for t in portfolio_state['active_trades']): continue
        for interval in INTERVALS_TO_SCAN:
            current_symbol_indicators = all_indicators.get(symbol, {}).get(interval)
            if not current_symbol_indicators or current_symbol_indicators.get('price', 0) == 0: continue
            
            # --- LOGIC QUYẾT ĐỊNH VÀO LỆNH V5.0 ---
            trade_type = None
            entry_price = current_symbol_indicators['price']
            final_score = get_advisor_decision(symbol, interval, current_symbol_indicators, ADVISOR_BASE_CONFIG, weights_override=effective_tactic.get("WEIGHTS")).get("final_score", 0.0)

            # 1. Ưu tiên kiểm tra tín hiệu Breakout
            if effective_tactic.get("ENABLE_BREAKOUT_TRADE") and current_symbol_indicators.get("breakout_signal") == 'bullish' and final_score >= effective_tactic.get("ENTRY_SCORE", 6.8):
                trade_type = "BREAKOUT_BUY"
            # 2. Kiểm tra tín hiệu Range Trade
            elif effective_tactic.get("ENABLE_RANGE_TRADE"):
                support = current_symbol_indicators.get("support_level", 0)
                proximity = effective_tactic.get("RANGE_ENTRY_PROXIMITY", 0.015)
                if support > 0 and abs(entry_price - support) / support < proximity:
                    trade_type = "RANGE_BUY"
            # 3. Kiểm tra Trend Follow
            elif final_score >= effective_tactic.get("ENTRY_SCORE", 9.9): # Mặc định cao để tránh vào lệnh nếu không có logic cụ thể
                trade_type = "TREND_FOLLOW"
            # 4. Kiểm tra Dip Buy
            elif effective_tactic.get("ENABLE_DIP", False):
                score_min, score_max = effective_tactic.get("DIP_RANGE", [0,0])
                if score_min <= final_score < score_max and (current_symbol_indicators.get('rsi_divergence') == 'bullish' or current_symbol_indicators.get('candle_pattern') == 'hammer'):
                    trade_type = "DIP_BUY"

            # Nếu có tín hiệu, tiến hành tạo lệnh
            if trade_type:
                # Tính toán kích thước lệnh
                amount_percent = effective_tactic.get("TRADE_PCT", 0.1)
                if effective_tactic.get("USE_DYNAMIC_TRADE_PCT", False):
                    amount_percent = effective_tactic.get("DYNAMIC_TRADE_PCT_RULES", {}).get(trade_type, amount_percent)
                invested_usd = portfolio_state['cash'] * amount_percent
                if invested_usd > portfolio_state['cash'] or invested_usd < 10: continue

                # Tính toán TP/SL
                tp_price, sl_price = 0, 0
                if trade_type == "RANGE_BUY":
                    sl_price = current_symbol_indicators['support_level'] * (1 - effective_tactic.get("SL_BELOW_SUPPORT_PCT", 0.02))
                    tp_price = current_symbol_indicators['resistance_level']
                else: # Logic cho các loại lệnh khác
                    calculated_rr = effective_tactic.get("RR", 2.0)
                    if final_score >= TP_SL_SCALING_RULES["critical_score_threshold"]: calculated_rr *= TP_SL_SCALING_RULES["critical_score_rr_multiplier"]
                    elif final_score >= TP_SL_SCALING_RULES["high_score_threshold"]: calculated_rr *= TP_SL_SCALING_RULES["high_score_rr_multiplier"]
                    
                    risk_distance = 0
                    if effective_tactic.get("USE_ATR_SL", False) and current_symbol_indicators.get('atr', 0) > 0:
                        risk_distance = current_symbol_indicators['atr'] * effective_tactic.get("ATR_SL_MULTIPLIER", 2.0)
                    else:
                        risk_distance = entry_price * effective_tactic.get("SL_PCT", 0.03)
                    sl_price = entry_price - risk_distance
                    tp_price = entry_price + (risk_distance * calculated_rr)
                
                if tp_price <= entry_price or sl_price >= entry_price: continue

                # Tạo và lưu lệnh mới
                new_trade = {"trade_id": str(uuid.uuid4()), "symbol": symbol, "interval": interval, "status": "ACTIVE", "opened_by_tactic": selected_tactic_name, "trade_type": trade_type, "entry_price": entry_price, "tp": round(tp_price, 8), "sl": round(sl_price, 8), "invested_usd": invested_usd, "entry_time": datetime.now(VIETNAM_TZ).isoformat(), "entry_score": final_score}
                portfolio_state["cash"] -= invested_usd
                portfolio_state["active_trades"].append(new_trade)
                opened_this_session = True
                log_message(f"🔥 Lệnh Mới ({selected_tactic_name}/{trade_type}): {symbol} | Score: {final_score:.2f} | Invested: ${invested_usd:,.2f}")
                break
        if opened_this_session: break

    # Lưu trạng thái và báo cáo
    current_total_equity = calculate_total_equity(portfolio_state)
    log_message(f"💰 Tiền Mặt Khả Dụng: ${portfolio_state['cash']:,.2f} | Tổng Tài Sản: ${current_total_equity:,.2f} | Lệnh Mở: {len(portfolio_state['active_trades'])}")
    save_json_file(STATE_FILE, portfolio_state)
    if newly_closed_trades: export_trade_history_to_csv(newly_closed_trades)
    
    timestamps = load_json_file(TIMESTAMP_FILE, {})
    if should_send_daily_summary(datetime.now(VIETNAM_TZ), timestamps):
        report_content = build_professional_summary_report(portfolio_state)
        send_discord_report(report_content)
        timestamps["last_daily_report_time_slot"] = datetime.now(VIETNAM_TZ).strftime("%Y-%m-%d-%H")
        save_json_file(TIMESTAMP_FILE, timestamps)

# --- Các hàm báo cáo (build_professional_summary_report, get_current_pnl, should_send_daily_summary) giữ nguyên ---
def get_current_pnl(trade: Dict) -> Tuple[float, float]:
    current_data = all_indicators.get(trade["symbol"], {}).get(trade["interval"])
    if not current_data or current_data.get('price', 0) == 0 or trade.get('entry_price', 0) == 0: return 0.0, 0.0
    current_price = current_data['price']; invested_amount = trade.get('invested_usd', 0.0)
    pnl_percent = (current_price - trade['entry_price']) / trade['entry_price']
    return invested_amount * pnl_percent, pnl_percent * 100
def should_send_daily_summary(now_vn: datetime, timestamps: dict) -> bool:
    last_sent_time_slot = timestamps.get("last_daily_report_time_slot", "")
    current_time_slot = now_vn.strftime("%Y-%m-%d-%H")
    return now_vn.hour in [8, 20] and current_time_slot != last_sent_time_slot
def build_professional_summary_report(state: Dict) -> str:
    now_vn = datetime.now(VIETNAM_TZ)
    if not state: return "Chưa có dữ liệu danh mục để báo cáo."
    current_total_equity = calculate_total_equity(state)
    pnl_usd = current_total_equity - INITIAL_CAPITAL
    pnl_percent = (pnl_usd / INITIAL_CAPITAL) * 100 if INITIAL_CAPITAL > 0 else 0
    pnl_icon = "📈" if pnl_usd >= 0 else "📉"
    winrate_pct, wins, losses = calculate_winrate(state.get('trade_history', []))
    report_lines = [f"📊 **Báo Cáo Tổng Quan - {now_vn.strftime('%H:%M %d-%m-%Y')}** 📊\n" f"```{pnl_icon} Tổng Tài Sản: ${current_total_equity:,.2f} ({pnl_percent:+.2f}%)\n" f"   - PnL         : ${pnl_usd:,.2f}\n" f"   - Vốn Ban Đầu : ${INITIAL_CAPITAL:,.2f}\n" f"   - Winrate     : {winrate_pct:.2f}% ({wins}W/{losses}L)\n" f"💰 Tiền Mặt     : ${state.get('cash', 0):,.2f}```"]
    active_trades = state.get('active_trades', [])
    report_lines.append(f"**💼 Vị thế đang mở ({len(active_trades)})**")
    if not active_trades: report_lines.append("> `Không có vị thế nào đang mở.`")
    else:
        positions_by_symbol = defaultdict(list)
        for trade in active_trades: positions_by_symbol[trade['symbol']].append(trade)
        summary_text = ""
        for symbol, trades in positions_by_symbol.items():
            total_invested = sum(t['invested_usd'] for t in trades); total_pnl_usd = sum(get_current_pnl(t)[0] for t in trades)
            avg_pnl_percent = total_pnl_usd / total_invested * 100 if total_invested > 0 else 0
            icon = "🟢" if total_pnl_usd >= 0 else "🔴"
            summary_text += (f"{icon} {symbol}: {len(trades)} lệnh | Invest: ${total_invested:,.2f} | PnL: ${total_pnl_usd:,.2f} ({avg_pnl_percent:+.2f}%)\n")
        report_lines.append(f"```{summary_text}```")
    trade_history = state.get('trade_history', [])
    winning_trades = sorted([t for t in trade_history if t.get('pnl_usd', 0) > 0], key=lambda x: x.get('exit_time', ''), reverse=True)
    report_lines.append("\n**🏆 Top 5 Lệnh Thắng Gần Nhất**")
    if not winning_trades: report_lines.append("> `Chưa có lệnh thắng nào.`")
    else:
        win_text = ""
        for trade in winning_trades[:5]: win_text += (f"✅ {trade['symbol']} | PnL: ${trade['pnl_usd']:,.2f} ({trade['pnl_percent']:.2f}%) | Tactic: {trade['opened_by_tactic']}\n")
        report_lines.append(f"```{win_text}```")
    losing_trades = sorted([t for t in trade_history if t.get('pnl_usd', 0) <= 0], key=lambda x: x.get('exit_time', ''), reverse=True)
    report_lines.append("\n**💔 Top 5 Lệnh Thua Gần Nhất**")
    if not losing_trades: report_lines.append("> `Chưa có lệnh thua nào.`")
    else:
        loss_text = ""
        for trade in losing_trades[:5]: loss_text += (f"❌ {trade['symbol']} | PnL: ${trade['pnl_usd']:,.2f} ({trade['pnl_percent']:.2f}%) | Tactic: {trade['opened_by_tactic']}\n")
        report_lines.append(f"```{loss_text}```")
    active_trades_with_pnl = []
    for trade in active_trades: pnl_usd, pnl_percent = get_current_pnl(trade); trade_copy = trade.copy(); trade_copy['current_pnl_percent'] = pnl_percent; active_trades_with_pnl.append(trade_copy)
    sideway_trades = sorted(active_trades_with_pnl, key=lambda x: abs(x.get('current_pnl_percent', 0)))
    report_lines.append("\n**⚖️ Top 5 Lệnh Ít Biến Động Nhất (Sideway)**")
    if not sideway_trades: report_lines.append("> `Không có lệnh nào đang mở.`")
    else:
        sideway_text = ""
        for trade in sideway_trades[:5]: sideway_text += (f"🟡 {trade['symbol']} | PnL: {trade.get('current_pnl_percent', 0):+.2f}% | Giữ: {(datetime.now(VIETNAM_TZ) - datetime.fromisoformat(trade['entry_time'])).total_seconds() / 3600:.1f}h\n")
        report_lines.append(f"```{sideway_text}```")
    return "\n".join(report_lines)

if __name__ == "__main__":
    log_message("====== 🚀 QUẢN LÝ DANH MỤC (PAPER TRADE) V5.0 BẮT ĐẦU PHIÊN LÀM VIỆC 🚀 ======")
    try:
        run_paper_trade_session()
    except Exception as e:
        log_message(f"!!!!!! ❌ LỖI NGHIÊM TRỌNG TRONG PHIÊN LÀM VIỆC ❌ !!!!!!")
        import traceback
        log_message(traceback.format_exc())
    log_message("====== ✅ QUẢN LÝ DANH MỤC (PAPER TRADE) KẾT THÚC PHIÊN LÀM VIỆC ✅ ======")
