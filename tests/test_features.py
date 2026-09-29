"""Уведомления, страница УК, защита API, справочник и разбор данных MAX."""
import unittest
from unittest import mock

from app.bot import client as max_client
from app.bot import geo
from app.config import settings
from app.models import UTILITY_ELECTRICITY
from app.security import appeal_link, appeal_signature
from tests.support import ApiTestCase


class TestOutageNotifications(ApiTestCase):
    def pending(self):
        response = self.client.get("/outages/notifications/pending")
        self.assertEqual(response.status_code, 200)
        return response.json()

    def resident(self, **settings_fields):
        user = self.create_user()
        self.add_address(user["id"])
        if settings_fields:
            self.client.patch(f"/users/{user['id']}", json=settings_fields)
        return user

    def test_soon_outage_is_pending(self):
        self.add_outage(starts_in_hours=1)
        user = self.resident()
        [item] = self.pending()
        self.assertEqual(item["max_user_id"], "1001")
        self.assertEqual(item["user_id"], user["id"])
        self.assertIn("ул. Ленина, 11", item["address"])

    def test_far_outage_waits_for_its_window(self):
        self.add_outage(starts_in_hours=20)
        self.resident()
        self.assertEqual(self.pending(), [])

    def test_bigger_window_catches_far_outage(self):
        self.add_outage(starts_in_hours=20)
        self.resident(notify_hours_before=24)
        self.assertEqual(len(self.pending()), 1)

    def test_running_outage_is_pending_and_finished_is_not(self):
        self.add_outage(starts_in_hours=-1, duration_hours=3)
        self.add_outage(starts_in_hours=-5, duration_hours=1)
        self.resident()
        self.assertEqual(len(self.pending()), 1)

    def test_settings_are_respected(self):
        self.add_outage(starts_in_hours=1)
        self.add_outage(starts_in_hours=1, utility=UTILITY_ELECTRICITY)
        user = self.resident(notify_water=False)
        self.assertEqual([item["outage"]["utility"] for item in self.pending()], [UTILITY_ELECTRICITY])
        self.client.patch(f"/users/{user['id']}", json={"notify_outages": False})
        self.assertEqual(self.pending(), [])

    def test_other_house_is_not_notified(self):
        self.add_outage(starts_in_hours=1, houses="40-50")
        self.resident()
        self.assertEqual(self.pending(), [])

    def test_mark_notified(self):
        outage_id = self.add_outage(starts_in_hours=1)
        user = self.resident()
        response = self.client.post(f"/outages/{outage_id}/notified", json={"user_id": user["id"]})
        self.assertEqual(response.status_code, 204)
        self.assertEqual(self.pending(), [])
        again = self.client.post(f"/outages/{outage_id}/notified", json={"user_id": user["id"]})
        self.assertEqual(again.status_code, 204)

    def test_ends_after_filter(self):
        self.add_outage(starts_in_hours=-10, duration_hours=2)
        self.add_outage(starts_in_hours=2)
        from app.timeutil import local_now

        response = self.client.get("/outages", params={"ends_after": local_now().isoformat()})
        self.assertEqual(len(response.json()), 1)


class TestAppealStatuses(ApiTestCase):
    def appeal(self):
        user = self.create_user()
        address = self.add_address(user["id"])
        body = {"user_id": user["id"], "address_id": address["id"], "subject": "Лифт",
                "text": "Не работает", "contact": "Иван, +79990001122"}
        response = self.client.post("/appeals", json=body)
        self.assertEqual(response.status_code, 201)
        return response.json()

    def test_appeal_has_company_contact_and_link(self):
        appeal = self.appeal()
        self.assertIsNotNone(appeal["company_id"])
        self.assertEqual(appeal["contact"], "Иван, +79990001122")
        self.assertIn(f"/uk/appeals/{appeal['number']}?sig=", appeal["uk_link"])

    def test_bot_statuses_are_not_pending(self):
        appeal = self.appeal()
        self.client.patch(f"/appeals/{appeal['number']}", json={"status": "sent"})
        self.assertEqual(self.client.get("/appeals/updates/pending").json(), [])

    def test_company_status_is_pending_until_marked(self):
        appeal = self.appeal()
        self.client.patch(f"/appeals/{appeal['number']}", json={"status": "resolved", "comment": "Починили"})
        [update] = self.client.get("/appeals/updates/pending").json()
        self.assertEqual(update["status"], "resolved")
        self.assertEqual(update["uk_comment"], "Починили")
        self.assertEqual(update["company_name"], "УК «Сибирь»")
        self.client.post(f"/appeals/{appeal['number']}/notified", json={"status": "resolved"})
        self.assertEqual(self.client.get("/appeals/updates/pending").json(), [])

    def test_resolved_at_is_set(self):
        appeal = self.appeal()
        updated = self.client.patch(f"/appeals/{appeal['number']}", json={"status": "resolved"}).json()
        self.assertIsNotNone(updated["resolved_at"])


