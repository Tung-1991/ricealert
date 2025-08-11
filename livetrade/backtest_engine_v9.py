# /root/ricealert/backtest/backtest_engine_v9.py
# PHIÊN BẢN 9.0 - MÔ PHỎNG LIVE_TRADE v8.7+
# Tác giả: Gemini & [Tên của bạn]
# Mục tiêu: Backtest chính xác các logic mới nhất của live_trade.py bao gồm:
# - TACTICS_LAB: Các chiến thuật phức tạp.
# - 4-ZONE MODEL: Phân tích vùng thị trường.
# - RISK FENCING: SL với SÀN (min) và TRẦN (max) an toàn.
# - ENSEMBLE AI: Sử dụng cả 3 model AI (LGBM, LSTM, Transformer).

import os
import sys
import pandas as pd
import joblib
import warnings
import json
from datetime import datetime
from typing import Dict, List, Tuple
import numpy as np

# --- Thiết lập đường dẫn & Import ---
warnings.filterwarnings("ignore", category=UserWarning)
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
sys.path.append(project_root)

# Import các thành phần cốt lõi từ hệ thống live
from livetrade.live_trade import (
    TACTICS_LAB, ZONE_BASED_POLICIES, RISK_RULES_CONFIG,
    get_mtf_adjustment_coefficient # Sẽ cần import thêm hàm này nếu chưa có
)
from indicator import calculate_indicators
from trade_advisor import get_advisor_decision, FULL_CONFIG as ADVISOR_BASE_CONFIG
from trainer import get_full_price_history, add_features # Cần 2 hàm này để lấy và xử lý dữ liệu
import tensorflow as tf
from keras.models import load_model

# --- Các hằng số Backtest ---
SYMBOLS_TO_TEST = ["ETHUSDT", "AVAXUSDT", "INJUSDT", "LINKUSDT", "SUIUSDT"] # Rút gọn để test nhanh hơn
INTERVALS_TO_TEST = ["1h", "4h"]
TOTAL_DAYS_TO_TEST = 90
INITIAL_CAPITAL = 10000.0
COMMISSION_RATE = 0.001 # Phí giao dịch spot (mua + bán)
SEQUENCE_LENGTH = 60 # Phải khớp với model AI

# --- Đường dẫn ---
CACHE_DIR = os.path.join(current_dir, "data_cache")
DATA_DIR = os.path.join(project_root, "data")
BACKTEST_RESULTS_DIR = os.path.join(current_dir, "backtest_results")
os.makedirs(CACHE_DIR, exist_ok=True)
os.makedirs(BACKTEST_RESULTS_DIR, exist_ok=True)

# Biến toàn cục để lưu cache chỉ báo, tránh tính toán lại
indicator_results_cache = {}

def determine_market_zone_for_backtest(symbol: str, interval: str, candle: pd.Series) -> str:
    # Hàm này là phiên bản đơn giản hóa của hàm trong live_trade
    # Dựa trên dữ liệu của một cây nến duy nhất
    adx = candle.get('adx', 20)
    bb_width = candle.get('bb_width', 0)
    
    if adx < 20 and bb_width < 0.05: # Giả định
        return "LEADING"
    if adx > 25:
        return "LAGGING"
    if candle.get('volume', 0) > candle.get('vol_ma20', 1) * 2:
        return "COINCIDENT"
    return "NOISE"

