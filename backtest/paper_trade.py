# /root/ricealert/backtest/paper_trader.py
# -*- coding: utf-8 -*-
"""
paper_trader.py - Phòng Thí Nghiệm Giao Dịch Mô Phỏng (Paper Trading Lab)
Version: 3.0 - Tích hợp Tâm lý PnL & Dip Buying hoàn chỉnh
Date: 2025-07-06
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

# --- Tải biến môi trường (.env) ---
load_dotenv()

# --- Thiết lập đường dẫn ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
sys.path.append(PROJECT_ROOT)

# --- Tạo thư mục lưu trữ riêng ---
PAPER_DATA_DIR = os.path.join(BASE_DIR, "paper_data")
os.makedirs(PAPER_DATA_DIR, exist_ok=True)

# --- Import các thành phần cốt lõi ---
from indicator import get_price_data, calculate_indicators
from trade_advisor import get_advisor_decision, FULL_CONFIG as ADVISOR_BASE_CONFIG

# ==============================================================================
# ================== 🔬 PHÒNG THÍ NGHIỆM CHIẾN LƯỢC MÔ PHỎNG 🔬 =================
# ==============================================================================
STRATEGY_LAB = {
    "BalancedTrader": {
        "NOTES": "Trader cân bằng, có tâm lý, biết sợ hãi và tham lam, có mua dip.",
        "WEIGHTS_OVERRIDE": {'tech': 0.4, 'context': 0.2, 'ai': 0.4},
        "ENTRY_SCORE_THRESHOLD": 6.8, "RR_RATIO": 2.0, "SL_PERCENT": 0.03,
        "TRADE_AMOUNT_PERCENT": 0.1, # 10% vốn cho lệnh thường

        # --- Cấu hình Dip Buying ---
        "ENABLE_DIP_BUYING": True,
        "DIP_BUY_SCORE_RANGE": [3.0, 4.5], # Mua khi điểm thấp trong khoảng này
        "DIP_BUY_AMOUNT_PERCENT": 0.05, # Chỉ dùng 5% vốn cho lệnh dip buy rủi ro
        
        # --- Cấu hình Tâm lý ---
        "ENABLE_PSYCHOLOGY_MODE": True,
        "PSYCHOLOGY_PNL_THRESHOLD_PERCENT": -5.0, # Ngưỡng kích hoạt "sợ hãi" khi lỗ 5%
    },
    "AggressiveBot": {
        "NOTES": "Bot hung hăng, chỉ tin vào AI, không có tâm lý, không mua dip.",
        "WEIGHTS_OVERRIDE": {'tech': 0.1, 'context': 0.1, 'ai': 0.8},
        "ENTRY_SCORE_THRESHOLD": 7.2, "RR_RATIO": 1.8, "SL_PERCENT": 0.05,
        "TRADE_AMOUNT_PERCENT": 0.15, # Rủi ro cao hơn: 15% vốn
        "ENABLE_DIP_BUYING": False,
        "ENABLE_PSYCHOLOGY_MODE": False,
    },
}

# --- Cài đặt chung ---
INITIAL_CAPITAL = 10000.0
SYMBOLS_TO_SCAN = ["ETHUSDT", "AVAXUSDT", "INJUSDT", "LINKUSDT", "SUIUSDT", "FETUSDT", "TAOUSDT"]
INTERVALS_TO_SCAN = ["1h", "4h"]
VIETNAM_TZ = pytz.timezone('Asia/Ho_Chi_Minh')

# --- Đường dẫn file & Webhook ---
LOG_FILE = os.path.join(PAPER_DATA_DIR, "paper_trader_log.txt")
TIMESTAMP_FILE = os.path.join(PAPER_DATA_DIR, "paper_trader_timestamps.json")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_PAPER_WEBHOOK")

# ==============================================================================
# ================= 🛠️ CÁC HÀM TIỆN ÍCH & QUẢN LÝ 🛠️ ======================
# ==============================================================================
# ... (Các hàm log_message, load/save_json, load/save_state, send_discord, build_report, should_send không đổi) ...
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
def load_state(strategy_name: str) -> Dict[str, Any]:
    state_file = os.path.join(PAPER_DATA_DIR, f"paper_{strategy_name}_state.json")
    state = load_json_file(state_file)
    if not state:
        log_message(f"[{strategy_name}] 🟡 Không tìm thấy file trạng thái, tạo mới.")
        return {"capital": INITIAL_CAPITAL, "active_trades": [], "trade_history": []}
    return state
def save_state(strategy_name: str, state: Dict[str, Any]):
    state_file = os.path.join(PAPER_DATA_DIR, f"paper_{strategy_name}_state.json")
    save_json_file(state_file, state)
def send_discord_report(content: str):
    if not DISCORD_WEBHOOK_URL: return
    log_message("🚀 Đang gửi báo cáo tóm tắt đến Discord...")
    for i in range(0, len(content), 1950):
        try:
            requests.post(DISCORD_WEBHOOK_URL, json={"content": content[i:i+1950]}, timeout=10).raise_for_status()
            time.sleep(1)
        except requests.exceptions.RequestException as e:
            log_message(f"❌ Lỗi khi gửi báo cáo Discord: {e}")
            break
def build_summary_report() -> str:
    now_vn = datetime.now(VIETNAM_TZ)
    report_lines = [f"📊 **Báo Cáo Tóm Tắt Giao Dịch Mô Phỏng - {now_vn.strftime('%H:%M %d-%m-%Y')}** 📊\n"]
    for name, config in STRATEGY_LAB.items():
        state = load_state(name)
        capital = state.get('capital', INITIAL_CAPITAL)
        pnl_usd = capital - INITIAL_CAPITAL
        pnl_percent = (pnl_usd / INITIAL_CAPITAL) * 100 if INITIAL_CAPITAL > 0 else 0
        pnl_icon = "📈" if pnl_usd >= 0 else "📉"
        report_lines.append(f"--- **`{name}`** ---")
        report_lines.append(f"{pnl_icon} **Vốn:** `${capital:,.2f}` | **PnL:** `${pnl_usd:,.2f}` (`{pnl_percent:+.2f}%`)")
        active_trades = state.get('active_trades', [])
        if active_trades:
            report_lines.append(f"   **Lệnh đang mở ({len(active_trades)}):**")
            for trade in active_trades:
                entry_time = datetime.fromisoformat(trade['entry_time']).astimezone(VIETNAM_TZ)
                held_hours = (now_vn - entry_time).total_seconds() / 3600
                report_lines.append(f"   - `{trade['symbol']}` ({trade['trade_type']}) | Entry: `${trade['entry_price']:.3f}` | Giữ: `{held_hours:.1f}h`")
        else:
            report_lines.append("   -> `Không có lệnh nào đang mở.`")
        report_lines.append("")
    return "\n".join(report_lines)
def should_send_report() -> bool:
    now_vn = datetime.now(VIETNAM_TZ)
    if now_vn.hour not in [8, 20]: return False
    timestamps = load_json_file(TIMESTAMP_FILE, {"last_report_sent": 0})
    if (now_vn.timestamp() - timestamps.get("last_report_sent", 0)) > 12 * 3600: return True
    return False

# ==============================================================================
# ================= 🧠 LOGIC CHÍNH CỦA AGENT 🧠 ==========================
# ==============================================================================

def apply_psychology_mode(config: Dict, state: Dict) -> Dict:
    """Điều chỉnh cấu hình chiến lược dựa trên hiệu suất PnL."""
    if not config.get("ENABLE_PSYCHOLOGY_MODE", False):
        return config # Trả về config gốc nếu không bật chế độ tâm lý

    pnl_percent = (state['capital'] - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
    threshold = config.get("PSYCHOLOGY_PNL_THRESHOLD_PERCENT", -5.0)
    
    effective_config = config.copy() # Tạo bản sao để thay đổi
    
    if pnl_percent < threshold:
        # Trạng thái "Sợ hãi": Lỗ vượt ngưỡng -> Thận trọng hơn
        original_threshold = config["ENTRY_SCORE_THRESHOLD"]
        original_amount_pct = config["TRADE_AMOUNT_PERCENT"]
        
        effective_config["ENTRY_SCORE_THRESHOLD"] = original_threshold + 0.5
        effective_config["TRADE_AMOUNT_PERCENT"] = original_amount_pct / 2 # Giảm rủi ro đi một nửa
        
        log_message(f"[{config['NOTES']}] 😨 Chế độ Sợ Hãi: PnL {pnl_percent:.2f}% < {threshold}%. Ngưỡng vào lệnh tăng, rủi ro giảm.")

    elif pnl_percent > abs(threshold) * 2: # Thắng gấp đôi ngưỡng lỗ -> Tự tin
        # Trạng thái "Hưng phấn": Tự tin hơn
        original_threshold = config["ENTRY_SCORE_THRESHOLD"]
        effective_config["ENTRY_SCORE_THRESHOLD"] = original_threshold - 0.2
        log_message(f"[{config['NOTES']}] 😎 Chế độ Hưng Phấn: PnL {pnl_percent:.2f}% > {abs(threshold)*2}%. Tự tin hơn một chút.")

    return effective_config

def run_strategy_session(strategy_name: str, strategy_config: Dict, all_indicators: Dict):
    """Thực thi một phiên quét cho một chiến lược cụ thể."""
    log_message(f"--- ▶️ Bắt đầu quét cho chiến lược: [{strategy_name}] ---")
    
    state = load_state(strategy_name)
    # ÁP DỤNG TÂM LÝ: Lấy cấu hình hiệu quả cho phiên này
    effective_config = apply_psychology_mode(strategy_config, state)

    # 1. Kiểm tra và Đóng lệnh (không đổi)
    trades_to_remove = []
    for trade in state["active_trades"]:
        # ... (logic đóng lệnh giữ nguyên) ...
        current_indicators = all_indicators.get(trade["symbol"], {}).get(trade["interval"])
        if not current_indicators or 'price' not in current_indicators: continue
        current_price = current_indicators['price']
        status, exit_price = (None, None)
        if current_price <= trade["sl"]: status, exit_price = "SL_HIT", trade["sl"]
        elif current_price >= trade["tp"]: status, exit_price = "TP_HIT", trade["tp"]
        if status:
            pnl_percent = (exit_price - trade["entry_price"]) / trade["entry_price"]
            pnl_usd = trade["amount_usd"] * pnl_percent
            state["capital"] += pnl_usd
            trade.update({"status": status, "exit_price": exit_price, "exit_time": datetime.now().isoformat(), "pnl_percent": pnl_percent * 100, "pnl_usd": pnl_usd})
            state["trade_history"].append(trade)
            trades_to_remove.append(trade)
            pnl_icon = "✅" if pnl_usd > 0 else "❌"
            log_message(f"[{strategy_name}] {pnl_icon} Lệnh Đóng: {trade['symbol']} ({trade['trade_type']}) | {status} | PnL: ${pnl_usd:,.2f}")
    if trades_to_remove: state["active_trades"] = [t for t in state["active_trades"] if t not in trades_to_remove]

    # 2. Quét tìm lệnh mới (logic được nâng cấp)
    for symbol in SYMBOLS_TO_SCAN:
        if any(t['symbol'] == symbol for t in state['active_trades']): continue

        for interval in INTERVALS_TO_SCAN:
            main_indicators = all_indicators.get(symbol, {}).get(interval)
            if not main_indicators or 'price' not in main_indicators: continue

            for tf in ["1h", "4h", "1d"]: main_indicators[f'rsi_{tf}'] = all_indicators.get(symbol, {}).get(tf, {}).get('rsi_14', 50)

            decision = get_advisor_decision(symbol, interval, main_indicators, ADVISOR_BASE_CONFIG, weights_override=effective_config["WEIGHTS_OVERRIDE"])
            final_score = decision.get("final_score", 0.0)
            
            # --- Logic vào lệnh ---
            trade_type = None
            amount_percent = 0.0

            # Điều kiện 1: Bắt trend (điểm cao)
            if final_score >= effective_config["ENTRY_SCORE_THRESHOLD"]:
                trade_type = "TREND_FOLLOW"
                amount_percent = effective_config["TRADE_AMOUNT_PERCENT"]
            
            # Điều kiện 2: Mua sóng hồi (điểm thấp + tín hiệu đảo chiều)
            elif effective_config.get("ENABLE_DIP_BUYING", False):
                score_min, score_max = effective_config["DIP_BUY_SCORE_RANGE"]
                if score_min <= final_score < score_max:
                    if main_indicators.get('rsi_divergence') == 'bullish' or main_indicators.get('doji_type') == 'dragonfly':
                        trade_type = "DIP_BUY"
                        amount_percent = effective_config["DIP_BUY_AMOUNT_PERCENT"]

            # Nếu có tín hiệu (bất kể loại nào), tiến hành vào lệnh
            if trade_type:
                entry_price = main_indicators['price']
                amount_usd = state['capital'] * amount_percent
                if amount_usd > state['capital']: continue
                
                sl_price = entry_price * (1 - effective_config["SL_PERCENT"])
                tp_price = entry_price * (1 + effective_config["SL_PERCENT"] * effective_config["RR_RATIO"])
                
                new_trade = {"trade_id": str(uuid.uuid4()), "symbol": symbol, "interval": interval, "status": "ACTIVE", "trade_type": trade_type, "entry_price": entry_price, "tp": tp_price, "sl": sl_price, "amount_usd": amount_usd, "entry_time": datetime.now().isoformat(), "entry_score": final_score}
                state["active_trades"].append(new_trade)
                
                log_icon = "🔥" if trade_type == "TREND_FOLLOW" else "💡"
                log_message(f"[{strategy_name}] {log_icon} Lệnh Mới ({trade_type}): {symbol} ({interval}) | Score: {final_score:.2f} | Entry: {entry_price:.4f}")
                break

    # 3. Lưu trạng thái
    log_message(f"[{strategy_name}] 💰 Vốn Hiện Tại: ${state['capital']:,.2f} | Lệnh Mở: {len(state['active_trades'])}")
    save_state(strategy_name, state)
    log_message(f"--- ⏹️ Kết thúc quét cho chiến lược: [{strategy_name}] ---")

def main():
    log_message("====== 🚀 PHIÊN GIAO DỊCH MÔ PHỎNG BẮT ĐẦU 🚀 ======")
    all_indicators = {}
    log_message("⏳ Đang tải dữ liệu chung...")
    all_symbols, all_intervals = SYMBOLS_TO_SCAN, list(set(INTERVALS_TO_SCAN + ["1d"]))
    for symbol in all_symbols:
        all_indicators[symbol] = {}
        for interval in all_intervals:
            try:
                df = get_price_data(symbol, interval, limit=200)
                if not df.empty and len(df) >= 51:
                    all_indicators[symbol][interval] = calculate_indicators(df, symbol, interval)
            except Exception as e: log_message(f"❌ Lỗi khi lấy dữ liệu cho {symbol}-{interval}: {e}")
    log_message("✅ Dữ liệu chung đã sẵn sàng.")

    for name, config in STRATEGY_LAB.items():
        run_strategy_session(name, config, all_indicators)

    if should_send_report():
        report_content = build_summary_report()
        send_discord_report(report_content)
        save_json_file(TIMESTAMP_FILE, {"last_report_sent": datetime.now().timestamp()})
    else:
        log_message("ℹ️ Chưa đến giờ gửi báo cáo tóm tắt.")
    log_message("====== ✅ PHIÊN GIAO DỊCH MÔ PHỎNG KẾT THÚC ✅ ======")

if __name__ == "__main__":
    main()
