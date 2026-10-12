"""Веб-панель (awg-web): адрес, логин, служба, новый пароль — из бота,
когда адрес забыт или панель надо поставить без терминала.

Раздел только для владельцев: адрес с секретным путём и пароль — ключи от
сервера. Пароль на сервере хранится только хешем: прежний показать нельзя,
можно выдать новый. Его бот показывает один раз — «✅ Сохранил» правит это же
сообщение, и пароль из чата пропадает.

Доступ к панели: для всех, только с указанных адресов (и через свой VPN) или
только через VPN. Бот работает всегда — отсюда и возвращают «для всех», если
адрес дома сменился.
"""

from __future__ import annotations

import re

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from .. import api, ask, ui
from ..ui import esc

router = Router()
act = ui.Actions(router, "web", owner="Веб-панель настраивает только владелец")
TIMEOUT = 180                       # установка: код уже стоит вместе с ботом, ждём старт службы


@act()
async def show(cb: CallbackQuery, state: FSMContext, arg: str = "") -> None:
    await screen(cb)


def _access_label(d: dict) -> str:
    mode = d.get("access") or "all"
    if mode == "ip":
        return f"по адресам ({len(d.get('allow') or [])}) и через VPN"
    return "только через VPN" if mode == "vpn" else "для всех"


def _cert_line(d: dict) -> str:
    if d.get("cert"):
        return f"🔐 Сертификат: <code>{esc(d.get('cert_name') or '')}</code> · до {ui.fmt_time(d.get('cert_expires'))}"
    return "🔐 Сертификат самоподписанный — браузер предупредит. Настоящий: Telegram-бот → 📱 Mini App"


async def screen(target: ui.Target, note: str = "") -> None:
    r = await api.call("web", "status")
    if not r.ok or not isinstance(r.data, dict):
        await ui.render(target, ui.fail(r, "Веб-панель"), ui.kb(ui.back()))
        return
    d = r.data
    lines = ["<b>💻 Веб-панель</b>", "Все разделы Тулзы в браузере — вход по логину и паролю, без Telegram.", ""]
    if note:
        lines += [note, ""]
    if not d.get("installed"):
        lines += ["⚪️ Не установлена", "",
                  "<i>Логин — admin, пароль бот придумает сам и покажет один раз. Порт и секретный путь — "
                  "случайные.</i>"]
        await ui.render(target, "\n".join(lines), ui.kb(("📦 Установить", act.data("inst")), ui.back()))
        return
    url = d.get("url") or ""
    lines += [
        "🟢 Работает" if d.get("active") else "🔴 Остановлена",
        f"Адрес: <code>{esc(url)}</code>",
        f"Логин: <code>{esc(d.get('user') or '')}</code>",
        f"🛡 Доступ: {_access_label(d)}",
        _cert_line(d), "",
        "<i>Пароль на сервере хранится только хешем — прежний не показать, можно выдать новый. "
        "Новый адрес — другой секретный путь: старая ссылка перестанет открываться.</i>",
    ]
    buttons = [
        ("🔑 Новый пароль", act.data("pw")), ("🔀 Новый адрес", act.data("path")),
        ("🛡 Доступ", act.data("acc")), ("🔄 Перезапустить", act.data("restart")),
        ("⏹ Остановить", act.data("stop")) if d.get("active") else ("▶️ Запустить", act.data("start")),
        ("📜 Журнал входов", "diag:log:web|web"), ("🔐 Сертификат", "app"),
        ("🗑 Удалить", act.data("rm")), ui.back(),
    ]
    text = "\n".join(lines)
    if not (d.get("active") and url.startswith("https://")):
        await ui.render(target, text, ui.kb(*buttons))
        return
    try:
        await ui.render(target, text, ui.kb(ui.Row(("🌐 Открыть", url)), *buttons))
    except TelegramBadRequest:
        # Ссылку на голый IP Telegram может не принять — адрес и так виден текстом
        await ui.render(target, text, ui.kb(*buttons))


