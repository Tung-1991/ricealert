# -*- coding: utf-8 -*-
"""RiceAlert – main runner

* 08:00 & 20:00 (report time):
  - Always send Discord alerts for **all intervals** and a full portfolio report.
  - **Do not** write to CSV (avoid bloating daily logs).
* Every 30 minutes via crontab (non‑report time):
  - Evaluate only intervals listed in ENV `INTERVALS` (default "1h,4h").
  - Send Discord + write CSV **only** for signals ⩾ WATCHLIST that are out of cooldown.

This file is fully self‑contained and safe to run with `python -m py_compile`.
"""

from dotenv import load_dotenv
load_dotenv()

import os
import time
import json
import pandas as pd
from datetime import datetime, timedelta
from portfolio import get_account_balances
from indicator import get_price_data, calculate_indicators
from signal_logic import check_signal
from alert_manager import send_discord_alert
from csv_logger import log_to_csv, write_named_log

# ---------------------------------------------------------------------------
# Constants & config ---------------------------------------------------------
# ---------------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
COOLDOWN_FILE = os.path.join(BASE_DIR, "cooldown_tracker.json")
COOLDOWN_LEVEL_MAP = {
    "1h":    {"WATCHLIST": 300,  "ALERT": 240,  "WARNING": 180,  "CRITICAL":  90},
    "4h":    {"WATCHLIST": 720,  "ALERT": 480,  "WARNING": 360,  "CRITICAL": 240},
    "1d":    {"WATCHLIST": 1800, "ALERT": 1560, "WARNING": 1500, "CRITICAL": 1380},
}

# Levels worth notifying outside the 08h/20h daily reports
SEND_LEVELS = ["WATCHLIST", "ALERT", "WARNING", "CRITICAL"]

# ---------------------------------------------------------------------------
# Helper functions -----------------------------------------------------------
# ---------------------------------------------------------------------------

