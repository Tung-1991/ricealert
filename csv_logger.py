# /root/ricealert/csv_logger.py

import os
import pandas as pd
from datetime import datetime, timezone, timedelta

VN_TZ = timezone(timedelta(hours=7))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(BASE_DIR, "output", "signal_log.csv")

def format_price(price_value):
    """Tự động định dạng giá với số chữ số thập phân phù hợp."""
    if not isinstance(price_value, (int, float)):
        return str(price_value)
    if price_value >= 100:
        return f"{price_value:.2f}"
    if price_value >= 1:
        return f"{price_value:.4f}"
    if price_value >= 0.001:
        return f"{price_value:.6f}"
    return f"{price_value:.8f}"

def log_to_csv(symbol: str, interval: str, price: float, timestamp: str, recommendation: dict):
    os.makedirs(os.path.dirname(CSV_PATH), exist_ok=True)

    signal_details = recommendation.get("signal_details", {})
    level = signal_details.get("level", "HOLD")
    tag = signal_details.get("tag", "unknown")

    trade_plan = recommendation.get("combined_trade_plan", {})
    entry = trade_plan.get("entry", 0)
    tp = trade_plan.get("tp", 0)
    sl = trade_plan.get("sl", 0)
    trade_plan_str = f"{format_price(entry)}/{format_price(tp)}/{format_price(sl)}"

    ai_pred = recommendation.get("ai_prediction", {})
    prob_buy = ai_pred.get("prob_buy", 50.0)
    prob_sell = ai_pred.get("prob_sell", 0.0)
    ai_skew = (prob_buy - prob_sell) / 100.0

    log_entry = {
        "timestamp": timestamp,
        "symbol": symbol,
        "interval": interval,
        "signal": level,
        "tag": tag,
        "price": format_price(price),
        "advisor_trade_plan": trade_plan_str,
        "entry_exit_pnl": "0/0/0",
        "status": "No",
        "money": 0,
        "advisor_score": recommendation.get("final_score", 0),
        "tech_score": recommendation.get("tech_score", 0),
        "ai_skew": round(ai_skew, 4),
        "market_trend": recommendation.get("market_trend", "NEUTRAL"),
        "news_factor": recommendation.get("news_factor", 0),
    }

    df_new = pd.DataFrame([log_entry])

    if os.path.exists(CSV_PATH):
        try:
            df_existing = pd.read_csv(CSV_PATH)
            df_combined = pd.concat([df_existing, df_new], ignore_index=True)
        except Exception as e:
            print(f"⚠️ Lỗi đọc CSV cũ: {e}, tạo file mới.")
            df_combined = df_new
    else:
        df_combined = df_new

    header = [
        "timestamp", "symbol", "interval", "signal", "tag", "price",
        "advisor_trade_plan", "entry_exit_pnl", "status", "money",
        "advisor_score", "tech_score", "ai_skew", "market_trend", "news_factor"
    ]
    df_combined = df_combined.reindex(columns=header)

    df_combined.to_csv(CSV_PATH, index=False)

    print(f"✅ Ghi CSV (Điểm: {log_entry['advisor_score']}): {symbol}-{interval} @ {log_entry['price']}")
    return df_combined.tail(1)

def write_named_log(content: str, file_path: str):
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)
