# Самообновление. Канал stable — основной репозиторий, beta — ранние сборки.
# Выбор хранится в /var/lib/awg2/channel; AWG2_UPDATE_CHANNEL=beta — разовый
# запуск на другом канале. У каналов раздельные кэши проверки версии.

UPDATE_CHANNEL="" UPDATE_REPO="" UPDATE_URL="" UPDATE_CACHE="" BOT_INSTALL_URL=""

update_channel_apply() {
  if [[ "${1:-}" == beta ]]; then
    UPDATE_CHANNEL=beta; UPDATE_REPO="$UPDATE_REPO_BETA"; UPDATE_CACHE="$STATE_DIR/update_check.beta"
  else
    UPDATE_CHANNEL=stable; UPDATE_REPO="$UPDATE_REPO_STABLE"; UPDATE_CACHE="$STATE_DIR/update_check"
  fi
  UPDATE_URL="https://raw.githubusercontent.com/$UPDATE_REPO/main/awg2.sh"
  BOT_INSTALL_URL="https://raw.githubusercontent.com/$UPDATE_REPO/main/awg-bot-install.sh"
}

update_channel_read() {
  [[ "$(tr -d '[:space:]' 2>/dev/null < "$UPDATE_CHANNEL_FILE")" == beta ]] && echo beta || echo stable
}

update_channel_label() { [[ "$UPDATE_CHANNEL" == beta ]] && echo "бета" || echo "стабильный"; }

update_channel_init() { update_channel_apply "${AWG2_UPDATE_CHANNEL:-$(update_channel_read)}"; }

# Фоновая проверка раз в 6 часов: шапка меню читает только кэш и сеть не ждёт.
# Качаем первые 4 КБ — VERSION= стоит в начале файла.
update_check_async() {
  local ts now
  [[ -n "${AWG_NO_UPDATE_CHECK:-}" ]] && return 0
  now=$(date +%s)
  ts=$(awk '{print $2 + 0; exit}' "$UPDATE_CACHE" 2>/dev/null || echo 0)
  (( now - ${ts:-0} < UPDATE_CHECK_TTL )) && return 0
  mkdir -p "$STATE_DIR"
  (
    v=$(curl -fsSL --connect-timeout 5 --max-time 10 -r 0-4095 -H 'Cache-Control: no-cache' \
          "$UPDATE_URL?nocache=$now" 2>/dev/null | grep -m1 '^VERSION=' | cut -d'"' -f2)
    [[ -n "$v" ]] && printf '%s %s\n' "$v" "$(date +%s)" > "$UPDATE_CACHE"
  ) </dev/null &>/dev/null &
  disown 2>/dev/null || true
}

