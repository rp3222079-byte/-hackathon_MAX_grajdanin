#формирует текст уведомления
def format_outage_message(outage: dict, address: dict) -> str:
    utility_names = {
        "water": "воду",
        "electricity": "свет",
    }
    utility = utility_names.get(outage["type"], outage["type"])

    street = address["street"]
    house = address["house_number"]
    corpus = address.get("house_corpus")
    house_str = f"{house}{corpus}" if corpus else str(house)

    return (
        f"Отключат {utility} по адресу {street}, {house_str}.\n"
        f"Начало: {outage['start']}\n"
        f"Окончание: {outage['end']}\n"
        f"Причина: {outage['reason']}"
    )
# Находим затронутых пользователей и формируем уведомления без повторной отправки
def notify_affected_users(outage: dict, addresses: list[dict], sent_notifications: set[tuple[int, int]]) -> list[dict]: 
    from app.services.matching import find_affected_users
    houses_raw = outage["houses_raw"]
    street = outage["street"]
    
    affected = find_affected_users(street, houses_raw, addresses)
    sent_now = []
    for address in affected:
        key = (address["user_id"], outage["id"])
        if key in sent_notifications:
            continue
        message = format_outage_message(outage, address)
        sent_now.append({"user_id": address["user_id"], "message": message})
        sent_notifications.add(key)
    
    return sent_now

if __name__ == "__main__":
    fake_outage = {
        "type": "water",
        "start": "2026-09-28 10:00",
        "end": "2026-09-28 18:00",
        "reason": "плановый ремонт",
    }

    fake_address = {
        "user_id": 1,
        "street": "Ленина",
        "house_number": 7,
        "house_corpus": None,
    }

    fake_outage_full = {
        "id": 101,
        "type": "water",
        "start": "2026-09-28 10:00",
        "end": "2026-09-28 18:00",
        "reason": "плановый ремонт",
        "street": "Ленина",
        "houses_raw": "1-15",
    }

    fake_addresses = [
        {"user_id": 1, "street": "Ленина", "house_number": 7, "house_corpus": None},
        {"user_id": 2, "street": "Мира", "house_number": 5, "house_corpus": None},
    ]

    sent = set()

    result1 = notify_affected_users(fake_outage_full, fake_addresses, sent)
    print("Первый вызов:", result1)

    result2 = notify_affected_users(fake_outage_full, fake_addresses, sent)
    print("Второй вызов:", result2)