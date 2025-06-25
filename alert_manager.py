# alert_manager.py
# -*- coding: utf-8 -*-
import os
import requests

DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")

def send_discord_alert(message: str):
    """Gửi message đơn giản lên Discord"""
    if not DISCORD_WEBHOOK:
        print("❌ DISCORD_WEBHOOK chưa được cấu hình trong .env")
        return

    payload = {
        "content": message
    }

    try:
        response = requests.post(DISCORD_WEBHOOK, json=payload)
        if response.status_code == 204:
            print("✅ Gửi Discord thành công")
        else:
            print(f"⚠️ Lỗi gửi Discord: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"❌ Exception khi gửi Discord: {e}")
