import json
from typing import Any, Dict, List
from openai import OpenAI

SYSTEM_RU = """
Вы — финансовый помощник по ТЕХАНАЛИЗУ, работаете строго по Александру Элдеру.
Используйте «Систему трёх экранов»:
- Старший (trend filter): направленность тренда (MA и цена относительно MA).
- Средний (setup): MACD и его пересечения/гистограмма.
- Младший (timing): подтверждение объёмом и краткосрочный тайминг входа.
Возвращайте СТРОГО JSON без комментариев.
"""

def build_prompt_triple(
    symbol: str,
    snapshots_by_tf: Dict[str, Dict[str, Any]],
    literature_urls: List[str],
    locale: str = "ru",
) -> str:
    guidelines = "; ".join(literature_urls) if literature_urls else "А. Элдер «Трейдинг с доктором Элдером»"
    text = f"""
Источник(и): {guidelines}

Проанализируй {symbol} по «Системе трёх экранов»:
- Старший TF = 1w (фильтр тренда).
- Средний TF = 1d (настройка по MACD).
- Младший TF = 4h (тайминг и объём).

Даны снапшоты по каждому TF (цена, MA, MACD, объём, и предвычисленные флаги):

{json.dumps(snapshots_by_tf, ensure_ascii=False, indent=2)}

Правила решения:
- buy_signal = true только если: (Старший подтверждает восходящий тренд: цена>=MA или MA растёт) И (на Среднем MACD пересёк вверх/выше сигнальной или растёт гистограмма) И (на Младшем желательно подтверждение объёмом или отсутствие явных противоречий).
- Учитывай согласованность сигналов; оцени «confidence» 0..1.
- reason — кратко на {locale} без воды.

Верни СТРОГО такой JSON:
{{
  "buy_signal": true|false,
  "confidence": 0..1,
  "reason": "<кратко на {locale}>",
  "checks": {{
    "weekly_trend_ok": true|false,
    "daily_macd_ok": true|false,
    "h4_volume_confirmation": true|false
  }},
  "principles_used": ["Elder: triple screen", "Elder: trend/MA", "Elder: MACD", "Elder: volume"],
  "source_url": "{guidelines}"
}}
    """.strip()
    return text

class LLMAnalyzer:
    def __init__(self, api_key: str, model: str):
        self.client = OpenAI(api_key=api_key)
        self.model = model

    # старый метод (на случай, если где-то ещё нужен одиночный tf)
    def analyze(self, symbol: str, timeframe: str, snapshot: Dict[str, Any], literature_urls: List[str], locale: str = "ru") -> Dict[str, Any]:
        prompt = (
            "Единичный таймфрейм больше не используется, применяйте тройной анализ."
        )
        return {"buy_signal": False, "confidence": 0.0, "reason": prompt, "checks": {}}

    # НОВЫЙ: анализ «три экрана»
    def analyze_triple(
        self,
        symbol: str,
        snapshots_by_tf: Dict[str, Dict[str, Any]],
        literature_urls: List[str],
        locale: str = "ru",
    ) -> Dict[str, Any]:
        prompt = build_prompt_triple(symbol, snapshots_by_tf, literature_urls, locale)
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_RU},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        content = resp.choices[0].message.content
        try:
            data = json.loads(content)
        except Exception:
            data = {
                "buy_signal": False,
                "confidence": 0.0,
                "reason": "Невалидный ответ модели",
                "checks": {},
                "principles_used": ["Elder: triple screen", "Elder: trend/MA", "Elder: MACD", "Elder: volume"],
                "source_url": "; ".join(literature_urls) if literature_urls else ""
            }
        return data
