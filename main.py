import time
import hmac
import base64
import hashlib
import json
import requests
import os
from flask import Flask, request, jsonify

app = Flask(__name__)

# ================== ENV ==================
API_KEY = os.getenv("OKX_API_KEY")
API_SECRET = os.getenv("OKX_API_SECRET")
PASSPHRASE = os.getenv("OKX_PASSPHRASE")

BASE_URL = "https://www.okx.com"

SYMBOL = os.getenv("SYMBOL", "AXS-USDT")
BUY_USDT = float(os.getenv("BUY_USDT", "16"))

MAX_STEPS = 10
STATE_FILE = "state.json"

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

LEVELS = {
    "DEBUG": 10,
    "INFO": 20,
    "WARN": 30,
    "ERROR": 40
}

# ================== LOG ==================
def log(level, message):
    if LEVELS[level] >= LEVELS.get(LOG_LEVEL, 20):
        print(f"{level} | {message}", flush=True)

# ================== STATE ==================
DEFAULT_STATE = {
    "step": 0,
    "asset_qty": 0.0,
    "usdt_spent": 0.0
}

def load_state():
    if not os.path.exists(STATE_FILE):
        save_state(DEFAULT_STATE.copy())
        return DEFAULT_STATE.copy()

    with open(STATE_FILE, "r") as f:
        state = json.load(f)

    # защита от старых / битых state.json
    for k, v in DEFAULT_STATE.items():
        state.setdefault(k, v)

    return state

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)

# ================== OKX SIGN ==================
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

# ================== BUY ==================
def buy_spot():
    state = load_state()

    if state["step"] >= MAX_STEPS:
        log("WARN", "⛔ BUY BLOCKED | max steps reached")
        return {"BUY": "SKIP", "reason": "max steps"}

    log("INFO", f"🟢 BUY TRY | step={state['step']} | amount={BUY_USDT} USDT")

    path = "/api/v5/trade/order"
    body = {
        "instId": SYMBOL,
        "tdMode": "cash",
        "side": "buy",
        "ordType": "market",
        "tgtCcy": "quote_ccy",
        "sz": str(BUY_USDT)
    }

    body_json = json.dumps(body)
    headers = okx_headers("POST", path, body_json)
    res = requests.post(BASE_URL + path, headers=headers, data=body_json).json()

    if res.get("code") != "0" or not res.get("data"):
        log("ERROR", f"❌ BUY ERROR | okx={res}")
        return {"BUY": "ERROR", "okx": res}

    fill = res["data"][0]

    qty = float(
        fill.get("accFillSz")
        or fill.get("fillSz")
        or 0
    )

    if qty <= 0:
        log("WARN", f"⚠️ BUY NO FILL | response={fill}")
        return {"BUY": "NO_FILL", "okx": fill}

    state["step"] += 1
    state["asset_qty"] = round(state["asset_qty"] + qty, 8)
    state["usdt_spent"] = round(state["usdt_spent"] + BUY_USDT, 2)

    save_state(state)

    log(
        "INFO",
        f"🟢 BUY OK | filled={qty} | steps={state['step']} | asset_total={state['asset_qty']}"
    )

    return {
        "BUY": "OK",
        "step": state["step"],
        "qty": qty,
        "asset_total": state["asset_qty"]
    }

# ================== SELL ==================
def sell_spot():
    state = load_state()
    step = state["step"]
    asset_qty = state["asset_qty"]

    if step <= 0:
        log("WARN", "⛔ SELL BLOCKED | step=0")
        return {"SELL": "SKIP", "reason": "step <= 0"}

    sell_percent = 1 / step
    sell_qty = round(asset_qty * sell_percent, 6)

    log(
        "INFO",
        f"🔴 SELL TRY | qty={sell_qty} | step={step} | asset_total={asset_qty}"
    )

    if sell_qty <= 0:
        log("WARN", "⛔ SELL BLOCKED | qty too small")
        return {"SELL": "SKIP", "reason": "qty too small"}

    path = "/api/v5/trade/order"
    body = {
        "instId": SYMBOL,
        "tdMode": "cash",
        "side": "sell",
        "ordType": "market",
        "sz": str(sell_qty)
    }

    body_json = json.dumps(body)
    headers = okx_headers("POST", path, body_json)
    res = requests.post(BASE_URL + path, headers=headers, data=body_json).json()

    if res.get("code") != "0":
        log("ERROR", f"❌ SELL ERROR | okx={res}")
        return {"SELL": "ERROR", "okx": res}

    state["asset_qty"] = round(asset_qty - sell_qty, 8)
    state["step"] -= 1
    save_state(state)

    log(
        "INFO",
        f"✅ SELL OK | sold={sell_qty} | steps NOW={state['step']} | asset_left={state['asset_qty']}"
    )

    return {
        "SELL": "OK",
        "sold_qty": sell_qty,
        "step_after": state["step"],
        "asset_left": state["asset_qty"]
    }

# ================== WEBHOOK ==================
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json or {}
    action = data.get("action")

    if action == "buy":
        return jsonify(buy_spot())

    if action == "sell":
        return jsonify(sell_spot())

    return jsonify({"error": "unknown action"}), 400

# ================== START ==================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
