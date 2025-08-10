# backtest/control_panel.py
# -*- coding: utf-8 -*-
"""
Control Panel v2.2 (FIXED & STABLE) for Paper Trading
Date: 2025-08-10
"""
import os
import sys
import json
import uuid
import traceback
import requests
import pytz
import pandas as pd
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
sys.path.append(PROJECT_ROOT)

try:
    from paper_trade import PaperTrader, Config
except ImportError as e:
    sys.exit(f"❌ Lỗi: Không thể import module cần thiết: {e}.")

STATE_FILE = Config.STATE_FILE
TRADE_HISTORY_CSV_FILE = Config.TRADE_HISTORY_CSV_FILE
VIETNAM_TZ = Config.VIETNAM_TZ

def get_current_price(symbol: str) -> float | None:
    url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        return float(response.json()['price'])
    except Exception:
        return None

def select_from_list(options: list, prompt: str, display_list: list | None = None) -> any:
    if not options: return None
    display = display_list if display_list is not None else options
    for i, item in enumerate(display): print(f"  {i+1}. {item}")
    while True:
        try:
            choice_str = input(prompt)
            if not choice_str: return None
            choice = int(choice_str)
            if 1 <= choice <= len(options): return options[choice - 1]
            else: print("⚠️ Lựa chọn không hợp lệ.")
        except ValueError: print("⚠️ Vui lòng nhập một con số.")

def show_dashboard():
    print("\n" + "="*80)
    print(f"📊 BẢNG ĐIỀU KHIỂN & TRẠNG THÁI LỆNH - {datetime.now(VIETNAM_TZ).strftime('%H:%M %d-%m-%Y')} 📊")
    try:
        trader = PaperTrader()
        active_trades = trader.state.get("active_trades", [])
        symbols_needed = list(set(trade['symbol'] for trade in active_trades))
        prices = {sym: get_current_price(sym) for sym in symbols_needed}
        equity = trader._calculate_total_equity(realtime_prices=prices)
        if equity is None:
            print("\n⚠️ Không thể tính tổng tài sản do thiếu dữ liệu giá.")
            return None
        print("\n" + trader._build_report_header(equity))
        print(trader._build_pnl_summary_line(prices))
        print("\n" + "---" * 10 + " 🛰️ DANH SÁCH LỆNH ĐANG MỞ 🛰️ " + "---" * 10)
        if not active_trades:
            print("ℹ️ Không có lệnh nào đang mở.")
            return None
        for i, trade in enumerate(sorted(active_trades, key=lambda x: x['entry_time'])):
            price = prices.get(trade['symbol'])
            if price is None:
                print(f"{(i+1):>2}. ⚠️ {trade['symbol']} - Không thể lấy giá hiện tại.")
                continue
            details_text = trader._build_trade_details_for_report(trade, current_price=price)
            print(f"{(i+1):>2}. " + details_text.lstrip())
        return active_trades
    except Exception as e:
        print(f"❌ Lỗi khi hiển thị dashboard: {e}")
        traceback.print_exc()
        return None

def view_csv_history():
    print("\n" + "---" * 10 + " 📜 20 Giao dịch cuối từ file CSV 📜 " + "---" * 10)
    try:
        if not os.path.exists(TRADE_HISTORY_CSV_FILE):
            print("ℹ️ Không tìm thấy file trade_history.csv."); return
        df = pd.read_csv(TRADE_HISTORY_CSV_FILE, engine='python', on_bad_lines='skip')
        if df.empty:
            print("ℹ️ File lịch sử trống."); return
        
        df['exit_time_dt'] = pd.to_datetime(df['exit_time'], errors='coerce')
        df.dropna(subset=['exit_time_dt'], inplace=True)
        df_sorted = df.sort_values(by='exit_time_dt', ascending=False).head(20)
        
        cols_to_use = ['exit_time_dt', 'symbol', 'interval', 'pnl_usd', 'pnl_percent', 'holding_duration_hours', 'opened_by_tactic', 'status']
        df_display = df_sorted[[c for c in cols_to_use if c in df_sorted.columns]].copy()
        
        df_display['Time'] = df_display['exit_time_dt'].dt.strftime('%m-%d %H:%M')
        df_display['pnl_usd'] = pd.to_numeric(df_display['pnl_usd'], errors='coerce').apply(lambda x: f"${x:+.2f}")
        df_display['pnl_percent'] = pd.to_numeric(df_display['pnl_percent'], errors='coerce').apply(lambda x: f"({x:+.2f}%)")
        df_display.rename(columns={'holding_duration_hours': 'Hold(h)', 'opened_by_tactic': 'Tactic'}, inplace=True)
        
        final_cols = [c for c in ['Time', 'symbol', 'interval', 'pnl_usd', 'pnl_percent', 'Hold(h)', 'Tactic', 'status'] if c in df_display.columns]
        print(df_display[final_cols].to_string(index=False))
    except Exception as e:
        print(f"⚠️ Lỗi khi đọc file CSV: {e}"); traceback.print_exc()

