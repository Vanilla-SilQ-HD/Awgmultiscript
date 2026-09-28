# Клиенты AWG: добавление, удаление, переименование, выдача конфигов.

# QR с экрана терминала телефоны берут примерно до 2800 байт конфига.
QR_MAX=2800

share_config() {  # файл [qr]
  local f="$1" size
  [[ -f "$f" ]] || return 1
  size=$(wc -c < "$f")
  if [[ "${2:-}" == qr ]]; then
    if command -v qrencode &>/dev/null && (( size <= QR_MAX )); then
      qrencode -t ansiutf8 -m 1 < "$f"
      echo -e "${D}  ↑ QR конфига ($size байт) — сканируй в AmneziaVPN / AmneziaWG${N}"
      return 0
    fi
    warn "Конфиг $size байт — в читаемый QR не влезет, показываю текст"
  fi
  echo -e "${Y}  ── ${f##*/} ──${N}"
  cat "$f"
  echo -e "${Y}  ──────────────${N}"
}

# Добавляет клиента в awg0.conf и в работающий интерфейс, пишет его конфиг.
# Мимикрия берётся из I_LINES/MIMICRY. $5 — срок действия (unix-время), пусто — бессрочно.
client_add() {
  local name="$1" addr="$2" dns="$3" mtu="$4" expire="${5:-}" priv pub psk size
  priv=$(awg genkey) && pub=$(awg pubkey <<< "$priv") && psk=$(awg genpsk) || return 1
  size=$(stat -c%s "$SERVER_CONF")
  printf '\n[Peer]\n# %s\n# mimicry=%s\nPublicKey = %s\nPresharedKey = %s\nAllowedIPs = %s\n' \
    "$name" "$(mimicry_tag)" "$pub" "$psk" "$addr" >> "$SERVER_CONF"
  if iface_up && ! awg set "$AWG_IF" peer "$pub" preshared-key <(printf '%s\n' "$psk") allowed-ips "$addr"; then
    truncate -s "$size" "$SERVER_CONF"
    err "Ядро не приняло пира — запись откатана"
    return 1
  fi
  write_client_conf "$(client_file "$name")" "$priv" "$addr" "$psk" "$dns" "$mtu" || return 1
  if [[ -n "$expire" ]]; then
    expire_install
    py expire-set "$SERVER_CONF" "$name" "$expire"
  fi
  log_info "клиент добавлен: $name $addr"
}

# Удаляет пира по ключу: из конфига, из ядра, файл клиента и списки туннелей.
client_delete() {
  local pub="$1" name ip
  ip=$(clients_tsv | awk -F'\t' -v k="$pub" '$2 == k {split($3, a, "/"); print a[1]; exit}')
  name=$(py peer-del "$SERVER_CONF" "$pub") || return 1
  iface_up && awg set "$AWG_IF" peer "$pub" remove 2>/dev/null
  [[ -n "$name" ]] && rm -f "$CLIENT_DIR/${name}_awg2.conf" "$CLIENT_DIR/${name}_awg3.conf"
  rm -f "$EXPIRE_STATE_DIR/warn1h_${pub//[^A-Za-z0-9]/_}"
  [[ -n "$ip" ]] && tunnel_peers_forget "$ip"
  log_info "клиент удалён: ${name:-?} ($pub)"
  ok "Удалён: ${name:-без имени}"
}

# Имя для нового клиента: валидное и не занятое ни пиром, ни файлом.
_name_free() { valid_client_name "$1" && ! client_exists "$1" && [[ ! -e "$CLIENT_DIR/${1}_awg2.conf" && ! -e "$CLIENT_DIR/${1}_awg3.conf" ]]; }

