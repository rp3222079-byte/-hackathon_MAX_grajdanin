"""Тесты разбора адресов. Запуск: python -m unittest discover tests"""
import unittest

from app.services.addresses import (
    expand_house_range,
    normalize_house,
    normalize_street,
    parse_address_line,
)


class NormalizeStreetTest(unittest.TestCase):
    def test_removes_street_type(self):
        self.assertEqual(normalize_street("ул. Ленина"), normalize_street("Ленина улица"))

    def test_handles_yo(self):
        self.assertEqual(normalize_street("Алёхина"), "алехина")

    def test_prospect(self):
        self.assertEqual(normalize_street("проспект Мира"), "мира")


class NormalizeHouseTest(unittest.TestCase):
    def test_building_forms_match(self):
        keys = {normalize_house(value) for value in ("д. 12 корп. 2", "12к2", "12/2", "12 к.2")}
        self.assertEqual(keys, {"12к2"})

    def test_letter_house(self):
        self.assertEqual(normalize_house("12а"), "12а")


class ExpandRangeTest(unittest.TestCase):
    def test_range(self):
        self.assertEqual(expand_house_range("1-3"), ["1", "2", "3"])

    def test_single(self):
        self.assertEqual(expand_house_range("7"), ["7"])

    def test_broken_range_kept_as_is(self):
        self.assertEqual(expand_house_range("15-1"), ["15-1"])


class ParseLineTest(unittest.TestCase):
    def test_range_and_list(self):
        self.assertEqual(
            parse_address_line("ул. Ленина, д. 1-3, 7"),
            [("ленина", "1"), ("ленина", "2"), ("ленина", "3"), ("ленина", "7")],
        )

    def test_street_starting_with_number(self):
        self.assertEqual(parse_address_line("8 Марта, 5"), [("8 марта", "5")])

    def test_building(self):
        self.assertEqual(parse_address_line("пр-кт Мира, 12/2"), [("мира", "12к2")])

    def test_no_digits(self):
        self.assertEqual(parse_address_line("улица без номеров"), [])

    def test_empty(self):
        self.assertEqual(parse_address_line(""), [])


class MatchingTest(unittest.TestCase):
    """Адрес жителя и адрес из источника должны сойтись по ключам."""

    def test_resident_matches_source(self):
        source = set(parse_address_line("ул. Ленина, д. 10-12"))
        resident = (normalize_street("Ленина улица"), normalize_house("д. 11"))
        self.assertIn(resident, source)


if __name__ == "__main__":
    unittest.main()
