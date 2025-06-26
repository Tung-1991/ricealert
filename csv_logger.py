import os
import pandas as pd
from datetime import datetime, timedelta, timezone

VN_TZ = timezone(timedelta(hours=7))
CSV_PATH = "output/signal_log.csv"
LOG_DIR = "log"

def log_to_csv(symbol, interval, signal, tag, price, trade_plan):
    os.makedirs("output", exist_ok=True)

    entry = trade_plan.get("entry", 0)
    tp = trade_plan.get("tp", 0)
    sl = trade_plan.get("sl", 0)
    trade_plan_str = f"{entry}/{tp}/{sl}"

    log_entry = {
        "timestamp": datetime.now(VN_TZ).strftime("%Y-%m-%d %H:%M:%S"),
        "symbol": str(symbol) if symbol else "No",
        "interval": str(interval) if interval else "No",
        "signal": str(signal) if signal else "No",
        "tag": str(tag) if tag else "No",
        "price": price if price is not None else 0,
        "trade_plan": trade_plan_str,
        "real_entry": 0,
        "real_exit": 0,
        "pnl_percent": 0,
        "status": "No"
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

def write_named_log(text, filename):
    today = datetime.now(VN_TZ).strftime("%Y-%m-%d")
    folder_path = os.path.join(LOG_DIR, today)
    os.makedirs(folder_path, exist_ok=True)

    full_path = os.path.join(folder_path, filename)
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(text)

