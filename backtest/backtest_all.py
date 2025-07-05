# /root/ricealert/backtest/backtest_intelligent_trader.py
# CHIẾN LƯỢC: INTELLIGENT TRADER - GIAO DỊCH THÔNG MINH
# Triết lý: Thích ứng, quản lý rủi ro theo PNL, đa chiến lược, tối ưu hóa lợi nhuận.

import os, sys, pandas as pd, joblib, warnings, json, ta
from datetime import datetime
from typing import Dict, List

# --- Thiết lập đường dẫn & Import ---
current_dir, project_root = os.path.dirname(os.path.abspath(__file__)), os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)
warnings.filterwarnings("ignore", category=UserWarning)
from trainer import get_full_price_history, add_features

# ==============================================================================
# =================== ⚙️ CẤU HÌNH TRADER THÔNG MINH ⚙️ =====================
# ==============================================================================
TRADER_CONFIG = {
    "NOTES": "Intelligent Trader: Context, PNL-based Risk, Multi-Strategy, Trailing Stop.",
    "WEIGHTS": {'tech': 0.40, 'ai': 0.35, 'context': 0.25},
    # Ngưỡng cho Trailing Stop
    "TRAILING_STOP_ACTIVATE_PERCENT": 0.03, # Kích hoạt khi lãi 3%
    "TRAILING_STOP_DISTANCE_PERCENT": 0.02, # Đặt SL cách đỉnh mới 2%
}
# --- Các hằng số Backtest ---
SYMBOLS_TO_TEST = ["ETHUSDT", "AVAXUSDT", "LINKUSDT", "SUIUSDT", "TAOUSDT", "INJUSDT"]
INTERVAL, TOTAL_DAYS_TO_TEST = "1h", 90
INITIAL_CAPITAL, MAX_ACTIVE_TRADES, BASE_TRADE_AMOUNT_PERCENT, COMMISSION_RATE = 10000.0, 5, 0.1, 0.0004
CACHE_DIR, DATA_DIR = os.path.join(current_dir, "data_cache"), os.path.join(project_root, "data")
os.makedirs(CACHE_DIR, exist_ok=True)

# (Hàm load_all_historical_data, load_all_ai_models giữ nguyên)
def load_all_historical_data(symbols, interval, days):
    # ... (Giống file Sniper) ...
    all_data = {}
    for symbol in symbols:
        #... (Tải dữ liệu và thêm 'ema_200', 'bb_bbw' (Bollinger Band Width))
    return all_data

def load_all_ai_models(symbols, interval):
    # ... (Giống file Sniper) ...
    return {}

def simulate_advanced_context(indicators: Dict) -> float:
    """Tạo ra điểm bối cảnh từ -1 (Sợ hãi) đến +1 (Tham lam)."""
    score = 0.0
    # 1. Thiên kiến dài hạn
    score += 0.4 if indicators['close'] > indicators.get('ema_200', indicators['close']) else -0.4
    # 2. Sức mạnh xu hướng
    adx = indicators.get('adx', 20)
    if adx > 30: score += 0.3 # Trend mạnh là tốt
    elif adx < 20: score -= 0.3 # Sideway là rủi ro
    # 3. Mức độ biến động
    bbw = indicators.get('bb_bbw', 0.05)
    if bbw > 0.08: score -= 0.3 # Biến động quá lớn (dễ bị quét SL)
    elif bbw < 0.03: score += 0.1 # Biến động thấp (báo hiệu sắp có bão)
    return max(-1.0, min(score, 1.0))

def manage_risk_by_pnl(capital: float, streak: int) -> float:
    """Quản lý vốn dựa trên chuỗi thắng/thua."""
    multiplier = 1.0
    if streak <= -2: # Thua 2 lệnh liên tiếp trở lên
        multiplier = 0.5
        print(f"    [RISK MGMT] Chuỗi thua {abs(streak)} lệnh. Giảm vốn còn 50%.")
    elif streak >= 3: # Thắng 3 lệnh liên tiếp trở lên
        multiplier = 1.25
        print(f"    [RISK MGMT] Chuỗi thắng {streak} lệnh. Tăng vốn lên 125%.")
    return capital * BASE_TRADE_AMOUNT_PERCENT * multiplier

# ==============================================================================
# ====================== HÀM BACKTEST CHÍNH CỦA TRADER =======================
# ==============================================================================
def run_intelligent_trader_backtest(all_data: Dict, all_models: Dict, config: Dict):
    print(f"\n--- Bắt đầu backtest với kịch bản: '{config['NOTES']}' ---")
    capital, trade_history, active_trades = INITIAL_CAPITAL, [], {}
    pnl_streak = 0 # Theo dõi chuỗi thắng/thua
    master_index = pd.concat([df.index.to_series() for df in all_data.values()]).unique().sort_values()

    for timestamp in master_index:
        # --- 1. Quản lý các lệnh đang mở (có Trailing Stop) ---
        for symbol in list(active_trades.keys()):
            if timestamp in all_data[symbol].index:
                current_price, high, low = all_data[symbol].loc[timestamp]['close'], all_data[symbol].loc[timestamp]['high'], all_data[symbol].loc[timestamp]['low']
                trade = active_trades[symbol]

                # Kích hoạt Trailing Stop
                if not trade['is_trailing'] and current_price >= trade['entry_price'] * (1 + config['TRAILING_STOP_ACTIVATE_PERCENT']):
                    trade['is_trailing'] = True
                    print(f"    [TRAILING] Kích hoạt Trailing Stop cho {symbol} @ {current_price:.4f}")

                # Cập nhật Trailing Stop
                if trade['is_trailing']:
                    new_peak = max(trade['peak_price'], high)
                    trade['peak_price'] = new_peak
                    new_sl = new_peak * (1 - config['TRAILING_STOP_DISTANCE_PERCENT'])
                    if new_sl > trade['sl']:
                        trade['sl'] = new_sl # Dời SL lên

                # Kiểm tra đóng lệnh
                status, exit_price = (("SL", trade['sl']) if low <= trade['sl'] else (("TP", trade['tp']) if high >= trade['tp'] and not trade['is_trailing'] else (None, None)))
                if status:
                    pnl = (exit_price - trade['entry_price']) / trade['entry_price']
                    net_pnl_usd = (trade['amount_usd'] * pnl) - (trade['amount_usd'] * (1 + pnl) * COMMISSION_RATE)
                    capital += net_pnl_usd
                    # Cập nhật chuỗi thắng/thua
                    if net_pnl_usd > 0: pnl_streak = (pnl_streak + 1) if pnl_streak > 0 else 1
                    else: pnl_streak = (pnl_streak - 1) if pnl_streak < 0 else -1
                    
                    trade.update({'exit_price': exit_price, 'exit_time': timestamp, 'pnl_usd': net_pnl_usd, 'status': status})
                    trade_history.append(trade)
                    del active_trades[symbol]

        # --- 2. Tìm kiếm cơ hội mới ---
        if len(active_trades) < MAX_ACTIVE_TRADES:
            for symbol in all_data.keys():
                # ... (Logic tìm và mở lệnh tương tự phiên bản advanced, nhưng sử dụng manage_risk_by_pnl)
                # ... và khởi tạo trade với các key mới cho trailing stop
                # active_trades[symbol] = {..., 'is_trailing': False, 'peak_price': entry_price}
                pass # Giả lập logic tìm lệnh
    
    return trade_history, capital

if __name__ == "__main__":
    # ... (Chạy backtest tương tự file Sniper) ...
    pass
