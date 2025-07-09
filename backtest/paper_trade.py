# -*- coding: utf-8 -*-
"""
paper_trade.py - Quản lý Danh mục & Rủi ro Thông minh
Version: 2.3 - "Tướng Mưu Lược" - HOÀN THIỆN BÁO CÁO (TINH GỌN)
Date: 2025-07-08

Description:
Phiên bản hoàn thiện nhất, tích hợp cơ chế chọn Tactic "đa giác quan" thông minh,
kết hợp với toàn bộ các tính năng phòng thủ và tấn công đã được phát triển.
Bot giờ đây sẽ hoạt động như một vị tướng, biết phân tích thời thế (Macro)
và thực lực của từng binh sĩ (Micro) để chọn ra chiến thuật phù hợp nhất.
Đặc biệt cải thiện báo cáo Discord để cung cấp thông tin chi tiết, minh bạch nhưng TINH GỌN hơn.
"""
import os
import sys
import json
import uuid
import time
import requests
import pytz
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Any, Tuple
from dotenv import load_dotenv
import traceback

# --- Tải và Thiết lập ---
load_dotenv()
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
sys.path.append(PROJECT_ROOT)
PAPER_DATA_DIR = os.path.join(BASE_DIR, "paper_data")
os.makedirs(PAPER_DATA_DIR, exist_ok=True)

try:
    from indicator import get_price_data, calculate_indicators
    from trade_advisor import get_advisor_decision, FULL_CONFIG as ADVISOR_BASE_CONFIG
except ImportError:
    sys.exit("Lỗi: Thiếu module 'indicator' hoặc 'trade_advisor'. Hãy chắc chắn chúng ở đúng vị trí.")

# ==============================================================================
# ================= ⚙️ TRUNG TÂM CẤU HÌNH (v2.3) ⚙️ =================
# ==============================================================================

INITIAL_CAPITAL = 10000.0

GENERAL_CONFIG = {
    "DATA_FETCH_LIMIT": 300,
    "DAILY_SUMMARY_TIMES": ["08:05", "20:05"],
}

DYNAMIC_ALERT_CONFIG = {
    "ENABLED": True,
    "COOLDOWN_HOURS": 4,
    "FORCE_UPDATE_HOURS": 10,
    "PNL_CHANGE_THRESHOLD_PCT": 1.5
}

RISK_RULES_CONFIG = {
    "MAX_ACTIVE_TRADES": 7,
    "STALE_TRADE_RULES": {
        "1h": {"HOURS": 48,  "PROGRESS_THRESHOLD": 0.25, "MIN_RISK_BUFFER_PCT": 0.2},
        "4h": {"HOURS": 96,  "PROGRESS_THRESHOLD": 0.25, "MIN_RISK_BUFFER_PCT": 0.2},
        "1d": {"HOURS": 240, "PROGRESS_THRESHOLD": 0.20, "MIN_RISK_BUFFER_PCT": 0.1}
    }
}

CAPITAL_MANAGEMENT_CONFIG = {
    "TACTIC_TO_TIER_MAP": {
        "AI_Aggressor": "LOW_RISK", "Breakout_Hunter": "LOW_RISK",
        "Balanced_Trader": "MEDIUM_RISK", "Market_Mirror": "MEDIUM_RISK",
        "Dip_Hunter": "HIGH_RISK", "Range_Trader": "HIGH_RISK", "Cautious_Observer": "HIGH_RISK",
    },
    "MAX_TOTAL_EXPOSURE_PCT": 0.60
}

# --- CẤU HÌNH DCA ---
DCA_CONFIG = {
    "ENABLED": True,
    "MAX_DCA_ENTRIES": 2, # Tối đa 2 lần DCA cho một lệnh
    "TRIGGER_DROP_PCT": -5.0, # Kích hoạt DCA khi giá giảm 5% so với giá vào lệnh gần nhất
    "SCORE_MIN_THRESHOLD": 4.5, # Chỉ DCA khi điểm vẫn trên 4.5
    "CAPITAL_MULTIPLIER": 1.5 # Lần DCA sau sẽ dùng số vốn gấp 1.5 lần lần đầu tư trước
}

ALERT_CONFIG = {
    "DISCORD_WEBHOOK_URL": os.getenv("DISCORD_PAPER_WEBHOOK"),
    "DISCORD_CHUNK_DELAY_SECONDS": 2,
}

TACTICS_LAB = {
    "AI_Aggressor": {
        "NOTES": "Tin vào AI, tự động gồng lời với Trailing SL",
        "WEIGHTS": {'tech': 0.1, 'context': 0.1, 'ai': 0.8},
        "ENTRY_SCORE": 6.3, "RR": 2.5, "USE_ATR_SL": True, "ATR_SL_MULTIPLIER": 3.0,
        "USE_TRAILING_SL": True, "TRAIL_ACTIVATION_RR": 1.0, "TRAIL_DISTANCE_RR": 0.8,
        "ENABLE_PARTIAL_TP": True, "TP1_RR_RATIO": 0.8, "TP1_PROFIT_PCT": 0.5
    },
    "Balanced_Trader": {
        "NOTES": "Cân bằng...", "WEIGHTS": {'tech': 0.4, 'context': 0.2, 'ai': 0.4},
        "ENTRY_SCORE": 6.0, "RR": 2.2, "USE_ATR_SL": True, "ATR_SL_MULTIPLIER": 2.5,
        "ENABLE_PARTIAL_TP": False
    },
    "Dip_Hunter": {
        "NOTES": "Bắt đáy khi sợ hãi...", "WEIGHTS": {'tech': 0.5, 'context': 0.3, 'ai': 0.2},
        "ENTRY_SCORE": 6.5, "RR": 3.0, "USE_ATR_SL": True, "ATR_SL_MULTIPLIER": 2.0,
        "ENABLE_PARTIAL_TP": True, "TP1_RR_RATIO": 0.7, "TP1_PROFIT_PCT": 0.4
    },
    "Breakout_Hunter": {
        "NOTES": "Săn đột biến giá/volume", "WEIGHTS": {'tech': 0.7, 'context': 0.1, 'ai': 0.2},
        "ENTRY_SCORE": 7.0, "RR": 2.8, "USE_ATR_SL": True, "ATR_SL_MULTIPLIER": 2.0,
        "ENABLE_PARTIAL_TP": False # Breakout thường không TP1
    },
    "Cautious_Observer": {
        "NOTES": "Bảo toàn vốn...", "WEIGHTS": {'tech': 0.5, 'context': 0.5, 'ai': 0.0},
        "ENTRY_SCORE": 8.5, # Rất khó vào lệnh
        "ENABLE_PARTIAL_TP": False
    },
}

SYMBOLS_TO_SCAN = ["ETHUSDT", "AVAXUSDT", "INJUSDT", "LINKUSDT", "SUIUSDT", "FETUSDT", "TAOUSDT"]
INTERVALS_TO_SCAN = ["1h", "4h", "1d"]
ALL_TIME_FRAMES = ["1h", "4h", "1d"]
VIETNAM_TZ = pytz.timezone('Asia/Ho_Chi_Minh')

