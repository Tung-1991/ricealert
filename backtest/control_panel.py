# backtest/control_panel.py
# -*- coding: utf-8 -*-
"""
Control Panel for Paper Trading
Version: 1.3.1 - Enhanced Display Format
Date: 2025-08-03

CHANGELOG (v1.3.1):
- UI/UX: Overhauled the `view_open_trades` function for a much cleaner, more readable,
  and professional multi-line display for each trade, similar to modern trading panels.
- Readability: Each trade's info is now split into three logical lines:
  1. Identification & Tactic Info.
  2. PnL, Duration & Capital Info.
  3. Key Price Levels (Entry, Current, TP, SL).
- This change significantly improves at-a-glance diagnostics.
"""
import os
import sys
import json
from datetime import datetime, timedelta
import pytz
import requests
import uuid
import traceback

# --- CẤU HÌNH ĐƯỜNG DẪN ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
sys.path.append(PROJECT_ROOT)

try:
    from paper_trade import PaperTrader, Config
except ImportError as e:
    sys.exit(f"Lỗi: Không thể import class `PaperTrader` hoặc `Config`.\nLỗi chi tiết: {e}")

# --- CÁC HẰNG SỐ VÀ CẤU HÌNH ---
STATE_FILE = os.path.join(BASE_DIR, "paper_data", "paper_trade_state.json")
ENV_FILE = os.path.join(PROJECT_ROOT, ".env")
VIETNAM_TZ = pytz.timezone('Asia/Ho_Chi_Minh')

TACTICS = list(Config.TACTICS_LAB.keys())
ZONES = Config.ZONES
INTERVALS = Config.INTERVALS_TO_SCAN

# --- CÁC HÀM TIỆN ÍCH ---
def get_current_price(symbol):
    """Lấy giá hiện tại từ Binance."""
    url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        return float(response.json()['price'])
    except Exception as e:
        print(f"\n⚠️  Không thể lấy giá cho {symbol}: {e}")
        return None

def parse_env_variable(key_name):
    """Đọc một biến từ file .env."""
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
    """Hiển thị menu lựa chọn cho người dùng."""
    for i, option in enumerate(options): print(f"  {i+1}. {option}")
    while True:
        try:
            choice = int(input(prompt))
            if 1 <= choice <= len(options): return options[choice - 1]
            else: print("⚠️ Lựa chọn không hợp lệ.")
        except ValueError:
            print("⚠️ Vui lòng nhập một con số.")

def build_simple_header(trader, equity):
    """Tạo header báo cáo đơn giản, mô phỏng lại logic từ paper_trade."""
    initial_capital = trader.state.get('initial_capital', Config.INITIAL_CAPITAL)
    pnl_since_start = equity - initial_capital
    pnl_percent = (pnl_since_start / initial_capital) * 100 if initial_capital > 0 else 0
    pnl_icon = "🟢" if pnl_since_start >= 0 else "🔴"
    header = []
    header.append(f"💰 Vốn BĐ: ${initial_capital:,.2f} | 💵 Tiền mặt: ${trader.state.get('cash', 0):,.2f}")
    header.append(f"📊 Tổng TS: ${equity:,.2f} | 📈 PnL Tổng: {pnl_icon} ${pnl_since_start:,.2f} ({pnl_percent:+.2f}%)")
    return "\n".join(header)

# --- CÁC HÀM CHỨC NĂNG (Đã cập nhật để dùng PaperTrader) ---

def view_open_trades():
    """Hiển thị các lệnh đang mở với định dạng mới, chi tiết và dễ đọc."""
    print("\n--- DANH SÁCH LỆNH ĐANG MỞ (Real-time) ---")
    try:
        trader = PaperTrader()
    except SystemExit as e:
        print(f"❌ Lỗi khi khởi tạo PaperTrader: {e}")
        return None

    active_trades = trader.state.get("active_trades", [])
    if not active_trades:
        print(f"💵 Tiền mặt: ${trader.state.get('cash', 0):,.2f}")
        print("ℹ️ Không có lệnh nào đang mở.")
        return None

    symbols_needed = list(set(trade['symbol'] for trade in active_trades))
    prices = {sym: get_current_price(sym) for sym in symbols_needed}

    total_equity = trader._calculate_total_equity(realtime_prices=prices)
    if total_equity is None:
        print("⚠️ Không thể tính tổng tài sản do thiếu dữ liệu giá.")
        total_equity = trader.state.get('cash', 0) # Fallback

    report_header = build_simple_header(trader, total_equity)
    print(report_header)
    print("-" * 80)

    for i, trade in enumerate(active_trades):
        symbol = trade.get('symbol', 'N/A')
        current_price = prices.get(symbol)
        
        if current_price is None:
            print(f"{i+1}. ⚠️ {symbol} - Không thể lấy giá hiện tại.")
            continue

        pnl_usd, pnl_percent = trader._get_current_pnl(trade, current_price)
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
        
        current_value = trade.get('total_invested_usd', 0) + pnl_usd

        # Định dạng 3 dòng mới
        line1 = f"{i+1}. {pnl_icon} {symbol}-{trade.get('interval', 'N/A')} {tactic_info}"
        line2 = f"    PnL: {pnl_usd:+.2f} ({pnl_percent:+.2f}%) | Giữ: {holding_hours:.1f}h | Vốn: ${trade.get('total_invested_usd', 0):,.2f} -> ${current_value:,.2f}{dca_info}{tp1_info}{stale_info}"
        line3 = f"    Entry: {trade.get('entry_price', 0):.4f} | Cur: {current_price:.4f} | TP: {trade.get('tp', 0):.4f} | SL: {trade.get('sl', 0):.4f}{tsl_info}"

        print(line1)
        print(line2)
        print(line3)
        
    print("-" * 80)
    return active_trades


