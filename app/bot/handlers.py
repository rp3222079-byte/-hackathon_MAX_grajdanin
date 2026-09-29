"""Сценарии диалогов бота.

Точка входа — route(message): получает входящее сообщение и возвращает
ответ (текст, клавиатура). Кнопки главного меню, «Отмена» и /start
работают на любом шаге: они прерывают начатый диалог, поэтому жилец
не может «застрять».
"""
from dataclasses import dataclass, field
from datetime import datetime

from app.bot import api, geo, keyboards, profiles, states, texts, workers
from app.services.addresses import parse_house_fragment, normalize_street
from app.services.matching import normalize_city
from app.timeutil import local_now

MAX_PHOTOS = 5
MIN_MESSAGE_LENGTH = 5
LONG_TEXT = 25


@dataclass
class Incoming:
    """Входящее сообщение или нажатие кнопки, уже разобранное из события MAX."""

    user_id: int
    text: str = ""
    photos: list[str] = field(default_factory=list)
    location: tuple[float, float] | None = None
    contact: dict | None = None


def _norm(text: str) -> str:
    return texts.normalize_input(text)


# --- форматирование ---
def house_label(address) -> str:
    return f'{address["house_number"]}{address.get("house_corpus") or ""}'


def full_address(address) -> str:
    text = f'{address["city"]}, {address["street"]}, {house_label(address)}'
    if address.get("flat"):
        text += f', кв. {address["flat"]}'
    return text


def short_address(address) -> str:
    return f'{address["street"]}, {house_label(address)}'


def _parse_dt(value):
    return datetime.fromisoformat(value) if isinstance(value, str) else value


def _hm(moment: datetime) -> str:
    return moment.strftime("%H:%M")


def _dm(moment: datetime) -> str:
    return moment.strftime("%d.%m")


def outage_when(outage, now: datetime | None = None) -> str:
    """«идёт сейчас, до 21:00» или «01.10 с 10:00 до 18:00»."""
    now = now or local_now()
    starts = _parse_dt(outage["starts_at"])
    ends = _parse_dt(outage.get("ends_at"))
    if starts <= now:
        if ends is None:
            until = "до окончания работ"
        elif ends.date() == now.date():
            until = f"до {_hm(ends)}"
        else:
            until = f"до {_dm(ends)} {_hm(ends)}"
        return texts.OUTAGE_NOW.format(until=until)
    if ends is None:
        return f"{_dm(starts)} с {_hm(starts)}"
    if ends.date() == starts.date():
        return f"{_dm(starts)} с {_hm(starts)} до {_hm(ends)}"
    return f"с {_dm(starts)} {_hm(starts)} до {_dm(ends)} {_hm(ends)}"


def _company_phone(company) -> str:
    phone = (company or {}).get("phone")
    return f", тел. {phone}" if phone else ""


# --- маршрутизация ---
def route(message: Incoming):
    """Ответ на сообщение: (текст, клавиатура или None)."""
    text = (message.text or "").strip()
    normalized = _norm(text)
    user_id = message.user_id

    command = _global_command(normalized, text)
    if command is not None:
        states.clear_state(user_id)
        return command(message)

    state = states.get_state(user_id)
    if state is not None:
        return _dialog(message, state)

    if len(text) > LONG_TEXT:
        return texts.UNKNOWN_LONG_TEXT, keyboards.main_menu()
    return texts.UNKNOWN, keyboards.main_menu()


def _global_command(normalized: str, raw: str):
    """Команда, которая работает с любого шага, или None."""
    simple = {
        "/start": handle_start,
        "/help": handle_help,
        "/menu": handle_menu,
        _norm(texts.BTN_HELP): handle_help,
        _norm(texts.BTN_MENU): handle_menu,
        _norm(texts.BTN_CANCEL): handle_cancel,
        _norm(texts.BTN_APPEAL): handle_appeal,
        _norm(texts.BTN_MY_APPEALS): handle_my_appeals,
        _norm(texts.BTN_OUTAGES): handle_outages,
        _norm(texts.BTN_MY_ADDRESS): handle_my_address,
        _norm(texts.BTN_ADD_ADDRESS): handle_add_address,
        _norm(texts.BTN_SETTINGS): handle_settings,
        _norm(texts.BTN_SET_HOURS): handle_ask_hours,
        keyboards.SETTINGS_WATER: handle_toggle_water,
        keyboards.SETTINGS_ELECTRICITY: handle_toggle_electricity,
        keyboards.SETTINGS_ALL_OFF: handle_all_off,
        keyboards.SETTINGS_ALL_ON: handle_all_on,
    }
    if normalized in simple:
        return simple[normalized]
    for prefix, handler in (
        (keyboards.PRIMARY_PREFIX, handle_make_primary),
        (keyboards.DELETE_PREFIX, handle_delete_address),
        (keyboards.RESEND_PREFIX, handle_resend),
        (keyboards.HOURS_PREFIX, handle_hours_button),
    ):
        if raw.startswith(prefix):
            argument = raw[len(prefix):]
            return lambda message, handler=handler, argument=argument: handler(message, argument)
    return None


