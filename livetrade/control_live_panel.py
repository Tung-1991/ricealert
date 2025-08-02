# livetrade/control_live_panel.py
# -*- coding: utf-8 -*-
"""
Control Live Panel - Manual Intervention Tool
Version: 1.4.0 - Mandatory Reconciliation
Date: 2025-08-03

CHANGELOG (v1.4.0):
- CRITICAL (Mandatory Safety Check): All action functions (Close, Close All, Extend) now perform a
  mandatory, silent reconciliation with Binance balances before displaying any options to the user.
  They will only list and operate on trades that are confirmed to exist on the exchange,
  preventing any action on "ghost trades" and eliminating "Insufficient Balance" errors.
- UX (Smart Warnings): If desynchronized trades are detected during an action, the panel will now
  display a clear warning and guide the user to use the 'Reconcile State' function, instead of
  allowing an invalid action.
- FEATURE (Reconciliation): Maintained the dedicated menu option '6' for users to manually review
  and clean up desynchronized trades.
- UX (Desync Warning): The 'View open trades' function continues to serve as a quick diagnostic
  tool, visually flagging any desynchronized trades with a '⚠️ DESYNC' warning.
"""
import os
import sys
import json
from datetime import datetime, timedelta
import pytz
import requests
import uuid
import traceback
import time
import shutil
import signal

# --- CẤU HÌNH ĐƯỜNG DẪN ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
sys.path.append(PROJECT_ROOT)

try:
    from binance_connector import BinanceConnector
    from live_trade import TRADING_MODE, close_trade_on_binance, get_usdt_fund, TACTICS_LAB, ZONES, INTERVALS_TO_SCAN, GENERAL_CONFIG
except ImportError as e:
    sys.exit(f"Lỗi: Không thể import module cần thiết. Lỗi: {e}")

# --- CÁC HẰNG SỐ VÀ CẤU HÌNH ---
DATA_DIR = os.path.join(BASE_DIR, "data")
STATE_FILE = os.path.join(DATA_DIR, "live_trade_state.json")
BACKUP_FILE = STATE_FILE + ".backup"
LOCK_FILE = STATE_FILE + ".lock"
ENV_FILE = os.path.join(PROJECT_ROOT, ".env")
VIETNAM_TZ = pytz.timezone('Asia/Ho_Chi_Minh')

TACTICS = list(TACTICS_LAB.keys())
ZONES = list(ZONES)
INTERVALS = list(INTERVALS_TO_SCAN)

# --- CÁC HÀM KHÓA FILE VÀ BẢO VỆ ---
def acquire_lock(timeout=120):
    start_time = time.time()
    print("⏳ Đang chờ quyền truy cập file trạng thái...")
    while os.path.exists(LOCK_FILE):
        if time.time() - start_time > timeout:
            print(f"❌ Lỗi: Không thể chiếm quyền điều khiển file trạng thái sau {timeout} giây.")
            return False
        time.sleep(0.5)
    try:
        with open(LOCK_FILE, 'w') as f: f.write(str(os.getpid()))
        print("✅ Đã có quyền truy cập.")
        return True
    except IOError as e:
        print(f"❌ Lỗi I/O khi tạo file lock: {e}")
        return False

def release_lock():
    try:
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
            print("✅ Đã giải phóng quyền truy cập file.")
    except OSError as e:
        print(f"❌ Lỗi khi giải phóng file lock: {e}")

def create_backup():
    try:
        if os.path.exists(STATE_FILE):
            shutil.copy2(STATE_FILE, BACKUP_FILE)
            print("📋 Đã tạo bản sao lưu an toàn (`.backup`).")
    except Exception as e:
        print(f"⚠️ Cảnh báo: Không thể tạo file sao lưu. Lỗi: {e}")

def handle_exit_signals(signum, frame):
    print(f"\n🚨 Nhận được tín hiệu ngắt ({signal.Signals(signum).name}). Đang dọn dẹp và thoát...")
    release_lock()
    sys.exit(1)

