import time, hmac, base64, hashlib, json, requests, os
from flask import Flask, request, jsonify
from datetime import datetime
from zoneinfo import ZoneInfo

app = Flask(__name__)

# ===== ENV BITGET =====
API_KEY = os.getenv("BITGET_API_KEY")
API_SECRET = os.getenv("BITGET_API_SECRET")
PASSPHRASE = os.getenv("BITGET_PASSPHRASE")

BASE_URL = "https://api.bitget.com"

SYMBOL = os.getenv("SYMBOL", "AXSUSDT")  # Bitget формат!
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

        requests.patch(url, headers=HEADERS_GIST, json=payload, timeout=10)

    except Exception as e:
        log(f"⚠️ save_state error: {e}")

# ===== BITGET SIGN =====

def bitget_headers(method, path, body=""):
    timestamp = str(int(time.time() * 1000))
    message = timestamp + method.upper() + path + body

    sign = base64.b64encode(
        hmac.new(API_SECRET.encode(), message.encode(), hashlib.sha256).digest()
    ).decode()

    return {
        "ACCESS-KEY": API_KEY,
        "ACCESS-SIGN": sign,
        "ACCESS-TIMESTAMP": timestamp,
        "ACCESS-PASSPHRASE": PASSPHRASE,
        "Content-Type": "application/json"
    }

# ===== GET SPOT BALANCE =====

def get_spot_balance():
    path = "/api/v2/spot/account/assets"
    headers = bitget_headers("GET", path)

    res = requests.get(BASE_URL + path, headers=headers).json()

    if res.get("code") != "00000":
        return 0.0

    base_ccy = SYMBOL.replace("USDT", "")

    for item in res["data"]:
        if item["coin"] == base_ccy:
            return float(item["available"])

    return 0.0

# ===== BUY =====

def buy_spot():
    state = load_state()

    if state["step"] >= MAX_STEPS:
        return {"BUY": "SKIP", "reason": "max steps reached"}

    path = "/api/v2/spot/trade/place-order"

    body = {
        "symbol": SYMBOL,
        "side": "buy",
        "orderType": "market",
        "force": "gtc",
        "size": BUY_USDT,
        "quoteCoin": "USDT"
    }

    body_json = json.dumps(body)
    headers = bitget_headers("POST", path, body_json)

    res = requests.post(BASE_URL + path, headers=headers, data=body_json).json()

    if res.get("code") != "00000":
        return {"BUY": "ERROR", "bitget": res}

    state["step"] += 1
    save_state(state)

    log(f"🟢 BUY OK | step={state['step']}")

    return {"BUY": "OK", "step": state["step"]}

# ===== SELL =====

def sell_spot():
    state = load_state()
    step = state.get("step", 0)

    if step <= 0:
        return {"SELL": "SKIP", "reason": "step <= 0"}

    balance = get_spot_balance()

    if balance <= 0:
        return {"SELL": "SKIP", "reason": "balance 0"}

    sell_percent = 1 / step
    sell_qty = round(balance * sell_percent, 6)

    path = "/api/v2/spot/trade/place-order"

    body = {
        "symbol": SYMBOL,
        "side": "sell",
        "orderType": "market",
        "force": "gtc",
        "size": str(sell_qty)
    }

    body_json = json.dumps(body)
    headers = bitget_headers("POST", path, body_json)

    res = requests.post(BASE_URL + path, headers=headers, data=body_json).json()

    if res.get("code") != "00000":
        return {"SELL": "ERROR", "bitget": res}

    state["step"] -= 1
    save_state(state)

    log(f"🔴 SELL OK | step_now={state['step']}")

    return {"SELL": "OK", "step_after": state["step"]}

# ===== HEALTH =====

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "step": load_state().get("step", 0)
    })

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
