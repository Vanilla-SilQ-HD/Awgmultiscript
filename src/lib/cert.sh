# HTTPS-сертификат сервера — Let's Encrypt через acme.sh: на IP (профиль
# shortlived, ~6 дней, продление каждые 3 дня) или на домен (90 дней).
#
# Нужен Mini App бота: Telegram открывает её только по HTTPS с настоящим
# сертификатом. Владение адресом проверяется по http-01: на время выпуска и
# продления acme.sh сам слушает 80-й порт (standalone), поэтому порт должен
# быть свободен и открыт снаружи. Для IP другого способа нет — DNS-проверка
# у Let's Encrypt только для доменов.
#
# Файлы для потребителей — $CERT_FULL и $CERT_KEY: acme.sh кладёт туда
# сертификат при выпуске и после каждого продления (таймер $CERT_TIMER).
#
# Порт 80 занят (Caddy, nginx…) — два выхода. Готовый сертификат сервера:
# его уже выпустила та программа, $CERT_FULL и $CERT_KEY становятся ссылками
# на её файлы, а продлевает она сама (kind=external). Или выпуск с паузой:
# acme.sh останавливает занявшую порт службу на секунды выпуска и каждого
# продления (хуки он запоминает сам).

cert_installed() { [[ -s "$CERT_FULL" && -s "$CERT_KEY" ]]; }
cert_get() { sed -n "s/^$1=//p" "$CERT_STATE" 2>/dev/null | head -1; }

# Срок действия (unixtime) или пусто.
cert_expires() {
  local end
  end=$(openssl x509 -enddate -noout -in "$CERT_FULL" 2>/dev/null) || return 0
  date -d "${end#notAfter=}" +%s 2>/dev/null || true
}

# Кто слушает TCP 80 — пусто, если никто.
cert_port80_holder() {
  ss -ltnpH 'sport = :80' 2>/dev/null | grep -oE 'users:\(\("[^"]+' | head -1 | sed 's/.*"//' || true
}

# Служба systemd, которая держит TCP 80, — её можно останавливать на время выпуска.
cert_port80_unit() {
  local pid unit
  pid=$(ss -ltnpH 'sport = :80' 2>/dev/null | grep -oE 'pid=[0-9]+' | head -1 | cut -d= -f2)
  [[ "$pid" =~ ^[0-9]+$ ]] || return 0
  unit=$(grep -oE '[A-Za-z0-9@._-]+\.service' "/proc/$pid/cgroup" 2>/dev/null | tail -1)
  [[ "$unit" =~ ^[A-Za-z0-9@._-]+\.service$ ]] && echo "$unit"
  return 0
}

# Готовые сертификаты сервера: «имя<TAB>источник<TAB>сертификат<TAB>ключ<TAB>до».
cert_find() {
  py cert-find "$(public_ip_cached)" "${CERT_FIND_ROOT:-/}" "$ACME_HOME" "$CERT_DIR"
}

# cert_use СЕРТИФИКАТ — взять готовый: только из найденных, не любой путь.
cert_use() {
  local want="$1" name src crt key exp old
  while IFS=$'\t' read -r name src crt key exp; do
    [[ "$crt" == "$want" ]] && break
    crt=""
  done < <(cert_find)
  [[ -n "$crt" ]] || { err "Такого готового сертификата на сервере нет"; return 1; }
  old=$(cert_get name)
  if [[ "$(cert_get kind)" =~ ^(ip|domain)$ && -n "$old" && -x "$ACME_DIR/acme.sh" ]]; then
    acme --remove -d "$old" --ecc &>/dev/null
  fi
  remove_unit "$CERT_TIMER" "$CERT_SERVICE"
  ufw_delete_matching "$CERT_TAG"
  mkdir -p "$CERT_DIR" && chmod 700 "$CERT_DIR"
  ln -sfn "$crt" "$CERT_FULL" && ln -sfn "$key" "$CERT_KEY" || { err "Не удалось сослаться на $crt"; return 1; }
  printf 'kind=external\nname=%s\nsource=%s\n' "$name" "$src" | write_file "$CERT_STATE" 600
  log_info "сертификат: готовый $src $name"
  ok "Сертификат $src на $name до $(date -d "@$exp" '+%d.%m.%Y'), продлевает $src"
}

