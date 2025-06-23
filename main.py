import requests, os, time
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK")

def get_eth_price():
    try:
        r = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd")
        return r.json()["ethereum"]["usd"]
    except Exception as e:
        print("❌ Failed to fetch ETH price:", e)
        return None

def send_discord_message(msg):
    if WEBHOOK_URL:
        try:
            requests.post(WEBHOOK_URL, json={"content": msg})
            print("✅ Sent to Discord")
        except Exception as e:
            print("❌ Failed to send to Discord:", e)

def main():
    while True:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        price = get_eth_price()
        if price:
            msg = f"🕒 {now}\n💰 ETH Price: **${price}**"
            send_discord_message(msg)
        time.sleep(3600)  # Gửi mỗi giờ

if __name__ == "__main__":
    main()
