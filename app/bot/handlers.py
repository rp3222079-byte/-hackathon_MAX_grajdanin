from app.bot import texts, keyboards
import itertools
from app.bot import states

from app.services.matching import find_affected_users
from app.services.notifier import format_outage_message

def handle_start(message_text):
    reply_text = texts.WELCOME
    reply_keyboard = keyboards.main_menu()
    return reply_text, reply_keyboard

def handle_help(message_text):
    reply_text = texts.HELP
    reply_keyboard = None
    return reply_text, reply_keyboard

def handle_my_address(message_text):
    reply_text = "IN_PROCESS"
    reply_keyboard = keyboards.main_menu()
    return reply_text, reply_keyboard

def handle_outages(message_text):
    return handle_current_outage(message_text)

def handle_appeal(user_id, message_text):
    states.set_state(user_id, "waiting_category")
    return texts.ASK_CATEGORY, keyboards.category_menu()



# временные заглушки — компания и счётчик обращений,
# пока не готовы реальные БД/API (issues #4, #5)
FAKE_COMPANY = {"name": 'УК "Дом"', "email": "uk@example.com"}
_appeal_counter = itertools.count(1)
FAKE_USER_ADDRESS = {
    "user_id": 1,
    "street": "Ленина",
    "house_number": 7,
    "house_corpus": None,
}




def handle_appeal_dialog(user_id, message_text, state) : 
    step = state["step"]
    data = state["data"]

    if step == "waiting_category": 
        return _appeal_category_step(user_id, message_text)
    elif step == "waiting_message" : 
        return _appeal_message_step(user_id, message_text, data)
    elif step == "waiting_photo" : 
        return _appeal_photo_step(user_id, message_text, data)
    elif step == "waiting_confirm":
        return _appeal_confirm_step(user_id, message_text, data)
    else :
        states.clear_state(user_id)
        return texts.ERROR, keyboards.main_menu()

def _appeal_category_step(user_id, message_text):
    normalized_categories = [texts.normalize_input(c) for c in texts.CATEGORIES]
    if message_text not in normalized_categories:
        return texts.ASK_CATEGORY, keyboards.category_menu()

    # находим оригинальное написание категории по нормализованному совпадению
    index = normalized_categories.index(message_text)
    category = texts.CATEGORIES[index]

    states.set_state(user_id, "waiting_message", {"category": category})
    return texts.ASK_MESSAGE, None

def _appeal_message_step(user_id, message_text, data):
    data["message"] = message_text
    states.set_state(user_id, "waiting_photo", data)
    return texts.ASK_PHOTO, keyboards.skip_photo_menu()

def _appeal_photo_step(user_id, message_text, data):
    if message_text == texts.normalize_input(texts.BTN_SKIP_PHOTO): 
        data["photo"] = None 
    else: 
        data["photo"] = message_text #заглушка здесь будет file_id
    states.set_state(user_id, "waiting_confirm", data)

    address = FAKE_USER_ADDRESS
    address_str = f'{address["street"]}, {address["house_number"]}'
    confirm_text = texts.APPEAL_CONFIRM.format(
        address = address_str, 
        category = data["category"], 
        message = data["message"], 
        company = FAKE_COMPANY["name"],
    )
    return confirm_text, keyboards.confirm_menu()

def _appeal_confirm_step(user_id, message_text, data):
    if message_text == texts.normalize_input(texts.BTN_CONFIRM_YES):
        appeal_number = next(_appeal_counter)
        states.clear_state(user_id)
        reply_text = texts.APPEAL_SENT.format(number=appeal_number, company=FAKE_COMPANY["name"])
        return reply_text, keyboards.main_menu()

    elif message_text == texts.normalize_input(texts.BTN_CONFIRM_NO):
        states.clear_state(user_id)
        return texts.APPEAL_CANCELLED, keyboards.main_menu()
    else:
        return texts.UNKNOWN, keyboards.confirm_menu()


# временная "база" — потом заменится на реальные запросы к БД
FAKE_USER_ADDRESS = {
    "user_id": 1,
    "street": "Ленина",
    "house_number": 7,
    "house_corpus": None,
}

FAKE_OUTAGES = [
    {
        "id": 101,
        "type": "water",
        "start": "2026-09-28 10:00",
        "end": "2026-09-28 18:00",
        "reason": "плановый ремонт",
        "street": "Ленина",
        "houses_raw": "1-15",
    },
]
#Обрабатываем запрос пользователя и возвращаем текст ответа и клавиатуру
def handle_current_outage(message_text) : 
    user_address = FAKE_USER_ADDRESS
    matching_outage = []
    for outage in FAKE_OUTAGES :
        affected = find_affected_users(outage["street"], outage["houses_raw"],[user_address])
        if affected:
            matching_outage.append(outage)
    if not matching_outage :
        reply_text = texts.NO_OUTAGES
    else :
        parts = [format_outage_message(outage, user_address) for outage in matching_outage]
        reply_text = "\n\n".join(parts)

    reply_keyboard = keyboards.main_menu()
    return reply_text, reply_keyboard 