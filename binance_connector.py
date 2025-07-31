# binance_connector.py (v2.3.1 - Sửa lỗi cú pháp)
"""
BinanceConnector – Robust & Production-Ready v2.3.1
==================================================
Phiên bản sửa lỗi cú pháp trong hàm get_open_orders.

CHANGELOG v2.3.1:
- SỬA LỖI: Sửa lại cú pháp không hợp lệ trong định nghĩa hàm get_open_orders.
- GIỮ NGUYÊN: Tính năng công tắc TRADING_MODE linh hoạt của v2.3.
"""
from __future__ import annotations

import os
import time
import hmac
import hashlib
import random
import decimal
import logging
import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Literal, Optional, TypedDict
from urllib.parse import urlencode

import requests
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# 1. Cấu hình & Hằng số
# ---------------------------------------------------------------------------

# <<< CÔNG TẮC CHUYỂN ĐỔI MÔI TRƯỜNG >>>
# Đổi giá trị này thành "live" để giao dịch tiền thật.
# Đổi giá trị này thành "testnet" để giao dịch tiền ảo, an toàn để phát triển.
TRADING_MODE: Literal["live", "testnet"] = "testnet"
# ==========================================

load_dotenv()

# Tải tất cả các key từ file .env
LIVE_API_KEY = os.getenv("BINANCE_API_KEY_TRADE")
LIVE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY_TRADE")
TESTNET_API_KEY = os.getenv("BINANCE_API_TEST_KEY")
TESTNET_SECRET_KEY = os.getenv("BINANCE_SECRET_TEST_KEY")

# URL cho các môi trường
LIVE_URL = "https://api.binance.com"
TESTNET_URL = "https://testnet.binance.vision"

# Cấu hình logging
logging.basicConfig(level=logging.INFO,
                    format="[%(asctime)s] [%(levelname)s] (BinanceConnector) [%(network)s] %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S")

decimal.getcontext().prec = 28

# ---------------------------------------------------------------------------
# 2. Kiểu dữ liệu (TypedDict) - Giữ nguyên
# ---------------------------------------------------------------------------
class Balance(TypedDict):
    asset: str
    free: str
    locked: str

class AccountInfo(TypedDict):
    balances: List[Balance]

class Order(TypedDict):
    symbol: str
    orderId: int
    price: str
    origQty: str
    executedQty: str
    status: str
    side: str

