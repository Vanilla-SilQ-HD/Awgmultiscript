<div align="center">

# **AWG Toolza**

**Менеджер AmneziaWG 2.0 / 3.1** — одной командой, из консоли или из Telegram.<br>
3 уровня обфускации, 9 профилей мимикрии (QUIC / cURL QUIC+ECH / DNS / STUN / WebRTC / SIP / NTP / RTP / SSDP), локальный CPS-генератор на базе payloadGen, **Warp туннель Cloudflare**, DPI-тест.

<br>

[![License: MIT](https://img.shields.io/badge/License-MIT-ffffff?style=flat-square&labelColor=000000)](https://opensource.org/licenses/MIT)
[![Platform](https://img.shields.io/badge/Ubuntu%2024%20%2F%20Debian%2012%2B-E95420?style=flat-square&logo=ubuntu&logoColor=white)](https://ubuntu.com/)
[![Protocol](https://img.shields.io/badge/AWG-2.0%20%2F%203.1-00d4ff?style=flat-square)](#)
[![Version](https://img.shields.io/badge/version-v1.0.0-ff6b00?style=flat-square)](#)

<br>

[![Boosty](https://img.shields.io/badge/Boosty-Поддержать-F15F2C?style=for-the-badge&logo=boost&logoColor=white)](https://boosty.to/awgtoolza/donate)
[![YooMoney](https://img.shields.io/badge/YooMoney-Поддержать-8B3FFC?style=for-the-badge&logo=yandex&logoColor=white)](https://yoomoney.ru/to/4100119521619579)

</div>

---

## Быстрый старт

```bash
sudo curl -fsSL https://raw.githubusercontent.com/genaRijoff/awg-multi-script/main/awg2.sh -o /usr/local/bin/awg2 && sudo chmod +x /usr/local/bin/awg2 && sudo awg2
```

Запуск в любой момент:
```bash
sudo awg2
```

История версий — [CHANGELOG.md](CHANGELOG.md).

### Канал обновлений

По умолчанию скрипт обновляется из основного репозитория (`pumbaX/awg-multi-script`) —
это стабильный канал. Ранние сборки живут в бета-репозитории
(`genaRijoff/awg-multi-script`): `sudo awg2` → **Обновление** → **Бета-канал**. Выбор сохраняется в `/var/lib/awg2/channel` и переживает обновление;
вернуться на стабильный канал можно там же (если бета-версия окажется новее, обновление
предложит откат). Разовый запуск на бета-канале без сохранения:
`AWG2_UPDATE_CHANNEL=beta sudo -E awg2`.

Канал влияет и на Telegram-бота: установка и обновление бота берут его код из
того же репозитория.

---

## Требования к клиентам

Версия протокола задаётся на **весь сервер**, поэтому клиент обязан её понимать:

| версия сервера | что нужно клиенту |
|---|---|
| AWG 2.0 | любой клиент AmneziaWG |
| AWG 3.1 | **AmneziaVPN 5.0.1.5 или новее** |

Клиент старше 5.0.1.5 не знает ключей `RandomTrailers` и `DisableCookies` и
отказывается импортировать конфиг с незнакомым ключом **целиком** — не
«пропускает строку», а отвергает весь файл. Если среди ваших клиентов есть
те, кого обновить нельзя, поднимите им отдельный сервер на 2.0.

Отдельно: `HeaderProtectionKey`, `S1`-`S4`, `H1`-`H4` и `RandomTrailers`
обязаны совпадать у сервера и клиента побайтово. Расхождение проявляется
молчанием — в `awg show` просто никогда не появится `latest handshake`, без
единой строки в логах.

---

## Модуль ядра и amneziawg-tools

`awg2` собирает модуль `amneziawg` (DKMS) и `amneziawg-tools` из исходников апстрима
и следит за ними сам: **Сервер → Модуль ядра и утилиты** показывает, что стоит, под
какие ядра собрано и есть ли новые теги, и умеет:

- обновить модуль до последнего тега или выбрать тег из списка;
- обновить `amneziawg-tools`;
- пересобрать модуль под все установленные ядра (после обновления ядра);
- перезагрузить модуль без перезагрузки сервера;
- откатиться из резервной копии исходников.

Перед заменой сборки делается резервная копия исходников и пробная компиляция
новых: если новый код не собирается под это ядро, старая сборка остаётся на месте.
Перезагрузка модуля кладёт туннели на несколько секунд; если SSH идёт через сам
туннель, перезапуск уходит в `systemd-run`, чтобы не потерять сервер. Для AWG 3.1
нужен модуль и tools с поддержкой 3.1 — переход на 3.1 (**Сервер → Протокол**)
предложит обновить их сам.

---

## Туннели: Xray, tun2socks, AWG-exit

Раздел **Туннели и DNS** — Warp, шифрованный DNS, каскад портов, плюс:

- **Xray** — outbounds из ссылок `vless://` / `vmess://` / `hysteria2://`,
  балансировка (random / roundRobin / leastPing / leastLoad), выбор того, кто
  из клиентов идёт в туннель. Трафик уходит через интерфейс `xray0`.
  **РФ-сайты напрямую** (Туннели → Xray): `.ru/.su/.рф`, сервисы «только из РФ»
  и РФ-IP идут с сервера мимо туннеля — для сервера в РФ с выходом за границу.
  Базы runetfreedom обновляются раз в неделю.
- **tun2socks** — весь трафик AWG-клиентов в готовый SOCKS5
  (`awg-tun2socks.service`)
- **AWG exit-ноды** — каскад через другие AWG-серверы, ECMP-балансировка,
  можно назначить клиенту конкретную ноду (Туннели → AWG exit-ноды → Клиенты):
  один выходит через одну страну, другой — через другую

Одновременно может быть активен только один из Warp / Xray / tun2socks / exit —
скрипт проверяет это при включении каждого.

Перед тем как увести клиентов в туннель, скрипт проверяет, что трафик по нему
реально ходит: не ходит — туннель не включается и маршруты клиентов не
меняются. Если что-то всё же пошло не так, **Туннели → Аварийный сброс** гасит
все туннели и возвращает клиентов на прямой маршрут, ничего не удаляя из
настроек.

Про `xray0`: апстримный XTLS/Xray-core не умеет inbound `tun`, поэтому скрипт
спрашивает у самого бинаря (`xray run -test`), есть ли TUN-вход. Если нет —
Xray отдаёт SOCKS5 на `127.0.0.1:10808`, а `xray0` поднимает поверх него
tun2socks. Снаружи разницы нет; режим виден в статусе туннеля.

Ссылка `hysteria2://` принимается только сборкой Xray с поддержкой этого
протокола — в апстримном XTLS/Xray-core её нет. Скрипт проверяет каждый
outbound на самом бинаре до записи в конфиг и не даёт положить туда то, что
Xray не примет. Разобраться с уже сломанным конфигом помогает
**Туннели → Xray → Диагностика** — покажет причину и предложит убрать
неподдерживаемые outbounds.

Туннели переживают перезагрузку: WARP, Xray, tun2socks и exit-ноды живут в
постоянных юнитах systemd и восстанавливают маршруты клиентов сами.

CLI:

```bash
sudo awg2 --auto                  # неинтерактивная установка сервера и client1
sudo awg2 --add-client имя        # добавить клиента
sudo awg2 --tunnel xray restart   # warp | xray | tun2socks | exits | dns: up | down | restart
sudo awg2 --status                # сводка состояния
sudo awg2 api help                # JSON-интерфейс (им пользуется Telegram-бот)
sudo awg2 --help                  # список аргументов
```

`AUTOINSTALL=1` — то же, что `--auto`.


### Бот не подключается к Telegram

На части серверов (чаще всего в РФ) провайдер блокирует адрес, который DNS
отдаёт для `api.telegram.org` — а отдаёт он ровно один. Переключиться не на
что, и бот молча не отвечает.

С версии 2.2.3 бот сам подмешивает к ответу DNS известные адреса Telegram и
берёт тот, что отвечает. Настройки для этого не нужно.

Если режут не по IP, нужен прокси: **Telegram-бот → Прокси до Telegram** (в меню
awg2 или в самом боте). Бот сам найдёт все выходы сервера — SOCKS Xray, апстрим tun2socks, WARP, AWG
Exit-ноды, TUN-интерфейсы — проверит каждый до Telegram и перезапустит бота.
Подойдёт и любой сторонний SOCKS5 или HTTP-прокси. Туннели без SOCKS бот
использует через `iface://<интерфейс>` (привязка сокетов, как `curl --interface`).

Если туннель выключен (например, аварийным сбросом), прокси на `127.0.0.1`
исчезает. Бот это переживает: не достучавшись до прокси, он идёт напрямую с
запасными адресами и пишет причину в лог. Когда туннель подняли обратно —
`systemctl restart awg-bot`.

Руками — строка в `/etc/awg-bot.conf`, затем `systemctl restart awg-bot`:

```
BOT_PROXY=socks5://127.0.0.1:10808
# или через туннель:
BOT_PROXY=iface://warp0
```

Проверить, что запасные адреса подключились:

```
journalctl -u awg-bot -n 50 | grep 'Запасные адреса'
```

Строка `Запасные адреса Telegram подключены (5 шт.)` — всё на месте.

---

## WG + обфускатор (как Phobos)

Пункт **WG + обфускатор** главного меню — второй сервер рядом с AWG: обычный WireGuard
(`wgobf0`) за [wg-obfuscator](https://github.com/ClusterM/wg-obfuscator)
v1.6. Весь трафик клиента маскируется под **STUN** (видеозвонок) или
XOR-обфусцируется. Снаружи виден только порт обфускатора: порт WireGuard
закрыт для всего, кроме самого обфускатора.

- AWG, его клиенты и туннели (Warp / Xray / tun2socks / exit) не
  затрагиваются: своя подсеть, свои правила iptables (метка `awg-wgobf`),
  клиенты `wgobf0` всегда выходят напрямую через сервер.
- Обфускатор собирается из исходников закреплённого тега (коммит сверяется).
- Клиенту выдаётся комплект в `/root/wgobf/<имя>/`: `wg.conf`,
  `obfuscator.conf`, `install-linux.sh` (Debian/Ubuntu одной командой) и
  памятка для Windows / macOS / OpenWrt / Android.
- Keenetic с [AWG Manager](https://github.com/hoaxisr/awg-manager): вкладка
  «Phobos» — ссылка `phobos://` одной вставкой (`phobos-link.txt`), или вкладка
  «ClusterM» — поля руками. Всё расписано в `keenetic.txt` комплекта.
- Клиенты Phobos совместимы, пока у них выключены `obfuscate-bytes` и
  маскировка `MEDIA` (проверено).
- Клиенту нужен обфускатор на устройстве: роутер, Linux, Windows, macOS.
  Для iOS и телефонов без обфускатора есть опция «пускать клиентов без
  обфускатора» — такие подключаются обычным WireGuard (`wg-direct.conf`),
  но их трафик DPI видит как WireGuard.
- Смена ключа обфускатора — **Настройки → Сменить ключ** (комплекты перевыпускаются сами).
- В Telegram-боте — тот же раздел «🛡 WG + обфускатор»: установка, клиенты,
  комплект одним архивом и ссылка `phobos://`, настройки, смена ключа.
- Без меню: `awg2 --wgobf add|del|bundle ИМЯ`, `awg2 --wgobf rotate-key|restart`.
- **Бэкапы** и **Удаление → Удалить всё** режим учитывают.

---

## 🤖 Telegram-бот

Бот повторяет меню `awg2` целиком: те же девять разделов и те же пункты, кнопками
в два столбца; пояснения к пунктам — в тексте экрана. Установка компонентов, создание сервера, клиенты (конфиг файлом и
QR, сроки, мимикрия, туннели клиента), протокол 2.0/3.1, модуль ядра, диагностика
и журналы, бэкапы (скачать, восстановить из присланного архива), WARP, Xray,
tun2socks, exit-ноды, каскад, шифрованный DNS, WG + обфускатор, обновление и
удаление — всё доступно со смартфона.

- Всю работу делает `awg2 api`: бот не хранит своей логики AWG, поэтому ведёт
  себя ровно как меню.
- Долгие операции (сборка модуля, установка, обновления) идут задачами: бот
  показывает живой журнал в сообщении и итог. Задача переживает перезапуск бота
  — так бот обновляет и перезапускает сам себя.
- Доступ: владельцы (`ADMIN_ID` в `/etc/awg-bot.conf`) и приглашённые админы —
  одноразовая ссылка на 15 минут. Списком админов управляет только владелец.
- Мониторинг: `#ping` в заметке клиента (или кнопка «Мониторинг активности») —
  бот сообщит, когда клиент пропал и когда вернулся. Об истечении сроков пишет
  таймер `awg2`, даже когда бот остановлен.

**Установка:** `sudo awg2` → **Telegram-бот** → Установить. Или вручную:

```bash
sudo bash -c 'curl -fsSL https://raw.githubusercontent.com/pumbaX/awg-multi-script/main/awg-bot-install.sh -o /tmp/awg-bot-install.sh && bash /tmp/awg-bot-install.sh'
```

Установщик спросит:
1. **Bot Token** — у [@BotFather](https://t.me/BotFather): `/newbot` → имя → токен
2. **Telegram ID** — свой ID (узнать у [@userinfobot](https://t.me/userinfobot))

Бот работает службой `awg-bot.service` и поднимается сам после перезагрузки.
Ему нужен `awg2` версии 1.0 или новее.

---

## Импорт на клиенте

[**AmneziaVPN**](https://amnezia.org) (Android / iOS / macOS / Windows / Linux):
- **QR** — Клиенты → Показать QR, сканируй с терминала (или QR от бота)
- **Текст** — Клиенты → Показать конфиг для больших конфигов (с I1–I5) → копируй в буфер
- **Файл** — `Добавить туннель → Из файла` → передай `/root/<имя>_awg2.conf` (AWG 2.0) или `_awg3.conf` (3.x) через scp

[**AmneziaWG**](https://github.com/amnezia-vpn/amneziawg-windows-client) — официальное приложение протокола AmneziaWG:
- [**Android**](https://play.google.com/store/apps/details?id=org.amnezia.awg)
- [**iOS**](https://apps.apple.com/app/amneziawg/id6478942365)
- [**Windows**](https://github.com/amnezia-vpn/amneziawg-windows-client/releases/tag/2.0.0)

[**Keenetic**](https://docs.amnezia.org/documentation/instructions/keenetic-os-awg) — KeeneticOS 4.x+ или AWG Manager на Entware


---

## Проверка конфига

Проверить свой `.conf` на валидность, DPI-стойкость и оптимальность параметров можно через [AWG Analyzer](https://pumbax.github.io/awg-analyzer/) — полностью локальный JS-инструмент.

---

## Разработка

Исходники `awg2` — в `src/` (модули `src/lib/*.sh`, встроенный Python — `src/py/`).
Один файл для установки собирает `./build.sh` → `dist/awg2.sh` (`./build.sh awg2.sh` — в корень
репозитория, откуда его берут установка и самообновление). Бот — `awg_bot/`.

Тесты без root и сети (песочница — `tests/sandbox.py`):

```bash
./build.sh
python3 tests/test_toolza.py      # awg2: параметры, конфиги, helper, служебные скрипты, API
python3 tests/test_cps.py         # генератор I1-I5
python3 tests/test_bot.py         # бот на живом диспетчере против awg2 api (нужен aiogram)
python3 tests/test_admins.py && python3 tests/test_net.py
```

---

## Поддержать

**Boosty:** https://boosty.to/awgtoolza/donate

**YooMoney:** https://yoomoney.ru/to/4100119521619579

| Сеть | Адрес |
|---|---|
| USDT TRC20 | `TN2rQAsGNHQr8wnneKRD14UMX629D2Ca5q` |
| USDT ERC20 | `0x721845234eeC44e0a9BaE78402965828C1bc6c57` |
| USDT TON | `UQCwj-RY2a4BH7sIDDeLb77XRaPDq0mb1FVwyC4UaOGbLMYy` |
| TON | `UQCdQtJO4CF0Lyeb93X2zdeWeAcDJ-ieBC3AaL7LIqWfMBg3` |

---

<div align="center">

*Отдельная благодарность [AWG-Manager](https://t.me/awgmanager)*

<br>

*Сообщество [AWG-Toolza](https://t.me/awgToolza)*

**AWG Toolza v1.0.0** · MIT License

</div>
