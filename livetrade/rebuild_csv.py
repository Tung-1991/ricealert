import json
import pandas as pd
import os
from datetime import datetime
import pytz

print("--- SCRIPT TÁI TẠO CSV TỪ STATE.JSON (vFinal) ---")

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
    if not os.path.exists(STATE_FILE):
        print(f"❌ KHÔNG TÌM THẤY FILE STATE: {STATE_FILE}")
        return

    print(f"📖 Đang đọc file state.json...")
    with open(STATE_FILE, 'r', encoding='utf-8') as f:
        state_data = json.load(f)

    trade_history = state_data.get("trade_history")
    if not trade_history:
        print("❌ KHÔNG TÌM THẤY 'trade_history' TRONG FILE STATE.JSON.")
        return
        
    print(f"✅ Tìm thấy {len(trade_history)} giao dịch. Bắt đầu tính toán lại...")

    try:
        # TÍNH TOÁN LẠI DURATION CHO DỮ LIỆU CŨ
        for trade in trade_history:
            try:
                if trade.get('entry_time') and trade.get('exit_time'):
                    entry_dt = datetime.fromisoformat(trade['entry_time']).astimezone(VIETNAM_TZ)
                    exit_dt = datetime.fromisoformat(trade['exit_time']).astimezone(VIETNAM_TZ)
                    duration_hours = round((exit_dt - entry_dt).total_seconds() / 3600, 2)
                    trade['holding_duration_hours'] = duration_hours
            except:
                trade['holding_duration_hours'] = 0.0

        df = pd.DataFrame(trade_history)
        for col in CORRECT_HEADER:
            if col not in df.columns:
                df[col] = None
        
        df_cleaned = df[CORRECT_HEADER]
        df_cleaned.to_csv(CSV_FILE_OUTPUT, index=False, encoding='utf-8')
        
        print("\n✨✨✨ HOÀN TẤT! ✨✨✨")
        print(f"File '{os.path.basename(CSV_FILE_OUTPUT)}' đã được tái tạo thành công.")
        print("Cột 'holding_duration_hours' đã được tính toán lại cho toàn bộ lịch sử.")

    except Exception as e:
        print(f"\n🔥🔥🔥 LỖI: {e}")

if __name__ == "__main__":
    rebuild()
