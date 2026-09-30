"""panel.py — JSON API полной панели Mini App.

Все запросы — POST с JSON; подпись Telegram и доступ проверяет webapp
(user_of). Панель делает то же, что бот, и тем же путём — через awg2 api;
сверх него здесь то, что ведёт сам бот: заметки и мониторинг клиентов,
QR, отправка файлов в чат. Права — как в боте: владельческое (удаление
всего, удаление бота, сертификат и порт Mini App) — только владельцам.
"""

from __future__ import annotations

import base64
import os
import re
from typing import Any, Callable

from aiogram.types import BufferedInputFile, FSInputFile
from aiohttp import web

from . import access, api, media, store
from .sections import clients as cls

# Команды awg2 api, открытые панели; первое слово — раздел
ALLOWED = {"status", "version", "server", "module", "clients", "client", "mimicry", "diag", "backup",
           "tunnels", "warp", "xray", "t2s", "exits", "cascade", "dns", "wgobf", "update", "log", "bot",
           "cert", "uninstall"}
OWNER_ONLY = (("uninstall",), ("bot", "uninstall"), ("bot", "webapp", "port"), ("cert", "issue"),
              ("cert", "remove"))
NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
MAX_ARGS, MAX_ARG = 16, 4000
TIMEOUT_MAX = 900

UserOf = Callable[[web.Request], dict]


def _bad(text: str) -> web.HTTPBadRequest:
    return web.HTTPBadRequest(text=f'{{"error": "{text}"}}', content_type="application/json")


async def _body(request: web.Request) -> dict:
    try:
        body = await request.json()
    except ValueError:
        raise _bad("нужен JSON") from None
    if not isinstance(body, dict):
        raise _bad("нужен JSON-объект")
    return body


def _name(body: dict, key: str = "name") -> str:
    name = str(body.get(key) or "")
    if not NAME_RE.match(name):
        raise _bad("имя клиента: латиница, цифры, _ и -, до 32")
    return name


def _args(body: dict) -> list[str]:
    args = body.get("args")
    if (not isinstance(args, list) or not args or len(args) > MAX_ARGS
            or not all(isinstance(a, (str, int)) and len(str(a)) <= MAX_ARG for a in args)):
        raise _bad("args — список строк")
    return [str(a) for a in args]


def _check(user: dict, args: list[str]) -> None:
    if args[0] not in ALLOWED:
        raise web.HTTPForbidden(text='{"error": "команда недоступна панели"}', content_type="application/json")
    if any(tuple(args[:len(p)]) == p for p in OWNER_ONLY) and not access.is_owner(int(user["id"])):
        raise web.HTTPForbidden(text='{"error": "только владелец"}', content_type="application/json")


def _result(r: api.Result) -> web.Response:
    return web.json_response({"ok": r.ok, "data": r.data, "log": (r.log or "")[-8000:],
                              "error": "" if r.ok else r.message})