def _dialog(message: Incoming, state):
    step = state["step"]
    if step.startswith("addr_"):
        return _address_dialog(message, state)
    if step.startswith("appeal_"):
        return _appeal_dialog(message, state)
    if step == "settings_hours":
        return _hours_step(message)
    states.clear_state(message.user_id)
    return texts.MENU, keyboards.main_menu()


# --- простые команды ---
def handle_start(message: Incoming):
    if not api.list_addresses(message.user_id):
        return _begin_address(message.user_id, prefix=texts.WELCOME + "\n\n")
    return texts.WELCOME_BACK, keyboards.main_menu()


def handle_help(message: Incoming):
    return texts.HELP, keyboards.main_menu()


def handle_menu(message: Incoming):
    return texts.MENU, keyboards.main_menu()


def handle_cancel(message: Incoming):
    return texts.CANCELLED, keyboards.main_menu()


# --- адрес ---
def _known_cities() -> list[str]:
    try:
        return api.list_cities()
    except api.ApiError:
        return []


def _begin_address(user_id, prefix=""):
    states.set_state(user_id, "addr_city", {})
    question = texts.ASK_CITY if geo.geocoding_enabled() else texts.ASK_CITY_TEXT
    return prefix + question, keyboards.city_menu(_known_cities())


def handle_add_address(message: Incoming):
    return _begin_address(message.user_id)


def _address_dialog(message: Incoming, state):
    user_id = message.user_id
    step, data = state["step"], state["data"]
    text = (message.text or "").strip()

    if message.location is not None:
        return _address_from_location(user_id, *message.location)

    if step == "addr_city":
        if not text:
            return _begin_address(user_id)
        return _choose_city(user_id, text)

    if step == "addr_geo_confirm":
        if _norm(text) == _norm(texts.BTN_GEO_YES):
            return _check_house(user_id, data)
        if _norm(text) == _norm(texts.BTN_GEO_NO):
            return _begin_address(user_id)
        return texts.GEO_CONFIRM.format(address=full_address(data)), keyboards.geo_confirm_menu()

    if step in ("addr_street", "addr_street_pick"):
        if step == "addr_street_pick":
            if _norm(text) == _norm(texts.BTN_RETYPE_STREET):
                states.set_state(user_id, "addr_street", data)
                return texts.ASK_STREET, keyboards.cancel_only()
            if text in data.get("suggestions", []):
                return _street_chosen(user_id, data, text)
        if not text:
            return texts.ASK_STREET, keyboards.cancel_only()
        return _resolve_street(user_id, data, text)

    if step == "addr_house":
        try:
            number, corpus = parse_house_fragment(text.replace(" ", ""))
        except ValueError:
            return texts.HOUSE_FAILED, keyboards.cancel_only()
        if number < 1 or number > 99999:
            return texts.HOUSE_FAILED, keyboards.cancel_only()
        data["house_number"], data["house_corpus"] = number, corpus
        return _check_house(user_id, data)

    if step == "addr_flat":
        return _save_address(user_id, data, text)

    return _begin_address(user_id)


def _choose_city(user_id, text):
    cities = _known_cities()
    if not cities:
        city = text
    else:
        matches = [known for known in cities if normalize_city(known) == normalize_city(text)]
        if not matches:
            reply = texts.CITY_UNKNOWN.format(city=text, cities=", ".join(cities))
            return reply, keyboards.city_menu(cities)
        city = matches[0]
    states.set_state(user_id, "addr_street", {"city": city})
    return texts.ASK_STREET, keyboards.cancel_only()


