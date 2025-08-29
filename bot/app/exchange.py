import ccxt
import pandas as pd
from datetime import datetime, timezone
from typing import Optional

class ExchangeClient:
    def __init__(self, exchange_id: str):
        ex_class = getattr(ccxt, exchange_id)
        self.ex = ex_class({"enableRateLimit": True})

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
