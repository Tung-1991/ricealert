# backtest/control_panel.py
# -*- coding: utf-8 -*-
"""
Control Panel for Paper Trading
Version: 1.2.1 - Path & Import Fix
Date: 2025-08-03

CHANGELOG (v1.2.1):
- FIX: Corrected the sys.path and import logic. The panel now correctly imports modules
  from the root project directory and the local `paper_trade.py` file.
- COMPATIBILITY: Ensured all imported variables match the latest paper_trade v8.3.1 definitions.
"""
import os
import sys
import json
from datetime import datetime, timedelta
import pytz
import requests
import uuid
import traceback

# --- CẤU HÌNH ĐƯỜNG DẪN (Đã sửa) ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
sys.path.append(PROJECT_ROOT) # Thêm thư mục gốc (ricealert) vào path

try:
    # Import trực tiếp logic và cấu hình từ paper_trade để đảm bảo đồng bộ
    from paper_trade import (
        close_trade_simulated,
        calculate_total_equity,
        build_report_header,
        TACTICS_LAB, ZONES, INTERVALS_TO_SCAN
    )
except ImportError as e:
    sys.exit(f"Lỗi: Không thể import module `paper_trade`. Hãy chắc chắn file `paper_trade.py` đã được cập nhật lên v8.3.1.\nLỗi chi tiết: {e}")

# --- CÁC HẰNG SỐ VÀ CẤU HÌNH ---
STATE_FILE = os.path.join(BASE_DIR, "paper_data", "paper_trade_state.json")
ENV_FILE = os.path.join(PROJECT_ROOT, ".env")
VIETNAM_TZ = pytz.timezone('Asia/Ho_Chi_Minh')

TACTICS = list(TACTICS_LAB.keys())
ZONES = list(ZONES)
INTERVALS = list(INTERVALS_TO_SCAN)

# --- CÁC HÀM TIỆN ÍCH ---
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
            if not content: return {"cash": 0, "active_trades": [], "trade_history": []}
            return json.loads(content)
    except Exception as e:
        print(f"❌ Lỗi khi đọc file trạng thái: {e}")
        return None

def save_state(state):
    try:
        state_to_save = state.copy()
        for key in ['temp_newly_opened_trades', 'temp_newly_closed_trades']:
            state_to_save.pop(key, None)
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state_to_save, f, indent=4, ensure_ascii=False)
        print("\n✅ Đã lưu lại trạng thái thành công!")
    except Exception as e:
        print(f"❌ Lỗi khi lưu file trạng thái: {e}")

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

def select_from_list(options, prompt):
    for i, option in enumerate(options): print(f"  {i+1}. {option}")
    while True:
        try:
            choice = int(input(prompt))
            if 1 <= choice <= len(options): return options[choice - 1]
            else: print("⚠️ Lựa chọn không hợp lệ.")
        except ValueError:
            print("⚠️ Vui lòng nhập một con số.")

# --- CÁC HÀM CHỨC NĂNG ---
def view_open_trades():
    print("\n--- DANH SÁCH LỆNH ĐANG MỞ (Real-time) ---")
    state = load_state()
    if not state: return None
    
    active_trades = state.get("active_trades", [])
    if not active_trades:
        print(f"💵 Tiền mặt: ${state.get('cash', 0):,.2f}")
        print("ℹ️ Không có lệnh nào đang mở.")
        return None

    symbols_needed = list(set(trade['symbol'] for trade in active_trades))
    prices = {sym: get_current_price(sym) for sym in symbols_needed}
    
    total_equity = calculate_total_equity(state, realtime_prices=prices)
    report_header = build_report_header(state, total_equity)
    print(report_header.replace('**', ''))
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
        if 'stale_override_until' in trade and datetime.now(VIETNAM_TZ) < datetime.fromisoformat(trade['stale_override_until']):
            stale_info = f" 🛡️Gia hạn"

        entry_score, last_score = trade.get('entry_score', 0.0), trade.get('last_score', 0.0)
        score_display = f"{entry_score:,.1f}→{last_score:,.1f}" + ("📉" if last_score < entry_score else "📈" if last_score > entry_score else "")
        zone_display = f"{trade.get('entry_zone', 'N/A')}→{trade.get('last_zone', 'N/A')}" if trade.get('last_zone') != trade.get('entry_zone') else trade.get('entry_zone', 'N/A')
        tactic_info = f"({trade.get('opened_by_tactic')} | {score_display} | {zone_display})"

        line1 = f"{i+1}. {pnl_icon} {symbol}-{trade.get('interval', 'N/A')} {tactic_info} PnL: ${pnl_usd:,.2f} ({pnl_percent:+.2f}%) | Giữ:{holding_hours:.1f}h{dca_info}{tp1_info}{stale_info}"
        current_value = invested_usd + pnl_usd
        line2 = f"    Vốn:${invested_usd:,.2f} -> ${current_value:,.2f} | Entry:{entry_price:.4f} Cur:{current_price:.4f} TP:{trade.get('tp', 0):.4f} SL:{trade.get('sl', 0):.4f}{tsl_info}"

        print(line1)
        print(line2)
    print("-" * 80)
    return active_trades

