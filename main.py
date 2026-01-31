import time
import hmac
import base64
import hashlib
import json
import requests
import os
from flask import Flask, request, jsonify

app = Flask(__name__)

total_qty = 0.0
steps = 0

# ===== ENV НАСТРОЙКИ OKX =====
API_KEY = os.getenv("OKX_API_KEY")
API_SECRET = os.getenv("OKX_API_SECRET")
PASSPHRASE = os.getenv("OKX_PASSPHRASE")

BASE_URL = "https://www.okx.com"

SYMBOL = os.getenv("SYMBOL", "AXS-USDT")   # спот пара
BUY_USDT = os.getenv("BUY_USDT", "20")     # сумма покупки в USDT

# ===== ПРОВЕРКА (чтобы не упал молча) =====
if not API_KEY or not API_SECRET or not PASSPHRASE:
    raise Exception("❌ OKX API keys not set in Environment Variables")

# ===== ПОДПИСЬ OKX =====
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
    global total_qty, steps

    path = "/api/v5/trade/order"
    url = BASE_URL + path

    body = {
        "instId": SYMBOL,
        "tdMode": "cash",
        "side": "buy",
        "ordType": "market",
        "tgtCcy": "quote_ccy",
        "sz": BUY_USDT
    }

    body_json = json.dumps(body)
    headers = okx_headers("POST", path, body_json)

    r = requests.post(url, headers=headers, data=body_json).json()

    # считаем шаг
    # считаем шаг
if r.get("code") == "0" and r.get("data"):
    order = r["data"][0]

    filled = float(order.get("accFillSz", 0))
    if filled > 0:
        total_qty += filled
        steps += 1

    return r

# ===== SELL (количество монет, AXS) =====
def sell_spot():
    global total_qty, steps

    if steps <= 0 or total_qty <= 0:
        return {"error": "nothing to sell"}

    sell_qty = total_qty / steps   # ← ВАЖНО

    path = "/api/v5/trade/order"
    url = BASE_URL + path

    body = {
        "instId": SYMBOL,
        "tdMode": "cash",
        "side": "sell",
        "ordType": "market",
        "sz": str(round(sell_qty, 6))
    }

    body_json = json.dumps(body)
    headers = okx_headers("POST", path, body_json)

    r = requests.post(url, headers=headers, data=body_json).json()

    if r.get("code") == "0":
        total_qty -= sell_qty
        steps -= 1

    return r

# ===== WEBHOOK =====
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    print("📩 Сигнал:", data)

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
