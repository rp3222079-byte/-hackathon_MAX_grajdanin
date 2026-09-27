"""Тесты API: эндпоинты, валидация и ответы с ошибками.

Приложение работает на отдельной базе в памяти — domovoy.db не трогаем.
"""
import unittest
from collections.abc import Iterator
from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import create_db_engine, get_db
from app.main import app
from app.migrations import run_migrations
from app.models import (
    UTILITY_ELECTRICITY,
    UTILITY_WATER,
    CompanyHouse,
    ManagementCompany,
    Outage,
)

HOUSE = {"city": "Новосибирск", "street": "ул. Ленина", "house_number": 11}


class TestApi(unittest.TestCase):
    """Общая заготовка: пустая база в памяти, одно отключение и одна УК."""

    def setUp(self):
        self.engine = create_db_engine("sqlite://")
        run_migrations(self.engine)
        app.dependency_overrides[get_db] = self.session
        self.client = TestClient(app)
        self.add_outages()
        self.add_company()

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.clear()
        self.engine.dispose()

    def session(self) -> Iterator[Session]:
        with Session(self.engine) as db:
            yield db

    def add_outages(self) -> None:
        with Session(self.engine) as db:
            db.add_all(
                [
                    Outage(
                        utility=UTILITY_WATER,
                        city="Новосибирск",
                        street="ул. Ленина",
                        houses_raw="1-15, 12к2",
                        starts_at=datetime(2026, 9, 28, 10, 0),
                        ends_at=datetime(2026, 9, 28, 18, 0),
                        source="demo",
                        reason="Плановый ремонт",
                    ),
                    Outage(
                        utility=UTILITY_ELECTRICITY,
                        city="Новосибирск",
                        street="ул. Мира",
                        houses_raw="5",
                        starts_at=datetime(2026, 9, 29, 9, 0),
                        source="demo",
                    ),
                    Outage(
                        utility=UTILITY_WATER,
                        city="Москва",
                        street="Тверская",
                        houses_raw="11",
                        starts_at=datetime(2026, 9, 30, 9, 0),
                        source="demo",
                    ),
                ]
            )
            db.commit()

    def add_company(self) -> None:
        with Session(self.engine) as db:
            company = ManagementCompany(
                name="УК Ленина", email="uk@example.ru", city="Новосибирск"
            )
            db.add(company)
            db.flush()
            # в справочнике улица написана полностью, жилец пишет «ул.»
            db.add(
                CompanyHouse(
                    company_id=company.id,
                    city="Новосибирск",
                    street="улица Ленина",
                    house_number=11,
                )
            )
            db.commit()

    def company(self) -> ManagementCompany:
        with Session(self.engine) as db:
            return db.scalar(select(ManagementCompany))

    def create_user(self, telegram_id: str = "1001") -> dict:
        response = self.client.post("/users", json={"telegram_id": telegram_id})
        self.assertEqual(response.status_code, 201)
        return response.json()

    def add_address(self, user_id: int, **extra) -> dict:
        response = self.client.post(f"/users/{user_id}/addresses", json={**HOUSE, **extra})
        self.assertEqual(response.status_code, 201)
        return response.json()


class TestUsers(TestApi):
    def test_create_user(self):
        user = self.create_user()
        self.assertEqual(user["telegram_id"], "1001")
        self.assertTrue(user["notify_outages"])
        self.assertEqual(user["addresses"], [])

    def test_same_telegram_id_does_not_duplicate(self):
        first = self.create_user("1001")
        second = self.create_user("1001")
        self.assertEqual(first["id"], second["id"])

    def test_user_with_addresses(self):
        user = self.create_user()
        self.add_address(user["id"])
        response = self.client.get(f"/users/{user['id']}")
        self.assertEqual(len(response.json()["addresses"]), 1)

    def test_user_not_found(self):
        response = self.client.get("/users/404")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Жилец 404 не найден")

    def test_notification_settings(self):
        user = self.create_user()
        response = self.client.patch(f"/users/{user['id']}", json={"notify_water": False})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["notify_water"])
        self.assertTrue(response.json()["notify_electricity"])


class TestAddresses(TestApi):
    def test_first_address_becomes_primary(self):
        user = self.create_user()
        self.assertTrue(self.add_address(user["id"])["is_primary"])

    def test_second_address_is_not_primary(self):
        user = self.create_user()
        self.add_address(user["id"])
        second = self.add_address(user["id"], street="ул. Мира", house_number=12)
        self.assertFalse(second["is_primary"])

    def test_corpus_is_normalized(self):
        user = self.create_user()
        address = self.add_address(user["id"], house_number=12, house_corpus="2К")
        self.assertEqual(address["house_corpus"], "к2")

    def test_same_house_twice(self):
        user = self.create_user()
        self.add_address(user["id"])
        response = self.client.post(f"/users/{user['id']}/addresses", json=HOUSE)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"], "Этот адрес уже добавлен")

    def test_addresses_listed(self):
        user = self.create_user()
        self.add_address(user["id"])
        self.add_address(user["id"], street="ул. Мира", house_number=12)
        response = self.client.get(f"/users/{user['id']}/addresses")
        self.assertEqual(len(response.json()), 2)

    def test_address_deleted(self):
        user = self.create_user()
        address = self.add_address(user["id"])
        self.assertEqual(self.client.delete(f"/addresses/{address['id']}").status_code, 204)
        self.assertEqual(self.client.get(f"/addresses/{address['id']}").status_code, 404)

    def test_blank_street_rejected(self):
        user = self.create_user()
        response = self.client.post(
            f"/users/{user['id']}/addresses", json={**HOUSE, "street": "   "}
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["errors"][0]["field"], "street")

    def test_house_number_must_be_positive(self):
        user = self.create_user()
        response = self.client.post(
            f"/users/{user['id']}/addresses", json={**HOUSE, "house_number": 0}
        )
        self.assertEqual(response.status_code, 422)

    def test_address_for_unknown_user(self):
        response = self.client.post("/users/404/addresses", json=HOUSE)
        self.assertEqual(response.status_code, 404)


