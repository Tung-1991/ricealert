# livetrade/control_live.py
# -*- coding: utf-8 -*-
# Version: 7.4.0 - FINAL FIX

import os
import sys
import json
import uuid
import time
import requests
import pytz
import pandas as pd
import traceback
import shutil
import signal
import csv
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
        get_price_data_with_cache,
        close_trade_on_binance,
        export_trade_history_to_csv
    )
    from trade_advisor import get_advisor_decision, FULL_CONFIG as ADVISOR_BASE_CONFIG
except ImportError as e:
    sys.exit(f"❌ Lỗi: Không thể import module cần thiết: {e}.")

# --- CÁC HẰNG SỐ ---
DATA_DIR = os.path.join(BASE_DIR, "data")
STATE_FILE = os.path.join(DATA_DIR, "live_trade_state.json")
TRADE_HISTORY_CSV_FILE = os.path.join(DATA_DIR, "live_trade_history.csv")
LOCK_FILE = STATE_FILE + ".lock"
ENV_FILE = os.path.join(PROJECT_ROOT, ".env")
VIETNAM_TZ = pytz.timezone('Asia/Ho_Chi_Minh')
TACTICS = list(TACTICS_LAB.keys())
INTERVALS = list(INTERVALS_TO_SCAN)

# --- CÁC HÀM TIỆN ÍCH & KHÓA FILE ---
def format_price_dynamically(price: float) -> str:
    if price is None or pd.isna(price): return "N/A"
    try:
        price_f = float(price)
        if price_f >= 1.0: return f"${price_f:,.4f}"
        return f"${price_f:,.8f}"
    except (ValueError, TypeError):
        return "N/A"

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
        try: os.remove(LOCK_FILE)
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

# --- CÁC HÀM CHỨC NĂNG MENU ---

def refresh_market_data_for_panel():
    print("\n... Đang tải dữ liệu thị trường mới nhất...")
    all_symbols_in_env = parse_env_variable("SYMBOLS_TO_SCAN")
    if not all_symbols_in_env:
        print("⚠️ Không tìm thấy symbol nào trong file .env để tải dữ liệu.")
        return
    for symbol in all_symbols_in_env:
        indicator_results.setdefault(symbol, {})
        price_dataframes.setdefault(symbol, {})
        for interval in ["1h", "4h", "1d"]:
            df = get_price_data_with_cache(symbol, interval, GENERAL_CONFIG["DATA_FETCH_LIMIT"])
            if df is not None and not df.empty:
                indicator_results[symbol][interval] = calculate_indicators(df.copy(), symbol, interval)
                price_dataframes[symbol][interval] = df
    print("... Tải dữ liệu hoàn tất ...")

