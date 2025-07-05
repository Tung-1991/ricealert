# /root/ricealert/backtest/backtest_sniper.py
# CHIẾN LƯỢC: SNIPER - BẮN TỈA
# Triết lý: Chỉ vào lệnh khi có độ tin cậy cực cao, tối đa hóa tỷ lệ thắng.

import os, sys, pandas as pd, joblib, warnings, json, ta
from datetime import datetime
from typing import Dict, List

# --- Thiết lập đường dẫn ---
current_dir, project_root = os.path.dirname(os.path.abspath(__file__)), os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)
warnings.filterwarnings("ignore", category=UserWarning)
from trainer import get_full_price_history, add_features

# ==============================================================================
# =================== ⚙️ CẤU HÌNH CHIẾN LƯỢC SNIPER ⚙️ =====================
# ==============================================================================
SNIPER_CONFIG = {
    "NOTES": "Sniper: Ngưỡng điểm > 8.5, có xác nhận volume, trọng số AI cao.",
    "WEIGHTS": {'tech': 0.40, 'ai': 0.60, 'context': 0.0}, # Context bị loại bỏ
    "ENTRY_SCORE_THRESHOLD": 8.5, # Ngưỡng điểm cực cao
    "VOLUME_CONFIRMATION_RATIO": 1.5, # Volume phải cao gấp 1.5 lần trung bình
}
# --- Các hằng số Backtest ---
SYMBOLS_TO_TEST = ["ETHUSDT", "AVAXUSDT", "LINKUSDT", "SUIUSDT", "TAOUSDT", "INJUSDT"]
INTERVAL, TOTAL_DAYS_TO_TEST = "1h", 90
INITIAL_CAPITAL, MAX_ACTIVE_TRADES, TRADE_AMOUNT_PERCENT, COMMISSION_RATE = 10000.0, 3, 0.1, 0.0004
RR_RATIO = 2.5 # Tỷ lệ Lời:Lỗ cố định là 2.5:1 cho các lệnh chất lượng cao
CACHE_DIR, DATA_DIR = os.path.join(current_dir, "data_cache"), os.path.join(project_root, "data")
os.makedirs(CACHE_DIR, exist_ok=True)

# (Các hàm load_all_historical_data, load_all_ai_models giữ nguyên)
def load_all_historical_data(symbols, interval, days):
    print(f"\n[SNIPER] Tải dữ liệu giá cho {len(symbols)} symbols...")
    all_data = {}
    for symbol in symbols:
        try:
            cache_file = os.path.join(CACHE_DIR, f"{symbol}-{interval}-{days}d.parquet")
            if os.path.exists(cache_file): df = pd.read_parquet(cache_file)
            else:
                df = get_full_price_history(symbol, interval, days * 24, 1000)
                if not df.empty: df.to_parquet(cache_file)
            if not df.empty: all_data[symbol] = add_features(df)
        except Exception as e: print(f"Lỗi tải dữ liệu {symbol}: {e}")
    return all_data

def load_all_ai_models(symbols, interval):
    print(f"[SNIPER] Tải mô hình AI...")
    all_models = {}
    for symbol in symbols:
        try:
            all_models[symbol] = {"clf": joblib.load(os.path.join(DATA_DIR, f"model_{symbol}_clf_{interval}.pkl")), "meta": json.load(open(os.path.join(DATA_DIR, f"meta_{symbol}_{interval}.json"), 'r'))}
        except FileNotFoundError: pass
    return all_models

