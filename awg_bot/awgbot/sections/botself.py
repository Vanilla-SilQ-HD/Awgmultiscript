"""Telegram-бот: версия, обновление, перезапуск, журнал, прокси до Telegram,
админы и приглашения, удаление бота.

Обновление, перезапуск и удаление идут задачами awg2: они останавливают сам
бот, а задача в отдельном юните доводит дело до конца. После старта бот
дочитывает её журнал (jobs.resume) и ставит итог в то же сообщение.
"""

from __future__ import annotations

import time

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from .. import __version__, access, admins, api, ask, jobs, ui
from ..ui import esc

router = Router()
act = ui.Actions(router, "botm")
adm = ui.Actions(router, "adm")


@act()
async def show(cb: CallbackQuery, state: FSMContext, arg: str = "") -> None:
    d = await api.data("bot", "status", default={}) or {}
    owner = access.is_owner(cb.from_user.id)
    await ui.render(cb, "<b>🤖 Telegram-бот</b>\n\n"
                        f"Версия: <b>{esc(__version__)}</b>\n"
                        f"Прокси до Telegram: {esc(d.get('proxy') or 'нет — напрямую')}\n"
                        f"Админов: владельцев {len(access.owners())}, приглашённых {len(admins.invited_ids())}",
                    ui.kb(("⬆️ Обновить / переустановить", act.data("update")),
                          ("🔄 Перезапустить", act.data("restart")),
                          ("📜 Журнал", "diag:log:bot"),
                          ("🌐 Прокси до Telegram", act.data("proxy")),
                          ("👮 Админы и приглашения", adm.data()) if owner else None,
                          ("🗑 Удалить бота", act.data("rm")) if owner else None,
                          ui.back()))


