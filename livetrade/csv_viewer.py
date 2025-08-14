# livetrade/csv_viewer.py
# -*- coding: utf-8 -*-
"""
CSV Viewer - Công cụ xem và phân tích toàn bộ lịch sử giao dịch.
Version: 1.4.0 - Thêm bảng phân tích Tactic và đánh số thứ tự.
Date: 2025-08-15
"""
import os
import sys
import json
import pandas as pd
import pytz
import traceback
import csv

# --- CẤU HÌNH ĐƯỜNG DẪN ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
DATA_DIR = os.path.join(BASE_DIR, "data")
TRADE_HISTORY_CSV_FILE = os.path.join(DATA_DIR, "live_trade_history.csv")
VIETNAM_TZ = pytz.timezone('Asia/Ho_Chi_Minh')

# --- CẤU TRÚC CSV CHUẨN ---
CORRECT_HEADER = [
    "trade_id", "symbol", "interval", "status", "opened_by_tactic",
    "tactic_used", "trade_type", "entry_price", "exit_price", "tp", "sl",
    "initial_sl", "total_invested_usd", "pnl_usd", "pnl_percent",
    "entry_time", "exit_time", "holding_duration_hours", "entry_score",
    "last_score", "dca_entries", "partial_pnl_details",
    "realized_pnl_usd", "binance_market_order_id", "entry_zone", "last_zone", "initial_entry"
]
PARTIAL_PNL_DETAILS_INDEX = CORRECT_HEADER.index('partial_pnl_details')

def format_price_dynamically(price: float) -> str:
    if price is None or pd.isna(price): return "N/A"
    try:
        price_f = float(price)
        if price_f >= 1.0: return f"{price_f:,.4f}"
        return f"{price_f:,.8f}"
    except (ValueError, TypeError): return "N/A"

def parse_json_like_string(s: str) -> dict or list:
    if pd.isna(s) or not isinstance(s, str) or not s.strip():
        return {} if '{' in str(s) else []
    try:
        s_cleaned = str(s).replace("'", '"').replace('None', 'null').replace('True', 'true').replace('False', 'false')
        if s_cleaned.startswith('"') and s_cleaned.endswith('"'):
            s_cleaned = json.loads(s_cleaned)
        return json.loads(s_cleaned) if isinstance(s_cleaned, str) else s_cleaned
    except (json.JSONDecodeError, TypeError):
        return {} if '{' in str(s) else []

def read_and_normalize_csv():
    """Đọc và chuẩn hóa file CSV, trả về một DataFrame sạch."""
    if not os.path.exists(TRADE_HISTORY_CSV_FILE):
        print(f"❌ Lỗi: Không tìm thấy file lịch sử tại '{TRADE_HISTORY_CSV_FILE}'")
        return None
    
    all_rows_normalized = []
    with open(TRADE_HISTORY_CSV_FILE, 'r', encoding='utf-8', newline='') as f:
        reader = csv.reader(f)
        next(reader, None)
        for i, row in enumerate(reader, 2):
            if len(row) == 26:
                row.insert(PARTIAL_PNL_DETAILS_INDEX, None)
                all_rows_normalized.append(row)
            elif len(row) == 27:
                all_rows_normalized.append(row)
            else:
                print(f"⚠️ Cảnh báo: Bỏ qua dòng {i} không hợp lệ với {len(row)} cột.")
    
    df = pd.DataFrame(all_rows_normalized, columns=CORRECT_HEADER)
    
    if df.empty:
        print("ℹ️ Không có dữ liệu hợp lệ nào được tìm thấy trong file CSV.")
        return None
        
    print(f"✅ Đã tải và chuẩn hóa thành công {len(df)} bản ghi. Đang xử lý...")
    return df

