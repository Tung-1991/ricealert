# livetrade/control_live.py
# -*- coding: utf-8 -*-
# Version: 7.1.0 - FINAL FUCKING STABLE VERSION + New Features

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
    from live_trade import (
        TRADING_MODE, GENERAL_CONFIG, TACTICS_LAB,
        ZONES, INTERVALS_TO_SCAN, RISK_RULES_CONFIG,
        # --- THÊM CÁC HÀM NÀY VÀO ---
        calculate_total_equity, build_dynamic_alert_text, build_daily_summary_text,
        send_discord_message_chunks, ALERT_CONFIG
    )
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
    except IOError as e:
        print(f"\r❌ Lỗi I/O khi tạo file lock: {e}"); return False

def release_lock():
    if os.path.exists(LOCK_FILE):
        try: os.remove(LOCK_FILE); print("✅ Đã giải phóng quyền truy cập file.")
        except OSError as e: print(f"❌ Lỗi khi giải phóng file lock: {e}")

def create_backup():
    try:
        if os.path.exists(STATE_FILE): shutil.copy2(STATE_FILE, BACKUP_FILE); print("📋 Đã tạo bản sao lưu an toàn (`.backup`).")
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
    except FileNotFoundError:
        print(f"⚠️ Không tìm thấy file .env tại {ENV_FILE}"); return []
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
    except Exception as e:
        print(f"❌ Lỗi khi đọc file trạng thái: {e}"); return None

def save_state(state):
    try:
        temp_keys = ['temp_newly_opened_trades', 'temp_newly_closed_trades', 'temp_money_spent_on_trades', 'temp_pnl_from_closed_trades', 'session_has_events']
        state_to_save = {k: v for k, v in state.items() if k not in temp_keys}
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state_to_save, f, indent=4, ensure_ascii=False)
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

def reconcile_state(bnc: BinanceConnector):
    state = load_state()
    if not state or not state.get("active_trades"): return [], []
    try:
        balances = {item['asset']: float(item['free']) + float(item['locked']) for item in bnc.get_account_balance().get("balances", [])}
    except Exception as e:
        print(f"⚠️ Không thể lấy số dư để đối soát: {e}"); return state.get("active_trades", []), []
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

def process_and_log_closed_trade(bnc, trade, reason, state) -> tuple[bool, float, float]:
    symbol, qty = trade['symbol'], float(trade.get('quantity', 0))
    if qty <= 0: return False, 0.0, 0.0
    try:
        print(f"⚡️ Đang gửi lệnh BÁN {qty:.8f} {symbol.replace('USDT','')}...")
        order = bnc.place_market_order(symbol=symbol, side="SELL", quantity=qty)
        if not (order and float(order.get('executedQty', 0)) > 0):
            raise Exception("Lệnh đóng không khớp hoặc không có phản hồi.")
    except Exception as e:
        print(f"❌ Lỗi API Binance khi đóng lệnh {symbol}: {e}"); return False, 0.0, 0.0

    closed_qty = float(order['executedQty'])
    exit_price = float(order['cummulativeQuoteQty']) / closed_qty if closed_qty > 0 else trade['entry_price']
    pnl_usd = (exit_price - trade['entry_price']) * closed_qty

    trade.update({
        'status': f'Closed ({reason})', 'exit_price': exit_price,
        'exit_time': datetime.now(VIETNAM_TZ).isoformat(),
        'pnl_usd': trade.get('realized_pnl_usd', 0.0) + pnl_usd,
        'pnl_percent': (pnl_usd / trade.get('total_invested_usd', 1)) * 100,
    })

    state['active_trades'] = [t for t in state['active_trades'] if t['trade_id'] != trade['trade_id']]
    state.setdefault('trade_history', []).append(trade)
    print(f"✅ Đóng {symbol} thành công. PnL: ${pnl_usd:,.2f}")
    return True, pnl_usd, trade.get('total_invested_usd', 0)

