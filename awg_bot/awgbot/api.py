"""api.py — вызовы awg2 api.

Бот ничего не знает о конфигах AWG, туннелях и systemd: всё делает awg2,
а бот зовёт его машинный интерфейс и показывает ответ. Ответ awg2 — одна
строка JSON {"ok", "rc", "data", "log", "error"}; log — тот же текст, что
видит пользователь меню awg2.

Долгие операции (сборка модуля, установка, обновления) идут задачами:
job_start возвращает id, job_status — состояние и новый кусок журнала.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from typing import Any

log = logging.getLogger("awgbot.api")

AWG2 = os.environ.get("AWG2_BIN", "/usr/local/bin/awg2")

# Быстрые команды отвечают за секунды; запас — на медленный диск и apt,
# который awg2 может позвать за недостающей утилитой.
DEFAULT_TIMEOUT = 180


@dataclass
class Result:
    ok: bool
    rc: int = 0
    data: Any = None
    log: str = ""
    error: str = ""

    @property
    def message(self) -> str:
        """Причина неудачи для пользователя."""
        return self.error or (self.log.strip().splitlines() or ["без подробностей"])[-1]


async def call(*args: Any, stdin: str | bytes | None = None,
               timeout: float = DEFAULT_TIMEOUT) -> Result:
    """awg2 api АРГУМЕНТЫ... → Result. Не бросает исключений."""
    argv = [AWG2, "api", *(str(a) for a in args)]
    data = stdin.encode() if isinstance(stdin, str) else stdin
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE if data is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    except FileNotFoundError:
        return Result(False, 127, error=f"awg2 не найден ({AWG2}) — установи AWG Toolza")
    except OSError as e:
        return Result(False, 126, error=f"awg2 не запускается: {e}")
    try:
        out, err = await asyncio.wait_for(proc.communicate(data), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        log.warning("awg2 api %s: нет ответа за %s с", " ".join(argv[2:4]), timeout)
        return Result(False, 124, error=f"awg2 не ответил за {int(timeout)} с")
    lines = out.decode(errors="replace").strip().splitlines()
    try:
        env = json.loads(lines[-1])
    except (IndexError, ValueError):
        tail = (out + err).decode(errors="replace").strip()[-500:]
        log.warning("awg2 api %s: ответ не JSON (rc=%s): %s", args[:2], proc.returncode, tail)
        if "нужен root" in tail:
            return Result(False, proc.returncode or 1, error="Бот запущен не от root — awg2 ему недоступен")
        if "api" in tail and ("Неизвестный аргумент" in tail or "--help" in tail):
            return Result(False, proc.returncode or 1,
                          error="Установленный awg2 не знает команду api — обнови AWG Toolza")
        return Result(False, proc.returncode or 1, log=tail, error="awg2 ответил не JSON")
    return Result(bool(env.get("ok")), int(env.get("rc") or 0), env.get("data"),
                  env.get("log") or "", env.get("error") or "")


async def data(*args: Any, default: Any = None, **kw: Any) -> Any:
    """Только data успешного ответа, иначе default."""
    r = await call(*args, **kw)
    return r.data if r.ok and r.data is not None else default


async def job_start(*args: Any, stdin: str | bytes | None = None) -> Result:
    """Запуск задачи. data.id — её номер."""
    return await call("job", "start", *args, stdin=stdin, timeout=60)


async def job_status(job_id: str, offset: int = 0) -> Result:
    return await call("job", "status", job_id, offset, timeout=60)
