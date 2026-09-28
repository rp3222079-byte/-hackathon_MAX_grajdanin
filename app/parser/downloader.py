"""Скачивание открытых выгрузок ГИС ЖКХ (https://dom.gosuslugi.ru).

Сайт отдаёт файлы без авторизации, но проверяет заголовки запроса,
поэтому клиент притворяется браузером.

Большая выгрузка — сведения об объектах жилищного фонда, около 3 ГБ
в одном архиве. Она качается параллельными диапазонами (сайт
поддерживает Range) и сразу распаковывается в csv нужного региона,
чтобы не держать архив на диске целиком.
"""
import concurrent.futures
import csv
import gzip
import re
import tarfile
import time
from collections.abc import Iterator
from pathlib import Path

import httpx

BASE_URL = "https://dom.gosuslugi.ru"

# Служебный адрес веб-выгрузки объектов жилищного фонда
OZHF_PATH = "/egisso/rao"

# Регион по умолчанию; ключевое слово города в названии файлов архива
OZHF_REGION = "Новосибирск"

# Размер куска при параллельной загрузке и число одновременных загрузок
CHUNK_SIZE = 32 * 1024 * 1024
CHUNK_WORKERS = 12

# Сайт обрывает длинные диапазоны, поэтому каждый кусок качаем с повторами
PART_ATTEMPTS = 5
PART_RETRY_DELAY = 2.0

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    "Referer": f"{BASE_URL}/",
    "Origin": BASE_URL,
}

JSON_HEADERS = {
    **BROWSER_HEADERS,
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json;charset=UTF-8",
}

# Части одного региона в архиве называются одинаково с номером на конце:
# «Сведения по ОЖФ Новосибирская обл на 27-09-2026_1.csv»
_REGION_PART = re.compile(r"_(?P<part>\d+)\.csv$")


class SourceError(RuntimeError):
    """ГИС ЖКХ не отдала ожидаемый ответ."""


def _client(timeout: float = 300) -> httpx.Client:
    return httpx.Client(
        headers=BROWSER_HEADERS,
        timeout=httpx.Timeout(60, read=timeout),
        follow_redirects=True,
    )


def get_json(path: str) -> object:
    """GET к JSON-ручке ГИС ЖКХ."""
    with _client(timeout=60) as client:
        response = client.get(f"{BASE_URL}{path}", headers=JSON_HEADERS)
    if response.status_code != 200:
        raise SourceError(f"{path} -> {response.status_code}")
    return response.json()


def download_file(url: str, destination: Path) -> Path:
    """Скачивает один файл целиком."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with _client() as client, client.stream("GET", url) as response:
        response.raise_for_status()
        with destination.open("wb") as handle:
            for chunk in response.iter_bytes(CHUNK_SIZE):
                handle.write(chunk)
    return destination


def download_ozhf_csv(cache_dir: Path, *, force: bool = False, region: str = OZHF_REGION) -> Path:
    """Готовит csv со сведениями об объектах жилищного фонда региона.

    Архив весит около 3 ГБ, поэтому он не сохраняется целиком: куски
    приходят параллельно, а на диск попадает только разжатый csv
    нужного региона. Второй вызов берёт готовый файл из кэша.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = cache_dir / f"ozhf_{slug(region)}.csv"
    if target.exists() and not force:
        return target

    url = resolve_ozhf_url()
    size = remote_size(url)
    parts = [cache_dir / f"ozhf.part{index:04d}" for index in range(parts_count(size))]
    try:
        _download_missing_parts(url, size, parts)
        _write_region_csv(parts, target, region)
    finally:
        for part in parts:
            part.unlink(missing_ok=True)
    return target


def resolve_ozhf_url() -> str:
    """Адрес архива: сайт сам перенаправляет на файл с датой выгрузки."""
    with _client(timeout=60) as client:
        response = client.head(f"{BASE_URL}{OZHF_PATH}")
        response.raise_for_status()
    return str(response.url)


def remote_size(url: str) -> int:
    with _client(timeout=60) as client:
        response = client.head(url)
        response.raise_for_status()
    return int(response.headers["content-length"])


