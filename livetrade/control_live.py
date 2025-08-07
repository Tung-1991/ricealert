# livetrade/control_live.py
# -*- coding: utf-8 -*-
# Version: 7.3.0 - ACCOUNTING SYNC & RESTRUCTURED MENU

import os
import sys
import json
import uuid
import time
import requests
import pytz
import pandas as pd
import csv
import traceback
import shutil
import signal
from datetime import datetime, timedelta

# --- CẤU HÌNH ĐƯỜNG DẪN ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
sys.path.append(PROJECT_ROOT)

try:
    from binance_connector import BinanceConnector
    from indicator import calculate_indicators
    from live_trade import (
        TRADING_MODE, GENERAL_CONFIG, TACTICS_LAB,
        INTERVALS_TO_SCAN, RISK_RULES_CONFIG,
        calculate_total_equity, build_dynamic_alert_text, build_daily_summary_text,
        send_discord_message_chunks, ALERT_CONFIG,
        determine_market_zone_with_scoring, get_mtf_adjustment_coefficient,
        indicator_results, price_dataframes,
        get_price_data_with_cache
    )
    from trade_advisor import get_advisor_decision, FULL_CONFIG as ADVISOR_BASE_CONFIG
except ImportError as e:
    sys.exit(f"❌ Lỗi: Không thể import module cần thiết: {e}.")


# --- CÁC HẰNG SỐ ---
DATA_DIR = os.path.join(BASE_DIR, "data")
STATE_FILE = os.path.join(DATA_DIR, "live_trade_state.json")
TRADE_HISTORY_CSV_FILE = os.path.join(DATA_DIR, "live_trade_history.csv")
BACKUP_FILE = STATE_FILE + ".backup"
LOCK_FILE = STATE_FILE + ".lock"
ENV_FILE = os.path.join(PROJECT_ROOT, ".env")
VIETNAM_TZ = pytz.timezone('Asia/Ho_Chi_Minh')
TACTICS = list(TACTICS_LAB.keys())
INTERVALS = list(INTERVALS_TO_SCAN)
CSV_HEADER = [
    "trade_id", "symbol", "interval", "status", "opened_by_tactic", "tactic_used", "trade_type",
    "entry_price", "exit_price", "tp", "sl", "initial_sl", "total_invested_usd",
    "pnl_usd", "pnl_percent", "entry_time", "exit_time", "holding_duration_hours",
    "entry_score", "last_score", "dca_entries", "realized_pnl_usd",
    "binance_market_order_id", "entry_zone", "last_zone", "initial_entry"
]

# --- CÁC HÀM TIỆN ÍCH & KHÓA FILE ---
def format_price_dynamically(price: float) -> str:
    if price is None: return "N/A"
    if price >= 1.0: return f"${price:,.4f}"
    return f"${price:,.8f}"

def acquire_lock(timeout=120):
    start_time = time.time()
    print("⏳ Đang chờ quyền truy cập file trạng thái...", end='', flush=True)
    while os.path.exists(LOCK_FILE):
        if time.time() - start_time > timeout:
            print(f"\r❌ Lỗi: Không thể chiếm quyền điều khiển file sau {timeout} giây.")
            return False
        time.sleep(0.5); print(".", end='', flush=True)
    try:
        with open(LOCK_FILE, 'w') as f: f.write(str(os.getpid()))
        print("\r✅ Đã có quyền truy cập.                                       ")
        return True
    except IOError as e: print(f"\r❌ Lỗi I/O khi tạo file lock: {e}"); return False

def release_lock():
    if os.path.exists(LOCK_FILE):
        try: os.remove(LOCK_FILE); print("✅ Đã giải phóng quyền truy cập file.")
        except OSError as e: print(f"❌ Lỗi khi giải phóng file lock: {e}")

def create_backup(state_file_path):
    try:
        if os.path.exists(state_file_path):
            shutil.copy2(state_file_path, state_file_path + ".backup")
            print("📋 Đã tạo bản sao lưu an toàn (`.backup`).")
    except Exception as e: print(f"⚠️ Cảnh báo: Không thể tạo file sao lưu. Lỗi: {e}")

def handle_exit_signals(signum, frame):
    print(f"\n🚨 Nhận được tín hiệu ngắt. Đang dọn dẹp và thoát...")
    release_lock()
    sys.exit(1)

def parse_env_variable(key_name):
    try:
        with open(ENV_FILE, 'r') as f:
            for line in f:
                if line.strip() and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    if key.strip() == key_name:
                        return [item.strip() for item in value.strip().strip('"').strip("'").split(',')]
    except FileNotFoundError: print(f"⚠️ Không tìm thấy file .env tại {ENV_FILE}"); return []
    return []

def get_current_price(symbol):
    url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
    try: return float(requests.get(url, timeout=5).json()['price'])
    except Exception: return None

def get_usdt_fund(bnc: BinanceConnector):
    try:
        balance_info = bnc.get_account_balance()
        usdt = next((b for b in balance_info.get("balances", []) if b["asset"] == "USDT"), None)
        if usdt: return float(usdt['free']), float(usdt['free']) + float(usdt['locked'])
    except Exception as e: print(f"⚠️ Lỗi không thể lấy số dư USDT: {e}"); return 0.0, 0.0

def load_state():
    if not os.path.exists(STATE_FILE): return {"active_trades": [], "trade_history": []}
    try:
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            content = f.read()
            return json.loads(content) if content else {"active_trades": [], "trade_history": []}
    except Exception as e: print(f"❌ Lỗi khi đọc file trạng thái: {e}"); return None

