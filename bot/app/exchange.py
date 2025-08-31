# bot/app/exchange.py

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

import ccxt
import pandas as pd


class ExchangeClient:
    """
    Обёртка над ccxt для синхронного получения OHLCV.
    Используется run_sync(...) при вызове из асинхронного кода.
    """

    def __init__(self, exchange_id: str | None = None):
        # Биржу берём из аргумента или из окружения
        exchange_id = exchange_id or os.getenv("EXCHANGE_ID", "binance")

        # Прокси (опционально)
        proxy_url = (os.getenv("PROXY_URL") or "").strip()

        params: dict = {
            "enableRateLimit": True,
        }
        if proxy_url:
            # ccxt использует requests, ему подаем proxies в таком виде
            params["proxies"] = {
                "http": proxy_url,
                "https": proxy_url,
            }

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

    params: dict = {
        "enableRateLimit": True,
    }
    if proxy_url:
        params["proxies"] = {
            "http": proxy_url,
            "https": proxy_url,
        }

    exchange_class = getattr(ccxt, exchange_id)
    return exchange_class(params)
