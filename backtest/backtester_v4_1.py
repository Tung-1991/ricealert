import os
import sys
import pandas as pd
import joblib
import warnings
from datetime import datetime

# --- Thêm đường dẫn gốc của dự án vào sys.path ---
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
sys.path.append(project_root)
warnings.filterwarnings("ignore")

# --- Import các module logic cốt lõi ---
from indicator import calculate_indicators
from trade_advisor import get_advisor_decision
from trainer import get_full_price_history, add_features
from ml_report import classify_level

# --- Cấu hình ---
CONFIG = {
    "SYMBOLS": ["ETHUSDT", "AVAXUSDT", "INJUSDT", "LINKUSDT", "SUIUSDT", "FETUSDT", "TAOUSDT"],
    "INTERVAL": "1h",
    "TOTAL_DAYS_TO_TEST": 90,
    "INITIAL_CAPITAL": 10000.0,
    "MAX_ACTIVE_TRADES": 4,
    "TRADE_AMOUNT_PERCENT": 0.1,
    "RECOVERY_TRADE_AMOUNT_PERCENT": 0.05,
    "COMMISSION_RATE": 0.0004,
    "ADVISOR_BUY_SCORE_THRESHOLD": 7.0,
    "RECOVERY_BUY_SCORE_MIN": 4.5,
    "SIMULATED_MARKET_TREND": "UPTREND",
    "SIMULATED_NEWS_FACTOR": 0
}

CACHE_DIR = os.path.join(current_dir, "data_cache")
DATA_DIR = os.path.join(project_root, "data")
os.makedirs(CACHE_DIR, exist_ok=True)

def load_all_historical_data(symbols, interval, days):
    all_data = {}
    for symbol in symbols:
        cache_file = os.path.join(CACHE_DIR, f"{symbol}-{interval}-{days}d.parquet")
        if os.path.exists(cache_file):
            df = pd.read_parquet(cache_file)
        else:
            interval_map = {"h": 24, "d": 1}
            candles_per_day = interval_map.get(interval[-1], 24)
            limit = days * candles_per_day
            df = get_full_price_history(symbol, interval, limit, 1000)
            if not df.empty: df.to_parquet(cache_file)
        if not df.empty:
            all_data[symbol] = add_features(df)
    return all_data

def load_all_ai_models(symbols, interval):
    all_models = {}
    for symbol in symbols:
        try:
            clf = joblib.load(os.path.join(DATA_DIR, f"model_{symbol}_clf_{interval}.pkl"))
            reg = joblib.load(os.path.join(DATA_DIR, f"model_{symbol}_reg_{interval}.pkl"))
            with open(os.path.join(DATA_DIR, f"meta_{symbol}_{interval}.json"), 'r') as f:
                meta = pd.read_json(f, typ='series').to_dict()
            all_models[symbol] = {"clf": clf, "reg": reg, "meta": meta}
        except FileNotFoundError:
            print(f"  - Cảnh báo: Thiếu model AI cho {symbol}, bỏ qua.")
    return all_models