@act("update")
async def _update(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    await ui.confirm(cb, "Обновить бота из канала обновлений AWG Toolza? Он перезапустится и продолжит "
                         "показывать ход обновления здесь.",
                     ("⬆️ Обновить", act.data("updateok")), "botm")


@act("updateok")
async def _update_ok(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    await jobs.start(cb, "Обновление бота", "bot", "update", back_to="botm")


@act("restart")
async def _restart(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    await jobs.start(cb, "Перезапуск бота", "bot", "restart", back_to="botm")


# ── Прокси ────────────────────────────────────────────────
@act("proxy")
async def _proxy(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    d = await api.data("bot", "status", default={}) or {}
    cur = d.get("proxy") or ""
    await ui.render(cb, "<b>🌐 Прокси до Telegram</b>\nНужен, если Telegram у хостера заблокирован: "
                        "SOCKS5/HTTP-прокси или туннель этого сервера.\n\n"
                        f"Сейчас: <code>{esc(cur or 'нет — напрямую')}</code>",
                    ui.kb(("🔎 Найти на сервере", act.data("pcand")),
                          ("✏️ Ввести адрес", act.data("penter")),
                          ("🩺 Проверить", act.data("pcheck")) if cur else None,
                          ("🗑 Убрать прокси", act.data("pclear")) if cur else None,
                          ui.back("botm")))


@act("pcand")
async def _pcand(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    await ui.render(cb, "⏳ Ищу прокси и туннели на сервере, проверяю Telegram через каждый…")
    rows = await api.data("bot", "proxy", "candidates", default=[]) or []
    await ui.remember(state, "proxy", [r["url"] for r in rows])
    if not rows:
        await ui.render(cb, "Подходящих выходов на сервере нет — введи адрес вручную.",
                        ui.kb(("✏️ Ввести адрес", act.data("penter")), ui.back(act.data("proxy"))))
        return
    await ui.render(cb, "<b>Выходы сервера</b>\n✅ — Telegram через него отвечает.",
                    ui.kb([(f"{'✅' if r['ok'] else '❌'} {r['url']} — {r['label'].split(' — ')[0]}",
                            act.data("pset", str(i))) for i, r in enumerate(rows)], ui.back(act.data("proxy"))))


@act("pset")
async def _pset(cb: CallbackQuery, state: FSMContext, idx: str) -> None:
    url = await ui.recall(state, "proxy", idx)
    if url:
        await _apply_proxy(cb, state, url)


@act("penter")
async def _penter(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    await ask.ask(cb, state, "bot_proxy", "Адрес: <code>схема://[логин:пароль@]хост:порт</code> "
                                          "(http, https, socks4, socks5, socks5h) или <code>iface://warp0</code>.",
                  act.data("proxy"))


@ask.on("bot_proxy")
async def _proxy_answer(msg: Message, state: FSMContext, ctx: ask.Ctx) -> None:
    url = ask.text_of(msg).replace(" ", "")
    try:
        await msg.delete()                  # в адресе может быть пароль
    except Exception:                       # noqa: BLE001
        pass
    await _apply_proxy(msg, state, url)


async def _apply_proxy(target: ui.Target, state: FSMContext, url: str, force: bool = False) -> None:
    await ui.render(target, "⏳ Проверяю Telegram через прокси…")
    r = await api.call("bot", "proxy", "set", url, *(["force"] if force else []))
    if r.ok:
        await state.update_data(proxy_pending="")
        await ui.render(target, "✅ Прокси сохранён. Бот перезапускается — через несколько секунд он снова "
                                "на связи.", ui.kb(ui.back("botm")))
        return
    # Адрес для «сохранить всё равно» — только в памяти бота: в callback_data
    # ему не место (там может быть пароль)
    await state.update_data(proxy_pending=url)
    await ui.render(target, ui.fail(r, "Прокси"),
                    ui.kb(("⚠️ Сохранить всё равно", act.data("pforce")) if not force else None,
                          ui.back(act.data("proxy"))))


@act("pforce")
async def _pforce(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    url = (await state.get_data()).get("proxy_pending")
    if url:
        await _apply_proxy(cb, state, url, force=True)
    else:
        await _proxy(cb, state, "")


@act("pcheck")
async def _pcheck(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    r = await api.call("bot", "proxy", "check")
    await cb.answer(("✅ " if r.ok else "❌ ") + (r.message if not r.ok else "Telegram отвечает")[:180],
                    show_alert=True)


@act("pclear")
async def _pclear(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    r = await api.call("bot", "proxy", "clear")
    await ui.result(cb, r, "Прокси убран", "botm", "Бот ходит напрямую и сейчас перезапустится." if r.ok else "")


# ── Удаление бота ─────────────────────────────────────────
@act("rm")
async def _rm(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    if not access.is_owner(cb.from_user.id):
        await cb.answer("Только владелец", show_alert=True)
        return
    await ui.confirm(cb, "Удалить бота: службу, код и конфиг с токеном? AWG не затрагивается, "
                         "конфиг копируется в бэкапы.",
                     ("🗑 Удалить бота", act.data("rmok")), "botm")


@act("rmok")
async def _rm_ok(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    if access.is_owner(cb.from_user.id):
        await jobs.start(cb, "Удаление бота", "bot", "uninstall", back_to="main")


# ── Админы ────────────────────────────────────────────────
async def _owner_only(cb: CallbackQuery) -> bool:
    if access.is_owner(cb.from_user.id):
        return True
    await cb.answer("Список админов правит только владелец", show_alert=True)
    return False


@adm()
async def admins_screen(cb: CallbackQuery, state: FSMContext, arg: str = "") -> None:
    if not await _owner_only(cb):
        return
    lines = ["<b>👮 Админы</b>", "", "Владельцы (ADMIN_ID в /etc/awg-bot.conf):"]
    lines += [f"• <code>{uid}</code>" for uid in sorted(access.owners())]
    invited = admins.list_invited()
    lines.append("\nПриглашённые:" if invited else "\nПриглашённых нет.")
    lines += [f"• <code>{a.uid}</code>" + (f" @{esc(a.username)}" if a.username else "") for a in invited]
    pending = admins.pending_invites()
    if pending:
        lines.append(f"\nНеиспользованных приглашений: {pending}")
    await ui.render(cb, "\n".join(lines), ui.kb(
        ("➕ Пригласить админа (ссылка на 15 минут)", adm.data("invite")),
        [(f"🚫 Отозвать {a.uid}" + (f" @{a.username}" if a.username else ""), adm.data("rm", str(a.uid)))
         for a in invited],
        ("🧯 Погасить приглашения", adm.data("revoke")) if pending else None,
        ui.back("botm")))


@adm("invite")
async def _invite(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    if not await _owner_only(cb):
        return
    token, exp = admins.create_invite(cb.from_user.id)
    if token is None:
        await cb.answer(str(exp)[:190], show_alert=True)
        return
    me = await cb.bot.me()  # type: ignore[union-attr]
    link = f"https://t.me/{me.username}?start={admins.INVITE_PREFIX}{token}"
    await ui.render(cb, "<b>➕ Приглашение</b>\n\nПерешли ссылку тому, кому даёшь доступ. Она одноразовая и "
                        f"сгорит {ui.fmt_time(int(exp))} (через {ui.fmt_dur(int(exp) - int(time.time()))}).\n\n"
                        f"<code>{esc(link)}</code>\n\n"
                        "⚠️ Админ может всё, кроме управления списком админов: бот — это root на сервере.",
                    ui.kb(ui.back(adm.data())))


@adm("rm")
async def _adm_rm(cb: CallbackQuery, state: FSMContext, uid: str) -> None:
    if await _owner_only(cb):
        await ui.confirm(cb, f"Отозвать доступ у <code>{esc(uid)}</code>? Выданные им конфиги продолжат работать.",
                         ("🚫 Отозвать", adm.data("rmok", uid)), adm.data())


@adm("rmok")
async def _adm_rm_ok(cb: CallbackQuery, state: FSMContext, uid: str) -> None:
    if not await _owner_only(cb) or not uid.isdigit():
        return
    ok, res = admins.remove(int(uid), removed_by=cb.from_user.id)
    await cb.answer(res[:190], show_alert=not ok)
    await admins_screen(cb, state)


@adm("revoke")
async def _revoke(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    if await _owner_only(cb):
        n = admins.revoke_invites()
        await cb.answer(f"Погашено приглашений: {n}")
        await admins_screen(cb, state)
