import unittest

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import seed
from app.db import create_db_engine
from app.migrations import run_migrations
from app.models import (
    UTILITY_TYPES,
    CompanyHouse,
    ManagementCompany,
    Outage,
    OutageNotification,
    User,
)
from app.services.addresses import parse_house_list
from app.services.matching import find_affected_users

DEMO_CITY = "Новосибирск"
# Адреса, обещанные в README: на них демо-отключения точно есть
README_HOMES = [
    {"user_id": 1, "street": "ул. Ленина", "house_number": 11, "house_corpus": None},
    {"user_id": 2, "street": "улица Мира", "house_number": 12, "house_corpus": "к2"},
]


class TestSeed(unittest.TestCase):
    def setUp(self):
        self.engine = create_db_engine("sqlite://")
        run_migrations(self.engine)
        self.db = Session(self.engine, expire_on_commit=False)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_companies_loaded(self):
        added = seed.load_companies(self.db)
        self.assertGreater(added, 0)
        companies = self.db.scalars(select(ManagementCompany)).all()
        self.assertTrue(companies)
        for company in companies:
            self.assertEqual(company.city, DEMO_CITY)
            self.assertTrue(company.email)

    def test_companies_not_duplicated_on_second_run(self):
        seed.load_companies(self.db)
        self.assertEqual(seed.load_companies(self.db), 0)

    def test_every_house_belongs_to_a_company(self):
        seed.load_companies(self.db)
        houses = self.db.scalars(
            select(CompanyHouse).where(CompanyHouse.city == DEMO_CITY)
        ).all()
        self.assertGreater(len(houses), 0)
        self.assertTrue(all(house.company_id for house in houses))

    def test_directory_covers_many_streets(self):
        rows = seed.read_company_rows()
        streets = seed.demo_streets()
        self.assertEqual(len(streets), len(rows))
        self.assertGreaterEqual(len(streets), 80)
        self.assertEqual({row["city"] for row in rows}, {DEMO_CITY})
        for row in rows:
            with self.subTest(company=row["name"]):
                self.assertTrue(row["email"].endswith("@example.ru"))

    def test_outages_loaded(self):
        seed.load_outages(self.db)
        outages = self.db.scalars(select(Outage)).all()
        self.assertGreater(len(outages), 0)
        for outage in outages:
            self.assertEqual(outage.city, DEMO_CITY)
            self.assertIn(outage.utility, UTILITY_TYPES)
            self.assertEqual(outage.source, "demo")
            self.assertTrue(outage.reason)
            self.assertLess(outage.starts_at, outage.ends_at)

    def test_outage_created_for_every_directory_street(self):
        added = seed.load_outages(self.db)
        self.assertEqual(added, len(seed.demo_streets()))
        streets = {
            (outage.city, outage.street)
            for outage in self.db.scalars(select(Outage)).all()
        }
        self.assertEqual(streets, {(city, street) for city, street, _ in seed.demo_streets()})

    def test_outage_params_are_stable_per_street(self):
        for _, street, _ in seed.demo_streets():
            with self.subTest(street=street):
                self.assertEqual(
                    seed.demo_outage_params(street), seed.demo_outage_params(street)
                )

    def test_outages_not_duplicated_on_second_run(self):
        seed.load_outages(self.db)
        self.assertEqual(seed.load_outages(self.db), 0)

    def test_outage_houses_are_served_by_a_company(self):
        seed.load_companies(self.db)
        seed.load_outages(self.db)
        houses = [
            {"user_id": 1, "street": house.street, "house_number": house.house_number,
             "house_corpus": house.house_corpus}
            for house in self.db.scalars(select(CompanyHouse)).all()
        ]
        outages = self.db.scalars(select(Outage)).all()
        for outage in outages:
            with self.subTest(outage=repr(outage)):
                self.assertTrue(find_affected_users(outage.street, outage.houses_raw, houses))

    def test_readme_addresses_have_outages(self):
        seed.load_outages(self.db)
        outages = self.db.scalars(select(Outage)).all()
        for home in README_HOMES:
            with self.subTest(home=home["street"]):
                found = [
                    outage
                    for outage in outages
                    if find_affected_users(outage.street, outage.houses_raw, [home])
                ]
                self.assertTrue(found)

    def test_any_directory_address_gets_an_outage(self):
        seed.load_outages(self.db)
        outages = self.db.scalars(select(Outage)).all()
        for _, street, houses_raw in seed.demo_streets():
            houses = sorted(
                parse_house_list(houses_raw), key=lambda house: (house[0], house[1] or "")
            )
            for house_number, house_corpus in (houses[0], houses[-1]):
                home = {
                    "user_id": 1,
                    "street": street,
                    "house_number": house_number,
                    "house_corpus": house_corpus,
                }
                with self.subTest(home=f"{street} {house_number}{house_corpus or ''}"):
                    self.assertTrue(
                        any(
                            find_affected_users(outage.street, outage.houses_raw, [home])
                            for outage in outages
                        )
                    )

    def test_clear_removes_outages_and_notifications(self):
        seed.load_outages(self.db)
        outage_count = len(self.db.scalars(select(Outage)).all())
        user = User(max_user_id="demo")
        self.db.add(user)
        self.db.flush()
        outage_id = self.db.scalars(select(Outage.id)).first()
        self.db.add(OutageNotification(user_id=user.id, outage_id=outage_id))
        self.db.commit()

        self.assertEqual(seed.clear_outages(self.db), outage_count)
        self.assertEqual(self.db.scalars(select(Outage)).all(), [])
        self.assertEqual(self.db.scalars(select(OutageNotification)).all(), [])


if __name__ == "__main__":
    unittest.main()