def show_tactic_analysis():
    print("\n" + "="*15 + " 📊 PHÂN TÍCH HIỆU SUẤT TACTIC 📊 " + "="*15)
    try:
        if not os.path.exists(TRADE_HISTORY_CSV_FILE):
            print("ℹ️ Không tìm thấy file trade_history.csv."); return
        df = pd.read_csv(TRADE_HISTORY_CSV_FILE, on_bad_lines='skip')
        df['pnl_usd'] = pd.to_numeric(df['pnl_usd'], errors='coerce')
        df = df[df['pnl_usd'].notna() & df['status'].str.contains('Closed', na=False, case=False)]
        if df.empty:
            print("ℹ️ Không có dữ liệu hợp lệ để phân tích."); return
        grouped = df.groupby('opened_by_tactic').agg(
            Total_Trades=('pnl_usd', 'count'), Total_PnL=('pnl_usd', 'sum'),
            Wins=('pnl_usd', lambda x: (x > 0).sum()),
            Avg_Win_PnL=('pnl_usd', lambda x: x[x > 0].mean()),
            Avg_Loss_PnL=('pnl_usd', lambda x: x[x <= 0].mean())
        ).fillna(0)
        grouped['Win_Rate_%'] = (grouped['Wins'] / grouped['Total_Trades'] * 100).where(grouped['Total_Trades'] > 0, 0)
        grouped['Payoff_Ratio'] = (grouped['Avg_Win_PnL'] / abs(grouped['Avg_Loss_PnL'])).where(grouped['Avg_Loss_PnL'] != 0, float('inf'))
        win_rate = grouped['Wins'] / grouped['Total_Trades'].replace(0,1)
        loss_rate = 1 - win_rate
        grouped['Expectancy_$'] = (win_rate * grouped['Avg_Win_PnL']) + (loss_rate * grouped['Avg_Loss_PnL'])
        formatted_df = grouped.reset_index().rename(columns={'opened_by_tactic': 'Tactic'})
        formatted_df = formatted_df[['Tactic', 'Total_Trades', 'Win_Rate_%', 'Total_PnL', 'Expectancy_$', 'Payoff_Ratio']]
        print("Chú thích: Expectancy_$: Lợi nhuận kỳ vọng mỗi lệnh | Payoff_Ratio: Lãi trung bình / Lỗ trung bình")
        print("-" * 80)
        pd.options.display.float_format = '{:,.2f}'.format
        print(formatted_df.sort_values(by="Total_PnL", ascending=False).to_string(index=False))
        pd.options.display.float_format = None
    except Exception as e:
        print(f"⚠️ Lỗi khi phân tích: {e}")

def manual_report():
    print("\n" + "📜" * 10 + " TẠO BÁO CÁO THỦ CÔNG " + "📜" * 10)
    try:
        trader = PaperTrader()
        prices = {t['symbol']: get_current_price(t['symbol']) for t in trader.state.get('active_trades', [])}
        equity = trader._calculate_total_equity(realtime_prices=prices)
        if equity is None:
            print("❌ Không thể tạo báo cáo do lỗi API giá."); return
        report_content = trader._build_report_text(prices, equity)
        print("\n" + "="*80); print(report_content); print("="*80)
        if Config.ALERT_CONFIG.get("DISCORD_WEBHOOK_URL") and input("\n👉 Gửi báo cáo này lên Discord? (y/n): ").lower() == 'y':
            print("... Đang gửi lên Discord..."); trader._send_discord_message(report_content); print("✅ Đã gửi.")
    except Exception as e:
        print(f"❌ Lỗi khi tạo báo cáo: {e}"); traceback.print_exc()

