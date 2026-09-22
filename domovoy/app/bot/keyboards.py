"""Клавиатуры бота. Кнопка — это словарь для MAX Bot API."""
from __future__ import annotations

from app.bot.texts import CATEGORIES


def button(text: str, payload: str) -> dict[str, str]:
    return {"type": "callback", "text": text, "payload": payload}


MAIN_MENU = [
    [button("Отключения у меня", "outages")],
    [button("Написать в УК", "appeal")],
    [button("Мои обращения", "my_appeals")],
    [button("Мой адрес", "address"), button("Уведомления", "settings")],
]

ADDRESS_MENU = [
    [button("Изменить адрес", "address_set")],
    [button("Удалить адрес", "address_delete")],
    [button("Назад", "menu")],
]

SKIP_PHOTO = [[button("Пропустить", "photo_skip")], [button("Отменить", "cancel")]]

CONFIRM_APPEAL = [
    [button("Отправить", "appeal_send")],
    [button("Отменить", "cancel")],
]

BACK_TO_MENU = [[button("В меню", "menu")]]


def categories_keyboard() -> list[list[dict[str, str]]]:
    rows = [[button(name, f"category:{name}")] for name in CATEGORIES]
    rows.append([button("Отменить", "cancel")])
    return rows


def settings_keyboard(notify_water: bool, notify_electricity: bool) -> list[list[dict[str, str]]]:
    water = "Вода: присылать" if notify_water else "Вода: не присылать"
    power = "Свет: присылать" if notify_electricity else "Свет: не присылать"
    return [
        [button(water, "toggle_water")],
        [button(power, "toggle_electricity")],
        [button("Назад", "menu")],
    ]
