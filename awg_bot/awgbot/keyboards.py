"""keyboards.py — все инлайн-клавиатуры. Управление только кнопками."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from . import core


# Профили CPS-мимикрии: (ключ, подпись кнопки, короткое имя для текста).
# Набор обязан совпадать с генератором awg2 (cps.PROFILES); один список на
# все клавиатуры и подписи, чтобы новый профиль добавлялся в одном месте.
MIMICRY_PROFILES: tuple[tuple[str, str, str], ...] = (
    ("quic",      "⚡ QUIC Initial (рекомендуется)", "QUIC"),
    ("curl_quic", "🔒 cURL QUIC + ECH",              "cURL QUIC + ECH"),
    ("dns",       "🌐 DNS Query",                    "DNS"),
    ("stun",      "📡 STUN / TURN",                  "STUN/TURN"),
    ("webrtc",    "🎥 WebRTC",                       "WebRTC"),
    ("sip",       "📞 SIP (VoIP)",                   "SIP"),
    ("ntp",       "🕐 NTP",                          "NTP"),
    ("rtp",       "🎵 RTP",                          "RTP"),
    ("ssdp",      "🔎 SSDP",                         "SSDP"),
    ("basic",     "🔇 Базовый (без I1-I5)",          "базовый"),
)


def mimicry_label(profile: str) -> str:
    """Человекочитаемое имя профиля для текста сообщений."""
    for key, _btn, short in MIMICRY_PROFILES:
        if key == profile:
            return short
    if profile == "tls":
        # Конфиги, созданные до перехода на payloadGen: генератор сводит tls
        # к quic, поэтому показываем это явно, а не сырым ключом.
        return "QUIC (бывший TLS)"
    if profile in ("", "none"):
        return "нет"
    return profile


def profile_choices() -> InlineKeyboardMarkup:
    """Выбор профиля мимикрии при создании клиента (как в awg2 Pro)."""
    b = InlineKeyboardBuilder()
    for key, label, _short in MIMICRY_PROFILES:
        b.button(text=label, callback_data=f"prof:{key}")
    b.button(text="‹ Отмена", callback_data="clients")
    b.adjust(*([1] * (len(MIMICRY_PROFILES) + 1)))
    return b.as_markup()


def mimicry_choices(idx: int) -> InlineKeyboardMarkup:
    """Смена мимикрии у выданного клиента (п.10 меню клиентов в awg2)."""
    b = InlineKeyboardBuilder()
    for key, label, _short in MIMICRY_PROFILES:
        b.button(text=label, callback_data=f"cl_mim_set:{idx}:{key}")
    b.button(text="‹ Отмена", callback_data=f"client:{idx}")
    b.adjust(*([1] * (len(MIMICRY_PROFILES) + 1)))
    return b.as_markup()


def main_menu(installed: bool, wgobf: bool = False) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if installed:
        b.button(text="👥 Клиенты", callback_data="clients")
        b.button(text="📊 Статус сервера", callback_data="status")
        b.button(text="⏳ Сроки действия", callback_data="expire")
        b.button(text="🛡 Туннели", callback_data="tunnels")
        b.button(text="💾 Бэкап / Рестор", callback_data="backup")
        b.button(text="↻ Перезапуск awg0", callback_data="restart_confirm")
        b.button(text="🔧 Обслуживание", callback_data="maint")
        b.button(text="❤️ Поддержать", url="https://t.me/awgToolza/156/157")
        if wgobf:
            b.button(text="🧅 WG + обфускатор", callback_data="wgobf")
            b.adjust(2, 2, 2, 2, 1)
        else:
            b.adjust(2, 2, 2, 2)
    else:
        b.button(text="⚙️ Сервер не установлен — открыть консоль awg2",
                 callback_data="not_installed")
        # WG + обфускатор живёт и без AWG — не прячем его
        if wgobf:
            b.button(text="🧅 WG + обфускатор", callback_data="wgobf")
        b.adjust(1)
    return b.as_markup()


# ── WG + обфускатор (awg2, пункт 9) ──
# В callback — имя клиента, а не индекс: список меняется при добавлении и
# удалении, а имя (≤32 символа, [A-Za-z0-9_-]) влезает в лимит 64 байта.
def wgobf_menu() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="👥 Клиенты", callback_data="wgo_list")
    b.button(text="➕ Добавить", callback_data="wgo_add")
    b.button(text="🔑 Сменить ключ", callback_data="wgo_key")
    b.button(text="↻ Перезапуск", callback_data="wgo_restart")
    b.button(text="🔄 Обновить", callback_data="wgobf")
    b.button(text="‹ В меню", callback_data="menu")
    b.adjust(2, 2, 2)
    return b.as_markup()


def wgobf_clients_menu(names: list[str]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for n in names:
        b.button(text=f"🧅 {n}", callback_data=f"wgo_c:{n}")
    b.button(text="➕ Добавить", callback_data="wgo_add")
    b.button(text="‹ Назад", callback_data="wgobf")
    # клиенты по 2 в ряд (нечётный — один в последнем ряду), затем 2 кнопки
    b.adjust(*([2] * (len(names) // 2)), *([1] if len(names) % 2 else []), 2)
    return b.as_markup()


def wgobf_client_card(name: str, direct: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🔗 Ссылка phobos://", callback_data=f"wgo_link:{name}")
    b.button(text="📦 Файлы комплекта", callback_data=f"wgo_files:{name}")
    if direct:
        b.button(text="📱 QR без обфускатора", callback_data=f"wgo_qr:{name}")
    b.button(text="🗑 Удалить", callback_data=f"wgo_del:{name}")
    b.button(text="‹ К списку", callback_data="wgo_list")
    b.adjust(2, *([1] if direct else []), 2)
    return b.as_markup()


def back_button(to: str = "menu") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="‹ Назад", callback_data=to)]
    ])


CLIENTS_PER_PAGE = 12  # по 6 строк в 2 столбца


def clients_menu(peers: list[core.Peer], page: int = 0,
                 sort_active: bool = False) -> InlineKeyboardMarkup:
    """
    Список клиентов в 2 столбца с пагинацией.
    Индекс в callback ссылается на позицию в ИСХОДНОМ списке core.list_peers(),
    чтобы открывался правильный клиент независимо от сортировки/страницы.
    """
    b = InlineKeyboardBuilder()
    b.button(text="➕ Добавить", callback_data="client_add")
    b.button(text="🔄 Обновить", callback_data=f"clpage:{page}:{int(sort_active)}")

    # порядок отображения: с сохранением реального индекса
    indexed = list(enumerate(peers))  # (real_idx, peer)
    if sort_active:
        # сначала онлайн, потом офлайн, потом заблокированные
        def rank(ip):
            p = ip[1]
            return (0 if p.online else (2 if p.blocked else 1), p.name.lower())
        indexed = sorted(indexed, key=rank)

    total = len(indexed)
    pages = max(1, (total + CLIENTS_PER_PAGE - 1) // CLIENTS_PER_PAGE)
    page = max(0, min(page, pages - 1))
    chunk = indexed[page * CLIENTS_PER_PAGE:(page + 1) * CLIENTS_PER_PAGE]

    # кнопка переключения сортировки
    sort_label = "✓ Активные сверху" if sort_active else "↕️ Сорт. по активным"
    b.button(text=sort_label, callback_data=f"clpage:{page}:{0 if sort_active else 1}")

    for real_idx, p in chunk:
        dot = "🟢" if p.online else ("🚫" if p.blocked else "⚪️")
        b.button(text=f"{dot} {p.name}", callback_data=f"client:{real_idx}")

    # навигация по страницам (если больше одной)
    nav = []
    if pages > 1:
        if page > 0:
            b.button(text="‹ Назад", callback_data=f"clpage:{page-1}:{int(sort_active)}")
            nav.append(1)
        b.button(text=f"{page+1}/{pages}", callback_data="noop")
        nav.append(1)
        if page < pages - 1:
            b.button(text="Вперёд ›", callback_data=f"clpage:{page+1}:{int(sort_active)}")
            nav.append(1)

    b.button(text="‹ В меню", callback_data="menu")

    # раскладка: [Добавить|Обновить], [сортировка], клиенты по 2,
    # затем навигация в ряд, затем В меню
    n_clients = len(chunk)
    rows = [2, 1]
    rows += [2] * (n_clients // 2)
    if n_clients % 2:
        rows += [1]
    if nav:
        rows += [len(nav)]
    rows += [1]
    b.adjust(*rows)
    return b.as_markup()


def client_card(idx: int, monitored: bool = False, warp_state=None) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="📥 Скачать .conf", callback_data=f"cl_conf:{idx}")
    b.button(text="📱 QR-код", callback_data=f"cl_qr:{idx}")
    b.button(text="⏳ Срок", callback_data=f"cl_exp:{idx}")
    # WARP-кнопка: текст зависит от состояния (None = WARP не установлен)
    if warp_state is True:
        b.button(text="☁ WARP: выкл", callback_data=f"cl_warp_off:{idx}")
    elif warp_state is False:
        b.button(text="☁ WARP: вкл", callback_data=f"cl_warp_on:{idx}")
    else:
        b.button(text="☁ WARP (не установлен)", callback_data="warp_not_installed")
    b.button(text="📝 Заметка", callback_data=f"cl_note:{idx}")
    # Мониторинг активности (офлайн/онлайн-алерты). Кнопка называет действие,
    # как у WARP выше: включено — предлагаем выключить.
    if monitored:
        b.button(text="🔕 Активность: выкл", callback_data=f"cl_mon:{idx}:0")
    else:
        b.button(text="🔔 Активность: вкл", callback_data=f"cl_mon:{idx}:1")
    b.button(text="🎭 Мимикрия", callback_data=f"cl_mim:{idx}")
    b.button(text="✏️ Переименовать", callback_data=f"cl_ren:{idx}")
    b.button(text="🗑 Удалить", callback_data=f"cl_del:{idx}")
    b.button(text="‹ К списку", callback_data="clients")
    b.adjust(2, 2, 2, 2, 1, 1)
    return b.as_markup()


def dns_upstream_choices() -> InlineKeyboardMarkup:
    """Выбор upstream-резолверов DNSCrypt (серверный шифрованный DNS)."""
    from . import core
    b = InlineKeyboardBuilder()
    for key, (label, _servers, _nf) in core.DNS_UPSTREAMS.items():
        b.button(text=label, callback_data=f"dns_up:{key}")
    b.button(text="‹ Назад", callback_data="tun:dns")
    b.adjust(1, 1, 1, 1, 1, 1)
    return b.as_markup()


def confirm(yes_cb: str, no_cb: str = "menu", danger: bool = True) -> InlineKeyboardMarkup:
    yes = "❌ Да, удалить" if danger else "✓ Да"
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=yes, callback_data=yes_cb),
        InlineKeyboardButton(text="‹ Отмена", callback_data=no_cb),
    ]])


def expire_choices(idx: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for label, spec in [("1 час", "1h"), ("1 день", "1d"),
                        ("7 дней", "7d"), ("30 дней", "30d")]:
        b.button(text=label, callback_data=f"exp_set:{idx}:{spec}")
    b.button(text="♾ Бессрочно (снять срок)", callback_data=f"exp_clear:{idx}")
    b.button(text="📅 Своя дата", callback_data=f"exp_custom:{idx}")
    b.button(text="‹ Назад", callback_data=f"client:{idx}")
    b.adjust(2, 2, 1, 1, 1)
    return b.as_markup()


def expire_menu() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="📋 Список со сроками", callback_data="exp_list")
    b.button(text="🧹 Удалить просроченные", callback_data="exp_purge_confirm")
    b.button(text="‹ Назад", callback_data="menu")
    b.adjust(1, 1, 1)
    return b.as_markup()


TUNNEL_TITLES = {
    "warp": "☁ WARP", "xray": "⚡ Xray", "exits": "🔗 AWG Exit-ноды",
    "tun2socks": "🧦 tun2socks", "dns": "🌐 DNS",
}


def tunnels_menu() -> InlineKeyboardMarkup:
    """Сводка туннелей: по кнопке на каждый + обновить."""
    b = InlineKeyboardBuilder()
    for name, title in TUNNEL_TITLES.items():
        b.button(text=title, callback_data=f"tun:{name}")
    b.button(text="🔄 Обновить", callback_data="tunnels")
    b.button(text="‹ Назад", callback_data="menu")
    b.adjust(2, 2, 1, 1, 1)
    return b.as_markup()


def tunnel_card(name: str) -> InlineKeyboardMarkup:
    """Действия с одним туннелем."""
    b = InlineKeyboardBuilder()
    if name == "dns":
        b.button(text="📋 Статус", callback_data="t_dns_status")
        b.button(text="🔄 Перезапуск", callback_data="tun_do:dns:restart")
        b.button(text="🔀 Сменить резолверы", callback_data="dns_upstream")
        b.button(text="📥 Установить", callback_data="t_dns_install")
        b.button(text="🗑 Удалить", callback_data="t_dns_remove")
        b.button(text="‹ Туннели", callback_data="tunnels")
        b.adjust(2, 1, 2, 1)
        return b.as_markup()
    b.button(text="▶ Включить", callback_data=f"tun_do:{name}:up")
    b.button(text="⏹ Выключить", callback_data=f"tun_ask:{name}:down")
    b.button(text="🔄 Перезапуск", callback_data=f"tun_do:{name}:restart")
    rows = [3]
    if name == "warp":
        b.button(text="📋 Статус", callback_data="t_warp_status")
        b.button(text="💥 Hard Restart", callback_data="t_warp_restart")
        b.button(text="📥 Установить", callback_data="t_warp_install")
        b.button(text="🗑 Удалить", callback_data="t_warp_remove")
        rows += [2, 2]
    elif name == "xray":
        b.button(text="⚖ Балансировщик", callback_data="xbal")
        rows += [1]
    b.button(text="‹ Туннели", callback_data="tunnels")
    b.adjust(*rows, 1)
    return b.as_markup()


def xray_balancer_choices(current: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    labels = {"random": "🎲 random", "roundRobin": "🔁 roundRobin",
              "leastPing": "📶 leastPing", "leastLoad": "📉 leastLoad",
              "off": "⛔ выключить"}
    for key, label in labels.items():
        mark = " ✓" if key == (current or "off") else ""
        b.button(text=label + mark, callback_data=f"xbal_set:{key}")
    b.button(text="‹ Xray", callback_data="tun:xray")
    b.adjust(2, 2, 1, 1)
    return b.as_markup()


def backup_menu() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="📥 Создать бэкап", callback_data="backup_create")
    b.button(text="📤 Восстановить из файла", callback_data="backup_restore")
    b.button(text="‹ Назад", callback_data="menu")
    b.adjust(1, 1, 1)
    return b.as_markup()


def maint_menu() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="📄 Конфиг сервера (скачать)", callback_data="show_server_conf")
    b.button(text="📜 Логи awg2", callback_data="show_logs")
    b.button(text="🤖 Управление ботом", callback_data="botctl")
    b.button(text="‹ Назад", callback_data="menu")
    b.adjust(1, 1, 1, 1)
    return b.as_markup()


def botctl_menu(is_owner: bool = False) -> InlineKeyboardMarkup:
    """
    Меню управления самим ботом (аналог консольного awg-bot).
    Пункт «Админы» видит только владелец — приглашённый админ список не правит.
    """
    b = InlineKeyboardBuilder()
    rows = 6
    b.button(text="⬆️ Обновить бота (сохранив токен)", callback_data="bot_update")
    b.button(text="📊 Статус бота", callback_data="bot_status")
    b.button(text="📜 Логи бота (50 строк)", callback_data="bot_logs")
    if is_owner:
        b.button(text="👮 Админы бота", callback_data="admins")
        rows += 1
    b.button(text="↻ Перезапустить бота", callback_data="bot_restart_confirm")
    b.button(text="🗑 Удалить бота (токен оставить)",
             callback_data="bot_uninstall_confirm")
    b.button(text="💀 Удалить полностью (с токеном)",
             callback_data="bot_purge_confirm")
    b.button(text="‹ Назад", callback_data="maint")
    b.adjust(*([1] * (rows + 1)))
    return b.as_markup()


def update_menu(has_update: bool, channel: str) -> InlineKeyboardMarkup:
    """Экран обновления: сама кнопка обновления + переключение канала."""
    b = InlineKeyboardBuilder()
    b.button(text="✓ Обновить бота" if has_update else "↻ Переустановить текущую версию",
             callback_data="bot_update_ok")
    b.button(text=("🛡 Вернуться на стабильный канал" if channel == "beta"
                   else "🧪 Перейти на бета-канал"),
             callback_data="bot_channel")
    b.button(text="‹ Назад", callback_data="botctl")
    b.adjust(1, 1, 1)
    return b.as_markup()


def admins_menu(invited, pending: int) -> InlineKeyboardMarkup:
    """Список приглашённых админов: кнопка на каждого — отзыв доступа."""
    b = InlineKeyboardBuilder()
    for a in invited:
        who = f"@{a.username}" if a.username else str(a.uid)
        b.button(text=f"🚫 Отозвать · {who}", callback_data=f"adm_del:{a.uid}")
    b.button(text="➕ Добавить админа", callback_data="adm_add")
    if pending:
        b.button(text=f"🔗 Отозвать приглашения ({pending})",
                 callback_data="adm_revoke")
    b.button(text="‹ Назад", callback_data="botctl")
    b.adjust(*([1] * (len(invited) + 2 + (1 if pending else 0))))
    return b.as_markup()


def admin_add_menu() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🔗 Ссылка-приглашение (одноразовая)", callback_data="adm_invite")
    b.button(text="🆔 По Telegram ID", callback_data="adm_by_id")
    b.button(text="‹ Назад", callback_data="admins")
    b.adjust(1, 1, 1)
    return b.as_markup()
