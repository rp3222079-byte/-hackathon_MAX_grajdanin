"""Нормализация адресов и разбор адресных строк из источника.

Источники пишут адреса как попало: «ул. Ленина, д. 1-15, 2, 4», «Ленина ул. 10 к.2».
Здесь всё приводится к паре ключей (street_key, house_key), по которым
отключение сопоставляется с адресом жителя.
"""
from __future__ import annotations

import re

# Слова, которые не несут смысла при сравнении улиц
STREET_NOISE = (
    "улица", "ул", "проспект", "просп", "пр-кт", "пр", "переулок", "пер",
    "бульвар", "б-р", "шоссе", "ш", "проезд", "набережная", "наб",
    "площадь", "пл", "микрорайон", "мкр", "аллея", "тупик",
    "дом", "д", "город", "г", "корпус", "корп", "к", "строение", "стр",
)
NOISE_RE = re.compile(r"\b(" + "|".join(STREET_NOISE) + r")\.?\b", re.IGNORECASE)
HOUSE_RE = re.compile(r"\d+[а-яa-z]?(?:\s*[/\-к.]?\s*\d+)?", re.IGNORECASE)
RANGE_RE = re.compile(r"^(\d+)\s*[-–—]\s*(\d+)$")
# Улицы, начинающиеся с числа: «8 Марта», «1-я Тверская-Ямская»
LEADING_NUMBER_STREET = re.compile(r"^\s*\d+\s*(?:-?[а-я]{1,2})?\s+[а-яa-z]", re.IGNORECASE)


def normalize_street(value: str) -> str:
    """«ул. Ленина» и «Ленина улица» дают одинаковый ключ «ленина»."""
    text = (value or "").lower().replace("ё", "е")
    text = NOISE_RE.sub(" ", text)
    text = re.sub(r"[^\w\s-]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_house(value: str) -> str:
    """«д. 12 к.2», «12к2», «12/2» дают одинаковый ключ «12к2»."""
    text = (value or "").lower().replace("ё", "е")
    text = re.sub(r"\b(дом|д)\.?\s*", " ", text)
    text = re.sub(r"\s*(корпус|корп|кор|к|строение|стр|с)\.?\s*(?=\d)", "к", text)
    text = re.sub(r"[/\\\-–—]+", "к", text)
    text = re.sub(r"[^\w]", "", text)
    return text.strip()


def expand_house_range(value: str) -> list[str]:
    """«1-15» превращает в список домов. Дома с буквами не разворачивает."""
    match = RANGE_RE.match(value.strip())
    if not match:
        return [value.strip()]
    start, end = int(match.group(1)), int(match.group(2))
    if start > end or end - start > 200:
        return [value.strip()]
    return [str(number) for number in range(start, end + 1)]


def parse_address_line(line: str) -> list[tuple[str, str]]:
    """Разбирает строку из источника в пары (street_key, house_key).

    >>> parse_address_line("ул. Ленина, д. 1-3, 7")
    [('ленина', '1'), ('ленина', '2'), ('ленина', '3'), ('ленина', '7')]
    """
    if not line or not line.strip():
        return []

    text = line.replace(";", ",").strip()
    # Улица — это всё до первого числа, дома — всё после.
    # Исключение: название улицы само начинается с числа («8 Марта»).
    offset = 0
    leading = LEADING_NUMBER_STREET.match(text)
    if leading:
        offset = leading.end() - 1
    first_digit = re.search(r"\d", text[offset:])
    if not first_digit:
        return []
    split_at = offset + first_digit.start()
    street_part = text[:split_at]
    houses_part = text[split_at:]

    street_key = normalize_street(street_part)
    if not street_key:
        return []

    pairs: list[tuple[str, str]] = []
    for chunk in houses_part.split(","):
        chunk = chunk.strip(" .")
        if not chunk:
            continue
        for house in expand_house_range(chunk):
            house_key = normalize_house(house)
            if house_key:
                pairs.append((street_key, house_key))

    # Убираем дубли, сохраняя порядок
    seen: set[tuple[str, str]] = set()
    unique: list[tuple[str, str]] = []
    for pair in pairs:
        if pair not in seen:
            seen.add(pair)
            unique.append(pair)
    return unique


def parse_address_block(block: str) -> list[tuple[str, str]]:
    """Разбирает многострочный блок адресов (по строке на улицу)."""
    pairs: list[tuple[str, str]] = []
    for line in (block or "").splitlines():
        pairs.extend(parse_address_line(line))
    return pairs