# --- CÁC CHỨC NĂNG MENU ---
def show_full_dashboard(bnc: BinanceConnector):
    state = load_state()
    if not state: return
    print("\n" + "="*80)
    valid_trades, desynced_trades = reconcile_state(bnc)
    available_usdt, total_usdt = get_usdt_fund(bnc)
    prices = {s['symbol']: get_current_price(s['symbol']) for s in valid_trades}
    value_open = sum(float(t.get('quantity', 0)) * prices.get(t['symbol'], 0) for t in valid_trades)
    equity = total_usdt + value_open
    initial_capital = state.get('initial_capital', equity or 1)
    pnl_total_usd = equity - initial_capital
    pnl_total_percent = (pnl_total_usd / initial_capital) * 100 if initial_capital > 0 else 0
    print(f"📊 BÁO CÁO TỔNG KẾT (LIVE) - {datetime.now(VIETNAM_TZ).strftime('%H:%M %d-%m-%Y')} 📊")
    print(f"💰 Vốn BĐ: ${initial_capital:,.2f} | 💵 Tiền mặt (USDT): ${total_usdt:,.2f}")
    print(f"📊 Tổng TS: ${equity:,.2f} | 📈 PnL Tổng: {'🟢' if pnl_total_usd >= 0 else '🔴'} ${pnl_total_usd:,.2f} ({pnl_total_percent:+.2f}%)")

    print("\n--- DANH SÁCH LỆNH ĐANG MỞ ---")
    all_trades = sorted(valid_trades + desynced_trades, key=lambda t: t.get('entry_time', ''))
    if not all_trades:
        print("ℹ️ Không có lệnh nào đang mở.")
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
                price_info = f"Vốn:${invested_usd:,.2f} -> ${current_value:,.2f} | Entry:{entry_price:.4f} Cur:{current_price:.4f} TP:{trade.get('tp', 0):.4f} SL:{trade.get('sl', 0):.4f}"
            else:
                price_info = f"Vốn:${trade.get('total_invested_usd', 0):,.2f} | Entry:{trade.get('entry_price', 0):.4f} (Không thể tính PnL)"

            pnl_icon = "⚪️" if is_desynced else ("🟢" if pnl_usd >= 0 else "🔴")
            score_display = f"{trade.get('entry_score', 0.0):.1f}→{trade.get('last_score', 0.0):.1f}"

            # Logic hiển thị zone thông minh hơn
            entry_zone = trade.get('entry_zone', 'N/A')
            last_zone = trade.get('last_zone') # Lấy last_zone, có thể là None
            if last_zone and last_zone != entry_zone:
                zone_display = f"{entry_zone}→{last_zone}"
            else:
                zone_display = entry_zone

            tactic_info = f"({trade.get('opened_by_tactic', 'N/A')} | {score_display} | {zone_display})"


            print(f"{pnl_icon}{' ⚠️ DESYNC' if is_desynced else ''} {symbol}-{trade.get('interval', 'N/A')} {tactic_info} PnL: ${pnl_usd:,.2f} ({pnl_percent:+.2f}%)")
            print(f"   {price_info}")
    print("="*80)

def close_manual_trade(bnc: BinanceConnector):
    if not acquire_lock(): return
    try:
        valid_trades, _ = reconcile_state(bnc)
        if not valid_trades: print("ℹ️ Không có lệnh hợp lệ để đóng."); return
        display_list = [f"{t['symbol']}-{t['interval']}" for t in valid_trades]
        trade_to_close = select_from_list(valid_trades, "👉 Chọn lệnh cần đóng: ", display_list)
        if not trade_to_close: print("Hủy."); return
        state = load_state()
        create_backup()
        success, pnl, spent = process_and_log_closed_trade(bnc, trade_to_close, "Panel Manual", state)
        if success:
            state['pnl_closed_last_session'] = state.get('pnl_closed_last_session', 0) + pnl
            state['money_spent_on_trades_last_session'] = 0
            state['usdt_balance_end_of_last_session'], _ = get_usdt_fund(bnc)
            save_state(state)
            write_trades_to_csv([trade_to_close])
    finally: release_lock()

def close_all_trades(bnc: BinanceConnector):
    if not acquire_lock(): return
    try:
        valid_trades, _ = reconcile_state(bnc)
        if not valid_trades: print("ℹ️ Không có lệnh hợp lệ để đóng."); return
        if input(f"⚠️ CẢNH BÁO: Sẽ đóng {len(valid_trades)} lệnh. Tiếp tục? (y/n): ").lower() != 'y':
            print("Hủy."); return
        state = load_state()
        create_backup()
        closed, pnl_session, spent_session = [], 0.0, 0.0
        for trade in list(valid_trades):
            success, pnl, spent = process_and_log_closed_trade(bnc, trade, "Panel Close All", state)
            if success:
                closed.append(trade); pnl_session += pnl; spent_session += spent
        if closed:
            state['pnl_closed_last_session'] = pnl_session
            state['money_spent_on_trades_last_session'] = 0
            state['usdt_balance_end_of_last_session'], _ = get_usdt_fund(bnc)
            save_state(state)
            write_trades_to_csv(closed)
    finally: release_lock()

