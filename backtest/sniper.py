# /root/ricealert/backtest/backtest_sniper.py
# PHIÊN BẢN 5.3 - STRATEGY LAB REFINED & CONCISE REPORTING

import os
import sys
import pandas as pd
import joblib
import warnings
import json
from datetime import datetime
from typing import Dict, List, Tuple
import numpy as np
from collections import deque

# --- Thiết lập đường dẫn & Import ---
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
sys.path.append(project_root)
warnings.filterwarnings("ignore", category=UserWarning)

from trainer import get_full_price_history, add_features
from trade_advisor import get_advisor_decision, FULL_CONFIG

# ==============================================================================
# ================= 🔬 PHÒNG THÍ NGHIỆM CHIẾN LƯỢC 🔬 =====================
# ==============================================================================
STRATEGY_CONFIGS = {
    # ⚙️ MỚI: AI với rủi ro thực tế - SL 3%, RR 2
    "AI_ThucTe_3SL_2RR": {
        "NOTES": "AI Gốc - Thử nghiệm SL 3% và RR 2.0 để cân bằng Lợi nhuận/Rủi ro.",
        "WEIGHTS_OVERRIDE": {'tech': 0.0, 'ai': 1.0, 'context': 0.0},
        "ENTRY_SCORE_THRESHOLD": 6.5,  # Ngưỡng vào lệnh hợp lý
        "RR_RATIO": 2.0,               # Tỷ lệ RR tiêu chuẩn
        "SL_PERCENT": 0.03,            # << SL 3%, một con số thực tế hơn nhiều
        "SCORE_RANGE_OVERRIDE": 7
    },

    # ⚙️ MỚI: AI với rủi ro vừa phải - SL 5%, RR 2
    "AI_ThucTe_5SL_2RR": {
        "NOTES": "AI Gốc - Cho phép biến động nhiều hơn với SL 5%.",
        "WEIGHTS_OVERRIDE": {'tech': 0.0, 'ai': 1.0, 'context': 0.0},
        "ENTRY_SCORE_THRESHOLD": 6.5,
        "RR_RATIO": 2.0,
        "SL_PERCENT": 0.05,            # << SL 5%, phù hợp cho swing trade ngắn
        "SCORE_RANGE_OVERRIDE": 7
    },

    # ⚙️ MỚI: AI với rủi ro cao hơn - SL 8%, RR 1.8
    "AI_ThucTe_8SL_1.8RR": {
        "NOTES": "AI Gốc - SL rộng (8%) để bắt các con sóng lớn, RR giảm nhẹ.",
        "WEIGHTS_OVERRIDE": {'tech': 0.0, 'ai': 1.0, 'context': 0.0},
        "ENTRY_SCORE_THRESHOLD": 6.0, # Giảm ngưỡng để bắt nhiều tín hiệu hơn
        "RR_RATIO": 1.8,
        "SL_PERCENT": 0.08,            # << SL 8%, chấp nhận rủi ro cao hơn
        "SCORE_RANGE_OVERRIDE": 7
    },
    
    # Giữ lại chiến lược AI 20% SL để so sánh
    "AI_Goc_20SL": {
        "NOTES": "Chiến lược AI gốc với SL 20% để làm cơ sở so sánh.",
        "WEIGHTS_OVERRIDE": {'tech': 0.0, 'ai': 1.0, 'context': 0.0},
        "ENTRY_SCORE_THRESHOLD": 7,
        "RR_RATIO": 1,
        "SL_PERCENT": 0.2,
        "SCORE_RANGE_OVERRIDE": 8
    }
}
# --- Các hằng số Backtest ---
SYMBOLS_TO_TEST = ["ETHUSDT", "AVAXUSDT", "INJUSDT", "LINKUSDT", "SUIUSDT", "FETUSDT", "TAOUSDT"]
INTERVALS_TO_TEST = ["1h", "4h", "1d"]
TOTAL_DAYS_TO_TEST = 90
INITIAL_CAPITAL = 10000.0
TRADE_AMOUNT_PERCENT = 0.1
COMMISSION_RATE = 0.0004

