import unittest
from datetime import datetime

from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import create_db_engine
from app.migrations import applied_versions, run_migrations
from app.models import (
    APPEAL_STATUS_NEW,
    UTILITY_WATER,
    Address,
    Appeal,
    CompanyHouse,
    ManagementCompany,
    Outage,
    OutageNotification,
    User,
)

EXPECTED_TABLES = frozenset(
    {
        "users",
        "addresses",
        "management_companies",
        "company_houses",
        "outages",
        "outage_notifications",
        "appeals",
        "schema_migrations",
    }
)


def make_engine():
    """Отдельная база в памяти: тесты не трогают domovoy.db."""
    return create_db_engine("sqlite://")


class TestMigrations(unittest.TestCase):
    def setUp(self):
        self.engine = make_engine()

    def tearDown(self):
        self.engine.dispose()

    def test_creates_all_tables(self):
        run_migrations(self.engine)
        self.assertEqual(set(inspect(self.engine).get_table_names()), EXPECTED_TABLES)

    def test_second_run_applies_nothing(self):
        run_migrations(self.engine)
        self.assertEqual(run_migrations(self.engine), [])

    def test_applied_versions_recorded(self):
        run_migrations(self.engine)
        with self.engine.connect() as conn:
            self.assertEqual(applied_versions(conn), {1})


class TestScenarios(unittest.TestCase):
    def setUp(self):
        self.engine = make_engine()
        run_migrations(self.engine)
        self.db = Session(self.engine, expire_on_commit=False)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def add_user(self, telegram_id: str = "1001") -> User:
        user = User(telegram_id=telegram_id)
        self.db.add(user)
        self.db.commit()
        return user

    def add_address(self, user: User, house_number: int = 11) -> Address:
        address = Address(
            user_id=user.id,
            city="Москва",
            street="Ленина",
            house_number=house_number,
            is_primary=True,
        )
        self.db.add(address)
        self.db.commit()
        return address

    def test_notification_settings_default_to_true(self):
        user = self.add_user()
        self.assertTrue(user.notify_outages)
        self.assertTrue(user.notify_water)
        self.assertTrue(user.notify_electricity)

    def test_same_house_twice_forbidden(self):
        user = self.add_user()
        self.add_address(user)
        self.db.add(
            Address(user_id=user.id, city="Москва", street="Ленина", house_number=11)
        )
        with self.assertRaises(IntegrityError):
            self.db.commit()
        self.db.rollback()

    def test_same_house_is_allowed_for_another_user(self):
        self.add_address(self.add_user("1001"))
        self.add_address(self.add_user("1002"), house_number=11)

    def test_deleting_user_removes_addresses(self):
        user = self.add_user()
        self.add_address(user)
        self.db.delete(user)
        self.db.commit()
        self.assertEqual(self.db.scalars(select(Address)).all(), [])

    def test_appeal_without_user_saved(self):
        appeal = Appeal(
            number="DM-00001",
            address_text="Москва, Ленина, 11",
            subject="Не горит свет",
            text="Во дворе темно.",
            status=APPEAL_STATUS_NEW,
        )
        self.db.add(appeal)
        self.db.commit()
        self.assertEqual(appeal.user_id, None)

    def test_appeal_gets_company_by_house(self):
        user = self.add_user()
        address = self.add_address(user)
        company = ManagementCompany(name="УК Ленина 11", email="uk@example.ru", city="Москва")
        self.db.add(company)
        self.db.commit()
        self.db.add(
            CompanyHouse(
                company_id=company.id,
                city="Москва",
                street="Ленина",
                house_number=11,
            )
        )
        appeal = Appeal(
            number="DM-00002",
            user_id=user.id,
            company_id=company.id,
            address_id=address.id,
            address_text="Москва, Ленина, 11",
            subject="Не горит свет",
            text="Во дворе темно.",
        )
        self.db.add(appeal)
        self.db.commit()
        self.assertEqual(appeal.company.name, "УК Ленина 11")

    def test_same_outage_from_source_saved_once(self):
        starts_at = datetime(2026, 9, 28, 10, 0)
        outage = Outage(
            utility=UTILITY_WATER,
            city="Москва",
            street="Ленина",
            houses_raw="1-15",
            starts_at=starts_at,
            source="https://otklyuchenia.ru/",
            reason="плановый ремонт",
        )
        self.db.add(outage)
        self.db.commit()
        self.db.add(
            Outage(
                utility=UTILITY_WATER,
                city="Москва",
                street="Ленина",
                houses_raw="1-15",
                starts_at=starts_at,
                source="https://otklyuchenia.ru/",
            )
        )
        with self.assertRaises(IntegrityError):
            self.db.commit()
        self.db.rollback()

    def test_notification_sent_once(self):
        user = self.add_user()
        outage = Outage(
            utility=UTILITY_WATER,
            city="Москва",
            street="Ленина",
            houses_raw="1-15",
            starts_at=datetime(2026, 9, 28, 10, 0),
            source="https://otklyuchenia.ru/",
        )
        self.db.add(outage)
        self.db.commit()
        self.db.add(OutageNotification(user_id=user.id, outage_id=outage.id))
        self.db.commit()
        self.db.add(OutageNotification(user_id=user.id, outage_id=outage.id))
        with self.assertRaises(IntegrityError):
            self.db.commit()
        self.db.rollback()


if __name__ == "__main__":
    unittest.main()
