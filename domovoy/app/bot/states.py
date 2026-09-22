"""Состояния диалогов. Хранятся в памяти процесса — этого хватает для хакатона."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any


class Step(Enum):
    IDLE = auto()
    # Адрес
    ADDRESS_CITY = auto()
    ADDRESS_STREET = auto()
    ADDRESS_HOUSE = auto()
    ADDRESS_FLAT = auto()
    # Обращение
    APPEAL_CATEGORY = auto()
    APPEAL_MESSAGE = auto()
    APPEAL_PHOTO = auto()
    APPEAL_CONFIRM = auto()


@dataclass
class Dialog:
    step: Step = Step.IDLE
    data: dict[str, Any] = field(default_factory=dict)

    def reset(self) -> None:
        self.step = Step.IDLE
        self.data.clear()


class DialogStore:
    """Диалог на каждого пользователя MAX."""

    def __init__(self) -> None:
        self._dialogs: dict[str, Dialog] = {}

    def get(self, user_id: str) -> Dialog:
        return self._dialogs.setdefault(user_id, Dialog())

    def reset(self, user_id: str) -> None:
        self.get(user_id).reset()
