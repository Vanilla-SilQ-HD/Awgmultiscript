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
      initData, ready: noop, expand: noop,
      BackButton: { show: () => window.__log.push("back:show"), hide: () => window.__log.push("back:hide"), onClick: (f) => { window.__back = f; } },
      HapticFeedback: { notificationOccurred: (t) => window.__log.push("haptic:" + t) },
      showConfirm: (t, cb) => { window.__log.push("confirm:" + t); cb(true); },
      showAlert: (t) => { window.__log.push("alert:" + t); },
    } };
    if (theme === "light") {
      document.addEventListener("DOMContentLoaded", () => {
        const s = document.documentElement.style;
        s.setProperty("--tg-theme-bg-color", "#ffffff"); s.setProperty("--tg-theme-secondary-bg-color", "#f1f1f4");
        s.setProperty("--tg-theme-text-color", "#000000"); s.setProperty("--tg-theme-hint-color", "#8e8e93");
        s.setProperty("--tg-theme-button-color", "#2481cc"); s.setProperty("--tg-theme-button-text-color", "#ffffff");
      });
    }
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

  await step("главная", async () => { await nav("/", ".tile"); await shot("01-home"); });
  if (theme === "light") { await browser.close(); console.log("ERRORS", JSON.stringify(errors)); return; }

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
  await step("список", async () => { await nav("/clients", ".item"); await shot("02-clients"); });
  await step("поиск", async () => {
    await page.fill("input[type=search]", "анн");
    const n = await page.locator(".item").count();
    if (n !== 1) throw new Error("ожидался 1 клиент по заметке, найдено " + n);
    await page.fill("input[type=search]", "");
  });
  await step("карточка", async () => { await page.click(".item >> text=alice"); await page.waitForSelector("text=Мониторинг активности"); await shot("03-card"); });
  await step("мониторинг", async () => {
    await page.click("text=Мониторинг активности");
    await page.waitForSelector(".switch.on");
  });
  await step("QR", async () => { await page.click("text=Конфиг и QR"); await page.waitForSelector("img.qr"); await shot("04-qr"); });
  await step("в чат", async () => { await page.click("text=Отправить файл в чат"); await page.waitForSelector(".toast"); });
  await step("срок", async () => {
    await nav("/client/alice", "text=Срок");
    await page.click("button:has-text('⏳ Срок')"); await page.waitForSelector(".sheet"); await shot("05-expire-sheet");
    await page.click(".sheet >> text=7 дней"); await page.waitForSelector("text=через 6д");
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
    await nav("/clients", ".item");
    await page.click(".bar >> text=Выбрать");
    await page.click(".item >> text=t-001"); await page.click(".item >> text=t-002");
    await shot("08-select");
    await page.click(".bar >> text=Удалить");
    await page.waitForSelector(".toast >> text=Удалено: 2");
    await page.waitForSelector(".item");
    if (await page.locator(".item >> text=t-001").count()) throw new Error("t-001 остался");
  });
  await step("мимикрия", async () => { await nav("/client/alice/mimicry", ".item"); await shot("09-mimicry"); });
  await step("удалить клиента", async () => {
    await nav("/client/carol", "text=Удалить клиента");
    await page.click("text=Удалить клиента");
    await page.waitForURL(/#\/clients$/);
  });

  // ── Сервер ──
  await step("сервер", async () => { await nav("/server", "text=Endpoint"); await page.waitForSelector("text=Модуль ядра"); await shot("20-server"); });
  await step("рестарт awg0", async () => { await page.click("text=Рестарт awg0"); await page.waitForSelector(".toast"); });
  await step("протокол", async () => { await nav("/server/proto", "text=Перейти на 3.1"); await shot("21-proto"); });
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
    await nav("/tunnels", ".item");
    const n = await page.locator(".item").count();
    if (n !== 6) throw new Error("ждали 6 строк (4 туннеля, каскад, DNS), есть " + n);
    await page.waitForSelector("text=Сейчас:");
    await shot("30-tunnels");
  });
  await step("WARP", async () => { await page.click(".item >> text=WARP"); await page.waitForSelector("text=Бэкенд"); await shot("31-warp"); });
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
    await nav("/tunnels", ".item");
    await page.click("text=Всё напрямую");
    await page.waitForSelector(".toast >> text=клиенты идут напрямую");
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
    await page.click("button:has-text('♻️ Восстановить')");
    await page.waitForSelector("h1 >> text=✅ Восстановление из бэкапа", { timeout: 90000 });
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
    await shot("48-update-available");
  });
  await step("бета-канал", async () => {
    await page.click("button:has-text('Бета-канал')");
    await page.waitForSelector("text=бета — ранние сборки");
  });
  await step("главная: плитки открываются", async () => {
    await nav("/", ".tile");
    if (await page.locator(".tile.soon").count() !== 2) throw new Error("ждали две плитки «скоро» (обфускатор и бот)");
  });

  const log = await page.evaluate(() => window.__log);
  say("ALERTS", JSON.stringify(log.filter((l) => l.startsWith("alert:"))));
  say("ERRORS", JSON.stringify(errors));
  await browser.close();
})();
