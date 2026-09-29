"""bot.py — сборка бота: конфиг, сессия, доступ, разделы, фоновые задачи.

Бот — тонкий интерфейс к awg2: каждый пункт меню awg2 здесь кнопка, а всю
работу делает `awg2 api`. Порядок роутеров важен: /start первым (через него
приходят приглашения), затем ожидание ввода текста, затем разделы.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage, SimpleEventIsolation
from aiogram.types import BotCommand, CallbackQuery, ErrorEvent, Message

from . import __version__, access, admins, api, ask, icons, jobs, monitor, net, store, ui, webapp
from .config import load_config
from .sections import backup, botself, clients, diag, main as main_menu, server, system, tunnels, wgobf

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("awgbot")

fallback = Router()


@fallback.message(F.text | F.document)
async def _anything(msg: Message) -> None:
    """Сообщение вне ввода — показать меню: кнопки удобнее команд."""
    await main_menu.show_menu(msg)


@fallback.callback_query()
async def _stale(cb: CallbackQuery) -> None:
    await cb.answer("Кнопка устарела — открой меню заново: /start", show_alert=True)


async def _on_error(event: ErrorEvent) -> None:
    log.exception("Ошибка обработки: %s", event.exception, exc_info=event.exception)
    cb = event.update.callback_query
    if cb is not None:
        with contextlib.suppress(Exception):
            await cb.answer("Ошибка — подробности в журнале бота", show_alert=True)


def build(session: BaseSession | None = None) -> tuple[Bot, Dispatcher]:
    """Бот и диспетчер. session — для тестов: подменная сессия Telegram."""
    cfg = load_config()
    access.setup(cfg)
    bot = Bot(token=cfg.token, session=session or net.build_session(cfg.proxy),
              default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True))
    bot.session.middleware(ui.TrackSent())
    bot.session.middleware(icons.Middleware())
    dp = Dispatcher(storage=MemoryStorage(), events_isolation=SimpleEventIsolation())
    guard = access.AccessMiddleware()
    dp.message.outer_middleware(guard)
    dp.callback_query.outer_middleware(guard)
    dp.errors.register(_on_error)
    dp.include_routers(main_menu.router, ask.router, server.router, clients.router, diag.router,
                       backup.router, tunnels.router, botself.router, system.router, wgobf.router, fallback)
    return bot, dp


async def restore(bot: Bot) -> None:
    """После старта: дочитать задачи и поправить экран «перезапускаюсь»."""
    n = jobs.resume(bot)
    if n:
        log.info("Дослеживаю задач: %d", n)
    notice = store.notice_pop()
    if notice.get("chat") and notice.get("msg"):
        text = (f"✅ {ui.esc(str(notice.get('text') or 'Бот перезапущен'))}\n"
                f"Бот снова на связи. Telegram — {ui.esc(net.route_note)}.")
        with contextlib.suppress(Exception):
            await bot.edit_message_text(text, chat_id=int(notice["chat"]), message_id=int(notice["msg"]),
                                        reply_markup=ui.kb(ui.back(str(notice.get("back") or "main"))))
            ui.set_screen(int(notice["chat"]), int(notice["msg"]))


async def main() -> None:
    bot, dp = build()
    tasks: list[asyncio.Task] = []

    @dp.startup()
    async def _startup() -> None:
        log.info("Бот %s запущен: владельцев %d, приглашённых %d, awg2: %s",
                 __version__, len(access.owners()), len(admins.invited_ids()), api.AWG2)
        # Нажатия за время простоя адресованы устаревшим экранам — не разбираем
        with contextlib.suppress(Exception):
            await bot.delete_webhook(drop_pending_updates=True)
        with contextlib.suppress(Exception):
            await bot.set_my_commands([BotCommand(command="start", description="Главное меню")])
        await restore(bot)
        tasks.append(asyncio.create_task(monitor.loop(bot), name="monitor"))
        try:
            await webapp.SERVER.start(bot)
        except Exception:                                   # noqa: BLE001
            log.exception("Mini App не запущена")

    @dp.shutdown()
    async def _shutdown() -> None:
        with contextlib.suppress(Exception):
            await webapp.SERVER.stop()
        for t in tasks:
            t.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await t
        log.info("Бот остановлен")

    await dp.start_polling(bot)

