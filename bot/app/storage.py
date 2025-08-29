import sqlite3
import os
from typing import Optional, List
from datetime import datetime, timezone

class Storage:
    def __init__(self, state_dir: str):
        os.makedirs(state_dir, exist_ok=True)
        self.path = os.path.join(state_dir, "state.db")
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.path) as con:
            con.execute("""
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_utc TEXT NOT NULL,
                symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                decision TEXT NOT NULL, -- BUY/NO_BUY
                confidence REAL NOT NULL,
                reason TEXT
            )
            """)
            con.execute("CREATE INDEX IF NOT EXISTS idx_symbol_tf ON signals(symbol, timeframe)")
            con.execute("""
            CREATE TABLE IF NOT EXISTS users (
                chat_id INTEGER PRIMARY KEY,
                symbol TEXT,
                timeframe TEXT
            )
            """)
            # Глобальные настройки бота (ключ-значение)
            con.execute("""
            CREATE TABLE IF NOT EXISTS app_kv (
                k TEXT PRIMARY KEY,
                v TEXT
            )
            """)

    # ---------- signals ----------
    def last_buy_ts(self, symbol: str, timeframe: str) -> Optional[str]:
        with sqlite3.connect(self.path) as con:
            cur = con.execute("""
                SELECT ts_utc FROM signals
                WHERE symbol=? AND timeframe=? AND decision='BUY'
                ORDER BY id DESC LIMIT 1
            """, (symbol, timeframe))
            row = cur.fetchone()
            return row[0] if row else None

    def insert_signal(self, symbol: str, timeframe: str, decision: str, confidence: float, reason: str):
        with sqlite3.connect(self.path) as con:
            con.execute("""
                INSERT INTO signals (ts_utc, symbol, timeframe, decision, confidence, reason)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (datetime.now(timezone.utc).isoformat(timespec="seconds"),
                  symbol, timeframe, decision, float(confidence), reason))

    # ---------- user prefs (персистентные личные) ----------
    def get_user_prefs(self, chat_id: int) -> tuple[Optional[str], Optional[str]]:
        with sqlite3.connect(self.path) as con:
            cur = con.execute("SELECT symbol, timeframe FROM users WHERE chat_id=?", (chat_id,))
            row = cur.fetchone()
            return (row[0], row[1]) if row else (None, None)

    def set_user_symbol(self, chat_id: int, symbol: str) -> None:
        with sqlite3.connect(self.path) as con:
            con.execute("""
                INSERT INTO users(chat_id, symbol)
                VALUES(?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET symbol=excluded.symbol
            """, (chat_id, symbol))

    def set_user_timeframe(self, chat_id: int, timeframe: str) -> None:
        with sqlite3.connect(self.path) as con:
            con.execute("""
                INSERT INTO users(chat_id, timeframe)
                VALUES(?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET timeframe=excluded.timeframe
            """, (chat_id, timeframe))

    # ---------- app_kv (глобальные пары для автоциклов) ----------
    def _get_kv(self, key: str) -> Optional[str]:
        with sqlite3.connect(self.path) as con:
            cur = con.execute("SELECT v FROM app_kv WHERE k=?", (key,))
            row = cur.fetchone()
            return row[0] if row else None

    def _set_kv(self, key: str, val: str) -> None:
        with sqlite3.connect(self.path) as con:
            con.execute("""
                INSERT INTO app_kv(k, v)
                VALUES(?, ?)
                ON CONFLICT(k) DO UPDATE SET v=excluded.v
            """, (key, val))

    def set_global_symbols(self, symbols_csv: str) -> None:
        # Храним как CSV в верхнем регистре, с нормализацией разделителя
        norm = ",".join([s.strip().upper().replace(":", "/") for s in symbols_csv.split(",") if s.strip()])
        self._set_kv("global_symbols", norm)

    def clear_global_symbols(self) -> None:
        with sqlite3.connect(self.path) as con:
            con.execute("DELETE FROM app_kv WHERE k='global_symbols'")

    def get_global_symbols(self) -> List[str]:
        raw = self._get_kv("global_symbols")
        if not raw:
            return []
        return [s.strip() for s in raw.split(",") if s.strip()]