def show_full_dashboard(bnc: BinanceConnector):
    print("\n" + "="*80)
    print(f"📊 BÁO CÁO TỔNG QUAN & RADAR THỊ TRƯỜNG - {datetime.now(VIETNAM_TZ).strftime('%H:%M %d-%m-%Y')} 📊")
    state = load_state()
    if not state:
        print("❌ Không thể tải file trạng thái.")
        return

    # Dọn dẹp các key tạm thời để hàm build_dynamic_alert_text không hiển thị thông tin cũ
    state.pop('temp_newly_opened_trades', None)
    state.pop('temp_newly_closed_trades', None)

    # Lấy dữ liệu cần thiết
    valid_trades, desynced_trades = reconcile_state(bnc, state)
    available_usdt, total_usdt = get_usdt_fund(bnc)

    # Cập nhật lại state chỉ với các lệnh hợp lệ để tính toán
    state['active_trades'] = valid_trades

    active_symbols = {t['symbol'] for t in valid_trades}
    realtime_prices = {s: get_current_price(s) for s in active_symbols if s}

    # Tính toán Equity
    equity = calculate_total_equity(state, total_usdt, realtime_prices)
    if equity is None:
        print("❌ Lỗi khi tính toán tổng tài sản. Vui lòng thử lại.")
        return

    # --- SỬ DỤNG HÀM BÁO CÁO GỐC TỪ live_trade.py ---
    report_content = build_dynamic_alert_text(state, total_usdt, available_usdt, realtime_prices, equity)
    print(report_content.replace('**', '').replace('`', ''))

    # Xử lý riêng các lệnh bất đồng bộ (nếu có)
    if desynced_trades:
        print("\n" + "---" * 10 + " ⚠️ LỆNH BẤT ĐỒNG BỘ (LỆNH MA) ⚠️ " + "---" * 10)
        print("Các lệnh này có trong file trạng thái nhưng không có trên sàn. Dùng chức năng 10 để dọn dẹp.")
        for trade in desynced_trades:
            print(f"  ⚪️ {trade.get('symbol', 'N/A')}-{trade.get('interval', 'N/A')} | Tactic: {trade.get('opened_by_tactic', 'N/A')}")
        print("-" * 80)

    # --- PHẦN RADAR THỊ TRƯỜNG ĐÃ NÂNG CẤP ---
    if input("\n👉 Hiển thị Radar thị trường? (y/n): ").lower() != 'y':
        print("="*80)
        return

    print("\n" + "---" * 10 + " 📡 RADAR QUÉT THỊ TRƯỜNG 📡 " + "---" * 10)
    refresh_market_data_for_panel()
    symbols_to_scan = parse_env_variable("SYMBOLS_TO_SCAN")
    symbols_in_trades = {t['symbol'] for t in (valid_trades + desynced_trades)}

    if not symbols_to_scan:
        print("ℹ️ Không có symbol nào trong .env để quét.")
    else:
        # Import hàm get_extreme_zone_adjustment_coefficient từ live_trade
        from live_trade import get_extreme_zone_adjustment_coefficient

        for symbol in symbols_to_scan:
            trade_status_tag = " [MỞ]" if symbol in symbols_in_trades else ""
            print(f"\n--- {symbol}{trade_status_tag} ---")

            price_str = "N/A"
            temp_indicators = indicator_results.get(symbol, {}).get("1h")
            if temp_indicators and temp_indicators.get('price'):
                price_str = format_price_dynamically(temp_indicators.get('price')).replace("$", "")
            print(f"  Giá hiện tại: ${price_str}")

            for interval in ["1h", "4h", "1d"]:
                indicators = indicator_results.get(symbol, {}).get(interval)
                if not indicators:
                    print(f"  ⚪️ [{interval}]: Không có dữ liệu để phân tích.")
                    continue

                zone = determine_market_zone_with_scoring(symbol, interval)

                best_raw_score, best_final_score, best_tactic, entry_threshold = 0, 0, "N/A", "N/A"
                final_mtf_coeff, final_ez_coeff = 1.0, 1.0

                for tactic_name, tactic_cfg in TACTICS_LAB.items():
                    optimal_zones = tactic_cfg.get("OPTIMAL_ZONE", [])
                    if not isinstance(optimal_zones, list): optimal_zones = [optimal_zones]

                    if zone in optimal_zones:
                        decision = get_advisor_decision(symbol, interval, indicators, ADVISOR_BASE_CONFIG, weights_override=tactic_cfg.get("WEIGHTS"))
                        raw_score = decision.get("final_score", 0.0)

                        mtf_coeff = get_mtf_adjustment_coefficient(symbol, interval)

                        ez_coeff = 1.0
                        if tactic_cfg.get("USE_EXTREME_ZONE_FILTER", False):
                            ez_coeff = get_extreme_zone_adjustment_coefficient(indicators, interval)

                        final_score = raw_score * mtf_coeff * ez_coeff

                        if final_score > best_final_score:
                            best_raw_score, best_final_score, best_tactic = raw_score, final_score, tactic_name
                            entry_threshold = tactic_cfg.get("ENTRY_SCORE", "N/A")
                            final_mtf_coeff, final_ez_coeff = mtf_coeff, ez_coeff

                if best_raw_score == 0:
                    decision = get_advisor_decision(symbol, interval, indicators, ADVISOR_BASE_CONFIG)
                    best_raw_score = decision.get("final_score", 0.0)
                    final_mtf_coeff = get_mtf_adjustment_coefficient(symbol, interval)
                    final_ez_coeff = 1.0
                    best_final_score = best_raw_score * final_mtf_coeff * final_ez_coeff
                    best_tactic = "Default"

                is_strong_signal = isinstance(entry_threshold, (int, float)) and best_final_score >= entry_threshold
                icon = "🟢" if is_strong_signal else ("🟡" if best_final_score >= 5.5 else "🔴")

                # <<< THAY ĐỔI Ở ĐÂY: Hiển thị đầy đủ, không ẩn đi nữa >>>
                adjustment_display = f"MTF x{final_mtf_coeff:.2f} EZ x{final_ez_coeff:.2f}"

                score_display = f"Gốc: {best_raw_score:.2f} | Cuối: {best_final_score:.2f} ({adjustment_display})"
                print(f"  {icon} [{interval}]: Zone: {zone.ljust(10)} | {score_display} | Tactic: {best_tactic} (Ngưỡng: {entry_threshold})")
    print("="*80)