async def access_screen(target: ui.Target, note: str = "") -> None:
    r = await api.call("web", "status")
    if not r.ok or not isinstance(r.data, dict) or not r.data.get("installed"):
        await ui.render(target, ui.fail(r, "Веб-панель") if not r.ok else "Веб-панель не установлена",
                        ui.kb(ui.back(act.data())))
        return
    d = r.data
    mode, allow = d.get("access") or "all", d.get("allow") or []
    lines = ["<b>🛡 Доступ к веб-панели</b>", f"Сейчас: <b>{_access_label(d)}</b>", ""]
    if note:
        lines += [note, ""]
    if allow:
        lines.append("Адреса: " + ", ".join(f"<code>{esc(a)}</code>" for a in allow[:20])
                     + (f" и ещё {len(allow) - 20}" if len(allow) > 20 else ""))
    if d.get("vpn_url"):
        lines.append(f"Изнутри VPN: <code>{esc(d['vpn_url'])}</code>")
    lines += ["", "<i>«По адресам» — только с них и через свой VPN (AWG, WG + обфускатор): сменился адрес "
                  "дома — зайди через VPN. «Только через VPN» — снаружи порт закрыт для всех. Изнутри VPN "
                  "браузер предупредит о сертификате: он выписан на внешний адрес. Бот и SSH работают "
                  "всегда — вернуть «для всех» можно отсюда.</i>"]
    mark = {m: "✅ " if mode == m else "" for m in ("all", "ip", "vpn")}
    buttons: list = [(f"{mark['all']}🌍 Для всех", act.data("acc_all")),
                     (f"{mark['ip']}📍 По адресам", act.data("acc_ip"))]
    if allow and mode != "ip":
        buttons.append((f"📍 Прежние адреса ({len(allow)})", act.data("acc_old")))
    if d.get("vpn_nets"):
        buttons.append((f"{mark['vpn']}🔒 Только через VPN", act.data("acc_vpn")))
    await ui.render(target, "\n".join(lines), ui.kb(*buttons, ui.back(act.data())))


