"""Задевает ли отключение адрес жильца.

Источник отключений пишет дома строкой: «1-15, 12к2». Жилец вводит
улицу как привык: «ул. Ленина», «Ленина», «улица Ленина». Поэтому улица
сравнивается после normalize_street, а дом ищется в разобранном списке.
"""
from app.services.addresses import normalize_corpus, normalize_street, parse_house_list


def normalize_city(city: str) -> str:
    return city.strip().lower().replace("ё", "е")


def house_in_list(houses_raw: str, house_number: int, house_corpus: str | None) -> bool:
    """Есть ли дом в списке источника.

    Дом с корпусом попадает и под диапазон без корпуса: «1-15» задевает
    и «12к2» — источник обычно перечисляет номера, а не отдельные корпуса.
    """
    try:
        houses = parse_house_list(houses_raw)
    except ValueError:
        # кривой список домов в источнике не должен ронять весь ответ
        return False
    house_corpus = normalize_corpus(house_corpus)
    if (house_number, house_corpus) in houses:
        return True
    return house_corpus is not None and (house_number, None) in houses


def outage_covers(
    outage_city: str,
    outage_street: str,
    houses_raw: str,
    *,
    city: str | None,
    street: str | None,
    house_number: int | None,
    house_corpus: str | None = None,
) -> bool:
    """Задевает ли отключение адрес. Пустые части адреса не проверяются."""
    if city and normalize_city(outage_city) != normalize_city(city):
        return False
    if street and normalize_street(street) != normalize_street(outage_street):
        return False
    if house_number is None:
        return True
    return house_in_list(houses_raw, house_number, house_corpus)


def find_affected_users(street: str, houses_raw: str, addresses: list[dict]) -> list[dict]:
    """Адреса из списка, которые задевает отключение на улице street."""
    return [
        address
        for address in addresses
        if outage_covers(
            address.get("city", ""),
            street,
            houses_raw,
            city=None,
            street=address["street"],
            house_number=address["house_number"],
            house_corpus=address.get("house_corpus"),
        )
    ]
