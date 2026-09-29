"""Клиенты AWG: список, карточка, конфиг и QR, срок, мимикрия, туннели,
заметки и мониторинг, массовое создание, экспорт."""

from __future__ import annotations

import os
import re
import time

from aiogram import Bot, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, FSInputFile, Message

from .. import api, ask, media, store, ui
from ..ui import esc

router = Router()
act = ui.Actions(router, "cl")

PAGE = 10
NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
EXPIRES = [("1 час", "+1h"), ("1 день", "+1d"), ("7 дней", "+7d"), ("30 дней", "+30d")]
LEVELS = [("I1-I5 — полная цепочка", "3"), ("Только I1 — один пакет", "2")]


# ── Данные ────────────────────────────────────────────────
async def clients() -> list[dict] | None:
    r = await api.call("clients", "list")
    return r.data if r.ok and isinstance(r.data, list) else None


async def client(name: str) -> dict | None:
    return next((c for c in await clients() or [] if c["name"] == name), None)


def icon(c: dict) -> str:
    if c.get("blocked"):
        return "🚫"
    return "🟢" if c.get("online") else "⚪️"


def seen(c: dict) -> str:
    if c.get("blocked"):
        return "заблокирован: срок истёк"
    if c.get("online"):
        return f"онлайн ({ui.fmt_dur(c.get('ago'))} назад)"
    if c.get("handshake"):
        return f"был {ui.fmt_dur(c.get('ago'))} назад"
    return "не подключался"


# ── Отправка конфига ──────────────────────────────────────
async def send_config(bot: Bot, chat_id: int, name: str) -> bool:
    """Файл конфига и QR — для импорта в AmneziaVPN / AmneziaWG. Ошибка
    становится экраном; False — файлов нет."""
    r = await api.call("client", "conf", name)
    if not r.ok or not isinstance(r.data, dict):
        await ui.show_new(bot, chat_id, ui.fail(r, f"Конфиг {name}"), ui.kb(ui.back("cl")))
        return False
    text, path = r.data.get("text") or "", r.data.get("file") or f"{name}.conf"
    png = media.qr_png(text)
    caption = f"📄 <b>{esc(name)}</b> — импорт в AmneziaVPN / AmneziaWG"
    if not png:
        caption += f"\nℹ️ {len(text.encode())} байт — в читаемый QR не влезает, импортируй файлом"
    await bot.send_document(chat_id, BufferedInputFile(text.encode(), filename=os.path.basename(path)),
                            caption=caption)
    if png:
        await bot.send_photo(chat_id, BufferedInputFile(png, filename=f"{name}.png"),
                             caption=f"🔳 {esc(name)} — сканируй в AmneziaVPN")
    return True


# ── Список ────────────────────────────────────────────────
@act()
async def show_list(cb: CallbackQuery, state: FSMContext, arg: str = "0") -> None:
    await list_screen(cb, int(arg) if arg.isdigit() else 0)


