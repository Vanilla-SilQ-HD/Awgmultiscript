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

PAGE = 20
NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
EXPIRES = [("1 час", "+1h"), ("1 день", "+1d"), ("7 дней", "+7d"), ("30 дней", "+30d")]
LEVELS = [("Цепочка I1-I5", "3"), ("Только I1", "2")]


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


# Сортировка списка: по активности — сначала онлайн, затем кто был недавно,
# неподключавшиеся и заблокированные в конце; по имени — без учёта регистра.
SORTS = {"activity": "по активности", "name": "по имени"}


def sort_rows(rows: list[dict], mode: str) -> list[dict]:
    if mode == "name":
        return sorted(rows, key=lambda c: c["name"].lower())
    return sorted(rows, key=lambda c: (bool(c.get("blocked")), not c.get("online"),
                                       -(c.get("handshake") or 0), c["name"].lower()))


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
    mode = store.setting("clients_sort", "activity")
    rows: list[dict] = sort_rows(r.data, mode)
    online = sum(1 for c in rows if c.get("online"))
    blocked = sum(1 for c in rows if c.get("blocked"))
    pages = max(1, (len(rows) + PAGE - 1) // PAGE)
    page = min(max(page, 0), pages - 1)
    text = (f"<b>👥 Клиенты: {len(rows)}</b> · 🟢 {online} онлайн"
            + (f" · 🚫 {blocked} заблок." if blocked else "")
            + ("\n\nКлиентов пока нет." if not rows else
               f"\nСортировка: {SORTS.get(mode, mode)}\n\n🟢 онлайн · ⚪️ офлайн · 🚫 срок истёк · 🔔 мониторинг"))
    notes = store.notes()
    buttons: list[ui.Button] = []
    for c in rows[page * PAGE:(page + 1) * PAGE]:
        bell = " 🔔" if store.MONITOR_TAG in notes.get(c["name"], "").lower() else ""
        label = f"{icon(c)} {c['name'] or '(без имени)'}{bell}"
        # По активности — и давность, если влезает в полстроки
        if mode == "activity" and c.get("handshake") and not c.get("blocked"):
            with_ago = f"{label} · {ui.fmt_dur(c.get('ago'))}"
            label = with_ago if ui.width(with_ago) <= ui.WIDE else label
        buttons.append((label, act.data("v", c["name"])))
    nav: list[ui.Button] = []
    if page > 0:
        nav.append((f"◀️ Стр. {page}", act.data("p", str(page - 1))))
    if page < pages - 1:
        nav.append((f"Стр. {page + 2} ▶️", act.data("p", str(page + 1))))
    other = "name" if mode == "activity" else "activity"
    await ui.render(target, text, ui.kb(
        buttons, nav,
        ("➕ Добавить", act.data("add")),
        ("➕ Несколько", act.data("bulk")),
        (f"🔃 {SORTS[other].capitalize()}", act.data("sort", other)) if len(rows) > 1 else None,
        ("📊 Трафик", act.data("activity")) if rows else None,
        ("📦 Экспорт zip", act.data("export")) if rows else None,
        ("🗑 Удалить…", act.data("dsel")) if rows else None,
        ("🧹 Истёкшие", act.data("purge")) if blocked else None,
        ui.back()))


@act("sort")
async def _sort(cb: CallbackQuery, state: FSMContext, mode: str) -> None:
    store.set_setting("clients_sort", mode if mode in SORTS else "activity")
    await list_screen(cb)


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


@act("purge")
async def _purge(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    await ui.confirm(cb, "Удалить всех клиентов с истёкшим сроком? Их конфиги перестанут существовать.",
                     ("🗑 Да, удалить", act.data("purgeok")), "cl")


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
        ("🔕 Мониторинг" if mon else "🔔 Мониторинг", act.data("mon", name)),
        ("🗑 Удалить", act.data("del", name)),
        ui.back("cl", "◀️ К списку")))


@act("v")
async def _view(cb: CallbackQuery, state: FSMContext, name: str) -> None:
    await card(cb, name)


