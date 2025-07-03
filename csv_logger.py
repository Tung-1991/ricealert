# /root/ricealert/csv_logger.py

import os
import pandas as pd
from datetime import timezone, timedelta

VN_TZ = timezone(timedelta(hours=7))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(BASE_DIR, "output", "signal_log.csv")

def log_to_csv(symbol, interval, signal, tag, price, trade_plan, timestamp, recommendation: dict):
    os.makedirs(os.path.dirname(CSV_PATH), exist_ok=True)

    entry = trade_plan.get("entry", 0)
    tp    = trade_plan.get("tp", 0)
    sl    = trade_plan.get("sl", 0)
    trade_plan_str = f"{entry:.8f}/{tp:.8f}/{sl:.8f}"

    entry_exit_pnl = "0/0/0"
    status = "No"

    # SỬA ĐỔI: Ghi lại các cột điểm mới và đổi tên cột "ai_score"
    log_entry = {
        "timestamp": timestamp,
        "symbol": symbol,
        "interval": interval,
        "signal": signal,
        "tag": tag,
        "price": price,
        "trade_plan": trade_plan_str,
        "entry_exit_pnl": entry_exit_pnl,
        "status": status,
        "money": 0,
        "advisor_score": recommendation.get("final_score", 0),
        "tech_score": recommendation.get("tech_score", 0),
        "ai_pct_change": recommendation.get("ai_pct_change", 0), # Đổi tên từ ai_score
        "market_trend": recommendation.get("market_trend", "NEUTRAL"),
        "news_factor": recommendation.get("news_factor", 0),
    }

    df_new = pd.DataFrame([log_entry])

    # Đảm bảo các giá trị số được định dạng đúng trong Google Sheet
    for col in ['price', 'advisor_score', 'tech_score', 'ai_pct_change']:
        df_new[col] = df_new[col].astype(str).str.replace('.', ',')

    if os.path.exists(CSV_PATH):
        try:
            df_existing = pd.read_csv(CSV_PATH)
            df_combined = pd.concat([df_existing, df_new], ignore_index=True)
        except Exception as e:
            print(f"⚠️ Lỗi đọc CSV cũ: {e}, tạo file mới.")
            df_combined = df_new
    else:
        df_combined = df_new

    # Đảm bảo các cột mới được thêm vào nếu file cũ chưa có
    header = ["timestamp", "symbol", "interval", "signal", "tag", "price", "trade_plan", "entry_exit_pnl", "status", "money", "advisor_score", "tech_score", "ai_pct_change", "market_trend", "news_factor"]
    df_combined = df_combined.reindex(columns=header)

    df_combined.to_csv(CSV_PATH, index=False)
    print(f"✅ Ghi CSV (Điểm: {log_entry['advisor_score']}): {symbol}-{interval} @ {price}")
    return df_combined.tail(1)

def write_named_log(content: str, file_path: str):
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)

