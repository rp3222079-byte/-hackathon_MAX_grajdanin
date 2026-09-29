"""Доверенные сертификаты для запросов бота.

MAX Bot API (platform-api2.max.ru) подписан сертификатом Минцифры,
которого нет в стандартном наборе certifi. Собираем общий файл:
certifi + certs/russian_trusted_root_ca.pem — и передаём его в requests.
"""
import tempfile
from functools import lru_cache
from pathlib import Path

import certifi

RUSSIAN_ROOT_CA = Path(__file__).resolve().parents[2] / "certs" / "russian_trusted_root_ca.pem"


@lru_cache(maxsize=1)
def ca_bundle_path() -> str:
    """Путь к объединённому набору сертификатов; собирается один раз."""
    bundle = Path(tempfile.gettempdir()) / "domovoy-ca-bundle.pem"
    parts = [Path(certifi.where()).read_text(encoding="utf-8")]
    if RUSSIAN_ROOT_CA.is_file():
        parts.append(RUSSIAN_ROOT_CA.read_text(encoding="utf-8"))
    bundle.write_text("\n".join(parts), encoding="utf-8")
    return str(bundle)
