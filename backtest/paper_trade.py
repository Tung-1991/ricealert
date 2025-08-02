# -*- coding: utf-8 -*-
"""
Paper Trade - The 4-Zone Strategy (Refactored)
Version: 8.3.1 - Clarity & Sync
Date: 2025-08-03

Mô tả:
Đây là phiên bản tái cấu trúc của paper_trade.py.
Mục tiêu chính là cải thiện cấu trúc, khả năng đọc và bảo trì code
mà không làm thay đổi logic giao dịch cốt lõi.

Các cải tiến chính:
- Lập trình hướng đối tượng (OOP): Toàn bộ logic được đóng gói trong class `PaperTrader`
  giúp quản lý trạng thái (state) và các hoạt động một cách mạch lạc,
  loại bỏ các biến toàn cục.
- Cấu trúc rõ ràng: Code được chia thành các khu vực chức năng riêng biệt
  (Config, Utilities, Data Fetching, Trade Logic, Reporting, Main Execution).
- Quản lý Config tập trung: Tất cả các cấu hình được gom vào một class `Config` duy nhất,
  dễ dàng tìm kiếm và điều chỉnh.
- Docstrings và Type Hinting: Bổ sung docstring chi tiết cho các class và phương thức,
  đồng thời chuẩn hóa Type Hinting để tăng cường sự rõ ràng.
- Hàm được chia nhỏ: Các hàm lớn, phức tạp (ví dụ: `check_and_manage_open_positions`)
  được chia thành các phương thức nhỏ hơn, mỗi phương thức thực hiện một nhiệm vụ cụ thể.
- Quản lý đường dẫn hiện đại: Sử dụng `pathlib` thay cho `os.path` để xử lý
  đường dẫn file một cách an toàn và trực quan hơn.
"""
import os
import sys
import json
import uuid
import time
import requests
import pytz
import pandas as pd
import numpy as np
import ta
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Any, Tuple, Optional, Literal
from dotenv import load_dotenv

# --- Tải và Thiết lập Ban đầu ---
# Sử dụng pathlib để quản lý đường dẫn một cách hiện đại và an toàn hơn
try:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
    sys.path.append(str(PROJECT_ROOT))
    load_dotenv(dotenv_path=PROJECT_ROOT / '.env')

    from indicator import get_price_data, calculate_indicators
    from trade_advisor import get_advisor_decision, FULL_CONFIG as ADVISOR_BASE_CONFIG
except (ImportError, FileNotFoundError) as e:
    sys.exit(f"Lỗi khởi tạo: Không thể tải các module hoặc file .env. Chi tiết: {e}")

# ==============================================================================
# ================== ⚙️ TRUNG TÂM CẤU HÌNH (Đồng bộ v8.3.1) ⚙️ ==================
# ==============================================================================
class Config:
    """
    Class chứa toàn bộ cấu hình của bot.
    Việc gom vào một nơi giúp dễ dàng quản lý và tham chiếu.
    """
    # --- 1. Cấu hình Cơ bản & Môi trường ---
    INITIAL_CAPITAL = 10000.0
    SYMBOLS_TO_SCAN = [s.strip() for s in os.getenv("SYMBOLS_TO_SCAN", "ETHUSDT,BTCUSDT").split(',')]
    INTERVALS_TO_SCAN = ["1h", "4h", "1d"]
    ALL_TIME_FRAMES = ["1h", "4h", "1d"]
    VIETNAM_TZ = pytz.timezone('Asia/Ho_Chi_Minh')

    # --- 2. Cấu hình Đường dẫn & File ---
    BASE_DIR = Path(__file__).resolve().parent
    PAPER_DATA_DIR = BASE_DIR / "paper_data"
    CACHE_DIR = PAPER_DATA_DIR / "indicator_cache"
    LOG_FILE = PAPER_DATA_DIR / "paper_trade_log.txt"
    ERROR_LOG_FILE = PAPER_DATA_DIR / "error_log.txt"
    STATE_FILE = PAPER_DATA_DIR / "paper_trade_state.json"
    TRADE_HISTORY_CSV_FILE = PAPER_DATA_DIR / "trade_history.csv"

    # --- 3. Cấu hình Vận hành & Logic ---
    GENERAL = {
        "DATA_FETCH_LIMIT": 300,
        "DAILY_SUMMARY_TIMES": ["08:10", "20:10"],
        "TRADE_COOLDOWN_HOURS": 1,
        "CRITICAL_ERROR_ALERT_COOLDOWN_MINUTES": 30
    }
    
    MTF_ANALYSIS = {
        "ENABLED": True,
        "BONUS_COEFFICIENT": 1.15,
        "PENALTY_COEFFICIENT": 0.85,
        "SEVERE_PENALTY_COEFFICIENT": 0.70,
        "SIDEWAYS_PENALTY_COEFFICIENT": 0.90
    }
    
    ACTIVE_TRADE_MANAGEMENT = {
        "EARLY_CLOSE_ABSOLUTE_THRESHOLD": 4.8,
        "EARLY_CLOSE_RELATIVE_DROP_PCT": 0.27,
        "PARTIAL_EARLY_CLOSE_PCT": 0.5,
        "PROFIT_PROTECTION": {
            "ENABLED": True,
            "MIN_PEAK_PNL_TRIGGER": 3.5,
            "PNL_DROP_TRIGGER_PCT": 2.0,
            "PARTIAL_CLOSE_PCT": 0.7
        }
    }
    
    DYNAMIC_ALERT = {
        "ENABLED": True,
        "COOLDOWN_HOURS": 3,
        "FORCE_UPDATE_HOURS": 10,
        "PNL_CHANGE_THRESHOLD_PCT": 2.0
    }
    
    RISK_RULES = {
        "MAX_ACTIVE_TRADES": 12,
        "MAX_SL_PERCENT_BY_TIMEFRAME": {"1h": 0.06, "4h": 0.08, "1d": 0.10},
        "MAX_TP_PERCENT_BY_TIMEFRAME": {"1h": 0.12, "4h": 0.20, "1d": 0.35},
        "STALE_TRADE_RULES": {
            "1h": {"HOURS": 48, "PROGRESS_THRESHOLD_PCT": 25.0},
            "4h": {"HOURS": 72, "PROGRESS_THRESHOLD_PCT": 25.0},
            "1d": {"HOURS": 168, "PROGRESS_THRESHOLD_PCT": 20.0},
            "STAY_OF_EXECUTION_SCORE": 6.8
        }
    }

    CAPITAL_MANAGEMENT = {
        "MAX_TOTAL_EXPOSURE_PCT": 0.75
    }

    DCA = {
        "ENABLED": True,
        "MAX_DCA_ENTRIES": 2,
        "TRIGGER_DROP_PCT": -5.0,
        "SCORE_MIN_THRESHOLD": 6.5,
        "CAPITAL_MULTIPLIER": 0.75,
        "DCA_COOLDOWN_HOURS": 8
    }

    ALERT = {
        "DISCORD_WEBHOOK_URL": os.getenv("DISCORD_PAPER_WEBHOOK"),
        "DISCORD_CHUNK_DELAY_SECONDS": 2
    }

    # --- 4. Cấu hình Chiến lược & Tactics ---
    LEADING_ZONE, COINCIDENT_ZONE, LAGGING_ZONE, NOISE_ZONE = "LEADING", "COINCIDENT", "LAGGING", "NOISE"
    ZONES = [LEADING_ZONE, COINCIDENT_ZONE, LAGGING_ZONE, NOISE_ZONE]
    
    ZONE_BASED_POLICIES = {
        LEADING_ZONE:   {"CAPITAL_PCT": 0.04},
        COINCIDENT_ZONE:{"CAPITAL_PCT": 0.07},
        LAGGING_ZONE:   {"CAPITAL_PCT": 0.06},
        NOISE_ZONE:     {"CAPITAL_PCT": 0.03}
    }

    TACTICS_LAB = {
        "Breakout_Hunter": {
            "NOTES": "Săn đột phá.", "OPTIMAL_ZONE": [LEADING_ZONE, COINCIDENT_ZONE],
            "WEIGHTS": {'tech': 0.7, 'context': 0.1, 'ai': 0.2},
            "ENTRY_SCORE": 7.0, "RR": 2.5, "ATR_SL_MULTIPLIER": 1.8,
            "USE_TRAILING_SL": True, "TRAIL_ACTIVATION_RR": 1.0, "TRAIL_DISTANCE_RR": 0.8,
            "ENABLE_PARTIAL_TP": True, "TP1_RR_RATIO": 1.0, "TP1_PROFIT_PCT": 0.5
        },
        "Dip_Hunter": {
            "NOTES": "Bắt đáy/sóng hồi.", "OPTIMAL_ZONE": [LEADING_ZONE, COINCIDENT_ZONE],
            "WEIGHTS": {'tech': 0.6, 'context': 0.2, 'ai': 0.2},
            "ENTRY_SCORE": 6.8, "RR": 2.2, "ATR_SL_MULTIPLIER": 2.0,
            "USE_TRAILING_SL": False, "TRAIL_ACTIVATION_RR": None,
            "ENABLE_PARTIAL_TP": True, "TP1_RR_RATIO": 0.8, "TP1_PROFIT_PCT": 0.6
        },
        "AI_Aggressor": {
            "NOTES": "Tin vào AI.", "OPTIMAL_ZONE": COINCIDENT_ZONE,
            "WEIGHTS": {'tech': 0.3, 'context': 0.1, 'ai': 0.6},
            "ENTRY_SCORE": 6.6, "RR": 2.2, "ATR_SL_MULTIPLIER": 2.5,
            "USE_TRAILING_SL": True, "TRAIL_ACTIVATION_RR": 1.2, "TRAIL_DISTANCE_RR": 0.8,
            "ENABLE_PARTIAL_TP": True, "TP1_RR_RATIO": 1.0, "TP1_PROFIT_PCT": 0.5
        },
        "Balanced_Trader": {
            "NOTES": "Đi theo xu hướng.", "OPTIMAL_ZONE": LAGGING_ZONE,
            "WEIGHTS": {'tech': 0.4, 'context': 0.2, 'ai': 0.4},
            "ENTRY_SCORE": 6.3, "RR": 1.8, "ATR_SL_MULTIPLIER": 2.8,
            "USE_TRAILING_SL": True, "TRAIL_ACTIVATION_RR": 1.2, "TRAIL_DISTANCE_RR": 1.0,
            "ENABLE_PARTIAL_TP": True, "TP1_RR_RATIO": 1.2, "TP1_PROFIT_PCT": 0.5
        },
        "Cautious_Observer": {
            "NOTES": "Chỉ đánh khi có cơ hội VÀNG.", "OPTIMAL_ZONE": NOISE_ZONE,
            "WEIGHTS": {'tech': 0.7, 'context': 0.2, 'ai': 0.1},
            "ENTRY_SCORE": 8.0, "RR": 1.5, "ATR_SL_MULTIPLIER": 1.5,
            "USE_TRAILING_SL": True, "TRAIL_ACTIVATION_RR": 0.7, "TRAIL_DISTANCE_RR": 0.5,
            "ENABLE_PARTIAL_TP": True, "TP1_RR_RATIO": 0.8, "TP1_PROFIT_PCT": 0.5
        }
    }


