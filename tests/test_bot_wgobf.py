"""
test_bot_wgobf.py — раздел «WG + обфускатор» в боте на живом диспетчере aiogram.

Обновления идут через настоящий Dispatcher (как в test_bot_access.py), сеть
подменена сессией-заглушкой. Файлы awg2 (state, конфиг сервера, комплекты)
лежат во временном каталоге, сам awg2 — заглушка, которая пишет, с какими
аргументами её вызвали, и меняет файлы так же, как настоящий `awg2 --wgobf`.

Проверяется: пункт в главном меню появляется только при установленном режиме,
сводка/список/карточка читают файлы awg2, ссылка phobos:// и файлы комплекта
отдаются, добавление/удаление/смена ключа идут через `awg2 --wgobf`, мусорное
имя (в том числе с ../) не доходит ни до файлов, ни до awg2, посторонний
отбит.

Запуск:  python3 tests/test_bot_wgobf.py
Выход:   0 — всё сошлось (или «пропущен» без aiogram), 1 — есть провалы.
"""
import asyncio
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "awg_bot"))

try:
    from aiogram.client.session.base import BaseSession
    from aiogram.methods import TelegramMethod
    from aiogram.types import CallbackQuery, Chat, Message, Update, User
except ImportError as exc:
    print("пропущен: не установлен aiogram (%s)" % exc)
    sys.exit(0)

OWNER = 111111111
STRANGER = 222222222

TMP = tempfile.mkdtemp(prefix="awg-bot-wgobf.")
STATE = os.path.join(TMP, "state")
WGCONF = os.path.join(TMP, "wgobf0.conf")
CLIENTS = os.path.join(TMP, "clients")
CALLS = os.path.join(TMP, "calls.log")

os.environ.setdefault("BOT_TOKEN", "42:TEST")
os.environ.setdefault("ADMIN_ID", str(OWNER))
os.environ["AWG_BOT_CONF"] = os.path.join(_HERE, "_no_such_conf")
os.environ["AWG_ADMINS_FILE"] = os.path.join(TMP, "admins.json")
os.environ["AWG_MON_STATE"] = os.path.join(TMP, "monitor.json")
os.environ["AWG_SERVER_CONF"] = os.path.join(TMP, "no_awg0.conf")   # AWG не установлен
os.environ["AWG_WGOBF_STATE"] = STATE
os.environ["AWG_WGOBF_WG_CONF"] = WGCONF
os.environ["AWG_WGOBF_CLIENTS"] = CLIENTS

from awgbot import bot as botmod, core    # noqa: E402  (после env)

# ── заглушка awg2 ──
STUB = os.path.join(TMP, "awg2")
with open(STUB, "w") as f:
    f.write(f"""#!/usr/bin/env bash
echo "$*" >> "{CALLS}"
[[ "$1" == --wgobf ]] || exit 1
bundle() {{
  mkdir -p "{CLIENTS}/$1"
  printf '[Interface]\\nPrivateKey = K\\n' > "{CLIENTS}/$1/wg.conf"
  printf '[main]\\nkey = k\\n' > "{CLIENTS}/$1/obfuscator.conf"
  printf 'phobos://QUJD#%s\\n' "$1" > "{CLIENTS}/$1/phobos-link.txt"
  printf 'x\\n' > "{CLIENTS}/$1/phobos.conf"
  printf 'x\\n' > "{CLIENTS}/$1/keenetic.txt"
}}
case "$2" in
  add)
    printf '\\n[Peer]\\n# client=%s\\nPublicKey = P%s\\nAllowedIPs = 10.60.1.9/32\\n' "$3" "$3" >> "{WGCONF}"
    bundle "$3"; echo "√ Клиент $3" ;;
  del)
    python3 - "$3" <<'PY'
import sys
p = "{WGCONF}"
blocks = open(p).read().split("[Peer]")
keep = [b for b in blocks if f"# client={{sys.argv[1]}}" not in b]
open(p, "w").write("[Peer]".join(keep))
PY
    rm -rf "{CLIENTS}/$3"; echo "√ удалён" ;;
  bundle) bundle "$3" ;;
  rotate-key|restart) echo "√ $2" ;;
  *) exit 1 ;;
esac
""")
os.chmod(STUB, 0o755)
core.AWG2_BIN_PATH = STUB


