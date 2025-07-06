# /root/ricealert/backtest/portfolio_manager.py
# -*- coding: utf-8 -*-
"""
portfolio_manager.py - Quản lý Danh mục Mô phỏng Thông minh
Version: 1.0 (The Intelligent Portfolio)
Date: 2025-07-07

Description:
Hệ thống này quản lý một danh mục duy nhất và tự động lựa chọn "lối đánh" 
(tactic) phù hợp nhất dựa trên tình hình thị trường hiện tại.
- Quản lý 1 danh mục vốn chung.
- Tự động phân tích và chọn 1 trong 5 lối đánh trong mỗi phiên.
- Tích hợp tâm lý giao dịch dựa trên PnL tổng.
- Gửi báo cáo định kỳ và lưu trữ file gọn gàng.
"""
import os
import sys
import json
import uuid
import time
import requests
import pytz
from datetime import datetime
from typing import Dict, List, Any
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
# ====================== 📚 THƯ VIỆN LỐI ĐÁNH (TACTICS LAB) 📚 ===================
# ==============================================================================
TACTICS_LAB = {
    "Balanced_Trader": { "NOTES": "Mặc định, cân bằng 3 yếu tố", "WEIGHTS": {'tech': 0.4, 'context': 0.2, 'ai': 0.4}, "ENTRY_SCORE": 6.5, "SL_PCT": 0.03, "RR": 2.0, "TRADE_PCT": 0.1, "ENABLE_DIP": True, "DIP_RANGE": [3.0, 4.8], "DIP_PCT": 0.05 },
    "AI_Aggressor": { "NOTES": "Khi trend mạnh, tin vào AI", "WEIGHTS": {'tech': 0.1, 'context': 0.1, 'ai': 0.8}, "ENTRY_SCORE": 7.0, "SL_PCT": 0.05, "RR": 1.8, "TRADE_PCT": 0.15, "ENABLE_DIP": False },
    "Dip_Hunter": { "NOTES": "Khi sợ hãi, chuyên bắt đáy", "WEIGHTS": {'tech': 0.5, 'context': 0.3, 'ai': 0.2}, "ENTRY_SCORE": 7.0, "SL_PCT": 0.035,"RR": 2.5, "TRADE_PCT": 0.07, "ENABLE_DIP": True, "DIP_RANGE": [2.5, 4.5], "DIP_PCT": 0.07 },
    "Cautious_Observer": { "NOTES": "Khi sideways, bảo toàn vốn", "WEIGHTS": {'tech': 0.5, 'context': 0.5, 'ai': 0.0}, "ENTRY_SCORE": 7.5, "SL_PCT": 0.025,"RR": 2.0, "TRADE_PCT": 0.08, "ENABLE_DIP": False },
    "Market_Mirror": { "NOTES": "Mô phỏng Alerter, làm baseline", "WEIGHTS": {'tech': 0.4, 'context': 0.2, 'ai': 0.4}, "ENTRY_SCORE": 6.0, "SL_PCT": 0.03, "RR": 1.8, "TRADE_PCT": 0.1, "ENABLE_DIP": True, "DIP_RANGE": [3.0, 4.8], "DIP_PCT": 0.05 },
}

# --- Cài đặt chung ---
INITIAL_CAPITAL = 10000.0
SYMBOLS_TO_SCAN = ["ETHUSDT", "AVAXUSDT", "INJUSDT", "LINKUSDT", "SUIUSDT", "FETUSDT", "TAOUSDT"]
INTERVALS_TO_SCAN = ["1h", "4h"]
VIETNAM_TZ = pytz.timezone('Asia/Ho_Chi_Minh')
PSYCHOLOGY_PNL_THRESHOLD_PERCENT = -5.0 # Ngưỡng "sợ hãi" chung cho toàn danh mục

