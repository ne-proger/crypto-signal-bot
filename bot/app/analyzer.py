# bot/app/analyzer.py
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from openai import OpenAI  # требуется пакет openai>=1.0
# модель и ключ берём из .env при инициализации класса

log = logging.getLogger("analyzer")


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _as_bool(x: Any) -> bool:
    if isinstance(x, bool):
        return x
    if isinstance(x, (int, float)):
        return bool(x)
    if isinstance(x, str):
        return x.strip().lower() in {"1", "true", "yes", "y", "да"}
    return False


def _first_json_in_text(text: str) -> Optional[dict]:
    """
    На случай, если модель вернула префикс/пояснение — достаём первый {...}.
    """
    try:
        # простая, но надёжная скобочная вытяжка
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start : end + 1])
    except Exception:
        pass
    return None


def _trend_guess(price_above_ma: Optional[bool], macd_above_zero: Optional[bool]) -> str:
    # грубая эвристика, если в снапшоте нет «trend»
    pa = _as_bool(price_above_ma)
    ma = _as_bool(macd_above_zero)
    if pa and ma:
        return "up"
    if (not pa) and (not ma):
        return "down"
    return "range"


def _macd_context(macd: float, macd_signal: float) -> str:
    if macd > 0 and macd >= macd_signal:
        return "above_zero"
    if macd < 0 and macd <= macd_signal:
        return "below_zero"
    return "crossing"


def _format_tf_block(tf_name: str, snap: Dict[str, Any], ma_window: int) -> str:
    """
    Сводная строка по ТФ (для user-промта).
    """
    close = snap.get("close")
    ma = snap.get("ma")
    price_above_ma = snap.get("price_above_ma")
    macd = snap.get("macd", 0.0)
    macd_signal = snap.get("macd_signal", 0.0)
    volume = snap.get("volume")
    volume_ma = snap.get("volume_ma")
    volume_spike = snap.get("volume_spike")

    macd_above_zero = macd is not None and macd > 0
    trend = _trend_guess(price_above_ma, macd_above_zero)
    macd_ctx = _macd_context(float(macd or 0.0), float(macd_signal or 0.0))

    return (
        f"{tf_name}: close={close}, MA{ma_window}={ma}, "
        f"aboveMA={bool(price_above_ma)}, MACD={macd:.4f}/{macd_signal:.4f}({macd_ctx}), "
        f"vol={volume} avg={volume_ma} spike={bool(volume_spike)}; trend≈{trend}"
    )


def _render_user_prompt(
    symbol: str,
    snapshots: Dict[str, Dict[str, Any]],
    ma_window: int,
    macd_fast: int,
    macd_slow: int,
    macd_signal: int,
    sensitivity: str,
    template_from_env: Optional[str],
    book_url: Optional[str],
) -> str:
    # Подготовим сводки по трём ТФ (ключи в проекте: "1w", "1d", "4h")
    w = snapshots.get("1w", {})
    d = snapshots.get("1d", {})
    h4 = snapshots.get("4h", {})

    w_line = _format_tf_block("W1", w, ma_window)
    d_line = _format_tf_block("D1", d, ma_window)
    h4_line = _format_tf_block("H4", h4, ma_window)

    base = (
        f"{_now_utc_iso()} UTC. Проанализируй {symbol} по трём ТФ (W1/D1/H4). "
        f"Решение принимается на H4 c учётом старших ТФ.\n\n"
        f"Параметры индикаторов: MA={ma_window}, MACD(fast/slow/signal)={macd_fast}/{macd_slow}/{macd_signal}.\n"
        f"Чувствительность (SENSITIVITY): {sensitivity}  # high=больше сигналов, low=только явные.\n"
        f"(Ссылка на методологию дана внутренне, в ответе ничего про источники не писать.)\n\n"
        f"{w_line}\n{d_line}\n{h4_line}\n\n"
        f"Верни строго JSON по схеме (она передана отдельно)."
    )

    # Если в ENV задан шаблон — аккуратно подставим доступные плейсхолдеры.
    if template_from_env:
        ctx = {
            "{{now_utc}}": _now_utc_iso(),
            "{{symbol}}": symbol,
            "{{ma_window}}": str(ma_window),
            "{{macd_fast}}": str(macd_fast),
            "{{macd_slow}}": str(macd_slow),
            "{{macd_signal}}": str(macd_signal),
            "{{sensitivity}}": sensitivity,
            "{{book_url}}": (book_url or ""),
            # Простые сводки — чтобы не взрываться с глубокой шаблонизацией:
            "{{weekly.indicators_summary}}": w_line,
            "{{daily.indicators_summary}}": d_line,
            "{{h4.indicators}}": h4_line,
            "{{weekly.trend}}": _trend_guess(w.get("price_above_ma"), (w.get("macd") or 0) > 0),
            "{{daily.trend}}": _trend_guess(d.get("price_above_ma"), (d.get("macd") or 0) > 0),
            "{{h4.signals}}": h4_line,
            "{{h4.levels}}": f"recent_high={h4.get('recent_high')} recent_low={h4.get('recent_low')}",
            "{{weekly.levels}}": "",
            "{{daily.levels}}": "",
        }
        rendered = template_from_env
        for k, v in ctx.items():
            rendered = rendered.replace(k, str(v))
        # Добавим наши вычисленные строки на случай, если шаблон слишком минимален
        return rendered + "\n\n---\n" + base

    return base


