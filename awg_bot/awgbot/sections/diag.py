"""Диагностика: сводка, домены мимикрии, тест мимикрии, DPI у клиента,
журналы служб."""

from __future__ import annotations

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from .. import api, jobs, ui
from ..ui import esc

router = Router()
act = ui.Actions(router, "diag")

LOGS = [
    ("manager", "awg2 — действия"), ("install", "компоненты"), ("module", "сборка модуля"),
    ("awg", "awg0 (awg-quick)"), ("expire", "сроки клиентов"), ("warp", "WARP"),
    ("warp-health", "WARP health-check"), ("xray", "Xray"), ("xray-routing", "маршруты Xray"),
    ("tun2socks", "tun2socks"), ("exits", "exit-ноды"), ("cascade", "каскад"),
    ("dns", "dnscrypt-proxy"), ("dns-health", "DNS health-check"), ("wgobf", "WG + обфускатор"),
    ("bot", "Telegram-бот"),
]

DPI_HINT = (
    "<b>🔍 DPI со стороны клиента</b>\n\n"
    "Запускать на устройстве клиента, не на сервере:\n"
    "<code>docker run --rm -it --pull=always ghcr.io/runnin4ik/dpi-detector:latest</code>\n"
    "или Python: <code>git clone https://github.com/Runnin4ik/dpi-detector.git</code>, "
    "затем <code>pip install -r requirements.txt</code> и <code>python dpi_detector.py</code>. "
    "Для Windows и macOS — готовые сборки в Releases.\n\n"
    "<b>Что делать с результатом</b>\n"
    "• рабочий у провайдера клиента домен → домен мимикрии (карточка клиента → Мимикрия)\n"
    "• подмена DNS / перехват UDP 53 → Туннели → Шифрованный DNS\n"
    "• обрыв после первых КБ → профиль «AmneziaVPN» и короче I1-I5\n\n"
    "<i>Сторонний проект (MIT), awg2 его не ставит.</i>"
)


@act()
async def show(cb: CallbackQuery, state: FSMContext, arg: str = "") -> None:
    await ui.render(cb, "<b>🩺 Диагностика</b>\n\n"
                        "• Домены — какие домены мимикрии отвечают (мир или Россия)\n"
                        "• Тест мимикрии — захват первых пакетов клиента\n"
                        "• DPI клиента — проверка со стороны клиента", ui.kb(
        ("📋 Сводка", act.data("status")),
        ("📜 Журналы", act.data("logs")),
        ("🌍 Домены: мир", act.data("dom", "world")),
        ("🇷🇺 Домены: РФ", act.data("dom", "ru")),
        ("🎯 Тест мимикрии", act.data("sniff")),
        ("🔍 DPI клиента", act.data("dpi")),
        ("🧩 Модуль ядра", "mod"),
        ui.back()))


@act("status")
async def _status(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    r = await api.call("diag", "status")
    await ui.render(cb, "<b>📋 Сводка</b>\n" + (ui.pre(r.log, 3500, tail=False) if r.ok else ui.fail(r)),
                    ui.kb(("🔄 Обновить", act.data("status")), ui.back("diag")))


@act("dom")
async def _domains(cb: CallbackQuery, state: FSMContext, region: str) -> None:
    await jobs.start(cb, f"Домены мимикрии ({'Россия' if region == 'ru' else 'мир'})",
                     "diag", "domains", region, back_to="diag")


@act("dpi")
async def _dpi(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    await ui.render(cb, DPI_HINT, ui.kb(ui.back("diag")))


@act("sniff")
async def _sniff(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    rows = await api.data("diag", "sniff-list", default=[]) or []
    if not rows:
        await ui.render(cb, "Нет клиентов, которые уже подключались. Подключись с устройства и вернись сюда.",
                        ui.kb(("🔄 Обновить", act.data("sniff")), ui.back("diag")))
        return
    await ui.render(cb, "<b>🎯 Тест мимикрии</b>\nСервер 20 секунд слушает первые пакеты клиента и "
                        "проверяет, видны ли пакеты мимикрии и на что они похожи.\n\nКлиент:",
                    ui.kb([(r["name"], act.data("sn", r["name"])) for r in rows[:40]], ui.back("diag")))


@act("sn")
async def _sniff_client(cb: CallbackQuery, state: FSMContext, name: str) -> None:
    await ui.render(cb, f"<b>🎯 {esc(name)}</b>\n\nНа устройстве клиента: отключись, нажми «Слушать» и "
                        "в течение 20 секунд подключись снова.",
                    ui.kb(("👂 Слушать 20 с", act.data("sngo", name)), ui.back(act.data("sniff"))))


@act("sngo")
async def _sniff_go(cb: CallbackQuery, state: FSMContext, name: str) -> None:
    await jobs.start(cb, f"Тест мимикрии: {name}", "diag", "sniff", name, back_to="diag")


@act("logs")
async def _logs(cb: CallbackQuery, state: FSMContext, arg: str) -> None:
    await ui.render(cb, "<b>📜 Журналы</b>\nПоследние строки журнала службы.",
                    ui.kb([(label, act.data("log", name)) for name, label in LOGS], ui.back("diag")))


@act("log")
async def _log(cb: CallbackQuery, state: FSMContext, name: str) -> None:
    r = await api.call("log", name, 80)
    label = dict(LOGS).get(name, name)
    body = (ui.pre(r.log, 3600) or "<i>пусто</i>") if r.ok else ui.fail(r)
    await ui.render(cb, f"<b>📜 {esc(label)}</b>\n{body}",
                    ui.kb(("🔄 Обновить", act.data("log", name)), ui.back(act.data("logs"))))
