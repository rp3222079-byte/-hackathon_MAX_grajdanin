import time
from app.bot import texts, keyboards, handlers, states
from app.bot.client import MaxClient

def route(user_id, message_text):
    normalized = texts.normalize_input(message_text)

    state = states.get_state(user_id)
    if state is not None:
        return handlers.handle_appeal_dialog(user_id, normalized, state)

    if normalized == "/start":
        return handlers.handle_start(message_text)
    elif normalized == "/help":
        return handlers.handle_help(message_text)
    elif normalized == texts.normalize_input(texts.BTN_MY_ADDRESS):
        return handlers.handle_my_address(message_text)
    elif normalized == texts.normalize_input(texts.BTN_OUTAGES):
        return handlers.handle_outages(message_text)
    elif normalized == texts.normalize_input(texts.BTN_APPEAL):
        return handlers.handle_appeal(user_id, message_text)
    else:
        return texts.UNKNOWN, keyboards.main_menu()

def handle_update(client, update):
    kind = update.get("update_type")

    if kind == "bot_started":            # пользователь впервые открыл бота
        user_id = update["user"]["user_id"]
        text = "/start"
    elif kind == "message_created":      # обычное текстовое сообщение
        message = update["message"]
        user_id = message["sender"]["user_id"]
        text = (message.get("body") or {}).get("text") or ""
    elif kind == "message_callback":     # нажатие inline-кнопки
        callback = update["callback"]
        user_id = callback["user"]["user_id"]
        text = callback.get("payload") or ""
        try:
            client.answer_callback(callback["callback_id"])
        except Exception as error:
            print("answer_callback error:", error, flush=True)
    else:
        return

    reply_text, reply_keyboard = route(user_id, text)
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
            print("UPDATE:", update, flush=True)   # временно, для отладки
            try:
                handle_update(client, update)
            except Exception as error:
                print("handle_update error:", error, flush=True)


if __name__ == "__main__":
    run()