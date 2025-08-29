import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from typing import List

from aiogram import Bot, Dispatcher, Router
from aiogram.enums import ParseMode
from aiogram.types import Message
from aiogram.filters import CommandStart, Command

from .config import load_settings
from .exchange import ExchangeClient, ts_now_iso
from .indicators import add_indicators, latest_snapshot
from .analyzer import LLMAnalyzer
from .storage import Storage
from .scheduler import run_sync

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("bot")

@asynccontextmanager
async def lifespan(dp: Dispatcher):
    yield

# Публиковать ли автоматические сигналы в канал (ручные команды доступны всегда)
active = True
router = Router()

# ----------------- Утилиты -----------------

def _within_cooldown(storage: Storage, symbol: str, timeframe: str, hours: int) -> bool:
    last = storage.last_buy_ts(symbol, timeframe)
    if not last:
        return False
    try:
        last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
    except Exception:
        return False
    return (datetime.now(timezone.utc) - last_dt) < timedelta(hours=hours)

def _norm_symbol(s: str) -> str:
    return s.upper().replace(":", "/").replace(" ", "")

async def _build_snapshots_triple(
    ex: ExchangeClient,
    symbol: str,
    tfs: List[str],
    ma_window: int,
    macd_fast: int,
    macd_slow: int,
    macd_signal: int,
):
    """
    Возвращает dict: { '1w': snapshot, '1d': snapshot, '4h': snapshot }
    или None если по какому-то TF не хватает данных.
    """
    result = {}
    for tf in tfs:
        df = await run_sync(ex.fetch_ohlcv, symbol, tf, 300)
        if df is None or len(df) < max(ma_window, macd_slow) + 5:
            return None
        df = add_indicators(df, ma_window, macd_fast, macd_slow, macd_signal)
        snap = latest_snapshot(df, ma_window)
        result[tf] = snap
    return result

def _format_card(symbol: str, tfs: List[str], buy: bool, conf: float, checks: dict, reason: str) -> str:
    return (
        f"{'🟢' if buy else '🔸'} <b>Результат (три экрана Элдера)</b>\n"
        f"Инструмент: <code>{symbol}</code>\n"
        f"TF: <code>{'/'.join(tfs)}</code>\n"
        f"Время (UTC): <code>{ts_now_iso()}</code>\n\n"
        f"Сигнал: <b>{'ПОКУПАТЬ' if buy else 'нет'}</b>\n"
        f"Уверенность: <b>{conf:.2f}</b>\n"
        f"Проверки: weekly_trend_ok={checks.get('weekly_trend_ok')}, "
        f"daily_macd_ok={checks.get('daily_macd_ok')}, "
        f"h4_volume_confirmation={checks.get('h4_volume_confirmation')}\n"
        f"Комментарий: {reason}"
    )

# ----------------- Команды -----------------

@router.message(CommandStart())
async def cmd_start(msg: Message):
    global active
    active = True
    settings = load_settings()
    storage = Storage(settings.state_dir)

    # что сейчас мониторим
    stored = storage.get_global_symbols()
    current_list = stored if stored else (settings.symbols if settings.symbols else ["BTC/USDT"])
    await msg.answer(
        "✅ Бот запущен!\n"
        "Используем «Систему трёх экранов» Элдера: 1w / 1d / 4h.\n\n"
        "Команды:\n"
        "• /setpairs BTC/USDT,ETH/USDT — задать список пар для постоянного мониторинга\n"
        "• /pairs — показать текущий список пар (используется автоциклом и /checkall)\n"
        "• /clearpairs — очистить список (возврат к .env SYMBOLS)\n"
        "• /check [SYMBOL/QUOTE] — анализ одной пары\n"
        "• /checkall [S1,S2,...] — пакетный анализ (если список не указан, берём /pairs)\n"
        "• /stop — выключить автопубликацию в канал, /start — включить\n\n"
        f"Текущее наблюдение: <code>{', '.join(current_list)}</code>",
        parse_mode=ParseMode.HTML
    )

