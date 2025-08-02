# livetrade/control_live_panel.py
import os
import sys
import json
import re
from datetime import datetime
import pytz
import requests
import traceback

# --- IMPORT CẤU HÌNH VÀ MODULE ---
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(PROJECT_ROOT)

try:
    from binance_connector import BinanceConnector
except ImportError as e:
    print(f"❌ Lỗi import: {e}. Hãy chắc chắn bạn đã có file binance_connector.py.")
    sys.exit()

# --- CÁC HÀM TIỆN ÍCH ---

def get_network_from_bot_script() -> str:
    # ... (Hàm này đã đúng, giữ nguyên)
    try:
        bot_script_path = os.path.join(os.path.dirname(__file__), 'live_trade.py')
        with open(bot_script_path, 'r', encoding='utf-8') as f:
            content = f.read()
        match = re.search(r'BinanceConnector\s*\(\s*network\s*=\s*"([^"]+)"', content)
        if match:
            network = match.group(1)
            print(f"ℹ️ Tự động phát hiện network từ bot: *** {network.upper()} ***")
            return network
        print("⚠️ Không tìm thấy cấu hình network. Mặc định dùng 'testnet'.")
        return "testnet"
    except Exception:
        print("⚠️ Lỗi khi đọc file live_trade.py. Mặc định dùng 'testnet'.")
        return "testnet"

NETWORK = get_network_from_bot_script()
LIVE_DATA_DIR = os.path.join(PROJECT_ROOT, "livetrade", "data")
STATE_FILE = os.path.join(LIVE_DATA_DIR, "live_trade_state.json")
VIETNAM_TZ = pytz.timezone('Asia/Ho_Chi_Minh')

def get_current_price(symbol: str) -> float | None:
    # ... (Hàm này đã đúng, giữ nguyên)
    url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        return float(response.json()['price'])
    except Exception:
        return None

def load_state() -> dict:
    # ... (Hàm này đã đúng, giữ nguyên)
    if not os.path.exists(STATE_FILE):
        return {"active_trades": [], "trade_history": [], "initial_capital": 0.0}
    try:
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            content = f.read()
            return json.loads(content) if content else {"active_trades": [], "trade_history": [], "initial_capital": 0.0}
    except Exception as e:
        print(f"❌ Lỗi khi tải state: {e}")
        return {"active_trades": [], "trade_history": [], "initial_capital": 0.0}

def save_state(state: dict):
    # ... (Hàm này đã đúng, giữ nguyên)
    try:
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=4, ensure_ascii=False)
        print("\n✅ Đã lưu lại trạng thái thành công!")
    except Exception as e:
        print(f"❌ Lỗi khi lưu file trạng thái: {e}")

# --- CÁC HÀM CHỨC NĂNG CHÍNH ---

