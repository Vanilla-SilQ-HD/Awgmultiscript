"""
test_bot.py — сквозная проверка Telegram-бота без Telegram и без root.

Обработчики aiogram получают настоящие апдейты (dp.feed_update), бот зовёт
настоящий `awg2 api` собранного awg2 в песочнице (sandbox.py), а сеть
Telegram подменена сессией, которая записывает вызовы Bot API.

Запуск:  python3 tests/test_bot.py [путь/к/dist/awg2.sh]
         (нужен aiogram: pip install -r awg_bot/requirements.txt)
"""
import asyncio
import datetime
import hashlib
import hmac
import itertools
import json
import logging
import os
import socket
import sys
import time
from urllib.parse import urlencode

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sandbox import *  # noqa: E402,F401,F403

try:
    import aiogram  # noqa: F401
except ImportError:
    print("aiogram не установлен — тест бота пропущен (pip install -r awg_bot/requirements.txt)")
    sys.exit(0)

import aiohttp  # noqa: E402
from aiogram.client.session.base import BaseSession  # noqa: E402
from aiogram.exceptions import TelegramBadRequest  # noqa: E402
from aiogram.types import (CallbackQuery, Chat, ChatMemberLeft, ChatMemberMember, ChatMemberUpdated,  # noqa: E402
                           InlineKeyboardMarkup, Message, MessageEntity, Sticker, StickerSet, Update, User)

# Как Telegram обходится с иконками (custom emoji) от бота: ok — показывает
# (Premium у владельца), strip — молча срезает, reject — отклоняет запрос
PREMIUM = {"mode": "strip"}
# Telegram не принимает адрес Mini App (например, IP вместо домена)
WEBAPP_REJECT = [False]
PACK = {"🖥": "111", "👥": "222", "🌐": "333", "🗑": "444", "⭐": "555", "💿": "666", "🟢": "777"}

# ── Окружение бота ────────────────────────────────────────
API = api_wrapper()
STATE = os.path.join(TMP, "botstate")
os.makedirs(STATE)
BOT_CONF = os.path.join(TMP, "awg-bot.conf")
with open(BOT_CONF, "w") as f:
    f.write("BOT_TOKEN=123456:" + "A" * 35 + "\nADMIN_ID=111\n")
os.environ.update(ENV)
os.environ.update(AWG2_BIN=API, AWG_BOT_STATE=STATE, AWG_ADMINS_FILE=os.path.join(STATE, "admins.json"),
                  AWG_BOT_CONF=BOT_CONF, AWG_CERT_FULL=os.path.join(ROOT, "etc/awg2/cert/fullchain.pem"),
                  AWG_CERT_KEY=os.path.join(ROOT, "etc/awg2/cert/key.pem"))
sys.path.insert(0, os.path.join(HERE, "..", "awg_bot"))

from awgbot import admins, bot as botmod, jobs, store, ui, webapp  # noqa: E402

USER_NAMED = ("cl:v:", "tc:t:", "ex:pick:", "xr:delok:", "wo:v:", "adm:rm:", "diag:sn:", "mod:tag:")

logging.getLogger("aiogram").setLevel(logging.WARNING)

jobs.POLL, jobs.EDIT_EVERY = 0.2, 0.0

os.makedirs(os.path.join(ROOT, "etc/amnezia/amneziawg"), exist_ok=True)
os.makedirs(os.path.join(ROOT, "root"), exist_ok=True)
with open(os.path.join(ROOT, "etc/amnezia/amneziawg/awg0.conf"), "w") as f:
    f.write(OLD20)
for n in ("alice", "bob"):
    with open(os.path.join(ROOT, "root", n + "_awg2.conf"), "w") as f:
        f.write("[Interface]\nPrivateKey = X\nAddress = 10.23.45.2/32\n")


# AWG_DUMP_KB=файл — все экраны с раскладкой кнопок, для глаз
DUMP = open(os.environ["AWG_DUMP_KB"], "w") if os.environ.get("AWG_DUMP_KB") else None


class FakeSession(BaseSession):
    """Bot API без сети: запоминает вызовы, ведёт «чат» (какие сообщения
    бота живы и с кнопками ли они) и отвечает правдоподобно."""

    def __init__(self):
        super().__init__()
        self.sent = []
        self.chat = {}          # id сообщения бота → "screen" | "text" | "file"
        self.text = {}          # id сообщения бота → его текущий текст
        self.deleted = set()

    async def make_request(self, bot, method, timeout=None):
        name = type(method).__name__
        self.sent.append((name, method))
        if DUMP and name in ("SendMessage", "EditMessageText") and method.reply_markup:
            DUMP.write("\n" + "═" * 60 + "\n" + (method.text or "")[:300] + "\n")
            for row in method.reply_markup.inline_keyboard:
                DUMP.write("  " + " | ".join(f"[{b.text}]" for b in row) + "\n")
        if name == "GetMe":
            return User(id=999, is_bot=True, first_name="Bot", username="testbot").as_(bot)
        if name == "DeleteMessage":
            self.deleted.add(method.message_id)
            self.chat.pop(method.message_id, None)
            return True
        if name == "SetChatMenuButton" and WEBAPP_REJECT[0] and method.menu_button.type == "web_app":
            raise TelegramBadRequest(method=method, message="Bad Request: BUTTON_URL_INVALID")
        if name == "GetStickerSet":
            return StickerSet(name=method.name, title="Icons", sticker_type="custom_emoji", stickers=[
                Sticker(file_id=f"f{i}", file_unique_id=f"u{i}", type="custom_emoji", width=100, height=100,
                        is_animated=False, is_video=False, emoji=e, custom_emoji_id=i) for e, i in PACK.items()])
        if name == "EditMessageReplyMarkup":
            if method.message_id in self.chat and not method.reply_markup:
                self.chat[method.message_id] = "text"
            return True
        if name in ("SendMessage", "EditMessageText", "SendDocument", "SendPhoto"):
            markup = getattr(method, "reply_markup", None)
            icons_in = "<tg-emoji" in (getattr(method, "text", None) or "") or (
                isinstance(markup, InlineKeyboardMarkup)
                and any(b.icon_custom_emoji_id for row in markup.inline_keyboard for b in row))
            if WEBAPP_REJECT[0] and isinstance(markup, InlineKeyboardMarkup) and any(
                    b.web_app for row in markup.inline_keyboard for b in row):
                raise TelegramBadRequest(method=method, message="Bad Request: BUTTON_URL_INVALID")
            if icons_in and PREMIUM["mode"] == "reject":
                raise TelegramBadRequest(method=method, message="Bad Request: custom emoji not allowed")
            entities, echo = None, markup
            if icons_in and PREMIUM["mode"] == "ok":
                entities = [MessageEntity(type="custom_emoji", offset=0, length=2, custom_emoji_id="111")]
            elif icons_in and isinstance(markup, InlineKeyboardMarkup):
                echo = InlineKeyboardMarkup(inline_keyboard=[
                    [b.model_copy(update={"icon_custom_emoji_id": None}) for b in row] for row in markup.inline_keyboard])
            # В личном чате номера сообщений общие для обеих сторон
            mid = getattr(method, "message_id", None) or next(MSG_IDS)
            if method.chat_id == OWNER.id:
                self.chat[mid] = ("file" if name in ("SendDocument", "SendPhoto")
                                  else "screen" if method.reply_markup else "text")
                self.text[mid] = getattr(method, "text", None) or getattr(method, "caption", None) or ""
            return Message(message_id=mid, date=datetime.datetime.now(), chat=Chat(id=method.chat_id, type="private"),
                           text=getattr(method, "text", None), entities=entities,
                           reply_markup=echo if isinstance(echo, InlineKeyboardMarkup) else None).as_(bot)
        return True

    def texts(self):
        """Живые текстовые сообщения бота у владельца (без файлов)."""
        return [m for m, kind in self.chat.items() if kind != "file"]

    def screen_id(self):
        screens = [m for m, kind in self.chat.items() if kind == "screen"]
        return max(screens) if screens else 0

    async def stream_content(self, *args, **kwargs):
        raise NotImplementedError
        yield b""                                               # pragma: no cover

    async def close(self):
        pass


