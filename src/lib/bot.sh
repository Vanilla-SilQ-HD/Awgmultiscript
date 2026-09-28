# Telegram-бот управления: установка (awg-bot-install.sh из того же канала,
# что и awg2), запуск, журнал, прокси до Telegram API, полное удаление.
# Сам бот — отдельная программа (awg_bot/), с awg2 он общается через CLI.

BOT_ARTIFACTS=(/opt/awg-bot /var/lib/awg-bot /usr/local/bin/awg-bot /usr/local/bin/awg-bot.py
               /etc/systemd/system/awg-bot.service /etc/awg-bot.conf)
BOT_VENV_PY="$BOT_DIR/venv/bin/python"

# Любой след бота, а не только маркер: после частичного удаления его
# остатки тоже надо уметь добить.
bot_installed() { [[ -f /usr/local/bin/awg-bot.py || -d "$BOT_DIR" || -f "/etc/systemd/system/$BOT_UNIT" ]]; }

bot_version() {
  sed -n "s/^__version__[[:space:]]*=[[:space:]]*[\"']\([^\"']*\)[\"'].*/\1/p" \
    "$BOT_DIR/awgbot/__init__.py" 2>/dev/null | head -1
}

# ── Прокси до Telegram ────────────────────────────────────
bot_proxy_get() {
  sed -n 's/^[[:space:]]*BOT_PROXY[[:space:]]*=[[:space:]]*//p' "$BOT_CONF" 2>/dev/null | tail -1 \
    | sed -e 's/[[:space:]]*$//' -e "s/^[\"']//" -e "s/[\"']\$//"
}

# Пароль прокси весит как токен бота, а меню снимают на скриншоты
bot_proxy_mask() { if [[ "$1" == *@* ]]; then echo "${1%%://*}://***@${1##*@}"; else echo "$1"; fi; }

bot_proxy_valid() {
  local url="$1" scheme="${1%%://*}"
  [[ "$url" == *://?* ]] || return 1
  [[ "$scheme" == iface ]] && { [[ "${url#iface://}" =~ ^[A-Za-z0-9_.:-]{1,15}$ ]]; return; }
  [[ " $BOT_PROXY_SCHEMES " == *" $scheme "* ]]
}

# Любой HTTP-ответ api.telegram.org значит «прокси работает» (на / там 404)
bot_proxy_probe() {
  local code via=(--proxy "$1")
  [[ "$1" == iface://* ]] && via=(--interface "${1#iface://}")
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 "${via[@]}" https://api.telegram.org/ 2>/dev/null) || code=000
  [[ "$code" =~ ^[1-5][0-9][0-9]$ ]]
}

_bot_proxy_write() {  # url (пусто — убрать)
  [[ -f "$BOT_CONF" ]] || { err "Нет $BOT_CONF — сначала установи бота"; return 1; }
  { grep -vE '^[[:space:]]*BOT_PROXY[[:space:]]*=' "$BOT_CONF" || true
    if [[ -n "$1" ]]; then echo "BOT_PROXY=$1"; fi; } | write_file "$BOT_CONF" 600
}

# Выходы этого сервера, годные боту, строки «url|описание».
_bot_proxy_candidates() {
  local list=() dev line url
  [[ -n "$(xray_port_owners)" ]] && list+=("socks5://$XRAY_SOCKS|SOCKS-вход Xray")
  url=$(t2s_proxy)
  [[ -n "$url" ]] && list+=("socks5://$url|прокси tun2socks")
  for dev in /sys/class/net/*; do
    dev="${dev##*/}"
    case "$dev" in
      warp0) list+=("iface://$dev|WARP") ;;
      awg-exit-*) list+=("iface://$dev|exit-нода ${dev#awg-exit-}") ;;
      xray0) list+=("iface://$dev|TUN Xray") ;;
      tun0) list+=("iface://$dev|TUN tun2socks") ;;
    esac
  done
  for line in ${list[@]+"${list[@]}"}; do
    if bot_proxy_probe "${line%%|*}"; then echo "$line — Telegram отвечает"
    else echo "$line — Telegram НЕ отвечает"; fi
  done
}

