"""panel_stand.py — сервер панели Mini App на песочнице awg2 для прогона в браузере.

Запускает test_panel.py: печатает «READY порт initData» и работает, пока его
не остановят. PROFILE=lite|pro — профиль сервера (от него зависят экраны),
AWG2_SH — сборка awg2 (по умолчанию dist/awg2.sh). Telegram здесь нет:
сессия бота только печатает вызовы.
"""
import asyncio
import hashlib
import hmac
import json
import os
import socket
import subprocess
import sys
import time
from urllib.parse import urlencode

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.argv = ["panel_stand", os.environ.get("AWG2_SH") or os.path.join(HERE, "..", "dist", "awg2.sh")]
from sandbox import *  # noqa: E402,F401,F403

TOKEN = "123456:" + "A" * 35
API = api_wrapper()
fake_acme()

# Сервер AWG с двумя клиентами: alice онлайн, bob был два часа назад
STATE = os.path.join(TMP, "botstate")
os.makedirs(STATE)
os.makedirs(os.path.join(ROOT, "etc/amnezia/amneziawg"), exist_ok=True)
os.makedirs(os.path.join(ROOT, "root"), exist_ok=True)
with open(os.path.join(ROOT, "etc/amnezia/amneziawg/awg0.conf"), "w") as f:
    f.write(OLD20.replace("AWG_PROFILE=pro", "AWG_PROFILE=" + os.environ.get("PROFILE", "pro")))
for n in ("alice", "bob"):
    with open(os.path.join(ROOT, "root", n + "_awg2.conf"), "w") as f:
        f.write("[Interface]\nPrivateKey = X\nAddress = 10.23.45.2/32\n")
now = int(time.time())
with open(AWG_DUMP, "w") as f:
    f.write(f"PRIV\tPUB\t51820\toff\n"
            f"PUBALICE=\t(none)\t5.6.7.8:4242\t10.23.45.2/32\t{now - 20}\t12345678\t987654\toff\n"
            f"PUBBOB=\t(none)\t(none)\t10.23.45.3/32\t{now - 7200}\t1024\t2048\toff\n")

with socket.socket() as s:
    s.bind(("127.0.0.1", 0))
    PORT = s.getsockname()[1]
with open(os.path.join(ROOT, "bot.conf"), "w") as f:
    f.write(f"BOT_TOKEN={TOKEN}\nADMIN_ID=111\nWEBAPP_PORT={PORT}\n")
os.environ.update(ENV)
os.environ.update(AWG2_BIN=API, AWG_BOT_STATE=STATE, AWG_ADMINS_FILE=os.path.join(STATE, "admins.json"),
                  AWG_BOT_CONF=os.path.join(ROOT, "bot.conf"),
                  AWG_CERT_FULL=os.path.join(ROOT, "etc/awg2/cert/fullchain.pem"),
                  AWG_CERT_KEY=os.path.join(ROOT, "etc/awg2/cert/key.pem"))

sys.path.insert(0, os.path.join(HERE, "..", "awg_bot"))
from aiogram import Bot  # noqa: E402
from aiogram.client.session.base import BaseSession  # noqa: E402

from awgbot import access, store, webapp  # noqa: E402
from awgbot.config import load_config  # noqa: E402


class Session(BaseSession):
    async def make_request(self, bot, method, timeout=None):
        print("TG", type(method).__name__, getattr(method, "chat_id", ""), flush=True)
        return True

    async def stream_content(self, *args, **kwargs):
        raise NotImplementedError
        yield b""                                               # pragma: no cover

    async def close(self):
        pass


def init_data(uid):
    fields = {"auth_date": str(int(time.time())), "query_id": "AAH",
              "user": json.dumps({"id": uid, "first_name": "Ivan"}, separators=(",", ":"))}
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


async def main():
    access.setup(load_config())
    subprocess.run([API, "api", "cert", "issue", "ip"], capture_output=True)
    store.set_note("alice", "телефон Анны")
    await webapp.SERVER.start(Bot(TOKEN, session=Session()))
    print("READY", PORT, init_data(111), webapp.SERVER.error or "-", flush=True)
    while True:
        await asyncio.sleep(3600)


asyncio.run(main())