def close_manual_trades():
    print("\n" + "🎬" * 10 + " ĐÓNG LỆNH THỦ CÔNG " + "🎬" * 10)
    active_trades = show_dashboard()
    if not active_trades: return
    try:
        trader = PaperTrader()
        choice_str = input("\n👉 Nhập số thứ tự lệnh cần đóng (vd: 1,3). 'all' để đóng tất cả. Enter để hủy: ").lower()
        if not choice_str: return
        trades_to_process = []
        if choice_str == 'all':
            if input("⚠️ CẢNH BÁO: Đóng tất cả vị thế? (y/n): ").lower() == 'y':
                trades_to_process = active_trades
        else:
            indices_to_close = {int(p.strip()) - 1 for p in choice_str.split(',') if p.strip().isdigit()}
            trades_to_process = [active_trades[i] for i in sorted(indices_to_close) if 0 <= i < len(active_trades)]
        if not trades_to_process: print("❌ Không có lựa chọn hợp lệ."); return
        closed_count = 0
        for trade in trades_to_process:
            print(f"⚡️ Đang xử lý đóng lệnh {trade['symbol']}...")
            current_price = get_current_price(trade['symbol'])
            if current_price is None:
                print(f"❌ Không thể đóng {trade['symbol']} vì lỗi API giá."); continue
            if trader._close_trade_simulated(trade, "Panel Manual", current_price):
                print(f"✅ Đã đóng thành công.")
                closed_count += 1
        if closed_count > 0:
            trader._save_state()
            print(f"\n✅ Đã đóng {closed_count} lệnh và lưu trạng thái.")
    except Exception as e:
        print(f"\n❌ Lỗi không mong muốn: {e}")

def open_manual_trade():
    print("\n" + "🔥" * 10 + " MỞ LỆNH MỚI THỦ CÔNG " + "🔥" * 10)
    try:
        trader = PaperTrader()
        print(f"💵 Tiền mặt khả dụng: ${trader.state.get('cash', 0):,.2f}")
        symbol = select_from_list(Config.SYMBOLS_TO_SCAN, "👉 Chọn Symbol: ")
        if not symbol: return
        interval = select_from_list(Config.ALL_TIME_FRAMES, "👉 Chọn Interval: ")
        if not interval: return
        tactic_name = select_from_list(list(Config.TACTICS_LAB.keys()), "👉 Chọn Tactic: ")
        if not tactic_name: return
        entry_price = float(input(f"👉 Giá vào lệnh (Entry) cho {symbol}: "))
        invested_usd = float(input("👉 Số vốn đầu tư (USD): "))
        if invested_usd <= 0 or invested_usd > trader.state.get('cash', 0):
            print("❌ Vốn không hợp lệ."); return
        tactic_cfg = Config.TACTICS_LAB.get(tactic_name, {})
        risk_dist = entry_price * Config.RISK_RULES_CONFIG["MAX_SL_PERCENT_BY_TIMEFRAME"].get(interval, 0.07)
        sl_price = entry_price - risk_dist
        tp_price = entry_price + (risk_dist * tactic_cfg.get("RR", 2.0))
        new_trade = {
            "trade_id": str(uuid.uuid4()), "symbol": symbol, "interval": interval, "status": "ACTIVE",
            "opened_by_tactic": tactic_name, "trade_type": "LONG", "entry_price": entry_price,
            "quantity": invested_usd / entry_price, "tp": tp_price, "sl": sl_price, "initial_sl": sl_price,
            "initial_entry": {"price": entry_price, "invested_usd": invested_usd},
            "total_invested_usd": invested_usd, "entry_time": datetime.now(VIETNAM_TZ).isoformat(),
            "entry_score": 9.9, "last_score": 9.9, "entry_zone": "Manual", "last_zone": "Manual",
            "tactic_used": ["Manual_Entry"], "dca_entries": [], "realized_pnl_usd": 0.0,
            "peak_pnl_percent": 0.0, "tp1_hit": False, "partial_closed_by_score": False, "profit_taken": False
        }
        trader.state['cash'] -= invested_usd
        trader.state['active_trades'].append(new_trade)
        trader._save_state()
        print(f"\n✅ Đã tạo lệnh mới cho {symbol} và lưu trạng thái.")
    except (ValueError, TypeError): print("❌ Vui lòng nhập số hợp lệ.")
    except Exception as e: print(f"❌ Lỗi: {e}")