# Dán đè hàm này vào control_live.py

def view_csv_history():
    print("\n--- 📜 20 Giao dịch cuối cùng (từ file CSV) 📜 ---")
    
    # --- Step 1: Logic đọc file an toàn, "bê" nguyên từ csv_viewer.py ---
    if not os.path.exists(TRADE_HISTORY_CSV_FILE):
        print(f"❌ Lỗi: Không tìm thấy file lịch sử tại '{TRADE_HISTORY_CSV_FILE}'")
        return

    try:
        # Cấu trúc CSV chuẩn mà chúng ta muốn
        CORRECT_HEADER = [
            "trade_id", "symbol", "interval", "status", "opened_by_tactic",
            "tactic_used", "trade_type", "entry_price", "exit_price", "tp", "sl",
            "initial_sl", "total_invested_usd", "pnl_usd", "pnl_percent",
            "entry_time", "exit_time", "holding_duration_hours", "entry_score",
            "last_score", "dca_entries", "partial_pnl_details", "realized_pnl_usd", 
            "binance_market_order_id", "entry_zone", "last_zone", "initial_entry"
        ]
        # Tìm vị trí cột mới để chèn vào dữ liệu cũ
        PARTIAL_PNL_DETAILS_INDEX = CORRECT_HEADER.index('partial_pnl_details')

        all_rows_normalized = []
        with open(TRADE_HISTORY_CSV_FILE, 'r', encoding='utf-8', newline='') as f:
            reader = csv.reader(f)
            header_from_file = next(reader, None) # Đọc header để bỏ qua
            
            # Đọc từng dòng và chuẩn hóa
            for i, row in enumerate(reader, 2):
                if not row: continue # Bỏ qua dòng trống
                
                # Đây là các dòng cũ trước khi thêm cột partial_pnl_details
                if len(row) == 26: 
                    row.insert(PARTIAL_PNL_DETAILS_INDEX, None)
                    all_rows_normalized.append(row)
                # Đây là các dòng mới đã có đủ cột
                elif len(row) == 27:
                    all_rows_normalized.append(row)
                else:
                    # Bỏ qua các dòng không hợp lệ khác
                    print(f"⚠️ Cảnh báo: Bỏ qua dòng {i} không hợp lệ với {len(row)} cột.")

        if not all_rows_normalized:
            print("ℹ️ Không có dữ liệu hợp lệ nào được tìm thấy trong file CSV.")
            return

        # Tạo DataFrame từ dữ liệu đã được làm sạch 100%
        df = pd.DataFrame(all_rows_normalized, columns=CORRECT_HEADER)
        print(f"✅ Đã tải và chuẩn hóa thành công {len(df)} bản ghi. Đang xử lý...")
        
    except Exception as e:
        print(f"🔥🔥 Lỗi nghiêm trọng khi đọc và chuẩn hóa file CSV: {e}")
        traceback.print_exc()
        return

    # --- Step 2: Logic xử lý và hiển thị, lấy phần tốt nhất từ cả hai file ---
    try:
        if df.empty:
            print("ℹ️ File lịch sử trống sau khi chuẩn hóa.")
            return
            
        # Chuyển đổi các cột số
        numeric_cols = [
            'entry_price', 'exit_price', 'pnl_usd', 'pnl_percent',
            'holding_duration_hours', 'entry_score', 'last_score'
        ]
        for col in numeric_cols:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # Sắp xếp theo thời gian một cách chính xác
        df['exit_time_dt'] = pd.to_datetime(df['exit_time'], errors='coerce')
        df.sort_values(by='exit_time_dt', ascending=False, inplace=True)

        # Chỉ lấy 20 dòng đầu tiên SAU KHI đã sắp xếp
        df_display = df.head(20).copy()

        # Hàm helper để parse JSON an toàn
        def parse_json_like_string(s):
            if pd.isna(s) or not isinstance(s, str) or not s.strip(): return {}
            try:
                return json.loads(s.replace("'", '"'))
            except json.JSONDecodeError:
                return {}

        # Tạo các cột hiển thị
        df_display['Vốn'] = df_display.apply(lambda r: parse_json_like_string(r.get('initial_entry', '{}')).get('invested_usd', r.get('total_invested_usd')), axis=1)
        df_display['Time Close'] = df_display['exit_time_dt'].dt.tz_convert(VIETNAM_TZ).dt.strftime('%m-%d %H:%M')
        df_display['Vốn'] = pd.to_numeric(df_display['Vốn'], errors='coerce').apply(lambda x: f"${x:,.2f}" if pd.notna(x) else "N/A")
        df_display['Giá vào'] = df_display['entry_price'].apply(lambda p: format_price_dynamically(p).replace('$', ''))
        df_display['Giá ra'] = df_display['exit_price'].apply(lambda p: format_price_dynamically(p).replace('$', ''))
        df_display['pnl_usd'] = df_display['pnl_usd'].apply(lambda x: f"${x:+.2f}" if pd.notna(x) else "N/A")
        df_display['PnL %'] = df_display['pnl_percent'].apply(lambda x: f"{x:+.2f}%" if pd.notna(x) else "N/A")
        df_display['Hold (h)'] = df_display['holding_duration_hours'].apply(lambda x: f"{x:.2f}" if pd.notna(x) else "N/A")
        df_display['Score'] = df_display.apply(lambda r: f"{r.get('entry_score', 0.0):.1f}→{r.get('last_score', 0.0):.1f}" if pd.notna(r.get('entry_score')) and pd.notna(r.get('last_score')) else "N/A", axis=1)
        df_display['Zone'] = df_display.apply(lambda r: f"{r.get('entry_zone', 'N/A')}→{r.get('last_zone', 'N/A')}" if pd.notna(r.get('last_zone')) and r.get('entry_zone') != r.get('last_zone') else r.get('entry_zone', 'N/A'), axis=1)
        df_display.rename(columns={'opened_by_tactic': 'Tactic'}, inplace=True)
        
        # Chọn cột cuối cùng để hiển thị
        final_order = ['Time Close', 'symbol', 'interval', 'Giá vào', 'Giá ra', 'Vốn', 'pnl_usd', 'PnL %', 'Hold (h)', 'Score', 'Zone', 'Tactic', 'status']
        df_final_display = df_display[[c for c in final_order if c in df_display.columns]]

        # In ra kết quả
        print(df_final_display.to_string(index=False))

    except Exception as e:
        print(f"🔥🔥 Lỗi khi xử lý và hiển thị DataFrame: {e}")
        traceback.print_exc()


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
    if not os.path.exists(TRADE_HISTORY_CSV_FILE):
        print("ℹ️ Không tìm thấy file trade_history.csv.")
        return
    try:
        df = pd.read_csv(TRADE_HISTORY_CSV_FILE)
        df['pnl_usd'] = pd.to_numeric(df['pnl_usd'], errors='coerce')
        df.dropna(subset=['pnl_usd', 'opened_by_tactic'], inplace=True)
        df = df[df['status'].str.contains('Closed', na=False, case=False)]

        if df.empty:
            print("ℹ️ Không có dữ liệu hợp lệ để phân tích hiệu suất.")
            return

        grouped = df.groupby('opened_by_tactic').agg(
            Total_Trades=('pnl_usd', 'count'),
            Total_PnL=('pnl_usd', 'sum'),
            Wins=('pnl_usd', lambda x: (x > 0).sum()),
            Avg_Win_PnL=('pnl_usd', lambda x: x[x > 0].mean()),
            Avg_Loss_PnL=('pnl_usd', lambda x: x[x <= 0].mean()),
            # Sửa lỗi cú pháp ở đây: Dùng tên hợp lệ, không có ký tự '$'
            Max_Win=('pnl_usd', lambda x: x[x > 0].max()),
            Max_Loss=('pnl_usd', lambda x: x[x <= 0].min())
        ).fillna(0)

        grouped['Win_Rate_%'] = (grouped['Wins'] / grouped['Total_Trades'] * 100).where(grouped['Total_Trades'] > 0, 0)
        grouped['Payoff_Ratio'] = abs(grouped['Avg_Win_PnL'] / grouped['Avg_Loss_PnL']).where(grouped['Avg_Loss_PnL'] != 0, float('inf'))
        win_rate = grouped['Wins'] / grouped['Total_Trades']
        loss_rate = 1 - win_rate
        grouped['Expectancy_$'] = (win_rate * grouped['Avg_Win_PnL']) + (loss_rate * grouped['Avg_Loss_PnL'])

        total_row = {
            'Tactic': 'TỔNG CỘNG',
            'Total_Trades': df.shape[0],
            'Total_PnL': df['pnl_usd'].sum(),
            'Wins': (df['pnl_usd'] > 0).sum(),
            'Avg_Win_PnL': df[df['pnl_usd'] > 0]['pnl_usd'].mean(),
            'Avg_Loss_PnL': df[df['pnl_usd'] <= 0]['pnl_usd'].mean(),
            'Max_Win': df[df['pnl_usd'] > 0]['pnl_usd'].max(),
            'Max_Loss': df[df['pnl_usd'] <= 0]['pnl_usd'].min()
        }
        total_row['Win_Rate_%'] = (total_row['Wins'] / total_row['Total_Trades'] * 100) if total_row['Total_Trades'] > 0 else 0
        total_row['Payoff_Ratio'] = abs(total_row['Avg_Win_PnL'] / total_row['Avg_Loss_PnL']) if total_row.get('Avg_Loss_PnL') and total_row['Avg_Loss_PnL'] != 0 else float('inf')
        total_win_rate_frac = total_row['Wins'] / total_row['Total_Trades'] if total_row['Total_Trades'] > 0 else 0
        total_row['Expectancy_$'] = (total_win_rate_frac * total_row.get('Avg_Win_PnL', 0)) + ((1 - total_win_rate_frac) * total_row.get('Avg_Loss_PnL', 0))

        total_df = pd.DataFrame([total_row]).set_index('Tactic')
        analysis_df = pd.concat([grouped, total_df.fillna(0)])

        final_df = analysis_df.reset_index().rename(columns={'index': 'Tactic'})

        # Đổi tên cột ở bước cuối cùng để hiển thị, tránh lỗi cú pháp
        final_df.rename(columns={'Max_Win': 'Max_Win_$', 'Max_Loss': 'Max_Loss_$'}, inplace=True)
        final_cols = ['Tactic', 'Total_Trades', 'Win_Rate_%', 'Total_PnL', 'Expectancy_$', 'Payoff_Ratio', 'Avg_Win_PnL', 'Avg_Loss_PnL', 'Max_Win_$', 'Max_Loss_$']

        pd.options.display.float_format = '{:,.2f}'.format
        print("Chú thích:")
        print("  - Expectancy_$: Lợi nhuận kỳ vọng cho mỗi lần vào lệnh bằng Tactic này.")
        print("  - Payoff_Ratio: Khi thắng, bạn ăn được gấp bao nhiêu lần so với khi thua.")
        print("-" * 60)
        print(final_df[final_cols].to_string(index=False))
        pd.options.display.float_format = None
    except Exception as e:
        print(f"⚠️ Lỗi khi phân tích file CSV: {e}")
        traceback.print_exc()
    print("="*80)


