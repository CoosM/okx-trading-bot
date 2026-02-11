import time, hmac, base64, hashlib, json, requests, os
from flask import Flask, request, jsonify
from datetime import datetime
from zoneinfo import ZoneInfo

app = Flask(__name__)

# ================= CONFIG =================

SYMBOL = os.getenv("SYMBOL", "AXS")   # просто AXS
BUY_USDT = float(os.getenv("BUY_USDT", "14"))
MAX_STEPS = 10

USE_BITGET = os.getenv("USE_BITGET", "true").lower() == "true"
USE_OKX = os.getenv("USE_OKX", "false").lower() == "true"

# ================= GITHUB STATE =================

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GIST_ID = os.getenv("GIST_ID")

HEADERS_GIST = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json"
}

cached_state = None

def log(msg):
    now = datetime.now(ZoneInfo("Europe/Kyiv")).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] {msg}", flush=True)

def load_state():
    global cached_state
    try:
        url = f"https://api.github.com/gists/{GIST_ID}"
        r = requests.get(url, headers=HEADERS_GIST, timeout=10)
        r.raise_for_status()
        files = r.json()["files"]

        if "state.json" not in files:
            cached_state = {"bitget": 0, "okx": 0}
            return cached_state

        cached_state = json.loads(files["state.json"]["content"])
        return cached_state
    except:
        return {"bitget": 0, "okx": 0}

def save_state(state):
    global cached_state
    cached_state = state
    url = f"https://api.github.com/gists/{GIST_ID}"
    payload = {
        "files": {
            "state.json": {
                "content": json.dumps(state)
            }
        }
    }
    requests.patch(url, headers=HEADERS_GIST, json=payload, timeout=10)

# ================= BITGET =================

BG_KEY = os.getenv("BITGET_API_KEY")
BG_SECRET = os.getenv("BITGET_SECRET")
BG_PASSPHRASE = os.getenv("BITGET_PASSPHRASE")
BG_URL = "https://api.bitget.com"

symbol_cache = {}

def bitget_headers(method, path, body=""):
    ts = str(int(time.time() * 1000))
    msg = ts + method + path + body
    sign = base64.b64encode(
        hmac.new(BG_SECRET.encode(), msg.encode(), hashlib.sha256).digest()
    ).decode()
    return {
        "ACCESS-KEY": BG_KEY,
        "ACCESS-SIGN": sign,
        "ACCESS-TIMESTAMP": ts,
        "ACCESS-PASSPHRASE": BG_PASSPHRASE,
        "Content-Type": "application/json"
    }

def bitget_symbol_info():
    pair = SYMBOL + "USDT"

    if pair in symbol_cache:
        return symbol_cache[pair]

    path = "/api/v2/spot/public/symbols"
    res = requests.get(BG_URL + path, timeout=10).json()

    if res.get("code") != "00000":
        return 2, 0.0

    for s in res["data"]:
        if s["symbol"] == pair:
            precision = int(s["quantityPrecision"])
            min_size = float(s["minTradeAmount"])
            symbol_cache[pair] = (precision, min_size)
            return precision, min_size

    return 2, 0.0

def bitget_balance():
    path = "/api/v2/spot/account/assets"
    headers = bitget_headers("GET", path)
    res = requests.get(BG_URL + path, headers=headers).json()

    if res.get("code") != "00000":
        return 0.0

    for coin in res["data"]:
        if coin["coin"] == SYMBOL:
            return float(coin["available"])
    return 0.0

def bitget_buy(state):
    if state["bitget"] >= MAX_STEPS:
        return

    path = "/api/v2/spot/trade/place-order"
    body = {
        "symbol": SYMBOL + "USDT",
        "side": "buy",
        "orderType": "market",
        "force": "normal",
        "size": str(BUY_USDT)
    }

    body_json = json.dumps(body)
    headers = bitget_headers("POST", path, body_json)
    res = requests.post(BG_URL + path, headers=headers, data=body_json).json()

    log(f"BITGET BUY RESPONSE: {res}")

    if res.get("code") == "00000":
        state["bitget"] += 1
        log(f"🟢 BITGET BUY | step={state['bitget']}")

def bitget_sell(state):
    step = state["bitget"]
    if step <= 0:
        return

    balance = bitget_balance()
    if balance <= 0:
        log("SELL SKIPPED: balance 0")
        return

    precision, min_size = bitget_symbol_info()

    qty = balance / step
    qty = float(f"{qty:.{precision}f}")

    if qty < min_size:
        log(f"SELL SKIPPED: qty {qty} < min_size {min_size}")
        return

    path = "/api/v2/spot/trade/place-order"
    body = {
        "symbol": SYMBOL + "USDT",
        "side": "sell",
        "orderType": "market",
        "force": "normal",
        "size": str(qty)
    }

    body_json = json.dumps(body)
    headers = bitget_headers("POST", path, body_json)
    res = requests.post(BG_URL + path, headers=headers, data=body_json).json()

    log(f"BITGET SELL RESPONSE: {res}")

    if res.get("code") == "00000":
        state["bitget"] -= 1
        log(f"🔴 BITGET SELL | step={state['bitget']}")

# ================= OKX =================

OKX_KEY = os.getenv("OKX_API_KEY")
OKX_SECRET = os.getenv("OKX_API_SECRET")
OKX_PASS = os.getenv("OKX_PASSPHRASE")
OKX_URL = "https://www.okx.com"

def okx_headers(method, path, body=""):
    ts = time.strftime('%Y-%m-%dT%H:%M:%S.000Z', time.gmtime())
    msg = ts + method + path + body
    sign = base64.b64encode(
        hmac.new(OKX_SECRET.encode(), msg.encode(), hashlib.sha256).digest()
    ).decode()
    return {
        "OK-ACCESS-KEY": OKX_KEY,
        "OK-ACCESS-SIGN": sign,
        "OK-ACCESS-TIMESTAMP": ts,
        "OK-ACCESS-PASSPHRASE": OKX_PASS,
        "Content-Type": "application/json"
    }

def okx_buy(state):
    if state["okx"] >= MAX_STEPS:
        return

    path = "/api/v5/trade/order"
    body = {
        "instId": SYMBOL + "-USDT",
        "tdMode": "cash",
        "side": "buy",
        "ordType": "market",
        "tgtCcy": "quote_ccy",
        "sz": str(BUY_USDT)
    }

    body_json = json.dumps(body)
    headers = okx_headers("POST", path, body_json)
    res = requests.post(OKX_URL + path, headers=headers, data=body_json).json()

    log(f"OKX BUY RESPONSE: {res}")

    if res.get("code") == "0":
        state["okx"] += 1
        log(f"🟢 OKX BUY | step={state['okx']}")

# ================= HEALTH =================

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "cached_state": cached_state
    })

# ================= WEBHOOK =================

@app.route("/webhook", methods=["POST"])
def webhook():
    action = request.json.get("action", "").lower()
    state = load_state()

    if action == "buy":
        if USE_BITGET:
            bitget_buy(state)
        if USE_OKX:
            okx_buy(state)

    if action == "sell":
        if USE_BITGET:
            bitget_sell(state)

    save_state(state)
    return jsonify(state)

# ================= RUN =================

if __name__ == "__main__":
    load_state()
    app.run(host="0.0.0.0", port=5000)
