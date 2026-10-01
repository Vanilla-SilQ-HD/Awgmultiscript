"""panel.py — JSON API полной панели Mini App.

Все запросы — POST с JSON (архив бэкапа — телом запроса); подпись Telegram
и доступ проверяет webapp (user_of). Панель делает то же, что бот, и тем же
путём — через awg2 api; сверх него здесь то, что ведёт сам бот: заметки и
мониторинг клиентов, QR, файлы в чат, приём архива бэкапа с телефона. Права —
как в боте: владельческое (удаление всего, удаление бота, сертификат и порт
Mini App) — только владельцам.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
from typing import Any, Callable

from aiogram.types import BufferedInputFile, FSInputFile
from aiohttp import web

from . import __version__, access, admins, api, icons, media, store
from .sections import backup as bk
from .sections import botself
from .sections import clients as cls
from .sections import main as main_menu
from .sections import wgobf

# Команды awg2 api, открытые панели; первое слово — раздел
ALLOWED = {"status", "version", "server", "module", "clients", "client", "mimicry", "diag", "backup",
           "tunnels", "warp", "xray", "t2s", "exits", "cascade", "dns", "wgobf", "update", "log", "bot",
           "cert", "uninstall"}
OWNER_ONLY = (("uninstall",), ("bot", "uninstall"), ("bot", "webapp", "port"), ("cert", "issue"),
              ("cert", "use"), ("cert", "remove"))
NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
MAX_ARGS, MAX_ARG = 32, 4000       # правка всех параметров 3.1 — 23 аргумента
TIMEOUT_MAX = 900
UPLOAD_MAX = 20 * 1024 * 1024       # как у файлов, присланных боту

UserOf = Callable[[web.Request], dict]


def _bad(text: str) -> web.HTTPBadRequest:
    return web.HTTPBadRequest(text=json.dumps({"error": text}, ensure_ascii=False), content_type="application/json")


def _owner(user: dict) -> None:
    if not access.is_owner(int(user["id"])):
        raise web.HTTPForbidden(text='{"error": "только владелец"}', content_type="application/json")


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


_tasks: set[asyncio.Task] = set()       # отложенный перезапуск сервера панели


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
            timeout = float(body.get("timeout") or 120)
        except (TypeError, ValueError):
            timeout = 120.0
        # Отрицательное или NaN сработало бы сразу — и api.call убил бы awg2
        # посреди изменения конфига.
        if not timeout >= 1:
            timeout = 120.0
        timeout = min(timeout, TIMEOUT_MAX)
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
            return web.json_response({"ok": ok, "error": "" if ok else "Конфига нет — подробности в чате с ботом"})
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
        if what == "backup":
            # Только бэкап из списка на сервере: иначе это чтение любого файла
            path = str(body.get("path") or "")
            rows = await api.data("backup", "list", default=[]) or []
            if not path or path not in {b.get("path") for b in rows}:
                raise _bad("такого бэкапа на сервере нет")
            data, name = await asyncio.to_thread(bk.pack, path)
            await bot.send_document(uid, BufferedInputFile(data, filename=name),
                                    caption="💾 В бэкапе приватные ключи — храни как пароль")
            return web.json_response({"ok": True})
        if what in ("wgobf", "wgobf_zip"):
            send = wgobf.send_bundle if what == "wgobf" else wgobf.send_archive
            await send(bot, uid, _name(body))
            return web.json_response({"ok": True})
        raise _bad("what: conf | export | zip | backup | wgobf | wgobf_zip")

    # ── WG + обфускатор: комплект клиента на экран ──
    @route("/api/wgobf/bundle")
    async def _wgobf_bundle(request: web.Request, user: dict, body: dict) -> web.Response:
        r = await api.call("wgobf", "bundle", _name(body))
        if not r.ok or not isinstance(r.data, dict):
            return _result(r)
        files = {f["name"]: f["path"] for f in r.data.get("files") or []}
        direct = _read(files.get("wg-direct.conf", ""))
        png = media.qr_png(direct) if direct else None
        return web.json_response({"ok": True, "link": (r.data.get("phobos") or "").strip(),
                                  "conf": _read(files.get("phobos.conf", "")), "direct": direct,
                                  "png": base64.b64encode(png).decode() if png else None})

    # ── Бот: админы, оформление, сервер панели ──
    @route("/api/bot/info")
    async def _bot_info(request: web.Request, user: dict, body: dict) -> web.Response:
        from . import webapp                                # webapp сам подключает панель
        owner = access.is_owner(int(user["id"]))
        st = await api.data("bot", "status", default={}) or {}
        srv = webapp.SERVER
        d: dict[str, Any] = {
            "ok": True, "version": __version__, "owner": owner, "proxy": st.get("proxy") or "",
            "owners": len(access.owners()), "invited": len(admins.invited_ids()),
            "icons": {"active": icons.active(), "pack": icons.pack(), "count": len(icons.mapping()),
                      "total": len(icons.TEMPLATE), "default": icons.DEFAULT_PACK},
            "webapp": {"running": srv.running, "url": srv.url, "error": srv.error, "port": webapp.configured_port()},
        }
        if owner:
            d["admins"] = {"owners": sorted(access.owners()), "pending": admins.pending_invites(),
                           "invited": [{"uid": a.uid, "username": a.username, "added_at": a.added_at}
                                       for a in admins.list_invited()]}
        return web.json_response(d)

    @route("/api/bot/invite")
    async def _invite(request: web.Request, user: dict, body: dict) -> web.Response:
        _owner(user)
        token, exp = admins.create_invite(int(user["id"]))
        if token is None:
            raise _bad(str(exp))
        me = await request.app["bot"].me()
        return web.json_response({"ok": True, "expires": exp,
                                  "link": f"https://t.me/{me.username}?start={admins.INVITE_PREFIX}{token}"})

    @route("/api/bot/admin/del")
    async def _admin_del(request: web.Request, user: dict, body: dict) -> web.Response:
        _owner(user)
        uid = str(body.get("uid") or "")
        if not uid.isdigit():
            raise _bad("uid — число")
        ok, msg = admins.remove(int(uid), removed_by=int(user["id"]))
        return web.json_response({"ok": ok, "message": msg, "error": "" if ok else msg})

    @route("/api/bot/invites/revoke")
    async def _revoke(request: web.Request, user: dict, body: dict) -> web.Response:
        _owner(user)
        return web.json_response({"ok": True, "revoked": admins.revoke_invites()})

    @route("/api/bot/icons")
    async def _icons(request: web.Request, user: dict, body: dict) -> web.Response:
        """Иконки custom emoji в боте: включить набор и проверить на деле —
        пробным сообщением в чат (не показал Telegram — middleware выключит)."""
        _owner(user)
        bot, uid, action = request.app["bot"], int(user["id"]), body.get("action")
        if action == "off":
            icons.disable("выключены владельцем")
            return web.json_response({"ok": True, "active": False})
        if action == "pack":
            m = botself.PACK_RE.search(str(body.get("name") or icons.DEFAULT_PACK).strip())
            if not m:
                raise _bad("нужна ссылка вида t.me/addemoji/ИМЯ")
            name, mapping = await botself.pack_icons(bot, m.group(1))
            if not mapping:
                raise _bad(name)
        elif action == "on":
            name, mapping = icons.pack(), icons.mapping()
            if not mapping:
                raise _bad("набор иконок ещё не выбран")
        else:
            raise _bad("action: pack | on | off")
        icons.save(name, mapping, True)
        sample = [e for e in icons.TEMPLATE if e in mapping][:8]
        await bot.send_message(uid, "🎨 Проверка иконок из панели: " + " ".join(sample))
        have, miss = icons.coverage(mapping)
        return web.json_response({"ok": True, "active": icons.active(), "pack": name, "have": have, "miss": miss})

    @route("/api/bot/menu")
    async def _menu(request: web.Request, user: dict, body: dict) -> web.Response:
        """Главное меню бота новым сообщением в самый низ чата."""
        await main_menu.send_menu(request.app["bot"], int(user["id"]))
        return web.json_response({"ok": True})

    @route("/api/bot/webapp/restart")
    async def _webapp_restart(request: web.Request, user: dict, body: dict) -> web.Response:
        """Сервер панели — заново (новый сертификат, порт, удаление): ответ
        уходит сейчас, перезапуск — через секунду."""
        _owner(user)
        from . import webapp
        bot = request.app["bot"]

        async def later() -> None:
            await asyncio.sleep(1)
            await webapp.SERVER.start(bot)
        task = asyncio.get_running_loop().create_task(later())
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
        return web.json_response({"ok": True})

    # ── Архив бэкапа с телефона: тело запроса — сам файл ──
    async def _upload(request: web.Request) -> web.Response:
        user_of(request)
        if (request.content_length or 0) > UPLOAD_MAX:
            raise _bad("файл больше 20 МБ")
        data = bytearray()
        async for chunk in request.content.iter_chunked(1 << 16):
            data += chunk
            if len(data) > UPLOAD_MAX:
                raise _bad("файл больше 20 МБ")
        if not data:
            raise _bad("пустой файл")
        path = await asyncio.to_thread(bk.save_upload, bytes(data))
        return web.json_response({"ok": True, "path": str(path)})

    app.router.add_post("/api/backup/upload", _upload)