# ==============================================================================
# ======================== 🚀 PAPER TRADER CLASS 🚀 ==========================
# ==============================================================================

class PaperTrader:
    """
    Class chính điều khiển toàn bộ logic của paper trading bot.
    Quản lý trạng thái, dữ liệu, logic giao dịch và báo cáo.
    """

    def __init__(self):
        """Khởi tạo bot, tải cấu hình và trạng thái."""
        self.config = Config()
        self._setup_directories()

        self.state: Dict[str, Any] = self._load_state()
        self.indicator_results: Dict[str, Any] = {}
        self.price_dataframes: Dict[str, Any] = {}
        self.session_events: List[str] = []

        self._log_message("="*50)
        self._log_message("🚀 Khởi động Paper Trading Bot...")
        self._check_capital_adjustment()

    def _setup_directories(self):
        """Tạo các thư mục cần thiết nếu chưa tồn tại."""
        self.config.PAPER_DATA_DIR.mkdir(exist_ok=True)
        self.config.CACHE_DIR.mkdir(exist_ok=True)

    # --- 1. Utility Methods ---
    def _log_message(self, message: str):
        """Ghi log thông thường ra console và file."""
        timestamp = datetime.now(self.config.VIETNAM_TZ).strftime('%Y-%m-%d %H:%M:%S')
        log_entry = f"[{timestamp}] (PaperTrade) {message}"
        print(log_entry)
        with open(self.config.LOG_FILE, "a", encoding="utf-8") as f:
            f.write(log_entry + "\n")

    def _log_error(self, message: str, error_details: str = "", send_to_discord: bool = False):
        """Ghi log lỗi và tùy chọn gửi cảnh báo qua Discord."""
        timestamp = datetime.now(self.config.VIETNAM_TZ).strftime('%Y-%m-%d %H:%M:%S')
        log_entry = f"[{timestamp}] (PaperTrade-ERROR) {message}\n"
        if error_details:
            log_entry += f"--- TRACEBACK ---\n{error_details}\n------------------\n"
        with open(self.config.ERROR_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(log_entry)
        self._log_message(f"!!!!!! ❌ LỖI: {message}. Chi tiết trong error.log ❌ !!!!!!")
        if send_to_discord:
            discord_message = f"🔥🔥🔥 BOT MÔ PHỎNG GẶP LỖI 🔥🔥🔥\n**{message}**\n```python\n{error_details if error_details else 'N/A'}\n```"
            self._send_discord_message(discord_message)

    def _load_state(self) -> Dict[str, Any]:
        """Tải trạng thái từ file JSON, hoặc tạo mới nếu không tồn tại."""
        if not self.config.STATE_FILE.exists():
            self._log_message("Không tìm thấy file state, khởi tạo mới...")
            return {
                "cash": self.config.INITIAL_CAPITAL,
                "initial_capital": self.config.INITIAL_CAPITAL,
                "active_trades": [],
                "trade_history": [],
                "cooldown_until": {},
                "last_dynamic_alert": {},
                "last_summary_sent_time": None,
                "last_critical_error": {}
            }
        try:
            with open(self.config.STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            self._log_error(f"File JSON hỏng: {self.config.STATE_FILE}. Không thể tiếp tục.", send_to_discord=True)
            sys.exit(1)

    def _save_state(self):
        """Lưu trạng thái hiện tại vào file JSON."""
        temp_path = self.config.STATE_FILE.with_suffix(".json.tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(self.state, f, indent=4, ensure_ascii=False)
        os.replace(temp_path, self.config.STATE_FILE)

    def _send_discord_message(self, full_content: str):
        """Gửi tin nhắn (có thể chia nhỏ) đến Discord webhook."""
        webhook_url = self.config.ALERT["DISCORD_WEBHOOK_URL"]
        if not webhook_url:
            return

        max_len = 1900
        chunks = []
        current_chunk = ""
        for line in full_content.split('\n'):
            if len(current_chunk) + len(line) + 1 > max_len:
                if current_chunk:
                    chunks.append(current_chunk)
                current_chunk = line
            else:
                current_chunk += ("\n" + line) if current_chunk else line
        if current_chunk:
            chunks.append(current_chunk)

        for i, chunk in enumerate(chunks):
            content_to_send = f"*(Phần {i+1}/{len(chunks)})*\n{chunk}" if len(chunks) > 1 else chunk
            try:
                requests.post(webhook_url, json={"content": content_to_send}, timeout=15).raise_for_status()
                if i < len(chunks) - 1:
                    time.sleep(self.config.ALERT["DISCORD_CHUNK_DELAY_SECONDS"])
            except requests.exceptions.RequestException as e:
                self._log_error(f"Lỗi gửi chunk Discord {i+1}/{len(chunks)}: {e}")
                break
    
    @staticmethod
    def _get_current_pnl(trade: Dict, current_price: Optional[float]) -> Tuple[float, float]:
        """Tính PnL (USD và %) cho một giao dịch."""
        if not (trade and trade.get('entry_price', 0) > 0 and current_price and current_price > 0):
            return 0.0, 0.0
        pnl_percent = ((current_price - trade['entry_price']) / trade['entry_price']) * 100
        pnl_usd = trade.get('total_invested_usd', 0.0) * (pnl_percent / 100)
        return pnl_usd, pnl_percent

    def _export_trade_history_to_csv(self, closed_trades: List[Dict]):
        """Xuất lịch sử các lệnh đã đóng ra file CSV."""
        if not closed_trades:
            return
        try:
            df = pd.DataFrame(closed_trades)
            df['entry_time'] = pd.to_datetime(df['entry_time']).dt.tz_convert(self.config.VIETNAM_TZ)
            if 'exit_time' in df.columns:
                df['exit_time'] = pd.to_datetime(df['exit_time']).dt.tz_convert(self.config.VIETNAM_TZ)
                df['holding_duration_hours'] = round((df['exit_time'] - df['entry_time']).dt.total_seconds() / 3600, 2)

            cols = ["trade_id", "symbol", "interval", "status", "opened_by_tactic", "tactic_used", "trade_type", "entry_price", "exit_price", "tp", "sl", "total_invested_usd", "pnl_usd", "pnl_percent", "entry_time", "exit_time", "holding_duration_hours", "entry_score", "dca_entries"]
            df = df[[c for c in cols if c in df.columns]]

            file_exists = self.config.TRADE_HISTORY_CSV_FILE.exists()
            header_mismatch = False
            if file_exists:
                try:
                    existing_cols = set(pd.read_csv(self.config.TRADE_HISTORY_CSV_FILE, nrows=0).columns)
                    if existing_cols != set(df.columns):
                        header_mismatch = True
                except Exception:
                    header_mismatch = True
            
            write_header = not file_exists or header_mismatch
            write_mode = 'w' if write_header else 'a'
            df.to_csv(self.config.TRADE_HISTORY_CSV_FILE, mode=write_mode, header=write_header, index=False, encoding="utf-8")
        except Exception as e:
            self._log_error(f"Lỗi xuất lịch sử giao dịch ra CSV: {e}")

    # --- 2. Data Fetching & Processing ---
    def _get_price_data_with_cache(self, symbol: str, interval: str) -> Optional[pd.DataFrame]:
        """Tải dữ liệu giá, sử dụng cache để tăng tốc."""
        cache_filepath = self.config.CACHE_DIR / f"{symbol}-{interval}.parquet"
        limit = self.config.GENERAL["DATA_FETCH_LIMIT"]
        existing_df = None
        
        if cache_filepath.exists():
            try:
                existing_df = pd.read_parquet(cache_filepath)
            except Exception as e:
                self._log_message(f"⚠️ Lỗi đọc cache {cache_filepath}: {e}. Sẽ tải lại.")

        interval_map = {'h': 3600, 'd': 86400}
        interval_ms = int(interval[:-1]) * interval_map.get(interval[-1], 0) * 1000

        if existing_df is not None and not existing_df.empty and interval_ms > 0:
            last_ts = int(existing_df.index[-1].timestamp() * 1000)
            start_time = last_ts + interval_ms
            if int(datetime.now(timezone.utc).timestamp() * 1000) > start_time:
                new_data = get_price_data(symbol, interval, limit=limit, startTime=start_time)
                if new_data is not None and not new_data.empty:
                    combined = pd.concat([existing_df, new_data])
                    final_df = combined[~combined.index.duplicated(keep='last')].tail(limit).copy()
                else:
                    final_df = existing_df.tail(limit).copy()
            else:
                final_df = existing_df.tail(limit).copy()
        else:
            final_df = get_price_data(symbol, interval, limit=limit)

        if final_df is not None and not final_df.empty:
            try:
                final_df.to_parquet(cache_filepath)
            except Exception as e:
                self._log_error(f"Lỗi lưu cache {cache_filepath}: {e}")
            return final_df
        return existing_df

    def _run_heavy_tasks(self, equity: float):
        """
        Thực hiện các tác vụ nặng: tải dữ liệu, tính toán chỉ báo,
        cập nhật điểm số cho các lệnh đang mở và tìm kiếm cơ hội mới.
        """
        self._log_message("---[🔄 Bắt đầu chu trình tác vụ nặng 🔄]---")
        self.indicator_results.clear()
        self.price_dataframes.clear()
        
        symbols_to_load = list(set(self.config.SYMBOLS_TO_SCAN + [t['symbol'] for t in self.state.get('active_trades', [])] + ["BTCUSDT"]))
        self._log_message(f"Đang tải dữ liệu cho các symbol: {', '.join(symbols_to_load)}")

        for symbol in symbols_to_load:
            self.indicator_results[symbol], self.price_dataframes[symbol] = {}, {}
            for interval in self.config.ALL_TIME_FRAMES:
                df = self._get_price_data_with_cache(symbol, interval)
                if df is not None and not df.empty:
                    # Tính toán các chỉ báo phụ trợ ngay tại đây
                    df['ema_20'] = ta.trend.ema_indicator(df["close"], window=20)
                    df['ema_50'] = ta.trend.ema_indicator(df["close"], window=50)
                    df['bb_width'] = ta.volatility.BollingerBands(df["close"], window=20, window_dev=2).bollinger_wband()
                    
                    self.indicator_results[symbol][interval] = calculate_indicators(df.copy(), symbol, interval)
                    self.price_dataframes[symbol][interval] = df

        # Cập nhật điểm và zone cho các lệnh đang mở
        for trade in self.state.get("active_trades", []):
            indicators = self.indicator_results.get(trade['symbol'], {}).get(trade['interval'])
            if indicators:
                tactic_cfg = self.config.TACTICS_LAB.get(trade['opened_by_tactic'], {})
                decision = get_advisor_decision(trade['symbol'], trade['interval'], indicators, ADVISOR_BASE_CONFIG, weights_override=tactic_cfg.get("WEIGHTS"))
                trade['last_score'] = decision.get("final_score", 0.0)
                trade['last_zone'] = self._determine_market_zone(trade['symbol'], trade['interval'])
        
        self._find_and_open_new_trades(equity)
        self._log_message("---[✅ Hoàn thành chu trình tác vụ nặng ✅]---")

    # --- 3. Core Trading Logic ---
    def _close_trade_simulated(self, trade: Dict, reason: str, close_price: float, close_pct: float = 1.0) -> bool:
        """Mô phỏng việc đóng một phần hoặc toàn bộ lệnh."""
        invested_to_close = trade['total_invested_usd'] * close_pct
        pnl_on_closed_part = ((close_price - trade['entry_price']) / trade['entry_price']) * invested_to_close if trade['entry_price'] > 0 else 0

        if close_pct >= 0.999: # Đóng toàn bộ
            trade.update({
                'status': f'Closed ({reason})',
                'exit_price': close_price,
                'exit_time': datetime.now(self.config.VIETNAM_TZ).isoformat(),
                'pnl_usd': trade.get('realized_pnl_usd', 0.0) + pnl_on_closed_part,
                'pnl_percent': ((close_price - trade['entry_price']) / trade['entry_price']) * 100 if trade['entry_price'] > 0 else 0
            })
            self.state['cash'] += trade['total_invested_usd'] + pnl_on_closed_part
            self.state['active_trades'] = [t for t in self.state['active_trades'] if t['trade_id'] != trade['trade_id']]
            self.state['trade_history'].append(trade)
            self.state.setdefault('cooldown_until', {})[trade['symbol']] = (datetime.now(self.config.VIETNAM_TZ) + timedelta(hours=self.config.GENERAL["TRADE_COOLDOWN_HOURS"])).isoformat()
            self._export_trade_history_to_csv([trade])
            
            icon = '✅' if pnl_on_closed_part >= 0 else '❌'
            self.session_events.append(f"🎬 {icon} {trade['symbol']} (Đóng toàn bộ - {reason}): PnL ${trade['pnl_usd']:,.2f}")
        else: # Đóng một phần
            trade['realized_pnl_usd'] = trade.get('realized_pnl_usd', 0.0) + pnl_on_closed_part
            trade['total_invested_usd'] *= (1 - close_pct)
            self.state['cash'] += invested_to_close + pnl_on_closed_part
            trade.setdefault('tactic_used', []).append(f"Partial_Close_{reason}")
            self.session_events.append(f"💰 {trade['symbol']} (Đóng {close_pct*100:.0f}% - {reason}): PnL ${pnl_on_closed_part:,.2f}")
        return True

    def _manage_open_positions(self):
        """Kiểm tra và quản lý tất cả các vị thế đang mở."""
        for trade in self.state.get("active_trades", [])[:]:
            indicators = self.indicator_results.get(trade['symbol'], {}).get(trade['interval'], {})
            current_price = indicators.get('price')
            if not current_price:
                continue

            # Cập nhật PnL đỉnh
            _, pnl_percent = self._get_current_pnl(trade, current_price=current_price)
            trade['peak_pnl_percent'] = max(trade.get('peak_pnl_percent', 0.0), pnl_percent)

            # Kiểm tra các điều kiện đóng lệnh
            if self._check_sl_tp(trade, current_price): continue
            if self._check_early_close(trade, current_price): continue
            if self._check_partial_tp(trade, current_price): continue
            if self._check_profit_protection(trade, current_price): continue
            self._check_trailing_sl(trade, current_price)

    def _check_sl_tp(self, trade: Dict, current_price: float) -> bool:
        """Kiểm tra chạm Stop Loss hoặc Take Profit."""
        if current_price <= trade['sl']:
            return self._close_trade_simulated(trade, "SL", state=self.state, close_price=trade['sl'])
        if current_price >= trade['tp']:
            return self._close_trade_simulated(trade, "TP", state=self.state, close_price=trade['tp'])
        return False

    def _check_early_close(self, trade: Dict, current_price: float) -> bool:
        """Kiểm tra các quy tắc đóng lệnh sớm dựa trên điểm số."""
        cfg = self.config.ACTIVE_TRADE_MANAGEMENT
        last_score, entry_score = trade.get('last_score', 5.0), trade.get('entry_score', 5.0)

        if last_score < cfg['EARLY_CLOSE_ABSOLUTE_THRESHOLD']:
            return self._close_trade_simulated(trade, f"EC_Abs_{last_score:.1f}", self.state, current_price)
        
        if last_score < entry_score and not trade.get('is_in_warning_zone', False):
            trade['is_in_warning_zone'] = True
        
        if trade.get('is_in_warning_zone', False) and not trade.get('partial_closed_by_score', False):
            if last_score < entry_score * (1 - cfg.get('EARLY_CLOSE_RELATIVE_DROP_PCT', 0.35)):
                if self._close_trade_simulated(trade, f"EC_Rel_{last_score:.1f}", self.state, current_price, close_pct=cfg.get("PARTIAL_EARLY_CLOSE_PCT", 0.5)):
                    trade['partial_closed_by_score'] = True
                    trade['sl'] = trade['entry_price'] # Dời SL về entry
                    return True # Đã xử lý, có thể tiếp tục vòng lặp
        return False

    def _check_partial_tp(self, trade: Dict, current_price: float) -> bool:
        """Kiểm tra chốt lời một phần (TP1) theo R:R ratio."""
        tactic_cfg = self.config.TACTICS_LAB.get(trade.get('opened_by_tactic'), {})
        if not tactic_cfg.get("ENABLE_PARTIAL_TP", False) or trade.get("tp1_hit", False):
            return False

        initial_risk_dist = abs(trade['initial_entry']['price'] - trade['initial_sl'])
        if initial_risk_dist <= 0: return False

        pnl_ratio = (current_price - trade['entry_price']) / initial_risk_dist
        tp1_rr_ratio = tactic_cfg.get("TP1_RR_RATIO", 1.0)

        if pnl_ratio >= tp1_rr_ratio:
            tp1_price = trade['initial_entry']['price'] + (initial_risk_dist * tp1_rr_ratio)
            if self._close_trade_simulated(trade, f"TP1_{tp1_rr_ratio:.1f}R", self.state, tp1_price, close_pct=tactic_cfg.get("TP1_PROFIT_PCT", 0.5)):
                trade['tp1_hit'] = True
                trade['sl'] = trade['entry_price'] # Dời SL về entry
                return True
        return False

    def _check_profit_protection(self, trade: Dict, current_price: float) -> bool:
        """Kiểm tra quy tắc bảo vệ lợi nhuận."""
        pp_config = self.config.ACTIVE_TRADE_MANAGEMENT.get("PROFIT_PROTECTION", {})
        if not pp_config.get("ENABLED", False) or trade.get('profit_taken', False):
            return False

        _, pnl_percent = self._get_current_pnl(trade, current_price)
        if trade['peak_pnl_percent'] >= pp_config.get("MIN_PEAK_PNL_TRIGGER", 3.5):
            if (trade['peak_pnl_percent'] - pnl_percent) >= pp_config.get("PNL_DROP_TRIGGER_PCT", 2.0):
                if self._close_trade_simulated(trade, "Protect_Profit", self.state, current_price, close_pct=pp_config.get("PARTIAL_CLOSE_PCT", 0.7)):
                    trade['profit_taken'] = True
                    trade['sl'] = trade['entry_price'] # Dời SL về entry
                    return True
        return False

    def _check_trailing_sl(self, trade: Dict, current_price: float):
        """Kiểm tra và cập nhật Trailing Stop Loss."""
        tactic_cfg = self.config.TACTICS_LAB.get(trade.get('opened_by_tactic'), {})
        if not tactic_cfg.get("USE_TRAILING_SL", False):
            return

        initial_risk_dist = abs(trade['initial_entry']['price'] - trade['initial_sl'])
        if initial_risk_dist <= 0: return

        pnl_ratio_from_entry = (current_price - trade['entry_price']) / initial_risk_dist
        if pnl_ratio_from_entry >= tactic_cfg.get("TRAIL_ACTIVATION_RR", float('inf')):
            new_sl = current_price - (initial_risk_dist * tactic_cfg.get("TRAIL_DISTANCE_RR", 0.8))
            if new_sl > trade['sl']:
                self.session_events.append(f"📈 TSL {trade['symbol']}: SL mới {new_sl:.4f} (cũ {trade['sl']:.4f})")
                trade['sl'] = new_sl
                if "Trailing_SL_Active" not in trade.get('tactic_used', []):
                    trade.setdefault('tactic_used', []).append("Trailing_SL_Active")

    def _handle_stale_trades(self):
        """Xử lý các lệnh bị "stale" (kẹt lệnh quá lâu không có tiến triển)."""
        now_aware = datetime.now(self.config.VIETNAM_TZ)
        rules_cfg = self.config.RISK_RULES["STALE_TRADE_RULES"]
        
        for trade in self.state.get("active_trades", [])[:]:
            if 'stale_override_until' in trade and now_aware < datetime.fromisoformat(trade['stale_override_until']):
                continue
            
            rules = rules_cfg.get(trade.get("interval"))
            if not rules:
                continue

            holding_hours = (now_aware - datetime.fromisoformat(trade['entry_time'])).total_seconds() / 3600
            if holding_hours > rules["HOURS"]:
                current_price = self.indicator_results.get(trade['symbol'], {}).get(trade['interval'], {}).get('price')
                if not current_price: continue

                _, pnl_pct = self._get_current_pnl(trade, current_price=current_price)
                if pnl_pct < rules["PROGRESS_THRESHOLD_PCT"] and trade.get('last_score', 5.0) < rules_cfg["STAY_OF_EXECUTION_SCORE"]:
                    self._close_trade_simulated(trade, "Stale", self.state, current_price)

    def _handle_dca_opportunities(self, equity: float):
        """Tìm và thực hiện DCA cho các lệnh đủ điều kiện."""
        dca_cfg = self.config.DCA
        if not dca_cfg["ENABLED"]: return

        current_exposure_usd = sum(t.get('total_invested_usd', 0.0) for t in self.state.get("active_trades", []))
        now = datetime.now(self.config.VIETNAM_TZ)

        for trade in self.state.get("active_trades", [])[:]:
            # Các điều kiện kiểm tra để thực hiện DCA
            if len(trade.get("dca_entries", [])) >= dca_cfg["MAX_DCA_ENTRIES"]: continue
            if trade.get('last_dca_time') and (now - datetime.fromisoformat(trade.get('last_dca_time'))).total_seconds() / 3600 < dca_cfg['DCA_COOLDOWN_HOURS']: continue
            
            current_data = self.indicator_results.get(trade["symbol"], {}).get(trade["interval"], {})
            current_price = current_data.get('price')
            if not current_price or current_price <= 0: continue
            
            last_entry_price = trade['dca_entries'][-1]['price'] if trade.get('dca_entries') else trade['initial_entry']['price']
            price_drop_pct = ((current_price - last_entry_price) / last_entry_price) * 100
            if price_drop_pct > dca_cfg["TRIGGER_DROP_PCT"]: continue

            if get_advisor_decision(trade['symbol'], trade['interval'], current_data, ADVISOR_BASE_CONFIG).get("final_score", 0.0) < dca_cfg["SCORE_MIN_THRESHOLD"]: continue
            
            # Tính toán và thực hiện DCA
            dca_investment = (trade['dca_entries'][-1]['invested_usd'] if trade.get('dca_entries') else trade['initial_entry']['invested_usd']) * dca_cfg["CAPITAL_MULTIPLIER"]
            if dca_investment <= 0 or dca_investment > self.state['cash'] or (current_exposure_usd + dca_investment) > (equity * self.config.CAPITAL_MANAGEMENT["MAX_TOTAL_EXPOSURE_PCT"]): continue
            
            # Cập nhật trạng thái sau DCA
            self.state['cash'] -= dca_investment
            trade.setdefault('dca_entries', []).append({"price": current_price, "invested_usd": dca_investment, "timestamp": now.isoformat()})
            
            all_entries = [trade['initial_entry']] + trade['dca_entries']
            new_total_cost = sum(e['invested_usd'] for e in all_entries)
            new_avg_price = sum(e['price'] * e['invested_usd'] for e in all_entries) / new_total_cost if new_total_cost > 0 else 0
            
            initial_risk_dist = abs(trade['initial_entry']['price'] - trade['initial_sl'])
            trade.update({
                'entry_price': new_avg_price, 'total_invested_usd': new_total_cost,
                'sl': new_avg_price - initial_risk_dist,
                'tp': new_avg_price + (initial_risk_dist * self.config.TACTICS_LAB[trade['opened_by_tactic']]['RR']),
                'last_dca_time': now.isoformat()
            })
            trade.setdefault('tactic_used', []).append(f"DCA_{len(trade.get('dca_entries', []))}")
            self.session_events.append(f"🎯 DCA {trade['symbol']} với ${dca_investment:,.2f}")

    def _determine_market_zone(self, symbol: str, interval: str) -> str:
        """Xác định "zone" thị trường dựa trên các chỉ báo kỹ thuật."""
        indicators = self.indicator_results.get(symbol, {}).get(interval, {})
        df = self.price_dataframes.get(symbol, {}).get(interval)
        if not indicators or df is None or df.empty:
            return self.config.NOISE_ZONE
        
        scores = {zone: 0 for zone in self.config.ZONES}
        adx, bb_width, rsi_14, trend = indicators.get('adx', 20), indicators.get('bb_width', 0), indicators.get('rsi_14', 50), indicators.get('trend', "sideways")

        # Noise Zone
        if adx < 20: scores[self.config.NOISE_ZONE] += 3
        if 'ema_50' in df.columns and np.sign(df['close'].iloc[-30:] - df['ema_50'].iloc[-30:]).diff().ne(0).sum() > 4: scores[self.config.NOISE_ZONE] += 2
        
        # Lagging Zone (xu hướng rõ ràng)
        if adx > 25: scores[self.config.LAGGING_ZONE] += 2.5
        if trend == "uptrend": scores[self.config.LAGGING_ZONE] += 2
        if 'ema_20' in df.columns and 'ema_50' in df.columns and not df['ema_20'].isna().all() and not df['ema_50'].isna().all():
            if trend == "uptrend" and df['ema_20'].iloc[-1] > df['ema_50'].iloc[-1] and df['ema_20'].iloc[-10] > df['ema_50'].iloc[-10]:
                scores[self.config.LAGGING_ZONE] += 1.5
        
        # Leading Zone (tích lũy, chuẩn bị đột phá)
        if 'bb_width' in df.columns and not df['bb_width'].isna().all() and bb_width < df['bb_width'].iloc[-100:].quantile(0.20):
            scores[self.config.LEADING_ZONE] += 2.5
        htf_interval = '4h' if interval == '1h' else '1d'
        htf_trend = self.indicator_results.get(symbol, {}).get(htf_interval, {}).get('trend', 'sideway')
        if htf_trend == 'uptrend' and rsi_14 < 45: scores[self.config.LEADING_ZONE] += 2
        if adx > 28: scores[self.config.LEADING_ZONE] -= 2 # Phạt nếu xu hướng đã quá mạnh

        # Coincident Zone (đang diễn ra đột phá)
        if indicators.get('breakout_signal', "none") != "none": scores[self.config.COINCIDENT_ZONE] += 3
        if indicators.get('macd_cross', "neutral") not in ["neutral", "no_cross"]: scores[self.config.COINCIDENT_ZONE] += 2
        if indicators.get('vol_ma20', 1) > 0 and indicators.get('volume', 0) > indicators.get('vol_ma20', 1) * 2: scores[self.config.COINCIDENT_ZONE] += 1.5

        return max(scores, key=scores.get) if scores and any(v > 0 for v in scores.values()) else self.config.NOISE_ZONE

    def _get_mtf_adjustment_coefficient(self, symbol: str, target_interval: str) -> float:
        """Tính hệ số điều chỉnh điểm số dựa trên phân tích đa khung thời gian (MTF)."""
        cfg = self.config.MTF_ANALYSIS
        if not cfg["ENABLED"]: return 1.0
        
        trends = {tf: self.indicator_results.get(symbol, {}).get(tf, {}).get("trend", "sideways") for tf in self.config.ALL_TIME_FRAMES}
        fav, unfav, side = "uptrend", "downtrend", "sideways"

        if target_interval == "1h":
            htf1, htf2 = trends["4h"], trends["1d"]
            if htf1 == unfav and htf2 == unfav: return cfg["SEVERE_PENALTY_COEFFICIENT"]
            if htf1 == unfav or htf2 == unfav: return cfg["PENALTY_COEFFICIENT"]
            if htf1 == fav and htf2 == fav: return cfg["BONUS_COEFFICIENT"]
            if htf1 == side or htf2 == side: return cfg["SIDEWAYS_PENALTY_COEFFICIENT"]
        elif target_interval == "4h":
            htf1 = trends["1d"]
            if htf1 == unfav: return cfg["PENALTY_COEFFICIENT"]
            if htf1 == fav: return cfg["BONUS_COEFFICIENT"]
            if htf1 == side: return cfg["SIDEWAYS_PENALTY_COEFFICIENT"]
        return 1.0

    def _find_and_open_new_trades(self, equity: float):
        """Quét, đánh giá và mở các giao dịch mới nếu có cơ hội tốt."""
        if len(self.state.get("active_trades", [])) >= self.config.RISK_RULES["MAX_ACTIVE_TRADES"]:
            return

        potential_opportunities = []
        now_vn = datetime.now(self.config.VIETNAM_TZ)
        
        for symbol in self.config.SYMBOLS_TO_SCAN:
            if any(t['symbol'] == symbol for t in self.state.get("active_trades", [])): continue
            cooldown_map = self.state.get('cooldown_until', {})
            if symbol in cooldown_map and now_vn < datetime.fromisoformat(cooldown_map[symbol]): continue

            for interval in self.config.INTERVALS_TO_SCAN:
                market_zone = self._determine_market_zone(symbol, interval)
                for tactic_name, tactic_cfg in self.config.TACTICS_LAB.items():
                    optimal_zones = tactic_cfg.get("OPTIMAL_ZONE", [])
                    if not isinstance(optimal_zones, list): optimal_zones = [optimal_zones]
                    
                    if market_zone in optimal_zones:
                        indicators = self.indicator_results.get(symbol, {}).get(interval)
                        if not (indicators and indicators.get('price', 0) > 0): continue
                        
                        decision = get_advisor_decision(symbol, interval, indicators, ADVISOR_BASE_CONFIG, weights_override=tactic_cfg.get("WEIGHTS"))
                        adjusted_score = decision.get("final_score", 0.0) * self._get_mtf_adjustment_coefficient(symbol, interval)
                        
                        potential_opportunities.append({
                            "decision": decision, "tactic_name": tactic_name, 
                            "tactic_cfg": tactic_cfg, "score": adjusted_score, 
                            "symbol": symbol, "interval": interval, "zone": market_zone
                        })
        
        self._log_message("---[🔍 Quét Cơ Hội Mới 🔍]---")
        if not potential_opportunities:
            self._log_message("  => Không tìm thấy cơ hội tiềm năng nào.")
            return

        best_opportunity = sorted(potential_opportunities, key=lambda x: x['score'], reverse=True)[0]
        entry_score_threshold = best_opportunity['tactic_cfg'].get("ENTRY_SCORE", 9.9)
        self._log_message(f"  🏆 Cơ hội tốt nhất: {best_opportunity['symbol']}-{best_opportunity['interval']} | Tactic: {best_opportunity['tactic_name']} | Điểm: {best_opportunity['score']:.2f} (Ngưỡng: {entry_score_threshold})")

        if best_opportunity['score'] >= entry_score_threshold:
            self._log_message("    => ✅ Đạt ngưỡng! Mô phỏng vào lệnh...")
            self._execute_trade_opening(best_opportunity, equity)
        else:
            self._log_message("    => 📉 Không đạt ngưỡng. Bỏ qua.")
            
    def _execute_trade_opening(self, opportunity: Dict, equity: float):
        """Thực thi việc mở một lệnh mới dựa trên cơ hội đã được chọn."""
        decision_data, tactic_cfg = opportunity['decision'], opportunity['tactic_cfg']
        symbol, interval, zone = opportunity['symbol'], opportunity['interval'], opportunity['zone']
        full_indicators = decision_data.get('full_indicators', {})
        entry_price = full_indicators.get('price')
        if not entry_price or entry_price <= 0: return

        # Xác định SL/TP
        risk_dist_from_atr = full_indicators.get('atr', 0) * tactic_cfg.get("ATR_SL_MULTIPLIER", 2.0)
        max_sl_pct = self.config.RISK_RULES["MAX_SL_PERCENT_BY_TIMEFRAME"].get(interval, 0.1)
        final_risk_dist = min(risk_dist_from_atr, entry_price * max_sl_pct)
        if final_risk_dist <= 0: return

        sl_p = entry_price - final_risk_dist
        tp_p = entry_price + (final_risk_dist * tactic_cfg.get("RR", 2.0))
        max_tp_pct_cfg = self.config.RISK_RULES["MAX_TP_PERCENT_BY_TIMEFRAME"].get(interval)
        if max_tp_pct_cfg is not None and tp_p > entry_price * (1 + max_tp_pct_cfg):
            tp_p = entry_price * (1 + max_tp_pct_cfg)
        if tp_p <= entry_price or sl_p >= entry_price or sl_p <= 0: return

        # Quản lý vốn
        capital_pct = self.config.ZONE_BASED_POLICIES.get(zone, {}).get("CAPITAL_PCT", 0.03)
        invested_amount = equity * capital_pct
        current_exposure_usd = sum(t.get('total_invested_usd', 0.0) for t in self.state.get("active_trades", []))
        if invested_amount > self.state['cash'] or (current_exposure_usd + invested_amount) > (equity * self.config.CAPITAL_MANAGEMENT["MAX_TOTAL_EXPOSURE_PCT"]) or invested_amount < 10:
            self._log_message(f"    => ❌ Không đủ vốn hoặc vượt ngưỡng rủi ro. Bỏ qua.")
            return

        # Tạo lệnh mới
        new_trade = {
            "trade_id": str(uuid.uuid4()), "symbol": symbol, "interval": interval, "status": "ACTIVE",
            "opened_by_tactic": opportunity['tactic_name'], "trade_type": "LONG", "entry_price": entry_price,
            "quantity": invested_amount / entry_price, "tp": tp_p, "sl": sl_p, "initial_sl": sl_p,
            "initial_entry": {"price": entry_price, "invested_usd": invested_amount},
            "total_invested_usd": invested_amount, "entry_time": datetime.now(self.config.VIETNAM_TZ).isoformat(), 
            "entry_score": opportunity['score'], "entry_zone": zone, "last_zone": zone, "dca_entries": [], 
            "realized_pnl_usd": 0.0, "last_score": opportunity['score'], "peak_pnl_percent": 0.0, 
            "tp1_hit": False, "is_in_warning_zone": False, "partial_closed_by_score": False, "profit_taken": False
        }
        self.state['cash'] -= invested_amount
        self.state['active_trades'].append(new_trade)
        self.session_events.append(f"🔥 {symbol}-{interval} ({opportunity['tactic_name']}): Vốn ${new_trade['total_invested_usd']:,.2f}")

    # --- 4. Reporting & Summarizing ---
    def _calculate_total_equity(self, realtime_prices: Optional[Dict[str, float]] = None) -> float:
        """Tính toán tổng tài sản hiện tại (tiền mặt + giá trị các lệnh mở)."""
        cash = self.state.get('cash', 0)
        value_of_open_positions = 0
        for t in self.state.get('active_trades', []):
            price_to_use = realtime_prices.get(t['symbol']) if realtime_prices else self.indicator_results.get(t['symbol'], {}).get(t['interval'], {}).get('price', t['entry_price'])
            if price_to_use:
                pnl_usd, _ = self._get_current_pnl(t, current_price=price_to_use)
                value_of_open_positions += t.get('total_invested_usd', 0.0) + pnl_usd
            else: # Fallback if price is not available
                value_of_open_positions += t.get('total_invested_usd', 0.0)
        return cash + value_of_open_positions

    def _build_report_text(self, realtime_prices: Dict[str, float], report_type: str) -> str:
        """Xây dựng nội dung báo cáo để gửi đi."""
        now_vn_str = datetime.now(self.config.VIETNAM_TZ).strftime('%H:%M %d-%m-%Y')
        title = f"📊 **BÁO CÁO TỔNG KẾT (PAPER)** - `{now_vn_str}`" if report_type == "daily" else f"💡 **CẬP NHẬT ĐỘNG (PAPER)** - `{now_vn_str}`"
        lines = [title, ""]
        
        equity = self._calculate_total_equity(realtime_prices)
        
        # Header
        initial_capital = self.state.get('initial_capital', self.config.INITIAL_CAPITAL)
        pnl_since_start = equity - initial_capital
        pnl_percent = (pnl_since_start / initial_capital) * 100 if initial_capital > 0 else 0
        pnl_icon = "🟢" if pnl_since_start >= 0 else "🔴"
        lines.append(f"💰 Vốn BĐ: **${initial_capital:,.2f}** | 💵 Tiền mặt: **${self.state.get('cash', 0):,.2f}**")
        lines.append(f"📊 Tổng TS: **${equity:,.2f}** | 📈 PnL Tổng: {pnl_icon} **${pnl_since_start:,.2f} ({pnl_percent:+.2f}%)**")

        # PnL Summary
        df_history = pd.DataFrame(self.state.get('trade_history', []))
        total_trades = len(df_history)
        win_rate_str = "N/A"
        if total_trades > 0:
            winning_trades = len(df_history[df_history['pnl_usd'] > 0])
            win_rate_str = f"{winning_trades / total_trades * 100:.2f}% ({winning_trades}/{total_trades})"
        total_pnl_closed = df_history['pnl_usd'].sum() if total_trades > 0 else 0.0
        realized_partial_pnl = sum(t.get('realized_pnl_usd', 0.0) for t in self.state.get('active_trades', []))
        unrealized_pnl = sum(self._get_current_pnl(t, current_price=realtime_prices.get(t['symbol']))[0] for t in self.state.get('active_trades', []))
        lines.append(f"\n🏆 Win Rate: **{win_rate_str}** | ✅ PnL Đóng: **${total_pnl_closed:,.2f}** | 💎 PnL TP1: **${realized_partial_pnl:,.2f}** | 🌊 PnL Mở: **{'+' if unrealized_pnl >= 0 else ''}${unrealized_pnl:,.2f}**")

        # Active Trades
        active_trades = self.state.get('active_trades', [])
        lines.append(f"\n--- **Vị thế đang mở ({len(active_trades)})** ---")
        if not active_trades:
            lines.append("  (Không có vị thế nào)")
        else:
            for trade in sorted(active_trades, key=lambda x: x['entry_time']):
                current_price = realtime_prices.get(trade["symbol"])
                if current_price:
                    lines.append(self._build_trade_details_for_report(trade, current_price))
        
        lines.append("\n====================================")
        return "\n".join(lines)

    def _build_trade_details_for_report(self, trade: Dict, realtime_price: float) -> str:
        """Tạo chuỗi chi tiết cho một lệnh đang mở trong báo cáo."""
        pnl_usd, pnl_pct = self._get_current_pnl(trade, current_price=realtime_price)
        icon = "🟢" if pnl_usd >= 0 else "🔴"
        holding_h = (datetime.now(self.config.VIETNAM_TZ) - datetime.fromisoformat(trade['entry_time'])).total_seconds() / 3600
        dca_info = f" (DCA:{len(trade.get('dca_entries',[]))})" if trade.get('dca_entries') else ""
        tsl_info = f" TSL:{trade['sl']:.4f}" if "Trailing_SL_Active" in trade.get('tactic_used', []) else ""
        tp1_info = " TP1✅" if trade.get('tp1_hit', False) or trade.get('profit_taken', False) else ""
        entry_score, last_score = trade.get('entry_score', 0.0), trade.get('last_score', 0.0)
        score_display = f"{entry_score:,.1f}→{last_score:,.1f}" + ("📉" if last_score < entry_score else "📈" if last_score > entry_score else "")
        zone_display = f"{trade.get('entry_zone', 'N/A')}→{trade.get('last_zone', 'N/A')}" if trade.get('last_zone') != trade.get('entry_zone') else trade.get('entry_zone', 'N/A')
        tactic_info = f"({trade.get('opened_by_tactic')} | {score_display} | {zone_display})"
        invested_usd, current_value = trade.get('total_invested_usd', 0.0), trade.get('total_invested_usd', 0.0) + pnl_usd
        
        details1 = f"  {icon} **{trade['symbol']}-{trade['interval']}** {tactic_info} PnL: **${pnl_usd:,.2f} ({pnl_pct:+.2f}%)**"
        details2 = f"  Giữ:{holding_h:.1f}h{dca_info}{tp1_info}"
        details3 = f"  Vốn:${invested_usd:,.2f} -> **${current_value:,.2f}** | Entry:{trade['entry_price']:.4f} Cur:{realtime_price:.4f} TP:{trade['tp']:.4f} SL:{trade['sl']:.4f}{tsl_info}"
        return f"{details1}\n   {details2}\n   {details3}"

    def _should_send_report(self, equity: float) -> Optional[str]:
        """Quyết định xem có nên gửi báo cáo hay không và loại báo cáo nào."""
        now_vn = datetime.now(self.config.VIETNAM_TZ)
        
        # Daily Summary Report
        last_summary_str = self.state.get('last_summary_sent_time')
        last_summary_dt = datetime.fromisoformat(last_summary_str).astimezone(self.config.VIETNAM_TZ) if last_summary_str else None
        for time_str in self.config.GENERAL.get("DAILY_SUMMARY_TIMES", []):
            hour, minute = map(int, time_str.split(':'))
            scheduled_dt_today = now_vn.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if now_vn >= scheduled_dt_today and (last_summary_dt is None or last_summary_dt < scheduled_dt_today):
                return "daily"

        # Dynamic Update Report
        dyn_cfg = self.config.DYNAMIC_ALERT
        if not dyn_cfg.get("ENABLED", False): return None
        
        last_alert = self.state.get('last_dynamic_alert', {})
        if not last_alert.get('timestamp'):
            return "dynamic" if self.state.get('active_trades') else None

        last_alert_dt = datetime.fromisoformat(last_alert.get("timestamp")).astimezone(self.config.VIETNAM_TZ)
        hours_since = (now_vn - last_alert_dt).total_seconds() / 3600
        if hours_since >= dyn_cfg["FORCE_UPDATE_HOURS"]: return "dynamic"
        if hours_since < dyn_cfg["COOLDOWN_HOURS"]: return None
        
        initial_capital = self.state.get('initial_capital', 1)
        if initial_capital <= 0: return None
        
        current_pnl_pct = ((equity - initial_capital) / initial_capital) * 100
        if abs(current_pnl_pct - last_alert.get('total_pnl_percent', 0.0)) >= dyn_cfg["PNL_CHANGE_THRESHOLD_PCT"]:
            return "dynamic"
            
        return None

    # --- 5. Main Execution Loop ---
    def _check_capital_adjustment(self):
        """Phát hiện và ghi nhận việc nạp/rút vốn mô phỏng."""
        if 'initial_capital' in self.state and self.state.get('cash') != self.state.get('initial_capital') and not self.state.get('active_trades'):
            diff = self.state.get('cash', 0) - self.state.get('initial_capital', 0)
            self._log_message(f"💵 (Sim) Phát hiện thay đổi vốn: ${diff:,.2f}. Cập nhật vốn ban đầu.")
            self.state['initial_capital'] = self.state.get('cash')

    def run(self):
        """Vòng lặp chính thực thi một phiên giao dịch."""
        try:
            self.session_events = []
            
            # Tính toán tài sản ban đầu cho phiên
            equity = self._calculate_total_equity()

            # Thực hiện các tác vụ chính
            self._run_heavy_tasks(equity)
            self._manage_open_positions()
            self._handle_stale_trades()
            self._handle_dca_opportunities(equity)

            # Ghi log các sự kiện trong phiên
            if self.session_events:
                self._log_message("---[🔔 Cập nhật sự kiện trong phiên 🔔]---")
                for msg in self.session_events:
                    self._log_message(f"  {msg}")
            
            # Lấy giá realtime để báo cáo chính xác nhất
            active_symbols = list(set([t['symbol'] for t in self.state.get('active_trades', [])]))
            realtime_prices = {sym: price for sym in active_symbols if (price := self._get_realtime_price(sym)) is not None}

            # Tính toán tài sản cuối cùng và gửi báo cáo nếu cần
            final_equity = self._calculate_total_equity(realtime_prices=realtime_prices)
            report_type_to_send = self._should_send_report(final_equity)
            if report_type_to_send:
                self._log_message(f"📬 Gửi báo cáo loại: {report_type_to_send.upper()}")
                report_content = self._build_report_text(realtime_prices, report_type_to_send)
                self._send_discord_message(report_content)
                if report_type_to_send == "daily":
                    self.state['last_summary_sent_time'] = datetime.now(self.config.VIETNAM_TZ).isoformat()
                
                # Cập nhật trạng thái cho lần báo cáo động tiếp theo
                initial_capital = self.state.get('initial_capital', 1)
                current_pnl_pct = ((final_equity - initial_capital) / initial_capital) * 100 if initial_capital > 0 else 0
                self.state['last_dynamic_alert'] = {"timestamp": datetime.now(self.config.VIETNAM_TZ).isoformat(), "total_pnl_percent": current_pnl_pct}

            # Dọn dẹp và lưu trạng thái
            if 'last_critical_error' in self.state: self.state['last_critical_error'] = {}
            self._save_state()
            self._log_message("✅ Phiên làm việc hoàn tất.\n" + "="*50)

        except Exception as e:
            self._handle_critical_error(e)

    def _handle_critical_error(self, e: Exception):
        """Xử lý các lỗi nghiêm trọng, bất ngờ."""
        error_msg, now_ts = str(e), time.time()
        last_error = self.state.get('last_critical_error', {})
        cooldown_seconds = self.config.GENERAL.get("CRITICAL_ERROR_ALERT_COOLDOWN_MINUTES", 30) * 60
        
        should_alert_discord = True
        if last_error.get('message') == error_msg and (now_ts - last_error.get('timestamp', 0)) < cooldown_seconds:
            should_alert_discord = False
            
        self._log_error(f"LỖI TOÀN CỤC NGOÀI DỰ KIẾN", error_details=traceback.format_exc(), send_to_discord=should_alert_discord)
        self.state['last_critical_error'] = {'message': error_msg, 'timestamp': now_ts}
        self._save_state()

    @staticmethod
    def _get_realtime_price(symbol: str) -> Optional[float]:
        """Lấy giá realtime từ Binance API (hàm tĩnh để không phụ thuộc state)."""
        if symbol == "USDT": return 1.0
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
        try:
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            return float(response.json()['price'])
        except requests.exceptions.RequestException:
            # Không log lỗi ở đây để tránh spam khi API có vấn đề tạm thời
            return None

if __name__ == "__main__":
    trader = PaperTrader()
    trader.run()