@router.message(Command("stop"))
async def cmd_stop(msg: Message):
    global active
    active = False
    await msg.answer("⛔️ Автопубликация в канал остановлена. Ручные команды работают.")

@router.message(Command("setpairs"))
async def cmd_setpairs(msg: Message):
    """
    /setpairs BTC/USDT,ETH/USDT,HYPE/USDT
    Сохраняет список пар в БД, которые будут мониториться автоциклом и по умолчанию в /checkall.
    """
    settings = load_settings()
    storage = Storage(settings.state_dir)

    parts = (msg.text or "").strip().split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await msg.answer("⚠️ Укажи пары через запятую: <code>/setpairs BTC/USDT,ETH/USDT</code>", parse_mode=ParseMode.HTML)
        return

    raw = parts[1]
    pairs = [_norm_symbol(x) for x in raw.split(",") if x.strip()]
    bad = [p for p in pairs if "/" not in p]
    if bad:
        await msg.answer("❌ Неверный формат у: <code>" + ", ".join(bad) + "</code>. Используй <code>SYMBOL/QUOTE</code>.",
                         parse_mode=ParseMode.HTML)
        return

    # Сохраняем
    storage.set_global_symbols(",".join(pairs))
    await msg.answer("✅ Пары сохранены и будут мониториться: <code>" + ", ".join(pairs) + "</code>", parse_mode=ParseMode.HTML)

@router.message(Command("pairs"))
async def cmd_pairs(msg: Message):
    settings = load_settings()
    storage = Storage(settings.state_dir)
    stored = storage.get_global_symbols()
    if stored:
        await msg.answer("📈 Текущий список пар (из БД): <code>" + ", ".join(stored) + "</code>", parse_mode=ParseMode.HTML)
    else:
        base = settings.symbols if settings.symbols else ["BTC/USDT"]
        await msg.answer("ℹ️ В БД список пуст. Используется резерв из .env: <code>" + ", ".join(base) + "</code>",
                         parse_mode=ParseMode.HTML)

@router.message(Command("clearpairs"))
async def cmd_clearpairs(msg: Message):
    settings = load_settings()
    storage = Storage(settings.state_dir)
    storage.clear_global_symbols()
    base = settings.symbols if settings.symbols else ["BTC/USDT"]
    await msg.answer("🧹 Список пар очищен. Будут использованы .env SYMBOLS: <code>" + ", ".join(base) + "</code>",
                     parse_mode=ParseMode.HTML)

