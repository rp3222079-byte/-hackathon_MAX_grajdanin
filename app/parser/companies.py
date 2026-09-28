"""Разбор выгрузок ГИС ЖКХ: поставщики информации и объекты жилищного фонда.

На сайте dom.gosuslugi.ru две открытые выгрузки описывают одну и ту же
жизнь дома с разных сторон:

* реестр поставщиков информации — организации, которые ведут себя
  в ГИС ЖКХ: название, ОГРН, email, телефон, сайт;
* сведения об объектах жилищного фонда — дома: адрес, тип, способ
  управления и ОГРН организации, которая домом управляет.

Связь между ними — ОГРН. По нему собирается справочник: контакты
управляющей компании и список домов, за ней закреплённых.
"""
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from app.parser import downloader, xlsx

# Колонки реестра поставщиков информации
COL_FULL_NAME = "Полное наименование"
COL_SHORT_NAME = "Сокращенное наименование"
COL_OGRN = "ОГРН"
COL_SITE = "Официальный сайт в сети Интернет"
COL_PHONE = "Телефон"
COL_EMAIL = "Адрес электронной почты"
COL_FUNCTION = "Функция"

# Колонки выгрузки объектов жилищного фонда
OZHF_ADDRESS = "Адрес ОЖФ"
OZHF_HOUSE_TYPE = "Тип дома"
OZHF_MANAGEMENT = "Способ управления"
OZHF_OGRN = "ОГРН организации, осуществляющей управление домом"
OZHF_ORG_NAME = "Наименование организации, осуществляющей управление домом"
OZHF_STATE = "Состояние"

# Дом считаем управляемым, если в графе способа управления стоит
# управляющая организация, товарищество или кооператив
MANAGED_BY_ORGANIZATION = ("УО", "ТСЖ", "ЖК")

APARTMENT_HOUSE = "Многоквартирный"

# Сокращения вида элемента адреса из выгрузки ОЖФ
_STREET_PREFIXES = {
    "ул": "улица",
    "улица": "улица",
    "просп": "проспект",
    "проспект": "проспект",
    "пр-кт": "проспект",
    "пер": "переулок",
    "переулок": "переулок",
    "ш": "шоссе",
    "шоссе": "шоссе",
    "б-р": "бульвар",
    "бульвар": "бульвар",
    "пл": "площадь",
    "площадь": "площадь",
    "наб": "набережная",
    "набережная": "набережная",
    "пр-д": "проезд",
    "проезд": "проезд",
    "мкр": "микрорайон",
    "микрорайон": "микрорайон",
    "тер": "территория",
    "территория": "территория",
    "ст": "станция",
    "станция": "станция",
    "аул": "аул",
    "кп": "коттеджный посёлок",
    "дп": "дачный посёлок",
    "ж/д": "железнодорожная станция",
    "мгстр": "малоэтажная застройка",
    "п": "посёлок",
    "с": "село",
    "д": "деревня",
    "г": "город",
    "рп": "рабочий посёлок",
    "р-н": "район",
    "г.о": "городской округ",
    "мгс": "малоэтажная застройка",
}

# Графы адреса, из которых собираем дом
_HOUSE_LABELS = ("д", "дом", "вл", "владение")
_CORPUS_LABELS = ("корп", "к", "стр", "строение", "корпус")
# Строение без отдельного «д.»: «ул. Сосновая, строение 8»
_BUILDING_LABELS = ("сооружение",)

_POSTCODE = re.compile(r"^\d{6}$")
# Корпус в адресе приходит словами: «д. 27, строение 1» или «д. 27, к 2»
_CORPUS_WORD = re.compile(r"^(?P<label>[^0-9]+?)[\s.]*(?P<value>\d+)$")
_HOUSE_NUMBER = re.compile(r"^\d+")
# В названиях улиц встречаются цифры: «6-я Парковая»
_STREET_WITH_DIGITS = re.compile(r"^\d+-?[яей]?\s", re.IGNORECASE)


@dataclass
class Place:
    """Адрес дома, разобранный на части."""

    city: str
    street: str
    number: int
    corpus: str | None = None


@dataclass
class Provider:
    """Организация из реестра поставщиков информации."""

    ogrn: str
    name: str
    email: str = ""
    phone: str = ""
    website: str = ""
    function: str = ""


@dataclass
class House:
    """Дом из выгрузки объектов жилищного фонда."""

    city: str
    street: str
    number: int
    corpus: str | None
    ogrn: str
    house_type: str = ""


@dataclass
class CompanyDirectory:
    """Управляющая компания с адресами и списком домов."""

    name: str
    email: str = ""
    phone: str = ""
    website: str = ""
    city: str = ""
    ogrn: str = ""
    streets: dict[str, set[tuple[int, str | None]]] = field(default_factory=dict)

    def add(self, house: House) -> None:
        self.streets.setdefault(house.street, set()).add((house.number, house.corpus))

    @property
    def houses_count(self) -> int:
        return sum(len(items) for items in self.streets.values())


def read_providers(xlsx_path: Path) -> Iterator[Provider]:
    """Организации из реестра поставщиков информации."""
    for row in xlsx.read_dicts(xlsx_path):
        ogrn = (row.get(COL_OGRN) or "").strip()
        if not ogrn.isdigit():
            continue
        name = _clean(row.get(COL_SHORT_NAME)) or _clean(row.get(COL_FULL_NAME))
        if not name:
            continue
        yield Provider(
            ogrn=ogrn,
            name=name,
            email=_clean(row.get(COL_EMAIL)),
            phone=_clean(row.get(COL_PHONE)),
            website=_clean(row.get(COL_SITE)),
            function=_clean(row.get(COL_FUNCTION)),
        )


