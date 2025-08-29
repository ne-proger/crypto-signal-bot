import pandas as pd
import pandas_ta as ta

def add_indicators(df: pd.DataFrame, ma_window: int, fast: int, slow: int, signal: int) -> pd.DataFrame:
    # Защита
    df = df.copy()
    # Простая скользящая
    df[f"ma_{ma_window}"] = df["close"].rolling(ma_window).mean()

    # MACD (используем pandas_ta)
    macd = ta.macd(df["close"], fast=fast, slow=slow, signal=signal)
    df["macd"] = macd["MACD_12_26_9"]
    df["macd_signal"] = macd["MACDs_12_26_9"]
    df["macd_hist"] = macd["MACDh_12_26_9"]

    # Объём и его MA для оценки всплесков
    vol_ma_window = max(10, ma_window // 2)
    df[f"vol_ma_{vol_ma_window}"] = df["volume"].rolling(vol_ma_window).mean()

    # Флаги состояний (последняя свеча)
    return df

def latest_snapshot(df: pd.DataFrame, ma_window: int) -> dict:
    last = df.iloc[-1]
    prev = df.iloc[-2] if len(df) >= 2 else last
    snapshot = {
        "close": float(last["close"]),
        "ma": float(last[f"ma_{ma_window}"]),
        "macd": float(last["macd"]),
        "macd_signal": float(last["macd_signal"]),
        "macd_hist": float(last["macd_hist"]),
        "volume": float(last["volume"]),
        "volume_ma": float(last[[c for c in df.columns if c.startswith("vol_ma_")][0]]),
        "ma_trend_up": bool(last[f"ma_{ma_window}"] > prev[f"ma_{ma_window}"]),
        "price_above_ma": bool(last["close"] >= last[f"ma_{ma_window}"]),
        "macd_cross_up": bool(last["macd"] > last["macd_signal"] and prev["macd"] <= prev["macd_signal"]),
        "volume_spike": bool(last["volume"] > 1.5 * last[[c for c in df.columns if c.startswith("vol_ma_")][0]]),
    }
    return snapshot