_ask_expire() {  # → unix-время в stdout или пусто
  local c d ts=""
  {
    echo -e "  Срок действия:"
    echo -e "  ${C}1)${N} Бессрочно"
    echo -e "  ${C}2)${N} 1 час"
    echo -e "  ${C}3)${N} 1 день"
    echo -e "  ${C}4)${N} 7 дней"
    echo -e "  ${C}5)${N} 30 дней"
    echo -e "  ${C}6)${N} До даты"
  } >&2
  read_choice c "${C}  Выбор [1-6] (Enter = 1): ${N}" 1 6 1 >&2
  case "$c" in
    2) ts=$(date -d '+1 hour' +%s) ;; 3) ts=$(date -d '+1 day' +%s) ;;
    4) ts=$(date -d '+7 days' +%s) ;; 5) ts=$(date -d '+30 days' +%s) ;;
    6) read_line d "${C}  Дата (ГГГГ-ММ-ДД ЧЧ:ММ): ${N}" >&2
       ts=$(date -d "$d" +%s 2>/dev/null) || { warn "Дата не распознана — бессрочно" >&2; ts=""; } ;;
  esac
  echo "$ts"
}

# Мимикрия для нового клиента по профилю сервера.
_client_mimicry() {
  local profile c
  profile=$(server_profile)
  I_LINES=(); MIMICRY=none
  case "$profile" in
    lite) gen_chain_from_server ;;
    standard)
      MIMICRY=quic; scan_domains quic "${QUIC_DOMAINS[@]}"
      gen_chain quic "${SCAN_OK[0]:-}" --only-i1 || MIMICRY=none ;;
    *)
      c=$(conf_marker AWG_MIMICRY)
      echo -e "  Мимикрия I1-I5:"
      echo -e "  ${C}1)${N} Как у сервера ${D}(${c:-none})${N}"
      echo -e "  ${C}2)${N} Выбрать"
      echo -e "  ${C}3)${N} Без I1-I5"
      read_choice c "${C}  Выбор [1-3] (Enter = 1): ${N}" 1 3 1
      case "$c" in
        1) gen_chain_from_server ;;
        2) choose_and_gen_chain || { I_LINES=(); MIMICRY=none; } ;;
      esac ;;
  esac
}