@act("conf")
async def _conf(cb: CallbackQuery, state: FSMContext, name: str) -> None:
    await cb.answer()
    await send_config(cb.bot, ui.chat_of(cb).chat.id, name)  # type: ignore[arg-type]


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


# ── Удаление нескольких ───────────────────────────────────
# Отмеченные имена — в данных FSM (del_sel): в callback_data их не уложить.
async def _pick_screen(target: ui.Target, state: FSMContext, page: int = 0) -> None:
    rows = await clients()
    if rows is None:
        await ui.render(target, "❌ Список клиентов не получен", ui.kb(ui.back("cl")))
        return
    rows = sort_rows(rows, store.setting("clients_sort", "activity"))
    names = {c["name"] for c in rows}
    sel = [n for n in (await state.get_data()).get("del_sel") or [] if n in names]
    await state.update_data(del_sel=sel)
    buttons = [(f"{'🗑' if c['name'] in sel else '⬜️'} {c['name']}", act.data("ds", f"{page}|{c['name']}"))
               for c in rows]
    await ui.render(target, "<b>🗑 Удалить клиентов</b>\nОтметь, кого удалить. Их конфиги перестанут работать.\n\n"
                            + (f"Отмечено: {len(sel)}" if sel else "Никто не отмечен."),
                    ui.kb(ui.paged(buttons, page, lambda p: act.data("dsp", str(p))),
                          ("☑️ Отметить всех", act.data("dsa", "all")) if len(sel) < len(rows) else None,
                          ("⬜️ Снять все", act.data("dsa", "none")) if sel else None,
                          (f"🗑 Удалить: {len(sel)}", act.data("dsgo")) if sel else None,
                          ui.back("cl")))


