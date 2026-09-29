"""Общая заготовка для тестов: API на базе в памяти с тестовым справочником УК.

BotTestCase дополнительно подключает бота к этому API: запросы бота
(app/bot/api.py) идут в TestClient, а не по сети, письма складываются
во временную папку, состояния диалогов — во временный файл.
"""
import os
import shutil
import tempfile
import unittest
from collections.abc import Iterator
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app import seed
from app.bot import api as bot_api
from app.bot import profiles, states, workers
from app.db import create_db_engine, get_db
from app.main import app
from app.migrations import run_migrations
from app.models import UTILITY_WATER, Outage
from app.services import mailer
from app.timeutil import local_now


_template_engine = None


def _template():
    """База со справочником УК: собирается один раз, дальше копируется."""
    global _template_engine
    if _template_engine is None:
        _template_engine = create_db_engine("sqlite://")
        run_migrations(_template_engine)
        with Session(_template_engine) as db:
            seed.load_companies(db)
    return _template_engine


class ApiTestCase(unittest.TestCase):
    """Пустая база в памяти со справочником УК из data/companies.csv."""

    def setUp(self):
        self.engine = create_db_engine("sqlite://")
        source, target = _template().raw_connection(), self.engine.raw_connection()
        try:
            source.driver_connection.backup(target.driver_connection)
        finally:
            source.close()
            target.close()
        app.dependency_overrides[get_db] = self.session
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.clear()
        self.engine.dispose()

    def session(self) -> Iterator[Session]:
        with Session(self.engine) as db:
            yield db

    def add_outage(self, *, street="улица Ленина", houses="1-33", starts_in_hours=1.0,
                   duration_hours=4, utility=UTILITY_WATER, source="demo") -> int:
        starts_at = local_now() + timedelta(hours=starts_in_hours)
        with Session(self.engine) as db:
            outage = Outage(
                utility=utility,
                city="Новосибирск",
                street=street,
                houses_raw=houses,
                starts_at=starts_at,
                ends_at=starts_at + timedelta(hours=duration_hours) if duration_hours else None,
                source=source,
                reason="Плановые работы",
            )
            db.add(outage)
            db.commit()
            return outage.id

    def create_user(self, max_user_id="1001") -> dict:
        return self.client.post("/users", json={"max_user_id": max_user_id}).json()

    def add_address(self, user_id, **fields) -> dict:
        body = {"city": "Новосибирск", "street": "ул. Ленина", "house_number": 11, **fields}
        response = self.client.post(f"/users/{user_id}/addresses", json=body)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()


class FakeMaxClient:
    """Вместо MAX: запоминает отправленные сообщения."""

    def __init__(self):
        self.sent: list[tuple[int, str, list | None]] = []

    def send_message(self, user_id, text, keyboard=None):
        self.sent.append((user_id, text, keyboard))
        return {}

    def download(self, url):
        if "broken" in url:
            raise OSError("нет сети")
        return b"\xff\xd8fake-jpeg", "image/jpeg"


class BotTestCase(ApiTestCase):
    USER = 555

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp()
        self._env = {key: os.environ.get(key) for key in ("BOT_STATE_PATH", "GEOCODER_URL", "SMTP_DRY_RUN",
                                                           "MAIL_REDIRECT_TO")}
        os.environ["BOT_STATE_PATH"] = os.path.join(self.tmp, "state.json")
        os.environ["GEOCODER_URL"] = ""
        os.environ["SMTP_DRY_RUN"] = "true"
        os.environ.pop("MAIL_REDIRECT_TO", None)
        self._outbox = mailer.OUTBOX_DIR
        mailer.OUTBOX_DIR = __import__("pathlib").Path(self.tmp) / "outbox"

        self._original_request = bot_api._request
        bot_api._request = self._request
        bot_api.forget_users()
        states.clear_state(self.USER)
        while not workers._jobs.empty():
            workers._jobs.get_nowait()
        profiles.remember(self.USER, "Иван Петров", "ivan")
        self.max = FakeMaxClient()

    def tearDown(self):
        bot_api._request = self._original_request
        bot_api.forget_users()
        mailer.OUTBOX_DIR = self._outbox
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        states._loaded_from = None
        shutil.rmtree(self.tmp, ignore_errors=True)
        super().tearDown()

    def _request(self, method, path, **kwargs):
        response = self.client.request(method, path, **kwargs)
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail")
            except ValueError:
                detail = response.text
            raise bot_api.ApiError(response.status_code, detail)
        return response.json() if response.content else None

    def say(self, text="", **extra):
        from app.bot.handlers import Incoming, route

        return route(Incoming(user_id=self.USER, text=text, **extra))

    @staticmethod
    def labels(keyboard) -> list[str]:
        return [item if isinstance(item, str) else item["text"] for row in keyboard or [] for item in row]

    def register_address(self, street="ул. Ленина", house="11", flat="5"):
        self.say("/start")
        self.say("Новосибирск")
        self.say(street)
        self.say(house)
        return self.say(flat)

    def run_jobs(self):
        results = []
        while not workers._jobs.empty():
            results.append(workers.process_send(self.max, workers._jobs.get_nowait()))
        return results
