# Антисканер: новые входящие подключения из сетей сканеров (РКН, СКИПА) и
# госорганов отбрасываются до служб сервера — SSH, Xray, панелей, Mini App.
# Сервер реже попадает в базы, которые собирают по итогам сканирований.
#
# Списки — публичные (shadow-netlab/traffic-guard-lists). Чужому списку на
# слово не верим: каждая запись проверяется, частные и служебные сети и
# слишком широкие подсети отбрасываются, короткий (оборванный) список не
# заменяет прежний.
#
# Как устроено: наборы ipset hash:net (IPv4 и IPv6) и одно правило первым в
# INPUT — DROP только НОВЫХ соединений: уже открытые (текущий SSH) не рвутся.
# Трафик клиентов через VPN (FORWARD) не трогается. Исключения — записи
# nomatch: адрес внутри подсети списка остаётся доступным. SSH-адрес, с
# которого включают, и адреса самого сервера попадают в исключения сами.
#
# Служба awg2-antiscan.service ставит наборы и правило при загрузке (раньше
# UFW и netfilter-persistent), таймер раз в час возвращает правило на место,
# если его сбросили или подвинули, и раз в сутки обновляет списки. Без сети
# работает на сохранённых списках. iptables-persistent не нужен.

# id<TAB>файл в репозитории списков<TAB>подпись<TAB>минимум записей
_antiscan_lists() {
  printf '%s\t%s\t%s\t%s\n' \
    scan antiscanner.list "Сканеры" 20 \
    skipa skipa.list "СКИПА — сканеры РКН" 20 \
    gov government_networks.list "Сети госорганов" 300
}

_antiscan_get() {  # КЛЮЧ — значение из antiscan.conf (файл не исполняется)
  sed -n "s/^$1=//p" "$ANTISCAN_CONF" 2>/dev/null | tail -1
}

_antiscan_set() {  # КЛЮЧ ЗНАЧЕНИЕ
  local v="${2//[$'\n\r']/ }"
  mkdir -p "$ANTISCAN_DIR" && chmod 700 "$ANTISCAN_DIR"
  { grep -v "^$1=" "$ANTISCAN_CONF" 2>/dev/null; printf '%s=%s\n' "$1" "$v"; } | write_file "$ANTISCAN_CONF" 600
}

_antiscan_log() { mkdir -p "$(dirname "$ANTISCAN_LOG")"; echo "[$(date '+%F %T')] $*" >> "$ANTISCAN_LOG"; }

# Включённые списки: id через пробел, только известные (по умолчанию все)
_antiscan_enabled_lists() {
  local want id out=()
  want=" $(_antiscan_get LISTS) "
  [[ "$want" == "  " ]] && want=" scan skipa gov "
  while IFS=$'\t' read -r id _; do
    [[ "$want" == *" $id "* ]] && out+=("$id")
  done < <(_antiscan_lists)
  echo "${out[*]}"
}

