"""net.py — сетевой слой бота: прокси и запасные адреса Telegram API.

Зачем это нужно. DNS отдаёт для api.telegram.org ровно один A-адрес. Если
именно он у провайдера заблокирован (обычная картина на серверах в РФ),
переключаться не на что: ни aiohttp, ни aiogram не могут выбрать другой
адрес, потому что другого им никто не назвал. Бот молча не отвечает.

Два независимых средства:

* прокси (BOT_PROXY) — самое надёжное, работает при любой блокировке, а не
  только при блокировке по IP. Требует, чтобы прокси где-то был поднят.
  Кроме http/socks понимает iface://<dev> — выход через туннель сервера
  (warp0, awg-exit-*, tun0...): сокеты бота привязываются к интерфейсу;
* запасные адреса — работают без настройки: резолвер подмешивает к ответу
  DNS известные адреса Telegram, а aiohttp сам выбирает отвечающий
  (happy eyeballs гоняет их наперегонки с задержкой в четверть секунды).

Список адресов, как и любой захардкоженный список, устаревает. Но ломается
он не весь разом: ответ DNS всегда идёт первым, а запасные — только
дополнение к нему.
"""

from __future__ import annotations

import inspect
import logging
import os
import re
import socket
from typing import Any
from urllib.parse import urlsplit

log = logging.getLogger("awgbot.net")

# Каким путём бот на самом деле ходит в Telegram — для сообщения после рестарта.
route_note = "напрямую"

TELEGRAM_API_HOST = "api.telegram.org"

# Адреса api.telegram.org, встречающиеся на практике. Порядок не важен:
# aiohttp пробует их параллельно и берёт тот, что ответил первым.
TELEGRAM_FALLBACK_IPS = (
    "149.154.167.220",
    "149.154.167.99",
    "149.154.166.110",
    "149.154.167.91",
    "149.154.166.120",
)

# Схемы, которые понимает aiogram/aiohttp. socks* требуют aiohttp_socks.
# iface:// — наша: не прокси, а привязка сокетов к интерфейсу туннеля.
IFACE_SCHEME = "iface://"
PROXY_SCHEMES = ("http://", "https://", "socks4://", "socks5://", "socks5h://",
                 IFACE_SCHEME)

# Имя сетевого интерфейса Linux: до 15 символов, без / и пробелов.
_IFACE_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,15}$")


def iface_of(url: str) -> str:
    """Имя интерфейса из iface://<dev>, иначе пусто."""
    return url[len(IFACE_SCHEME):].strip() if url.startswith(IFACE_SCHEME) else ""


def valid_proxy(url: str) -> bool:
    """Похоже ли значение на адрес прокси. Пустая строка — не ошибка."""
    if not url.startswith(PROXY_SCHEMES):
        return False
    if url.startswith(IFACE_SCHEME):
        return bool(_IFACE_RE.match(iface_of(url)))
    # Схема без хоста ("socks5://") — мусор, но одной проверки схемы ей мало:
    # такой конфиг принимался на старте, а падал позже и невнятно, уже при
    # попытке соединиться. awg2 (bot_proxy_valid) отвергает его сразу,
    # держим оба конца одинаковыми.
    return bool(url.split("://", 1)[1].strip())


class TelegramFallbackResolver:
    """
    Резолвер aiohttp: ответ системного DNS плюс запасные адреса Telegram.

    Реализует интерфейс aiohttp.abc.AbstractResolver, но НЕ наследуется от
    него — иначе модуль нельзя было бы импортировать там, где aiohttp не
    установлен (тесты, проверка конфига). Утиной типизации aiohttp хватает.
    """

    def __init__(self, base_factory: Any = None) -> None:
        # Фабрика, а не готовый резолвер: aiohttp.DefaultResolver в
        # конструкторе берёт текущий цикл событий (asyncio.get_running_loop),
        # а сессия строится ДО запуска цикла — на старте это падало с
        # "no running event loop", и запасные адреса не подключались.
        # Создаём при первом resolve(), он уже вызывается внутри цикла.
        self._base_factory = base_factory
        self._base: Any = None

    def _base_resolver(self) -> Any:
        if self._base is None and self._base_factory is not None:
            self._base = self._base_factory()
        return self._base

    async def resolve(self, host: str, port: int = 0,
                      family: int = socket.AF_INET) -> list[dict[str, Any]]:
        hosts: list[dict[str, Any]] = []
        base = self._base_resolver()
        try:
            if base is not None:
                hosts = list(await base.resolve(host, port, family))
        except Exception as e:                       # noqa: BLE001
            # DNS не ответил. Для Telegram это не приговор: ниже подмешаем
            # запасные адреса и попробуем их. Для любого другого хоста —
            # ошибка настоящая, отдаём её вызывающему.
            if host != TELEGRAM_API_HOST or family not in (socket.AF_INET, 0):
                raise
            log.warning("DNS не ответил на %s (%s) — беру запасные адреса", host, e)

        if host != TELEGRAM_API_HOST or family not in (socket.AF_INET, 0):
            return hosts

        known = {h.get("host") for h in hosts}
        for ip in TELEGRAM_FALLBACK_IPS:
            if ip in known:
                continue
            hosts.append({
                "hostname": host,
                "host": ip,
                "port": port,
                "family": socket.AF_INET,
                "proto": 0,
                "flags": 0,
            })
        return hosts

    async def close(self) -> None:
        if self._base is not None:
            await self._base.close()


def mask_proxy(url: str) -> str:
    """Адрес прокси без логина и пароля — для логов."""
    if "@" in url and "://" in url:
        return "%s://***@%s" % (url.split("://", 1)[0], url.rsplit("@", 1)[1])
    return url


