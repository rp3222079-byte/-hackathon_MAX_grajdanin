# app/bot/handlers.py
from app.bot import api, keyboards, profiles, states, texts
from app.services import mailer
from app.services.addresses import parse_house_fragment


def _addr_str(address):
    text = f'{address["city"]}, {address["street"]}, {address["house_number"]}{address.get("house_corpus") or ""}'
    if address.get("flat"):
        text += f', кв. {address["flat"]}'
    return text


def _format_contact(profile):
    if not profile:
        return None
    parts = []
    if profile.get("name"):
        parts.append(profile["name"])
    if profile.get("username"):
        parts.append(f'@{profile["username"]}')
    return " ".join(parts) or None


# --- простые команды ---
def handle_start(user_id, message_text):
    if not api.list_addresses(user_id):
        states.set_state(user_id, "addr_city")
        return texts.WELCOME + "\n\n" + texts.ASK_CITY, None
    return texts.WELCOME, keyboards.main_menu()


def handle_help(message_text):
    return texts.HELP, None


def handle_my_address(user_id, message_text):
    addresses = api.list_addresses(user_id)
    if not addresses:
        states.set_state(user_id, "addr_city")
        return texts.ASK_CITY, None
    lines = "\n".join(
        "• " + _addr_str(a) + (" (основной)" if a["is_primary"] else "") for a in addresses
    )
    return texts.MY_ADDRESSES.format(addresses=lines), keyboards.address_menu()


def handle_add_address(user_id, message_text):
    states.set_state(user_id, "addr_city")
    return texts.ASK_CITY, None


def handle_outages(user_id, message_text):
    address = api.get_primary_address(user_id)
    if address is None:
        return texts.NO_ADDRESS, keyboards.main_menu()

    outages = api.list_outages_for_address(address)
    if not outages:
        reply_text = texts.NO_OUTAGES
    else:
        reply_text = "\n\n".join(_format_outage(o) for o in outages)
    return reply_text, keyboards.main_menu()


def _format_outage(outage):
    utility_names = {"water": "воду", "electricity": "свет"}
    utility = utility_names.get(outage["utility"], outage["utility"])
    return (
        f"Отключат {utility} по адресу {outage['city']}, {outage['street']}.\n"
        f"Начало: {outage['starts_at']}\n"
        f"Окончание: {outage['ends_at'] or 'не указано'}\n"
        f"Причина: {outage['reason'] or 'не указана'}"
    )


# --- диалог адреса (и первого, и «Добавить адрес») ---
def _address_dialog(user_id, message_text, state):
    step = state["step"]
    data = state["data"]
    value = message_text.strip()

    if step == "addr_city":
        if not value:
            return texts.ASK_CITY, None
        data["city"] = value
        states.set_state(user_id, "addr_street", data)
        return texts.ASK_STREET, None

    if step == "addr_street":
        if not value:
            return texts.ASK_STREET, None
        data["street"] = value
        states.set_state(user_id, "addr_house", data)
        return texts.ASK_HOUSE, None

    if step == "addr_house":
        try:
            number, corpus = parse_house_fragment(value)
        except ValueError:
            return texts.ADDRESS_FAILED, None
        corpus = (corpus or "").strip()
        if number < 1 or (corpus and not corpus[0].isalpha()):
            return texts.ADDRESS_FAILED, None
        data["house_number"] = number
        data["house_corpus"] = corpus or None
        states.set_state(user_id, "addr_flat", data)
        return texts.ASK_FLAT, None

    if step == "addr_flat":
        flat = None
        if value != "-":
            if not value.isdigit() or int(value) < 1:
                return texts.ASK_FLAT, None
            flat = int(value)
        try:
            address = api.add_address(
                user_id, data["city"], data["street"],
                data["house_number"], data.get("house_corpus"), flat,
            )
        except api.ApiError as error:
            if error.status == 409:
                states.clear_state(user_id)
                return texts.ADDRESS_EXISTS, keyboards.main_menu()
            raise
        states.clear_state(user_id)
        return texts.ADDRESS_SAVED.format(address=_addr_str(address)), keyboards.main_menu()

    states.clear_state(user_id)
    return texts.ERROR, keyboards.main_menu()


# --- диалог обращения ---
def handle_appeal(user_id, message_text):
    states.set_state(user_id, "waiting_category")
    return texts.ASK_CATEGORY, keyboards.category_menu()


