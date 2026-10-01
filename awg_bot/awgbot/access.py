"""access.py — кто управляет ботом.

Владельцы — ID из ADMIN_ID в /etc/awg-bot.conf, приглашённые админы — из
admins.json. Бот — это root на сервере, поэтому проверка стоит одним слоем
на входе диспетчера, а не в каждом обработчике: кнопка, где забыли бы
проверку, была бы дырой. Мимо проверки проходит только /start — через него
приходят приглашения и подсказка «твой ID». Группы и каналы бот не слушает
вовсе, даже владельца: отвечает только в личных сообщениях.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from . import admins
from .config import Config

log = logging.getLogger("awgbot.access")

_cfg: Config | None = None


def setup(cfg: Config) -> None:
    global _cfg
    _cfg = cfg


def owners() -> set[int]:
    return set(_cfg.admins) if _cfg else set()


def is_owner(uid: int) -> bool:
    return uid in owners()


def authorized(uid: int) -> bool:
    return uid in owners() or uid in admins.invited_ids()


def all_ids() -> set[int]:
    """Кому слать уведомления: владельцы и приглашённые."""
    return owners() | admins.invited_ids()


class AccessMiddleware(BaseMiddleware):
    @staticmethod
    def _is_start(text: str | None) -> bool:
        """Ровно команда /start (с «@бот» или payload приглашения), а не
        «/startfoo»: та прошла бы мимо CommandStart() в общий обработчик и
        показала бы чужому меню со сводкой сервера."""
        parts = (text or "").split(maxsplit=1)
        return bool(parts) and parts[0].partition("@")[0] == "/start"

    async def __call__(self, handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
                       event: TelegramObject, data: dict[str, Any]) -> Any:
        user = data.get("event_from_user")
        uid = user.id if user else 0
        # Только личка: в группе конфиги, ключи и QR увидели бы все участники
        chat = data.get("event_chat")
        if getattr(chat, "type", None) != "private":
            if isinstance(event, CallbackQuery):
                await event.answer("Бот работает только в личных сообщениях", show_alert=True)
            log.info("Не личный чат — пропущено: %s (%s)", getattr(chat, "id", "—"), getattr(chat, "type", "—"))
            return None
        if authorized(uid):
            return await handler(event, data)
        if isinstance(event, Message) and self._is_start(event.text):
            return await handler(event, data)
        if isinstance(event, CallbackQuery):
            await event.answer("⛔️ Нет доступа", show_alert=True)
        log.warning("Отказ в доступе: %s (%s)", uid, getattr(user, "username", "") or "—")
        return None
