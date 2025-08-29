from aiogram.utils.keyboard import InlineKeyboardBuilder

def symbols_kb(symbols: list[str]):
    kb = InlineKeyboardBuilder()
    for s in symbols:
        kb.button(text=s, callback_data=f"set_sym:{s}")
    kb.adjust(2)
    return kb.as_markup()

def timeframes_kb(timeframes: list[str]):
    kb = InlineKeyboardBuilder()
    for tf in timeframes:
        kb.button(text=tf, callback_data=f"set_tf:{tf}")
    kb.adjust(3)
    return kb.as_markup()

def settings_menu_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="Выбрать инструмент", callback_data="menu:symbols")
    kb.button(text="Выбрать таймфрейм", callback_data="menu:timeframes")
    kb.adjust(1)
    return kb.as_markup()
