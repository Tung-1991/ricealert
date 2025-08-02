# backtest/control_panel.py
import os
import sys
import json
from datetime import datetime, timedelta
import pytz
import requests
import uuid

# --- CÁC HẰNG SỐ VÀ CẤU HÌNH ---
# Thêm sys.path để đảm bảo có thể import từ thư mục gốc
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR) # Chỉ đi lên 1 cấp
sys.path.append(PROJECT_ROOT)

# Cập nhật đường dẫn file state
STATE_FILE = os.path.join(BASE_DIR, "paper_data", "paper_trade_state.json")
ENV_FILE = os.path.join(PROJECT_ROOT, ".env")
VIETNAM_TZ = pytz.timezone('Asia/Ho_Chi_Minh')

# ### <<< CẬP NHẬT >>> ###
# Tên các chiến thuật và Vùng được lấy từ file paper_trade.py v8
TACTICS = [
    "Breakout_Hunter", "Dip_Hunter", "AI_Aggressor",
    "Balanced_Trader", "Cautious_Observer"
]
ZONES = ["LEADING", "COINCIDENT", "LAGGING", "NOISE"]
INTERVALS = ["1h", "4h", "1d"]

# --- CÁC HÀM TIỆN ÍCH ---

def get_current_price(symbol):
    """Lấy giá thị trường hiện tại cho một symbol từ API Binance Spot."""
    url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()
        return float(data['price'])
    except Exception as e:
        print(f"\n⚠️  Không thể lấy giá cho {symbol}: {e}")
        return None

def load_state():
    """Tải trạng thái hiện tại từ file JSON."""
    if not os.path.exists(STATE_FILE):
        print(f"❌ Lỗi: Không tìm thấy file trạng thái tại: {STATE_FILE}")
        return None
    try:
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            content = f.read()
            if not content:
                print("⚠️ File trạng thái trống, trả về trạng thái mặc định.")
                return {"cash": 0, "active_trades": [], "trade_history": []}
            return json.loads(content)
    except json.JSONDecodeError:
        print(f"❌ Lỗi: File trạng thái {STATE_FILE} bị lỗi JSON.")
        return None
    except Exception as e:
        print(f"❌ Lỗi không xác định khi đọc file: {e}")
        return None

def save_state(state):
    """Lưu trạng thái mới vào file JSON."""
    try:
        # Tạo một bản sao để không thay đổi state gốc khi loại bỏ key tạm
        state_to_save = state.copy()
        state_to_save.pop('temp_newly_opened_trades', None)
        state_to_save.pop('temp_newly_closed_trades', None)
        
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state_to_save, f, indent=4, ensure_ascii=False)
        print("\n✅ Đã lưu lại trạng thái thành công!")
    except Exception as e:
        print(f"❌ Lỗi khi lưu file trạng thái: {e}")