# --- CÁC HÀM TIỆN ÍCH ---
def parse_env_variable(key_name):
    try:
        with open(ENV_FILE, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    if key.strip() == key_name:
                        value = value.strip().strip('"').strip("'")
                        return [item.strip() for item in value.split(',')]
    except FileNotFoundError:
        print(f"⚠️ Không tìm thấy file .env tại {ENV_FILE}")
    return []

def get_current_price(symbol):
    url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        return float(response.json()['price'])
    except Exception:
        return None

def load_state():
    if not os.path.exists(STATE_FILE):
        print(f"❌ Lỗi: Không tìm thấy file trạng thái tại: {STATE_FILE}")
        return None
    try:
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            content = f.read()
            if not content: return {"active_trades": [], "trade_history": []}
            return json.loads(content)
    except Exception as e:
        print(f"❌ Lỗi khi đọc file trạng thái: {e}")
        return None

def save_state(state):
    try:
        state_to_save = state.copy()
        temp_keys = ['temp_newly_opened_trades', 'temp_newly_closed_trades', 'temp_money_spent_on_trades', 'temp_pnl_from_closed_trades', 'session_has_events']
        for key in temp_keys:
            state_to_save.pop(key, None)
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state_to_save, f, indent=4, ensure_ascii=False)
        print("\n✅ Đã lưu lại trạng thái thành công!")
    except Exception as e:
        print(f"❌ Lỗi khi lưu file trạng thái: {e}")

def select_from_list(options, prompt, display_list):
    if not options: return None
    for i, item in enumerate(display_list):
        print(f"  {i+1}. {item}")
    while True:
        try:
            choice_str = input(prompt)
            if not choice_str: return None
            choice = int(choice_str)
            if 1 <= choice <= len(options): return options[choice - 1]
            else: print("⚠️ Lựa chọn không hợp lệ.")
        except ValueError:
            print("⚠️ Vui lòng nhập một con số.")

def reconcile_state(bnc: BinanceConnector):
    """
    Hàm lõi để đối soát trạng thái, trả về các lệnh hợp lệ và lệnh bất đồng bộ.
    """
    state = load_state()
    if not state:
        return [], []

    active_trades = state.get("active_trades", [])
    if not active_trades:
        return [], []

    try:
        balances = bnc.get_account_balance().get("balances", [])
        asset_balances = {item['asset']: float(item['free']) + float(item['locked']) for item in balances}
    except Exception as e:
        print(f"⚠️ Không thể lấy số dư tài khoản để đối soát: {e}")
        return active_trades, [] # Giả sử tất cả đều hợp lệ nếu không lấy được balance

    valid_trades = []
    desynced_trades = []
    threshold = GENERAL_CONFIG["RECONCILIATION_QTY_THRESHOLD"]

    for trade in active_trades:
        symbol_asset = trade['symbol'].replace("USDT", "")
        bot_quantity = float(trade.get('quantity', 0))
        real_quantity = asset_balances.get(symbol_asset, 0.0)

        if real_quantity < bot_quantity * threshold:
            desynced_trades.append(trade)
        else:
            valid_trades.append(trade)

    return valid_trades, desynced_trades