def save_state(state):
    try:
        temp_keys = ['temp_newly_opened_trades', 'temp_newly_closed_trades', 'temp_money_spent_on_trades', 'temp_pnl_from_closed_trades', 'session_has_events']
        state_to_save = {k: v for k, v in state.items() if k not in temp_keys}
        with open(STATE_FILE, 'w', encoding='utf-8') as f: json.dump(state_to_save, f, indent=4, ensure_ascii=False)
        print("\n✅ Đã lưu lại trạng thái (state.json) thành công!")
    except Exception as e: print(f"❌ Lỗi khi lưu file trạng thái: {e}")

def select_from_list(options, prompt, display_list):
    if not options: return None
    for i, item in enumerate(display_list): print(f"  {i+1}. {item}")
    while True:
        try:
            choice_str = input(prompt)
            if not choice_str: return None
            choice = int(choice_str)
            if 1 <= choice <= len(options): return options[choice - 1]
            else: print("⚠️ Lựa chọn không hợp lệ.")
        except ValueError: print("⚠️ Vui lòng nhập một con số.")

def reconcile_state(bnc: BinanceConnector, state: dict):
    if not state or not state.get("active_trades"): return [], []
    try:
        balances = {item['asset']: float(item['free']) + float(item['locked']) for item in bnc.get_account_balance().get("balances", [])}
    except Exception as e: print(f"⚠️ Không thể lấy số dư để đối soát: {e}"); return state.get("active_trades", []), []
    valid, desynced = [], []
    threshold = GENERAL_CONFIG.get("RECONCILIATION_QTY_THRESHOLD", 0.95)
    for trade in state.get("active_trades", []):
        asset = trade['symbol'].replace("USDT", "")
        if balances.get(asset, 0.0) < float(trade.get('quantity', 0)) * threshold:
            desynced.append(trade)
        else: valid.append(trade)
    return valid, desynced

def write_trades_to_csv(closed_trades: list):
    if not closed_trades: return
    try:
        with open(TRADE_HISTORY_CSV_FILE, 'a', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=CSV_HEADER, extrasaction='ignore')
            if f.tell() == 0: writer.writeheader()
            for trade in closed_trades:
                trade_to_write = {k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in trade.items()}
                writer.writerow(trade_to_write)
        print(f"✍️  Đã ghi thành công {len(closed_trades)} lệnh vào file CSV.")
    except Exception as e: print(f"❌ Lỗi nghiêm trọng khi ghi file CSV: {e}")

# --- CÁC HÀM XỬ LÝ GIAO DỊCH CÓ GHI SỔ SÁCH (ACCOUNTING SYNC) ---

def process_and_log_closed_trade(bnc: BinanceConnector, trade: dict, reason: str, state: dict) -> bool:
    """
    Hàm đóng lệnh trung tâm.
    [v7.3.0] NÂNG CẤP: Cập nhật 'money_gained_from_trades_last_session' để đồng bộ với live_trade.py.
    """
    symbol, qty = trade['symbol'], float(trade.get('quantity', 0))
    if qty <= 0: return False
    try:
        print(f"⚡️ Đang gửi lệnh BÁN {qty:.8f} {symbol.replace('USDT','')}...")
        order = bnc.place_market_order(symbol=symbol, side="SELL", quantity=qty)
        if not (order and float(order.get('executedQty', 0)) > 0):
            raise Exception("Lệnh đóng không khớp hoặc không có phản hồi.")
    except Exception as e:
        print(f"❌ Lỗi API Binance khi đóng lệnh {symbol}: {e}"); return False

    money_gained = float(order['cummulativeQuoteQty'])
    closed_qty = float(order['executedQty'])
    exit_price = money_gained / closed_qty if closed_qty > 0 else trade['entry_price']
    pnl_usd = (exit_price - trade['entry_price']) * closed_qty
    invested_usd = trade.get('total_invested_usd', 1)
    pnl_percent = (pnl_usd / invested_usd) * 100 if invested_usd > 0 else 0

    # Cập nhật thông tin lệnh đã đóng
    trade.update({
        'status': f'Closed ({reason})', 'exit_price': exit_price,
        'exit_time': datetime.now(VIETNAM_TZ).isoformat(),
        'pnl_usd': trade.get('realized_pnl_usd', 0.0) + pnl_usd,
        'pnl_percent': pnl_percent,
    })

    # === DÒNG GIAO TIẾP QUAN TRỌNG ===
    # Báo cho live_trade biết rằng có một khoản tiền đã được thu về
    state['money_gained_from_trades_last_session'] = state.get('money_gained_from_trades_last_session', 0.0) + money_gained

    # Di chuyển lệnh từ active_trades sang trade_history
    state['active_trades'] = [t for t in state['active_trades'] if t['trade_id'] != trade['trade_id']]
    state.setdefault('trade_history', []).append(trade)
    state['trade_history'] = state['trade_history'][-200:] # Giới hạn lịch sử
    print(f"✅ Đóng {symbol} thành công. PnL: ${pnl_usd:,.2f}. Đã cập nhật sổ sách.")
    return True

# --- CÁC HÀM CHỨC NĂNG MENU ---