# ### <<< CẢI TIẾN >>> ###
# Hàm đọc file .env linh hoạt hơn
def parse_env_variable(key_name):
    """Đọc một biến từ file .env và trả về dưới dạng danh sách."""
    try:
        with open(ENV_FILE, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    if key.strip() == key_name:
                        return [item.strip() for item in value.strip().split(',')]
    except FileNotFoundError:
        print(f"⚠️ Không tìm thấy file .env tại {ENV_FILE}")
    return []

def select_from_list(options, prompt):
    """Hiển thị một danh sách lựa chọn và trả về lựa chọn của người dùng."""
    for i, option in enumerate(options):
        print(f"  {i+1}. {option}")
    while True:
        try:
            choice = int(input(prompt))
            if 1 <= choice <= len(options):
                return options[choice - 1]
            else:
                print("⚠️ Lựa chọn không hợp lệ.")
        except ValueError:
            print("⚠️ Vui lòng nhập một con số.")

# --- CÁC HÀM CHỨC NĂNG ---

# ### <<< THAY ĐỔI LỚN >>> ###
# Cập nhật hoàn toàn phần hiển thị để giống với báo cáo của paper_trade v8
def view_open_trades():
    """Hiển thị chi tiết tất cả các lệnh đang mở, bao gồm PnL real-time."""
    print("\n--- DANH SÁCH LỆNH ĐANG MỞ (Real-time) ---")
    state = load_state()
    if not state or not state.get("active_trades"):
        print("ℹ️ Không có lệnh nào đang mở.")
        return None

    active_trades = state.get("active_trades", [])
    symbols_needed = list(set(trade['symbol'] for trade in active_trades))
    prices = {sym: get_current_price(sym) for sym in symbols_needed}

    total_invested = sum(t.get('total_invested_usd', 0.0) for t in active_trades)
    total_unrealized_pnl = sum(
        (((prices.get(t['symbol'], t['entry_price']) - t['entry_price']) / t['entry_price']) * t['total_invested_usd'])
        if prices.get(t['symbol']) else 0
        for t in active_trades
    )
    
    cash = state.get('cash', 0.0)
    total_equity = cash + total_invested + total_unrealized_pnl
    pnl_icon_total = "🟢" if total_unrealized_pnl >= 0 else "🔴"

    print(f"💵 Tiền mặt: ${cash:,.2f} | 💼 Vốn trong lệnh: ${total_invested:,.2f}")
    print(f"📊 Tổng tài sản ước tính: ${total_equity:,.2f} | PnL đang mở: {pnl_icon_total} ${total_unrealized_pnl:,.2f}\n")

    for i, trade in enumerate(active_trades):
        symbol = trade.get('symbol', 'N/A')
        current_price = prices.get(symbol)
        
        if current_price is None:
            print(f"{i+1}. ⚠️ {symbol} - Không thể lấy giá hiện tại. Bỏ qua hiển thị PnL.")
            continue
            
        # Tính toán PnL
        entry_price = trade.get('entry_price', 0)
        invested_usd = trade.get('total_invested_usd', 0)
        pnl_percent = ((current_price - entry_price) / entry_price) * 100
        pnl_usd = (pnl_percent / 100) * invested_usd
        pnl_icon = "🟢" if pnl_usd >= 0 else "🔴"
        
        # Tính toán thời gian giữ lệnh
        entry_time_iso = trade.get('entry_time', datetime.now(VIETNAM_TZ).isoformat())
        holding_duration = datetime.now(VIETNAM_TZ) - datetime.fromisoformat(entry_time_iso)
        holding_hours = holding_duration.total_seconds() / 3600
        
        # Chuẩn bị các chuỗi thông tin phụ
        dca_info = f" (DCA:{len(trade.get('dca_entries',[]))})" if trade.get('dca_entries') else ""
        tsl_info = f" TSL:{trade['sl']:.4f}" if "Trailing_SL_Active" in trade.get('tactic_used', []) else ""
        tp1_info = " TP1✅" if trade.get('tp1_hit', False) else ""

        # Chuẩn bị thông tin Vùng và Điểm số
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

        # Dòng 1: Tổng quan (giống báo cáo)
        tactic_info = f"({trade.get('opened_by_tactic')} | {score_display} | {zone_display})"
        line1 = (f"{i+1}. {pnl_icon} **{trade['symbol']}-{trade['interval']}** {tactic_info} "
                 f"PnL: **${pnl_usd:,.2f} ({pnl_percent:+.2f}%)** | Giữ:{holding_hours:.1f}h{dca_info}{tp1_info}")
        
        # Dòng 2: Chi tiết giá (giống báo cáo)
        current_value = invested_usd + pnl_usd

        # Dòng 2: Chi tiết giá (giống báo cáo)
        line2 = (f"    Vốn:${invested_usd:,.2f} -> ${current_value:,.2f} | Entry:{entry_price:.4f} Cur:{current_price:.4f} "
                 f"TP:{trade.get('tp', 0):.4f} SL:{trade.get('sl', 0):.4f}{tsl_info}")

        
        # In ra màn hình (loại bỏ markdown)
        print(line1.replace('**', ''))
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
        if not choice.strip():
            print("Hủy thao tác.")
            return

        indices_to_close = []
        parts = choice.split(',')
        for part in parts:
            if part.strip().isdigit():
                index = int(part.strip()) - 1
                if 0 <= index < len(active_trades):
                    indices_to_close.append(index)
                else:
                    print(f"⚠️ Cảnh báo: Số '{part.strip()}' không hợp lệ.")
        
        if not indices_to_close:
            print("❌ Không có lựa chọn hợp lệ. Thao tác bị hủy.")
            return
            
        indices_to_close.sort(reverse=True) # Xóa từ cuối để không làm thay đổi chỉ số
        
        for index in indices_to_close:
            trade = state['active_trades'][index]
            symbol = trade.get('symbol')
            print(f"\nĐang xử lý đóng lệnh #{index + 1}: {symbol}...")
            
            current_price = get_current_price(symbol)
            if current_price is None:
                print(f"❌ Không thể đóng lệnh cho {symbol} vì không lấy được giá. Bỏ qua.")
                continue

            # Tính toán PnL
            entry_price = trade.get('entry_price', 0)
            invested_usd = trade.get('total_invested_usd', 0)
            pnl_percent = ((current_price - entry_price) / entry_price) * 100
            pnl_usd = (pnl_percent / 100) * invested_usd

            # Cập nhật thông tin cho lệnh đã đóng
            trade['status'] = 'Closed (Manual)'
            trade['exit_price'] = current_price
            trade['exit_time'] = datetime.now(VIETNAM_TZ).isoformat()
            trade['pnl_usd'] = pnl_usd + trade.get('realized_pnl_usd', 0.0) # Cộng dồn PnL đã chốt
            trade['pnl_percent'] = pnl_percent

            # Cập nhật state
            state['cash'] = state.get('cash', 0) + invested_usd + pnl_usd
            closed_trade = state['active_trades'].pop(index)
            state.setdefault('trade_history', []).append(closed_trade)
            
            print(f"✅ Đã đóng lệnh {symbol}. PnL phiên cuối: ${pnl_usd:,.2f}. PnL tổng: ${closed_trade['pnl_usd']:,.2f}")
            
        save_state(state)

    except Exception as e:
        print(f"\n❌ Đã xảy ra lỗi không mong muốn: {e}")

def close_all_trades():
    print("\n--- Chức năng: Đóng TẤT CẢ lệnh ---")
    state = load_state()
    if not state or not state.get("active_trades"):
        print("ℹ️ Không có lệnh nào đang mở để đóng.")
        return

    print("⚠️ CẢNH BÁO: Hành động này sẽ đóng tất cả các vị thế đang mở ngay lập tức.")
    confirm = input("👉 Bạn có chắc chắn muốn tiếp tục? (y/n): ").lower()
    if confirm != 'y':
        print("Hủy thao tác.")
        return

    trades_to_close = list(state['active_trades'])
    closed_count = 0
    state['active_trades'] = [] # Xóa hết danh sách lệnh đang mở

    for trade in trades_to_close:
        symbol = trade.get('symbol')
        print(f"\nĐang xử lý đóng lệnh: {symbol}...")
        
        current_price = get_current_price(symbol)
        if current_price is None:
            print(f"❌ Không thể đóng lệnh cho {symbol} vì không lấy được giá. Hoàn lại lệnh vào danh sách active.")
            state['active_trades'].append(trade) # Trả lại nếu không đóng được
            continue

        entry_price = trade.get('entry_price', 0)
        invested_usd = trade.get('total_invested_usd', 0)
        pnl_percent = ((current_price - entry_price) / entry_price) * 100
        pnl_usd = (pnl_percent / 100) * invested_usd
        
        trade['status'] = 'Closed (All Manual)'
        trade['exit_price'] = current_price
        trade['exit_time'] = datetime.now(VIETNAM_TZ).isoformat()
        trade['pnl_usd'] = pnl_usd + trade.get('realized_pnl_usd', 0.0)
        trade['pnl_percent'] = pnl_percent
        
        state['cash'] = state.get('cash', 0) + invested_usd + pnl_usd
        state.setdefault('trade_history', []).append(trade)
        
        print(f"✅ Đã đóng lệnh {symbol}. PnL phiên cuối: ${pnl_usd:,.2f}. PnL tổng: ${trade['pnl_usd']:,.2f}")
        closed_count += 1

    if closed_count > 0:
        save_state(state)
    else:
        print("ℹ️ Không có lệnh nào được đóng.")

def extend_stale_check():
    print("\n--- Chức năng: Gia hạn lệnh ---")
    state = load_state()
    if not state: return
    
    active_trades = view_open_trades()
    if not active_trades: return

    try:
        choice = input("\n👉 Chọn số thứ tự của lệnh cần gia hạn (nhấn Enter để hủy): ")
        if not choice.strip() or not choice.strip().isdigit():
            print("Hủy thao tác.")
            return
            
        index = int(choice.strip()) - 1
        if not (0 <= index < len(active_trades)):
            print("❌ Lựa chọn không hợp lệ.")
            return
            
        hours = float(input("👉 Nhập số giờ muốn gia hạn (ví dụ: 48): "))
        if hours <= 0:
            print("❌ Số giờ phải là một số dương.")
            return
            
        override_until = datetime.now(VIETNAM_TZ) + timedelta(hours=hours)
        # Truy cập trực tiếp vào state để cập nhật
        trade_to_update = state['active_trades'][index]
        trade_to_update['stale_override_until'] = override_until.isoformat()
        
        print(f"\n✅ Lệnh {trade_to_update['symbol']} đã được gia hạn.")
        print(f"   Hệ thống sẽ bỏ qua kiểm tra 'stale' cho lệnh này cho đến: {override_until.strftime('%Y-%m-%d %H:%M:%S')}")
        save_state(state)
        
    except ValueError:
        print("❌ Vui lòng nhập một con số hợp lệ cho số giờ.")
    except Exception as e:
        print(f"\n❌ Đã xảy ra lỗi không mong muốn: {e}")

# ### <<< THAY ĐỔI LỚN >>> ###
# Cập nhật hàm mở lệnh để tương thích với cấu trúc của v8
def open_manual_trade():
    print("\n--- Chức năng: Mở lệnh mới thủ công ---")
    state = load_state()
    if not state: return

    try:
        symbols = parse_env_variable("SYMBOLS_TO_SCAN")
        if not symbols:
            print("❌ Không thể đọc cấu hình SYMBOLS_TO_SCAN từ .env.")
            return

        print("\n--- Bước 1: Chọn thông tin cơ bản ---")
        symbol = select_from_list(symbols, "👉 Chọn Symbol: ")
        interval = select_from_list(INTERVALS, "👉 Chọn Interval: ")
        tactic = select_from_list(TACTICS, "👉 Chọn Tactic: ")
        zone = select_from_list(ZONES, "👉 Chọn Vùng (Zone) vào lệnh: ")
        
        print("\n--- Bước 2: Nhập chi tiết lệnh ---")
        entry_price = float(input(f"👉 Giá vào lệnh (Entry) cho {symbol}: "))
        tp = float(input("👉 Giá chốt lời (Take Profit): "))
        sl = float(input("👉 Giá cắt lỗ (Stop Loss): "))
        invested_usd = float(input("👉 Số vốn đầu tư (USD): "))

        if not all(x > 0 for x in [entry_price, tp, sl, invested_usd]):
            print("❌ Các giá trị phải là số dương.")
            return
        if invested_usd > state.get('cash', 0):
            print(f"❌ Vốn đầu tư (${invested_usd:,.2f}) lớn hơn tiền mặt hiện có (${state.get('cash', 0):,.2f}).")
            return
            
        # Tạo đối tượng trade với cấu trúc mới của v8
        new_trade = {
            "trade_id": str(uuid.uuid4()),
            "symbol": symbol,
            "interval": interval,
            "status": "ACTIVE",
            "opened_by_tactic": tactic,
            "trade_type": "LONG",
            "entry_price": entry_price,
            "quantity": invested_usd / entry_price,
            "tp": tp,
            "sl": sl,
            "initial_sl": sl,
            "initial_entry": {"price": entry_price, "invested_usd": invested_usd},
            "total_invested_usd": invested_usd,
            "entry_time": datetime.now(VIETNAM_TZ).isoformat(),
            "entry_score": 9.99, # Điểm cao để không bị hệ thống tự động đóng sớm
            "entry_zone": zone,
            "last_zone": zone,
            "binance_market_order_id": None, # Không có cho paper trade
            "dca_entries": [],
            "profit_taken": False,
            "realized_pnl_usd": 0.0,
            "last_score": 9.99,
            "peak_pnl_percent": 0.0,
            "tp1_hit": False,
            "is_in_warning_zone": False,
            "partial_closed_by_score": False,
            "tactic_used": [tactic, "Manual_Entry"] # Thêm tactic_used
        }

        state['cash'] -= invested_usd
        state.setdefault('active_trades', []).append(new_trade)
        
        print(f"\n✅ ĐÃ TẠO LỆNH MỚI CHO {symbol} VỚI VỐN ${invested_usd:,.2f}")
        save_state(state)

    except ValueError:
        print("❌ Giá trị nhập không hợp lệ. Vui lòng nhập số.")
    except Exception as e:
        print(f"\n❌ Đã xảy ra lỗi không mong muốn: {e}")

def main_menu():
    while True:
        print("\n" + "="*12 + " 📊 BẢNG ĐIỀU KHIỂN (Paper-v8) 📊 " + "="*12)
        print("1. Xem tất cả lệnh đang mở")
        print("2. Đóng một hoặc nhiều lệnh thủ công")
        print("3. Đóng TẤT CẢ lệnh đang mở")
        print("4. Gia hạn cho lệnh (bỏ qua kiểm tra 'stale')")
        print("5. Mở lệnh mới thủ công")
        print("0. Thoát")
        print("="*58)
        
        choice = input("👉 Vui lòng chọn một chức năng: ")
        
        if choice == '1': view_open_trades()
        elif choice == '2': close_manual_trades()
        elif choice == '3': close_all_trades()
        elif choice == '4': extend_stale_check()
        elif choice == '5': open_manual_trade()
        elif choice == '0':
            print("👋 Tạm biệt!")
            break
        else:
            print("⚠️ Lựa chọn không hợp lệ, vui lòng thử lại.")

if __name__ == "__main__":
    main_menu()
