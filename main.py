import time, hmac, base64, hashlib, json, requests, os
from flask import Flask, request, jsonify
from datetime import datetime
from zoneinfo import ZoneInfo

app = Flask(__name__)

# ===== EXCHANGE =====
ENABLE_OKX = os.getenv("ENABLE_OKX", "true").lower() == "true"
ENABLE_BITGET = os.getenv("ENABLE_BITGET", "true").lower() == "true"

# ================= CONFIG =================

MAX_STEPS = 10

# ===== OKX =====
OKX_API_KEY = os.getenv("OKX_API_KEY")
OKX_API_SECRET = os.getenv("OKX_API_SECRET")
OKX_PASSPHRASE = os.getenv("OKX_PASSPHRASE")
OKX_SYMBOL = os.getenv("OKX_SYMBOL", "AXS-USDT")
OKX_BUY_USDT = os.getenv("OKX_BUY_USDT", "16")
OKX_BASE_URL = "https://www.okx.com"

# ===== BITGET =====
BITGET_API_KEY = os.getenv("BITGET_API_KEY")
BITGET_API_SECRET = os.getenv("BITGET_API_SECRET")
BITGET_PASSPHRASE = os.getenv("BITGET_PASSPHRASE")
BITGET_SYMBOL = os.getenv("BITGET_SYMBOL", "AXSUSDT")
BITGET_BUY_USDT = os.getenv("BITGET_BUY_USDT", "16")
BITGET_BASE_URL = "https://api.bitget.com"

# ===== GITHUB =====
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GIST_ID = os.getenv("GIST_ID")
STATE_FILE_NAME = "state.json"

HEADERS_GIST = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json"
}

# ================= MEMORY PROTECTION =================

cached_state = {"okx_step": 0, "bitget_step": 0}
LAST_KNOWN_STATE = {"okx_step": 0, "bitget_step": 0}

# ================= LOG =================

def log(msg):
    now = datetime.now(ZoneInfo("Europe/Kyiv")).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] {msg}", flush=True)

# ================= STATE =================

def load_state():
    global cached_state, LAST_KNOWN_STATE

    try:
        url = f"https://api.github.com/gists/{GIST_ID}"
        r = requests.get(url, headers=HEADERS_GIST, timeout=10)
        r.raise_for_status()

        files = r.json()["files"]
        if STATE_FILE_NAME not in files:
            return cached_state

        data = json.loads(files[STATE_FILE_NAME]["content"])

        if "okx_step" in data and "bitget_step" in data:
            cached_state = data
            LAST_KNOWN_STATE = data
            return cached_state

        log("⚠️ Invalid state format. Using LAST_KNOWN_STATE")
        return LAST_KNOWN_STATE

    except Exception as e:
        log(f"⚠️ load_state error: {e}")
        return LAST_KNOWN_STATE


def save_state(state):
    global cached_state, LAST_KNOWN_STATE

    try:
        url = f"https://api.github.com/gists/{GIST_ID}"
        payload = {
            "files": {
                STATE_FILE_NAME: {
                    "content": json.dumps(state)
                }
            }
        }

        r = requests.patch(url, headers=HEADERS_GIST, json=payload, timeout=10)
        r.raise_for_status()

        cached_state = state
        LAST_KNOWN_STATE = state

    except Exception as e:
        log(f"⚠️ save_state error: {e}")
        log("⚠️ Keeping LAST_KNOWN_STATE (no reset)")

# ================= OKX =================

def okx_headers(method, path, body=""):
    ts = time.strftime('%Y-%m-%dT%H:%M:%S.000Z', time.gmtime())
    msg = ts + method + path + body
    sign = base64.b64encode(
        hmac.new(OKX_API_SECRET.encode(), msg.encode(), hashlib.sha256).digest()
    ).decode()

    return {
        "OK-ACCESS-KEY": OKX_API_KEY,
        "OK-ACCESS-SIGN": sign,
        "OK-ACCESS-TIMESTAMP": ts,
        "OK-ACCESS-PASSPHRASE": OKX_PASSPHRASE,
        "Content-Type": "application/json"
    }

def okx_balance():
    path = "/api/v5/account/balance"
    headers = okx_headers("GET", path)
    res = requests.get(OKX_BASE_URL + path, headers=headers).json()

    if res.get("code") != "0":
        return 0.0

    base = OKX_SYMBOL.split("-")[0]
    for d in res["data"][0]["details"]:
        if d["ccy"] == base:
            return float(d["availBal"])
    return 0.0

def okx_buy():
    state = load_state()
    step = state["okx_step"]

    if step >= MAX_STEPS:
        return {"OKX_BUY": "MAX_STEPS"}

    path = "/api/v5/trade/order"
    body = {
        "instId": OKX_SYMBOL,
        "tdMode": "cash",
        "side": "buy",
        "ordType": "market",
        "tgtCcy": "quote_ccy",
        "sz": OKX_BUY_USDT
    }

    body_json = json.dumps(body)
    headers = okx_headers("POST", path, body_json)
    res = requests.post(OKX_BASE_URL + path, headers=headers, data=body_json).json()

    if res.get("code") != "0":
        return {"OKX_BUY": "ERROR", "response": res}

    state["okx_step"] += 1
    save_state(state)
    return {"OKX_BUY": "OK", "step": state["okx_step"]}

