import time
import hmac
import base64
import hashlib
import json
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# ===== НАСТРОЙКИ OKX =====
API_KEY = "OKX_API_KEY"
API_SECRET = "OKX_API_SECRET"
PASSPHRASE = "OKX_PASSPHRASE"

BASE_URL = "https://www.okx.com"

SYMBOL = "AXS-USDT"      # спот пара
SIZE = "20"              # сумма покупки в USDT (для buy)
SELL_SIZE = "5"      # количество BTC для продажи

# ===== ПОДПИСЬ =====
def okx_headers(method, path, body=""):
    ts = time.strftime('%Y-%m-%dT%H:%M:%S.000Z', time.gmtime())
    msg = ts + method + path + body
    sign = base64.b64encode(
        hmac.new(API_SECRET.encode(), msg.encode(), hashlib.sha256).digest()
    ).decode()

    return {
        "OK-ACCESS-KEY": API_KEY,
        "OK-ACCESS-SIGN": sign,
        "OK-ACCESS-TIMESTAMP": ts,
        "OK-ACCESS-PASSPHRASE": PASSPHRASE,
        "Content-Type": "application/json"
    }

# ===== BUY (на сумму USDT) =====
def buy_spot():
    path = "/api/v5/trade/order"
    url = BASE_URL + path

    body = {
        "instId": SYMBOL,
        "tdMode": "cash",
        "side": "buy",
        "ordType": "market",
        "tgtCcy": "quote_ccy",
        "sz": SIZE        # сумма в USDT
    }

    body_json = json.dumps(body)
    headers = okx_headers("POST", path, body_json)
    return requests.post(url, headers=headers, data=body_json).json()

# ===== SELL (количество монет) =====
def sell_spot():
    path = "/api/v5/trade/order"
    url = BASE_URL + path

    body = {
        "instId": SYMBOL,
        "tdMode": "cash",
        "side": "sell",
        "ordType": "market",
        "sz": SELL_SIZE   # количество BTC
    }

    body_json = json.dumps(body)
    headers = okx_headers("POST", path, body_json)
    return requests.post(url, headers=headers, data=body_json).json()

# ===== WEBHOOK =====
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    print("Сигнал:", data)

    action = data.get("action")

    if action == "buy":
        result = buy_spot()
    elif action == "sell":
        result = sell_spot()
    else:
        return jsonify({"error": "unknown action"}), 400

    return jsonify(result)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
