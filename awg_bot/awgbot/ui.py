"""ui.py — экраны бота: клавиатуры в одну колонку, форматирование, отрисовка.

Каждый экран — текст и кнопки, по одной в строке, как пункты меню awg2.
Нажатие кнопки перерисовывает то же сообщение; ответ на ввод текста
приходит новым сообщением.
"""

from __future__ import annotations

import html
import logging
import time
from typing import Awaitable, Callable, Iterable, Union

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import (CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
                           Message)

from . import api

log = logging.getLogger("awgbot.ui")

Target = Union[CallbackQuery, Message]
Button = tuple[str, str]
TEXT_MAX = 4096

esc = html.escape


# ── Клавиатуры ────────────────────────────────────────────
def kb(*items: Button | Iterable[Button] | None) -> InlineKeyboardMarkup:
    """Кнопки по одной в строке. Элемент — (текст, данные), список таких
    пар или None (пропуск: удобно для условных пунктов)."""
    rows: list[list[InlineKeyboardButton]] = []
    for item in items:
        if not item:
            continue
        pairs = [item] if isinstance(item, tuple) else list(item)
        for text, data in pairs:
            rows.append([InlineKeyboardButton(text=text, callback_data=data)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def back(to: str = "main", text: str = "◀️ Назад") -> Button:
    return (text, to)


HOME: Button = ("🏠 Главное меню", "main")


# ── Текст ─────────────────────────────────────────────────
def pre(text: str, limit: int = 3000, tail: bool = True) -> str:
    """Моноширинный блок. Длинный текст режется: по умолчанию остаётся
    конец — в журналах важны последние строки."""
    text = (text or "").strip("\n")
    if not text:
        return ""
    if len(text) > limit:
        text = ("…\n" + text[-limit:]) if tail else (text[:limit] + "\n…")
    return f"<pre>{esc(text)}</pre>"


def fmt_bytes(n: int | None) -> str:
    n = int(n or 0)
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if n < 1024:
            return f"{n} {unit}" if unit == "Б" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} ТБ"


def fmt_dur(sec: int | None) -> str:
    """3с / 5м / 2ч 15м / 3д 4ч."""
    s = max(0, int(sec or 0))
    if s < 60:
        return f"{s}с"
    if s < 3600:
        return f"{s // 60}м"
    if s < 86400:
        return f"{s // 3600}ч {s % 3600 // 60}м"
    return f"{s // 86400}д {s % 86400 // 3600}ч"


def fmt_time(ts: int | None) -> str:
    return time.strftime("%d.%m.%Y %H:%M", time.localtime(int(ts or 0)))


def fmt_expire(ts: int | None) -> str:
    if not ts:
        return "бессрочно"
    left = int(ts) - int(time.time())
    return f"{fmt_time(ts)} ({'через ' + fmt_dur(left) if left > 0 else 'истёк'})"


def state_icon(state: str) -> str:
    """Состояние туннеля из awg2: up / off / none."""
    return {"up": "🟢", "off": "⚪️"}.get(state, "▫️")


def state_word(state: str) -> str:
    return {"up": "включён", "off": "выключен", "none": "не настроен"}.get(state, state)


def fail(r: api.Result, title: str = "") -> str:
    """Экран ошибки: причина и хвост журнала awg2."""
    head = f"❌ <b>{esc(title)}</b>\n" if title else "❌ "
    text = f"{head}{esc(r.message)}"
    log_tail = "\n".join(r.log.strip().splitlines()[-12:])
    if log_tail and log_tail.strip() != r.message.strip():
        text += "\n" + pre(log_tail, 2000)
    return text


# ── Отрисовка ─────────────────────────────────────────────
async def render(target: Target, text: str, markup: InlineKeyboardMarkup | None = None) -> Message | None:
    """Кнопка — правим её сообщение; сообщение — отвечаем новым."""
    text = text[:TEXT_MAX]
    if isinstance(target, CallbackQuery):
        msg = target.message
        try:
            await target.answer()
        except TelegramBadRequest:
            pass                                    # колбэк старше 15 минут
        if isinstance(msg, Message):
            try:
                return await msg.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
            except TelegramBadRequest as e:
                if "not modified" in str(e):
                    return msg
                log.debug("edit_text: %s — шлю новым сообщением", e)
            return await msg.answer(text, reply_markup=markup, disable_web_page_preview=True)
        return None
    return await target.answer(text, reply_markup=markup, disable_web_page_preview=True)


def chat_of(target: Target) -> Message:
    """Сообщение, в чат которого отвечать."""
    return target.message if isinstance(target, CallbackQuery) else target  # type: ignore[return-value]


async def result(target: Target, r: api.Result, title: str, back_to: str,
                 ok_text: str = "") -> None:
    """Итог быстрой команды: текст awg2 при успехе, причина при ошибке."""
    if r.ok:
        body = ok_text or pre("\n".join(r.log.strip().splitlines()[-15:]), 2500)
        await render(target, f"✅ <b>{esc(title)}</b>\n{body}", kb(back(back_to)))
    else:
        await render(target, fail(r, title), kb(back(back_to)))


async def confirm(target: Target, text: str, yes: Button, no_to: str) -> None:
    await render(target, text, kb(yes, back(no_to, "✖️ Отмена")))


# ── Колбэки разделов ──────────────────────────────────────
Handler = Callable[[CallbackQuery, FSMContext, str], Awaitable[None]]


class Actions:
    """Колбэки раздела вида «префикс:действие:аргумент» → функции
    (cb, state, аргумент). Пустое действие — экран самого раздела.
    Любое нажатие отменяет незаконченный ввод текста; данные мастеров
    (ключи FSM) при этом остаются."""

    def __init__(self, router: Router, prefix: str) -> None:
        self.prefix = prefix
        self.table: dict[str, Handler] = {}
        router.callback_query.register(
            self._dispatch, F.data.func(lambda d: d == prefix or d.startswith(prefix + ":")))

    def __call__(self, act: str = "") -> Callable[[Handler], Handler]:
        def deco(fn: Handler) -> Handler:
            self.table[act] = fn
            return fn
        return deco

    def data(self, act: str = "", arg: str = "") -> str:
        """Готовая строка колбэка. Telegram ограничивает её 64 байтами."""
        d = self.prefix + (f":{act}" if act or arg else "") + (f":{arg}" if arg else "")
        if len(d.encode()) > 64:
            raise ValueError(f"callback_data длиннее 64 байт: {d}")
        return d

    async def _dispatch(self, cb: CallbackQuery, state: FSMContext) -> None:
        _, _, rest = (cb.data or "").partition(":")
        act, _, arg = rest.partition(":")
        fn = self.table.get(act)
        if fn is None:
            await cb.answer("Кнопка устарела — открой меню заново", show_alert=True)
            return
        if await state.get_state() is not None:
            await state.set_state(None)
        await fn(cb, state, arg)


# ── Списки за кнопками ────────────────────────────────────
# В callback_data влезает 64 байта — длинные значения (пути бэкапов, теги
# Xray) кнопка передаёт номером, а сам список лежит в данных FSM.
async def remember(state: FSMContext, key: str, items: list) -> None:
    await state.update_data({f"list:{key}": items})


async def recall(state: FSMContext, key: str, idx: str):
    items = (await state.get_data()).get(f"list:{key}") or []
    try:
        return items[int(idx)]
    except (ValueError, IndexError):
        return None
