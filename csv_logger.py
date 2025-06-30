# csv_logger.py
import os
import pandas as pd
from datetime import timezone, timedelta

VN_TZ = timezone(timedelta(hours=7))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(BASE_DIR, "output", "signal_log.csv")

def log_to_csv(symbol, interval, signal, tag, price, trade_plan, timestamp):
    os.makedirs("output", exist_ok=True)

    entry = trade_plan.get("entry", 0)
    tp = trade_plan.get("tp", 0)
    sl = trade_plan.get("sl", 0)
    trade_plan_str = f"{entry:.8f}/{tp:.8f}/{sl:.8f}"

    # Gộp entry/exit/pnl lại → tách riêng status
    entry_exit_pnl = "0/0/0"
    status = "No"

    log_entry = {
        "timestamp": timestamp,
        "symbol": str(symbol) if symbol else "No",
        "interval": str(interval) if interval else "No",
        "signal": str(signal) if signal else "No",
        "tag": str(tag) if tag else "No",
        "price": price if price is not None else 0,
        "trade_plan": trade_plan_str,
        "entry_exit_pnl": entry_exit_pnl,
        "status": status,
        "money": 0  # ✅ Trường mới
    }

    df_new = pd.DataFrame([log_entry])

    if os.path.exists(CSV_PATH):
        try:
            df_existing = pd.read_csv(CSV_PATH)
            df_combined = pd.concat([df_existing, df_new], ignore_index=True)
        except Exception as e:
            print(f"⚠️ Lỗi đọc CSV cũ: {e}, tạo file mới")
            df_combined = df_new
    else:
        df_combined = df_new

    df_combined.to_csv(CSV_PATH, index=False)
    print(f"✅ Ghi CSV: {log_entry['symbol']}-{log_entry['interval']} @ {log_entry['price']} | Time VN: {log_entry['timestamp']}")
    return df_combined.tail(1)

def write_named_log(content: str, file_path: str):
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)

