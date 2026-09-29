"""WG + обфускатор (wg-obfuscator, как Phobos): установка, клиенты и их
комплекты, настройки, удаление."""

from __future__ import annotations

import re

from aiogram import Bot, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from .. import api, ask, jobs, media, ui
from ..ui import esc

router = Router()
act = ui.Actions(router, "wo")

NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


async def send_bundle(bot: Bot, chat_id: int, name: str) -> None:
    """Комплект клиента одним zip и ссылка для Keenetic (AWG Manager → Phobos)."""
    r = await api.call("wgobf", "bundle", name)
    if not r.ok or not isinstance(r.data, dict):
        await bot.send_message(chat_id, ui.fail(r, f"Комплект {name}"))
        return
    files = [f["path"] for f in r.data.get("files") or []]
    await bot.send_document(chat_id, BufferedInputFile(media.zip_files(files), filename=f"wgobf-{name}.zip"),
                            caption=f"🛡 <b>{esc(name)}</b>: wg.conf + obfuscator.conf, установщик для Linux, "
                                    "инструкция (README.txt)")
    link = (r.data.get("phobos") or "").strip()
    if link:
        await bot.send_message(chat_id, f"Keenetic, AWG Manager → «Phobos» (одной вставкой):\n<code>{esc(link)}</code>")


@act()
async def show(cb: CallbackQuery, state: FSMContext, arg: str = "") -> None:
    r = await api.call("wgobf", "status")
    if not r.ok or not isinstance(r.data, dict):
        await ui.render(cb, ui.fail(r, "WG + обфускатор"), ui.kb(ui.back()))
        return
    d = r.data
    if not d.get("installed"):
        await ui.render(cb, f"<b>🛡 WG + обфускатор</b> (wg-obfuscator {esc(d.get('version', ''))})\n\n"
                            "Отдельный WireGuard за обфускатором — как Phobos. AWG не трогает. Клиентам нужен "
                            "wg-obfuscator рядом с WireGuard (роутер Keenetic, Linux) — комплект это описывает.",
                        ui.kb(("📦 Установить", act.data("install")), ui.back()))
        return
    await ui.render(cb, "<b>🛡 WG + обфускатор</b>\n" + ui.pre(r.log, 1500, tail=False), ui.kb(
        ("➕ Добавить клиента", act.data("add")),
        ("👥 Клиенты", act.data("list")),
        ("🔄 Перезапустить", act.data("restart")),
        (f"🎭 Маскировка клиентов: {d.get('masking')} → {'NONE' if d.get('masking') == 'STUN' else 'STUN'}",
         act.data("mask", "NONE" if d.get("masking") == "STUN" else "STUN")),
        (f"🚪 Клиенты без обфускатора: {'да → нет' if d.get('clean') else 'нет → да'}",
         act.data("clean", "0" if d.get("clean") else "1")),
        ("🔑 Сменить ключ обфускатора", act.data("key")),
        ("📜 Журнал", "diag:log:wgobf"),
        ("🗑 Удалить WG + обфускатор", act.data("rm")),
        ui.back()))


# ── Установка ─────────────────────────────────────────────
async def _install_screen(target: ui.Target, state: FSMContext) -> None:
    o = (await state.get_data()).get("wgobf") or {}
    await ui.render(target, "<b>📦 Установка WG + обфускатор</b>\n\n"
                            f"Порт: {esc(o.get('port') or 'случайный')}\n"
                            f"Маскировка у клиентов: {o.get('masking', 'STUN')}\n"
                            f"Клиенты без обфускатора: {'да' if o.get('clean') == '1' else 'нет'}\n"
                            f"Первый клиент: {esc(o.get('client') or 'client1')}",
                    ui.kb(("✏️ Порт", act.data("iport")),
                          ("🎭 Маскировка: STUN ↔ NONE", act.data("iopt", "masking")),
                          ("🚪 Без обфускатора: да ↔ нет", act.data("iopt", "clean")),
                          ("✏️ Имя первого клиента", act.data("iname")),
                          ("✅ Установить", act.data("igo")),
                          ui.back("wo", "✖️ Отмена")))


