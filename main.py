import time, hmac, base64, hashlib, json, requests, os
from flask import Flask, request, jsonify
from datetime import datetime
from zoneinfo import ZoneInfo

app = Flask(__name__)

# ===== ENV =====
EXCHANGE = os.getenv("EXCHANGE", "okx").lower()

SYMBOL = os.getenv("SYMBOL", "AXS-USDT")
BUY_USDT = os.getenv("BUY_USDT", "16")
MAX_STEPS = int(os.getenv("MAX_STEPS", "10"))

# ===== OKX ENV =====
OKX_API_KEY = os.getenv("OKX_API_KEY")
OKX_API_SECRET = os.getenv("OKX_API_SECRET")
OKX_API_PASSPHRASE = os.getenv("OKX_API_PASSPHRASE")
OKX_BASE_URL = "https://www.okx.com"

# ===== BITGET ENV =====
BITGET_API_KEY = os.getenv("BITGET_API_KEY")
BITGET_API_SECRET = os.getenv("BITGET_API_SECRET")
BITGET_API_PASSPHRASE = os.getenv("BITGET_API_PASSPHRASE")
BITGET_BASE_URL = "https://api.bitget.com"

# ===== GIST =====
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GIST_ID = os.getenv("GIST_ID")
STATE_FILE_NAME = "state.json"

HEADERS_GIST = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json"
}

# ===== LOG =====
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
        requests.patch(url, headers=HEADERS_GIST, json=payload, timeout=10)
    except Exception as e:
        log(f"⚠️ save_state error: {e}")

# ===== OKX SIGN =====
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
        "OK-ACCESS-PASSPHRASE": OKX_API_PASSPHRASE,
        "Content-Type": "application/json"
    }

# ===== BITGET SIGN =====
def bitget_headers(method, path, body=""):
    ts = str(int(time.time() * 1000))
    message = ts + method + path + body
    sign = base64.b64encode(
        hmac.new(BITGET_API_SECRET.encode(), message.encode(), hashlib.sha256).digest()
    ).decode()

    return {
        "ACCESS-KEY": BITGET_API_KEY,
        "ACCESS-SIGN": sign,
        "ACCESS-TIMESTAMP": ts,
        "ACCESS-PASSPHRASE": BITGET_API_PASSPHRASE,
        "Content-Type": "application/json"
    }

# ===== GET BALANCE =====
def get_balance():
    if EXCHANGE == "okx":
        path = "/api/v5/account/balance"
        headers = okx_headers("GET", path)
        res = requests.get(OKX_BASE_URL + path, headers=headers).json()

        if res.get("code") != "0":
            return 0.0

        base = SYMBOL.split("-")[0]
        for item in res["data"][0]["details"]:
            if item["ccy"] == base:
                return float(item["availBal"])

    elif EXCHANGE == "bitget":
        path = "/api/spot/v1/account/assets"
        headers = bitget_headers("GET", path)
        res = requests.get(BITGET_BASE_URL + path, headers=headers).json()

        base = SYMBOL.replace("-", "")[:-4]  # AXSUSDT → AXS
        if res.get("code") == "00000":
            for item in res["data"]:
                if item["coinName"] == base:
                    return float(item["available"])

    return 0.0

# ===== BUY =====
def buy_spot():
    state = load_state()

    if state["step"] >= MAX_STEPS:
        return {"BUY": "SKIP", "reason": "max steps reached"}

    if EXCHANGE == "okx":
        path = "/api/v5/trade/order"
        body = {
            "instId": SYMBOL,
            "tdMode": "cash",
            "side": "buy",
            "ordType": "market",
            "tgtCcy": "quote_ccy",
            "sz": BUY_USDT
        }
        headers = okx_headers("POST", path, json.dumps(body))
        res = requests.post(OKX_BASE_URL + path, headers=headers, json=body).json()

    elif EXCHANGE == "bitget":
        path = "/api/spot/v1/trade/orders"
        body = {
            "symbol": SYMBOL.replace("-", ""),
            "side": "buy",
            "orderType": "market",
            "force": "normal",
            "size": BUY_USDT
        }
        headers = bitget_headers("POST", path, json.dumps(body))
        res = requests.post(BITGET_BASE_URL + path, headers=headers, json=body).json()

    else:
        return {"error": "Unknown exchange"}

    state["step"] += 1
    save_state(state)

    log(f"🟢 BUY OK | {EXCHANGE.upper()} | step={state['step']}")
    return {"BUY": "OK", "step": state["step"]}

# ===== SELL =====
def sell_spot():
    state = load_state()
    step = state.get("step", 0)

    if step <= 0:
        return {"SELL": "SKIP", "reason": "step <= 0"}

    balance = get_balance()
    if balance <= 0:
        return {"SELL": "SKIP", "reason": "no balance"}

    sell_percent = 1 / step
    sell_qty = round(balance * sell_percent, 6)

    if EXCHANGE == "okx":
        path = "/api/v5/trade/order"
        body = {
            "instId": SYMBOL,
            "tdMode": "cash",
            "side": "sell",
            "ordType": "market",
            "sz": str(sell_qty)
        }
        headers = okx_headers("POST", path, json.dumps(body))
        res = requests.post(OKX_BASE_URL + path, headers=headers, json=body).json()

    elif EXCHANGE == "bitget":
        path = "/api/spot/v1/trade/orders"
        body = {
            "symbol": SYMBOL.replace("-", ""),
            "side": "sell",
            "orderType": "market",
            "force": "normal",
            "size": str(sell_qty)
        }
        headers = bitget_headers("POST", path, json.dumps(body))
        res = requests.post(BITGET_BASE_URL + path, headers=headers, json=body).json()

    state["step"] -= 1
    save_state(state)

    log(f"🔴 SELL OK | {EXCHANGE.upper()} | step={state['step']}")
    return {"SELL": "OK", "step": state["step"]}

# ===== HEALTH =====
@app.route("/health", methods=["GET"])
def health():
    state = load_state()
    return jsonify({"status": "ok", "exchange": EXCHANGE, "step": state.get("step", 0)})

# ===== WEBHOOK =====
@app.route("/webhook", methods=["POST"])
def webhook():
    action = request.json.get("action")

    if action == "buy":
        return jsonify(buy_spot())

    if action == "sell":
        return jsonify(sell_spot())

    if action == "set_step":
        new_step = int(request.json.get("step", 0))
        state = load_state()
        state["step"] = new_step
        save_state(state)
        return jsonify({"STEP_SET": new_step})

    return jsonify({"error": "unknown action"}), 400

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