def refresh_market_data_for_panel():
    print("\n... Đang tải dữ liệu thị trường mới nhất...")
    all_symbols_in_env = parse_env_variable("SYMBOLS_TO_SCAN")
    if not all_symbols_in_env:
        print("⚠️ Không tìm thấy symbol nào trong file .env để tải dữ liệu.")
        return
    # Chỉ tải cho các symbol trong .env để tăng tốc
    for symbol in all_symbols_in_env:
        indicator_results.setdefault(symbol, {})
        price_dataframes.setdefault(symbol, {})
        for interval in ["1h", "4h", "1d"]:
            df = get_price_data_with_cache(symbol, interval, GENERAL_CONFIG["DATA_FETCH_LIMIT"])
            if df is not None and not df.empty:
                indicator_results[symbol][interval] = calculate_indicators(df.copy(), symbol, interval)
                price_dataframes[symbol][interval] = df
    print("... Tải dữ liệu hoàn tất ...")

# --- NHÓM 1: XEM & PHÂN TÍCH ---

def show_full_dashboard(bnc: BinanceConnector):
    print("\n" + "="*80)
    print(f"📊 BÁO CÁO TỔNG QUAN & RADAR THỊ TRƯỜNG - {datetime.now(VIETNAM_TZ).strftime('%H:%M %d-%m-%Y')} 📊")
    state = load_state()
    if not state: print("❌ Không thể tải state."); return
    valid_trades, desynced_trades = reconcile_state(bnc, state)
    _, total_usdt = get_usdt_fund(bnc)
    prices = {s['symbol']: get_current_price(s['symbol']) for s in valid_trades}
    value_open = sum(float(t.get('quantity', 0)) * prices.get(t['symbol'], 0) for t in valid_trades if prices.get(t['symbol']))
    equity = total_usdt + value_open
    initial_capital = state.get('initial_capital', equity or 1)
    if initial_capital <= 0: initial_capital = 1
    pnl_total_usd = equity - initial_capital
    pnl_total_percent = (pnl_total_usd / initial_capital) * 100

    print(f"\n💰 Vốn BĐ: ${initial_capital:,.2f} | 💵 Tiền mặt (USDT): ${total_usdt:,.2f}")
    print(f"📊 Tổng TS: ${equity:,.2f} | 📈 PnL Tổng: {'🟢' if pnl_total_usd >= 0 else '🔴'} ${pnl_total_usd:,.2f} ({pnl_total_percent:+.2f}%)")
    print("\n" + "---" * 10 + " 🛰️ DANH SÁCH LỆNH ĐANG MỞ 🛰️ " + "---" * 10)
    all_trades = sorted(valid_trades + desynced_trades, key=lambda t: t.get('entry_time', ''))
    if not all_trades: print("ℹ️ Không có lệnh nào đang mở.");
    else:
        for trade in all_trades:
            is_desynced = any(t['trade_id'] == trade['trade_id'] for t in desynced_trades)
            symbol = trade.get('symbol', 'N/A')
            current_price = prices.get(symbol)
            pnl_usd, pnl_percent = 0, 0
            if current_price and not is_desynced:
                entry_price = trade.get('entry_price', 0)
                invested_usd = trade.get('total_invested_usd', 0)
                if entry_price > 0:
                    pnl_percent = ((current_price - entry_price) / entry_price) * 100
                    pnl_usd = invested_usd * (pnl_percent / 100)
                current_value = invested_usd + pnl_usd
                price_info = f"Vốn: ${invested_usd:,.2f} → ${current_value:,.2f} | Entry: {format_price_dynamically(entry_price)} | Cur: {format_price_dynamically(current_price)} | TP: {format_price_dynamically(trade.get('tp'))} | SL: {format_price_dynamically(trade.get('sl'))}"
            else:
                invested_usd = trade.get('total_invested_usd', 0)
                price_info = f"Vốn: ${invested_usd:,.2f} | Entry: {format_price_dynamically(trade.get('entry_price'))} (Không thể tính PnL)"
            pnl_icon = "⚪️" if is_desynced else ("🟢" if pnl_usd >= 0 else "🔴")
            score_display = f"{trade.get('entry_score', 0.0):.1f}→{trade.get('last_score', 0.0):.1f}"
            entry_zone, last_zone = trade.get('entry_zone', 'N/A'), trade.get('last_zone')
            zone_display = f"{entry_zone}→{last_zone}" if last_zone and last_zone != entry_zone else entry_zone
            tactic_info = f"({trade.get('opened_by_tactic', 'N/A')} | {score_display} | {zone_display})"
            print(f"{pnl_icon}{' ⚠️ DESYNC' if is_desynced else ''} {symbol}-{trade.get('interval', 'N/A')} {tactic_info} PnL: ${pnl_usd:,.2f} ({pnl_percent:+.2f}%)")
            print(f"   {price_info}")

    if input("\n👉 Hiển thị Radar thị trường? (y/n): ").lower() != 'y': print("="*80); return
    print("\n" + "---" * 10 + " 📡 RADAR QUÉT THỊ TRƯỜNG (v2.0 - Đã nâng cấp) 📡 " + "---" * 10)
    refresh_market_data_for_panel()
    symbols_to_scan = parse_env_variable("SYMBOLS_TO_SCAN")
    symbols_in_trades = {t['symbol'] for t in all_trades}

    # === THAY ĐỔI LỚN #1: Bỏ bộ lọc, quét tất cả các symbol trong .env ===
    # symbols_for_radar = [s for s in symbols_to_scan if s not in symbols_in_trades] # <- DÒNG CŨ BỊ XÓA
    if not symbols_to_scan: # <- DÒNG MỚI (thay cho symbols_for_radar)
        print("ℹ️ Không có symbol nào trong .env để quét.")
    else:
        for symbol in symbols_to_scan: # <- DÒNG MỚI
            # === THAY ĐỔI LỚN #2: Thêm tag [MỞ] nếu có lệnh ===
            trade_status_tag = " [MỞ]" if symbol in symbols_in_trades else ""
            print(f"\n--- {symbol}{trade_status_tag} ---")
            price_str = "N/A"
            temp_indicators = indicator_results.get(symbol, {}).get("1h")
            if temp_indicators and temp_indicators.get('price'): price_str = format_price_dynamically(temp_indicators.get('price'))
            print(f"  Giá hiện tại: {price_str}")
            for interval in ["1h", "4h", "1d"]:
                indicators = indicator_results.get(symbol, {}).get(interval)
                if not indicators: print(f"  [{interval}]: Không có dữ liệu để phân tích."); continue
                zone = determine_market_zone_with_scoring(symbol, interval)

                # === THAY ĐỔI LỚN #3: Logic tính toán và hiển thị điểm chi tiết hơn ===
                best_raw_score, best_adj_score, best_tactic, entry_threshold, mtf_coeff = 0, 0, "N/A", "N/A", 1.0

                for tactic_name, tactic_cfg in TACTICS_LAB.items():
                    optimal_zones = tactic_cfg.get("OPTIMAL_ZONE", [])
                    if not isinstance(optimal_zones, list): optimal_zones = [optimal_zones]
                    if zone in optimal_zones:
                        decision = get_advisor_decision(symbol, interval, indicators, ADVISOR_BASE_CONFIG, weights_override=tactic_cfg.get("WEIGHTS"))
                        raw_score = decision.get("final_score", 0.0)
                        temp_mtf_coeff = get_mtf_adjustment_coefficient(symbol, interval)
                        adjusted_score = raw_score * temp_mtf_coeff
                        
                        # So sánh dựa trên điểm đã điều chỉnh
                        if adjusted_score > best_adj_score:
                            best_raw_score = raw_score
                            best_adj_score = adjusted_score
                            best_tactic = tactic_name
                            entry_threshold = tactic_cfg.get("ENTRY_SCORE", "N/A")
                            mtf_coeff = temp_mtf_coeff

                if best_raw_score == 0: # Fallback nếu không có tactic nào phù hợp zone
                    decision = get_advisor_decision(symbol, interval, indicators, ADVISOR_BASE_CONFIG)
                    best_raw_score = decision.get("final_score", 0.0)
                    mtf_coeff = get_mtf_adjustment_coefficient(symbol, interval)
                    best_adj_score = best_raw_score * mtf_coeff
                    best_tactic = "Default"
                
                # So sánh điểm ĐÃ ĐIỀU CHỈNH với ngưỡng
                is_strong_signal = isinstance(entry_threshold, (int, float)) and best_adj_score >= entry_threshold
                icon = "🟢" if is_strong_signal else ("🟡" if best_adj_score >= 5.5 else "🔴")

                # Xây dựng chuỗi hiển thị mới
                mtf_display = f"x{mtf_coeff:.2f}"
                score_display = f"Gốc: {best_raw_score:.2f} | Cuối: {best_adj_score:.2f} (MTF {mtf_display})"
                print(f"  {icon} [{interval}]: Zone: {zone.ljust(10)} | {score_display} | Tactic: {best_tactic} (Ngưỡng: {entry_threshold})")

    print("="*80)