@act("acc")
async def _acc(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    await access_screen(cb)


async def _acc_set(target: ui.Target, mode: str, *allow: str) -> api.Result:
    r = await api.call("web", "access", mode, *allow, timeout=TIMEOUT)
    labels = {"all": "для всех", "ip": "по адресам и через VPN", "vpn": "только через VPN"}
    if r.ok:
        await access_screen(target, f"✅ Доступ: {labels[mode]}")
    return r


@act("acc_all")
async def _acc_all(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    r = await _acc_set(cb, "all")
    if not r.ok:
        await access_screen(cb, ui.fail(r, "Доступ"))


@act("acc_vpn")
async def _acc_vpn(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    await ui.confirm(cb, "<b>🔒 Только через VPN?</b>\n\nСнаружи порт панели закроется для всех — открывать её "
                         "придётся с подключённым VPN по адресу изнутри VPN. Бот и SSH продолжат работать.",
                     ("🔒 Закрыть снаружи", act.data("acc_vpnok")), act.data("acc"))


@act("acc_vpnok")
async def _acc_vpn_ok(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    r = await _acc_set(cb, "vpn")
    if not r.ok:
        await access_screen(cb, ui.fail(r, "Доступ"))


@act("acc_old")
async def _acc_old(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    r = await api.call("web", "status")
    allow = r.data.get("allow") if r.ok and isinstance(r.data, dict) else None
    if not allow:
        await access_screen(cb, ui.fail(r, "Доступ") if not r.ok else "Список адресов пуст")
        return
    r = await _acc_set(cb, "ip", *allow)
    if not r.ok:
        await access_screen(cb, ui.fail(r, "Доступ"))


@act("acc_ip")
async def _acc_ip(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    await ask.ask(cb, state, "web_allow", "Адреса и подсети, с которых открывать панель, — через запятую или "
                                          "пробел: <code>1.2.3.4, 5.6.7.0/24</code> (по умолчанию панель слушает только IPv4). Список "
                                          "заменит прежний; свой VPN пускается всегда.", act.data("acc"))


@ask.on("web_allow")
async def _acc_ip_answer(msg: Message, state: FSMContext, ctx: ask.Ctx) -> None:
    items = [a for a in re.split(r"[\s,;]+", ask.text_of(msg)) if a][:64]
    if not items:
        await ask.retry(msg, state, ctx, "Нужен хотя бы один адрес или подсеть")
        return
    r = await _acc_set(msg, "ip", *items)
    if not r.ok:
        await ask.retry(msg, state, ctx, r.message)


async def _access(target: ui.Target, r: api.Result, title: str) -> None:
    """Итог установки или нового пароля: пароль — один раз, «Сохранил» его стирает."""
    if not r.ok or not isinstance(r.data, dict):
        await ui.render(target, ui.fail(r, title), ui.kb(ui.back(act.data())))
        return
    d = r.data
    lines = [f"✅ <b>{esc(title)}</b>", "", f"Адрес: <code>{esc(d.get('url') or '')}</code>",
             f"Логин: <code>{esc(d.get('user') or '')}</code>"]
    if d.get("password"):
        lines += [f"Пароль: <tg-spoiler><code>{esc(d['password'])}</code></tg-spoiler>", "",
                  "<i>Сохрани пароль в менеджер паролей: больше его не покажу. «✅ Сохранил» уберёт его из "
                  "этого сообщения. Если пересылал или копировал куда-то ещё — удали и там.</i>"]
    await ui.render(target, "\n".join(lines), ui.kb(("✅ Сохранил", act.data())))


@act("inst")
async def _inst(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    await ui.render(cb, "⏳ Ставлю веб-панель…")
    await _access(cb, await api.call("web", "install", timeout=TIMEOUT), "Веб-панель установлена")


@act("pw")
async def _pw(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    await ui.confirm(cb, "Выдать новый пароль веб-панели? Прежний перестанет подходить, все открытые входы "
                         "завершатся.", ("🔑 Новый пароль", act.data("pwok")), act.data())


@act("pwok")
async def _pw_ok(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    await ui.render(cb, "⏳ Меняю пароль…")
    await _access(cb, await api.call("web", "password", timeout=TIMEOUT), "Новый пароль")


@act("path")
async def _path(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    await ui.confirm(cb, "Сменить секретный путь в адресе? Старая ссылка и закладки перестанут открываться.",
                     ("🔀 Сменить", act.data("pathok")), act.data())


@act("pathok")
async def _path_ok(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    r = await api.call("web", "path", timeout=TIMEOUT)
    await screen(cb, "✅ Новый адрес — старая ссылка больше не открывается" if r.ok else ui.fail(r, "Новый адрес"))


async def _service(cb: CallbackQuery, what: str, done: str) -> None:
    r = await api.call("web", what, timeout=TIMEOUT)
    await screen(cb, f"✅ {done}" if r.ok else ui.fail(r, "Веб-панель"))


@act("restart")
async def _restart(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    await _service(cb, "restart", "Перезапущена")


@act("start")
async def _start(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    await _service(cb, "start", "Запущена")


@act("stop")
async def _stop(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    await _service(cb, "stop", "Остановлена — адрес не открывается, пока не запустишь")


@act("rm")
async def _rm(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    await ui.confirm(cb, "<b>🗑 Удалить веб-панель?</b>\n\nСлужба, логин и пароль, правило UFW. Бот и Mini App "
                         "остаются.", ("🗑 Удалить", act.data("rmok")), act.data())


@act("rmok")
async def _rm_ok(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    await _service(cb, "remove", "Веб-панель удалена")