def install_fixture() -> None:
    with open(STATE, "w") as f:
        f.write("PORT=37590\nWG_PORT=40000\nKEY=k\nMASKING=STUN\nALLOW_CLEAN=1\n"
                "NET=10.60.1.0/24\nMTU=1380\nDNS=1.1.1.1\nENDPOINT=85.121.54.58\n"
                "SERVER_PUB=S\n")
    with open(WGCONF, "w") as f:
        f.write("[Interface]\nPrivateKey = X\nAddress = 10.60.1.1/24\n\n"
                "[Peer]\n# client=c1\nPublicKey = PC1\nAllowedIPs = 10.60.1.2/32\n")
    d = os.path.join(CLIENTS, "c1")
    os.makedirs(d, exist_ok=True)
    for fn, body in (("wg.conf", "[Interface]\n"), ("obfuscator.conf", "[main]\n"),
                     ("phobos.conf", "x\n"), ("keenetic.txt", "x\n"),
                     ("phobos-link.txt", "phobos://QUJD#c1\n"),
                     ("wg-direct.conf", "[Interface]\nPrivateKey = K\n"),
                     ("README.txt", "r\n"), ("install-linux.sh", "#!/bin/bash\n")):
        with open(os.path.join(d, fn), "w") as f:
            f.write(body)


class MockSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[str, dict]] = []

    async def close(self) -> None:
        pass

    async def make_request(self, bot, method: TelegramMethod, timeout=None):
        name = type(method).__name__
        self.calls.append((name, method.model_dump(exclude_none=True)))
        if name in ("SendMessage", "EditMessageText", "SendDocument", "SendPhoto"):
            return _make_message(1, OWNER, "ok")
        return True

    async def stream_content(self, url, headers=None, timeout=30,
                             chunk_size=65536, raise_for_status=True):
        yield b""


def _make_message(message_id: int, uid: int, text: str) -> Message:
    user = User(id=uid, is_bot=False, first_name="T")
    chat = Chat(id=uid, type="private")
    return Message(message_id=message_id, date=datetime.now(timezone.utc),
                   chat=chat, from_user=user, text=text).as_(botmod.bot)


_uid = 0


def cb(uid: int, data: str) -> Update:
    global _uid
    _uid += 1
    user = User(id=uid, is_bot=False, first_name="T")
    q = CallbackQuery(id="cb%d" % _uid, from_user=user, chat_instance="ci",
                      data=data, message=_make_message(10, uid, "меню"))
    return Update(update_id=_uid, callback_query=q)


def msg(uid: int, text: str) -> Update:
    global _uid
    _uid += 1
    return Update(update_id=_uid, message=_make_message(11, uid, text))


fail = 0


def chk(name: str, cond: bool, detail: str = "") -> None:
    global fail
    if cond:
        print("  OK   %s" % name)
    else:
        fail += 1
        print("  FAIL %s%s" % (name, (" — " + detail[:200]) if detail else ""))


async def feed(update: Update) -> list[tuple[str, dict]]:
    session: MockSession = botmod.bot.session          # type: ignore[assignment]
    session.calls.clear()
    await botmod.dp.feed_update(botmod.bot, update)
    return list(session.calls)


def texts(calls) -> str:
    return " ".join(str(p.get("text", "")) + str(p.get("caption", "")) for _, p in calls)


def buttons(calls) -> list[str]:
    out = []
    for _, p in calls:
        for row in (p.get("reply_markup") or {}).get("inline_keyboard", []):
            out += [b.get("callback_data", "") for b in row]
    return out


def awg2_calls() -> list[str]:
    try:
        return open(CALLS).read().split("\n")[:-1]
    except OSError:
        return []


