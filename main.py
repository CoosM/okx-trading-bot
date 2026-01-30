from flask import Flask, request, jsonify
import os
import time

app = Flask(__name__)

@app.route("/")
def home():
    return "OKX bot is running"

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    print("Webhook received:", data)

    # Тут позже будет реальная логика торговли OKX
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
