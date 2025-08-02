# livetrade/control_live_panel.py
# -*- coding: utf-8 -*-
"""
Control Live Panel - Manual Intervention Tool
Version: 1.2.0 - Ultimate Safety
Date: 2025-08-03

CHANGELOG (v1.2.0):
- CRITICAL FIX (Signal Handling): Implemented a signal handler for SIGTSTP (Ctrl+Z).
  This prevents the lock file from being orphaned when the user suspends the process,
  which was the root cause of the panel getting stuck.
- ROBUSTNESS (Auto Backup): The panel now automatically creates a `live_trade_state.json.backup`
  file before any modification, ensuring a safe restore point in case of a crash.
- UX (Timeout Increase): Increased the lock acquisition timeout to 120 seconds, giving users
  more flexibility when the bot is performing a long-running task.
- FIX: Resolved a `KeyError` when closing trades by initializing temporary state keys.
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
import shutil # << THÊM MỚI: Để sao chép file
import signal # << THÊM MỚI: Để xử lý Ctrl+Z

# --- CẤU HÌNH ĐƯỜNG DẪN ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
sys.path.append(PROJECT_ROOT)

try:
    from binance_connector import BinanceConnector
    from live_trade import TRADING_MODE, close_trade_on_binance, get_usdt_fund, TACTICS_LAB, ZONES, INTERVALS_TO_SCAN
except ImportError as e:
    sys.exit(f"Lỗi: Không thể import module cần thiết. Lỗi: {e}")

# --- CÁC HẰNG SỐ VÀ CẤU HÌNH ---
DATA_DIR = os.path.join(BASE_DIR, "data")
STATE_FILE = os.path.join(DATA_DIR, "live_trade_state.json")
BACKUP_FILE = STATE_FILE + ".backup" # << THÊM MỚI: Đường dẫn file backup
LOCK_FILE = STATE_FILE + ".lock"
ENV_FILE = os.path.join(PROJECT_ROOT, ".env")
VIETNAM_TZ = pytz.timezone('Asia/Ho_Chi_Minh')

TACTICS = list(TACTICS_LAB.keys())
ZONES = list(ZONES)
INTERVALS = list(INTERVALS_TO_SCAN)

# --- CÁC HÀM KHÓA FILE VÀ BẢO VỆ ---
def acquire_lock(timeout=120): # << THAY ĐỔI: Tăng timeout lên 120 giây
    """Cố gắng chiếm giữ lock, chờ tối đa 'timeout' giây."""
    start_time = time.time()
    print("⏳ Đang chờ quyền truy cập file trạng thái...")
    while os.path.exists(LOCK_FILE):
        if time.time() - start_time > timeout:
            print(f"❌ Lỗi: Không thể chiếm quyền điều khiển file trạng thái sau {timeout} giây. Bot có thể đang chạy một tác vụ nặng.")
            return False
        time.sleep(0.5)
    try:
        with open(LOCK_FILE, 'w') as f:
            f.write(str(os.getpid()))
        print("✅ Đã có quyền truy cập.")
        return True
    except IOError as e:
        print(f"❌ Lỗi I/O khi tạo file lock: {e}")
        return False

def release_lock():
    """Giải phóng lock."""
    try:
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
            print("✅ Đã giải phóng quyền truy cập file.")
    except OSError as e:
        print(f"❌ Lỗi khi giải phóng file lock: {e}")

def create_backup(): # << THÊM MỚI: Hàm tạo backup
    """Tạo một bản sao lưu của file state."""
    try:
        if os.path.exists(STATE_FILE):
            shutil.copy2(STATE_FILE, BACKUP_FILE)
            print("📋 Đã tạo bản sao lưu an toàn (`.backup`).")
    except Exception as e:
        print(f"⚠️ Cảnh báo: Không thể tạo file sao lưu. Lỗi: {e}")

def handle_exit_signals(signum, frame): # << THÊM MỚI: Hàm xử lý tín hiệu thoát
    """Đảm bảo giải phóng lock khi bị ngắt bởi Ctrl+C hoặc Ctrl+Z."""
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
    except Exception as e:
        print(f"\n⚠️  Không thể lấy giá cho {symbol}: {e}")
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
        for key in ['temp_newly_opened_trades', 'temp_newly_closed_trades', 'temp_money_spent_on_trades', 'temp_pnl_from_closed_trades', 'session_has_events']:
            state_to_save.pop(key, None)
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state_to_save, f, indent=4, ensure_ascii=False)
        print("\n✅ Đã lưu lại trạng thái thành công!")
    except Exception as e:
        print(f"❌ Lỗi khi lưu file trạng thái: {e}")

def select_from_list(options, prompt):
    if not options: return None
    for i, option in enumerate(options): print(f"  {i+1}. {option}")
    while True:
        try:
            choice_str = input(prompt)
            if not choice_str: return None
            choice = int(choice_str)
            if 1 <= choice <= len(options): return options[choice - 1]
            else: print("⚠️ Lựa chọn không hợp lệ.")
        except ValueError:
            print("⚠️ Vui lòng nhập một con số.")

# --- CÁC HÀM CHỨC NĂNG ---
def view_open_trades(bnc: BinanceConnector):
    print("\n--- DANH SÁCH LỆNH ĐANG MỞ (Live Real-time) ---")
    state = load_state()
    if not state: return None
    available_usdt, total_usdt = get_usdt_fund(bnc)
    active_trades = state.get("active_trades", [])
    if not active_trades:
        print(f"💵 Tổng USDT trên sàn: ${total_usdt:,.2f} |  Khả dụng: ${available_usdt:,.2f}")
        print("ℹ️ Không có lệnh nào đang mở.")
        return None

    symbols_needed = list(set(trade['symbol'] for trade in active_trades))
    prices = {sym: get_current_price(sym) for sym in symbols_needed}
    value_of_open_positions = sum(float(trade.get('quantity', 0)) * prices.get(trade['symbol'], 0) for trade in active_trades)

    total_equity = total_usdt + value_of_open_positions
    initial_capital = state.get('initial_capital', total_usdt)
    if initial_capital <= 0: initial_capital = total_equity

    pnl_total_usd = total_equity - initial_capital
    pnl_total_percent = (pnl_total_usd / initial_capital) * 100 if initial_capital > 0 else 0
    pnl_icon_total = "🟢" if pnl_total_usd >= 0 else "🔴"

    header_line1 = f"💰 Vốn BĐ: ${initial_capital:,.2f} | 💵 Tiền mặt: ${available_usdt:,.2f}"
    header_line2 = f"📊 Tổng TS: ${total_equity:,.2f} | PnL Tổng: {pnl_icon_total} ${pnl_total_usd:,.2f} ({pnl_total_percent:+.2f}%)"
    print(header_line1)
    print(header_line2)
    print("-" * 80)

    for i, trade in enumerate(active_trades):
        symbol = trade.get('symbol', 'N/A')
        current_price = prices.get(symbol)
        if current_price is None:
            print(f"{i+1}. ⚠️ {symbol} - Không thể lấy giá hiện tại.")
            continue

        entry_price = trade.get('entry_price', 0)
        invested_usd = trade.get('total_invested_usd', 0)
        pnl_percent = ((current_price - entry_price) / entry_price) * 100 if entry_price > 0 else 0
        pnl_usd = invested_usd * (pnl_percent / 100)
        pnl_icon = "🟢" if pnl_usd >= 0 else "🔴"

        holding_hours = (datetime.now(VIETNAM_TZ) - datetime.fromisoformat(trade['entry_time'])).total_seconds() / 3600
        dca_info = f" (DCA:{len(trade.get('dca_entries',[]))})" if trade.get('dca_entries') else ""
        tsl_info = f" TSL:{trade['sl']:.4f}" if "Trailing_SL_Active" in trade.get('tactic_used', []) else ""
        tp1_info = " TP1✅" if trade.get('tp1_hit', False) else ""

        stale_info = ""
        if 'stale_override_until' in trade:
            override_dt = datetime.fromisoformat(trade['stale_override_until'])
            if datetime.now(VIETNAM_TZ) < override_dt:
                stale_info = f" 🛡️Gia hạn"

        entry_score, last_score = trade.get('entry_score', 0.0), trade.get('last_score', 0.0)
        score_display = f"{entry_score:,.1f}→{last_score:,.1f}" + ("📉" if last_score < entry_score else "📈" if last_score > entry_score else "")
        zone_display = f"{trade.get('entry_zone', 'N/A')}→{trade.get('last_zone', 'N/A')}" if trade.get('last_zone') != trade.get('entry_zone') else trade.get('entry_zone', 'N/A')
        tactic_info = f"({trade.get('opened_by_tactic')} | {score_display} | {zone_display})"

        line1 = f"{i+1}. {pnl_icon} {symbol}-{trade.get('interval', 'N/A')} {tactic_info} PnL: ${pnl_usd:,.2f} ({pnl_percent:+.2f}%) | Giữ:{holding_hours:.1f}h{dca_info}{tp1_info}{stale_info}"
        current_value = invested_usd + pnl_usd
        line2 = f"   Vốn:${invested_usd:,.2f} -> ${current_value:,.2f} | Entry:{entry_price:.4f} Cur:{current_price:.4f} TP:{trade.get('tp', 0):.4f} SL:{trade.get('sl', 0):.4f}{tsl_info}"

        print(line1)
        print(line2)
    print("-" * 80)
    return active_trades

def close_manual_trades(bnc: BinanceConnector):
    if not acquire_lock(): return
    try:
        create_backup() # << THÊM MỚI
        print("\n" + "🔥" * 10 + " HÀNH ĐỘNG TRỰC TIẾP TRÊN SÀN BINANCE " + "🔥" * 10)
        print("--- Chức năng: Đóng lệnh thủ công ---")
        state = load_state()
        if not state: return
        
        state['temp_pnl_from_closed_trades'] = 0.0
        state.setdefault('temp_newly_closed_trades', [])

        active_trades = view_open_trades(bnc)
        if not active_trades: return
        
        choice = input("\n👉 Nhập số thứ tự của các lệnh cần đóng (ví dụ: 1,3). Nhấn Enter để hủy: ")
        if not choice.strip():
            print("Hủy thao tác.")
            return

        indices_to_close = []
        for part in choice.split(','):
            if part.strip().isdigit():
                index = int(part.strip()) - 1
                if 0 <= index < len(active_trades):
                    indices_to_close.append(index)
                else:
                    print(f"⚠️ Cảnh báo: Số '{part.strip()}' không hợp lệ.")
        if not indices_to_close:
            print("❌ Không có lựa chọn hợp lệ.")
            return

        trades_to_process = [active_trades[i] for i in sorted(list(set(indices_to_close)), reverse=True)]
        closed_count = 0
        for trade in trades_to_process:
            print(f"\n⚡️ Đang gửi yêu cầu đóng lệnh cho {trade['symbol']}...")
            success = close_trade_on_binance(bnc, trade, "Manual Panel", state)
            if success:
                print(f"✅ Yêu cầu đóng {trade['symbol']} thành công.")
                closed_count += 1
            else:
                print(f"❌ Không thể đóng {trade['symbol']}. Vui lòng kiểm tra log.")
        
        if closed_count > 0:
            save_state(state)

    except Exception as e:
        print(f"\n❌ Lỗi không mong muốn: {e}"); traceback.print_exc()
    finally:
        release_lock()

def close_all_trades(bnc: BinanceConnector):
    if not acquire_lock(): return
    try:
        create_backup() # << THÊM MỚI
        print("\n" + "🔥" * 10 + " HÀNH ĐỘNG TRỰC TIẾP TRÊN SÀN BINANCE " + "🔥" * 10)
        print("--- Chức năng: Đóng TẤT CẢ lệnh ---")
        state = load_state()
        if not state or not state.get("active_trades"):
            print("ℹ️ Không có lệnh nào đang mở để đóng.")
            return
            
        state['temp_pnl_from_closed_trades'] = 0.0
        state.setdefault('temp_newly_closed_trades', [])

        if input("⚠️ CẢNH BÁO: Đóng tất cả vị thế? (y/n): ").lower() != 'y':
            print("Hủy thao tác.")
            return

        trades_to_close, closed_count = list(state['active_trades']), 0
        for trade in trades_to_close:
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
        create_backup() # << THÊM MỚI
        print("\n--- Chức năng: Gia hạn lệnh ---")
        state = load_state()
        if not state: return
        active_trades = view_open_trades(bnc)
        if not active_trades: return
        
        choice = input("\n👉 Chọn số lệnh cần gia hạn (Enter để hủy): ")
        if not choice.strip() or not choice.strip().isdigit():
            print("Hủy thao tác.")
            return
        index = int(choice.strip()) - 1
        if not (0 <= index < len(active_trades)):
            print("❌ Lựa chọn không hợp lệ.")
            return

        hours_input = input("👉 Nhập số giờ muốn gia hạn (ví dụ: 48): ")
        hours = float(hours_input)
        if hours <= 0:
            print("❌ Số giờ phải dương.")
            return

        trade_id_to_update = active_trades[index]['trade_id']
        trade_found = False
        for trade in state['active_trades']:
            if trade['trade_id'] == trade_id_to_update:
                override_until = datetime.now(VIETNAM_TZ) + timedelta(hours=hours)
                trade['stale_override_until'] = override_until.isoformat()
                print(f"\n✅ Lệnh {trade['symbol']} đã được gia hạn đến: {override_until.strftime('%Y-%m-%d %H:%M:%S')}")
                save_state(state)
                trade_found = True
                break
        
        if not trade_found:
            print("❌ Không tìm thấy trade để cập nhật. Có thể state đã thay đổi.")

    except ValueError:
        print("❌ Vui lòng nhập một con số hợp lệ.")
    except Exception as e:
        print(f"\n❌ Lỗi không mong muốn: {e}")
    finally:
        release_lock()

def open_manual_trade(bnc: BinanceConnector):
    if not acquire_lock(): return
    try:
        create_backup() # << THÊM MỚI
        print("\n" + "🔥" * 10 + " HÀNH ĐỘNG TRỰC TIẾP TRÊN SÀN BINANCE " + "🔥" * 10)
        print("--- Chức năng: Mở lệnh mới thủ công ---")
        state = load_state()
        if not state: return
        
        available_usdt, _ = get_usdt_fund(bnc)
        print(f"💵 USDT khả dụng: ${available_usdt:,.2f}")

        allowed_symbols = parse_env_variable("SYMBOLS_TO_SCAN")
        if not allowed_symbols:
            print("❌ Không đọc được SYMBOLS_TO_SCAN từ file .env.")
            return

        print("\n--- Bước 1: Chọn thông tin ---")
        symbol = select_from_list(allowed_symbols, "👉 Chọn Symbol: ")
        if symbol is None: print("Hủy thao tác."); return
        interval = select_from_list(INTERVALS, "👉 Chọn Interval: ")
        if interval is None: print("Hủy thao tác."); return
        tactic = select_from_list(TACTICS, "👉 Chọn Tactic: ")
        if tactic is None: print("Hủy thao tác."); return
        zone = select_from_list(ZONES, "👉 Chọn Vùng (Zone): ")
        if zone is None: print("Hủy thao tác."); return

        print("\n--- Bước 2: Nhập chi tiết ---")
        invested_usd = float(input(f"� Vốn đầu tư (USD): "))
        sl_percent = float(input("👉 Cắt lỗ % (ví dụ: 5): ")) / 100
        rr_ratio = float(input("👉 Tỷ lệ R:R (ví dụ: 2): "))

        if not all(x > 0 for x in [invested_usd, sl_percent, rr_ratio]):
            print("❌ Các giá trị phải dương.")
            return
        if invested_usd > available_usdt:
            print(f"❌ Vốn đầu tư (${invested_usd:,.2f}) lớn hơn USDT khả dụng (${available_usdt:,.2f}).")
            return

        print(f"\n⚡️ Đang gửi yêu cầu mua {invested_usd:,.2f} USD của {symbol}...")
        market_order = bnc.place_market_order(symbol=symbol, side="BUY", quote_order_qty=round(invested_usd, 2))
        if not (market_order and float(market_order.get('executedQty', 0)) > 0):
            print("❌ Lệnh Market không khớp. Response:", market_order)
            return

        filled_qty, filled_cost = float(market_order['executedQty']), float(market_order['cummulativeQuoteQty'])
        avg_price = filled_cost / filled_qty
        print(f"\n✅ Lệnh đã khớp! Giá TB: {avg_price:.4f}, Số lượng: {filled_qty:.8f}")

        sl_p, tp_p = avg_price * (1 - sl_percent), avg_price * (1 + (sl_percent * rr_ratio))

        new_trade = {
            "trade_id": str(uuid.uuid4()), "symbol": symbol, "interval": interval, "status": "ACTIVE",
            "opened_by_tactic": tactic, "trade_type": "LONG", "entry_price": avg_price,
            "quantity": filled_qty, "tp": tp_p, "sl": sl_p, "initial_sl": sl_p,
            "initial_entry": {"price": avg_price, "quantity": filled_qty, "invested_usd": filled_cost},
            "total_invested_usd": filled_cost, "entry_time": datetime.now(VIETNAM_TZ).isoformat(),
            "entry_score": 9.99, "entry_zone": zone, "last_zone": zone,
            "binance_market_order_id": market_order['orderId'], "dca_entries": [],
            "realized_pnl_usd": 0.0, "last_score": 9.99, "peak_pnl_percent": 0.0,
            "tp1_hit": False, "is_in_warning_zone": False, "partial_closed_by_score": False,
            "profit_taken": False, "tactic_used": [tactic, "Manual_Entry"],
            "close_retry_count": 0
        }

        state.setdefault('active_trades', []).append(new_trade)
        save_state(state)
        
    except ValueError:
        print("❌ Giá trị nhập không hợp lệ.")
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
                print("1. Xem tất cả lệnh đang mở")
                print("2. Đóng một hoặc nhiều lệnh thủ công")
                print("3. Đóng TẤT CẢ lệnh đang mở")
                print("4. Gia hạn cho lệnh (bỏ qua 'stale')")
                print("5. Mở lệnh mới thủ công")
                print("0. Thoát")
                print("="*61)
                choice = input("👉 Vui lòng chọn một chức năng: ")
                if choice == '1': view_open_trades(bnc)
                elif choice == '2': close_manual_trades(bnc)
                elif choice == '3': close_all_trades(bnc)
                elif choice == '4': extend_stale_check(bnc)
                elif choice == '5': open_manual_trade(bnc)
                elif choice == '0': print("👋 Tạm biệt!"); break
                else: print("⚠️ Lựa chọn không hợp lệ.")
    except Exception as e:
        print(f"\n🔥🔥🔥 Lỗi nghiêm trọng khi khởi tạo Binance Connector: {e}"); traceback.print_exc()

if __name__ == "__main__":
    # << THÊM MỚI: Đăng ký bộ xử lý tín hiệu
    # Bắt tín hiệu Ctrl+C (SIGINT) và Ctrl+Z (SIGTSTP)
    signal.signal(signal.SIGINT, handle_exit_signals)
    if sys.platform != "win32": # SIGTSTP không có trên Windows
        signal.signal(signal.SIGTSTP, handle_exit_signals)
    
    main_menu()