def _resolve_street(user_id, data, typed):
    streets = api.find_streets(data["city"], typed)
    if streets and normalize_street(streets[0]) == normalize_street(typed):
        return _street_chosen(user_id, data, streets[0])
    if streets:
        data["suggestions"] = streets
        states.set_state(user_id, "addr_street_pick", data)
        return texts.STREET_SUGGEST.format(street=typed), keyboards.street_suggestions(streets)
    states.set_state(user_id, "addr_street", data)
    return texts.STREET_NOT_FOUND.format(street=typed, city=data["city"]), keyboards.cancel_only()


def _street_chosen(user_id, data, street):
    data.pop("suggestions", None)
    data["street"] = street
    if data.get("house_number"):
        return _check_house(user_id, data)
    states.set_state(user_id, "addr_house", data)
    return texts.ASK_HOUSE, keyboards.cancel_only()


def _check_house(user_id, data):
    """Дом есть в справочнике — спрашиваем квартиру, нет — просим проверить номер."""
    company = api.lookup_company(data["city"], data["street"], data["house_number"], data.get("house_corpus"))
    if company is None:
        states.set_state(user_id, "addr_house", data)
        reply = texts.HOUSE_NOT_FOUND.format(house=house_label(data), street=data["street"])
        return reply, keyboards.cancel_only()
    data["company"] = {"name": company["name"], "phone": company.get("phone")}
    states.set_state(user_id, "addr_flat", data)
    return texts.ASK_FLAT, keyboards.flat_menu()


def _save_address(user_id, data, text):
    flat = None
    if _norm(text) not in (_norm(texts.BTN_NO_FLAT), "-"):
        if not text.isdigit() or not 1 <= int(text) <= 99999:
            return texts.FLAT_FAILED, keyboards.flat_menu()
        flat = int(text)
    try:
        address = api.add_address(
            user_id, data["city"], data["street"], data["house_number"], data.get("house_corpus"), flat,
        )
    except api.ApiError as error:
        if error.status == 409:
            states.clear_state(user_id)
            return texts.ADDRESS_EXISTS, keyboards.main_menu()
        raise
    states.clear_state(user_id)
    company = data.get("company") or {}
    reply = texts.ADDRESS_SAVED.format(
        address=full_address(address), company=company.get("name", "—"), phone=_company_phone(company),
    )
    return reply, keyboards.main_menu()


def _address_from_location(user_id, latitude, longitude):
    found = geo.reverse_geocode(latitude, longitude)
    if not found.get("city"):
        return _begin_address(user_id, prefix=texts.GEO_FAILED + "\n\n")

    cities = _known_cities()
    matches = [known for known in cities if normalize_city(known) == normalize_city(found["city"])]
    if cities and not matches:
        reply = texts.CITY_UNKNOWN.format(city=found["city"], cities=", ".join(cities))
        states.set_state(user_id, "addr_city", {})
        return reply, keyboards.city_menu(cities)
    data = {"city": matches[0] if matches else found["city"]}

    street = None
    if found.get("street"):
        streets = api.find_streets(data["city"], found["street"])
        if streets and normalize_street(streets[0]) == normalize_street(found["street"]):
            street = streets[0]
    if street is None:
        states.set_state(user_id, "addr_street", data)
        partial = texts.GEO_PARTIAL.format(found=data["city"])
        return f"{partial}\n\n{texts.ASK_STREET}", keyboards.cancel_only()

    data["street"] = street
    if not found.get("house_number"):
        states.set_state(user_id, "addr_house", data)
        partial = texts.GEO_PARTIAL.format(found=f'{data["city"]}, {street}')
        return f"{partial}\n\n{texts.ASK_HOUSE}", keyboards.cancel_only()

    data["house_number"] = found["house_number"]
    data["house_corpus"] = found.get("house_corpus")
    states.set_state(user_id, "addr_geo_confirm", data)
    return texts.GEO_CONFIRM.format(address=full_address(data)), keyboards.geo_confirm_menu()


