"""Тесты парсера ГИС ЖКХ: разбор выгрузок, склейка по ОГРН, выгрузка и загрузка."""
import csv
import json
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.db import create_db_engine
from app.migrations import run_migrations
from app.models import CompanyHouse, ManagementCompany
from app.parser import downloader, export, xlsx
from app.parser.companies import (
    CompanyDirectory,
    House,
    build_directory,
    clean_email,
    parse_address,
    read_houses,
    read_providers,
)
from app.parser.loader import load_file
from app.services.addresses import normalize_street

# Минимальный xlsx: в файле из ГИС ЖКХ значения хранятся как inlineStr
INLINE_XLSX_HEAD = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    '<sheetData>'
)
INLINE_XLSX_TITLE = (
    '<row r="2"><c r="A2" t="inlineStr"><is><t>Реестр поставщиков информации</t></is></c></row>'
)
INLINE_XLSX_TAIL = "</sheetData></worksheet>"

OZHF_HEADER = (
    "Адрес ОЖФ|Глобальный уникальный идентификатор дома по ФИАС|"
    "Тип дома|Способ управления|"
    "ОГРН организации, осуществляющей управление домом"
)


def make_xlsx(path: Path, rows: list[list[str]], *, title: bool = True) -> Path:
    """Книга с одной строкой заголовка и строками данных.

    title добавляет строку с названием файла: в книге ГИС ЖКХ она стоит
    над шапкой, и разбор обязан её перешагнуть.
    """
    body = INLINE_XLSX_HEAD + (INLINE_XLSX_TITLE if title else "")
    for number, row in enumerate(rows, start=3 if title else 2):
        cells = "".join(
            f'<c r="{chr(ord("A") + index)}{number}" t="inlineStr"><is><t>{value}</t></is></c>'
            for index, value in enumerate(row)
        )
        body += f'<row r="{number}">{cells}</row>'
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as book:
        book.writestr("xl/worksheets/sheet1.xml", body + INLINE_XLSX_TAIL)
    return path