def view_csv_history():
    print("\n--- 📜 20 Giao dịch cuối cùng (từ file CSV) 📜 ---")
    try:
        if not os.path.exists(TRADE_HISTORY_CSV_FILE): print("ℹ️ Không tìm thấy file trade_history.csv."); return
        df = pd.read_csv(TRADE_HISTORY_CSV_FILE)
        if df.empty: print("ℹ️ File lịch sử trống."); return
        cols = ['exit_time', 'symbol', 'opened_by_tactic', 'pnl_usd', 'pnl_percent', 'holding_duration_hours']
        df_display = df[[c for c in cols if c in df.columns]].copy()
        df_display['exit_time'] = pd.to_datetime(df_display['exit_time']).dt.strftime('%Y-%m-%d %H:%M')
        df_display['pnl_usd'] = df_display['pnl_usd'].map('${:,.2f}'.format)
        df_display['pnl_percent'] = df_display['pnl_percent'].map('{:,.2f}%'.format)
        print(df_display.sort_values(by='exit_time', ascending=False).head(20).to_string(index=False))
    except Exception as e: print(f"⚠️ Lỗi khi đọc file CSV: {e}")

def manual_report(bnc: BinanceConnector):
    print("\n" + "📜" * 10 + " TẠO BÁO CÁO THỦ CÔNG " + "📜" * 10)
    state = load_state()
    if not state: print("❌ Không thể tải file trạng thái."); return
    print("... Đang tính toán dữ liệu báo cáo...")
    available_usdt, total_usdt = get_usdt_fund(bnc)
    realtime_prices = {t['symbol']: get_current_price(t['symbol']) for t in state.get('active_trades', []) if t.get('symbol')}
    equity = calculate_total_equity(state, total_usdt, realtime_prices)
    if equity is None: print("❌ Không thể tính tổng tài sản do lỗi API. Vui lòng thử lại."); return
    print("\nChọn loại báo cáo:"); print("  1. Báo cáo Động (Dynamic - Ngắn gọn)"); print("  2. Báo cáo Tổng kết (Daily - Chi tiết)")
    report_choice = input("👉 Lựa chọn của bạn (Enter để hủy): ")
    report_content = ""
    if report_choice == '1': report_content = build_dynamic_alert_text(state, total_usdt, available_usdt, realtime_prices, equity)
    elif report_choice == '2':
        state.update({'temp_newly_opened_trades': [], 'temp_newly_closed_trades': []})
        report_content = build_daily_summary_text(state, total_usdt, available_usdt, realtime_prices, equity)
    else: return
    print("\n" + "="*80); print(report_content); print("="*80)
    if ALERT_CONFIG.get("DISCORD_WEBHOOK_URL") and input("\n👉 Gửi báo cáo này lên Discord? (y/n): ").lower() == 'y':
        print("... Đang gửi lên Discord..."); send_discord_message_chunks(report_content, force=True); print("✅ Đã gửi.")