def analyze_tactic_performance(df: pd.DataFrame):
    """Phân tích và hiển thị hiệu suất của các Tactic từ DataFrame."""
    print("\n" + "="*20, "📊 BẢNG PHÂN TÍCH HIỆU SUẤT TACTIC 📊", "="*20)
    
    df_analysis = df.copy()
    df_analysis['pnl_usd'] = pd.to_numeric(df_analysis['pnl_usd'], errors='coerce')
    df_analysis.dropna(subset=['pnl_usd', 'opened_by_tactic'], inplace=True)
    df_analysis = df_analysis[df_analysis['status'].astype(str).str.contains('Closed', na=False, case=False)]

    if df_analysis.empty:
        print("ℹ️ Không có dữ liệu hợp lệ để phân tích hiệu suất.")
        return

    grouped = df_analysis.groupby('opened_by_tactic').agg(
        Total_Trades=('pnl_usd', 'count'),
        Total_PnL=('pnl_usd', 'sum'),
        Wins=('pnl_usd', lambda x: (x > 0).sum()),
        Avg_Win_PnL=('pnl_usd', lambda x: x[x > 0].mean()),
        Avg_Loss_PnL=('pnl_usd', lambda x: x[x <= 0].mean()),
        Max_Win=('pnl_usd', 'max'),
        Max_Loss=('pnl_usd', 'min')
    ).fillna(0)

    grouped['Win_Rate_%'] = (grouped['Wins'] / grouped['Total_Trades'] * 100).where(grouped['Total_Trades'] > 0, 0)
    grouped['Payoff_Ratio'] = abs(grouped['Avg_Win_PnL'] / grouped['Avg_Loss_PnL']).where(grouped['Avg_Loss_PnL'] != 0, float('inf'))
    
    total_trades_all = len(df_analysis)
    wins_all = (df_analysis['pnl_usd'] > 0).sum()
    
    total_row = {
        'Tactic': 'TỔNG CỘNG',
        'Total_Trades': total_trades_all,
        'Total_PnL': df_analysis['pnl_usd'].sum(),
        'Wins': wins_all,
        'Win_Rate_%': (wins_all / total_trades_all * 100) if total_trades_all > 0 else 0,
        'Avg_Win_PnL': df_analysis[df_analysis['pnl_usd'] > 0]['pnl_usd'].mean(),
        'Avg_Loss_PnL': df_analysis[df_analysis['pnl_usd'] <= 0]['pnl_usd'].mean(),
        'Max_Win': df_analysis['pnl_usd'].max(),
        'Max_Loss': df_analysis['pnl_usd'].min(),
    }
    avg_win_all = total_row.get('Avg_Win_PnL', 0)
    avg_loss_all = total_row.get('Avg_Loss_PnL', 0)
    total_row['Payoff_Ratio'] = abs(avg_win_all / avg_loss_all) if avg_loss_all != 0 else float('inf')

    total_df = pd.DataFrame([total_row]).set_index('Tactic')
    analysis_df = pd.concat([grouped, total_df.fillna(0)])
    
    final_df = analysis_df.reset_index().rename(columns={'index': 'Tactic'})

    final_cols = ['Tactic', 'Total_Trades', 'Win_Rate_%', 'Total_PnL', 'Avg_Win_PnL', 'Avg_Loss_PnL', 'Payoff_Ratio', 'Max_Win', 'Max_Loss']
    
    pd.options.display.float_format = '{:,.2f}'.format
    print(final_df[final_cols].to_string(index=False))
    pd.reset_option('display.float_format')

    # *** PHẦN CHÚ THÍCH CHI TIẾT ĐÂY RỒI! ***
    print("\n" + "-"*25 + " 💡 CHÚ THÍCH CÁC CỘT 💡 " + "-"*25)
    print("  - Total_Trades: Tổng số lệnh đã đóng của Tactic này.")
    print("  - Win_Rate_%:   Tỷ lệ phần trăm số lệnh thắng trên tổng số lệnh.")
    print("  - Total_PnL:    Tổng lợi nhuận/thua lỗ ròng ($) mà Tactic này tạo ra.")
    print("  - Avg_Win_PnL:  Lợi nhuận trung bình ($) của một lệnh THẮNG.")
    print("  - Avg_Loss_PnL: Mức lỗ trung bình ($) của một lệnh THUA.")
    print("  - Payoff_Ratio: Tỷ lệ Lời/Lỗ. Ví dụ 1.5 nghĩa là khi thắng, bạn ăn được gấp 1.5 lần so với khi thua.")
    print("                  (Càng cao càng tốt, > 1.0 là tích cực).")
    print("  - Max_Win:      Lệnh thắng lớn nhất ($) của Tactic này.")
    print("  - Max_Loss:     Lệnh thua lỗ nặng nhất ($) của Tactic này.")




