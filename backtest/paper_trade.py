# paper_trade.py
# -*- coding: utf-8 -*-
"""
Paper Trade - The 4-Zone Strategy (Refactored)
Version: 8.7.0 - Logic & Reporting Overhaul
Date: 2025-08-05
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

try:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
    sys.path.append(str(PROJECT_ROOT))
    load_dotenv(dotenv_path=PROJECT_ROOT / '.env')
    from indicator import get_price_data, calculate_indicators
    from trade_advisor import get_advisor_decision, FULL_CONFIG as ADVISOR_BASE_CONFIG
except (ImportError, FileNotFoundError) as e:
    sys.exit(f"Lỗi khởi tạo: Không thể tải các module hoặc file .env. Chi tiết: {e}")

class Config:
    TRADING_MODE: Literal["paper"] = "paper"
    INITIAL_CAPITAL = 10000.0
    SYMBOLS_TO_SCAN = [s.strip() for s in os.getenv("SYMBOLS_TO_SCAN", "ETHUSDT,BTCUSDT").split(',')]
    ALL_TIME_FRAMES = ["1h", "4h", "1d"]
    VIETNAM_TZ = pytz.timezone('Asia/Ho_Chi_Minh')

    BASE_DIR = Path(__file__).resolve().parent
    PAPER_DATA_DIR = BASE_DIR / "paper_data"
    CACHE_DIR = PAPER_DATA_DIR / "indicator_cache"
    LOG_FILE = PAPER_DATA_DIR / "paper_trade_log.txt"
    ERROR_LOG_FILE = PAPER_DATA_DIR / "error_log.txt"
    STATE_FILE = PAPER_DATA_DIR / "paper_trade_state.json"
    TRADE_HISTORY_CSV_FILE = PAPER_DATA_DIR / "trade_history.csv"

    GENERAL_CONFIG = {
        "DATA_FETCH_LIMIT": 300,
        "DAILY_SUMMARY_TIMES": ["08:15", "20:15"],
        "TRADE_COOLDOWN_HOURS": 1.0,
        "CRITICAL_ERROR_ALERT_COOLDOWN_MINUTES": 30,
        "TOP_N_OPPORTUNITIES_TO_CHECK": 5,
    }
    
    MTF_ANALYSIS_CONFIG = {
        "ENABLED": True,
        "BONUS_COEFFICIENT": 1.10,
        "PENALTY_COEFFICIENT": 0.88,
        "SEVERE_PENALTY_COEFFICIENT": 0.78,
        "SIDEWAYS_PENALTY_COEFFICIENT": 0.92,
    }
    
    ACTIVE_TRADE_MANAGEMENT_CONFIG = {
        "EARLY_CLOSE_ABSOLUTE_THRESHOLD": 4.2,
        "EARLY_CLOSE_RELATIVE_DROP_PCT": 0.40,
        "PARTIAL_EARLY_CLOSE_PCT": 0.5,
        "PROFIT_PROTECTION": {
            "ENABLED": True,
            "MIN_PEAK_PNL_TRIGGER": 4.5,
            "PNL_DROP_TRIGGER_PCT": 3.0,
            "PARTIAL_CLOSE_PCT": 0.6,
        }
    }
    
    RISK_RULES_CONFIG = {
        "MAX_ACTIVE_TRADES": 15,
        "MAX_SL_PERCENT_BY_TIMEFRAME": {"1h": 0.07, "4h": 0.09, "1d": 0.12},
        "MAX_TP_PERCENT_BY_TIMEFRAME": {"1h": 0.21, "4h": 0.27, "1d": 0.36},
        "STALE_TRADE_RULES": {
            "1h": {"HOURS": 48, "PROGRESS_THRESHOLD_PCT": 20.0},
            "4h": {"HOURS": 72, "PROGRESS_THRESHOLD_PCT": 20.0},
            "1d": {"HOURS": 168, "PROGRESS_THRESHOLD_PCT": 15.0},
            "STAY_OF_EXECUTION_SCORE": 6.5
        }
    }

    CAPITAL_MANAGEMENT_CONFIG = {
        "MAX_TOTAL_EXPOSURE_PCT": 0.85
    }

    DCA_CONFIG = {
        "ENABLED": True,
        "MAX_DCA_ENTRIES": 2,
        "TRIGGER_DROP_PCT": -4.5,
        "SCORE_MIN_THRESHOLD": 6.8,
        "CAPITAL_MULTIPLIER": 1.0,
        "DCA_COOLDOWN_HOURS": 12
    }

    ALERT_CONFIG = {
        "DISCORD_WEBHOOK_URL": os.getenv("DISCORD_PAPER_WEBHOOK"),
        "DISCORD_CHUNK_DELAY_SECONDS": 2
    }

    LEADING_ZONE, COINCIDENT_ZONE, LAGGING_ZONE, NOISE_ZONE = "LEADING", "COINCIDENT", "LAGGING", "NOISE"
    ZONES = [LEADING_ZONE, COINCIDENT_ZONE, LAGGING_ZONE, NOISE_ZONE]
    
    ZONE_BASED_POLICIES = {
        LEADING_ZONE:   {"CAPITAL_PCT": 0.045},
        COINCIDENT_ZONE:{"CAPITAL_PCT": 0.065},
        LAGGING_ZONE:   {"CAPITAL_PCT": 0.055},
        NOISE_ZONE:     {"CAPITAL_PCT": 0.035}
    }

    TACTICS_LAB = {
        "Breakout_Hunter": {
            "OPTIMAL_ZONE": [LEADING_ZONE, COINCIDENT_ZONE], "NOTES": "Săn điểm phá vỡ.",
            "WEIGHTS": {'tech': 0.6, 'context': 0.1, 'ai': 0.3}, "ENTRY_SCORE": 7.0,
            "RR": 2.8, "ATR_SL_MULTIPLIER": 2.0, "USE_TRAILING_SL": True,
            "TRAIL_ACTIVATION_RR": 1.5, "TRAIL_DISTANCE_RR": 1.0, "ENABLE_PARTIAL_TP": False,
            "TP1_RR_RATIO": None, "TP1_PROFIT_PCT": None
        },
        "Dip_Hunter": {
            "OPTIMAL_ZONE": [LEADING_ZONE, COINCIDENT_ZONE], "NOTES": "Bắt đáy/sóng hồi an toàn.",
            "WEIGHTS": {'tech': 0.5, 'context': 0.2, 'ai': 0.3}, "ENTRY_SCORE": 6.8,
            "RR": 2.0, "ATR_SL_MULTIPLIER": 2.0, "USE_TRAILING_SL": False,
            "TRAIL_ACTIVATION_RR": None, "ENABLE_PARTIAL_TP": True,
            "TP1_RR_RATIO": 0.8, "TP1_PROFIT_PCT": 0.6
        },
        "AI_Aggressor": {
            "OPTIMAL_ZONE": COINCIDENT_ZONE, "NOTES": "Tấn công theo tín hiệu AI mạnh.",
            "WEIGHTS": {'tech': 0.3, 'context': 0.1, 'ai': 0.6}, "ENTRY_SCORE": 6.6,
            "RR": 2.5, "ATR_SL_MULTIPLIER": 2.5, "USE_TRAILING_SL": True,
            "TRAIL_ACTIVATION_RR": 1.2, "TRAIL_DISTANCE_RR": 1.0, "ENABLE_PARTIAL_TP": True,
            "TP1_RR_RATIO": 1.2, "TP1_PROFIT_PCT": 0.4
        },
        "Balanced_Trader": {
            "OPTIMAL_ZONE": [LAGGING_ZONE, COINCIDENT_ZONE], "NOTES": "Chiến binh đi theo trend.",
            "WEIGHTS": {'tech': 0.4, 'context': 0.2, 'ai': 0.4}, "ENTRY_SCORE": 6.3,
            "RR": 2.8, "ATR_SL_MULTIPLIER": 3.0, "USE_TRAILING_SL": True,
            "TRAIL_ACTIVATION_RR": 1.5, "TRAIL_DISTANCE_RR": 1.2, "ENABLE_PARTIAL_TP": True,
            "TP1_RR_RATIO": 1.4, "TP1_PROFIT_PCT": 0.4
        },
        "Cautious_Observer": {
            "OPTIMAL_ZONE": NOISE_ZONE, "NOTES": "Bắn tỉa trong vùng nhiễu.",
            "WEIGHTS": {'tech': 0.6, 'context': 0.2, 'ai': 0.2}, "ENTRY_SCORE": 8.0,
            "RR": 1.8, "ATR_SL_MULTIPLIER": 1.5, "USE_TRAILING_SL": True,
            "TRAIL_ACTIVATION_RR": 0.8, "TRAIL_DISTANCE_RR": 0.6, "ENABLE_PARTIAL_TP": True,
            "TP1_RR_RATIO": 0.8, "TP1_PROFIT_PCT": 0.7
        }
    }

class PaperTrader:
    def __init__(self):
        self.config = Config()
        self._setup_directories()
        self.state: Dict[str, Any] = self._load_state()
        self.indicator_results: Dict[str, Any] = {}
        self.price_dataframes: Dict[str, Any] = {}
        self.session_events: List[str] = []
        self._log_message("="*50)
        self._log_message(f"🚀 Khởi động Paper Trading Bot (v{self.state.get('version', '8.7.0')})...")

    def _setup_directories(self):
        self.config.PAPER_DATA_DIR.mkdir(exist_ok=True)
        self.config.CACHE_DIR.mkdir(exist_ok=True)

    def _log_message(self, message: str):
        timestamp = datetime.now(self.config.VIETNAM_TZ).strftime('%Y-%m-%d %H:%M:%S')
        log_entry = f"[{timestamp}] (PaperTrade) {message}"
        print(log_entry)
        with open(self.config.LOG_FILE, "a", encoding="utf-8") as f:
            f.write(log_entry + "\n")

    def _log_error(self, message: str, error_details: str = "", send_to_discord: bool = False):
        timestamp = datetime.now(self.config.VIETNAM_TZ).strftime('%Y-%m-%d %H:%M:%S')
        log_entry = f"[{timestamp}] (PaperTrade-ERROR) {message}\n"
        if error_details:
            log_entry += f"--- TRACEBACK ---\n{error_details}\n------------------\n"
        with open(self.config.ERROR_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(log_entry)
        self._log_message(f"!!!!!! ❌ LỖI: {message}. Chi tiết trong error.log ❌ !!!!!!")
        if send_to_discord:
            discord_message = f"🔥🔥🔥 BOT MÔ PHỎNG GẶP LỖI 🔥🔥🔥\n**{message}**\n```python\n{error_details or 'N/A'}\n```"
            self._send_discord_message(discord_message)

    def _load_state(self) -> Dict[str, Any]:
        if not self.config.STATE_FILE.exists():
            self._log_message("Không tìm thấy file state, khởi tạo mới...")
            return {
                "version": "8.7.0", "cash": self.config.INITIAL_CAPITAL,
                "initial_capital": self.config.INITIAL_CAPITAL, "active_trades": [],
                "trade_history": [], "cooldown_until": {},
                "last_dynamic_alert": {}, "last_summary_sent_time": None
            }
        try:
            with open(self.config.STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            self._log_error(f"File JSON hỏng: {self.config.STATE_FILE}. Không thể tiếp tục.", send_to_discord=True)
            sys.exit(1)

    def _save_state(self):
        temp_path = self.config.STATE_FILE.with_suffix(".json.tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(self.state, f, indent=4, ensure_ascii=False)
        os.replace(temp_path, self.config.STATE_FILE)

    def _send_discord_message(self, full_content: str):
        webhook_url = self.config.ALERT_CONFIG["DISCORD_WEBHOOK_URL"]
        if not webhook_url: return
        max_len, chunks, current_chunk = 1900, [], ""
        for line in full_content.split('\n'):
            if len(current_chunk) + len(line) + 1 > max_len:
                if current_chunk: chunks.append(current_chunk)
                current_chunk = line
            else: current_chunk += ("\n" + line) if current_chunk else line
        if current_chunk: chunks.append(current_chunk)
        for i, chunk in enumerate(chunks):
            content_to_send = f"*(Phần {i+1}/{len(chunks)})*\n{chunk}" if len(chunks) > 1 else chunk
            try:
                requests.post(webhook_url, json={"content": content_to_send}, timeout=15).raise_for_status()
                if i < len(chunks) - 1: time.sleep(self.config.ALERT_CONFIG["DISCORD_CHUNK_DELAY_SECONDS"])
            except requests.exceptions.RequestException as e:
                self._log_error(f"Lỗi gửi chunk Discord {i+1}/{len(chunks)}: {e}")
                break
    
    @staticmethod
    def _get_current_pnl(trade: Dict, current_price: Optional[float]) -> Tuple[float, float]:
        if not (trade and trade.get('entry_price', 0) > 0 and current_price and current_price > 0):
            return 0.0, 0.0
        pnl_percent = ((current_price - trade['entry_price']) / trade['entry_price']) * 100
        pnl_usd = trade.get('total_invested_usd', 0.0) * (pnl_percent / 100)
        return pnl_usd, pnl_percent

    def _export_trade_history_to_csv(self, closed_trades: List[Dict]):
        if not closed_trades: return
        try:
            df = pd.DataFrame(closed_trades)
            cols = ["trade_id", "symbol", "interval", "status", "opened_by_tactic", "tactic_used", "trade_type", "entry_price", "exit_price", "tp", "sl", "total_invested_usd", "pnl_usd", "pnl_percent", "entry_time", "exit_time", "holding_duration_hours", "entry_score", "last_score", "entry_zone", "last_zone", "dca_entries", "realized_pnl_usd"]
            for col in cols:
                if col not in df.columns: df[col] = None
            df['entry_time'] = pd.to_datetime(df['entry_time']).dt.tz_convert(self.config.VIETNAM_TZ)
            df['exit_time'] = pd.to_datetime(df['exit_time']).dt.tz_convert(self.config.VIETNAM_TZ)
            df['holding_duration_hours'] = round((df['exit_time'] - df['entry_time']).dt.total_seconds() / 3600, 2)
            df = df[cols]
            file_exists = self.config.TRADE_HISTORY_CSV_FILE.exists()
            df.to_csv(self.config.TRADE_HISTORY_CSV_FILE, mode='a', header=not file_exists, index=False, encoding="utf-8")
        except Exception as e:
            self._log_error(f"Lỗi xuất lịch sử giao dịch ra CSV", error_details=traceback.format_exc())

    @staticmethod
    def _get_realtime_price(symbol: str) -> Optional[float]:
        if symbol == "USDT": return 1.0
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
        try:
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            return float(response.json()['price'])
        except requests.exceptions.RequestException:
            return None

    def _run_heavy_tasks(self, equity: float):
        self._log_message("---[🔄 Bắt đầu chu trình tác vụ nặng 🔄]---")
        self.indicator_results.clear(); self.price_dataframes.clear()
        symbols_to_load = list(set(self.config.SYMBOLS_TO_SCAN + [t['symbol'] for t in self.state.get('active_trades', [])] + ["BTCUSDT"]))
        for symbol in symbols_to_load:
            self.indicator_results[symbol], self.price_dataframes[symbol] = {}, {}
            for interval in self.config.ALL_TIME_FRAMES:
                df = get_price_data(symbol, interval, limit=self.config.GENERAL_CONFIG["DATA_FETCH_LIMIT"])
                if df is not None and not df.empty:
                    self.indicator_results[symbol][interval] = calculate_indicators(df.copy(), symbol, interval)
                    self.price_dataframes[symbol][interval] = df
        for trade in self.state.get("active_trades", []):
            indicators = self.indicator_results.get(trade['symbol'], {}).get(trade['interval'])
            if indicators:
                tactic_cfg = self.config.TACTICS_LAB.get(trade['opened_by_tactic'], {})
                decision = get_advisor_decision(trade['symbol'], trade['interval'], indicators, ADVISOR_BASE_CONFIG, weights_override=tactic_cfg.get("WEIGHTS"))
                trade['last_score'] = decision.get("final_score", 0.0)
                trade['last_zone'] = self._determine_market_zone(trade['symbol'], trade['interval'])
        self._find_and_open_new_trades(equity)

    def _close_trade_simulated(self, trade: Dict, reason: str, close_price: float, close_pct: float = 1.0) -> bool:
        invested_to_close = trade['total_invested_usd'] * close_pct
        pnl_on_closed_part = ((close_price - trade['entry_price']) / trade['entry_price']) * invested_to_close if trade['entry_price'] > 0 else 0
        self.state['cash'] += invested_to_close + pnl_on_closed_part
        trade.setdefault('tactic_used', []).append(f"Close_{reason}")
        if close_pct >= 0.999:
            trade.update({
                'status': f'Closed ({reason})', 'exit_price': close_price,
                'exit_time': datetime.now(self.config.VIETNAM_TZ).isoformat(),
                'pnl_usd': trade.get('realized_pnl_usd', 0.0) + pnl_on_closed_part,
                'pnl_percent': ((close_price - trade['entry_price']) / trade['entry_price']) * 100 if trade['entry_price'] > 0 else 0
            })
            self.state['active_trades'] = [t for t in self.state['active_trades'] if t['trade_id'] != trade['trade_id']]
            self.state['trade_history'].append(trade)
            self.state['trade_history'] = self.state['trade_history'][-100:]
            cooldown_map = self.state.setdefault('cooldown_until', {})
            cooldown_map[trade['symbol']] = (datetime.now(self.config.VIETNAM_TZ) + timedelta(hours=self.config.GENERAL_CONFIG["TRADE_COOLDOWN_HOURS"])).isoformat()
            self._export_trade_history_to_csv([trade])
            icon = '✅' if trade['pnl_usd'] >= 0 else '❌'
            self.session_events.append(f"🎬 {icon} {trade['symbol']} (Đóng toàn bộ - {reason}): PnL ${trade['pnl_usd']:,.2f}")
        else:
            trade['realized_pnl_usd'] = trade.get('realized_pnl_usd', 0.0) + pnl_on_closed_part
            trade['total_invested_usd'] *= (1 - close_pct)
            self.session_events.append(f"💰 {trade['symbol']} (Đóng {close_pct*100:.0f}% - {reason}): PnL ${pnl_on_closed_part:,.2f}")
        return True

    def _manage_open_positions(self, realtime_prices: Dict[str, float]):
        for trade in self.state.get("active_trades", [])[:]:
            current_price = realtime_prices.get(trade['symbol'])
            if not current_price: continue
            
            pnl_usd, pnl_percent = self._get_current_pnl(trade, current_price)
            trade['peak_pnl_percent'] = max(trade.get('peak_pnl_percent', 0.0), pnl_percent)
            
            tactic_cfg = self.config.TACTICS_LAB.get(trade.get('opened_by_tactic'), {})
            if current_price <= trade['sl']:
                if self._close_trade_simulated(trade, "SL", close_price=trade['sl']): continue
            if current_price >= trade['tp']:
                if self._close_trade_simulated(trade, "TP", close_price=trade['tp']): continue
            
            last_score, entry_score = trade.get('last_score', 5.0), trade.get('entry_score', 5.0)
            cfg_mgmt = self.config.ACTIVE_TRADE_MANAGEMENT_CONFIG
            if last_score < cfg_mgmt['EARLY_CLOSE_ABSOLUTE_THRESHOLD']:
                if self._close_trade_simulated(trade, f"EC_Abs_{last_score:.1f}", current_price): continue
            
            if not trade.get('partial_closed_by_score', False) and last_score < entry_score * (1 - cfg_mgmt.get('EARLY_CLOSE_RELATIVE_DROP_PCT', 0.4)):
                if self._close_trade_simulated(trade, f"EC_Rel_{last_score:.1f}", current_price, close_pct=cfg_mgmt.get("PARTIAL_EARLY_CLOSE_PCT", 0.5)):
                    trade['partial_closed_by_score'] = True
                    trade['sl'] = trade['entry_price'] # Move SL to Break-Even
                    continue

            if tactic_cfg.get("ENABLE_PARTIAL_TP", False) and not trade.get("tp1_hit", False):
                initial_risk_dist = abs(trade['initial_entry']['price'] - trade['initial_sl'])
                if initial_risk_dist > 0:
                    pnl_ratio = (current_price - trade['entry_price']) / initial_risk_dist
                    if pnl_ratio >= tactic_cfg.get("TP1_RR_RATIO", 1.0):
                        if self._close_trade_simulated(trade, f"TP1_{tactic_cfg.get('TP1_RR_RATIO', 1.0):.1f}R", current_price, close_pct=tactic_cfg.get("TP1_PROFIT_PCT", 0.5)):
                            trade['tp1_hit'] = True
                            trade['sl'] = trade['entry_price'] # Move SL to Break-Even
                            continue
            
            pp_config = cfg_mgmt.get("PROFIT_PROTECTION", {})
            if pp_config.get("ENABLED", False) and not trade.get('profit_taken', False) and trade['peak_pnl_percent'] >= pp_config.get("MIN_PEAK_PNL_TRIGGER"):
                if (trade['peak_pnl_percent'] - pnl_percent) >= pp_config.get("PNL_DROP_TRIGGER_PCT"):
                    if self._close_trade_simulated(trade, "Protect_Profit", current_price, close_pct=pp_config.get("PARTIAL_CLOSE_PCT")):
                        trade['profit_taken'] = True
                        trade['sl'] = trade['entry_price']
                        continue
            
            if tactic_cfg.get("USE_TRAILING_SL", False):
                initial_risk_dist = abs(trade['initial_entry']['price'] - trade['initial_sl'])
                if initial_risk_dist > 0:
                    if (current_price - trade['entry_price']) / initial_risk_dist >= tactic_cfg.get("TRAIL_ACTIVATION_RR", float('inf')):
                        new_sl = current_price - (initial_risk_dist * tactic_cfg.get("TRAIL_DISTANCE_RR", 0.8))
                        if new_sl > trade['sl']:
                            self.session_events.append(f"⚙️ TSL {trade['symbol']}: SL mới {new_sl:.4f} (cũ {trade['sl']:.4f})")
                            trade['sl'] = new_sl
                            if "Trailing_SL_Active" not in trade.get('tactic_used', []):
                                trade.setdefault('tactic_used', []).append("Trailing_SL_Active")

    def _handle_stale_trades(self, realtime_prices: Dict[str, float]):
        now_aware = datetime.now(self.config.VIETNAM_TZ)
        rules_cfg = self.config.RISK_RULES_CONFIG["STALE_TRADE_RULES"]
        for trade in self.state.get("active_trades", [])[:]:
            rules = rules_cfg.get(trade.get("interval"))
            if not rules: continue
            holding_hours = (now_aware - datetime.fromisoformat(trade['entry_time'])).total_seconds() / 3600
            if holding_hours > rules["HOURS"]:
                current_price = realtime_prices.get(trade['symbol'])
                if not current_price: continue
                _, pnl_pct = self._get_current_pnl(trade, current_price)
                if pnl_pct < rules["PROGRESS_THRESHOLD_PCT"] and trade.get('last_score', 5.0) < rules_cfg["STAY_OF_EXECUTION_SCORE"]:
                    self._close_trade_simulated(trade, "Stale", current_price)

    def _handle_dca_opportunities(self, equity: float, realtime_prices: Dict[str, float]):
        dca_cfg = self.config.DCA_CONFIG
        if not dca_cfg["ENABLED"]: return
        current_exposure_usd = sum(t.get('total_invested_usd', 0.0) for t in self.state.get("active_trades", []))
        now = datetime.now(self.config.VIETNAM_TZ)
        for trade in self.state.get("active_trades", [])[:]:
            if len(trade.get("dca_entries", [])) >= dca_cfg["MAX_DCA_ENTRIES"]: continue
            if trade.get('last_dca_time') and (now - datetime.fromisoformat(trade.get('last_dca_time'))).total_seconds() / 3600 < dca_cfg['DCA_COOLDOWN_HOURS']: continue
            current_price = realtime_prices.get(trade["symbol"])
            if not current_price or current_price <= 0: continue
            
            last_entry_price = trade['dca_entries'][-1]['price'] if trade.get('dca_entries') else trade['initial_entry']['price']
            price_drop_pct = ((current_price - last_entry_price) / last_entry_price) * 100
            if price_drop_pct > dca_cfg["TRIGGER_DROP_PCT"]: continue

            indicators = self.indicator_results.get(trade["symbol"], {}).get(trade["interval"], {})
            if not indicators or get_advisor_decision(trade['symbol'], trade['interval'], indicators, ADVISOR_BASE_CONFIG).get("final_score", 0.0) < dca_cfg["SCORE_MIN_THRESHOLD"]: continue
            
            dca_investment = (trade['dca_entries'][-1]['invested_usd'] if trade.get('dca_entries') else trade['initial_entry']['invested_usd']) * dca_cfg["CAPITAL_MULTIPLIER"]
            if dca_investment <= 0 or dca_investment > self.state['cash'] or (current_exposure_usd + dca_investment) > (equity * self.config.CAPITAL_MANAGEMENT_CONFIG["MAX_TOTAL_EXPOSURE_PCT"]): continue
            
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
        indicators = self.indicator_results.get(symbol, {}).get(interval, {})
        if not indicators: return self.config.NOISE_ZONE
        scores = {zone: 0 for zone in self.config.ZONES}
        adx = indicators.get('adx', 20)
        if adx < 20: scores[self.config.NOISE_ZONE] += 3
        if adx > 25: scores[self.config.LAGGING_ZONE] += 2.5
        if indicators.get('trend', "sideways") == "uptrend": scores[self.config.LAGGING_ZONE] += 2
        df = self.price_dataframes.get(symbol, {}).get(interval)
        if df is not None:
             if 'bb_width' in df.columns and not df['bb_width'].isna().all() and indicators.get('bb_width',0) < df['bb_width'].iloc[-100:].quantile(0.20):
                scores[self.config.LEADING_ZONE] += 2.5
        if indicators.get('breakout_signal', "none") != "none": scores[self.config.COINCIDENT_ZONE] += 3
        return max(scores, key=scores.get) if scores and any(v > 0 for v in scores.values()) else self.config.NOISE_ZONE

    def _get_mtf_adjustment_coefficient(self, symbol: str, target_interval: str) -> float:
        cfg = self.config.MTF_ANALYSIS_CONFIG
        if not cfg["ENABLED"]: return 1.0
        trends = {tf: self.indicator_results.get(symbol, {}).get(tf, {}).get("trend", "sideways") for tf in self.config.ALL_TIME_FRAMES}
        fav, unfav = "uptrend", "downtrend"
        if target_interval == "1h":
            htf1, htf2 = trends.get("4h", "sideways"), trends.get("1d", "sideways")
            if htf1 == unfav and htf2 == unfav: return cfg["SEVERE_PENALTY_COEFFICIENT"]
            if htf1 == unfav or htf2 == unfav: return cfg["PENALTY_COEFFICIENT"]
            if htf1 == fav and htf2 == fav: return cfg["BONUS_COEFFICIENT"]
            return cfg["SIDEWAYS_PENALTY_COEFFICIENT"]
        elif target_interval == "4h":
            htf1 = trends.get("1d", "sideways")
            if htf1 == unfav: return cfg["PENALTY_COEFFICIENT"]
            if htf1 == fav: return cfg["BONUS_COEFFICIENT"]
            return cfg["SIDEWAYS_PENALTY_COEFFICIENT"]
        return 1.0

    def _find_and_open_new_trades(self, equity: float):
        if len(self.state.get("active_trades", [])) >= self.config.RISK_RULES_CONFIG["MAX_ACTIVE_TRADES"]: return
        potential_opportunities = []
        now_vn = datetime.now(self.config.VIETNAM_TZ)
        cooldown_map = self.state.get('cooldown_until', {})
        for symbol in self.config.SYMBOLS_TO_SCAN:
            if any(t['symbol'] == symbol for t in self.state.get("active_trades", [])): continue
            if symbol in cooldown_map and now_vn < datetime.fromisoformat(cooldown_map[symbol]): continue
            for interval in self.config.ALL_TIME_FRAMES:
                market_zone = self._determine_market_zone(symbol, interval)
                for tactic_name, tactic_cfg in self.config.TACTICS_LAB.items():
                    optimal_zones = tactic_cfg.get("OPTIMAL_ZONE", [])
                    if not isinstance(optimal_zones, list): optimal_zones = [optimal_zones]
                    if market_zone in optimal_zones:
                        indicators = self.indicator_results.get(symbol, {}).get(interval)
                        if not (indicators and indicators.get('price', 0) > 0): continue
                        decision = get_advisor_decision(symbol, interval, indicators, ADVISOR_BASE_CONFIG, weights_override=tactic_cfg.get("WEIGHTS"))
                        adjusted_score = decision.get("final_score", 0.0) * self._get_mtf_adjustment_coefficient(symbol, interval)
                        if adjusted_score >= tactic_cfg.get("ENTRY_SCORE", 9.9):
                            potential_opportunities.append({
                                "decision": decision, "tactic_name": tactic_name, "tactic_cfg": tactic_cfg, 
                                "score": adjusted_score, "symbol": symbol, "interval": interval, "zone": market_zone
                            })
        if not potential_opportunities: return
        best_opportunity = sorted(potential_opportunities, key=lambda x: x['score'], reverse=True)[0]
        self._log_message(f"🏆 Cơ hội tốt nhất: {best_opportunity['symbol']}-{best_opportunity['interval']} | Tactic: {best_opportunity['tactic_name']} | Điểm: {best_opportunity['score']:.2f}")
        self._execute_trade_opening(best_opportunity, equity)
            
    def _execute_trade_opening(self, opportunity: Dict, equity: float):
        decision_data, tactic_cfg = opportunity['decision'], opportunity['tactic_cfg']
        symbol, interval, zone = opportunity['symbol'], opportunity['interval'], opportunity['zone']
        full_indicators = decision_data.get('full_indicators', {})
        entry_price = full_indicators.get('price')
        if not entry_price or entry_price <= 0: return

        risk_dist_from_atr = full_indicators.get('atr', 0) * tactic_cfg.get("ATR_SL_MULTIPLIER", 2.0)
        max_sl_pct = self.config.RISK_RULES_CONFIG["MAX_SL_PERCENT_BY_TIMEFRAME"].get(interval, 0.1)
        final_risk_dist = min(risk_dist_from_atr, entry_price * max_sl_pct)
        if final_risk_dist <= 0: return
        
        sl_p = entry_price - final_risk_dist
        tp_p = entry_price + (final_risk_dist * tactic_cfg.get("RR", 2.0))
        max_tp_pct_cfg = self.config.RISK_RULES_CONFIG["MAX_TP_PERCENT_BY_TIMEFRAME"].get(interval)
        if max_tp_pct_cfg is not None and tp_p > entry_price * (1 + max_tp_pct_cfg):
            tp_p = entry_price * (1 + max_tp_pct_cfg)
        if tp_p <= entry_price or sl_p >= entry_price or sl_p <= 0: return

        capital_pct = self.config.ZONE_BASED_POLICIES.get(zone, {}).get("CAPITAL_PCT", 0.03)
        invested_amount = equity * capital_pct
        current_exposure_usd = sum(t.get('total_invested_usd', 0.0) for t in self.state.get("active_trades", []))
        if invested_amount > self.state['cash'] or (current_exposure_usd + invested_amount) > (equity * self.config.CAPITAL_MANAGEMENT_CONFIG["MAX_TOTAL_EXPOSURE_PCT"]) or invested_amount < 11:
            return

        new_trade = {
            "trade_id": str(uuid.uuid4()), "symbol": symbol, "interval": interval, "status": "ACTIVE",
            "opened_by_tactic": opportunity['tactic_name'], "trade_type": "LONG", "entry_price": entry_price,
            "quantity": invested_amount / entry_price, "tp": tp_p, "sl": sl_p, "initial_sl": sl_p,
            "initial_entry": {"price": entry_price, "invested_usd": invested_amount},
            "total_invested_usd": invested_amount, "entry_time": datetime.now(self.config.VIETNAM_TZ).isoformat(), "entry_score": opportunity['score'], 
            "entry_zone": zone, "last_zone": zone, "dca_entries": [], "realized_pnl_usd": 0.0, 
            "last_score": opportunity['score'], "peak_pnl_percent": 0.0, "tp1_hit": False, 
            "partial_closed_by_score": False, "profit_taken": False
        }
        self.state['cash'] -= invested_amount
        self.state['active_trades'].append(new_trade)
        self.session_events.append(f"🔥 {symbol}-{interval} ({opportunity['tactic_name']}): Vốn ${new_trade['total_invested_usd']:,.2f}")

    def _calculate_total_equity(self, realtime_prices: Dict[str, float]) -> Optional[float]:
        cash = self.state.get('cash', 0.0)
        value_of_open_positions = 0.0
        active_trades = self.state.get('active_trades', [])
        for t in active_trades:
            price = realtime_prices.get(t['symbol'])
            if price is None:
                self._log_message(f"⚠️ Thiếu giá của {t['symbol']} để tính equity. Bỏ qua báo cáo.")
                return None
            pnl_usd, _ = self._get_current_pnl(t, current_price=price)
            current_trade_value = t.get('total_invested_usd', 0.0) + pnl_usd
            value_of_open_positions += current_trade_value
        return cash + value_of_open_positions

    def _build_report_header(self, equity: float) -> str:
        initial_capital = self.state.get('initial_capital', self.config.INITIAL_CAPITAL)
        pnl_since_start = equity - initial_capital
        pnl_percent = (pnl_since_start / initial_capital) * 100 if initial_capital > 0 else 0
        pnl_icon = "🟢" if pnl_since_start >= 0 else "🔴"
        return (f"💰 Vốn BĐ: **${initial_capital:,.2f}** | 💵 Tiền mặt: **${self.state.get('cash', 0):,.2f}**\n"
                f"📊 Tổng TS: **${equity:,.2f}** | 📈 PnL Tổng: {pnl_icon} **${pnl_since_start:,.2f} ({pnl_percent:+.2f}%)**")

    def _build_pnl_summary_line(self, realtime_prices: Dict[str, float]) -> str:
        df_history = pd.DataFrame(self.state.get('trade_history', []))
        total_trades = len(df_history)
        win_rate_str = "N/A"
        if total_trades > 0:
            winning_trades = len(df_history[df_history['pnl_usd'] > 0])
            win_rate_str = f"{winning_trades / total_trades * 100:.2f}% ({winning_trades}/{total_trades})"
        total_pnl_closed = df_history['pnl_usd'].sum() if total_trades > 0 else 0.0
        realized_partial_pnl = sum(t.get('realized_pnl_usd', 0.0) for t in self.state.get('active_trades', []))
        unrealized_pnl = sum(self._get_current_pnl(t, current_price=realtime_prices.get(t['symbol'], 0))[0] for t in self.state.get('active_trades', []))
        return (f"🏆 Win Rate: **{win_rate_str}** | ✅ PnL Đóng: **${total_pnl_closed:,.2f}** | "
                f"💎 PnL TP1: **${realized_partial_pnl:,.2f}** | 🌊 PnL Mở: **{'+' if unrealized_pnl >= 0 else ''}${unrealized_pnl:,.2f}**")

    def _build_trade_details_for_report(self, trade: Dict, current_price: float) -> str: # <--- SỬA DUY NHẤT DÒNG NÀY (realtime_price -> current_price)
        pnl_usd, pnl_pct = self._get_current_pnl(trade, current_price=current_price) # <--- SỬA DÒNG NÀY
        icon = "🟢" if pnl_usd >= 0 else "🔴"
        holding_h = (datetime.now(self.config.VIETNAM_TZ) - datetime.fromisoformat(trade['entry_time'])).total_seconds() / 3600
        dca_info = f" (DCA:{len(trade.get('dca_entries',[]))})" if trade.get('dca_entries') else ""
        tsl_info = f" TSL:{trade['sl']:.4f}" if "Trailing_SL_Active" in trade.get('tactic_used', []) else ""
        tp1_info = " TP1✅" if trade.get('tp1_hit', False) or trade.get('profit_taken', False) else ""
        entry_score, last_score = trade.get('entry_score', 0.0), trade.get('last_score', 0.0)
        score_display = f"{entry_score:,.1f}→{last_score:,.1f}" + ("📉" if last_score < entry_score else "📈" if last_score > entry_score else "")
        entry_zone, last_zone = trade.get('entry_zone', 'N/A'), trade.get('last_zone', 'N/A')
        zone_display = f"{entry_zone}→{last_zone}" if last_zone != entry_zone else entry_zone
        tactic_info = f"({trade.get('opened_by_tactic')} | {score_display} | {zone_display})"
        invested_usd = trade.get('total_invested_usd', 0.0)
        current_value = invested_usd + pnl_usd
        return (f"  {icon} **{trade['symbol']}-{trade['interval']}** {tactic_info} PnL: **${pnl_usd:,.2f} ({pnl_pct:+.2f}%)**\n"
                f"    Vốn:${invested_usd:,.2f} -> **${current_value:,.2f}** | Entry:{trade['entry_price']:.4f} Cur:{current_price:.4f} TP:{trade['tp']:.4f} SL:{trade['sl']:.4f}{tsl_info} | Giữ: {holding_h:.1f}h")


    def _build_report_text(self, realtime_prices: Dict[str, float], equity: float) -> str:
        now_vn_str = datetime.now(self.config.VIETNAM_TZ).strftime('%H:%M %d-%m-%Y')
        lines = [f"📊 **BÁO CÁO MÔ PHỎNG** - `{now_vn_str}` 📊"]
        lines.append(self._build_report_header(equity))
        lines.append("\n" + self._build_pnl_summary_line(realtime_prices))
        active_trades = self.state.get('active_trades', [])
        lines.append(f"\n--- **Vị thế đang mở ({len(active_trades)})** ---")
        if not active_trades: lines.append("  (Không có vị thế nào)")
        else:
            for trade in sorted(active_trades, key=lambda x: x['entry_time']):
                lines.append(self._build_trade_details_for_report(trade, realtime_prices[trade["symbol"]]))
        lines.append("\n====================================")
        return "\n".join(lines)

    def _should_send_report(self) -> bool:
        now_vn = datetime.now(self.config.VIETNAM_TZ)
        last_summary_str = self.state.get('last_summary_sent_time')
        last_summary_dt = datetime.fromisoformat(last_summary_str).astimezone(self.config.VIETNAM_TZ) if last_summary_str else None
        for time_str in self.config.GENERAL_CONFIG.get("DAILY_SUMMARY_TIMES", []):
            hour, minute = map(int, time_str.split(':'))
            scheduled_dt_today = now_vn.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if now_vn >= scheduled_dt_today and (last_summary_dt is None or last_summary_dt < scheduled_dt_today):
                return True
        return False

    def run(self):
        try:
            self.session_events = []
            initial_equity = self.state.get('cash', self.config.INITIAL_CAPITAL)
            self._run_heavy_tasks(initial_equity)
            
            active_symbols = list(set([t['symbol'] for t in self.state.get('active_trades', [])]))
            realtime_prices = {sym: price for sym in active_symbols if (price := self._get_realtime_price(sym)) is not None}
            
            if len(realtime_prices) == len(active_symbols):
                self._manage_open_positions(realtime_prices)
                self._handle_stale_trades(realtime_prices)
                final_equity = self._calculate_total_equity(realtime_prices)
                self._handle_dca_opportunities(final_equity or initial_equity, realtime_prices)
                
                if final_equity and self._should_send_report():
                    self._log_message("📬 Gửi báo cáo tổng kết...")
                    report_content = self._build_report_text(realtime_prices, final_equity)
                    self._send_discord_message(report_content)
                    self.state['last_summary_sent_time'] = datetime.now(self.config.VIETNAM_TZ).isoformat()
            else:
                missing = [s for s in active_symbols if s not in realtime_prices]
                self._log_message(f"⚠️ Tạm dừng quản lý vị thế do không lấy được giá cho: {', '.join(missing)}")

            self._save_state()
            self._log_message("✅ Phiên mô phỏng hoàn tất.\n" + "="*50)
        except Exception as e:
            self._log_error(f"LỖI TOÀN CỤC NGOÀI DỰ KIẾN", error_details=traceback.format_exc(), send_to_discord=True)
            self._save_state()

if __name__ == "__main__":
    trader = PaperTrader()
    trader.run()