async def main() -> int:
    botmod.bot.session = MockSession()

    print("── не установлен ──")
    calls = await feed(cb(OWNER, "menu"))
    chk("без режима кнопки в меню нет", "wgobf" not in buttons(calls), str(buttons(calls)))
    calls = await feed(cb(OWNER, "wgobf"))
    chk("экран подсказывает установку в консоли", "пункт 9" in texts(calls), texts(calls))

    install_fixture()
    print("── установлен ──")
    calls = await feed(cb(OWNER, "menu"))
    chk("кнопка появилась (и без AWG)", "wgobf" in buttons(calls), str(buttons(calls)))
    calls = await feed(cb(OWNER, "wgobf"))
    t = texts(calls)
    chk("сводка: вход и маскировка", "85.121.54.58:37590" in t and "STUN" in t, t)
    chk("сводка: клиентов 1", "клиентов: <b>1</b>" in t, t)

    calls = await feed(cb(OWNER, "wgo_list"))
    chk("список: c1 и кнопка карточки", "c1" in texts(calls) and "wgo_c:c1" in buttons(calls),
        str(buttons(calls)))
    calls = await feed(cb(OWNER, "wgo_c:c1"))
    chk("карточка: IP", "10.60.1.2" in texts(calls), texts(calls))
    chk("карточка: QR без обфускатора есть (allow-clean)", "wgo_qr:c1" in buttons(calls))

    calls = await feed(cb(OWNER, "wgo_link:c1"))
    chk("ссылка phobos:// отправлена", "phobos://QUJD#c1" in texts(calls), texts(calls))
    calls = await feed(cb(OWNER, "wgo_files:c1"))
    docs = [p for n, p in calls if n == "SendDocument"]
    chk("файлы комплекта: все 7", len(docs) == 7, str(len(docs)))
    calls = await feed(cb(OWNER, "wgo_qr:c1"))
    chk("QR без обфускатора отправлен",
        any(n in ("SendPhoto", "SendDocument") for n, _ in calls), str(calls)[:150])

    print("── добавление ──")
    await feed(cb(OWNER, "wgo_add"))
    before = len(awg2_calls())
    calls = await feed(msg(OWNER, "bad name"))
    chk("мусорное имя отбито", "❌" in texts(calls) and len(awg2_calls()) == before, texts(calls))
    calls = await feed(msg(OWNER, "new_one"))
    chk("awg2 --wgobf add new_one", awg2_calls()[-1:] == ["--wgobf add new_one"], str(awg2_calls()))
    chk("ответ: клиент создан", "Клиент создан" in texts(calls), texts(calls))
    chk("клиент в конфиге", core.wgobf_client("new_one") is not None)

    print("── имена из callback ──")
    before = len(awg2_calls())
    for bad in ("wgo_c:../etc", "wgo_files:../../root", "wgo_delok:a b", "wgo_link:"):
        calls = await feed(cb(OWNER, bad))
        chk(f"{bad!r} отбит", "Некорректное" in texts(calls) or "не найдена" in texts(calls)
            or "не найден" in texts(calls), texts(calls))
    chk("мусор до awg2 не дошёл", len(awg2_calls()) == before, str(awg2_calls()[before:]))

    print("── удаление, ключ, перезапуск ──")
    calls = await feed(cb(OWNER, "wgo_delok:new_one"))
    chk("awg2 --wgobf del new_one", awg2_calls()[-1:] == ["--wgobf del new_one"], str(awg2_calls()))
    chk("после удаления список без new_one", "wgo_c:new_one" not in buttons(calls),
        str(buttons(calls)))
    calls = await feed(cb(OWNER, "wgo_key"))
    chk("смена ключа спрашивает подтверждение", "wgo_keyok" in buttons(calls)
        and awg2_calls()[-1:] != ["--wgobf rotate-key"])
    calls = await feed(cb(OWNER, "wgo_keyok"))
    chk("awg2 --wgobf rotate-key", awg2_calls()[-1:] == ["--wgobf rotate-key"], str(awg2_calls()))
    chk("после смены — «Ключ заменён»", "Ключ заменён" in texts(calls), texts(calls))
    calls = await feed(cb(OWNER, "wgo_restart"))
    chk("awg2 --wgobf restart", awg2_calls()[-1:] == ["--wgobf restart"], str(awg2_calls()))

    print("── посторонний ──")
    before = len(awg2_calls())
    for data in ("wgobf", "wgo_link:c1", "wgo_keyok", "wgo_delok:c1"):
        calls = await feed(cb(STRANGER, data))
        chk(f"посторонний: {data} отбит",
            any("Доступ запрещён" in str(p.get("text", "")) for _, p in calls)
            and not any(n in ("SendMessage", "EditMessageText", "SendDocument") for n, _ in calls))
    chk("посторонний ничего не вызвал в awg2", len(awg2_calls()) == before)

    print("\nпровалов:", fail)
    return 1 if fail else 0


if __name__ == "__main__":
    try:
        code = asyncio.run(main())
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(code)