def close_manual_trades():
    print("\n--- Chức năng: Đóng lệnh thủ công ---")
    active_trades = view_open_trades()
    if not active_trades: return

    try:
        trader = PaperTrader()
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

        trades_to_process = [active_trades[i] for i in sorted(list(set(indices_to_close)))]
        for trade in trades_to_process:
            print(f"\n⚡️ Đang xử lý đóng lệnh cho {trade['symbol']}...")
            current_price = get_current_price(trade['symbol'])
            if current_price is None:
                print(f"❌ Không thể đóng {trade['symbol']} vì không lấy được giá.")
                continue

            success = trader._close_trade_simulated(trade, "Manual Panel", current_price)
            if success:
                print(f"✅ Đã đóng {trade['symbol']} thành công.")
            else:
                print(f"❌ Đóng {trade['symbol']} thất bại.")

        trader._save_state()
        print("\n✅ Đã lưu lại trạng thái thành công!")

    except Exception as e:
        print(f"\n❌ Lỗi không mong muốn: {e}"); traceback.print_exc()

def close_all_trades():
    print("\n--- Chức năng: Đóng TẤT CẢ lệnh ---")
    try:
        trader = PaperTrader()
        if not trader.state.get("active_trades"):
            print("ℹ️ Không có lệnh nào đang mở để đóng.")
            return
        if input("⚠️ CẢNH BÁO: Đóng tất cả vị thế? (y/n): ").lower() != 'y':
            print("Hủy thao tác.")
            return

        trades_to_close = list(trader.state['active_trades'])
        closed_count = 0
        for trade in trades_to_close:
            print(f"\n⚡️ Đang đóng {trade['symbol']}...")
            current_price = get_current_price(trade['symbol'])
            if current_price is None:
                print(f"❌ Không thể đóng {trade['symbol']} vì không lấy được giá. Bỏ qua.")
                continue

            if trader._close_trade_simulated(trade, "All Manual", current_price):
                print(f"✅ Đóng {trade['symbol']} thành công.")
                closed_count += 1
            else:
                print(f"❌ Đóng {trade['symbol']} thất bại.")

        if closed_count > 0:
            trader._save_state()
            print("\n✅ Đã lưu lại trạng thái thành công!")
    except Exception as e:
        print(f"\n❌ Lỗi không mong muốn: {e}"); traceback.print_exc()

def extend_stale_check():
    print("\n--- Chức năng: Gia hạn lệnh ---")
    active_trades = view_open_trades()
    if not active_trades: return
    try:
        trader = PaperTrader()
        choice = input("\n👉 Chọn số lệnh cần gia hạn (Enter để hủy): ")
        if not choice.strip() or not choice.strip().isdigit():
            print("Hủy thao tác.")
            return
        index = int(choice.strip()) - 1
        if not (0 <= index < len(active_trades)):
            print("❌ Lựa chọn không hợp lệ.")
            return

        hours = float(input("👉 Nhập số giờ muốn gia hạn (ví dụ: 48): "))
        if hours <= 0:
            print("❌ Số giờ phải dương.")
            return

        trade_id_to_update = active_trades[index]['trade_id']
        trade_found = False
        for trade in trader.state['active_trades']:
            if trade['trade_id'] == trade_id_to_update:
                override_until = datetime.now(VIETNAM_TZ) + timedelta(hours=hours)
                trade['stale_override_until'] = override_until.isoformat()
                print(f"\n✅ Lệnh {trade['symbol']} đã được gia hạn đến: {override_until.strftime('%Y-%m-%d %H:%M:%S')}")
                trade_found = True
                break

        if trade_found:
            trader._save_state()
            print("\n✅ Đã lưu lại trạng thái thành công!")
        else:
            print("❌ Không tìm thấy trade để cập nhật. Có thể state đã thay đổi.")

    except ValueError:
        print("❌ Vui lòng nhập một con số hợp lệ.")
    except Exception as e:
        print(f"\n❌ Lỗi không mong muốn: {e}")

def open_manual_trade():
    print("\n--- Chức năng: Mở lệnh mới thủ công ---")
    try:
        trader = PaperTrader()
        print(f"💵 Tiền mặt khả dụng: ${trader.state.get('cash', 0):,.2f}")
        allowed_symbols = parse_env_variable("SYMBOLS_TO_SCAN")
        if not allowed_symbols:
            print("❌ Không đọc được SYMBOLS_TO_SCAN từ file .env.")
            return

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
        if invested_usd > trader.state.get('cash', 0):
            print(f"❌ Vốn đầu tư (${invested_usd:,.2f}) lớn hơn tiền mặt (${trader.state.get('cash', 0):,.2f})."); return

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

        trader.state['cash'] -= invested_usd
        trader.state.setdefault('active_trades', []).append(new_trade)
        trader._save_state()
        print(f"\n✅ ĐÃ TẠO LỆNH MỚI CHO {symbol} VỚI VỐN ${invested_usd:,.2f}")
        print("\n✅ Đã lưu lại trạng thái thành công!")
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
