"""icons.py — монохромные иконки (custom emoji) вместо обычных эмодзи в тексте
и на кнопках.

Telegram показывает custom emoji от бота, только если у владельца бота
(аккаунт, создавший его в @BotFather) есть Telegram Premium или у бота есть
имя, купленное на Fragment. Поэтому иконки выключены, пока владелец не
подключит набор и пробное сообщение не покажет их (см. botself). Если
Telegram потом перестанет их принимать, бот сам вернётся к обычным эмодзи.

Состояние — icons.json: {"on": bool, "pack": имя набора, "map": {эмодзи: id}}.
Ключи — эмодзи без селектора варианта (U+FE0F).
"""

from __future__ import annotations

import logging
import re

from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardMarkup, Message

from . import store

log = logging.getLogger("awgbot.icons")

# Цветные значки состояния остаются обычными: в монохромной иконке цвет,
# а с ним и смысл, пропадёт
KEEP = {"🟢", "🔴", "⚪", "▫", "✅", "❌", "⬜", "☑", "🔘", "💚", "🇷🇺", "🌍"}

# Эмодзи бота в порядке «пришли свои иконки»: сначала главное меню
TEMPLATE = ["🖥", "👥", "🩺", "💾", "🌐", "🤖", "🗑", "⬆", "🛡", "🔄",
            "➕", "📊", "📦", "📄", "✏", "⏳", "🎭", "📝", "🔔", "🔃",
            "🧹", "◀", "🏠", "✖", "⚠", "🔀", "🧩", "🛠", "♻", "🔎",
            "📋", "🔁", "📜", "🎯", "🔍", "📂", "📤", "📥", "🔑", "👮",
            "☁", "🛰", "🚪", "🔐", "▶", "⏹", "⚖", "🚨", "🎨", "👤"]

# Набор TgAndroidIcons (значки Telegram для Android) — предлагается кнопкой
DEFAULT_PACK = "TgAndroidIcons"

# Похожие эмодзи: иконки в наборах привязаны к своим эмодзи, и точного
# совпадения с эмодзи бота часто нет — тогда берётся первое похожее
SIMILAR = {
    "🖥": "💻🖱⌨📟", "👥": "👤🫂👪", "🩺": "🔬🧪💉🏥", "💾": "💿📀🗄🗃", "🌐": "🌍🌎🌏🗺",
    "🤖": "👾🦾💬", "🗑": "🚮❌", "⬆": "🔼⏫🆙📲", "🛡": "🔒🔐🛂", "🔄": "🔃🔁♻",
    "➕": "🆕✳", "📊": "📈📉🧮", "📦": "🗃🎁🗂", "📄": "📃📑📋🧾", "✏": "✍🖊🖋📝",
    "⏳": "⌛⏰⏱📅🗓", "🎭": "🥸🕶", "📝": "🗒✏📃", "🔔": "📢📣🔕", "🔃": "🔄🔀",
    "🧹": "🗑🧽", "◀": "⬅🔙↩", "🏠": "🏡🏘", "✖": "❎❌🚫", "⚠": "❗🚨",
    "🔀": "🔃🔄", "🧩": "⚙🔧", "🛠": "🔧🔨⚙🪛", "♻": "🔄🔁", "🔎": "🔍",
    "📋": "📄🗒📑", "🔁": "🔄♻", "📜": "📃📄🧾", "🎯": "📍", "🔍": "🔎",
    "📂": "📁🗂", "📤": "⬆📩🔼", "📥": "⬇📩🔽", "🔑": "🗝🔐", "👮": "👤🛡",
    "☁": "⛅🌥", "🛰": "📡🚀", "🚪": "🚶↪", "🔐": "🔒🔑", "▶": "⏯🔛",
    "⏹": "⏸⛔🛑", "⚖": "🔀", "🚨": "⚠🆘❗", "🎨": "🖌🖍🌈", "👤": "👥🙂",
}

EMOJI_RE = re.compile(
    "(?:[\U0001F1E6-\U0001F1FF]{2}"
    "|[←-⇿⌀-⏿①-➿⬀-⯿\U0001F000-\U0001FAFF])"
    "️?(?:‍[☀-➿\U0001F000-\U0001FAFF]️?)*")
# Код и моноширинные блоки не трогаем: там иконке не место
_SKIP_RE = re.compile(r"(<pre>.*?</pre>|<code>.*?</code>|<[^>]+>)", re.S)

_state: dict = {}


def norm(emoji: str) -> str:
    return emoji.replace("️", "")


def load() -> None:
    global _state
    _state = store.load(store.ICONS)


def active() -> bool:
    return bool(_state.get("on") and _state.get("map"))


def pack() -> str:
    return str(_state.get("pack") or "")


def mapping() -> dict[str, str]:
    return dict(_state.get("map") or {})


def save(pack_name: str, icons: dict[str, str], on: bool) -> None:
    global _state
    _state = {"on": on, "pack": pack_name, "map": icons}
    store.save(store.ICONS, _state)


def disable(why: str = "") -> None:
    """Выключить, набор оставить: включить снова можно после проверки."""
    if _state.get("on"):
        log.warning("Иконки выключены: %s", why or "по запросу")
        save(pack(), mapping(), False)


