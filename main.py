@app.route("/webhook", methods=["POST"])
def webhook():
    # 1. Получаем сырые данные, чтобы подпись была точной
    body = request.get_data(as_text=True) 
    if not body:
        return "Empty body", 400

    print("➡️ Received from TV:", body)

    path = "/api/v5/trade/order"
    url = OKX_BASE_URL + path
    
    # 2. OKX требует строго ISO формат с миллисекундами
    timestamp = time.strftime('%Y-%m-%dT%H:%M:%S.000Z', time.gmtime())

    # 3. Генерируем заголовки
    headers = {
        "OK-ACCESS-KEY": OKX_API_KEY,
        "OK-ACCESS-SIGN": sign(timestamp, "POST", path, body),
        "OK-ACCESS-TIMESTAMP": timestamp,
        "OK-ACCESS-PASSPHRASE": OKX_PASSPHRASE,
        "Content-Type": "application/json"
    }

    # 4. Отправляем именно ТУ ЖЕ строку body, что подписали
    response = requests.post(url, headers=headers, data=body)

    print("📊 OKX status code:", response.status_code)
    print("📩 OKX full response:", response.text)

    return jsonify(response.json()), response.status_code