def _proxy_hostport(url: str) -> tuple[str, int]:
    """Хост и порт прокси. Порт по умолчанию — по схеме."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    port = parts.port
    if not port:
        port = 80 if parts.scheme in ("http",) else 443 if parts.scheme == "https" else 1080
    return host, port


def proxy_alive(url: str, timeout: float = 4.0) -> bool:
    """
    Открыт ли порт прокси. Именно TCP-коннект, а не проверка прокси-протокола:
    задача — отличить «прокси поднят» от «прокси нет вовсе», и для второго
    случая хватает отказа в соединении.

    Нужно вот зачем. Самый удобный прокси на нашем сервере — SOCKS-вход Xray
    или туннель awg2, а туннель может быть выключен (аварийный сброс, ошибка
    после перезагрузки). Без этой проверки бот уходил бы в бесконечные
    попытки достучаться через мёртвый порт — то есть молчал бы, хотя напрямую
    (с запасными адресами) вполне мог работать.
    """
    dev = iface_of(url)
    if dev:
        # Туннель поднят — интерфейс есть в /sys/class/net.
        return os.path.isdir(f"/sys/class/net/{dev}")
    host, port = _proxy_hostport(url)
    if not host:
        return False
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError as e:
        log.debug("прокси %s:%s не отвечает: %s", host, port, e)
        return False


def _iface_socket_factory(dev: str) -> Any:
    """Фабрика сокетов для aiohttp: каждый сокет привязан к интерфейсу dev.
    Маршрут по умолчанию в туннель не нужен — ядро шлёт в dev напрямую
    (как curl --interface)."""
    def factory(addr_info: Any) -> socket.socket:
        family, type_, proto = addr_info[0], addr_info[1], addr_info[2]
        sock = socket.socket(family=family, type=type_, proto=proto)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE,
                            dev.encode() + b"\0")
        except OSError:
            sock.close()
            raise
        return sock
    return factory


def _bind_iface(session: Any, dev: str) -> bool:
    """Подключить привязку к интерфейсу в коннектор aiogram-сессии.
    socket_factory у TCPConnector — с aiohttp 3.12."""
    try:
        from aiohttp import TCPConnector
        init = getattr(session, "_connector_init", None)
        if not isinstance(init, dict):
            return False
        if "socket_factory" not in inspect.signature(TCPConnector).parameters:
            log.warning("aiohttp %s без socket_factory — iface:// не работает, "
                        "обновите бота", getattr(__import__("aiohttp"), "__version__", "?"))
            return False
        init["socket_factory"] = _iface_socket_factory(dev)
        log.info("Telegram API через интерфейс %s", dev)
        return True
    except Exception as e:                           # noqa: BLE001
        log.warning("Не удалось привязаться к %s: %s", dev, e)
        return False


def build_session(proxy: str = "") -> Any:
    """
    Сессия aiogram с прокси и запасными адресами. Возвращает None, если
    ничего настраивать не требуется — тогда вызывающий создаёт Bot как раньше.
    """
    from aiogram.client.session.aiohttp import AiohttpSession

    global route_note
    route_note = "напрямую"
    if proxy and not proxy_alive(proxy):
        # Молчать нельзя: бот будет работать, но не так, как настроено, и
        # если блокировка именно та, ради которой прокси заводили, помощи
        # от запасных адресов не будет. Пусть в логе стоит причина.
        log.warning("Прокси %s не отвечает — иду напрямую. Если он поднимается "
                    "туннелем awg2 — включи туннель (Туннели и DNS), затем: "
                    "systemctl restart awg-bot",
                    mask_proxy(proxy))
        route_note = f"напрямую — прокси {mask_proxy(proxy)} не отвечает"
        proxy = ""

    dev = iface_of(proxy)
    if dev:
        session = AiohttpSession()
        if _bind_iface(session, dev):
            route_note = f"через интерфейс {dev}"
        else:
            log.warning("Привязка к %s недоступна — иду напрямую", dev)
            route_note = f"напрямую — привязка к {dev} недоступна (обнови бота)"
    elif proxy:
        try:
            session = AiohttpSession(proxy=proxy)
        except ImportError as e:
            # socks-схемы aiogram обслуживает через aiohttp_socks. Без него
            # трейс на пол-экрана не объясняет, что доставить.
            raise SystemExit(
                f"BOT_PROXY={proxy} требует пакет aiohttp_socks, а его нет ({e}).\n"
                "Поставьте его в venv бота:\n"
                "  /opt/awg-bot/venv/bin/pip install aiohttp-socks\n"
                "или переустановите бота: sudo awg2 → Telegram-бот → Обновить."
            ) from e
        # В логе только адрес: у прокси с авторизацией до @ стоят логин и пароль.
        log.info("Telegram API через прокси %s", mask_proxy(proxy))
        route_note = f"через прокси {mask_proxy(proxy)}"
    else:
        session = AiohttpSession()

    # Резолвер кладём в параметры коннектора, который aiogram создаёт сам.
    # Это внутренняя деталь aiogram, поэтому под проверкой: сменится —
    # останемся без запасных адресов, но бот продолжит работать.
    try:
        from aiohttp.resolver import DefaultResolver

        init = getattr(session, "_connector_init", None)
        if isinstance(init, dict):
            init["resolver"] = TelegramFallbackResolver(DefaultResolver)
            log.info("Запасные адреса Telegram подключены (%d шт.)",
                     len(TELEGRAM_FALLBACK_IPS))
        else:
            log.warning("aiogram изменил устройство сессии — запасные адреса "
                        "Telegram недоступны, работаем только через DNS")
    except Exception as e:                           # noqa: BLE001
        log.warning("Не удалось подключить запасные адреса Telegram: %s", e)

    return session