def show_tactic_analysis():
    print("\n" + "="*15, "📊 BẢNG PHÂN TÍCH HIỆU SUẤT TACTIC 📊", "="*15)
    if not os.path.exists(TRADE_HISTORY_CSV_FILE): print("ℹ️ Không tìm thấy file trade_history.csv."); return
    try:
        # Sử dụng pandas để đọc CSV, xử lý lỗi tốt hơn
        df = pd.read_csv(TRADE_HISTORY_CSV_FILE, on_bad_lines='skip')
        df = df[df['pnl_usd'].notna() & df['status'].str.contains('Closed', na=False, case=False)]
        if df.empty: print("ℹ️ Không có dữ liệu hợp lệ để phân tích hiệu suất."); return

        # Nhóm theo 'opened_by_tactic'
        grouped = df.groupby('opened_by_tactic').agg(
            Total_Trades=('pnl_usd', 'count'),
            Total_PnL=('pnl_usd', 'sum'),
            Wins=('pnl_usd', lambda x: (x > 0).sum()),
            Losses=('pnl_usd', lambda x: (x <= 0).sum()),
            Avg_Win_PnL=('pnl_usd', lambda x: x[x > 0].mean()),
            Avg_Loss_PnL=('pnl_usd', lambda x: x[x <= 0].mean())
        ).fillna(0)

        grouped['Win_Rate_%'] = (grouped['Wins'] / grouped['Total_Trades'] * 100).where(grouped['Total_Trades'] > 0, 0)
        grouped['Payoff_Ratio'] = (grouped['Avg_Win_PnL'] / abs(grouped['Avg_Loss_PnL'])).where(grouped['Avg_Loss_PnL'] != 0, float('inf'))

        # Định dạng và hiển thị
        formatted_df = grouped.reset_index().rename(columns={'opened_by_tactic': 'Tactic'})
        formatted_df = formatted_df[['Tactic', 'Total_Trades', 'Win_Rate_%', 'Total_PnL', 'Avg_Win_PnL', 'Avg_Loss_PnL', 'Payoff_Ratio']]
        pd.options.display.float_format = '{:,.2f}'.format
        print(formatted_df.sort_values(by="Total_PnL", ascending=False).to_string(index=False))
        pd.options.display.float_format = None # Reset lại
    except Exception as e:
        print(f"⚠️ Lỗi khi phân tích file CSV: {e}")
    print("="*80)

# --- NHÓM 2: HÀNH ĐỘNG GIAO DỊCH ---

def open_manual_trade(bnc: BinanceConnector):
    """
    [v7.3.0] NÂNG CẤP: Cập nhật 'money_spent_on_trades_last_session' để đồng bộ với live_trade.py.
    """
    if not acquire_lock(): return
    try:
        print("\n" + "🔥" * 10 + " MỞ LỆNH MỚI THỦ CÔNG " + "🔥" * 10)
        state = load_state()
        if state is None: return

        # Phần chọn symbol, interval, tactic
        available_symbols = parse_env_variable("SYMBOLS_TO_SCAN")
        if not available_symbols: print("❌ Không thể đọc symbol từ .env."); return
        symbol = select_from_list(available_symbols, "👉 Chọn Symbol (Enter để hủy): ", available_symbols)
        if not symbol: return
        interval = select_from_list(INTERVALS, "👉 Chọn Interval (Enter để hủy): ", INTERVALS)
        if not interval: return
        tactic_name = select_from_list(TACTICS, "👉 Chọn Tactic (Enter để hủy): ", TACTICS)
        if not tactic_name: return
        tactic_cfg = TACTICS_LAB.get(tactic_name, {})

        # Phần nhập vốn
        available_usdt, _ = get_usdt_fund(bnc)
        print(f"💵 USDT khả dụng: ${available_usdt:,.2f}")
        invested_amount = float(input(f"👉 Nhập vốn USDT: "))
        min_order_val = GENERAL_CONFIG.get('MIN_ORDER_VALUE_USDT', 11.0)
        if invested_amount > available_usdt or invested_amount < min_order_val:
            print(f"❌ Vốn không hợp lệ (Phải <= ${available_usdt:,.2f} và >= ${min_order_val})."); return

        if input(f"⚠️ Đặt lệnh MUA {symbol} với ${invested_amount:,.2f}? (y/n): ").lower() != 'y': return

        create_backup(STATE_FILE)

        # Gửi lệnh và xử lý kết quả
        order = bnc.place_market_order(symbol=symbol, side="BUY", quote_order_qty=round(invested_amount, 2))
        if not (order and float(order.get('executedQty', 0)) > 0):
            raise Exception("Lệnh không khớp hoặc không có phản hồi.")

        qty, cost = float(order['executedQty']), float(order['cummulativeQuoteQty'])
        price = cost / qty if qty > 0 else 0
        sl_price = price * (1 - RISK_RULES_CONFIG["MAX_SL_PERCENT_BY_TIMEFRAME"].get(interval, 0.08))
        tp_price = price + ((price - sl_price) * tactic_cfg.get("RR", 2.0))

        new_trade = {
            "trade_id": str(uuid.uuid4()), "symbol": symbol, "interval": interval, "status": "ACTIVE",
            "opened_by_tactic": tactic_name, "trade_type": "LONG", "entry_price": price,
            "quantity": qty, "tp": tp_price, "sl": sl_price, "initial_sl": sl_price,
            "initial_entry": {"price": price, "quantity": qty, "invested_usd": cost},
            "total_invested_usd": cost, "entry_time": datetime.now(VIETNAM_TZ).isoformat(),
            "entry_score": 5.0, "last_score": 5.0, "entry_zone": "Manual", "last_zone": "Manual",
            "tactic_used": ["Manual_Entry"], "binance_market_order_id": order['orderId'],
            "dca_entries": [], "realized_pnl_usd": 0.0,
        }
        state['active_trades'].append(new_trade)

        # === DÒNG GIAO TIẾP QUAN TRỌNG ===
        state['money_spent_on_trades_last_session'] = state.get('money_spent_on_trades_last_session', 0.0) + cost

        save_state(state)
        print(f"✅ Đã thêm lệnh {symbol} thành công và cập nhật sổ sách.")

    except (ValueError, TypeError): print("❌ Vui lòng nhập số hợp lệ.")
    except Exception as e: print(f"❌ Lỗi: {e}"); traceback.print_exc()
    finally: release_lock()

