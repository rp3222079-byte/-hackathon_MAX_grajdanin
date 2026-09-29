from app.bot import texts

def main_menu():
    return [
        [texts.BTN_MY_ADDRESS], 
        [texts.BTN_OUTAGES], 
        [texts.BTN_APPEAL],
        [texts.BTN_MY_APPEALS],
        [texts.BTN_SETTINGS]
    ]
def category_menu():
    return [[category] for category in texts.CATEGORIES]

def skip_photo_menu():
    return [[texts.BTN_SKIP_PHOTO]]

def confirm_menu():
    return [[texts.BTN_CONFIRM_YES], [texts.BTN_CONFIRM_NO]]

def contact_menu():
    return [[texts.BTN_CONTACT_YES], [texts.BTN_CONTACT_NO]]

def address_menu():
    return [[texts.BTN_ADD_ADDRESS]] + main_menu()

def settings_menu():
    return [
        [texts.BTN_TOGGLE_WATER],
        [texts.BTN_TOGGLE_ELECTRICITY],
        [texts.BTN_SET_HOURS],
        [texts.BTN_UNSUBSCRIBE_ALL],
        [texts.BTN_MY_ADDRESS],
        [texts.BTN_OUTAGES],
        [texts.BTN_APPEAL],
        [texts.BTN_MY_APPEALS],
    ]