# --- Đường dẫn ---
CACHE_DIR = os.path.join(current_dir, "data_cache")
DATA_DIR = os.path.join(project_root, "data")
BACKTEST_RESULTS_DIR = os.path.join(current_dir, "backtest_results")
os.makedirs(CACHE_DIR, exist_ok=True)
os.makedirs(BACKTEST_RESULTS_DIR, exist_ok=True)

# ==============================================================================
# CÁC HÀM TẢI VÀ CHUẨN BỊ DỮ LIỆU
# ==============================================================================
def load_all_historical_data(symbols: List[str], intervals: List[str], days: int) -> Dict:
    print(f"\n[Backtest] Tải dữ liệu giá cho {len(symbols)} symbols, {len(intervals)} intervals ({days} ngày)...")
    all_data = {}
    for symbol in symbols:
        all_data[symbol] = {}
        for interval in intervals + ['1d']: # Luôn tải thêm dữ liệu 1d
            try:
                if interval == '1h': limit_candles = days * 24 + 200
                elif interval == '4h': limit_candles = days * 6 + 200
                else: limit_candles = days + 200 # Cho khung 1d

                cache_file = os.path.join(CACHE_DIR, f"{symbol}-{interval}-{days}d.parquet")
                if os.path.exists(cache_file) and (datetime.now() - datetime.fromtimestamp(os.path.getmtime(cache_file))).days < 1:
                    df = pd.read_parquet(cache_file)
                else:
                    df = get_full_price_history(symbol, interval, limit_candles, 1000)
                    if not df.empty: df.to_parquet(cache_file)

                if not df.empty:
                    df_with_features = add_features(df)
                    all_data[symbol][interval] = df_with_features
            except Exception as e: print(f"Lỗi tải dữ liệu cho {symbol}-{interval}: {e}")
    print("✅ Hoàn thành tải dữ liệu.")
    return all_data

def prepare_context_and_ai_data_for_backtest(all_data: Dict):
    print("\n[Backtest] Chuẩn bị dữ liệu AI và Context cho toàn bộ lịch sử...")
    all_models = {}
    for symbol in SYMBOLS_TO_TEST:
        all_models[symbol] = {}
        for interval in INTERVALS_TO_TEST:
            try:
                clf_path = os.path.join(DATA_DIR, f"model_{symbol}_clf_{interval}.pkl")
                reg_path = os.path.join(DATA_DIR, f"model_{symbol}_reg_{interval}.pkl")
                meta_path = os.path.join(DATA_DIR, f"meta_{symbol}_{interval}.json")
                if os.path.exists(clf_path):
                    all_models[symbol][interval] = {"clf": joblib.load(clf_path), "reg": joblib.load(reg_path), "meta": json.load(open(meta_path, 'r'))}
            except Exception as e: print(f"Lỗi tải model AI cho {symbol}-{interval}: {e}")

    for symbol, symbol_data in all_data.items():
        for interval, df in symbol_data.items():
            if df.empty or interval == '1d': continue # Không cần chạy AI cho 1d
            ai_model_info = all_models.get(symbol, {}).get(interval)
            if ai_model_info:
                model_features = ai_model_info['meta']['features']
                X_ai = df[model_features].reindex(columns=model_features, fill_value=0)
                probs_ai = ai_model_info['clf'].predict_proba(X_ai)
                classes_ai = ai_model_info['clf'].classes_.tolist()
                buy_idx = classes_ai.index(2) if 2 in classes_ai else -1
                sell_idx = classes_ai.index(0) if 0 in classes_ai else -1
                df['ai_prob_buy'] = probs_ai[:, buy_idx] * 100 if buy_idx != -1 else 50.0
                df['ai_prob_sell'] = probs_ai[:, sell_idx] * 100 if sell_idx != -1 else 0.0
                reg_preds = ai_model_info['reg'].predict(X_ai)
                df['ai_predicted_pct'] = (reg_preds * df['atr'] * 100) / (df['close'] + 1e-9)
            else:
                df['ai_prob_buy'], df['ai_prob_sell'], df['ai_predicted_pct'] = 50.0, 0.0, 0.0
            df['context_market_trend'], df['context_news_factor'] = "NEUTRAL", 0.0
    print("✅ Hoàn thành chuẩn bị dữ liệu AI và Context.")
    return all_data

