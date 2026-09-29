# app/bot/main.py
import time

from app.bot import handlers, keyboards, profiles, states, texts
from app.bot.client import MaxClient


def route(user_id, message_text):
    normalized = texts.normalize_input(message_text)

    if normalized == "/start":            # /start всегда выводит из любого диалога
        states.clear_state(user_id)

    state = states.get_state(user_id)
    if state is not None:
        return handlers.handle_appeal_dialog(user_id, message_text, state)

    if normalized == "/start":
        return handlers.handle_start(user_id, message_text)
    elif normalized == "/help":
        return handlers.handle_help(message_text)
    elif normalized == texts.normalize_input(texts.BTN_MY_ADDRESS):
        return handlers.handle_my_address(user_id, message_text)
    elif normalized == texts.normalize_input(texts.BTN_ADD_ADDRESS):
        return handlers.handle_add_address(user_id, message_text)
    elif normalized == texts.normalize_input(texts.BTN_OUTAGES):
        return handlers.handle_outages(user_id, message_text)
    elif normalized == texts.normalize_input(texts.BTN_APPEAL):
        return handlers.handle_appeal(user_id, message_text)
    else:
        return texts.UNKNOWN, keyboards.main_menu()


def handle_update(client, update):
    kind = update.get("update_type")

    if kind == "bot_started":
        person = update["user"]
        text = "/start"
    elif kind == "message_created":
        message = update["message"]
        person = message["sender"]
        text = (message.get("body") or {}).get("text") or ""
    elif kind == "message_callback":
        callback = update["callback"]
        person = callback["user"]
        text = callback.get("payload") or ""
        try:
            client.answer_callback(callback["callback_id"])
        except Exception as error:
            print("answer_callback error:", error, flush=True)
    else:
        return

    user_id = person["user_id"]
    print(f"[{kind}] user={user_id} text={text!r}", flush=True)
    profiles.remember(user_id, person.get("name"), person.get("username"))

    try:
        reply_text, reply_keyboard = route(user_id, text)
    except Exception as error:   # API недоступен и т.п. — жилец получает понятный ответ
        print("route error:", error, flush=True)
        reply_text, reply_keyboard = texts.ERROR, keyboards.main_menu()
    client.send_message(user_id, reply_text, reply_keyboard)


def run():
    client = MaxClient()
    print("Бот запущен:", client.get_me().get("name"), flush=True)

    marker = None
    while True:
        try:
            data = client.get_updates(marker=marker)
        except Exception as error:
            print("get_updates error:", error, flush=True)
            time.sleep(5)
            continue

        marker = data.get("marker", marker)
        for update in data.get("updates", []):
            try:
                handle_update(client, update)
            except Exception as error:
                print("handle_update error:", error, flush=True)


if __name__ == "__main__":
    run()