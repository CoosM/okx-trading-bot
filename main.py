from flask import Flask, request, jsonify
import os, time, hmac, hashlib, base64, json, requests

app = Flask(__name__)

TEST_MODE = True

OKX_API_KEY = os.getenv("OKX_API_KEY")
OKX_SECRET_KEY = os.getenv("OKX_SECRET_KEY")
OKX_PASSPHRASE = os.getenv("OKX_PASSPHRASE")
OKX_BASE_URL = os.getenv("OKX_BASE_URL", "https://www.okx.com")

def sign(timestamp, method, path, body):
    message = f"{timestamp}{method}{path}{body}"
    mac = hmac.new(
        OKX_SECRET_KEY.encode(),
        message.encode(),
        hashlib.sha256
    )
    return base64.b64encode(mac.digest()).decode()

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    print("Webhook received:", data)

    if data.get("test") == "BUY" and TEST_MODE:
        print("🟡 TEST MODE: BUY получен")
        print("Данные:", data)
        return {"status": "test_ok"}, 200
        
    body = json.dumps(data)
    path = "/api/v5/trade/order"
    url = OKX_BASE_URL + path
    timestamp = time.strftime('%Y-%m-%dT%H:%M:%S.000Z', time.gmtime())

    headers = {
        "OK-ACCESS-KEY": OKX_API_KEY,
        "OK-ACCESS-SIGN": sign(timestamp, "POST", path, body),
        "OK-ACCESS-TIMESTAMP": timestamp,
        "OK-ACCESS-PASSPHRASE": OKX_PASSPHRASE,
        "Content-Type": "application/json"
    }

    print("Sending to OKX:", body)

    response = requests.post(url, headers=headers, data=body)

    print("OKX status:", response.status_code)
    print("OKX response:", response.text)

    return jsonify({"status": "sent"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