# ==============================================================================
# HÀM BACKTEST CHÍNH
# ==============================================================================
def run_sniper_backtest(all_data: Dict, strategy_config: Dict):
    capital, trade_history = INITIAL_CAPITAL, []
    active_trades: Dict[Tuple[str, str], Dict] = {}
    debug_messages = deque(maxlen=3) # <-- THAY ĐỔI: Giảm số dòng debug

    # --- CẢI TIẾN: Chuẩn bị config một lần cho mỗi chiến lược ---
    local_config = FULL_CONFIG.copy()
    if "SCORE_RANGE_OVERRIDE" in strategy_config:
        local_config["SCORE_RANGE"] = strategy_config["SCORE_RANGE_OVERRIDE"]

    all_indices = [df.index for symbol_data in all_data.values() for df in symbol_data.values() if not df.empty]
    if not all_indices: return [], capital, []

    master_index = pd.DatetimeIndex(pd.concat([s.to_series() for s in all_indices]).unique()).sort_values()
    end_date, start_date = master_index.max(), master_index.max() - pd.Timedelta(days=TOTAL_DAYS_TO_TEST)
    master_index = master_index[(master_index >= start_date) & (master_index <= end_date)]

    for timestamp in master_index:
        # Check close trades
        for (symbol, interval), trade in list(active_trades.items()):
            if symbol in all_data and interval in all_data[symbol] and timestamp in all_data[symbol][interval].index:
                current_price_data = all_data[symbol][interval].loc[timestamp]
                high, low = current_price_data['high'], current_price_data['low']
                status, exit_price = (("SL", trade['sl']) if low <= trade['sl'] else
                                      ("TP", trade['tp']) if high >= trade['tp'] else (None, None))
                if status:
                    pnl = (exit_price - trade['entry_price']) / trade['entry_price']
                    net_pnl_usd = (trade['amount_usd'] * pnl) - (trade['amount_usd'] * (1 + abs(pnl)) * COMMISSION_RATE)
                    capital += net_pnl_usd
                    trade.update({'exit_price': exit_price, 'exit_time': timestamp, 'pnl_percent': pnl * 100, 'pnl_usd': net_pnl_usd, 'status': status, 'final_capital': capital})
                    trade_history.append(trade)
                    del active_trades[(symbol, interval)]

        # Find new signals
        for symbol in SYMBOLS_TO_TEST:
            if any(key[0] == symbol for key in active_trades.keys()): continue
            for interval in INTERVALS_TO_TEST:
                if any(key[0] == symbol for key in active_trades.keys()): break
                df = all_data.get(symbol, {}).get(interval)
                if df is None or timestamp not in df.index: continue

                candle = df.loc[timestamp]
                indicators = candle.to_dict()
                indicators.update({"symbol": symbol, "interval": interval})

                # Chuẩn bị RSI đa khung thời gian
                for tf in ["1h", "4h", "1d"]:
                    df_tf = all_data.get(symbol, {}).get(tf)
                    indicators[f'rsi_{tf}'] = df_tf.loc[timestamp, 'rsi_14'] if df_tf is not None and timestamp in df_tf.index else indicators.get('rsi_14', 50)

                ai_data = {"prob_buy": candle.get('ai_prob_buy', 50.0), "prob_sell": candle.get('ai_prob_sell', 0.0), "pct": candle.get('ai_predicted_pct', 0.0)}
                context_data = {"market_trend": "NEUTRAL", "news_factor": 0.0}

                decision = get_advisor_decision(symbol, interval, indicators, local_config,
                                                ai_data_override=ai_data, context_override=context_data,
                                                weights_override=strategy_config["WEIGHTS_OVERRIDE"])

                debug_line = f"[DEBUG] {timestamp.strftime('%y-%m-%d %H:%M')} | {symbol}-{interval} | Score: {decision['final_score']:.2f} (SR: {local_config['SCORE_RANGE']})"
                debug_messages.append(debug_line)

                if decision['decision_type'] == "OPPORTUNITY_BUY" and decision['final_score'] >= strategy_config['ENTRY_SCORE_THRESHOLD']:
                    entry, amount = candle['close'], capital * TRADE_AMOUNT_PERCENT
                    if capital < amount: continue
                    sl = entry * (1 - strategy_config['SL_PERCENT'])
                    tp = entry * (1 + strategy_config['SL_PERCENT'] * strategy_config['RR_RATIO'])
                    capital -= (amount * COMMISSION_RATE)
                    active_trades[(symbol, interval)] = {'symbol': symbol, 'interval': interval, 'entry_price': entry, 'tp': tp, 'sl': sl, 'amount_usd': amount, 'status': "open", 'score': decision['final_score'], 'entry_time': timestamp}

    # Close remaining trades at the end
    for (symbol, interval), trade in list(active_trades.items()):
        if symbol in all_data and interval in all_data[symbol] and master_index.max() in all_data[symbol][interval].index:
            last_price = all_data[symbol][interval].loc[master_index.max()]['close']
            pnl = (last_price - trade['entry_price']) / trade['entry_price']
            net_pnl_usd = (trade['amount_usd'] * pnl) - (trade['amount_usd'] * (1 + abs(pnl)) * COMMISSION_RATE)
            capital += net_pnl_usd
            trade.update({'exit_price': last_price, 'exit_time': master_index.max(), 'pnl_percent': pnl * 100, 'pnl_usd': net_pnl_usd, 'status': "Closed (End)", 'final_capital': capital})
            trade_history.append(trade)

    return trade_history, capital, list(debug_messages)

