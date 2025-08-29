# Crypto Signal Bot (Telegram + CCXT + Indicators + ChatGPT)

Телеграм‑бот, который по расписанию:
1) Тянет OHLCV по ряду инструментов (через CCXT).
2) Считает MA, MACD, объём.
3) Отправляет снэпшот в LLM (ChatGPT) с жёстким JSON‑форматом.
4) Если `buy_signal=true` — публикует сигнал в Telegram‑канал, где он админ.

## Запуск

```bash
cp .env.example .env
# отредактируй .env (токены, символы, канал)

docker compose up --build
