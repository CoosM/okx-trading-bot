import time, hmac, base64, hashlib, json, requests, os
from flask import Flask, request, jsonify
from datetime import datetime
from zoneinfo import ZoneInfo

app = Flask(__name__)

# =========================================================
# ================== ENABLE EXCHANGES =====================
# =========================================================

USE_BITGET = os.getenv("USE_BITGET", "true").lower() == "true"
USE_OKX = os.getenv("USE_OKX", "false").lower() == "true"

MAX_STEPS = 10
STATE_FILE_NAME = "state.json"

# =========================================================
# ================== STATE CACHE ==========================
# =========================================================

cached_state = None
LAST_KNOWN_STATE = {"bitget": 0, "okx": 0}

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GIST_ID = os.getenv("GIST_ID")

HEADERS_GIST = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json"
}

def log(msg):
    now = datetime.now(ZoneInfo("Europe/Kyiv")).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] {msg}", flush=True)

# =========================================================
# ================== STATE FUNCTIONS ======================
# =========================================================

def load_state():
    global cached_state, LAST_KNOWN_STATE

    if cached_state is not None:
        return cached_state

    try:
        url = f"https://api.github.com/gists/{GIST_ID}"
        r = requests.get(url, headers=HEADERS_GIST, timeout=10)
        r.raise_for_status()

        files = r.json()["files"]

        if STATE_FILE_NAME not in files:
            cached_state = {"bitget": 0, "okx": 0}
        else:
            state = json.loads(files[STATE_FILE_NAME]["content"])
            if "bitget" not in state:
                state = {"bitget": 0, "okx": 0}
            cached_state = state

        LAST_KNOWN_STATE = cached_state
        return cached_state

    except Exception as e:
        log(f"⚠️ load_state error: {e}")
        cached_state = LAST_KNOWN_STATE
        return cached_state


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
        cached_state = state

# =========================================================
# ====================== BITGET ===========================
# =========================================================

BITGET_API_KEY = os.getenv("BITGET_API_KEY")
BITGET_SECRET = os.getenv("BITGET_API_SECRET")
BITGET_PASS = os.getenv("BITGET_PASSPHRASE")
BITGET_SYMBOL = os.getenv("BITGET_SYMBOL", "AXSUSDT")
BITGET_BUY_USDT = os.getenv("BITGET_BUY_USDT", "14")
BITGET_BASE = "https://api.bitget.com"

def bitget_headers(method, path, body=""):
    ts = str(int(time.time() * 1000))
    msg = ts + method.upper() + path + body
    sign = base64.b64encode(
        hmac.new(BITGET_SECRET.encode(), msg.encode(), hashlib.sha256).digest()
    ).decode()

    return {
        "ACCESS-KEY": BITGET_API_KEY,
        "ACCESS-SIGN": sign,
        "ACCESS-TIMESTAMP": ts,
        "ACCESS-PASSPHRASE": BITGET_PASS,
        "Content-Type": "application/json"
    }

def bitget_get_balance():
    path = "/api/v2/spot/account/assets"
    headers = bitget_headers("GET", path)
    res = requests.get(BITGET_BASE + path, headers=headers).json()

    if res.get("code") != "00000":
        return 0.0

    base_ccy = BITGET_SYMBOL.replace("USDT", "")
    for item in res["data"]:
        if item["coin"] == base_ccy:
            return float(item["available"])
    return 0.0

def bitget_buy():
    state = load_state()
    step = state["bitget"]

    if step >= MAX_STEPS:
        return {"status": "max steps reached"}

    path = "/api/v2/spot/trade/place-order"
    body = {
        "symbol": BITGET_SYMBOL,
        "side": "buy",
        "orderType": "market",
        "force": "gtc",
        "size": BITGET_BUY_USDT,
        "quoteCoin": "USDT"
    }

    body_json = json.dumps(body)
    headers = bitget_headers("POST", path, body_json)

    res = requests.post(BITGET_BASE + path, headers=headers, data=body_json).json()
    log(f"📦 BITGET BUY: {res}")

    if res.get("code") != "00000":
        return {"error": res}

    state["bitget"] += 1
    save_state(state)

    return {"status": "buy ok", "step": state["bitget"]}