def _addresses_view(user_id, prefix=""):
    addresses = api.list_addresses(user_id)
    if not addresses:
        return prefix + texts.NO_ADDRESSES_LEFT, keyboards.no_address_menu()
    lines = []
    for address in addresses:
        line = "• " + full_address(address) + (" — основной" if address["is_primary"] else "")
        company = api.lookup_company(
            address["city"], address["street"], address["house_number"], address.get("house_corpus")
        )
        line += f"\n  УК: {company['name']}" if company else "\n  УК не найдена в справочнике"
        lines.append(line)
    reply = prefix + texts.MY_ADDRESSES.format(addresses="\n".join(lines))
    return reply, keyboards.address_menu(addresses, short_address)


def handle_my_address(message: Incoming):
    return _addresses_view(message.user_id)


def _own_address(user_id, argument):
    if not argument.isdigit():
        return None
    return next((a for a in api.list_addresses(user_id) if a["id"] == int(argument)), None)


def handle_make_primary(message: Incoming, argument: str):
    address = _own_address(message.user_id, argument)
    if address is None:
        return _addresses_view(message.user_id, prefix=texts.ADDRESS_NOT_YOURS + "\n\n")
    api.set_primary_address(address["id"])
    prefix = texts.ADDRESS_PRIMARY_SET.format(address=full_address(address)) + "\n\n"
    return _addresses_view(message.user_id, prefix=prefix)


def handle_delete_address(message: Incoming, argument: str):
    address = _own_address(message.user_id, argument)
    if address is None:
        return _addresses_view(message.user_id, prefix=texts.ADDRESS_NOT_YOURS + "\n\n")
    api.delete_address(address["id"])
    prefix = texts.ADDRESS_DELETED.format(address=full_address(address)) + "\n\n"
    return _addresses_view(message.user_id, prefix=prefix)


# --- отключения ---
def handle_outages(message: Incoming):
    address = api.get_primary_address(message.user_id)
    if address is None:
        return texts.NO_ADDRESS, keyboards.no_address_menu()

    now = local_now()
    outages = api.list_outages_for_address(address, ends_after=now)
    if not outages:
        return texts.NO_OUTAGES.format(address=full_address(address)), keyboards.main_menu()

    outages = sorted(outages, key=lambda outage: outage["starts_at"])
    lines = [
        texts.OUTAGE_LINE.format(
            utility=texts.UTILITY_NAMES.get(outage["utility"], outage["utility"]),
            when=outage_when(outage, now),
            reason=outage.get("reason") or "не указана",
        )
        for outage in outages
    ]
    reply = texts.OUTAGES_TITLE.format(address=full_address(address), outages="\n\n".join(lines))
    if any(outage.get("source") == "demo" for outage in outages):
        reply += texts.DEMO_DATA_NOTE
    return reply, keyboards.main_menu()


def outage_alert_text(address_text: str, outage, now: datetime | None = None) -> str:
    """Текст уведомления об отключении, которое рассылает бот."""
    reply = texts.OUTAGE_ALERT.format(
        address=address_text,
        utility=texts.UTILITY_ACCUSATIVE.get(outage["utility"], outage["utility"]),
        when=outage_when(outage, now).capitalize(),
        reason=outage.get("reason") or "не указана",
    )
    if outage.get("source") == "demo":
        reply += texts.DEMO_DATA_NOTE
    return reply


# --- обращение ---
def handle_appeal(message: Incoming):
    user_id = message.user_id
    address = api.get_primary_address(user_id)
    if address is None:
        return texts.NO_ADDRESS, keyboards.no_address_menu()
    company = api.lookup_company(
        address["city"], address["street"], address["house_number"], address.get("house_corpus")
    )
    if company is None:
        reply = texts.APPEAL_NO_COMPANY.format(address=full_address(address))
        return reply, [[texts.BTN_MY_ADDRESS], [texts.BTN_MENU]]

    states.set_state(user_id, "appeal_category", {
        "address": address,
        "company": {key: company.get(key) for key in ("id", "name", "phone", "email")},
        "photos": [],
    })
    reply = texts.ASK_CATEGORY.format(company=company["name"], address=full_address(address))
    return reply, keyboards.category_menu()