def icon(emoji: str) -> str | None:
    """id иконки для эмодзи — только когда иконки включены."""
    key = norm(emoji)
    return _state["map"].get(key) if active() and key not in KEEP else None


def emoji_of(icon_id: str) -> str:
    return next((e for e, i in mapping().items() if i == icon_id), "")


def lead(text: str) -> tuple[str, str]:
    """Эмодзи в начале подписи и остальной текст."""
    m = EMOJI_RE.match(text)
    return (m.group(0), text[m.end():].lstrip()) if m else ("", text)


def decorate(text: str) -> str:
    """Эмодзи текста → <tg-emoji>; обычное эмодзи остаётся внутри тега —
    его Telegram покажет, если иконка недоступна."""
    if not active():
        return text

    def sub(m: re.Match) -> str:
        e = m.group(0)
        i = icon(e)
        return f'<tg-emoji emoji-id="{i}">{e}</tg-emoji>' if i else e

    parts = _SKIP_RE.split(text)
    return "".join(p if k % 2 else EMOJI_RE.sub(sub, p) for k, p in enumerate(parts))


def from_pack(stickers: list) -> dict[str, str]:
    """Набор custom emoji → {эмодзи: id} по эмодзи, привязанным к иконкам;
    эмодзи бота без точного совпадения — по похожим (SIMILAR), не отдавая
    одну иконку двум значкам."""
    out: dict[str, str] = {}
    for s in stickers:
        key = norm(getattr(s, "emoji", "") or "")
        if key and key not in KEEP and getattr(s, "custom_emoji_id", None) and key not in out:
            out[key] = s.custom_emoji_id
    used = {out[k] for k in TEMPLATE if k in out}
    for key in TEMPLATE:
        if key in out:
            continue
        for alt in EMOJI_RE.findall(SIMILAR.get(key, "")):
            i = out.get(norm(alt))
            if i and i not in used:
                out[key] = i
                used.add(i)
                break
    return out


def coverage(icons: dict[str, str]) -> tuple[list[str], list[str]]:
    """Эмодзи бота с иконками и без."""
    return [e for e in TEMPLATE if e in icons], [e for e in TEMPLATE if e not in icons]


def from_message(text: str, entities: list) -> dict[str, str]:
    """Иконки, присланные по порядку TEMPLATE. Обычное эмодзи на месте
    иконки — «оставить как есть»."""
    starts = {e.offset: e.custom_emoji_id for e in entities or [] if e.type == "custom_emoji"}
    out: dict[str, str] = {}
    pos16, last = 0, 0
    tokens = []
    for m in EMOJI_RE.finditer(text):
        pos16 += len(text[last:m.start()].encode("utf-16-le")) // 2
        tokens.append(starts.get(pos16))
        pos16 += len(m.group(0).encode("utf-16-le")) // 2
        last = m.end()
    for key, icon_id in zip(TEMPLATE, tokens):
        if icon_id:
            out[key] = icon_id
    return out


def _has_icons(markup: object) -> bool:
    return isinstance(markup, InlineKeyboardMarkup) and any(
        b.icon_custom_emoji_id for row in markup.inline_keyboard for b in row)


def plain_markup(markup: object) -> object:
    """Клавиатура без иконок: эмодзи возвращается в подпись."""
    if not _has_icons(markup):
        return markup
    return InlineKeyboardMarkup(inline_keyboard=[
        [b.model_copy(update={"text": f"{emoji_of(b.icon_custom_emoji_id)} {b.text}".strip(),
                              "icon_custom_emoji_id": None}) if b.icon_custom_emoji_id else b for b in row]
        for row in markup.inline_keyboard])  # type: ignore[union-attr]


class Middleware(BaseRequestMiddleware):
    """Иконки в тексте каждого сообщения бота. Telegram отклонил сообщение с
    иконками — повтор без них и выключение; принял, но иконки срезал (нет
    Premium у владельца) — выключение: следующие экраны будут с эмодзи."""

    async def __call__(self, make_request, bot, method):  # type: ignore[no-untyped-def]
        if type(method).__name__ not in ("SendMessage", "EditMessageText") or not active():
            return await make_request(bot, method)
        plain = method.text
        method.text = decorate(plain)
        markup = getattr(method, "reply_markup", None)
        in_text, on_buttons = method.text != plain, _has_icons(markup)
        if not (in_text or on_buttons):
            return await make_request(bot, method)
        try:
            result = await make_request(bot, method)
        except TelegramBadRequest as e:
            if "not modified" in str(e):
                raise
            # Повтор без иконок; не прошёл и он — дело не в иконках (ошибка
            # уходит дальше, иконки остаются включёнными)
            method.text, method.reply_markup = plain, plain_markup(markup)
            result = await make_request(bot, method)
            disable(f"Telegram отклонил сообщение с иконками: {e}")
            return result
        # Судим по тексту: сущности custom_emoji в ответе есть всегда, когда
        # Telegram их принял; кнопки — только если в тексте иконок не было
        if isinstance(result, Message):
            shown = (any(e.type == "custom_emoji" for e in result.entities or []) if in_text
                     else _has_icons(result.reply_markup))
            if not shown:
                disable("Telegram не показал иконки — у владельца бота нет Telegram Premium?")
        return result


load()