def open_manual_trade(bnc: BinanceConnector):
    if not acquire_lock(): return
    try:
        print("\n" + "🔥" * 10 + " MỞ LỆNH MỚI THỦ CÔNG " + "🔥" * 10)
        state = load_state()
        if state is None: return

        available_symbols = parse_env_variable("SYMBOLS_TO_SCAN")
        if not available_symbols: print("❌ Không thể đọc symbol từ .env."); return
        symbol = select_from_list(available_symbols, "👉 Chọn Symbol (Enter để hủy): ", available_symbols)
        if not symbol: return
        interval = select_from_list(INTERVALS, "👉 Chọn Interval (Enter để hủy): ", INTERVALS)
        if not interval: return
        tactic_name = select_from_list(TACTICS, "👉 Chọn Tactic (Enter để hủy): ", TACTICS)
        if not tactic_name: return
        tactic_cfg = TACTICS_LAB.get(tactic_name, {})

        available_usdt, _ = get_usdt_fund(bnc)
        print(f"💵 USDT khả dụng: ${available_usdt:,.2f}")
        invested_amount = float(input(f"👉 Nhập vốn USDT: "))
        min_order_val = GENERAL_CONFIG.get('MIN_ORDER_VALUE_USDT', 11.0)
        if invested_amount > available_usdt or invested_amount < min_order_val:
            print(f"❌ Vốn không hợp lệ (Phải <= ${available_usdt:,.2f} và >= ${min_order_val})."); return

        if input(f"⚠️ Đặt lệnh MUA {symbol} với ${invested_amount:,.2f}? (y/n): ").lower() != 'y': return

        create_backup(STATE_FILE)

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
        # Mấy dòng này không cần thiết nếu state được quản lý tốt, nhưng cứ để cho chắc
        state.setdefault('money_gained_from_trades_last_session', 0.0)
        state.setdefault('temp_pnl_from_closed_trades', 0.0)

        valid_trades, _ = reconcile_state(bnc, state)
        if not valid_trades:
            print("ℹ️ Không có lệnh hợp lệ để đóng.")
            return

        display_list = [f"{t['symbol']}-{t['interval']} (Vốn: ${t.get('total_invested_usd', 0):.2f})" for t in valid_trades]
        trade_to_close = select_from_list(valid_trades, "👉 Chọn lệnh cần đóng (Enter để hủy): ", display_list)
        if not trade_to_close:
            print("Hủy thao tác.")
            return

        create_backup(STATE_FILE)
        print(f"⚡️ Đang yêu cầu đóng lệnh {trade_to_close['symbol']}...")

        # Hàm close_trade_on_binance bên live_trade.py sẽ tự lo việc ghi CSV
        # Mình chỉ cần gọi nó và save state là đủ.
        success = close_trade_on_binance(bnc, trade_to_close, "Panel Manual", state, close_pct=1.0)

        if success:
            print(f"✅ Yêu cầu đóng {trade_to_close['symbol']} đã được xử lý thành công.")
            # ### BỎ ĐOẠN NÀY ĐI, NÓ GÂY DUPLICATE ###
            # closed_trade_data = next((t for t in reversed(state.get('trade_history', [])) if t['trade_id'] == trade_to_close['trade_id']), None)
            # if closed_trade_data:
            #      export_trade_history_to_csv([closed_trade_data])
            # ###########################################
            save_state(state) # Chỉ cần lưu state là đủ
        else:
            print(f"❌ Xử lý yêu cầu đóng {trade_to_close['symbol']} thất bại. Vui lòng kiểm tra log.")
    finally: release_lock()