# ---------------------------------------------------------------------------
# 3. Connector chính - Đã được nâng cấp
# ---------------------------------------------------------------------------
class BinanceConnector:
    """Client đồng bộ, mạnh mẽ để tương tác với API Binance Spot."""

    def __init__(
        self,
        network: Optional[Literal["live", "testnet"]] = None,
        max_retries: int = 5,
        backoff_base: float = 1.0,
    ) -> None:
        self.network = network if network is not None else TRADING_MODE

        if self.network == "live":
            self.api_key = LIVE_API_KEY
            self.secret_key = LIVE_SECRET_KEY
            self.base_url = LIVE_URL
        elif self.network == "testnet":
            self.api_key = TESTNET_API_KEY
            self.secret_key = TESTNET_SECRET_KEY
            self.base_url = TESTNET_URL
        else:
            raise ValueError("Mạng phải là 'live' hoặc 'testnet'")

        if not self.api_key or not self.secret_key:
            key_name = "BINANCE_API_KEY_TRADE/SECRET" if self.network == "live" else "BINANCE_API_TEST_KEY/SECRET"
            raise ValueError(f"Thiếu {key_name}. Hãy chắc chắn chúng đã được đặt trong file .env")

        self.max_retries = max_retries
        self.backoff_base = backoff_base
        
        self.logger = logging.LoggerAdapter(logging.getLogger(), {'network': self.network.upper()})

        self.session = requests.Session()
        self.session.headers.update({"X-MBX-APIKEY": self.api_key})

        self._exchange_info: Dict[str, Any] = {}
        self._last_exchange_info_sync: datetime = datetime.min

        self._time_offset_ms: int = 0
        self._last_sync: datetime = datetime.min
        self._sync_time()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def close(self) -> None:
        self.session.close()
        self.logger.debug("Đã đóng session BinanceConnector")

    def _sync_time(self) -> None:
        try:
            srv = self.session.get(f"{self.base_url}/api/v3/time", timeout=5).json()
            local = int(time.time() * 1000)
            self._time_offset_ms = srv["serverTime"] - local
            self._last_sync = datetime.now()
            self.logger.debug("Đồng bộ thời gian thành công: offset %d ms", self._time_offset_ms)
        except Exception as e:
            self.logger.warning("Không thể đồng bộ thời gian server: %s", e)

    def _get_timestamp(self) -> int:
        if datetime.now() - self._last_sync > timedelta(minutes=30):
            self._sync_time()
        return int(time.time() * 1000 + self._time_offset_ms)

    def _sign(self, params: Dict[str, Any]) -> str:
        q = urlencode(params, doseq=True)
        return hmac.new(self.secret_key.encode(), q.encode(), hashlib.sha256).hexdigest()

    def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        signed: bool = False,
    ) -> Any:
        params = params.copy() if params else {}
        if signed:
            params.update({"timestamp": self._get_timestamp(), "recvWindow": 60000})
            params["signature"] = self._sign(params)

        url = f"{self.base_url}{endpoint}"

        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self.session.request(method, url, params=params, timeout=15)

                try:
                    data = resp.json()
                except ValueError:
                    self.logger.error("Không nhận JSON (có thể 502/504 HTML): %.120s", resp.text)
                    resp.raise_for_status()
                    continue

                if resp.status_code >= 400:
                    self.logger.error("Lỗi API (HTTP %d) tại '%s': %s", resp.status_code, endpoint, data)
                    if data.get("code") == -2015:
                         self.logger.critical("LỖI QUYỀN API (-2015): Hãy kiểm tra xem API key đã bật 'Enable Spot & Margin Trading' và không bị giới hạn IP chưa.")
                    if data.get("code") == -1021:
                        self.logger.warning("-1021 Timestamp lệch – Đồng bộ lại và retry ngay lập tức...")
                        self._sync_time()
                        params["timestamp"] = self._get_timestamp()
                        params["signature"] = self._sign(params)
                        continue

                resp.raise_for_status()
                return data

            except requests.exceptions.RequestException as exc:
                self.logger.warning("Lỗi mạng khi gọi '%s': %s", endpoint, exc)
                if attempt == self.max_retries:
                    self.logger.error("Vượt quá số lần retry cho '%s'. Bỏ cuộc.", endpoint)
                    raise
                backoff = self.backoff_base * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
                self.logger.debug("Retry %s %s (%d/%d) sau %.2fs", method, endpoint, attempt, self.max_retries, backoff)
                time.sleep(backoff)
        return None

    def get_exchange_info(self) -> Dict[str, Any]:
        if datetime.now() - self._last_exchange_info_sync > timedelta(hours=1):
            try:
                self.logger.info("Đang làm mới cache thông tin sàn (exchange info)...")
                info = self._request("GET", "/api/v3/exchangeInfo")
                self._exchange_info = {s['symbol']: s for s in info['symbols']}
                self._last_exchange_info_sync = datetime.now()
                self.logger.info("✅ Cache thông tin sàn đã được làm mới.")
            except Exception as e:
                self.logger.error("Lỗi nghiêm trọng khi lấy exchange info: %s", e)
        return self._exchange_info

    def _get_symbol_filter(self, symbol: str, filter_type: str) -> Dict[str, Any] | None:
        info = self.get_exchange_info().get(symbol)
        if info:
            for f in info['filters']:
                if f['filterType'] == filter_type:
                    return f
        return None

    def _format_quantity(self, symbol: str, quantity: float | str) -> str:
        lot_size_filter = self._get_symbol_filter(symbol, 'LOT_SIZE')
        if lot_size_filter and 'stepSize' in lot_size_filter:
            step = decimal.Decimal(lot_size_filter['stepSize'])
            val = decimal.Decimal(str(quantity))
            rounded = (val // step) * step
            return format(rounded.quantize(step), 'f').rstrip('0').rstrip('.')
        return format(decimal.Decimal(str(quantity)), 'f').rstrip('0').rstrip('.')


    def _format_price(self, symbol: str, price: float | str) -> str:
        price_filter = self._get_symbol_filter(symbol, 'PRICE_FILTER')
        if price_filter and 'tickSize' in price_filter:
            tick = decimal.Decimal(price_filter['tickSize'])
            val = decimal.Decimal(str(price))
            rounded = (val // tick) * tick
            return format(rounded.quantize(tick), 'f').rstrip('0').rstrip('.')
        return format(decimal.Decimal(str(price)), 'f').rstrip('0').rstrip('.')


    def get_account_balance(self) -> AccountInfo:
        return self._request("GET", "/api/v3/account", signed=True)

    # <<< SỬA LỖI CÚ PHÁP TẠI ĐÂY >>>
    def get_open_orders(self, symbol: Optional[str] = None) -> List[Order]:
        params = {"symbol": symbol} if symbol else {}
        return self._request("GET", "/api/v3/openOrders", params=params, signed=True)

    def cancel_order(self, symbol: str, order_id: int) -> Order:
        params = {"symbol": symbol, "orderId": order_id}
        return self._request("DELETE", "/api/v3/order", params, signed=True)

    def place_market_order(
        self,
        symbol: str,
        side: Literal["BUY", "SELL"],
        quantity: Optional[float | str] = None,
        quote_order_qty: Optional[float | str] = None
    ) -> Order:
        if not (quantity or quote_order_qty):
            raise ValueError("Phải cung cấp quantity hoặc quote_order_qty")

        params: Dict[str, Any] = {"symbol": symbol.upper(), "side": side, "type": "MARKET"}
        if quantity:
            params['quantity'] = self._format_quantity(symbol, quantity)
        if quote_order_qty:
            params['quoteOrderQty'] = quote_order_qty

        self.logger.info("➡️ Đặt lệnh MARKET: %s", params)
        return self._request("POST", "/api/v3/order", params, signed=True)

    def create_oco_order(
        self,
        symbol: str,
        side: Literal["SELL"],
        quantity: float | str,
        price: float | str,
        stop_price: float | str,
        stop_limit_price: Optional[float | str] = None
    ) -> Dict:
        if stop_limit_price is None:
            stop_limit_price = stop_price

        params = {
            "symbol": symbol.upper(),
            "side": side,
            "quantity": self._format_quantity(symbol, quantity),
            "price": self._format_price(symbol, price),
            "stopPrice": self._format_price(symbol, stop_price),
            "stopLimitPrice": self._format_price(symbol, stop_limit_price),
            "stopLimitTimeInForce": "GTC"
        }
        self.logger.info("➡️ Đặt lệnh OCO: %s", params)
        return self._request("POST", "/api/v3/order/oco", params, signed=True)

    def test_connection(self) -> bool:
        try:
            self.logger.info("Đang kiểm tra kết nối tới Binance...")
            self.get_exchange_info()
            self.get_account_balance()
            self.logger.info("✅ Kết nối và xác thực API thành công!")
            return True
        except Exception as e:
            self.logger.error("❌ Test kết nối thất bại: %s", e)
            return False

# ---------------------------------------------------------------------------
# 4. Demo và Kiểm thử - Đã được nâng cấp
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    with BinanceConnector() as bnc:
        print(f"--- CHẠY KIỂM THỬ TRÊN MÔI TRƯỜNG: {bnc.network.upper()} ---")
        
        if bnc.test_connection():
            balance_info = bnc.get_account_balance()
            usdt_balance = next((b for b in balance_info["balances"] if b["asset"] == "USDT"), None)
            
            if usdt_balance:
                bnc.logger.info(f"Số dư USDT: {usdt_balance['free']}")
            else:
                bnc.logger.info("Không tìm thấy số dư USDT.")

            if bnc.network == "testnet":
                if usdt_balance and float(usdt_balance['free']) >= 15:
                    try:
                        market_buy_order = bnc.place_market_order(
                            symbol="ETHUSDT",
                            side="BUY",
                            quote_order_qty=10
                        )
                        bnc.logger.info("Kết quả lệnh Market Buy:\n%s", json.dumps(market_buy_order, indent=2))

                        time.sleep(3)

                        if market_buy_order and market_buy_order.get('status') == 'FILLED':
                            filled_qty = float(market_buy_order['executedQty'])
                            avg_price = float(market_buy_order['cummulativeQuoteQty']) / filled_qty
                            tp_price = avg_price * 1.10
                            sl_price = avg_price * 0.95

                            oco_order = bnc.create_oco_order(
                                symbol="ETHUSDT",
                                side="SELL",
                                quantity=filled_qty,
                                price=tp_price,
                                stop_price=sl_price
                            )
                            bnc.logger.info("Kết quả lệnh OCO:\n%s", json.dumps(oco_order, indent=2))

                    except Exception as e:
                        bnc.logger.error("Lỗi trong quá trình thử đặt lệnh: %s", e)
                else:
                    bnc.logger.warning("Không đủ USDT (cần >= 15) trên Testnet để chạy thử nghiệm đặt lệnh.")
