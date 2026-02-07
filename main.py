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

# ===== STATE (STEP ONLY, GIST) =====
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

# ===== GET BALANCE =====
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

    log(f"🟢 BUY OK | step={state['step']}")

    return {"BUY": "OK", "step": state["step"]}

# ===== SELL =====
def sell_spot():
    state = load_state()
    step = state.get("step", 0)

    if step <= 0:
        log(f"⛔ SELL BLOCKED | step={step}")
        return {"SELL": "SKIP", "reason": "step <= 0", "step": step}

    balance = get_spot_balance()

    if balance <= 0:
        log(f"⚠️ SELL SKIP | balance=0 | step={step}")
        return {"SELL": "SKIP", "reason": "balance delay", "step": step}

    sell_percent = 1 / step
    sell_qty = round(balance * sell_percent, 6)

    if sell_qty <= 0:
        return {"SELL": "SKIP", "reason": "qty too small"}

    log(
        f"🔴 SELL TRY | balance={balance:.6f} | "
        f"{sell_percent*100:.2f}% | qty={sell_qty} | step={step}"
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

    if res.get("code") != "0":
        return {"SELL": "ERROR", "okx": res}

    state["step"] -= 1
    save_state(state)

    log(f"✅ SELL OK | sold={sell_qty} | step_now={state['step']}")

    return {
        "SELL": "OK",
        "sold_qty": sell_qty,
        "percent": round(sell_percent * 100, 2),
        "step_after": state["step"]
    }

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
        log(f"⚙️ MANUAL STEP SET → {new_step}")
        return jsonify({"STEP_SET": new_step})
    
    return jsonify({"error": "unknown action"}), 400

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
