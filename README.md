# TradingView Engulfing + RSI DCA Exit % (Auto Bot)

Автоматическая система исполнения DCA-стратегии через TradingView Webhook.

## Стратегия

- RSI + Engulfing сигналы.
- Automatic DCA BUY.
- Dynamic DCA EXIT (%).

Процент продажи зависит от количества открытых DCA-шагов.

| Step | Sell |
|-----:|-----:|
| 1 | 100% |
| 2 | 50% |
| 3 | 33.33% |
| 4 | 25% |
| ... | ... |
| N | 1 / Step |

- BUY → Step +1
- SELL → Step -1
- State сохраняется после перезапуска сервера.

## Архитектура

```text
TradingView
      │
      ▼
Webhook
      │
      ▼
Flask API (Render)
      │
      ▼
OKX / Bitget
      │
      ▼
GitHub Gist (state.json)
      │
      ▼
UptimeRobot
```

## Возможности

- TradingView Webhook
- RSI + Engulfing Strategy
- Dynamic DCA Exit %
- Automatic BUY / SELL
- Manual Step Control
- GitHub Gist State Storage
- OKX Spot API
- Bitget Spot API
- Render Hosting
- UptimeRobot Monitoring

## Технологии

- Python
- Flask
- Pine Script v4
- TradingView
- OKX API
- Bitget API
- GitHub API
- Render
- UptimeRobot

## Разработка

- 📅 Период разработки: **21.01.2026 → 01.02.2026**
- ⏱️ 11 дней
- 💻 ≈18 часов каждый день
- 🕒 ≈198 часов общей разработки

## Статус

✅ Завершён

Работает на реальном торговом аккаунте более **2 месяцев**.

---

> Цель достигнута.
> После завершения разработки стратегия работает автоматически.

---

> **99% видят код.  
> 1% — систему.**
