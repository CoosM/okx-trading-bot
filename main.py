import os
import json
import time
import hmac
import base64
import hashlib
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# ================== CONFIG ==================
STATE_FILE = "state.json"
MAX_STEPS = 10
LOG_LEVEL = "INFO"  # INFO | WARN | ERROR

OKX_API_KEY = os.getenv("OKX_API_KEY")
OKX_API_SECRET = os.getenv("OKX_API_SECRET")
OKX_PASSPHRASE = os.getenv("OKX_PASSPHRASE")

OKX_BASE = "https://www.okx.com"
SYMBOL = "BTC-USDT"
TRADE_MODE = "cash"
ORDER_TYPE = "market"
BASE_USDT = 16.0

# ================== LOG ==================
def log(level, msg):
    levels = ["INFO", "WARN", "ERROR"]
    if levels.index(level) >= levels.index(LOG_LEVEL):
        print(f"{level} | {msg}")

# ================== STATE ==================
def load_state():
    if not os.path.exists(STATE_FILE):
        return {"steps": 0}
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except:
        return {"steps": 0}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)

# ================== OKX SIGN ==================
def okx_headers(method, path, body=""):
    ts = str(time.time())
    msg = ts + method + path + body
    sign = base64.b64encode(
        hmac.new(
            OKX_API_SECRET.encode(),
            msg.encode(),
            hashlib.sha256
        ).digest()
    ).decode()

    return {
        "OK-ACCESS-KEY": OKX_API_KEY,
        "OK-ACCESS-SIGN": sign,
        "OK-ACCESS-TIMESTAMP": ts,
        "OK-ACCESS-PASSPHRASE": OKX_PASSPHRASE,
        "Content-Type": "application/json"
    }

# ================== ORDERS ==================
def place_order(side, usdt_amount):
    path = "/api/v5/trade/order"
    body = {
        "instId": SYMBOL,
        "tdMode": TRADE_MODE,
        "side": side,
        "ordType": ORDER_TYPE,
        "sz": str(usdt_amount)
    }
    body_json = json.dumps(body)
    headers = okx_headers("POST", path, body_json)
    r = requests.post(OKX_BASE + path, headers=headers, data=body_json)
    return r.json()

# ================== BUY ==================
def buy_spot():
    state = load_state()

    if state["steps"] >= MAX_STEPS:
        log("WARN", f"⛔ BUY BLOCKED | steps={state['steps']}")
        return {"status": "blocked"}

    log("INFO", f"🟢 BUY TRY | step={state['steps']} | amount={BASE_USDT} USDT")
    res = place_order("buy", BASE_USDT)

    state["steps"] += 1
    save_state(state)

    log("INFO", f"✅ BUY OK | steps NOW={state['steps']}")
    return res

# ================== SELL ==================
def sell_spot():
    state = load_state()

    if state["steps"] <= 0:
        log("WARN", f"⛔ SELL BLOCKED | steps={state['steps']}")
        return {"status": "blocked"}

    log("INFO", f"🔴 SELL TRY | step={state['steps']} | amount={BASE_USDT} USDT")
    res = place_order("sell", BASE_USDT)

    state["steps"] -= 1
    save_state(state)

    log("INFO", f"✅ SELL OK | steps NOW={state['steps']}")
    return res

# ================== WEBHOOK ==================
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json or {}
    signal = data.get("signal")

    if signal == "BUY":
        return jsonify(buy_spot())

    if signal == "SELL":
        return jsonify(sell_spot())

    return jsonify({"status": "ignored"})

# ================== RUN ==================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
