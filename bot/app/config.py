from dataclasses import dataclass
import os

def _get(name: str, default: str | None = None, required: bool = False) -> str:
    val = os.getenv(name, default)
    if required and (val is None or val == ""):
        raise RuntimeError(f"Missing required env var: {name}")
    return val

@dataclass(frozen=True)
class Settings:
    telegram_token: str
    telegram_channel_id: str
    openai_api_key: str
    openai_model: str
    exchange_id: str
    candles_limit: int
    symbols: list[str]                 # глобальные пары для автоцикла (можешь оставить 1-2)
    ma_window: int
    macd_fast: int
    macd_slow: int
    macd_signal: int
    schedule_seconds: int
    literature_urls: list[str]
    report_locale: str
    state_dir: str
    buy_cooldown_hours: int
    triple_timeframes: list[str]       # <<< НОВОЕ: ["1w","1d","4h"]

def load_settings() -> Settings:
    symbols = [s.strip().upper().replace(":", "/") for s in _get("SYMBOLS", "BTC/USDT").split(",") if s.strip()]
    literature_raw = _get("LITERATURE_URLS", "").replace(",", " ").split()
    triple_tfs = [t.strip() for t in _get("TRIPLE_TFS", "1w,1d,4h").split(",") if t.strip()]
    return Settings(
        telegram_token=_get("TELEGRAM_BOT_TOKEN", required=True),
        telegram_channel_id=_get("TELEGRAM_CHANNEL_ID", required=True),
        openai_api_key=_get("OPENAI_API_KEY", required=True),
        openai_model=_get("OPENAI_MODEL", "gpt-4o-mini"),
        exchange_id=_get("EXCHANGE_ID", "binance"),
        candles_limit=int(_get("CANDLES_LIMIT", "300")),
        symbols=symbols,
        ma_window=int(_get("MA_WINDOW", "50")),
        macd_fast=int(_get("MACD_FAST", "12")),
        macd_slow=int(_get("MACD_SLOW", "26")),
        macd_signal=int(_get("MACD_SIGNAL", "9")),
        schedule_seconds=int(_get("SCHEDULE_SECONDS", "900")),
        literature_urls=literature_raw,
        report_locale=_get("REPORT_LOCALE", "ru"),
        state_dir=_get("BOT_STATE_DIR", "/state"),
        buy_cooldown_hours=int(_get("BUY_COOLDOWN_HOURS", "6")),
        triple_timeframes=triple_tfs,
    )