LOG_FILE = os.path.join(PAPER_DATA_DIR, "paper_trade_log.txt")
STATE_FILE = os.path.join(PAPER_DATA_DIR, "paper_trade_state.json")
TRADE_HISTORY_CSV_FILE = os.path.join(PAPER_DATA_DIR, "trade_history.csv")

all_indicators: Dict[str, Any] = {}

# ==============================================================================
# ================= TIỆN ÍCH & CẢNH BÁO =======================================
# ==============================================================================

def log_message(message: str):
    """Ghi log message ra console và file log."""
    timestamp = datetime.now(VIETNAM_TZ).strftime('%Y-%m-%d %H:%M:%S')
    log_entry = f"[{timestamp}] {message}"
    print(log_entry)
    with open(LOG_FILE, "a", encoding="utf-8") as f: f.write(log_entry + "\n")

def load_json_file(path: str, default: Any = None) -> Any:
    """Tải dữ liệu từ file JSON, xử lý lỗi nếu file hỏng hoặc không tồn tại."""
    if not os.path.exists(path): return default if default is not None else {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        log_message(f"⚠️ Cảnh báo: File {path} bị hỏng. Sử dụng giá trị mặc định.")
        return default if default is not None else {}

def save_json_file(path: str, data: Any):
    """Lưu dữ liệu vào file JSON."""
    with open(path, "w", encoding="utf-8") as f: json.dump(data, f, indent=4, ensure_ascii=False)

def send_discord_message_chunks(full_content: str):
    """Gửi tin nhắn dài đến Discord bằng cách chia thành các chunk nhỏ."""
    webhook_url = ALERT_CONFIG.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        log_message("⚠️ Không có Discord Webhook URL. Bỏ qua gửi tin nhắn Discord.")
        return

    max_len = 1900 # Giữ an toàn dưới giới hạn 2000 ký tự của Discord
    lines = full_content.split('\n')
    chunks, current_chunk = [], ""
    
    for line in lines:
        # Nếu thêm dòng này vượt quá max_len, tạo chunk mới
        if len(current_chunk) + len(line) + 1 > max_len:
            if current_chunk: # Chỉ thêm chunk nếu nó không rỗng
                chunks.append(current_chunk)
            current_chunk = line # Bắt đầu chunk mới với dòng hiện tại
        else:
            # Thêm dòng vào chunk hiện tại, đảm bảo có newline nếu chunk không rỗng
            current_chunk += ("\n" + line) if current_chunk else line
    
    # Thêm chunk cuối cùng nếu có
    if current_chunk:
        chunks.append(current_chunk)

    total_chunks = len(chunks)
    for i, chunk in enumerate(chunks):
        # Thêm chỉ số phần nếu có nhiều chunk
        content_to_send = f"*(Phần {i+1}/{total_chunks})*\n{chunk}" if total_chunks > 1 else chunk
        try:
            requests.post(webhook_url, json={"content": content_to_send}, timeout=15).raise_for_status()
            # Tránh Rate Limit nếu có nhiều chunk
            if i < total_chunks - 1:
                time.sleep(ALERT_CONFIG["DISCORD_CHUNK_DELAY_SECONDS"])
        except requests.exceptions.RequestException as e:
            log_message(f"❌ Lỗi gửi chunk Discord {i+1}/{total_chunks}: {e}")
            break # Dừng nếu có lỗi gửi một chunk

def get_current_pnl(trade: Dict) -> Tuple[float, float]:
    """Tính toán PnL (Profit and Loss) hiện tại của một lệnh."""
    current_data = all_indicators.get(trade["symbol"], {}).get(trade["interval"])
    if not (current_data and current_data.get('price', 0) > 0 and trade.get('entry_price', 0) > 0):
        return 0.0, 0.0
    pnl_percent = (current_data['price'] - trade['entry_price']) / trade['entry_price']
    return trade.get('total_invested_usd', 0.0) * pnl_percent, pnl_percent * 100

def export_trade_history_to_csv(closed_trades: List[Dict]):
    """Xuất các lệnh đã đóng ra file CSV."""
    if not closed_trades: return
    try:
        df = pd.DataFrame(closed_trades)
        df['entry_time'] = pd.to_datetime(df['entry_time']).dt.tz_convert(VIETNAM_TZ)
        if 'exit_time' in df.columns:
            df['exit_time'] = pd.to_datetime(df['exit_time']).dt.tz_convert(VIETNAM_TZ)
            df['holding_duration_hours'] = round((df['exit_time'] - df['entry_time']).dt.total_seconds() / 3600, 2)
        else:
            df['holding_duration_hours'] = None

        cols = ["trade_id", "symbol", "interval", "status", "opened_by_tactic", "trade_type",
                "entry_price", "exit_price", "tp", "sl", "total_invested_usd",
                "pnl_usd", "pnl_percent", "entry_time", "exit_time", "holding_duration_hours",
                "entry_score", "dca_entries"]
        
        df = df[[c for c in cols if c in df.columns]]
        
        if 'dca_entries' in df.columns:
            df['dca_entries'] = df['dca_entries'].apply(lambda x: json.dumps(x) if x else '[]')

        df.to_csv(TRADE_HISTORY_CSV_FILE, mode='a' if os.path.exists(TRADE_HISTORY_CSV_FILE) else 'w', header=not os.path.exists(TRADE_HISTORY_CSV_FILE), index=False, encoding="utf-8")
        log_message(f"✅ Đã xuất {len(df)} lệnh đã đóng vào {TRADE_HISTORY_CSV_FILE}")
    except Exception as e:
        log_message(f"❌ Lỗi khi xuất lịch sử giao dịch ra CSV: {e}")

def safe_get_price_data(symbol: str, interval: str, limit: int):
    """Lấy dữ liệu giá một cách an toàn, xử lý lỗi API hoặc dữ liệu rỗng."""
    try:
        df = get_price_data(symbol, interval, limit=limit)
        if df is None or getattr(df, "empty", True):
            log_message(f"⚠️ Không có dữ liệu cho {symbol}-{interval}")
            return None
        return df
    except Exception as e:
        log_message(f"❌ Lỗi fetch dữ liệu {symbol}-{interval}: {e}")
        return None

# ==============================================================================
# ================== QUẢN LÝ VỊ THẾ ===========================================
# ==============================================================================

def calculate_total_equity(state: Dict) -> float:
    """Tính tổng tài sản (tiền mặt + giá trị các lệnh đang mở)."""
    # Đảm bảo total_invested_usd được truy cập an toàn
    return state.get('cash', INITIAL_CAPITAL) + sum(t.get('total_invested_usd', 0.0) + get_current_pnl(t)[0] for t in state.get('active_trades', []))

def determine_dynamic_capital_pct(atr_percent: float) -> float:
    """Xác định tỷ lệ vốn đầu tư cho mỗi lệnh dựa trên ATR (biến động)."""
    if atr_percent <= 1.5: base = 0.10
    elif atr_percent <= 3: base = 0.07
    elif atr_percent <= 5: base = 0.05
    else: base = 0.03
    return max(0.03, min(base, 0.12))

def calculate_average_price(trade: Dict) -> float:
    """Tính giá vào lệnh trung bình sau các lần DCA."""
    # Đảm bảo initial_entry và invested_usd được truy cập an toàn
    initial_investment = trade['initial_entry'].get('invested_usd', 0.0)
    initial_price = trade['initial_entry'].get('price', 0.0)
    total_invested_value = initial_investment
    total_cost = initial_investment * initial_price

    for dca in trade.get('dca_entries', []):
        total_invested_value += dca.get('invested_usd', 0.0)
        total_cost += dca.get('invested_usd', 0.0) * dca.get('entry_price', 0.0)

    return total_cost / total_invested_value if total_invested_value > 0 else 0

def handle_trade_closure(portfolio_state: Dict) -> List[Dict]:
    """
    Xử lý đóng lệnh: kiểm tra chốt lời (TP), cắt lỗ (SL), chốt lời từng phần (TP1)
    và cập nhật Trailing Stop Loss (TSL).
    """
    closed_trades, newly_closed_details = [], []
    now_vn = datetime.now(VIETNAM_TZ)

    for trade in portfolio_state["active_trades"][:]:
        data = all_indicators.get(trade['symbol'], {}).get(trade['interval'], {})
        current_price = data.get('price', 0)
        if not current_price > 0: continue

        status, exit_p = (None, None)
        tactic_cfg = TACTICS_LAB.get(trade['opened_by_tactic'], {})

        # Cập nhật Trailing SL
        if tactic_cfg.get("USE_TRAILING_SL", False) and 'initial_risk_dist' in trade and trade['initial_risk_dist'] > 0:
            # Chỉ cập nhật TSL nếu lệnh đang có lãi (vượt mức kích hoạt)
            pnl_ratio_from_entry = (current_price - trade['entry_price']) / trade['initial_risk_dist']
            if pnl_ratio_from_entry >= tactic_cfg["TRAIL_ACTIVATION_RR"]:
                new_trailing_sl = current_price - (trade['initial_risk_dist'] * tactic_cfg.get("TRAIL_DISTANCE_RR", 0.8))
                if new_trailing_sl > trade.get('trailing_sl', trade['sl']): # Chỉ nâng TSL lên
                    trade['trailing_sl'] = new_trailing_sl
                    trade['sl'] = new_trailing_sl # Đồng bộ SL gốc với TSL
                    # log_message(f"➡️ Cập nhật Trailing SL cho {trade['symbol']}: {trade['trailing_sl']:.4f}")

        # Kiểm tra TP1 (Partial Take Profit)
        if tactic_cfg.get("ENABLE_PARTIAL_TP", False) and not trade.get('tp1_taken', False) and 'initial_risk_dist' in trade and trade['initial_risk_dist'] > 0:
            tp1_price = trade['entry_price'] + (trade['initial_risk_dist'] * tactic_cfg.get("TP1_RR_RATIO", 0.8))
            if current_price >= tp1_price:
                profit_taken_pct = tactic_cfg.get("TP1_PROFIT_PCT", 0.5)
                invested_to_close = trade.get('total_invested_usd', 0.0) * profit_taken_pct # Sử dụng .get()
                
                partial_pnl_usd = (tp1_price - trade['entry_price']) / trade['entry_price'] * invested_to_close
                
                portfolio_state['cash'] += (invested_to_close + partial_pnl_usd)
                trade['total_invested_usd'] = trade.get('total_invested_usd', 0.0) - invested_to_close # Sử dụng .get()
                trade['tp1_taken'] = True
                trade['sl'] = trade['entry_price'] # Dời SL về hòa vốn sau TP1
                # Nếu có Trailing SL, đảm bảo nó cũng không thấp hơn hòa vốn
                trade['trailing_sl'] = max(trade.get('trailing_sl', trade['sl']), trade['entry_price'])
                
                log_message(f"💰 Đã chốt lời TP1 cho {trade['symbol']} (${invested_to_close:,.2f}) | PnL TP1: ${partial_pnl_usd:,.2f}. SL dời về hòa vốn.")
                newly_closed_details.append(f"💰 {trade['symbol']} (TP1): PnL ${partial_pnl_usd:,.2f}")

        # Kiểm tra SL (bao gồm cả Trailing SL đã cập nhật)
        # Sử dụng trade['sl'] vì nó đã được đồng bộ với trailing_sl
        if current_price <= trade['sl']:
            status, exit_p = "SL", trade['sl']
        
        # Kiểm tra TP cuối cùng
        elif current_price >= trade['tp']:
            status, exit_p = "TP", trade['tp']

        if status:
            pnl_ratio = (exit_p - trade['entry_price']) / trade['entry_price']
            pnl_usd = trade.get('total_invested_usd', 0.0) * pnl_ratio # Sử dụng .get()
            
            portfolio_state['cash'] += (trade.get('total_invested_usd', 0.0) + pnl_usd) # Sử dụng .get()
            
            trade.update({
                'status': f'Closed ({status})',
                'exit_price': exit_p,
                'exit_time': now_vn.isoformat(),
                'pnl_usd': pnl_usd,
                'pnl_percent': pnl_ratio * 100
            })
            
            portfolio_state['active_trades'].remove(trade)
            portfolio_state['trade_history'].append(trade)
            closed_trades.append(trade)
            icon = '✅' if status == 'TP' else '❌'
            log_message(f"{icon} Đã đóng lệnh {status}: {trade['symbol']} | PnL: ${pnl_usd:,.2f}")
            newly_closed_details.append(f"{icon} {trade['symbol']} ({status}): PnL ${pnl_usd:,.2f}")

    if newly_closed_details:
        portfolio_state['temp_newly_closed_trades'] = newly_closed_details
    return closed_trades

def handle_stale_trades(portfolio_state: Dict) -> List[Dict]:
    """Xử lý các lệnh "ì ạch" không có tiến triển sau một thời gian nhất định."""
    closed_trades, newly_closed_details = [], []
    now_aware = datetime.now(VIETNAM_TZ)

    for trade in portfolio_state.get("active_trades", [])[:]:
        rules = RISK_RULES_CONFIG["STALE_TRADE_RULES"].get(trade.get("interval"))
        if not rules: continue

        entry_time = datetime.fromisoformat(trade['entry_time'])
        holding_duration_hours = (now_aware - entry_time).total_seconds() / 3600

        if holding_duration_hours > rules["HOURS"]:
            pnl_usd, pnl_pct = get_current_pnl(trade)
            
            progress_made = False
            # Nếu đã có lãi hoặc đạt ngưỡng tiến triển
            if pnl_pct >= rules["PROGRESS_THRESHOLD"] * 100:
                progress_made = True
            
            # Kiểm tra "đệm rủi ro" so với SL hiện tại của lệnh (đã đồng bộ với TSL)
            current_data = all_indicators.get(trade['symbol'], {}).get(trade['interval'], {})
            current_price = current_data.get('price', 0)
            
            if current_price > 0 and trade.get('entry_price', 0) > 0 and trade.get('sl', 0) > 0:
                # Khoảng cách từ giá hiện tại đến SL
                current_sl_buffer_pct = (current_price - trade['sl']) / trade['entry_price'] * 100
                if current_sl_buffer_pct >= rules["MIN_RISK_BUFFER_PCT"] * 100:
                    progress_made = True # Vẫn còn "đệm" rủi ro đủ an toàn

            if not progress_made:
                exit_price = all_indicators.get(trade['symbol'], {}).get(trade['interval'], {}).get('price', trade['entry_price'])
                pnl_ratio = (exit_price - trade['entry_price']) / trade['entry_price']
                pnl_usd_final = trade.get('total_invested_usd', 0.0) * pnl_ratio # Sử dụng .get()

                portfolio_state['cash'] += (trade.get('total_invested_usd', 0.0) + pnl_usd_final) # Sử dụng .get()
                
                trade.update({
                    'status': 'Closed (Stale)',
                    'exit_price': exit_price,
                    'exit_time': now_aware.isoformat(),
                    'pnl_usd': pnl_usd_final,
                    'pnl_percent': pnl_ratio * 100
                })
                
                portfolio_state['active_trades'].remove(trade)
                portfolio_state['trade_history'].append(trade)
                closed_trades.append(trade)
                log_message(f"🐌 Đã đóng lệnh ì (Stale): {trade['symbol']} ({trade['interval']}) sau {holding_duration_hours:.1f}h | PnL: ${pnl_usd_final:,.2f}")
                newly_closed_details.append(f"🐌 {trade['symbol']} (Stale): PnL ${pnl_usd_final:,.2f}")
    
    if newly_closed_details:
        portfolio_state.setdefault('temp_newly_closed_trades', []).extend(newly_closed_details)
    return closed_trades

def handle_dca_opportunities(state: Dict, equity: float):
    """Quét các lệnh đang mở để tìm cơ hội DCA (Dollar-Cost Averaging)."""
    if not DCA_CONFIG["ENABLED"]: return

    log_message("🔄 Bắt đầu quét cơ hội DCA cho các lệnh đang mở...")
    current_exposure_usd = sum(t.get('total_invested_usd', 0.0) for t in state.get('active_trades', []))

    for trade in state.get("active_trades", []):
        # Điều kiện 1: Kiểm tra số lần DCA
        if len(trade.get("dca_entries", [])) >= DCA_CONFIG["MAX_DCA_ENTRIES"]:
            continue

        # Điều kiện 2: Kiểm tra giá đã giảm đủ sâu chưa
        current_data = all_indicators.get(trade["symbol"], {}).get(trade["interval"], {})
        current_price = current_data.get('price', 0)
        if not current_price > 0: continue

        # DCA dựa trên giá vào lệnh gần nhất để phản ứng nhanh hơn
        last_entry_price = trade['dca_entries'][-1].get('entry_price', trade['entry_price']) if trade.get('dca_entries') else trade['entry_price']
        price_drop_pct = ((current_price - last_entry_price) / last_entry_price) * 100
        
        if price_drop_pct > DCA_CONFIG["TRIGGER_DROP_PCT"]:
            continue

        # Điều kiện 3: Kiểm tra điểm kỹ thuật có còn tốt không
        decision = get_advisor_decision(trade['symbol'], trade['interval'], current_data, ADVISOR_BASE_CONFIG)
        current_score = decision.get("final_score", 0.0)
        if current_score < DCA_CONFIG["SCORE_MIN_THRESHOLD"]:
            log_message(f"❌ Muốn DCA cho {trade['symbol']} nhưng điểm quá thấp ({current_score:.2f}). Bỏ qua.")
            continue

        # Đủ điều kiện, tính toán DCA
        last_investment = trade['dca_entries'][-1].get('invested_usd', 0.0) if trade.get('dca_entries') else trade.get('total_invested_usd', 0.0)
        dca_investment = last_investment * DCA_CONFIG["CAPITAL_MULTIPLIER"]

        # Kiểm tra giới hạn tổng exposure
        potential_exposure_usd = current_exposure_usd + dca_investment
        if potential_exposure_usd / equity > CAPITAL_MANAGEMENT_CONFIG["MAX_TOTAL_EXPOSURE_PCT"]:
            log_message(f"⚠️ Muốn DCA cho {trade['symbol']} nhưng sẽ vượt ngưỡng exposure tối đa ({potential_exposure_usd/equity:.2%} > {CAPITAL_MANAGEMENT_CONFIG['MAX_TOTAL_EXPOSURE_PCT']:.2%}). Bỏ qua.")
            continue

        if dca_investment > state['cash']:
            log_message(f"⚠️ Muốn DCA cho {trade['symbol']} nhưng không đủ tiền mặt. Cần ${dca_investment:,.2f}, còn ${state['cash']:,.2f}")
            continue
        
        log_message(f"🎯 THỰC HIỆN DCA Lần {len(trade.get('dca_entries', [])) + 1} cho {trade['symbol']}...")
        
        state['cash'] -= dca_investment
        trade.setdefault('dca_entries', []).append({
            "entry_price": current_price,
            "invested_usd": dca_investment,
            "timestamp": datetime.now(VIETNAM_TZ).isoformat()
        })

        new_total_invested = trade.get('total_invested_usd', 0.0) + dca_investment
        new_avg_price = calculate_average_price(trade)
        
        trade['entry_price'] = new_avg_price
        trade['total_invested_usd'] = new_total_invested

        # Cập nhật lại SL/TP dựa trên giá vào lệnh trung bình mới
        initial_risk_dist_original = trade['initial_entry'].get('price', trade['entry_price']) - trade['initial_sl']
        if initial_risk_dist_original <= 0: # Tránh lỗi chia 0 hoặc âm
            initial_risk_dist_original = new_avg_price * 0.02 # Sử dụng new_avg_price làm cơ sở

        tactic_cfg = TACTICS_LAB.get(trade['opened_by_tactic'], {})
        
        trade['sl'] = new_avg_price - initial_risk_dist_original # SL mới theo khoảng cách ban đầu
        trade['tp'] = new_avg_price + (initial_risk_dist_original * tactic_cfg.get('RR', 2.0))

        if tactic_cfg.get("USE_TRAILING_SL", False):
            if 'trailing_sl' in trade and trade.get('initial_entry', {}).get('price', 0) > 0 and trade.get('trailing_sl', 0) > 0:
                original_tsl_dist_from_entry = trade['initial_entry']['price'] - trade['trailing_sl']
                trade['trailing_sl'] = new_avg_price - original_tsl_dist_from_entry
                trade['sl'] = trade['trailing_sl'] # Đồng bộ SL gốc với TSL
            else:
                 trade['trailing_sl'] = trade['sl'] # Nếu chưa kích hoạt hoặc không có initial_entry, TSL = SL mới

            trade['tp1_taken'] = False # Cho phép chốt lời TP1 lại sau DCA

        log_message(f"✅ DCA thành công. Vốn mới cho {trade['symbol']}: ${new_total_invested:,.2f}. Giá TB mới: {new_avg_price:.4f}")

# ==============================================================================
# ================== BỘ NÃO & RA QUYẾT ĐỊNH (v2.2) ============================
# ==============================================================================

def select_best_tactic_for_symbol(market_context: Dict, coin_indicators: Dict) -> str:
    """
    Chọn chiến thuật tối ưu dựa trên cả bối cảnh thị trường (Macro)
    và đặc tính riêng của coin (Micro) bằng hệ thống tính điểm.
    """
    scores = {
        "AI_Aggressor": 0,
        "Balanced_Trader": 0,
        "Dip_Hunter": 0,
        "Breakout_Hunter": 0,
        "Cautious_Observer": 1, # Luôn có 1 điểm cơ bản để làm lựa chọn cuối cùng
    }

    # --- 1. Phân tích bối cảnh thị trường chung (Macro) ---
    fear_greed = market_context.get("fear_greed", 50)
    btc_adx = market_context.get("btc_d1_adx", 20.0)

    # Đánh giá chung về thị trường dựa trên Fear & Greed Index và xu hướng của BTC
    if fear_greed >= 68 and btc_adx > 25: # Rất hưng phấn, xu hướng mạnh
        scores["AI_Aggressor"] += 3
        scores["Breakout_Hunter"] += 2
        scores["Dip_Hunter"] -= 1 # Giảm điểm Dip Hunter khi thị trường đang tăng mạnh
    elif fear_greed <= 30: # Rất sợ hãi
        scores["Dip_Hunter"] += 3
        scores["Cautious_Observer"] += 1
        scores["AI_Aggressor"] -= 1
        scores["Breakout_Hunter"] -= 1
    elif 40 <= fear_greed <= 60 and btc_adx < 20: # Sideway, thiếu xu hướng
        scores["Balanced_Trader"] += 2
        scores["AI_Aggressor"] -= 1
        scores["Breakout_Hunter"] -= 1
    else: # Các trường hợp còn lại
        scores["Balanced_Trader"] += 1
    
    # --- 2. Phân tích đặc tính riêng của Coin (Micro) ---
    # Sử dụng dữ liệu của khung thời gian chính (ví dụ: 4h) cho phân tích micro
    coin_rsi = coin_indicators.get('rsi_14', coin_indicators.get('rsi', 50)) # Lấy rsi_14 hoặc rsi
    coin_adx = coin_indicators.get("adx", 20)
    coin_vol = coin_indicators.get("volume", 0)
    # Đảm bảo vol_ma20 hợp lý, tránh chia cho 0 hoặc giá trị quá nhỏ
    coin_vol_ma = max(coin_indicators.get('vol_ma20', coin_vol * 0.8), 1)
    price = coin_indicators.get("price", 0)
    ema200 = coin_indicators.get("ema_200", price)
    
    # RSI quá bán, tiềm năng hồi phục
    if coin_rsi < 30: scores["Dip_Hunter"] += 3
    # RSI quá mua, có thể đảo chiều
    if coin_rsi > 70: scores["AI_Aggressor"] -= 1 # Giảm hưng phấn khi quá mua
    
    # Xu hướng mạnh và giá trên EMA200 (uptrend)
    if coin_adx > 30 and price > ema200:
        scores["AI_Aggressor"] += 2
        scores["Breakout_Hunter"] += 1
        scores["Dip_Hunter"] -= 2 # Không bắt đáy trong xu hướng tăng mạnh
    
    # Volume tăng đột biến (dấu hiệu breakout)
    if coin_vol > coin_vol_ma * 2.5:
        scores["Breakout_Hunter"] += 3
        scores["AI_Aggressor"] += 1 # Có thể hưởng lợi từ breakout
    
    # Thị trường sideway ở cấp độ coin
    if coin_adx < 20 and 40 < coin_rsi < 60:
        scores["Balanced_Trader"] += 2
        scores["AI_Aggressor"] -= 1 # Không phù hợp cho AI Aggressor
        scores["Breakout_Hunter"] -= 1

    # --- 3. Điều chỉnh điểm cuối cùng và Chọn Tactic có điểm cao nhất ---
    for k in scores: scores[k] = max(0, scores[k]) # Đảm bảo điểm không âm

    best_tactic = max(scores, key=scores.get)
    
    symbol = coin_indicators.get('symbol', 'N/A')
    interval_for_micro = coin_indicators.get('interval', 'N/A')
    log_message(f"🧠 Phân tích Tactic cho {symbol} ({interval_for_micro}): {scores} -> Lựa chọn: {best_tactic}")
    
    return best_tactic

def find_and_open_new_trades(state: Dict, equity: float, context: Dict):
    """Tìm kiếm và mở lệnh mới dựa trên cơ hội tốt nhất được chọn."""
    active_trades = state.get('active_trades', [])
    if len(active_trades) >= RISK_RULES_CONFIG["MAX_ACTIVE_TRADES"]:
        log_message(f"ℹ️ Đã đạt giới hạn {len(active_trades)}/{RISK_RULES_CONFIG['MAX_ACTIVE_TRADES']} lệnh đang mở. Không tìm lệnh mới.")
        return

    potential_opportunities = []

    log_message("🔎 Bắt đầu quét tất cả các symbol để tìm cơ hội...")
    for symbol in SYMBOLS_TO_SCAN:
        if any(t['symbol'] == symbol for t in active_trades):
            log_message(f"ℹ️ {symbol} đang có lệnh mở. Bỏ qua.")
            continue

        # Lấy chỉ báo của khung thời gian chính (ví dụ: 4h) để đưa vào hàm chọn Tactic
        primary_indicators = all_indicators.get(symbol, {}).get("4h")
        if not primary_indicators: # Nếu không có 4h, thử 1d
            primary_indicators = all_indicators.get(symbol, {}).get("1d")
        
        if not primary_indicators:
            log_message(f"⚠️ Không có dữ liệu khung thời gian chính (4h/1d) cho {symbol}. Bỏ qua chọn Tactic.")
            continue

        # Chọn tactic dựa trên market context và micro-indicators của coin đó
        tactic_name = select_best_tactic_for_symbol(context, primary_indicators)
        tactic_cfg = TACTICS_LAB.get(tactic_name, {})

        # Sau khi chọn tactic, quét lại các interval để tìm điểm vào lệnh cụ thể
        for interval in INTERVALS_TO_SCAN:
            indicators = all_indicators.get(symbol, {}).get(interval)
            if not (indicators and indicators.get('price', 0) > 0):
                continue

            decision = get_advisor_decision(symbol, interval, indicators, ADVISOR_BASE_CONFIG, weights_override=tactic_cfg.get("WEIGHTS"))
            score = decision.get("final_score", 0.0)
            
            if score >= tactic_cfg.get("ENTRY_SCORE", 9.9):
                log_message(f"✅ Tìm thấy cơ hội: {symbol} ({interval}) với Tactic '{tactic_name}', Điểm: {score:.2f}")
                potential_opportunities.append({
                    "decision": decision,
                    "tactic_name": tactic_name,
                    "tactic_cfg": tactic_cfg
                })

    if not potential_opportunities:
        log_message("ℹ️ Phiên này không tìm thấy cơ hội nào đủ điều kiện.")
        return

    # Chỉ chọn cơ hội có điểm số cao nhất (tinh anh) để mở lệnh
    best_opportunity = sorted(potential_opportunities, key=lambda x: x['decision']['final_score'], reverse=True)[0]
    
    decision_data = best_opportunity['decision']
    tactic_name = best_opportunity['tactic_name']
    tactic_cfg = best_opportunity['tactic_cfg']
    
    full_indicators = decision_data.get('full_indicators', {})
    symbol = full_indicators.get('symbol', 'N/A')
    interval = full_indicators.get('interval', 'N/A')
    score = decision_data.get('final_score', 0.0)
    entry_p = full_indicators.get('price', 0.0)

    log_message(f"🏆 Cơ hội tốt nhất được chọn: {symbol} | Interval: {interval} | Tactic: {tactic_name} | Điểm: {score:.2f}")

    risk_tier = CAPITAL_MANAGEMENT_CONFIG["TACTIC_TO_TIER_MAP"].get(tactic_name, "HIGH_RISK")
    capital_pct = determine_dynamic_capital_pct(full_indicators.get('atr_percent', 3.0))
    invested_amount = equity * capital_pct * {'LOW_RISK': 1.2, 'MEDIUM_RISK': 1.0, 'HIGH_RISK': 0.8}.get(risk_tier, 1.0)

    current_exposure_usd = sum(t.get('total_invested_usd', 0.0) for t in state.get('active_trades', [])) # Sử dụng .get()
    potential_exposure_pct = (current_exposure_usd + invested_amount) / equity
    if potential_exposure_pct > CAPITAL_MANAGEMENT_CONFIG["MAX_TOTAL_EXPOSURE_PCT"]:
        log_message(f"⚠️ Mở lệnh mới cho {symbol} sẽ vượt ngưỡng exposure tối đa ({potential_exposure_pct:.2%} > {CAPITAL_MANAGEMENT_CONFIG['MAX_TOTAL_EXPOSURE_PCT']:.2%}). Bỏ qua.")
        return

    if invested_amount > state['cash']:
        log_message(f"⚠️ Không đủ tiền mặt để mở lệnh {symbol}. Cần ${invested_amount:,.2f}, còn ${state['cash']:,.2f}")
        return

    risk_dist = (full_indicators.get('atr', 0) * tactic_cfg.get("ATR_SL_MULTIPLIER", 2.0)) if tactic_cfg.get("USE_ATR_SL") else entry_p * 0.05
    sl_p = entry_p - risk_dist
    tp_p = entry_p + (risk_dist * tactic_cfg.get("RR", 2.0))
    
    if tp_p <= entry_p or sl_p <= 0:
        log_message(f"⚠️ SL hoặc TP không hợp lệ cho {symbol}. SL: {sl_p:.4f}, TP: {tp_p:.4f}. Bỏ qua.")
        return

    new_trade = {
        "trade_id": str(uuid.uuid4()),
        "symbol": symbol,
        "interval": interval,
        "status": "ACTIVE",
        "opened_by_tactic": tactic_name, # Đảm bảo tactic được lưu
        "trade_type": "LONG",
        "entry_price": entry_p,
        "tp": round(tp_p, 8),
        "sl": round(sl_p, 8),
        "initial_sl": round(sl_p, 8),
        "initial_risk_dist": risk_dist,
        "total_invested_usd": invested_amount,
        "initial_entry": {"price": entry_p, "invested_usd": invested_amount},
        "entry_time": datetime.now(VIETNAM_TZ).isoformat(),
        "entry_score": score,
        "dca_entries": [],
        "tp1_taken": False,
        "trailing_sl": round(sl_p, 8) # Khởi tạo trailing_sl bằng initial_sl
    }
    
    state["cash"] -= invested_amount
    state["active_trades"].append(new_trade)
    log_message(f"🔥 Lệnh Mới (Tốt nhất): {symbol} | Vốn: ${invested_amount:,.2f} | SL: {sl_p:.4f} | TP: {tp_p:.4f}")
    state.setdefault('temp_newly_opened_trades', []).append(f"🔥 {symbol} ({tactic_name}): Vốn ${invested_amount:,.2f}")

# ==============================================================================
# ==================== BÁO CÁO & VÒNG LẶP CHÍNH ===============================
# ==============================================================================

def build_report_header(state: Dict) -> List[str]:
    """Tạo các dòng header cho báo cáo (vốn, PnL tổng)."""
    header_lines = []
    total_equity = calculate_total_equity(state)
    cash = state.get('cash', INITIAL_CAPITAL)
    
    header_lines.append(f"💰 Vốn ban đầu: **${INITIAL_CAPITAL:,.2f}**")
    header_lines.append(f"💵 Tiền mặt hiện có: **${cash:,.2f}**")
    header_lines.append(f"📊 Tổng tài sản (Equity): **${total_equity:,.2f}**")
    
    pnl_since_start = total_equity - INITIAL_CAPITAL
    pnl_percent_since_start = (pnl_since_start / INITIAL_CAPITAL) * 100 if INITIAL_CAPITAL > 0 else 0
    pnl_icon = "🟢" if pnl_since_start >= 0 else "🔴"
    header_lines.append(f"📈 PnL Tổng cộng: {pnl_icon} **${pnl_since_start:,.2f} ({pnl_percent_since_start:+.2f}%)**")
    
    return header_lines

def build_trade_details_for_report(trade: Dict, current_price: float) -> str:
    """Tạo chuỗi chi tiết cho một lệnh đang mở để báo cáo, gói gọn vào một dòng."""
    pnl_usd, pnl_pct = get_current_pnl(trade)
    icon = "🟢" if pnl_usd >= 0 else "🔴"
    holding_h = (datetime.now(VIETNAM_TZ) - datetime.fromisoformat(trade['entry_time'])).total_seconds() / 3600
    dca_info = f" (DCA: {len(trade.get('dca_entries',[]))})" if trade.get('dca_entries') else ""
    tsl_info = f" TSL:{trade['trailing_sl']:.4f}" if TACTICS_LAB.get(trade.get('opened_by_tactic'), {}).get("USE_TRAILING_SL") and 'trailing_sl' in trade else ""

    # Gói gọn tất cả thông tin quan trọng vào một dòng
    details_line = (
        f"  {icon} **{trade['symbol']}** ({trade.get('opened_by_tactic', 'N/A')} | Score:{trade.get('entry_score', 0.0):.1f}) "
        f"PnL: ${pnl_usd:,.2f} ({pnl_pct:+.2f}%) | Giữ:{holding_h:.1f}h{dca_info}\n"
        f"    Entry:{trade['entry_price']:.4f} Cur:{current_price:.4f} SL:{trade['sl']:.4f} TP:{trade['tp']:.4f} {tsl_info} "
        f"Vốn:${trade.get('total_invested_usd', 0.0):,.2f}"
    )
    return details_line


def build_daily_summary_text(state: Dict) -> str:
    """Tạo nội dung báo cáo tổng kết hàng ngày."""
    now_vn_str = datetime.now(VIETNAM_TZ).strftime('%H:%M %d-%m-%Y')
    lines = [f"📊 **BÁO CÁO TỔNG KẾT HÀNG NGÀY** - `{now_vn_str}` 📊", ""]
    lines.extend(build_report_header(state))
    lines.append("\n--- **Chi tiết trong phiên** ---")
    
    if state.get('temp_newly_opened_trades'):
        lines.append("✨ **Lệnh mới mở:**")
        lines.extend([f"    - {msg}" for msg in state['temp_newly_opened_trades']])
    else:
        lines.append("✨ Lệnh mới mở: (Không có)")

    if state.get('temp_newly_closed_trades'):
        lines.append("\n⛔ **Lệnh đã đóng:**")
        lines.extend([f"    - {msg}" for msg in state['temp_newly_closed_trades']])
    else:
        lines.append("\n⛔ Lệnh đã đóng: (Không có)")

    lines.append("\n--- **Vị thế đang mở** ---")
    active_trades = state.get('active_trades', [])
    lines.append(f"💼 Tổng vị thế đang mở: **{len(active_trades)}**")
    if not active_trades: lines.append("    (Không có vị thế nào)")
    else:
        for trade in active_trades:
            current_data = all_indicators.get(trade["symbol"], {}).get(trade["interval"], {})
            current_price = current_data.get('price', 0)
            if current_price > 0:
                lines.append(build_trade_details_for_report(trade, current_price))
            else:
                lines.append(f"⚠️ {trade['symbol']} - Không có dữ liệu giá hiện tại để báo cáo chi tiết.")

    # Báo cáo tổng kết lịch sử giao dịch
    lines.append("\n--- **Tổng kết lịch sử giao dịch** ---")
    trade_history = state.get('trade_history', [])
    if trade_history:
        df_history = pd.DataFrame(trade_history)
        df_history['pnl_usd'] = df_history['pnl_usd'].astype(float)
        
        total_trades = len(df_history)
        # Lệnh hòa vốn thường được tính vào lệnh thua để khuyến khích lợi nhuận dương
        winning_trades = df_history[df_history['pnl_usd'] > 0]
        losing_trades = df_history[df_history['pnl_usd'] <= 0] 

        win_rate = (len(winning_trades) / total_trades * 100) if total_trades > 0 else 0
        
        total_pnl_history = df_history['pnl_usd'].sum()
        avg_win_pnl = winning_trades['pnl_usd'].mean() if len(winning_trades) > 0 else 0
        avg_loss_pnl = losing_trades['pnl_usd'].mean() if len(losing_trades) > 0 else 0

        lines.append(f"📊 Tổng lệnh đã đóng: {total_trades}")
        lines.append(f"✅ Lệnh thắng: {len(winning_trades)} | ❌ Lệnh thua: {len(losing_trades)}")
        lines.append(f"🏆 Win Rate: **{win_rate:.2f}%**")
        lines.append(f"💰 Tổng PnL lịch sử: **${total_pnl_history:,.2f}**")
        lines.append(f"Avg PnL thắng: ${avg_win_pnl:,.2f} | Avg PnL thua: ${avg_loss_pnl:,.2f}")
        
        # 5 lệnh lãi/lỗ gần nhất
        lines.append("\n--- Top 5 lệnh lãi gần nhất ---")
        top_5_wins = winning_trades.nlargest(5, 'pnl_usd')
        if not top_5_wins.empty:
            for idx, trade_data in top_5_wins.iterrows():
                lines.append(f"  - {trade_data['symbol']} ({trade_data.get('opened_by_tactic', 'N/A')}) | PnL: ${trade_data['pnl_usd']:,.2f} ({trade_data['pnl_percent']:+.2f}%)")
        else:
            lines.append("  (Chưa có lệnh lãi)")

        lines.append("\n--- Top 5 lệnh lỗ gần nhất ---")
        top_5_losses = losing_trades.nsmallest(5, 'pnl_usd')
        if not top_5_losses.empty:
            for idx, trade_data in top_5_losses.iterrows():
                lines.append(f"  - {trade_data['symbol']} ({trade_data.get('opened_by_tactic', 'N/A')}) | PnL: ${trade_data['pnl_usd']:,.2f} ({trade_data['pnl_percent']:+.2f}%)")
        else:
            lines.append("  (Chưa có lệnh lỗ)")
            
    else:
        lines.append("    (Chưa có lịch sử giao dịch)")

    lines.append("\n====================================")
    return "\n".join(lines)

def should_send_dynamic_alert(state: Dict) -> bool:
    """Kiểm tra điều kiện để gửi cảnh báo động Discord."""
    if not DYNAMIC_ALERT_CONFIG["ENABLED"]: return False

    now_vn = datetime.now(VIETNAM_TZ)
    last_alert_time = state.get('last_dynamic_alert', {}).get('timestamp')
    last_alert_pnl = state.get('last_dynamic_alert', {}).get('total_pnl_percent', 0.0)

    current_total_equity = calculate_total_equity(state)
    current_total_pnl_percent = ((current_total_equity - INITIAL_CAPITAL) / INITIAL_CAPITAL) * 100 if INITIAL_CAPITAL > 0 else 0

    if last_alert_time:
        last_alert_dt = datetime.fromisoformat(last_alert_time).astimezone(VIETNAM_TZ)
        time_since_last_alert = (now_vn - last_alert_dt).total_seconds() / 3600
        
        if time_since_last_alert >= DYNAMIC_ALERT_CONFIG["FORCE_UPDATE_HOURS"]:
            return True
        
        if time_since_last_alert < DYNAMIC_ALERT_CONFIG["COOLDOWN_HOURS"]:
            return False

    pnl_change = abs(current_total_pnl_percent - last_alert_pnl)
    if pnl_change >= DYNAMIC_ALERT_CONFIG["PNL_CHANGE_THRESHOLD_PCT"]:
        return True
    
    if not last_alert_time and state.get('active_trades'): # Gửi alert đầu tiên nếu có lệnh
        return True

    return False

def build_dynamic_alert_text(state: Dict) -> str:
    """Tạo nội dung cảnh báo động."""
    now_vn_str = datetime.now(VIETNAM_TZ).strftime('%H:%M %d-%m-%Y')
    lines = [f"💡 **CẬP NHẬT ĐỘNG** - `{now_vn_str}` 💡", ""]
    lines.extend(build_report_header(state))
    lines.append("\n--- **Vị thế đang mở** ---")
    
    active_trades = state.get('active_trades', [])
    lines.append(f"💼 Tổng vị thế đang mở: **{len(active_trades)}**")
    if not active_trades: lines.append("    (Không có vị thế nào)")
    else:
        for trade in active_trades:
            current_data = all_indicators.get(trade["symbol"], {}).get(trade["interval"], {})
            current_price = current_data.get('price', 0)
            if current_price > 0:
                lines.append(build_trade_details_for_report(trade, current_price))
            else:
                lines.append(f"⚠️ {trade['symbol']} - Không có dữ liệu giá hiện tại để báo cáo chi tiết.")
    lines.append("\n====================================")
    return "\n".join(lines)

def run_session():
    """Chạy một phiên giao dịch chính của bot."""
    session_id = datetime.now(VIETNAM_TZ).strftime('%Y%m%d_%H%M%S')
    log_message(f"====== 🚀 BẮT ĐẦU PHIÊN (v2.3 - Hoàn thiện Báo cáo Tinh gọn) (ID: {session_id}) 🚀 ======")
    try:
        # Tải trạng thái hoặc khởi tạo mới nếu không tồn tại
        state = load_json_file(STATE_FILE, {
            "cash": INITIAL_CAPITAL,
            "active_trades": [],
            "trade_history": [],
            "last_dynamic_alert": {"timestamp": None, "total_pnl_percent": 0.0},
            "last_daily_report_day": None
        })

        # Xóa các thông báo tạm thời từ phiên trước để tránh lặp lại
        state.pop('temp_newly_opened_trades', None)
        state.pop('temp_newly_closed_trades', None)

        # 1. Lấy dữ liệu và tính toán indicators cho tất cả các symbol và khung thời gian
        log_message("⏳ Đang tải và tính toán indicators...")
        all_indicators.clear()
        symbols_to_fetch = list(set(SYMBOLS_TO_SCAN + ["BTCUSDT"]))
        for symbol in symbols_to_fetch:
            all_indicators[symbol] = {}
            for interval in ALL_TIME_FRAMES:
                df = safe_get_price_data(symbol, interval, GENERAL_CONFIG["DATA_FETCH_LIMIT"])
                if df is not None:
                    all_indicators[symbol][interval] = calculate_indicators(df, symbol, interval)
        log_message("✅ Đã tải xong indicators.")

        # 2. Xử lý đóng lệnh (TP/SL/Trailing)
        closed_tp_sl = handle_trade_closure(state)
        
        # 3. Xử lý đóng lệnh "ì" (Stale trades)
        closed_stale = handle_stale_trades(state)
        
        # Gộp tất cả các lệnh đã đóng trong phiên và xuất ra CSV
        all_closed_trades_in_session = closed_tp_sl + closed_stale
        if all_closed_trades_in_session:
            export_trade_history_to_csv(all_closed_trades_in_session)

        # Tính toán tổng tài sản hiện tại
        total_equity = calculate_total_equity(state)

        # 4. Xử lý DCA cho các lệnh đang mở (nếu có cơ hội)
        handle_dca_opportunities(state, total_equity)

        # 5. Tìm và mở lệnh mới TỐT NHẤT (nếu đủ điều kiện và chưa đạt giới hạn)
        # Lấy market context từ BTCUSDT 1d và Fear & Greed Index
        btc_d1_adx = all_indicators.get("BTCUSDT", {}).get("1d", {}).get("adx", 20.0)
        fg_path = os.path.join(PROJECT_ROOT, "ricenews", "lognew", "market_context.json")
        fear_greed_context = load_json_file(fg_path, {}).get("fear_greed", 50)
        market_context = {"fear_greed": fear_greed_context, "btc_d1_adx": btc_d1_adx}
        
        find_and_open_new_trades(state, total_equity, market_context)

        # 6. Xử lý báo cáo và alerts Discord
        now_vn = datetime.now(VIETNAM_TZ)

        # Gửi báo cáo tổng kết hàng ngày vào các khung giờ cấu hình
        for daily_time in GENERAL_CONFIG["DAILY_SUMMARY_TIMES"]:
            daily_hour, daily_minute = map(int, daily_time.split(':'))
            
            last_daily_report_day_dt = None
            if state.get('last_daily_report_day'):
                last_daily_report_day_dt = datetime.fromisoformat(state['last_daily_report_day']).date()

            if now_vn.hour == daily_hour and now_vn.minute >= daily_minute and \
               (not last_daily_report_day_dt or last_daily_report_day_dt != now_vn.date()):
                summary_text = build_daily_summary_text(state)
                send_discord_message_chunks(summary_text) # Luôn dùng chunk
                state['last_daily_report_day'] = now_vn.date().isoformat()
                log_message(f"🔔 Đã gửi báo cáo tổng kết hàng ngày.")
                break # Chỉ gửi một báo cáo hàng ngày mỗi khi điều kiện được đáp ứng

        # Gửi cảnh báo động nếu có sự thay đổi PnL đáng kể hoặc đã đến lúc cập nhật bắt buộc
        if should_send_dynamic_alert(state):
            alert_text = build_dynamic_alert_text(state)
            send_discord_message_chunks(alert_text) # Luôn dùng chunk
            # Cập nhật trạng thái alert cuối cùng
            current_total_equity = calculate_total_equity(state)
            current_total_pnl_percent = ((current_total_equity - INITIAL_CAPITAL) / INITIAL_CAPITAL) * 100 if INITIAL_CAPITAL > 0 else 0
            state['last_dynamic_alert'] = {
                "timestamp": now_vn.isoformat(),
                "total_pnl_percent": current_total_pnl_percent
            }
            log_message(f"🔔 Đã gửi alert động.")

        # Lưu trạng thái hiện tại của bot
        save_json_file(STATE_FILE, state)

    except Exception:
        # Xử lý các lỗi nghiêm trọng và gửi thông báo Discord
        error_details = traceback.format_exc()
        log_message(f"!!!!!! ❌ LỖI NGHIÊM TRỌNG TRONG PHIÊN LÀM VIỆC ❌ !!!!!!\n{error_details}")
        send_discord_message_chunks(f"🔥🔥🔥 BOT GẶP LỖI NGHIÊM TRỌNG 🔥🔥🔥\n```python\n{error_details}\n```")

    log_message(f"====== ✅ KẾT THÚC PHIÊN (ID: {session_id}) ✅ ======\n")


if __name__ == "__main__":
    run_session()
