import json
import pandas as pd
import os
from datetime import datetime
import pytz

print("--- SCRIPT TÁI TẠO & HỢP NHẤT CSV TỪ STATE.JSON (vSafe) ---")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
STATE_FILE = os.path.join(DATA_DIR, "live_trade_state.json")
CSV_FILE_OUTPUT = os.path.join(DATA_DIR, "live_trade_history.csv")
VIETNAM_TZ = pytz.timezone('Asia/Ho_Chi_Minh')

CORRECT_HEADER = [
    "trade_id", "symbol", "interval", "status", "opened_by_tactic", "tactic_used", 
    "trade_type", "entry_price", "exit_price", "tp", "sl", "initial_sl", 
    "total_invested_usd", "pnl_usd", "pnl_percent", "entry_time", "exit_time", 
    "holding_duration_hours", "entry_score", "last_score", "dca_entries", 
    "realized_pnl_usd", "binance_market_order_id", "entry_zone", "last_zone", 
    "initial_entry"
]

def rebuild():
    # 1. Đọc dữ liệu mới nhất từ state.json
    if not os.path.exists(STATE_FILE):
        print(f"❌ KHÔNG TÌM THẤY FILE STATE: {STATE_FILE}")
        return

    print(f"📖 Đang đọc file state.json...")
    with open(STATE_FILE, 'r', encoding='utf-8') as f:
        state_data = json.load(f)

    trade_history_json = state_data.get("trade_history")
    if not trade_history_json:
        print("❌ KHÔNG TÌM THẤY 'trade_history' TRONG FILE STATE.JSON.")
        return
    
    print(f"✅ Tìm thấy {len(trade_history_json)} giao dịch trong JSON. Bắt đầu xử lý...")
    
    # Tạo DataFrame từ JSON
    json_df = pd.DataFrame(trade_history_json)
    # Tính toán lại duration cho chắc chắn
    try:
        json_df['entry_time_dt'] = pd.to_datetime(json_df['entry_time'])
        json_df['exit_time_dt'] = pd.to_datetime(json_df['exit_time'])
        json_df['holding_duration_hours'] = round((json_df['exit_time_dt'] - json_df['entry_time_dt']).dt.total_seconds() / 3600, 2)
        json_df.drop(columns=['entry_time_dt', 'exit_time_dt'], inplace=True)
    except Exception as e:
        print(f"⚠️ Cảnh báo khi tính toán duration: {e}")

    # 2. Đọc dữ liệu lịch sử cũ từ file CSV (nếu có)
    if os.path.exists(CSV_FILE_OUTPUT) and os.path.getsize(CSV_FILE_OUTPUT) > 0:
        print(f"📖 Đang đọc file CSV lịch sử: {os.path.basename(CSV_FILE_OUTPUT)}...")
        try:
            csv_df = pd.read_csv(CSV_FILE_OUTPUT)
            print(f"✅ Tìm thấy {len(csv_df)} giao dịch trong file CSV cũ.")

            # 3. Logic "CẬP NHẬT VÀ HỢP NHẤT"
            # Đặt trade_id làm chỉ mục để dễ dàng cập nhật và tìm kiếm
            csv_df.set_index('trade_id', inplace=True)
            json_df.set_index('trade_id', inplace=True)

            # Cập nhật các bản ghi cũ trong CSV bằng dữ liệu mới từ JSON
            print("🔄️ Đang cập nhật các bản ghi trùng lặp...")
            csv_df.update(json_df)
            
            # Tìm các bản ghi hoàn toàn mới trong JSON mà chưa có trong CSV
            new_trades_mask = ~json_df.index.isin(csv_df.index)
            new_trades_df = json_df[new_trades_mask]
            
            if not new_trades_df.empty:
                print(f"➕ Tìm thấy {len(new_trades_df)} bản ghi mới. Đang thêm vào lịch sử...")
                # Nối các bản ghi mới vào DataFrame đã được cập nhật
                final_df = pd.concat([csv_df.reset_index(), new_trades_df.reset_index()])
            else:
                print("ℹ️ Không có bản ghi mới nào để thêm.")
                final_df = csv_df.reset_index()

        except Exception as e:
            print(f"🔥🔥 LỖI khi đọc hoặc xử lý file CSV: {e}. Ghi đè bằng dữ liệu từ JSON để đảm bảo an toàn.")
            final_df = json_df.reset_index() # Ghi đè trong trường hợp CSV bị hỏng nặng
            
    else:
        # Nếu file CSV không tồn tại, thì file cuối cùng chính là dữ liệu từ JSON
        print("ℹ️ Không tìm thấy file CSV cũ, sẽ tạo file mới từ JSON.")
        final_df = json_df.reset_index()

    try:
        # Sắp xếp lại các cột theo đúng thứ tự và điền các cột còn thiếu
        for col in CORRECT_HEADER:
            if col not in final_df.columns:
                final_df[col] = None
        
        final_df_cleaned = final_df[CORRECT_HEADER]
        # Sắp xếp theo thời gian để file đẹp hơn (tùy chọn)
        final_df_cleaned = final_df_cleaned.sort_values(by='exit_time', ascending=False)
        
        # Ghi lại toàn bộ lịch sử đã được hợp nhất
        final_df_cleaned.to_csv(CSV_FILE_OUTPUT, index=False, encoding='utf-8')
        
        print("\n✨✨✨ HOÀN TẤT! ✨✨✨")
        print(f"File '{os.path.basename(CSV_FILE_OUTPUT)}' đã được hợp nhất và cập nhật thành công.")
        print(f"Tổng số giao dịch trong lịch sử: {len(final_df_cleaned)}")

    except Exception as e:
        print(f"\n🔥🔥🔥 LỖI CUỐI CÙNG: {e}")

if __name__ == "__main__":
    rebuild()