# ==============================================================================
# BÁO CÁO KẾT QUẢ NÂNG CAO
# ==============================================================================
def generate_backtest_report(strategy_name: str, config: Dict, trade_history: List[Dict], final_capital: float, debug_log: List[str]):
    print("\n\n" + "="*80)
    print(f"============== 📊 BÁO CÁO CHIẾN LƯỢC: {strategy_name} 📊 ==============")
    print(f"============== '{config['NOTES']}' ==============")
    print("="*80)

    if not trade_history:
        print("Không có giao dịch nào được thực hiện. Hãy thử nới lỏng ngưỡng vào lệnh.")
        return

    df = pd.DataFrame(trade_history)
    df['entry_time'] = pd.to_datetime(df['entry_time'])
    df['exit_time'] = pd.to_datetime(df['exit_time'])
    df['holding_hours'] = (df['exit_time'] - df['entry_time']).dt.total_seconds() / 3600

    total_trades = len(df)
    winning_trades = df[df['pnl_usd'] > 0]
    losing_trades = df[df['pnl_usd'] <= 0]
    win_rate = (len(winning_trades) / total_trades * 100) if total_trades > 0 else 0
    total_pnl_usd = final_capital - INITIAL_CAPITAL
    net_profit_percent = (total_pnl_usd / INITIAL_CAPITAL * 100)
    avg_win_pnl = winning_trades['pnl_usd'].mean() if not winning_trades.empty else 0
    avg_loss_pnl = losing_trades['pnl_usd'].mean() if not losing_trades.empty else 0
    profit_factor = abs(winning_trades['pnl_usd'].sum() / losing_trades['pnl_usd'].sum()) if not losing_trades.empty and losing_trades['pnl_usd'].sum() != 0 else float('inf')

    df['cumulative_capital'] = df['final_capital']
    peak = df['cumulative_capital'].cummax()
    drawdown = (df['cumulative_capital'] - peak) / peak
    max_drawdown_percent = abs(drawdown.min() * 100) if not drawdown.empty else 0
    pnl_std = df['pnl_percent'].std()
    sharpe_ratio = (df['pnl_percent'].mean() / pnl_std) * np.sqrt(252 * (24 / (df['holding_hours'].mean() if df['holding_hours'].mean() > 0 else 24))) if pnl_std > 0 else 0

    print("I. TỔNG QUAN HIỆU SUẤT:")
    print(f"  - Lợi nhuận ròng:      ${total_pnl_usd:,.2f} ({net_profit_percent:+.2f}%)")
    print(f"  - Vốn cuối cùng:        ${final_capital:,.2f} (từ ${INITIAL_CAPITAL:,.2f})")
    print(f"  - Hệ số lợi nhuận:      {profit_factor:.2f} (Mục tiêu > 1.5)")

    print("\nII. THỐNG KÊ GIAO DỊCH:")
    print(f"  - Tổng số lệnh:          {total_trades}")
    print(f"  - Tỷ lệ thắng:           {win_rate:.2f}% ({len(winning_trades)} thắng / {len(losing_trades)} thua)")
    print(f"  - Lời/lệnh thắng TB:    ${avg_win_pnl:,.2f}")
    print(f"  - Lỗ/lệnh thua TB:      ${avg_loss_pnl:,.2f}")
    print(f"  - Thời gian giữ lệnh TB: {df['holding_hours'].mean():.2f} giờ")

    print("\nIII. QUẢN LÝ RỦI RO:")
    print(f"  - Sụt giảm vốn tối đa: {max_drawdown_percent:.2f}%")
    print(f"  - Tỷ lệ Sharpe (năm):   {sharpe_ratio:.2f} (Mục tiêu > 1.0)")

    # --- CẢI TIẾN: Thêm phân tích theo từng cặp giao dịch ---
    print("\nIV. PHÂN TÍCH THEO CẶP GIAO DỊCH:")
    symbol_analysis = df.groupby('symbol')['pnl_usd'].agg(['sum', 'count', lambda x: (x > 0).sum() / len(x) * 100])
    symbol_analysis.columns = ['Total PnL ($)', 'Trade Count', 'Win Rate (%)']
    print(symbol_analysis.to_string(float_format="%.2f"))

    if debug_log:
        print("\nV. NHẬT KÝ DEBUG (3 dòng cuối):") # <-- THAY ĐỔI: Cập nhật tiêu đề
        for line in debug_log:
            print(f"  {line}")

    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_filename = f"{strategy_name}_{timestamp_str}.csv"
    csv_path = os.path.join(BACKTEST_RESULTS_DIR, csv_filename)
    df.to_csv(csv_path, index=False, float_format='%.4f')
    print(f"\n✅ Chi tiết giao dịch đã được lưu vào: {csv_path}")
    print("="*80)

# ==============================================================================
# MAIN EXECUTION
# ==============================================================================
if __name__ == "__main__":
    print(" BẮT ĐẦU PHIÊN BACKTEST ĐA CHIẾN LƯỢC ".center(80, "="))

    # Cần dữ liệu 1D cho logic đa khung thời gian
    all_intervals_needed = list(set(INTERVALS_TO_TEST + ['1d']))
    all_data = load_all_historical_data(SYMBOLS_TO_TEST, all_intervals_needed, TOTAL_DAYS_TO_TEST)
    all_data_prepared = prepare_context_and_ai_data_for_backtest(all_data)

    if not any(any(not df.empty for df in sym_data.values()) for sym_data in all_data_prepared.values()):
        print("❌ Không có dữ liệu để backtest. Vui lòng kiểm tra lại.")
    else:
        for name, config in STRATEGY_CONFIGS.items():
            history, final_cap, debug_messages = run_sniper_backtest(all_data_prepared, config)
            generate_backtest_report(name, config, history, final_cap, debug_messages)

    print(" KẾT THÚC PHIÊN BACKTEST ".center(80, "="))