def _appeal_dialog(message: Incoming, state):
    user_id = message.user_id
    step, data = state["step"], state["data"]
    text = (message.text or "").strip()
    normalized = _norm(text)

    if step == "appeal_category":
        categories = {_norm(category): category for category in texts.CATEGORIES}
        if normalized not in categories:
            return texts.ASK_CATEGORY.format(
                company=data["company"]["name"], address=full_address(data["address"])
            ), keyboards.category_menu()
        data["category"] = categories[normalized]
        states.set_state(user_id, "appeal_text", data)
        hint = ""
        if data["category"] in texts.URGENT_CATEGORIES:
            phone = data["company"].get("phone")
            hint = texts.URGENT_HINT.format(phone=f" по телефону {phone}" if phone else "")
        return texts.ASK_MESSAGE.format(hint=hint), keyboards.cancel_only()

    if step == "appeal_text":
        _add_photos(data, message.photos)
        if not text:
            if message.photos:
                states.set_state(user_id, "appeal_text", data)
                return texts.PHOTO_ONLY_SAVED.format(count=len(data["photos"])), keyboards.cancel_only()
            return texts.ASK_MESSAGE.format(hint=""), keyboards.cancel_only()
        if len(text) < MIN_MESSAGE_LENGTH:
            return texts.MESSAGE_TOO_SHORT, keyboards.cancel_only()
        data["message"] = text
        if data["photos"]:
            return _ask_contact(user_id, data)
        states.set_state(user_id, "appeal_photo", data)
        return texts.ASK_PHOTO, keyboards.photo_menu()

    if step == "appeal_photo":
        if message.photos:
            _add_photos(data, message.photos)
            return _ask_contact(user_id, data)
        if normalized == _norm(texts.BTN_SKIP_PHOTO):
            return _ask_contact(user_id, data)
        return texts.PHOTO_EXPECTED, keyboards.photo_menu()

    if step == "appeal_contact":
        if message.contact is not None:
            data["contact"] = geo.contact_from_attachment(message.contact)
        elif normalized == _norm(texts.BTN_CONTACT_NAME):
            data["contact"] = _profile_contact(user_id)
        elif normalized == _norm(texts.BTN_CONTACT_NO):
            data["contact"] = None
        else:
            return texts.CONTACT_EXPECTED, keyboards.contact_menu()
        states.set_state(user_id, "appeal_confirm", data)
        return _confirm_text(data), keyboards.confirm_menu()

    if step == "appeal_confirm":
        if normalized == _norm(texts.BTN_SEND):
            return _submit_appeal(user_id, data)
        return texts.CONFIRM_EXPECTED, keyboards.confirm_menu()

    states.clear_state(user_id)
    return texts.MENU, keyboards.main_menu()


def _add_photos(data, photos):
    for url in photos:
        if len(data["photos"]) < MAX_PHOTOS and url not in data["photos"]:
            data["photos"].append(url)


def _ask_contact(user_id, data):
    states.set_state(user_id, "appeal_contact", data)
    return texts.ASK_CONTACT, keyboards.contact_menu()


def _profile_contact(user_id):
    profile = profiles.get(user_id) or {}
    parts = []
    if profile.get("name"):
        parts.append(profile["name"])
    if profile.get("username"):
        parts.append(f'@{profile["username"]}')
    return " ".join(parts) or None


def _confirm_text(data):
    return texts.APPEAL_CONFIRM.format(
        company=data["company"]["name"],
        address=full_address(data["address"]),
        category=data["category"],
        contact=data.get("contact") or "не указан",
        photos=len(data["photos"]) or "нет",
        message=data["message"],
    )


def _submit_appeal(user_id, data):
    appeal = api.create_appeal(
        user_id,
        data["address"]["id"],
        data["category"],
        data["message"],
        contact=data.get("contact"),
        photos=len(data["photos"]),
    )
    states.clear_state(user_id)
    workers.enqueue_send(workers.SendJob(
        user_id=user_id,
        number=appeal["number"],
        company=data["company"],
        category=data["category"],
        message=data["message"],
        address_text=appeal["address_text"],
        contact=data.get("contact"),
        photos=list(data["photos"]),
        uk_link=appeal["uk_link"],
    ))
    reply = texts.APPEAL_ACCEPTED.format(number=appeal["number"], company=data["company"]["name"])
    return reply, keyboards.main_menu()


