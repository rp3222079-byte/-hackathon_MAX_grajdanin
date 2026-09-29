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


#Объявляем функцию normalize_street: raw — строка на входе, str после -> — строка на выходе
def normalize_street(raw: str) ->str: 
    return _STREET_RE.sub("", raw.strip().lower()).strip()
    
# функция возвращает кортеж из числа int и строки или None
def parse_house_fragment(fragment: str) -> tuple[int, str | None] :
    fragment = fragment.strip()
    if fragment.isdigit() : 
        return int(fragment), None

    i = 0
    while i < len(fragment) and fragment[i].isdigit(): 
        i+=1
    number_part = fragment[:i]
    corpus_part = fragment[i:]
    return int(number_part), corpus_part

def expand_fragment(fragment : str) -> set[tuple[int, str | None]]: 
    fragment = fragment.strip()
    if "-" in fragment:
        start_str, end_str = fragment.split("-")
        start = int(start_str.strip())
        end = int(end_str.strip())
        return {(n, None) for n in range(start, end + 1)}

    return {parse_house_fragment(fragment)}

# финальая функция рабивает всю строку по запятым и объеденяет результат 
def parse_house_list(raw: str) -> set[tuple[int, str | None]] : 
    result = set()
    for fragment in raw.split(","):
        result |= expand_fragment(fragment)
    return result
