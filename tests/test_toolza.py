"""
test_toolza.py — проверка собранного awg2 (dist/awg2.sh) без root и без сети.

Функции берутся из самого собранного файла: он подключается в bash как
библиотека (без последней строки «main "$@"»), пути состояния переводятся во
временный каталог, а системные команды (ip, iptables, systemctl, awg...)
подменены заглушками, которые пишут вызовы в журнал.

Что проверяется:
  • генератор параметров AWG 2.0 / 3.0 / 3.1 — инварианты длин, H1-H4,
    таймеры 3.x, совместимость набора ключей с ботом;
  • чтение конфигов прежних версий (метки, версия по ключам, подсеть);
  • встроенный helper.py — клиенты, сроки, замена параметров, Xray, exit-ноды;
  • служебные скрипты (emit_script) — синтаксис и запуск: нет «command not
    found», правила iptables ставятся с нужными метками;
  • разбор iptables-save с комментарием в кавычках.

Запуск:  python3 tests/test_toolza.py [путь/к/dist/awg2.sh]
Выход:   0 — всё прошло, 1 — есть провалы.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
AWG2 = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "..", "dist", "awg2.sh"))
BOT_CORE = os.path.join(HERE, "..", "awg_bot", "awgbot", "core.py")

fails = 0
checks = 0


def chk(label, cond, detail=""):
    global fails, checks
    checks += 1
    if cond:
        print(f"  OK   {label}")
    else:
        fails += 1
        print(f"  FAIL {label}" + (f"\n       {detail}" if detail else ""))


# ── Песочница ─────────────────────────────────────────────
TMP = tempfile.mkdtemp(prefix="awg2-test.")
BIN = os.path.join(TMP, "bin")
os.makedirs(BIN)
CALLS = os.path.join(TMP, "calls.log")
LINKS = os.path.join(TMP, "links")          # «поднятые» интерфейсы, по строке
IPT_SAVE = os.path.join(TMP, "iptables-save.txt")
open(LINKS, "w").close()
open(IPT_SAVE, "w").close()

STUBS = {
    # ip link show X — успех, если X в файле links; остальное — только журнал
    "ip": r'''echo "ip $*" >> "$CALLS"
if [[ "$1" == link && "$2" == show ]]; then grep -qx "${3:-}" "$LINKS"; exit; fi
if [[ "$1" == -4 && "$2" == route && "$3" == show ]]; then echo "default via 192.0.2.1 dev eth0"; exit 0; fi
if [[ "$1" == -4 && "$2" == -o && "$3" == addr ]]; then echo "2: eth0    inet 203.0.113.10/24 brd 203.0.113.255 scope global eth0"; exit 0; fi
if [[ "$1" == rule && "$2" == del ]]; then exit 1; fi
if [[ "$1" == rule && "$2" == show ]]; then exit 0; fi
exit 0''',
    "iptables": r'''echo "iptables $*" >> "$CALLS"
for a in "$@"; do [[ "$a" == -C ]] && exit 1; [[ "$a" == -D ]] && exit 1; done
exit 0''',
    "iptables-save": r'''cat "$IPT_SAVE"''',
    "ip6tables": r'''echo "ip6tables $*" >> "$CALLS"; exit 1''',
    "systemctl": r'''echo "systemctl $*" >> "$CALLS"
[[ "$1" == is-active || "$1" == is-enabled ]] && exit 1
exit 0''',
    "sysctl": r'''echo "sysctl $*" >> "$CALLS"; exit 0''',
    "awg": r'''case "$1" in
  genkey|genpsk) head -c 32 /dev/urandom | base64 ;;
  pubkey) sha256sum | head -c 43; echo "=" ;;
  *) echo "awg $*" >> "$CALLS" ;;
esac
exit 0''',
    "awg-quick": r'''echo "awg-quick $*" >> "$CALLS"
[[ "$1" == strip ]] && printf '[Interface]\nPrivateKey = x\n'
exit 0''',
    "wg": r'''echo "wg $*" >> "$CALLS"; exit 0''',
    "conntrack": r'''exit 0''',
    "ss": r'''exit 0''',
    "curl": r'''for a in "$@"; do [[ "$a" == *http_code* ]] && { echo 204; exit 0; }; done
exit 1''',
    "ufw": r'''exit 1''',
    "modprobe": r'''exit 0''',
}
for name, body in STUBS.items():
    p = os.path.join(BIN, name)
    with open(p, "w") as f:
        f.write("#!/usr/bin/env bash\n" + body + "\n")
    os.chmod(p, 0o755)

LIB = os.path.join(TMP, "lib.sh")
with open(AWG2, encoding="utf-8") as f:
    src = f.read()
assert src.rstrip().endswith('main "$@"'), "последняя строка сборки — main"
with open(LIB, "w", encoding="utf-8") as f:
    f.write(src.rstrip()[: -len('main "$@"')])

ROOT = os.path.join(TMP, "root")
os.makedirs(ROOT)
# Все пути состояния — в песочницу; юниты пишутся в каталог вместо /etc/systemd.
PRELUDE = f'''
source "{LIB}"
AWG_DIR="{ROOT}/etc/amnezia/amneziawg"; SERVER_CONF="$AWG_DIR/awg0.conf"
CLIENT_DIR="{ROOT}/root"; STATE_DIR="{ROOT}/var/lib/awg2"; LOG_FILE="{ROOT}/awg.log"
INSTALL_LOG="{ROOT}/install.log"; EXITS_DIR="$AWG_DIR"
EXITS_PEERS="$EXITS_DIR/exits_peers.list"; EXITS_STATE="$EXITS_DIR/exits_state"
for v in DNS_PERSIST_SCRIPT DNS_HEALTH_SCRIPT CASCADE_SCRIPT T2S_ROUTING_SCRIPT XRAY_ROUTING_SCRIPT \\
         EXITS_SCRIPT EXPIRE_BIN WARP_AUTOSTART_SCRIPT WARP_HEALTH_SCRIPT WGOBF_FW USQUE_UP_HOOK; do
  printf -v "$v" '%s' "{ROOT}/scripts/$v"
done
CASCADE_DIR="{ROOT}/etc/awg-cascade"; CASCADE_RULES="$CASCADE_DIR/rules.conf"; CASCADE_LOG="{ROOT}/cascade.log"
WGOBF_DIR="{ROOT}/etc/awg-wgobf"; WGOBF_STATE="$WGOBF_DIR/state"
EXPIRE_STATE_DIR="{ROOT}/var/lib/awg2-expire"; EXPIRE_LOG="{ROOT}/expire.log"; BOT_CONF="{ROOT}/bot.conf"
WARP_PEERS="{ROOT}/warp.peers"; XRAY_PEERS="{ROOT}/xray.peers"; USQUE_LOG="{ROOT}/usque.log"
write_unit() {{ mkdir -p "{ROOT}/units"; cat > "{ROOT}/units/$1"; }}
remove_unit() {{ :; }}
mkdir -p "$AWG_DIR" "$CLIENT_DIR" "$STATE_DIR" "{ROOT}/scripts"
'''

ENV = dict(os.environ, PATH=BIN + ":" + os.environ["PATH"], CALLS=CALLS, LINKS=LINKS,
           IPT_SAVE=IPT_SAVE, LC_ALL="C.UTF-8")


def bash(code, stdin=None):
    r = subprocess.run(["bash", "-c", PRELUDE + code], input=stdin, capture_output=True,
                       text=True, env=ENV, timeout=300)
    return r.returncode, r.stdout, r.stderr


def run_script(path, *args):
    r = subprocess.run(["bash", path, *args], capture_output=True, text=True, env=ENV, timeout=60)
    return r.returncode, r.stdout, r.stderr


def calls():
    with open(CALLS) as f:
        return f.read()


def reset_calls():
    open(CALLS, "w").close()


def kv(text):
    out = {}
    for line in text.splitlines():
        if " = " in line:
            k, v = line.split(" = ", 1)
            out[k.strip()] = v.strip()
    return out


# ── 1. Генератор параметров ───────────────────────────────
print("Параметры AWG")
BOT_KEYS = set()
if os.path.exists(BOT_CORE):
    m = re.search(r'for key in \(("Jc".*?)\):', open(BOT_CORE, encoding="utf-8").read(), re.S)
    if m:
        BOT_KEYS = set(re.findall(r'"([A-Za-z0-9]+)"', m.group(1)))

N = 120
for proto in ("2.0", "3.0", "3.1"):
    for profile in ("lite", "standard", "pro"):
        rc, out, err = bash(f'MTU=1280; AUTO_MODE=1; for i in $(seq {N}); do gen_awg_params {profile} {proto} || exit 1; echo "$AWG_PARAMS"; echo ---; done')
        sets = [kv(b) for b in out.split("---") if b.strip()]
        label = f"{proto}/{profile}"
        chk(f"{label}: сгенерировано {N}", rc == 0 and len(sets) == N, err[-300:])
        bad = []
        for p in sets:
            S = [int(p[f"S{i}"]) for i in range(1, 5)]
            jc, jmin, jmax = int(p["Jc"]), int(p["Jmin"]), int(p["Jmax"])
            if not (1 <= jc <= 128 and jmin < jmax):
                bad.append(("J", p))
            if S[3] > 32:
                bad.append(("S4>32", p))
            if abs(S[0] + 56 - S[1]) < 10 or abs(S[0] + 84 - S[2]) < 10 or abs(S[1] + 28 - S[2]) < 10:
                bad.append(("S-коллизия", S))
            H = [p[f"H{i}"] for i in range(1, 5)]
            if proto.startswith("3"):
                if min(S) < 12:
                    bad.append(("S<12", S))
                if H != ["1", "2", "3", "4"]:
                    bad.append(("H", H))
                rat = [int(x) for x in p["RekeyAfterTime"].split("-")]
                rjt = [int(x) for x in p["RejectAfterTime"].split("-")]
                if not (rat[0] < rat[1] < rjt[0] < rjt[1]):
                    bad.append(("таймеры", rat, rjt))
                if ("RandomTrailers" in p) != (proto == "3.1") or ("DisableCookies" in p) != (proto == "3.1"):
                    bad.append(("3.1-ключи", sorted(p)))
                if "HeaderProtectionKey" not in p:
                    bad.append(("HPK", sorted(p)))
            else:
                rng = [tuple(int(x) for x in h.split("-")) for h in H]
                flat = [x for r in rng for x in r]
                if flat != sorted(flat) or flat[-1] > 2**31 - 1 or any(b - a < 1000 for a, b in rng):
                    bad.append(("H-диапазоны", H))
                if any(k in p for k in ("HeaderProtectionKey", "RandomTrailers")):
                    bad.append(("3.x-ключи в 2.0", sorted(p)))
            if BOT_KEYS and not set(p) <= BOT_KEYS:
                bad.append(("ключи, которых не знает бот", sorted(set(p) - BOT_KEYS)))
        chk(f"{label}: инварианты", not bad, str(bad[:3]))

rc, out, _ = bash('MTU=1420; AUTO_MODE=1; gen_awg_params pro 3.1 >/dev/null; echo "$MTU"')
chk("MTU 1420 на 3.1 снижается до запаса", rc == 0 and int(out.split()[-1]) < 1420, out)

# ── 2. Конфиги прежних версий ─────────────────────────────
print("Конфиги")
OLD20 = """# AWG_PROFILE=pro
# AmneziaWG Toolza — AWG 2.0 server config
# Region: ru
# AWG_MIMICRY=quic
[Interface]
PrivateKey = sPRIV=
Address = 10.23.45.1/24
ListenPort = 51820
MTU = 1320
Jc = 5
Jmin = 10
Jmax = 90
S1 = 40
S2 = 60
S3 = 20
S4 = 10
H1 = 100-2000
H2 = 536870912-536880000
H3 = 1073741824-1073750000
H4 = 1610612736-1610620000
PostUp = true
PostDown = true

