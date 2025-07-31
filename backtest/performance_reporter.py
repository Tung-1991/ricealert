# -*- coding: utf-8 -*-
import os
import json
import pandas as pd
from typing import Dict, Any

# --- Thiết lập đường dẫn ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PAPER_DATA_DIR = os.path.join(BASE_DIR, "paper_data")
STATE_FILE = os.path.join(PAPER_DATA_DIR, "paper_trade_state.json")

def load_trade_history() -> list:
    """Tải lịch sử giao dịch từ file state.json."""
    if not os.path.exists(STATE_FILE):
        print(f"❌ Lỗi: Không tìm thấy file state '{STATE_FILE}'.")
        return []
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("trade_history", [])
    except json.JSONDecodeError:
        print(f"❌ Lỗi: File state '{STATE_FILE}' bị hỏng.")
        return []

def analyze_tactic_performance(trade_history: list) -> pd.DataFrame | None:
    """Phân tích hiệu suất của từng Tactic từ lịch sử giao dịch."""
    if not trade_history:
        print("ℹ️ Lịch sử giao dịch trống, không có gì để phân tích.")
        return None

    df = pd.DataFrame(trade_history)

    # Chỉ phân tích các lệnh đã có PnL
    df = df[df['pnl_usd'].notna()]
    if df.empty:
        print("ℹ️ Không có lệnh đã đóng nào có PnL để phân tích.")
        return None

    # Phân tích theo Tactic mở lệnh ban đầu
    results = []
    for tactic, group in df.groupby('opened_by_tactic'):
        total_trades = len(group)
        wins = group[group['pnl_usd'] > 0]
        losses = group[group['pnl_usd'] <= 0]
        
        num_wins = len(wins)
        num_losses = len(losses)
        
        win_rate = (num_wins / total_trades) * 100 if total_trades > 0 else 0
        total_pnl = group['pnl_usd'].sum()
        
        avg_win_pnl = wins['pnl_usd'].mean() if num_wins > 0 else 0
        avg_loss_pnl = losses['pnl_usd'].mean() if num_losses > 0 else 0
        
        # Payoff Ratio = (Lợi nhuận trung bình) / (Thua lỗ trung bình)
        payoff_ratio = abs(avg_win_pnl / avg_loss_pnl) if avg_loss_pnl != 0 else float('inf')

        results.append({
            "Tactic": tactic,
            "Total Trades": total_trades,
            "Win Rate (%)": win_rate,
            "Total PnL ($)": total_pnl,
            "Avg Win ($)": avg_win_pnl,
            "Avg Loss ($)": avg_loss_pnl,
            "Payoff Ratio": payoff_ratio
        })

    if not results:
        return None
        
    # Sắp xếp theo Total PnL để biết Tactic nào hiệu quả nhất
    performance_df = pd.DataFrame(results).sort_values(by="Total PnL ($)", ascending=False)
    return performance_df

def main():
    """Hàm chính để chạy phân tích và hiển thị kết quả."""
    print("="*15, "📊 BẢNG PHÂN TÍCH HIỆU SUẤT TACTIC 📊", "="*15)
    
    trade_history = load_trade_history()
    performance_df = analyze_tactic_performance(trade_history)

    if performance_df is not None:
        # Định dạng output cho đẹp
        pd.set_option('display.float_format', '{:,.2f}'.format)
        print(performance_df.to_string(index=False))
    
    print("="*65)

if __name__ == "__main__":
    main()
