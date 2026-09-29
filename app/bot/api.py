"""Запросы бота к API «Домового».

Бот не обращается к базе напрямую: все данные идут через API, поэтому
логика хранения живёт в одном месте. Каждый поток бота (приём сообщений,
рассылка, отправка писем) получает свою HTTP-сессию.
"""
import os
import threading

import requests

_local = threading.local()
_user_ids: dict[int, int] = {}


class ApiError(Exception):
    def __init__(self, status, detail):
        super().__init__(f"API {status}: {detail}")
        self.status = status
        self.detail = detail


def _base_url() -> str:
    return os.getenv("API_BASE_URL", "http://localhost:8000").rstrip("/")


def _session() -> requests.Session:
    session = getattr(_local, "session", None)
    if session is None:
        session = requests.Session()
        token = os.getenv("API_TOKEN", "")
        if token:
            session.headers["X-API-Key"] = token
        _local.session = session
    return session


def _request(method, path, **kwargs):
    response = _session().request(method, _base_url() + path, timeout=10, **kwargs)
    if not response.ok:
        try:
            detail = response.json().get("detail", response.text)
        except ValueError:
            detail = response.text
        raise ApiError(response.status_code, detail)
    return response.json() if response.content else None


# --- жильцы ---
def get_user_id(max_user_id):
    """id жильца в базе по id из MAX; при первом обращении регистрирует его."""
    if max_user_id not in _user_ids:
        user = _request("POST", "/users", json={"max_user_id": str(max_user_id)})
        _user_ids[max_user_id] = user["id"]
    return _user_ids[max_user_id]


def get_settings(max_user_id):
    return _request("GET", f"/users/{get_user_id(max_user_id)}")


def update_settings(max_user_id, **fields):
    return _request("PATCH", f"/users/{get_user_id(max_user_id)}", json=fields)


# --- адреса ---
def list_addresses(max_user_id):
    return _request("GET", f"/users/{get_user_id(max_user_id)}/addresses")


def get_primary_address(max_user_id):
    """Основной адрес: API отдаёт его первым."""
    addresses = list_addresses(max_user_id)
    return addresses[0] if addresses else None


def add_address(max_user_id, city, street, house_number, house_corpus=None, flat=None, primary=True):
    body = {"city": city, "street": street, "house_number": house_number, "is_primary": primary}
    if house_corpus:
        body["house_corpus"] = house_corpus
    if flat:
        body["flat"] = flat
    return _request("POST", f"/users/{get_user_id(max_user_id)}/addresses", json=body)


def set_primary_address(address_id):
    return _request("PATCH", f"/addresses/{address_id}/primary")


def delete_address(address_id):
    return _request("DELETE", f"/addresses/{address_id}")


# --- справочник УК ---
def list_cities():
    return _request("GET", "/companies/cities")


def find_streets(city, query):
    return _request("GET", "/companies/streets", params={"city": city, "q": query})


def lookup_company(city, street, house_number, house_corpus=None):
    """УК дома или None, если дома нет в справочнике."""
    params = {"city": city, "street": street, "house_number": house_number}
    if house_corpus:
        params["house_corpus"] = house_corpus
    try:
        return _request("GET", "/companies/lookup", params=params)
    except ApiError as error:
        if error.status == 404:
            return None
        raise


def get_company(company_id):
    if company_id is None:
        return None
    try:
        return _request("GET", f"/companies/{company_id}")
    except ApiError as error:
        if error.status == 404:
            return None
        raise


# --- отключения ---
def list_outages_for_address(address, ends_after=None):
    params = {"city": address["city"], "street": address["street"], "house_number": address["house_number"]}
    if address.get("house_corpus"):
        params["house_corpus"] = address["house_corpus"]
    if ends_after is not None:
        params["ends_after"] = ends_after.isoformat()
    return _request("GET", "/outages", params=params)


def pending_outage_notifications():
    return _request("GET", "/outages/notifications/pending")


def mark_outage_notified(outage_id, user_id):
    return _request("POST", f"/outages/{outage_id}/notified", json={"user_id": user_id})


# --- обращения ---
def create_appeal(max_user_id, address_id, subject, text, contact=None, photos=0):
    body = {
        "user_id": get_user_id(max_user_id),
        "address_id": address_id,
        "subject": subject,
        "text": text,
    }
    if contact:
        body["contact"] = contact
    if photos:
        body["photo_path"] = f"фото: {photos}"
    return _request("POST", "/appeals", json=body)


def get_appeal(number):
    return _request("GET", f"/appeals/{number}")


def list_appeals(max_user_id, limit=10):
    return _request("GET", "/appeals", params={"user_id": get_user_id(max_user_id), "limit": limit})


def update_appeal_status(number, new_status, comment=None):
    body = {"status": new_status}
    if comment:
        body["comment"] = comment
    return _request("PATCH", f"/appeals/{number}", json=body)


def pending_appeal_updates():
    return _request("GET", "/appeals/updates/pending")


def mark_appeal_notified(number, status):
    return _request("POST", f"/appeals/{number}/notified", json={"status": status})


def forget_users():
    """Сбросить кэш id жильцов: например, если базу пересоздали."""
    _user_ids.clear()
