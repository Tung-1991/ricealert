import os
import shutil
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv
import gspread
from oauth2client.service_account import ServiceAccountCredentials

load_dotenv()

CSV_PATH = "output/signal_log.csv"
BACKUP_PATH = "log/signal_log.csv.bak"
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_JSON", "ricealert-ec406ac4f2f7.json")

def sync_csv_to_google_sheet():
    if not os.path.exists(CSV_PATH):
        print("[INFO] Không có file CSV để sync → bỏ qua.")
        return

    # 🧠 Backup trước khi xoá
    os.makedirs("log", exist_ok=True)
    shutil.copy(CSV_PATH, BACKUP_PATH)
    print(f"[BACKUP] Đã tạo bản backup tại: {BACKUP_PATH}")

    # 🔑 Auth Google Sheets API
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
    client = gspread.authorize(creds)

    # 📅 Tên sheet theo tháng
    sheet_name = f"signal_log_{datetime.now().strftime('%Y%m')}"
    sheet = client.open_by_key(GOOGLE_SHEET_ID)
    try:
        worksheet = sheet.worksheet(sheet_name)
    except gspread.exceptions.WorksheetNotFound:
        worksheet = sheet.add_worksheet(title=sheet_name, rows="1000", cols="20")

    # 📊 Ghi đè toàn bộ
    df = pd.read_csv(CSV_PATH)
    worksheet.clear()
    worksheet.update([df.columns.values.tolist()] + df.values.tolist())
    print(f"[SYNC] Đã sync dữ liệu lên Google Sheet: {sheet_name}")

    # ❌ Xóa CSV sau sync
    os.remove(CSV_PATH)
    print(f"[CLEANUP] Đã xoá {CSV_PATH} sau khi sync xong")

if __name__ == "__main__":
    sync_csv_to_google_sheet()