[Peer]
# alice
PublicKey = PUBALICE=
PresharedKey = PSK=
AllowedIPs = 10.23.45.2/32

[Peer]
# bob
# expires=1
PublicKey = PUBBOB=
AllowedIPs = 10.23.45.3/32
"""
os.makedirs(os.path.join(ROOT, "etc/amnezia/amneziawg"), exist_ok=True)
conf = os.path.join(ROOT, "etc/amnezia/amneziawg/awg0.conf")
with open(conf, "w") as f:
    f.write(OLD20)
rc, out, _ = bash('echo "$(server_proto)|$(server_net)|$(server_port)|$(server_region)|$(server_profile)|$(client_suffix)"')
chk("2.0 без метки AWG_PROTO", out.strip() == "2.0|10.23.45.0/24|51820|ru|pro|_awg2", out)
rc, out, _ = bash("clients_tsv")
rows = [r.split("\t") for r in out.strip().splitlines()]
chk("клиенты и метки", [r[0] for r in rows] == ["alice", "bob"] and rows[1][3] == "1", out)
rc, out, _ = bash('conf_marker_set AWG_PROTO 3.1; conf_marker AWG_PROTO; head -3 "$SERVER_CONF"')
chk("метка вставляется в шапку", out.splitlines()[0] == "3.1" and "# AWG_PROTO=3.1" in out, out)
with open(conf, "w") as f:
    f.write(OLD20.replace("H4 = 1610612736-1610620000", "H4 = 4\nHeaderProtectionKey = K=\nRandomTrailers = on"))
rc, out, _ = bash("server_proto")
chk("3.1 по ключам без метки", out.strip() == "3.1", out)

# ── 3. helper.py ──────────────────────────────────────────
print("helper.py")
with open(conf, "w") as f:
    f.write(OLD20)
rc, out, _ = bash('py expire-check "$SERVER_CONF" 127.0.0.2/32 "$EXPIRE_STATE_DIR"; py peers "$SERVER_CONF"')
chk("истёкший клиент блокируется", "EXPIRED\tbob\t10.23.45.3/32" in out and "127.0.0.2/32\t1\t10.23.45.3/32" in out, out)
rc, out, _ = bash('py expire-clear "$SERVER_CONF" bob 127.0.0.2/32; py peers "$SERVER_CONF" | grep bob')
chk("разблокировка возвращает адрес", "10.23.45.3/32\t\t\t" in out, repr(out))
rc, out, _ = bash('py peer-del "$SERVER_CONF" PUBALICE=; grep -c "^\\[Peer\\]" "$SERVER_CONF"')
chk("удаление пира", out.split() == ["alice", "1"], out)
rc, out, _ = bash('printf "Jc = 7\\nS1 = 33\\nH1 = 1\\nHeaderProtectionKey = NEW=\\n" | py params-replace "$SERVER_CONF"; '
                  'sed -n "/^\\[Peer\\]/q;p" "$SERVER_CONF"')
p = kv(out)
chk("замена параметров", p.get("Jc") == "7" and p.get("S1") == "33" and p.get("HeaderProtectionKey") == "NEW="
    and "S2" not in p and p.get("PrivateKey") == "sPRIV=" and p.get("Address") == "10.23.45.1/24", out)

EXIT = os.path.join(TMP, "exit.conf")
with open(EXIT, "w") as f:
    f.write("[Interface]\nPrivateKey = X\nAddress = 10.9.0.2/32\nDNS = 1.1.1.1\nTable = auto\n\n[Peer]\nEndpoint = 1.2.3.4:51820\nAllowedIPs = 0.0.0.0/0\n")
rc, out, _ = bash(f'py exit-conf-fix "{EXIT}"; cat "{EXIT}"')
chk("exit-нода: Table = off, без DNS", "Table = off" in out and "DNS" not in out and "Table = auto" not in out, out)

rc, out, _ = bash('printf "10.10.0.0/16\\n10.20.1.1/24\\n" | py pick-net awg')
net = out.strip()
chk("свободная подсеть", re.match(r"^10\.\d+\.\d+\.0/24$", net) and not net.startswith("10.10.")
    and not net.startswith("10.20.1."), net)
rc, out, _ = bash("py allowed-except 1.2.3.4")
chk("AllowedIPs без адреса сервера", "1.2.3.4/32" not in out and "1.2.3.5/32" in out and out.strip().endswith("::/0"), out[:120])

VLESS = ("vless://11111111-2222-3333-4444-555555555555@ex.example.com:443?type=xhttp&security=reality"
         "&pbk=PBK&sid=ab&sni=www.site.com&fp=chrome&path=%2Fp&mode=auto&flow=#test")
rc, out, _ = bash(f"py xray-link '{VLESS}'")
ob = json.loads(out) if rc == 0 else {}
ss = ob.get("streamSettings", {})
chk("vless reality + xhttp", ob.get("protocol") == "vless" and ss.get("network") == "xhttp"
    and ss.get("realitySettings", {}).get("publicKey") == "PBK" and ss.get("xhttpSettings", {}).get("path") == "/p", out)
XC = os.path.join(TMP, "xray.json")
rc, out, err = bash(f'''py xray-default "{XC}"
py xray-link '{VLESS}' | py xray-add "{XC}"
py xray-link '{VLESS.replace("ex.example.com", "two.example.com")}' | py xray-add "{XC}"
py xray-prepare "{XC}" tun2socks
py xray-balancer "{XC}" leastPing
py xray-ru "{XC}" on
cat "{XC}"''')
xc = json.loads(out) if rc == 0 else {}
rules = xc.get("routing", {}).get("rules", [])
chk("Xray: два выхода, балансировщик, РФ напрямую",
    len([o for o in xc.get("outbounds", []) if o["protocol"] == "vless"]) == 2
    and xc["routing"]["balancers"][0]["strategy"]["type"] == "leastPing"
    and sum(1 for r in rules if r.get("ruleTag") == "ru-direct") == 2
    and rules[-1].get("balancerTag") == "balancer"
    and all(i.get("protocol") != "tun" for i in xc["inbounds"]), err or out[:300])
rc, out, _ = bash(f'py xray-del "{XC}" proxy_two_example_com; py xray-prepare "{XC}" native; cat "{XC}"')
xc = json.loads(out)
chk("Xray: удаление выхода чинит балансировщик", not xc["routing"].get("balancers")
    and any(i.get("protocol") == "tun" for i in xc["inbounds"])
    and all(r.get("outboundTag") != "proxy_two_example_com" for r in xc["routing"]["rules"]), out[:300])

# ── 4. Служебные скрипты ──────────────────────────────────
print("Служебные скрипты")
with open(conf, "w") as f:
    f.write(OLD20)
with open(LINKS, "w") as f:
    f.write("awg0\ntun0\nxray0\nwarp0\nawg-exit-de\nawg-exit-nl\n")
os.makedirs(os.path.join(ROOT, "etc/awg-cascade"), exist_ok=True)
with open(os.path.join(ROOT, "etc/awg-cascade/rules.conf"), "w") as f:
    f.write("udp|443|5.6.7.8|443|de\ntcp|8443|5.6.7.8|443|\n")
for n in ("de", "nl"):
    open(os.path.join(ROOT, f"etc/amnezia/amneziawg/awg-exit-{n}.conf"), "w").close()
with open(os.path.join(ROOT, "etc/amnezia/amneziawg/exits_state"), "w") as f:
    f.write("active\nmode=peers\nbalancer=ecmp\nsingle_exit=\n")
with open(os.path.join(ROOT, "etc/amnezia/amneziawg/exits_peers.list"), "w") as f:
    f.write("10.23.45.2|nl\n10.23.45.3\n")
os.makedirs(os.path.join(ROOT, "etc/awg-wgobf"), exist_ok=True)
with open(os.path.join(ROOT, "etc/awg-wgobf/state"), "w") as f:
    f.write("NET=10.77.1.0/24\nWG_PORT=40001\nPORT=40000\n")
with open(os.path.join(TMP, "warp0.conf"), "w") as f:
    f.write("[Interface]\nPrivateKey = P\nAddress = 172.16.0.2/32, 2606::1/128\nMTU = 1280\n[Peer]\nPublicKey = Q\nEndpoint = 162.159.192.1:2408\n")

rc, out, err = bash(f'''
WARP_CONF="{TMP}/warp0.conf"
_dns_emit_helpers && _cascade_persist && _exits_write_unit && expire_install >/dev/null
emit_script "$T2S_ROUTING_SCRIPT" 't2s_routing_run "$@"' T2S_IF T2S_TABLE T2S_ADDR "${{RT_FUNCS[@]}}" t2s_routing_run
emit_script "$XRAY_ROUTING_SCRIPT" 'xray_routing_run "$@"' XRAY_IF XRAY_TABLE XRAY_PEERS XRAY_TUN_ADDR XRAY_SOCKS socks_probe "${{RT_FUNCS[@]}}" xray_routing_run
emit_script "$WGOBF_FW" 'wgobf_fw_run "$@"' WGOBF_STATE WGOBF_TAG WGOBF_IF ipt_del_grep ipt_del_tagged wgobf_get wgobf_fw_run
emit_script "$WARP_AUTOSTART_SCRIPT" 'warp_wg_bringup' WARP_CONF WARP_IF WARP_TABLE WARP_PEERS "${{RT_FUNCS[@]}}" warp_wg_bringup
emit_script "$WARP_HEALTH_SCRIPT" 'warp_health_run' WARP_IF WARP_TABLE WARP_STATE WARP_BACKEND_FILE WARP_HEALTH_LOG "${{RT_FUNCS[@]}}" warp_health_run
emit_script "$USQUE_UP_HOOK" 'usque_on_connect' WARP_IF WARP_TABLE WARP_PEERS USQUE_LOG "${{RT_FUNCS[@]}}" usque_on_connect
ls "{ROOT}/scripts"''')
scripts = out.split()
chk("скрипты сгенерированы", rc == 0 and len(scripts) == 11, err + out)
for s in scripts:
    r = subprocess.run(["bash", "-n", os.path.join(ROOT, "scripts", s)], capture_output=True, text=True)
    chk(f"bash -n {s}", r.returncode == 0, r.stderr)

SCR = lambda n: os.path.join(ROOT, "scripts", n)
NOT_FOUND = re.compile(r"command not found|unbound variable")


def run_and_check(label, script, *args, must=(), must_not=()):
    reset_calls()
    rc, out, err = run_script(SCR(script), *args)
    log = calls()
    missing = [m for m in must if not re.search(m, log)]
    present = [m for m in must_not if re.search(m, log)]
    chk(label, not NOT_FOUND.search(err) and not missing and not present,
        f"rc={rc} err={err.strip()[-300:]} нет: {missing} лишнее: {present}")


run_and_check("DNS: перехват и блок DoT в mangle", "DNS_PERSIST_SCRIPT",
              must=[r"-t nat -A PREROUTING -i awg0 -p udp --dport 53 -j DNAT --to-destination 127\.0\.2\.1:53 -m comment --comment awg2-dns",
                    r"-t mangle -A PREROUTING -i awg0 -p tcp --dport 853 -j DROP -m comment --comment awg2-dns",
                    r"-t filter -I INPUT 1 -i awg0 -d 127\.0\.2\.1"])
run_and_check("DNS: health-check", "DNS_HEALTH_SCRIPT", must=[r"-t nat -A PREROUTING"])
run_and_check("Каскад: только адреса сервера, туда и обратно", "CASCADE_SCRIPT",
              must=[r"-t nat -A PREROUTING -p udp --dport 443 -m addrtype --dst-type LOCAL -j DNAT --to-destination 5\.6\.7\.8:443 -m comment --comment awg-cascade:udp-443",
                    r"-I FORWARD 1 -p tcp -s 5\.6\.7\.8 --sport 443 -j ACCEPT -m comment --comment awg-cascade:tcp-8443"])
run_and_check("tun2socks: вся подсеть в таблицу 100", "T2S_ROUTING_SCRIPT", "start",
              must=[r"ip rule add from 10\.23\.45\.0/24 lookup 100 priority 100", r"MASQUERADE -m comment --comment awg2-tun-tun0"])
run_and_check("Xray: клиенты из списка в таблицу 201", "XRAY_ROUTING_SCRIPT", "start",
              must=[r"ip route replace default dev xray0 table 201"])
run_and_check("Exit-ноды: ECMP и персональная нода", "EXITS_SCRIPT", "start",
              must=[r"nexthop dev awg-exit-de weight 1 nexthop dev awg-exit-nl weight 1",
                    r"ip route replace default dev awg-exit-nl table 211",
                    r"ip rule add from 10\.23\.45\.2 lookup 211 priority 202",
                    r"ip rule add from 10\.23\.45\.3 lookup 202 priority 202"])
run_and_check("Exit-ноды: остановка", "EXITS_SCRIPT", "stop", must_not=[r"-A "])
run_and_check("WG+обфускатор: правила по метке", "WGOBF_FW", "up",
              must=[r"-I INPUT 1 -p udp --dport 40001 ! -i lo -j DROP -m comment --comment awg-wgobf",
                    r"-t nat -A POSTROUTING -s 10\.77\.1\.0/24 ! -o wgobf0 -j MASQUERADE"])
run_and_check("usque on-connect", "USQUE_UP_HOOK", must=[r"table 200"])
run_and_check("Сроки клиентов", "EXPIRE_BIN", must=[r"awg-quick strip awg0"])
with open(conf) as f:
    chk("истёкший клиент заблокирован скриптом таймера", "AllowedIPs = 127.0.0.2/32" in f.read())
with open(LINKS, "w") as f:
    f.write("awg0\n")
run_and_check("WARP: подъём warp0 только с IPv4", "WARP_AUTOSTART_SCRIPT",
              must=[r"ip link add dev warp0 type wireguard", r"ip -4 addr add 172\.16\.0\.2/32 dev warp0",
                    r"ip route replace default dev warp0 src 172\.16\.0\.2 table 200"],
              must_not=[r"2606::1"])

# ── 5. Разбор iptables-save ───────────────────────────────
print("iptables-save")
with open(IPT_SAVE, "w") as f:
    f.write('-A PREROUTING -p udp -m udp --dport 443 -m addrtype --dst-type LOCAL -m comment --comment "awg-cascade:udp-443" -j DNAT --to-destination 5.6.7.8:443\n'
            '-A PREROUTING -p udp -m udp --dport 4430 -m comment --comment "awg-cascade:udp-4430" -j DNAT --to-destination 5.6.7.8:4430\n'
            '-A POSTROUTING -s 10.0.0.0/24 -o tun0 -m comment --comment awg2-tun-tun0 -j MASQUERADE\n')
reset_calls()
bash("cascade_unapply udp 443")
log = calls()
chk("правило с комментарием в кавычках удаляется, соседнее — нет",
    "-D PREROUTING -p udp -m udp --dport 443 -m addrtype --dst-type LOCAL -m comment --comment awg-cascade:udp-443 -j DNAT" in log
    and "4430" not in log, log)
reset_calls()
bash("rt_fw_down tun0")
chk("метка туннеля", "-t nat -D POSTROUTING -s 10.0.0.0/24 -o tun0 -m comment --comment awg2-tun-tun0 -j MASQUERADE" in calls(), calls())

# ── 6. CLI без root ───────────────────────────────────────
print("CLI")
r = subprocess.run(["bash", AWG2, "--version"], capture_output=True, text=True)
chk("--version", r.returncode == 0 and r.stdout.startswith("awg2 v"), r.stdout + r.stderr)
r = subprocess.run(["bash", AWG2, "--help"], capture_output=True, text=True)
chk("--help", r.returncode == 0 and "--tunnel" in r.stdout and "--wgobf" in r.stdout, r.stderr)
head = open(AWG2, encoding="utf-8").read(4096)
chk("VERSION в первых 4 КБ (самообновление и бот)", re.search(r'^VERSION="v\d+\.\d+\.\d+"$', head, re.M) is not None)

# ── 7. Машинный API (awg2 api) ────────────────────────────
print("API")
# Обёртка вместо установленного awg2: те же функции, пути — песочница.
# systemd-run «нет» — задачи идут запасным путём через setsid.
API_WRAP = os.path.join(TMP, "awg2-api")
with open(API_WRAP, "w") as f:
    f.write("#!/usr/bin/env bash\n" + PRELUDE + '[[ "${1:-}" == api ]] && shift\napi_main "$@"\n')
os.chmod(API_WRAP, 0o755)
with open(os.path.join(BIN, "systemd-run"), "w") as f:
    f.write("#!/usr/bin/env bash\nexit 1\n")
os.chmod(os.path.join(BIN, "systemd-run"), 0o755)
with open(conf, "w") as f:
    f.write(OLD20)
for n in ("alice", "bob"):
    with open(os.path.join(ROOT, "root", n + "_awg2.conf"), "w") as f:
        f.write("[Interface]\nPrivateKey = X\n")


def api(*args, stdin=None, env=None):
    # stdin — открытый пайп: API обязан не ждать его без нужды
    r = subprocess.run([API_WRAP, *args], input=stdin, capture_output=True, text=True,
                       env=dict(ENV, **(env or {})), timeout=120)
    lines = r.stdout.strip().splitlines()
    try:
        res = json.loads(lines[-1]) if len(lines) == 1 else {"raw": r.stdout}
    except ValueError:
        res = {"raw": r.stdout}
    res["_rc"] = r.returncode
    res["_err"] = r.stderr
    return res


r = api("version")
chk("api version — одна строка JSON", r.get("ok") is True and r["data"]["version"].startswith("v")
    and r["data"]["api"] == 1, r)
r = api("status")
d = r.get("data") or {}
chk("api status", r.get("ok") and d["server"]["exists"] and d["server"]["clients"] == 2
    and d["server"]["proto"] == "2.0" and d["tunnels"]["warp"] == "none", r)
r = api("clients", "list")
rows = r.get("data") or []
chk("api clients list", [c["name"] for c in rows] == ["alice", "bob"] and rows[0]["ip"] == "10.23.45.2"
    and rows[0]["file"].endswith("alice_awg2.conf") and rows[1]["expires"] == 1 and rows[0]["warp"] is None, r)
r = api("client", "add", "carol", "expire=+1d", "mimicry=none")
d = r.get("data") or {}
chk("api client add", r.get("ok") and d.get("name") == "carol" and "[Interface]" in d.get("text", ""), r)
r = api("client", "add", "carol", "mimicry=none")
chk("занятое имя — ошибка с текстом", r.get("ok") is False and r["rc"] == 1 and "carol" in r["error"], r)
rows = api("clients", "list").get("data") or []
carol = next((c for c in rows if c["name"] == "carol"), {})
chk("срок клиента", carol.get("expires", 0) > 1e9 and carol.get("mimicry") == "none", carol)
r = api("client", "rename", "carol", "dave")
chk("api client rename", r.get("ok") and os.path.exists(os.path.join(ROOT, "root", "dave_awg2.conf")), r)
r = api("client", "del", "dave")
chk("api client del", r.get("ok") and not os.path.exists(os.path.join(ROOT, "root", "dave_awg2.conf")), r)
r = api("clients", "bulk", "t:3", "mimicry=none")
chk("api clients bulk", r.get("ok") and r["data"] == ["t-001", "t-002", "t-003"], r)
r = api("tunnels", "clients", "warp")
chk("клиенты туннеля без списка — все", r.get("ok") and len(r["data"]) == 5 and all(c["on"] for c in r["data"]), r)
api("tunnels", "client", "warp", "none")
r = api("tunnels", "client", "warp", "alice", "on")
rows = api("tunnels", "clients", "warp").get("data") or []
chk("выбор клиентов туннеля", [c["name"] for c in rows if c["on"]] == ["alice"], rows)
r = api("mimicry")
chk("api mimicry", r.get("ok") and len(r["data"]) == 9 and r["data"][0]["id"] == "quic" and r["data"][0]["domain"], r)
r = api("cascade", "add", "udp", "4443", "5.6.7.8", "443", "тест")
rule = next((x for x in api("cascade", "list").get("data") or [] if x["in"] == 4443), {})
chk("api cascade add/list", r.get("ok") and rule.get("out") == 443 and rule.get("proto") == "udp"
    and rule.get("comment") == "тест", [r, rule])
r = api("exits", "add", "n1", stdin="")
chk("stdin обязателен для exits add", r.get("ok") is False and "stdin" in r["error"], r)
r = api("exits", "add", "n1", stdin="[Interface]\nPrivateKey = X\n")
chk("конфиг ноды читается из stdin", r.get("ok") is False and "Endpoint" in r["error"], r)
rfd, wfd = os.pipe()          # пишущий конец держим открытым до конца вызова
try:
    out = subprocess.run([API_WRAP, "version"], stdin=rfd, capture_output=True, text=True,
                         env=ENV, timeout=60).stdout
except subprocess.TimeoutExpired:
    out = "завис на чтении stdin"
os.close(rfd)
os.close(wfd)
chk("открытый stdin не блокирует команду", '"ok": true' in out, out)
r = api("frobnicate")
chk("неизвестная команда — rc 2", r.get("ok") is False and r["rc"] == 2, r)
r = api("server", "proto", "9.9")
chk("проверка аргументов", r.get("ok") is False and r["rc"] == 2 and "server proto" in r["error"], r)

# Очередь: пока занят замок, изменяющая команда отказывает, чтение — нет
lock = os.path.join(ROOT, "var/lib/awg2/api.lock")
holder = subprocess.Popen(["flock", lock, "sleep", "8"])
import time
time.sleep(0.5)
r = api("client", "del", "t-001", env={"API_LOCK_WAIT": "1"})
chk("занятая очередь — rc 75", r.get("ok") is False and r["rc"] == 75 and "другая операция" in r["error"], r)
r = api("clients", "list")
chk("чтение мимо очереди", r.get("ok") is True, r)
holder.kill()
holder.wait()

# Фоновая задача: старт, опрос журнала по смещению, итог
r = api("job", "start", "diag", "dpi-hint")
jid = (r.get("data") or {}).get("id", "")
chk("api job start", r.get("ok") and re.match(r"^\d{8}-\d{6}-[0-9a-f]{4}$", jid), r)
st, log, off = {}, "", 0
for _ in range(60):
    st = api("job", "status", jid, str(off)).get("data") or {}
    log += st.get("log", "")
    off = st.get("offset", off)
    if st.get("state") != "running":
        break
    time.sleep(0.5)
chk("задача завершилась", st.get("state") == "done" and st.get("ok") is True and st.get("rc") == 0, st)
chk("журнал задачи без цвета", "dpi-detector" in log and "\x1b[" not in log, log[:200])
r = api("job", "list")
chk("api job list", r.get("ok") and r["data"] and r["data"][0]["id"] == jid and r["data"][0]["state"] == "done", r)
r = api("job", "start", "bogus")
jid = (r.get("data") or {}).get("id", "")
for _ in range(60):
    st = api("job", "status", jid).get("data") or {}
    if st.get("state") != "running":
        break
    time.sleep(0.5)
chk("ошибка задачи в итоге", st.get("state") == "done" and st.get("ok") is False and st.get("rc") == 2, st)

shutil.rmtree(TMP, ignore_errors=True)
print(f"\nпроверок: {checks}, провалов: {fails}")
sys.exit(1 if fails else 0)
