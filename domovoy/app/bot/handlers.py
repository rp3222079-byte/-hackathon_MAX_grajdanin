"""Сценарии бота: адрес, отключения, обращение в УК, настройки."""
from __future__ import annotations

import logging
from typing import Any

from app.bot import keyboards as kb
from app.bot import texts
from app.bot.api import ApiClient, ApiError
from app.bot.client import MaxClient
from app.bot.states import DialogStore, Step

logger = logging.getLogger(__name__)


class BotLogic:
    def __init__(self, max_client: MaxClient, api: ApiClient) -> None:
        self.max = max_client
        self.api = api
        self.dialogs = DialogStore()
        self._user_cache: dict[str, dict] = {}

    # --- служебное ---

    def user(self, max_user_id: str, full_name: str | None = None) -> dict:
        """Возвращает пользователя из API, создавая его при первом обращении."""
        cached = self._user_cache.get(max_user_id)
        if cached:
            return cached
        data = self.api.upsert_user(max_user_id, full_name)
        self._user_cache[max_user_id] = data
        return data

    def refresh_user(self, max_user_id: str) -> dict:
        self._user_cache.pop(max_user_id, None)
        return self.user(max_user_id)

    def say(self, user_id: str, text: str, keyboard: list | None = None) -> None:
        try:
            self.max.send_message(user_id, text, keyboard)
        except Exception:  # noqa: BLE001 — не роняем бота из-за одного сообщения
            logger.exception("Не удалось отправить сообщение пользователю %s", user_id)

    def show_menu(self, user_id: str, prefix: str | None = None) -> None:
        self.dialogs.reset(user_id)
        self.say(user_id, prefix or texts.MENU, kb.MAIN_MENU)

    # --- точки входа ---

    def handle_message(self, user_id: str, text: str, full_name: str | None, attachments: list | None) -> None:
        text = (text or "").strip()
        dialog = self.dialogs.get(user_id)

        if text.lower() in {"/start", "старт", "начать"}:
            self.user(user_id, full_name)
            self.dialogs.reset(user_id)
            self.say(user_id, texts.WELCOME)
            self.start_address(user_id)
            return

        if text.lower() in {"/help", "помощь"}:
            self.show_menu(user_id)
            return

        if text.lower() in {"/menu", "меню", "отмена", "/cancel"}:
            self.show_menu(user_id, texts.APPEAL_CANCELLED if dialog.step != Step.IDLE else None)
            return

        handler = {
            Step.ADDRESS_CITY: self.on_city,
            Step.ADDRESS_STREET: self.on_street,
            Step.ADDRESS_HOUSE: self.on_house,
            Step.ADDRESS_FLAT: self.on_flat,
            Step.APPEAL_MESSAGE: self.on_appeal_message,
            Step.APPEAL_PHOTO: self.on_appeal_photo,
        }.get(dialog.step)

        if handler is None:
            self.say(user_id, texts.UNKNOWN, kb.MAIN_MENU)
            return

        if dialog.step is Step.APPEAL_PHOTO:
            handler(user_id, text, attachments)
        else:
            handler(user_id, text)

    def handle_callback(self, user_id: str, payload: str, full_name: str | None) -> None:
        self.user(user_id, full_name)

        if payload == "menu":
            self.show_menu(user_id)
        elif payload == "outages":
            self.show_outages(user_id)
        elif payload == "address":
            self.show_address(user_id)
        elif payload == "address_set":
            self.start_address(user_id)
        elif payload == "address_delete":
            self.delete_address(user_id)
        elif payload == "appeal":
            self.start_appeal(user_id)
        elif payload.startswith("category:"):
            self.on_category(user_id, payload.split(":", 1)[1])
        elif payload == "photo_skip":
            self.on_appeal_photo(user_id, "", None)
        elif payload == "appeal_send":
            self.send_appeal(user_id)
        elif payload == "my_appeals":
            self.show_my_appeals(user_id)
        elif payload == "settings":
            self.show_settings(user_id)
        elif payload in {"toggle_water", "toggle_electricity"}:
            self.toggle_setting(user_id, payload)
        elif payload == "cancel":
            self.show_menu(user_id, texts.APPEAL_CANCELLED)
        else:
            self.say(user_id, texts.UNKNOWN, kb.MAIN_MENU)

    # --- адрес ---

    def start_address(self, user_id: str) -> None:
        dialog = self.dialogs.get(user_id)
        dialog.reset()
        dialog.step = Step.ADDRESS_CITY
        self.say(user_id, texts.ASK_CITY)

    def on_city(self, user_id: str, text: str) -> None:
        dialog = self.dialogs.get(user_id)
        dialog.data["city"] = text
        dialog.step = Step.ADDRESS_STREET
        self.say(user_id, texts.ASK_STREET)

    def on_street(self, user_id: str, text: str) -> None:
        dialog = self.dialogs.get(user_id)
        dialog.data["street"] = text
        dialog.step = Step.ADDRESS_HOUSE
        self.say(user_id, texts.ASK_HOUSE)

    def on_house(self, user_id: str, text: str) -> None:
        dialog = self.dialogs.get(user_id)
        dialog.data["house"] = text
        dialog.step = Step.ADDRESS_FLAT
        self.say(user_id, texts.ASK_FLAT)

    def on_flat(self, user_id: str, text: str) -> None:
        dialog = self.dialogs.get(user_id)
        flat = None if text.strip() in {"-", "нет", ""} else text.strip()
        user = self.user(user_id)

        # У жителя один активный адрес: старые удаляем
        for address in user.get("addresses", []):
            try:
                self.api.delete_address(user["id"], address["id"])
            except ApiError:
                logger.warning("Не удалось удалить адрес %s", address["id"])

        try:
            created = self.api.add_address(
                user["id"], dialog.data["city"], dialog.data["street"], dialog.data["house"], flat
            )
        except ApiError as error:
            logger.warning("Адрес не сохранён: %s", error)
            self.say(user_id, texts.ADDRESS_FAILED)
            dialog.step = Step.ADDRESS_STREET
            return

        self.refresh_user(user_id)
        dialog.reset()
        address_text = f"{created['street']}, д. {created['house']}"
        if created.get("flat"):
            address_text += f", кв. {created['flat']}"
        self.say(user_id, texts.ADDRESS_SAVED.format(address=address_text), kb.MAIN_MENU)

    def show_address(self, user_id: str) -> None:
        user = self.refresh_user(user_id)
        addresses = user.get("addresses", [])
        if not addresses:
            self.say(user_id, texts.NO_ADDRESS)
            self.start_address(user_id)
            return
        address = addresses[0]
        text = f"{address['city']}, {address['street']}, д. {address['house']}"
        if address.get("flat"):
            text += f", кв. {address['flat']}"
        self.say(user_id, text, kb.ADDRESS_MENU)

    def delete_address(self, user_id: str) -> None:
        user = self.refresh_user(user_id)
        for address in user.get("addresses", []):
            try:
                self.api.delete_address(user["id"], address["id"])
            except ApiError:
                logger.warning("Не удалось удалить адрес %s", address["id"])
        self.refresh_user(user_id)
        self.say(user_id, "Адрес удалён. Уведомления приходить не будут.", kb.MAIN_MENU)

    # --- отключения ---

    def show_outages(self, user_id: str) -> None:
        user = self.refresh_user(user_id)
        if not user.get("addresses"):
            self.say(user_id, texts.NO_ADDRESS)
            self.start_address(user_id)
            return

        try:
            outages = self.api.outages_for_user(user["id"])
        except ApiError:
            logger.exception("Не удалось получить отключения")
            self.say(user_id, texts.ERROR, kb.MAIN_MENU)
            return

        if not outages:
            self.say(user_id, texts.NO_OUTAGES, kb.MAIN_MENU)
            return

        for outage in outages[:5]:
            self.say(user_id, texts.outage_card(outage))
        self.say(user_id, texts.MENU, kb.MAIN_MENU)

    # --- обращение ---

    def start_appeal(self, user_id: str) -> None:
        user = self.refresh_user(user_id)
        if not user.get("addresses"):
            self.say(user_id, texts.NO_ADDRESS)
            self.start_address(user_id)
            return

        dialog = self.dialogs.get(user_id)
        dialog.reset()
        dialog.step = Step.APPEAL_CATEGORY
        self.say(user_id, texts.ASK_CATEGORY, kb.categories_keyboard())

    def on_category(self, user_id: str, category: str) -> None:
        dialog = self.dialogs.get(user_id)
        dialog.data["category"] = category
        dialog.step = Step.APPEAL_MESSAGE
        self.say(user_id, texts.ASK_MESSAGE)

    def on_appeal_message(self, user_id: str, text: str) -> None:
        if len(text) < 5:
            self.say(user_id, "Слишком коротко. Опишите проблему подробнее.")
            return
        dialog = self.dialogs.get(user_id)
        dialog.data["message"] = text
        dialog.step = Step.APPEAL_PHOTO
        self.say(user_id, texts.ASK_PHOTO, kb.SKIP_PHOTO)

    def on_appeal_photo(self, user_id: str, text: str, attachments: list | None) -> None:
        dialog = self.dialogs.get(user_id)
        photo_url = self._photo_url(attachments)
        if photo_url:
            try:
                content = self.max.download_file(photo_url)
                dialog.data["photo_path"] = self.api.upload_photo("photo.jpg", content)
            except Exception:  # noqa: BLE001 — фото не должно ломать обращение
                logger.exception("Фото не загрузилось")
                self.say(user_id, "Фото не загрузилось, отправлю обращение без него.")
        self.confirm_appeal(user_id)

    @staticmethod
    def _photo_url(attachments: list | None) -> str | None:
        for attachment in attachments or []:
            if attachment.get("type") in {"image", "photo"}:
                payload = attachment.get("payload", {})
                return payload.get("url") or payload.get("token")
        return None

    def confirm_appeal(self, user_id: str) -> None:
        dialog = self.dialogs.get(user_id)
        user = self.user(user_id)
        address = user["addresses"][0]
        company = self.api.company_by_address(address["street"], address["house"])

        if not company:
            dialog.reset()
            self.say(user_id, texts.APPEAL_NO_COMPANY, kb.MAIN_MENU)
            return

        dialog.data["company_name"] = company["name"]
        dialog.step = Step.APPEAL_CONFIRM
        address_text = f"{address['city']}, {address['street']}, д. {address['house']}"
        self.say(
            user_id,
            texts.APPEAL_CONFIRM.format(
                address=address_text,
                category=dialog.data["category"],
                message=dialog.data["message"],
                company=company["name"],
            ),
            kb.CONFIRM_APPEAL,
        )

    def send_appeal(self, user_id: str) -> None:
        dialog = self.dialogs.get(user_id)
        if dialog.step is not Step.APPEAL_CONFIRM:
            self.show_menu(user_id)
            return

        user = self.user(user_id)
        address = user["addresses"][0]
        payload: dict[str, Any] = {
            "category": dialog.data["category"],
            "message": dialog.data["message"],
            "city": address["city"],
            "street": address["street"],
            "house": address["house"],
            "flat": address.get("flat"),
            "max_user_id": user_id,
            "photo_path": dialog.data.get("photo_path"),
            "source": "max",
        }

        try:
            appeal = self.api.create_appeal(**payload)
        except ApiError:
            logger.exception("Обращение не создалось")
            self.say(user_id, texts.ERROR, kb.MAIN_MENU)
            return

        dialog.reset()
        company_name = (appeal.get("company") or {}).get("name", dialog.data.get("company_name", "УК"))
        self.say(
            user_id,
            texts.APPEAL_SENT.format(number=appeal["number"], company=company_name),
            kb.MAIN_MENU,
        )

    def show_my_appeals(self, user_id: str) -> None:
        user = self.user(user_id)
        try:
            appeals = self.api.my_appeals(user["id"])
        except ApiError:
            self.say(user_id, texts.ERROR, kb.MAIN_MENU)
            return

        if not appeals:
            self.say(user_id, "Обращений пока нет.", kb.MAIN_MENU)
            return

        lines = []
        for appeal in appeals[:10]:
            status = texts.STATUS_LABELS.get(appeal["status"], appeal["status"])
            lines.append(f"{appeal['number']} — {appeal['category']} — {status}")
        self.say(user_id, "\n".join(lines), kb.MAIN_MENU)

    # --- настройки ---

    def show_settings(self, user_id: str) -> None:
        user = self.refresh_user(user_id)
        self.say(
            user_id,
            texts.SETTINGS_TITLE,
            kb.settings_keyboard(user["notify_water"], user["notify_electricity"]),
        )

    def toggle_setting(self, user_id: str, payload: str) -> None:
        user = self.refresh_user(user_id)
        field = "notify_water" if payload == "toggle_water" else "notify_electricity"
        self.api.update_settings(user["id"], **{field: not user[field]})
        self.refresh_user(user_id)
        self.show_settings(user_id)