def read_houses(csv_path: Path, city: str) -> Iterator[House]:
    """Многоквартирные дома выбранного города с управляющей организацией."""
    wanted = city.strip().lower()
    for row in downloader.read_ozhf_rows(csv_path):
        if (row.get(OZHF_MANAGEMENT) or "").strip() not in MANAGED_BY_ORGANIZATION:
            continue
        if (row.get(OZHF_HOUSE_TYPE) or "").strip() != APARTMENT_HOUSE:
            continue
        ogrn = (row.get(OZHF_OGRN) or "").strip()
        if not ogrn.isdigit():
            continue
        place = parse_address(row.get(OZHF_ADDRESS) or "")
        if place is None or place.city.lower() != wanted:
            continue
        yield House(
            city=place.city,
            street=place.street,
            number=place.number,
            corpus=place.corpus,
            ogrn=ogrn,
            house_type=(row.get(OZHF_HOUSE_TYPE) or "").strip(),
        )


def build_directory(
    providers_path: Path, houses_path: Path, city: str
) -> dict[str, CompanyDirectory]:
    """Справочник УК города: компании с контактами и своими домами.

    Дом без организации в реестре поставщиков пропускаем: отправлять
    обращение некуда, а company.email в таблице обязателен.
    """
    providers = {provider.ogrn: provider for provider in read_providers(providers_path)}
    directory: dict[str, CompanyDirectory] = {}
    for house in read_houses(houses_path, city):
        provider = providers.get(house.ogrn)
        if provider is None:
            continue
        company = directory.get(provider.ogrn)
        if company is None:
            company = CompanyDirectory(
                name=provider.name,
                email=provider.email or f"ogrn{provider.ogrn}@gis.jkh",
                phone=provider.phone,
                website=provider.website,
                city=house.city,
                ogrn=provider.ogrn,
            )
            directory[provider.ogrn] = company
        company.add(house)
    return directory


def parse_address(raw: str) -> Place | None:
    """Разбирает адрес из выгрузки ОЖФ.

    Адрес приходит одной строкой: «630001, Новосибирская обл,
    г. Новосибирск, ул. Кирова, д. 27», иногда с корпусом
    отдельной графой: «д. 27, строение 1». Название города и
    региона отбрасываем, остальное приводим к виду справочника
    проекта: «улица Кирова», дом 27, корпус «к1».
    """
    parts = [part.strip() for part in raw.split(",") if part.strip()]
    if len(parts) < 4:
        return None

    index = 0
    if _POSTCODE.match(parts[index]):
        index += 1
    if index >= len(parts):
        return None
    index += 1  # регион

    city = _place_name(parts[index]) if index < len(parts) else ""
    if not city:
        return None
    index += 1

    street = ""
    number = 0
    corpus: str | None = None
    for part in parts[index:]:
        label, value = _split_label(part)
        if not _HOUSE_NUMBER.match(value):
            # «д. Умна, ул. Береговая» — Умна это деревня, а не улица
            if not street and value and label not in _HOUSE_LABELS:
                street = _street_name(label, value)
            continue
        if label in _HOUSE_LABELS or label in _BUILDING_LABELS:
            if not number:
                number, corpus = _parse_house(value)
        elif label in _CORPUS_LABELS:
            # «стр. 22» без отдельного «д.» — это и есть номер дома,
            # а «д. 27, стр. 1» — уже корпус
            if not number:
                number, _ = _parse_house(value)
            elif corpus is None:
                corpus = _corpus_name(value)
        elif not street:
            street = _street_name(label, value)

    if not street or not number:
        return None
    return Place(city=city, street=street, number=number, corpus=corpus)


def _split_label(part: str) -> tuple[str, str]:
    """Делит графу адреса на вид и значение: «д. 27» -> («д», «27»)."""
    head, _, tail = part.partition(" ")
    label = head.rstrip(".").lower()
    if label in _HOUSE_LABELS or label in _CORPUS_LABELS or label in _STREET_PREFIXES:
        return label, tail.strip()
    if label in _BUILDING_LABELS:
        return label, tail.strip()
    return "", part


def _place_name(part: str) -> str:
    """«г. Новосибирск» -> «Новосибирск», «р-н. X» -> «X».

    Вид населённого пункта не расшифровываем: в справочнике город
    хранится так, как его вводит пользователь при регистрации.
    """
    label, value = _split_label(part)
    del label
    return value if value else ""


def _street_name(label: str, value: str) -> str:
    """«ул. Кирова» -> «улица Кирова», «6-я Парковая ул» -> «6-я Парковая».

    Тип улицы в выгрузке встречается и в начале, и в конце названия.
    Регистр не трогаем: сравнение адресов идёт через normalize_street,
    который всё равно приводит текст вниз.
    """
    name = value.strip()
    if not name:
        return ""
    tail = name.rsplit(" ", 1)
    if len(tail) == 2 and tail[1].rstrip(".").lower() in _STREET_PREFIXES:
        name = tail[0].strip()
    if label and label in _STREET_PREFIXES and not _STREET_WITH_DIGITS.match(name):
        return f"{_STREET_PREFIXES[label]} {name}".strip()
    return name


def _parse_house(value: str) -> tuple[int, str | None] | None:
    match = _HOUSE_NUMBER.match(value.strip())
    if not match:
        return None
    rest = value.strip()[match.end() :]
    corpus = _corpus_name(rest) if rest else None
    return int(match.group()), corpus


def _corpus_name(value: str) -> str | None:
    """Приводит корпус к виду справочника: «1» или «строение 1» -> «к1»."""
    text = value.strip()
    if not text:
        return None
    match = _CORPUS_WORD.match(text)
    number = match.group("value") if match else (text if text.isdigit() else "")
    return f"к{number}" if number else None


def _clean(value: str | None) -> str:
    return (value or "").strip()