def run_portfolio_backtest(all_data, all_models):
    capital = CONFIG['INITIAL_CAPITAL']
    trade_history = []
    active_trades = {}
    all_indices = [df.index for df in all_data.values()]
    master_index = pd.DatetimeIndex(pd.concat([pd.Series(index) for index in all_indices]).unique()).sort_values()

    for timestamp in master_index:
        for symbol in list(active_trades.keys()):
            if timestamp in all_data[symbol].index:
                current_price = all_data[symbol].loc[timestamp]['close']
                trade = active_trades[symbol]
                status = None
                if current_price >= trade['tp']: status = "TP"
                elif current_price <= trade['sl']: status = "SL"
                if status:
                    pnl = (current_price - trade['entry_price']) / trade['entry_price']
                    pnl_usd = trade['amount_usd'] * pnl
                    commission = (trade['amount_usd'] + pnl_usd) * CONFIG['COMMISSION_RATE']
                    net_pnl_usd = pnl_usd - commission
                    capital += net_pnl_usd
                    trade.update({'exit_price': current_price, 'exit_time': timestamp, 'pnl_percent': pnl * 100, 'pnl_usd': net_pnl_usd, 'status': status})
                    trade_history.append(trade)
                    del active_trades[symbol]

        if len(active_trades) < CONFIG['MAX_ACTIVE_TRADES']:
            for symbol in all_data.keys():
                if symbol not in active_trades and timestamp in all_data[symbol].index:
                    df_slice = all_data[symbol].loc[:timestamp]
                    if len(df_slice) < 50: continue
                    indicators = calculate_indicators(df_slice, symbol, CONFIG['INTERVAL'])

                    ai_data_for_advisor = {}
                    if symbol in all_models:
                        models = all_models[symbol]
                        latest_features = df_slice.iloc[-1]
                        X = pd.DataFrame([latest_features])[models['meta']['features']]
                        if not X.isnull().values.any():
                            probs = models['clf'].predict_proba(X)[0]
                            prob_buy = probs[2] * 100
                            ai_data_for_advisor = {"prob_buy": prob_buy, "pct": 0}

                    context_override = {
                        "market_trend": CONFIG["SIMULATED_MARKET_TREND"],
                        "news_factor": CONFIG["SIMULATED_NEWS_FACTOR"],
                    }

                    decision_data = get_advisor_decision(symbol, CONFIG['INTERVAL'], indicators, {}, ai_data_override=ai_data_for_advisor)
                    score = decision_data['final_score']
                    decision_type = decision_data['decision_type']

                    if decision_type == 'OPPORTUNITY_BUY':
                        if score >= CONFIG['ADVISOR_BUY_SCORE_THRESHOLD']:
                            amount_to_invest = capital * CONFIG['TRADE_AMOUNT_PERCENT']
                        elif score >= CONFIG['RECOVERY_BUY_SCORE_MIN']:
                            amount_to_invest = capital * CONFIG['RECOVERY_TRADE_AMOUNT_PERCENT']
                        else:
                            continue

                        commission = amount_to_invest * CONFIG['COMMISSION_RATE']
                        capital -= commission
                        active_trades[symbol] = {
                            'symbol': symbol,
                            'entry_price': indicators['price'],
                            'entry_time': timestamp,
                            'tp': decision_data['combined_trade_plan']['tp'],
                            'sl': decision_data['combined_trade_plan']['sl'],
                            'amount_usd': amount_to_invest,
                            'advisor_score': score,
                            'recovery': score < CONFIG['ADVISOR_BUY_SCORE_THRESHOLD']
                        }
                        if len(active_trades) >= CONFIG['MAX_ACTIVE_TRADES']: break
    return trade_history, capital

def generate_report(trade_history, final_capital, all_data):
    print("\n\n--- Báo cáo kết quả BACKTEST ---")
    if not trade_history:
        print("Không có giao dịch nào.")
        return
    df_trades = pd.DataFrame(trade_history)
    initial_capital = CONFIG['INITIAL_CAPITAL']
    total_trades = len(df_trades)
    win_trades = len(df_trades[df_trades['pnl_usd'] > 0])
    win_rate = (win_trades / total_trades * 100) if total_trades > 0 else 0
    total_pnl_usd = df_trades['pnl_usd'].sum()
    total_pnl_percent = (total_pnl_usd / initial_capital) * 100
    start_time = min(df.index.min() for df in all_data.values())
    end_time = max(df.index.max() for df in all_data.values())
    print(f"Khung thời gian       : {start_time} -> {end_time}")
    print(f"Vốn ban đầu          : ${initial_capital:,.2f}")
    print(f"Vốn cuối cùng         : ${final_capital:,.2f}")
    print(f"Tổng PnL             : ${total_pnl_usd:,.2f} ({total_pnl_percent:.2f}%)")
    print(f"Tổng số lệnh         : {total_trades}")
    print(f"Tỷ lệ thắng          : {win_rate:.2f}%")
    pnl_by_symbol = df_trades.groupby('symbol')['pnl_usd'].sum().sort_values(ascending=False)
    print("\nPnL theo Symbol:")
    print(pnl_by_symbol)
    report_file = os.path.join(current_dir, f"backtest_report_PORTFOLIO_v4_1.csv")
    df_trades.to_csv(report_file, index=False)
    print(f"\nĐã lưu chi tiết vào: {report_file}")

if __name__ == "__main__":
    all_models = load_all_ai_models(CONFIG['SYMBOLS'], CONFIG['INTERVAL'])
    all_data = load_all_historical_data(CONFIG['SYMBOLS'], CONFIG['INTERVAL'], CONFIG['TOTAL_DAYS_TO_TEST'])
    valid_symbols = list(all_models.keys() & all_data.keys())
    print(f"\nChạy backtest trên symbols: {valid_symbols}")
    filtered_data = {sym: df for sym, df in all_data.items() if sym in valid_symbols}
    if filtered_data:
        history, final_capital = run_portfolio_backtest(filtered_data, all_models)
        generate_report(history, final_capital, filtered_data)
    else:
        print("Không có symbol hợp lệ để backtest.")
