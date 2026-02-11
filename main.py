import time, hmac, base64, hashlib, json, requests, os
from flask import Flask, request, jsonify
from datetime import datetime
from zoneinfo import ZoneInfo

app = Flask(__name__)

# ===== MODE =====
MODE = os.getenv("MODE", "SINGLE").upper()
EXCHANGE = os.getenv("EXCHANGE", "OKX").upper()

# ===== SYMBOL =====
RAW_SYMBOL = os.getenv("SYMBOL", "BTCUSDT").upper()

def normalize_okx_symbol(sym):
    return sym if "-" in sym else sym[:-4] + "-" + sym[-4:]

def normalize_bitget_symbol(sym):
    return sym.replace("-", "")

SYMBOL_OKX = normalize_okx_symbol(RAW_SYMBOL)
SYMBOL_BITGET = normalize_bitget_symbol(RAW_SYMBOL)

BUY_USDT = os.getenv("BUY_USDT", "20")
MAX_STEPS = 10

# ===== BITGET ENV =====
BITGET_KEY = os.getenv("BITGET_API_KEY")
BITGET_SECRET = os.getenv("BITGET_SECRET")
BITGET_PASS = os.getenv("BITGET_PASSPHRASE")
BITGET_BASE = "https://api.bitget.com"

# ===== GIST =====
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GIST_ID = os.getenv("GIST_ID")
STATE_FILE_NAME = "state.json"

HEADERS_GIST = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json"
}

def log(msg):
    now = datetime.now(ZoneInfo("Europe/Kyiv")).strftime("%H:%M:%S")
    print(f"[{now}] {msg}", flush=True)

# ===== STATE =====
def load_state():
    try:
        r = requests.get(f"https://api.github.com/gists/{GIST_ID}",
                         headers=HEADERS_GIST, timeout=10)
        files = r.json()["files"]
        if STATE_FILE_NAME not in files:
            return {"step": 0}
        return json.loads(files[STATE_FILE_NAME]["content"])
    except:
        return {"step": 0}

def save_state(state):
    try:
        payload = {"files": {STATE_FILE_NAME: {"content": json.dumps(state)}}}
        requests.patch(f"https://api.github.com/gists/{GIST_ID}",
                       headers=HEADERS_GIST, json=payload, timeout=10)
    except:
        pass

# ================= BITGET =================
def bitget_headers(method, path, body=""):
    ts = str(int(time.time() * 1000))
    msg = ts + method + path + body
    sign = base64.b64encode(
        hmac.new(BITGET_SECRET.encode(), msg.encode(), hashlib.sha256).digest()
    ).decode()

    return {
        "ACCESS-KEY": BITGET_KEY,
        "ACCESS-SIGN": sign,
        "ACCESS-TIMESTAMP": ts,
        "ACCESS-PASSPHRASE": BITGET_PASS,
        "Content-Type": "application/json"
    }

def buy_bitget():
    state = load_state()
    log(f"BUY BITGET | step={state['step']}")

    if state["step"] >= MAX_STEPS:
        log("MAX STEPS REACHED")
        return

    path = "/api/spot/v1/trade/orders"

    # ⚠️ ВАЖНО: market buy через quoteQty
    body = {
        "symbol": SYMBOL_BITGET,
        "side": "buy",
        "orderType": "market",
        "force": "normal",
        "quoteQty": BUY_USDT
    }

    body_json = json.dumps(body)
    headers = bitget_headers("POST", path, body_json)

    r = requests.post(BITGET_BASE + path,
                      headers=headers,
                      data=body_json).json()

    log(f"BITGET RESPONSE: {r}")

    if r.get("code") == "00000":
        state["step"] += 1
        save_state(state)
        log(f"BUY SUCCESS | step={state['step']}")
    else:
        log("BUY FAILED")

def sell_bitget():
    state = load_state()
    log(f"SELL BITGET | step={state['step']}")

    if state["step"] <= 0:
        return

    # Получаем баланс
    path = "/api/spot/v1/account/assets"
    headers = bitget_headers("GET", path)
    res = requests.get(BITGET_BASE + path, headers=headers).json()

    log(f"BALANCE RESPONSE: {res}")

    base = SYMBOL_BITGET[:-4]
    balance = 0

    for item in res.get("data", []):
        if item["coinName"] == base:
            balance = float(item["available"])

    if balance <= 0:
        log("NO BALANCE")
        return

    sell_qty = round(balance * (1 / state["step"]), 6)

    order_path = "/api/spot/v1/trade/orders"
    body = {
        "symbol": SYMBOL_BITGET,
        "side": "sell",
        "orderType": "market",
        "force": "normal",
        "size": str(sell_qty)
    }

    body_json = json.dumps(body)
    headers = bitget_headers("POST", order_path, body_json)

    r = requests.post(BITGET_BASE + order_path,
                      headers=headers,
                      data=body_json).json()

    log(f"SELL RESPONSE: {r}")

    if r.get("code") == "00000":
        state["step"] -= 1
        save_state(state)
        log(f"SELL SUCCESS | step={state['step']}")
    else:
        log("SELL FAILED")

# ================= ROUTE =================
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.json
        log(f"WEBHOOK: {data}")

        if not data:
            return jsonify({"error": "no json"}), 400

        action = data.get("action")

        if action == "buy":
            buy_bitget()
        elif action == "sell":
            sell_bitget()
        else:
            return jsonify({"error": "invalid action"}), 400

        return jsonify({"status": "ok"})

    except Exception as e:
        log(f"ERROR: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "exchange": EXCHANGE,
        "mode": MODE,
        "step": load_state().get("step", 0)
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
