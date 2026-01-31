from flask import Flask, request, jsonify
import os
import time
import hmac
import hashlib
import base64
import json
import requests

app = Flask(__name__)

# ===== OKX ENV =====
OKX_API_KEY = os.getenv("OKX_API_KEY")
OKX_SECRET_KEY = os.getenv("OKX_SECRET_KEY")
OKX_PASSPHRASE = os.getenv("OKX_PASSPHRASE")
OKX_BASE_URL = os.getenv("OKX_BASE_URL", "https://www.okx.com")


def sign(timestamp, method, path, body):
    message = f"{timestamp}{method}{path}{body}"
    mac = hmac.new(
        OKX_SECRET_KEY.encode(),
        message.encode(),
        hashlib.sha256
    )
    return base64.b64encode(mac.digest()).decode()


@app.route("/")
def home():
    return "OKX bot is running"


@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    print("📩 Webhook received:", data)

    body = json.dumps(data)
    print("➡️ Отправка ордера в OKX:", body)

    path = "/api/v5/trade/order"
    url = OKX_BASE_URL + path
    timestamp = time.strftime('%Y-%m-%dT%H:%M:%S.000Z', time.gmtime())

    headers = {
        "OK-ACCESS-KEY": OKX_API_KEY,
        "OK-ACCESS-SIGN": sign(timestamp, "POST", path, body),
        "OK-ACCESS-TIMESTAMP": timestamp,
        "OK-ACCESS