# Записи списка → нормализованные подсети одного семейства (4 или 6).
# allow=1 — для исключений: без запрета частных сетей и ширины.
_antiscan_parse() {  # 4|6 [allow]
  awk -v fam="$1" -v allow="${2:-0}" '
    function ip2n(s,  a) { split(s, a, "."); return ((a[1] * 256 + a[2]) * 256 + a[3]) * 256 + a[4] }
    function n2ip(n,  a, i) { for (i = 4; i >= 1; i--) { a[i] = n % 256; n = int(n / 256) }
                              return a[1] "." a[2] "." a[3] "." a[4] }
    BEGIN {
      # Частные, служебные, документационные и multicast: там сети самого
      # сервера и клиентов VPN, блокировать их нельзя ни при каком списке
      split("0.0.0.0/8 10.0.0.0/8 100.64.0.0/10 127.0.0.0/8 169.254.0.0/16 172.16.0.0/12 " \
            "192.0.0.0/24 192.0.2.0/24 192.168.0.0/16 198.18.0.0/15 198.51.100.0/24 " \
            "203.0.113.0/24 224.0.0.0/3", res, " ")
      for (i in res) { split(res[i], q, "/"); rs[i] = ip2n(q[1]); re[i] = rs[i] + 2 ^ (32 - q[2]) - 1 }
    }
    { sub(/#.*/, ""); gsub(/[ \t\r]/, "") }
    $0 == "" { next }
    fam == 4 && /^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+(\/[0-9]+)?$/ {
      split($0, p, "/"); len = (p[2] == "" ? 32 : p[2] + 0); split(p[1], o, ".")
      for (i = 1; i <= 4; i++) if (o[i] + 0 > 255 || o[i] ~ /^0[0-9]/) next
      if (len > 32 || (!allow && len < 12) || len < 8) next
      size = 2 ^ (32 - len); s = ip2n(p[1]); s -= s % size; e = s + size - 1
      if (!allow) for (i in rs) if (s <= re[i] && e >= rs[i]) next
      print n2ip(s) "/" len; next
    }
    fam == 6 && /:/ {
      if (split(tolower($0), p, "/") > 2) next
      ip = p[1]; len = (p[2] == "" ? 128 : p[2] + 0)
      if (p[2] != "" && p[2] !~ /^[0-9]+$/) next
      if (ip !~ /^[0-9a-f:]+$/ || ip ~ /:::/ || len > 128 || (!allow && len < 24) || len < 16) next
      t = ip; dbl = gsub(/::/, "", t)
      if (dbl > 1) next
      n = split(ip, g, ":"); cnt = 0
      for (i = 1; i <= n; i++) { if (length(g[i]) > 4) next; if (g[i] != "") cnt++ }
      if ((dbl == 0 && (n != 8 || cnt != 8)) || (dbl == 1 && cnt > 7)) next
      # Только глобальные адреса 2000::/3, без документационной 2001:db8::/32
      if (!allow && (g[1] !~ /^[23][0-9a-f][0-9a-f][0-9a-f]$/ || ip ~ /^2001:0?db8:/)) next
      print ip "/" len; next
    }
  '
}

# Подписи сетей из комментариев списка госсетей: «подсеть<TAB>организация».
_antiscan_names() {
  awk '
    /^# Networks announced by/ { org = ""; asn = ""; next }
    /^# AS-Name:/ { asn = $0; sub(/^# AS-Name:[ \t]*/, "", asn); next }
    /^#/ { if (org == "" && asn != "") { org = $0; sub(/^#[ \t]*/, "", org) } next }
    NF { n = $1; sub(/\/(32|128)$/, "", n); print n "\t" substr(org != "" ? org : asn, 1, 80) }
  ' | tr -d '\000-\010\013-\037\177'
}

# Адреса, которые не блокируются никогда: адреса сервера и SSH-сессии
# (текущая — из SSH_CONNECTION, остальные — установленные соединения sshd).
_antiscan_auto_allow() {
  {
    ip -o addr show scope global 2>/dev/null | awk '{sub(/\/.*/, "", $4); print $4}'
    [[ -n "${SSH_CONNECTION:-}" ]] && echo "${SSH_CONNECTION%% *}"
    ss -tnpH state established 2>/dev/null | awk '/"sshd/ {print $4}' | sed -E 's/^\[?([^]]*)\]?:[0-9]+$/\1/'
  } | sed 's/^::ffff://' | grep -E '^[0-9a-fA-F.:]+$' | sort -u
}

_antiscan_ssh_peers() {
  {
    [[ -n "${SSH_CONNECTION:-}" ]] && echo "${SSH_CONNECTION%% *}"
    ss -tnpH state established 2>/dev/null | awk '/"sshd/ {print $4}' | sed -E 's/^\[?([^]]*)\]?:[0-9]+$/\1/'
  } | sed 's/^::ffff://' | grep -E '^[0-9a-fA-F.:]+$' | sort -u
}

# Скачать включённые списки. Оборванный или пустой ответ прежний список не
# заменяет. Ошибки — в ERROR, время удачного обновления — в UPDATED.
_antiscan_fetch_all() {
  local id file label min tmp n errs=() ok=0
  mkdir -p "$ANTISCAN_DIR/lists"
  while IFS=$'\t' read -r id file label min; do
    [[ " $(_antiscan_enabled_lists) " == *" $id "* ]] || continue
    tmp=$(mktemp "$ANTISCAN_DIR/.dl.XXXXXX") || return 1
    if ! curl -fsS --proto '=https' --max-time 40 --max-filesize 8000000 -o "$tmp" "$ANTISCAN_SRC/$file" 2>/dev/null; then
      errs+=("$label: не скачался"); rm -f "$tmp"; continue
    fi
    n=$(( $(_antiscan_parse 4 < "$tmp" | wc -l) + $(_antiscan_parse 6 < "$tmp" | wc -l) ))
    if (( n < min )); then
      errs+=("$label: в ответе $n записей — оставлен прежний"); rm -f "$tmp"; continue
    fi
    chmod 600 "$tmp" && mv -f "$tmp" "$ANTISCAN_DIR/lists/$id.list"
    ok=$((ok + 1))
  done < <(_antiscan_lists)
  if (( ${#errs[@]} )); then
    _antiscan_set ERROR "${errs[*]}"
    _antiscan_log "списки: ${errs[*]}"
  else
    _antiscan_set ERROR ""
    _antiscan_set UPDATED "$(date +%s)"
  fi
  (( ok > 0 ))
}

_antiscan_rule() {  # набор → ANTISCAN_RULE
  ANTISCAN_RULE=(-m conntrack --ctstate NEW -m set --match-set "$1" src -m comment --comment "$ANTISCAN_TAG" -j DROP)
}

# Правило — первым в INPUT: ACCEPT своих портов, вставленные позже (UFW,
# fail2ban, другие программы), иначе пропускали бы сканер раньше него.
_antiscan_rule_up() {  # iptables|ip6tables набор
  local ipt="$1"
  _antiscan_rule "$2"
  if "$ipt" -C INPUT "${ANTISCAN_RULE[@]}" 2>/dev/null; then
    "$ipt" -S INPUT 2>/dev/null | sed -n 2p | grep -q -- "$ANTISCAN_TAG" && return 0
    while "$ipt" -D INPUT "${ANTISCAN_RULE[@]}" 2>/dev/null; do :; done
  fi
  "$ipt" -I INPUT 1 "${ANTISCAN_RULE[@]}"
}

_antiscan_rule_down() {  # iptables|ip6tables набор
  local guard=0
  command -v "$1" &>/dev/null || return 0
  _antiscan_rule "$2"
  while (( guard++ < 32 )) && "$1" -D INPUT "${ANTISCAN_RULE[@]}" 2>/dev/null; do :; done
  return 0
}

_antiscan_rule_first() {  # iptables|ip6tables
  "$1" -S INPUT 2>/dev/null | sed -n 2p | grep -q -- "$ANTISCAN_TAG"
}

# Правила на месте: есть набор — правило первое в своей таблице
antiscan_rules_ok() {
  ipset list -n "$ANTISCAN_SET" &>/dev/null && _antiscan_rule_first iptables || return 1
  if ipset list -n "$ANTISCAN_SET6" &>/dev/null; then _antiscan_rule_first ip6tables || return 1; fi
  return 0
}

# Загрузить набор атомарно: новый под временным именем, затем swap —
# правило не остаётся без набора ни на миг.
_antiscan_load() {  # набор inet|inet6 файл_записей файл_исключений
  local set="$1" family="$2" tmpset="${1}-new" n
  n=$(wc -l < "$3")
  {
    echo "create $tmpset hash:net family $family hashsize 4096 maxelem 262144 counters -exist"
    echo "flush $tmpset"
    sed "s|^|add $tmpset |; s|$| -exist|" "$3"
    sed "s|^|add $tmpset |; s|$| nomatch -exist|" "$4"
  } | ipset restore || { ipset destroy "$tmpset" 2>/dev/null; return 1; }
  ipset create "$set" hash:net family "$family" hashsize 4096 maxelem 262144 counters -exist || return 1
  ipset swap "$tmpset" "$set" && ipset destroy "$tmpset"
  echo "$n"
}

# IPv4-адрес внутри какой-нибудь подсети из файла (по строке «сеть/длина»)?
_antiscan_covers() {  # файл адрес
  awk -v ip="$2" '
    function ip2n(s,  a) { split(s, a, "."); return ((a[1] * 256 + a[2]) * 256 + a[3]) * 256 + a[4] }
    BEGIN { if (ip !~ /^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$/) exit; x = ip2n(ip) }
    { split($0, p, "/"); s = ip2n(p[1]); if (x >= s && x < s + 2 ^ (32 - p[2])) { found = 1; exit } }
    END { exit !found }' "$1"
}

# Собрать наборы из сохранённых списков и поставить правила.
_antiscan_apply() {
  local d rc=0
  d=$(mktemp -d "$ANTISCAN_DIR/.apply.XXXXXX") || return 1
  _antiscan_apply_in "$d" || rc=$?
  rm -rf "$d"
  return "$rc"
}

_antiscan_apply_in() {  # временный каталог
  local d="$1" id ip n4 n6=0
  : > "$d/v4"; : > "$d/v6"
  for id in $(_antiscan_enabled_lists); do
    [[ -f "$ANTISCAN_DIR/lists/$id.list" ]] || continue
    _antiscan_parse 4 < "$ANTISCAN_DIR/lists/$id.list" >> "$d/v4"
    _antiscan_parse 6 < "$ANTISCAN_DIR/lists/$id.list" >> "$d/v6"
  done
  sort -u -o "$d/v4" "$d/v4"; sort -u -o "$d/v6" "$d/v6"
  if [[ ! -s "$d/v4" && ! -s "$d/v6" ]]; then
    _antiscan_log "нечего применять: списки ещё не скачаны"
    return 3
  fi
  if (( $(wc -l < "$d/v4") + $(wc -l < "$d/v6") > 200000 )); then
    _antiscan_log "в списках больше 200000 записей — не применяю"
    return 4
  fi
  [[ -f "$ANTISCAN_DIR/lists/gov.list" ]] && _antiscan_names < "$ANTISCAN_DIR/lists/gov.list" > "$ANTISCAN_DIR/names"
  # SSH-адрес внутри списка — в исключения насовсем: иначе после следующего
  # обновления с него не открылась бы новая сессия
  for ip in $(_antiscan_ssh_peers); do
    _antiscan_covers "$d/v4" "$ip" || continue
    _antiscan_allow_rows | grep -qxF -e "$ip" -e "$ip/32" && continue
    printf '%s # SSH — добавлен сам %s\n' "$ip" "$(date '+%F')" >> "$ANTISCAN_ALLOW"
    chmod 600 "$ANTISCAN_ALLOW"
    _antiscan_log "SSH-адрес $ip есть в списке — добавлен в исключения"
  done
  { _antiscan_allow_rows; _antiscan_auto_allow; } > "$d/allow"
  _antiscan_parse 4 1 < "$d/allow" | sort -u > "$d/a4"
  _antiscan_parse 6 1 < "$d/allow" | sort -u > "$d/a6"
  n4=$(_antiscan_load "$ANTISCAN_SET" inet "$d/v4" "$d/a4") || { _antiscan_log "ipset: набор IPv4 не загрузился"; return 5; }
  _antiscan_rule_up iptables "$ANTISCAN_SET" || { _antiscan_log "iptables: правило не поставилось"; return 5; }
  if [[ -s "$d/v6" ]] && command -v ip6tables &>/dev/null \
      && n6=$(_antiscan_load "$ANTISCAN_SET6" inet6 "$d/v6" "$d/a6") \
      && _antiscan_rule_up ip6tables "$ANTISCAN_SET6"; then
    :
  else
    n6=0
    _antiscan_rule_down ip6tables "$ANTISCAN_SET6"
    ipset destroy "$ANTISCAN_SET6" 2>/dev/null || true
  fi
  _antiscan_set ENTRIES "$n4 $n6"
  _antiscan_log "применено: IPv4 $n4, IPv6 $n6"
  return 0
}

_antiscan_allow_rows() { grep -v '^\s*#' "$ANTISCAN_ALLOW" 2>/dev/null | awk 'NF {print $1}'; }

antiscan_down() {
  _antiscan_rule_down iptables "$ANTISCAN_SET"
  _antiscan_rule_down ip6tables "$ANTISCAN_SET6"
  command -v ipset &>/dev/null || return 0
  ipset destroy "$ANTISCAN_SET" 2>/dev/null || true
  ipset destroy "$ANTISCAN_SET6" 2>/dev/null || true
  return 0
}

# Точка входа службы и таймера (и awg2): apply | update | heal | off.
antiscan_run() {
  local mode="${1:-heal}" rc=0 upd
  mkdir -p "$ANTISCAN_DIR" && chmod 700 "$ANTISCAN_DIR"
  exec 9>"$ANTISCAN_DIR/.lock"
  flock -w 180 9 || { _antiscan_log "$mode: занято другой операцией"; return 75; }
  if [[ "$mode" == off || "$(_antiscan_get ON)" != 1 ]]; then
    antiscan_down
    return 0
  fi
  case "$mode" in
    update) _antiscan_fetch_all || true; _antiscan_apply || rc=$? ;;
    apply) _antiscan_apply || rc=$? ;;
    heal)
      touch "$ANTISCAN_DIR/heal"
      upd=$(_antiscan_get UPDATED)
      if (( $(date +%s) - ${upd:-0} > 86400 )); then
        _antiscan_fetch_all || true
        _antiscan_apply || rc=$?
      elif ! antiscan_rules_ok; then
        _antiscan_log "правило пропало или сдвинуто — возвращаю"
        _antiscan_apply || rc=$?
      fi ;;
    *) echo "использование: ${0##*/} apply|update|heal|off" >&2; return 2 ;;
  esac
  return "$rc"
}

# ── Установка ─────────────────────────────────────────────
_antiscan_emit() {
  emit_script "$ANTISCAN_SCRIPT" 'antiscan_run "$@"' \
    ANTISCAN_DIR ANTISCAN_CONF ANTISCAN_ALLOW ANTISCAN_LOG ANTISCAN_SET ANTISCAN_SET6 ANTISCAN_TAG ANTISCAN_SRC \
    write_file _antiscan_lists _antiscan_get _antiscan_set _antiscan_log _antiscan_enabled_lists _antiscan_parse \
    _antiscan_names _antiscan_auto_allow _antiscan_ssh_peers _antiscan_fetch_all _antiscan_rule _antiscan_rule_up \
    _antiscan_rule_down _antiscan_rule_first antiscan_rules_ok _antiscan_load _antiscan_covers _antiscan_allow_rows \
    _antiscan_apply _antiscan_apply_in antiscan_down \
    antiscan_run || return 1
  # Раньше UFW и netfilter-persistent, как сам ufw.service: их правила
  # встанут после нашего, а восстановление iptables-persistent найдёт набор
  write_unit "$ANTISCAN_UNIT" <<EOF
[Unit]
Description=AWG Toolza — антисканер: сети сканеров не доходят до служб сервера
DefaultDependencies=no
Wants=network-pre.target local-fs.target
After=local-fs.target systemd-modules-load.service
Before=network-pre.target ufw.service netfilter-persistent.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=$ANTISCAN_SCRIPT apply

[Install]
WantedBy=multi-user.target
EOF
  write_unit "${ANTISCAN_TIMER%.timer}.service" <<EOF
[Unit]
Description=AWG Toolza — антисканер: правило на месте, списки раз в сутки
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=$ANTISCAN_SCRIPT heal
EOF
  write_unit "$ANTISCAN_TIMER" <<'EOF'
[Unit]
Description=AWG Toolza — антисканер: проверка раз в час

[Timer]
OnBootSec=120
OnUnitActiveSec=3600
RandomizedDelaySec=300

[Install]
WantedBy=timers.target
EOF
}

antiscan_on() { [[ "$(_antiscan_get ON)" == 1 ]]; }

antiscan_enable() {
  local rc=0
  need_cmds ipset:ipset flock:util-linux || return 1
  [[ -n "$(_antiscan_get LISTS)" ]] || _antiscan_set LISTS "scan skipa gov"
  _antiscan_set ON 1
  _antiscan_emit || { err "Не удалось записать службу антисканера"; return 1; }
  info "Скачиваю и проверяю списки..."
  "$ANTISCAN_SCRIPT" update || rc=$?
  if (( rc )); then
    _antiscan_set ON 0
    "$ANTISCAN_SCRIPT" off &>/dev/null || true
    case $rc in
      3) err "Списки не скачались: $(_antiscan_get ERROR)" ;;
      75) err "Антисканер занят другой операцией — повтори через минуту" ;;
      *) err "Не удалось применить правила (код $rc) — журнал: $ANTISCAN_LOG" ;;
    esac
    return 1
  fi
  systemctl enable "$ANTISCAN_UNIT" &>/dev/null || true
  systemctl enable --now "$ANTISCAN_TIMER" &>/dev/null || true
  log_info "антисканер включён"
  ok "Антисканер включён: $(antiscan_summary)"
  [[ -n "$(_antiscan_get ERROR)" ]] && warn "$(_antiscan_get ERROR)"
  return 0
}