def handle_appeal_dialog(user_id, message_text, state):
    if state["step"].startswith("addr_"):
        return _address_dialog(user_id, message_text, state)

    step = state["step"]
    data = state["data"]
    normalized = texts.normalize_input(message_text)

    if step == "waiting_category":
        return _appeal_category_step(user_id, normalized)
    elif step == "waiting_message":
        return _appeal_message_step(user_id, message_text, data)
    elif step == "waiting_photo":
        return _appeal_photo_step(user_id, normalized, data)
    elif step == "waiting_contact":
        return _appeal_contact_step(user_id, normalized, data)
    elif step == "waiting_confirm":
        return _appeal_confirm_step(user_id, normalized, data)

    states.clear_state(user_id)
    return texts.ERROR, keyboards.main_menu()


def _appeal_category_step(user_id, normalized):
    normalized_categories = [texts.normalize_input(c) for c in texts.CATEGORIES]
    if normalized not in normalized_categories:
        return texts.ASK_CATEGORY, keyboards.category_menu()

    category = texts.CATEGORIES[normalized_categories.index(normalized)]
    states.set_state(user_id, "waiting_message", {"category": category})
    return texts.ASK_MESSAGE, None


def _appeal_message_step(user_id, message_text, data):
    if not message_text.strip():
        return texts.ASK_MESSAGE, None
    data["message"] = message_text.strip()
    states.set_state(user_id, "waiting_photo", data)
    return texts.ASK_PHOTO, keyboards.skip_photo_menu()


def _appeal_photo_step(user_id, normalized, data):
    if normalized == texts.normalize_input(texts.BTN_SKIP_PHOTO):
        data["photo"] = None
    else:
        data["photo"] = normalized  # заглушка, здесь будет file_id фото
    states.set_state(user_id, "waiting_contact", data)
    return texts.ASK_CONTACT, keyboards.contact_menu()


def _appeal_contact_step(user_id, normalized, data):
    if normalized == texts.normalize_input(texts.BTN_CONTACT_YES):
        data["contact"] = _format_contact(profiles.get(user_id))
    elif normalized == texts.normalize_input(texts.BTN_CONTACT_NO):
        data["contact"] = None
    else:
        return texts.UNKNOWN, keyboards.contact_menu()

    address = api.get_primary_address(user_id)
    if address is None:
        states.clear_state(user_id)
        return texts.NO_ADDRESS, keyboards.main_menu()
    data["address"] = address

    states.set_state(user_id, "waiting_confirm", data)
    confirm_text = texts.APPEAL_CONFIRM.format(
        address=_addr_str(address),
        category=data["category"],
        contact=data["contact"] or "не указан",
        message=data["message"],
    )
    return confirm_text, keyboards.confirm_menu()


def _appeal_confirm_step(user_id, normalized, data):
    if normalized == texts.normalize_input(texts.BTN_CONFIRM_YES):
        if "appeal" not in data:
            try:
                data["appeal"] = api.create_appeal(
                    user_id, data["address"]["id"], data["category"], data["message"],
                )
            except api.ApiError as error:
                print("create_appeal error:", error, flush=True)
                return texts.ERROR, keyboards.confirm_menu()

        appeal = data["appeal"]
        company = api.get_company(appeal.get("company_id"))
        if company is None:
            states.clear_state(user_id)
            return texts.APPEAL_NO_COMPANY, keyboards.main_menu()

        try:
            mailer.send_appeal(
                number=appeal["number"],
                to_email=company["email"],
                company=company["name"],
                category=data["category"],
                message=data["message"],
                address=_addr_str(data["address"]),
                contact=data.get("contact"),
            )
        except mailer.MailError as error:
            print("send_appeal error:", error, flush=True)
            return texts.APPEAL_SEND_FAILED, keyboards.confirm_menu()

        states.clear_state(user_id)
        reply_text = texts.APPEAL_SENT.format(number=appeal["number"], company=company["name"])
        return reply_text, keyboards.main_menu()

    elif normalized == texts.normalize_input(texts.BTN_CONFIRM_NO):
        states.clear_state(user_id)
        return texts.APPEAL_CANCELLED, keyboards.main_menu()

    return texts.UNKNOWN, keyboards.confirm_menu()
