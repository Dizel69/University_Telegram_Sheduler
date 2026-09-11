"""Постоянная клавиатура личного бота (личка, не группа)."""

MENU_KEYBOARD = {
    "keyboard": [
        [{"text": "Сегодня"}, {"text": "Завтра"}],
        [{"text": "Пара"}, {"text": "ДЗ"}],
        [{"text": "Неделя"}],
        [{"text": "Настройки"}, {"text": "Обратная связь"}],
    ],
    "resize_keyboard": True,
    "is_persistent": True,
}


def menu_keyboard(*, persistent: bool = True) -> dict:
    markup = {
        "keyboard": MENU_KEYBOARD["keyboard"],
        "resize_keyboard": True,
    }
    if persistent:
        markup["is_persistent"] = True
    return markup