acme() { "$ACME_DIR/acme.sh" --home "$ACME_HOME" --config-home "$ACME_HOME" "$@"; }

# acme.sh — последний тег с GitHub (или зеркал), без установки в систему:
# скрипт запускается из своего каталога, всё состояние — в $ACME_HOME.
acme_install() {
  [[ -x "$ACME_DIR/acme.sh" ]] && return 0
  local tag ref tmp
  mktmp tmp -d || return 1
  tag=$(gh_latest_tag acmesh-official/acme.sh || true)
  ref=${tag:+tags/$tag}
  gh_fetch "https://github.com/acmesh-official/acme.sh/archive/refs/${ref:-heads/master}.tar.gz" "$tmp/a.tgz" 100000 any \
    || { err "acme.sh не скачался ни напрямую, ни через зеркала"; return 1; }
  [[ "$(head -c2 "$tmp/a.tgz" | od -An -tx1 | tr -d ' \n')" == 1f8b ]] \
    || { err "Вместо архива acme.sh пришло что-то другое"; return 1; }
  mkdir -p "$ACME_DIR" "$ACME_HOME" && chmod 700 "$ACME_HOME"
  tar -xzf "$tmp/a.tgz" -C "$ACME_DIR" --strip-components=1 || { err "Архив acme.sh не распаковался"; return 1; }
  chmod 755 "$ACME_DIR/acme.sh"
  # standalone-режиму нужен socat или python3; socat надёжнее
  command -v socat &>/dev/null || apt_install socat || true
  ok "acme.sh ${tag:-master}"
}

cert_timer_install() {
  write_unit "$CERT_SERVICE" <<UNIT
[Unit]
Description=AWG Toolza — продление HTTPS-сертификата (acme.sh)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=$ACME_DIR/acme.sh --cron --home $ACME_HOME --config-home $ACME_HOME
UNIT
  write_unit "$CERT_TIMER" <<'UNIT'
[Unit]
Description=AWG Toolza — таймер продления HTTPS-сертификата

[Timer]
OnCalendar=*-*-* 04,16:20:00
RandomizedDelaySec=45min
Persistent=true

[Install]
WantedBy=timers.target
UNIT
  systemctl enable --now "$CERT_TIMER" &>/dev/null || warn "Таймер продления не запустился: systemctl status $CERT_TIMER"
}

