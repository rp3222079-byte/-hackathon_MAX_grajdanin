"""Сценарии бота от начала до конца на настоящем API с базой в памяти."""
import email
from email import policy
from unittest import mock

from app.bot import geo, keyboards, main, states, texts, workers
from tests.support import BotTestCase


class TestAddressDialog(BotTestCase):
    def test_first_start_asks_city_with_buttons(self):
        reply, keyboard = self.say("/start")
        self.assertIn("Домовой", reply)
        self.assertIn("Новосибирск", self.labels(keyboard))
        self.assertEqual(states.get_state(self.USER)["step"], "addr_city")

    def test_full_address_flow_shows_company(self):
        reply, keyboard = self.register_address()
        self.assertIn("Новосибирск, улица Ленина, 11, кв. 5", reply)
        self.assertIn("УК «Сибирь»", reply)
        self.assertIsNone(states.get_state(self.USER))
        self.assertIn(texts.BTN_APPEAL, self.labels(keyboard))

    def test_city_outside_directory_is_rejected(self):
        self.say("/start")
        reply, _ = self.say("Москва")
        self.assertIn("справочника управляющих компаний пока нет", reply)
        self.assertEqual(states.get_state(self.USER)["step"], "addr_city")

    def test_street_typo_gets_suggestions(self):
        self.say("/start")
        self.say("новосибирск")
        reply, keyboard = self.say("Ленена")
        self.assertIn("Возможно", reply)
        self.assertIn("улица Ленина", self.labels(keyboard))
        reply, _ = self.say("улица Ленина")
        self.assertEqual(reply, texts.ASK_HOUSE)

    def test_unknown_street_is_not_saved(self):
        self.say("/start")
        self.say("Новосибирск")
        reply, _ = self.say("Абракадабровая")
        self.assertIn("Не нашёл улицу", reply)
        self.assertEqual(states.get_state(self.USER)["step"], "addr_street")

    def test_house_missing_in_directory(self):
        self.say("/start")
        self.say("Новосибирск")
        self.say("Ленина")
        reply, _ = self.say("999")
        self.assertIn("нет в справочнике", reply)
        self.assertEqual(states.get_state(self.USER)["step"], "addr_house")

    def test_menu_button_mid_dialog_is_not_saved_as_street(self):
        """Раньше нажатие «Отключения» на шаге улицы сохраняло улицу «Отключения»."""
        self.say("/start")
        self.say("Новосибирск")
        reply, _ = self.say(texts.BTN_OUTAGES)
        self.assertEqual(reply, texts.NO_ADDRESS)
        self.assertIsNone(states.get_state(self.USER))

    def test_cancel_leaves_dialog(self):
        self.say("/start")
        reply, _ = self.say(texts.BTN_CANCEL)
        self.assertEqual(reply, texts.CANCELLED)
        self.assertIsNone(states.get_state(self.USER))

    def test_second_address_becomes_primary_and_can_be_switched_back(self):
        self.register_address()
        self.say(texts.BTN_ADD_ADDRESS)
        self.say("Новосибирск")
        self.say("Мира")
        self.say("12к2")
        reply, _ = self.say(texts.BTN_NO_FLAT)
        self.assertIn("улица Мира, 12к2", reply)

        reply, keyboard = self.say(texts.BTN_MY_ADDRESS)
        self.assertIn("улица Мира, 12к2 — основной", reply)
        make_primary = next(item for row in keyboard for item in row
                            if isinstance(item, dict) and item["payload"].startswith(keyboards.PRIMARY_PREFIX))
        reply, _ = self.say(make_primary["payload"])
        self.assertIn("улица Ленина, 11, кв. 5 — основной", reply)

    def test_delete_address(self):
        self.register_address()
        _, keyboard = self.say(texts.BTN_MY_ADDRESS)
        delete = next(item for row in keyboard for item in row
                      if isinstance(item, dict) and item["payload"].startswith(keyboards.DELETE_PREFIX))
        reply, _ = self.say(delete["payload"])
        self.assertIn("Адрес удалён", reply)
        self.assertIn(texts.NO_ADDRESSES_LEFT, reply)

    def test_foreign_address_id_is_ignored(self):
        self.register_address()
        reply, _ = self.say(f"{keyboards.DELETE_PREFIX}99999")
        self.assertIn(texts.ADDRESS_NOT_YOURS, reply)

    def test_geolocation_fills_address(self):
        found = {"city": "Новосибирск", "street": "улица Ленина", "house_number": 11, "house_corpus": None}
        with mock.patch.object(geo, "reverse_geocode", return_value=found):
            self.say("/start")
            reply, _ = self.say(location=(55.03, 82.92))
        self.assertIn("Новосибирск, улица Ленина, 11", reply)
        reply, _ = self.say(texts.BTN_GEO_YES)
        self.assertEqual(reply, texts.ASK_FLAT)

    def test_geolocation_without_house_asks_house(self):
        found = {"city": "Новосибирск", "street": "улица Ленина"}
        with mock.patch.object(geo, "reverse_geocode", return_value=found):
            self.say("/start")
            reply, _ = self.say(location=(55.03, 82.92))
        self.assertIn(texts.ASK_HOUSE, reply)

    def test_dialog_survives_restart(self):
        self.say("/start")
        self.say("Новосибирск")
        states._user_states.clear()
        states._loaded_from = None  # как после перезапуска процесса
        self.assertEqual(states.get_state(self.USER)["step"], "addr_street")


