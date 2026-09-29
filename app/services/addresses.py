import re

# Полные названия вида улицы: отбрасываем только вместе с пробелом,
# иначе «улица» вместе с «Ульяновская» дали бы «ьяновская»
STREET_FULL = [
    "улица",
    "проспект",
    "просп.",
    "переулок",
    "шоссе",
    "бульвар",
    "площадь",
    "набережная",
    "проезд",
    "микрорайон",
    "территория",
    "малоэтажная застройка",
    "линия",
]
# Сокращения с точкой: «ул. Ленина» и «ул.Ленина» читаются одинаково
STREET_ABBREV = [
    "ул.",
    "пр-кт.",
    "пр-кт",
    "пр-т.",
    "пр-т",
    "просп.",
    "пр.",
    "пер.",
    "ш.",
    "б-р.",
    "б-р",
    "пл.",
    "наб.",
    "пр-д.",
    "пр-д",
    "мкр.",
    "мк-р.",
    "мк-р",
    "тер.",
    "лн.",
]
# Длинные варианты проверяем первыми: «улица» должна попасть в «улица»,
# а не в «улица Ульяновская», отрезанную вместе с буквой «ц»
STREET_PREFIXES = sorted(STREET_FULL + STREET_ABBREV, key=len, reverse=True)

_STREET_RE = re.compile(
    r"^(?:"
    + "|".join(re.escape(name) for name in sorted(STREET_FULL, key=len, reverse=True))
    + r")\s+|(?:"
    + "|".join(re.escape(name) for name in sorted(STREET_ABBREV, key=len, reverse=True))
    + r")\s*"
)


def normalize_street(raw: str) -> str:
    """«ул. Ленина», «улица Ленина» и «Ленина» → «ленина»."""
    return _STREET_RE.sub("", raw.strip().lower().replace("ё", "е")).strip()


# Как пишут корпус и строение: приводим к короткой форме «к2», «с1»
_CORPUS_WORDS = (
    ("корпус", "к"),
    ("корп", "к"),
    ("строение", "с"),
    ("стр", "с"),
)


def normalize_corpus(raw: str | None) -> str | None:
    """«Корп. 2», « к 2», «К2» → «к2»; пусто → None."""
    if raw is None:
        return None
    corpus = raw.strip().lower().replace(" ", "").replace(".", "")
    for word, short in _CORPUS_WORDS:
        if corpus.startswith(word):
            corpus = short + corpus[len(word):]
            break
    return corpus or None


def parse_house_fragment(fragment: str) -> tuple[int, str | None]:
    """«12» → (12, None), «12к2» → (12, "к2"). Без номера — ValueError."""
    fragment = fragment.strip()
    if fragment.isdigit():
        return int(fragment), None

    i = 0
    while i < len(fragment) and fragment[i].isdigit():
        i += 1
    if i == 0:
        raise ValueError(f"в «{fragment}» нет номера дома")
    return int(fragment[:i]), normalize_corpus(fragment[i:])


def expand_fragment(fragment: str) -> set[tuple[int, str | None]]:
    """«1-5» → пять домов без корпуса, «12к2» → один дом."""
    fragment = fragment.strip()
    if "-" in fragment:
        start_str, end_str = fragment.split("-", 1)
        start = int(start_str.strip())
        end = int(end_str.strip())
        return {(n, None) for n in range(start, end + 1)}

    return {parse_house_fragment(fragment)}


def parse_house_list(raw: str) -> set[tuple[int, str | None]]:
    """Разбивает строку источника по запятым и объединяет дома."""
    result = set()
    for fragment in raw.split(","):
        if fragment.strip():
            result |= expand_fragment(fragment)
    return result
