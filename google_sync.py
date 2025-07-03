# /root/ricealert/google_sync.py

import os
import shutil
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from gspread_formatting import CellFormat, TextFormat, format_cell_range

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(BASE_DIR, "output/signal_log.csv")
BAK_DIR = os.path.join(BASE_DIR, "output")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_JSON", os.path.join(BASE_DIR, "ricealert-ec406ac4f2f7.json"))

def cleanup_old_backups(keep=1):
    files = [f for f in os.listdir(BAK_DIR) if f.endswith(".csv.bak")]
    files = sorted(files, key=lambda f: os.path.getmtime(os.path.join(BAK_DIR, f)), reverse=True)
    for f in files[keep:]:
        path = os.path.join(BAK_DIR, f)
        os.remove(path)
        print(f"[CLEANUP] Đã xoá file backup cũ: {path}")

def sync_csv_to_google_sheet():
    if not os.path.exists(CSV_PATH):
        print("[INFO] Không có file CSV để sync → bỏ qua.")
        return

    # 🔒 Backup theo timestamp
    os.makedirs(BAK_DIR, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_file = os.path.join(BAK_DIR, f"signal_log_{timestamp}.csv.bak")
    shutil.copy(CSV_PATH, backup_file)
    print(f"[BACKUP] Đã tạo bản backup tại: {backup_file}")

    # 🧹 Dọn backup cũ
    cleanup_old_backups(keep=1)

    # 🔑 Google API
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
    client = gspread.authorize(creds)

    # 📅 Sheet theo tháng
    sheet_name = f"signal_log_{datetime.now().strftime('%Y%m')}"
    sheet = client.open_by_key(GOOGLE_SHEET_ID)

    # 📊 Đọc file CSV
    df = pd.read_csv(CSV_PATH)
    rows = df.values.tolist()
    header = df.columns.tolist()

    # 🧾 Tạo worksheet nếu chưa có
    try:
        worksheet = sheet.worksheet(sheet_name)
    except gspread.exceptions.WorksheetNotFound:
        worksheet = sheet.add_worksheet(title=sheet_name, rows="1000", cols="30")
        worksheet.append_row(header, value_input_option="USER_ENTERED")

    # 🔢 Đếm dòng hiện tại
    existing_rows = len(worksheet.get_all_values())

    # ⬇️ Append dữ liệu
    worksheet.append_rows(rows, value_input_option="USER_ENTERED")

    # 🎯 Format font dòng mới
    start_row = existing_rows + 1
    end_row = existing_rows + len(rows)
    col_end = chr(64 + len(header))  # A, B, ..., J, K...
    range_str = f"A{start_row}:{col_end}{end_row}"

    fmt = CellFormat(textFormat=TextFormat(fontSize=12))
    format_cell_range(worksheet, range_str, fmt)

    print(f"[SYNC] Đã append {len(rows)} dòng lên Google Sheet: {sheet_name}")
    os.remove(CSV_PATH)
    print(f"[CLEANUP] Đã xoá {CSV_PATH} sau khi sync xong")

if __name__ == "__main__":
    sync_csv_to_google_sheet()
