import time, hmac, base64, hashlib, json, requests, os
from flask import Flask, request, jsonify

app = Flask(__name__)

def log(msg):
    print(msg, flush=True)

# ===== ENV OKX =====
API_KEY = os.getenv("OKX_API_KEY")
API_SECRET = os.getenv("OKX_API_SECRET")
PASSPHRASE = os.getenv("OKX_PASSPHRASE")

BASE_URL = "https://www.okx.com"

SYMBOL = os.getenv("SYMBOL", "AXS-USDT")
BUY_USDT = os.getenv("BUY_USDT", "16")

MAX_STEPS = 10
STATE_FILE = "state.json"

# ===== STATE (ТОЛЬКО STEP) =====
def load_state():
    if not os.path.exists(STATE_FILE):
        return {"step": 0}
    with open(STATE_FILE, "r") as f:
        return json.load(f)

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

LEVELS = {
    "DEBUG": 10,
    "INFO": 20,
    "WARN": 30,
    "ERROR": 40
}

def log(level, message):
    if LEVELS[level] >= LEVELS.get(LOG_LEVEL, 20):
        print(f"{level} | {message}", flush=True)

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

# ===== GET REAL OKX BALANCE =====
def get_spot_balance():
    path = "/api/v5/account/balance"
    headers = okx_headers("GET", path)
    res = requests.get(BASE_URL + path, headers=headers).json()

    if res.get("code") != "0":
        return 0.0

    base_ccy = SYMBOL.split("-")[0]

    for item in res["data"][0]["details"]:
        if item["ccy"] == base_ccy:
            return float(item["availBal"])

    return 0.0

# ===== BUY =====
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
        "sz": BUY_USDT
    }

    body_json = json.dumps(body)
    headers = okx_headers("POST", path, body_json)
    res = requests.post(BASE_URL + path, headers=headers, data=body_json).json()

    if res.get("code") != "0" or not res.get("data"):
        log("ERROR", f"❌ BUY ERROR | okx={res}")
        return {"BUY": "ERROR", "okx": res}

    fill = res["data"][0]

    # ✅ БЕЗОПАСНОЕ ИЗВЛЕЧЕНИЕ QTY
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
    state["usdt_spent"] = round(state.get("usdt_spent", 0) + float(BUY_USDT), 2)

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

# ===== SELL (1 / step от реального баланса) =====
def sell_spot():
    state = load_state()
    step = state["step"]
    asset_qty = state["asset_qty"]

    if step <= 0:
        log("⛔ SELL BLOCKED | step=0")
        return {"SELL": "SKIP", "reason": "step <= 0"}

    sell_percent = 1 / step
    sell_qty = round(asset_qty * sell_percent, 6)

    log(
        f"🔴 SELL TRY | qty={sell_qty} | "
        f"step={step} | asset_total={asset_qty}"
    )

    if sell_qty <= 0:
        log("⛔ SELL BLOCKED | qty too small")
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
        log(f"❌ SELL ERROR | okx={res}")
        return {"SELL": "ERROR", "okx": res}

    state["asset_qty"] = round(asset_qty - sell_qty, 8)
    state["step"] -= 1
    save_state(state)

    log(
        f"✅ SELL OK | sold={sell_qty} | "
        f"steps NOW={state['step']} | "
        f"asset_left={state['asset_qty']}"
    )

    return {
        "SELL": "OK",
        "sold_qty": sell_qty,
        "step_after": state["step"],
        "asset_left": state["asset_qty"]
    }

# ===== WEBHOOK =====
@app.route("/webhook", methods=["POST"])
def webhook():
    action = request.json.get("action")

    if action == "buy":
        return jsonify(buy_spot())

    if action == "sell":
        return jsonify(sell_spot())

    return jsonify({"error": "unknown action"}), 400

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
