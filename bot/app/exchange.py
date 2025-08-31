# bot/app/exchange.py

from __future__ import annotations

import os
import logging
from datetime import datetime, timezone
from typing import Optional

import ccxt
import pandas as pd
import requests

log = logging.getLogger("exchange")


class ExchangeClient:
    """
    Обёртка над ccxt для синхронного получения OHLCV.
    Используется run_sync(...) при вызове из асинхронного кода.
    """

    def __init__(self, exchange_id: str | None = None):
        exchange_id = exchange_id or os.getenv("EXCHANGE_ID", "binance")
        proxy_url = (os.getenv("PROXY_URL") or "").strip()

        params: dict = {
            "enableRateLimit": True,
        }

        proxies: dict | None = None
        if proxy_url:
            proxies = {"http": proxy_url, "https": proxy_url}
            params["proxies"] = proxies

            # --- Диагностика доступности прокси ---
            try:
                ip = requests.get("https://api.ipify.org",
                                  proxies=proxies, timeout=8).text
                log.info(f"[Proxy OK] egress IP via proxy: {ip}")
                # Быстрый пинг до Binance через тот же прокси
                r = requests.get("https://api.binance.com/api/v3/exchangeInfo",
                                 proxies=proxies, timeout=8)
                r.raise_for_status()
                log.info("[Proxy OK] Binance reachable via proxy")
            except Exception as e:
                log.error(f"[Proxy ERROR] connectivity check failed: {e}")

        ex_class = getattr(ccxt, exchange_id)
        self.ex = ex_class(params)

    # ВАЖНО: синхронная функция!
    def fetch_ohlcv(
        self, symbol: str, timeframe: str, limit: int
    ) -> Optional[pd.DataFrame]:
        """
        Синхронный вызов CCXT. Вызывается через run_sync(...) из asyncio,
        чтобы не блокировать event loop.
        """
        data = self.ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        if not data:
            return None

        df = pd.DataFrame(
            data, columns=["timestamp", "open", "high", "low", "close", "volume"]
        )
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df.set_index("timestamp", inplace=True)
        return df


def ts_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_exchange():
    """
    Фабрика ccxt-клиента (если где-то нужен «чистый» ccxt без нашей обёртки).
    Прокси также подхватываются из окружения.
    """
    exchange_id = os.getenv("EXCHANGE_ID", "binance")
    proxy_url = (os.getenv("PROXY_URL") or "").strip()

    params: dict = {"enableRateLimit": True}
    if proxy_url:
        params["proxies"] = {"http": proxy_url, "https": proxy_url}

    exchange_class = getattr(ccxt, exchange_id)
    return exchange_class(params)