# ==============================================================================
# ====================== HÀM BACKTEST CHÍNH CỦA SNIPER =======================
# ==============================================================================
def run_sniper_backtest(all_data: Dict, all_models: Dict, config: Dict):
    print(f"\n--- Bắt đầu backtest với kịch bản: '{config['NOTES']}' ---")
    capital, trade_history, active_trades = INITIAL_CAPITAL, [], {}
    master_index = pd.concat([df.index.to_series() for df in all_data.values()]).unique().sort_values()

    for timestamp in master_index:
        # --- 1. Kiểm tra đóng lệnh ---
        for symbol in list(active_trades.keys()):
            if timestamp in all_data[symbol].index:
                high, low = all_data[symbol].loc[timestamp]['high'], all_data[symbol].loc[timestamp]['low']
                trade = active_trades[symbol]
                status, exit_price = (("SL", trade['sl']) if low <= trade['sl'] else (("TP", trade['tp']) if high >= trade['tp'] else (None, None)))
                if status:
                    pnl = (exit_price - trade['entry_price']) / trade['entry_price']
                    net_pnl_usd = (trade['amount_usd'] * pnl) - (trade['amount_usd'] * (1 + pnl) * COMMISSION_RATE)
                    capital += net_pnl_usd
                    trade.update({'exit_price': exit_price, 'exit_time': timestamp, 'pnl_usd': net_pnl_usd, 'status': status})
                    trade_history.append(trade)
                    del active_trades[symbol]

        # --- 2. Tìm kiếm tín hiệu bắn tỉa ---
        if len(active_trades) < MAX_ACTIVE_TRADES:
            for symbol in all_data.keys():
                if symbol not in active_trades and timestamp in all_data[symbol].index and symbol in all_models:
                    df_slice = all_data[symbol].loc[:timestamp]
                    if len(df_slice) < 50: continue
                    
                    indicators = df_slice.iloc[-1].to_dict()
                    
                    # BỘ LỌC 1: VOLUME CONFIRMATION
                    vol_ma_20 = indicators.get('volume', 0) / (indicators.get('vol_ma20', 1) + 1e-9)
                    if indicators.get('volume', 0) < indicators.get('vol_ma20', 0) * config['VOLUME_CONFIRMATION_RATIO']:
                        continue # Bỏ qua nếu volume không đủ mạnh

                    # Lấy dự đoán AI
                    try:
                        models, X = all_models[symbol], pd.DataFrame([indicators])[all_models[symbol]['meta']['features']]
                        if X.isnull().values.any(): continue
                        probs = models['clf'].predict_proba(X)[0]
                        classes = models['clf'].classes_.tolist()
                        prob_buy = probs[classes.index(2)] * 100 if 2 in classes else 0
                        prob_sell = probs[classes.index(0)] * 100 if 0 in classes else 0
                    except Exception: continue

                    # Tính điểm Tech và AI
                    tech_score = 10 if indicators['rsi_14'] > 60 and indicators['close'] > indicators['ema_20'] else (2 if indicators['rsi_14'] < 40 and indicators['close'] < indicators['ema_20'] else 5)
                    tech_scaled = (tech_score / 5.0) - 1.0
                    ai_skew = (prob_buy - prob_sell) / 100.0
                    
                    # Tính điểm cuối cùng (không có context)
                    final_rating = (config['WEIGHTS']['tech'] * tech_scaled) + (config['WEIGHTS']['ai'] * ai_skew)
                    final_score = round(min(max((final_rating + 1) * 5, 0), 10), 1)

                    # BỘ LỌC 2: ENTRY SCORE THRESHOLD
                    if final_score >= config['ENTRY_SCORE_THRESHOLD']:
                        entry_price = indicators['close']
                        sl_price = entry_price * (1 - 0.02) # SL 2%
                        tp_price = entry_price + (entry_price - sl_price) * RR_RATIO

                        amount_to_invest = INITIAL_CAPITAL * TRADE_AMOUNT_PERCENT
                        if capital < amount_to_invest: continue
                        
                        print(f"[{str(timestamp)[:16]}] 🔫 SNIPER FIRE! {symbol} | Score: {final_score:.1f} | Vol Ratio: {vol_ma_20:.1f}")
                        
                        capital -= (amount_to_invest * COMMISSION_RATE)
                        active_trades[symbol] = {
                            'symbol': symbol, 'entry_price': entry_price, 'entry_time': timestamp,
                            'tp': tp_price, 'sl': sl_price, 'amount_usd': amount_to_invest, 'score': final_score
                        }
                        if len(active_trades) >= MAX_ACTIVE_TRADES: break
    
    return trade_history, capital

if __name__ == "__main__":
    all_data = load_all_historical_data(SYMBOLS_TO_TEST, INTERVAL, TOTAL_DAYS_TO_TEST)
    all_models = load_all_ai_models(SYMBOLS_TO_TEST, INTERVAL)
    if all_data and all_models:
        history, final_cap = run_sniper_backtest(all_data, all_models, SNIPER_CONFIG)
        # (Bạn có thể thêm hàm generate_report vào đây)
        print("\n--- SNIPER BACKTEST COMPLETE ---")
        print(f"Final Capital: ${final_cap:,.2f} | Total Trades: {len(history)}")
