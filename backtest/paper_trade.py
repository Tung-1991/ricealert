# /root/ricealert/backtest/paper_trade.py
# -*- coding: utf-8 -*-
"""
paper_trade.py - Quản lý Danh mục Mô phỏng Thông minh (Paper Trading)
Version: 4.0 (Professional Reporting & Bug Fixes)
Date: 2025-07-07

Description:
Hệ thống quản lý danh mục với báo cáo chuyên nghiệp và các bản sửa lỗi quan trọng.
- BÁO CÁO DISCORD NÂNG CAO:
  1. Báo cáo tóm tắt hàng ngày được thiết kế lại hoàn toàn, chuyên nghiệp và chi tiết.
  2. Hiển thị tóm tắt các vị thế đang mở, nhóm theo từng tài sản.
  3. Liệt kê Top 5 lệnh Thắng/Thua/Đi ngang gần nhất.
- SỬA LỖI GHI FILE CSV: Khắc phục lỗi ghi lặp lại lịch sử giao dịch.
- CẢI THIỆN FILE CSV: Thêm cột 'holding_duration_hours' để dễ phân tích.
- Tương thích hoàn toàn với indicator.py phiên bản mới nhất (đã sửa lỗi ATR).
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
sys.path.append(PROJECT_ROOT) # Để import các module từ PROJECT_ROOT
PAPER_DATA_DIR = os.path.join(BASE_DIR, "paper_data")
os.makedirs(PAPER_DATA_DIR, exist_ok=True)

# --- Import các thành phần cốt lõi ---
from indicator import get_price_data, calculate_indicators
from trade_advisor import get_advisor_decision, FULL_CONFIG as ADVISOR_BASE_CONFIG

# ==============================================================================
# ====================== 📚 THƯ VIỆN LỐI ĐÁNH (TACTICS LAB) 📚 ===================
# ======================== PHIÊN BẢN CẢI TIẾN V3.0 ============================
# ==============================================================================
TACTICS_LAB = {
    "Balanced_Trader": {
        "NOTES": "Cân bằng, SL động theo ATR, kích thước lệnh theo loại",
        "WEIGHTS": {'tech': 0.4, 'context': 0.2, 'ai': 0.4}, "ENTRY_SCORE": 6.5, "RR": 2.2, "ENABLE_DIP": True, "DIP_RANGE": [3.0, 4.8],
        "USE_ATR_SL": True, "ATR_SL_MULTIPLIER": 2.5, "SL_PCT": 0.05,
        "USE_DYNAMIC_TRADE_PCT": True, "DYNAMIC_TRADE_PCT_RULES": {'TREND_FOLLOW': 0.1, 'DIP_BUY': 0.06}, "TRADE_PCT": 0.1
    },
    "AI_Aggressor": {
        "NOTES": "Khi trend mạnh, tin vào AI, SL rộng theo ATR",
        "WEIGHTS": {'tech': 0.1, 'context': 0.1, 'ai': 0.8}, "ENTRY_SCORE": 7.0, "RR": 1.8, "ENABLE_DIP": False,
        "USE_ATR_SL": True, "ATR_SL_MULTIPLIER": 3.0, "SL_PCT": 0.08,
        "USE_DYNAMIC_TRADE_PCT": False, "TRADE_PCT": 0.15
    },
    "Dip_Hunter": {
        "NOTES": "Khi sợ hãi, chuyên bắt đáy, RR cao, SL động",
        "WEIGHTS": {'tech': 0.5, 'context': 0.3, 'ai': 0.2}, "ENTRY_SCORE": 7.0, "RR": 3.0, "ENABLE_DIP": True, "DIP_RANGE": [2.5, 4.5],
        "USE_ATR_SL": True, "ATR_SL_MULTIPLIER": 2.0, "SL_PCT": 0.04,
        "USE_DYNAMIC_TRADE_PCT": True, "DYNAMIC_TRADE_PCT_RULES": {'TREND_FOLLOW': 0.08, 'DIP_BUY': 0.07}, "TRADE_PCT": 0.08
    },
    "Cautious_Observer": {
        "NOTES": "Khi sideways, chỉ quan sát, bảo toàn vốn",
        "WEIGHTS": {'tech': 0.5, 'context': 0.5, 'ai': 0.0}, "ENTRY_SCORE": 9.9, "RR": 2.0, "ENABLE_DIP": False,
        "USE_ATR_SL": True, "ATR_SL_MULTIPLIER": 2.0, "SL_PCT": 0.03,
        "USE_DYNAMIC_TRADE_PCT": False, "TRADE_PCT": 0.08
    },
    "Market_Mirror": {
        "NOTES": "Mô phỏng Alerter, làm baseline, SL động",
        "WEIGHTS": {'tech': 0.4, 'context': 0.2, 'ai': 0.4}, "ENTRY_SCORE": 6.0, "RR": 1.8, "ENABLE_DIP": True, "DIP_RANGE": [3.0, 4.8],
        "USE_ATR_SL": True, "ATR_SL_MULTIPLIER": 2.5, "SL_PCT": 0.05,
        "USE_DYNAMIC_TRADE_PCT": True, "DYNAMIC_TRADE_PCT_RULES": {'TREND_FOLLOW': 0.1, 'DIP_BUY': 0.05}, "TRADE_PCT": 0.1
    },
}


# --- Cài đặt chung & Báo cáo ---
INITIAL_CAPITAL = 10000.0
SYMBOLS_TO_SCAN = ["ETHUSDT", "AVAXUSDT", "INJUSDT", "LINKUSDT", "SUIUSDT", "FETUSDT", "TAOUSDT"]
INTERVALS_TO_SCAN = ["1h", "4h"]
ALL_TIME_FRAMES = ["1h", "4h", "1d"]
VIETNAM_TZ = pytz.timezone('Asia/Ho_Chi_Minh')
PSYCHOLOGY_PNL_THRESHOLD_PERCENT = -5.0

# --- Cài đặt cho Báo cáo Biến động ---
VOLATILITY_REPORT_COOLDOWN_HOURS = 4
VOLATILITY_REPORT_PNL_THRESHOLD = 0.5

# --- Cài đặt cho TP/SL Scaling dựa trên Score ---
TP_SL_SCALING_RULES = {
    "high_score_rr_multiplier": 1.2,
    "critical_score_rr_multiplier": 1.5,
    "high_score_threshold": 7.0,
    "critical_score_threshold": 8.5
}

# --- Đường dẫn file & Webhook ---
LOG_FILE = os.path.join(PAPER_DATA_DIR, "paper_trade_log.txt")
STATE_FILE = os.path.join(PAPER_DATA_DIR, "paper_trade_state.json")
TIMESTAMP_FILE = os.path.join(PAPER_DATA_DIR, "paper_trade_timestamps.json")
TRADE_HISTORY_CSV_FILE = os.path.join(PAPER_DATA_DIR, "trade_history.csv")

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_PAPER_WEBHOOK")

# ==============================================================================
# BIẾN TOÀN CỤC
# ==============================================================================
all_indicators: Dict[str, Any] = {}

# ==============================================================================
# ================= 🛠️ CÁC HÀM TIỆN ÍCH & QUẢN LÝ 🛠️ ======================
# ==============================================================================
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
    # Discord có giới hạn 2000 ký tự mỗi tin nhắn
    for i in range(0, len(content), 1950):
        chunk = content[i:i+1950]
        payload = {"content": chunk}
        try:
            requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10).raise_for_status()
            time.sleep(1) # Tránh rate limit
        except requests.exceptions.RequestException as e:
            log_message(f"❌ Lỗi khi gửi báo cáo Discord: {e}")
            break

def export_trade_history_to_csv(trade_history: List[Dict]):
    """Ghi lịch sử giao dịch vào file CSV. Chỉ ghi những lệnh được truyền vào."""
    if not trade_history:
        return

    df_history = pd.DataFrame(trade_history)

    # Tính toán thêm các cột hữu ích
    df_history['entry_time_dt'] = pd.to_datetime(df_history['entry_time'])
    df_history['exit_time_dt'] = pd.to_datetime(df_history['exit_time'])
    df_history['holding_duration_hours'] = (df_history['exit_time_dt'] - df_history['entry_time_dt']).dt.total_seconds() / 3600
    df_history['holding_duration_hours'] = df_history['holding_duration_hours'].round(2)

    # Sắp xếp các cột theo thứ tự dễ đọc
    columns_order = [
        "trade_id", "symbol", "interval", "status", "opened_by_tactic", "trade_type",
        "entry_price", "exit_price", "tp", "sl", "invested_usd",
        "pnl_usd", "pnl_percent", "entry_time", "exit_time", "holding_duration_hours", "entry_score"
    ]
    df_history = df_history[[col for col in columns_order if col in df_history.columns]]

    file_exists = os.path.exists(TRADE_HISTORY_CSV_FILE)
    mode = 'a' if file_exists else 'w'
    header = not file_exists

    try:
        df_history.to_csv(TRADE_HISTORY_CSV_FILE, mode=mode, header=header, index=False, encoding="utf-8")
        log_message(f"✅ Đã xuất {len(df_history)} lệnh đã đóng vào {TRADE_HISTORY_CSV_FILE}")
    except Exception as e:
        log_message(f"❌ Lỗi khi xuất lịch sử giao dịch ra CSV: {e}")

# ==============================================================================
# ============ 🧠 BỘ NÃO THÍCH ỨNG: CHỌN LỐI ĐÁNH 🧠 =============
# ==============================================================================
def select_best_tactic(market_snapshot: Dict) -> str:
    tactic_scores = {tactic: 0 for tactic in TACTICS_LAB}
    fg_index = market_snapshot.get("fear_greed", 50)
    btc_d1_trend = market_snapshot.get("btc_d1_trend", "sideway")
    btc_d1_adx = market_snapshot.get("btc_d1_adx", 20.0)
    btc_d1_atr_pct = market_snapshot.get("btc_d1_atr_percent", 1.5)
    btc_h4_ai_score = market_snapshot.get("btc_h4_ai_score", 5.0)
    btc_d1_doji_type = market_snapshot.get("btc_d1_doji_type", "none")
    btc_d1_candle_pattern = market_snapshot.get("btc_d1_candle_pattern", "none")

    log_message(f"Snapshot Thị trường: F&G={fg_index}, BTC Trend={btc_d1_trend}, ADX={btc_d1_adx:.2f}, ATR%={btc_d1_atr_pct:.2f}, AI Score (BTC)={btc_h4_ai_score:.2f}, Doji={btc_d1_doji_type}, Pattern={btc_d1_candle_pattern}")

    # Rules Engine
    if btc_d1_adx > 28 and btc_d1_trend == "uptrend":
        tactic_scores["AI_Aggressor"] += 3; tactic_scores["Balanced_Trader"] += 1; tactic_scores["Cautious_Observer"] -= 2
    elif btc_d1_adx > 28 and btc_d1_trend == "downtrend":
        tactic_scores["Dip_Hunter"] += 2; tactic_scores["Cautious_Observer"] -= 1; tactic_scores["AI_Aggressor"] -= 2
    elif btc_d1_adx < 20:
        tactic_scores["Cautious_Observer"] += 3; tactic_scores["Balanced_Trader"] += 1; tactic_scores["AI_Aggressor"] -= 2; tactic_scores["Dip_Hunter"] += 1
    if fg_index > 75:
        tactic_scores["AI_Aggressor"] += 2; tactic_scores["Market_Mirror"] += 1; tactic_scores["Dip_Hunter"] -= 1
    elif fg_index < 25:
        tactic_scores["Dip_Hunter"] += 3; tactic_scores["Cautious_Observer"] += 1; tactic_scores["AI_Aggressor"] -= 1
    if btc_d1_atr_pct > 4.0:
        tactic_scores["Dip_Hunter"] += 2; tactic_scores["AI_Aggressor"] += 1; tactic_scores["Cautious_Observer"] -= 2
    elif btc_d1_atr_pct < 1.5:
        tactic_scores["Cautious_Observer"] += 2; tactic_scores["AI_Aggressor"] -= 1
    if btc_h4_ai_score > 7.5:
        tactic_scores["AI_Aggressor"] += 4; tactic_scores["Balanced_Trader"] += 1
    elif btc_h4_ai_score < 4.0:
        tactic_scores["AI_Aggressor"] -= 2; tactic_scores["Cautious_Observer"] += 1; tactic_scores["Dip_Hunter"] += 0.5
    if btc_d1_doji_type == "dragonfly" and btc_d1_trend == "downtrend":
        tactic_scores["Dip_Hunter"] += 2.5; tactic_scores["Balanced_Trader"] += 1
    elif btc_d1_doji_type == "gravestone" and btc_d1_trend == "uptrend":
        tactic_scores["Cautious_Observer"] += 2; tactic_scores["AI_Aggressor"] -= 1
    elif btc_d1_candle_pattern == "bullish_engulfing" and btc_d1_trend == "downtrend":
        tactic_scores["Dip_Hunter"] += 2; tactic_scores["Balanced_Trader"] += 1
    elif btc_d1_candle_pattern == "bearish_engulfing" and btc_d1_trend == "uptrend":
        tactic_scores["Cautious_Observer"] += 1.5; tactic_scores["AI_Aggressor"] -= 1
    elif btc_d1_doji_type in ["common", "long_legged"]:
        tactic_scores["Cautious_Observer"] += 1; tactic_scores["Balanced_Trader"] += 0.5
    
    tactic_scores["Balanced_Trader"] += 1
    log_message(f"Chấm điểm lối đánh: {tactic_scores}")
    best_tactic = max(tactic_scores, key=tactic_scores.get)
    log_message(f"🏆 Lối đánh chiến thắng: [{best_tactic}] với số điểm {tactic_scores[best_tactic]}")
    return best_tactic

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
        effective_config["ENTRY_SCORE"] += 0.5
        log_message(f"😨 Tâm lý Sợ hãi kích hoạt! (PnL: {pnl_percent:.2f}%) -> Giảm rủi ro, tăng ngưỡng điểm.")
    return effective_config

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
    winrate = (winning_trades / total_closed_trades) * 100
    return round(winrate, 2), winning_trades, losing_trades

# ==============================================================================
# ======================== CORE TRADING SESSION ============================
# ==============================================================================
def run_paper_trade_session():
    global all_indicators
    portfolio_state = load_json_file(STATE_FILE, {"cash": INITIAL_CAPITAL, "active_trades": [], "trade_history": []})
    
    # Normalize state
    if 'cash' not in portfolio_state: portfolio_state['cash'] = INITIAL_CAPITAL
    for trade_list_key in ['active_trades', 'trade_history']:
        for trade in portfolio_state.get(trade_list_key, []):
            if 'invested_usd' not in trade: trade['invested_usd'] = trade.pop('amount_usd', 0.0)
            trade['invested_usd'] = float(trade.get('invested_usd', 0.0))
            trade['entry_price'] = float(trade.get('entry_price', 0.0))
    
    realized_pnl_sum = sum(t.get('pnl_usd', 0) for t in portfolio_state.get('trade_history', []))
    invested_in_active_trades = sum(t.get('invested_usd', 0) for t in portfolio_state.get('active_trades', []))
    portfolio_state['cash'] = INITIAL_CAPITAL + realized_pnl_sum - invested_in_active_trades
    log_message(f"✅ Đã tính toán lại tiền mặt khả dụng: ${portfolio_state['cash']:,.2f}")

    # Fetch all indicators
    all_indicators.clear()
    all_symbols_to_fetch = list(set(SYMBOLS_TO_SCAN + ["BTCUSDT"]))
    for symbol in all_symbols_to_fetch:
        all_indicators[symbol] = {}
        for interval in ALL_TIME_FRAMES:
            try:
                df = get_price_data(symbol, interval, limit=200)
                all_indicators[symbol][interval] = calculate_indicators(df, symbol, interval)
            except Exception as e:
                log_message(f"❌ Lỗi khi tính chỉ báo cho {symbol}-{interval}: {e}")
                all_indicators[symbol][interval] = {"price": 0, "atr": 0, "reason": "Lỗi tính toán"}
    
    # Enrich indicators with multi-timeframe RSI
    log_message("Đang làm giàu dữ liệu chỉ báo với RSI đa khung thời gian...")
    for sym_enrich in all_symbols_to_fetch:
        rsi_h1 = all_indicators.get(sym_enrich, {}).get("1h", {}).get("rsi_14", 50)
        rsi_h4 = all_indicators.get(sym_enrich, {}).get("4h", {}).get("rsi_14", 50)
        rsi_d1 = all_indicators.get(sym_enrich, {}).get("1d", {}).get("rsi_14", 50)
        for itv_enrich in ALL_TIME_FRAMES:
            if all_indicators.get(sym_enrich, {}).get(itv_enrich):
                all_indicators[sym_enrich][itv_enrich].update({'rsi_1h': rsi_h1, 'rsi_4h': rsi_h4, 'rsi_1d': rsi_d1})
    log_message("✅ Hoàn thành làm giàu dữ liệu chỉ báo.")

    # Close old trades
    trades_to_remove = []
    newly_closed_trades = [] # SỬA LỖI CSV
    for trade in portfolio_state["active_trades"]:
        current_data = all_indicators.get(trade["symbol"], {}).get(trade["interval"])
        if not current_data or current_data.get('price', 0) == 0: continue
        current_price = current_data['price']
        status, exit_price = (None, None)
        if current_price <= trade["sl"]: status, exit_price = "SL_HIT", trade["sl"]
        elif current_price >= trade["tp"]: status, exit_price = "TP_HIT", trade["tp"]
        if status:
            pnl_percent = (exit_price - trade["entry_price"]) / trade["entry_price"]
            pnl_usd = trade["invested_usd"] * pnl_percent
            portfolio_state["cash"] += (trade["invested_usd"] + pnl_usd)
            trade.update({"status": status, "exit_price": exit_price, "exit_time": datetime.now(VIETNAM_TZ).isoformat(), "pnl_percent": pnl_percent * 100, "pnl_usd": pnl_usd})
            portfolio_state["trade_history"].append(trade)
            newly_closed_trades.append(trade) # SỬA LỖI CSV
            trades_to_remove.append(trade)
            log_message(f"{'✅' if pnl_usd >= 0 else '❌'} Lệnh Đóng: {trade['symbol']} | {status} | PnL: ${pnl_usd:,.2f}")

    if trades_to_remove:
        portfolio_state["active_trades"] = [t for t in portfolio_state["active_trades"] if t not in trades_to_remove]
        portfolio_state["trade_history"] = sorted(portfolio_state["trade_history"], key=lambda x: x.get('exit_time', ''), reverse=True)[:1000]

    # Decide and Act
    market_context = load_json_file(os.path.join(PROJECT_ROOT, "ricenews/lognew/market_context.json"))
    btc_h4_indicators = all_indicators.get("BTCUSDT", {}).get("4h", {})
    btc_h4_advisor_input = btc_h4_indicators.copy()
    btc_h4_advisor_input['price'] = btc_h4_indicators.get('closed_candle_price', 0)
    btc_h4_advisor_decision = get_advisor_decision("BTCUSDT", "4h", btc_h4_advisor_input, ADVISOR_BASE_CONFIG) if btc_h4_advisor_input['price'] > 0 else {}
    
    market_snapshot = {
        "fear_greed": market_context.get("fear_greed", 50),
        "btc_d1_trend": all_indicators.get("BTCUSDT", {}).get("1d", {}).get("trend", "sideway"),
        "btc_d1_adx": all_indicators.get("BTCUSDT", {}).get("1d", {}).get("adx", 20.0),
        "btc_d1_atr_percent": all_indicators.get("BTCUSDT", {}).get("1d", {}).get("atr_percent", 1.5),
        "btc_h4_ai_score": btc_h4_advisor_decision.get("final_score", 5.0),
        "btc_d1_doji_type": all_indicators.get("BTCUSDT", {}).get("1d", {}).get("doji_type", "none"),
        "btc_d1_candle_pattern": all_indicators.get("BTCUSDT", {}).get("1d", {}).get("candle_pattern", "none"),
    }
    selected_tactic_name = select_best_tactic(market_snapshot)
    effective_tactic = apply_portfolio_psychology(TACTICS_LAB[selected_tactic_name], portfolio_state)

    # Scan for new trades
    opened_this_session = False
    for symbol in SYMBOLS_TO_SCAN:
        if any(t['symbol'] == symbol for t in portfolio_state['active_trades']): continue
        for interval in INTERVALS_TO_SCAN:
            current_symbol_indicators = all_indicators.get(symbol, {}).get(interval)
            if not current_symbol_indicators or current_symbol_indicators.get('price', 0) == 0: continue
            
            indicators_for_advisor = current_symbol_indicators.copy()
            indicators_for_advisor['price'] = current_symbol_indicators.get('closed_candle_price', 0)
            if indicators_for_advisor['price'] == 0: continue
            
            decision = get_advisor_decision(symbol, interval, indicators_for_advisor, ADVISOR_BASE_CONFIG, weights_override=effective_tactic["WEIGHTS"])
            final_score = decision.get("final_score", 0.0)
            
            trade_type = None
            if final_score >= effective_tactic["ENTRY_SCORE"]: trade_type = "TREND_FOLLOW"
            elif effective_tactic.get("ENABLE_DIP", False):
                score_min, score_max = effective_tactic["DIP_RANGE"]
                if score_min <= final_score < score_max:
                    if (indicators_for_advisor.get('rsi_divergence') == 'bullish' or indicators_for_advisor.get('doji_type') == 'dragonfly' or indicators_for_advisor.get('candle_pattern') == 'hammer'):
                        trade_type = "DIP_BUY"
            
            if trade_type:
                entry_price = current_symbol_indicators['price']
                if entry_price == 0: continue
                
                # Dynamic Position Sizing
                amount_percent = 0.0
                if effective_tactic.get("USE_DYNAMIC_TRADE_PCT", False):
                    amount_percent = effective_tactic.get("DYNAMIC_TRADE_PCT_RULES", {}).get(trade_type, 0.0)
                else:
                    amount_percent = effective_tactic.get("TRADE_PCT", 0.0)
                
                if amount_percent <= 0: continue
                invested_usd = portfolio_state['cash'] * amount_percent
                if invested_usd > portfolio_state['cash'] or invested_usd < 10: continue

                # Dynamic TP/SL
                calculated_rr = effective_tactic["RR"]
                if final_score >= TP_SL_SCALING_RULES["critical_score_threshold"]: calculated_rr *= TP_SL_SCALING_RULES["critical_score_rr_multiplier"]
                elif final_score >= TP_SL_SCALING_RULES["high_score_threshold"]: calculated_rr *= TP_SL_SCALING_RULES["high_score_rr_multiplier"]
                
                risk_distance = 0.0
                if effective_tactic.get("USE_ATR_SL", False) and 'atr' in current_symbol_indicators and current_symbol_indicators['atr'] > 0:
                    risk_distance = current_symbol_indicators['atr'] * effective_tactic.get("ATR_SL_MULTIPLIER", 2.0)
                else:
                    risk_distance = entry_price * effective_tactic.get("SL_PCT", 0.03)
                
                if risk_distance <= 0: continue
                sl_price = entry_price - risk_distance
                tp_price = entry_price + (risk_distance * calculated_rr)
                
                new_trade = {"trade_id": str(uuid.uuid4()), "symbol": symbol, "interval": interval, "status": "ACTIVE", "opened_by_tactic": selected_tactic_name, "trade_type": trade_type, "entry_price": entry_price, "tp": round(tp_price, 8), "sl": round(sl_price, 8), "invested_usd": invested_usd, "entry_time": datetime.now(VIETNAM_TZ).isoformat(), "entry_score": final_score}
                portfolio_state["cash"] -= invested_usd
                portfolio_state["active_trades"].append(new_trade)
                opened_this_session = True
                log_message(f"{'🔥' if trade_type == 'TREND_FOLLOW' else '💡'} Lệnh Mới ({selected_tactic_name}/{trade_type}): {symbol} | Score: {final_score:.2f} | Invested: ${invested_usd:,.2f}")
                break
        if opened_this_session: break

    # Save state and report
    current_total_equity = calculate_total_equity(portfolio_state)
    log_message(f"💰 Tiền Mặt Khả Dụng: ${portfolio_state['cash']:,.2f} | Tổng Tài Sản: ${current_total_equity:,.2f} | Lệnh Mở: {len(portfolio_state['active_trades'])}")
    save_json_file(STATE_FILE, portfolio_state)
    
    if newly_closed_trades: # SỬA LỖI CSV
        export_trade_history_to_csv(newly_closed_trades)

    now_vn = datetime.now(VIETNAM_TZ)
    timestamps = load_json_file(TIMESTAMP_FILE, {})
    if should_send_daily_summary(now_vn, timestamps):
        report_content = build_professional_summary_report(portfolio_state) # <-- GỌI HÀM BÁO CÁO MỚI
        send_discord_report(report_content)
        timestamps["last_daily_report_time_slot"] = now_vn.strftime("%Y-%m-%d-%H")
        save_json_file(TIMESTAMP_FILE, timestamps)

# ==============================================================================
# ======================== BÁO CÁO CHUYÊN NGHIỆP =========================
# ==============================================================================
def should_send_daily_summary(now_vn: datetime, timestamps: dict) -> bool:
    last_sent_time_slot = timestamps.get("last_daily_report_time_slot", "")
    current_time_slot = now_vn.strftime("%Y-%m-%d-%H")
    return now_vn.hour in [8, 20] and current_time_slot != last_sent_time_slot

def get_current_pnl(trade: Dict) -> Tuple[float, float]:
    """Tính PnL hiện tại cho một lệnh đang mở."""
    current_data = all_indicators.get(trade["symbol"], {}).get(trade["interval"])
    if not current_data or current_data.get('price', 0) == 0 or trade.get('entry_price', 0) == 0:
        return 0.0, 0.0

    current_price = current_data['price']
    invested_amount = trade.get('invested_usd', 0.0)
    pnl_percent = (current_price - trade['entry_price']) / trade['entry_price']
    pnl_usd = invested_amount * pnl_percent
    return pnl_usd, pnl_percent * 100

def build_professional_summary_report(state: Dict) -> str:
    now_vn = datetime.now(VIETNAM_TZ)
    if not state: return "Chưa có dữ liệu danh mục để báo cáo."

    # --- 1. Phần Tổng Quan ---
    current_total_equity = calculate_total_equity(state)
    pnl_usd = current_total_equity - INITIAL_CAPITAL
    pnl_percent = (pnl_usd / INITIAL_CAPITAL) * 100 if INITIAL_CAPITAL > 0 else 0
    pnl_icon = "📈" if pnl_usd >= 0 else "📉"
    winrate_pct, wins, losses = calculate_winrate(state.get('trade_history', []))
    
    report_lines = [f"📊 **Báo Cáo Tổng Quan - {now_vn.strftime('%H:%M %d-%m-%Y')}** 📊\n"
                    f"```{pnl_icon} Tổng Tài Sản: ${current_total_equity:,.2f} ({pnl_percent:+.2f}%)\n"
                    f"   - PnL         : ${pnl_usd:,.2f}\n"
                    f"   - Vốn Ban Đầu : ${INITIAL_CAPITAL:,.2f}\n"
                    f"   - Winrate     : {winrate_pct:.2f}% ({wins}W/{losses}L)\n"
                    f"💰 Tiền Mặt     : ${state.get('cash', 0):,.2f}```"]

    # --- 2. Tóm tắt các vị thế đang mở ---
    active_trades = state.get('active_trades', [])
    report_lines.append(f"**💼 Vị thế đang mở ({len(active_trades)})**")
    
    if not active_trades:
        report_lines.append("> `Không có vị thế nào đang mở.`")
    else:
        # Nhóm các lệnh theo symbol
        positions_by_symbol = defaultdict(list)
        for trade in active_trades:
            positions_by_symbol[trade['symbol']].append(trade)

        summary_text = ""
        for symbol, trades in positions_by_symbol.items():
            total_invested = sum(t['invested_usd'] for t in trades)
            total_pnl_usd = sum(get_current_pnl(t)[0] for t in trades)
            avg_pnl_percent = total_pnl_usd / total_invested * 100 if total_invested > 0 else 0
            icon = "🟢" if total_pnl_usd >= 0 else "🔴"
            
            summary_text += (f"{icon} {symbol}: {len(trades)} lệnh | Invest: ${total_invested:,.2f} | "
                             f"PnL: ${total_pnl_usd:,.2f} ({avg_pnl_percent:+.2f}%)\n")
        report_lines.append(f"```{summary_text}```")

    # --- 3. Phân loại các lệnh ---
    trade_history = state.get('trade_history', [])
    
    # Lệnh Lãi gần nhất
    winning_trades = sorted([t for t in trade_history if t.get('pnl_usd', 0) > 0], key=lambda x: x.get('exit_time', ''), reverse=True)
    report_lines.append("\n**🏆 Top 5 Lệnh Thắng Gần Nhất**")
    if not winning_trades:
        report_lines.append("> `Chưa có lệnh thắng nào.`")
    else:
        win_text = ""
        for trade in winning_trades[:5]:
            win_text += (f"✅ {trade['symbol']} | PnL: ${trade['pnl_usd']:,.2f} ({trade['pnl_percent']:.2f}%) | "
                         f"Tactic: {trade['opened_by_tactic']}\n")
        report_lines.append(f"```{win_text}```")

    # Lệnh Thua gần nhất
    losing_trades = sorted([t for t in trade_history if t.get('pnl_usd', 0) <= 0], key=lambda x: x.get('exit_time', ''), reverse=True)
    report_lines.append("\n**💔 Top 5 Lệnh Thua Gần Nhất**")
    if not losing_trades:
        report_lines.append("> `Chưa có lệnh thua nào.`")
    else:
        loss_text = ""
        for trade in losing_trades[:5]:
            loss_text += (f"❌ {trade['symbol']} | PnL: ${trade['pnl_usd']:,.2f} ({trade['pnl_percent']:.2f}%) | "
                          f"Tactic: {trade['opened_by_tactic']}\n")
        report_lines.append(f"```{loss_text}```")

    # Lệnh đang Sideway (ít biến động nhất)
    # Thêm PnL hiện tại vào mỗi lệnh đang mở để sắp xếp
    active_trades_with_pnl = []
    for trade in active_trades:
        pnl_usd, pnl_percent = get_current_pnl(trade)
        trade_copy = trade.copy()
        trade_copy['current_pnl_percent'] = pnl_percent
        active_trades_with_pnl.append(trade_copy)

    sideway_trades = sorted(active_trades_with_pnl, key=lambda x: abs(x.get('current_pnl_percent', 0)))
    report_lines.append("\n**⚖️ Top 5 Lệnh Ít Biến Động Nhất (Sideway)**")
    if not sideway_trades:
        report_lines.append("> `Không có lệnh nào đang mở.`")
    else:
        sideway_text = ""
        for trade in sideway_trades[:5]:
            sideway_text += (f"🟡 {trade['symbol']} | PnL: {trade.get('current_pnl_percent', 0):+.2f}% | "
                             f"Giữ: {(datetime.now(VIETNAM_TZ) - datetime.fromisoformat(trade['entry_time'])).total_seconds() / 3600:.1f}h\n")
        report_lines.append(f"```{sideway_text}```")

    return "\n".join(report_lines)

if __name__ == "__main__":
    log_message("====== 🚀 QUẢN LÝ DANH MỤC (PAPER TRADE) V4.0 BẮT ĐẦU PHIÊN LÀM VIỆC 🚀 ======")
    try:
        run_paper_trade_session()
    except Exception as e:
        log_message(f"!!!!!! ❌ LỖI NGHIÊM TRỌNG TRONG PHIÊN LÀM VIỆC ❌ !!!!!!")
        import traceback
        log_message(traceback.format_exc())
    log_message("====== ✅ QUẢN LÝ DANH MỤC (PAPER TRADE) KẾT THÚC PHIÊN LÀM VIỆC ✅ ======")