def view_open_trades():
    """Hiển thị báo cáo tổng quan và chi tiết các lệnh đang mở. (ĐÃ SỬA LỖI LOGIC TÍNH TOÁN)"""
    state = load_state()
    active_trades = state.get("active_trades", [])
    trade_history = state.get("trade_history", [])
    initial_capital = state.get('initial_capital', 0.0)

    print("\n" + "--- BÁO CÁO TÀI KHOẢN & LỆNH ĐANG MỞ ---")

    # --- BƯỚC 1: LẤY DỮ LIỆU ---
    total_usdt = 0.0
    try:
        with BinanceConnector(network=NETWORK) as bnc:
            balance_info = bnc.get_account_balance()
            usdt_balance = next((b for b in balance_info.get("balances", []) if b["asset"] == "USDT"), None)
            if usdt_balance:
                total_usdt = float(usdt_balance['free']) + float(usdt_balance['locked'])
    except Exception as e:
        print(f"⚠️ Không thể lấy số dư USDT: {e}")

    symbols_needed = list(set(trade['symbol'] for trade in active_trades))
    prices = {sym: get_current_price(sym) for sym in symbols_needed}

    # --- BƯỚC 2: TÍNH TOÁN LẠI THEO CÔNG THỨC ĐÚNG ---
    unrealized_pnl = 0
    value_of_open_positions = 0
    for t in active_trades:
        current_price = prices.get(t['symbol'], t['entry_price'])
        # Tính tổng giá trị hiện tại của các lệnh đang mở
        value_of_open_positions += float(t['quantity']) * current_price
        # Tính PnL đang mở
        pnl_multiplier = 1 if t.get('trade_type', 'LONG') == 'LONG' else -1
        unrealized_pnl += (current_price - t['entry_price']) * float(t['quantity']) * pnl_multiplier

    # CÔNG THỨC ĐÚNG ĐỂ TÍNH TỔNG TÀI SẢN
    total_equity = total_usdt + value_of_open_positions

    pnl_since_start = total_equity - initial_capital if initial_capital > 0 else 0.0
    pnl_percent_since_start = (pnl_since_start / initial_capital) * 100 if initial_capital > 0 else 0.0

    closed_pnl = sum(t.get('pnl_usd', 0.0) for t in trade_history)
    partial_pnl = sum(t.get('realized_pnl_usd', 0.0) for t in active_trades)

    total_trades = len(trade_history)
    win_rate_str = "N/A"
    if total_trades > 0:
        winning_trades = len([t for t in trade_history if t.get('pnl_usd', 0.0) > 0])
        win_rate_str = f"{winning_trades / total_trades:.2%}"

    # --- BƯỚC 3: HIỂN THỊ HEADER ĐÃ SỬA LỖI ---
    pnl_icon = "🟢" if pnl_since_start >= 0 else "🔴"
    print(f"💰 Vốn BĐ: ${initial_capital:,.2f} | 💵 Tiền mặt (USDT): ${total_usdt:,.2f}")
    print(f"📊 Tổng TS: ${total_equity:,.2f} | 📈 PnL Tổng: {pnl_icon} ${pnl_since_start:,.2f} ({pnl_percent_since_start:+.2f}%)")
    print(f"🏆 Win Rate: {win_rate_str} | ✅ PnL Đóng: ${closed_pnl:,.2f} | 💎 PnL TP1: ${partial_pnl:,.2f} | 📈 PnL Mở: ${unrealized_pnl:,.2f}")
    print("-" * 65)

    # --- BƯỚC 4: HIỂN THỊ DANH SÁCH LỆNH (Đã nâng cấp hiển thị điểm) ---
    if not active_trades:
        print("ℹ️ Không có lệnh nào đang mở.")
        return

    for i, trade in enumerate(active_trades):
        symbol = trade['symbol']
        current_price = prices.get(symbol)
        pnl_usd, pnl_percent = 0.0, 0.0

        if current_price:
            pnl_multiplier = 1 if trade.get('trade_type', 'LONG') == 'LONG' else -1
            pnl_usd = (current_price - trade['entry_price']) * float(trade['quantity']) * pnl_multiplier
            if trade.get('total_invested_usd', 0) > 0:
                pnl_percent = (pnl_usd / trade['total_invested_usd']) * 100

        pnl_icon_trade = "🟢" if pnl_usd >= 0 else "🔴"
        holding_duration = datetime.now(VIETNAM_TZ) - datetime.fromisoformat(trade['entry_time'])
        
        # --- PHẦN LOGIC MỚI ĐỂ HIỂN THỊ ĐIỂM ---
        entry_score = trade.get('entry_score', 0.0)
        last_score = trade.get('last_score', entry_score)
        score_display = f"{entry_score:,.1f}→{last_score:,.1f}"
        if last_score < entry_score: score_display += "📉"
        elif last_score > entry_score: score_display += "📈"

        entry_zone = trade.get('entry_zone', 'N/A')
        last_zone = trade.get('last_zone', entry_zone)
        zone_display = entry_zone
        if last_zone != entry_zone:
            zone_display = f"{entry_zone}→{last_zone}"

        tactic_info = f"({trade.get('opened_by_tactic')} | {score_display} | {zone_display})"
        # --- KẾT THÚC LOGIC MỚI ---
        
        # Loại bỏ các ký tự Markdown ** vì console không hỗ trợ
        clean_tactic_info = tactic_info.replace("**", "")

        print(f"{i+1}. {pnl_icon_trade} {symbol}-{trade['interval']} {clean_tactic_info} | PnL: ${pnl_usd:,.2f} ({pnl_percent:+.2f}%)")
        print(f"   Vốn: ${trade.get('total_invested_usd', 0):,.2f} | Giữ: {str(holding_duration).split('.')[0]}")
        
        # Thêm thông tin TSL nếu có
        tsl_info = f" | TSL: {trade['sl']:.4f}" if "Trailing_SL_Active" in trade.get('tactic_used', []) else ""
        print(f"   Entry: {trade['entry_price']:.4f} | Hiện tại: {current_price or 'N/A':.4f} | SL: {trade['sl']:.4f} | TP: {trade['tp']:.4f}{tsl_info}")
        print("-" * 65)