class TestAppealDialog(BotTestCase):
    def start_appeal(self):
        self.register_address()
        return self.say(texts.BTN_APPEAL)

    def test_appeal_needs_address(self):
        reply, keyboard = self.say(texts.BTN_APPEAL)
        self.assertEqual(reply, texts.NO_ADDRESS)
        self.assertIn(texts.BTN_ADD_ADDRESS, self.labels(keyboard))

    def test_recipient_is_known_before_writing(self):
        reply, keyboard = self.start_appeal()
        self.assertIn("УК «Сибирь»", reply)
        self.assertIn("Лифт", self.labels(keyboard))

    def test_urgent_category_shows_phone(self):
        self.start_appeal()
        reply, _ = self.say("Протечка")
        self.assertIn("+7 383 300-00-01", reply)

    def test_full_appeal_is_sent_and_tracked(self):
        self.start_appeal()
        self.say("Лифт")
        self.say("Лифт не работает третий день")
        self.say(texts.BTN_SKIP_PHOTO)
        reply, _ = self.say(texts.BTN_CONTACT_NAME)
        self.assertIn("Получатель: УК «Сибирь»", reply)
        self.assertIn("Иван Петров @ivan", reply)

        reply, _ = self.say(texts.BTN_SEND)
        self.assertIn("принято", reply)
        self.assertEqual(self.run_jobs(), [True])
        self.assertIn("отправлено в УК «Сибирь»", self.max.sent[-1][1])

        letters = list((mailer_dir := workers.mailer.OUTBOX_DIR).glob("*.eml"))
        self.assertEqual(len(letters), 1, mailer_dir)
        letter = email.message_from_bytes(letters[0].read_bytes())
        self.assertEqual(letter["To"], "uk-sib@example.ru")
        plain = letter.get_payload(0).get_payload(decode=True).decode("utf-8")
        self.assertIn("/uk/appeals/DM-00001?sig=", plain)

        reply, _ = self.say(texts.BTN_MY_APPEALS)
        self.assertIn("DM-00001", reply)
        self.assertIn("отправлено в УК", reply)

    def test_photos_and_shared_phone_go_into_letter(self):
        self.start_appeal()
        self.say("Подъезд и двор")
        reply, _ = self.say(photos=["https://i.example/a.jpg"])
        self.assertIn("Фото сохранил (1)", reply)
        reply, _ = self.say("Разбито окно на третьем этаже")
        self.assertEqual(reply, texts.ASK_CONTACT)
        vcard = "BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Иван Петров\r\nTEL;TYPE=cell:+79990001122\r\nEND:VCARD"
        reply, _ = self.say(contact={"vcf_info": vcard})
        self.assertIn("Иван Петров, +79990001122", reply)
        self.assertIn("Фото: 1", reply)
        self.say(texts.BTN_SEND)
        self.run_jobs()

        letter = email.message_from_bytes(
            next(workers.mailer.OUTBOX_DIR.glob("*.eml")).read_bytes(), policy=policy.default
        )
        attachments = [part.get_filename() for part in letter.iter_attachments()]
        self.assertIn("photo-1.jpg", attachments)

    def test_failed_letter_can_be_resent(self):
        self.start_appeal()
        for step in ("Мусор", "Контейнеры не вывозят неделю", texts.BTN_SKIP_PHOTO, texts.BTN_CONTACT_NO):
            self.say(step)
        self.say(texts.BTN_SEND)
        with mock.patch.object(workers.mailer, "send_email", side_effect=workers.mailer.MailError("down")):
            self.assertEqual(self.run_jobs(), [False])
        text, keyboard = self.max.sent[-1][1], self.max.sent[-1][2]
        self.assertIn("Не получилось отправить", text)
        resend = keyboard[0][0]["payload"]

        reply, _ = self.say(texts.BTN_MY_APPEALS)
        self.assertIn("не отправлено", reply)
        reply, _ = self.say(resend)
        self.assertIn("Повторяю отправку", reply)
        self.assertEqual(self.run_jobs(), [True])
        reply, _ = self.say(resend)
        self.assertIn("уже отправлено", reply)

    def test_short_text_is_rejected(self):
        self.start_appeal()
        self.say("Лифт")
        reply, _ = self.say("да")
        self.assertEqual(reply, texts.MESSAGE_TOO_SHORT)

    def test_text_instead_of_photo_is_not_accepted(self):
        self.start_appeal()
        self.say("Лифт")
        self.say("Лифт не работает")
        reply, _ = self.say("вот")
        self.assertEqual(reply, texts.PHOTO_EXPECTED)


