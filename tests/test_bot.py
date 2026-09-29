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
import time

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

from awgbot import bot as botmod, jobs, store, ui  # noqa: E402

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
        if name == "EditMessageReplyMarkup":
            if method.message_id in self.chat and not method.reply_markup:
                self.chat[method.message_id] = "text"
            return True
        if name in ("SendMessage", "EditMessageText", "SendDocument", "SendPhoto"):
            # В личном чате номера сообщений общие для обеих сторон
            mid = getattr(method, "message_id", None) or next(MSG_IDS)
            if method.chat_id == OWNER.id:
                self.chat[mid] = ("file" if name in ("SendDocument", "SendPhoto")
                                  else "screen" if method.reply_markup else "text")
                self.text[mid] = getattr(method, "text", None) or getattr(method, "caption", None) or ""
            return Message(message_id=mid, date=datetime.datetime.now(), chat=Chat(id=method.chat_id, type="private"),
                           text=getattr(method, "text", None)).as_(bot)
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


def _msg(user, text):
    return Message(message_id=next(MSG_IDS), date=datetime.datetime.now(), chat=Chat(id=user.id, type="private"),
                   from_user=user, text=text)


LAST_SAID = [0]


async def say(text, user=OWNER):
    mark = len(SESSION.sent)
    msg = _msg(user, text)
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
            return m.text or "", [(b.text, b.callback_data) for row in rows for b in row]
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

    print("Главное меню")
    text, buttons = screen(await say("/start"))
    chk("сводка сервера", "AWG Toolza" in text and "AWG 2.0" in text and "2 клиента · 0 онлайн" in text, text)
    chk("шапка блоками", text.count("<blockquote>") >= 3 and "<b>vm" not in text.split("<blockquote>")[0], text)
    datas = [d for _, d in buttons]
    chk("девять пунктов меню в порядке awg2",
        datas[:9] == ["srv", "cl", "diag", "bk", "tun", "botm", "del", "upd", "wo"], buttons)
    chk("главное меню — два столбца", [len(r) for r in keyboard(SESSION.sent)] == [2, 2, 2, 2, 2],
        [[b.text for b in r] for r in keyboard(SESSION.sent)])
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
    long_domain = "a" * 60 + ".example.com"
    await press("srv:epdom")
    text, buttons = screen(await say(long_domain))
    chk("длинный домен endpoint не ломает кнопки", "srv:epgo:keep" in [d for _, d in buttons], [text, buttons])
    text, _ = screen(await press("srv:epgo:keep"))
    chk("endpoint применён", "✅" in text and long_domain in text, text)
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
    # Подписи — в половину экрана: иначе Telegram режет их многоточием.
    # Имена клиентов, нод и тегов задаёт пользователь — их не считаем.
    wide = sorted({b.text for name, m in SESSION.sent if name in ("SendMessage", "EditMessageText")
                   and m.reply_markup for row in m.reply_markup.inline_keyboard for b in row
                   if ui.width(b.text) > ui.WIDE and not b.callback_data.startswith(USER_NAMED)})
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

    print("Ширина экрана")
    short = ui.fit("<b>🛡 alice</b>", ui.kb(("📦 Комплект", "a"), ("🗑 Удалить", "b")))
    chk("короткий текст дополняется до ширины кнопок", short.startswith("<b>🛡 alice</b>")
        and ui.width(short.replace("<b>", "").replace("</b>", "")) >= 2 * (ui.width("📦 Комплект") + 4), short)
    long_text = "<b>Заголовок</b>\n" + "очень длинная строка текста экрана"
    chk("длинный текст не трогается", ui.fit(long_text, ui.kb(("📦 Комплект", "a"))) == long_text)


asyncio.run(run())
asyncio.run(BOT.session.close())
summary()
