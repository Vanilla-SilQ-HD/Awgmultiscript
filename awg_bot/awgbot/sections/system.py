"""Удаление и обновление AWG Toolza — пункты «Удаление» и «Обновление»."""

from __future__ import annotations

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from .. import access, api, jobs, store, ui
from ..ui import esc

router = Router()
rm = ui.Actions(router, "del")
upd = ui.Actions(router, "upd")


# ── Удаление ──────────────────────────────────────────────
@rm()
async def uninstall_screen(cb: CallbackQuery, state: FSMContext, arg: str = "") -> None:
    owner = access.is_owner(cb.from_user.id)
    await ui.render(cb, "<b>🗑 Удаление</b>\n\nПеред удалением делается бэкап в <code>~/awg_backup</code>.",
                    ui.kb(("🧹 Удалить всех клиентов — сервер остаётся", rm.data("clients")),
                          ("💣 Удалить всё", rm.data("all")) if owner else None,
                          ui.back()))


@rm("clients")
async def _clients(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    await ui.confirm(cb, "Удалить <b>всех</b> клиентов? Их конфиги перестанут работать; сервер, его параметры "
                         "и туннели останутся. Перед удалением — авто-бэкап.",
                     ("🧹 Да, удалить всех клиентов", rm.data("clientsok")), "del")


@rm("clientsok")
async def _clients_ok(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    r = await api.call("clients", "clean")
    if r.ok:
        store.save(store.NOTES, {})
    await ui.result(cb, r, "Клиенты удалены", "del")


async def _all_screen(target: ui.Target, state: FSMContext) -> None:
    opts = (await state.get_data()).get("uninstall") or {}
    mark = lambda k: "✅" if opts.get(k) else "⬜️"                        # noqa: E731
    await ui.render(target, "<b>💣 Удалить всё</b>\n\nСервер AWG, клиенты, туннели, модуль ядра и утилиты. "
                            "Отметь, что удалить вместе с ними:",
                    ui.kb((f"{mark('bot')} Telegram-бот (этот бот)", rm.data("opt", "bot")),
                          (f"{mark('wgobf')} WG + обфускатор", rm.data("opt", "wgobf")),
                          (f"{mark('self')} Сам скрипт awg2", rm.data("opt", "self")),
                          ("💣 Удалить", rm.data("allgo")),
                          ui.back("del", "✖️ Отмена")))


@rm("all")
async def _all(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    if not access.is_owner(cb.from_user.id):
        await cb.answer("Только владелец", show_alert=True)
        return
    await state.update_data(uninstall={})
    await _all_screen(cb, state)


@rm("opt")
async def _opt(cb: CallbackQuery, state: FSMContext, key: str) -> None:
    opts = dict((await state.get_data()).get("uninstall") or {})
    opts[key] = not opts.get(key)
    await state.update_data(uninstall=opts)
    await _all_screen(cb, state)


@rm("allgo")
async def _all_go(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    await ui.confirm(cb, "⚠️ Это необратимо: VPN-сервер перестанет существовать. Точно удалить?",
                     ("💣 Да, удалить всё", rm.data("allok")), rm.data("all"))


@rm("allok")
async def _all_ok(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    if not access.is_owner(cb.from_user.id):
        return
    opts = (await state.get_data()).get("uninstall") or {}
    await state.update_data(uninstall={})
    await jobs.start(cb, "Удаление AWG Toolza", "uninstall", *[k for k in ("bot", "wgobf", "self") if opts.get(k)],
                     back_to="main")


# ── Обновление ────────────────────────────────────────────
@upd()
async def update_screen(cb: CallbackQuery, state: FSMContext, arg: str = "") -> None:
    d = await api.data("update", "status", default={}) or {}
    await _render_update(cb, d, d.get("available") or "")


async def _render_update(target: ui.Target, d: dict, latest: str, checked: bool = False) -> None:
    beta = d.get("channel") == "beta"
    text = (f"<b>⬆️ Обновление AWG Toolza</b>\n\nУстановлена: <b>{esc(d.get('version', '?'))}</b>\n"
            f"Канал: {'бета — ранние сборки' if beta else 'стабильный'}")
    if latest:
        text += f"\nДоступна: <b>{esc(latest)}</b>"
    elif checked:
        text += "\nОбновлений нет."
    await ui.render(target, text, ui.kb(
        (f"⬆️ Обновить до {latest}", upd.data("go")) if latest else None,
        ("🔎 Проверить обновления", upd.data("check")),
        ("♻️ Переустановить из канала", upd.data("force")),
        ("🔀 Вернуться на стабильный канал" if beta else "🧪 Бета-канал", upd.data("ch", "stable" if beta else "beta")),
        ui.back()))


@upd("check")
async def _check(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    await ui.render(cb, "⏳ Проверяю канал обновлений…")
    r = await api.call("update", "check")
    if not r.ok or not isinstance(r.data, dict):
        await ui.render(cb, ui.fail(r, "Проверка обновлений"), ui.kb(ui.back("upd")))
        return
    d = r.data
    await _render_update(cb, d, d.get("latest") if d.get("newer") else "", checked=True)


async def _after_update(bot, chat_id: int, st: dict) -> None:
    await bot.send_message(chat_id, "awg2 обновлён. Если бот отстаёт от новой версии, обнови и его.",
                           reply_markup=ui.kb(("⬆️ Обновить бота", "botm:update"), ui.HOME))


@upd("go")
async def _go(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    await jobs.start(cb, "Обновление awg2", "update", "install", back_to="upd", done=_after_update)


@upd("force")
async def _force(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    await ui.confirm(cb, "Поставить версию из канала поверх текущей? Если в канале версия старше — это откат.",
                     ("♻️ Переустановить", upd.data("forceok")), "upd")


@upd("forceok")
async def _force_ok(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    await jobs.start(cb, "Переустановка awg2", "update", "install", "force", back_to="upd", done=_after_update)


@upd("ch")
async def _channel(cb: CallbackQuery, state: FSMContext, ch: str) -> None:
    r = await api.call("update", "channel", ch)
    if not r.ok:
        await ui.render(cb, ui.fail(r, "Канал"), ui.kb(ui.back("upd")))
        return
    await _check(cb, state, "")
