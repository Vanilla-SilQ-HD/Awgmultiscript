"""
test_wgobf.py — режим «WG + обфускатор» (пункт 9 awg2).

Проверяет то, что ломается тихо и бьёт по клиентам:
  • AllowedIPs «весь интернет, кроме IP сервера»: IP сервера не должен
    попасть в туннель (иначе петля — пакеты обфускатора уходят в сам
    туннель), а весь остальной IPv4 — должен (иначе трафик идёт мимо VPN);
  • удаление клиента вырезает ровно его [Peer] и не трогает соседей;
  • подсеть не пересекается с занятыми (AWG, маршруты), а при занятом 10/8
    уходит в запасной диапазон.

Функции берутся из настоящего awg2.sh, а не копируются.

Запуск:  python3 tests/test_wgobf.py [путь/к/awg2.sh]
Выход:   0 — всё сошлось, 1 — есть провалы.
"""
import ipaddress
import os
import re
import subprocess
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
AWG2 = os.path.abspath(sys.argv[1] if len(sys.argv) > 1
                       else os.path.join(_HERE, "..", "awg2.sh"))
SRC = open(AWG2, encoding="utf-8", errors="replace").read()

fails = 0
checks = 0


def chk(label, ok, detail=""):
    global fails, checks
    checks += 1
    if ok:
        print(f"  OK   {label}")
    else:
        fails += 1
        print(f"  FAIL {label}" + (f"\n       {detail}" if detail else ""))


def bash_fn(name):
    m = re.search(rf"^{name}\(\) \{{.*?^\}}$", SRC, re.S | re.M)
    if not m:
        raise SystemExit(f"функция {name} не найдена в {AWG2}")
    return m.group(0)


def run(script):
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


# ── AllowedIPs ──────────────────────────────────────────────
print("AllowedIPs без IP сервера")
for srv in ("198.51.100.2", "1.2.3.4", "255.255.255.254", "0.0.0.1"):
    rc, out, err = run(bash_fn("_wgobf_allowed_ips") + f'\n_wgobf_allowed_ips "{srv}"')
    chk(f"{srv}: команда отработала", rc == 0, err)
    parts = [p.strip() for p in out.split(",")]
    chk(f"{srv}: в конце ::/0 (IPv6 не течёт мимо туннеля)", parts[-1] == "::/0", out[-40:])
    v4 = [ipaddress.ip_network(p) for p in parts if ":" not in p]
    ip = ipaddress.ip_address(srv)
    chk(f"{srv}: IP сервера не в туннеле", not any(ip in n for n in v4))
    total = sum(n.num_addresses for n in v4)
    chk(f"{srv}: покрыт весь остальной IPv4", total == 2**32 - 1, f"адресов: {total}")
    chk(f"{srv}: без пересечений",
        all(not a.overlaps(b) for i, a in enumerate(v4) for b in v4[i + 1:]))

# ── удаление клиента ───────────────────────────────────────
print("Удаление клиента из конфига")
TMP = tempfile.mkdtemp(prefix="awg-wgobf-test.")
conf = os.path.join(TMP, "wgobf0.conf")
state_dir = os.path.join(TMP, "st")
os.makedirs(state_dir)
with open(conf, "w") as f:
    f.write("# шапка\n[Interface]\nPrivateKey = K\nAddress = 10.60.1.1/24\n"
            "ListenPort = 40000\n\n"
            "[Peer]\n# client=a\nPublicKey = PA\nAllowedIPs = 10.60.1.2/32\n\n"
            "[Peer]\n# client=b\nPublicKey = PB\nAllowedIPs = 10.60.1.3/32\n\n"
            "[Peer]\n# client=ab\nPublicKey = PAB\nAllowedIPs = 10.60.1.4/32\n")
stubs = "\n".join([
    "err() { echo \"ERR $*\" >&2; }", "ok() { :; }", "warn() { :; }",
    "log_info() { :; }",
    # интерфейса нет — _wgobf_sync ничего не применяет
    "ip() { return 1; }",
])
script = "\n".join([
    stubs,
    f'WGOBF_WG_CONF="{conf}"', f'WGOBF_DIR="{state_dir}"',
    f'WGOBF_CLIENTS="{TMP}/clients"', 'WGOBF_IFACE=wgobf0',
    bash_fn("_wgobf_client_names"), bash_fn("_wgobf_sync"),
    bash_fn("_wgobf_delete_client"),
    "_wgobf_delete_client b && _wgobf_client_names",
])
rc, out, err = run(script)
chk("удаление b прошло", rc == 0, err)
chk("остались a и ab (ab не спутан с a/b)", out.split() == ["a", "ab"], out)
text = open(conf).read()
chk("ключ b вычищен", "PB" not in text)
chk("[Interface] и шапка на месте", text.startswith("# шапка\n[Interface]\n"), text[:40])
chk("нет двойных пустых строк", "\n\n\n" not in text)
rc, out, err = run(script.replace("_wgobf_delete_client b &&",
                                  "_wgobf_delete_client nope;"))
chk("несуществующий клиент — ошибка без правки", rc == 0 and "ERR" in err
    and open(conf).read() == text, err)

# ── подсеть ────────────────────────────────────────────────
print("Выбор подсети")
fn = bash_fn("_wgobf_pick_net")


def pick(routes):
    # ip подменён: отдаёт «маршруты сервера»
    s = "\n".join([
        f'ip() {{ printf "%s\\n" "{routes}"; }}',
        f'SERVER_CONF="{TMP}/awg0.conf"',
        fn, "_wgobf_pick_net",
    ])
    return run(s)


with open(os.path.join(TMP, "awg0.conf"), "w") as f:
    f.write("[Interface]\nAddress = 10.45.12.1/24\n")
ok_all, last = True, ""
for _ in range(20):
    rc, out, _e = pick("default via 192.0.2.1 dev eth0\\n192.0.2.0/24 dev eth0")
    last = out
    net = ipaddress.ip_network(out) if rc == 0 else None
    if not (net and net.prefixlen == 24
            and net.subnet_of(ipaddress.ip_network("10.0.0.0/8"))
            and not net.overlaps(ipaddress.ip_network("10.45.12.0/24"))
            and not net.overlaps(ipaddress.ip_network("10.30.1.0/24"))):
        ok_all = False
        break
chk("обычно — /24 из 10/8, мимо AWG и tun2socks (20 прогонов)", ok_all, last)
rc, out, _e = pick("10.0.0.0/8 dev eth1")
net = ipaddress.ip_network(out) if rc == 0 else None
chk("10/8 занят — запасной диапазон", net is not None
    and not net.overlaps(ipaddress.ip_network("10.0.0.0/8")), out)
chk("запасной не задевает WARP/Xray (172.16.0/250)", net is not None
    and not net.overlaps(ipaddress.ip_network("172.16.0.0/24"))
    and not net.overlaps(ipaddress.ip_network("172.16.250.0/24")), out)
rc, out, _e = pick("10.0.0.0/8 dev a\\n172.16.0.0/12 dev b\\n192.168.0.0/16 dev c")
chk("всё занято — отказ, а не пересечение", rc != 0 and out == "", out)

print(f"\nпроверок: {checks}, провалов: {fails}")
sys.exit(1 if fails else 0)