def okx_sell():
    state = load_state()
    step = state["okx_step"]

    if step <= 0:
        return {"OKX_SELL": "NO_STEP"}

    balance = okx_balance()
    if balance <= 0:
        return {"OKX_SELL": "NO_BALANCE"}

    percent = 1 / step
    qty = round(balance * percent, 6)

    path = "/api/v5/trade/order"
    body = {
        "instId": OKX_SYMBOL,
        "tdMode": "cash",
        "side": "sell",
        "ordType": "market",
        "sz": str(qty)
    }

    body_json = json.dumps(body)
    headers = okx_headers("POST", path, body_json)
    res = requests.post(OKX_BASE_URL + path, headers=headers, data=body_json).json()

    if res.get("code") != "0":
        return {"OKX_SELL": "ERROR", "response": res}

    state["okx_step"] -= 1
    save_state(state)
    return {"OKX_SELL": "OK", "step": state["okx_step"]}

# ================= BITGET =================

def bitget_headers(method, path, body=""):
    ts = str(int(time.time() * 1000))
    msg = ts + method + path + body
    sign = base64.b64encode(
        hmac.new(BITGET_API_SECRET.encode(), msg.encode(), hashlib.sha256).digest()
    ).decode()

    return {
        "ACCESS-KEY": BITGET_API_KEY,
        "ACCESS-SIGN": sign,
        "ACCESS-TIMESTAMP": ts,
        "ACCESS-PASSPHRASE": BITGET_PASSPHRASE,
        "Content-Type": "application/json"
    }

def bitget_buy():
    state = load_state()
    step = state["bitget_step"]

    if step >= MAX_STEPS:
        return {"BITGET_BUY": "MAX_STEPS"}

    path = "/api/v2/spot/trade/place-order"
    
    body = {
        "symbol": BITGET_SYMBOL,
        "side": "buy",
        "orderType": "market",
        "force": "normal",
        "size": BITGET_BUY_USDT
    }

    body_json = json.dumps(body)
    headers = bitget_headers("POST", path, body_json)
    res = requests.post(BITGET_BASE_URL + path, headers=headers, data=body_json).json()

    log(f"🟢 BITGET BUY RESPONSE: {res}")

    if res.get("code") != "00000":
        return {"BITGET_BUY": "ERROR", "response": res}

    state["bitget_step"] += 1
    save_state(state)
    return {"BITGET_BUY": "OK", "step": state["bitget_step"]}

def bitget_sell():
    state = load_state()
    step = state["bitget_step"]

    if step <= 0:
        return {"BITGET_SELL": "NO_STEP"}

    percent = 1 / step

    path_balance = "GET /api/v2/spot/account/assets"
    headers_balance = bitget_headers("GET", path_balance)
    bal = requests.get(BITGET_BASE_URL + path_balance, headers=headers_balance).json()

    log(f"🔵 BITGET BALANCE RESPONSE: {bal}")
    
    base = BITGET_SYMBOL.replace("USDT", "")
    balance = 0.0

    if bal.get("code") == "00000":
        for a in bal["data"]:
            if a["coinName"] == base:
                balance = float(a["available"])
                break

    if balance <= 0:
        return {"BITGET_SELL": "NO_BALANCE"}

    qty = round(balance * percent, 6)

    path = "/api/spot/v1/trade/orders"
    body = {
        "symbol": BITGET_SYMBOL,
        "side": "sell",
        "orderType": "market",
        "force": "normal",
        "size": str(qty)
    }

    body_json = json.dumps(body)
    headers = bitget_headers("POST", path, body_json)
    res = requests.post(BITGET_BASE_URL + path, headers=headers, data=body_json).json()

    if res.get("code") != "00000":
        return {"BITGET_SELL": "ERROR", "response": res}

    state["bitget_step"] -= 1
    save_state(state)
    return {"BITGET_SELL": "OK", "step": state["bitget_step"]}

# ================= ROUTES =================

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "cached_state": cached_state
    })

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    action = data.get("action")
    exchange = data.get("exchange")

    if action == "buy":
        return jsonify(okx_buy() if exchange == "okx" else bitget_buy())

    if action == "sell":
        return jsonify(okx_sell() if exchange == "okx" else bitget_sell())

    if action == "set_step":
        state = load_state()
        step = int(data.get("step", 0))

        if exchange == "okx":
            state["okx_step"] = step
        else:
            state["bitget_step"] = step

        save_state(state)
        return jsonify({"STEP_SET": step})

    return jsonify({"error": "unknown action"}), 400

# ================= START =================

if __name__ == "__main__":
    load_state()
    app.run(host="0.0.0.0", port=5000)
