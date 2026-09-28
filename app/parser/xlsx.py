"""Потоковый разбор xlsx без внешних зависимостей.

Реестр поставщиков информации ГИС ЖКХ весит 26 МБ в zip, а
разжатый лист — около 226 МБ, и строк в нём 205 тысяч. Читать
книгу целиком в память незачем: лист разбирается построчно, а
словарь строится только для нужных колонок и только для строк,
которые прошли фильтр.

Читать быстрее помогают три решения:

* слушаем только событие «конец элемента»: адрес ячейки есть и в
  нём, поэтому второе событие на каждую из трёх миллионов ячеек
  не нужно;
* ячейки, которые никто не просит, не превращаются в строки;
* фильтр по значению применяется до того, как собран словарь.
"""
import re
import zipfile
from collections.abc import Iterator, Sequence
from pathlib import Path
from xml.etree import ElementTree

# Пространство имён xlsx
SPREADSHEET_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"

_CELL_REF = re.compile(r"([A-Z]+)")

# Шапкой считаем строку, где заполнено хотя бы столько ячеек
HEADER_MIN_FILLED = 2


class XlsxError(RuntimeError):
    """Файл не похож на книгу xlsx."""


def read_rows(xlsx_path: Path, sheet: str | None = None) -> Iterator[list[str | None]]:
    """Строки листа: список значений ячеек, пропуски — None.

    Значения приводятся к строке, как их записал источник: пустая
    ячейка остаётся пустой, даты приходят в исходном виде.
    """
    with zipfile.ZipFile(xlsx_path) as book:
        shared = _read_shared_strings(book)
        with book.open(sheet or _first_sheet(book)) as stream:
            yield from _iter_sheet_rows(stream, shared, None)


def read_dicts(
    xlsx_path: Path,
    sheet: str | None = None,
    *,
    columns: Sequence[str] | None = None,
    key: str | None = None,
    keys: set[str] | None = None,
) -> Iterator[dict[str, str]]:
    """Строки листа как словари: имя колонки из шапки -> значение.

    Пустые ячейки в словарь не попадают, поэтому в разборе удобно
    проверять наличие ключа, а не пустоту значения.

    columns — колонки, которые стоит разбирать; остальные ячейки
    пропускаются на разборе и в словарь не попадают. Колонки, которых
    в шапке нет, игнорируются: состав выгрузки со временем меняется.
    key и keys отбрасывают строки, у которых в графе key нет значения
    из keys: так из 205 тысяч организаций города мы строим словари
    только для нужных полутора тысяч.

    Шапка ищется сама: в книге ГИС ЖКХ перед ней стоят заголовок
    файла и пустая строка, поэтому пустые строки сверху пропускаются.
    """
    with zipfile.ZipFile(xlsx_path) as book:
        name = sheet or _first_sheet(book)
        names, skip = _read_header(book, name)
        if not names:
            return
        wanted = _positions(names, columns) if columns else None
        # фильтр по значению включаем только когда переданы оба аргументы
        key_index = names.index(key) if key and keys and key in names else None
        if key_index is not None and wanted is not None and key_index not in wanted:
            wanted = wanted + [key_index]
        needed = set(wanted) if wanted is not None else None
        if key_index is not None:
            needed = (needed or set(range(len(names)))) | {key_index}

        shared = _read_shared_strings(book)
        with book.open(name) as stream:
            for position, row in enumerate(_iter_sheet_rows(stream, shared, needed), start=1):
                if position <= skip:
                    continue
                if key_index is not None and (row[key_index] or "").strip() not in keys:
                    continue
                record = {}
                for index in wanted if wanted is not None else range(len(row)):
                    if index >= len(row) or row[index] is None or not names[index]:
                        continue
                    record[names[index]] = row[index]
                if record:
                    yield record


def read_header(xlsx_path: Path, sheet: str | None = None) -> list[str]:
    """Имена колонок листа."""
    with zipfile.ZipFile(xlsx_path) as book:
        return _read_header(book, sheet or _first_sheet(book))[0]


