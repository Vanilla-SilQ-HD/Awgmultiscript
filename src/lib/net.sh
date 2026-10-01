# Сеть: проверка адресов, аплинк, публичный IP, порты, домены.

valid_ip() {
  local ip="$1" o
  [[ "$ip" =~ ^([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})$ ]] || return 1
  for o in "${BASH_REMATCH[@]:1}"; do (( 10#$o <= 255 )) || return 1; done
}

valid_cidr() {
  [[ "$1" == */* ]] || return 1
  local mask="${1#*/}"
  valid_ip "${1%/*}" && [[ "$mask" =~ ^(0|[1-9][0-9]?)$ ]] && (( mask <= 32 ))
}

# Без ведущих нулей: «0080» и «/08» — не восьмеричные числа и не ошибка
# арифметики, а отказ; иначе такое значение легло бы в конфиги как есть.
valid_port() { [[ "$1" =~ ^[1-9][0-9]{0,4}$ ]] && (( $1 <= 65535 )); }

# Имя хоста (не IP): метки из букв, цифр и дефисов, минимум одна точка.
valid_domain() {
  local d="$1"
  [[ -n "$d" && ${#d} -le 253 ]] || return 1
  valid_ip "$d" && return 1
  [[ "$d" =~ ^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$ ]]
}

# 10/8, 172.16/12, 192.168/16, 127/8, 169.254/16, 100.64/10 (CGNAT у хостеров).
ip_is_private() {
  local ip="$1"
  [[ "$ip" =~ ^10\. || "$ip" =~ ^192\.168\. || "$ip" =~ ^127\. || "$ip" =~ ^169\.254\. ]] && return 0
  [[ "$ip" =~ ^172\.(1[6-9]|2[0-9]|3[01])\. ]] && return 0
  [[ "$ip" =~ ^100\.(6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7])\. ]] && return 0
  return 1
}

# Первый интерфейс маршрута по умолчанию, не считая наших туннелей.
uplink_iface() {
  local dev
  while read -r dev; do
    [[ -n "$dev" && "$OWN_IFACES" != *" $dev "* ]] && { echo "$dev"; return 0; }
  done < <(ip -4 route show default 2>/dev/null | awk '{for(i=1;i<NF;i++) if($i=="dev") print $(i+1)}')
  return 1
}

# Публичный IPv4 сервера. Сначала адрес самого аплинка; если он приватный
# (сервер за NAT) — спрашиваем внешний сервис, прибив curl к аплинку: при
# поднятом туннеле иначе вернётся адрес туннеля.
public_ip() {
  local dev ip svc
  dev=$(uplink_iface || true)
  if [[ -n "$dev" ]]; then
    ip=$(ip -4 -o addr show dev "$dev" scope global 2>/dev/null | awk '{split($4,a,"/"); print a[1]; exit}')
    valid_ip "$ip" && ! ip_is_private "$ip" && { echo "$ip"; return 0; }
  fi
  for svc in https://api.ipify.org https://ifconfig.me/ip https://ipinfo.io/ip; do
    ip=$(curl -4 -fsS --max-time 5 ${dev:+--interface "$dev"} "$svc" 2>/dev/null || true)
    [[ -z "$ip" && -n "$dev" ]] && ip=$(curl -4 -fsS --max-time 5 "$svc" 2>/dev/null || true)
    valid_ip "$ip" && ! ip_is_private "$ip" && { echo "$ip"; return 0; }
  done
  # Сервер без выхода наружу: лучше показать локальный адрес, чем ничего
  ip=$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<NF;i++) if($i=="src"){print $(i+1); exit}}')
  valid_ip "$ip" && echo "$ip"
}

# Кэш на время одного запуска: адрес дёргается из шапки меню и генераторов.
_PUBLIC_IP=""
public_ip_cached() {
  [[ -n "$_PUBLIC_IP" ]] || _PUBLIC_IP=$(public_ip || true)
  echo "$_PUBLIC_IP"
}

udp_listening() { ss -lunH "sport = :$1" 2>/dev/null | grep -q .; }

# Занят ли UDP-порт кем угодно из известных: сокет, AWG, каскад, обфускатор.
udp_port_busy() {
  local p="$1"
  valid_port "$p" || return 0
  udp_listening "$p" && return 0
  [[ "$(conf_iface_get ListenPort)" == "$p" ]] && return 0
  grep -qE "^udp\|${p}\|" "$CASCADE_RULES" 2>/dev/null && return 0
  wgobf_owns_port "$p" && return 0
  return 1
}

random_free_udp_port() {
  local p i avoid="${1:-}"
  for i in {1..40}; do
    p=$(rand_range 30001 65535)
    [[ "$p" == "$avoid" ]] && continue
    udp_port_busy "$p" || { echo "$p"; return 0; }
  done
  return 1
}

# Сверяет A-запись домена с IP сервера. Не запрет, а предупреждение:
# DNS могли ещё не прописать.
domain_points_here() {
  local d="$1" ips srv
  ips=$(getent ahostsv4 "$d" 2>/dev/null | awk '{print $1}' | sort -u | tr '\n' ' ')
  if [[ -z "$ips" ]]; then
    warn "Домен $d не резолвится с этого сервера"
    return 1
  fi
  srv=$(public_ip_cached)
  if [[ -n "$srv" && " $ips" != *" $srv "* ]]; then
    warn "Домен ведёт на ${ips% }, а IP сервера — $srv"
    info "Нужна прямая A-запись на IP сервера (без прокси Cloudflare)"
    return 1
  fi
  ok "Домен ведёт на этот сервер (${ips% })"
}

# Доходит ли трафик через SOCKS5. Настоящий запрос наружу: прокси может
# принимать соединения и никуда их не отправлять. В stdout — код ответа.
socks_probe() {
  local addr="$1" code opt
  command -v curl &>/dev/null || return 0
  for opt in --socks5-hostname --socks5; do
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$opt" "$addr" \
             http://cp.cloudflare.com/generate_204 2>/dev/null || true)
    [[ "$code" == 204 || "$code" == 200 ]] && return 0
  done
  echo "${code:-нет ответа}"
  return 1
}

# Внешний IP через интерфейс (проверка туннеля). Пусто — трафик не идёт.
iface_egress_ip() {
  curl -4 -fsS --max-time "${2:-6}" --interface "$1" https://api.ipify.org 2>/dev/null || true
}

# Все адреса и маршруты сервера — для выбора подсети без пересечений.
# Адреса туннелей добавлены явно: пока туннель выключен, их в системе нет.
taken_networks() {
  ip -4 -o addr show 2>/dev/null || true
  ip -4 route show table all 2>/dev/null || true
  conf_iface_get Address
  echo "$T2S_ADDR 172.16.0.0/24 $XRAY_TUN_ADDR"
}