def close_manual_trades():
    print("\n--- Chức năng: Đóng lệnh thủ công ---")
    state = load_state()
    if not state: return
    active_trades = view_open_trades()
    if not active_trades: return
    try:
        choice = input("\n👉 Nhập số thứ tự của các lệnh cần đóng (ví dụ: 1,3). Nhấn Enter để hủy: ")
        if not choice.strip(): print("Hủy thao tác."); return

        indices_to_close = []
        for part in choice.split(','):
            if part.strip().isdigit():
                index = int(part.strip()) - 1
                if 0 <= index < len(active_trades): indices_to_close.append(index)
                else: print(f"⚠️ Cảnh báo: Số '{part.strip()}' không hợp lệ.")
        if not indices_to_close: print("❌ Không có lựa chọn hợp lệ."); return

        trades_to_process = [active_trades[i] for i in sorted(list(set(indices_to_close)))]
        for trade in trades_to_process:
            print(f"\n⚡️ Đang xử lý đóng lệnh cho {trade['symbol']}...")
            current_price = get_current_price(trade['symbol'])
            if current_price is None:
                print(f"❌ Không thể đóng {trade['symbol']} vì không lấy được giá.")
                continue
            
            success = close_trade_simulated(trade, "Manual Panel", state, current_price)
            if success: print(f"✅ Đã đóng {trade['symbol']} thành công.")
            else: print(f"❌ Đóng {trade['symbol']} thất bại.")
        save_state(state)
    except Exception as e:
        print(f"\n❌ Lỗi không mong muốn: {e}"); traceback.print_exc()

def close_all_trades():
    print("\n--- Chức năng: Đóng TẤT CẢ lệnh ---")
    state = load_state()
    if not state or not state.get("active_trades"):
        print("ℹ️ Không có lệnh nào đang mở để đóng."); return
    if input("⚠️ CẢNH BÁO: Đóng tất cả vị thế? (y/n): ").lower() != 'y':
        print("Hủy thao tác."); return

    trades_to_close = list(state['active_trades'])
    closed_count = 0
    for trade in trades_to_close:
        print(f"\n⚡️ Đang đóng {trade['symbol']}...")
        current_price = get_current_price(trade['symbol'])
        if current_price is None:
            print(f"❌ Không thể đóng {trade['symbol']} vì không lấy được giá. Bỏ qua.")
            continue
        if close_trade_simulated(trade, "All Manual", state, current_price):
            print(f"✅ Đóng {trade['symbol']} thành công."); closed_count += 1
        else: print(f"❌ Đóng {trade['symbol']} thất bại.")
    if closed_count > 0: save_state(state)

def extend_stale_check():
    print("\n--- Chức năng: Gia hạn lệnh ---")
    state = load_state()
    if not state: return
    active_trades = view_open_trades()
    if not active_trades: return
    try:
        choice = input("\n👉 Chọn số lệnh cần gia hạn (Enter để hủy): ")
        if not choice.strip() or not choice.strip().isdigit(): print("Hủy thao tác."); return
        index = int(choice.strip()) - 1
        if not (0 <= index < len(active_trades)): print("❌ Lựa chọn không hợp lệ."); return

        hours = float(input("👉 Nhập số giờ muốn gia hạn (ví dụ: 48): "))
        if hours <= 0: print("❌ Số giờ phải dương."); return

        trade_id_to_update = active_trades[index]['trade_id']
        trade_found = False
        for trade in state['active_trades']:
            if trade['trade_id'] == trade_id_to_update:
                override_until = datetime.now(VIETNAM_TZ) + timedelta(hours=hours)
                trade['stale_override_until'] = override_until.isoformat()
                print(f"\n✅ Lệnh {trade['symbol']} đã được gia hạn đến: {override_until.strftime('%Y-%m-%d %H:%M:%S')}")
                trade_found = True
                break
        
        if trade_found: save_state(state)
        else: print("❌ Không tìm thấy trade để cập nhật. Có thể state đã thay đổi.")

    except ValueError:
        print("❌ Vui lòng nhập một con số hợp lệ.")
    except Exception as e:
        print(f"\n❌ Lỗi không mong muốn: {e}")