def prepare_ai_predictions_for_history(df: pd.DataFrame, symbol: str, interval: str) -> pd.DataFrame:
    """
    Hàm quan trọng: Chạy các model AI hiện tại trên dữ liệu lịch sử.
    """
    print(f"  -> Chuẩn bị AI cho {symbol}-{interval}...")
    try:
        # Tải tất cả model và scaler
        meta = json.load(open(os.path.join(DATA_DIR, f"meta_{symbol}_{interval}.json")))
        scaler = joblib.load(os.path.join(DATA_DIR, f"scaler_{symbol}_{interval}.pkl"))
        clf_lgbm = joblib.load(os.path.join(DATA_DIR, f"model_{symbol}_lgbm_clf_{interval}.pkl"))
        reg_lgbm = joblib.load(os.path.join(DATA_DIR, f"model_{symbol}_lgbm_reg_{interval}.pkl"))
        clf_lstm = load_model(os.path.join(DATA_DIR, f"model_{symbol}_lstm_clf_{interval}.keras"), compile=False)
        reg_lstm = load_model(os.path.join(DATA_DIR, f"model_{symbol}_lstm_reg_{interval}.keras"), compile=False)
        clf_trans = load_model(os.path.join(DATA_DIR, f"model_{symbol}_transformer_clf_{interval}.keras"), compile=False)
        reg_trans = load_model(os.path.join(DATA_DIR, f"model_{symbol}_transformer_clf_{interval}.keras"), compile=False)
    except Exception as e:
        print(f"     Lỗi: Không tìm thấy đủ bộ model cho {symbol}-{interval}. Bỏ qua AI. Lỗi: {e}")
        df['ai_prob_buy'], df['ai_prob_sell'], df['ai_pct'] = 50.0, 0.0, 0.0
        return df

    features_to_use = meta['features']
    df_scaled = df.copy()
    df_scaled[features_to_use] = scaler.transform(df[features_to_use])

    ai_results = []
    for i in range(len(df)):
        if i < SEQUENCE_LENGTH:
            ai_results.append({'prob_buy': 50.0, 'prob_sell': 0.0, 'pct': 0.0})
            continue

        # Dữ liệu cho LGBM (dòng cuối)
        latest_row = df[features_to_use].iloc[[i]]
        # Dữ liệu cho LSTM/Transformer (chuỗi 60 dòng)
        sequence_data = df_scaled[features_to_use].iloc[i-SEQUENCE_LENGTH:i].values
        sequence_to_predict = sequence_data[np.newaxis, :, :]

        # Dự báo
        lgbm_prob = clf_lgbm.predict_proba(latest_row)[0]
        lgbm_reg = reg_lgbm.predict(latest_row)[0]
        lstm_prob = clf_lstm.predict(sequence_to_predict, verbose=0)[0]
        lstm_reg = reg_lstm.predict(sequence_to_predict, verbose=0)[0][0]
        trans_prob = clf_trans.predict(sequence_to_predict, verbose=0)[0]
        trans_reg = reg_trans.predict(sequence_to_predict, verbose=0)[0][0]

        # Ensemble
        prob_buy = (lgbm_prob[2] * 0.25) + (lstm_prob[2] * 0.35) + (trans_prob[2] * 0.40)
        prob_sell = (lgbm_prob[0] * 0.25) + (lstm_prob[0] * 0.35) + (trans_prob[0] * 0.40)
        pct = (lgbm_reg * 0.25) + (lstm_reg * 0.35) + (trans_reg * 0.40)
        
        ai_results.append({'prob_buy': prob_buy * 100, 'prob_sell': prob_sell * 100, 'pct': pct})

    ai_df = pd.DataFrame(ai_results, index=df.index)
    df['ai_prob_buy'] = ai_df['prob_buy']
    df['ai_prob_sell'] = ai_df['prob_sell']
    df['ai_pct'] = ai_df['pct']
    
    tf.keras.backend.clear_session()
    return df