class TestOutages(TestApi):
    def test_list_all(self):
        response = self.client.get("/outages")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 3)

    def test_filter_by_address(self):
        response = self.client.get("/outages", params={**HOUSE, "street": "Ленина"})
        self.assertEqual(len(response.json()), 1)
        self.assertEqual(response.json()[0]["houses_raw"], "1-15, 12к2")

    def test_city_is_case_insensitive(self):
        response = self.client.get("/outages", params={"city": "новосибирск"})
        self.assertEqual(len(response.json()), 2)

    def test_address_of_another_city_not_found(self):
        response = self.client.get("/outages", params={**HOUSE, "city": "Москва"})
        self.assertEqual(response.json(), [])

    def test_filter_by_house_with_corpus(self):
        response = self.client.get(
            "/outages", params={**HOUSE, "house_number": 12, "house_corpus": "к2"}
        )
        self.assertEqual(len(response.json()), 1)

    def test_house_outside_list_not_found(self):
        response = self.client.get("/outages", params={**HOUSE, "house_number": 40})
        self.assertEqual(response.json(), [])

    def test_filter_by_utility(self):
        response = self.client.get("/outages", params={"utility": UTILITY_ELECTRICITY})
        self.assertEqual(len(response.json()), 1)

    def test_unknown_utility_rejected(self):
        self.assertEqual(self.client.get("/outages", params={"utility": "gas"}).status_code, 422)

    def test_filter_by_time(self):
        response = self.client.get("/outages", params={"starts_after": "2026-09-29T00:00:00"})
        self.assertEqual(len(response.json()), 2)

    def test_limit_and_offset(self):
        response = self.client.get("/outages", params={"limit": 1, "offset": 1})
        self.assertEqual(len(response.json()), 1)

    def test_one_outage(self):
        outage_id = self.client.get("/outages", params=HOUSE).json()[0]["id"]
        self.assertEqual(self.client.get(f"/outages/{outage_id}").status_code, 200)

    def test_outage_not_found(self):
        self.assertEqual(self.client.get("/outages/404").status_code, 404)


class TestAppeals(TestApi):
    def payload(self, **extra) -> dict:
        return {"subject": "Не горит свет", "text": "В подъезде темно", **extra}

    def test_create_with_address(self):
        user = self.create_user()
        address = self.add_address(user["id"])
        response = self.client.post(
            "/appeals", json=self.payload(user_id=user["id"], address_id=address["id"])
        )
        self.assertEqual(response.status_code, 201)
        appeal = response.json()
        self.assertEqual(appeal["number"], "DM-00001")
        self.assertEqual(appeal["status"], "new")
        self.assertEqual(appeal["address_text"], "Новосибирск, ул. Ленина, 11")

    def test_company_found_despite_street_prefix(self):
        user = self.create_user()
        address = self.add_address(user["id"])
        response = self.client.post(
            "/appeals", json=self.payload(user_id=user["id"], address_id=address["id"])
        )
        self.assertEqual(response.json()["company_id"], self.company().id)

    def test_numbers_grow(self):
        first = self.client.post("/appeals", json=self.payload(address_text="Ленина, 11"))
        second = self.client.post("/appeals", json=self.payload(address_text="Ленина, 11"))
        self.assertEqual(first.json()["number"], "DM-00001")
        self.assertEqual(second.json()["number"], "DM-00002")

    def test_get_by_number(self):
        created = self.client.post("/appeals", json=self.payload(address_text="Ленина, 11"))
        response = self.client.get(f"/appeals/{created.json()['number']}")
        self.assertEqual(response.json()["subject"], "Не горит свет")

    def test_appeal_not_found(self):
        response = self.client.get("/appeals/DM-99999")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Обращение DM-99999 не найдено")

    def test_address_is_required(self):
        self.assertEqual(self.client.post("/appeals", json=self.payload()).status_code, 422)

    def test_empty_subject_rejected(self):
        response = self.client.post(
            "/appeals", json=self.payload(subject="  ", address_text="Ленина, 11")
        )
        self.assertEqual(response.status_code, 422)

    def test_address_of_another_user_rejected(self):
        first = self.create_user("1001")
        second = self.create_user("1002")
        address = self.add_address(first["id"])
        response = self.client.post(
            "/appeals", json=self.payload(user_id=second["id"], address_id=address["id"])
        )
        self.assertEqual(response.status_code, 404)

    def test_list_filtered_by_company(self):
        user = self.create_user()
        address = self.add_address(user["id"])
        self.client.post(
            "/appeals", json=self.payload(user_id=user["id"], address_id=address["id"])
        )
        self.client.post("/appeals", json=self.payload(address_text="Москва, Тверская, 1"))
        by_company = self.client.get("/appeals", params={"company_id": self.company().id})
        self.assertEqual(len(by_company.json()), 1)
        self.assertEqual(len(self.client.get("/appeals").json()), 2)

    def test_unknown_status_rejected(self):
        self.assertEqual(
            self.client.get("/appeals", params={"status": "unknown"}).status_code, 422
        )


class TestDocs(TestApi):
    def test_openapi_is_served(self):
        self.assertEqual(self.client.get("/openapi.json").status_code, 200)

    def test_docs_page_is_served(self):
        response = self.client.get("/docs")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Домовой API", response.text)

    def test_health(self):
        self.assertEqual(self.client.get("/health").json(), {"status": "ok"})


if __name__ == "__main__":
    unittest.main()