# cert_issue ip [pause] | domain ИМЯ [pause] — pause: если порт 80 занят
# службой, она останавливается на время выпуска и каждого продления.
cert_issue() {
  local kind="${1:-}" name="${2:-}" args=() ip pub holder unit pause="" rc=0 old out n
  [[ "${*: -1}" == pause ]] && pause=1
  [[ "$kind" == ip ]] && name=""
  case "$kind" in
    ip)
      name=$(public_ip)
      valid_ip "$name" && ! ip_is_private "$name" || { err "У сервера нет публичного IPv4 — сертификат на IP не выпустить"; return 1; }
      # Сертификаты на IP Let's Encrypt выдаёт только с профилем shortlived
      args=(--cert-profile shortlived --days 3) ;;
    domain)
      name="${name,,}"
      valid_domain "$name" || { err "Нужен домен вида panel.example.com"; return 1; }
      ip=$(getent ahostsv4 "$name" 2>/dev/null | awk 'NR == 1 {print $1}')
      pub=$(public_ip)
      [[ -n "$ip" ]] || { err "Домен $name не резолвится — проверь A-запись"; return 1; }
      [[ "$ip" == "$pub" ]] || { err "A-запись $name ведёт на $ip, а IP сервера — $pub: Let's Encrypt не проверит владение"; return 1; } ;;
    *) err "Сертификат: ip | domain ИМЯ"; return 1 ;;
  esac
  holder=$(cert_port80_holder)
  if [[ -n "$holder" ]]; then
    unit=$(cert_port80_unit)
    if [[ -n "$pause" && -n "$unit" ]]; then
      args+=(--pre-hook "systemctl stop $unit" --post-hook "systemctl start $unit")
      warn "Порт 80 занят $unit — остановлю его на время выпуска (несколько секунд) и так же при каждом продлении"
    else
      err "Порт 80 занят ($holder): acme.sh слушает его сам на время выпуска и продления"
      n=$(cert_find | grep -c . || true)
      (( n > 0 )) && info "На сервере есть готовые сертификаты ($n) — их можно взять без порта 80"
      [[ -n "$unit" ]] && info "Или выпуск с паузой $unit: служба останавливается на секунды выпуска и продления"
      return 1
    fi
  fi
  acme_install || return 1
  ufw_allow 80/tcp "$CERT_TAG"
  info "Let's Encrypt: сертификат на $name…"
  mkdir -p "$ACME_HOME"
  out=$(acme --issue --server letsencrypt -d "$name" --standalone --httpport 80 --keylength ec-256 "${args[@]}" 2>&1) || rc=$?
  # Без самого сертификата и путей к файлам acme.sh — только ход выпуска
  printf '%s\n' "$out" | sed -e 's/^\[[^]]*\] //' -e '/-----BEGIN/,/-----END/d' \
    | grep -vE '^$|^(Your cert|The intermediate|And the full-chain|ARI suggestedWindow|It is later than|[0-9]{4}-[0-9]{2}-[0-9]{2}T)' \
    | tail -n 8
  # 2 — сертификат уже выпущен и продлевать его рано
  if (( rc != 0 && rc != 2 )); then
    err "Let's Encrypt не выдал сертификат — проверь, что порт 80 открыт снаружи (и в файрволе хостера)"
    return 1
  fi
  mkdir -p "$CERT_DIR" && chmod 700 "$CERT_DIR"
  # Был готовый сертификат — здесь ссылки на чужие файлы: acme.sh записал бы
  # прямо в них и затёр сертификат той программы
  rm -f "$CERT_FULL" "$CERT_KEY"
  acme --install-cert -d "$name" --ecc --key-file "$CERT_KEY" --fullchain-file "$CERT_FULL" &>/dev/null
  cert_installed || { err "Сертификат выпущен, но не скопирован в $CERT_DIR"; return 1; }
  chmod 600 "$CERT_KEY"
  # Прежний адрес больше не продлеваем — иначе таймер дёргал бы 80-й порт зря
  old=$(cert_get name)
  [[ "$(cert_get kind)" != external && -n "$old" && "$old" != "$name" ]] && acme --remove -d "$old" --ecc &>/dev/null
  printf 'kind=%s\nname=%s\n' "$kind" "$name" | write_file "$CERT_STATE" 600
  cert_timer_install
  log_info "сертификат: $kind $name"
  ok "Сертификат на $name до $(date -d "@$(cert_expires)" '+%d.%m.%Y %H:%M'), продлевается сам"
}

cert_remove() {
  local name
  name=$(cert_get name)
  # Готовый сертификат чужой — убираем только свои ссылки на него
  [[ "$(cert_get kind)" != external && -n "$name" && -x "$ACME_DIR/acme.sh" ]] && acme --remove -d "$name" --ecc &>/dev/null
  remove_unit "$CERT_TIMER" "$CERT_SERVICE"
  rm -rf "$CERT_DIR" "$CERT_STATE"
  ufw_delete_matching "$CERT_TAG"
  log_info "сертификат удалён"
  ok "Сертификат удалён"
}

cert_state_line() {
  local exp k
  cert_installed || { echo -e "${D}нет${N}"; return; }
  exp=$(cert_expires)
  case "$(cert_get kind)" in
    ip) k=IP ;; external) k="готовый, $(cert_get source)" ;; *) k=домен ;;
  esac
  echo -e "${W}$(cert_get name)${N} ${D}($k, до $(date -d "@${exp:-0}" '+%d.%m %H:%M'))${N}"
}
