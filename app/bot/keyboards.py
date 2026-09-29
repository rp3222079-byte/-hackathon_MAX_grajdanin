"""Клавиатуры бота.

Строка в клавиатуре — обычная кнопка, payload которой равен тексту.
Словарь — кнопка с отдельным payload (callback_button) или кнопка MAX,
запрашивающая данные устройства (contact_button, geo_button).
"""
from app.bot import texts
from app.bot.client import callback_button, contact_button, geo_button
from app.bot.geo import geocoding_enabled

# payload кнопок с параметром
PRIMARY_PREFIX = "addr:primary:"
DELETE_PREFIX = "addr:delete:"
RESEND_PREFIX = "appeal:resend:"
HOURS_PREFIX = "settings:hours:"
SETTINGS_WATER = "settings:water"
SETTINGS_ELECTRICITY = "settings:electricity"
SETTINGS_ALL_OFF = "settings:all_off"
SETTINGS_ALL_ON = "settings:all_on"


def main_menu():
    return [
        [texts.BTN_APPEAL],
        [texts.BTN_MY_APPEALS, texts.BTN_OUTAGES],
        [texts.BTN_MY_ADDRESS, texts.BTN_SETTINGS],
        [texts.BTN_HELP],
    ]


def cancel_only():
    return [[texts.BTN_CANCEL]]


def city_menu(cities):
    rows = []
    if geocoding_enabled():
        rows.append([geo_button(texts.BTN_GEO)])
    rows += [[city] for city in cities[:6]]
    rows.append([texts.BTN_CANCEL])
    return rows


def street_suggestions(streets):
    return [[street] for street in streets] + [[texts.BTN_RETYPE_STREET], [texts.BTN_CANCEL]]


def geo_confirm_menu():
    return [[texts.BTN_GEO_YES], [texts.BTN_GEO_NO], [texts.BTN_CANCEL]]


def flat_menu():
    return [[texts.BTN_NO_FLAT], [texts.BTN_CANCEL]]


def address_menu(addresses, short):
    """Кнопки управления адресами: основной, удалить, добавить."""
    rows = []
    for address in addresses:
        label = short(address)
        if not address["is_primary"]:
            rows.append([callback_button(texts.BTN_MAKE_PRIMARY.format(address=label),
                                         f"{PRIMARY_PREFIX}{address['id']}")])
        rows.append([callback_button(texts.BTN_DELETE_ADDRESS.format(address=label),
                                     f"{DELETE_PREFIX}{address['id']}")])
    rows.append([texts.BTN_ADD_ADDRESS])
    rows.append([texts.BTN_MENU])
    return rows


def no_address_menu():
    return [[texts.BTN_ADD_ADDRESS], [texts.BTN_MENU]]


def category_menu():
    categories = texts.CATEGORIES
    rows = [categories[i:i + 2] for i in range(0, len(categories), 2)]
    rows.append([texts.BTN_CANCEL])
    return rows


def photo_menu():
    return [[texts.BTN_SKIP_PHOTO], [texts.BTN_CANCEL]]


def contact_menu():
    return [
        [contact_button(texts.BTN_CONTACT_PHONE)],
        [texts.BTN_CONTACT_NAME],
        [texts.BTN_CONTACT_NO],
        [texts.BTN_CANCEL],
    ]


def confirm_menu():
    return [[texts.BTN_SEND], [texts.BTN_CANCEL]]


def resend_menu(numbers):
    rows = [[callback_button(texts.BTN_RESEND.format(number=number), f"{RESEND_PREFIX}{number}")]
            for number in numbers]
    return rows + main_menu()


def settings_menu(settings):
    rows = []
    if settings["notify_outages"]:
        rows.append([callback_button(
            texts.BTN_WATER_OFF if settings["notify_water"] else texts.BTN_WATER_ON, SETTINGS_WATER)])
        rows.append([callback_button(
            texts.BTN_ELECTRICITY_OFF if settings["notify_electricity"] else texts.BTN_ELECTRICITY_ON,
            SETTINGS_ELECTRICITY)])
        rows.append([texts.BTN_SET_HOURS])
        rows.append([callback_button(texts.BTN_ALL_OFF, SETTINGS_ALL_OFF)])
    else:
        rows.append([callback_button(texts.BTN_ALL_ON, SETTINGS_ALL_ON)])
    rows.append([texts.BTN_MENU])
    return rows


def hours_menu():
    options = [callback_button(texts.BTN_HOURS.format(hours=h), f"{HOURS_PREFIX}{h}")
               for h in texts.HOURS_OPTIONS]
    return [options[:3], options[3:], [texts.BTN_CANCEL]]