antiscan_disable() {
  _antiscan_set ON 0
  remove_unit "$ANTISCAN_TIMER" "${ANTISCAN_TIMER%.timer}.service" "$ANTISCAN_UNIT"
  antiscan_down
  log_info "антисканер выключен"
  ok "Антисканер выключен — правила и наборы сняты"
}

antiscan_update() {
  antiscan_on || { err "Антисканер выключен"; return 1; }
  _antiscan_emit || return 1
  "$ANTISCAN_SCRIPT" update || { err "Не удалось применить списки — журнал: $ANTISCAN_LOG"; return 1; }
  if [[ -n "$(_antiscan_get ERROR)" ]]; then warn "$(_antiscan_get ERROR)"; fi
  ok "Списки обновлены: $(antiscan_summary)"
}

# Какие списки блокировать: id через запятую или пробел (хотя бы один)
antiscan_lists_set() {
  local want=" ${*//,/ } " id out=()
  while IFS=$'\t' read -r id _; do [[ "$want" == *" $id "* ]] && out+=("$id"); done < <(_antiscan_lists)
  (( ${#out[@]} )) || { err "Нужен хотя бы один список: scan, skipa, gov"; return 1; }
  _antiscan_set LISTS "${out[*]}"
  antiscan_on || { ok "Списки: ${out[*]}"; return 0; }
  if ! { _antiscan_emit && "$ANTISCAN_SCRIPT" update; }; then err "Не удалось применить — журнал: $ANTISCAN_LOG"; return 1; fi
  ok "Списки: ${out[*]} — $(antiscan_summary)"
}

# Исключение — адрес или подсеть IPv4/IPv6
antiscan_allow() {  # add|del АДРЕС
  local op="$1" v="${2:-}" norm short
  norm=$(printf '%s\n' "$v" | _antiscan_parse 4 1)
  [[ -n "$norm" ]] || norm=$(printf '%s\n' "$v" | _antiscan_parse 6 1)
  [[ -n "$norm" && "$v" != *[[:space:]]* && "$norm" != *$'\n'* ]] \
    || { err "Нужен IPv4 или IPv6 адрес (можно с /маской): $(shown "$v")"; return 1; }
  short="${norm%/32}"; short="${short%/128}"
  mkdir -p "$ANTISCAN_DIR" && chmod 700 "$ANTISCAN_DIR"
  touch "$ANTISCAN_ALLOW" && chmod 600 "$ANTISCAN_ALLOW"
  case "$op" in
    add) _antiscan_allow_rows | grep -qxF -e "$norm" -e "$short" || echo "$norm" >> "$ANTISCAN_ALLOW" ;;
    del) _antiscan_allow_rows | grep -qxF -e "$norm" -e "$short" || { err "Такого исключения нет: $norm"; return 1; }
         awk -v n="$norm" -v s="$short" '$1 != n && $1 != s' "$ANTISCAN_ALLOW" > "$ANTISCAN_ALLOW.new"
         mv -f "$ANTISCAN_ALLOW.new" "$ANTISCAN_ALLOW"; chmod 600 "$ANTISCAN_ALLOW" ;;
    *) err "allow add|del АДРЕС"; return 2 ;;
  esac
  if antiscan_on; then
    if ! { _antiscan_emit && "$ANTISCAN_SCRIPT" apply; }; then err "Не удалось применить — журнал: $ANTISCAN_LOG"; return 1; fi
  fi
  ok "Исключения: $([[ "$op" == add ]] && echo "добавлен" || echo "убран") $norm"
}