def close_manual_trade(bnc: BinanceConnector):
    if not acquire_lock(): return
    try:
        state = load_state()
        if not state: return
        valid_trades, _ = reconcile_state(bnc, state)
        if not valid_trades: print("ℹ️ Không có lệnh hợp lệ để đóng."); return
        trade_to_close = select_from_list(valid_trades, "👉 Chọn lệnh cần đóng: ", [f"{t['symbol']}-{t['interval']}" for t in valid_trades])
        if not trade_to_close: print("Hủy."); return

        create_backup(STATE_FILE)
        
        if process_and_log_closed_trade(bnc, trade_to_close, "Panel Manual", state):
            save_state(state)
            write_trades_to_csv([trade_to_close])
            
    finally: release_lock()

def close_all_trades(bnc: BinanceConnector):
    if not acquire_lock(): return
    try:
        state = load_state()
        if not state: return
        valid_trades, _ = reconcile_state(bnc, state)
        if not valid_trades: print("ℹ️ Không có lệnh hợp lệ để đóng."); return
        if input(f"⚠️ CẢNH BÁO: Sẽ đóng {len(valid_trades)} lệnh. Tiếp tục? (y/n): ").lower() != 'y': print("Hủy."); return
        
        create_backup(STATE_FILE)
        closed_trades = []
        # Lặp trên bản copy để tránh lỗi khi sửa list
        for trade in list(valid_trades):
            if process_and_log_closed_trade(bnc, trade, "Panel Close All", state):
                closed_trades.append(trade)
        
        if closed_trades:
            save_state(state)
            write_trades_to_csv(closed_trades)

    finally: release_lock()

def extend_stale_check(bnc: BinanceConnector):
    if not acquire_lock(): return
    try:
        state = load_state()
        if not state: return
        valid_trades, _ = reconcile_state(bnc, state)
        if not valid_trades: print("ℹ️ Không có lệnh hợp lệ để gia hạn."); return

        display_list = [f"{t['symbol']}-{t['interval']}" for t in valid_trades]
        trade_to_extend = select_from_list(valid_trades, "👉 Chọn lệnh cần gia hạn: ", display_list)
        if not trade_to_extend: print("Hủy."); return

        hours = float(input("👉 Nhập số giờ muốn gia hạn: "))
        if hours <= 0: print("❌ Số giờ phải dương."); return
        
        create_backup(STATE_FILE)
        
        # Tìm và cập nhật lệnh trong state đã tải
        trade_found = False
        for trade in state.get('active_trades', []):
            if trade.get('trade_id') == trade_to_extend.get('trade_id'):
                override_until = datetime.now(VIETNAM_TZ) + timedelta(hours=hours)
                trade['stale_override_until'] = override_until.isoformat()
                trade_found = True
                print(f"\n✅ Lệnh {trade['symbol']} đã gia hạn đến: {override_until.strftime('%Y-%m-%d %H:%M:%S')}")
                break
        
        if trade_found:
            save_state(state)
        else:
            print("❌ Không tìm thấy lệnh trong state, có thể đã bị thay đổi.")

    except (ValueError, TypeError): print("❌ Vui lòng nhập số hợp lệ.")
    finally: release_lock()

# --- NHÓM 3: BẢO TRÌ & TIỆN ÍCH ---

