"""Адрес по геолокации и контакт из карточки MAX.

Геолокацию жилец отправляет кнопкой MAX «Отправить геолокацию»;
адрес по координатам определяет открытый геокодер OpenStreetMap
Nominatim (GEOCODER_URL, пустое значение выключает функцию).
Результат жилец обязательно подтверждает: координаты неточны.
"""
import logging
import os
import re

import requests

from app.bot.tls import ca_bundle_path
from app.services.addresses import parse_house_fragment

logger = logging.getLogger("domovoy.bot")

DEFAULT_GEOCODER_URL = "https://nominatim.openstreetmap.org/reverse"
# Политика Nominatim требует понятный User-Agent
USER_AGENT = "domovoy-max-bot/1.0 (hackathon MAX, github.com/rp3222079-byte/-hackathon_MAX_grajdanin)"


def geocoder_url() -> str:
    return os.getenv("GEOCODER_URL", DEFAULT_GEOCODER_URL).strip()


def geocoding_enabled() -> bool:
    return bool(geocoder_url())


def parse_nominatim(address: dict) -> dict:
    """Ответ Nominatim → {"city", "street", "house_number", "house_corpus"} (что нашлось)."""
    result: dict = {}
    city = address.get("city") or address.get("town") or address.get("village")
    if city:
        result["city"] = city
    street = address.get("road") or address.get("pedestrian")
    if street:
        result["street"] = street
    house = (address.get("house_number") or "").replace(" ", "")
    if house:
        try:
            number, corpus = parse_house_fragment(house)
        except ValueError:
            number, corpus = None, None
        if number:
            result["house_number"] = number
            result["house_corpus"] = corpus
    return result


def reverse_geocode(latitude: float, longitude: float) -> dict:
    """Адрес по координатам; пустой словарь — если определить не удалось."""
    url = geocoder_url()
    if not url:
        return {}
    try:
        response = requests.get(
            url,
            params={
                "format": "jsonv2",
                "lat": latitude,
                "lon": longitude,
                "zoom": 18,
                "addressdetails": 1,
                "accept-language": "ru",
            },
            headers={"User-Agent": USER_AGENT},
            timeout=10,
            verify=ca_bundle_path(),
        )
        response.raise_for_status()
        return parse_nominatim(response.json().get("address") or {})
    except (requests.RequestException, ValueError) as error:
        logger.warning("Геокодер не ответил: %s", error)
        return {}


_VCARD_LINE = re.compile(r"^(?P<key>[A-Z]+)(?:;[^:]*)?:(?P<value>.*)$")


def parse_vcard(vcf: str | None) -> dict:
    """Имя и телефон из vCard, которую MAX присылает при «Поделиться контактом»."""
    result: dict = {}
    for raw_line in (vcf or "").replace("\r\n", "\n").split("\n"):
        match = _VCARD_LINE.match(raw_line.strip())
        if not match:
            continue
        key, value = match["key"], match["value"].strip()
        if key == "TEL" and value and "phone" not in result:
            result["phone"] = value
        elif key == "FN" and value:
            result["name"] = value
    return result


def contact_from_attachment(payload: dict) -> str | None:
    """Строка контакта для письма УК: «Иван Петров, +79990000000»."""
    card = parse_vcard(payload.get("vcf_info"))
    info = payload.get("max_info") or {}
    name = card.get("name") or " ".join(
        part for part in (info.get("first_name"), info.get("last_name")) if part
    ) or info.get("name")
    parts = [part for part in (name, card.get("phone")) if part]
    return ", ".join(parts) or None
