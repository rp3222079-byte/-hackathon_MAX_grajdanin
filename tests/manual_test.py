from app.bot import texts, keyboards, handlers, states

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


if __name__ == "__main__":
    fake_user_id = 1
    while True:
        user_input = input("Вы: ")
        reply_text, reply_keyboard = route(fake_user_id, user_input)
        print("Бот:", reply_text)
        print("Клавиатура:", reply_keyboard)