@act("install")
async def _install(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    await state.update_data(wgobf={})
    await _install_screen(cb, state)


@act("iopt")
async def _install_opt(cb: CallbackQuery, state: FSMContext, key: str) -> None:
    o = dict((await state.get_data()).get("wgobf") or {})
    if key == "masking":
        o["masking"] = "NONE" if o.get("masking", "STUN") == "STUN" else "STUN"
    elif key == "clean":
        o["clean"] = "0" if o.get("clean") == "1" else "1"
    await state.update_data(wgobf=o)
    await _install_screen(cb, state)


@act("iport")
async def _install_port(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    await ask.ask(cb, state, "wo_port", "UDP-порт обфускатора (1024-65535):", "wo")


@ask.on("wo_port")
async def _install_port_answer(msg: Message, state: FSMContext, ctx: ask.Ctx) -> None:
    v = ask.text_of(msg)
    if not v.isdigit() or not 1024 <= int(v) <= 65535:
        await ask.retry(msg, state, ctx, "Порт — число 1024-65535")
        return
    o = dict((await state.get_data()).get("wgobf") or {}, port=v)
    await state.update_data(wgobf=o)
    await _install_screen(msg, state)


@act("iname")
async def _install_name(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    await ask.ask(cb, state, "wo_iname", "Имя первого клиента: латиница, цифры, _ и -, до 32.", "wo")


@ask.on("wo_iname")
async def _install_name_answer(msg: Message, state: FSMContext, ctx: ask.Ctx) -> None:
    v = ask.text_of(msg)
    if not NAME_RE.match(v):
        await ask.retry(msg, state, ctx, "Имя: латиница, цифры, _ и -, до 32 символов")
        return
    o = dict((await state.get_data()).get("wgobf") or {}, client=v)
    await state.update_data(wgobf=o)
    await _install_screen(msg, state)


@act("igo")
async def _install_go(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    o = (await state.get_data()).get("wgobf") or {}
    await state.update_data(wgobf={})
    name = o.get("client") or "client1"
    args = [f"masking={o.get('masking', 'STUN')}", f"clean={o.get('clean', '0')}", f"client={name}"]
    if o.get("port"):
        args.append(f"port={o['port']}")

    async def done(bot: Bot, chat_id: int, st: dict) -> None:
        await send_bundle(bot, chat_id, name)

    await jobs.start(cb, "Установка WG + обфускатор", "wgobf", "install", *args, back_to="wo", done=done)


# ── Клиенты ───────────────────────────────────────────────
@act("add")
async def _add(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    await ask.ask(cb, state, "wo_add", "Имя клиента: латиница, цифры, _ и -, до 32.", "wo")


@ask.on("wo_add")
async def _add_answer(msg: Message, state: FSMContext, ctx: ask.Ctx) -> None:
    name = ask.text_of(msg)
    if not NAME_RE.match(name):
        await ask.retry(msg, state, ctx, "Имя: латиница, цифры, _ и -, до 32 символов")
        return
    r = await api.call("wgobf", "add", name)
    if not r.ok:
        await ask.retry(msg, state, ctx, r.message)
        return
    await send_bundle(msg.bot, msg.chat.id, name)  # type: ignore[arg-type]
    await ui.render(msg, f"✅ Клиент <b>{esc(name)}</b> добавлен.", ui.kb(("👥 Клиенты", act.data("list")), ui.back("wo")))


@act("list")
async def _list(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    rows = await api.data("wgobf", "clients", default=[]) or []
    page = int(arg) if arg.isdigit() else 0
    await ui.render(cb, "<b>👥 Клиенты WG + обфускатор</b>" + ("" if rows else "\n\nКлиентов нет."),
                    ui.kb(ui.paged([(f"{'🟢' if r.get('ago') is not None and r['ago'] < 180 else '⚪️'} "
                                     f"{r['name']} · {r['ip']}"
                                     + (f" · {ui.fmt_dur(r['ago'])} назад" if r.get("ago") is not None else ""),
                                     act.data("v", r["name"])) for r in rows], page, lambda p: act.data("list", str(p))),
                          ui.back("wo")))


@act("v")
async def _view(cb: CallbackQuery, state: FSMContext, name: str) -> None:
    await ui.render(cb, f"<b>🛡 {esc(name)}</b>",
                    ui.kb(("📦 Комплект клиента", act.data("bundle", name)),
                          ("🗑 Удалить клиента", act.data("del", name)),
                          ui.back(act.data("list"))))


@act("bundle")
async def _bundle(cb: CallbackQuery, state: FSMContext, name: str) -> None:
    await cb.answer("Отправляю…")
    await send_bundle(cb.bot, ui.chat_of(cb).chat.id, name)  # type: ignore[arg-type]


@act("del")
async def _del(cb: CallbackQuery, state: FSMContext, name: str) -> None:
    await ui.confirm(cb, f"Удалить клиента <b>{esc(name)}</b>?", ("🗑 Удалить", act.data("delok", name)),
                     act.data("v", name))


@act("delok")
async def _del_ok(cb: CallbackQuery, state: FSMContext, name: str) -> None:
    r = await api.call("wgobf", "del", name)
    if not r.ok:
        await ui.render(cb, ui.fail(r, "Удаление"), ui.kb(ui.back(act.data("list"))))
        return
    await _list(cb, state, "")


# ── Настройки ─────────────────────────────────────────────
async def _quick(cb: CallbackQuery, title: str, *args: str) -> None:
    await ui.render(cb, f"⏳ {esc(title)}…")
    await ui.result(cb, await api.call(*args), title, "wo")


@act("restart")
async def _restart(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    await _quick(cb, "Перезапуск", "wgobf", "restart")


@act("mask")
async def _mask(cb: CallbackQuery, state: FSMContext, v: str) -> None:
    await _quick(cb, f"Маскировка {v}", "wgobf", "masking", v)


@act("clean")
async def _clean(cb: CallbackQuery, state: FSMContext, v: str) -> None:
    await _quick(cb, "Клиенты без обфускатора", "wgobf", "clean", v)


@act("key")
async def _key(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    await ui.confirm(cb, "Сменить ключ обфускатора? <b>Все</b> клиенты отключатся, пока не получат новый комплект.",
                     ("🔑 Сменить ключ", act.data("keyok")), "wo")


@act("keyok")
async def _key_ok(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    await _quick(cb, "Смена ключа", "wgobf", "rotate-key")


@act("rm")
async def _rm(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    await ui.confirm(cb, "Удалить WG + обфускатор со всеми его клиентами? AWG не затрагивается; архив "
                         "на всякий случай ляжет в ~/awg_backup.",
                     ("🗑 Удалить", act.data("rmok")), "wo")


@act("rmok")
async def _rm_ok(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    await _quick(cb, "Удаление WG + обфускатор", "wgobf", "remove")