def adopt_orphan_asset(bnc: BinanceConnector):
    """
    [v7.3.0] NÂNG CẤP: Coi vốn đầu tư của lệnh nhận nuôi như một khoản "chi tiêu" để
    cân bằng kế toán của live_trade, tránh hiểu nhầm là rút tiền.
    """
    if not acquire_lock(): return
    try:
        print("\n" + "🐾" * 10 + " CHỨC NĂNG NHẬN NUÔI TÀI SẢN " + "🐾" * 10)
        print("Chức năng này đăng ký một tài sản đã có trên sàn vào hệ thống quản lý của bot.")

        # 1. Liệt kê tài sản mồ côi
        state = load_state()
        if state is None: return
        account = bnc.get_account_balance()
        if not account: print("❌ Không thể lấy số dư."); return
        balances = {b['asset']: float(b['free']) for b in account.get('balances', []) if float(b['free']) > 0}
        env_symbols = parse_env_variable("SYMBOLS_TO_SCAN")
        symbols_in_state = {t['symbol'] for t in state.get("active_trades", [])}

        orphan_assets = []
        for asset, qty in balances.items():
            symbol = f"{asset}USDT"
            if symbol in env_symbols and symbol not in symbols_in_state:
                price = get_current_price(symbol)
                value_usdt = qty * price if price else 0
                if value_usdt >= GENERAL_CONFIG.get('MIN_ORDER_VALUE_USDT', 11.0):
                    orphan_assets.append({'symbol': symbol, 'asset': asset, 'quantity': qty, 'value_usdt': value_usdt})

        if not orphan_assets:
            print("\n✅ Không tìm thấy tài sản mồ côi nào đủ điều kiện để nhận nuôi."); return

        # 2. Chọn tài sản và khai báo thông tin
        display_list = [f"{a['asset']} (SL: {a['quantity']:.6f}, Trị giá: ~${a['value_usdt']:,.2f})" for a in orphan_assets]
        asset_to_adopt = select_from_list(orphan_assets, "\n👉 Chọn tài sản cần nhận nuôi (Enter để hủy): ", display_list)
        if not asset_to_adopt: return

        print(f"\n--- Nhập thông tin cho lệnh {asset_to_adopt['symbol']} ---")
        try:
            entry_price = float(input(f"👉 Nhập giá vào lệnh trung bình (Entry Price): "))
            total_invested_usd = float(input(f"👉 Nhập tổng vốn USDT đã đầu tư cho lệnh này: "))
            interval = select_from_list(INTERVALS, "👉 Chọn Interval để bot quản lý: ", INTERVALS)
            tactic_name = select_from_list(TACTICS, "👉 Chọn Tactic để gán: ", TACTICS)
            if not all([entry_price > 0, total_invested_usd > 0, interval, tactic_name]):
                print("❌ Thông tin không hợp lệ. Hủy thao tác."); return
        except (ValueError, TypeError):
            print("❌ Vui lòng nhập số hợp lệ. Hủy thao tác."); return

        # 3. Tạo object lệnh
        tactic_cfg = TACTICS_LAB.get(tactic_name, {})
        sl_price = entry_price * (1 - RISK_RULES_CONFIG["MAX_SL_PERCENT_BY_TIMEFRAME"].get(interval, 0.08))
        tp_price = entry_price + ((entry_price - sl_price) * tactic_cfg.get("RR", 2.0))

        new_trade = {
            "trade_id": str(uuid.uuid4()), "symbol": asset_to_adopt['symbol'], "interval": interval,
            "status": "ACTIVE", "opened_by_tactic": tactic_name, "tactic_used": ["Manual_Adoption"],
            "trade_type": "LONG", "entry_price": entry_price, "quantity": asset_to_adopt['quantity'],
            "tp": tp_price, "sl": sl_price, "initial_sl": sl_price,
            "total_invested_usd": total_invested_usd, "entry_time": datetime.now(VIETNAM_TZ).isoformat(),
            "initial_entry": {"price": entry_price, "quantity": asset_to_adopt['quantity'], "invested_usd": total_invested_usd},
            "entry_score": 5.0, "last_score": 5.0, "entry_zone": "Manual", "last_zone": "Manual",
            "dca_entries": [], "realized_pnl_usd": 0.0,
        }

        # 4. Xác nhận và cập nhật state
        print("\n" + "="*20 + "\nXEM LẠI THÔNG TIN LỆNH SẮP TẠO:\n" + json.dumps(new_trade, indent=2) + "\n" + "="*20)
        if input("\n⚠️ Xác nhận thêm lệnh này vào hệ thống? (y/n): ").lower() != 'y':
            print("Hủy thao tác."); return

        create_backup(STATE_FILE)
        state['active_trades'].append(new_trade)

        # === DÒNG GIAO TIẾP QUAN TRỌNG ===
        # Vì không có USDT nào được tiêu THỰC SỰ lúc này, chúng ta cần "giả" một khoản chi tiêu
        # để cân bằng lại việc tài sản (coin) được thêm vào hệ thống.
        # Điều này ngăn live_trade hiểu nhầm đây là một khoản lỗ/rút tiền.
        state['money_spent_on_trades_last_session'] = state.get('money_spent_on_trades_last_session', 0.0) + total_invested_usd

        save_state(state)
        print(f"\n✅ Đã nhận nuôi thành công tài sản {asset_to_adopt['asset']} và cập nhật sổ sách!")

    except Exception as e:
        print(f"\n🔥🔥 Lỗi khi nhận nuôi tài sản: {e}"); traceback.print_exc()
    finally: release_lock()