# Отбито новых подключений с последнего применения правил (пакетов)
antiscan_dropped() {
  { iptables-save -c -t filter 2>/dev/null; ip6tables-save -c -t filter 2>/dev/null; } \
    | awk -v tag="$ANTISCAN_TAG" 'index($0, "--comment " tag) && /^\[/ {
        split(substr($1, 2), c, ":"); n += c[1] } END { print n + 0 }'
}

# Чаще всего стучавшиеся подсети: «пакетов<TAB>подсеть<TAB>организация»
antiscan_top() {
  local n="${1:-5}"
  { ipset list "$ANTISCAN_SET" 2>/dev/null; ipset list "$ANTISCAN_SET6" 2>/dev/null; } \
    | awk '$2 == "packets" && $3 > 0 {print $3 "\t" $1}' | sort -t$'\t' -k1,1nr | head -n "$n" \
    | awk -F'\t' -v names="$ANTISCAN_DIR/names" '
        BEGIN { while ((getline l < names) > 0) { split(l, a, "\t"); org[a[1]] = a[2] } }
        { k = $2; sub(/\/(32|128)$/, "", k); print $1 "\t" $2 "\t" org[k] }'
}

antiscan_summary() {
  local e
  read -r -a e <<< "$(_antiscan_get ENTRIES)"
  echo "подсетей IPv4 ${e[0]:-0}, IPv6 ${e[1]:-0}"
}

