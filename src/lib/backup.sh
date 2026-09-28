# Бэкапы в ~/awg_backup (домашний каталог того, кто запустил sudo):
#   awg2_backup_<время>/        — полный: сервер, клиенты, WARP, WG + обфускатор,
#                                 настройки туннелей (tunnels.tar.gz);
#   auto_<причина>_<время>.tar.gz — перед опасными операциями: сервер и клиенты.

# Настройки туннелей: сами туннели при восстановлении не включаются.
_BACKUP_TUNNEL_PATHS=()
_backup_tunnel_paths() {
  local p
  _BACKUP_TUNNEL_PATHS=()
  for p in "$XRAY_DIR" "$EXITS_STATE" "$EXITS_PEERS" "$CASCADE_RULES" "$T2S_CONF" "$DNS_PROXY_CONF" \
           "$EXITS_DIR"/awg-exit-*.conf; do
    [[ -e "$p" ]] && _BACKUP_TUNNEL_PATHS+=("${p#/}")
  done
  return 0
}

auto_backup() {  # причина
  local files=() arch f
  [[ -f "$SERVER_CONF" ]] || return 0
  mkdir -p "$BACKUP_DIR" && chmod 700 "$BACKUP_DIR"
  arch="$BACKUP_DIR/auto_${1:-operation}_$(date +%Y%m%d_%H%M%S).tar.gz"
  files=("${SERVER_CONF#/}")
  while IFS= read -r f; do files+=("${f#/}"); done < <(client_files)
  tar -czf "$arch" -C / "${files[@]}" 2>/dev/null || return 1
  chmod 600 "$arch"
  info "Авто-бэкап: ${arch##*/}"
}