@act("dsel")
async def _dsel(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    await state.update_data(del_sel=[])
    await _pick_screen(cb, state)


@act("dsp")
async def _dsel_page(cb: CallbackQuery, state: FSMContext, page: str) -> None:
    await _pick_screen(cb, state, int(page) if page.isdigit() else 0)


@act("ds")
async def _dsel_toggle(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    page, _, name = arg.partition("|")
    sel = list((await state.get_data()).get("del_sel") or [])
    if name in sel:
        sel.remove(name)
    else:
        sel.append(name)
    await state.update_data(del_sel=sel)
    await _pick_screen(cb, state, int(page) if page.isdigit() else 0)


@act("dsa")
async def _dsel_all(cb: CallbackQuery, state: FSMContext, what: str) -> None:
    rows = await clients() or []
    await state.update_data(del_sel=[c["name"] for c in rows] if what == "all" else [])
    await _pick_screen(cb, state)


@act("dsgo")
async def _dsel_go(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    sel = (await state.get_data()).get("del_sel") or []
    if not sel:
        await _pick_screen(cb, state)
        return
    shown = ", ".join(sel[:30]) + (f" и ещё {len(sel) - 30}" if len(sel) > 30 else "")
    await ui.confirm(cb, f"Удалить клиентов: <b>{len(sel)}</b>?\n{esc(shown)}\n\nИх конфиги перестанут работать. "
                         "Копия awg0.conf сохранится рядом с ним.",
                     ("🗑 Да, удалить", act.data("dsok")), act.data("dsp", "0"))


@act("dsok")
async def _dsel_ok(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    sel = (await state.get_data()).get("del_sel") or []
    if not sel:
        await list_screen(cb)
        return
    await ui.render(cb, f"⏳ Удаляю клиентов: {len(sel)}…")
    r = await api.call("clients", "del", ",".join(sel), timeout=600)
    gone = list(r.data or []) if isinstance(r.data, list) else []
    for n in gone:
        store.drop_note(n)
    await state.update_data(del_sel=[])
    if not r.ok:
        await ui.render(cb, ui.fail(r, "Удаление клиентов"), ui.kb(ui.back("cl")))
        return
    await ui.render(cb, f"✅ <b>Удалено клиентов: {len(gone)}</b>\n{esc(', '.join(gone))}",
                    ui.kb(ui.Row(("👥 Клиенты", "cl"), ui.HOME)))


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
        ("♾ Снять срок" if has else "♾ Бессрочно", act.data(prefix, tag + "none")),
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
def server_mimicry(srv: dict, profiles: list[dict]) -> str:
    """Что выдаёт «Как у сервера»: профиль и уровень по меткам сервера."""
    mim = srv.get("mimicry") or "none"
    if mim == "none" or str(srv.get("obf_level") or "1") == "1":
        return "без I1-I5"
    label = next((p.get("label") for p in profiles if p.get("id") == mim), mim)
    return f"{label}, " + ("только I1" if str(srv.get("obf_level")) == "2" else "цепочка I1-I5")


async def mimicry_screen(target: ui.Target, title: str, pick: str, back_to: str, arg: str = "") -> None:
    """Выбор мимикрии. pick — действие, которому уходит строка мимикрии;
    arg — имя клиента (пусто для нового)."""
    tag = f"{arg}|" if arg else ""
    profiles = await api.data("mimicry", default=[])
    srv = await api.data("server", "info", default={}) or {}
    await ui.render(target, f"<b>🎭 {esc(title)}</b>\n\nПакеты I1-I5 перед рукопожатием — под какой протокол "
                            "маскироваться. Меняются только у клиента: сервер их не проверяет.\n"
                            f"Как у сервера — {esc(server_mimicry(srv, profiles))}.\n\n"
                            + ui.profile_hints(profiles),
                    ui.kb(("Как у сервера", act.data(pick, tag + "server")),
                          ("Без I1-I5", act.data(pick, tag + "none")),
                          [(p["label"], act.data("lvl", f"{pick}|{tag}{p['id']}")) for p in profiles],
                          ui.back(back_to)))


@act("lvl")
async def _lvl(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    pick, _, rest = arg.partition("|")
    await ui.render(cb, "<b>Уровень мимикрии</b>\n• Цепочка I1-I5 — полная\n"
                        "• Только I1 — один пакет: Keenetic читает только его\nWireSock не читает I1-I5 вовсе.",
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
    await ui.render(cb, f"✅ Мимикрия <b>{esc(name)}</b> обновлена — новый конфиг ниже, "
                        "старый больше не подключится.",
                    ui.kb(ui.back(act.data("v", name), "◀️ К клиенту")))
    await send_config(cb.bot, ui.chat_of(cb).chat.id, name)  # type: ignore[arg-type]


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
    if not r.ok:
        await ui.render(target, ui.fail(r, f"Клиент {name}"), ui.kb(ui.back("cl")))
        return
    store.drop_note(name)           # заметка от удалённого тёзки не наследуется
    await card(target, name)        # «⏳» становится карточкой, файлы — под ней
    msg = ui.chat_of(target)
    await send_config(msg.bot, msg.chat.id, name)  # type: ignore[arg-type]


# ── Несколько клиентов ────────────────────────────────────
# Как в меню awg2: префикс и количество (user-001…) или имена списком.
COUNTS = (2, 3, 5, 10, 20, 50)


@act("bulk")
async def _bulk(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    await ui.render(cb, "<b>➕ Несколько клиентов</b>\nКак назвать?\n"
                        "• Префикс+номер — user-001, user-002…\n• Имена списком — через запятую",
                    ui.kb(("🔢 Префикс+номер", act.data("bpre")),
                          ("✍️ Имена списком", act.data("bnames")),
                          ui.back("cl")))


@act("bpre")
async def _bulk_prefix(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    await ask.ask(cb, state, "cl_bprefix", "<b>➕ Несколько клиентов</b>\nПрефикс имён: латиница, цифры, _ и -, "
                                           "до 27 символов. Получатся <code>префикс-001</code>, <code>-002</code>…",
                  act.data("bulk"), [("user", act.data("bp", "user")), ("client", act.data("bp", "client"))])


@ask.on("cl_bprefix")
async def _bulk_prefix_answer(msg: Message, state: FSMContext, ctx: ask.Ctx) -> None:
    prefix = ask.text_of(msg)
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,27}", prefix):
        await ask.retry(msg, state, ctx, "Префикс: латиница, цифры, _ и -, до 27 символов")
        return
    await _bulk_count(msg, state, prefix)


@act("bp")
async def _bulk_prefix_btn(cb: CallbackQuery, state: FSMContext, prefix: str) -> None:
    await _bulk_count(cb, state, prefix)


async def _bulk_count(target: ui.Target, state: FSMContext, prefix: str) -> None:
    await state.update_data(bulk_prefix=prefix)
    await ui.render(target, f"<b>➕ Несколько клиентов</b>\nСколько создать? Имена: <code>{esc(prefix)}-001</code>…",
                    ui.kb([(str(n), act.data("bn", str(n))) for n in COUNTS],
                          ("✏️ Другое…", act.data("bn", "ask")), ui.back(act.data("bulk"))))


@act("bn")
async def _bulk_n(cb: CallbackQuery, state: FSMContext, n: str) -> None:
    prefix = (await state.get_data()).get("bulk_prefix")
    if not prefix:
        await _bulk(cb, state, "")
        return
    if n == "ask":
        await ask.ask(cb, state, "cl_bcount", "Сколько клиентов создать (1-200)?", act.data("bulk"))
        return
    await _bulk_expire_screen(cb, state, f"{prefix}:{n}")


@ask.on("cl_bcount")
async def _bulk_count_answer(msg: Message, state: FSMContext, ctx: ask.Ctx) -> None:
    v = ask.text_of(msg)
    prefix = (await state.get_data()).get("bulk_prefix")
    if not v.isdigit() or not 1 <= int(v) <= 200:
        await ask.retry(msg, state, ctx, "Нужно число от 1 до 200")
        return
    await _bulk_expire_screen(msg, state, f"{prefix}:{int(v)}")


@act("bnames")
async def _bulk_names(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    await ask.ask(cb, state, "cl_bnames", "<b>➕ Несколько клиентов</b>\nИмена через запятую, например "
                                          "<code>anna, boris, vera</code>", act.data("bulk"))


@ask.on("cl_bnames")
async def _bulk_names_answer(msg: Message, state: FSMContext, ctx: ask.Ctx) -> None:
    names = [n for n in ask.text_of(msg).replace(" ", "").split(",") if n]
    if not names or not all(NAME_RE.match(n) for n in names):
        await ask.retry(msg, state, ctx, "Имена: латиница, цифры, _ и -, до 32 символов, через запятую")
        return
    await _bulk_expire_screen(msg, state, ",".join(names))


async def _bulk_expire_screen(target: ui.Target, state: FSMContext, spec: str) -> None:
    await state.update_data(bulk=spec)
    what = (f"{spec.split(':')[1]} шт. с префиксом {spec.split(':')[0]}" if ":" in spec
            else ", ".join(spec.split(",")))
    await ui.render(target, f"<b>➕ Несколько клиентов</b>\n{esc(what)}\n\nСрок действия для всех:",
                    expire_kb("be", "", False, "cl"))


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
    if not r.ok:
        await ui.render(target, ui.fail(r, "Создание клиентов"), ui.kb(ui.back("cl")))
        return
    created = list(r.data or [])
    for n in created:               # заметка от удалённого тёзки не наследуется
        store.drop_note(n)
    shown = ", ".join(created[:30]) + (f" и ещё {len(created) - 30}" if len(created) > 30 else "")
    await ui.render(target, f"✅ <b>Создано клиентов: {len(created)}</b>\n{esc(shown)}\n\n"
                            "Конфиги — архивом ниже.",
                    ui.kb(ui.Row(("👥 Клиенты", "cl"), ui.HOME)))
    files = [c["file"] for c in await clients() or [] if c["name"] in set(created)]
    await ui.chat_of(target).answer_document(
        BufferedInputFile(media.zip_files(files), filename="awg_clients.zip"),
        caption=f"📦 Конфиги: {len(files)}")
