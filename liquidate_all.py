# liquidate_top.py – Bán coin top theo danh sách chỉ định, in ra số dư USDT

from binance_connector import BinanceConnector

# Các coin top mà Ngài cho phép bán
SYMBOLS_TO_SCAN = "ETHUSDT,AVAXUSDT,INJUSDT,LINKUSDT,SUIUSDT,FETUSDT,TAOUSDT,BTCUSDT,ARBUSDT,ADAUSDT,SOLUSDT"
ALLOWED_SYMBOLS = SYMBOLS_TO_SCAN.split(",")

def extract_base_symbol(symbol: str) -> str:
    return symbol.replace("USDT", "")

if __name__ == "__main__":
    with BinanceConnector() as bnc:
        account = bnc.get_account_balance()
        balances = {b['asset']: float(b['free']) for b in account['balances'] if float(b['free']) > 0}

        for symbol in ALLOWED_SYMBOLS:
            coin = extract_base_symbol(symbol)
            if coin not in balances:
                continue

            qty = balances[coin]
            try:
                print(f"🔁 Bán {qty} {coin} => {symbol}")
                result = bnc.place_market_order(
                    symbol=symbol,
                    side="SELL",
                    quantity=qty
                )
                print(f"✅ Đã bán {coin}: {result['status']}")
            except Exception as e:
                print(f"❌ Không thể bán {coin}: {e}")

        # In số dư USDT sau khi bán
        final_account = bnc.get_account_balance()
        usdt_balance = next((b for b in final_account["balances"] if b["asset"] == "USDT"), None)
        print(f"\n💰 SỐ DƯ USDT CUỐI: {usdt_balance['free'] if usdt_balance else '0'}")