def run_backtest_for_tactic(tactic_name: str, all_data: Dict):
    capital, trade_history = INITIAL_CAPITAL, []
    active_trade: Dict = {}
    tactic_cfg = TACTICS_LAB[tactic_name]

    # Hợp nhất tất cả các index và sắp xếp
    all_indices = [df.index for symbol_data in all_data.values() for df in symbol_data.values() if not df.empty]
    if not all_indices: return [], capital
    master_index = pd.DatetimeIndex(pd.concat([s.to_series() for s in all_indices]).unique()).sort_values()
    
    # Giới hạn ngày backtest
    end_date, start_date = master_index.max(), master_index.max() - pd.Timedelta(days=TOTAL_DAYS_TO_TEST)
    master_index = master_index[(master_index >= start_date) & (master_index <= end_date)]

    print(f"\n[Backtest] Đang chạy mô phỏng cho Tactic: {tactic_name}...")
    
    for timestamp in master_index:
        # 1. Quản lý lệnh đang mở
        if active_trade:
            symbol, interval = active_trade['symbol'], active_trade['interval']
            df_trade = all_data.get(symbol, {}).get(interval)
            if df_trade is not None and timestamp in df_trade.index:
                current_candle = df_trade.loc[timestamp]
                status, exit_price = (None, None)
                if current_candle['low'] <= active_trade['sl']:
                    status, exit_price = "SL", active_trade['sl']
                elif current_candle['high'] >= active_trade['tp']:
                    status, exit_price = "TP", active_trade['tp']
                
                if status:
                    pnl = (exit_price - active_trade['entry_price']) / active_trade['entry_price']
                    net_pnl_usd = (active_trade['amount_usd'] * pnl) - (active_trade['amount_usd'] * (1 + abs(pnl)) * COMMISSION_RATE)
                    capital += net_pnl_usd
                    active_trade.update({'exit_price': exit_price, 'exit_time': timestamp, 'pnl_usd': net_pnl_usd, 'status': status})
                    trade_history.append(active_trade)
                    active_trade = {} # Đóng lệnh

        # 2. Tìm cơ hội mới (chỉ khi không có lệnh nào đang mở)
        if not active_trade:
            for symbol in SYMBOLS_TO_TEST:
                for interval in INTERVALS_TO_TEST:
                    df = all_data.get(symbol, {}).get(interval)
                    if df is None or timestamp not in df.index: continue

                    candle = df.loc[timestamp]
                    
                    # Mô phỏng việc tính toán chỉ báo và zone
                    indicator_results_cache.setdefault(symbol, {}).setdefault(interval, {})
                    indicator_results_cache[symbol][interval] = calculate_indicators(df.loc[:timestamp].tail(300), symbol, interval)
                    market_zone = determine_market_zone_for_backtest(symbol, interval, candle)

                    if market_zone in tactic_cfg.get("OPTIMAL_ZONE", []):
                        # Lấy dữ liệu AI đã được tính toán trước
                        ai_data = {"prob_buy": candle.get('ai_prob_buy', 50.0), "prob_sell": candle.get('ai_prob_sell', 0.0), "pct": candle.get('ai_pct', 0.0)}
                        # Giả định context trung lập
                        context_data = {"market_trend": "NEUTRAL", "news_factor": 0.0}

                        decision = get_advisor_decision(symbol, interval, indicator_results_cache[symbol][interval], ADVISOR_BASE_CONFIG,
                                                      ai_data_override=ai_data, context_override=context_data,
                                                      weights_override=tactic_cfg.get("WEIGHTS"))
                        
                        if decision['final_score'] >= tactic_cfg.get("ENTRY_SCORE", 9.9):
                            entry_price = candle['close']
                            
                            # Tính toán vốn theo Zone
                            capital_pct = ZONE_BASED_POLICIES.get(market_zone, {}).get("CAPITAL_PCT", 0.03)
                            amount_usd = capital * capital_pct

                            # Tính toán SL/TP theo logic mới
                            risk_dist_from_atr = indicator_results_cache[symbol][interval].get('atr', 0) * tactic_cfg.get("ATR_SL_MULTIPLIER", 2.0)
                            min_risk_map = RISK_RULES_CONFIG.get("MIN_RISK_DIST_PERCENT_BY_TIMEFRAME", {})
                            max_risk_map = RISK_RULES_CONFIG.get("MAX_SL_PERCENT_BY_TIMEFRAME", {})
                            min_risk_pct = min_risk_map.get(interval, 0.02)
                            max_risk_pct = max_risk_map.get(interval, 0.10)
                            min_risk_dist = entry_price * min_risk_pct
                            max_risk_dist = entry_price * max_risk_pct
                            effective_risk_dist = max(risk_dist_from_atr, min_risk_dist)
                            final_risk_dist = min(effective_risk_dist, max_risk_dist)

                            sl = entry_price - final_risk_dist
                            tp = entry_price + (final_risk_dist * tactic_cfg.get("RR", 2.0))

                            active_trade = {
                                'symbol': symbol, 'interval': interval, 'entry_price': entry_price, 
                                'tp': tp, 'sl': sl, 'amount_usd': amount_usd, 'status': "open", 
                                'score': decision['final_score'], 'entry_time': timestamp, 'zone': market_zone
                            }
                            capital -= (amount_usd * COMMISSION_RATE) # Trừ phí mua
                            break # Chỉ mở 1 lệnh mỗi lần
                if active_trade:
                    break

    return trade_history, capital

