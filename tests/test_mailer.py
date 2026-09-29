import unittest

from app.services import mailer


class TestSendAppeal(unittest.TestCase):
    """Письмо уходит только по настоящему адресу."""

    def test_без_почты_отправка_отклоняется(self):
        for empty in ("", "   ", None):
            with self.subTest(email=empty):
                with self.assertRaises(mailer.MailError) as caught:
                    mailer.send_appeal(
                        number=1,
                        to_email=empty,
                        company='ООО УК "АЗИМУТ"',
                        category="Отопление",
                        message="тест",
                        address="ул. Кирова, 27",
                    )
                self.assertIn("АЗИМУТ", str(caught.exception))

    def test_с_почтой_письмо_собирается(self):
        sent = []
        original = mailer.send_email
        mailer.send_email = lambda msg: sent.append(msg)
        try:
            mailer.send_appeal(
                number=7,
                to_email="uk@novosibirsk.ru",
                company='ООО УК "Проверка"',
                category="Отопление",
                message="тест",
                address="ул. Кирова, 27",
            )
        finally:
            mailer.send_email = original
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["To"], "uk@novosibirsk.ru")
        body = sent[0].get_payload(0).get_payload(decode=True).decode("utf-8")
        self.assertIn("Кому:", body)
        self.assertIn("Проверка", body)