# --- Đường dẫn file & Webhook ---
LOG_FILE = os.path.join(PAPER_DATA_DIR, "portfolio_log.txt")
STATE_FILE = os.path.join(PAPER_DATA_DIR, "portfolio_state.json")
TIMESTAMP_FILE = os.path.join(PAPER_DATA_DIR, "portfolio_timestamps.json")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_PAPER_WEBHOOK")

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
    log_message("🚀 Đang gửi báo cáo tóm tắt đến Discord...")
    # Tăng sleep time để đảm bảo không bị rate limit
    for i in range(0, len(content), 1950):
        try:
            requests.post(DISCORD_WEBHOOK_URL, json={"content": content[i:i+1950]}, timeout=10).raise_for_status()
            time.sleep(2)
        except requests.exceptions.RequestException as e:
            log_message(f"❌ Lỗi khi gửi báo cáo Discord: {e}")
            break

# ==============================================================================
# ============ 🧠 BỘ NÃO CỦA QUẢN LÝ DANH MỤC 🧠 =============
# ==============================================================================
def get_current_market_state(all_indicators: Dict) -> str:
    """Phân tích và trả về trạng thái thị trường chung."""
    # Lấy bối cảnh từ file market_context.json mà ricenews tạo ra
    market_context_path = os.path.join(PROJECT_ROOT, "ricenews/lognew/market_context.json")
    market_context = load_json_file(market_context_path)
    
    fear_greed = market_context.get("fear_greed", 50)
    
    # Lấy trend của BTC để làm đại diện
    btc_trend = all_indicators.get("BTCUSDT", {}).get("1d", {}).get("trend", "sideway")

    if fear_greed > 75 and btc_trend == "uptrend": return "EXTREME_GREED"
    if fear_greed > 65 and btc_trend == "uptrend": return "GREED"
    if fear_greed < 35 and btc_trend == "downtrend": return "FEAR"
    if fear_greed < 25 and btc_trend == "downtrend": return "EXTREME_FEAR"
    if btc_trend == "sideway": return "SIDEWAYS"
    return "NEUTRAL"

def select_tactic_for_market(market_state: str) -> str:
    """Chọn lối đánh phù hợp với trạng thái thị trường."""
    tactic_map = {
        "EXTREME_GREED": "AI_Aggressor",
        "GREED": "AI_Aggressor",
        "FEAR": "Dip_Hunter",
        "EXTREME_FEAR": "Dip_Hunter",
        "SIDEWAYS": "Cautious_Observer",
        "NEUTRAL": "Balanced_Trader",
    }
    selected = tactic_map.get(market_state, "Balanced_Trader")
    log_message(f"🔎 Trạng thái thị trường: {market_state} -> Lựa chọn lối đánh: [{selected}]")
    return selected

