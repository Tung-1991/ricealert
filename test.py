import requests

url = "https://discord.com/api/webhooks/1386662555358859264/I_Z6Vmn0wy1CySEc4jExkSH1lkt-vwuxPMPo5050-amckJ5R6UtxLH1svtL6nSKNDFjU"
data = {
    "content": "✅ **Webhook test thành công!**\nETH Agent sắp lên sóng 🚀"
}
requests.post(url, json=data)
