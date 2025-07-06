# /root/ricealert/backtest/paper_trade.py
# -*- coding: utf-8 -*-
"""
paper_trade.py - Quản lý Danh mục Mô phỏng Thông minh (Paper Trading)
Version: 2.3 (The Adaptive Mind with Enhanced Market Insight & Reporting)
Date: 2025-07-09

Description:
Hệ thống quản lý danh mục với bộ não thích ứng và khả năng nhận diện thị trường sâu hơn.
- Bộ não chấm điểm (select_best_tactic) giờ đây sử dụng ADX, ATR, F&G, AI Confidence
  VÀ CÁC MẪU HÌNH NẾN (Doji, Engulfing, Hammer, Shooting Star) của BTC để đưa ra quyết định lối đánh.
- Mỗi lối đánh có cấu hình rủi ro riêng (SL_PCT, RR). Tỷ lệ RR sẽ được điều chỉnh
  tăng lên nếu điểm giao dịch (final_score) của Trade Advisor cao.
- Tích hợp 2 cơ chế báo cáo:
  1. Báo cáo tổng quan định kỳ (8h, 20h) KÈM BIỂU ĐỒ EQUITY CURVE.
  2. Cảnh báo biến động PnL mỗi 4 giờ nếu có thay đổi > 0.5%.
- Tự động EXPORT lịch sử giao dịch ra file CSV mỗi phiên.
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
import matplotlib.pyplot as plt # Import matplotlib để vẽ biểu đồ
# import ta # KHÔNG CẦN IMPORT TA Ở ĐÂY, ĐÃ CÓ TRONG INDICATOR.PY

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
# ==============================================================================
TACTICS_LAB = {
    "Balanced_Trader": { "NOTES": "Mặc định, cân bằng 3 yếu tố", "WEIGHTS": {'tech': 0.4, 'context': 0.2, 'ai': 0.4}, "ENTRY_SCORE": 6.5, "SL_PCT": 0.03, "RR": 2.0, "TRADE_PCT": 0.1, "ENABLE_DIP": True, "DIP_RANGE": [3.0, 4.8], "DIP_PCT": 0.05 },
    "AI_Aggressor": { "NOTES": "Khi trend mạnh, tin vào AI", "WEIGHTS": {'tech': 0.1, 'context': 0.1, 'ai': 0.8}, "ENTRY_SCORE": 7.0, "SL_PCT": 0.05, "RR": 1.8, "TRADE_PCT": 0.15, "ENABLE_DIP": False },
    "Dip_Hunter": { "NOTES": "Khi sợ hãi, chuyên bắt đáy", "WEIGHTS": {'tech': 0.5, 'context': 0.3, 'ai': 0.2}, "ENTRY_SCORE": 7.0, "SL_PCT": 0.035,"RR": 2.5, "TRADE_PCT": 0.07, "ENABLE_DIP": True, "DIP_RANGE": [2.5, 4.5], "DIP_PCT": 0.07 },
    "Cautious_Observer": { "NOTES": "Khi sideways, bảo toàn vốn", "WEIGHTS": {'tech': 0.5, 'context': 0.5, 'ai': 0.0}, "ENTRY_SCORE": 7.5, "SL_PCT": 0.025,"RR": 2.0, "TRADE_PCT": 0.08, "ENABLE_DIP": False },
    "Market_Mirror": { "NOTES": "Mô phỏng Alerter, làm baseline", "WEIGHTS": {'tech': 0.4, 'context': 0.2, 'ai': 0.4}, "ENTRY_SCORE": 6.0, "SL_PCT": 0.03, "RR": 1.8, "TRADE_PCT": 0.1, "ENABLE_DIP": True, "DIP_RANGE": [3.0, 4.8], "DIP_PCT": 0.05 },
    # Thêm các lối đánh mới tại đây nếu cần (Range_Trader, Momentum_Chaser, v.v.)
}

# --- Cài đặt chung & Báo cáo ---
INITIAL_CAPITAL = 10000.0
SYMBOLS_TO_SCAN = ["ETHUSDT", "AVAXUSDT", "INJUSDT", "LINKUSDT", "SUIUSDT", "FETUSDT", "TAOUSDT"]
INTERVALS_TO_SCAN = ["1h", "4h"] # Các interval để quét lệnh mới
ALL_TIME_FRAMES = ["1h", "4h", "1d"] # Tất cả các interval để tính chỉ báo và snapshot thị trường
VIETNAM_TZ = pytz.timezone('Asia/Ho_Chi_Minh')
PSYCHOLOGY_PNL_THRESHOLD_PERCENT = -5.0 # Ngưỡng "sợ hãi" chung cho toàn danh mục

# --- Cài đặt cho Báo cáo Biến động ---
VOLATILITY_REPORT_COOLDOWN_HOURS = 4
VOLATILITY_REPORT_PNL_THRESHOLD = 0.5 # %

# --- Cài đặt cho TP/SL Scaling dựa trên Score ---
TP_SL_SCALING_RULES = {
    "high_score_rr_multiplier": 1.2,    # Nếu score >= high_score_threshold, RR = base_RR * 1.2
    "critical_score_rr_multiplier": 1.5, # Nếu score >= critical_score_threshold, RR = base_RR * 1.5
    "high_score_threshold": 7.0,         # Ngưỡng score để áp dụng high_score_rr_multiplier
    "critical_score_threshold": 8.5      # Ngưỡng score để áp dụng critical_score_rr_multiplier
}

# --- Đường dẫn file & Webhook ---
LOG_FILE = os.path.join(PAPER_DATA_DIR, "paper_trade_log.txt")
STATE_FILE = os.path.join(PAPER_DATA_DIR, "paper_trade_state.json")
TIMESTAMP_FILE = os.path.join(PAPER_DATA_DIR, "paper_trade_timestamps.json")
TRADE_HISTORY_CSV_FILE = os.path.join(PAPER_DATA_DIR, "trade_history.csv") # File xuất lịch sử giao dịch
EQUITY_CURVE_CSV_FILE = os.path.join(PAPER_DATA_DIR, "equity_curve.csv")    # File dữ liệu đường vốn
EQUITY_CURVE_IMAGE_FILE = os.path.join(PAPER_DATA_DIR, "equity_curve.png") # File ảnh biểu đồ đường vốn

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
    log_message("🚀 Đang gửi báo cáo text đến Discord...")
    for i in range(0, len(content), 1950):
        try:
            requests.post(DISCORD_WEBHOOK_URL, json={"content": content[i:i+1950]}, timeout=10).raise_for_status()
            time.sleep(2) # Tăng sleep để tránh rate limit
        except requests.exceptions.RequestException as e:
            log_message(f"❌ Lỗi khi gửi báo cáo Discord: {e}")
            break

def send_discord_image(image_path: str, caption: str = "📊 Biểu đồ"):
    """Gửi ảnh lên Discord qua webhook."""
    if not DISCORD_WEBHOOK_URL: return
    if not os.path.exists(image_path):
        log_message(f"❌ Không tìm thấy file ảnh để gửi: {image_path}")
        return

    log_message(f"📸 Đang gửi ảnh {os.path.basename(image_path)} đến Discord...")
    try:
        with open(image_path, "rb") as f:
            files = {"file": (os.path.basename(image_path), f)}
            payload = {"content": caption}
            response = requests.post(DISCORD_WEBHOOK_URL, data=payload, files=files, timeout=15)
            response.raise_for_status()
            log_message(f"✅ Đã gửi ảnh {os.path.basename(image_path)}.")
    except requests.exceptions.RequestException as e:
        log_message(f"❌ Lỗi khi gửi ảnh lên Discord: {e}")
    except Exception as e:
        log_message(f"❌ Lỗi không xác định khi gửi ảnh: {e}")

def export_trade_history_to_csv(trade_history: List[Dict]):
    """Ghi lịch sử giao dịch vào file CSV."""
    if not trade_history:
        log_message("Không có lịch sử giao dịch để xuất CSV.")
        return

    df_history = pd.DataFrame(trade_history)
    # Sắp xếp các cột theo thứ tự dễ đọc
    columns_order = [
        "trade_id", "symbol", "interval", "status", "opened_by_tactic", "trade_type",
        "entry_price", "exit_price", "tp", "sl", "amount_usd",
        "pnl_usd", "pnl_percent", "entry_time", "exit_time", "entry_score"
    ]
    # Chỉ giữ lại các cột có trong dữ liệu
    df_history = df_history[[col for col in columns_order if col in df_history.columns]]

    # Kiểm tra nếu file tồn tại để quyết định có ghi header hay không
    file_exists = os.path.exists(TRADE_HISTORY_CSV_FILE)
    mode = 'a' if file_exists else 'w'
    header = not file_exists

    try:
        df_history.to_csv(TRADE_HISTORY_CSV_FILE, mode=mode, header=header, index=False, encoding="utf-8")
        log_message(f"✅ Đã xuất lịch sử giao dịch vào {TRADE_HISTORY_CSV_FILE}")
    except Exception as e:
        log_message(f"❌ Lỗi khi xuất lịch sử giao dịch ra CSV: {e}")

def log_equity_point(capital: float):
    """Ghi một điểm vốn vào file equity_curve.csv."""
    now_str = datetime.now(VIETNAM_TZ).strftime("%Y-%m-%d %H:%M:%S")

    file_exists = os.path.exists(EQUITY_CURVE_CSV_FILE)
    mode = 'a' if file_exists else 'w'
    header = not file_exists # Ghi header chỉ lần đầu

    try:
        with open(EQUITY_CURVE_CSV_FILE, mode, encoding="utf-8") as f:
            if header:
                f.write("timestamp,capital\n")
            f.write(f"{now_str},{capital:.2f}\n")
        log_message(f"✅ Đã ghi điểm vốn: {capital:,.2f}")
    except Exception as e:
        log_message(f"❌ Lỗi khi ghi điểm vốn vào CSV: {e}")

def plot_equity_curve(image_path: str = EQUITY_CURVE_IMAGE_FILE):
    """Vẽ biểu đồ Equity Curve và lưu thành ảnh."""
    try:
        df_equity = pd.read_csv(EQUITY_CURVE_CSV_FILE, names=["timestamp", "capital"], header=0) # header=0 vì chúng ta ghi header ở log_equity_point
        df_equity["timestamp"] = pd.to_datetime(df_equity["timestamp"])

        plt.figure(figsize=(12, 6)) # Kích thước lớn hơn cho biểu đồ rõ ràng
        plt.plot(df_equity["timestamp"], df_equity["capital"], linewidth=2, color='skyblue')
        plt.title("📈 Đường Vốn Danh Mục (Equity Curve)", fontsize=16)
        plt.xlabel("Thời gian", fontsize=12)
        plt.ylabel("Vốn ($)", fontsize=12)
        plt.grid(True, linestyle='--', alpha=0.7)
        plt.xticks(rotation=45, ha='right') # Xoay nhãn trục x để dễ đọc
        plt.tick_params(axis='x', labelsize=10)
        plt.tick_params(axis='y', labelsize=10)
        plt.tight_layout() # Đảm bảo mọi thứ vừa vặn trong figure
        plt.savefig(image_path, dpi=100) # Lưu ảnh với DPI cao hơn để rõ nét
        plt.close() # Đóng figure để giải phóng bộ nhớ
        log_message(f"✅ Đã vẽ và lưu biểu đồ vốn tại {image_path}")
    except FileNotFoundError:
        log_message(f"⚠️ File dữ liệu vốn không tìm thấy: {EQUITY_CURVE_CSV_FILE}. Không thể vẽ biểu đồ.")
    except Exception as e:
        log_message(f"❌ Lỗi khi vẽ biểu đồ Equity Curve: {e}")

# ==============================================================================
# ============ 🧠 BỘ NÃO THÍCH ỨNG: CHỌN LỐI ĐÁNH 🧠 =============
# ==============================================================================
def select_best_tactic(market_snapshot: Dict) -> str:
    """
    Chấm điểm và chọn ra lối đánh tốt nhất dựa trên ảnh chụp thị trường.
    Đây là bộ não của hệ thống, thay thế cho logic if/else đơn giản.
    """
    tactic_scores = {tactic: 0 for tactic in TACTICS_LAB}

    # --- Trích xuất dữ liệu thị trường từ Snapshot ---
    fg_index = market_snapshot.get("fear_greed", 50)
    btc_d1_trend = market_snapshot.get("btc_d1_trend", "sideway")
    btc_d1_adx = market_snapshot.get("btc_d1_adx", 20.0)
    btc_d1_atr_pct = market_snapshot.get("btc_d1_atr_percent", 1.5)
    btc_h4_ai_score = market_snapshot.get("btc_h4_ai_score", 5.0)
    btc_d1_doji_type = market_snapshot.get("btc_d1_doji_type", "none")
    btc_d1_candle_pattern = market_snapshot.get("btc_d1_candle_pattern", "none")

    log_message(f"Snapshot Thị trường: F&G={fg_index}, BTC Trend={btc_d1_trend}, ADX={btc_d1_adx:.2f}, ATR%={btc_d1_atr_pct:.2f}, AI Score (BTC)={btc_h4_ai_score:.2f}, Doji={btc_d1_doji_type}, Pattern={btc_d1_candle_pattern}")

    # --- Các luật chấm điểm (Rules Engine) ---

    # 1. Dựa vào Sức mạnh Trend (ADX) và Hướng Trend
    if btc_d1_adx > 28 and btc_d1_trend == "uptrend":
        tactic_scores["AI_Aggressor"] += 3
        tactic_scores["Balanced_Trader"] += 1
        tactic_scores["Cautious_Observer"] -= 2
    elif btc_d1_adx > 28 and btc_d1_trend == "downtrend":
        tactic_scores["Dip_Hunter"] += 2 # Mạnh dạn bắt đáy khi trend giảm rõ rệt
        tactic_scores["Cautious_Observer"] -= 1 # Tránh quá thận trọng khi có cơ hội
        tactic_scores["AI_Aggressor"] -= 2 # Tránh theo AI vào trend giảm
    elif btc_d1_adx < 20: # Sideway, trend yếu
        tactic_scores["Cautious_Observer"] += 3
        tactic_scores["Balanced_Trader"] += 1
        tactic_scores["AI_Aggressor"] -= 2
        tactic_scores["Dip_Hunter"] += 1 # Sideway dễ có false break/rút chân để bắt dip

    # 2. Dựa vào Tâm lý Thị trường (Fear & Greed Index)
    if fg_index > 75: # Tham lam tột độ
        tactic_scores["AI_Aggressor"] += 2
        tactic_scores["Market_Mirror"] += 1 # Nếu thị trường quá hưng phấn, hãy theo sát
        tactic_scores["Dip_Hunter"] -= 1 # Không bắt đáy khi mọi người đang FOMO
    elif fg_index < 25: # Sợ hãi tột độ
        tactic_scores["Dip_Hunter"] += 3
        tactic_scores["Cautious_Observer"] += 1
        tactic_scores["AI_Aggressor"] -= 1 # Không theo AI nếu nó có vẻ tích cực giữa lúc sợ hãi

    # 3. Dựa vào Độ biến động (ATR)
    if btc_d1_atr_pct > 4.0: # Biến động rất mạnh
        tactic_scores["Dip_Hunter"] += 2 # Nhiều cơ hội cho Dip Hunter
        tactic_scores["AI_Aggressor"] += 1 # Nếu AI đúng, lợi nhuận lớn
        tactic_scores["Cautious_Observer"] -= 2 # Không phù hợp với thị trường biến động
    elif btc_d1_atr_pct < 1.5: # Thị trường ảm đạm
        tactic_scores["Cautious_Observer"] += 2
        tactic_scores["AI_Aggressor"] -= 1

    # 4. Dựa vào Sự tự tin của AI (Insight từ backtest) - YẾU TỐ QUAN TRỌNG
    if btc_h4_ai_score > 7.5:
        tactic_scores["AI_Aggressor"] += 4 # Thưởng lớn khi AI rất tự tin
        tactic_scores["Balanced_Trader"] += 1
    elif btc_h4_ai_score < 4.0:
        tactic_scores["AI_Aggressor"] -= 2
        tactic_scores["Cautious_Observer"] += 1
        tactic_scores["Dip_Hunter"] += 0.5 # Nếu AI không tự tin, thị trường có thể đảo chiều bất ngờ

    # 5. Dựa vào Mẫu hình Nến (BTC 1D)
    if btc_d1_doji_type == "dragonfly" and btc_d1_trend == "downtrend":
        tactic_scores["Dip_Hunter"] += 2.5 # Dấu hiệu đảo chiều đáy mạnh mẽ
        tactic_scores["Balanced_Trader"] += 1
    elif btc_d1_doji_type == "gravestone" and btc_d1_trend == "uptrend":
        tactic_scores["Cautious_Observer"] += 2 # Dấu hiệu đảo chiều đỉnh mạnh mẽ
        tactic_scores["AI_Aggressor"] -= 1
    elif btc_d1_candle_pattern == "bullish_engulfing" and btc_d1_trend == "downtrend":
        tactic_scores["Dip_Hunter"] += 2
        tactic_scores["Balanced_Trader"] += 1
    elif btc_d1_candle_pattern == "bearish_engulfing" and btc_d1_trend == "uptrend":
        tactic_scores["Cautious_Observer"] += 1.5
        tactic_scores["AI_Aggressor"] -= 1
    elif btc_d1_doji_type == "common" or btc_d1_doji_type == "long_legged": # Thị trường lưỡng lự
        tactic_scores["Cautious_Observer"] += 1
        tactic_scores["Balanced_Trader"] += 0.5


    # Luôn cho Balanced_Trader một điểm nền để làm lựa chọn an toàn khi không có lựa chọn rõ ràng
    tactic_scores["Balanced_Trader"] += 1

    log_message(f"Chấm điểm lối đánh: {tactic_scores}")

    # Chọn lối đánh có điểm cao nhất
    best_tactic = max(tactic_scores, key=tactic_scores.get)
    log_message(f"🏆 Lối đánh chiến thắng: [{best_tactic}] với số điểm {tactic_scores[best_tactic]}")

    return best_tactic

def apply_portfolio_psychology(tactic_config: Dict, portfolio_state: Dict) -> Dict:
    """Điều chỉnh thông số của lối đánh dựa trên PnL tổng."""
    # Tránh chia cho 0 nếu INITIAL_CAPITAL là 0
    pnl_percent = (portfolio_state['capital'] - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100 if INITIAL_CAPITAL > 0 else 0

    effective_config = tactic_config.copy()

    if pnl_percent < PSYCHOLOGY_PNL_THRESHOLD_PERCENT:
        effective_config["TRADE_PCT"] /= 2  # Giảm rủi ro đi một nửa
        effective_config["ENTRY_SCORE"] += 0.5 # Kén chọn hơn
        log_message(f"😨 Tâm lý Sợ hãi kích hoạt! (PnL: {pnl_percent:.2f}%) -> Giảm rủi ro, tăng ngưỡng điểm.")

    return effective_config

def run_paper_trade_session():
    # 1. Tải trạng thái danh mục & Lấy dữ liệu mới
    portfolio_state = load_json_file(STATE_FILE)
    if not portfolio_state:
        portfolio_state = {"capital": INITIAL_CAPITAL, "active_trades": [], "trade_history": []}
        # Đảm bảo last_capital cho volatility report được khởi tạo
        timestamps = load_json_file(TIMESTAMP_FILE, {})
        timestamps["capital_at_last_volatility_report"] = INITIAL_CAPITAL
        save_json_file(TIMESTAMP_FILE, timestamps)


    all_indicators = {}
    # Luôn lấy dữ liệu BTC trên 1D và 4H cho Market Snapshot
    all_symbols_to_fetch = SYMBOLS_TO_SCAN + ["BTCUSDT"]
    # Luôn lấy 1h, 4h, 1d cho tất cả các symbol để đảm bảo đủ dữ liệu cho Trade Advisor và Market Snapshot
    
    for symbol in all_symbols_to_fetch:
        all_indicators[symbol] = {}
        for interval in ALL_TIME_FRAMES: # Sử dụng ALL_TIME_FRAMES
            try:
                df = get_price_data(symbol, interval, limit=200)
                # calculate_indicators đã tự xử lý trường hợp thiếu dữ liệu và trả về dict mặc định
                calculated_data = calculate_indicators(df, symbol, interval)
                all_indicators[symbol][interval] = calculated_data
                if calculated_data.get("reason"): # Nếu có cảnh báo thiếu dữ liệu từ indicator
                    log_message(f"⚠️ {calculated_data['reason']} cho {symbol}-{interval}. Sử dụng dữ liệu mặc định.")
            except Exception as e:
                log_message(f"❌ Lỗi khi tính chỉ báo cho {symbol}-{interval}: {e}")
                # Đảm bảo vẫn có entry trống để tránh lỗi KeyError sau này
                all_indicators[symbol][interval] = {"price": 0, "closed_candle_price": 0, "rsi_14": 50.0, "trend": "sideway", "adx": 20.0, "atr_percent": 1.5, "doji_type": "none", "candle_pattern": "none"}


    # BỔ SUNG: Làm giàu dữ liệu chỉ báo với RSI đa khung thời gian cho tất cả các symbol
    # Điều này cần được thực hiện SAU KHI TẤT CẢ all_indicators đã được populate từ get_price_data và calculate_indicators
    log_message("\nĐang làm giàu dữ liệu chỉ báo với RSI đa khung thời gian...")
    for sym_enrich in all_symbols_to_fetch:
        rsi_h1 = all_indicators.get(sym_enrich, {}).get("1h", {}).get("rsi_14", 50)
        rsi_h4 = all_indicators.get(sym_enrich, {}).get("4h", {}).get("rsi_14", 50)
        rsi_d1 = all_indicators.get(sym_enrich, {}).get("1d", {}).get("rsi_14", 50)
        for itv_enrich in ALL_TIME_FRAMES:
            if all_indicators.get(sym_enrich, {}).get(itv_enrich):
                all_indicators[sym_enrich][itv_enrich]['rsi_1h'] = rsi_h1
                all_indicators[sym_enrich][itv_enrich]['rsi_4h'] = rsi_h4
                all_indicators[sym_enrich][itv_enrich]['rsi_1d'] = rsi_d1
    log_message("✅ Hoàn thành làm giàu dữ liệu chỉ báo.")


    # 2. Đóng các lệnh cũ
    trades_to_remove = []
    closed_this_session = False
    for trade in portfolio_state["active_trades"]:
        # Kiểm tra dữ liệu hiện tại của symbol/interval của lệnh
        current_data = all_indicators.get(trade["symbol"], {}).get(trade["interval"])
        if not current_data or current_data.get('price', 0) == 0:
            log_message(f"⚠️ Không có dữ liệu hiện tại (live price) cho lệnh {trade['symbol']}-{trade['interval']}. Bỏ qua kiểm tra đóng lệnh.")
            continue

        current_price = current_data['price'] # Sử dụng live price để kiểm tra SL/TP
        status, exit_price = (None, None)

        # Kiểm tra SL/TP
        if current_price <= trade["sl"]: status, exit_price = "SL_HIT", trade["sl"]
        elif current_price >= trade["tp"]: status, exit_price = "TP_HIT", trade["tp"]

        if status:
            pnl_percent = (exit_price - trade["entry_price"]) / trade["entry_price"]
            pnl_usd = trade["amount_usd"] * pnl_percent
            portfolio_state["capital"] += pnl_usd
            trade.update({"status": status, "exit_price": exit_price, "exit_time": datetime.now(VIETNAM_TZ).isoformat(), "pnl_percent": pnl_percent * 100, "pnl_usd": pnl_usd})
            portfolio_state["trade_history"].append(trade)
            trades_to_remove.append(trade)
            closed_this_session = True
            log_message(f"{'✅' if pnl_usd >= 0 else '❌'} Lệnh Đóng: {trade['symbol']} ({trade['opened_by_tactic']}) | {status} | PnL: ${pnl_usd:,.2f}")

    if trades_to_remove:
        portfolio_state["active_trades"] = [t for t in portfolio_state["active_trades"] if t not in trades_to_remove]
        # Giới hạn lịch sử giao dịch để không làm file quá lớn (ví dụ: 1000 lệnh gần nhất)
        portfolio_state["trade_history"] = sorted(portfolio_state["trade_history"], key=lambda x: x.get('exit_time', ''), reverse=True)[:1000]


    # 3. Tư duy và Hành động với Bộ não mới
    # 3.1. Tạo ảnh chụp thị trường (Market Snapshot)
    market_context_path = os.path.join(PROJECT_ROOT, "ricenews/lognew/market_context.json")
    market_context = load_json_file(market_context_path)

    # Lấy chỉ báo BTC trên 1D và 4H cho market snapshot
    btc_d1_indicators = all_indicators.get("BTCUSDT", {}).get("1d", {})
    btc_h4_indicators = all_indicators.get("BTCUSDT", {}).get("4h", {})

    # Để lấy AI score của BTC, cần chạy Trade Advisor trên BTC H4
    # indicators_for_advisor đã được làm giàu RSI đa khung thời gian ở trên
    btc_h4_advisor_input = btc_h4_indicators.copy()
    btc_h4_advisor_input['price'] = btc_h4_indicators.get('closed_candle_price', btc_h4_indicators.get('price', 0))

    # KHÔNG CẦN THÊM DÒNG NÀY NỮA VÌ ĐÃ LÀM GIÀU Ở TRÊN
    # for tf in ["1h", "4h", "1d"]:
    #     df_rsi = get_price_data("BTCUSDT", tf)
    #     if not df_rsi.empty and len(df_rsi) >= 20:
    #         btc_h4_advisor_input[f"rsi_{tf}"] = round(ta.momentum.rsi(df_rsi["close"], window=14).iloc[-2], 2)
    #     else:
    #         btc_h4_advisor_input[f"rsi_{tf}"] = 50.0

    btc_h4_advisor_decision = {}
    if btc_h4_advisor_input.get('price', 0) != 0 and not btc_h4_indicators.get('reason'):
        btc_h4_advisor_decision = get_advisor_decision("BTCUSDT", "4h", btc_h4_advisor_input, ADVISOR_BASE_CONFIG)

    market_snapshot = {
        "fear_greed": market_context.get("fear_greed", 50),
        "btc_d1_trend": btc_d1_indicators.get("trend", "sideway"),
        "btc_d1_adx": btc_d1_indicators.get("adx", 20.0),
        "btc_d1_atr_percent": btc_d1_indicators.get("atr_percent", 1.5),
        "btc_h4_ai_score": btc_h4_advisor_decision.get("final_score", 5.0),
        "btc_d1_doji_type": btc_d1_indicators.get("doji_type", "none"),
        "btc_d1_candle_pattern": btc_d1_indicators.get("candle_pattern", "none"),
    }

    # 3.2. Chọn lối đánh tốt nhất
    selected_tactic_name = select_best_tactic(market_snapshot)
    base_tactic_config = TACTICS_LAB[selected_tactic_name]

    # 3.3. Áp dụng tâm lý lên lối đánh đã chọn
    effective_tactic = apply_portfolio_psychology(base_tactic_config, portfolio_state)

    # 4. Quét lệnh mới với lối đánh đã chọn
    opened_this_session = False
    for symbol in SYMBOLS_TO_SCAN:
        # Bỏ qua nếu đã có lệnh mở với symbol này
        if any(t['symbol'] == symbol for t in portfolio_state['active_trades']): continue

        for interval in INTERVALS_TO_SCAN: # Chỉ quét các interval đã cấu hình để mở lệnh
            # Lấy chỉ báo của nến ĐÃ ĐÓNG cho quyết định của Trade Advisor
            # và giá live cho entry
            current_symbol_indicators = all_indicators.get(symbol, {}).get(interval)

            # Nếu không có dữ liệu hoặc dữ liệu không đủ để Trade Advisor xử lý
            if not current_symbol_indicators or current_symbol_indicators.get('reason'):
                log_message(f"⚠️ Bỏ qua {symbol}-{interval}. Dữ liệu chỉ báo không đủ hoặc không hợp lệ: {current_symbol_indicators.get('reason', 'Không rõ lý do')}.")
                continue

            # Trade Advisor cần các chỉ báo của nến ĐÃ ĐÓNG (closed_candle_price)
            # Ta sẽ tạo một bản sao và điều chỉnh để phù hợp với Trade Advisor
            indicators_for_advisor = current_symbol_indicators.copy()
            indicators_for_advisor['price'] = current_symbol_indicators.get('closed_candle_price', current_symbol_indicators.get('price', 0))
            if indicators_for_advisor['price'] == 0: # Giá nến đóng không hợp lệ
                log_message(f"⚠️ Bỏ qua {symbol}-{interval}. Giá nến đóng để tính advisor score là 0.")
                continue


            # KHÔNG CẦN THÊM DÒNG NÀY NỮA VÌ ĐÃ LÀM GIÀU Ở TRÊN
            # Bổ sung RSI đa khung thời gian cho altcoin (rsi_1h, rsi_4h, rsi_1d)
            # for tf_alt in ["1h", "4h", "1d"]:
            #     df_rsi_alt = get_price_data(symbol, tf_alt)
            #     if not df_rsi_alt.empty and len(df_rsi_alt) >= 20:
            #         indicators_for_advisor[f"rsi_{tf_alt}"] = round(ta.momentum.rsi(df_rsi_alt["close"], window=14).iloc[-2], 2)
            #     else:
            #         indicators_for_advisor[f"rsi_{tf_alt}"] = 50.0

            decision = get_advisor_decision(
                symbol, interval, indicators_for_advisor, ADVISOR_BASE_CONFIG,
                weights_override=effective_tactic["WEIGHTS"]
            )
            final_score = decision.get("final_score", 0.0)

            trade_type, amount_percent = None, 0.0
            if final_score >= effective_tactic["ENTRY_SCORE"]:
                trade_type = "TREND_FOLLOW"
                amount_percent = effective_tactic["TRADE_PCT"]
            elif effective_tactic.get("ENABLE_DIP", False):
                score_min, score_max = effective_tactic["DIP_RANGE"]
                if score_min <= final_score < score_max:
                    # Tận dụng doji_type và candle_pattern đã có từ indicator.py (từ nến đã đóng)
                    if (indicators_for_advisor.get('rsi_divergence') == 'bullish' or
                        indicators_for_advisor.get('doji_type') == 'dragonfly' or
                        indicators_for_advisor.get('candle_pattern') == 'hammer' or
                        indicators_for_advisor.get('candle_pattern') == 'bullish_engulfing'):
                        trade_type = "DIP_BUY"
                        amount_percent = effective_tactic["DIP_PCT"]

            if trade_type:
                # Giá vào lệnh phải là giá live hiện tại
                entry_price = current_symbol_indicators['price']
                amount_usd = portfolio_state['capital'] * amount_percent
                if amount_usd > portfolio_state['capital'] or amount_usd < 10: # Đảm bảo không quá vốn và đủ lớn
                    log_message(f"⚠️ Số tiền giao dịch quá nhỏ hoặc vượt vốn (${amount_usd:,.2f}). Bỏ qua lệnh cho {symbol}.")
                    continue
                if entry_price == 0: # Đảm bảo giá entry không phải 0
                    log_message(f"⚠️ Giá vào lệnh cho {symbol} là 0. Bỏ qua lệnh.")
                    continue


                # === LOGIC TÍNH TP/SL DỰA TRÊN FINAL_SCORE & TACTIC'S BASE RR ===
                base_rr = effective_tactic["RR"]
                calculated_rr = base_rr

                # Áp dụng multiplier nếu score đủ cao
                if final_score >= TP_SL_SCALING_RULES["critical_score_threshold"]:
                    calculated_rr = base_rr * TP_SL_SCALING_RULES["critical_score_rr_multiplier"]
                    log_message(f"📈 Critical Score RR kích hoạt! ({final_score:.2f} >= {TP_SL_SCALING_RULES['critical_score_threshold']}) -> RR tăng lên {calculated_rr:.2f}")
                elif final_score >= TP_SL_SCALING_RULES["high_score_threshold"]:
                    calculated_rr = base_rr * TP_SL_SCALING_RULES["high_score_rr_multiplier"]
                    log_message(f"📊 High Score RR kích hoạt! ({final_score:.2f} >= {TP_SL_SCALING_RULES['high_score_threshold']}) -> RR tăng lên {calculated_rr:.2f}")

                sl_price = entry_price * (1 - effective_tactic["SL_PCT"])
                tp_price = entry_price * (1 + effective_tactic["SL_PCT"] * calculated_rr)

                # Làm tròn TP/SL để tránh số quá dài
                tp_price = round(tp_price, 8)
                sl_price = round(sl_price, 8)

                # Đảm bảo TP > Entry > SL (cho lệnh mua)
                if tp_price <= entry_price or sl_price >= entry_price:
                    log_message(f"⚠️ TP ({tp_price}) hoặc SL ({sl_price}) không hợp lệ so với Entry ({entry_price}). Bỏ qua lệnh cho {symbol}.")
                    continue
                # ======================================================

                new_trade = {
                    "trade_id": str(uuid.uuid4()), "symbol": symbol, "interval": interval,
                    "status": "ACTIVE", "opened_by_tactic": selected_tactic_name,
                    "trade_type": trade_type, "entry_price": entry_price,
                    "tp": tp_price, "sl": sl_price, "amount_usd": amount_usd,
                    "entry_time": datetime.now(VIETNAM_TZ).isoformat(), "entry_score": final_score
                }
                portfolio_state["capital"] -= amount_usd # Trừ vốn khi mở lệnh
                portfolio_state["active_trades"].append(new_trade)
                opened_this_session = True

                log_icon = "🔥" if trade_type == "TREND_FOLLOW" else "💡"
                log_message(f"{log_icon} Lệnh Mới ({selected_tactic_name}/{trade_type}): {symbol} | Score: {final_score:.2f} | Entry: {entry_price:.4f} | TP: {tp_price:.4f} | SL: {sl_price:.4f} | Amount: ${amount_usd:,.2f}")
                break # Chỉ mở 1 lệnh mới mỗi phiên quét
        if opened_this_session: break # Chỉ mở 1 lệnh mới mỗi phiên quét

    # 5. Lưu trạng thái, ghi log vốn và xuất lịch sử giao dịch
    log_message(f"💰 Vốn Hiện Tại: ${portfolio_state['capital']:,.2f} | Lệnh Mở: {len(portfolio_state['active_trades'])}")
    save_json_file(STATE_FILE, portfolio_state)
    export_trade_history_to_csv(portfolio_state['trade_history']) # Xuất lịch sử giao dịch
    log_equity_point(portfolio_state['capital']) # Ghi điểm vốn hiện tại

    # 6. Logic gửi báo cáo (Cả 2 loại)
    # 6.1 Báo cáo tổng quan hàng ngày (8h, 20h)
    if should_send_daily_summary():
        report_content = build_daily_summary_report(portfolio_state, all_indicators) # TRUYỀN all_indicators
        send_discord_report(report_content)

        # Vẽ và gửi biểu đồ Equity Curve kèm báo cáo hàng ngày
        plot_equity_curve(EQUITY_CURVE_IMAGE_FILE)
        send_discord_image(EQUITY_CURVE_IMAGE_FILE, "📊 **Cập nhật Đường Vốn (Equity Curve)**")

        timestamps = load_json_file(TIMESTAMP_FILE, {})
        # Cập nhật timestamp theo mốc giờ đã gửi
        timestamps["last_daily_report_time_slot"] = datetime.now(VIETNAM_TZ).strftime("%Y-%m-%d-%H")
        save_json_file(TIMESTAMP_FILE, timestamps)

    # 6.2 Cảnh báo biến động (Mỗi 4h nếu PnL thay đổi > 0.5%)
    should_send, pnl_change_pct = should_send_volatility_report(portfolio_state)
    if should_send:
        report_content = build_volatility_report(portfolio_state, pnl_change_pct, all_indicators) # TRUYỀN all_indicators
        send_discord_report(report_content)
        timestamps = load_json_file(TIMESTAMP_FILE, {})
        timestamps["last_volatility_report_sent"] = datetime.now().timestamp()
        timestamps["capital_at_last_volatility_report"] = portfolio_state['capital']
        save_json_file(TIMESTAMP_FILE, timestamps)

# ==============================================================================
# ======================== BÁO CÁO & ĐIỀU KIỆN GỬI =========================
# ==============================================================================

def should_send_daily_summary() -> bool:
    """Kiểm tra xem có nên gửi báo cáo tóm tắt hàng ngày không."""
    now_vn = datetime.now(VIETNAM_TZ)
    timestamps = load_json_file(TIMESTAMP_FILE, {"last_daily_report_time_slot": ""}) # Lưu dạng "YYYY-MM-DD-HH"

    current_time_slot = now_vn.strftime("%Y-%m-%d-%H")
    last_sent_time_slot = timestamps.get("last_daily_report_time_slot", "")

    # Chỉ gửi nếu hiện tại là 8h hoặc 20h và chưa gửi cho mốc thời gian này hôm nay
    if now_vn.hour == 8 and current_time_slot != last_sent_time_slot:
        return True
    elif now_vn.hour == 20 and current_time_slot != last_sent_time_slot:
        return True
    return False

def build_daily_summary_report(state: Dict, all_indicators: Dict) -> str: # BỔ SUNG THAM SỐ all_indicators
    """Xây dựng báo cáo tóm tắt hàng ngày cho danh mục."""
    now_vn = datetime.now(VIETNAM_TZ)
    if not state: return "Chưa có dữ liệu danh mục để báo cáo."

    capital = state.get('capital', INITIAL_CAPITAL)
    pnl_usd = capital - INITIAL_CAPITAL
    pnl_percent = (pnl_usd / INITIAL_CAPITAL) * 100 if INITIAL_CAPITAL > 0 else 0
    pnl_icon = "📈" if pnl_usd >= 0 else "📉"

    report_lines = [f"📊 **Báo Cáo Tổng Quan - {now_vn.strftime('%H:%M %d-%m-%Y')}** 📊\n"]
    report_lines.append(f"--- **`Tổng Quan`** ---")
    report_lines.append(f"{pnl_icon} **Vốn:** `${capital:,.2f}` | **PnL:** `${pnl_usd:,.2f}` (`{pnl_percent:+.2f}%`)")

    active_trades = state.get('active_trades', [])
    report_lines.append(f"  **Lệnh đang mở ({len(active_trades)}):**")
    if active_trades:
        for trade in active_trades:
            entry_time = datetime.fromisoformat(trade['entry_time']).astimezone(VIETNAM_TZ)
            held_hours = (datetime.now(VIETNAM_TZ) - entry_time).total_seconds() / 3600

            # Ước tính PnL hiện tại nếu có live price trong all_indicators
            # SỬ DỤNG THAM SỐ all_indicators
            current_price_info = all_indicators.get(trade['symbol'], {}).get(trade['interval'])
            current_live_price = current_price_info.get('price') if current_price_info else None

            current_pnl_str = "N/A"
            if current_live_price and trade['entry_price'] > 0:
                current_pnl_pct = (current_live_price - trade['entry_price']) / trade['entry_price'] * 100
                current_pnl_usd = trade['amount_usd'] * (current_live_price - trade['entry_price']) / trade['entry_price']
                current_pnl_str = f"PnL: `${current_pnl_usd:,.2f}` (`{current_pnl_pct:+.2f}%`)"

            report_lines.append(f"  - `{trade['symbol']}` ({trade['trade_type']}) | Tactic: `{trade['opened_by_tactic']}` | Giữ: `{held_hours:.1f}h` | {current_pnl_str}")
    else:
        report_lines.append("  -> `Không có lệnh nào đang mở.`")
    return "\n".join(report_lines)

def should_send_volatility_report(current_state: Dict) -> Tuple[bool, float]:
    """Kiểm tra xem có nên gửi cảnh báo biến động không."""
    timestamps = load_json_file(TIMESTAMP_FILE, {})
    last_report_ts = timestamps.get("last_volatility_report_sent", 0)

    # Cooldown 4 tiếng
    if (datetime.now().timestamp() - last_report_ts) < VOLATILITY_REPORT_COOLDOWN_HOURS * 3600:
        return False, 0

    last_check_capital = timestamps.get("capital_at_last_volatility_report", INITIAL_CAPITAL)
    current_capital = current_state['capital']

    # Nếu lần đầu chạy hoặc vốn không đủ để tính %
    if last_check_capital == 0 or INITIAL_CAPITAL == 0:
        # Đặt lại giá trị ban đầu nếu chưa có để bắt đầu theo dõi
        timestamps["capital_at_last_volatility_report"] = current_capital
        save_json_file(TIMESTAMP_FILE, timestamps)
        return False, 0

    pnl_change_percent = ((current_capital - last_check_capital) / last_check_capital) * 100

    # Gửi nếu có biến động vốn đáng kể
    if abs(pnl_change_percent) >= VOLATILITY_REPORT_PNL_THRESHOLD:
        return True, pnl_change_percent

    return False, 0

def build_volatility_report(state: Dict, pnl_change: float, all_indicators: Dict) -> str: # BỔ SUNG THAM SỐ all_indicators
    """Xây dựng báo cáo cảnh báo biến động."""
    capital = state.get('capital', INITIAL_CAPITAL)
    pnl_icon = "📈" if pnl_change >= 0 else "📉"

    report_lines = [f"⚡ **Cập nhật Biến động Danh mục ({VOLATILITY_REPORT_COOLDOWN_HOURS}H)** ⚡\n"]
    report_lines.append(f"{pnl_icon} **PnL thay đổi:** `{pnl_change:+.2f}%` | **Vốn hiện tại:** `${capital:,.2f}`")

    # 5 lệnh đóng gần nhất (sắp xếp theo thời gian đóng lệnh mới nhất)
    trade_history = sorted(state.get('trade_history', []), key=lambda x: x.get('exit_time', ''), reverse=True)
    if trade_history:
        report_lines.append(f"\n**5 Lệnh đóng gần nhất:**")
        for trade in trade_history[:5]:
            icon = '✅' if trade['pnl_usd'] >= 0 else '❌'
            report_lines.append(f"{icon} `{trade['symbol']}` ({trade['trade_type']}) | PnL: `${trade['pnl_usd']:,.2f}` (`{trade['pnl_percent']:.2f}%`)")
    else:
        report_lines.append(f"\n`Không có lệnh nào được đóng gần đây.`")


    # 5 lệnh mở gần nhất (sắp xếp theo thời gian mở lệnh mới nhất)
    active_trades = sorted(state.get('active_trades', []), key=lambda x: x.get('entry_time', ''), reverse=True)
    if active_trades:
        report_lines.append(f"\n**5 Lệnh mở gần nhất:**")
        for trade in active_trades[:5]:
            icon = "🔥" if trade['trade_type'] == "TREND_FOLLOW" else "💡"
            
            # Ước tính PnL hiện tại cho lệnh đang mở
            current_price_info = all_indicators.get(trade['symbol'], {}).get(trade['interval'])
            current_live_price = current_price_info.get('price') if current_price_info else None
            
            current_pnl_str = "N/A"
            if current_live_price and trade['entry_price'] > 0:
                current_pnl_pct = (current_live_price - trade['entry_price']) / trade['entry_price'] * 100
                current_pnl_usd = trade['amount_usd'] * (current_live_price - trade['entry_price']) / trade['entry_price']
                current_pnl_str = f"PnL: `${current_pnl_usd:,.2f}` (`{current_pnl_pct:+.2f}%`)"
            
            report_lines.append(f"{icon} `{trade['symbol']}` ({trade['opened_by_tactic']}/{trade['trade_type']}) | {current_pnl_str}")
    else:
        report_lines.append(f"\n`Không có lệnh nào được mở gần đây.`")

    return "\n".join(report_lines)

if __name__ == "__main__":
    log_message("====== 🚀 QUẢN LÝ DANH MỤC (PAPER TRADE) BẮT ĐẦU PHIÊN LÀM VIỆC 🚀 ======")
    # all_indicators sẽ được populate trong run_paper_trade_session
    # và được truyền vào các hàm báo cáo.
    run_paper_trade_session()
    log_message("====== ✅ QUẢN LÝ DANH MỤC (PAPER TRADE) KẾT THÚC PHIÊN LÀM VIỆC ✅ ======")