def load_cooldown() -> dict[str, datetime]:
    """Return last‑alert timestamps (max 2 days back)."""
    if os.path.exists(COOLDOWN_FILE):
        try:
            with open(COOLDOWN_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                now = datetime.now()
                return {
                    key: datetime.fromisoformat(val)
                    for key, val in data.items()
                    if now - datetime.fromisoformat(val) < timedelta(days=2)
                }
        except Exception as exc:  # noqa: BLE001
            print(f"⚠️ Không thể load cooldown file: {exc}")
    return {}


def save_cooldown(cooldown: dict[str, datetime]) -> None:
    with open(COOLDOWN_FILE, "w", encoding="utf-8") as f:
        json.dump({k: v.isoformat() for k, v in cooldown.items()}, f)


def is_report_time() -> bool:
    now = datetime.now()
    report_times = os.getenv("REPORT_TIMES", "08:00,20:00").split(",")
    return now.strftime("%H:%M") in report_times


# ----------------------------- Portfolio rendering -------------------------

def render_portfolio() -> list[str]:
    balances = get_account_balances()
    spot      = [b for b in balances if b["source"] == "Spot"]
    flexible  = [b for b in balances if b["source"] == "Earn Flexible"]
    locked    = [b for b in balances if b["source"] == "Earn Locked"]
    total     = [b for b in balances if b["source"] == "All"]

    def section(title: str, rows: list[dict]) -> list[str]:
        lines: list[str] = []
        if rows:
            lines.append(f"\n{title}")
            for r in rows:
                lines.append(f"🪙 {r['asset']}: {r['amount']} ≈ ${r['value']}")
            subtotal = sum(r["value"] for r in rows)
            lines.append(f"🔢 Tổng ({title.strip()}): ${round(subtotal, 2)}")
        return lines

    print("\n💰 Portfolio hiện tại:")
    lines: list[str] = []
    lines += section("📦 Spot:", spot)
    lines += section("🪴 Earn Flexible:", flexible)
    lines += section("🔒 Earn Locked:", locked)

    for l in lines:
        print(l)

    if total:
        total_line = f"\n💵 Tổng tài sản: ${total[0]['value']}"
        print(total_line)
        lines.append(total_line.replace("💵", "\n💵"))

    return lines


def send_portfolio_report() -> None:
    send_discord_alert(
        "📊 **BÁO CÁO TỔNG TÀI SẢN**\n" + "\n".join(render_portfolio())
    )
    time.sleep(3)


# ----------------------------- Symbol report -------------------------------

def format_symbol_report(symbol: str, ind_map: dict[str, dict]) -> str:
    parts: list[str] = []
    for interval, ind in ind_map.items():
        macd_cross = ind.get("macd_cross", "N/A")
        adx        = ind.get("adx", "N/A")
        rsi_div    = ind.get("rsi_divergence", "None")
        trade_plan = ind.get("trade_plan", {})
        doji_note  = f"{ind['doji_type'].capitalize()} Doji" if ind.get("doji_type") else "No"
        trend      = ind.get("trend", "unknown")
        cmf        = ind.get("cmf", "N/A")
        signal, reason = check_signal(ind)

        block = f"""📊 **{symbol} ({interval})**
🔹 Price: {ind['price']:.8f}
📈 EMA20: {ind['ema_20']}
💪 RSI14: {ind['rsi_14']} ({rsi_div})
📉 MACD Line: {ind['macd_line']}
📊 MACD Signal: {ind['macd_signal']} → {macd_cross}
📊 ADX: {adx}
🔺 BB Upper: {ind['bb_upper']}
🔻 BB Lower: {ind['bb_lower']}
🔊 Volume: {ind['volume']} / MA20: {ind['vol_ma20']}
🌀 Fibo 0.618: {ind.get('fib_0_618')}
🕯️ Doji: {doji_note}
🔺 Trend: {trend}
💸 CMF: {cmf}
🧠 Signal: **{signal}** {f'→ {reason}' if reason else ''}"""

        if trade_plan:
            entry = trade_plan.get("entry", 0)
            tp    = trade_plan.get("tp", 0)
            sl    = trade_plan.get("sl", 0)
            block += f"""
🎯 **Trade Plan**
- Entry: {entry:.8f}
- TP:     {tp:.8f}
- SL:     {sl:.8f}"""

        parts.append(block)
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Main loop ------------------------------------------------------------------
# ---------------------------------------------------------------------------

def main() -> None:
    print("🔁 Bắt đầu vòng check...\n")

    # Basic setup -----------------------------------------------------------
    symbols   = os.getenv("SYMBOLS", "ETHUSDT,AVAXUSDT").split(",")
    intervals = [i.strip() for i in os.getenv("INTERVALS", "1h,4h").split(",")]

    should_report = is_report_time()          # 08:00 & 20:00
    force_daily   = should_report             # alias for clarity

    now          = datetime.now()
    now_str      = now.strftime("%Y-%m-%d %H:%M:%S")
    log_date_dir = os.path.join(BASE_DIR, "log", now.strftime("%Y-%m-%d"))
    os.makedirs(log_date_dir, exist_ok=True)

    # Prefetch data to minimise API calls ----------------------------------
    cached: dict[str, dict[str, object]] = {"1h": {}, "4h": {}, "1d": {}}
    # luôn fetch 1h
    for sym in symbols:
        cached["1h"][sym] = get_price_data(sym, "1h")
    # fetch 4h nếu cần
    if "4h" in intervals:
        for sym in symbols:
            cached["4h"][sym] = get_price_data(sym, "4h")
    # fetch 1d nếu cần
    if "1d" in intervals:
        for sym in symbols:
            cached["1d"][sym] = get_price_data(sym, "1d")

    cooldowns = load_cooldown()

    if should_report:
        send_portfolio_report()

    # ---------------------------------------------------------------------
    # Per‑symbol processing ------------------------------------------------
    # ---------------------------------------------------------------------
    log_lines: list[str] = []
    for symbol in symbols:
        try:
            indic_map:      dict[str, dict] = {}
            send_intervals: list[str]       = []
            alert_levels:   list[str]       = []

            for interval in intervals:
                # Get dataframe (use cache if ready)
                df = (
                    cached[interval].get(symbol)
                    if interval in cached and symbol in cached[interval]
                    else get_price_data(symbol, interval)
                )
                df["close_time"] = pd.to_datetime(df["close_time"], unit="ms")
                df = df[df["close_time"] < now - timedelta(minutes=1)]


                ind = calculate_indicators(df, symbol, interval)
                ind["interval"] = interval

                # Cross‑frame RSI ------------------------------------------------
                if interval == "1h":
                    rsi_4h = calculate_indicators(cached["4h"][symbol], symbol, "4h")["rsi_14"]
                    rsi_1d = calculate_indicators(cached["1d"][symbol], symbol, "1d")["rsi_14"]
                    ind["rsi_1h"] = ind["rsi_14"]
                    ind["rsi_4h"] = rsi_4h
                    ind["rsi_1d"] = rsi_1d

                elif interval == "4h":
                    ind1 = calculate_indicators(cached["1h"][symbol], symbol, "1h")
                    rsi_1d = calculate_indicators(cached["1d"][symbol], symbol, "1d")["rsi_14"]
                    ind["rsi_1h"] = ind1["rsi_14"]
                    ind["rsi_4h"] = ind["rsi_14"]
                    ind["rsi_1d"] = rsi_1d

                elif interval == "1d":
                    ind1 = calculate_indicators(cached["1h"][symbol], symbol, "1h")
                    ind4 = calculate_indicators(cached["4h"][symbol], symbol, "4h")
                    ind["rsi_1h"] = ind1["rsi_14"]
                    ind["rsi_4h"] = ind4["rsi_14"]
                    ind["rsi_1d"] = ind["rsi_14"]


                signal, _ = check_signal(ind)
                indic_map[interval] = ind

                # Skip signals not in SEND_LEVELS except during daily report
                if signal not in SEND_LEVELS and not force_daily:
                    msg = f"🔇 {symbol} - {interval} → {signal} → KHÔNG lưu/GỬI"
                    print(msg)
                    log_lines.append(msg)
                    continue

                # Cooldown handling ----------------------------------------
                cd_key      = f"{symbol}_{interval}_{signal}"
                cd_minutes  = COOLDOWN_LEVEL_MAP.get(interval, {}).get(signal, 90)

                if force_daily:
                    # Daily report: always send, never write CSV
                    send_intervals.append(interval)
                    alert_levels.append(signal)
                else:
                    last_time = cooldowns.get(cd_key)
                    if not last_time or now - last_time >= timedelta(minutes=cd_minutes):
                        # Record to CSV
                        log_to_csv(
                            symbol=symbol,
                            interval=interval,
                            signal=signal,
                            tag=ind.get("tag", "hold"),
                            price=ind.get("price", 0),
                            trade_plan=ind.get("trade_plan", {}),
                            timestamp=now_str,
                        )

                        if signal != "WATCHLIST":
                            print(f"📤 CSV + chờ Discord: {symbol} - {interval} ({signal})")
                            log_lines.append(f"📤 CSV + chờ Discord: {symbol} - {interval} ({signal})")
                        else:
                            print(f"👀 {symbol} - {interval} → WATCHLIST → CSV+Discord")
                            log_lines.append(f"👀 {symbol} - {interval} → WATCHLIST → CSV+Discord")

                        send_intervals.append(interval)
                        alert_levels.append(signal)
                        cooldowns[cd_key] = now
                    else:
                        remain = cd_minutes - int((now - last_time).total_seconds() // 60)
                        msg = f"⏳ {symbol}-{interval} ({signal}) Cooldown {remain}′ → skip"
                        print(msg)
                        log_lines.append(msg)
                        continue

            # ----------------------------------------------------------------
            # Prepare & maybe send Discord message ---------------------------
            filtered = (
                {iv: indic_map[iv] for iv in send_intervals} if send_intervals else indic_map
            )
            report = format_symbol_report(symbol, filtered)
            print(report + "\n" + "-" * 50)
            log_lines.append(report)

            if send_intervals:
                highest = (
                    "CRITICAL" if "CRITICAL" in alert_levels else
                    "WARNING"  if "WARNING"  in alert_levels else
                    "ALERT"    if "ALERT"    in alert_levels else
                    "WATCHLIST"
                )
                icon = {"CRITICAL": "🚨", "WARNING": "⚠️", "ALERT": "📣", "WATCHLIST": "👀"}[highest]
                title = f"{icon} [{symbol}] **{highest}** từ khung {', '.join(send_intervals)} | ⏱️ {now_str}"
                ids   = "\n".join([f"🆔 ID: {now_str}\t{symbol}\t{iv}" for iv in send_intervals])
                send_discord_alert(f"{title}\n{ids}\n\n{report}")
                print(f"📨 Discord: {symbol} - {', '.join(send_intervals)} ({highest})")
                log_lines.append(f"📨 Discord: {symbol} - {', '.join(send_intervals)} ({highest})")
                time.sleep(3)
        except Exception as exc:  # noqa: BLE001
            msg = f"❌ Lỗi xử lý {symbol}: {exc}"
            print(msg)
            log_lines.append(msg)

    # ---------------------------------------------------------------------
    # Persist logs & cooldown ---------------------------------------------
    if log_lines:
        content = "\n\n" + ("\n" + "=" * 60 + "\n\n").join(log_lines)
        write_named_log(content, os.path.join(log_date_dir, f"{now.strftime('%H%M')}.txt"))

    save_cooldown(cooldowns)


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    main()

