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

def normalize_okx(sym):
    return sym if "-" in sym else sym[:-4] + "-" + sym[-4:]

def normalize_bitget(sym):
    return sym.replace("-", "")

SYMBOL_OKX = normalize_okx(RAW_SYMBOL)
SYMBOL_BITGET = normalize_bitget(RAW_SYMBOL)

BUY_USDT = os.getenv("BUY_USDT", "20")
MAX_STEPS = 10

# ===== OKX ENV =====
OKX_KEY = os.getenv("OKX_API_KEY")
OKX_SECRET = os.getenv("OKX_API_SECRET")
OKX_PASS = os.getenv("OKX_PASSPHRASE")
OKX_BASE = "https://www.okx.com"

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
    now = datetime.now(ZoneInfo("Europe/Kyiv")).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] {msg}", flush=True)

# ================= STATE =================
def load_state():
    try:
        r = requests.get(
            f"https://api.github.com/gists/{GIST_ID}",
            headers=HEADERS_GIST,
            timeout=10
        )
        files = r.json()["files"]
        if STATE_FILE_NAME not in files:
            return {"step": 0}
        return json.loads(files[STATE_FILE_NAME]["content"])
    except:
        return {"step": 0}

def save_state(state):
    try:
        payload = {"files": {STATE_FILE_NAME: {"content": json.dumps(state)}}}
        requests.patch(
            f"https://api.github.com/gists/{GIST_ID}",
            headers=HEADERS_GIST,
            json=payload,
            timeout=10
        )
    except:
        pass

# ================= OKX =================
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

def buy_okx():
    state = load_state()
    log(f"BUY OKX | step={state['step']}")

    if state["step"] >= MAX_STEPS:
        return

    path = "/api/v5/trade/order"
    body = {
        "instId": SYMBOL_OKX,
        "tdMode": "cash",
        "side": "buy",
        "ordType": "market",
        "tgtCcy": "quote_ccy",
        "sz": BUY_USDT
    }

    body_json = json.dumps(body)
    headers = okx_headers("POST", path, body_json)
    r = requests.post(OKX_BASE + path, headers=headers, data=body_json).json()

    log(f"OKX RESPONSE: {r}")

    if r.get("code") == "0":
        state["step"] += 1
        save_state(state)
        log(f"🟢 OKX BUY OK | step={state['step']}")

# ================= BITGET V2 =================
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
        return

    # 1️⃣ Получаем цену
    ticker = requests.get(
        f"{BITGET_BASE}/api/v2/spot/market/tickers?symbol={SYMBOL_BITGET}"
    ).json()

    price = float(ticker["data"][0]["lastPr"])

    # 2️⃣ Считаем количество монет
    qty = round(float(BUY_USDT) / price, 6)

    path = "/api/v2/spot/trade/place-order"

    body = {
        "symbol": SYMBOL_BITGET,
        "side": "buy",
        "orderType": "market",
        "force": "gtc",
        "size": str(qty)
    }

    body_json = json.dumps(body)
    headers = bitget_headers("POST", path, body_json)

    r = requests.post(
        BITGET_BASE + path,
        headers=headers,
        data=body_json
    ).json()

    log(f"BITGET RESPONSE: {r}")

    if r.get("code") == "00000":
        state["step"] += 1
        save_state(state)
        log(f"🟢 BITGET BUY OK | step={state['step']}")
    else:
        log("BUY FAILED")

# ================= ROUTE =================
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    log(f"WEBHOOK: {data}")

    action = data.get("action")

    if MODE == "DUAL":
        if action == "buy":
            buy_okx()
            buy_bitget()
    else:
        if EXCHANGE == "OKX":
            if action == "buy":
                buy_okx()
        elif EXCHANGE == "BITGET":
            if action == "buy":
                buy_bitget()

    return jsonify({"status": "ok", "mode": MODE, "exchange": EXCHANGE})

@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "mode": MODE,
        "exchange": EXCHANGE,
        "step": load_state().get("step", 0)
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
