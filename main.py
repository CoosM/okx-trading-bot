state time, hmac, base64, hashlib, json, requests, os
from flask import Flask, request, jsonify

app = Flask(__name__)

# ===== ENV OKX =====
API_KEY = os.getenv("OKX_API_KEY")
API_SECRET = os.getenv("OKX_API_SECRET")
PASSPHRASE = os.getenv("OKX_PASSPHRASE")

BASE_URL = "https://www.okx.com"

SYMBOL = os.getenv("SYMBOL", "AXS-USDT")
BUY_USDT = os.getenv("BUY_USDT", "16")

MAX_STEPS = 10
STATE_FILE = "state.json"

def log(msg):
    print(msg, flush=True)

# ===== STATE (ТОЛЬКО STEP) =====
def load_state():
    if not os.path.exists(STATE_FILE):
        return {"step": 0}
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
        return {"BUY": "SKIP", "reason": "max steps reached"}

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

    if res.get("code") != "0":
        return {"BUY": "ERROR", "okx": res}

    state["step"] += 1
    save_state(state)

    return {
        "BUY": "OK",
        "step": state["step"]
    }

# ===== SELL (1 / step от реального баланса) =====
def sell_spot():
    state = load_state()
    step = state.get("step", 0)

    # --- STEP CHECK ---
    if step <= 0:
        log(f"⛔ SELL BLOCKED | reason=step<=0 | step={step}")
        return {"SELL": "SKIP", "reason": "step <= 0", "step": step}

    # --- BALANCE CHECK ---
    balance = get_spot_balance()

    if balance <= 0:
        log(f"⛔ SELL BLOCKED | reason=no_balance | balance={balance} | step={step}")
        return {"SELL": "SKIP", "reason": "no balance", "step": step}

    # --- QTY CALC ---
    sell_percent = 1 / step
    sell_qty = round(balance * sell_percent, 6)

    if sell_qty <= 0:
        log(
            f"⛔ SELL BLOCKED | reason=qty_too_small | "
            f"balance={balance} | step={step} | qty={sell_qty}"
        )
        return {
            "SELL": "SKIP",
            "reason": "qty too small",
            "step": step,
            "balance": balance
        }

    # --- TRY SELL ---
    log(
        f"🔴 SELL TRY | balance={balance:.6f} | "
        f"percent={sell_percent*100:.2f}% | qty={sell_qty} | step={step}"
    )

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

    # --- OKX ERROR ---
    if res.get("code") != "0":
        log(f"❌ SELL ERROR | okx={res}")
        return {"SELL": "ERROR", "okx": res}

    # --- SUCCESS ---
    state["step"] -= 1
    save_state(state)

    log(
        f"✅ SELL OK | sold={sell_qty} | "
        f"step_before={step} | step_now={state['step']}"
    )

    return {
        "SELL": "OK",
        "sold_qty": sell_qty,
        "percent": round(sell_percent * 100, 2),
        "step_before": step,
        "step_after": state["step"]
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