def extend_stale_check(bnc: BinanceConnector):
    if not acquire_lock(): return
    try:
        valid_trades, _ = reconcile_state(bnc)
        if not valid_trades: print("ℹ️ Không có lệnh hợp lệ để gia hạn."); return
        display_list = [f"{t['symbol']}-{t['interval']}" for t in valid_trades]
        trade_to_extend = select_from_list(valid_trades, "👉 Chọn lệnh cần gia hạn: ", display_list)
        if not trade_to_extend: print("Hủy."); return
        hours = float(input("👉 Nhập số giờ muốn gia hạn: "))
        if hours <= 0: print("❌ Số giờ phải dương."); return
        state = load_state()
        create_backup()
        for trade in state['active_trades']:
            if trade['trade_id'] == trade_to_extend['trade_id']:
                override_until = datetime.now(VIETNAM_TZ) + timedelta(hours=hours)
                trade['stale_override_until'] = override_until.isoformat()
                print(f"\n✅ Lệnh {trade['symbol']} đã gia hạn đến: {override_until.strftime('%Y-%m-%d %H:%M:%S')}")
                save_state(state)
                return
    except (ValueError, TypeError): print("❌ Vui lòng nhập số hợp lệ.")
    finally: release_lock()

def open_manual_trade(bnc: BinanceConnector):
    if not acquire_lock(): return
    try:
        print("\n" + "🔥" * 10 + " MỞ LỆNH MỚI THỦ CÔNG " + "🔥" * 10)
        state = load_state()
        if state is None: return
        available_symbols = parse_env_variable("SYMBOLS_TO_SCAN")
        if not available_symbols: print("❌ Không thể đọc symbol từ .env."); return
        symbol = select_from_list(available_symbols, "👉 Chọn Symbol (Enter để hủy): ", available_symbols)
        if not symbol: print("Hủy."); return
        interval = select_from_list(INTERVALS, "👉 Chọn Interval (Enter để hủy): ", INTERVALS)
        if not interval: print("Hủy."); return
        tactic_name = select_from_list(TACTICS, "👉 Chọn Tactic (Enter để hủy): ", TACTICS)
        if not tactic_name: print("Hủy."); return
        tactic_cfg = TACTICS_LAB.get(tactic_name, {})
        available_usdt, _ = get_usdt_fund(bnc)
        print(f"💵 USDT khả dụng: ${available_usdt:,.2f}")
        invested_amount = float(input(f"👉 Nhập vốn USDT: "))
        if invested_amount > available_usdt: print("❌ Không đủ USDT."); return
        min_order_value = GENERAL_CONFIG.get('MIN_ORDER_VALUE_USDT', 11.0)
        if invested_amount < min_order_value: print(f"❌ Vốn phải >= ${min_order_value}."); return
        if input(f"⚠️ Đặt lệnh MUA {symbol} với ${invested_amount:,.2f}? (y/n): ").lower() != 'y':
            print("Hủy."); return
        create_backup()
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
            "dca_entries": [], "realized_pnl_usd": 0.0, "peak_pnl_percent": 0.0,
            "tp1_hit": False, "close_retry_count": 0
        }
        state['active_trades'].append(new_trade)
        state['pnl_closed_last_session'] = 0.0
        state['money_spent_on_trades_last_session'] = cost
        state['usdt_balance_end_of_last_session'], _ = get_usdt_fund(bnc)
        save_state(state)
        print(f"✅ Đã thêm lệnh {symbol} và cập nhật state kế toán thành công.")
    except (ValueError, TypeError): print("❌ Vui lòng nhập số hợp lệ.")
    except Exception as e: print(f"❌ Lỗi: {e}")
    finally: release_lock()

