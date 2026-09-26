STREET_PREFIXES = [
    "улица",
    "ул.",
    "ул",
    "проспект",
    "пр.",
    "пр-т",
    "переулок",
    "пер.",
]
#Объявляем функцию normalize_street: raw — строка на входе, str после -> — строка на выходе
def normalize_street(raw: str) ->str: 
    text = raw.strip().lower()
    for prefix in STREET_PREFIXES:
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    text = text.strip()
    return text
    
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

def expand_fragment(fragment : str) -> set[tuple[int, srt | None]]: 
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