# --- мои обращения ---
def handle_my_appeals(message: Incoming):
    appeals = api.list_appeals(message.user_id)
    if not appeals:
        return texts.NO_APPEALS, [[texts.BTN_APPEAL], [texts.BTN_MENU]]

    companies = {}
    lines = []
    for appeal in appeals:
        company_id = appeal.get("company_id")
        if company_id not in companies:
            companies[company_id] = api.get_company(company_id)
        company = companies[company_id]
        line = texts.APPEAL_LINE.format(
            number=appeal["number"],
            subject=appeal["subject"],
            date=_parse_dt(appeal["created_at"]).strftime("%d.%m.%Y"),
            company=company["name"] if company else "УК не найдена",
            status=texts.STATUS_LABELS.get(appeal["status"], appeal["status"]),
        )
        if appeal.get("uk_comment"):
            line += texts.APPEAL_COMMENT.format(comment=appeal["uk_comment"])
        lines.append(line)

    retry = [a["number"] for a in appeals if a["status"] in ("failed", "new") and a.get("company_id")]
    reply = texts.MY_APPEALS.format(count=len(appeals), appeals="\n\n".join(lines))
    return reply, keyboards.resend_menu(retry[:3])


def handle_resend(message: Incoming, number: str):
    own = {a["number"]: a for a in api.list_appeals(message.user_id, limit=100)}
    appeal = own.get(number)
    if appeal is None:
        return texts.NO_APPEALS, keyboards.main_menu()
    if appeal["status"] not in ("failed", "new"):
        return texts.RESEND_NOT_NEEDED.format(number=number), keyboards.main_menu()
    company = api.get_company(appeal.get("company_id"))
    if company is None:
        return texts.APPEAL_NO_COMPANY.format(address=appeal["address_text"]), keyboards.main_menu()

    workers.enqueue_send(workers.SendJob(
        user_id=message.user_id,
        number=number,
        company={key: company.get(key) for key in ("id", "name", "phone", "email")},
        category=appeal["subject"],
        message=appeal["text"],
        address_text=appeal["address_text"],
        contact=appeal.get("contact"),
        photos=workers.cached_photos(number),
        uk_link=appeal["uk_link"],
    ))
    return texts.RESEND_STARTED.format(number=number), keyboards.main_menu()


# --- настройки ---
def _settings_reply(settings, prefix=""):
    text = texts.SETTINGS_STATUS.format(
        master=texts.ON if settings["notify_outages"] else texts.OFF,
        water=texts.ON if settings["notify_water"] else texts.OFF,
        electricity=texts.ON if settings["notify_electricity"] else texts.OFF,
        hours=settings["notify_hours_before"],
    )
    return prefix + text, keyboards.settings_menu(settings)


def handle_settings(message: Incoming):
    return _settings_reply(api.get_settings(message.user_id))


def handle_toggle_water(message: Incoming):
    settings = api.get_settings(message.user_id)
    return _settings_reply(api.update_settings(message.user_id, notify_water=not settings["notify_water"]))


def handle_toggle_electricity(message: Incoming):
    settings = api.get_settings(message.user_id)
    updated = api.update_settings(message.user_id, notify_electricity=not settings["notify_electricity"])
    return _settings_reply(updated)


def handle_all_off(message: Incoming):
    return _settings_reply(api.update_settings(message.user_id, notify_outages=False))


def handle_all_on(message: Incoming):
    settings = api.get_settings(message.user_id)
    fields = {"notify_outages": True}
    if not settings["notify_water"] and not settings["notify_electricity"]:
        fields.update(notify_water=True, notify_electricity=True)
    return _settings_reply(api.update_settings(message.user_id, **fields))


def handle_ask_hours(message: Incoming):
    states.set_state(message.user_id, "settings_hours")
    return texts.ASK_HOURS, keyboards.hours_menu()


def handle_hours_button(message: Incoming, argument: str):
    return _save_hours(message.user_id, argument)


def _hours_step(message: Incoming):
    return _save_hours(message.user_id, (message.text or "").strip())


def _save_hours(user_id, value):
    if not value.isdigit() or not 0 <= int(value) <= 72:
        states.set_state(user_id, "settings_hours")
        return texts.ASK_HOURS, keyboards.hours_menu()
    states.clear_state(user_id)
    updated = api.update_settings(user_id, notify_hours_before=int(value))
    return _settings_reply(updated, prefix=texts.HOURS_SAVED.format(hours=int(value)) + "\n\n")