# ── Меню ──────────────────────────────────────────────────
_antiscan_show() {
  local id file label min on n upd err ssh
  hdr "Антисканер"
  echo -e "  ${D}Новые входящие подключения из сетей сканеров РКН и госорганов"
  echo -e "  отбрасываются до SSH, Xray и панелей. VPN-трафик клиентов не трогается.${N}"
  echo ""
  if antiscan_on; then
    if antiscan_rules_ok; then echo -e "  Состояние : ${G}● включён${N} — $(antiscan_summary)"
    else echo -e "  Состояние : ${Y}▲ включён, правило не на месте${N} — вернёт таймер или «Обновить списки»"; fi
    echo -e "  Отбито    : ${W}$(antiscan_dropped)${N} ${D}новых подключений с последнего применения${N}"
  else
    echo -e "  Состояние : ${D}○ выключен${N}"
  fi
  upd=$(_antiscan_get UPDATED)
  [[ -n "$upd" ]] && echo -e "  Списки    : обновлены $(date -d "@$upd" '+%d.%m.%Y %H:%M' 2>/dev/null)"
  err=$(_antiscan_get ERROR)
  [[ -n "$err" ]] && echo -e "  ${Y}▲ $err${N}"
  while IFS=$'\t' read -r id file label min; do
    on="${D}○${N}"; [[ " $(_antiscan_enabled_lists) " == *" $id "* ]] && on="${G}●${N}"
    n=0; [[ -f "$ANTISCAN_DIR/lists/$id.list" ]] && n=$(( $(_antiscan_parse 4 < "$ANTISCAN_DIR/lists/$id.list" | wc -l) + $(_antiscan_parse 6 < "$ANTISCAN_DIR/lists/$id.list" | wc -l) ))
    echo -e "    $on $label ${D}— $n подсетей${N}"
  done < <(_antiscan_lists)
  n=$(_antiscan_allow_rows | wc -l)
  echo -e "  Исключения: ${W}$n${N}${D} + адреса сервера и SSH-сессий${N}"
  ssh=$(_antiscan_ssh_peers | head -3 | tr '\n' ' ')
  [[ -n "$ssh" ]] && echo -e "  ${D}Твой SSH: $ssh— не блокируется${N}"
}

