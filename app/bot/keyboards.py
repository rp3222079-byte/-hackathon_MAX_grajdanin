from app.bot import texts

def main_menu():
    return [
        [texts.BTN_MY_ADDRESS], 
        [texts.BTN_OUTAGES], 
        [texts.BTN_APPEAL]
    ]
def category_menu():
    return [[category] for category in texts.CATEGORIES]


def skip_photo_menu():
    return [[texts.BTN_SKIP_PHOTO]]


def confirm_menu():
    return [[texts.BTN_CONFIRM_YES], [texts.BTN_CONFIRM_NO]]