"use strict";
// AWG Toolza — Mini App. Всё идёт через API бота (webapp.py, panel.py) с
// подписью Telegram в каждом запросе: страница ничего не хранит, а без
// Telegram сервер ей ничего не отдаст.

const tg = window.Telegram && window.Telegram.WebApp;
const root = document.getElementById("app");
const S = { me: null, clients: null, sort: null, filter: "all", q: "", select: null };

// ── Связь с ботом ─────────────────────────────────────────
async function post(path, body = {}) {
  const r = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: "tma " + (tg ? tg.initData : "") },
    body: JSON.stringify(body),
  });
  const d = await r.json().catch(() => ({}));
  if (!r.ok || d.ok === false) {
    const e = new Error(d.error || `HTTP ${r.status}`);
    e.log = d.log || "";
    throw e;
  }
  return d;
}
const call = async (...args) => (await post("/api/call", { args })).data;

// ── Мелочи ────────────────────────────────────────────────
function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid != null && kid !== false) el.append(kid instanceof Node ? kid : String(kid));
  }
  return el;
}
const plural = (n, one, few, many) => {
  const a = Math.abs(n) % 100, b = a % 10;
  return b === 1 && a !== 11 ? one : b >= 2 && b <= 4 && (a < 12 || a > 14) ? few : many;
};
function fmtBytes(n) {
  n = Number(n || 0);
  for (const u of ["Б", "КБ", "МБ", "ГБ"]) {
    if (n < 1024) return u === "Б" ? `${n} ${u}` : `${n.toFixed(1)} ${u}`;
    n /= 1024;
  }
  return `${n.toFixed(1)} ТБ`;
}
function fmtDur(s) {
  s = Math.max(0, Math.floor(s || 0));
  if (s < 60) return `${s}с`;
  if (s < 3600) return `${Math.floor(s / 60)}м`;
  if (s < 86400) return `${Math.floor(s / 3600)}ч ${Math.floor(s % 3600 / 60)}м`;
  return `${Math.floor(s / 86400)}д ${Math.floor(s % 86400 / 3600)}ч`;
}
const fmtTime = (ts) => new Date(ts * 1000).toLocaleString("ru-RU",
  { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
function fmtExpire(ts) {
  if (!ts) return "бессрочно";
  const left = ts - Date.now() / 1000;
  return `${fmtTime(ts)} (${left > 0 ? "через " + fmtDur(left) : "истёк"})`;
}
const haptic = (t = "success") => tg && tg.HapticFeedback && tg.HapticFeedback.notificationOccurred(t);
const kv = (k, v) => h("div", { class: "kv" }, h("span", {}, k), h("span", {}, v));

// Одна подсказка за раз: новая сменяет прежнюю, а не ложится поверх
let toastEl = null;
function toast(text, ms = 2000) {
  if (toastEl) toastEl.remove();
  const t = toastEl = h("div", { class: "toast" }, text);
  document.body.append(t);
  setTimeout(() => { t.remove(); if (toastEl === t) toastEl = null; }, ms);
}
function fail(e) {
  haptic("error");
  const tail = (e.log || "").trim().split("\n").slice(-6).join("\n");
  const text = "❌ " + e.message + (tail && tail !== e.message ? "\n\n" + tail : "");
  if (tg && tg.showAlert) tg.showAlert(text.slice(0, 1000)); else alert(text);
}
function confirmTg(text) {
  return new Promise((ok) => (tg && tg.showConfirm ? tg.showConfirm(text, ok) : ok(window.confirm(text))));
}
// Выбор снизу: [{label, value, cls}] → значение или null
function sheet(title, options) {
  return new Promise((done) => {
    const bg = h("div", { class: "sheet-bg", onclick: (ev) => { if (ev.target === bg) { bg.remove(); done(null); } } },
      h("div", { class: "sheet" }, h("h3", {}, title),
        options.map((o) => h("button", { class: o.cls || "", onclick: () => { bg.remove(); done(o.value); } }, o.label)),
        h("button", { class: "muted", onclick: () => { bg.remove(); done(null); } }, "Отмена")));
    document.body.append(bg);
  });
}
// Кнопка на время действия гаснет; ошибка — всплывающим окном
async function busy(btn, fn) {
  if (btn) btn.disabled = true;
  try { return await fn(); } catch (e) { fail(e); } finally { if (btn) btn.disabled = false; }
}
async function copy(text) {
  try { await navigator.clipboard.writeText(text); } catch {
    const ta = h("textarea", {}, text);
    document.body.append(ta); ta.select(); document.execCommand("copy"); ta.remove();
  }
  haptic(); toast("Скопировано");
}

// ── Роутер: #/путь, «Назад» — кнопка Telegram ──────────────
const routes = [];
let token = 0;
const route = (re, fn) => routes.push([re, fn]);
const go = (path) => { location.hash = path; };
const replace = (path) => { location.replace("#" + path); };
const back = () => (history.length > 1 ? history.back() : go("/"));

async function render() {
  const path = location.hash.slice(1) || "/";
  const my = ++token;
  // Экран отрисовывает то, что успел загрузить; ушли с него — молчит
  const ctx = { put: (...nodes) => { if (my === token) root.replaceChildren(...nodes.flat()); }, live: () => my === token };
  if (tg && tg.BackButton) tg.BackButton[path === "/" ? "hide" : "show"]();
  for (const [re, fn] of routes) {
    const m = path.match(re);
    if (!m) continue;
    window.scrollTo(0, 0);
    ctx.put(h("div", { class: "spin" }, "Загрузка…"));
    try {
      await fn(ctx, ...m.slice(1).map(decodeURIComponent));
    } catch (e) {
      ctx.put(h("div", { class: "card" }, h("div", { class: "bad" }, "❌ " + e.message),
        e.log ? h("pre", {}, e.log.trim().split("\n").slice(-12).join("\n")) : null,
        h("button", { class: "btn-block", onclick: render }, "Повторить")));
    }
    return;
  }
  replace("/");
}

// ── Задача с живым журналом ────────────────────────────────
// Долгое (массовое создание и т. п.) идёт задачей awg2: журнал — по ходу,
// итог — на том же экране. done(data) рисует кнопки итога.
async function runJob(ctx, title, args, done) {
  const started = Date.now();
  const head = h("h1", {}, "⏳ " + title), time = h("div", { class: "muted small" }), log = h("pre", {}, "запускаю…");
  const foot = h("div");
  ctx.put(head, time, log, foot);
  const r = await post("/api/job", { args });
  const id = r.data.id;
  let offset = 0, text = "";
  while (ctx.live()) {
    await new Promise((ok) => setTimeout(ok, 1500));
    const st = (await post("/api/job/status", { id, offset })).data;
    offset = st.offset || offset;
    if (st.log) {
      text += st.log;
      // Рамки заголовков из терминального вывода awg2 здесь не нужны
      log.textContent = text.split("\n").filter((l) => !/^[\s━─═—–-]*$/.test(l)).slice(-40).join("\n") || "идёт…";
      log.scrollTop = log.scrollHeight;
    }
    time.textContent = fmtDur((Date.now() - started) / 1000);
    if (st.state === "running") continue;
    const ok = st.state === "done" && st.ok;
    head.textContent = (ok ? "✅ " : "❌ ") + title;
    if (!ok) time.textContent = st.state === "lost" ? "Задача прервана: awg2 остановлен или сервер перезагружен" : (st.error || "ошибка");
    haptic(ok ? "success" : "error");
    foot.replaceChildren(...[].concat(ok && done ? done(st.data) : [],
      h("button", { class: "btn-block", onclick: back }, "◀️ Назад")));
    return;
  }
}

// ── Главная ───────────────────────────────────────────────
const SECTIONS = [
  ["👥", "Клиенты", "/clients", "конфиги, сроки, QR"],
  ["🖥", "Сервер", null, "установка, модуль"],
  ["🌐", "Туннели и DNS", null, "WARP, Xray, ноды"],
  ["🩺", "Диагностика", null, "проверки, журналы"],
  ["💾", "Бэкапы", null, "сохранить, вернуть"],
  ["⬆️", "Обновление", null, "версии, канал"],
  ["🛡", "Обфускатор", null, "WG как Phobos"],
  ["🤖", "Бот", null, "прокси, админы"],
];

route(/^\/$/, async (ctx) => {
  const [me, d] = await Promise.all([post("/api/me"), post("/api/status")]);
  S.me = me;
  const s = d.server || {}, t = d.tunnels || {}, c = d.components || {};
  const up = Object.entries(t).filter(([, v]) => v === "up").map(([k]) => ({ warp: "WARP", xray: "Xray",
    tun2socks: "tun2socks", exits: "Exit-ноды", dns: "DNS" }[k] || k));
  if (d.wgobf === "up") up.push("WG+обф.");
  const alerts = [
    s.exists && !s.up ? "⚠️ awg0 не поднят — Сервер → Проверить и починить" : null,
    c.installed && c.reboot ? "▲ " + c.reboot : null,
    d.update ? `⬆️ Доступна ${d.update}` : null,
  ].filter(Boolean);
  ctx.put(
    h("h1", {}, "AWG Toolza ", h("span", { class: "muted small" }, `${d.version || ""} · ${d.channel === "beta" ? "бета" : "стабильный"}`)),
    alerts.length ? h("div", { class: "card warn" }, alerts.map((a) => h("div", {}, a))) : null,
    h("div", { class: "card" },
      h("div", { style: "font-weight:600" }, `🖥 ${d.host || ""} · ${d.ip || ""}`),
      h("div", { class: "muted small" }, d.os || ""),
      s.exists ? kv("Сервер", `${s.up ? "🟢" : "🔴"} AWG ${s.proto || "?"} · порт ${s.port || "?"}`) : kv("Сервер", "не создан"),
      kv("Модуль", `${c.module || "—"}${c.module_update ? " · есть " + c.module_update : ""}`)),
    h("div", { class: "stats" },
      h("div", { class: "stat" }, h("b", {}, s.clients || 0), h("span", {}, plural(s.clients || 0, "клиент", "клиента", "клиентов"))),
      h("div", { class: "stat" }, h("b", { class: s.online ? "ok" : "" }, s.online || 0), h("span", {}, "онлайн")),
      h("div", { class: "stat" }, h("b", {}, up.length), h("span", {}, up.length ? up.join(", ") : "туннелей"))),
    h("h2", {}, "Разделы"),
    h("div", { class: "grid" }, SECTIONS.map(([ico, title, path, sub]) =>
      h("div", { class: "tile" + (path ? "" : " soon"),
        onclick: () => (path ? go(path) : toast("Раздел появится в панели следующим обновлением — пока он в боте")) },
        h("div", { class: "ico" }, ico), h("div", { class: "t" }, title), h("div", { class: "s" }, path ? sub : "скоро · пока в боте")))),
    h("div", { class: "muted small", style: "text-align:center;margin-top:16px" },
      `${me.name} · ${me.owner ? "владелец" : "админ"} · бот ${me.bot}`));
});

// ── Клиенты ───────────────────────────────────────────────
const FILTERS = [["all", "Все"], ["online", "🟢 Онлайн"], ["blocked", "🚫 Истёкшие"], ["mon", "🔔 Мониторинг"]];
const EXPIRES = [["", "♾ Бессрочно"], ["+1h", "1 час"], ["+1d", "1 день"], ["+7d", "7 дней"], ["+30d", "30 дней"]];

function seen(c) {
  if (c.blocked) return "срок истёк";
  if (c.online) return "онлайн";
  if (c.handshake) return `был ${fmtDur(c.ago)} назад`;
  return "не подключался";
}
function expShort(ts) {
  const left = ts - Date.now() / 1000;
  return left > 0 ? fmtDur(left) : "истёк";
}
function sortRows(rows, mode) {
  const byName = (a, b) => a.name.localeCompare(b.name, "ru", { sensitivity: "base" });
  if (mode === "name") return [...rows].sort(byName);
  return [...rows].sort((a, b) => (a.blocked - b.blocked) || (b.online - a.online) || ((b.handshake || 0) - (a.handshake || 0)) || byName(a, b));
}
async function loadClients() {
  S.clients = await post("/api/clients");
  if (!S.sort) S.sort = S.clients.sort || "activity";
  return S.clients;
}
const byName = (name) => (S.clients && S.clients.rows || []).find((c) => c.name === name);

route(/^\/clients$/, async (ctx) => {
  const d = await loadClients();
  const list = h("div", { class: "card list" }), count = h("span", { class: "muted small" });
  const sortBtn = h("button", { class: "chip", onclick: () => {
    S.sort = S.sort === "name" ? "activity" : "name";
    post("/api/settings", { sort: S.sort }).catch(() => {});
    draw();
  } });
  const chips = h("div", { class: "chips" }), bar = h("div", { class: "bar" });
  const search = h("input", { type: "search", placeholder: "Поиск по имени, IP, заметке", value: S.q,
    oninput: () => { S.q = search.value.trim().toLowerCase(); draw(); } });

  function visible() {
    return sortRows(d.rows, S.sort).filter((c) =>
      (S.filter === "all" || (S.filter === "online" && c.online) || (S.filter === "blocked" && c.blocked) || (S.filter === "mon" && c.mon))
      && (!S.q || `${c.name} ${c.ip} ${c.note || ""}`.toLowerCase().includes(S.q)));
  }
  function row(c) {
    const sel = S.select && S.select.has(c.name);
    const mark = S.select ? h("div", { class: "check" + (sel ? " on" : "") })
      : h("div", { class: "dot" + (c.blocked ? " blocked" : c.online ? " on" : "") });
    return h("div", { class: "item", onclick: () => {
      if (!S.select) return go("/client/" + encodeURIComponent(c.name));
      S.select.has(c.name) ? S.select.delete(c.name) : S.select.add(c.name);
      draw();
    } }, mark,
      h("div", { class: "main" }, h("div", { class: "title" }, c.name + (c.mon ? " 🔔" : "")),
        h("div", { class: "sub" }, [c.ip, seen(c), c.expires && !c.blocked ? "⏳ " + expShort(c.expires) : null, c.note].filter(Boolean).join(" · "))),
      h("div", { class: "side" }, "↓" + fmtBytes(c.rx), h("br"), "↑" + fmtBytes(c.tx)));
  }
  function draw() {
    const rows = visible();
    list.replaceChildren(...(rows.length ? rows.map(row) : [h("div", { class: "empty" }, d.rows.length ? "Никого не нашлось" : "Клиентов пока нет")]));
    chips.replaceChildren(...FILTERS.map(([k, label]) =>
      h("button", { class: "chip" + (S.filter === k ? " on" : ""), onclick: () => { S.filter = k; draw(); } }, label)));
    sortBtn.textContent = S.sort === "name" ? "🔃 По имени" : "🔃 По активности";
    const online = d.rows.filter((c) => c.online).length;
    count.textContent = `${d.rows.length} ${plural(d.rows.length, "клиент", "клиента", "клиентов")} · ${online} онлайн`
      + (S.select ? ` · отмечено ${S.select.size}` : "");
    if (S.select) {
      bar.replaceChildren(
        h("button", { onclick: () => { const all = rows.every((c) => S.select.has(c.name));
          rows.forEach((c) => (all ? S.select.delete(c.name) : S.select.add(c.name))); draw(); } }, "Все"),
        h("button", { class: "btn-danger", disabled: !S.select.size || null, onclick: (ev) => deleteMany(ev.target) },
          `🗑 Удалить ${S.select.size || ""}`),
        h("button", { onclick: () => { S.select = null; draw(); } }, "Отмена"));
    } else {
      bar.replaceChildren(
        h("button", { class: "btn-primary", onclick: () => go("/add") }, "➕ Добавить"),
        h("button", { onclick: () => go("/bulk") }, "Несколько"),
        h("button", { onclick: () => { S.select = new Set(); draw(); } }, "Выбрать"));
    }
  }
  async function deleteMany(btn) {
    const names = [...S.select];
    if (!await confirmTg(`Удалить клиентов: ${names.length}?\n${names.slice(0, 20).join(", ")}${names.length > 20 ? "…" : ""}\n\nИх конфиги перестанут работать.`)) return;
    await busy(btn, async () => {
      await post("/api/client/del", { names });
      haptic(); toast(`Удалено: ${names.length}`);
      S.select = null;
      render();
    });
  }
  ctx.put(h("h1", {}, "👥 Клиенты"), search, chips,
    h("div", { class: "row", style: "justify-content:space-between;margin:2px 2px 8px" }, count, sortBtn), list,
    d.rows.length ? h("button", { class: "btn-block", onclick: (ev) => busy(ev.target, async () => {
      await post("/api/send", { what: "export" }); haptic(); toast("Архив всех конфигов — в чате с ботом");
    }) }, "📦 Все конфиги архивом в чат") : null, bar);
  draw();
});

// Карточка клиента
route(/^\/client\/([^/]+)$/, async (ctx, name) => {
  await loadClients();
  const c = byName(name);
  if (!c) return ctx.put(h("div", { class: "empty" }, `Клиента ${name} нет`), h("button", { class: "btn-block", onclick: () => replace("/clients") }, "К списку"));
  const r = S.clients.route || {};
  const enc = encodeURIComponent(name);
  const monSwitch = h("div", { class: "switch" + (c.mon ? " on" : "") });
  const status = c.blocked ? h("span", { class: "bad" }, "🚫 срок истёк") : c.online
    ? h("span", { class: "ok" }, `🟢 онлайн (${fmtDur(c.ago)} назад)`) : h("span", {}, "⚪️ " + seen(c));

  async function setExpire(btn) {
    const v = await sheet("⏳ Срок действия", [
      { label: c.expires ? "♾ Снять срок" + (c.blocked ? " и разблокировать" : "") : "♾ Бессрочно", value: "none" },
      ...EXPIRES.slice(1).map(([val, label]) => ({ label: "⏳ " + label, value: val })),
      { label: "📅 До даты…", value: "date" }]);
    if (!v) return;
    if (v === "date") return go(`/client/${enc}/date`);
    await busy(btn, async () => {
      await (v === "none" ? call("client", "unexpire", name) : call("client", "expire", name, v));
      haptic(); toast("Срок обновлён"); render();
    });
  }
  async function setRoute(btn) {
    const kind = r.kind;
    let opts;
    if (kind === "exits") {
      const cur = c.exit_choice;
      opts = [["off", "Напрямую"], ["shared", "Общий выход"], ...(r.nodes || []).map((n) => [n, "Нода " + n])]
        .map(([v, l]) => ({ label: (cur === v ? "🔘 " : "⚪️ ") + l, value: v }));
    } else {
      const on = c[kind] !== false, t = kind === "warp" ? "WARP" : "Xray";
      opts = [{ label: (on ? "🔘 " : "⚪️ ") + "Через " + t, value: "on" }, { label: (on ? "⚪️ " : "🔘 ") + "Напрямую", value: "off" }];
    }
    const v = await sheet("🌐 Маршрут " + name, opts);
    if (!v) return;
    await busy(btn, async () => {
      await (kind === "exits" ? call("exits", "client", name, v) : call("tunnels", "client", kind, name, v));
      haptic(); toast("Маршрут изменён"); render();
    });
  }
  async function remove(btn) {
    if (!await confirmTg(`Удалить клиента ${name}? Его конфиг перестанет работать.`)) return;
    await busy(btn, async () => {
      await post("/api/client/del", { names: [name] });
      haptic(); toast(`Удалён: ${name}`); replace("/clients");
    });
  }

  ctx.put(
    h("h1", {}, "👤 " + name),
    h("div", { class: "card" },
      kv("Статус", status),
      kv("IP", c.ip),
      kv("Трафик", `↓${fmtBytes(c.rx)} ↑${fmtBytes(c.tx)}`),
      c.endpoint ? kv("Адрес клиента", c.endpoint.replace(/:\d+$/, "")) : null,
      kv("Срок", fmtExpire(c.expires)),
      kv("Мимикрия", c.mimicry || "none"),
      kv("Маршрут", c.route || "напрямую"),
      c.note ? kv("Заметка", c.note) : null),
    h("div", { class: "card item", style: "border:0", onclick: () => busy(null, async () => {
      const on = !monSwitch.classList.contains("on");
      await post("/api/client/mon", { name, on });
      monSwitch.classList.toggle("on", on);
      haptic(); toast(on ? "🔔 Бот сообщит, когда клиент пропадёт и вернётся" : "🔕 Мониторинг выключен", 3000);
    }) }, h("div", { class: "main" }, h("div", { class: "title" }, "🔔 Мониторинг активности"),
      h("div", { class: "sub" }, "уведомления в чат, когда клиент пропал и вернулся")), monSwitch),
    h("div", { class: "actions" },
      h("button", { class: "btn-primary", onclick: () => go(`/client/${enc}/qr`) }, "📄 Конфиг и QR"),
      h("button", { onclick: () => go(`/client/${enc}/rename`) }, "✏️ Имя"),
      h("button", { onclick: (ev) => setExpire(ev.target) }, "⏳ Срок"),
      h("button", { onclick: () => go(`/client/${enc}/mimicry`) }, "🎭 Мимикрия"),
      ["warp", "xray", "exits"].includes(r.kind) ? h("button", { onclick: (ev) => setRoute(ev.target) }, "🌐 Маршрут") : null,
      h("button", { onclick: () => go(`/client/${enc}/note`) }, "📝 Заметка")),
    h("button", { class: "btn-danger btn-block", onclick: (ev) => remove(ev.target) }, "🗑 Удалить клиента"));
});

route(/^\/client\/([^/]+)\/qr$/, async (ctx, name) => {
  const d = await post("/api/client/qr", { name });
  ctx.put(
    h("h1", {}, "📄 " + name),
    d.png ? h("img", { class: "qr", src: "data:image/png;base64," + d.png, alt: "QR" })
      : h("div", { class: "card muted" }, "Конфиг длинный — в читаемый QR не влезает. Импортируй файлом."),
    h("div", { class: "muted small", style: "text-align:center;margin:6px 0 10px" }, "AmneziaVPN / AmneziaWG → добавить → QR или файл"),
    h("button", { class: "btn-primary btn-block", onclick: (ev) => busy(ev.target, async () => {
      await post("/api/send", { what: "conf", name }); haptic(); toast("Файл и QR — в чате с ботом");
    }) }, "✉️ Отправить файл в чат"),
    h("button", { class: "btn-block", onclick: () => copy(d.text) }, "📋 Скопировать конфиг"),
    h("pre", { class: "small" }, d.text));
});

route(/^\/client\/([^/]+)\/rename$/, async (ctx, name) => {
  const input = h("input", { value: name, maxlength: 32, autocapitalize: "off", autocomplete: "off" });
  ctx.put(h("h1", {}, "✏️ Новое имя"), h("label", {}, "Латиница, цифры, _ и -, до 32"), input,
    h("button", { class: "btn-primary btn-block", onclick: (ev) => busy(ev.target, async () => {
      const v = input.value.trim();
      if (!/^[A-Za-z0-9_-]{1,32}$/.test(v)) throw new Error("Имя: латиница, цифры, _ и -, до 32 символов");
      if (v !== name) await post("/api/client/rename", { old: name, new: v });
      haptic(); replace("/client/" + encodeURIComponent(v));
    }) }, "Сохранить"));
  input.focus();
});

route(/^\/client\/([^/]+)\/note$/, async (ctx, name) => {
  await loadClients();
  const c = byName(name) || {};
  const ta = h("textarea", { maxlength: 190 }, c.note || "");
  ctx.put(h("h1", {}, "📝 Заметка · " + name), h("label", {}, "До 190 символов; пусто — удалить"), ta,
    h("button", { class: "btn-primary btn-block", onclick: (ev) => busy(ev.target, async () => {
      await post("/api/client/note", { name, text: ta.value.trim() }); haptic(); back();
    }) }, "Сохранить"));
});

route(/^\/client\/([^/]+)\/date$/, async (ctx, name) => {
  const def = new Date(Date.now() + 30 * 86400e3);
  def.setMinutes(def.getMinutes() - def.getTimezoneOffset());
  const input = h("input", { type: "datetime-local", value: def.toISOString().slice(0, 16) });
  ctx.put(h("h1", {}, "📅 Срок · " + name), h("label", {}, "Клиент заблокируется в это время (время телефона)"), input,
    h("button", { class: "btn-primary btn-block", onclick: (ev) => busy(ev.target, async () => {
      const ts = Math.floor(new Date(input.value).getTime() / 1000);
      if (!ts || ts < Date.now() / 1000 + 60) throw new Error("Нужна дата в будущем");
      await call("client", "expire", name, ts); haptic(); toast("Срок обновлён"); back();
    }) }, "Сохранить"));
});

// Мимикрия: профиль и уровень; новый конфиг — сразу на экран QR
async function mimicryPicker(onPick) {
  const profiles = (await call("mimicry")) || [];
  let level = "3";
  const lv = h("div", { class: "chips" });
  const drawLv = () => lv.replaceChildren(...[["3", "Цепочка I1-I5"], ["2", "Только I1"]].map(([v, l]) =>
    h("button", { class: "chip" + (level === v ? " on" : ""), onclick: () => { level = v; drawLv(); } }, l)));
  drawLv();
  return [
    h("div", { class: "muted small", style: "margin:0 4px 6px" }, "Пакеты I1-I5 перед рукопожатием — под какой протокол маскироваться. Keenetic читает только I1, WireSock — ни одного."),
    h("label", {}, "Уровень"), lv,
    h("div", { class: "card list" },
      h("div", { class: "item", onclick: () => onPick("server") }, h("div", { class: "main" }, h("div", { class: "title" }, "Как у сервера"))),
      h("div", { class: "item", onclick: () => onPick("none") }, h("div", { class: "main" }, h("div", { class: "title" }, "Без I1-I5"))),
      profiles.map((p) => h("div", { class: "item", onclick: () => onPick(`${p.id}:${level}`) },
        h("div", { class: "main" }, h("div", { class: "title" }, p.label), h("div", { class: "sub" }, p.hint))))),
  ];
}

route(/^\/client\/([^/]+)\/mimicry$/, async (ctx, name) => {
  ctx.put(h("h1", {}, "🎭 Мимикрия · " + name), ...await mimicryPicker((spec) => busy(null, async () => {
    toast("Генерирую мимикрию…", 4000);
    await call("client", "mimicry", name, spec);
    haptic(); toast("Мимикрия обновлена — старый конфиг больше не подключится", 3500);
    replace(`/client/${encodeURIComponent(name)}/qr`);
  })));
});

// ── Новый клиент ──────────────────────────────────────────
function expireField() {
  const sel = h("select", {}, EXPIRES.map(([v, l]) => h("option", { value: v }, l)), h("option", { value: "date" }, "📅 До даты…"));
  const date = h("input", { type: "datetime-local", style: "display:none;margin-top:8px" });
  sel.onchange = () => { date.style.display = sel.value === "date" ? "" : "none"; };
  const value = () => {
    if (sel.value !== "date") return sel.value;
    const ts = Math.floor(new Date(date.value).getTime() / 1000);
    if (!ts || ts < Date.now() / 1000 + 60) throw new Error("Нужна дата в будущем");
    return String(ts);
  };
  return { nodes: [h("label", {}, "Срок действия"), sel, date], value };
}

route(/^\/add$/, async (ctx) => {
  const d = await loadClients();
  const taken = new Set(d.rows.map((c) => c.name));
  const free = () => { let n = 1; while (taken.has("client" + n)) n++; return "client" + n; };
  const name = h("input", { placeholder: "anna_phone", maxlength: 32, autocapitalize: "off", autocomplete: "off" });
  const exp = expireField();
  let spec = "server";
  const mimLabel = h("div", { class: "muted small" }, "Мимикрия: как у сервера");
  const pro = d.profile === "pro";
  ctx.put(h("h1", {}, "➕ Новый клиент"),
    h("label", {}, "Имя — латиница, цифры, _ и -, до 32"),
    h("div", { class: "row" }, name, h("button", { onclick: () => { name.value = free(); } }, "🎲")),
    exp.nodes,
    pro ? h("div", { style: "margin-top:12px" }, mimLabel, h("button", { class: "btn-block", onclick: async () => {
      const box = h("div", { class: "sheet" }, h("h3", {}, "🎭 Мимикрия"));
      const bg = h("div", { class: "sheet-bg", onclick: (ev) => ev.target === bg && bg.remove() }, box);
      box.append(...await mimicryPicker((s) => { spec = s; mimLabel.textContent = "Мимикрия: " + (s === "server" ? "как у сервера" : s === "none" ? "без I1-I5" : s); bg.remove(); }));
      document.body.append(bg);
    } }, "🎭 Выбрать мимикрию")) : null,
    h("button", { class: "btn-primary btn-block", onclick: (ev) => busy(ev.target, async () => {
      const v = name.value.trim() || free();
      if (!/^[A-Za-z0-9_-]{1,32}$/.test(v)) throw new Error("Имя: латиница, цифры, _ и -, до 32 символов");
      if (taken.has(v)) throw new Error(`Имя ${v} уже занято`);
      await post("/api/client/add", { name: v, expire: exp.value(), mimicry: spec });
      haptic(); toast("Клиент создан");
      replace(`/client/${encodeURIComponent(v)}/qr`);
    }) }, "Создать"));
});

route(/^\/bulk$/, async (ctx) => {
  let mode = "prefix";
  const tabs = h("div", { class: "chips" });
  const prefix = h("input", { value: "user", maxlength: 27, autocapitalize: "off" });
  const count = h("input", { type: "number", min: 1, max: 200, value: 5 });
  const names = h("textarea", { placeholder: "anna, boris, vera" });
  const box = h("div");
  const exp = expireField();
  const draw = () => {
    tabs.replaceChildren(...[["prefix", "Префикс + номер"], ["names", "Имена списком"]].map(([v, l]) =>
      h("button", { class: "chip" + (mode === v ? " on" : ""), onclick: () => { mode = v; draw(); } }, l)));
    box.replaceChildren(...(mode === "prefix"
      ? [h("label", {}, "Префикс — получатся user-001, user-002…"), prefix, h("label", {}, "Сколько (1-200)"), count]
      : [h("label", {}, "Имена через запятую"), names]));
  };
  draw();
  ctx.put(h("h1", {}, "➕ Несколько клиентов"), tabs, box, exp.nodes,
    h("button", { class: "btn-primary btn-block", onclick: (ev) => busy(ev.target, async () => {
      let spec;
      if (mode === "prefix") {
        const p = prefix.value.trim(), n = Number(count.value);
        if (!/^[A-Za-z0-9_-]{1,27}$/.test(p)) throw new Error("Префикс: латиница, цифры, _ и -, до 27 символов");
        if (!(n >= 1 && n <= 200)) throw new Error("Количество — от 1 до 200");
        spec = `${p}:${n}`;
      } else {
        const list = names.value.split(",").map((s) => s.trim()).filter(Boolean);
        if (!list.length || !list.every((s) => /^[A-Za-z0-9_-]{1,32}$/.test(s))) throw new Error("Имена: латиница, цифры, _ и -, через запятую");
        spec = list.join(",");
      }
      const e = exp.value();
      await runJob(ctx, "Создание клиентов", ["clients", "bulk", spec, ...(e ? [`expire=${e}`] : [])], (created) => {
        const list = Array.isArray(created) ? created : [];
        return [
          h("div", { class: "card" }, h("b", {}, `Создано: ${list.length}`), h("div", { class: "muted small" }, list.join(", "))),
          list.length ? h("button", { class: "btn-primary btn-block", onclick: (ev2) => busy(ev2.target, async () => {
            await post("/api/send", { what: "zip", names: list }); haptic(); toast("Архив конфигов — в чате с ботом");
          }) }, "📦 Конфиги архивом в чат") : null,
          h("button", { class: "btn-block", onclick: () => replace("/clients") }, "👥 К списку"),
        ];
      });
    }) }, "Создать"));
});

// ── Старт ─────────────────────────────────────────────────
if (tg) {
  tg.ready();
  tg.expand();
  if (tg.BackButton) tg.BackButton.onClick(back);
}
window.addEventListener("hashchange", render);
if (!tg || !tg.initData) {
  root.replaceChildren(h("div", { class: "empty" }, "Открой панель кнопкой в боте"));
} else {
  render();
}
