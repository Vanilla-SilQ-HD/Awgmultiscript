# Срок действия клиентов. Истёкший клиент не удаляется, а блокируется:
# его AllowedIPs меняется на 127.0.0.2/32, исходный адрес сохраняется меткой
# «# orig_ips=» — разблокировка возвращает его на место. Метку «# expires=»
# ставит и Telegram-бот, поэтому таймер нужен независимо от того, кто
# назначил срок.

# Уведомление владельцам и админам бота — напрямую в Telegram, через прокси
# бота: таймер работает и тогда, когда сам бот остановлен.
_expire_notify() {
  local token="" proxy="" id ids=() via=()
  [[ -f "$BOT_CONF" ]] || return 0
  { read -r token; read -r proxy; mapfile -t ids; } < <(py tg-targets "$BOT_CONF" "$BOT_ADMINS" 2>/dev/null)
  [[ -n "$token" ]] && (( ${#ids[@]} )) || return 0
  case "$proxy" in
    iface://*) via=(--interface "${proxy#iface://}") ;;
    ?*) via=(--proxy "$proxy") ;;
  esac
  for id in "${ids[@]}"; do
    # Токен не попадает в argv (его видно в списке процессов) — curl читает конфиг со stdin
    curl -sf --max-time 8 ${via[@]+"${via[@]}"} --config - >/dev/null 2>&1 <<EOF || true
url = "https://api.telegram.org/bot${token}/sendMessage"
data = "chat_id=${id}"
data = "parse_mode=HTML"
data-urlencode = "text=$1"
EOF
  done
}

# Точка входа таймера (awg2-expire-check).
expire_check_run() {
  local out ev name arg stripped
  [[ -f "$SERVER_CONF" ]] || return 0
  out=$(py expire-check "$SERVER_CONF" "$EXPIRE_SUSPEND_IP" "$EXPIRE_STATE_DIR" 2>>"$EXPIRE_LOG") || return 0
  while IFS=$'\t' read -r ev name arg; do
    case "$ev" in
      CHANGED)
        stripped=$(awg-quick strip "$AWG_IF" 2>/dev/null) \
          && awg syncconf "$AWG_IF" <(printf '%s\n' "$stripped") 2>>"$EXPIRE_LOG" ;;
      EXPIRED)
        echo "$(date '+%F %T') expired: $name (было $arg)" >> "$EXPIRE_LOG"
        command -v conntrack >/dev/null && conntrack -D -s "${arg%%/*}" >/dev/null 2>&1
        _expire_notify "🚫 Клиент <b>${name}</b> заблокирован: срок действия истёк." ;;
      WARN1H)
        echo "$(date '+%F %T') warn1h: $name ($arg мин)" >> "$EXPIRE_LOG"
        _expire_notify "⚠️ Клиент <b>${name}</b> истекает через ${arg} мин." ;;
    esac
  done <<< "$out"
  return 0
}

expire_install() {
  mkdir -p "$EXPIRE_STATE_DIR"
  emit_script "$EXPIRE_BIN" 'expire_check_run' \
    SERVER_CONF AWG_IF EXPIRE_SUSPEND_IP EXPIRE_STATE_DIR EXPIRE_LOG BOT_CONF BOT_ADMINS _PY_HELPER \
    py _expire_notify expire_check_run || return 1
  write_file "$EXPIRE_SERVICE" 644 <<EOF
[Unit]
Description=AWG Toolza — проверка сроков клиентов
After=awg-quick@awg0.service network-online.target

[Service]
Type=oneshot
ExecStart=$EXPIRE_BIN
EOF
  write_file "$EXPIRE_TIMER" 644 <<'EOF'
[Unit]
Description=AWG Toolza — таймер проверки сроков

[Timer]
OnBootSec=30s
OnUnitActiveSec=1min
AccuracySec=10s
Persistent=true

[Install]
WantedBy=timers.target
EOF
  systemctl daemon-reload
  systemctl enable --now awg2-expire.timer &>/dev/null || warn "Таймер сроков не запустился: systemctl status awg2-expire.timer"
}

expire_remove() {
  remove_unit awg2-expire.timer awg2-expire.service
  rm -f "$EXPIRE_BIN"
  rm -rf "$EXPIRE_STATE_DIR"
}

expire_fmt() {  # unix-время → «31.12.2026 23:59 (через 3д 4ч)»
  local ts="$1" d abs s="" when
  d=$(( ts - $(date +%s) )); abs=${d#-}
  (( abs >= 86400 )) && s+="$((abs / 86400))д "
  (( abs % 86400 >= 3600 )) && s+="$((abs % 86400 / 3600))ч "
  (( abs < 86400 )) && s+="$((abs % 3600 / 60))м"
  s="${s% }"
  when=$(date -d "@$ts" '+%d.%m.%Y %H:%M' 2>/dev/null || echo "$ts")
  if (( d >= 0 )); then echo "$when (через $s)"; else echo "$when (истёк $s назад)"; fi
}

_expire_apply() {
  local stripped
  iface_up || return 0
  stripped=$(awg-quick strip "$AWG_IF" 2>/dev/null) && awg syncconf "$AWG_IF" <(printf '%s\n' "$stripped")
}

do_expire_menu() {
  server_exists || { err "Сервер не создан"; return 1; }
  expire_install
  local c name pub ts now rows=() n=0 exp orig
  while true; do
    echo ""
    hdr "Срок действия клиентов"
    now=$(date +%s)
    while IFS='|' read -r name pub _ exp orig _; do
      [[ -n "$exp" ]] || continue
      n=$((n + 1))
      if [[ -n "$orig" ]]; then echo -e "  ${R}🚫 ${name}${N} ${D}— заблокирован, $(expire_fmt "$exp")${N}"
      else echo -e "  ${Y}⏰ ${name}${N} ${D}— $(expire_fmt "$exp")${N}"; fi
    done < <(clients_psv)
    (( n )) || echo -e "  ${D}Сроков нет — все клиенты бессрочные${N}"
    n=0
    echo ""
    echo -e "  ${C}1)${N} Поставить срок"
    echo -e "  ${C}2)${N} Снять срок / разблокировать"
    echo -e "  ${R}3)${N} Удалить заблокированных"
    echo -e "  ${W}0)${N} ← Назад"
    read_choice c "${C}  Выбор [0-3]: ${N}" 0 3 0
    case "$c" in
      1) _pick_client || continue
         name="${CHOSEN%%$'\t'*}"
         [[ -n "$name" ]] || { warn "У клиента нет имени"; continue; }
         ts=$(_ask_expire)
         [[ -n "$ts" ]] && { client_expire_set "$name" "$ts" || true; } ;;
      2) _pick_client || continue
         client_expire_clear "${CHOSEN%%$'\t'*}" || true ;;
      3) mapfile -t rows < <(clients_tsv | awk -F'\t' '$5 != "" {print $1}')
         (( ${#rows[@]} )) || { info "Заблокированных нет"; continue; }
         warn "Будут удалены навсегда: ${rows[*]}"
         read_confirm "${R}  Подтверди (введи yes): ${N}" && clients_purge_blocked ;;
      0) return 0 ;;
    esac
  done
}