def setup(app: web.Application, user_of: UserOf) -> None:
    """Маршруты панели. user_of(request) — пользователь или 401/403."""

    def route(path: str):  # type: ignore[no-untyped-def]
        def deco(fn: Callable[[web.Request, dict, dict], Any]):  # type: ignore[no-untyped-def]
            async def handler(request: web.Request) -> web.StreamResponse:
                user = user_of(request)
                return await fn(request, user, await _body(request))
            app.router.add_post(path, handler)
            return fn
        return deco

    # ── Общий вызов awg2 api и задачи ──
    @route("/api/call")
    async def _call(request: web.Request, user: dict, body: dict) -> web.Response:
        args = _args(body)
        _check(user, args)
        try:
            timeout = min(float(body.get("timeout") or 120), TIMEOUT_MAX)
        except (TypeError, ValueError):
            timeout = 120
        stdin = body.get("stdin")
        return _result(await api.call(*args, stdin=stdin if isinstance(stdin, str) else None, timeout=timeout))

    @route("/api/job")
    async def _job(request: web.Request, user: dict, body: dict) -> web.Response:
        args = _args(body)
        _check(user, args)
        stdin = body.get("stdin")
        return _result(await api.job_start(*args, stdin=stdin if isinstance(stdin, str) else None))

    @route("/api/job/status")
    async def _job_status(request: web.Request, user: dict, body: dict) -> web.Response:
        job_id = str(body.get("id") or "")
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", job_id):
            raise _bad("id задачи")
        offset = body.get("offset") or 0
        return _result(await api.job_status(job_id, int(offset) if str(offset).isdigit() else 0))

    # ── Клиенты: то, что знает только бот ──
    @route("/api/clients")
    async def _clients(request: web.Request, user: dict, body: dict) -> web.Response:
        r = await api.call("clients", "list")
        if not r.ok:
            return _result(r)
        rows = r.data if isinstance(r.data, list) else []
        route_ = await cls.active_route()
        notes = store.notes()
        for c in rows:
            raw = notes.get(c["name"], "")
            c["note"] = store.strip_tag(raw)
            c["mon"] = store.MONITOR_TAG in raw.lower()
            c["route"] = cls.route_of(c, route_)
            c["exit_choice"] = cls.exit_of(c, route_) if route_.get("kind") == "exits" else None
        info = await api.data("server", "info", default={}) or {}
        return web.json_response({"ok": True, "rows": rows, "route": route_, "profile": info.get("profile") or "",
                                  "sort": store.setting("clients_sort", "activity")})

    @route("/api/client/note")
    async def _note(request: web.Request, user: dict, body: dict) -> web.Response:
        name, text = _name(body), store.strip_tag(str(body.get("text") or "").strip())[:store.NOTE_MAX]
        if store.monitored(name):
            text = f"{text[:store.NOTE_MAX - len(store.MONITOR_TAG) - 1]} {store.MONITOR_TAG}".strip()
        store.set_note(name, text)
        return web.json_response({"ok": True})

    @route("/api/client/mon")
    async def _mon(request: web.Request, user: dict, body: dict) -> web.Response:
        store.set_monitored(_name(body), bool(body.get("on")))
        return web.json_response({"ok": True})

    @route("/api/client/qr")
    async def _qr(request: web.Request, user: dict, body: dict) -> web.Response:
        r = await api.call("client", "conf", _name(body))
        if not r.ok or not isinstance(r.data, dict):
            return _result(r)
        text = r.data.get("text") or ""
        png = media.qr_png(text)
        return web.json_response({"ok": True, "text": text, "file": os.path.basename(r.data.get("file") or ""),
                                  "png": base64.b64encode(png).decode() if png else None})

    @route("/api/client/add")
    async def _add(request: web.Request, user: dict, body: dict) -> web.Response:
        name = _name(body)
        args = ["client", "add", name, f"mimicry={body.get('mimicry') or 'server'}"]
        if body.get("expire"):
            args.append(f"expire={body['expire']}")
        r = await api.call(*args)
        if r.ok:
            store.drop_note(name)       # заметка от удалённого тёзки не наследуется
        return _result(r)

    @route("/api/client/rename")
    async def _rename(request: web.Request, user: dict, body: dict) -> web.Response:
        old, new = _name(body, "old"), _name(body, "new")
        r = await api.call("client", "rename", old, new)
        if r.ok:
            store.rename_note(old, new)
        return _result(r)

    @route("/api/client/del")
    async def _del(request: web.Request, user: dict, body: dict) -> web.Response:
        names = body.get("names")
        if not isinstance(names, list) or not names or not all(isinstance(n, str) and NAME_RE.match(n) for n in names):
            raise _bad("names — список имён")
        r = await (api.call("client", "del", names[0]) if len(names) == 1
                   else api.call("clients", "del", ",".join(names), timeout=600))
        gone = names if len(names) == 1 and r.ok else (r.data if isinstance(r.data, list) else [])
        for n in gone:
            store.drop_note(n)
        return _result(r)

    @route("/api/settings")
    async def _settings(request: web.Request, user: dict, body: dict) -> web.Response:
        if body.get("sort") in cls.SORTS:
            store.set_setting("clients_sort", body["sort"])
        return web.json_response({"ok": True})

    # ── Файлы — в чат с ботом ──
    @route("/api/send")
    async def _send(request: web.Request, user: dict, body: dict) -> web.Response:
        bot, uid, what = request.app["bot"], int(user["id"]), body.get("what")
        if what == "conf":
            ok = await cls.send_config(bot, uid, _name(body))
            return web.json_response({"ok": ok})
        if what == "export":
            r = await api.call("clients", "export")
            if not r.ok or not isinstance(r.data, dict):
                return _result(r)
            await bot.send_document(uid, FSInputFile(r.data["file"]), caption="📦 Все конфиги клиентов")
            return web.json_response({"ok": True})
        if what == "zip":
            names = body.get("names")
            if not isinstance(names, list) or not all(isinstance(n, str) and NAME_RE.match(n) for n in names):
                raise _bad("names — список имён")
            rows = await cls.clients() or []
            files = [c["file"] for c in rows if c["name"] in set(names) and c.get("file")]
            await bot.send_document(uid, BufferedInputFile(media.zip_files(files), filename="awg_clients.zip"),
                                    caption=f"📦 Конфиги: {len(files)}")
            return web.json_response({"ok": True})
        raise _bad("what: conf | export | zip")