@act("p")
async def _page(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    await list_screen(cb, int(arg) if arg.isdigit() else 0)


async def list_screen(target: ui.Target, page: int = 0) -> None:
    r = await api.call("clients", "list")
    if not r.ok or not isinstance(r.data, list):
        await ui.render(target, ui.fail(r, "Клиенты"), ui.kb(ui.back()))
        return
    rows: list[dict] = r.data
    online = sum(1 for c in rows if c.get("online"))
    blocked = sum(1 for c in rows if c.get("blocked"))
    pages = max(1, (len(rows) + PAGE - 1) // PAGE)
    page = min(max(page, 0), pages - 1)
    text = (f"<b>👥 Клиенты: {len(rows)}</b> · 🟢 {online} онлайн"
            + (f" · 🚫 {blocked} заблок." if blocked else "")
            + ("\n\nКлиентов пока нет." if not rows else "\n\n🟢 онлайн · ⚪️ офлайн · 🚫 срок истёк · 🔔 мониторинг"))
    notes = store.notes()
    buttons: list[ui.Button] = []
    for c in rows[page * PAGE:(page + 1) * PAGE]:
        bell = " 🔔" if store.MONITOR_TAG in notes.get(c["name"], "").lower() else ""
        buttons.append((f"{icon(c)} {c['name'] or '(без имени)'}{bell} · {c['ip']}", act.data("v", c["name"])))
    nav: list[ui.Button] = []
    if page > 0:
        nav.append((f"◀️ Страница {page}", act.data("p", str(page - 1))))
    if page < pages - 1:
        nav.append((f"Страница {page + 2} ▶️", act.data("p", str(page + 1))))
    await ui.render(target, text, ui.kb(
        buttons, nav,
        ("➕ Добавить клиента", act.data("add")),
        ("➕ Создать несколько", act.data("bulk")),
        ("📊 Активность и трафик", act.data("activity")) if rows else None,
        ("📦 Экспорт всех (zip)", act.data("export")) if rows else None,
        ("🧹 Удалить заблокированных", act.data("purge")) if blocked else None,
        ui.back()))


@act("activity")
async def _activity(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    rows = await clients()
    if rows is None:
        await ui.render(cb, "❌ Список клиентов не получен", ui.kb(ui.back("cl")))
        return
    lines = []
    for c in sorted(rows, key=lambda x: (not x.get("online"), -(x.get("handshake") or 0))):
        lines.append(f"{icon(c)} <b>{esc(c['name'])}</b> <code>{c['ip']}</code>\n"
                     f"    {seen(c)} · ↓{ui.fmt_bytes(c.get('rx'))} ↑{ui.fmt_bytes(c.get('tx'))}"
                     + (f"\n    ⏳ {ui.fmt_expire(c['expires'])}" if c.get("expires") and not c.get("blocked") else ""))
    text = "<b>📊 Активность и трафик</b>\n\n" + "\n".join(lines)
    if len(text) > ui.TEXT_MAX:
        text = text[:ui.TEXT_MAX - 20].rsplit("\n", 1)[0] + "\n…"
    await ui.render(cb, text, ui.kb(("🔄 Обновить", act.data("activity")), ui.back("cl")))


@act("export")
async def _export(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    await cb.answer("Собираю архив…")
    r = await api.call("clients", "export")
    if not r.ok or not isinstance(r.data, dict):
        await ui.render(cb, ui.fail(r, "Экспорт"), ui.kb(ui.back("cl")))
        return
    await ui.chat_of(cb).answer_document(FSInputFile(r.data["file"]),
                                         caption="📦 Все конфиги клиентов")
    await list_screen(ui.chat_of(cb))


@act("purge")
async def _purge(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    await ui.confirm(cb, "Удалить всех клиентов с истёкшим сроком? Их конфиги перестанут существовать.",
                     ("🗑 Да, удалить заблокированных", act.data("purgeok")), "cl")


@act("purgeok")
async def _purge_ok(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    gone = [c["name"] for c in await clients() or [] if c.get("blocked")]
    r = await api.call("clients", "purge-blocked")
    if r.ok:
        for n in gone:
            store.drop_note(n)
    await ui.result(cb, r, "Удаление заблокированных", "cl")


# ── Карточка ──────────────────────────────────────────────
# ── Маршрут ───────────────────────────────────────────────
# Клиентов везёт не больше одного туннеля. Показываем только работающий:
# списки выключенных туннелей хранятся, но на маршрут сейчас не влияют.
TUNNEL_NAMES = {"warp": "WARP", "xray": "Xray", "tun2socks": "tun2socks", "exits": "exit-ноды"}


async def active_route() -> dict:
    """Работающий туннель: {"kind": warp|xray|tun2socks|exits|"", для exits —
    mode (all|peers) и nodes}."""
    t = await api.data("tunnels", "status", default={}) or {}
    kind = next((k for k in ("warp", "xray", "tun2socks", "exits") if t.get(k) == "up"), "")
    route = {"kind": kind}
    if kind == "exits":
        e = await api.data("exits", "status", default={}) or {}
        route.update(mode=e.get("mode") or "all", nodes=[n["name"] for n in e.get("nodes") or []])
    return route


def exit_of(c: dict, route: dict) -> str:
    """Выход клиента через exit-ноды: off | shared | имя ноды. В режиме
    «все клиенты» все идут через общий выход, список не действует."""
    if route.get("mode") != "peers" or c.get("exit") is None:
        return "shared"
    return c["exit"]


def route_of(c: dict, route: dict) -> str:
    kind = route.get("kind")
    if not kind:
        return "напрямую"
    if kind in ("warp", "xray"):
        on = c.get(kind) is not False
        return f"через {TUNNEL_NAMES[kind]}" if on else f"напрямую ({TUNNEL_NAMES[kind]} — для других)"
    if kind == "tun2socks":
        return "через tun2socks"
    ex = exit_of(c, route)
    return {"off": "напрямую (exit-ноды — для других)", "shared": "exit-ноды, общий выход"}.get(ex, f"exit-нода {ex}")


def card_text(c: dict, route: dict) -> str:
    name = c["name"]
    note = store.strip_tag(store.note(name))
    return "\n".join(filter(None, [
        f"<b>👤 {esc(name)}</b>",
        "",
        f"IP: <code>{c['ip']}</code>",
        f"Статус: {icon(c)} {seen(c)}",
        f"Трафик: ↓{ui.fmt_bytes(c.get('rx'))} ↑{ui.fmt_bytes(c.get('tx'))}",
        f"Адрес клиента: <code>{esc(c['endpoint'].rsplit(':', 1)[0])}</code>" if c.get("endpoint") else "",
        f"Срок: {ui.fmt_expire(c.get('expires'))}",
        f"Мимикрия: {esc(c.get('mimicry') or 'none')}",
        f"Маршрут: {route_of(c, route)}",
        f"Заметка: {esc(note)}" if note else "",
        f"Мониторинг: {'🔔 вкл' if store.monitored(name) else '🔕 выкл'}",
    ]))


async def card(target: ui.Target, name: str) -> None:
    c = await client(name)
    if c is None:
        await ui.render(target, f"Клиента <b>{esc(name)}</b> нет.", ui.kb(ui.back("cl")))
        return
    route = await active_route()
    mon = store.monitored(name)
    await ui.render(target, card_text(c, route), ui.kb(
        ("📄 Конфиг и QR", act.data("conf", name)),
        ("✏️ Переименовать", act.data("ren", name)),
        ("⏳ Срок действия", act.data("exp", name)),
        ("🎭 Мимикрия", act.data("mim", name)),
        ("🌐 Маршрут", act.data("tun", name)) if route["kind"] in ("warp", "xray", "exits") else None,
        ("📝 Заметка", act.data("note", name)),
        ("🔕 Выключить мониторинг" if mon else "🔔 Мониторинг активности", act.data("mon", name)),
        ("🗑 Удалить", act.data("del", name)),
        ui.back("cl", "◀️ К списку")))


@act("v")
async def _view(cb: CallbackQuery, state: FSMContext, name: str) -> None:
    await card(cb, name)


@act("conf")
async def _conf(cb: CallbackQuery, state: FSMContext, name: str) -> None:
    await cb.answer()
    if await send_config(cb.bot, ui.chat_of(cb).chat.id, name):  # type: ignore[arg-type]
        await card(ui.chat_of(cb), name)            # карточка — под файлами


@act("mon")
async def _mon(cb: CallbackQuery, state: FSMContext, name: str) -> None:
    on = not store.monitored(name)
    store.set_monitored(name, on)
    await cb.answer("🔔 Буду сообщать, когда клиент пропадёт и вернётся" if on else "🔕 Мониторинг выключен")
    await card(cb, name)


@act("del")
async def _del(cb: CallbackQuery, state: FSMContext, name: str) -> None:
    await ui.confirm(cb, f"Удалить клиента <b>{esc(name)}</b>? Его конфиг перестанет работать.",
                     ("🗑 Да, удалить", act.data("delok", name)), act.data("v", name))


@act("delok")
async def _del_ok(cb: CallbackQuery, state: FSMContext, name: str) -> None:
    r = await api.call("client", "del", name)
    if not r.ok:
        await ui.render(cb, ui.fail(r, "Удаление"), ui.kb(ui.back(act.data("v", name))))
        return
    store.drop_note(name)
    await cb.answer(f"Удалён: {name}")
    await list_screen(cb)


# ── Переименование и заметка ──────────────────────────────
@act("ren")
async def _ren(cb: CallbackQuery, state: FSMContext, name: str) -> None:
    await ask.ask(cb, state, "cl_ren", f"Новое имя для <b>{esc(name)}</b>\n<i>латиница, цифры, _ и -, до 32</i>",
                  act.data("v", name), old=name)


@ask.on("cl_ren")
async def _ren_answer(msg: Message, state: FSMContext, ctx: ask.Ctx) -> None:
    new = ask.text_of(msg)
    if not NAME_RE.match(new):
        await ask.retry(msg, state, ctx, "Имя: латиница, цифры, _ и -, до 32 символов")
        return
    r = await api.call("client", "rename", ctx["old"], new)
    if not r.ok:
        await ask.retry(msg, state, ctx, r.message)
        return
    store.rename_note(ctx["old"], new)
    await card(msg, new)


@act("note")
async def _note(cb: CallbackQuery, state: FSMContext, name: str) -> None:
    cur = store.strip_tag(store.note(name))
    await ask.ask(cb, state, "cl_note",
                  f"Заметка для <b>{esc(name)}</b>" + (f"\nСейчас: {esc(cur)}" if cur else "")
                  + "\n<i>До 200 символов. «-» — очистить.</i>", act.data("v", name), name=name)


@ask.on("cl_note")
async def _note_answer(msg: Message, state: FSMContext, ctx: ask.Ctx) -> None:
    name, text = ctx["name"], ask.text_of(msg)
    text = "" if text == "-" else store.strip_tag(text)
    if store.monitored(name):
        text = f"{text[:store.NOTE_MAX - len(store.MONITOR_TAG) - 1]} {store.MONITOR_TAG}".strip()
    store.set_note(name, text)
    await card(msg, name)


# ── Срок действия ─────────────────────────────────────────
def expire_kb(prefix: str, arg: str, has: bool, back_to: str) -> ui.InlineKeyboardMarkup:
    """Сроки кнопками. prefix — действие, arg — имя клиента или пусто."""
    tag = f"{arg}|" if arg else ""
    return ui.kb(
        ("♾ Бессрочно" + (" / разблокировать" if has else ""), act.data(prefix, tag + "none")),
        [(f"⏳ {label}", act.data(prefix, tag + v)) for label, v in EXPIRES],
        ("📅 До даты…", act.data(prefix, tag + "date")),
        ui.back(back_to))


@act("exp")
async def _exp(cb: CallbackQuery, state: FSMContext, name: str) -> None:
    c = await client(name)
    if c is None:
        await card(cb, name)
        return
    await ui.render(cb, f"<b>⏳ Срок: {esc(name)}</b>\nСейчас: {ui.fmt_expire(c.get('expires'))}"
                        "\n\nИстёкший клиент не удаляется, а блокируется — срок можно снять.",
                    expire_kb("ex", name, bool(c.get("expires")), act.data("v", name)))


@act("ex")
async def _ex(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    name, _, v = arg.partition("|")
    if v == "date":
        await ask.ask(cb, state, "cl_exdate", "Дата окончания: <code>ГГГГ-ММ-ДД ЧЧ:ММ</code>",
                      act.data("exp", name), name=name)
        return
    r = await (api.call("client", "unexpire", name) if v == "none" else api.call("client", "expire", name, v))
    if not r.ok:
        await ui.render(cb, ui.fail(r, "Срок"), ui.kb(ui.back(act.data("v", name))))
        return
    await card(cb, name)


def parse_date(text: str) -> int | None:
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d", "%d.%m.%Y %H:%M", "%d.%m.%Y"):
        try:
            return int(time.mktime(time.strptime(text.strip(), fmt)))
        except ValueError:
            continue
    return None


@ask.on("cl_exdate")
async def _exdate(msg: Message, state: FSMContext, ctx: ask.Ctx) -> None:
    ts = parse_date(ask.text_of(msg))
    if not ts or ts <= time.time() + 60:
        await ask.retry(msg, state, ctx, "Нужна дата в будущем, например 2026-12-31 23:59")
        return
    r = await api.call("client", "expire", ctx["name"], ts)
    if not r.ok:
        await ask.retry(msg, state, ctx, r.message)
        return
    await card(msg, ctx["name"])


# ── Мимикрия ──────────────────────────────────────────────
async def mimicry_screen(target: ui.Target, title: str, pick: str, back_to: str, arg: str = "") -> None:
    """Выбор мимикрии. pick — действие, которому уходит строка мимикрии;
    arg — имя клиента (пусто для нового)."""
    tag = f"{arg}|" if arg else ""
    profiles = await api.data("mimicry", default=[])
    await ui.render(target, f"<b>🎭 {esc(title)}</b>\n\nПакеты I1-I5 перед рукопожатием — под какой протокол "
                            "маскироваться. Меняются только у клиента: сервер их не проверяет.",
                    ui.kb(("Как у сервера", act.data(pick, tag + "server")),
                          ("Без I1-I5", act.data(pick, tag + "none")),
                          [(f"{p['label']} — {p['hint']}", act.data("lvl", f"{pick}|{tag}{p['id']}"))
                           for p in profiles],
                          ui.back(back_to)))


@act("lvl")
async def _lvl(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    pick, _, rest = arg.partition("|")
    await ui.render(cb, "<b>Уровень мимикрии</b>\nWireSock не читает I1-I5; Keenetic — только I1.",
                    ui.kb([(label, act.data(pick, f"{rest}:{lvl}")) for label, lvl in LEVELS],
                          ui.back("cl")))


@act("mim")
async def _mim(cb: CallbackQuery, state: FSMContext, name: str) -> None:
    await mimicry_screen(cb, f"Мимикрия: {name}", "ms", act.data("v", name), name)


@act("ms")
async def _mim_set(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    name, _, spec = arg.partition("|")
    await ui.render(cb, f"⏳ Генерирую мимикрию для <b>{esc(name)}</b>…")
    r = await api.call("client", "mimicry", name, spec)
    if not r.ok:
        await ui.render(cb, ui.fail(r, "Мимикрия"), ui.kb(ui.back(act.data("v", name))))
        return
    if await send_config(cb.bot, ui.chat_of(cb).chat.id, name):  # type: ignore[arg-type]
        await ui.render(ui.chat_of(cb), f"✅ Мимикрия <b>{esc(name)}</b> обновлена — выше новый конфиг, "
                                        "старый больше не подключится.",
                        ui.kb(ui.back(act.data("v", name), "◀️ К клиенту")))


# ── Маршрут клиента ───────────────────────────────────────
@act("tun")
async def _tun(cb: CallbackQuery, state: FSMContext, name: str) -> None:
    c = await client(name)
    if c is None:
        await card(cb, name)
        return
    route = await active_route()
    kind = route["kind"]
    back_to = act.data("v", name)
    if kind not in ("warp", "xray", "exits"):
        await ui.render(cb, f"<b>🌐 Маршрут: {esc(name)}</b>\n\n"
                            + ("Все клиенты идут через tun2socks — выбора по клиентам у него нет."
                               if kind == "tun2socks" else "Туннели выключены — все клиенты идут напрямую."),
                        ui.kb(("🌐 Туннели и DNS", "tun"), ui.back(back_to)))
        return

    def opt(label: str, value: str, cur: bool) -> ui.Button:
        return (f"{'🔘' if cur else '⚪️'} {label}", act.data("rt", f"{kind}|{name}|{value}"))

    if kind == "exits":
        cur = exit_of(c, route)
        buttons = [opt("Напрямую", "off", cur == "off"), opt("Общий выход", "shared", cur == "shared")]
        buttons += [opt(f"Нода {n}", n, cur == n) for n in route.get("nodes") or []]
        note = ("\nВыбор для одного клиента переводит маршруты в режим «выбранные клиенты»: "
                "остальные остаются на общем выходе." if route.get("mode") != "peers" else "")
    else:
        on = c.get(kind) is not False
        buttons = [opt(f"Через {TUNNEL_NAMES[kind]}", "on", on), opt("Напрямую", "off", not on)]
        note = ""
    await ui.render(cb, f"<b>🌐 Маршрут: {esc(name)}</b>\nРаботает туннель: {TUNNEL_NAMES[kind]}.{note}",
                    ui.kb(buttons, ui.back(back_to)))


@act("rt")
async def _route_set(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    kind, name, value = (arg.split("|") + ["", "", ""])[:3]
    if kind == "exits":
        r = await api.call("exits", "client", name, value)
    else:
        r = await api.call("tunnels", "client", kind, name, value)
    if not r.ok:
        await ui.render(cb, ui.fail(r, "Маршрут"), ui.kb(ui.back(act.data("tun", name))))
        return
    await _tun(cb, state, name)


# ── Новый клиент ──────────────────────────────────────────
@act("add")
async def _add(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    await state.update_data(newcl={})
    await ask.ask(cb, state, "cl_add", "<b>➕ Новый клиент</b>\nИмя: латиница, цифры, _ и -, до 32 символов.",
                  "cl", [("🎲 Случайное имя", act.data("addrnd"))])


async def _add_expire(target: ui.Target, state: FSMContext, name: str) -> None:
    await state.update_data(newcl={"name": name})
    await ui.render(target, f"<b>➕ {esc(name)}</b>\nСрок действия:", expire_kb("ne", "", False, "cl"))


@act("addrnd")
async def _add_rnd(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    taken = {c["name"] for c in await clients() or []}
    n = 1
    while f"client{n}" in taken:
        n += 1
    await _add_expire(cb, state, f"client{n}")


@ask.on("cl_add")
async def _add_name(msg: Message, state: FSMContext, ctx: ask.Ctx) -> None:
    name = ask.text_of(msg)
    if not NAME_RE.match(name):
        await ask.retry(msg, state, ctx, "Имя: латиница, цифры, _ и -, до 32 символов")
        return
    if any(c["name"] == name for c in await clients() or []):
        await ask.retry(msg, state, ctx, f"Имя {name} уже занято")
        return
    await _add_expire(msg, state, name)


@act("ne")
async def _new_expire(cb: CallbackQuery, state: FSMContext, v: str) -> None:
    new = (await state.get_data()).get("newcl") or {}
    if not new.get("name"):
        await list_screen(cb)
        return
    if v == "date":
        await ask.ask(cb, state, "cl_nedate", "Дата окончания: <code>ГГГГ-ММ-ДД ЧЧ:ММ</code>", "cl")
        return
    await _new_mimicry(cb, state, "" if v == "none" else v)


@ask.on("cl_nedate")
async def _new_date(msg: Message, state: FSMContext, ctx: ask.Ctx) -> None:
    ts = parse_date(ask.text_of(msg))
    if not ts or ts <= time.time() + 60:
        await ask.retry(msg, state, ctx, "Нужна дата в будущем, например 2026-12-31 23:59")
        return
    await _new_mimicry(msg, state, str(ts))


async def _new_mimicry(target: ui.Target, state: FSMContext, expire: str) -> None:
    data = await state.get_data()
    new = dict(data.get("newcl") or {}, expire=expire)
    await state.update_data(newcl=new)
    server = await api.data("server", "info", default={}) or {}
    if server.get("profile") == "pro":
        await mimicry_screen(target, f"Мимикрия: {new['name']}", "nm", "cl")
    else:
        await _create(target, state, "server")


@act("nm")
async def _new_mim(cb: CallbackQuery, state: FSMContext, spec: str) -> None:
    await _create(cb, state, spec)


async def _create(target: ui.Target, state: FSMContext, spec: str) -> None:
    new = (await state.get_data()).get("newcl") or {}
    name = new.get("name")
    if not name:
        await list_screen(target)
        return
    await state.update_data(newcl={})
    await ui.render(target, f"⏳ Создаю <b>{esc(name)}</b>…")
    args = ["client", "add", name, f"mimicry={spec}"] + ([f"expire={new['expire']}"] if new.get("expire") else [])
    r = await api.call(*args)
    msg = ui.chat_of(target)
    if not r.ok:
        await ui.render(msg, ui.fail(r, f"Клиент {name}"), ui.kb(ui.back("cl")))
        return
    if await send_config(msg.bot, msg.chat.id, name):  # type: ignore[arg-type]
        await card(msg, name)


# ── Несколько клиентов ────────────────────────────────────
@act("bulk")
async def _bulk(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    await ask.ask(cb, state, "cl_bulk",
                  "<b>➕ Несколько клиентов</b>\n"
                  "Имена через запятую: <code>anna, boris, vera</code>\n"
                  "или префикс и число: <code>user:10</code> → user-001…user-010", "cl")


@ask.on("cl_bulk")
async def _bulk_answer(msg: Message, state: FSMContext, ctx: ask.Ctx) -> None:
    spec = ask.text_of(msg).replace(" ", "")
    m = re.fullmatch(r"([A-Za-z0-9_-]{1,27}):(\d{1,3})", spec)
    if m and not 1 <= int(m.group(2)) <= 200:
        await ask.retry(msg, state, ctx, "Число клиентов: 1-200")
        return
    if not m and not all(NAME_RE.match(n) for n in spec.split(",") if n):
        await ask.retry(msg, state, ctx, "Имена: латиница, цифры, _ и -, через запятую")
        return
    await state.update_data(bulk=spec)
    await ui.render(msg, "<b>➕ Несколько клиентов</b>\nСрок действия для всех:", expire_kb("be", "", False, "cl"))


@act("be")
async def _bulk_expire(cb: CallbackQuery, state: FSMContext, v: str) -> None:
    spec = (await state.get_data()).get("bulk")
    if not spec:
        await list_screen(cb)
        return
    if v == "date":
        await ask.ask(cb, state, "cl_bedate", "Дата окончания: <code>ГГГГ-ММ-ДД ЧЧ:ММ</code>", "cl")
        return
    await _bulk_create(cb, state, "" if v == "none" else v)


@ask.on("cl_bedate")
async def _bulk_date(msg: Message, state: FSMContext, ctx: ask.Ctx) -> None:
    ts = parse_date(ask.text_of(msg))
    if not ts or ts <= time.time() + 60:
        await ask.retry(msg, state, ctx, "Нужна дата в будущем, например 2026-12-31 23:59")
        return
    await _bulk_create(msg, state, str(ts))


async def _bulk_create(target: ui.Target, state: FSMContext, expire: str) -> None:
    spec = (await state.get_data()).get("bulk") or ""
    await state.update_data(bulk="")
    await ui.render(target, "⏳ Создаю клиентов…")
    r = await api.call("clients", "bulk", spec, *([f"expire={expire}"] if expire else []), timeout=900)
    msg = ui.chat_of(target)
    if not r.ok:
        await ui.render(msg, ui.fail(r, "Создание клиентов"), ui.kb(ui.back("cl")))
        return
    names = set(r.data or [])
    files = [c["file"] for c in await clients() or [] if c["name"] in names]
    await msg.answer_document(BufferedInputFile(media.zip_files(files), filename="awg_clients.zip"),
                              caption=f"📦 Создано клиентов: {len(names)}")
    await list_screen(msg)
