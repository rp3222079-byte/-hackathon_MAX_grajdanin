import os
import requests

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
_session = requests.Session()
_user_ids = {}   


class ApiError(Exception):
    def __init__(self, status, detail):
        super().__init__(f"API {status}: {detail}")
        self.status = status
        self.detail = detail


def _request(method, path, **kwargs):
    response = _session.request(method, API_BASE_URL.rstrip("/") + path, timeout=10, **kwargs)
    if not response.ok:
        try:
            detail = response.json().get("detail", response.text)
        except ValueError:
            detail = response.text
        raise ApiError(response.status_code, detail)
    return response.json() if response.content else None


def get_user_id(max_user_id):
    """id жильца в базе по id из MAX; при первом обращении регистрирует его."""
    if max_user_id not in _user_ids:
        user = _request("POST", "/users", json={"telegram_id": str(max_user_id)})
        _user_ids[max_user_id] = user["id"]
    return _user_ids[max_user_id]


def list_addresses(max_user_id):
    return _request("GET", f"/users/{get_user_id(max_user_id)}/addresses")


def get_primary_address(max_user_id):
    """Первый адрес из списка — API уже возвращает основной первым."""
    addresses = list_addresses(max_user_id)
    return addresses[0] if addresses else None


def add_address(max_user_id, city, street, house_number, house_corpus=None, flat=None):
    body = {"city": city, "street": street, "house_number": house_number}
    if house_corpus:
        body["house_corpus"] = house_corpus
    if flat:
        body["flat"] = flat
    return _request("POST", f"/users/{get_user_id(max_user_id)}/addresses", json=body)

def list_outages_for_address(address):
    params = {"city": address["city"], "street": address["street"], "house_number": address["house_number"]}
    if address.get("house_corpus"):
        params["house_corpus"] = address["house_corpus"]
    return _request("GET", "/outages", params=params)

def create_appeal(max_user_id, address_id, subject, text, photo_path=None):
    body = {
        "user_id": get_user_id(max_user_id),
        "address_id": address_id,
        "subject": subject,
        "text": text,
    }
    if photo_path:
        body["photo_path"] = photo_path
    return _request("POST", "/appeals", json=body)


def get_company(company_id):
    if company_id is None:
        return None
    try:
        return _request("GET", f"/companies/{company_id}")
    except ApiError as error:
        if error.status == 404:
            return None
        raise