class TestCompanyPage(ApiTestCase):
    def appeal_number(self):
        user = self.create_user()
        address = self.add_address(user["id"])
        body = {"user_id": user["id"], "address_id": address["id"], "subject": "Мусор", "text": "Не вывозят"}
        return self.client.post("/appeals", json=body).json()["number"]

    def test_page_opens_with_signature(self):
        number = self.appeal_number()
        response = self.client.get(appeal_link(number).split("8000", 1)[1])
        self.assertEqual(response.status_code, 200)
        self.assertIn("Не вывозят", response.text)
        self.assertIn("В работе", response.text)

    def test_wrong_signature_is_rejected(self):
        number = self.appeal_number()
        self.assertEqual(self.client.get(f"/uk/appeals/{number}?sig=forged").status_code, 403)
        self.assertEqual(self.client.get(f"/uk/appeals/{number}").status_code, 403)
        other = appeal_signature("DM-99999")
        self.assertEqual(self.client.get(f"/uk/appeals/{number}?sig={other}").status_code, 403)

    def test_company_sets_status_with_comment(self):
        number = self.appeal_number()
        form = {"sig": appeal_signature(number), "status": "in_progress", "comment": "Мастер придёт в 10:00"}
        response = self.client.post(f"/uk/appeals/{number}", data=form)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Готово", response.text)
        appeal = self.client.get(f"/appeals/{number}").json()
        self.assertEqual(appeal["status"], "in_progress")
        self.assertEqual(appeal["uk_comment"], "Мастер придёт в 10:00")

    def test_new_comment_with_same_status_is_notified_again(self):
        number = self.appeal_number()
        signature = appeal_signature(number)
        self.client.post(f"/uk/appeals/{number}", data={"sig": signature, "status": "in_progress"})
        self.client.post(f"/appeals/{number}/notified", json={"status": "in_progress"})
        self.client.post(f"/uk/appeals/{number}",
                         data={"sig": signature, "status": "in_progress", "comment": "Перенесли на завтра"})
        self.assertEqual(len(self.client.get("/appeals/updates/pending").json()), 1)

    def test_bot_statuses_cannot_be_set_from_page(self):
        number = self.appeal_number()
        response = self.client.post(f"/uk/appeals/{number}",
                                    data={"sig": appeal_signature(number), "status": "failed"})
        self.assertEqual(response.status_code, 422)

    def test_user_input_is_escaped(self):
        user = self.create_user()
        address = self.add_address(user["id"])
        body = {"user_id": user["id"], "address_id": address["id"], "subject": "Другое",
                "text": "<script>alert(1)</script>"}
        number = self.client.post("/appeals", json=body).json()["number"]
        page = self.client.get(f"/uk/appeals/{number}?sig={appeal_signature(number)}").text
        self.assertNotIn("<script>alert(1)</script>", page)


class TestApiKey(ApiTestCase):
    def setUp(self):
        super().setUp()
        self._token = settings.api_token
        settings.api_token = "secret-token"

    def tearDown(self):
        settings.api_token = self._token
        super().tearDown()

    def test_without_key_rejected(self):
        self.assertEqual(self.client.get("/appeals").status_code, 401)
        self.assertEqual(self.client.post("/users", json={}).status_code, 401)

    def test_with_key_allowed(self):
        response = self.client.get("/appeals", headers={"X-API-Key": "secret-token"})
        self.assertEqual(response.status_code, 200)

    def test_health_and_docs_are_public(self):
        self.assertEqual(self.client.get("/health").status_code, 200)
        self.assertEqual(self.client.get("/docs").status_code, 200)