def _normalize_sensitivity(val: Optional[str]) -> str:
    v = (val or "").strip().lower()
    if v in {"strict", "low"}:
        return "low"
    if v in {"aggressive", "high"}:
        return "high"
    return "medium"


class LLMAnalyzer:
    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model
        self.client = OpenAI(api_key=api_key)

        # Секретные промпты и ссылка на книгу — только из ENV
        # (нигде не логируем!)
        self.system_prompt = os.getenv("PROMPT_SYSTEM", "").strip()
        self.user_template = os.getenv("PROMPT_USER_TEMPLATE", "").strip() or None
        self.schema_text = os.getenv("PROMPT_JSON_SCHEMA", "").strip()
        self.book_url = os.getenv("PROMPT_BOOK_URL", "").strip() or None

        # Чувствительность по умолчанию (можно переопределять на уровне команд)
        self.default_sensitivity = _normalize_sensitivity(os.getenv("SENSITIVITY") or os.getenv("DEFAULT_SENSITIVITY") or "medium")

    # ---- Публичное API, которое вызывает main.py ----

    def analyze_triple(
        self,
        symbol: str,
        snapshots: Dict[str, Dict[str, Any]],
        literature_urls: list[str] | str | None,  # оставляем сигнатуру для совместимости; не используем наружу
        locale: str = "ru",
        sensitivity: Optional[str] = None,
        ma_window: Optional[int] = None,
        macd_fast: Optional[int] = None,
        macd_slow: Optional[int] = None,
        macd_signal: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Главный метод: анализ по трём ТФ с решением на H4.
        Возвращает dict с ключами, которые ожидает остальной код:
          buy_signal(bool), confidence(float), reason(str), checks(dict)
        """
        sens = _normalize_sensitivity(sensitivity or self.default_sensitivity)

        # Берём базовые параметры индикаторов из снапшота (если переданы сверху — используем их)
        # В текущем проекте ma_window/macd_* приходят из settings в main.py; если нет — дефолты.
        mw = int(ma_window or os.getenv("MA_WINDOW", 50))
        mf = int(macd_fast or os.getenv("MACD_FAST", 12))
        ms = int(macd_slow or os.getenv("MACD_SLOW", 26))
        msi = int(macd_signal or os.getenv("MACD_SIGNAL", 9))

        # Готовим user-контент
        user_content = _render_user_prompt(
            symbol=symbol,
            snapshots=snapshots,
            ma_window=mw,
            macd_fast=mf,
            macd_slow=ms,
            macd_signal=msi,
            sensitivity=sens,
            template_from_env=self.user_template,
            book_url=self.book_url,
        )

        # Готовим messages для чата
        system_content = self.system_prompt or (
            "Вы — аналитик. Примени многофреймовый анализ (W/D/4H) и выдай решение на H4. "
            "Верни строго JSON без лишнего текста."
        )

        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content},
        ]

        # Попросим JSON-ответ
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.2 if sens == "low" else (0.35 if sens == "medium" else 0.5),
            response_format={"type": "json_object"},
            # можно добавить max_tokens при необходимости
        )

        raw_text = (response.choices[0].message.content or "").strip()
        data = None
        try:
            data = json.loads(raw_text)
        except Exception:
            data = _first_json_in_text(raw_text)

        if not isinstance(data, dict):
            log.warning("LLM returned non-JSON or empty content, fallback NO_BUY. Text: %.200s", raw_text)
            return {
                "buy_signal": False,
                "confidence": 0.0,
                "reason": "LLM: invalid JSON",
                "checks": {},
            }

        # Нормализуем поля под ожидания остального кода
        buy = bool(data.get("buy_signal"))
        confidence = float(data.get("confidence", 0.0))
        # многие схемы называют поле rationale — отразим в reason
        reason = str(data.get("reason") or data.get("rationale") or "")

        # Попробуем построить простые checks из tf_summary, если он есть
        checks = data.get("checks")
        if not isinstance(checks, dict):
            checks = {}
            tf = data.get("tf_summary") or {}
            try:
                w = tf.get("W1") or {}
                d = tf.get("D1") or {}
                h = tf.get("H4") or {}
                checks = {
                    "weekly_trend_ok": (w.get("trend") == "up" or w.get("trend") == "down"),
                    "daily_macd_ok": (d.get("macd_context") in {"above_zero", "crossing"}),
                    "h4_volume_confirmation": (h.get("volume_context") in {"spike_up", "normal"}),
                }
            except Exception:
                checks = {}

        return {
            "buy_signal": buy,
            "confidence": confidence,
            "reason": reason,
            "checks": checks,
        }