bot_proxy_menu() {
  local cur c cands=() i url
  cur=$(bot_proxy_get)
  echo -e "  Сейчас: ${W}$([[ -n "$cur" ]] && bot_proxy_mask "$cur" || echo "нет — напрямую")${N}"
  echo -e "  ${D}Нужен, если Telegram заблокирован: SOCKS5/HTTP или туннель сервера.${N}"
  echo -e "  ${C}1)${N} Задать   ${C}2)${N} Проверить   ${R}3)${N} Убрать   ${W}0)${N} Назад"
  read_choice c "${C}  Выбор [0-3]: ${N}" 0 3 0
  case "$c" in
    1) info "Ищу прокси и туннели на сервере..."
       mapfile -t cands < <(_bot_proxy_candidates)
       for i in "${!cands[@]}"; do echo -e "  ${C}$((i + 1)))${N} ${W}${cands[$i]%%|*}${N} ${D}${cands[$i]#*|}${N}"; done
       url=""
       if (( ${#cands[@]} )); then
         read_choice c "${C}  Выбор (0 — ввести адрес): ${N}" 0 "${#cands[@]}" 0
         (( c )) && url="${cands[$((c - 1))]%%|*}"
       fi
       if [[ -z "$url" ]]; then
         echo -e "  ${D}Формат: схема://[логин:пароль@]хост:порт или iface://warp0${N}"
         read_line url "${C}  Адрес: ${N}"
         url="${url//[[:space:]]/}"
         [[ -n "$url" ]] || return 0
       fi
       bot_proxy_valid "$url" || { err "Нужна схема: ${BOT_PROXY_SCHEMES// /, }"; return 1; }
       if bot_proxy_probe "$url"; then ok "Через прокси Telegram отвечает"
       else ask_yes "  Telegram через него не отвечает. Всё равно сохранить? [y/N]: " n || return 0; fi
       # На давно установленном боте в venv может не быть нужных модулей
       if [[ "$url" == socks* && -x "$BOT_VENV_PY" ]] && ! "$BOT_VENV_PY" -c 'import aiohttp_socks' 2>/dev/null; then
         "$BOT_DIR/venv/bin/pip" install -q aiohttp-socks &>/dev/null || warn "Не поставился aiohttp-socks — обнови бота"
       fi
       if [[ "$url" == iface://* && -x "$BOT_VENV_PY" ]] && ! "$BOT_VENV_PY" -c \
          'import inspect,aiohttp; assert "socket_factory" in inspect.signature(aiohttp.TCPConnector).parameters' 2>/dev/null; then
         "$BOT_DIR/venv/bin/pip" install -q -U aiogram aiohttp &>/dev/null || warn "Не обновился aiohttp (нужен 3.12+) — обнови бота"
       fi
       _bot_proxy_write "$url" || return 1
       ok "Прокси: $(bot_proxy_mask "$url")"
       [[ "$url" == iface://* || "$url" == *127.0.0.1* ]] && info "Туннель лёг — бот пойдёт напрямую; поднял — systemctl restart awg-bot" ;;
    2) [[ -n "$cur" ]] || { info "Прокси не задан"; return 0; }
       if bot_proxy_probe "$cur"; then ok "Telegram отвечает"; else err "Через прокси Telegram не отвечает"; fi
       return 0 ;;
    3) [[ -n "$cur" ]] || return 0
       _bot_proxy_write "" && ok "Прокси убран" ;;
    *) return 0 ;;
  esac
  unit_active "$BOT_UNIT" && systemctl restart "$BOT_UNIT" && ok "Бот перезапущен"
  return 0
}

# ── Установка / удаление ──────────────────────────────────
# Код бота из распакованного архива рядом: при проверке правок на GitHub
# ещё старая версия.
_bot_local_src() {
  local d best="" ts best_ts=0
  d=$(dirname "$(readlink -f "$0")")
  [[ -d "$d/awg_bot/awgbot" && -f "$d/awg_bot/run.py" ]] && { echo "$d/awg_bot"; return 0; }
  for d in /opt/awg-toolza-*/ /root/awg-toolza-*/ /opt/awg-toolza/; do
    d="${d%/}"
    [[ -f "$d/awg_bot/run.py" ]] || continue
    ts=$(stat -c %Y "$d/awg_bot/run.py")
    (( ts >= best_ts )) && { best="$d/awg_bot"; best_ts=$ts; }
  done
  [[ -n "$best" ]] && echo "$best"
}

bot_install() {
  local src installer
  src=$(_bot_local_src || true)
  mktmp installer || return 1
  if [[ -n "$src" ]] && ask_yes "  Найден локальный код бота ($src). Ставить из него? [Y/n]: " y; then
    if [[ -f "${src%/awg_bot}/awg-bot-install.sh" ]]; then
      bash "${src%/awg_bot}/awg-bot-install.sh" --src "$src"
      return
    fi
    curl -fsSL "$BOT_INSTALL_URL" -o "$installer" || { err "Не скачался установщик"; return 1; }
    bash "$installer" --src "$src"
    return
  fi
  info "Установщик бота — канал $(update_channel_label)"
  curl -fsSL "$BOT_INSTALL_URL" -o "$installer" || { err "Не скачался установщик: $BOT_INSTALL_URL"; return 1; }
  # Бот и awg2 — из одного репозитория, иначе на бете они разъедутся
  AWG_REPO_URL="https://github.com/$UPDATE_REPO" bash "$installer"
}

# $1 = quiet — без вопроса. Токен перед удалением копируется в бэкапы.
bot_uninstall() {
  local p saved="" left=()
  if [[ "${1:-}" != quiet ]]; then
    warn "Будут удалены служба, код, venv и конфиг с токеном. AWG не затрагивается."
    read_confirm "${R}  Удалить бота? (введи yes): ${N}" || return 0
  fi
  if [[ -f "$BOT_CONF" ]]; then
    mkdir -p "$BACKUP_DIR" && chmod 700 "$BACKUP_DIR"
    saved="$BACKUP_DIR/awg-bot.conf.$(date +%Y%m%d_%H%M%S)"
    cp -a "$BOT_CONF" "$saved" || saved=""
  fi
  systemctl disable --now "$BOT_UNIT" &>/dev/null || true
  for p in "${BOT_ARTIFACTS[@]}"; do rm -rf "$p"; done
  systemctl daemon-reload
  systemctl reset-failed "$BOT_UNIT" &>/dev/null || true
  for p in "${BOT_ARTIFACTS[@]}"; do [[ -e "$p" ]] && left+=("$p"); done
  if (( ${#left[@]} )); then warn "Не удалось удалить: ${left[*]}"; else ok "Бот удалён"; fi
  [[ -n "$saved" ]] && info "Конфиг с токеном сохранён: $saved"
  log_info "бот удалён"
}

do_bot_menu() {
  local c v px
  while true; do
    echo ""
    hdr "Telegram-бот"
    if bot_installed; then
      if unit_active "$BOT_UNIT"; then echo -e "  Статус : ${G}● работает${N}"; else echo -e "  Статус : ${Y}○ остановлен${N}"; fi
      v=$(bot_version); px=$(bot_proxy_get)
      echo -e "  Версия : ${W}${v:-?}${N}"
      echo -e "  Прокси : $([[ -n "$px" ]] && bot_proxy_mask "$px" || echo "нет — напрямую")"
      echo ""
      echo -e "  ${C}1)${N} Обновить / переустановить   ${C}2)${N} Запустить     ${C}3)${N} Остановить"
      echo -e "  ${C}4)${N} Перезапустить               ${C}5)${N} Журнал        ${C}6)${N} Прокси до Telegram"
      echo -e "  ${R}7)${N} Удалить бота                ${W}0)${N} ← Назад"
      read_choice c "${C}  Выбор [0-7]: ${N}" 0 7 0
    else
      echo -e "  ${D}Управление сервером из Telegram: клиенты, сроки, туннели, статус.${N}"
      echo -e "  ${C}1)${N} Установить бота   ${W}0)${N} ← Назад"
      read_choice c "${C}  Выбор [0-1]: ${N}" 0 1 0
    fi
    case "$c" in
      1) bot_install || warn "Установщик завершился с ошибкой" ;;
      2) systemctl start "$BOT_UNIT" && ok "Запущен" || err "Не запустился: journalctl -u $BOT_UNIT" ;;
      3) systemctl stop "$BOT_UNIT" && ok "Остановлен" || true ;;
      4) systemctl restart "$BOT_UNIT" && ok "Перезапущен" || err "Не запустился: journalctl -u $BOT_UNIT" ;;
      5) journalctl -u "$BOT_UNIT" -n 40 --no-pager 2>/dev/null || true ;;
      6) bot_proxy_menu || true ;;
      7) bot_uninstall || true ;;
      0) return 0 ;;
    esac
    pause
  done
}
