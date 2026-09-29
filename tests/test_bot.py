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
import itertools
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sandbox import *  # noqa: E402,F401,F403

try:
    import aiogram  # noqa: F401
except ImportError:
    print("aiogram не установлен — тест бота пропущен (pip install -r awg_bot/requirements.txt)")
    sys.exit(0)

from aiogram.client.session.base import BaseSession  # noqa: E402
from aiogram.types import CallbackQuery, Chat, Message, Update, User  # noqa: E402

# ── Окружение бота ────────────────────────────────────────
API = api_wrapper()
STATE = os.path.join(TMP, "botstate")
os.makedirs(STATE)
BOT_CONF = os.path.join(TMP, "awg-bot.conf")
with open(BOT_CONF, "w") as f:
    f.write("BOT_TOKEN=123456:" + "A" * 35 + "\nADMIN_ID=111\n")
os.environ.update(ENV)
os.environ.update(AWG2_BIN=API, AWG_BOT_STATE=STATE, AWG_ADMINS_FILE=os.path.join(STATE, "admins.json"),
                  AWG_BOT_CONF=BOT_CONF)
sys.path.insert(0, os.path.join(HERE, "..", "awg_bot"))

from awgbot import bot as botmod, jobs, store  # noqa: E402

logging.getLogger("aiogram").setLevel(logging.WARNING)

jobs.POLL, jobs.EDIT_EVERY = 0.2, 0.0

os.makedirs(os.path.join(ROOT, "etc/amnezia/amneziawg"), exist_ok=True)
os.makedirs(os.path.join(ROOT, "root"), exist_ok=True)
with open(os.path.join(ROOT, "etc/amnezia/amneziawg/awg0.conf"), "w") as f:
    f.write(OLD20)
for n in ("alice", "bob"):
    with open(os.path.join(ROOT, "root", n + "_awg2.conf"), "w") as f:
        f.write("[Interface]\nPrivateKey = X\nAddress = 10.23.45.2/32\n")


class FakeSession(BaseSession):
    """Bot API без сети: запоминает вызовы и отвечает правдоподобно."""

    def __init__(self):
        super().__init__()
        self.sent = []
        self.ids = itertools.count(1000)

    async def make_request(self, bot, method, timeout=None):
        name = type(method).__name__
        self.sent.append((name, method))
        if name == "GetMe":
            return User(id=999, is_bot=True, first_name="Bot", username="testbot").as_(bot)
        if name in ("SendMessage", "EditMessageText", "SendDocument", "SendPhoto"):
            mid = getattr(method, "message_id", None) or next(self.ids)
            return Message(message_id=mid, date=datetime.datetime.now(), chat=Chat(id=method.chat_id, type="private"),
                           text=getattr(method, "text", None)).as_(bot)
        return True

    async def stream_content(self, *args, **kwargs):
        raise NotImplementedError
        yield b""                                               # pragma: no cover

    async def close(self):
        pass


SESSION = FakeSession()
BOT, DP = botmod.build(SESSION)
OWNER = User(id=111, is_bot=False, first_name="Owner", username="owner")
STRANGER = User(id=222, is_bot=False, first_name="Stranger")
seq = itertools.count(1)


def _msg(user, text):
    return Message(message_id=next(seq), date=datetime.datetime.now(), chat=Chat(id=user.id, type="private"),
                   from_user=user, text=text)


async def say(text, user=OWNER):
    mark = len(SESSION.sent)
    await DP.feed_update(BOT, Update(update_id=next(seq), message=_msg(user, text)))
    return SESSION.sent[mark:]


async def press(data, user=OWNER):
    mark = len(SESSION.sent)
    cb = CallbackQuery(id=str(next(seq)), from_user=user, chat_instance="ci", data=data,
                       message=_msg(user, "экран"))
    await DP.feed_update(BOT, Update(update_id=next(seq), callback_query=cb))
    return SESSION.sent[mark:]


def screen(sent):
    """Последний показанный экран: текст и кнопки (текст, данные)."""
    for name, m in reversed(sent):
        if name in ("SendMessage", "EditMessageText"):
            rows = m.reply_markup.inline_keyboard if m.reply_markup else []
            return m.text or "", [(b.text, b.callback_data) for row in rows for b in row]
    return "", []


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

    print("Главное меню")
    text, buttons = screen(await say("/start"))
    chk("сводка сервера", "AWG Toolza" in text and "AWG 2.0" in text and "клиентов 2" in text, text)
    datas = [d for _, d in buttons]
    chk("девять пунктов меню в одну колонку",
        datas[:9] == ["srv", "cl", "diag", "bk", "tun", "botm", "del", "upd", "wo"], buttons)
    text, _ = screen(await say("что-нибудь"))
    chk("любой текст вне ввода — меню", "AWG Toolza" in text, text)
    chk("устаревшая кнопка", any("устарела" in a for a in alerts(await press("zzz:1"))))

    print("Клиенты")
    text, buttons = screen(await press("cl"))
    chk("список клиентов", "Клиенты: 2" in text and ("cl:v:alice" in [d for _, d in buttons]), [text, buttons])
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

    await press("cl:note:carol")
    await say("домашний роутер")
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

    await press("cl:bulk")
    await say("u:2")
    sent = await press("cl:be:none")
    d = docs(sent)
    chk("несколько клиентов — zip", d and d[0].document.filename == "awg_clients.zip" and len(d[0].document.data) > 100,
        [n for n, _ in sent])

    print("Сервер и туннели")
    text, buttons = screen(await press("srv"))
    chk("экран сервера", "AWG 2.0" in text and "srv:proto" in [d for _, d in buttons], text)
    text, buttons = screen(await press("srv:create"))
    chk("мастер создания начинается с региона", "srv:w:region=ru" in [d for _, d in buttons], buttons)
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

    print("Все экраны")
    screens = ["srv", "mod", "srv:proto", "srv:ep", "srv:install", "srv:reset", "srv:reboot",
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

    print("Задачи")
    sent = await press("bk:create")
    chk("задача запущена отдельным сообщением",
        any(n == "SendMessage" and "Бэкап" in (m.text or "") for n, m in sent), [n for n, _ in sent])
    chk("задача завершилась", await wait_jobs())
    finals = [m for n, m in SESSION.sent if n == "EditMessageText" and "Бэкап" in (m.text or "")]
    chk("итог задачи в том же сообщении", finals and finals[-1].text.startswith("✅"),
        finals[-1].text if finals else "")
    chk("архив бэкапа отправлен", any(n == "SendDocument" and "Бэкап" in (m.caption or "") for n, m in SESSION.sent))
    chk("незавершённых задач не осталось", store.jobs() == {}, store.jobs())


asyncio.run(run())
asyncio.run(BOT.session.close())
summary()