do_antiscan_menu() {
  local c v id file label min
  while true; do
    echo ""
    _antiscan_show
    echo ""
    if antiscan_on; then echo -e "  ${C}1)${N} Выключить"; else echo -e "  ${C}1)${N} Включить"; fi
    echo -e "  ${C}2)${N} Обновить списки сейчас"
    echo -e "  ${C}3)${N} Списки — что блокировать"
    echo -e "  ${C}4)${N} Исключения — добавить адрес"
    echo -e "  ${C}5)${N} Исключения — убрать адрес"
    echo -e "  ${W}0)${N} ← Назад"
    read_choice c "${C}  Выбор [0-5]: ${N}" 0 5 0
    case "$c" in
      1) if antiscan_on; then antiscan_disable; else antiscan_enable || true; fi ;;
      2) antiscan_update || true ;;
      3) echo ""
         while IFS=$'\t' read -r id file label min; do echo -e "  ${C}$id${N} — $label"; done < <(_antiscan_lists)
         read_line v "${C}  Какие блокировать (через пробел) [$(_antiscan_enabled_lists)]: ${N}"
         [[ -n "$v" ]] && { antiscan_lists_set "$v" || true; } ;;
      4) read_line v "${C}  Адрес или подсеть (1.2.3.4 или 1.2.3.0/24): ${N}"
         [[ -n "$v" ]] && { antiscan_allow add "$v" || true; } ;;
      5) _antiscan_allow_rows | sed 's/^/    /'
         read_line v "${C}  Какой убрать: ${N}"
         [[ -n "$v" ]] && { antiscan_allow del "$v" || true; } ;;
      0) return 0 ;;
    esac
    pause
  done
}

# Таймер молчит дольше трёх часов (сброшен, заглох) — перезапустить
antiscan_watchdog() {
  local age
  antiscan_on || return 0
  [[ -f "$ANTISCAN_DIR/heal" ]] || return 0
  age=$(( $(date +%s) - $(stat -c %Y "$ANTISCAN_DIR/heal" 2>/dev/null || echo 0) ))
  (( age < 10800 )) && return 0
  touch "$ANTISCAN_DIR/heal"
  timer_heal "$ANTISCAN_TIMER"
  systemctl start --no-block "${ANTISCAN_TIMER%.timer}.service" &>/dev/null || true
}

antiscan_remove() {
  remove_unit "$ANTISCAN_TIMER" "${ANTISCAN_TIMER%.timer}.service" "$ANTISCAN_UNIT"
  antiscan_down
  rm -rf "$ANTISCAN_DIR" "$ANTISCAN_SCRIPT" "$ANTISCAN_LOG"
}