MSG_IDS = itertools.count(1)
SESSION = FakeSession()
BOT, DP = botmod.build(SESSION)
OWNER = User(id=111, is_bot=False, first_name="Owner", username="owner")
STRANGER = User(id=222, is_bot=False, first_name="Stranger")
seq = itertools.count(1)


def _msg(user, text, entities=None):
    return Message(message_id=next(MSG_IDS), date=datetime.datetime.now(), chat=Chat(id=user.id, type="private"),
                   from_user=user, text=text, entities=entities)


LAST_SAID = [0]


async def say(text, user=OWNER, entities=None):
    mark = len(SESSION.sent)
    msg = _msg(user, text, entities)
    LAST_SAID[0] = msg.message_id
    await DP.feed_update(BOT, Update(update_id=next(seq), message=msg))
    return SESSION.sent[mark:]


def no_hourglass(label):
    """Ни одно сообщение бота не осталось висеть на «⏳ …»."""
    stuck = [SESSION.text[m] for m in SESSION.texts() if SESSION.text.get(m, "").startswith("⏳")]
    chk(f"{label}: нет повисших «⏳»", not stuck, stuck)


async def press(data, user=OWNER):
    """Нажатие кнопки на текущем экране (как в настоящем чате)."""
    mark = len(SESSION.sent)
    msg = _msg(user, "экран")
    if user is OWNER and SESSION.screen_id():
        msg = Message(message_id=SESSION.screen_id(), date=datetime.datetime.now(),
                      chat=Chat(id=user.id, type="private"), text="экран")
    cb = CallbackQuery(id=str(next(seq)), from_user=user, chat_instance="ci", data=data, message=msg)
    await DP.feed_update(BOT, Update(update_id=next(seq), callback_query=cb))
    return SESSION.sent[mark:]


def screen(sent):
    """Последний показанный экран: текст и кнопки (текст, данные)."""
    for name, m in reversed(sent):
        if name in ("SendMessage", "EditMessageText"):
            rows = m.reply_markup.inline_keyboard if m.reply_markup else []
            return m.text or "", [(b.text, b.callback_data or b.url or ("webapp:" + b.web_app.url if b.web_app else None))
                                  for row in rows for b in row]
    return "", []


def keyboard(sent):
    """Строки кнопок последнего экрана."""
    for name, m in reversed(sent):
        if name in ("SendMessage", "EditMessageText"):
            return m.reply_markup.inline_keyboard if m.reply_markup else []
    return []


def alerts(sent):
    return [m.text or "" for name, m in sent if name == "AnswerCallbackQuery"]


def docs(sent):
    return [m for name, m in sent if name == "SendDocument"]


async def wait_jobs(timeout=60):
    for _ in range(int(timeout / 0.1)):
        if not jobs._tasks:
            return True
        await asyncio.sleep(0.1)
    return False