do_backup() {
  local ts dir n=0 f
  ts=$(date +%Y%m%d_%H%M%S)
  dir="$BACKUP_DIR/awg2_backup_$ts"
  mkdir -p "$dir" && chmod 700 "$BACKUP_DIR" "$dir"
  if [[ -f "$SERVER_CONF" ]]; then cp -a "$SERVER_CONF" "$dir/awg0.conf"; n=$((n + 1)); ok "Сервер: awg0.conf"
  else warn "Серверного конфига нет"; fi
  while IFS= read -r f; do cp -a "$f" "$dir/"; n=$((n + 1)); done < <(client_files)
  (( n > 1 )) && ok "Клиентов: $((n - 1))"
  iface_up && awg show "$AWG_IF" > "$dir/awg_show_dump.txt" 2>/dev/null
  # WARP: перерегистрация упирается в лимиты Cloudflare — аккаунт бережём
  if [[ -d "$WARP_DIR" ]]; then
    mkdir -p "$dir/warp" && cp -a "$WARP_DIR" "$dir/warp/wgcf" && ok "WARP (wg): аккаунт"
    [[ -f "$WARP_CONF" ]] && cp -a "$WARP_CONF" "$dir/warp/warp0.conf"
  fi
  if [[ -f "$USQUE_CONF" ]]; then
    mkdir -p "$dir/warp/usque" && cp -a "$USQUE_CONF" "$dir/warp/usque/config.json" && ok "WARP (usque): регистрация"
  fi
  if wgobf_installed; then
    mkdir -p "$dir/wgobf"
    cp -a "$WGOBF_DIR" "$dir/wgobf/etc" && cp -a "$WGOBF_WG_CONF" "$dir/wgobf/$WGOBF_IF.conf" && ok "WG + обфускатор"
    [[ -d "$WGOBF_CLIENTS" ]] && cp -a "$WGOBF_CLIENTS" "$dir/wgobf/clients"
  fi
  _backup_tunnel_paths
  if (( ${#_BACKUP_TUNNEL_PATHS[@]} )); then
    tar -czf "$dir/tunnels.tar.gz" -C / "${_BACKUP_TUNNEL_PATHS[@]}" 2>/dev/null && ok "Настройки туннелей"
  fi
  [[ -f "$LOG_FILE" ]] && cp -a "$LOG_FILE" "$dir/awg-manager.log"
  {
    echo "timestamp=$ts"
    echo "server_conf=$SERVER_CONF"
    echo "backed_files=$n"
    echo "awg_version=$(server_proto 2>/dev/null)"
    echo "warp_backend=$(warp_backend)"
    echo "toolza=$VERSION"
    echo "hostname=$(hostname)"
  } > "$dir/backup_meta.txt"
  chmod -R go-rwx "$dir"
  success_box "Бэкап: $dir"
  log_info "бэкап: $dir"
}

_restore_list() {  # → строки «путь» (новые сверху)
  find "$BACKUP_DIR" -maxdepth 1 \( -type d -name 'awg2_backup_*' -o -type f -name 'auto_*.tar.gz' \) \
    -printf '%T@ %p\n' 2>/dev/null | sort -rn | cut -d' ' -f2-
}

_restore_awg_files() {  # каталог бэкапа
  local src="$1" f
  install -D -m 600 "$src/awg0.conf" "$SERVER_CONF"
  while IFS= read -r -d '' f; do
    rm -f "$CLIENT_DIR/$(client_name_of "$f")"_awg[23].conf
    install -m 600 "$f" "$CLIENT_DIR/${f##*/}"
  done < <(find "$src" -maxdepth 1 -name '*_awg[23].conf' -print0)
}

_restore_warp() {  # каталог бэкапа
  local src="$1/warp" be
  [[ -d "$src" ]] || return 0
  if [[ -d "$src/wgcf" ]]; then
    mkdir -p "$WARP_DIR" && cp -a "$src/wgcf/." "$WARP_DIR/" && chmod 700 "$WARP_DIR" && ok "WARP (wg): аккаунт"
    # Состояние «включён» из бэкапа не переносим — туннель включают руками
    rm -f "$WARP_STATE" "$WARP_STATE.failed"
  fi
  [[ -f "$src/warp0.conf" ]] && install -D -m 600 "$src/warp0.conf" "$WARP_CONF"
  if [[ -f "$src/usque/config.json" ]]; then
    install -D -m 600 "$src/usque/config.json" "$USQUE_CONF" && chmod 700 "$USQUE_DIR" && ok "WARP (usque): регистрация"
  fi
  be=$(sed -n 's/^warp_backend=//p' "$1/backup_meta.txt" 2>/dev/null)
  [[ "$be" == wg || "$be" == usque ]] && echo "$be" | write_file "$WARP_BACKEND_FILE" 644
  info "WARP восстановлен выключенным — включи его в меню туннелей"
}

_restore_tunnels() {  # каталог бэкапа
  local arch="$1/tunnels.tar.gz" n
  [[ -f "$arch" ]] || return 0
  ask_yes "  Восстановить настройки туннелей (Xray, exit-ноды, каскад, tun2socks, DNS)? [Y/n]: " y || return 0
  tar -xzf "$arch" -C / || { warn "Настройки туннелей не распаковались"; return 0; }
  rm -f "$XRAY_STATE"
  [[ -f "$EXITS_STATE" ]] && exits_state_set state inactive
  for n in $(exits_nodes); do systemctl enable --now "awg-quick@awg-exit-$n" &>/dev/null || warn "Нода $n не поднялась"; done
  (( $(cascade_count) )) && { _cascade_persist; systemctl restart awg-cascade.service &>/dev/null; }
  ok "Настройки туннелей восстановлены; маршрутизация клиентов выключена"
}

do_restore() {
  local list=() i c src label name tmp port
  command -v awg-quick &>/dev/null || { err "Нет awg-quick — сначала установи компоненты (Сервер → 1)"; return 1; }
  mapfile -t list < <(_restore_list)
  (( ${#list[@]} )) || { err "Бэкапов нет в $BACKUP_DIR"; return 1; }
  for i in "${!list[@]}"; do
    name="${list[$i]##*/}"
    if [[ -d "${list[$i]}" ]]; then echo -e "  ${C}$((i + 1)))${N} $name ${D}(полный)${N}"
    else echo -e "  ${C}$((i + 1)))${N} $name ${D}(авто: сервер и клиенты)${N}"; fi
  done
  read_choice c "${C}  Бэкап (Enter = 1, 0 — отмена): ${N}" 0 "${#list[@]}" 1
  (( c )) || return 0
  src="${list[$((c - 1))]}"
  label="${src##*/}"
  if [[ -f "$src" ]]; then
    mktmp tmp -d || return 1
    tar -xzf "$src" -C "$tmp" || { err "Архив не распаковался"; return 1; }
    mkdir -p "$tmp/flat"
    cp -a "$tmp${SERVER_CONF}" "$tmp/flat/awg0.conf" 2>/dev/null || { err "В архиве нет awg0.conf"; return 1; }
    find "$tmp" -path "$tmp/flat" -prune -o -name '*_awg[23].conf' -exec cp -a {} "$tmp/flat/" \;
    src="$tmp/flat"
  fi
  [[ -f "$src/awg0.conf" ]] || { err "В бэкапе нет awg0.conf"; return 1; }
  read_confirm "${R}  Текущий сервер будет заменён. Продолжить? (введи yes): ${N}" || return 0
  awg-quick down "$SERVER_CONF" &>/dev/null || ip link del "$AWG_IF" &>/dev/null || true
  [[ -f "$SERVER_CONF" ]] && cp -a "$SERVER_CONF" "$SERVER_CONF.pre_restore.$(date +%s)"
  _restore_awg_files "$src"
  client_files_sync_suffix
  ok "Сервер и клиенты: $(client_files | wc -l) кл."
  _restore_warp "$src"
  if [[ -f "$src/wgobf/$WGOBF_IF.conf" && -d "$src/wgobf/etc" ]] \
     && ask_yes "  В бэкапе есть WG + обфускатор — восстановить? [Y/n]: " y; then
    wgobf_restore "$src/wgobf" || true
  fi
  _restore_tunnels "$src"
  # Восстановление на чистый сервер: автозапуск, форвардинг и порт в UFW
  ip_forward_enable
  setup_autostart
  port=$(server_port)
  [[ -n "$port" ]] && ufw_allow "$port/udp" AmneziaWG
  expire_install
  if awg_up_diag; then ok "awg0 поднят"; else err "awg0 не поднялся — конфиг: $SERVER_CONF"; return 1; fi
  success_box "Восстановлено из $label"
  log_info "восстановление из $label"
}