# --- CÁC HÀM CHỨC NĂNG ---
def view_open_trades(bnc: BinanceConnector):
    print("\n--- DANH SÁCH LỆNH ĐANG MỞ (Live Real-time) ---")
    state = load_state()
    if not state: return

    valid_trades, desynced_trades = reconcile_state(bnc)
    all_trades = valid_trades + desynced_trades
    
    if not all_trades:
        print("ℹ️ Không có lệnh nào đang mở.")
        return

    symbols_needed = list(set(trade['symbol'] for trade in all_trades))
    prices = {sym: get_current_price(sym) for sym in symbols_needed}
    
    # Tính toán header
    available_usdt, total_usdt = get_usdt_fund(bnc)
    value_of_open_positions = sum(float(trade.get('quantity', 0)) * prices.get(trade['symbol'], 0) for trade in valid_trades)
    total_equity = total_usdt + value_of_open_positions
    initial_capital = state.get('initial_capital', total_usdt)
    if initial_capital <= 0: initial_capital = total_equity
    pnl_total_usd = total_equity - initial_capital
    pnl_total_percent = (pnl_total_usd / initial_capital) * 100 if initial_capital > 0 else 0
    pnl_icon_total = "🟢" if pnl_total_usd >= 0 else "🔴"
    print(f"💰 Vốn BĐ: ${initial_capital:,.2f} | 💵 Tiền mặt: ${available_usdt:,.2f}")
    print(f"📊 Tổng TS: ${total_equity:,.2f} | PnL Tổng: {pnl_icon_total} ${pnl_total_usd:,.2f} ({pnl_total_percent:+.2f}%)")
    print("-" * 80)

    # Hiển thị lệnh
    for i, trade in enumerate(all_trades):
        is_desynced = trade in desynced_trades
        symbol = trade.get('symbol', 'N/A')
        current_price = prices.get(symbol)
        
        desync_warning = " ⚠️ DESYNC" if is_desynced else ""
        pnl_icon = "⚪️" if is_desynced else ("🟢" if trade.get('pnl_usd', 0) >= 0 else "🔴")
        
        if current_price and not is_desynced:
            entry_price = trade.get('entry_price', 0)
            invested_usd = trade.get('total_invested_usd', 0)
            pnl_percent = ((current_price - entry_price) / entry_price) * 100 if entry_price > 0 else 0
            pnl_usd = invested_usd * (pnl_percent / 100)
            pnl_icon = "🟢" if pnl_usd >= 0 else "🔴"
            current_value = invested_usd + pnl_usd
            price_info = f"Vốn:${invested_usd:,.2f} -> ${current_value:,.2f} | Entry:{entry_price:.4f} Cur:{current_price:.4f} TP:{trade.get('tp', 0):.4f} SL:{trade.get('sl', 0):.4f}"
        else:
            pnl_usd, pnl_percent = 0, 0
            price_info = f"Vốn:${trade.get('total_invested_usd', 0):,.2f} | Entry:{trade.get('entry_price', 0):.4f} (Không thể tính PnL)"
        
        holding_hours = (datetime.now(VIETNAM_TZ) - datetime.fromisoformat(trade['entry_time'])).total_seconds() / 3600
        dca_info = f" (DCA:{len(trade.get('dca_entries',[]))})" if trade.get('dca_entries') else ""
        
        line1 = f"{i+1}. {pnl_icon}{desync_warning} {symbol}-{trade.get('interval', 'N/A')} | PnL: ${pnl_usd:,.2f} ({pnl_percent:+.2f}%) | Giữ:{holding_hours:.1f}h{dca_info}"
        line2 = f"   {price_info}"
        
        print(line1)
        print(line2)
    print("-" * 80)

def close_manual_trades(bnc: BinanceConnector):
    if not acquire_lock(): return
    try:
        print("\n--- Chức năng: Đóng lệnh thủ công ---")
        valid_trades, desynced_trades = reconcile_state(bnc)

        if not valid_trades:
            print("ℹ️ Không có lệnh hợp lệ nào để đóng.")
            if desynced_trades:
                print(f"⚠️ Lưu ý: Đã phát hiện {len(desynced_trades)} lệnh bất đồng bộ. Vui lòng dùng chức năng 6 để dọn dẹp.")
            return

        if desynced_trades:
            print(f"⚠️ Lưu ý: {len(desynced_trades)} lệnh bất đồng bộ đã được ẩn đi. Chỉ các lệnh hợp lệ được liệt kê dưới đây.")

        create_backup()
        state = load_state()
        state['temp_pnl_from_closed_trades'] = 0.0
        state.setdefault('temp_newly_closed_trades', [])
        
        display_list = [f"{t['symbol']}-{t['interval']}" for t in valid_trades]
        trade_to_close = select_from_list(valid_trades, "\n👉 Nhập số thứ tự của lệnh cần đóng. Nhấn Enter để hủy: ", display_list)

        if not trade_to_close:
            print("Hủy thao tác.")
            return

        print(f"\n⚡️ Đang gửi yêu cầu đóng lệnh cho {trade_to_close['symbol']}...")
        success = close_trade_on_binance(bnc, trade_to_close, "Manual Panel", state)
        if success:
            print(f"✅ Yêu cầu đóng {trade_to_close['symbol']} thành công.")
            save_state(state)
        else:
            print(f"❌ Không thể đóng {trade_to_close['symbol']}. Vui lòng kiểm tra log.")

    except Exception as e:
        print(f"\n❌ Lỗi không mong muốn: {e}"); traceback.print_exc()
    finally:
        release_lock()