def close_all_trades(bnc: BinanceConnector):
    if not acquire_lock(): return
    try:
        state = load_state()
        if not state: return
        state.setdefault('money_gained_from_trades_last_session', 0.0)
        state.setdefault('temp_pnl_from_closed_trades', 0.0)
        valid_trades, _ = reconcile_state(bnc, state)
        if not valid_trades:
            print("ℹ️ Không có lệnh hợp lệ để đóng.")
            return
        if input(f"⚠️ CẢNH BÁO: Sẽ đóng {len(valid_trades)} lệnh. Tiếp tục? (y/n): ").lower() != 'y':
            print("Hủy thao tác.")
            return

        create_backup(STATE_FILE)
        closed_for_csv = []
        for trade in list(valid_trades):
            if close_trade_on_binance(bnc, trade, "Panel Close All", state, close_pct=1.0):
                closed_trade_data = next((t for t in reversed(state.get('trade_history', [])) if t['trade_id'] == trade['trade_id']), None)
                if closed_trade_data:
                    closed_for_csv.append(closed_trade_data)
        if closed_for_csv:
            export_trade_history_to_csv(closed_for_csv)
            save_state(state)
            print(f"✅ Đã xử lý đóng {len(closed_for_csv)} lệnh.")
        else:
            print("ℹ️ Không có lệnh nào được đóng thành công.")
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

