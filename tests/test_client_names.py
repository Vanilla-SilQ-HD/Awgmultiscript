"""
test_client_names.py — имена клиентских конфигов: _awg2.conf (2.0) / _awg3.conf (3.x).

Запуск:  python3 tests/test_client_names.py
Выход:   0 — всё сошлось, 1 — есть провалы.
"""
import os
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp(prefix="awg-names-")
SRV = os.path.join(TMP, "awg0.conf")
os.environ["AWG_SERVER_CONF"] = SRV
os.environ["AWG_CLIENT_DIR"] = TMP
sys.path.insert(0, os.path.join(_HERE, "..", "awg_bot"))

from awgbot import core                          # noqa: E402

fail = 0


def chk(name, cond):
    global fail
    if not cond:
        fail += 1
    print(("OK   " if cond else "FAIL ") + name)


def touch(n):
    open(os.path.join(TMP, n), "w").close()


def base(p):
    return os.path.basename(p)


open(SRV, "w").write("# AWG_PROTO=2.0\n")
chk("2.0: новый клиент → _awg2", base(core.client_conf("a")) == "a_awg2.conf")

open(SRV, "w").write("# AWG_PROTO=3.1\n")
chk("3.1: новый клиент → _awg3", base(core.client_conf("a")) == "a_awg3.conf")

touch("old_awg2.conf")
chk("3.1: старый *_awg2 находится", base(core.client_conf("old")) == "old_awg2.conf")

touch("new_awg3.conf")
touch("junk.conf")
names = sorted(base(f) for f in core.client_files())
chk("client_files видит обе версии, без мусора",
    names == ["new_awg3.conf", "old_awg2.conf"])

chk("is_client_file", core.is_client_file("x_awg3.conf")
    and core.is_client_file("x_awg2.conf") and not core.is_client_file("x.conf"))

print(f"\nпровалов: {fail}")
sys.exit(1 if fail else 0)