async def run():
    print("Доступ")
    text, _ = screen(await say("/start", STRANGER))
    chk("чужой видит отказ и свой ID", "Доступ запрещён" in text and "222" in text, text)
    chk("чужое нажатие отклонено", "⛔️ Нет доступа" in alerts(await press("cl", STRANGER)))
    for text in ("/startfoo", "/start@otherbot", "/startinv_x"):
        sent = await say(text, STRANGER)
        shown = screen(sent)[0]
        chk(f"чужому «{text}» — не меню со сводкой сервера", "AWG Toolza" not in shown and not keyboard(sent),
            [n for n, _ in sent])

    group = Chat(id=-1001234, type="supergroup", title="Группа")
    mark = len(SESSION.sent)
    await DP.feed_update(BOT, Update(update_id=next(seq), message=Message(
        message_id=next(MSG_IDS), date=datetime.datetime.now(), chat=group, from_user=OWNER, text="/start")))
    chk("в группе бот молчит даже владельцу", not [n for n, _ in SESSION.sent[mark:]], SESSION.sent[mark:])
    mark = len(SESSION.sent)
    gmsg = Message(message_id=next(MSG_IDS), date=datetime.datetime.now(), chat=group, text="экран")
    await DP.feed_update(BOT, Update(update_id=next(seq), callback_query=CallbackQuery(
        id=str(next(seq)), from_user=OWNER, chat_instance="g", data="cl", message=gmsg)))
    chk("кнопка в группе — отказ, экран не показан",
        alerts(SESSION.sent[mark:]) == ["Бот работает только в личных сообщениях"]
        and not screen(SESSION.sent[mark:])[0], SESSION.sent[mark:])
    mark = len(SESSION.sent)
    now = datetime.datetime.now()
    await DP.feed_update(BOT, Update(update_id=next(seq), my_chat_member=ChatMemberUpdated(
        chat=group, from_user=STRANGER, date=now,
        old_chat_member=ChatMemberLeft(user=User(id=999, is_bot=True, first_name="Bot")),
        new_chat_member=ChatMemberMember(user=User(id=999, is_bot=True, first_name="Bot")))))
    left = [m for n, m in SESSION.sent[mark:] if n == "LeaveChat"]
    chk("бота добавили в группу — сам выходит", len(left) == 1 and left[0].chat_id == group.id, SESSION.sent[mark:])
    chk("выход из групп включён в получаемые апдейты", "my_chat_member" in DP.resolve_used_update_types())

    print("Главное меню")
    text, buttons = screen(await say("/start"))
    chk("сводка сервера", "AWG Toolza" in text and "AWG 2.0" in text and "2 клиента · 0 онлайн" in text, text)
    chk("шапка блоками", text.count("<blockquote>") >= 3 and "<b>vm" not in text.split("<blockquote>")[0], text)
    datas = [d for _, d in buttons]
    chk("девять пунктов меню в порядке awg2",
        datas[:9] == ["srv", "cl", "diag", "bk", "tun", "botm", "del", "upd", "wo"], buttons)
    rows = keyboard(SESSION.sent)
    chk("главное меню — два столбца", [len(r) for r in rows] == [2, 2, 2, 2, 2, 1], [[b.text for b in r] for r in rows])
    chk("в самом низу — «Поддержать 💚» во всю ширину, ссылкой",
        rows[-1][0].text == "Поддержать 💚" and rows[-1][0].url == "https://t.me/awgToolza/156/157"
        and rows[-1][0].callback_data is None, rows[-1])
    menu_id = SESSION.screen_id()
    sent = await say("/start")
    chk("повторный /start — всегда новое меню внизу, старое не трогается",
        any(n == "SendMessage" for n, _ in sent) and SESSION.screen_id() > menu_id
        and not any(n in ("DeleteMessage", "EditMessageText") for n, _ in sent), [n for n, _ in sent])
    text, _ = screen(await say("что-нибудь"))
    chk("любой текст вне ввода — меню", "AWG Toolza" in text, text)
    chk("устаревшая кнопка", any("устарела" in a for a in alerts(await press("zzz:1"))))

    print("Клиенты")
    text, buttons = screen(await press("cl"))
    chk("список клиентов", "Клиенты: 2" in text and ("cl:v:alice" in [d for _, d in buttons]), [text, buttons])
    now = int(time.time())
    with open(AWG_DUMP, "w") as f:
        f.write(f"PRIV\tPUB\t51820\toff\nPUBALICE=\t(none)\t(none)\t10.23.45.2/32\t{now - 3600}\t0\t0\toff\n"
                f"PUBBOB=\t(none)\t1.2.3.4:5555\t10.23.45.3/32\t{now - 30}\t100\t200\toff\n")
    text, buttons = screen(await press("cl:sort:activity"))
    order = [d.split(":")[2] for _, d in buttons if d.startswith("cl:v:")]
    chk("сортировка по активности: онлайн первым, с давностью",
        order == ["bob", "alice"] and "по активности" in text and any(t.startswith("🟢 bob · ") for t, _ in buttons),
        [text, buttons])
    text, buttons = screen(await press("cl:sort:name"))
    order = [d.split(":")[2] for _, d in buttons if d.startswith("cl:v:")]
    chk("сортировка по имени", order == ["alice", "bob"] and "по имени" in text
        and ("🔃 По активности", "cl:sort:activity") in buttons, [text, buttons])
    chk("сортировка запоминается", store.setting("clients_sort") == "name", store.setting("clients_sort"))
    os.remove(AWG_DUMP)
    text, buttons = screen(await press("cl:v:alice"))
    chk("карточка", "alice" in text and "10.23.45.2" in text and ("cl:conf:alice" in [d for _, d in buttons]), text)

    await press("cl:add")
    text, buttons = screen(await say("bad name!"))
    chk("неверное имя — повторный вопрос", "латиница" in text, text)
    text, buttons = screen(await say("carol"))
    chk("после имени — срок", "Срок действия" in text and "cl:ne:+1d" in [d for _, d in buttons], [text, buttons])
    text, buttons = screen(await press("cl:ne:+1d"))
    chk("профиль pro — выбор мимикрии", "cl:nm:none" in [d for _, d in buttons], [text, buttons])
    sent = await press("cl:nm:none")
    d = docs(sent)
    chk("конфиг нового клиента файлом", d and d[0].document.filename == "carol_awg2.conf", [n for n, _ in sent])
    chk("и QR", any(n == "SendPhoto" for n, _ in sent))
    text, _ = screen(sent)
    chk("карточка нового клиента со сроком", "carol" in text and "через" in text, text)
    no_hourglass("добавление клиента")
    chk("«⏳» становится карточкой, файлы — под ней, лишних экранов нет",
        not any(n == "SendMessage" for n, _ in sent) and SESSION.screen_id() < max(SESSION.chat),
        [n for n, _ in sent])
    card_id = SESSION.screen_id()
    sent = await press("cl:conf:carol")
    chk("«Конфиг и QR» — только файлы, карточка остаётся на месте",
        docs(sent) and not any(n in ("SendMessage", "EditMessageText", "DeleteMessage") for n, _ in sent)
        and SESSION.screen_id() == card_id, [n for n, _ in sent])


    await press("cl:note:carol")
    await say("домашний роутер")
    chk("ответ на вопрос остаётся в чате", LAST_SAID[0] not in SESSION.deleted)
    await press("cl:mon:carol")
    chk("заметка и мониторинг", store.note("carol") == "домашний роутер #ping" and store.monitored("carol"),
        store.notes())
    await press("cl:ren:carol")
    text, _ = screen(await say("dave"))
    chk("переименование переносит заметку", "dave" in text and store.note("dave").startswith("домашний"), text)
    text, _ = screen(await press("cl:ex:dave|none"))
    chk("снять срок", "бессрочно" in text, text)
    await press("cl:delok:dave")
    chk("удаление клиента и его заметки", not os.path.exists(os.path.join(ROOT, "root", "dave_awg2.conf"))
        and store.note("dave") == "")

    text, buttons = screen(await press("cl:bulk"))
    chk("массовое создание: выбор — префикс и количество или имена",
        [d for _, d in buttons][:2] == ["cl:bpre", "cl:bnames"], buttons)
    await press("cl:bpre")
    text, buttons = screen(await say("u"))
    chk("после префикса — количество кнопками", "cl:bn:10" in [d for _, d in buttons]
        and "cl:bn:ask" in [d for _, d in buttons], buttons)
    await press("cl:bn:2")
    sent = await press("cl:be:none")
    d = docs(sent)
    chk("несколько клиентов — zip", d and d[0].document.filename == "awg_clients.zip" and len(d[0].document.data) > 100,
        [n for n, _ in sent])
    text, buttons = screen(sent)
    chk("итог массового создания — на месте «⏳», архив под ним",
        "Создано клиентов: 2" in text and "u-001" in text and ("👥 Клиенты", "cl") in buttons
        and SESSION.screen_id() < max(SESSION.chat), [text, buttons])
    no_hourglass("массовое создание")

    await press("cl:bnames")
    await say("e1,e2")
    await press("cl:be:date")
    sent = await say("2099-01-01 10:00")
    text, _ = screen(sent)
    chk("срок датой: итог ответом на дату, архив под ним",
        "Создано клиентов: 2" in text and docs(sent)
        and [n for n, _ in sent if n in ("SendMessage", "SendDocument")] == ["SendMessage", "SendDocument"],
        [n for n, _ in sent])
    no_hourglass("массовое создание со сроком-датой")
    await press("cl:bnames")
    await say("x1, x2, x3")
    sent = await press("cl:be:none")
    chk("имена через запятую — все созданы", "Создано клиентов: 3" in screen(sent)[0]
        and "Конфиги: 3" in (docs(sent)[0].caption if docs(sent) else ""), [n for n, _ in sent])
    await press("cl:bpre")
    await say("p")
    await press("cl:bn:ask")
    await say("25")
    await press("cl:be:none")
    text, buttons = screen(await press("cl:dsel"))
    chk("удаление нескольких: экран выбора", "Никто не отмечен" in text and "cl:ds:0|e1" in [d for _, d in buttons],
        [text, buttons[:4]])
    await press("cl:ds:0|e1")
    text, buttons = screen(await press("cl:ds:0|e2"))
    chk("отмечено двое", "Отмечено: 2" in text and ("🗑 e1", "cl:ds:0|e1") in buttons
        and ("🗑 Удалить: 2", "cl:dsgo") in buttons, [text, buttons])
    text, buttons = screen(await press("cl:ds:0|e2"))
    chk("повторное нажатие снимает отметку", "Отмечено: 1" in text and ("⬜️ e2", "cl:ds:0|e2") in buttons, text)
    await press("cl:ds:0|e2")
    text, _ = screen(await press("cl:dsgo"))
    chk("подтверждение со списком", "Удалить клиентов: <b>2</b>" in text and "e1, e2" in text, text)
    text, buttons = screen(await press("cl:dsok"))
    chk("удалены оба, конфиги тоже", "Удалено клиентов: 2" in text
        and not os.path.exists(os.path.join(ROOT, "root", "e1_awg2.conf"))
        and not os.path.exists(os.path.join(ROOT, "root", "e2_awg2.conf")), text)
    no_hourglass("удаление нескольких")
    text, buttons = screen(await press("tc::warp"))
    datas = [d for _, d in buttons]
    chk("длинный список клиентов туннеля — по страницам", "tc:pg:warp|1" in datas and len(buttons) <= 25, len(buttons))
    text, buttons = screen(await press("tc:pg:warp|1"))
    first = next(d for _, d in buttons if d.startswith("tc:t:"))
    text, buttons = screen(await press(first))
    chk("переключение клиента не сбрасывает страницу", "tc:pg:warp|0" in [d for _, d in buttons], buttons[:3])

    print("Сервер и туннели")
    text, buttons = screen(await press("srv"))
    chk("экран сервера", "AWG 2.0" in text and "srv:proto" in [d for _, d in buttons], text)
    text, buttons = screen(await press("srv:create"))
    chk("мастер создания начинается с региона", "srv:w:region=ru" in [d for _, d in buttons], buttons)
    for step in ("region=ru", "profile=lite", "mimicry=none", "proto=2.0", "dns=0"):
        await press(f"srv:w:{step}")
    text, buttons = screen(await press("srv:w:mtu=1280"))
    chk("мастер: подсеть — случайная или вручную", "Подсеть" in text and "srv:w:net=ask" in [d for _, d in buttons],
        [text, buttons])
    await press("srv:w:net=ask")
    text, _ = screen(await say("10.66.1.7/25"))
    chk("мастер: не /24 — повторный вопрос", "сеть /24" in text, text)
    text, buttons = screen(await say("10.66.1.7/24"))
    chk("мастер: после подсети — порт", "UDP-порт" in text, text)
    await press("srv:w:port=")
    text, _ = screen(await press("srv:w:endpoint="))
    chk("мастер: итог с подсетью", "Подсеть: 10.66.1.0/24" in text, text)
    long_domain = "a" * 60 + ".example.com"
    await press("srv:epdom")
    text, buttons = screen(await say(long_domain))
    chk("длинный домен endpoint не ломает кнопки", "srv:epgo:keep" in [d for _, d in buttons], [text, buttons])
    text, _ = screen(await press("srv:epgo:keep"))
    chk("endpoint применён", "✅" in text and long_domain in text, text)

    SRV_CONF = os.path.join(ROOT, "etc/amnezia/amneziawg/awg0.conf")
    text, buttons = screen(await press("srv"))
    chk("кнопка «Параметры AWG» на экране сервера", "srv:par" in [d for _, d in buttons], buttons)
    text, buttons = screen(await press("srv:par"))
    datas = [d for _, d in buttons]
    chk("параметры: значения и кнопки ключей", "Jc" in text and "= 5" in text and "srv:pk:Jc" in datas
        and "srv:pk:H4" in datas and "srv:pk:RandomTrailers" not in datas and "srv:pgo" not in datas, [text, datas])
    text, _ = screen(await press("srv:pk:Jc"))
    chk("параметры: подсказка и текущее значение", "0-128" in text and "Сейчас: <code>5</code>" in text
        or "Сейчас: 5" in text, text)
    text, _ = screen(await say("много"))
    chk("параметры: не число — повторный вопрос", "Нужно число" in text, text)
    text, buttons = screen(await say("7"))
    chk("параметры: правка помечена, можно применить", "✎ Jc" in text and "srv:pgo" in [d for _, d in buttons], [text, buttons])
    await press("srv:pk:S2")
    text, buttons = screen(await say("96"))
    chk("параметры: ошибка видна сразу, применить нельзя", "❌" in text and "S1 и S2" in text
        and "srv:pgo" not in [d for _, d in buttons], [text, buttons])
    await press("srv:pk:S2")
    await say("61")
    text, buttons = screen(await press("srv:pgo"))
    chk("параметры: подтверждение с предупреждением про клиентов", "Меняются: Jc, S2" in text
        and "обязаны совпадать" in text and "srv:pok" in [d for _, d in buttons], [text, buttons])
    text, buttons = screen(await press("srv:pok"))
    conf_now = open(SRV_CONF).read()
    chk("параметры записаны", "✅" in text and "\nJc = 7\n" in conf_now and "\nS2 = 61\n" in conf_now
        and "cl:export" in [d for _, d in buttons], [text, buttons])
    text, buttons = screen(await press("srv:par"))
    chk("после записи правки сброшены", "✎" not in text and "= 7" in text, text)
    text, buttons = screen(await press("tun"))
    chk("экран туннелей", "warp" in [d for _, d in buttons] and "tun:panic" in [d for _, d in buttons], buttons)

    await press("cas:add")
    await press("cas:p:udp")
    await say("5555")
    await say("5.6.7.8")
    await press("cas:out:5555")
    text, _ = screen(await press("cas:save"))
    chk("мастер каскада добавляет правило", "✅" in text, text)
    text, _ = screen(await press("cas"))
    chk("правило в списке", "UDP 5555 → 5.6.7.8:5555" in text, text)
    no_hourglass("мастер каскада")

    print("Маршрут клиента")
    with open(LINKS, "a") as f:
        f.write("warp0\n")
    text, _ = screen(await press("cl:v:alice"))
    chk("маршрут через работающий WARP", "Маршрут: через WARP" in text, text)
    # WARP выключили, работают exit-ноды в режиме «все клиенты»
    awg_dir = os.path.join(ROOT, "etc/amnezia/amneziawg")
    with open(os.path.join(awg_dir, "awg-exit-n1.conf"), "w") as f:
        f.write("[Interface]\nPrivateKey = X\nTable = off\n\n[Peer]\nEndpoint = 1.2.3.4:51820\n")
    with open(os.path.join(awg_dir, "exits_state"), "w") as f:
        f.write("active\nmode=all\nbalancer=single\nsingle_exit=n1\n")
    with open(LINKS, "w") as f:
        f.write("awg-exit-n1\n")
    with open(ACTIVE, "w") as f:
        f.write("awg-exits-routing.service\n")
    text, _ = screen(await press("cl:v:alice"))
    chk("WARP выключен — в карточке его нет, маршрут через exit-ноды",
        "exit-ноды, общий выход" in text and "WARP" not in text, text)
    text, buttons = screen(await press("cl:tun:alice"))
    labels = [t for t, _ in buttons]
    chk("экран маршрута: выходы exit-нод без WARP",
        "🔘 Общий выход" in labels and "⚪️ Нода n1" in labels and not any("WARP" in t for t in labels), labels)
    text, buttons = screen(await press("cl:rt:exits|alice|n1"))
    chk("клиент переведён на ноду n1", "🔘 Нода n1" in [t for t, _ in buttons], [t for t, _ in buttons])
    text, _ = screen(await press("cl:v:alice"))
    chk("карточка показывает ноду", "Маршрут: exit-нода n1" in text, text)
    text, buttons = screen(await press("ex:cl"))
    chk("exit-ноды → клиенты: у alice нода, у bob общий выход",
        any(t == "alice → n1" for t, _ in buttons) and any(t == "bob → общий" for t, _ in buttons),
        [t for t, _ in buttons][:4])

    print("Прокси и перезапуск бота")
    with open(os.path.join(ROOT, "bot.conf"), "w") as f:
        f.write("BOT_TOKEN=1:A\nADMIN_ID=111\n")
    with open(ACTIVE, "a") as f:
        f.write("awg-bot.service\n")
    await press("botm:penter")
    text, _ = screen(await say("socks5://127.0.0.1:10808"))
    chk("прокси сохраняется без «awg2 ответил не JSON»", "Бот перезапускается" in text, text)
    chk("адрес прокси без пароля остаётся в чате", LAST_SAID[0] not in SESSION.deleted)

    with open(os.path.join(ROOT, "bot.conf")) as f:
        chk("BOT_PROXY записан", "BOT_PROXY=socks5://127.0.0.1:10808" in f.read())
    notice_msg = store.load(store.NOTICE).get("msg")
    chk("экран «перезапускаюсь» запомнен", notice_msg == max(SESSION.chat), store.load(store.NOTICE))
    mark = len(SESSION.sent)
    await botmod.restore(BOT)
    fixed = [m for n, m in SESSION.sent[mark:] if n == "EditMessageText" and m.message_id == notice_msg]
    chk("после перезапуска экран поправлен: бот на связи и каким путём",
        fixed and "Бот снова на связи" in fixed[0].text and "Telegram —" in fixed[0].text,
        fixed[0].text if fixed else [n for n, _ in SESSION.sent[mark:]])
    text, _ = screen(await press("botm:restart"))
    chk("перезапуск из меню — сразу, без ошибки", "Бот перезапускается" in text, text)
    await botmod.restore(BOT)
    chk("до сих пор бот ничего не удалял", not SESSION.deleted, SESSION.deleted)
    await press("botm:penter")
    await say("socks5://user:secret@127.0.0.1:10808")
    chk("адрес прокси с паролем удалён — единственное, что бот удаляет", SESSION.deleted == {LAST_SAID[0]},
        SESSION.deleted)
    await botmod.restore(BOT)
    with open(ACTIVE, "w") as f:
        f.write("awg-exits-routing.service\n")

    print("Мониторинг")
    from awgbot import monitor
    store.set_note("ghost", "старый клиент #ping")
    store.set_note("alice", "#ping")
    mark = len(SESSION.sent)
    await monitor.tick(BOT, {}, True)
    chk("заметка удалённого клиента убрана", store.note("ghost") == "", store.notes())
    chk("ни разу не подключавшийся клиент не даёт «офлайн»",
        not any(n == "SendMessage" and "офлайн" in (m.text or "") for n, m in SESSION.sent[mark:]))
    # Пустой список клиентов: сервера нет (сброс, восстановление) — заметки остаются;
    # сервер есть, но клиентов ноль (последнего удалили из меню awg2) — чистятся
    conf_path = os.path.join(ROOT, "etc/amnezia/amneziawg/awg0.conf")
    with open(conf_path) as f:
        saved_conf = f.read()
    store.set_note("ghost2", "#ping")
    os.remove(conf_path)
    await monitor.tick(BOT, {}, True)
    chk("без сервера заметки не трогаются", store.note("ghost2") == "#ping" and store.note("alice") == "#ping",
        store.notes())
    with open(conf_path, "w") as f:
        f.write(saved_conf[:saved_conf.index("[Peer]")])
    await monitor.tick(BOT, {}, True)
    chk("сервер без клиентов — заметки удалённых убраны", store.note("ghost2") == "" and store.note("alice") == "",
        store.notes())
    with open(conf_path, "w") as f:
        f.write(saved_conf)
    store.set_note("alice", "#ping")

    print("Все экраны")
    screens = ["srv", "mod", "srv:proto", "srv:par", "srv:ep", "srv:install", "srv:reset", "srv:reboot",
               "cl:activity", "cl:exp:alice", "cl:mim:alice", "cl:tun:alice", "cl:ren:alice",
               "diag", "diag:status", "diag:dpi", "diag:logs", "diag:log:manager", "diag:sniff",
               "bk", "bk:list", "tun", "tc::warp", "warp", "warp:backend", "xr", "t2s", "ex", "cas", "dns",
               "botm", "botm:proxy", "adm", "del", "del:all", "upd", "wo", "wo:install"]
    broken = []
    for data in screens:
        sent = await press(data)
        text, buttons = screen(sent)
        if any("Ошибка" in a for a in alerts(sent)) or not text or not buttons:
            broken.append((data, text[:80]))
    chk(f"все {len(screens)} экранов открываются, у каждого есть кнопки", not broken, broken)
    # Подписи — в половину экрана: иначе Telegram режет их многоточием.
    # Имена клиентов, нод и тегов задаёт пользователь — их не считаем.
    wide = sorted({b.text for name, m in SESSION.sent if name in ("SendMessage", "EditMessageText")
                   and m.reply_markup for row in m.reply_markup.inline_keyboard for b in row
                   if ui.width(b.text) > ui.WIDE and not (b.callback_data or "").startswith(USER_NAMED)})
    chk("все кнопки влезают в два столбца", not wide, wide)
    rows = [len(row) for name, m in SESSION.sent if name in ("SendMessage", "EditMessageText") and m.reply_markup
            for row in m.reply_markup.inline_keyboard]
    chk("в два столбца, не одним списком", rows.count(2) >= rows.count(1), (rows.count(2), rows.count(1)))

    print("Задачи")
    screen_before = SESSION.screen_id()
    sent = await press("bk:create")
    chk("задача идёт в том же экране, без новых сообщений",
        not any(n == "SendMessage" for n, _ in sent)
        and any(n == "EditMessageText" and "Бэкап" in (m.text or "") and m.message_id == screen_before
                for n, m in sent), [n for n, _ in sent])
    chk("задача завершилась", await wait_jobs())
    chk("архив бэкапа отправлен", any(n == "SendDocument" and "Бэкап" in (m.caption or "") for n, m in SESSION.sent))
    last = [m for n, m in SESSION.sent if n in ("SendMessage", "EditMessageText") and "Бэкап" in (m.text or "")][-1]
    chk("итог задачи — в том же сообщении", last.text.startswith("✅") and last.message_id == screen_before,
        last.text[:60])
    no_hourglass("после задачи")
    chk("незавершённых задач не осталось", store.jobs() == {}, store.jobs())

    print("WG + обфускатор")
    os.makedirs(os.path.join(ROOT, "etc/awg-wgobf"), exist_ok=True)
    with open(os.path.join(ROOT, "etc/awg-wgobf/state"), "w") as f:
        f.write("ENDPOINT=203.0.113.10\nPORT=45888\nKEY=obfkey\nMASKING=STUN\nMTU=1380\nDNS=1.1.1.1\n"
                "SERVER_PUB=SRVPUB=\nALLOW_CLEAN=0\n")
    os.makedirs(os.path.join(ROOT, "etc/wireguard"), exist_ok=True)
    with open(os.path.join(ROOT, "etc/wireguard/wgobf0.conf"), "w") as f:
        f.write("[Interface]\nPrivateKey = S\nListenPort = 45888\n\n[Peer]\n# client=clus\nPublicKey = CPUB=\n"
                "AllowedIPs = 10.77.1.2/32\n")
    cdir = os.path.join(ROOT, "root/wgobf/clus")
    os.makedirs(cdir, exist_ok=True)
    with open(os.path.join(cdir, "wg.conf"), "w") as f:
        f.write("[Interface]\nPrivateKey = CPRIV=\nAddress = 10.77.1.2/32\n\n[Peer]\nPresharedKey = PSK=\n")
    text, buttons = screen(await press("wo:v:clus"))
    datas = [d for _, d in buttons]
    chk("карточка клиента: IP и две кнопки выдачи", "10.77.1.2" in text and "wo:bundle:clus" in datas
        and "wo:zip:clus" in datas, [text, buttons])
    sent = await press("wo:bundle:clus")
    msgs = [m.text or "" for n, m in sent if n == "SendMessage"]
    d = docs(sent)
    chk("ссылка phobos:// и конфиг — текстом",
        any("phobos://" in t and "<pre>" in t and "[instance]" in t and "CPRIV=" in t for t in msgs), msgs)
    chk("и один файл .conf со всеми данными",
        len(d) == 1 and d[0].document.filename == "clus.conf" and b"[Interface]" in d[0].document.data
        and b"[instance]" in d[0].document.data and b"key = obfkey" in d[0].document.data,
        [x.document.filename for x in d])
    chk("файлы — после текста", [n for n, _ in sent if n in ("SendMessage", "SendDocument")]
        == ["SendMessage", "SendDocument"], [n for n, _ in sent])
    sent = await press("wo:zip:clus")
    chk("архив для Linux — отдельной кнопкой", docs(sent) and docs(sent)[0].document.filename == "wgobf-clus.zip",
        [n for n, _ in sent])

    text, buttons = screen(await press("wo:install"))
    chk("установка обфускатора: DNS по умолчанию Cloudflare", "DNS клиентов: Cloudflare" in text, text)
    text, buttons = screen(await press("wo:iopt:dns"))
    chk("кнопка DNS перебирает варианты", "DNS клиентов: Google" in text and ("🌐 Google", "wo:iopt:dns") in buttons,
        [text, buttons])

    print("Mini App")
    fake_acme()
    webapp.CONF_PATH = os.path.join(ROOT, "bot.conf")        # тот же файл, что пишет awg2
    ports = []
    for _ in range(2):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            ports.append(s.getsockname()[1])
    with open(os.path.join(ROOT, "bot.conf"), "a") as f:
        f.write(f"WEBAPP_PORT={ports[0]}\n")
    text, buttons = screen(await press("app"))
    chk("экран Mini App: сертификата нет, сервер не запущен",
        "Сертификата нет" in text and "не запущена" in text and ("🔐 На IP", "app:ip") in buttons
        and not any((d or "").startswith("webapp:") for _, d in buttons), [text, buttons])
    await press("app:ip")
    chk("сертификат на IP — задачей", await wait_jobs())
    url = f"https://203.0.113.10:{ports[0]}/"
    chk("после выпуска сервер Mini App поднялся по адресу сертификата",
        webapp.SERVER.running and webapp.SERVER.url == url, [webapp.SERVER.url, webapp.SERVER.error])

    def menus():
        return [(m.chat_id, m.menu_button.type, getattr(getattr(m.menu_button, "web_app", None), "url", None))
                for n, m in SESSION.sent if n == "SetChatMenuButton"]

    chk("кнопка «Меню» у владельца открывает панель", (111, "web_app", url) in menus(), menus())
    mark = len(SESSION.sent)
    await say("/start")
    chk("/start освежает кнопку «Меню» (приглашённым тоже)",
        any(n == "SetChatMenuButton" and m.chat_id == 111 for n, m in SESSION.sent[mark:]))
    mark = len(SESSION.sent)
    await say("/start", STRANGER)
    chk("чужому кнопку «Меню» не трогаем", not any(n == "SetChatMenuButton" for n, _ in SESSION.sent[mark:]))
    text, buttons = screen(await press("app"))
    chk("кнопка «Открыть панель» — Mini App по этому адресу",
        ("📱 Открыть панель", "webapp:" + url) in buttons and "Сертификат: <code>203.0.113.10</code> (IP)" in text,
        [text, buttons])

    token = BOT.token

    def init_data(uid, auth=None, tamper=False, signature=False):
        fields = {"auth_date": str(int(auth or time.time())), "query_id": "AAHd",
                  "user": json.dumps({"id": uid, "first_name": "Max"}, separators=(",", ":"))}
        if signature:
            fields["signature"] = "c2ln"
        secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
        fields["hash"] = hmac.new(secret, "\n".join(f"{k}={v}" for k, v in sorted(fields.items())).encode(),
                                  hashlib.sha256).hexdigest()
        if tamper:
            fields["user"] = fields["user"].replace("Max", "Eve")
        return urlencode(fields)

    chk("подпись initData: верная — пользователь", (webapp.check_init_data(init_data(111), token) or {}).get("id") == 111)
    chk("подпись с полем signature тоже принимается",
        (webapp.check_init_data(init_data(111, signature=True), token) or {}).get("id") == 111)
    chk("подделка, чужой токен и старые данные — отказ",
        webapp.check_init_data(init_data(111, tamper=True), token) is None
        and webapp.check_init_data(init_data(111), "1:other") is None
        and webapp.check_init_data(init_data(111, auth=time.time() - 3 * 86400), token) is None
        and webapp.check_init_data("", token) is None)

    base = f"https://127.0.0.1:{ports[0]}"
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as http:
        async with http.get(base + "/") as r:
            page = await r.text()
        chk("страница Mini App отдаётся по HTTPS", r.status == 200 and "telegram-web-app.js" in page, r.status)

        async def post(path, data=None):
            headers = {"Authorization": "tma " + data} if data is not None else {}
            async with http.post(base + path, headers=headers) as r:
                return r.status, await r.json(content_type=None)

        st, body = await post("/api/me")
        chk("API без подписи Telegram — 401", st == 401, [st, body])
        st, body = await post("/api/me", init_data(111))
        chk("владелец входит", st == 200 and body.get("id") == 111 and body.get("owner") is True, [st, body])
        st, body = await post("/api/me", init_data(222))
        chk("чужой с настоящей подписью — 403", st == 403, [st, body])
        st, body = await post("/api/me", init_data(111, tamper=True))
        chk("подделанные данные — 401", st == 401, [st, body])
        st, body = await post("/api/status", init_data(111))
        chk("сводка сервера через Mini App", st == 200 and body.get("version") and "server" in body, [st, str(body)[:200]])

        # ── API панели ──
        async def api_(path, data, uid=111):
            async with http.post(base + path, json=data, headers={"Authorization": "tma " + init_data(uid)}) as r:
                return r.status, await r.json(content_type=None)

        async with http.get(base + "/app.js") as r:
            chk("скрипт панели отдаётся", r.status == 200 and "runJob" in await r.text(), r.status)
        async with http.get(base + "/icons.js") as r:
            chk("иконки панели отдаются", r.status == 200 and "const ICONS" in await r.text(), r.status)
        async with http.get(base + "/panel.py") as r:
            chk("кроме страницы, скрипта и иконок — ничего", r.status == 404, r.status)
        st, body = await api_("/api/call", {"args": ["status"]})
        chk("панель: общий вызов awg2 api", st == 200 and body["ok"] and body["data"].get("version"), [st, str(body)[:200]])
        st, body = await api_("/api/call", {"args": ["job", "list"]})
        chk("панель: команды вне белого списка — 403", st == 403, [st, body])
        st, body = await api_("/api/call", {"args": "status"})
        chk("панель: кривые аргументы — 400", st == 400, [st, body])
        admins.add(333, 111)
        st, body = await api_("/api/call", {"args": ["uninstall"]}, uid=333)
        chk("приглашённому админу владельческое закрыто", st == 403 and "владелец" in body.get("error", ""), [st, body])
        st, body = await api_("/api/call", {"args": ["cert", "remove"]}, uid=333)
        chk("…и сертификат тоже", st == 403, [st, body])
        st, body = await api_("/api/bot/info", {}, uid=333)
        chk("панель: приглашённому — сводка бота без списка админов",
            st == 200 and body.get("owner") is False and "admins" not in body and body.get("invited") == 1, [st, body])
        st1, _ = await api_("/api/bot/invite", {}, uid=333)
        st2, _ = await api_("/api/bot/icons", {"action": "off"}, uid=333)
        st3, _ = await api_("/api/bot/webapp/restart", {}, uid=333)
        chk("панель: приглашения, иконки и сервер панели — только владельцу", (st1, st2, st3) == (403, 403, 403),
            (st1, st2, st3))
        st, body = await api_("/api/bot/info", {})
        chk("панель: владельцу — список админов с приглашённым",
            st == 200 and body["owner"] and [a["uid"] for a in body["admins"]["invited"]] == [333], [st, body])
        st, body = await api_("/api/bot/invite", {})
        chk("панель: приглашение — ссылка на бота с одноразовым токеном",
            st == 200 and f"?start={admins.INVITE_PREFIX}" in body.get("link", "") and admins.pending_invites() == 1,
            [st, body])
        st, body = await api_("/api/bot/invites/revoke", {})
        chk("панель: приглашения гасятся", st == 200 and body.get("revoked") == 1 and admins.pending_invites() == 0, body)
        st, body = await api_("/api/bot/admin/del", {"uid": 333})
        chk("панель: владелец отзывает доступ", st == 200 and 333 not in admins.invited_ids(), [st, body])
        st, body = await api_("/api/me", {})
        chk("панель: /api/me — время старта бота (панель по нему ждёт перезапуск)",
            isinstance(body.get("started"), int) and body["started"] > 0, body)
        mark = len(SESSION.sent)
        st, body = await api_("/api/bot/menu", {})
        menu = [m for n, m in SESSION.sent[mark:] if n == "SendMessage" and getattr(m, "chat_id", None) == 111]
        chk("панель: «Меню бота в чат» — главное меню новым сообщением",
            st == 200 and menu and "srv" in [b.callback_data for row in menu[-1].reply_markup.inline_keyboard for b in row],
            [st, [n for n, _ in SESSION.sent[mark:]]])
        st, body = await api_("/api/wgobf/bundle", {"name": "nobody"})
        chk("панель: комплект обфускатора без обфускатора — понятная ошибка",
            st == 200 and body["ok"] is False and body.get("error"), [st, body])

        st, body = await api_("/api/clients", {})
        alice = next((c for c in body.get("rows") or [] if c["name"] == "alice"), {})
        chk("панель: клиенты с заметками, мониторингом и маршрутом",
            st == 200 and {"note", "mon", "route"} <= set(alice) and body.get("sort"), [st, alice])
        await api_("/api/client/note", {"name": "alice", "text": "ноутбук"})
        await api_("/api/client/mon", {"name": "alice", "on": True})
        chk("панель: заметка и мониторинг — в хранилище бота",
            store.note("alice") == "ноутбук #ping" and store.monitored("alice"), store.note("alice"))
        await api_("/api/client/mon", {"name": "alice", "on": False})
        st, body = await api_("/api/client/qr", {"name": "alice"})
        chk("панель: QR картинкой и текст конфига",
            st == 200 and len(body.get("png") or "") > 100 and "[Interface]" in body.get("text", ""), [st, str(body)[:120]])
        st, body = await api_("/api/client/add", {"name": "panel1", "expire": "+1d"})
        chk("панель: новый клиент", st == 200 and body["ok"], [st, body])
        st, body = await api_("/api/client/rename", {"old": "panel1", "new": "panel2"})
        chk("панель: переименование", st == 200 and body["ok"] and os.path.exists(os.path.join(ROOT, "root", "panel2_awg2.conf")),
            [st, body])
        st, body = await api_("/api/client/add", {"name": "bad name"})
        chk("панель: имя проверяется до awg2", st == 400, [st, body])
        mark = len(SESSION.sent)
        st, body = await api_("/api/send", {"what": "conf", "name": "panel2"})
        chk("панель: «отправить в чат» — файл и QR владельцу",
            st == 200 and [n for n, m in SESSION.sent[mark:] if getattr(m, "chat_id", None) == 111]
            == ["SendDocument", "SendPhoto"], [n for n, _ in SESSION.sent[mark:]])
        st, body = await api_("/api/job", {"args": ["clients", "bulk", "pj:2", "mimicry=none"]})
        jid = (body.get("data") or {}).get("id")
        for _ in range(100):
            st, body = await api_("/api/job/status", {"id": jid, "offset": 0})
            if (body.get("data") or {}).get("state") != "running":
                break
            await asyncio.sleep(0.3)
        chk("панель: задача с журналом — массовое создание",
            body["data"].get("ok") and body["data"].get("data") == ["pj-001", "pj-002"] and "pj-001" in body["data"].get("log", ""),
            body.get("data"))
        st, body = await api_("/api/client/del", {"names": ["panel2", "pj-001", "pj-002"]})
        chk("панель: удаление нескольких", st == 200 and body["ok"]
            and not os.path.exists(os.path.join(ROOT, "root", "pj-001_awg2.conf")), [st, body])

        # Бэкап: в чат — только из списка на сервере; архив с телефона — телом запроса
        st, body = await api_("/api/call", {"args": ["backup", "create"], "timeout": 300})
        bk_path = (body.get("data") or {}).get("path") or ""
        st, body = await api_("/api/send", {"what": "backup", "path": "/etc/passwd"})
        chk("панель: в чат уходит только бэкап из списка, не любой файл", st == 400, [st, body])
        mark = len(SESSION.sent)
        st, body = await api_("/api/send", {"what": "backup", "path": bk_path})
        chk("панель: бэкап — файлом в чат владельцу",
            st == 200 and [n for n, m in SESSION.sent[mark:] if getattr(m, "chat_id", None) == 111] == ["SendDocument"],
            [st, body, [n for n, _ in SESSION.sent[mark:]]])
        with open(bk_path, "rb") as f:
            archive = f.read()

        async def upload(data, uid=111):
            async with http.post(base + "/api/backup/upload", data=data,
                                 headers={"Authorization": "tma " + init_data(uid),
                                          "Content-Type": "application/octet-stream"}) as r:
                return r.status, await r.json(content_type=None)

        st, body = await upload(archive, uid=222)
        chk("панель: загрузка бэкапа чужим — 403", st == 403, [st, body])
        st, body = await upload(archive)
        up = body.get("path") or ""
        chk("панель: архив с телефона сохранён у бота, только для root",
            st == 200 and os.path.isfile(up) and oct(os.stat(up).st_mode & 0o777) == "0o600", [st, body])
        st, body = await api_("/api/call", {"args": ["backup", "inspect", up]})
        chk("панель: загруженный архив читается как бэкап", st == 200 and body["ok"] and body["data"]["clients"] >= 1,
            [st, str(body)[:200]])
        st, body = await upload(b"x" * (20 * 1024 * 1024 + 1))
        chk("панель: больше 20 МБ — отказ", st == 400 and "20 МБ" in body.get("error", ""), [st, body])

    text, _ = screen(await press(f"app:pset:{ports[1]}"))
    chk("смена порта перезапускает сервер", webapp.SERVER.running and webapp.SERVER.url.endswith(f":{ports[1]}/")
        and f"Порт Mini App: {ports[1]}" in text, [text[:200], webapp.SERVER.url])

    WEBAPP_REJECT[0] = True
    text, buttons = screen(await press("app"))
    chk("Telegram не принял адрес — понятно, что нужен домен, экран на месте",
        "Telegram не принял адрес" in text and "Нужен домен" in text and ("🌍 На домен…", "app:dom") in buttons
        and not any((d or "").startswith("webapp:") for _, d in buttons), [text[-300:], buttons])
    WEBAPP_REJECT[0] = False

    mark = len(SESSION.sent)
    await press("app:rmok")
    chk("удаление сертификата останавливает Mini App и возвращает обычное «Меню»",
        not webapp.SERVER.running and not os.path.exists(os.path.join(ROOT, "etc/awg2/cert/fullchain.pem"))
        and any(n == "SetChatMenuButton" and m.chat_id == 111 and m.menu_button.type == "default"
                for n, m in SESSION.sent[mark:]), menus()[-2:])

    print("Цвета кнопок")
    await say("/start")
    styles = {b.text: b.style for row in keyboard(SESSION.sent) for b in row}
    chk("главное меню: обновление синее, удаление красное, «Поддержать» зелёная, остальные обычные",
        styles.get("⬆️ Обновление") == "primary" and styles.get("🗑 Удаление") == "danger"
        and styles.get("Поддержать 💚") == "success" and styles.get("👥 Клиенты") is None
        and styles.get("🖥 Сервер") is None, styles)
    await press("cl")
    styles = {b.text: b.style for row in keyboard(SESSION.sent) for b in row}
    chk("клиенты: добавить — зелёная, удалить — красная, назад — обычная",
        styles.get("➕ Добавить") == "success" and styles.get("🗑 Удалить…") == "danger"
        and styles.get("◀️ Назад") is None, styles)
    await press("cl:del:alice")
    styles = {b.text: b.style for row in keyboard(SESSION.sent) for b in row}
    chk("подтверждение удаления: «Да» красная, «Отмена» обычная, в одной строке",
        styles == {"🗑 Да, удалить": "danger", "✖️ Отмена": None}
        and [len(r) for r in keyboard(SESSION.sent)] == [2], styles)

    print("Иконки")
    icons_mod = sys.modules["awgbot.icons"]
    text, buttons = screen(await press("look"))
    chk("экран оформления: иконки выключены, условие Premium названо",
        "выключены" in text and "Telegram Premium" in text and ("📥 Набор иконок", "look:pack") in buttons, text)
    text, buttons = screen(await press("look:pack"))
    chk("набор TgAndroidIcons — готовой кнопкой", ("📱 TgAndroidIcons", "look:pk:TgAndroidIcons") in buttons, buttons)
    text, _ = screen(await say("t.me/addemoji/SomeIcons"))
    chk("нет Premium — Telegram срезал иконки: выключены, набор сохранён",
        "не показал иконки" in text and not icons_mod.active() and icons_mod.mapping().get("🖥") == "111", text)
    chk("похожие эмодзи: 💾 — иконкой 💿; цветные значки набора не берутся",
        icons_mod.mapping().get("💾") == "666" and "🟢" not in icons_mod.mapping(), icons_mod.mapping())
    await say("/start")
    text, buttons = screen(SESSION.sent[-3:])
    rows = keyboard(SESSION.sent)
    chk("после отказа — обычные эмодзи", "<tg-emoji" not in text and rows[0][0].text == "🖥 Сервер"
        and rows[0][0].icon_custom_emoji_id is None, [text[:80], rows[0][0]])

    PREMIUM["mode"] = "ok"
    text, _ = screen(await press("look:pk:TgAndroidIcons"))
    chk("с Premium — проверка прошла, иконки включены, показано что подобралось",
        "Иконки включены: 5 из" in text and "Обычные эмодзи:" in text and icons_mod.active()
        and icons_mod.pack() == "TgAndroidIcons", text)
    sent = await say("/start")
    text, _ = screen(sent)
    rows = keyboard(sent)
    chk("иконки в тексте: эмодзи хоста — custom emoji, цветные точки — как есть",
        '<tg-emoji emoji-id="111">🖥</tg-emoji>' in text and "<tg-emoji emoji-id" in text
        and "🟢" in text and 'emoji-id="111">🟢' not in text, text[:300])
    chk("иконка на кнопке вместо эмодзи в подписи",
        rows[0][0].text == "Сервер" and rows[0][0].icon_custom_emoji_id == "111"
        and rows[0][1].text == "Клиенты" and rows[0][1].icon_custom_emoji_id == "222"
        and rows[1][0].text == "🩺 Диагностика", [rows[0], rows[1][0]])

    PREMIUM["mode"] = "reject"
    sent = await press("main")
    text, _ = screen(sent)
    chk("Telegram отклонил иконки — экран всё равно показан, с обычными эмодзи, иконки выключены",
        "AWG Toolza" in text and "<tg-emoji" not in text and not icons_mod.active()
        and keyboard(sent)[0][0].text == "🖥 Сервер", [n for n, _ in sent])

    PREMIUM["mode"] = "ok"
    await press("look:own")
    own = "🖥 🌐 👥"
    ents = [MessageEntity(type="custom_emoji", offset=0, length=2, custom_emoji_id="901"),
            MessageEntity(type="custom_emoji", offset=6, length=2, custom_emoji_id="903")]
    text, _ = screen(await say(own, entities=ents))
    m = icons_mod.mapping()
    chk("свои иконки дополняют набор; обычное эмодзи на месте — оставить",
        "Иконки включены" in text and m.get("🖥") == "901" and m.get("🩺") == "903" and m.get("👥") == "222"
        and icons_mod.pack() == "TgAndroidIcons + свои", [icons_mod.pack(), m])
    admin = User(id=333, is_bot=False, first_name="Admin")
    admins.add(333, 111)
    denied = [alerts(await press(d, admin)) for d in ("look", "look:pk:TgAndroidIcons", "look:own", "look:off",
                                                       "adm:invite", "app:rm")]
    chk("приглашённому админу оформление, админы и Mini App закрыты — каждая кнопка",
        all(len(a) == 1 and "только владелец" in a[0] for a in denied)
        and icons_mod.active() and icons_mod.pack() == "TgAndroidIcons + свои" and admins.pending_invites() == 0, denied)
    admins.remove(333, removed_by=111)

    await press("look:off")
    chk("выключение иконок", not icons_mod.active() and icons_mod.mapping(), icons_mod.mapping())
    PREMIUM["mode"] = "strip"

    print("Ширина экрана")
    short = ui.fit("<b>🛡 alice</b>", ui.kb(("📦 Комплект", "a"), ("🗑 Удалить", "b")))
    chk("короткий текст дополняется до ширины кнопок", short.startswith("<b>🛡 alice</b>")
        and ui.width(short.replace("<b>", "").replace("</b>", "")) >= 2 * (ui.width("📦 Комплект") + 4), short)
    long_text = "<b>Заголовок</b>\n" + "очень длинная строка текста экрана"
    chk("длинный текст не трогается", ui.fit(long_text, ui.kb(("📦 Комплект", "a"))) == long_text)


asyncio.run(run())
asyncio.run(BOT.session.close())
summary()
