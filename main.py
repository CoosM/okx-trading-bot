import time, hmac, base64, hashlib, json, requests, os
from flask import Flask, request, jsonify

app = Flask(__name__)

# ===== ENV OKX =====
API_KEY = os.getenv("OKX_API_KEY")
API_SECRET = os.getenv("OKX_API_SECRET")
PASSPHRASE = os.getenv("OKX_PASSPHRASE")

BASE_URL = "https://www.okx.com"

SYMBOL = os.getenv("SYMBOL", "AXS-USDT")
BUY_USDT = os.getenv("BUY_USDT", "16")

STATE_FILE = "state.json"

# ===== STATE =====
def load_state():
    if not os.path.exists(STATE_FILE):
        return {"step": 0, "asset_qty": 0}
    with open(STATE_FILE, "r") as f:
        return json.load(f)

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)

# ===== SIGN =====
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

# ===== BUY =====
def buy_spot():
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
    res = requests.post(url, headers=headers, data=body_json).json()

    try:
        fill = res["data"][0]
        qty = float(fill["accFillSz"])
    except:
        return res

    state = load_state()
    state["step"] += 1
    state["asset_qty"] += qty
    save_state(state)

    return {"BUY": "OK", "step": state["step"], "qty": qty}

# ===== SELL (1 / step) =====
def sell_spot():
    state = load_state()

    if state["step"] <= 0 or state["asset_qty"] <= 0:
        return {"SELL": "SKIP", "reason": "no position"}

    sell_percent = 1 / state["step"]
    sell_qty = round(state["asset_qty"] * sell_percent, 6)

    path = "/api/v5/trade/order"
    url = BASE_URL + path

    body = {
        "instId": SYMBOL,
        "tdMode": "cash",
        "side": "sell",
        "ordType": "market",
        "sz": str(sell_qty)
    }

    body_json = json.dumps(body)
    headers = okx_headers("POST", path, body_json)
    res = requests.post(url, headers=headers, data=body_json).json()

    state["asset_qty"] -= sell_qty
    state["step"] -= 1
    save_state(state)

    return {
        "SELL": "OK",
        "sold_qty": sell_qty,
        "percent": round(sell_percent * 100, 2),
        "step_after": state["step"]
    }

# ===== WEBHOOK =====
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    action = data.get("action")

    if action == "buy":
        return jsonify(buy_spot())

    if action == "sell":
        return jsonify(sell_spot())

    return jsonify({"error": "unknown action"}), 400

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
