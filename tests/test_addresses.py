import unittest
from app.services.addresses import normalize_street, parse_house_list

class TestNormalizeStreet(unittest.TestCase):
    def test_removes_prefix_ul(self):
        self.assertEqual(normalize_street("ул. Ленина"), "ленина")

    def test_removes_prefix_full_word(self):
        self.assertEqual(normalize_street("Улица Ленина"), "ленина")

    def test_handles_uppercase(self):
        self.assertEqual(normalize_street("ЛЕНИНА"), "ленина")

    def test_removes_prospekt(self):
        self.assertEqual(normalize_street("проспект Мира"), "мира")


class TestParseHouseList(unittest.TestCase):
    def test_range_with_duplicates(self):
        result = parse_house_list("1-15, 2, 4")
        expected = {(n, None) for n in range(1, 16)}
        self.assertEqual(result, expected)

    def test_single_house_with_corpus(self):
        result = parse_house_list("12к2")
        self.assertEqual(result, {(12, "к2")})

    def test_mixed_simple_and_corpus(self):
        result = parse_house_list("5, 12к2")
        self.assertEqual(result, {(5, None), (12, "к2")})

if __name__ == "__main__":
    unittest.main()