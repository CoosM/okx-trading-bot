import time, hmac, base64, hashlib, json, requests, os
from flask import Flask, request, jsonify
from datetime import datetime
from zoneinfo import ZoneInfo

app = Flask(__name__)

# ===== ENV OKX =====
API_KEY = os.getenv("OKX_API_KEY")
API_SECRET = os.getenv("OKX_API_SECRET")
PASSPHRASE = os.getenv("OKX_PASSPHRASE")

BASE_URL = "https://www.okx.com"

# ===== ENV BITGET =====
BITGET_API_KEY = os.getenv("BITGET_API_KEY")
BITGET_SECRET_KEY = os.getenv("BITGET_SECRET_KEY")
BITGET_PASSPHRASE = os.getenv("BITGET_PASSPHRASE")
BITGET_BASE_URL = "https://api.bitget.com"

SYMBOL = os.getenv("SYMBOL", "AXS-USDT")
BUY_USDT = os.getenv("BUY_USDT", "16")

MAX_STEPS = 10

# ===== GIST STATE =====
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GIST_ID = os.getenv("GIST_ID")
STATE_FILE_NAME = "state.json"

HEADERS_GIST = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json"
}

def log(msg):
    now = datetime.now(ZoneInfo("Europe/Kyiv")).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] {msg}", flush=True)

# ===== STATE =====
def load_state():
    try:
        url = f"https://api.github.com/gists/{GIST_ID}"
        r = requests.get(url, headers=HEADERS_GIST, timeout=10)
        r.raise_for_status()

        files = r.json()["files"]
        if STATE_FILE_NAME not in files:
            return {"step": 0}

        return json.loads(files[STATE_FILE_NAME]["content"])
    except Exception as e:
        log(f"⚠️ load_state error: {e}")
        return {"step": 0}

def save_state(state):
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
    except Exception as e:
        log(f"⚠️ save_state error: {e}")

# ================= OKX =================

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

    log(f"🟢 OKX BUY OK | step={state['step']}")
    return {"BUY": "OK", "step": state["step"]}

def sell_spot():
    state = load_state()
    step = state.get("step", 0)

    if step <= 0:
        return {"SELL": "SKIP", "reason": "step <= 0"}

    balance = get_spot_balance()
    if balance <= 0:
        return {"SELL": "SKIP", "reason": "balance delay"}

    sell_percent = 1 / step
    sell_qty = round(balance * sell_percent, 6)

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
        return {"SELL": "ERROR", "okx": res}

    state["step"] -= 1
    save_state(state)

    log(f"🔴 OKX SELL OK | step={state['step']}")
    return {"SELL": "OK", "step_after": state["step"]}

# ================= BITGET =================

def bitget_headers(method, path, body=""):
    ts = str(int(time.time() * 1000))
    message = ts + method + path + body
    sign = base64.b64encode(
        hmac.new(BITGET_SECRET_KEY.encode(), message.encode(), hashlib.sha256).digest()
    ).decode()

    return {
        "ACCESS-KEY": BITGET_API_KEY,
        "ACCESS-SIGN": sign,
        "ACCESS-TIMESTAMP": ts,
        "ACCESS-PASSPHRASE": BITGET_PASSPHRASE,
        "Content-Type": "application/json"
    }

def get_bitget_balance():
    path = "/api/spot/v1/account/assets"
    headers = bitget_headers("GET", path)
    res = requests.get(BITGET_BASE_URL + path, headers=headers).json()

    if res.get("code") != "00000":
        return 0.0

    base_ccy = SYMBOL.split("-")[0]
    for item in res["data"]:
        if item["coinName"] == base_ccy:
            return float(item["available"])

    return 0.0

def buy_bitget():
    state = load_state()
    if state["step"] >= MAX_STEPS:
        return {"BUY": "SKIP", "reason": "max steps reached"}

    path = "/api/spot/v1/trade/orders"
    body = {
        "symbol": SYMBOL.replace("-", ""),
        "side": "buy",
        "orderType": "market",
        "force": "normal",
        "size": BUY_USDT
    }

    body_json = json.dumps(body)
    headers = bitget_headers("POST", path, body_json)
    res = requests.post(BITGET_BASE_URL + path, headers=headers, data=body_json).json()

    if res.get("code") != "00000":
        return {"BUY": "ERROR", "bitget": res}

    state["step"] += 1
    save_state(state)

    log(f"🟢 BITGET BUY OK | step={state['step']}")
    return {"BUY": "OK", "step": state["step"]}

def sell_bitget():
    state = load_state()
    step = state.get("step", 0)

    if step <= 0:
        return {"SELL": "SKIP", "reason": "step <= 0"}

    balance = get_bitget_balance()
    if balance <= 0:
        return {"SELL": "SKIP", "reason": "balance delay"}

    sell_percent = 1 / step
    sell_qty = round(balance * sell_percent, 6)

    path = "/api/spot/v1/trade/orders"
    body = {
        "symbol": SYMBOL.replace("-", ""),
        "side": "sell",
        "orderType": "market",
        "force": "normal",
        "size": str(sell_qty)
    }

    body_json = json.dumps(body)
    headers = bitget_headers("POST", path, body_json)
    res = requests.post(BITGET_BASE_URL + path, headers=headers, data=body_json).json()

    if res.get("code") != "00000":
        return {"SELL": "ERROR", "bitget": res}

    state["step"] -= 1
    save_state(state)

    log(f"🔴 BITGET SELL OK | step={state['step']}")
    return {"SELL": "OK", "step_after": state["step"]}

# ================= ROUTES =================

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "step": load_state().get("step", 0)
    })

@app.route("/webhook", methods=["POST"])
def webhook_okx():
    action = request.json.get("action")
    if action == "buy":
        return jsonify(buy_spot())
    if action == "sell":
        return jsonify(sell_spot())
    return jsonify({"error": "unknown action"}), 400

@app.route("/webhook_bitget", methods=["POST"])
def webhook_bitget():
    action = request.json.get("action")
    if action == "buy":
        return jsonify(buy_bitget())
    if action == "sell":
        return jsonify(sell_bitget())
    return jsonify({"error": "unknown action"}), 400

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
