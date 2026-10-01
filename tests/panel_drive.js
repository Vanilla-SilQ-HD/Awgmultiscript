const { chromium } = require("playwright");
const fs = require("fs");
const say = (...a) => fs.appendFileSync(process.argv[4] + "/run.log", a.join(" ") + "\n");
const [port, initData, out, theme, profile, sandboxRoot] = process.argv.slice(2);
(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 390, height: 844 }, deviceScaleFactor: 2 });
  await ctx.route(/telegram\.org/, (r) => r.abort());
  await ctx.addInitScript(({ initData, theme }) => {
    const noop = () => {};
    window.__log = [];
    window.Telegram = { WebApp: {
      initData, colorScheme: theme, ready: noop, expand: noop, onEvent: noop, close: () => window.__log.push("close"),
      BackButton: { show: () => window.__log.push("back:show"), hide: () => window.__log.push("back:hide"), onClick: (f) => { window.__back = f; } },
      HapticFeedback: { notificationOccurred: (t) => window.__log.push("haptic:" + t) },
      showConfirm: (t, cb) => { window.__log.push("confirm:" + t); cb(true); },
      showAlert: (t) => { window.__log.push("alert:" + t); },
    } };
  }, { initData, theme });
  const page = await ctx.newPage();
  page.setDefaultTimeout(15000);
  const errors = [];
  page.on("pageerror", (e) => errors.push("pageerror: " + e));
  page.on("console", (m) => { if (m.type() === "error" && !/telegram\.org|ERR_FAILED/.test(m.text())) errors.push("console: " + m.text()); });
  const base = `https://127.0.0.1:${port}/`;
  const shot = async (name) => { await page.waitForTimeout(500); await page.screenshot({ path: `${out}/${name}.png`, fullPage: true }); };
  const noNull = async () => {
    const bad = await page.evaluate(() => [...document.querySelectorAll("#app, #app *")].some((el) =>
      [...el.childNodes].some((n) => n.nodeType === 3 && /^(null|undefined|false)$/.test(n.textContent.trim()))));
    if (bad) throw new Error("на экране текст null/undefined");
  };
  // Тот же адрес браузер навигацией не считает — тогда перезагружаем страницу
  const nav = async (hash, sel = "h1") => {
    if (page.url() === base + "#" + hash) await page.reload({ waitUntil: "domcontentloaded" });
    else await page.goto(base + "#" + hash, { waitUntil: "domcontentloaded" });
    await page.waitForSelector(sel); await page.waitForTimeout(300); await noNull();
  };
  // Подсказка прошлого шага не должна сойти за итог этого
  const step = async (name, fn) => {
    await page.evaluate(() => document.querySelectorAll(".toast").forEach((t) => t.remove()));
    try { await fn(); await noNull(); say("OK  ", name); } catch (e) { say("FAIL", name, String(e).split("\n")[0]); errors.push(name + ": " + e); }
  };

  const alerts = async () => (await page.evaluate(() => window.__log)).filter((l) => l.startsWith("alert:"));
  const expectAlert = async (text, fn) => {
    const before = (await alerts()).length;
    await fn();
    await page.waitForTimeout(300);
    const got = (await alerts()).slice(before);
    if (!got.some((a) => a.includes(text))) throw new Error(`ждали окно «${text}», было: ${JSON.stringify(got)}`);
    // Ожидаемые окна — не ошибки: из итогового списка их убираем
    await page.evaluate(() => { window.__log = window.__log.filter((l) => !l.startsWith("alert:")); });
  };

  await step("главная", async () => {
    await nav("/", ".tile");
    const t = await page.evaluate(() => document.documentElement.dataset.theme);
    if (t !== theme) throw new Error(`тема ${t}, а Telegram — ${theme}`);
    await page.waitForSelector(".top .ver");
    if (await page.locator("h1").count()) throw new Error("на главной остался заголовок");
    if (await page.locator(".top .chan").count()) throw new Error("плашка «бета» на стабильном канале");
    await shot("01-home");
  });

  if (profile === "none") {
    // Сервера ещё нет: мастер создания целиком, первый клиент — сразу QR
    await step("главная без сервера", async () => {
      await page.waitForSelector("text=не создан");
      await page.click(".tile >> text=Сервер"); await page.waitForSelector("text=Создать сервер"); await shot("11-server-none");
    });
    await step("мастер создания", async () => {
      await page.click("button:has-text('Создать сервер')");
      await page.waitForSelector("h1 >> text=Создание сервера");
      await page.click(".chip >> text=Мощный"); await page.waitForSelector(".chip >> text=Цепочка I1-I5");
      await page.waitForSelector("select >> nth=0");
      await shot("12-create-pro");
      await page.click(".chip >> text=AmneziaVPN");
      await page.click(".chip >> text=Пакет I1 (DNS)");
      await page.fill("input[placeholder^='случайная']", "10.66.1.7/25");
    });
    await step("мастер: неверная подсеть", async () => {
      await expectAlert("сеть /24", () => page.click("button.btn-primary:has-text('Создать сервер')"));
    });
    await step("мастер: сервер создан", async () => {
      await page.fill("input[placeholder^='случайная']", "10.66.1.7/24");
      await page.fill("input[placeholder='случайное']", "first");
      await page.click("button.btn-primary:has-text('Создать сервер')");
      await page.waitForSelector("text=Первый клиент", { timeout: 90000 });
      await shot("13-created");
      await page.click("text=Конфиг и QR");
      await page.waitForSelector("img.qr, .card.muted");
    });
    await step("обфускатор не установлен", async () => {
      await nav("/wgobf", "button:has-text('Установить')");
      await page.waitForSelector("text=STUN · видеозвонок");
      await shot("14-wgobf-install");
    });
    await step("сервер после создания", async () => {
      await nav("/server", "text=Endpoint");
      await page.waitForSelector("text=10.66.1.0/24");
    });
    const log = await page.evaluate(() => window.__log);
    say("ALERTS", JSON.stringify(log.filter((l) => l.startsWith("alert:"))));
    say("ERRORS", JSON.stringify(errors));
    await browser.close();
    return;
  }
  await step("список", async () => { await nav("/clients", "[data-name]"); await page.waitForSelector(".sgrid"); await shot("02-clients"); });
  await step("поиск", async () => {
    await page.fill("input[type=search]", "анн");
    const n = await page.locator("[data-name]").count();
    if (n !== 1) throw new Error("ожидался 1 клиент по заметке, найдено " + n);
    await page.fill("input[type=search]", "");
  });
  await step("вид списком", async () => {
    await page.click(".seg button >> nth=1");
    await page.waitForSelector(".card.list [data-name=alice]");
    await page.click(".seg button >> nth=0");
    await page.waitForSelector(".ecard[data-name=alice]");
  });
  await step("карточка", async () => { await page.click("[data-name=alice] .name"); await page.waitForSelector("text=Мониторинг активности"); await shot("03-card"); });
  await step("мониторинг", async () => {
    await page.click("text=Мониторинг активности");
    await page.waitForSelector(".switch.on");
  });
  await step("QR", async () => { await page.click("text=Конфиг и QR"); await page.waitForSelector("img.qr"); await shot("04-qr"); });
  await step("в чат", async () => { await page.click("text=Отправить файл в чат"); await page.waitForSelector(".toast"); });
  await step("срок", async () => {
    await nav("/client/alice", "text=Срок");
    await page.click(".actions button:has-text('Срок')"); await page.waitForSelector(".sheet"); await shot("05-expire-sheet");
    await page.click(".sheet >> text=7 дней"); await page.waitForSelector(".sgrid >> text=/^6д/");
  });
  await step("новый клиент", async () => {
    await nav("/add", "input");
    await page.fill("input", "carol");
    await page.selectOption("select", "+1d");
    await shot("06-add");
    await page.click("text=Создать");
    await page.waitForURL(/#\/client\/carol\/qr/); await page.waitForSelector("img.qr, .card.muted");
  });
  await step("массовое создание", async () => {
    await nav("/bulk", "input");
    await page.fill("input >> nth=0", "t");
    await page.fill("input[type=number]", "2");
    await page.click("text=Создать");
    await page.waitForSelector("text=Создано: 2", { timeout: 60000 });
    await shot("07-bulk-done");
  });
  await step("выбрать и удалить", async () => {
    await nav("/clients", "[data-name]");
    await page.click(".toolbar button:has-text('Выбрать')");
    await page.click("[data-name=t-001] .name"); await page.click("[data-name=t-002] .name");
    await shot("08-select");
    await page.click(".bar >> text=Удалить");
    await page.waitForSelector(".toast >> text=Удалено: 2");
    await page.waitForSelector("[data-name]");
    if (await page.locator("[data-name=t-001]").count()) throw new Error("t-001 остался");
  });
  await step("мимикрия", async () => {
    await nav("/client/alice/mimicry", ".item");
    await page.waitForSelector(".item:has-text('Как у сервера') .sub");
    await shot("09-mimicry");
  });
  await step("удалить клиента", async () => {
    await nav("/client/carol", "text=Удалить клиента");
    await page.click("text=Удалить клиента");
    await page.waitForURL(/#\/clients$/);
  });

  // ── Сервер ──
  await step("сервер", async () => { await nav("/server", "text=Endpoint"); await page.waitForSelector("text=Модуль ядра"); await shot("20-server"); });
  await step("рестарт awg0", async () => { await page.click(".ecard button:has-text('Рестарт')"); await page.waitForSelector(".toast"); });
  await step("протокол", async () => { await nav("/server/proto", "text=Перейти на 3.1"); await shot("21-proto"); });
  await step("параметры AWG", async () => {
    await nav("/server/params", "input[data-key=Jc]");
    await shot("21b-params");
    await page.fill("input[data-key=Jc]", "7");
    await page.waitForSelector("input[data-key=Jc].chg");
    await page.waitForSelector(".bar button.btn-primary:not([disabled])");
    // S1 у сервера случайный (профиль none создаёт свой) — совпадение длин считаем от него
    const s1 = Number(await page.inputValue("input[data-key=S1]"));
    const s2 = await page.inputValue("input[data-key=S2]");
    await page.fill("input[data-key=S2]", String(s1 + 56));
    await page.waitForSelector(".card.bad >> text=S1 и S2");
    await page.waitForSelector(".bar button.btn-primary[disabled]");
    if (/\bnull\b/.test(await page.textContent("#app"))) throw new Error("в форме «null»");
    await shot("21c-params-error");
    await page.fill("input[data-key=S2]", s2);
    const s4 = await page.inputValue("input[data-key=S4]");
    await page.fill("input[data-key=S4]", s4 === "20" ? "21" : "20");
    await page.waitForSelector("input[data-key=S4].chg");
    await page.waitForSelector(".bar button.btn-primary:not([disabled])");
    await page.click(".bar button.btn-primary");
    await page.waitForSelector(".sheet >> text=Клиентам нужны новые конфиги");
    await page.click(".sheet button:has-text('Все конфиги архивом')");
    await page.waitForSelector(".toast >> text=Архив всех конфигов");
    await page.waitForFunction(() => {
      const jc = document.querySelector("input[data-key=Jc]");
      return jc && jc.value === "7" && !document.querySelector("input.chg");
    });
    // Перед записью — авто-бэкап; убираем его, чтобы раздел «Бэкапы» начинался с пустого списка
    const dir = `${sandboxRoot}/awg_backup`;
    const auto = fs.existsSync(dir) ? fs.readdirSync(dir).filter((f) => f.startsWith("auto_params_")) : [];
    if (!auto.length) throw new Error("нет авто-бэкапа перед записью параметров");
    auto.forEach((f) => fs.unlinkSync(`${dir}/${f}`));
    if (!fs.readdirSync(dir).length) fs.rmdirSync(dir);
  });
  await step("endpoint", async () => {
    await nav("/server/endpoint", "input");
    await expectAlert("vpn.example.com", async () => { await page.fill("input", "bad"); await page.click("text=Сохранить домен"); });
    await page.fill("input", "vpn.example.com");
    await page.click("text=Переписать в выданных конфигах");
    await shot("22-endpoint");
    await page.click("text=Сохранить домен");
    await page.waitForSelector(".toast >> text=vpn.example.com");
    await nav("/server", "text=Endpoint");
    await page.waitForSelector("text=vpn.example.com");
  });
  await step("модуль ядра", async () => {
    await nav("/server/module", "text=Ядро");
    await page.click("summary"); await page.waitForSelector("details[open] pre");
    await shot("23-module");
  });
  await step("журнал", async () => { await nav("/log/manager", "pre"); });

  // ── Туннели и DNS ──
  await step("туннели", async () => {
    await nav("/tunnels", ".ecard");
    const n = await page.locator(".ecard").count();
    if (n !== 6) throw new Error("ждали 6 карточек (4 туннеля, каскад, DNS), есть " + n);
    await page.waitForSelector(".sgrid >> text=Exit-ноды");
    await shot("30-tunnels");
  });
  await step("WARP", async () => { await page.click("[data-name=WARP] .name"); await page.waitForSelector("text=Бэкенд"); await shot("31-warp"); });
  await step("клиенты в WARP", async () => {
    await nav("/tunnels/warp/clients", ".item");
    await page.click(".item >> text=alice");
    await page.waitForSelector(".item:has-text('alice') >> text=напрямую");
    await shot("32-warp-clients");
  });
  await step("Xray", async () => { await nav("/tunnels/xray", "text=Установить"); await shot("33-xray"); });
  await step("tun2socks", async () => {
    await nav("/tunnels/tun2socks", "input");
    await expectAlert("IP:ПОРТ", async () => { await page.fill("input", "нет"); await page.click("text=Включить"); });
    await shot("34-t2s");
  });
  await step("exit-ноды", async () => {
    await nav("/tunnels/exits", "text=Маршруты");
    await page.waitForSelector(".item >> text=n1");
    await shot("35-exits");
  });
  await step("выход клиента", async () => {
    await nav("/tunnels/exits/clients", ".item");
    await page.click(".item >> text=alice");
    await page.click(".sheet >> text=Нода n1");
    await page.waitForSelector(".item:has-text('alice') >> text=нода n1");
    await shot("36-exit-pick");
  });
  await step("каскад: добавить", async () => {
    await nav("/tunnels/cascade/add", "input");
    await page.fill("input[placeholder='51820']", "5555");
    await page.fill("input[placeholder='5.6.7.8']", "5.6.7.8");
    await page.fill("input[placeholder^='например']", "de-server");
    await shot("37-cascade-add");
    await page.click("button:has-text('Добавить')");
    await page.waitForSelector(".toast >> text=UDP 5555 → 5.6.7.8:5555");
    await nav("/tunnels/cascade", ".item");
    await page.waitForSelector("text=UDP 5555 → 5.6.7.8:5555");
    await shot("38-cascade");
  });
  await step("каскад: удалить", async () => {
    await page.click(".item >> text=UDP 5555");
    await page.waitForSelector("text=Правил нет");
  });
  await step("DNS", async () => { await nav("/tunnels/dns", "text=Включить"); await shot("39-dns"); });
  await step("всё напрямую", async () => {
    await nav("/tunnels", ".ecard");
    await page.click("text=Всё напрямую");
    await page.waitForSelector(".toast >> text=клиенты идут напрямую");
  });

  await step("тема вручную", async () => {
    const before = await page.evaluate(() => document.documentElement.dataset.theme);
    await page.click(".top button[aria-label='Тема']");
    await page.reload({ waitUntil: "domcontentloaded" }); await page.waitForSelector("h1");
    const after = await page.evaluate(() => document.documentElement.dataset.theme);
    if (after === before) throw new Error("тема не сменилась или не запомнилась");
    await page.click(".top button[aria-label='Тема']");
  });

  await step("вид панели: размер и жирность", async () => {
    await page.click(".top button[aria-label='Вид']");
    await page.waitForSelector(".sheet >> text=Вид панели");
    await page.click(".sheet .seg button:has-text('Жирнее')");
    await page.$eval(".sheet input[type=range]", (r) => { r.value = "90"; r.dispatchEvent(new Event("input")); r.dispatchEvent(new Event("change")); });
    await page.waitForSelector(".sheet >> text=Размер — 90%");
    await shot("25-look");
    const look = await page.evaluate(() => [document.documentElement.dataset.weight, document.documentElement.style.zoom]);
    if (look[0] !== "bold" || look[1] !== "0.9") throw new Error("жирность/размер не применились: " + look);
    await page.reload({ waitUntil: "domcontentloaded" }); await page.waitForSelector("h1");
    const kept = await page.evaluate(() => [document.documentElement.dataset.weight, document.documentElement.style.zoom]);
    if (kept.join() !== look.join()) throw new Error("не запомнилось: " + kept);
    await page.click(".top button[aria-label='Вид']");
    await page.click(".sheet button:has-text('Сбросить')");
    await page.click(".sheet button:has-text('Готово')");
    const reset = await page.evaluate(() => [document.documentElement.dataset.weight, document.documentElement.style.zoom]);
    if (reset[0] !== "normal" || reset[1] !== "") throw new Error("сброс не сработал: " + reset);
  });

  await step("вид главной", async () => {
    await nav("/", ".grid .tile");
    for (const [label, sel] of [["Компакт", ".card.list .item"], ["Иконки", ".igrid .ic"], ["Карточки", ".grid .tile"],
      ["Иконки", ".igrid .ic"]]) {
      await page.click(`.h2row .seg button[aria-label='${label}']`);
      await page.waitForSelector(`#app ${sel}`);
      await page.waitForSelector(`.h2row .seg button.on[aria-label='${label}']`);
    }
    await page.reload({ waitUntil: "domcontentloaded" }); await page.waitForSelector("#app .igrid .ic");
    await shot("26-home-icons");
    await page.click(".top button[aria-label='Вид']");
    await page.waitForSelector(".sheet .seg button.on:has-text('Иконки')");
    await page.click(".sheet .seg button:has-text('Компакт')");
    await page.waitForSelector("#app .card.list .item");
    await shot("27-home-compact");
    await page.click(".sheet button:has-text('Сбросить')");
    await page.waitForSelector("#app .grid .tile");
    await page.click(".sheet button:has-text('Готово')");
  });

  // ── Диагностика ──
  await step("диагностика", async () => { await nav("/diag", "text=Система"); await shot("40-diag"); });
  await step("домены мимикрии", async () => {
    await page.click("text=Домены мимикрии: мир");
    await page.waitForSelector("button:has-text('Назад')", { timeout: 90000 });
    await shot("41-domains");
  });
  await step("журналы", async () => {
    await nav("/diag/logs", ".item");
    const n = await page.locator(".item").count();
    if (n < 15) throw new Error("журналов в списке " + n);
    await page.click(".item >> text=Telegram-бот"); await page.waitForSelector("pre");
  });
  await step("тест мимикрии: клиенты", async () => { await nav("/diag/sniff", ".item"); await page.waitForSelector(".item >> text=alice"); });
  await step("DPI у клиента", async () => {
    await nav("/diag/dpi", "pre");
    await page.click("pre >> nth=0"); await page.waitForSelector(".toast >> text=Скопировано");
    await shot("42-dpi");
  });

  // ── Бэкапы ──
  await step("бэкап: создать и в чат", async () => {
    await nav("/backup", "text=Бэкапов на сервере нет");
    await page.click("button:has-text('Создать')");
    await page.waitForSelector("text=Файл — в чате с ботом", { timeout: 90000 });
    await shot("43-backup-done");
  });
  await step("бэкапы на сервере", async () => {
    await nav("/backup", ".item");
    if (await page.locator(".item").count() !== 2) throw new Error("ждали каталог и архив");
    await shot("44-backups");
    await page.click(".item >> nth=0");
    await page.click(".sheet >> text=Прислать в чат");
    await page.waitForSelector(".toast >> text=в чате с ботом");
  });
  await step("бэкап с телефона", async () => {
    const dir = `${sandboxRoot}/awg_backup`;
    const archive = fs.readdirSync(dir).find((f) => f.endsWith(".tar.gz"));
    await page.setInputFiles("input[type=file]", `${dir}/${archive}`);
    await page.waitForURL(/#\/backup\/restore$/);
    await page.waitForSelector("text=Клиентов");
    await shot("45-restore");
  });
  await step("восстановление", async () => {
    await page.click("button:has-text('Восстановить')");
    await page.waitForSelector("h1:has-text('Восстановление из бэкапа') .pill.ok", { timeout: 90000 });
    await shot("46-restored");
  });
  await step("не бэкап — понятная ошибка", async () => {
    await nav("/backup", ".item");
    await page.setInputFiles("input[type=file]", { name: "photo.tar.gz", mimeType: "application/gzip", buffer: Buffer.from("not a tar") });
    await page.waitForSelector("text=Архив не распаковался");
    await page.waitForSelector("text=это не архив tar.gz");
  });

  // ── Обновление ──
  // Главная сама заглядывает в канал — v9.9.9 может быть уже известна
  await step("обновление", async () => { await nav("/update", "text=Канал"); await page.waitForSelector("text=стабильный"); await shot("47-update"); });
  await step("проверка обновлений", async () => {
    await page.click("button:has-text('Проверить')");
    await page.waitForSelector(".toast >> text=Доступна v9.9.9");
    await page.waitForSelector("button:has-text('Обновить до v9.9.9')");
    // Список изменений из CHANGELOG.md канала — разметка без innerHTML
    await page.waitForSelector(".chlog-h >> text=Что нового в v9.9.9");
    await page.waitForSelector(".chlog b >> text=Новое");
    await page.waitForSelector(".chlog code >> text=сборка");
    await page.waitForSelector(".chlog li >> text=со второй строкой");
    if (await page.locator(".chlog-v >> text=v1.1.1").count()) throw new Error("в списке изменений — уже установленная версия");
    await shot("48-update-available");
  });
  await step("стрелка ↑ у версии в шапке", async () => {
    await page.waitForSelector(".top .ver .upd");
    if ((await page.getAttribute(".top .ver", "title")) !== "Доступна v9.9.9") throw new Error("у стрелки нет подсказки с версией");
    await nav("/", ".top .ver .upd");
    await shot("48b-update-arrow");
    await page.click(".top .ver");
    await page.waitForURL(/#\/update$/);
    await page.waitForSelector("text=Канал");
  });
  await step("бета-канал", async () => {
    await page.click("button:has-text('Бета-канал')");
    await page.waitForSelector("text=бета — ранние сборки");
    await page.waitForSelector(".top .chan >> text=бета");
    if (/null|undefined/.test(await page.textContent(".top"))) throw new Error("в шапке «null»");
  });
  // ── WG + обфускатор ──
  await step("обфускатор", async () => {
    await nav("/wgobf", "[data-name=wgobf]");
    await page.waitForSelector("text=Клиентов нет");
    await shot("50-wgobf");
  });
  await step("обфускатор: маскировка", async () => {
    await page.click(".seg button:has-text('NONE')");
    await page.waitForSelector(".toast >> text=NONE");
  });
  await step("обфускатор: клиент и комплект", async () => {
    await nav("/wgobf/add", "input");
    await page.fill("input", "kn1");
    await page.click("button:has-text('Создать')");
    await page.waitForURL(/#\/wgobf\/client\/kn1$/);
    await page.waitForSelector("text=Ссылка для Keenetic");
    await page.waitForSelector("pre >> text=[instance]");
    await page.waitForSelector("img.qr");
    await shot("51-wgobf-client");
    await page.click("button:has-text('Всё в чат')");
    await page.waitForSelector(".toast >> text=в чате с ботом");
  });
  await step("обфускатор: удалить клиента", async () => {
    await page.click("button:has-text('Удалить клиента')");
    await page.waitForURL(/#\/wgobf$/);
    await page.waitForSelector("text=Клиентов нет");
  });

  // ── Бот ──
  await step("бот", async () => { await nav("/bot", "[data-name=bot]"); await page.waitForSelector(".sgrid"); await shot("52-bot"); });
  await step("меню бота в чат", async () => {
    await page.click(".top button[aria-label='Разделы']");
    await page.click(".sheet >> text=Меню бота в чат");
    await page.waitForFunction(() => window.__log.includes("close"));
  });
  await step("админы: отозвать", async () => {
    await nav("/bot/admins", "text=@helper");
    await shot("53-admins");
    await page.click("[data-uid='333']");
    await page.waitForSelector("text=Приглашённых нет");
  });
  await step("админы: приглашение", async () => {
    await page.click("button:has-text('Пригласить')");
    await page.waitForSelector(".sheet pre >> text=/t\\.me\\/toolza_test_bot\\?start=inv_/");
    await shot("54-invite");
    await page.click(".sheet button:has-text('Готово')");
    await page.waitForSelector("text=Погасить приглашения: 1");
  });
  await step("оформление: набор иконок", async () => {
    await nav("/bot/look", "text=Иконки в боте");
    await page.click("button:has-text('Набор TgAndroidIcons')");
    await page.waitForSelector(".toast >> text=Иконки включены");
    await page.waitForSelector(".pill >> text=включены");
    await page.click("button:has-text('Выключить')");
    await page.waitForSelector(".pill >> text=выключены");
  });
  await step("прокси", async () => {
    await nav("/bot/proxy", "input");
    await expectAlert("схема", async () => { await page.fill("input", "1.2.3.4:1080"); await page.click("button:has-text('Сохранить')"); });
    await page.click("button:has-text('Найти на сервере')");
    await page.waitForSelector(".card.empty, .item >> nth=0", { timeout: 60000 });
    await shot("55-proxy");
  });
  await step("Mini App: сертификат на IP", async () => {
    await nav("/bot/app", "text=Сервер панели");
    await shot("56-app");
    await page.click("button:has-text('На IP')");
    await page.waitForSelector("h1:has-text('Сертификат на IP') .pill.ok", { timeout: 60000 });
  });
  await step("главная: все разделы в панели", async () => {
    await nav("/", ".tile");
    if (await page.locator(".tile.soon").count() !== 0) throw new Error("остались плитки «скоро»");
  });

  const log = await page.evaluate(() => window.__log);
  say("ALERTS", JSON.stringify(log.filter((l) => l.startsWith("alert:"))));
  say("ERRORS", JSON.stringify(errors));
  await browser.close();
})();