def adopt_orphan_asset(bnc: BinanceConnector):
    if not acquire_lock(): return
    try:
        print("\n" + "🐾" * 10 + " CHỨC NĂNG NHẬN NUÔI TÀI SẢN " + "🐾" * 10)
        print("Chức năng này đăng ký một tài sản đã có trên sàn vào hệ thống quản lý của bot.")
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

        print("\n" + "="*20 + "\nXEM LẠI THÔNG TIN LỆNH SẮP TẠO:\n" + json.dumps(new_trade, indent=2) + "\n" + "="*20)
        if input("\n⚠️ Xác nhận thêm lệnh này vào hệ thống? (y/n): ").lower() != 'y':
            print("Hủy thao tác."); return

        create_backup(STATE_FILE)
        state['active_trades'].append(new_trade)
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
        if not desynced_trades:
            print("\n✅ Trạng thái đã đồng bộ, không có 'lệnh ma'.")
            return

        create_backup(STATE_FILE)
        print("\n" + "⚠️" * 5 + " CÁC LỆNH BẤT ĐỒNG BỘ ĐÃ TÌM THẤY " + "⚠️" * 5)
        for i, trade in enumerate(desynced_trades): print(f"{i+1}. {trade['symbol']}")
        if input("\n👉 Xóa các lệnh này khỏi danh sách đang mở? (y/n): ").lower() != 'y': return

        trade_ids_to_remove = {t['trade_id'] for t in desynced_trades}
        closed_for_csv = []
        for trade in desynced_trades:
            trade.update({'status': 'Closed (Desynced by Panel)', 'exit_time': datetime.now(VIETNAM_TZ).isoformat(), 'pnl_usd': 0, 'pnl_percent': 0})
            state.setdefault('trade_history', []).append(trade)
            closed_for_csv.append(trade)
        state['active_trades'] = [t for t in state['active_trades'] if t['trade_id'] not in trade_ids_to_remove]

        export_trade_history_to_csv(closed_for_csv)
        save_state(state)
        print(f"✅ Đã xóa {len(closed_for_csv)} 'lệnh ma' và cập nhật lịch sử.")

    finally: release_lock()

