"""monitor.py — уведомления о клиентах с #ping в заметке.

Один раз — когда клиент пропал (🔴), один раз — когда вернулся (🟢, со
временем отсутствия). Пока состояние не меняется, бот молчит. 🟢 уходит
только в пару к отправленному 🔴: после перезапуска бота офлайн-клиенты
просто запоминаются, без уведомлений.

Состояние переживает перезапуск (формат прежних версий):
    {имя: {"since": <последняя активность>, "notified": <отправлено ли 🔴>}}
Сроки клиентов здесь не проверяются: блокирует их таймер awg2, он же и
сообщает об этом владельцам и админам. Клиент, который ни разу не
подключался, не считается пропавшим.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError, TelegramRetryAfter

from . import access, api, store, ui
from .ui import esc

log = logging.getLogger("awgbot.monitor")

# 5 минут, а не 3: с PersistentKeepalive = 25 рукопожатие обновляется
# примерно раз в 2 минуты, и три минуты давали ложные 🔴 от одной потери.
OFFLINE_AFTER = int(os.environ.get("AWG_MON_OFFLINE_AFTER", 5 * 60))
CHECK_INTERVAL = 60


def _load() -> dict[str, dict[str, Any]]:
    state: dict[str, dict[str, Any]] = {}
    for name, val in store.load(store.MONITOR).items():
        if isinstance(val, dict):
            since = val.get("since")
            state[name] = {"since": int(since) if isinstance(since, (int, float)) else 0,
                           "notified": bool(val.get("notified", True))}
        elif val == "offline":                      # самый старый формат
            state[name] = {"since": 0, "notified": True}
    return state


async def _send(bot: Bot, text: str) -> None:
    for uid in access.all_ids():
        for attempt in (1, 2):
            try:
                await bot.send_message(uid, text)
                break
            except TelegramRetryAfter as e:
                if attempt == 2:
                    break
                await asyncio.sleep(min(int(e.retry_after) + 1, 60))
            except TelegramForbiddenError:
                log.warning("Админ %s заблокировал бота — уведомления ему не доходят", uid)
                break
            except TelegramAPIError as e:
                log.warning("Уведомление %s не ушло: %s", uid, e)
                break


def _card(c: dict) -> str:
    note = store.strip_tag(store.note(c["name"]))
    return (f"👤 {esc(c['name'])}\nIP: <code>{esc(c['ip'])}</code>"
            + (f"\nЗаметка: {esc(note)}" if note else ""))


async def tick(bot: Bot, state: dict[str, dict[str, Any]], primed: bool) -> bool:
    """Один проход: уведомления и состояние. False — список клиентов не получен."""
    rows = await api.data("clients", "list")
    if not isinstance(rows, list):
        return False
    notes = store.notes()
    # Заметки удалённых клиентов (в том числе из меню awg2) — прочь: иначе
    # новый клиент с тем же именем унаследует чужой #ping
    alive = {c["name"] for c in rows}
    for gone in [n for n in notes if n not in alive]:
        store.drop_note(gone)
    # Ни разу не подключавшийся клиент не «пропадал» — о нём молчим
    watched = [c for c in rows if store.MONITOR_TAG in notes.get(c["name"], "").lower()
               and not c.get("blocked") and c.get("handshake")]
    now = int(time.time())
    for c in watched:
        hs = int(c["handshake"])
        off = now - hs >= OFFLINE_AFTER
        entry = state.get(c["name"])
        if off and entry is None:
            if primed:
                await _send(bot, f"🔴 <b>Клиент офлайн</b>\n\n{_card(c)}\n"
                                 f"Последняя активность: {ui.fmt_dur(now - hs)} назад")
            state[c["name"]] = {"since": hs, "notified": primed}
        elif not off and entry is not None:
            state.pop(c["name"], None)
            if primed and entry.get("notified"):
                gone = f"\nОтсутствовал: {ui.fmt_dur(now - int(entry['since']))}" if entry.get("since") else ""
                await _send(bot, f"🟢 <b>Клиент снова онлайн</b>\n\n{_card(c)}{gone}")
    names = {c["name"] for c in watched}
    for stale in [k for k in state if k not in names]:
        state.pop(stale)
    store.save(store.MONITOR, state)
    return True


async def loop(bot: Bot) -> None:
    log.info("Мониторинг активности: маркер %s, порог %d мин", store.MONITOR_TAG, OFFLINE_AFTER // 60)
    state = _load()
    primed = False                  # первый проход только запоминает картину
    while True:
        try:
            if await tick(bot, state, primed):
                primed = True
        except asyncio.CancelledError:
            raise
        except Exception:                                   # noqa: BLE001
            log.exception("Ошибка в цикле мониторинга")
        await asyncio.sleep(CHECK_INTERVAL)
