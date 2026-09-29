"""Главное меню — те же девять пунктов, что в меню awg2, и сводка сервера."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from .. import access, admins, api, ui
from ..ui import esc

router = Router()
act = ui.Actions(router, "main")

PROFILE = {"lite": "AmneziaVPN", "pro": "Мощный", "standard": "Standard"}


def _components(c: dict) -> str:
    if not c.get("installed"):
        return "❌ не установлены — <i>Сервер → Установить компоненты</i>"
    line = f"модуль <code>{esc(c.get('module') or '?')}</code>"
    if c.get("reboot"):
        line += f"\n   ▲ {esc(c['reboot'])}"
    elif c.get("module_update"):
        line += f" · ⬆️ есть {esc(c['module_update'])}"
    else:
        line += " ✓"
    return line


def _server(s: dict) -> str:
    if not s.get("exists"):
        return "не создан — <i>Сервер → Создать сервер</i>"
    up = "🟢" if s.get("up") else "🔴 не поднят ·"
    return (f"{up} AWG {esc(s.get('proto', '?'))} · {esc(PROFILE.get(s.get('profile', ''), s.get('profile', '')))}"
            f" · порт {s.get('port')} · клиентов {s.get('clients', 0)}")


def _tunnels(d: dict) -> str:
    t = d.get("tunnels") or {}
    names = [("warp", "WARP"), ("xray", "Xray"), ("tun2socks", "tun2socks"),
             ("exits", "Exit-ноды"), ("dns", "DNS")]
    parts = [f"{ui.state_icon(t[k])} {n}" for k, n in names if t.get(k, "none") != "none"]
    if t.get("cascade"):
        parts.append(f"🔀 каскад {t['cascade']}")
    if d.get("wgobf", "none") != "none":
        parts.append(f"{ui.state_icon(d['wgobf'])} WG+обф.")
    return " · ".join(parts) or "не настроены"


def status_text(d: dict) -> str:
    channel = "бета" if d.get("channel") == "beta" else "стабильный"
    head = f"<b>AWG Toolza</b> {esc(d.get('version', ''))} · {channel}"
    if d.get("update"):
        head += f" · ⬆️ {esc(d['update'])}"
    return "\n".join([
        head,
        f"🖥 {esc(d.get('host', ''))} · <code>{esc(d.get('ip', ''))}</code> · {esc(d.get('os', ''))}",
        "",
        f"Компоненты: {_components(d.get('components') or {})}",
        f"Сервер: {_server(d.get('server') or {})}",
        f"Туннели: {_tunnels(d)}",
    ])


def menu_kb(d: dict) -> ui.InlineKeyboardMarkup:
    upd = f"есть {d['update']}" if d.get("update") else ("бета" if d.get("channel") == "beta" else "стабильный")
    wo = "установлен" if d.get("wgobf", "none") != "none" else "как Phobos"
    return ui.kb(
        ("🖥 Сервер — установка", "srv"),
        ("👥 Клиенты — конфиги", "cl"),
        ("🩺 Диагностика — проверки", "diag"),
        ("💾 Бэкапы — сохранить", "bk"),
        ("🌐 Туннели и DNS — WARP, Xray", "tun"),
        ("🤖 Telegram-бот — управление", "botm"),
        ("🗑 Удаление — очистка", "del"),
        (f"⬆️ Обновление — {upd}", "upd"),
        (f"🛡 WG + обфускатор — {wo}", "wo"),
        ("🔄 Обновить сводку", "main"),
    )


async def show_menu(target: ui.Target) -> None:
    r = await api.call("status")
    if not r.ok or not isinstance(r.data, dict):
        # Без awg2 остаётся управление самим ботом — через него его и чинят
        await ui.render(target, ui.fail(r, "awg2 недоступен"),
                        ui.kb(("🤖 Telegram-бот — управление", "botm"), ("🔄 Повторить", "main")))
        return
    await ui.render(target, status_text(r.data), menu_kb(r.data))


@act()
async def _menu(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    await show_menu(cb)


@router.message(CommandStart())
async def cmd_start(msg: Message, state: FSMContext, command: CommandObject) -> None:
    user = msg.from_user
    if user is None:
        return
    payload = (command.args or "").strip()
    # Приглашение t.me/<бот>?start=inv_<токен>. Действующему админу ссылку не
    # гасим — пусть достанется тому, кого звали.
    if payload.startswith(admins.INVITE_PREFIX) and not access.authorized(user.id):
        ok, res = admins.consume_invite(payload[len(admins.INVITE_PREFIX):], user.id, user.username or "")
        if not ok:
            await msg.answer(f"⛔️ {esc(res)}")
            return
        who = f"@{esc(user.username)}" if user.username else f"<code>{user.id}</code>"
        for owner in access.owners():
            try:
                await msg.bot.send_message(owner, f"👮 Новый админ по приглашению: {who}")  # type: ignore[union-attr]
            except Exception:                                   # noqa: BLE001
                pass
        await msg.answer("✅ Приглашение принято — доступ к боту выдан.")
    if not access.authorized(user.id):
        await msg.answer("⛔️ Доступ запрещён.\n"
                         f"Твой Telegram ID: <code>{user.id}</code>\n"
                         "Владелец сервера может добавить его в ADMIN_ID или прислать приглашение.")
        return
    await state.clear()
    await show_menu(msg)