def reconcile_manually(bnc: BinanceConnector):
    if not acquire_lock(): return
    try:
        print("\n--- Chức năng: Đồng bộ lại trạng thái (Sửa 'lệnh ma') ---")
        _, desynced_trades = reconcile_state(bnc)
        if not desynced_trades: print("\n✅ Trạng thái đã đồng bộ."); return
        state = load_state()
        create_backup()
        print("\n" + "⚠️" * 5 + " CÁC LỆNH BẤT ĐỒNG BỘ ĐÃ TÌM THẤY " + "⚠️" * 5)
        for i, trade in enumerate(desynced_trades): print(f"{i+1}. {trade['symbol']}")
        if input("\n👉 Xóa các lệnh này khỏi danh sách đang mở? (y/n): ").lower() != 'y':
            print("Hủy."); return
        trade_ids_to_remove = {t['trade_id'] for t in desynced_trades}
        for trade in desynced_trades:
            trade.update({'status': 'Closed (Desynced by Panel)', 'exit_time': datetime.now(VIETNAM_TZ).isoformat(), 'pnl_usd': 0})
            state.setdefault('trade_history', []).append(trade)
        state['active_trades'] = [t for t in state['active_trades'] if t['trade_id'] not in trade_ids_to_remove]
        print(f"\n✅ Đã dọn dẹp {len(desynced_trades)} lệnh.")
        state['pnl_closed_last_session'] = 0.0
        state['money_spent_on_trades_last_session'] = 0.0
        state['usdt_balance_end_of_last_session'], _ = get_usdt_fund(bnc)
        save_state(state)
        write_trades_to_csv(desynced_trades)
    finally: release_lock()

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

def sell_manual_assets(bnc: BinanceConnector):
    print("\n" + "🗑️" * 10 + " CÔNG CỤ BÁN COIN LẺ " + "🗑️" * 10)
    print("Chức năng này bán coin trên sàn và KHÔNG ảnh hưởng đến state của bot.")
    try:
        print("\n... Đang lấy số dư và giá từ Binance...")
        account = bnc.get_account_balance()
        if not account:
            print("❌ Không thể lấy số dư."); return

        balances = {b['asset']: float(b['free']) for b in account.get('balances', []) if float(b['free']) > 0}
        
        # Chỉ lấy các coin có trong file .env để tránh bán nhầm
        env_symbols = parse_env_variable("SYMBOLS_TO_SCAN")
        env_assets = {s.replace("USDT", "") for s in env_symbols}
        
        assets_to_check = {asset: qty for asset, qty in balances.items() if asset in env_assets and asset not in ['USDT', 'BNB', 'BUSD', 'FDUSD']}

        if not assets_to_check:
            print("\n✅ Không tìm thấy coin lẻ nào (trong danh sách .env) để bán."); return

        # Lấy giá cho tất cả các coin cần kiểm tra
        all_prices_response = requests.get("https://api.binance.com/api/v3/ticker/price", timeout=10).json()
        prices = {p['symbol']: float(p['price']) for p in all_prices_response}

        print("\n--- DANH SÁCH COIN LẺ CÓ THỂ BÁN ---")
        
        display_list = []
        options = []
        assets_with_info = []

        for asset, qty in assets_to_check.items():
            symbol = f"{asset}USDT"
            price = prices.get(symbol, 0)
            value_usdt = qty * price
            
            info_line = f"{asset} (SL: {qty:.8f}) - Trị giá: ~${value_usdt:,.2f}"
            can_sell = value_usdt >= GENERAL_CONFIG.get('MIN_ORDER_VALUE_USDT', 11.0)
            
            if not can_sell:
                info_line += " (Giá trị quá nhỏ để bán)"
            
            display_list.append(info_line)
            options.append(asset)
            assets_with_info.append({"asset": asset, "qty": qty, "value": value_usdt, "can_sell": can_sell, "symbol": symbol})

        choice_asset_name = select_from_list(options, "\n👉 Chọn coin để bán (Enter để thoát): ", display_list)
        if not choice_asset_name:
            print("Hủy thao tác."); return

        # Tìm thông tin của coin đã chọn
        chosen_asset_info = next((a for a in assets_with_info if a['asset'] == choice_asset_name), None)

        if not chosen_asset_info['can_sell']:
            print(f"❌ Không thể bán {choice_asset_name} vì giá trị của nó quá thấp.")
            return

        if input(f"⚠️ Bán {chosen_asset_info['qty']:.8f} {choice_asset_name}? (y/n): ").lower() != 'y':
            print("Hủy thao tác."); return

        try:
            print(f"\n⚡️ Đang bán {chosen_asset_info['qty']:.8f} {choice_asset_name}...")
            formatted_qty = bnc._format_quantity(chosen_asset_info['symbol'], chosen_asset_info['qty'])
            bnc.place_market_order(symbol=chosen_asset_info['symbol'], side="SELL", quantity=formatted_qty)
            print(f"✅ Gửi lệnh bán thành công.")
        except Exception as e:
            print(f"❌ Không thể bán {choice_asset_name}: {e}")

    except Exception as e:
        print(f"\n🔥🔥 Lỗi: {e}")
        traceback.print_exc()