update_available() {  # → версия, если новее текущей
  local v
  v=$(awk '{print $1; exit}' "$UPDATE_CACHE" 2>/dev/null)
  [[ "$v" =~ ^v?[0-9]+\.[0-9]+ ]] || return 1
  (( 10#$(ver_num "$v") > 10#$(ver_num "$VERSION") )) || return 1
  echo "$v"
}

_update_download() {  # файл
  local mp url
  url="$UPDATE_URL?nocache=$(date +%s)"
  for mp in "${GH_MIRRORS[@]}"; do
    [[ -n "$mp" ]] && info "Через зеркало ${mp}"
    curl -fL --connect-timeout 10 --max-time 120 --progress-bar -H 'Cache-Control: no-cache' \
      "${mp}${url}" -o "$1" && return 0
  done
  return 1
}

do_self_update() {
  local tmp new cur_n new_n target="$SCRIPT_PATH"
  [[ -f "$target" ]] || target=$(readlink -f "$0")
  info "Канал: $(update_channel_label) ${D}($UPDATE_REPO)${N}"
  mktmp tmp || return 1
  _update_download "$tmp" || { err "Не удалось скачать обновление"; return 1; }
  if (( $(stat -c%s "$tmp") < 50000 )) || ! head -1 "$tmp" | grep -q '^#!.*bash' || ! bash -n "$tmp" 2>/dev/null; then
    err "Скачанный файл повреждён (не bash или синтаксическая ошибка) — повтори позже"
    return 1
  fi
  new=$(head -c 4096 "$tmp" | grep -m1 '^VERSION=' | cut -d'"' -f2)
  [[ -n "$new" ]] || { err "В скачанном файле нет VERSION"; return 1; }
  cur_n=$(ver_num "$VERSION"); new_n=$(ver_num "$new")
  echo -e "  Текущая: ${W}$VERSION${N}   В канале: ${W}$new${N}"
  if (( 10#$new_n < 10#$cur_n )); then
    warn "В канале версия старше текущей — это откат"
    read_confirm "${R}  Откатиться до $new? (введи yes): ${N}" || return 0
  elif (( 10#$new_n == 10#$cur_n )); then
    cmp -s "$target" "$tmp" && { ok "Уже последняя версия"; return 0; }
    ask_yes "  Версия та же, но файл отличается. Перезаписать? [y/N]: " n || return 0
  else
    ask_yes "  Установить $new? [Y/n]: " y || return 0
  fi
  cp -a "$target" "$target.bak" 2>/dev/null && info "Прежняя версия: $target.bak"
  install -m 755 "$tmp" "$target" || { err "Не удалось заменить $target"; return 1; }
  printf '%s %s\n' "$new" "$(date +%s)" > "$UPDATE_CACHE" 2>/dev/null || true
  hash -r
  ok "Установлено: $new"
  log_info "самообновление $VERSION → $new"
  # В памяти старый код, а bash дочитывает файл по ходу — продолжать здесь нельзя
  info "Перезапускаюсь..."
  exec "$target" --post-update "$VERSION"
}

do_switch_channel() {
  local to=beta
  [[ "$UPDATE_CHANNEL" == beta ]] && to=stable
  if [[ "$to" == beta ]]; then
    warn "Бета — ранние сборки: правки приезжают раньше, но могут быть сырыми"
    ask_yes "  Переключиться на бета-канал? [y/N]: " n || return 0
  fi
  mkdir -p "$STATE_DIR"
  echo "$to" | write_file "$UPDATE_CHANNEL_FILE" 644
  update_channel_apply "$to"
  ok "Канал: $(update_channel_label)"
  ask_yes "  Обновиться с этого канала сейчас? [Y/n]: " y && do_self_update
  return 0
}

# Служебные скрипты (автозапуск туннелей, таймеры) генерируются из кода awg2.
# После смены версии перегенерируем их у уже включённых компонентов — иначе
# при загрузке работала бы логика прежней версии.
helpers_refresh() {
  local mark="$STATE_DIR/version"
  [[ "$(cat "$mark" 2>/dev/null)" == "$VERSION" ]] && return 0
  mkdir -p "$STATE_DIR"
  server_exists && expire_install &>/dev/null
  if [[ -f "$WARP_AUTOSTART_SCRIPT" ]]; then
    emit_script "$WARP_AUTOSTART_SCRIPT" 'warp_wg_bringup' \
      WARP_CONF WARP_IF WARP_TABLE WARP_PEERS "${RT_FUNCS[@]}" warp_wg_bringup
  fi
  if [[ -f "$WARP_HEALTH_SCRIPT" ]]; then
    emit_script "$WARP_HEALTH_SCRIPT" 'warp_health_run' WARP_IF WARP_TABLE WARP_STATE \
      WARP_BACKEND_FILE WARP_HEALTH_LOG "${RT_FUNCS[@]}" warp_health_run
  fi
  [[ -f "$USQUE_UP_HOOK" ]] && _usque_write &>/dev/null
  if [[ -f "$DNS_PROXY_STATE" ]]; then
    _dns_emit_helpers &>/dev/null
    # Прежние версии ставили блок DoT в FORWARD ниже ACCEPT — он не работал
    iface_up && { dns_rules_down; dns_rules_up; }
  fi
  if (( $(cascade_count) )); then
    _cascade_persist && cascade_apply_all
  fi
  [[ -f "$T2S_ROUTING_SCRIPT" ]] && emit_script "$T2S_ROUTING_SCRIPT" 't2s_routing_run "$@"' \
    T2S_IF T2S_TABLE T2S_ADDR "${RT_FUNCS[@]}" t2s_routing_run
  [[ -f "$EXITS_SCRIPT" ]] && _exits_write_unit
  # Xray прежних версий жил во временных юнитах и перезагрузку не переживал
  [[ -f "$XRAY_STATE" && ! -f "/etc/systemd/system/$XRAY_UNIT" ]] && ! xray_is_up && rm -f "$XRAY_STATE"
  wgobf_installed && _wgobf_write_service_files
  echo "$VERSION" > "$mark"
  log_info "служебные скрипты обновлены под $VERSION"
}

do_update_menu() {
  local c upd
  while true; do
    echo ""
    hdr "Обновление скрипта"
    echo -e "  Версия : ${W}$VERSION${N}"
    echo -e "  Канал  : $([[ "$UPDATE_CHANNEL" == beta ]] && echo -e "${Y}бета${N}" || echo -e "${G}стабильный${N}") ${D}($UPDATE_REPO)${N}"
    upd=$(update_available || true)
    [[ -n "$upd" ]] && echo -e "  Доступна: ${G}$upd${N}"
    echo ""
    echo -e "  ${C}1)${N} Обновить скрипт"
    if [[ "$UPDATE_CHANNEL" == beta ]]; then echo -e "  ${C}2)${N} Вернуться на стабильный канал"
    else echo -e "  ${C}2)${N} Бета-канал ${D}(ранние сборки)${N}"; fi
    echo -e "  ${W}0)${N} ← Назад"
    read_choice c "${C}  Выбор [0-2]: ${N}" 0 2 0
    case "$c" in
      1) do_self_update || true ;;
      2) do_switch_channel || true ;;
      0) return 0 ;;
    esac
    pause
  done
}