def close_manual_trade():
    # ... (Hàm này đã đúng, giữ nguyên)
    # ... (Nội dung hàm không thay đổi)
    state = load_state()
    active_trades = state.get("active_trades", [])
    if not active_trades:
        print("\nℹ️ Không có lệnh nào để đóng.")
        return
    print("\n" + "--- Chức năng: Đóng lệnh thủ công trên SÀN ---")
    for i, trade in enumerate(active_trades):
        print(f"{i+1}. {trade['symbol']}-{trade['interval']}")
    try:
        choice = input("\n👉 Nhập SỐ của lệnh cần đóng (hoặc Enter để hủy): ")
        if not choice.strip().isdigit():
            print("Hủy thao tác.")
            return
        index = int(choice.strip()) - 1
        if not (0 <= index < len(active_trades)):
            print("❌ Lựa chọn không hợp lệ.")
            return
        trade = active_trades[index]
        confirm = input(f"👉 Bạn có chắc muốn đóng lệnh {trade['symbol']}? Nhập 'dong y' để xác nhận: ")
        if confirm.lower() != 'dong y':
            print("Hủy thao tác.")
            return
        print(f"\n⚡ Đang xử lý đóng lệnh {trade['symbol']}...")
        with BinanceConnector(network=NETWORK) as bnc:
            side_to_close = "SELL" if trade.get('trade_type', 'LONG') == 'LONG' else "BUY"
            quantity_to_close = str(trade['quantity'])
            print(f"   -> Đang gửi lệnh Market {side_to_close} với số lượng {quantity_to_close}...")
            close_order = bnc.place_market_order(symbol=trade['symbol'], side=side_to_close, quantity=quantity_to_close)
            if not (close_order and close_order.get('status') == 'FILLED'):
                raise Exception(f"Lệnh Market đóng không khớp! Phản hồi từ Binance: {close_order}")
            print("   ✅ Đã đóng vị thế thành công trên sàn.")
            closed_trade_obj = state['active_trades'].pop(index)
            exit_price = float(close_order['cummulativeQuoteQty']) / float(close_order['executedQty'])
            pnl_usd = (exit_price - trade['entry_price']) * float(trade['quantity']) * (1 if trade['trade_type'] == 'LONG' else -1)
            closed_trade_obj.update({
                'status': 'Closed (Manual Panel)',
                'exit_price': exit_price,
                'exit_time': datetime.now(VIETNAM_TZ).isoformat(),
                'pnl_usd': pnl_usd,
            })
            state.setdefault('trade_history', []).append(closed_trade_obj)
            save_state(state)
            print(f"\n🎉 Hoàn tất! Lợi nhuận/Thua lỗ thực tế: ${pnl_usd:,.2f}")
    except Exception as e:
        print(f"\n❌ LỖI NGHIÊM TRỌNG KHI ĐÓNG LỆNH: {e}")
        traceback.print_exc()

def main_menu():
    # ... (Hàm này đã đúng, giữ nguyên)
    print("\n" + "="*15 + " 📊 BẢNG ĐIỀU KHIỂN LIVE 📊 " + "="*15)
    while True:
        print("\n1. Xem báo cáo và các lệnh đang mở")
        print("2. Đóng một lệnh thủ công")
        print("0. Thoát")
        print("="*62)
        choice = input("👉 Vui lòng chọn một chức năng: ")
        if choice == '1':
            view_open_trades()
        elif choice == '2':
            close_manual_trade()
        elif choice == '0':
            print("👋 Tạm biệt!")
            break
        else:
            print("⚠️ Lựa chọn không hợp lệ, vui lòng nhập lại.")

if __name__ == "__main__":
    main_menu()