def make_ozhf(path: Path, rows: list[str]) -> Path:
    """csv объектов жилищного фонда с вертикальным разделителем."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join([OZHF_HEADER, *rows]) + "\n", encoding="utf-8")
    return path


def provider_row(ogrn: str, name: str, **contacts: str) -> list[str]:
    """Строка реестра поставщиков в порядке колонок выгрузки."""
    values = [
        name,
        "-",
        "630000, Новосибирская обл",
        "Новосибирск",
        ogrn,
        "5400000000",
        "540001001",
    ]
    values += [contacts.get(key, "") for key in ("site", "phone", "email", "function", "territory")]
    return values + ["Подтверждено", "01.09.2026"]


class TestXlsx(unittest.TestCase):
    def test_читает_шапку_и_строки(self):
        with TemporaryDirectory() as folder:
            path = make_xlsx(
                Path(folder) / "p.xlsx",
                [
                    ["Полное наименование", "ОГРН", "Адрес электронной почты"],
                    ['ООО "Ромашка"', "1025400000001", "info@romashka.ru"],
                ],
            )
            rows = list(xlsx.read_dicts(path))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["ОГРН"], "1025400000001")
        self.assertEqual(rows[0]["Адрес электронной почты"], "info@romashka.ru")

    def test_пропускает_пустые_ячейки(self):
        with TemporaryDirectory() as folder:
            path = make_xlsx(
                Path(folder) / "p.xlsx",
                [["Полное наименование", "Телефон"], ["ООО Ромашка", ""]],
            )
            row = next(iter(xlsx.read_dicts(path)))
        self.assertNotIn("Телефон", row)


class TestParseAddress(unittest.TestCase):
    def test_разбирает_обычный_адрес(self):
        place = parse_address("630001, Новосибирская обл, г. Новосибирск, ул. Кирова, д. 27")
        self.assertEqual(place.city, "Новосибирск")
        self.assertEqual(place.street, "улица Кирова")
        self.assertEqual(place.number, 27)
        self.assertIsNone(place.corpus)

    def test_разбирает_корпус_словами_и_буквой(self):
        self.assertEqual(
            parse_address(
                "630008, Новосибирская обл, г. Новосибирск, ул. Кирова, д. 27, строение 1"
            ).corpus,
            "к1",
        )
        self.assertEqual(
            parse_address("630001, Новосибирская обл, г. Новосибирск, пр-кт Димитрова, д. 7, к 2").corpus,
            "к2",
        )

    def test_строение_без_дома(self):
        place = parse_address(
            "630059, Новосибирская обл, г. Новосибирск, ул. Сосновая, строение 8"
        )
        self.assertEqual(place.number, 8)

    def test_населённый_пункт_в_адресе_не_считается_улицей(self):
        place = parse_address(
            "630510, Новосибирская обл, р-н. Коченевский, д. Умна, ул. Береговая, д. 18"
        )
        self.assertEqual(place.street, "улица Береговая")
        self.assertEqual(place.number, 18)

    def test_тип_улицы_в_конце_названия(self):
        place = parse_address("630001, Новосибирская обл, г. Новосибирск, 6-я Парковая ул, д. 12")
        self.assertEqual(normalize_street(place.street), "6-я парковая")

    def test_без_улицы_или_дома_не_разбирается(self):
        self.assertIsNone(parse_address("630520, Новосибирская обл, р-н. Новосибирский, д. 23"))
        self.assertIsNone(parse_address("Адрес ОЖФ"))

    def test_улица_совпадает_с_написанной_жильцом(self):
        stored = parse_address("630001, Новосибирская обл, г. Новосибирск, ул. Кирова, д. 27").street
        for written in ("улица Кирова", "ул. Кирова", "Улица Кирова", "ул.Кирова"):
            self.assertEqual(normalize_street(written), normalize_street(stored))


class TestXlsxFilters(unittest.TestCase):
    def test_берёт_только_нужные_колонки(self):
        with TemporaryDirectory() as folder:
            path = make_xlsx(
                Path(folder) / "p.xlsx",
                [["Полное наименование", "ОГРН", "Телефон"],
                 ["ООО Первый", "1", "100"],
                 ["ООО Второй", "2", "200"]],
            )
            rows = list(xlsx.read_dicts(path, columns=("ОГРН", "Телефон")))
        self.assertEqual(rows, [{"ОГРН": "1", "Телефон": "100"}, {"ОГРН": "2", "Телефон": "200"}])

    def test_отбрасывает_строки_не_из_списка(self):
        with TemporaryDirectory() as folder:
            path = make_xlsx(
                Path(folder) / "p.xlsx",
                [["Полное наименование", "ОГРН"], ["Нужная", "1"], ["Лишняя", "2"]],
            )
            rows = list(xlsx.read_dicts(path, key="ОГРН", keys={"1"}))
        self.assertEqual(rows, [{"Полное наименование": "Нужная", "ОГРН": "1"}])

    def test_неизвестная_колонка_не_ломает_разбор(self):
        with TemporaryDirectory() as folder:
            path = make_xlsx(
                Path(folder) / "p.xlsx", [["ОГРН", "Телефон"], ["1", "300"]],
            )
            rows = list(xlsx.read_dicts(path, columns=("ОГРН", "КолонкиНет")))
        self.assertEqual(rows, [{"ОГРН": "1"}])

    def test_лист_в_одну_графу_читается(self):
        with TemporaryDirectory() as folder:
            path = make_xlsx(Path(folder) / "p.xlsx", [["ОГРН"], ["1"], ["2"]], title=False)
            self.assertEqual(xlsx.read_header(path), ["ОГРН"])
            rows = list(xlsx.read_dicts(path))
        self.assertEqual(rows, [{"ОГРН": "1"}, {"ОГРН": "2"}])


class TestOzhfColumns(unittest.TestCase):
    def test_отдаёт_только_запрошенные_графы(self):
        with TemporaryDirectory() as folder:
            path = make_ozhf(
                Path(folder) / "o.csv",
                [
                    "630001, Новосибирская обл, г. Новосибирск, ул. Кирова, д. 27|id|Многоквартирный|УО|1025400000001",
                    "короткая|строка",
                ],
            )
            rows = list(
                downloader.read_ozhf_columns(path, ["Тип дома", "ОГРН организации, осуществляющей управление домом"])
            )
        self.assertEqual(rows, [("Многоквартирный", "1025400000001")])

    def test_тот_же_дом_не_повторяется(self):
        rows = [
            f"630001, Новосибирская обл, г. Новосибирск, ул. Кирова, д. 27|{index}|Многоквартирный|УО|1025400000001"
            for index in range(50)
        ]
        with TemporaryDirectory() as folder:
            path = make_ozhf(Path(folder) / "o.csv", rows)
            houses = list(read_houses(path, "Новосибирск"))
        self.assertEqual(len(houses), 1)
        self.assertEqual(houses[0].number, 27)


class TestCleanEmail(unittest.TestCase):
    def test_берёт_первый_из_нескольких(self):
        self.assertEqual(clean_email("uk@novosibirsk.ru\nвторой@novosibirsk.ru"), "uk@novosibirsk.ru")

    def test_отбрасывает_прочерк_и_пустоту(self):
        for value in ("", None, "  ", "-", "нет", "н/д", "—"):
            with self.subTest(value=value):
                self.assertEqual(clean_email(value), "")

    def test_убирает_пробелы_и_неразрывные(self):
        self.assertEqual(clean_email("  uk@novosibirsk.ru  ;"), "uk@novosibirsk.ru")
        self.assertEqual(clean_email(" uk@novosibirsk.ru"), "uk@novosibirsk.ru")

    def test_не_берёт_текст_похожий_на_почту(self):
        self.assertEqual(clean_email("телефон 8 383 300-00-99"), "")
        self.assertEqual(clean_email("uk@localhost"), "")

    def test_берёт_почту_из_многострочной_ячейки(self):
        self.assertEqual(clean_email("-\nuk@novosibirsk.ru"), "uk@novosibirsk.ru")


class TestReadSources(unittest.TestCase):
    def test_читает_поставщиков(self):
        with TemporaryDirectory() as folder:
            path = make_xlsx(
                Path(folder) / "p.xlsx",
                [
                    ["Полное наименование", "ОГРН", "Адрес электронной почты", "Телефон", "Функция"],
                    ['ООО "УК Ромашка"', "1025400000001", "info@romashka.ru", "300", "Управляющая организация"],
                    ["Без ОГРН", "", "x@y.ru", "", ""],
                ],
            )
            found = list(read_providers(path))
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].ogrn, "1025400000001")
        self.assertEqual(found[0].name, 'ООО "УК Ромашка"')
        self.assertEqual(found[0].email, "info@romashka.ru")

    def test_берёт_только_многоквартирные_дома_города_с_управляющей(self):
        with TemporaryDirectory() as folder:
            path = make_ozhf(
                Path(folder) / "o.csv",
                [
                    "630001, Новосибирская обл, г. Новосибирск, ул. Кирова, д. 27|id|Многоквартирный|УО|1025400000001",
                    "630001, Новосибирская обл, г. Новосибирск, ул. Мира, д. 1|id|Многоквартирный|УО|1025400000001",
                    "630001, Новосибирская обл, г. Новосибирск, ул. Титова, д. 5|id|Жилой|УО|1025400000001",
                    "630001, Новосибирская обл, г. Новосибирск, ул. Лесная, д. 2|id|Многоквартирный|Не выбран|1025400000001",
                    "630001, Новосибирская обл, г. Новосибирск, ул. Дачная, д. 3|id|Многоквартирный|УО|",
                    "630002, Новосибирская обл, г. Бердск, ул. Ленина, д. 9|id|Многоквартирный|УО|1025400000002",
                ],
            )
            houses = list(read_houses(path, "Новосибирск"))
        self.assertEqual([house.street for house in houses], ["улица Кирова", "улица Мира"])


class TestBuildDirectory(unittest.TestCase):
    def _sources(self, folder: str, house_rows: list[str]) -> tuple[Path, Path]:
        providers = make_xlsx(
            Path(folder) / "p.xlsx",
            [
                ["Полное наименование", "ОГРН", "Адрес электронной почты", "Телефон",
                 "Официальный сайт в сети Интернет", "Функция"],
                ['ООО "УК Ромашка"', "1025400000001", "info@romashka.ru", "300", "romashka.ru", "Управляющая организация"],
            ],
        )
        return providers, make_ozhf(Path(folder) / "o.csv", house_rows)

    def test_склеивает_дома_с_компанией_по_огрн(self):
        rows = [
            "630001, Новосибирская обл, г. Новосибирск, ул. Кирова, д. 27|id|Многоквартирный|УО|1025400000001",
            "630001, Новосибирская обл, г. Новосибирск, ул. Кирова, д. 27, к 2|id|Многоквартирный|УО|1025400000001",
            "630001, Новосибирская обл, г. Новосибирск, ул. Мира, д. 1|id|Многоквартирный|УО|1025400000001",
            "630001, Новосибирская обл, г. Новосибирск, ул. Лесная, д. 4|id|Многоквартирный|УО|1025400000009",
        ]
        with TemporaryDirectory() as folder:
            providers, houses = self._sources(folder, rows)
            directory = build_directory(providers, houses, "Новосибирск")
        company = directory["1025400000001"]
        self.assertEqual(company.name, 'ООО "УК Ромашка"')
        self.assertEqual(company.email, "info@romashka.ru")
        self.assertEqual(company.website, "romashka.ru")
        self.assertEqual(company.houses_count, 3)
        self.assertIn((27, None), company.streets["улица Кирова"])
        self.assertIn((27, "к2"), company.streets["улица Кирова"])
        self.assertNotIn("1025400000009", directory)

    def test_без_почты_остаётся_пустым(self):
        rows = [
            "630001, Новосибирская обл, г. Новосибирск, ул. Кирова, д. 27|id|Многоквартирный|УО|1025400000001",
        ]
        with TemporaryDirectory() as folder:
            providers = make_xlsx(
                Path(folder) / "p.xlsx",
                [["Полное наименование", "ОГРН"], ["УК Без Почты", "1025400000001"]],
            )
            houses = make_ozhf(Path(folder) / "o.csv", rows)
            company = build_directory(providers, houses, "Новосибирск")["1025400000001"]
        # адрес не выдумывается: на выдуманный писать бессмысленно
        self.assertEqual(company.email, "")

    def test_почта_берётся_из_реестра(self):
        rows = [
            "630001, Новосибирская обл, г. Новосибирск, ул. Кирова, д. 27|id|Многоквартирный|УО|1025400000001",
        ]
        with TemporaryDirectory() as folder:
            providers = make_xlsx(
                Path(folder) / "p.xlsx",
                [
                    ["Полное наименование", "ОГРН", "Адрес электронной почты"],
                    ["УК С Почтой", "1025400000001", "uk@novosibirsk.ru"],
                ],
            )
            houses = make_ozhf(Path(folder) / "o.csv", rows)
            company = build_directory(providers, houses, "Новосибирск")["1025400000001"]
        self.assertEqual(company.email, "uk@novosibirsk.ru")


class TestExport(unittest.TestCase):
    def _directory(self) -> dict[str, CompanyDirectory]:
        company = CompanyDirectory(
            name='ООО "УК Ромашка"',
            email="info@romashka.ru",
            phone="300",
            website="romashka.ru",
            city="Новосибирск",
            ogrn="1025400000001",
        )
        company.add(House("Новосибирск", "улица Кирова", 27, None, "1025400000001"))
        company.add(House("Новосибирск", "улица Кирова", 27, "к2", "1025400000001"))
        company.add(House("Новосибирск", "улица Мира", 1, None, "1025400000001"))
        return {"1025400000001": company}

    def test_csv_читается_существующим_форматом(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "nsk.csv"
            rows = export.write_csv(self._directory(), path)
            with path.open(encoding="utf-8") as handle:
                read_back = list(csv.DictReader(handle))
        self.assertEqual(rows, 2)
        kir = next(row for row in read_back if row["street"] == "улица Кирова")
        self.assertEqual(kir["houses"], "27,27к2")
        self.assertEqual(kir["email"], "info@romashka.ru")

    def test_json_хранит_дома_объектами(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "nsk.json"
            export.write_json(self._directory(), path)
            data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data[0]["ogrn"], "1025400000001")
        self.assertIn(
            {"street": "улица Кирова", "number": 27, "corpus": "к2"},
            data[0]["houses"],
        )


class TestLoader(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.engine = create_db_engine(f"sqlite:///{Path(self.folder.name) / 'test.db'}")
        run_migrations(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.close)
        self.directory = TestExport()._directory()
        self.csv_path = Path(self.folder.name) / "nsk.csv"
        self.json_path = Path(self.folder.name) / "nsk.json"
        export.write_csv(self.directory, self.csv_path)
        export.write_json(self.directory, self.json_path)

    def test_csv_загружает_компанию_и_дома(self):
        result = load_file(self.db, self.csv_path)
        self.assertEqual(result.companies, 1)
        self.assertEqual(result.houses, 3)
        company = self.db.scalar(select(ManagementCompany))
        self.assertEqual(company.name, 'ООО "УК Ромашка"')
        self.assertEqual(company.city, "Новосибирск")
        self.assertEqual(len(self.db.scalars(select(CompanyHouse)).all()), 3)

    def test_json_даёт_тот_же_результат(self):
        load_file(self.db, self.json_path)
        self.assertEqual(len(self.db.scalars(select(CompanyHouse)).all()), 3)

    def test_повторная_загрузка_не_дублирует(self):
        load_file(self.db, self.csv_path)
        again = load_file(self.db, self.csv_path)
        self.assertEqual(again.companies, 0)
        self.assertEqual(again.houses, 0)
        self.assertEqual(len(self.db.scalars(select(ManagementCompany)).all()), 1)
        self.assertEqual(len(self.db.scalars(select(CompanyHouse)).all()), 3)

    def test_дополняет_пустые_контакты(self):
        self.db.add(ManagementCompany(name='ООО "УК Ромашка"', email="noreply@gis.jkh", city="Новосибирск"))
        self.db.commit()
        result = load_file(self.db, self.csv_path)
        company = self.db.scalar(select(ManagementCompany))
        self.assertEqual(company.phone, "300")
        self.assertEqual(company.website, "romashka.ru")
        self.assertEqual(result.houses, 3)


class TestDownloaderHelpers(unittest.TestCase):
    def test_slug_латиницей(self):
        self.assertEqual(downloader.slug("Новосибирск"), "novosibirsk")
        self.assertEqual(downloader.slug("Санкт-Петербург"), "sankt-peterburg")

    def test_части_архива_определяются_по_имени(self):
        name = "Сведения по ОЖФ Новосибирская обл на 27-09-2026_2.csv"
        self.assertTrue(downloader._is_region_part(name, "Новосибирск"))
        self.assertFalse(downloader._is_region_part(name, "Москва"))
        self.assertTrue(
            downloader._is_region_part("Сведения по ОЖФ Москва на 27-09-2026.csv", "Москва")
        )

    def test_смещение_кусков_считается_верно(self):
        self.assertEqual(downloader.parts_count(65), 1)
        self.assertEqual(downloader.parts_count(downloader.CHUNK_SIZE + 1), 2)


if __name__ == "__main__":
    unittest.main()
