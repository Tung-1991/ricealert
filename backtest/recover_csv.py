# recover_csv.py
import json
import csv
import os

# --- CẤU HÌNH ---
STATE_FILE = os.path.join("paper_data", "paper_trade_state.json")
CSV_FILE = os.path.join("paper_data", "trade_history.csv")
# --- KẾT THÚC CẤU HÌNH ---

print(f"Đang đọc dữ liệu từ: {STATE_FILE}")

try:
    with open(STATE_FILE, 'r', encoding='utf-8') as f:
        state_data = json.load(f)
except FileNotFoundError:
    print(f"Lỗi: Không tìm thấy file {STATE_FILE}")
    exit()
except json.JSONDecodeError:
    print(f"Lỗi: File {STATE_FILE} bị hỏng.")
    exit()

trade_history = state_data.get("trade_history")

if not trade_history:
    print("Không tìm thấy dữ liệu 'trade_history' trong file json.")
    exit()

print(f"Tìm thấy {len(trade_history)} bản ghi lịch sử. Chuẩn bị ghi ra file CSV...")

# Lấy tất cả các key có thể có từ tất cả các trade để tạo header đầy đủ
all_keys = set()
for trade in trade_history:
    all_keys.update(trade.keys())
header = sorted(list(all_keys))

try:
    with open(CSV_FILE, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=header, extrasaction='ignore')
        writer.writeheader()
        
        count = 0
        for trade in trade_history:
            # Chuyển đổi các giá trị dict/list thành chuỗi JSON để ghi vào CSV
            row_to_write = {}
            for key, value in trade.items():
                if isinstance(value, (dict, list)):
                    row_to_write[key] = json.dumps(value)
                else:
                    row_to_write[key] = value
            writer.writerow(row_to_write)
            count += 1

    print(f"\n✅ THÀNH CÔNG! Đã khôi phục và ghi {count} bản ghi vào file {CSV_FILE}")

except Exception as e:
    print(f"\n❌ Lỗi khi ghi file CSV: {e}")

