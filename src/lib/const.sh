# Пути и константы. Все имена файлов совпадают с прежними версиями awg2:
# новая версия подхватывает уже работающий сервер без миграции.

SCRIPT_PATH="/usr/local/bin/awg2"
STATE_DIR="/var/lib/awg2"
LOG_FILE="/var/log/awg-manager.log"
INSTALL_LOG="/var/log/awg2-install.log"

# ── AmneziaWG ─────────────────────────────────────────────
AWG_DIR="/etc/amnezia/amneziawg"
SERVER_CONF="$AWG_DIR/awg0.conf"
AWG_IF="awg0"
CLIENT_DIR="/root"                 # клиенты: /root/<имя>_awg2.conf | _awg3.conf
AUTOSTART_DROPIN="/etc/systemd/system/awg-quick@awg0.service.d"
MODULES_LOAD_FILE="/etc/modules-load.d/amneziawg.conf"
SYSCTL_FORWARD_FILE="/etc/sysctl.d/99-awg2.conf"

# Компоненты собираются из исходников апстрима через git + DKMS.
MOD_REPO="https://github.com/amnezia-vpn/amneziawg-linux-kernel-module.git"
TOOLS_REPO="https://github.com/amnezia-vpn/amneziawg-tools.git"
MOD_NAME="amneziawg"
MOD_DKMS_VER="1.0.0"               # апстрим держит 1.0.0 во всех тегах
MOD_SRC_DIR="/usr/src/${MOD_NAME}-${MOD_DKMS_VER}"
MOD_TAG_FILE="$STATE_DIR/module_tag"
TOOLS_TAG_FILE="$STATE_DIR/tools_tag"
MOD_BACKUP_DIR="/var/backups/awg-mod"
MOD_LOG="/var/log/awg-mod-update.log"
MOD_FALLBACK_TAG="v3.1.20260906"
UPSTREAM_CACHE="$STATE_DIR/upstream_tags"
UPSTREAM_TTL=21600

# ── Обновление скрипта ────────────────────────────────────
UPDATE_REPO_STABLE="pumbaX/awg-multi-script"
UPDATE_REPO_BETA="genaRijoff/awg-multi-script"
UPDATE_CHANNEL_FILE="$STATE_DIR/channel"
UPDATE_CHECK_TTL=21600

# ── Бэкапы ────────────────────────────────────────────────
# В домашнем каталоге того, кто запустил sudo: так было всегда, и уже
# сделанные бэкапы лежат именно там.
_real_home() {
  local u home=""
  u=$(logname 2>/dev/null || echo "${SUDO_USER:-}")
  [[ -n "$u" ]] && home=$(getent passwd "$u" | cut -d: -f6)
  echo "${home:-/root}"
}
BACKUP_DIR="$(_real_home)/awg_backup"

# ── Туннели ───────────────────────────────────────────────
# Номера таблиц маршрутизации — общие для всех версий awg2.
T2S_TABLE=100
WARP_TABLE=200
XRAY_TABLE=201
EXITS_TABLE=202
EXITS_TABLE_BASE=210
EXITS_TABLE_MAX=249

WARP_IF="warp0"
WARP_DIR="/etc/wgcf"
WARP_CONF="/etc/wireguard/warp0.conf"
WARP_ACCOUNT="$WARP_DIR/wgcf-account.toml"
WARP_PROFILE="$WARP_DIR/wgcf-profile.conf"
WARP_STATE="$WARP_DIR/state"
WARP_PEERS="$WARP_DIR/peers.list"
WARP_BACKEND_FILE="/etc/awg-warp-backend"
WARP_AUTOSTART_SCRIPT="$WARP_DIR/warp-autostart.sh"
WARP_HEALTH_SCRIPT="/usr/local/bin/awg-warp-healthcheck.sh"
WARP_HEALTH_LOG="/var/log/awg-warp-health.log"
WARPSCOUT_BIN="/usr/local/bin/warpscout"
WARPSCOUT_DIR="/etc/warpscout"
WARPSCOUT_ACCOUNT="$WARPSCOUT_DIR/warpscout-account.json"
USQUE_DIR="/etc/usque"
USQUE_CONF="$USQUE_DIR/config.json"
USQUE_BIN="/usr/local/bin/usque"
USQUE_UP_HOOK="$USQUE_DIR/on-connect.sh"
USQUE_DOWN_HOOK="$USQUE_DIR/on-disconnect.sh"
USQUE_SYSCTL="/etc/sysctl.d/99-awg-usque.conf"
USQUE_LOG="/var/log/awg-usque.log"
USQUE_FALLBACK_VER="4.2.1"
WGCF_FALLBACK_VERS=(2.2.30 2.2.29 2.2.28)

DNS_PROXY_ADDR="127.0.2.1"
DNS_PROXY_PORT=53
DNS_PROXY_CONF="/etc/dnscrypt-proxy/dnscrypt-proxy.toml"
DNS_PROXY_STATE="/etc/dnscrypt-proxy/awg.state"
DNS_PROXY_BACKUP_CONF="/etc/dnscrypt-proxy/dnscrypt-proxy.toml.awg-backup"
DNS_PERSIST_SCRIPT="/usr/local/bin/awg-dns-persist.sh"
DNS_HEALTH_SCRIPT="/usr/local/bin/awg-dns-healthcheck.sh"
DNS_HEALTH_LOG="/var/log/awg-dns-health.log"
DNS_SYSCTL="/etc/sysctl.d/99-awg-dns.conf"

