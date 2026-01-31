import os
import time
import hmac
import hashlib
import base64
import json
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# Считываем ключи из настроек Render (Environment Variables)
OKX_API_KEY = os.getenv("OKX_API_KEY")
OKX_SECRET_KEY = os.getenv("OKX_SECRET_KEY")
OKX_PASSPHRASE = os.getenv("OKX_PASSPHRASE")
OKX_BASE_URL = "https://www.okx.com"

def sign(timestamp, method, path, body):
    msg = f"{timestamp}{method}{path}{body}"
    mac = hmac.new(
        OKX_SECRET_KEY.encode(),
        msg.encode(),
        hashlib.sha256
    )
    return base64.b64encode(mac.digest()).decode()

@app.route("/webhook", methods=["POST"])
def webhook():
    # 1. Получаем данные от TradingView
    data = request.get_data(as_text=True)
    if not data:
        print("❌ Error: Received empty body")
        return "Empty body", 400

    print(f"📩 Webhook received: {data}")

    # 2. Настройки запроса к OKX
    path = "/api/v5/trade/order"
    url = OKX_BASE_URL + path
    timestamp = time.strftime('%Y-%m-%dT%H:%M:%S.000Z', time.gmtime())

    # 3. Создаем подпись
    headers = {
        "OK-ACCESS-KEY": OKX_API_KEY,
        "OK-ACCESS-SIGN": sign(timestamp, "POST", path, data),
        "OK-ACCESS-TIMESTAMP": timestamp,
        "OK-ACCESS-PASSPHRASE": OKX_PASSPHRASE,
        "Content-Type": "application/json"
    }

    # 4. Отправляем ордер на биржу
    try:
        response = requests.post(url, headers=headers, data=data)
        print(f"📊 OKX Status Code: {response.status_code}")
        print(f"📩 OKX Response: {response.text}")
        return jsonify(response.json()), response.status_code
    except Exception as e:
        print(f"❌ Critical Error: {str(e)}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    # Render использует порт 10000 по умолчанию
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
