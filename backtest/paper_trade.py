# /root/ricealert/backtest/paper_trade.py
# -*- coding: utf-8 -*-
"""
paper_trade.py - Quản lý Danh mục & Rủi ro Thông minh
Version: GrandFinal
Date: 2025-07-11

Description:
Phiên bản hoàn thiện cuối cùng, tập trung vào trải nghiệm người dùng và
các quy tắc quản lý rủi ro nâng cao.
- Đại tu hoàn toàn Daily Summary: định dạng text, icon thông minh, gộp tin nhắn.
- Quy tắc giữ lệnh (Stale Trades) được tùy chỉnh theo từng khung thời gian.
- Hoàn thiện Smart Alert với output dạng text.
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
    sys.exit("Lỗi: Không tìm thấy module 'indicator' hoặc 'trade_advisor'. Đảm bảo các file này có sẵn trong thư mục dự án.")

# ==============================================================================
# ================= ⚙️ TRUNG TÂM CẤU HÌNH (GrandFinal) ⚙️ =====================
# ==============================================================================

INITIAL_CAPITAL = 10000.0

GENERAL_CONFIG = {
    "DATA_FETCH_LIMIT": 300, # Tăng từ 200 lên 300
    "DAILY_SUMMARY_HOURS": [8, 20],
}

SMART_UPDATE_CONFIG = {
    "ENABLED": True,
    "COOLDOWN_MINUTES": 240,  # 4 giờ
    "FORCE_UPDATE_MINUTES": 480, # 8 giờ
    "PNL_CHANGE_THRESHOLD_PCT": 2.0 # Ngưỡng thay đổi PnL để trigger, theo yêu cầu
}

# vGrandFinal: Quy tắc Stale được tùy chỉnh theo khung thời gian
RISK_RULES_CONFIG = {
    "MAX_ACTIVE_TRADES": 7,
    "STALE_TRADE_RULES": {
        "1h": {"HOURS": 72, "PNL_PCT_THRESHOLD": 1.5}, 
        "4h": {"HOURS": 120, "PNL_PCT_THRESHOLD": 2.0}, 
        "1d": {"HOURS": 144, "PNL_PCT_THRESHOLD": 2.5}  
    }
}

CAPITAL_MANAGEMENT_CONFIG = {
    "CAPITAL_TIERS": {"LOW_RISK": 0.08, "MEDIUM_RISK": 0.05, "HIGH_RISK": 0.03},
    "TACTIC_TO_TIER_MAP": {
        "AI_Aggressor": "LOW_RISK", "Breakout_Hunter": "LOW_RISK",
        "Balanced_Trader": "MEDIUM_RISK", "Market_Mirror": "MEDIUM_RISK",
        "Dip_Hunter": "HIGH_RISK", "Range_Trader": "HIGH_RISK", "Cautious_Observer": "HIGH_RISK",
    },
    "MAX_TOTAL_EXPOSURE_PCT": 0.60
}

ALERT_CONFIG = {
    "DISCORD_WEBHOOK_URL": os.getenv("DISCORD_PAPER_WEBHOOK"),
    "DISCORD_CHUNK_DELAY_SECONDS": 3, # Thêm delay cho chunks
    "ALERT_COOLDOWNS_MINUTES": {
        "NEW_TRADE": 0, "TRADE_CLOSED": 0, "TACTIC_CHANGE": 180,
        "RISK_WARNING": 60, "DAILY_SUMMARY": 720
    }
}

# Đảm bảo mọi Tactic đều có `ENTRY_SCORE` để hành vi được tường minh.
TACTICS_LAB = {
    "Balanced_Trader": {"NOTES": "Cân bằng...", "WEIGHTS": {'tech': 0.4, 'context': 0.2, 'ai': 0.4}, "ENTRY_SCORE": 5.8, "RR": 2.2, "USE_ATR_SL": True, "ATR_SL_MULTIPLIER": 2.5},
    "AI_Aggressor": {"NOTES": "Tin vào AI...", "WEIGHTS": {'tech': 0.1, 'context': 0.1, 'ai': 0.8}, "ENTRY_SCORE": 6.2, "RR": 1.8, "USE_ATR_SL": True, "ATR_SL_MULTIPLIER": 3.0},
    "Dip_Hunter": {"NOTES": "Bắt đáy...", "WEIGHTS": {'tech': 0.5, 'context': 0.3, 'ai': 0.2}, "ENTRY_SCORE": 6.5, "RR": 3.0, "USE_ATR_SL": True, "ATR_SL_MULTIPLIER": 2.0},
    "Cautious_Observer": {"NOTES": "Bảo toàn vốn...", "WEIGHTS": {'tech': 0.5, 'context': 0.5, 'ai': 0.0}, "ENTRY_SCORE": 9.9},
    "Market_Mirror": {"NOTES": "Làm baseline...", "WEIGHTS": {'tech': 0.4, 'context': 0.2, 'ai': 0.4}, "ENTRY_SCORE": 5.5, "RR": 1.8, "USE_ATR_SL": True, "ATR_SL_MULTIPLIER": 2.5},
    "Range_Trader": {"NOTES": "Giao dịch kênh giá...", "WEIGHTS": {'tech': 0.8, 'context': 0.2, 'ai': 0.0}, "ENABLE_RANGE_TRADE": True, "RANGE_ENTRY_PROXIMITY": 0.015, "RR": 1.8, "SL_BELOW_SUPPORT_PCT": 0.02, "ENTRY_SCORE": 9.9}, # Score cao để không vào lệnh TREND_FOLLOW
    "Breakout_Hunter": {"NOTES": "Săn phá vỡ...", "WEIGHTS": {'tech': 0.7, 'context': 0.1, 'ai': 0.2}, "ENABLE_BREAKOUT_TRADE": True, "ENTRY_SCORE": 6.0, "RR": 2.8, "USE_ATR_SL": True, "ATR_SL_MULTIPLIER": 2.0}
}

SYMBOLS_TO_SCAN = ["ETHUSDT", "AVAXUSDT", "INJUSDT", "LINKUSDT", "SUIUSDT", "FETUSDT", "TAOUSDT"]
INTERVALS_TO_SCAN = ["1h", "4h", "1d"]
ALL_TIME_FRAMES = ["1h", "4h", "1d"]
VIETNAM_TZ = pytz.timezone('Asia/Ho_Chi_Minh')

LOG_FILE = os.path.join(PAPER_DATA_DIR, "paper_trade_log.txt")
STATE_FILE = os.path.join(PAPER_DATA_DIR, "paper_trade_state.json")
TIMESTAMP_FILE = os.path.join(PAPER_DATA_DIR, "paper_trade_timestamps.json")
TRADE_HISTORY_CSV_FILE = os.path.join(PAPER_DATA_DIR, "trade_history.csv")

all_indicators: Dict[str, Any] = {}

# ==============================================================================
# ======================= TIỆN ÍCH & CẢNH BÁO (GrandFinal) =====================
# ==============================================================================

def log_message(message: str):
    timestamp = datetime.now(VIETNAM_TZ).strftime('%Y-%m-%d %H:%M:%S')
    log_entry = f"[{timestamp}] {message}"
    print(log_entry)
    with open(LOG_FILE, "a", encoding="utf-8") as f: f.write(log_entry + "\n")

def load_json_file(path: str, default: Any = {}) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f: return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError): return default

def save_json_file(path: str, data: Any):
    with open(path, "w", encoding="utf-8") as f: json.dump(data, f, indent=4, ensure_ascii=False)

def send_discord_message_chunks(full_content: str):
    """Gửi tin nhắn lên Discord, tự động chia nhỏ nếu quá dài."""
    webhook_url = ALERT_CONFIG.get("DISCORD_WEBHOOK_URL")
    if not webhook_url: return
    
    # Discord message limit is 2000 characters
    max_len = 1900 
    chunks = [full_content[i:i+max_len] for i in range(0, len(full_content), max_len)]
    
    for i, chunk in enumerate(chunks):
        payload = {"content": chunk}
        try:
            requests.post(webhook_url, json=payload, timeout=10).raise_for_status()
            if i < len(chunks) - 1: # Nếu không phải chunk cuối, đợi một chút
                time.sleep(ALERT_CONFIG["DISCORD_CHUNK_DELAY_SECONDS"])
        except requests.exceptions.RequestException as e:
            log_message(f"❌ Lỗi khi gửi chunk Discord: {e}")

def send_discord_embed(embed: Dict):
    webhook_url = ALERT_CONFIG.get("DISCORD_WEBHOOK_URL")
    if not webhook_url: return
    try:
        requests.post(webhook_url, json={"embeds": [embed]}, timeout=10).raise_for_status()
        time.sleep(0.5)
    except requests.exceptions.RequestException as e:
        log_message(f"❌ Lỗi khi gửi embed Discord: {e}")

def alert_manager(alert_type: str, content: str = None, embed: Dict = None):
    # Sử dụng send_discord_message_chunks hoặc send_discord_embed tùy loại alert
    cooldowns = load_json_file(TIMESTAMP_FILE, {})
    cooldown_minutes = ALERT_CONFIG.get("ALERT_COOLDOWNS_MINUTES", {}).get(alert_type, 60)
    
    # Bỏ qua cooldown nếu cooldown_minutes là 0
    if cooldown_minutes != 0:
        now_aware = datetime.now(VIETNAM_TZ)
        last_alert_time_str = cooldowns.get(alert_type)
        if last_alert_time_str:
            last_alert_time = datetime.fromisoformat(last_alert_time_str).astimezone(VIETNAM_TZ)
            if now_aware - last_alert_time < timedelta(minutes=cooldown_minutes):
                return # Vẫn trong thời gian cooldown, không gửi alert

    # Gửi alert
    if embed:
        send_discord_embed(embed)
    elif content:
        # Nếu content quá dài, tự động chia nhỏ và gửi từng phần
        send_discord_message_chunks(content)

    # Cập nhật timestamp chỉ khi alert được gửi thành công (hoặc không có cooldown)
    if cooldown_minutes != 0:
        cooldowns[alert_type] = datetime.now(VIETNAM_TZ).isoformat()
        save_json_file(TIMESTAMP_FILE, cooldowns)


def get_current_pnl(trade: Dict) -> Tuple[float, float]:
    current_data = all_indicators.get(trade["symbol"], {}).get(trade["interval"])
    if not current_data or current_data.get('price', 0) == 0 or trade.get('entry_price', 0) == 0:
        return 0.0, 0.0
    current_price = current_data['price']
    invested_amount = trade.get('invested_usd', 0.0)
    pnl_percent = (current_price - trade['entry_price']) / trade['entry_price']
    return invested_amount * pnl_percent, pnl_percent * 100

def export_trade_history_to_csv(closed_trades: List[Dict]):
    if not closed_trades: return
    try:
        df_history = pd.DataFrame(closed_trades)
        df_history['entry_time'] = pd.to_datetime(df_history['entry_time']).dt.tz_convert(VIETNAM_TZ)
        df_history['exit_time'] = pd.to_datetime(df_history['exit_time']).dt.tz_convert(VIETNAM_TZ)
        df_history['holding_duration_hours'] = round((df_history['exit_time'] - df_history['entry_time']).dt.total_seconds() / 3600, 2)
        columns_order = ["trade_id", "symbol", "interval", "status", "opened_by_tactic", "trade_type", "entry_price", "exit_price", "tp", "sl", "invested_usd", "pnl_usd", "pnl_percent", "entry_time", "exit_time", "holding_duration_hours", "entry_score"]
        df_history = df_history[[col for col in columns_order if col in df_history.columns]]
        file_exists = os.path.exists(TRADE_HISTORY_CSV_FILE)
        df_history.to_csv(TRADE_HISTORY_CSV_FILE, mode='a' if file_exists else 'w', header=not file_exists, index=False, encoding="utf-8")
        log_message(f"✅ Đã xuất {len(df_history)} lệnh đã đóng vào {TRADE_HISTORY_CSV_FILE}")
    except Exception as e:
        log_message(f"❌ Lỗi khi xuất lịch sử giao dịch ra CSV: {e}")

# ==============================================================================
# ================== XỬ LÝ DANH MỤC & RỦI RO (GrandFinal) ==================
# ==============================================================================

def calculate_total_equity(state: Dict) -> float:
    current_cash = state.get('cash', INITIAL_CAPITAL)
    total_open_trade_value = 0.0
    for trade in state.get('active_trades', []):
        pnl_usd, _ = get_current_pnl(trade)
        total_open_trade_value += (trade.get('invested_usd', 0) + pnl_usd)
    return current_cash + total_open_trade_value

def handle_trade_closure(portfolio_state: Dict) -> List[Dict]:
    closed_trades = []
    for trade in portfolio_state["active_trades"][:]:
        symbol, interval = trade['symbol'], trade['interval']
        current_data = all_indicators.get(symbol, {}).get(interval)
        if not current_data: continue
        high_price, low_price = current_data.get('high', 0), current_data.get('low', 0)
        status, exit_price = (("SL", trade['sl']) if low_price > 0 and low_price <= trade['sl'] else
                              ("TP", trade['tp']) if high_price > 0 and high_price >= trade['tp'] else (None, None))
        if status:
            pnl_percent = (exit_price - trade['entry_price']) / trade['entry_price']
            pnl_usd = trade['invested_usd'] * pnl_percent
            portfolio_state['cash'] += (trade['invested_usd'] + pnl_usd)
            trade.update({'status': f'Closed ({status})', 'exit_price': exit_price, 'exit_time': datetime.now(VIETNAM_TZ).isoformat(), 'pnl_usd': pnl_usd, 'pnl_percent': pnl_percent * 100})
            portfolio_state['active_trades'].remove(trade)
            portfolio_state['trade_history'].append(trade)
            closed_trades.append(trade)
            log_message(f"{'✅' if status == 'TP' else '❌'} Lệnh Đóng ({status}): {symbol} | PnL: ${pnl_usd:,.2f} ({pnl_percent*100:+.2f}%)")
            embed = {"title": f"{'✅ Chốt lời' if status == 'TP' else '❌ Cắt lỗ'}: {symbol}", "color": 3066993 if status == 'TP' else 15158332, "fields": [{"name": "Lợi nhuận (USD)", "value": f"`${pnl_usd:,.2f}`", "inline": True}, {"name": "Lợi nhuận (%)", "value": f"`{pnl_percent*100:+.2f}%`", "inline": True}, {"name": "Lối đánh", "value": trade['opened_by_tactic'], "inline": False}]}
            send_discord_embed(embed=embed) # Sử dụng send_discord_embed
    return closed_trades

def handle_stale_trades_by_interval(portfolio_state: Dict) -> List[Dict]:
    """vGrandFinal: Xử lý lệnh kẹt dựa trên quy tắc của từng khung thời gian."""
    closed_trades = []
    now_aware = datetime.now(VIETNAM_TZ)
    for trade in portfolio_state.get("active_trades", [])[:]:
        interval = trade.get("interval")
        rules = RISK_RULES_CONFIG["STALE_TRADE_RULES"].get(interval)
        if not rules: 
            log_message(f"Cảnh báo: Không tìm thấy quy tắc stale cho khung thời gian {interval}. Sử dụng mặc định.")
            # Fallback to general stale rules if no specific rule for interval
            rules = {"HOURS": 72, "PNL_PCT_THRESHOLD": 1.5} # Default values

        entry_time = datetime.fromisoformat(trade['entry_time'])
        holding_hours = (now_aware - entry_time).total_seconds() / 3600
        _, pnl_percent = get_current_pnl(trade)
        
        is_over_time = holding_hours > rules["HOURS"]
        is_stuck = abs(pnl_percent) < rules["PNL_PCT_THRESHOLD"]
        
        if is_over_time and is_stuck:
            log_message(f"⌛ Lệnh {trade['symbol']} ({interval}) bị kẹt quá {rules['HOURS']}h. Đang đóng để giải phóng vốn...")
            current_price = all_indicators.get(trade['symbol'],{}).get(trade['interval'],{}).get('price', trade['entry_price'])
            pnl_percent_at_close = (current_price - trade['entry_price']) / trade['entry_price']
            pnl_usd_at_close = trade['invested_usd'] * pnl_percent_at_close
            portfolio_state['cash'] += (trade['invested_usd'] + pnl_usd_at_close)
            trade.update({'status': 'Closed (Stale)', 'exit_price': current_price, 'exit_time': now_aware.isoformat(), 'pnl_usd': pnl_usd_at_close, 'pnl_percent': pnl_percent_at_close * 100})
            portfolio_state['active_trades'].remove(trade)
            portfolio_state['trade_history'].append(trade)
            closed_trades.append(trade)
            embed = {"title": f"⌛ Đóng lệnh bị kẹt: {trade['symbol']}", "color": 15105570, "description": f"Lệnh được đóng tự động sau **{holding_hours:.1f} giờ** với PnL không đáng kể.", "fields": [{"name": "Lợi nhuận (USD)", "value": f"`${pnl_usd_at_close:,.2f}`", "inline": True}]}
            send_discord_embed(embed=embed) # Sử dụng send_discord_embed
    return closed_trades

def find_and_open_new_trades(portfolio_state: Dict, selected_tactic_name: str, total_equity: float):
    if len(portfolio_state['active_trades']) >= RISK_RULES_CONFIG["MAX_ACTIVE_TRADES"]:
        log_message(f"⚠️ Đã đạt giới hạn {RISK_RULES_CONFIG['MAX_ACTIVE_TRADES']} lệnh mở. Tạm dừng tìm lệnh mới.")
        return

    invested_in_active_trades = sum(t.get('invested_usd', 0) for t in portfolio_state['active_trades'])
    current_exposure_pct = invested_in_active_trades / total_equity if total_equity > 0 else 0
    max_exposure_pct = CAPITAL_MANAGEMENT_CONFIG["MAX_TOTAL_EXPOSURE_PCT"]
    
    if current_exposure_pct >= max_exposure_pct:
        log_message(f"⚠️ Rủi ro tổng thể {current_exposure_pct:.1%} đã đạt ngưỡng {max_exposure_pct:.1%}. Ngừng mở lệnh mới.")
        alert_manager("RISK_WARNING", content=f"⚠️ Rủi ro danh mục đã vượt ngưỡng an toàn ({current_exposure_pct:.1%})!")
        return

    tactic_config = TACTICS_LAB[selected_tactic_name]
    
    for symbol in SYMBOLS_TO_SCAN:
        # CHÚ THÍCH CHIẾN LƯỢC QUẢN LÝ RỦI RO:
        # Điều kiện này ngăn mở lệnh mới cho một symbol đã có lệnh đang hoạt động,
        # bất kể khung thời gian. Đây là một quyết định có chủ đích để TRÁNH TẬP
        # TRUNG RỦI RO (concentration risk) vào một tài sản duy nhất.
        if any(t['symbol'] == symbol for t in portfolio_state['active_trades']):
            continue
        
        for interval in INTERVALS_TO_SCAN:
            indicators = all_indicators.get(symbol, {}).get(interval)
            if not indicators or indicators.get('price', 0) == 0: continue

            advisor_decision = get_advisor_decision(symbol, interval, indicators, ADVISOR_BASE_CONFIG, weights_override=tactic_config.get("WEIGHTS"))
            final_score = advisor_decision.get("final_score", 0.0)
            entry_price = indicators['price']
            trade_type = None
            
            if tactic_config.get("ENABLE_BREAKOUT_TRADE") and indicators.get("breakout_signal") == 'bullish' and final_score >= tactic_config.get("ENTRY_SCORE", 9.9):
                trade_type = "BREAKOUT_BUY"
            elif tactic_config.get("ENABLE_RANGE_TRADE"):
                support = indicators.get("support_level", 0)
                proximity = tactic_config.get("RANGE_ENTRY_PROXIMITY", 0.015)
                if support > 0 and abs(entry_price - support) / support < proximity:
                    trade_type = "RANGE_BUY"
            elif final_score >= tactic_config.get("ENTRY_SCORE", 9.9):
                trade_type = "TREND_FOLLOW"

            if trade_type:
                risk_tier = CAPITAL_MANAGEMENT_CONFIG["TACTIC_TO_TIER_MAP"].get(selected_tactic_name, "HIGH_RISK")
                capital_pct = CAPITAL_MANAGEMENT_CONFIG["CAPITAL_TIERS"][risk_tier]
                invested_usd = total_equity * capital_pct

                if invested_usd > portfolio_state['cash'] or invested_usd < 10: continue

                sl_price, tp_price = 0, 0
                if trade_type == "RANGE_BUY":
                    sl_price = indicators.get('support_level', 0) * (1 - tactic_config.get("SL_BELOW_SUPPORT_PCT", 0.02))
                    tp_price = indicators.get('resistance_level', 0)
                else: # Áp dụng cho TREND_FOLLOW và BREAKOUT_BUY
                    # Các Tactic này được thiết kế để sử dụng ATR làm cơ sở tính SL.
                    atr = indicators.get('atr', 0)
                    risk_distance = atr * tactic_config.get("ATR_SL_MULTIPLIER", 2.0) if atr > 0 else entry_price * 0.05
                    sl_price = entry_price - risk_distance
                    tp_price = entry_price + (risk_distance * tactic_config.get("RR", 2.0))
                
                if tp_price <= entry_price or sl_price <= 0 or sl_price >= entry_price: continue

                new_trade = {"trade_id": str(uuid.uuid4()),"symbol": symbol,"interval": interval,"status": "ACTIVE","opened_by_tactic": selected_tactic_name,"trade_type": trade_type,"entry_price": entry_price,"tp": round(tp_price, 8),"sl": round(sl_price, 8),"invested_usd": invested_usd,"entry_time": datetime.now(VIETNAM_TZ).isoformat(),"entry_score": final_score}
                portfolio_state["cash"] -= invested_usd
                portfolio_state["active_trades"].append(new_trade)
                log_message(f"🔥 Lệnh Mới ({selected_tactic_name}/{trade_type}): {symbol} | Vốn: ${invested_usd:,.2f} | Rủi ro: {risk_tier}")

                embed = {"title": f"🔥 Lệnh Mới: Mua {symbol}", "color": 3447003, "description": f"**Lối đánh:** {selected_tactic_name} ({risk_tier})\n**Loại lệnh:** {trade_type}", "fields": [{"name": "Vốn đầu tư", "value": f"`${invested_usd:,.2f}`", "inline": True}, {"name": "Điểm tin cậy", "value": f"`{final_score:.2f}/10`", "inline": True}, {"name": "Giá vào lệnh", "value": f"`{entry_price}`", "inline": False}, {"name": "Chốt lời (TP)", "value": f"`{round(tp_price, 4)}`", "inline": True}, {"name": "Cắt lỗ (SL)", "value": f"`{round(sl_price, 4)}`", "inline": True}]}
                send_discord_embed(embed=embed) # Sử dụng send_discord_embed
                return

def select_best_tactic(market_snapshot: Dict) -> str:
    tactic_scores = {tactic: 0 for tactic in TACTICS_LAB}
    fg_index = market_snapshot.get("fear_greed", 50)
    btc_d1_adx = market_snapshot.get("btc_d1_adx", 20.0)
    btc_d1_atr_pct = market_snapshot.get("btc_d1_atr_percent", 1.5)
    btc_breakout_signal = market_snapshot.get("btc_breakout_signal", "none")
    
    log_message(f"🔍 Phân tích thị trường: F&G={fg_index}, BTC D1 ADX={btc_d1_adx:.1f}, BTC D1 ATR%={btc_d1_atr_pct:.2f}%, BTC 4H Breakout={btc_breakout_signal}")

    if btc_breakout_signal != 'none':
        tactic_scores['Breakout_Hunter'] += 10
        tactic_scores['AI_Aggressor'] += 3
    elif btc_d1_adx < 20:
        if btc_d1_atr_pct < 1.5:
            tactic_scores['Cautious_Observer'] += 5
        else:
            tactic_scores['Range_Trader'] += 5
        tactic_scores['AI_Aggressor'] -= 2
    elif btc_d1_adx > 28:
        tactic_scores['AI_Aggressor'] += 4
        tactic_scores['Balanced_Trader'] += 2
        tactic_scores['Range_Trader'] -= 3
        tactic_scores['Cautious_Observer'] -= 3
    
    if fg_index < 25: tactic_scores['Dip_Hunter'] += 3
    tactic_scores['Balanced_Trader'] += 1
    
    log_message(f"Chấm điểm lối đánh: {tactic_scores}")
    best_tactic = max(tactic_scores, key=tactic_scores.get)
    log_message(f"🏆 Lối đánh chiến thắng: [{best_tactic}]")
    return best_tactic

# ==============================================================================
# ======================== BÁO CÁO & CẬP NHẬT (GrandFinal) ====================
# ==============================================================================

def build_grand_final_summary(state: Dict) -> str:
    """Tạo báo cáo tổng kết hoàn chỉnh dạng text."""
    now_vn = datetime.now(VIETNAM_TZ)
    total_equity = calculate_total_equity(state)
    pnl_usd = total_equity - INITIAL_CAPITAL
    pnl_percent = (pnl_usd / INITIAL_CAPITAL) * 100 if INITIAL_CAPITAL > 0 else 0
    
    # --- Icon thông minh ---
    if pnl_percent > 5: brain_icon = "🚀"
    elif pnl_percent < -5: brain_icon = "💥"
    else: brain_icon = "🧠"

    # --- Phần 1: Tổng quan ---
    history = state.get('trade_history', [])
    wins = [t for t in history if t.get('pnl_usd', 0) > 0]
    losses = [t for t in history if t.get('pnl_usd', 0) < 0]
    total_closed = len(wins) + len(losses)
    winrate = (len(wins) / total_closed * 100) if total_closed > 0 else 0.0

    report_lines = [
        f"📊 **Báo Cáo Tổng Quan - {now_vn.strftime('%H:%M %d-%m-%Y')}**",
        "----------------------------------------------------",
        f"{brain_icon} **Tổng Tài Sản:** `${total_equity:,.2f}` (`{pnl_percent:+.2f}%` từ `${INITIAL_CAPITAL:,.2f}`)",
        f"   - **PnL Thực Tế:** `${pnl_usd:,.2f}`",
        f"   - **Winrate:** `{winrate:.2f}%` ({len(wins)}W/{len(losses)}L)",
        f"💰 **Tiền Mặt Sẵn Sàng:** `${state.get('cash', 0):,.2f}`",
        " "
    ]

    # --- Phần 2: Vị thế đang mở ---
    active_trades = state.get('active_trades', [])
    report_lines.append(f"💼 **Vị thế đang mở ({len(active_trades)})**")
    if not active_trades:
        report_lines.append("_Không có vị thế nào đang mở._")
    else:
        for trade in active_trades:
            pnl_usd, pnl_pct = get_current_pnl(trade)
            icon = "🟢" if pnl_usd >= 0 else "🔴"
            # Thêm chi tiết Stop Loss và Take Profit vào báo cáo
            report_lines.append(f"{icon} **{trade['symbol']}** ({trade['interval']}) | Vốn: `${trade['invested_usd']:,.2f}` | PnL: `${pnl_usd:,.2f}` (`{pnl_pct:+.2f}%) | TP: `{trade['tp']:.4f}` | SL: `{trade['sl']:.4f}`")
    report_lines.append(" ")
    
    # --- Phần 3: Top Lệnh Thắng/Thua ---
    if history:
        # Top 5 Thắng
        top_wins = sorted(wins, key=lambda x: x['pnl_usd'], reverse=True)[:5]
        report_lines.append("🏆 **Top 5 Lệnh Thắng Gần Nhất**")
        if not top_wins: report_lines.append("_Chưa có lệnh thắng nào._")
        else:
            for i, trade in enumerate(top_wins):
                report_lines.append(f"`{i+1}.` {trade['symbol']} | PnL: `${trade['pnl_usd']:,.2f}` (`{trade['pnl_percent']:.2f}%`) | Lối đánh: {trade['opened_by_tactic']}")
        report_lines.append(" ")
        
        # Top 5 Thua
        top_losses = sorted(losses, key=lambda x: x['pnl_usd'])[:5]
        report_lines.append("💔 **Top 5 Lệnh Thua Gần Nhất**")
        if not top_losses: report_lines.append("_Chưa có lệnh thua nào._")
        else:
            for i, trade in enumerate(top_losses):
                report_lines.append(f"`{i+1}.` {trade['symbol']} | PnL: `${trade['pnl_usd']:,.2f}` (`{trade['pnl_percent']:.2f}%`) | Lối đánh: {trade['opened_by_tactic']}")
        report_lines.append(" ")

    # --- Phần 4: Lệnh ít biến động (Sideway) ---
    sideway_trades = []
    for trade in active_trades:
        _, pnl_pct = get_current_pnl(trade)
        # Sử dụng ngưỡng từ cấu hình stale trade rules cho interval cụ thể
        interval_rules = RISK_RULES_CONFIG["STALE_TRADE_RULES"].get(trade['interval'], {})
        stale_pnl_threshold = interval_rules.get("PNL_PCT_THRESHOLD", RISK_RULES_CONFIG["STALE_TRADE_RULES"]["1h"]["PNL_PCT_THRESHOLD"]) # Fallback to 1h if not found

        if abs(pnl_pct) < stale_pnl_threshold:
            entry_time = datetime.fromisoformat(trade['entry_time'])
            holding_hours = (now_vn - entry_time).total_seconds() / 3600
            trade['holding_hours'] = holding_hours
            trade['pnl_pct'] = pnl_pct
            sideway_trades.append(trade)
            
    report_lines.append("⚖️ **Lệnh Ít Biến Động Nhất (Sideway)**")
    if not sideway_trades:
        report_lines.append("_Không có lệnh nào đang sideway._")
    else:
        # Sắp xếp theo thời gian giữ lâu nhất
        sorted_sideway = sorted(sideway_trades, key=lambda x: x['holding_hours'], reverse=True)[:5]
        for trade in sorted_sideway:
            report_lines.append(f"🟡 **{trade['symbol']}** ({trade['interval']}) | PnL: `{trade['pnl_pct']:.2f}%` | Giữ: `{trade['holding_hours']:.1f}h`")
    report_lines.append(" ")

    report_lines.append("----------------------------------------------------")
    report_lines.append(f"⏳ Cập nhật lúc: {now_vn.strftime('%H:%M:%S')}")
    
    return "\n".join(report_lines)

def handle_grand_final_smart_update(state: Dict, total_equity: float):
    if not SMART_UPDATE_CONFIG["ENABLED"]: return
    now_aware = datetime.now(VIETNAM_TZ)
    last_update = state.get("last_smart_update", {})
    last_ts_str = last_update.get("timestamp")
    
    if not last_ts_str:
        state["last_smart_update"] = {"timestamp": now_aware.isoformat(), "total_equity": total_equity}
        return

    last_ts = datetime.fromisoformat(last_ts_str).astimezone(VIETNAM_TZ)
    minutes_passed = (now_aware - last_ts).total_seconds() / 60
    
    time_ok = minutes_passed > SMART_UPDATE_CONFIG["COOLDOWN_MINUTES"]
    force_ok = minutes_passed > SMART_UPDATE_CONFIG["FORCE_UPDATE_MINUTES"]
    
    last_equity = last_update.get("total_equity", total_equity)
    equity_change_pct = ((total_equity - last_equity) / last_equity * 100) if last_equity > 0 else 0
    pnl_threshold_passed = abs(equity_change_pct) > SMART_UPDATE_CONFIG["PNL_CHANGE_THRESHOLD_PCT"]

    if (time_ok and pnl_threshold_passed) or force_ok:
        pnl_change_usd = total_equity - last_equity
        icon = "📈" if pnl_change_usd >= 0 else "📉"
        update_lines = [
            f"💡 **Cập nhật Nhanh Danh mục** {icon}",
            f"> **Tổng tài sản:** `${total_equity:,.2f}`",
            f"> **Thay đổi từ lần trước:** `${pnl_change_usd:,.2f}` (`{equity_change_pct:+.2f}%`)"
        ]

        active_trades = state.get('active_trades', [])
        if active_trades:
            for trade in active_trades:
                trade['current_pnl_usd'], trade['current_pnl_pct'] = get_current_pnl(trade)
            sorted_trades = sorted(active_trades, key=lambda x: x['current_pnl_usd'], reverse=True)
            top_gain_trade = sorted_trades[0] if sorted_trades else None
            top_loss_trade = sorted_trades[-1] if sorted_trades else None

            if top_gain_trade:
                update_lines.append(f"> **Lệnh tốt nhất:** 🟢 **{top_gain_trade['symbol']}** (`{top_gain_trade['current_pnl_pct']:+.2f}%`)")
            if top_loss_trade and (not top_gain_trade or top_gain_trade['trade_id'] != top_loss_trade['trade_id']):
                update_lines.append(f"> **Lệnh tệ nhất:** 🔴 **{top_loss_trade['symbol']}** (`{top_loss_trade['current_pnl_pct']:+.2f}%`)")

        send_discord_message_chunks("\n".join(update_lines))
        state["last_smart_update"] = {"timestamp": now_aware.isoformat(), "total_equity": total_equity}


# ==============================================================================
# ======================== PHIÊN GIAO DỊCH CHÍNH (GrandFinal) =================
# ==============================================================================

def run_grand_final_session():
    log_message("====== 🚀 QUẢN LÝ DANH MỤC (GrandFinal) BẮT ĐẦU PHIÊN LÀM VIỆC 🚀 ======")
    
    try:
        # 1. Tải trạng thái danh mục hiện tại
        portfolio_state = load_json_file(STATE_FILE, {"cash": INITIAL_CAPITAL, "active_trades": [], "trade_history": [], "last_smart_update": {}})
        
        # 2. Thu thập dữ liệu và tính toán chỉ báo
        all_indicators.clear()
        all_symbols_to_fetch = list(set(SYMBOLS_TO_SCAN + ["BTCUSDT"]))
        for symbol in all_symbols_to_fetch:
            all_indicators[symbol] = {}
            for interval in ALL_TIME_FRAMES:
                try:
                    df = get_price_data(symbol, interval, limit=GENERAL_CONFIG["DATA_FETCH_LIMIT"])
                    if not df.empty: all_indicators[symbol][interval] = calculate_indicators(df, symbol, interval)
                except Exception as e: log_message(f"❌ Lỗi khi tính chỉ báo cho {symbol}-{interval}: {e}")
        
        # 3. Xử lý đóng lệnh (TP/SL và lệnh kẹt)
        closed_by_tp_sl = handle_trade_closure(portfolio_state) 
        closed_by_stale = handle_stale_trades_by_interval(portfolio_state) # Cập nhật hàm gọi
        newly_closed_trades = closed_by_tp_sl + closed_by_stale
        if newly_closed_trades: export_trade_history_to_csv(newly_closed_trades)
        
        # 4. Phân tích & Ra quyết định
        total_equity = calculate_total_equity(portfolio_state)
        
        # 4.1. Gửi Cập nhật Danh mục Thông minh (Smart Update)
        handle_grand_final_smart_update(portfolio_state, total_equity) # Cập nhật hàm gọi

        # 4.2. Chọn Lối đánh (Tactic)
        btc_d1_indicators = all_indicators.get("BTCUSDT", {}).get("1d", {})
        btc_h4_indicators = all_indicators.get("BTCUSDT", {}).get("4h", {})
        market_context_data = load_json_file(os.path.join(PROJECT_ROOT, "ricenews/lognew/market_context.json"))
        market_snapshot = {
            "fear_greed": market_context_data.get("fear_greed", 50),
            "btc_d1_adx": btc_d1_indicators.get("adx", 20.0),
            "btc_d1_atr_percent": btc_d1_indicators.get("atr_percent", 1.5),
            "btc_breakout_signal": btc_h4_indicators.get("breakout_signal", "none")
        }
        selected_tactic_name = select_best_tactic(market_snapshot) 
        last_tactic = portfolio_state.get("last_selected_tactic")
        if last_tactic != selected_tactic_name:
            alert_manager("TACTIC_CHANGE", content=f"🧠 **Bộ não đã thay đổi Lối đánh sang:** `{selected_tactic_name}`")
            portfolio_state["last_selected_tactic"] = selected_tactic_name
            
        # 5. Mở lệnh mới
        find_and_open_new_trades(portfolio_state, selected_tactic_name, total_equity)

        # 6. Báo cáo & Lưu trạng thái
        final_equity = calculate_total_equity(portfolio_state)
        invested_in_active_trades = sum(t.get('invested_usd', 0) for t in portfolio_state.get('active_trades', []))
        portfolio_state['cash'] = final_equity - invested_in_active_trades
        log_message(f"💰 Tiền Mặt: ${portfolio_state['cash']:,.2f} | Tổng Tài Sản: ${final_equity:,.2f} | Lệnh Mở: {len(portfolio_state['active_trades'])}")
        save_json_file(STATE_FILE, portfolio_state)
        
        # Gửi Báo cáo Daily Summary
        now_vn = datetime.now(VIETNAM_TZ)
        if now_vn.hour in GENERAL_CONFIG["DAILY_SUMMARY_HOURS"]:
            cooldowns = load_json_file(TIMESTAMP_FILE, {})
            last_alert_str = cooldowns.get("DAILY_SUMMARY")
            if last_alert_str:
                last_alert_time = datetime.fromisoformat(last_alert_str).astimezone(VIETNAM_TZ)
                if now_vn - last_alert_time < timedelta(minutes=ALERT_CONFIG["ALERT_COOLDOWNS_MINUTES"]["DAILY_SUMMARY"]):
                    return # Vẫn trong thời gian cooldown, không làm gì cả
            
            report_content = build_grand_final_summary(portfolio_state) # Cập nhật hàm gọi
            send_discord_message_chunks(report_content) # Sử dụng hàm gửi chunks

            # Cập nhật lại timestamp sau khi đã gửi thành công
            cooldowns["DAILY_SUMMARY"] = now_vn.isoformat()
            save_json_file(TIMESTAMP_FILE, cooldowns)

    except Exception as e:
        log_message(f"!!!!!! ❌ LỖI NGHIÊM TRỌNG TRONG PHIÊN LÀM VIỆC ❌ !!!!!!")
        import traceback
        log_message(traceback.format_exc())

    log_message("====== ✅ KẾT THÚC PHIÊN LÀM VIỆC ✅ ======")

if __name__ == "__main__":
    run_grand_final_session()