def extend_stale_check():
    print("\n" + "🛡️" * 10 + " GIA HẠN LỆNH 'Ì' " + "🛡️" * 10)
    active_trades = show_dashboard()
    if not active_trades: return
    try:
        trader = PaperTrader()
        trade_to_extend = select_from_list(active_trades, "👉 Chọn số lệnh cần gia hạn (Enter để hủy): ", [f"{t['symbol']}-{t['interval']}" for t in active_trades])
        if not trade_to_extend: return
        hours = float(input("👉 Nhập số giờ muốn gia hạn (ví dụ: 48): "))
        if hours <= 0: print("❌ Số giờ phải dương."); return
        trade_found = False
        for trade in trader.state['active_trades']:
            if trade['trade_id'] == trade_to_extend['trade_id']:
                override_until = datetime.now(VIETNAM_TZ) + timedelta(hours=hours)
                trade['stale_override_until'] = override_until.isoformat()
                print(f"\n✅ Lệnh {trade['symbol']} đã gia hạn đến: {override_until.strftime('%Y-%m-%d %H:%M:%S')}")
                trade_found = True
                break
        if trade_found: trader._save_state()
        else: print("❌ Không tìm thấy trade để cập nhật.")
    except (ValueError, TypeError): print("❌ Vui lòng nhập số hợp lệ.")
    except Exception as e: print(f"❌ Lỗi: {e}")

def reset_state():
    print("\n" + "💣" * 10 + " RESET TRẠNG THÁI " + "💣" * 10)
    print("CẢNH BÁO: Hành động này sẽ XÓA file state và history, đưa bot về trạng thái ban đầu.")
    if input("👉 Nhập 'RESET' để xác nhận: ") != 'RESET':
        print("Hủy thao tác."); return
    if input("👉 Xác nhận lần cuối, nhập 'DELETE ALL DATA' để tiếp tục: ") != 'DELETE ALL DATA':
        print("Hủy thao tác."); return
    try:
        if os.path.exists(STATE_FILE):
            os.remove(STATE_FILE); print(f"✅ Đã xóa file: {os.path.basename(STATE_FILE)}")
        if os.path.exists(TRADE_HISTORY_CSV_FILE):
            os.remove(TRADE_HISTORY_CSV_FILE); print(f"✅ Đã xóa file: {os.path.basename(TRADE_HISTORY_CSV_FILE)}")
        print("\n✅ Reset hoàn tất. Lần chạy tiếp theo sẽ bắt đầu lại từ đầu.")
    except Exception as e:
        print(f"❌ Lỗi khi reset: {e}")

def main():
    menu_actions = { '1': show_dashboard, '2': view_csv_history, '3': show_tactic_analysis, '4': manual_report, '5': open_manual_trade, '6': close_manual_trades, '7': extend_stale_check, '8': reset_state, }
    while True:
        print("\n" + "="*15 + " 📊 BẢNG ĐIỀU KHIỂN (PAPER-v2.2) 📊 " + "="*15)
        print("--- Xem & Phân tích ---"); print(" 1. Dashboard & Trạng thái lệnh"); print(" 2. Lịch sử giao dịch (từ CSV)"); print(" 3. Phân tích Hiệu suất Tactic"); print(" 4. Tạo & Gửi báo cáo thủ công")
        print("\n--- Hành động Mô phỏng ---"); print(" 5. Mở lệnh mới thủ công"); print(" 6. Đóng lệnh thủ công (chọn một hoặc nhiều)"); print(" 7. Gia hạn kiểm tra cho một lệnh 'ì'")
        print("\n--- Bảo trì ---"); print(" 8. Reset toàn bộ trạng thái")
        print("\n 0. Thoát"); print("="*67)
        choice = input("👉 Vui lòng chọn một chức năng: ")
        if choice == '0': print("👋 Tạm biệt!"); break
        action = menu_actions.get(choice)
        if action:
            try: action()
            except Exception: traceback.print_exc()
        else: print("⚠️ Lựa chọn không hợp lệ.")
if __name__ == "__main__":
    main()
