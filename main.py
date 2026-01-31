from flask import Flask, request, jsonify
import time, hmac, hashlib, base64, json, requests, os

app = Flask(__name__)

API_KEY = os.getenv("OKX_API_KEY")
SECRET_KEY = os.getenv("OKX_SECRET_KEY")
PASSPHRASE = os.getenv("OKX_PASSPHRASE")
BASE_URL = "https://www.okx.com"

def sign(ts, method, path, body):
    msg = f"{ts}{method}{path}{body}"
    mac = hmac.new(SECRET_KEY.encode(), msg.encode(), hashlib.sha256)
    return base64.b64encode(mac.digest()).decode()

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    print("Webhook received:", data)

    ts = str(time.time())
    path = "/api/v5/trade/order"
    body = json.dumps(data)

    headers = {
        "OK-ACCESS-KEY": API_KEY,
        "OK-ACCESS-SIGN": sign(ts, "POST", path, body),
        "OK-ACCESS-TIMESTAMP": ts,
        "OK-ACCESS-PASSPHRASE": PASSPHRASE,
        "Content-Type": "application/json"
    }

    print("➡️ Отправка ордера в OKX:", body)
    r = requests.post(BASE_URL + path, headers=headers, data=body)

    print("OKX STATUS:", r.status_code)
    print("OKX RESPONSE:", r.text)

    return jsonify({"okx_response": r.text})

@app.route("/")
def home():
    return "OKX BOT LIVE"