@router.message(Command("check"))
async def cmd_check(msg: Message, bot: Bot):
    """
    /check [SYMBOL/QUOTE] — тройной анализ одной пары (1w/1d/4h).
    Если пара не указана — берём первую из /pairs (или из .env, если список пуст).
    """
    settings = load_settings()
    storage = Storage(settings.state_dir)
    ex = ExchangeClient(settings.exchange_id)
    llm = LLMAnalyzer(settings.openai_api_key, settings.openai_model)

    parts = (msg.text or "").strip().split(maxsplit=1)
    if len(parts) > 1 and parts[1].strip():
        symbol = _norm_symbol(parts[1])
    else:
        stored = storage.get_global_symbols()
        symbol = stored[0] if stored else (settings.symbols[0] if settings.symbols else "BTC/USDT")

    if "/" not in symbol:
        await msg.answer("⚠️ Формат: <code>SYMBOL/QUOTE</code>. Пример: <code>BTC/USDT</code>", parse_mode=ParseMode.HTML)
        return

    await msg.answer(f"⏳ Тройной анализ <b>{symbol}</b> (1w/1d/4h)…", parse_mode=ParseMode.HTML)

    snapshots = await _build_snapshots_triple(
        ex, symbol, settings.triple_timeframes,
        settings.ma_window, settings.macd_fast, settings.macd_slow, settings.macd_signal
    )
    if not snapshots:
        await msg.answer("❌ Недостаточно данных от биржи для расчёта индикаторов на одном из TF.")
        return

    analysis = await run_sync(
        LLMAnalyzer.analyze_triple, llm,
        symbol, snapshots, settings.literature_urls, settings.report_locale
    )
    buy = bool(analysis.get("buy_signal"))
    conf = float(analysis.get("confidence", 0.0))
    reason = str(analysis.get("reason", ""))
    checks = analysis.get("checks", {})

    decision = "BUY" if buy else "NO_BUY"
    # для cooldown ведём по дневному экрану
    storage.insert_signal(symbol, "1d", decision, conf, reason)

    card = _format_card(symbol, settings.triple_timeframes, buy, conf, checks, reason)
    await msg.answer(card, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

    if buy:
        if _within_cooldown(storage, symbol, "1d", settings.buy_cooldown_hours):
            await msg.answer(f"⏸ BUY найден, но публикация пропущена: cooldown {settings.buy_cooldown_hours} ч. (по дневному экрану).")
        elif not active:
            await msg.answer("⏸ Сигнал найден, но автопубликация выключена (/start, чтобы включить).")
        else:
            await bot.send_message(
                settings.telegram_channel_id,
                "🟢 <b>Сигнал на покупку (три экрана Элдера)</b>\n" + card.split("\n", 3)[3],
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True
            )
            await msg.answer("✅ Сигнал опубликован в канал.")

@router.message(Command("checkall"))
async def cmd_checkall(msg: Message, bot: Bot):
    """
    /checkall
    /checkall BTC/USDT,ETH/USDT,BNB/USDT
    Пакетный анализ: берёт пары из аргумента или из /pairs (БД) или из .env.
    """
    settings = load_settings()
    storage = Storage(settings.state_dir)
    ex = ExchangeClient(settings.exchange_id)
    llm = LLMAnalyzer(settings.openai_api_key, settings.openai_model)

    parts = (msg.text or "").strip().split(maxsplit=1)
    if len(parts) > 1 and parts[1].strip():
        symbols = [_norm_symbol(s) for s in parts[1].split(",") if s.strip()]
    else:
        stored = storage.get_global_symbols()
        symbols = stored if stored else (settings.symbols if settings.symbols else ["BTC/USDT"])

    symbols = symbols[:12]  # защита от слишком больших пакетов
    await msg.answer(f"⏳ Пакетный анализ ({len(symbols)} пар) по трём экранам…")

    buys_to_publish = []
    results_lines = []

    for i, symbol in enumerate(symbols, start=1):
        try:
            snapshots = await _build_snapshots_triple(
                ex, symbol, settings.triple_timeframes,
                settings.ma_window, settings.macd_fast, settings.macd_slow, settings.macd_signal
            )
            if not snapshots:
                results_lines.append(f"{i}. {symbol}: ❌ недостаточно данных")
                continue

            analysis = await run_sync(
                LLMAnalyzer.analyze_triple, llm,
                symbol, snapshots, settings.literature_urls, settings.report_locale
            )
            buy = bool(analysis.get("buy_signal"))
            conf = float(analysis.get("confidence", 0.0))
            reason = str(analysis.get("reason", ""))
            checks = analysis.get("checks", {})

            decision = "BUY" if buy else "NO_BUY"
            storage.insert_signal(symbol, "1d", decision, conf, reason)

            card = _format_card(symbol, settings.triple_timeframes, buy, conf, checks, reason)
            await msg.answer(card, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

            results_lines.append(f"{i}. {symbol}: {'🟢 BUY' if buy else '—'} (conf={conf:.2f})")

            if buy:
                if _within_cooldown(storage, symbol, "1d", settings.buy_cooldown_hours):
                    results_lines[-1] += f" ⏸ cooldown {settings.buy_cooldown_hours}ч"
                elif not active:
                    results_lines[-1] += " ⏸ публикация выключена"
                else:
                    buys_to_publish.append(("🟢 <b>Сигнал на покупку (пакетный, три экрана)</b>\n" + card.split("\n", 3)[3]))
        except Exception as e:
            log.exception("checkall error on %s: %s", symbol, e)
            results_lines.append(f"{i}. {symbol}: ❌ ошибка анализа")

    # Публикуем найденные BUY в канал (если включено)
    for text in buys_to_publish:
        try:
            await bot.send_message(
                settings.telegram_channel_id,
                text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True
            )
        except Exception as e:
            log.exception("send to channel failed: %s", e)

    summary = "📊 Сводка пакетного анализа:\n" + "\n".join(results_lines)
    await msg.answer(summary, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

# Диагностика: любой необработанный апдейт
@router.message()
async def any_message(msg: Message):
    log.info("⚙️  Получено сообщение без команды: chat=%s text=%r", msg.chat.id, msg.text)

# ----------------- Автоцикл -----------------

async def periodic_task(settings, bot: Bot, storage: Storage, ex: ExchangeClient, llm: LLMAnalyzer):
    while True:
        try:
            # Берём пары в приоритете из БД, иначе из .env
            pairs = storage.get_global_symbols()
            symbols = pairs if pairs else (settings.symbols if settings.symbols else ["BTC/USDT"])

            for symbol in symbols:
                try:
                    log.info("Triple fetch %s %s ...", symbol, "/".join(settings.triple_timeframes))
                    snapshots = await _build_snapshots_triple(
                        ex, symbol, settings.triple_timeframes,
                        settings.ma_window, settings.macd_fast, settings.macd_slow, settings.macd_signal
                    )
                    if not snapshots:
                        log.warning("Not enough data for %s on one of tfs", symbol)
                        continue

                    analysis = await run_sync(
                        LLMAnalyzer.analyze_triple, llm,
                        symbol, snapshots, settings.literature_urls, settings.report_locale
                    )
                    buy = bool(analysis.get("buy_signal"))
                    conf = float(analysis.get("confidence", 0.0))
                    reason = str(analysis.get("reason", ""))

                    decision = "BUY" if buy else "NO_BUY"
                    storage.insert_signal(symbol, "1d", decision, conf, reason)

                    if buy:
                        if _within_cooldown(storage, symbol, "1d", settings.buy_cooldown_hours):
                            log.info("⏸ Пропускаю BUY по %s — cooldown %d ч. (дневной экран)", symbol, settings.buy_cooldown_hours)
                            continue

                        text = (
                            f"🟢 <b>Сигнал на покупку (три экрана Элдера)</b>\n"
                            f"Инструмент: <code>{symbol}</code>\n"
                            f"TF: <code>{'/'.join(settings.triple_timeframes)}</code>\n"
                            f"Время (UTC): <code>{ts_now_iso()}</code>\n"
                            f"Уверенность: <b>{conf:.2f}</b>\n"
                            f"Комментарий: {reason}"
                        )
                        if active:
                            await bot.send_message(
                                settings.telegram_channel_id,
                                text,
                                parse_mode=ParseMode.HTML,
                                disable_web_page_preview=True
                            )
                            log.info("✅ Сигнал отправлен в канал: %s", settings.telegram_channel_id)
                        else:
                            log.info("⏸ Сигнал не отправлен (бот в режиме stop)")
                except Exception as e:
                    log.exception("Error on symbol %s: %s", symbol, e)
        except Exception as e:
            log.exception("Periodic loop error: %s", e)

        await asyncio.sleep(settings.schedule_seconds)

# ----------------- Bootstrap -----------------

def build_bot() -> tuple[Dispatcher, Bot, Storage, ExchangeClient, LLMAnalyzer]:
    settings = load_settings()
    bot = Bot(token=settings.telegram_token)
    dp = Dispatcher(lifespan=lifespan)
    dp.include_router(router)

    storage = Storage(state_dir=settings.state_dir)
    ex = ExchangeClient(settings.exchange_id)
    llm = LLMAnalyzer(settings.openai_api_key, settings.openai_model)
    return dp, bot, storage, ex, llm

async def main():
    dp, bot, storage, ex, llm = build_bot()
    settings = load_settings()
    task = asyncio.create_task(periodic_task(settings, bot, storage, ex, llm))
    try:
        await dp.start_polling(bot)
    finally:
        task.cancel()
        with contextlib.suppress(Exception):
            await task

if __name__ == "__main__":
    import contextlib
    asyncio.run(main())