CASCADE_DIR="/etc/awg-cascade"
CASCADE_RULES="$CASCADE_DIR/rules.conf"
CASCADE_TAG="awg-cascade"
CASCADE_SCRIPT="/usr/local/bin/awg-cascade-apply.sh"
CASCADE_LOG="/var/log/awg-cascade.log"
CASCADE_UFW_BACKUP="$CASCADE_DIR/ufw-backup/ufw.default.original"

XRAY_DIR="/etc/xray"
XRAY_CONF="$XRAY_DIR/config.json"
XRAY_STATE="$XRAY_DIR/state"
XRAY_PEERS="$XRAY_DIR/peers.list"
XRAY_BIN="/usr/local/bin/xray"
XRAY_ASSET_DIR="/usr/local/bin"
XRAY_IF="xray0"
XRAY_TUN_ADDR="172.16.250.1/30"
XRAY_SOCKS="127.0.0.1:10808"
XRAY_UNIT="awg-xray.service"
XRAY_TUN_UNIT="awg-xray-tun.service"
XRAY_ROUTING_UNIT="awg-xray-routing.service"
XRAY_ROUTING_SCRIPT="/usr/local/bin/awg2-xray-routing.sh"
XRAY_RUGEO_URL="https://github.com/runetfreedom/russia-v2ray-rules-dat/releases/latest/download"

T2S_BIN="/usr/local/bin/tun2socks"
T2S_DIR="/etc/tun2socks"
T2S_CONF="$T2S_DIR/proxy.txt"
T2S_IF="tun0"
T2S_ADDR="10.30.1.1/24"
T2S_UNIT="awg-tun2socks.service"
T2S_ROUTING_SCRIPT="/usr/local/bin/awg2-tun2socks-routing.sh"

EXITS_DIR="$AWG_DIR"
EXITS_PEERS="$EXITS_DIR/exits_peers.list"
EXITS_STATE="$EXITS_DIR/exits_state"
EXITS_UNIT="awg-exits-routing.service"
EXITS_SCRIPT="/usr/local/bin/awg2-exits-routing.sh"

# ── Срок действия клиентов ────────────────────────────────
EXPIRE_BIN="/usr/local/bin/awg2-expire-check"
EXPIRE_SERVICE="/etc/systemd/system/awg2-expire.service"
EXPIRE_TIMER="/etc/systemd/system/awg2-expire.timer"
EXPIRE_STATE_DIR="/var/lib/awg2-expire"
EXPIRE_LOG="/var/log/awg2-expire.log"
EXPIRE_SUSPEND_IP="127.0.0.2/32"

# ── WG + обфускатор ───────────────────────────────────────
WGOBF_VERSION="v1.6"
WGOBF_COMMIT="6440304054a27158b6d373545925880f0e51bafb"
WGOBF_REPO="https://github.com/ClusterM/wg-obfuscator.git"
WGOBF_IF="wgobf0"
WGOBF_DIR="/etc/awg-wgobf"
WGOBF_STATE="$WGOBF_DIR/state"
WGOBF_OBF_CONF="$WGOBF_DIR/obfuscator.conf"
WGOBF_WG_CONF="/etc/wireguard/${WGOBF_IF}.conf"
WGOBF_LIB="/usr/local/lib/awg2"
WGOBF_BIN="$WGOBF_LIB/wg-obfuscator"
WGOBF_FW="$WGOBF_LIB/wgobf-fw.sh"
WGOBF_UNIT="awg-wgobf.service"
WGOBF_CLIENTS="/root/wgobf"
WGOBF_TAG="awg-wgobf"
WGOBF_MTU=1380

# ── Telegram-бот ──────────────────────────────────────────
BOT_CONF="/etc/awg-bot.conf"
BOT_ADMINS="/var/lib/awg-bot/admins.json"   # приглашённые админы (ведёт бот)
BOT_DIR="/opt/awg-bot"
BOT_UNIT="awg-bot.service"
BOT_PROXY_SCHEMES="http https socks4 socks5 socks5h iface"
WEBAPP_PORT_DEFAULT=8443                    # Mini App бота (WEBAPP_PORT в BOT_CONF)

# ── HTTPS-сертификат (Let's Encrypt через acme.sh) ───────
CERT_DIR="/etc/awg2/cert"
CERT_FULL="$CERT_DIR/fullchain.pem"
CERT_KEY="$CERT_DIR/key.pem"
CERT_STATE="$STATE_DIR/cert"                # kind=ip|domain, name=адрес
ACME_DIR="/usr/local/lib/awg2/acme.sh"      # код acme.sh
ACME_HOME="/var/lib/awg2/acme"              # аккаунт и сертификаты acme.sh
CERT_SERVICE="awg2-cert.service"
CERT_TIMER="awg2-cert.timer"
CERT_TAG="awg2-cert"

# Интерфейсы, которые поднимает сам awg2: их адрес не может быть Endpoint
# клиента, и маршрут через них — не аплинк сервера.
OWN_IFACES=" awg0 warp0 xray0 tun0 wgcf wgobf0 "
# GitHub в части сетей режут — релизы качаются и через зеркала.
GH_MIRRORS=("" "https://ghproxy.net/" "https://gh-proxy.com/" "https://mirror.ghproxy.com/")