def manual_report(bnc: BinanceConnector):
    print("\n" + "📜" * 10 + " TẠO BÁO CÁO THỦ CÔNG " + "📜" * 10)
    state = load_state()
    if not state:
        print("❌ Không thể tải file trạng thái.")
        return

    print("... Đang tính toán dữ liệu báo cáo...")
    available_usdt, total_usdt = get_usdt_fund(bnc)
    active_trades = state.get('active_trades', [])
    active_symbols = list(set([t['symbol'] for t in active_trades]))
    realtime_prices = {sym: get_current_price(sym) for sym in active_symbols if sym}

    # Lọc ra những symbol không lấy được giá
    failed_symbols = [sym for sym, price in realtime_prices.items() if price is None]
    if failed_symbols:
        print(f"⚠️ Cảnh báo: Không thể lấy giá của {', '.join(failed_symbols)}. Các coin này sẽ không được tính vào PnL mở.")
        realtime_prices = {sym: price for sym, price in realtime_prices.items() if price is not None}
    
    equity = calculate_total_equity(state, total_usdt, realtime_prices)
    if equity is None:
        print("❌ Không thể tính tổng tài sản do lỗi API. Vui lòng thử lại.")
        return
    
    print("\nChọn loại báo cáo:")
    print("  1. Báo cáo Động (Dynamic - Ngắn gọn)")
    print("  2. Báo cáo Tổng kết (Daily - Chi tiết)")
    report_choice = input("👉 Lựa chọn của bạn (Enter để hủy): ")

    report_content = ""
    if report_choice == '1':
        report_content = build_dynamic_alert_text(state, total_usdt, available_usdt, realtime_prices, equity)
    elif report_choice == '2':
        # Hàm daily summary cần một số key tạm thời, ta tạo chúng rỗng
        state['temp_newly_opened_trades'] = []
        state['temp_newly_closed_trades'] = []
        report_content = build_daily_summary_text(state, total_usdt, available_usdt, realtime_prices, equity)
    else:
        print("Hủy."); return

    print("\n" + "="*80)
    print(report_content)
    print("="*80)

    if ALERT_CONFIG.get("DISCORD_WEBHOOK_URL") and input("\n👉 Gửi báo cáo này lên Discord? (y/n): ").lower() == 'y':
        print("... Đang gửi lên Discord...")
        send_discord_message_chunks(report_content, force=True)
        print("✅ Đã gửi.")
    else:
        print("Không gửi hoặc chưa cấu hình webhook Discord.")

def main_menu():
    try:
        with BinanceConnector(network=TRADING_MODE) as bnc:
            if not bnc.test_connection(): return
            while True:
                print("\n" + "="*12 + f" 📊 BẢNG ĐIỀU KHIỂN (LIVE-{TRADING_MODE.upper()}) 📊 " + "="*12)
                print("1. [Xem] Làm mới Dashboard & Lệnh mở")
                print("2. [Hành động] Đóng một lệnh của Bot")
                print("3. [Hành động] Đóng TẤT CẢ lệnh của Bot")
                print("4. [Hành động] Gia hạn cho một lệnh")
                print("5. [Hành động] Mở lệnh mới cho Bot")
                print("6. [Bảo trì] Đồng bộ lại State (Sửa 'lệnh ma')")
                print("7. [Báo cáo] Xem 20 giao dịch cuối từ CSV")
                print("8. [Dọn dẹp] Bán coin lẻ trên sàn (từ .env)")
                print("9. [Báo cáo] Tạo và gửi báo cáo thủ công")
                print("0. Thoát")
                print("="*61)
                choice = input("👉 Vui lòng chọn một chức năng: ")
                if choice == '1': show_full_dashboard(bnc)
                elif choice == '2': close_manual_trade(bnc)
                elif choice == '3': close_all_trades(bnc)
                elif choice == '4': extend_stale_check(bnc)
                elif choice == '5': open_manual_trade(bnc)
                elif choice == '6': reconcile_manually(bnc)
                elif choice == '7': view_csv_history()
                elif choice == '8': sell_manual_assets(bnc)
                elif choice == '9': manual_report(bnc)
                elif choice == '0': print("👋 Tạm biệt!"); break
                else: print("⚠️ Lựa chọn không hợp lệ.")
    except Exception as e:
        print(f"\n🔥🔥🔥 Lỗi nghiêm trọng: {e}"); traceback.print_exc()

if __name__ == "__main__":
    signal.signal(signal.SIGINT, handle_exit_signals)
    if sys.platform != "win32":
        try:
            signal.signal(signal.SIGTSTP, handle_exit_signals)
        except AttributeError:
            pass
    main_menu()