do_add_client() {
  server_exists || { err "Сервер не создан"; return 1; }
  local name addr ip expire base
  while true; do
    read_line name "${C}  Имя клиента (латиница, цифры, _ -): ${N}"
    [[ -z "$name" ]] && return 0
    _name_free "$name" && break
    valid_client_name "$name" && warn "Клиент $name уже есть" || warn "Имя: латиница, цифры, _ и -, до 32 символов"
  done
  addr=$(free_client_ip) || { err "В подсети нет свободных адресов"; return 1; }
  if ! ask_yes "  Адрес $addr? [Y/n]: " y; then
    base=$(server_net); base="${base%.*}"
    while true; do
      read_line ip "${C}  Адрес ${base}.N: ${N}"
      ip="${ip%/32}"
      [[ -z "$ip" ]] && return 0
      if [[ "$ip" =~ ^${base//./\\.}\.([0-9]+)$ ]] && (( BASH_REMATCH[1] >= 2 && BASH_REMATCH[1] <= 254 )) \
         && ! clients_tsv | cut -f3,5 | tr '\t,' '\n\n' | grep -qx "$ip/32" \
         && [[ "$ip" != "$(conf_iface_get Address | cut -d/ -f1)" ]]; then
        addr="$ip/32"; break
      fi
      warn "Нужен свободный адрес ${base}.2-254"
    done
  fi
  S_DNS="1.1.1.1, 1.0.0.1"
  _choose_dns
  MTU=$(conf_iface_get MTU); _choose_mtu "${MTU:-1280}"
  _client_mimicry
  expire=$(_ask_expire)
  client_add "$name" "$addr" "$S_DNS" "$MTU" "$expire" || return 1
  share_config "$(client_file "$name")"
  success_box "Клиент $name: $addr"
  if [[ -n "$expire" ]]; then info "Срок действия: $(expire_fmt "$expire")"; fi
}

# Неинтерактивно (для скриптов и бота): мимикрия и MTU — как у сервера.
do_add_client_cli() {
  local name="$1" addr
  server_exists || { err "Сервер не создан"; return 1; }
  _name_free "$name" || { err "Имя $name занято или недопустимо"; return 1; }
  addr=$(free_client_ip) || { err "В подсети нет свободных адресов"; return 1; }
  I_LINES=(); MIMICRY=none
  [[ "$(server_profile)" != standard ]] && gen_chain_from_server
  client_add "$name" "$addr" "1.1.1.1, 1.0.0.1" "$(conf_iface_get MTU)" || return 1
  ok "Клиент $name добавлен"
  echo "Файл конфигурации: $(client_file "$name")"
}

do_bulk_add() {
  server_exists || { err "Сервер не создан"; return 1; }
  local c raw prefix count names=() n i addr expire created=0 part
  local -a parts=()
  echo -e "  ${C}1)${N} Префикс + количество ${D}(user-001...)${N}"
  echo -e "  ${C}2)${N} Имена через запятую"
  read_choice c "${C}  Выбор [1-2] (Enter = 1): ${N}" 1 2 1
  if [[ "$c" == 2 ]]; then
    read_line raw "${C}  Имена через запятую: ${N}"
    IFS=',' read -r -a parts <<< "$raw"
    for part in "${parts[@]}"; do
      n=$(tr -cd 'A-Za-z0-9_-' <<< "${part// /_}"); n="${n:0:32}"
      [[ -n "$n" ]] || continue
      if [[ " ${names[*]} " == *" $n "* ]] || ! _name_free "$n"; then warn "Пропущено: $n (занято)"; continue; fi
      names+=("$n")
    done
  else
    read_line prefix "${C}  Префикс: ${N}"
    valid_client_name "$prefix" && (( ${#prefix} <= 27 )) || { warn "Префикс: латиница, цифры, _ -, до 27 символов"; return 0; }
    read_line count "${C}  Сколько клиентов (1-200): ${N}"
    [[ "$count" =~ ^[0-9]+$ ]] && (( count >= 1 && count <= 200 )) || { warn "Нужно число 1-200"; return 0; }
    i=1
    while (( ${#names[@]} < count && i < 10000 )); do
      printf -v n '%s-%03d' "$prefix" "$i"
      _name_free "$n" && names+=("$n")
      i=$((i + 1))
    done
  fi
  (( ${#names[@]} )) || { warn "Нет имён для создания"; return 0; }
  S_DNS="1.1.1.1, 1.0.0.1"; _choose_dns
  MTU=$(conf_iface_get MTU); _choose_mtu "${MTU:-1280}"
  _client_mimicry
  expire=$(_ask_expire)
  ask_yes "  Создать клиентов: ${#names[@]}? [Y/n]: " y || return 0
  for n in "${names[@]}"; do
    addr=$(free_client_ip) || { warn "Подсеть заполнена — стоп"; break; }
    client_add "$n" "$addr" "$S_DNS" "$MTU" "$expire" || { warn "$n: не создан"; continue; }
    echo -e "  ${G}+${N} $n → $addr"
    created=$((created + 1))
  done
  success_box "Создано клиентов: $created из ${#names[@]}"
  info "Конфиги: $CLIENT_DIR/<имя>$(client_suffix).conf; архивом — Клиенты → Экспорт"
}

# Выбор клиента из списка. Результат — «имя<TAB>ключ» в CHOSEN.
CHOSEN=""
_pick_client() {
  local rows=() i c name pub aip
  mapfile -t rows < <(clients_tsv)
  (( ${#rows[@]} )) || { warn "Клиентов нет"; return 1; }
  echo ""
  for i in "${!rows[@]}"; do
    IFS=$'\t' read -r name pub aip _ <<< "${rows[$i]}"
    printf "  ${G}%3d)${N} %-24s ${D}%s${N}\n" "$((i + 1))" "${name:-без имени}" "$aip"
  done
  read_choice c "${C}  Номер (0 — отмена): ${N}" 0 "${#rows[@]}" 0
  (( c == 0 )) && return 1
  IFS=$'\t' read -r name pub _ <<< "${rows[$((c - 1))]}"
  CHOSEN="$name"$'\t'"$pub"
}

do_delete_client() {
  server_exists || { err "Сервер не создан"; return 1; }
  local c raw n pubs=() names=() row pub
  local -a parts=()
  echo -e "  ${C}1)${N} Одного по номеру"
  echo -e "  ${C}2)${N} Несколько по именам"
  read_choice c "${C}  Выбор [1-2] (Enter = 1): ${N}" 1 2 1
  if [[ "$c" == 1 ]]; then
    _pick_client || return 0
    names=("${CHOSEN%%$'\t'*}"); pubs=("${CHOSEN#*$'\t'}")
  else
    read_line raw "${C}  Имена через запятую: ${N}"
    IFS=',' read -r -a parts <<< "$raw"
    for n in "${parts[@]}"; do
      n="${n// /}"; [[ -n "$n" ]] || continue
      row=$(clients_tsv | awk -F'\t' -v n="$n" '$1 == n {print $2; exit}')
      if [[ -n "$row" ]]; then names+=("$n"); pubs+=("$row"); else warn "Нет клиента: $n"; fi
    done
    (( ${#pubs[@]} )) || return 0
  fi
  warn "Будут удалены: ${names[*]:-без имени}"
  read_confirm "${R}  Подтверди удаление (введи yes): ${N}" || { info "Отменено"; return 0; }
  cp -a "$SERVER_CONF" "${SERVER_CONF}.pre_delete.$(date +%s)"
  for pub in "${pubs[@]}"; do client_delete "$pub" || true; done
}

do_rename_client() {
  server_exists || { err "Сервер не создан"; return 1; }
  local old pub new f
  _pick_client || return 0
  old="${CHOSEN%%$'\t'*}"; pub="${CHOSEN#*$'\t'}"
  while true; do
    read_line new "${C}  Новое имя для ${old:-без имени}: ${N}"
    [[ -z "$new" || "$new" == "$old" ]] && return 0
    _name_free "$new" && break
    warn "Имя недопустимо или занято"
  done
  py peer-rename "$SERVER_CONF" "$pub" "$new" || return 1
  if [[ -n "$old" ]]; then
    f=$(client_file "$old")
    [[ -f "$f" ]] && mv -f "$f" "$CLIENT_DIR/${new}$(client_suffix).conf"
  fi
  ok "Переименован: ${old:-без имени} → $new"
}

_pick_client_file() {  # → путь в CHOSEN
  local files=() i c
  mapfile -t files < <(client_files)
  (( ${#files[@]} )) || { warn "Конфигов клиентов в $CLIENT_DIR нет"; return 1; }
  for i in "${!files[@]}"; do printf "  ${G}%3d)${N} %s\n" "$((i + 1))" "${files[$i]##*/}"; done
  read_choice c "${C}  Номер (Enter = 1, 0 — отмена): ${N}" 0 "${#files[@]}" 1
  (( c == 0 )) && return 1
  CHOSEN="${files[$((c - 1))]}"
}

do_show_client()    { _pick_client_file && share_config "$CHOSEN"; }
do_show_client_qr() { _pick_client_file && share_config "$CHOSEN" qr; }

do_list_clients() {
  server_exists || { err "Сервер не создан"; return 1; }
  local dump now name pub aip exp orig _ hs rx tx ep st i=0 age
  dump=$(awg show "$AWG_IF" dump 2>/dev/null | tail -n +2)
  now=$(date +%s)
  echo ""
  hdr "Клиенты"
  while IFS=$'\t' read -r name pub aip exp orig _; do
    i=$((i + 1))
    ep="" hs=0 rx=0 tx=0
    read -r ep hs rx tx < <(awk -F'\t' -v k="$pub" '$1 == k {print $3, $5, $6, $7; exit}' <<< "$dump") || true
    [[ "$ep" == "(none)" ]] && ep=""
    if [[ "${hs:-0}" =~ ^[0-9]+$ ]] && (( ${hs:-0} > 0 )); then
      age=$(( now - hs ))
      if (( age < 180 )); then st="${G}● онлайн${N} ${D}($(fmt_duration "$age") назад)${N}"
      else st="${D}○ был $(fmt_duration "$age") назад${N}"; fi
    else
      st="${D}○ не подключался${N}"
    fi
    echo -e "  ${W}$i) ${name:-без имени}${N}  ${D}$aip${N}"
    echo -e "     $st  ↑ $(fmt_bytes "${tx:-0}")  ↓ $(fmt_bytes "${rx:-0}")${ep:+  ${D}${ep%:*}${N}}"
    if [[ -n "$exp" ]]; then
      if [[ -n "$orig" ]]; then echo -e "     ${R}заблокирован: срок истёк $(expire_fmt "$exp")${N}"
      else echo -e "     ${Y}срок: $(expire_fmt "$exp")${N}"; fi
    fi
  done < <(clients_tsv)
  (( i )) || info "Клиентов нет"
}

do_export_clients() {
  local files=() out stamp
  mapfile -t files < <(client_files)
  (( ${#files[@]} )) || { warn "Конфигов клиентов нет"; return 0; }
  stamp=$(date +%Y%m%d_%H%M%S)
  if command -v zip &>/dev/null || apt_install zip >/dev/null 2>&1; then
    out="$CLIENT_DIR/awg_clients_$stamp.zip"
    zip -j -q "$out" "${files[@]}" || return 1
  else
    out="$CLIENT_DIR/awg_clients_$stamp.tar.gz"
    tar -czf "$out" -C "$CLIENT_DIR" "${files[@]##*/}" || return 1
  fi
  chmod 600 "$out"
  ok "Архив: $out (${#files[@]} конфигов)"
  info "Скачать: scp root@$(public_ip_cached):$out ."
}

# Смена мимикрии у выданного клиента: меняются только его I1-I5.
do_change_mimicry() {
  local f name
  _pick_client_file || return 0
  f="$CHOSEN"; name=$(client_name_of "$f")
  echo -e "  Сейчас: ${W}$(peer_meta_get "$name" mimicry || true)${N}"
  if [[ "$(server_profile)" == pro ]]; then
    choose_and_gen_chain || return 0
  else
    OBF_LEVEL=2
    choose_mimicry || return 0
    choose_cps_domain
    gen_chain "$MIMICRY" "$CPS_DOMAIN" --only-i1 || { warn "Генератор не выдал пакетов"; return 1; }
  fi
  cp -a "$f" "$f.bak.$(date +%s)"
  i_lines_block | py i-replace "$f" || return 1
  peer_meta_set "$name" mimicry "$(mimicry_tag)" || warn "Метку в awg0.conf обновить не удалось"
  ok "Мимикрия: $(mimicry_tag), пакетов: ${#I_LINES[@]}"
  warn "Клиенту нужен новый конфиг"
  share_config "$f"
}

do_clients_menu() {
  local c
  while true; do
    echo ""
    hdr "Клиенты ($(clients_tsv | wc -l))"
    echo -e "  ${G}1)${N} Добавить клиента"
    echo -e "  ${C}2)${N} Активность и трафик"
    echo -e "  ${C}3)${N} Показать конфиг"
    echo -e "  ${C}4)${N} Показать QR"
    echo -e "  ${C}5)${N} Переименовать"
    echo -e "  ${G}6)${N} Создать несколько"
    echo -e "  ${C}7)${N} Срок действия"
    echo -e "  ${C}8)${N} Экспорт всех (zip)"
    echo -e "  ${C}9)${N} Сменить мимикрию"
    echo -e "  ${R}10)${N} Удалить"
    echo -e "  ${W}0)${N} ← Назад"
    read_choice c "${C}  Выбор [0-10]: ${N}" 0 10 0
    case "$c" in
      1) do_add_client || true ;;     6) do_bulk_add || true ;;
      2) do_list_clients || true ;;   7) do_expire_menu || true ;;
      3) do_show_client || true ;;    8) do_export_clients || true ;;
      4) do_show_client_qr || true ;; 9) do_change_mimicry || true ;;
      5) do_rename_client || true ;;  10) do_delete_client || true ;;
      0) return 0 ;;
    esac
    pause
  done
}