def read_ozhf_rows(csv_path: Path) -> Iterator[dict[str, str]]:
    """Строки csv объектов жилищного фонда; разделитель — вертикальная черта."""
    with csv_path.open(encoding="utf-8", errors="replace", newline="") as handle:
        yield from csv.DictReader(handle, delimiter="|")


def parts_count(size: int) -> int:
    return (size + CHUNK_SIZE - 1) // CHUNK_SIZE


def _part_length(index: int, size: int) -> int:
    return min(CHUNK_SIZE, size - index * CHUNK_SIZE)


def _part_is_ready(part: Path, index: int, size: int) -> bool:
    return part.exists() and part.stat().st_size == _part_length(index, size)


def _download_missing_parts(url: str, size: int, parts: list[Path]) -> None:
    jobs = [
        (index, part)
        for index, part in enumerate(parts)
        if not _part_is_ready(part, index, size)
    ]
    with concurrent.futures.ThreadPoolExecutor(max_workers=CHUNK_WORKERS) as pool:
        list(pool.map(lambda job: _download_part(url, size, *job), jobs))


def _download_part(url: str, size: int, index: int, part: Path) -> None:
    """Качает один диапазон, переживая обрывы соединения."""
    start = index * CHUNK_SIZE
    end = start + _part_length(index, size) - 1
    headers = {"Range": f"bytes={start}-{end}"}
    for attempt in range(PART_ATTEMPTS):
        try:
            with _client() as client:
                response = client.get(url, headers=headers)
                response.raise_for_status()
                part.write_bytes(response.content)
            return
        except (httpx.HTTPError, httpx.RemoteProtocolError) as error:
            if attempt == PART_ATTEMPTS - 1:
                raise SourceError(f"кусок {index} не скачался: {error}") from error
            # сайт периодически рвёт соединение на длинных диапазонах
            time.sleep(PART_RETRY_DELAY)


class _PartStream:
    """Отдаёт содержимое кусков как один непрерывный поток байт."""

    def __init__(self, parts: list[Path]):
        self.parts = parts
        self.index = 0
        self.handle = None

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            chunks = []
            while True:
                data = self.read(1 << 20)
                if not data:
                    return b"".join(chunks)
                chunks.append(data)
        while True:
            if self.handle is None:
                if self.index >= len(self.parts):
                    return b""
                self.handle = self.parts[self.index].open("rb")
            data = self.handle.read(size)
            if data:
                return data
            self.handle.close()
            self.handle = None
            self.index += 1

    def close(self) -> None:
        if self.handle is not None:
            self.handle.close()
            self.handle = None


def _write_region_csv(parts: list[Path], target: Path, region: str) -> None:
    """Вытаскивает из архива части выбранного региона в один csv.

    Части региона идут подряд, поэтому берём первую подходящую и все
    следующие, пока имя файла принадлежит тому же региону.
    """
    stream = _PartStream(parts)
    archive = tarfile.open(fileobj=gzip.GzipFile(fileobj=stream), mode="r|")
    written = False
    with target.open("wb") as handle:
        for member in archive:
            if not _is_region_part(member.name, region):
                if written:
                    break
                continue
            source = archive.extractfile(member)
            if source is None:
                continue
            if written:
                handle.write(b"\n")
            while True:
                data = source.read(1 << 20)
                if not data:
                    break
                handle.write(data)
            written = True
    stream.close()
    if not written:
        target.unlink(missing_ok=True)
        raise SourceError(f"в архиве нет региона {region}")


def _is_region_part(name: str, region: str) -> bool:
    """Имя файла — часть выгрузки нашего региона (с номером или без)."""
    clean = _REGION_PART.sub(".csv", name)
    return clean.endswith(".csv") and region in clean


_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def slug(text: str) -> str:
    """Имя файла латиницей: «Новосибирск» -> «novosibirsk»."""
    result = "".join(_TRANSLIT.get(char, char) for char in text.lower())
    return re.sub(r"[^a-z0-9]+", "-", result).strip("-")
