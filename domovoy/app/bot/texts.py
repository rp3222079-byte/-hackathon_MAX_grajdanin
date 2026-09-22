"""Тексты и кнопки бота. Дизайнер правит этот файл, разработчик его не трогает."""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.config import settings

from app.models import UtilityType

UTILITY_LABELS = {
    UtilityType.WATER_COLD: "Холодная вода",
    UtilityType.WATER_HOT: "Горячая вода",
    UtilityType.ELECTRICITY: "Электричество",
    UtilityType.HEATING: "Отопление",
    UtilityType.GAS: "Газ",
}

UTILITY_ICONS = {
    UtilityType.WATER_COLD: "💧",
    UtilityType.WATER_HOT: "🚿",
    UtilityType.ELECTRICITY: "⚡",
    UtilityType.HEATING: "🔥",
    UtilityType.GAS: "🔵",
}

CATEGORIES = [
    "Протечка",
    "Отопление",
    "Лифт",
    "Мусор",
    "Подъезд и двор",
    "Другое",
]

WELCOME = (
    "Это «Домовой».\n\n"
    "Я предупреждаю об отключениях воды и света по вашему адресу "
    "и передаю обращения в управляющую компанию.\n\n"
    "Начнём с адреса."
)

MENU = "Что дальше?"
ASK_CITY = "Из какого вы города?"
ASK_STREET = "Улица?"
ASK_HOUSE = "Номер дома? Например: 12 или 12к2."
ASK_FLAT = "Квартира? Отправьте «-», если не хотите указывать."
ADDRESS_SAVED = "Адрес сохранён: {address}\n\nТеперь я пришлю сообщение, как только по нему появится отключение."
ADDRESS_FAILED = "Не разобрал адрес. Напишите улицу и дом так, как в квитанции."
NO_ADDRESS = "Сначала добавьте адрес — так я пойму, о каких отключениях писать."
NO_OUTAGES = "По вашему адресу отключений нет."

ASK_CATEGORY = "О чём обращение?"
ASK_MESSAGE = "Опишите, что случилось. Чем конкретнее, тем быстрее отреагирует управляющая компания."
ASK_PHOTO = "Пришлите фото или нажмите «Пропустить»."
APPEAL_CONFIRM = (
    "Проверьте обращение:\n\n"
    "Адрес: {address}\n"
    "Тема: {category}\n"
    "Текст: {message}\n\n"
    "Отправляем в {company}?"
)
APPEAL_SENT = "Обращение {number} отправлено в {company}.\n\nОтвет придёт на почту компании, а я сообщу о смене статуса."
APPEAL_NO_COMPANY = (
    "Для вашего дома не нашлась управляющая компания. "
    "Напишите организаторам сервиса или проверьте адрес."
)
APPEAL_CANCELLED = "Обращение отменено."
SETTINGS_TITLE = "Что вам присылать?"
UNKNOWN = "Не понял. Выберите пункт меню."
ERROR = "Что-то пошло не так. Попробуйте ещё раз через минуту."

STATUS_LABELS = {
    "new": "создано",
    "sent": "отправлено в УК",
    "in_progress": "в работе",
    "resolved": "решено",
    "failed": "не отправлено",
}


def format_dt(value: datetime | str | None) -> str:
    """Дату и время показываем в привычном виде: 14 июня, 09:00."""
    if value is None:
        return "время не указано"
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    value = value.astimezone(ZoneInfo(settings.timezone))
    months = (
        "января", "февраля", "марта", "апреля", "мая", "июня",
        "июля", "августа", "сентября", "октября", "ноября", "декабря",
    )
    return f"{value.day} {months[value.month - 1]}, {value:%H:%M}"


def outage_card(outage: dict) -> str:
    """Одно отключение в виде сообщения."""
    utility = UtilityType(outage["utility"])
    icon = UTILITY_ICONS.get(utility, "•")
    label = UTILITY_LABELS.get(utility, utility.value)
    kind = "плановое" if outage.get("is_planned", True) else "аварийное"

    lines = [f"{icon} {label} — {kind} отключение"]
    lines.append(f"С {format_dt(outage.get('starts_at'))}")
    if outage.get("ends_at"):
        lines.append(f"До {format_dt(outage.get('ends_at'))}")
    if outage.get("reason"):
        lines.append(f"Причина: {outage['reason']}")
    if outage.get("raw_addresses"):
        first_line = outage["raw_addresses"].splitlines()[0]
        lines.append(f"Адреса: {first_line}")
    return "\n".join(lines)


def notification_message(outage: dict, address_text: str) -> str:
    """Сообщение, которое приходит жильцу при новом отключении."""
    return f"{outage_card(outage)}\n\nВаш адрес: {address_text}"


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