class TestOutagesAndSettings(BotTestCase):
    def test_outages_view_hides_finished_and_marks_demo(self):
        self.add_outage(starts_in_hours=-10, duration_hours=2)  # уже закончилось
        self.add_outage(starts_in_hours=-1, duration_hours=5)
        self.register_address()
        reply, _ = self.say(texts.BTN_OUTAGES)
        self.assertIn("идёт сейчас", reply)
        self.assertEqual(reply.count("Вода —"), 1)
        self.assertIn("тестовые", reply)

    def test_no_outages(self):
        self.register_address()
        reply, _ = self.say(texts.BTN_OUTAGES)
        self.assertIn("не запланировано", reply)

    def test_outage_notification_is_sent_once(self):
        self.add_outage(starts_in_hours=1)
        self.register_address()
        self.assertEqual(workers.notify_outages(self.max), 1)
        user_id, text, _ = self.max.sent[-1]
        self.assertEqual(user_id, self.USER)
        self.assertIn("отключат воду", text)
        self.assertEqual(workers.notify_outages(self.max), 0)

    def test_settings_toggle_and_hours(self):
        self.register_address()
        reply, keyboard = self.say(texts.BTN_SETTINGS)
        self.assertIn("Вода: включены", reply)
        self.say(keyboards.SETTINGS_WATER)
        reply, _ = self.say(texts.BTN_SETTINGS)
        self.assertIn("Вода: выключены", reply)

        self.say(texts.BTN_SET_HOURS)
        reply, _ = self.say("100")
        self.assertEqual(reply, texts.ASK_HOURS)
        reply, _ = self.say(f"{keyboards.HOURS_PREFIX}24")
        self.assertIn("за 24 ч.", reply)

        reply, keyboard = self.say(keyboards.SETTINGS_ALL_OFF)
        self.assertIn("Уведомления об отключениях: выключены", reply)
        self.assertIn(texts.BTN_ALL_ON, self.labels(keyboard))

    def test_status_from_company_reaches_resident(self):
        self.register_address()
        self.say(texts.BTN_APPEAL)
        for step in ("Лифт", "Лифт не работает", texts.BTN_SKIP_PHOTO, texts.BTN_CONTACT_NO, texts.BTN_SEND):
            self.say(step)
        self.run_jobs()
        self.client.patch("/appeals/DM-00001", json={"status": "in_progress", "comment": "Мастер придёт завтра"})
        self.assertEqual(workers.notify_appeal_updates(self.max), 1)
        self.assertIn("в работе", self.max.sent[-1][1])
        self.assertIn("Мастер придёт завтра", self.max.sent[-1][1])
        self.assertEqual(workers.notify_appeal_updates(self.max), 0)


class TestUpdateParsing(BotTestCase):
    def test_message_with_photo_location_and_contact(self):
        message = {"body": {"text": "Вот", "attachments": [
            {"type": "image", "payload": {"url": "https://i/1.jpg", "photo_id": 1, "token": "t"}},
            {"type": "location", "latitude": 55.0, "longitude": 82.9},
            {"type": "contact", "payload": {"vcf_info": "FN:Иван"}},
        ]}}
        incoming = main.parse_message(message, 7)
        self.assertEqual(incoming.photos, ["https://i/1.jpg"])
        self.assertEqual(incoming.location, (55.0, 82.9))
        self.assertEqual(incoming.contact, {"vcf_info": "FN:Иван"})

    def test_pressed_label_found_by_payload(self):
        message = {"body": {"text": "Что дальше?", "attachments": [{"type": "inline_keyboard", "payload": {
            "buttons": [[{"type": "callback", "text": "Вода: выключить", "payload": "settings:water"}]]}}]}}
        self.assertEqual(main.pressed_label(message, "settings:water"), "Вода: выключить")

    def test_update_is_answered_even_if_api_is_down(self):
        class Client(type(self.max)):
            def answer_callback(self, *args, **kwargs):
                return {}

        client = Client()
        with mock.patch("app.bot.handlers.route", side_effect=RuntimeError("API недоступен")):
            main.handle_update(client, {"update_type": "message_created", "message": {
                "sender": {"user_id": self.USER, "name": "Иван"},
                "recipient": {"chat_type": "dialog"},
                "body": {"text": "привет"},
            }})
        self.assertEqual(client.sent[-1][1], texts.ERROR)