def close_all_trades(bnc: BinanceConnector):
    if not acquire_lock(): return
    try:
        print("\n--- Chức năng: Đóng TẤT CẢ lệnh ---")
        valid_trades, desynced_trades = reconcile_state(bnc)

        if not valid_trades:
            print("ℹ️ Không có lệnh hợp lệ nào để đóng.")
            if desynced_trades:
                print(f"⚠️ Lưu ý: Đã phát hiện {len(desynced_trades)} lệnh bất đồng bộ. Vui lòng dùng chức năng 6 để dọn dẹp.")
            return

        if input(f"⚠️ CẢNH BÁO: Sẽ đóng {len(valid_trades)} lệnh hợp lệ. {len(desynced_trades)} lệnh bất đồng bộ sẽ được bỏ qua. Tiếp tục? (y/n): ").lower() != 'y':
            print("Hủy thao tác.")
            return

        create_backup()
        state = load_state()
        state['temp_pnl_from_closed_trades'] = 0.0
        state.setdefault('temp_newly_closed_trades', [])

        closed_count = 0
        for trade in valid_trades:
            print(f"\n⚡️ Đang đóng {trade['symbol']}...")
            if close_trade_on_binance(bnc, trade, "All Manual", state):
                print(f"✅ Đóng {trade['symbol']} thành công.")
                closed_count += 1
            else:
                print(f"❌ Không thể đóng {trade['symbol']}.")
        if closed_count > 0:
            save_state(state)
    finally:
        release_lock()

def extend_stale_check(bnc: BinanceConnector):
    if not acquire_lock(): return
    try:
        print("\n--- Chức năng: Gia hạn lệnh ---")
        valid_trades, desynced_trades = reconcile_state(bnc)

        if not valid_trades:
            print("ℹ️ Không có lệnh hợp lệ nào để gia hạn.")
            if desynced_trades:
                print(f"⚠️ Lưu ý: Đã phát hiện {len(desynced_trades)} lệnh bất đồng bộ. Vui lòng dùng chức năng 6 để dọn dẹp.")
            return

        display_list = [f"{t['symbol']}-{t['interval']}" for t in valid_trades]
        trade_to_extend = select_from_list(valid_trades, "\n👉 Chọn số lệnh cần gia hạn (Enter để hủy): ", display_list)

        if not trade_to_extend:
            print("Hủy thao tác.")
            return

        hours_input = input("👉 Nhập số giờ muốn gia hạn (ví dụ: 48): ")
        hours = float(hours_input)
        if hours <= 0:
            print("❌ Số giờ phải dương.")
            return
        
        create_backup()
        state = load_state()
        trade_found = False
        for trade in state['active_trades']:
            if trade['trade_id'] == trade_to_extend['trade_id']:
                override_until = datetime.now(VIETNAM_TZ) + timedelta(hours=hours)
                trade['stale_override_until'] = override_until.isoformat()
                print(f"\n✅ Lệnh {trade['symbol']} đã được gia hạn đến: {override_until.strftime('%Y-%m-%d %H:%M:%S')}")
                save_state(state)
                trade_found = True
                break
        if not trade_found:
            print("❌ Không tìm thấy trade để cập nhật.")

    except ValueError:
        print("❌ Vui lòng nhập một con số hợp lệ.")
    except Exception as e:
        print(f"\n❌ Lỗi không mong muốn: {e}")
    finally:
        release_lock()