def open_manual_trade():
    print("\n--- Chức năng: Mở lệnh mới thủ công ---")
    state = load_state()
    if not state: return
    try:
        print(f"💵 Tiền mặt khả dụng: ${state.get('cash', 0):,.2f}")
        allowed_symbols = parse_env_variable("SYMBOLS_TO_SCAN")
        if not allowed_symbols:
            print("❌ Không đọc được SYMBOLS_TO_SCAN từ file .env."); return

        print("\n--- Bước 1: Chọn thông tin ---")
        symbol = select_from_list(allowed_symbols, "👉 Chọn Symbol: ")
        interval = select_from_list(INTERVALS, "👉 Chọn Interval: ")
        tactic = select_from_list(TACTICS, "👉 Chọn Tactic: ")
        zone = select_from_list(ZONES, "👉 Chọn Vùng (Zone): ")

        print("\n--- Bước 2: Nhập chi tiết ---")
        entry_price = float(input(f"👉 Giá vào lệnh (Entry) cho {symbol}: "))
        tp = float(input("👉 Giá chốt lời (Take Profit): "))
        sl = float(input("👉 Giá cắt lỗ (Stop Loss): "))
        invested_usd = float(input("👉 Số vốn đầu tư (USD): "))

        if not all(x > 0 for x in [entry_price, tp, sl, invested_usd]):
            print("❌ Các giá trị phải dương."); return
        if invested_usd > state.get('cash', 0):
            print(f"❌ Vốn đầu tư (${invested_usd:,.2f}) lớn hơn tiền mặt (${state.get('cash', 0):,.2f})."); return

        new_trade = {
            "trade_id": str(uuid.uuid4()), "symbol": symbol, "interval": interval, "status": "ACTIVE",
            "opened_by_tactic": tactic, "trade_type": "LONG", "entry_price": entry_price,
            "quantity": invested_usd / entry_price, "tp": tp, "sl": sl, "initial_sl": sl,
            "initial_entry": {"price": entry_price, "invested_usd": invested_usd},
            "total_invested_usd": invested_usd, "entry_time": datetime.now(VIETNAM_TZ).isoformat(),
            "entry_score": 9.99, "entry_zone": zone, "last_zone": zone,
            "dca_entries": [], "realized_pnl_usd": 0.0, "last_score": 9.99, "peak_pnl_percent": 0.0,
            "tp1_hit": False, "is_in_warning_zone": False, "partial_closed_by_score": False,
            "profit_taken": False, "tactic_used": [tactic, "Manual_Entry"]
        }

        state['cash'] -= invested_usd
        state.setdefault('active_trades', []).append(new_trade)
        save_state(state)
        print(f"\n✅ ĐÃ TẠO LỆNH MỚI CHO {symbol} VỚI VỐN ${invested_usd:,.2f}")
    except ValueError:
        print("❌ Giá trị nhập không hợp lệ.")
    except Exception as e:
        print(f"\n❌ Lỗi không mong muốn: {e}"); traceback.print_exc()

def main_menu():
    while True:
        print("\n" + "="*12 + " 📊 BẢNG ĐIỀU KHIỂN (PAPER-v8.3) 📊 " + "="*12)
        print("1. Xem tất cả lệnh đang mở")
        print("2. Đóng một hoặc nhiều lệnh thủ công")
        print("3. Đóng TẤT CẢ lệnh đang mở")
        print("4. Gia hạn cho lệnh (bỏ qua 'stale')")
        print("5. Mở lệnh mới thủ công")
        print("0. Thoát")
        print("="*61)
        choice = input("👉 Vui lòng chọn một chức năng: ")
        if choice == '1': view_open_trades()
        elif choice == '2': close_manual_trades()
        elif choice == '3': close_all_trades()
        elif choice == '4': extend_stale_check()
        elif choice == '5': open_manual_trade()
        elif choice == '0': print("👋 Tạm biệt!"); break
        else: print("⚠️ Lựa chọn không hợp lệ.")

if __name__ == "__main__":
    main_menu()