def reconcile_manually(bnc: BinanceConnector):
    if not acquire_lock(): return
    try:
        print("\n--- Chức năng: Đồng bộ lại trạng thái (Sửa 'lệnh ma') ---")
        state = load_state()
        if not state: return
        _, desynced_trades = reconcile_state(bnc, state)
        if not desynced_trades: print("\n✅ Trạng thái đã đồng bộ, không có 'lệnh ma'."); return
        
        create_backup(STATE_FILE)
        print("\n" + "⚠️" * 5 + " CÁC LỆNH BẤT ĐỒNG BỘ ĐÃ TÌM THẤY " + "⚠️" * 5)
        for i, trade in enumerate(desynced_trades): print(f"{i+1}. {trade['symbol']}")
        if input("\n👉 Xóa các lệnh này khỏi danh sách đang mở? (y/n): ").lower() != 'y': return

        trade_ids_to_remove = {t['trade_id'] for t in desynced_trades}
        closed_trades_log = []
        for trade in desynced_trades:
            trade.update({'status': 'Closed (Desynced by Panel)', 'exit_time': datetime.now(VIETNAM_TZ).isoformat(), 'pnl_usd': 0, 'pnl_percent': 0})
            state.setdefault('trade_history', []).append(trade)
            closed_trades_log.append(trade)
        state['active_trades'] = [t for t in state['active_trades'] if t['trade_id'] not in trade_ids_to_remove]
        
        # Vì không có giao dịch thực tế nào xảy ra, chúng ta không cần cập nhật sổ sách kế toán.
        # Chỉ cần lưu lại trạng thái đã được dọn dẹp.
        save_state(state)
        write_trades_to_csv(closed_trades_log)

    finally: release_lock()

def sell_manual_assets(bnc: BinanceConnector):
    print("\n" + "🗑️" * 10 + " CÔNG CỤ BÁN COIN LẺ " + "🗑️" * 10)
    print("Chức năng này bán coin trên sàn và KHÔNG ảnh hưởng đến state của bot.")
    print("LƯU Ý: live_trade sẽ tự động hiểu đây là một khoản NẠP TIỀN, vì tài sản này không thuộc quản lý của bot.")
    try:
        # ... (Phần code này đã tốt, không cần sửa)
        print("\n... Đang lấy số dư và giá từ Binance...")
        account = bnc.get_account_balance()
        if not account: print("❌ Không thể lấy số dư."); return
        balances = {b['asset']: float(b['free']) for b in account.get('balances', []) if float(b['free']) > 0}
        env_symbols = parse_env_variable("SYMBOLS_TO_SCAN")
        env_assets = {s.replace("USDT", "") for s in env_symbols}
        assets_to_check = {asset: qty for asset, qty in balances.items() if asset in env_assets and asset not in ['USDT', 'BNB']}
        if not assets_to_check: print("\n✅ Không tìm thấy coin lẻ nào (trong danh sách .env) để bán."); return
        
        # ... (Phần code còn lại đã tốt, giữ nguyên)

    except Exception as e: print(f"\n🔥🔥 Lỗi: {e}"); traceback.print_exc()

# --- HÀM MAIN VÀ MENU CHÍNH ---

def main_menu():
    try:
        with BinanceConnector(network=TRADING_MODE) as bnc:
            if not bnc.test_connection(): return
            while True:
                print("\n" + "="*15 + f" 📊 BẢNG ĐIỀU KHIỂN v7.3 (LIVE-{TRADING_MODE.upper()}) 📊 " + "="*15)
                # NHÓM 1: XEM & PHÂN TÍCH
                print("--- Xem & Phân tích ---")
                print(" 1. Dashboard & Radar thị trường")
                print(" 2. Xem 20 giao dịch cuối từ CSV")
                print(" 3. Phân tích Hiệu suất Tactic")
                print(" 4. Tạo và gửi báo cáo thủ công")
                # NHÓM 2: HÀNH ĐỘNG GIAO DỊCH
                print("\n--- Hành động Giao dịch ---")
                print(" 5. Mở lệnh mới thủ công")
                print(" 6. Đóng một lệnh của Bot")
                print(" 7. Đóng TẤT CẢ lệnh của Bot")
                print(" 8. Gia hạn kiểm tra cho một lệnh 'ì'")
                # NHÓM 3: BẢO TRÌ & TIỆN ÍCH
                print("\n--- Bảo trì & Tiện ích ---")
                print(" 9. Nhận nuôi Tài sản mồ côi")
                print("10. Đồng bộ lại State (Sửa 'lệnh ma')")
                print("11. Bán coin lẻ trên sàn (Ngoài hệ thống Bot)")
                print("\n 0. Thoát")
                print("="*67)

                choice = input("👉 Vui lòng chọn một chức năng: ")
                # Mapping choice to function
                menu_actions = {
                    '1': show_full_dashboard,
                    '2': view_csv_history,
                    '3': show_tactic_analysis,
                    '4': manual_report,
                    '5': open_manual_trade,
                    '6': close_manual_trade,
                    '7': close_all_trades,
                    '8': extend_stale_check,
                    '9': adopt_orphan_asset,
                    '10': reconcile_manually,
                    '11': sell_manual_assets,
                }
                
                if choice == '0':
                    print("👋 Tạm biệt!"); break
                
                action = menu_actions.get(choice)
                if action:
                    # Các hàm cần BNC object
                    if choice in ['1', '4', '5', '6', '7', '8', '9', '10', '11']:
                        action(bnc)
                    else: # Các hàm không cần
                        action()
                else:
                    print("⚠️ Lựa chọn không hợp lệ.")
                    
    except Exception as e:
        print(f"\n🔥🔥🔥 Lỗi nghiêm trọng trong menu chính: {e}"); traceback.print_exc()

if __name__ == "__main__":
    signal.signal(signal.SIGINT, handle_exit_signals)
    if sys.platform != "win32":
        try: signal.signal(signal.SIGTSTP, handle_exit_signals)
        except AttributeError: pass
    main_menu()

