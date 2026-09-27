from app.bot import texts, keyboards

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

def handle_appeal(message_text):
    reply_text = "IN_PROCESS"
    reply_keyboard = keyboards.main_menu()
    return reply_text, reply_keyboard


from app.services.matching import find_affected_users
from app.services.notifier import format_outage_message


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