def generate_report(tactic_name: str, trade_history: List[Dict], final_capital: float):
    print("\n\n" + "="*80)
    print(f"============== 📊 BÁO CÁO BACKTEST CHO TACTIC: {tactic_name} 📊 ==============")
    
    if not trade_history:
        print("Không có giao dịch nào được thực hiện.")
        return

    df = pd.DataFrame(trade_history)
    total_trades = len(df)
    winning_trades = df[df['pnl_usd'] > 0]
    win_rate = (len(winning_trades) / total_trades * 100) if total_trades > 0 else 0
    total_pnl_usd = final_capital - INITIAL_CAPITAL
    net_profit_percent = (total_pnl_usd / INITIAL_CAPITAL * 100)

    print(f"Lợi nhuận ròng:      ${total_pnl_usd:,.2f} ({net_profit_percent:+.2f}%)")
    print(f"Vốn cuối cùng:       ${final_capital:,.2f}")
    print(f"Tổng số lệnh:        {total_trades}")
    print(f"Tỷ lệ thắng:         {win_rate:.2f}%")
    
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_filename = f"backtest_{tactic_name}_{TOTAL_DAYS_TO_TEST}d_{timestamp_str}.csv"
    csv_path = os.path.join(BACKTEST_RESULTS_DIR, csv_filename)
    df.to_csv(csv_path, index=False, float_format='%.4f')
    print(f"✅ Chi tiết giao dịch đã được lưu vào: {csv_path}")
    print("="*80)

# ==============================================================================
# MAIN EXECUTION
# ==============================================================================
if __name__ == "__main__":
    print(" BẮT ĐẦU PHIÊN BACKTEST MÔ PHỎNG LIVE_TRADE ".center(80, "="))

    # 1. Tải và cache toàn bộ dữ liệu giá lịch sử
    all_data_historcial = {}
    for symbol in SYMBOLS_TO_TEST:
        all_data_historcial[symbol] = {}
        for interval in INTERVALS_TO_TEST:
            cache_file = os.path.join(CACHE_DIR, f"{symbol}-{interval}-{TOTAL_DAYS_TO_TEST}d.parquet")
            if os.path.exists(cache_file):
                df = pd.read_parquet(cache_file)
            else:
                limit = TOTAL_DAYS_TO_TEST * (24 if interval == '1h' else 6 if interval == '4h' else 1) + 300
                df = get_full_price_history(symbol, interval, limit, 1000)
                if not df.empty: df.to_parquet(cache_file)
            
            if not df.empty:
                print(f"Đã tải {len(df)} nến cho {symbol}-{interval}")
                df_with_features = add_features(df)
                all_data_historcial[symbol][interval] = prepare_ai_predictions_for_history(df_with_features, symbol, interval)
    
    # 2. Chạy backtest cho từng Tactic trong TACTICS_LAB
    for tactic in TACTICS_LAB.keys():
        history, final_cap = run_backtest_for_tactic(tactic, all_data_historcial)
        generate_report(tactic, history, final_cap)

    print(" KẾT THÚC PHIÊN BACKTEST ".center(80, "="))