class TestDirectory(ApiTestCase):
    def test_cities(self):
        self.assertEqual(self.client.get("/companies/cities").json(), ["Новосибирск"])

    def test_exact_street(self):
        response = self.client.get("/companies/streets", params={"city": "новосибирск", "q": "ул. Ленина"})
        self.assertEqual(response.json(), ["улица Ленина"])

    def test_street_typo_suggestion(self):
        response = self.client.get("/companies/streets", params={"city": "Новосибирск", "q": "Ленена"})
        self.assertEqual(response.json(), ["улица Ленина"])

    def test_nonsense_street(self):
        response = self.client.get("/companies/streets", params={"city": "Новосибирск", "q": "Абракадабровая"})
        self.assertEqual(response.json(), [])

    def test_lookup_company(self):
        params = {"city": "Новосибирск", "street": "Мира", "house_number": 12, "house_corpus": "К2"}
        response = self.client.get("/companies/lookup", params=params)
        self.assertEqual(response.json()["name"], "УК «Сибирь»")

    def test_lookup_unknown_house(self):
        params = {"city": "Новосибирск", "street": "Ленина", "house_number": 999}
        self.assertEqual(self.client.get("/companies/lookup", params=params).status_code, 404)

    def test_deleting_primary_promotes_next(self):
        user = self.create_user()
        first = self.add_address(user["id"])
        second = self.add_address(user["id"], street="ул. Мира", house_number=12)
        self.client.delete(f"/addresses/{first['id']}")
        [left] = self.client.get(f"/users/{user['id']}/addresses").json()
        self.assertEqual(left["id"], second["id"])
        self.assertTrue(left["is_primary"])


class TestParsing(unittest.TestCase):
    def test_nominatim_answer(self):
        found = geo.parse_nominatim({"city": "Новосибирск", "road": "улица Мира", "house_number": "12 к2"})
        self.assertEqual(found, {"city": "Новосибирск", "street": "улица Мира",
                                 "house_number": 12, "house_corpus": "к2"})

    def test_nominatim_without_house(self):
        self.assertEqual(geo.parse_nominatim({"town": "Бердск", "road": "улица Ленина"}),
                         {"city": "Бердск", "street": "улица Ленина"})

    def test_vcard_contact(self):
        vcf = "BEGIN:VCARD\nFN:Анна\nTEL;TYPE=cell:+7 999 111-22-33\nEND:VCARD"
        self.assertEqual(geo.contact_from_attachment({"vcf_info": vcf}), "Анна, +7 999 111-22-33")

    def test_contact_from_max_info(self):
        payload = {"max_info": {"first_name": "Анна", "last_name": "Смирнова"}}
        self.assertEqual(geo.contact_from_attachment(payload), "Анна Смирнова")


class TestMaxClient(unittest.TestCase):
    def test_strings_become_callback_buttons(self):
        keyboard = max_client.to_inline_keyboard([["Мой адрес"], [max_client.contact_button("Телефон")]])
        buttons = keyboard["payload"]["buttons"]
        self.assertEqual(buttons[0][0], {"type": "callback", "text": "Мой адрес", "payload": "Мой адрес"})
        self.assertEqual(buttons[1][0], {"type": "request_contact", "text": "Телефон"})

    def test_device_buttons_are_dropped_if_rejected(self):
        client = max_client.MaxClient(token="t", base_url="https://max.invalid")
        calls = []

        def fake_request(method, path, **kwargs):
            calls.append(kwargs["json"])
            if len(calls) == 1:
                raise max_client.MaxApiError(400, "bad button")
            return {}

        with mock.patch.object(client, "_request", side_effect=fake_request):
            client.send_message(1, "Контакт?", [[max_client.contact_button("Телефон")], ["Не указывать"]])
        buttons = calls[-1]["attachments"][0]["payload"]["buttons"]
        self.assertEqual(buttons, [[{"type": "callback", "text": "Не указывать", "payload": "Не указывать"}]])

    def test_ca_bundle_contains_russian_root(self):
        from app.bot.tls import RUSSIAN_ROOT_CA, ca_bundle_path

        with open(ca_bundle_path(), encoding="utf-8") as bundle:
            self.assertIn(RUSSIAN_ROOT_CA.read_text(encoding="utf-8").strip(), bundle.read())
