from app.bot import texts, keyboards, handlers
import time
def route(message_text):
    if message_text == "/start":
        return handlers.handle_start(message_text)
    elif message_text == "/help" :
        return handlers.handle_help(message_text)
    elif message_text == texts.BTN_MY_ADDRESS:
        return handlers.handle_my_address(message_text)
    elif message_text == texts.BTN_OUTAGES:
        return handlers.handle_outages(message_text)
    elif message_text == texts.BTN_APPEAL:
        return handlers.handle_appeal(message_text)
    else : 
        return texts.UNKNOWN, keyboards.main_menu()

if __name__ == "__main__":
    print("Бот запущен (заглушка, ждём токен MAX)")
    while True:
        time.sleep(10)
        print("bot: жив, жду токен для подключения к MAX API")