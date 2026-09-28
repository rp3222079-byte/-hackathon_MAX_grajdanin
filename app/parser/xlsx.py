"""Потоковый разбор xlsx без внешних зависимостей.

Реестр поставщиков информации ГИС ЖКХ весит 26 МБ в zip, а
разжатый лист — около 226 МБ. Читать его целиком в память не нужно:
достаточно идти по строкам листа и отдавать словари.
"""
import re
import zipfile
from collections.abc import Iterator
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
            yield from _iter_sheet_rows(stream, shared)


def read_dicts(xlsx_path: Path, sheet: str | None = None) -> Iterator[dict[str, str]]:
    """Строки листа как словари: имя колонки из шапки -> значение.

    Пустые ячейки в словарь не попадают, поэтому в разборе удобно
    проверять наличие ключа, а не пустоту значения.

    Шапка ищется сама: в книге ГИС ЖКХ перед ней стоят заголовок
    файла и пустая строка, поэтому пустые строки сверху пропускаются.
    """
    rows = read_rows(xlsx_path, sheet)
    header = None
    for row in rows:
        if sum(1 for value in row if value) >= HEADER_MIN_FILLED:
            header = row
            break
    if header is None:
        return
    names = [_column_name(index, value) for index, value in enumerate(header)]
    for row in rows:
        record = {}
        for index, value in enumerate(row):
            if value is None or index >= len(names):
                continue
            name = names[index]
            if name:
                record[name] = value
        if record:
            yield record


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


def _iter_sheet_rows(stream, shared: list[str]) -> Iterator[list[str | None]]:
    cells: dict[int, str | None] = {}
    column = 0
    for event, element in ElementTree.iterparse(stream, events=("start", "end")):
        tag = element.tag
        if tag == f"{SPREADSHEET_NS}c" and event == "start":
            ref = element.get("r", "")
            match = _CELL_REF.match(ref)
            column = _column_index(match.group(1)) if match else column + 1
        elif tag == f"{SPREADSHEET_NS}c":
            cells[column] = _cell_text(element, shared)
            column += 1
            element.clear()
        elif tag == f"{SPREADSHEET_NS}row" and event == "end":
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
        text = shared[int(value.text)] if cell_type == "s" and int(value.text) < len(shared) else value.text
    # пустую ячейку считаем отсутствующей, чтобы разбор не различал
    # «графа пустая» и «графы нет вовсе»
    return text or None


def _element_text(element: ElementTree.Element | None) -> str | None:
    if element is None:
        return None
    return "".join(node.text or "" for node in element.iter(f"{SPREADSHEET_NS}t"))


def _column_name(index: int, value: str | None) -> str:
    return (value or f"Колонка{index + 1}").strip()


def _column_index(letters: str) -> int:
    index = 0
    for letter in letters:
        index = index * 26 + (ord(letter) - ord("A") + 1)
    return index - 1
