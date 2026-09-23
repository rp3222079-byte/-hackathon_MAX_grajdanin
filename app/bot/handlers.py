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
    reply_text = "IN_PROCESS"
    reply_keyboard = keyboards.main_menu()
    return reply_text, reply_keyboard

def handle_appeal(message_text):
    reply_text = "IN_PROCESS"
    reply_keyboard = keyboards.main_menu()
    return reply_text, reply_keyboard