def display_full_csv_history():
    """Hàm chính để đọc, xử lý và hiển thị toàn bộ lịch sử giao dịch."""
    print("\n" + "="*25 + " 📜 TOÀN BỘ LỊCH SỬ GIAO DỊCH 📜 " + "="*25)
    
    df = read_and_normalize_csv()
    if df is None:
        return

    numeric_cols = [
        'entry_price', 'exit_price', 'initial_sl', 'pnl_usd', 'pnl_percent', 
        'holding_duration_hours', 'entry_score', 'last_score'
    ]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors='coerce')

    df['exit_time_dt'] = pd.to_datetime(df['exit_time'], errors='coerce')
    df.sort_values(by='exit_time_dt', ascending=False, inplace=True)
    
    # *** THÊM CỘT SỐ THỨ TỰ ***
    df.insert(0, 'STT', range(len(df), 0, -1))

    df['Vốn'] = df.apply(lambda r: parse_json_like_string(r.get('initial_entry', '{}')).get('invested_usd', r.get('total_invested_usd')), axis=1)
    df['Reason'] = df['status'].astype(str).str.extract(r'\((.*?)\)').fillna('N/A').iloc[:, 0]
    
    def create_tags(row):
        tags = []
        tactics_used = parse_json_like_string(row.get('tactic_used', '[]'))
        if any("TP1" in s for s in tactics_used if isinstance(s, str)): tags.append("TP1✅")
        if any("Protect_Profit" in s for s in tactics_used if isinstance(s, str)): tags.append("PP✅")
        dca_entries = parse_json_like_string(row.get('dca_entries', '[]'))
        if dca_entries and isinstance(dca_entries, list): tags.append(f"DCA:{len(dca_entries)}")
        return ", ".join(tags) if tags else "---"
    df['Tags'] = df.apply(create_tags, axis=1)
    
    df['Score'] = df.apply(lambda r: f"{r.get('entry_score', 0.0):.1f}→{r.get('last_score', 0.0):.1f}" if pd.notna(r.get('entry_score')) and pd.notna(r.get('last_score')) else "N/A", axis=1)
    df['Zone'] = df.apply(lambda r: f"{r.get('entry_zone', 'N/A')}→{r.get('last_zone', 'N/A')}" if pd.notna(r.get('last_zone')) and r.get('entry_zone') != r.get('last_zone') else r.get('entry_zone', 'N/A'), axis=1)

    df_display = pd.DataFrame()
    df_display['STT'] = df['STT']
    df_display['Time Close'] = df['exit_time_dt'].dt.tz_convert(VIETNAM_TZ).dt.strftime('%Y-%m-%d %H:%M')
    df_display['Symbol'] = df['symbol'].astype(str) + '-' + df['interval'].astype(str)
    df_display['Vốn'] = pd.to_numeric(df['Vốn'], errors='coerce').apply(lambda x: f"${x:,.2f}" if pd.notna(x) else "N/A")
    df_display['Giá vào'] = df['entry_price'].apply(format_price_dynamically)
    df_display['Giá ra'] = df['exit_price'].apply(format_price_dynamically)
    df_display['PnL $'] = df['pnl_usd'].apply(lambda x: f"${x:+.2f}" if pd.notna(x) else "N/A")
    df_display['PnL %'] = df['pnl_percent'].apply(lambda x: f"{x:+.2f}%" if pd.notna(x) else "N/A")
    df_display['Hold (h)'] = df['holding_duration_hours'].apply(lambda x: f"{x:.1f}" if pd.notna(x) else "N/A")
    df_display['Score'] = df['Score']
    df_display['Zone'] = df['Zone']
    df_display['Tactic'] = df['opened_by_tactic']
    df_display['Reason'] = df['Reason']
    df_display['Tags'] = df['Tags']
    
    pd.set_option('display.max_rows', None)
    print(df_display.to_string(index=False))
    pd.reset_option('display.max_rows')

    print("\n" + "="*75)
    
    # Gọi hàm phân tích Tactic
    analyze_tactic_performance(df)
    
    print("\n" + "="*75)
    print(f"📊 Tổng cộng: {len(df)} giao dịch đã được phân tích.")

if __name__ == "__main__":
    try:
        display_full_csv_history()
    except Exception as e:
        print(f"\n🔥🔥🔥 Đã xảy ra lỗi không mong muốn: {e}")
        traceback.print_exc()
