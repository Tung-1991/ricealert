import pandas as pd
import os
import json

# Định nghĩa các hằng số file
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
CSV_FILE = os.path.join(DATA_DIR, "live_trade_history.csv")
BACKUP_FILE = os.path.join(DATA_DIR, "live_trade_history.csv.bak")

def rebuild_the_csv():
    print(f" rebuilding file: {CSV_FILE}")
    if not os.path.exists(CSV_FILE):
        print("File CSV không tồn tại, không có gì để làm.")
        return

    try:
        # Đọc toàn bộ file vào một DataFrame, không có header để xử lý thủ công
        df = pd.read_csv(CSV_FILE)
        print(f"Đã đọc {len(df)} dòng từ file CSV.")

        # Tạo bản sao lưu an toàn
        if os.path.exists(BACKUP_FILE):
            os.remove(BACKUP_FILE) # Xóa backup cũ nếu có
        os.rename(CSV_FILE, BACKUP_FILE)
        print(f"Đã tạo file sao lưu an toàn tại: {BACKUP_FILE}")

        # Định nghĩa cấu trúc cột CHUẨN mà chúng ta muốn
        standard_columns = [
            "trade_id", "symbol", "interval", "status", "opened_by_tactic", "tactic_used",
            "trade_type", "entry_price", "exit_price", "tp", "sl", "initial_sl",
            "total_invested_usd", "pnl_usd", "pnl_percent", "entry_time", "exit_time",
            "holding_duration_hours", "entry_score", "last_score", "entry_zone", "last_zone",
            "dca_entries", "realized_pnl_usd", "binance_market_order_id", "initial_entry"
        ]
        
        # Ghi lại header chuẩn vào file mới
        pd.DataFrame(columns=standard_columns).to_csv(CSV_FILE, index=False, encoding='utf-8')
        
        # Ghi lại từng dòng đã được làm sạch
        for index, row in df.iterrows():
            clean_row_dict = row.to_dict()
            # Đảm bảo tất cả các cột chuẩn đều tồn tại trong từng dòng
            for col in standard_columns:
                if col not in clean_row_dict:
                    clean_row_dict[col] = None
            
            # Tạo DataFrame từ dict đã làm sạch và ghi nối tiếp
            pd.DataFrame([clean_row_dict])[standard_columns].to_csv(CSV_FILE, mode='a', header=False, index=False, encoding='utf-8')

        print(f"✅ Đã xây dựng lại thành công file {os.path.basename(CSV_FILE)} với {len(df)} dòng.")

    except Exception as e:
        print(f"❌ Lỗi nghiêm trọng khi xây dựng lại CSV: {e}")
        print("Đang cố gắng khôi phục từ file backup...")
        if os.path.exists(BACKUP_FILE):
            os.rename(BACKUP_FILE, CSV_FILE)
            print("✅ Đã khôi phục file CSV gốc từ backup.")

if __name__ == "__main__":
    rebuild_the_csv()