def apply_portfolio_psychology(tactic_config: Dict, portfolio_state: Dict) -> Dict:
    """Điều chỉnh thông số của lối đánh dựa trên PnL tổng."""
    pnl_percent = (portfolio_state['capital'] - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
    
    effective_config = tactic_config.copy()
    
    if pnl_percent < PSYCHOLOGY_PNL_THRESHOLD_PERCENT:
        # Tâm lý "Sợ hãi" toàn danh mục
        effective_config["TRADE_PCT"] /= 2  # Giảm rủi ro đi một nửa
        effective_config["ENTRY_SCORE"] += 0.5 # Kén chọn hơn
        log_message(f"😨 Tâm lý Sợ hãi kích hoạt! (PnL: {pnl_percent:.2f}%) -> Giảm rủi ro, tăng ngưỡng điểm.")
        
    return effective_config

def run_portfolio_session():
    # 1. Tải trạng thái danh mục & Lấy dữ liệu mới
    portfolio_state = load_json_file(STATE_FILE)
    if not portfolio_state:
        portfolio_state = {"capital": INITIAL_CAPITAL, "active_trades": [], "trade_history": []}
    
    all_indicators = {}
    all_symbols = SYMBOLS_TO_SCAN + ["BTCUSDT"] # Luôn lấy data BTC
    all_intervals = list(set(INTERVALS_TO_SCAN + ["1d"]))
    for symbol in all_symbols:
        all_indicators[symbol] = {}
        for interval in all_intervals:
            try:
                df = get_price_data(symbol, interval, limit=200)
                if not df.empty and len(df) >= 51:
                    all_indicators[symbol][interval] = calculate_indicators(df, symbol, interval)
            except Exception as e: log_message(f"❌ Lỗi dữ liệu: {symbol}-{interval}: {e}")

    # 2. Đóng các lệnh cũ (Logic không đổi)
    trades_to_remove = []
    for trade in portfolio_state["active_trades"]:
        current_indicators = all_indicators.get(trade["symbol"], {}).get(trade["interval"])
        if not current_indicators or 'price' not in current_indicators: continue
        current_price = current_indicators['price']
        status, exit_price = (None, None)
        if current_price <= trade["sl"]: status, exit_price = "SL_HIT", trade["sl"]
        elif current_price >= trade["tp"]: status, exit_price = "TP_HIT", trade["tp"]
        if status:
            pnl_percent = (exit_price - trade["entry_price"]) / trade["entry_price"]
            pnl_usd = trade["amount_usd"] * pnl_percent
            portfolio_state["capital"] += pnl_usd
            trade.update({"status": status, "exit_price": exit_price, "exit_time": datetime.now().isoformat(), "pnl_percent": pnl_percent * 100, "pnl_usd": pnl_usd})
            portfolio_state["trade_history"].append(trade)
            trades_to_remove.append(trade)
            log_message(f"{'✅' if pnl_usd > 0 else '❌'} Lệnh Đóng: {trade['symbol']} ({trade['opened_by_tactic']}) | {status} | PnL: ${pnl_usd:,.2f}")
    if trades_to_remove: portfolio_state["active_trades"] = [t for t in portfolio_state["active_trades"] if t not in trades_to_remove]

    # 3. Tư duy và Hành động
    market_state = get_current_market_state(all_indicators)
    selected_tactic_name = select_tactic_for_market(market_state)
    base_tactic_config = TACTICS_LAB[selected_tactic_name]
    
    # Áp dụng tâm lý lên lối đánh đã chọn
    effective_tactic = apply_portfolio_psychology(base_tactic_config, portfolio_state)
    
    # 4. Quét lệnh mới với lối đánh đã chọn
    for symbol in SYMBOLS_TO_SCAN:
        if any(t['symbol'] == symbol for t in portfolio_state['active_trades']): continue
        for interval in INTERVALS_TO_SCAN:
            main_indicators = all_indicators.get(symbol, {}).get(interval)
            if not main_indicators or 'price' not in main_indicators: continue
            for tf in ["1h", "4h", "1d"]: main_indicators[f'rsi_{tf}'] = all_indicators.get(symbol, {}).get(tf, {}).get('rsi_14', 50)

            decision = get_advisor_decision(symbol, interval, main_indicators, ADVISOR_BASE_CONFIG, weights_override=effective_tactic["WEIGHTS"])
            final_score = decision.get("final_score", 0.0)

            trade_type, amount_percent = None, 0.0
            if final_score >= effective_tactic["ENTRY_SCORE"]:
                trade_type = "TREND_FOLLOW"
                amount_percent = effective_tactic["TRADE_PCT"]
            elif effective_tactic.get("ENABLE_DIP", False):
                score_min, score_max = effective_tactic["DIP_RANGE"]
                if score_min <= final_score < score_max:
                    if main_indicators.get('rsi_divergence') == 'bullish' or main_indicators.get('doji_type') == 'dragonfly':
                        trade_type = "DIP_BUY"
                        amount_percent = effective_tactic["DIP_PCT"]
            
            if trade_type:
                entry_price = main_indicators['price']
                amount_usd = portfolio_state['capital'] * amount_percent
                if amount_usd > portfolio_state['capital'] or amount_usd < 10: continue

                sl_price = entry_price * (1 - effective_tactic["SL_PCT"])
                tp_price = entry_price * (1 + effective_tactic["SL_PCT"] * effective_tactic["RR"])
                
                new_trade = {"trade_id": str(uuid.uuid4()), "symbol": symbol, "interval": interval, "status": "ACTIVE", "opened_by_tactic": selected_tactic_name, "trade_type": trade_type, "entry_price": entry_price, "tp": tp_price, "sl": sl_price, "amount_usd": amount_usd, "entry_time": datetime.now().isoformat(), "entry_score": final_score}
                portfolio_state["active_trades"].append(new_trade)
                
                log_icon = "🔥" if trade_type == "TREND_FOLLOW" else "💡"
                log_message(f"{log_icon} Lệnh Mới ({selected_tactic_name}/{trade_type}): {symbol} | Score: {final_score:.2f}")
                break # Chỉ mở 1 lệnh mới mỗi phiên quét

    # 5. Lưu trạng thái và Gửi báo cáo
    log_message(f"💰 Vốn Hiện Tại: ${portfolio_state['capital']:,.2f} | Lệnh Mở: {len(portfolio_state['active_trades'])}")
    save_json_file(STATE_FILE, portfolio_state)
    
    # Logic gửi báo cáo (không đổi)
    if should_send_report():
        report_content = build_summary_report_for_portfolio() # Sẽ tạo hàm này
        send_discord_report(report_content)
        save_json_file(TIMESTAMP_FILE, {"last_report_sent": datetime.now().timestamp()})

def build_summary_report_for_portfolio() -> str:
    """Xây dựng báo cáo cho danh mục duy nhất."""
    now_vn = datetime.now(VIETNAM_TZ)
    state = load_json_file(STATE_FILE)
    if not state: return "Chưa có dữ liệu danh mục để báo cáo."

    capital = state.get('capital', INITIAL_CAPITAL)
    pnl_usd = capital - INITIAL_CAPITAL
    pnl_percent = (pnl_usd / INITIAL_CAPITAL) * 100 if INITIAL_CAPITAL > 0 else 0
    pnl_icon = "📈" if pnl_usd >= 0 else "📉"

    report_lines = [f"📊 **Báo Cáo Danh Mục Mô Phỏng - {now_vn.strftime('%H:%M %d-%m-%Y')}** 📊\n"]
    report_lines.append(f"--- **`Tổng Quan`** ---")
    report_lines.append(f"{pnl_icon} **Vốn:** `${capital:,.2f}` | **PnL:** `${pnl_usd:,.2f}` (`{pnl_percent:+.2f}%`)")
    
    active_trades = state.get('active_trades', [])
    if active_trades:
        report_lines.append(f"   **Lệnh đang mở ({len(active_trades)}):**")
        for trade in active_trades:
            entry_time = datetime.fromisoformat(trade['entry_time']).astimezone(VIETNAM_TZ)
            held_hours = (now_vn - entry_time).total_seconds() / 3600
            report_lines.append(f"   - `{trade['symbol']}` ({trade['trade_type']}) | Mở bởi: `{trade['opened_by_tactic']}` | Giữ: `{held_hours:.1f}h`")
    else:
        report_lines.append("   -> `Không có lệnh nào đang mở.`")
    return "\n".join(report_lines)

def should_send_report() -> bool:
    now_vn = datetime.now(VIETNAM_TZ)
    if now_vn.hour not in [8, 20]: return False
    timestamps = load_json_file(TIMESTAMP_FILE, {"last_report_sent": 0})
    if (now_vn.timestamp() - timestamps.get("last_report_sent", 0)) > 12 * 3600: return True
    return False

if __name__ == "__main__":
    log_message("====== 🚀 QUẢN LÝ DANH MỤC BẮT ĐẦU PHIÊN LÀM VIỆC 🚀 ======")
    run_portfolio_session()
    log_message("====== ✅ QUẢN LÝ DANH MỤC KẾT THÚC PHIÊN LÀM VIỆC ✅ ======")