def sell_manual_assets(bnc: BinanceConnector):
    print("\n" + "🗑️" * 10 + " CÔNG CỤ BÁN COIN LẺ " + "🗑️" * 10)
    print("Chức năng này bán coin trên sàn và KHÔNG ảnh hưởng đến state của bot.")
    print("LƯU Ý: live_trade sẽ tự động hiểu đây là một khoản NẠP TIỀN, vì tài sản này không thuộc quản lý của bot.")
    try:
        print("\n... Đang lấy số dư và giá từ Binance...")
        account = bnc.get_account_balance()
        if not account: print("❌ Không thể lấy số dư."); return
        balances = {b['asset']: float(b['free']) for b in account.get('balances', []) if float(b['free']) > 0}
        env_symbols = parse_env_variable("SYMBOLS_TO_SCAN")
        env_assets = {s.replace("USDT", "") for s in env_symbols}
        assets_to_check = {asset: qty for asset, qty in balances.items() if asset in env_assets and asset not in ['USDT', 'BNB']}
        if not assets_to_check: print("\n✅ Không tìm thấy coin lẻ nào (trong danh sách .env) để bán."); return
    except Exception as e: print(f"\n🔥🔥 Lỗi: {e}"); traceback.print_exc()

# --- HÀM MAIN VÀ MENU CHÍNH ---

def main_menu():
    try:
        with BinanceConnector(network=TRADING_MODE) as bnc:
            if not bnc.test_connection(): return
            while True:
                print("\n" + "="*15 + f" 📊 BẢNG ĐIỀU KHIỂN v7.4 (LIVE-{TRADING_MODE.upper()}) 📊 " + "="*15)
                print("--- Xem & Phân tích ---")
                print(" 1. Dashboard & Radar thị trường")
                print(" 2. Xem 20 giao dịch cuối từ CSV")
                print(" 3. Phân tích Hiệu suất Tactic")
                print(" 4. Tạo và gửi báo cáo thủ công")
                print("\n--- Hành động Giao dịch ---")
                print(" 5. Mở lệnh mới thủ công")
                print(" 6. Đóng một lệnh của Bot")
                print(" 7. Đóng TẤT CẢ lệnh của Bot")
                print(" 8. Gia hạn kiểm tra cho một lệnh 'ì'")
                print("\n--- Bảo trì & Tiện ích ---")
                print(" 9. Nhận nuôi Tài sản mồ côi")
                print("10. Đồng bộ lại State (Sửa 'lệnh ma')")
                print("11. Bán coin lẻ trên sàn (Ngoài hệ thống Bot)")
                print("\n 0. Thoát")
                print("="*67)

                choice = input("👉 Vui lòng chọn một chức năng: ")
                menu_actions = {
                    '1': show_full_dashboard, '2': view_csv_history, '3': show_tactic_analysis,
                    '4': manual_report, '5': open_manual_trade, '6': close_manual_trade,
                    '7': close_all_trades, '8': extend_stale_check, '9': adopt_orphan_asset,
                    '10': reconcile_manually, '11': sell_manual_assets,
                }

                if choice == '0':
                    print("👋 Tạm biệt!"); break

                action = menu_actions.get(choice)
                if action:
                    if choice in ['1', '4', '5', '6', '7', '8', '9', '10', '11']:
                        action(bnc)
                    else:
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
