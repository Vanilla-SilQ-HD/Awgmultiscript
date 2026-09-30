const { chromium } = require("playwright");
const fs = require("fs");
const say = (...a) => fs.appendFileSync(process.argv[4] + "/run.log", a.join(" ") + "\n");
const [port, initData, out, theme] = process.argv.slice(2);
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
  const nav = async (hash, sel = "h1") => { await page.goto(base + "#" + hash, { waitUntil: "domcontentloaded" }); await page.waitForSelector(sel); await page.waitForTimeout(300); await noNull(); };
  const step = async (name, fn) => { try { await fn(); await noNull(); say("OK  ", name); } catch (e) { say("FAIL", name, String(e).split("\n")[0]); errors.push(name + ": " + e); } };

  await step("главная", async () => { await nav("/", ".tile"); await shot("01-home"); });
  if (theme === "light") { await browser.close(); console.log("ERRORS", JSON.stringify(errors)); return; }
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
  const log = await page.evaluate(() => window.__log);
  say("ALERTS", JSON.stringify(log.filter((l) => l.startsWith("alert:"))));
  say("ERRORS", JSON.stringify(errors));
  await browser.close();
})();