def _read_header(book: zipfile.ZipFile, sheet: str) -> tuple[list[str], int]:
    """Шапка листа и число строк, которые она занимает.

    Перед шапкой в книге ГИС ЖКХ стоит заголовок файла в одну ячейку,
    поэтому ищем строку с несколькими графами. Если такой нет, берём
    первую непустую — так читается лист с единственной графой.
    """
    shared = _read_shared_strings(book)
    with book.open(sheet) as stream:
        return _find_header(_iter_sheet_rows(stream, shared, None))


def _find_header(rows: Iterator[list[str | None]]) -> tuple[list[str], int]:
    """Имена колонок и сколько строк сверху нужно пропустить."""
    first: list[str | None] = []
    first_position = 0
    position = 0
    for position, row in enumerate(rows, start=1):
        if not first and any(row):
            first, first_position = row, position
        if sum(1 for value in row if value) >= HEADER_MIN_FILLED:
            return [_column_name(index, value) for index, value in enumerate(row)], position
    if not first:
        return [], 0
    return [_column_name(index, value) for index, value in enumerate(first)], first_position


def _first_sheet(book: zipfile.ZipFile) -> str:
    sheets = [name for name in book.namelist() if name.startswith("xl/worksheets/")]
    if not sheets:
        raise XlsxError("в книге нет листов")
    return sheets[0]


def _read_shared_strings(book: zipfile.ZipFile) -> list[str]:
    """Общие строки книги: их мало, в отличие от самого листа."""
    if "xl/sharedStrings.xml" not in book.namelist():
        return []
    values: list[str] = []
    with book.open("xl/sharedStrings.xml") as stream:
        for _, element in ElementTree.iterparse(stream, events=("end",)):
            if element.tag == f"{SPREADSHEET_NS}si":
                values.append(_element_text(element))
                element.clear()
    return values


def _iter_sheet_rows(
    stream, shared: list[str], needed: set[int] | None
) -> Iterator[list[str | None]]:
    """Строки листа; needed — индексы колонок, которые надо разобрать.

    Номера колонок берём из адреса ячейки (r="C12"), поэтому
    достаточно слушать только закрытие элемента ячейки.
    """
    cells: dict[int, str | None] = {}
    column = 0
    for _, element in ElementTree.iterparse(stream, events=("end",)):
        tag = element.tag
        if tag == f"{SPREADSHEET_NS}c":
            match = _CELL_REF.match(element.get("r", ""))
            column = _column_index(match.group(1)) if match else column + 1
            if needed is None or column in needed:
                cells[column] = _cell_text(element, shared)
            element.clear()
        elif tag == f"{SPREADSHEET_NS}row":
            width = max(cells, default=-1) + 1
            yield [cells.get(index) for index in range(width)]
            cells.clear()
            column = 0
            element.clear()


def _cell_text(element: ElementTree.Element, shared: list[str]) -> str | None:
    cell_type = element.get("t")
    if cell_type == "inlineStr":
        text = _element_text(element.find(f"{SPREADSHEET_NS}is"))
    else:
        value = element.find(f"{SPREADSHEET_NS}v")
        if value is None or value.text is None:
            return None
        index = int(value.text)
        text = shared[index] if cell_type == "s" and index < len(shared) else value.text
    # пустую ячейку считаем отсутствующей, чтобы разбор не различал
    # «графа пустая» и «графы нет вовсе»
    return text or None


def _element_text(element: ElementTree.Element | None) -> str | None:
    if element is None:
        return None
    return "".join(node.text or "" for node in element.iter(f"{SPREADSHEET_NS}t"))


def _column_name(index: int, value: str | None) -> str:
    return (value or f"Колонка{index + 1}").strip()


def _positions(names: list[str], columns: Sequence[str]) -> list[int]:
    """Номера запрошенных колонок; неизвестные пропускаются."""
    found = []
    for name in columns:
        if name in names:
            found.append(names.index(name))
    return found


def _column_index(letters: str) -> int:
    index = 0
    for letter in letters:
        index = index * 26 + (ord(letter) - ord("A") + 1)
    return index - 1