def bitget_sell():
    state = load_state()
    step = state["bitget"]

    if step <= 0:
        return {"status": "skip", "reason": "step <= 0"}

    balance = bitget_get_balance()
    if balance <= 0:
        return {"status": "skip", "reason": "balance 0"}

    sell_percent = 1 / step
    raw_qty = balance * sell_percent

    sell_qty = float(f"{raw_qty:.2f}")

    path = "/api/v2/spot/trade/place-order"
    body = {
        "symbol": BITGET_SYMBOL,
        "side": "sell",
        "orderType": "market",
        "force": "gtc",
        "size": str(sell_qty)
    }

    body_json = json.dumps(body)
    headers = bitget_headers("POST", path, body_json)

    res = requests.post(BITGET_BASE + path, headers=headers, data=body_json).json()
    log(f"📦 BITGET SELL: {res}")

    if res.get("code") != "00000":
        return {"error": res}

    state["bitget"] -= 1
    save_state(state)

    return {"status": "sell ok", "step": state["bitget"]}

# =========================================================
# ======================== OKX ============================
# =========================================================

OKX_API_KEY = os.getenv("OKX_API_KEY")
OKX_SECRET = os.getenv("OKX_API_SECRET")
OKX_PASS = os.getenv("OKX_PASSPHRASE")
OKX_SYMBOL = os.getenv("OKX_SYMBOL", "AXS-USDT")
OKX_BUY_USDT = os.getenv("OKX_BUY_USDT", "16")
OKX_BASE = "https://www.okx.com"

def okx_headers(method, path, body=""):
    ts = time.strftime('%Y-%m-%dT%H:%M:%S.000Z', time.gmtime())
    msg = ts + method + path + body
    sign = base64.b64encode(
        hmac.new(OKX_SECRET.encode(), msg.encode(), hashlib.sha256).digest()
    ).decode()

    return {
        "OK-ACCESS-KEY": OKX_API_KEY,
        "OK-ACCESS-SIGN": sign,
        "OK-ACCESS-TIMESTAMP": ts,
        "OK-ACCESS-PASSPHRASE": OKX_PASS,
        "Content-Type": "application/json"
    }

def okx_get_balance():
    path = "/api/v5/account/balance"
    headers = okx_headers("GET", path)
    res = requests.get(OKX_BASE + path, headers=headers).json()

    if res.get("code") != "0":
        return 0.0

    base_ccy = OKX_SYMBOL.split("-")[0]
    for item in res["data"][0]["details"]:
        if item["ccy"] == base_ccy:
            return float(item["availBal"])
    return 0.0

def okx_buy():
    state = load_state()
    step = state["okx"]

    if step >= MAX_STEPS:
        return {"status": "max steps reached"}

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

    res = requests.post(OKX_BASE + path, headers=headers, data=body_json).json()
    log(f"📦 OKX BUY: {res}")

    if res.get("code") != "0":
        return {"error": res}

    state["okx"] += 1
    save_state(state)

    return {"status": "buy ok", "step": state["okx"]}

def okx_sell():
    state = load_state()
    step = state["okx"]

    if step <= 0:
        return {"status": "skip", "reason": "step <= 0"}

    balance = okx_get_balance()
    if balance <= 0:
        return {"status": "skip", "reason": "balance 0"}

    sell_percent = 1 / step
    sell_qty = round(balance * sell_percent, 6)

    path = "/api/v5/trade/order"
    body = {
        "instId": OKX_SYMBOL,
        "tdMode": "cash",
        "side": "sell",
        "ordType": "market",
        "sz": str(sell_qty)
    }

    body_json = json.dumps(body)
    headers = okx_headers("POST", path, body_json)

    res = requests.post(OKX_BASE + path, headers=headers, data=body_json).json()
    log(f"📦 OKX SELL: {res}")

    if res.get("code") != "0":
        return {"error": res}

    state["okx"] -= 1
    save_state(state)

    return {"status": "sell ok", "step": state["okx"]}

# =========================================================
# ======================== WEBHOOK ========================
# =========================================================

@app.route("/webhook", methods=["POST"])
def webhook():
    action = request.json.get("action")
    result = {}

    if action == "buy":
        if USE_BITGET:
            result["bitget"] = bitget_buy()
        if USE_OKX:
            result["okx"] = okx_buy()
        return jsonify(result)

    if action == "sell":
        if USE_BITGET:
            result["bitget"] = bitget_sell()
        if USE_OKX:
            result["okx"] = okx_sell()
        return jsonify(result)

    return jsonify({"error": "unknown action"}), 400

@app.route("/health")
def health():
    global cached_state
    if cached_state is None:
        cached_state = LAST_KNOWN_STATE

    return jsonify({
        "status": "ok",
        "state": cached_state,
        "bitget_enabled": USE_BITGET,
        "okx_enabled": USE_OKX
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