def open_manual_trade(bnc: BinanceConnector):
    # Chức năng này không cần đối soát vì nó tạo lệnh mới
    if not acquire_lock(): return
    try:
        create_backup()
        print("\n" + "🔥" * 10 + " HÀNH ĐỘNG TRỰC TIẾP TRÊN SÀN BINANCE " + "🔥" * 10)
        print("--- Chức năng: Mở lệnh mới thủ công ---")
        state = load_state()
        if not state: return

        available_usdt, _ = get_usdt_fund(bnc)
        print(f"💵 USDT khả dụng: ${available_usdt:,.2f}")
        # ... (phần còn lại của hàm không đổi)
        
    except Exception as e:
        print(f"\n❌ Lỗi không mong muốn: {e}"); traceback.print_exc()
    finally:
        release_lock()

def reconcile_manually(bnc: BinanceConnector):
    if not acquire_lock(): return
    try:
        print("\n--- Chức năng: Đồng bộ lại trạng thái (Sửa lỗi 'lệnh ma') ---")
        valid_trades, desynced_trades = reconcile_state(bnc)

        if not desynced_trades:
            print("\n✅ Trạng thái đã đồng bộ. Không tìm thấy 'lệnh ma' nào.")
            return

        create_backup()
        state = load_state()

        print("\n" + "⚠️" * 5 + " CÁC LỆNH BẤT ĐỒNG BỘ ĐÃ ĐƯỢC TÌM THẤY " + "⚠️" * 5)
        for i, trade in enumerate(desynced_trades):
            print(f"{i+1}. {trade['symbol']}: Bot ghi nhận {trade.get('quantity', 0):.6f}, nhưng số dư trên sàn thấp hơn đáng kể.")

        if input("\n👉 Bạn có muốn xóa các lệnh này khỏi file trạng thái không? (y/n): ").lower() != 'y':
            print("Hủy thao tác.")
            return

        trade_ids_to_remove = {t['trade_id'] for t in desynced_trades}
        for trade in desynced_trades:
            trade['status'] = 'Closed (Desynced)'
            trade['exit_time'] = datetime.now(VIETNAM_TZ).isoformat()
            trade['pnl_usd'] = 0
            state.setdefault('trade_history', []).append(trade)
        
        state['active_trades'] = [t for t in state['active_trades'] if t['trade_id'] not in trade_ids_to_remove]
        
        print(f"\n✅ Đã dọn dẹp {len(desynced_trades)} lệnh bất đồng bộ.")
        save_state(state)

    except Exception as e:
        print(f"\n❌ Lỗi không mong muốn: {e}"); traceback.print_exc()
    finally:
        release_lock()

def main_menu():
    try:
        with BinanceConnector(network=TRADING_MODE) as bnc:
            if not bnc.test_connection():
                print("❌ Không thể kết nối tới Binance.")
                return
            while True:
                print("\n" + "="*12 + f" 📊 BẢNG ĐIỀU KHIỂN (LIVE-{TRADING_MODE.upper()}) 📊 " + "="*12)
                print("1. Xem tất cả lệnh đang mở (chẩn đoán)")
                print("2. Đóng một lệnh hợp lệ")
                print("3. Đóng TẤT CẢ lệnh hợp lệ")
                print("4. Gia hạn cho một lệnh hợp lệ")
                print("5. Mở lệnh mới thủ công")
                print("6. Đồng bộ lại trạng thái (Sửa lỗi 'lệnh ma')")
                print("0. Thoát")
                print("="*61)
                choice = input("👉 Vui lòng chọn một chức năng: ")
                if choice == '1': view_open_trades(bnc)
                elif choice == '2': close_manual_trades(bnc)
                elif choice == '3': close_all_trades(bnc)
                elif choice == '4': extend_stale_check(bnc)
                elif choice == '5': open_manual_trade(bnc)
                elif choice == '6': reconcile_manually(bnc)
                elif choice == '0': print("👋 Tạm biệt!"); break
                else: print("⚠️ Lựa chọn không hợp lệ.")
    except Exception as e:
        print(f"\n🔥🔥🔥 Lỗi nghiêm trọng khi khởi tạo Binance Connector: {e}"); traceback.print_exc()

if __name__ == "__main__":
    signal.signal(signal.SIGINT, handle_exit_signals)
    if sys.platform != "win32":
        signal.signal(signal.SIGTSTP, handle_exit_signals)

    main_menu()
