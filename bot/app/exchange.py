import ccxt
import pandas as pd
from datetime import datetime, timezone
from typing import Optional
import os
import logging

log = logging.getLogger("exchange")

class ExchangeClient:
    def __init__(self, exchange_id: str):
        proxy_url = os.getenv("PROXY_URL")
        params = {
            "enableRateLimit": True,
            "timeout": 60000,  # 60s на всякий случай
        }

        if proxy_url:
            params["proxies"] = {
                "http": proxy_url,
                "https": proxy_url,
            }

        ex_class = getattr(ccxt, exchange_id)
        self.ex = ex_class(params)

        # покажем, что ccxt реально видит прокси
        try:
            sess = getattr(self.ex, "session", None)
            log.info("CCXT session proxies: %s", getattr(sess, "proxies", None))
        except Exception:
            pass

    def fetch_ohlcv(
        self, symbol: str, timeframe: str, limit: int
    ) -> Optional[pd.DataFrame]:
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
