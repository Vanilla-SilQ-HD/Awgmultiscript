// web_drive.js — веб-панель в Chromium: вход, обзор (ПК и телефон), лента и нижняя панель, клиенты
// с карточкой справа (ПК), скачивание, аккаунт, выход.
// Запускает test_web.py: node web_drive.js ПОРТ ПУТЬ ЛОГИН ПАРОЛЬ КАТАЛОГ_СКРИНШОТОВ
const { chromium } = require("playwright");
const [port, base, user, password, out] = process.argv.slice(2);
const say = (ok, label) => console.log(`${ok ? "OK" : "FAIL"} ${label}`);
(async () => {
  const browser = await chromium.launch();
  for (const [name, vp, scale] of [["ПК", { width: 1366, height: 860 }, 1], ["телефон", { width: 390, height: 844 }, 2]]) {
    const ctx = await browser.newContext({ ignoreHTTPSErrors: true, viewport: vp, deviceScaleFactor: scale, acceptDownloads: true });
    const page = await ctx.newPage();
    page.setDefaultTimeout(20000);
    page.on("pageerror", (e) => console.log(`ERR ${name}: ${e}`));
    page.on("request", (r) => { if (!r.url().startsWith(`https://127.0.0.1:${port}/`)) console.log(`ERR ${name}: внешний запрос ${r.url()}`); });
    const u = `https://127.0.0.1:${port}${base}`;
    const step = async (label, fn) => { try { await fn(); say(true, `${name}: ${label}`); } catch (e) { say(false, `${name}: ${label} — ${String(e).split("\n")[0]}`); } };
    await step("экран входа", async () => {
      await page.goto(u, { waitUntil: "networkidle" });
      await page.waitForSelector("form.login input[autocomplete=username]");
      await page.screenshot({ path: `${out}/${name}-вход.png` });
    });
    await step("неверный пароль — сообщение, панель не открылась", async () => {
      await page.fill("input[autocomplete=username]", user);
      await page.fill("input[type=password]", "wrong-password");
      await page.click("form.login button");
      await page.waitForSelector("form.login .bad:has-text('Неверный логин или пароль')");
    });
    await step("вход — обзор", async () => {
      await page.fill("input[type=password]", password);
      await page.press("input[type=password]", "Enter");
      await page.waitForSelector(".kpis .kpi");
      await page.waitForSelector(".topo svg .node");
      await page.waitForSelector(".top .lockup");
      await page.waitForTimeout(800);
      await page.screenshot({ path: `${out}/${name}-обзор.png` });
    });
    await step(name === "ПК" ? "лента разделов слева на широком экране" : "нижняя панель разделов на телефоне", async () => {
      const rail = await page.locator("#rail").isVisible(), tabs = await page.locator("#tabbar").isVisible();
      if (rail !== (name === "ПК") || tabs === (name === "ПК")) throw new Error(`#rail=${rail} #tabbar=${tabs}`);
    });
    await step("палитра команд: Ctrl+K — клиент по имени", async () => {
      await page.keyboard.press("Control+k");
      await page.waitForSelector(".pal.on input");
      await page.keyboard.type("alice");
      await page.waitForSelector(".pal li:has-text('alice')");
      await page.keyboard.press("Enter");
      await page.waitForURL(/#\/client\/alice$/);
    });
    await step(name === "ПК" ? "клиенты на ПК — таблицей, карточка клиента — панелью справа" : "клиенты на телефоне — карточками", async () => {
      await page.goto(u + "#/clients");
      await page.waitForSelector(name === "ПК" ? ".ctable tbody tr[data-name=alice]" : ".ecard[data-name=alice]");
      if (name !== "ПК" && await page.locator(".ctable").count()) throw new Error("таблица на телефоне");
      await page.screenshot({ path: `${out}/${name}-клиенты.png` });
      if (name === "ПК") {
        await page.click("tr[data-name=alice]");
        await page.waitForSelector(".drawer.on .cgrid .a-traf");
        await page.waitForSelector("tr.cur[data-name=alice]");          // список — за панелью, строка подсвечена
        await page.screenshot({ path: `${out}/${name}-клиент.png` });
        await page.keyboard.press("Escape");
        await page.waitForURL(/#\/clients$/);
        await page.waitForFunction(() => !document.querySelector(".drawer.on"), null, { timeout: 5000 })
          .catch(() => { throw new Error("панель не закрылась по Esc"); });
      } else {
        await page.goto(u + "#/client/alice");
        await page.waitForSelector("#app .cgrid .a-traf");
        await page.screenshot({ path: `${out}/${name}-клиент.png` });
      }
    });
    await step("клиенты и скачивание конфига: .conf и рядом ZIP", async () => {
      await page.goto(u + "#/client/alice/qr");
      await page.waitForSelector(".confbtns button:has-text('Скачать .conf')");
      const [dl] = await Promise.all([page.waitForEvent("download"), page.click(".confbtns button:has-text('Скачать .conf')")]);
      if (!/^[\w-]+\.conf$/.test(dl.suggestedFilename())) throw new Error(dl.suggestedFilename());
      const [dz] = await Promise.all([page.waitForEvent("download"), page.click(".confbtns button:has-text('Скачать ZIP')")]);
      if (!/^[\w-]+\.zip$/.test(dz.suggestedFilename())) throw new Error(dz.suggestedFilename());
      const zb = require("fs").readFileSync(await dz.path());
      if (zb.readUInt32LE(0) !== 0x04034b50 || !zb.includes(Buffer.from(dl.suggestedFilename()))) throw new Error("в ZIP нет " + dl.suggestedFilename());
    });
    await step("аккаунт: смена пароля и сессии", async () => {
      await page.goto(u + "#/account");
      await page.waitForSelector("text=Сменить пароль");
      await page.waitForSelector("text=Последние события");
      await page.screenshot({ path: `${out}/${name}-аккаунт.png`, fullPage: true });
    });
    await step("выход — снова экран входа, API закрыт", async () => {
      await page.click("#app button:has-text('Выйти')");
      await page.waitForSelector("form.login");
      await page.goto(u + "#/clients");
      await page.waitForSelector("form.login");
    });
    await ctx.close();
  }
  await browser.close();
})();
