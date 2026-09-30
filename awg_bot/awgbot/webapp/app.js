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
  // Условные части экрана приходят как null — их просто нет (иначе «null» текстом)
  const ctx = { put: (...nodes) => { if (my === token) root.replaceChildren(...nodes.flat(Infinity).filter((n) => n != null && n !== false)); },
    live: () => my === token };
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

// Строка вывода awg2 для узкого экрана: отступ меньше, колонки из пробелов сжаты
const tidy = (l) => {
  const lead = l.length - l.trimStart().length;
  return " ".repeat(Math.max(0, lead - 2)) + l.trim().replace(/ {3,}/g, "  ");
};

// ── Задача с живым журналом ────────────────────────────────
// Долгое (массовое создание, установка, сборка) идёт задачей awg2: журнал —
// по ходу, итог — на том же экране. done(data) рисует кнопки итога;
// opts.stdin — ввод задачи, opts.onBack — куда «Назад» (по умолчанию экран,
// с которого задачу запустили, уже с новым состоянием).
async function runJob(ctx, title, args, done, opts = {}) {
  const started = Date.now();
  const head = h("h1", {}, "⏳ " + title), time = h("div", { class: "muted small" }), log = h("pre", {}, "запускаю…");
  const foot = h("div");
  const backBtn = () => h("button", { class: "btn-block", onclick: () => (opts.onBack || render)() }, "◀️ Назад");
  ctx.put(head, time, log, foot);
  let id;
  try {
    id = (await post("/api/job", { args, stdin: opts.stdin })).data.id;
  } catch (e) {
    head.textContent = "❌ " + title; time.textContent = e.message;
    log.textContent = (e.log || "").trim() || "задача не запустилась";
    haptic("error"); foot.replaceChildren(backBtn());
    return;
  }
  let offset = 0, text = "", misses = 0;
  while (ctx.live()) {
    await new Promise((ok) => setTimeout(ok, 1500));
    let st;
    try {
      st = (await post("/api/job/status", { id, offset })).data;
      misses = 0;
    } catch (e) {
      // Бот мог перезапуститься по ходу задачи — задача awg2 от этого не встаёт
      if (++misses < 60) continue;
      throw e;
    }
    offset = st.offset || offset;
    if (st.log) {
      text += st.log;
      // Рамки заголовков из терминального вывода awg2 здесь не нужны
      log.textContent = text.split("\n").filter((l) => !/^[\s━─═—–-]*$/.test(l)).map(tidy).slice(-300).join("\n") || "идёт…";
      log.scrollTop = log.scrollHeight;
    }
    time.textContent = fmtDur((Date.now() - started) / 1000);
    if (st.state === "running") continue;
    const ok = st.state === "done" && st.ok;
    head.textContent = (ok ? "✅ " : "❌ ") + title;
    if (!ok) time.textContent = st.state === "lost" ? "Задача прервана: awg2 остановлен или сервер перезагружен" : (st.error || "ошибка");
    haptic(ok ? "success" : "error");
    foot.replaceChildren(...[].concat(ok && done ? done(st.data) : [], backBtn()).flat(Infinity)
      .filter((n) => n != null && n !== false));
    return;
  }
}

// ── Общее для разделов ────────────────────────────────────
// Ответ awg2 api целиком: data и журнал
const callR = (args, { timeout = 120, stdin } = {}) => post("/api/call", { args, timeout, stdin });
// Итог по журналу awg2: строки «√», «→» и «▲», последние две-три
function outcome(log, fallback) {
  const lines = (log || "").split("\n").filter((l) => /^\s*[√→▲]/.test(l)).map((l) => l.replace(/^\s*[√→]\s*/, "").trim());
  return lines.slice(-3).join("\n") || fallback;
}
// Быстрое действие: итог — подсказкой, ошибка — окном с журналом, затем
// экран перерисовывается (then(r) — вместо перерисовки)
function quick(btn, title, args, then = render, timeout = 600) {
  return busy(btn, async () => {
    const r = await callR(args, { timeout });
    haptic(); toast("✅ " + outcome(r.log, title), 3500);
    then(r);
  });
}
async function quickAsk(btn, question, title, args, then) {
  if (await confirmTg(question)) await quick(btn, title, args, then);
}
async function jobAsk(ctx, question, title, args, done) {
  if (await confirmTg(question)) await runJob(ctx, title, args, done);
}
// Журнал awg2 «Ключ : значение» → строки карточки; ● — хорошо, ▲ — внимание
const tone = (s) => (/^[●√]/.test(s) ? "ok" : /^[▲×]/.test(s) ? "warn" : /^○/.test(s) ? "muted" : "");
function logCard(log, ...head) {
  const rows = [];
  for (const raw of (log || "").split("\n")) {
    const l = raw.trim();
    if (!l || /^[━─═—–-]+$/.test(l)) continue;
    const m = l.match(/^([^:]{2,22}?)\s*:\s+(.+)$/);
    // Длинное значение — под названием, а не узким столбцом справа
    rows.push(!m ? h("div", { class: "small " + tone(l) }, l.replace(/^→\s*/, ""))
      : m[2].length > 26 ? h("div", { style: "padding:5px 0" }, h("div", { class: "muted" }, m[1]), h("div", { class: tone(m[2]) }, m[2]))
        : kv(m[1], h("span", { class: tone(m[2]) }, m[2])));
  }
  return h("div", { class: "card" }, head, rows);
}
// Вывод awg2 без рамок заголовков — на телефоне они переносятся в мусор
const plainLog = (text) => (text || "").split("\n").filter((l) => !/^[\s━─═]+$/.test(l) || !l.trim()).map(tidy).join("\n").trim();
// Длинный вывод (диагностика) — снизу, поверх экрана
function logSheet(title, text) {
  const bg = h("div", { class: "sheet-bg", onclick: (ev) => { if (ev.target === bg) bg.remove(); } },
    h("div", { class: "sheet" }, h("h3", {}, title), h("pre", {}, plainLog(text) || "пусто"),
      h("button", { onclick: () => bg.remove() }, "Закрыть")));
  document.body.append(bg);
}
// Переключатель строкой: onToggle(новое) — промис; ошибка оставляет как было
function switchRow(title, sub, on, onToggle) {
  const sw = h("div", { class: "switch" + (on ? " on" : "") });
  return h("div", { class: "card item", style: "border:0", onclick: () => busy(null, async () => {
    const next = !sw.classList.contains("on");
    await onToggle(next);
    sw.classList.toggle("on", next);
    haptic();
  }) }, h("div", { class: "main" }, h("div", { class: "title" }, title), sub ? h("div", { class: "sub wrap" }, sub) : null), sw);
}
// Файл с телефона в поле ввода (конфиги, профили)
function fileField(ta) {
  const input = h("input", { type: "file", accept: ".conf,.txt,text/plain", style: "display:none", onchange: async () => {
    const f = input.files[0];
    if (!f) return;
    if (f.size > 64 * 1024) return fail(new Error("Файл больше 64 КБ — это не конфиг"));
    ta.value = await f.text();
    toast("Загружен " + f.name);
  } });
  return [input, h("button", { class: "btn-block", style: "margin-top:0", onclick: () => input.click() }, "📎 Выбрать файл"),
    h("label", {}, "или вставь текст")];
}
const btn = (label, onclick, cls) => h("button", { class: cls || null, onclick: (ev) => onclick(ev.currentTarget) }, label);
const hint = (text) => h("div", { class: "muted small", style: "margin:8px 4px" }, text);
const IP_RE = /^(\d{1,3}\.){3}\d{1,3}$/;
const DOMAIN_RE = /^(?=.{4,253}$)([A-Za-z0-9-]{1,63}\.)+[A-Za-z]{2,63}$/;
const validPort = (v, min = 1) => /^\d{1,5}$/.test(v) && +v >= min && +v <= 65535;

// ── Главная ───────────────────────────────────────────────
const SECTIONS = [
  ["👥", "Клиенты", "/clients", "конфиги, сроки, QR"],
  ["🖥", "Сервер", "/server", "установка, модуль"],
  ["🌐", "Туннели и DNS", "/tunnels", "WARP, Xray, ноды"],
  ["🩺", "Диагностика", "/diag", "проверки, журналы"],
  ["💾", "Бэкапы", "/backup", "сохранить, вернуть"],
  ["⬆️", "Обновление", "/update", "версии, канал"],
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
    s.exists && !s.up ? ["⚠️ awg0 не поднят — Сервер → Починить", "/server"] : null,
    c.installed && c.reboot ? ["▲ " + c.reboot, "/server/module"] : null,
    d.update ? [`⬆️ Доступна ${d.update} — обновить`, "/update"] : null,
  ].filter(Boolean);
  ctx.put(
    h("h1", {}, "AWG Toolza ", h("span", { class: "muted small" }, `${d.version || ""} · ${d.channel === "beta" ? "бета" : "стабильный"}`)),
    alerts.length ? h("div", { class: "card warn" }, alerts.map(([a, path]) =>
      h("div", { style: "cursor:pointer;padding:2px 0", onclick: () => go(path) }, a))) : null,
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
      }, { onBack: back });
    }) }, "Создать"));
});

// ── Сервер ────────────────────────────────────────────────
const PROFILES = { lite: "AmneziaVPN", pro: "Мощный", standard: "Standard" };
const DNS = [["Cloudflare", "1.1.1.1, 1.0.0.1"], ["Google", "8.8.8.8, 8.8.4.4"],
  ["Quad9", "9.9.9.9, 149.112.112.112"], ["Яндекс", "77.88.8.8, 77.88.8.1"]];

route(/^\/server$/, async (ctx) => {
  const r = await callR(["server", "info"]);
  const d = r.data || {}, tip = (r.log || "").trim();
  const warnings = [d.reboot ? "▲ " + d.reboot : null, tip ? "→ " + tip : null].filter(Boolean);
  ctx.put(h("h1", {}, "🖥 Сервер"),
    warnings.length ? h("div", { class: "card warn small" }, warnings.map((w) => h("div", {}, w))) : null,
    h("div", { class: "card" },
      kv("Компоненты", d.installed ? "✅ установлены" : "❌ не установлены"),
      d.exists ? [
        kv("awg0", d.up ? h("span", { class: "ok" }, "● поднят") : h("span", { class: "bad" }, "● не поднят")),
        kv("Протокол", `AWG ${d.proto || "?"} · ${d.profile_label || PROFILES[d.profile] || d.profile || ""}`),
        kv("Endpoint", h("span", { onclick: () => copy(d.endpoint), style: "cursor:pointer" }, d.endpoint || "", " 📋")),
        kv("Порт · MTU", `${d.port} · ${d.mtu}`),
        kv("Подсеть", d.net || ""),
        kv("Регион", d.region === "ru" ? "Россия" : "мир"),
        kv("Мимикрия", (d.mimicry || "none") + (d.mimicry_domain ? ` (${d.mimicry_domain})` : "")),
        kv("Клиентов", d.clients || 0),
      ] : kv("Сервер", "не создан")),
    h("div", { class: "actions" },
      !d.exists ? btn("✨ Создать сервер", () => go("/server/create"), d.installed ? "btn-primary" : null) : null,
      d.exists ? btn("🔄 Рестарт awg0", (b) => quick(b, "awg0 перезапущен", ["server", "restart"])) : null,
      d.exists ? btn("🔀 Протокол", () => go("/server/proto")) : null,
      d.exists ? btn("🌍 Endpoint", () => go("/server/endpoint")) : null,
      btn("🧩 Модуль ядра", () => go("/server/module")),
      btn(d.installed ? "📦 Компоненты" : "📦 Установить", () => jobAsk(ctx, "Пакеты, заголовки ядра, сборка модуля AmneziaWG "
        + "и amneziawg-tools из исходников. Обычно 5-15 минут. Если ядру нет заголовков, поставится свежее ядро — "
        + "тогда понадобится перезагрузка.", "Установка компонентов", ["server", "install"]), d.installed ? null : "btn-primary"),
      btn("🛠 Починить", () => runJob(ctx, "Проверка и ремонт", ["server", "repair"], (res) => res
        ? h("div", { class: "card" }, kv("Найдено проблем", res.issues || 0), kv("Исправлено", res.fixed || 0)) : null)),
      btn("♻️ Перезагрузка", (b) => quickAsk(b, "Перезагрузить сервер? Панель и бот вернутся сами через минуту-две.",
        "Сервер перезагружается", ["server", "reboot"], () => {}))),
    d.exists ? h("button", { class: "btn-danger btn-block", onclick: (ev) => quickAsk(ev.currentTarget,
      "Сброс сервера: awg0 и все клиенты будут удалены, туннели выключены. Перед сбросом делается авто-бэкап, "
      + "компоненты остаются. Сбросить?", "Сервер сброшен", ["server", "reset"]) }, "⚠️ Сбросить сервер") : null);
});

// Создание сервера — те же вопросы, что задают меню awg2 и бот, одной формой
route(/^\/server\/create$/, async (ctx) => {
  const [info, profiles] = await Promise.all([call("server", "info"), call("mimicry")]);
  if (info.exists) {
    return ctx.put(h("div", { class: "empty" }, "Сервер уже создан"),
      h("button", { class: "btn-block", onclick: () => replace("/server") }, "🖥 К серверу"));
  }
  const mims = profiles || [];
  const f = { region: "world", profile: "lite", lite: "none", level: "3", proto: info.proto31 ? "3.1" : "2.0" };
  const box = h("div");
  const chips = (key, opts) => h("div", { class: "chips" }, opts.map(([v, l]) =>
    h("button", { class: "chip" + (f[key] === v ? " on" : ""), onclick: () => { f[key] = v; draw(); } }, l)));
  const mimSel = h("select", { onchange: () => draw() }, mims.map((p) => h("option", { value: p.id }, p.label)));
  if (mims.some((p) => p.id === "dns")) mimSel.value = "dns";
  const dnsSel = h("select", { onchange: () => draw() }, DNS.map(([l, ips], i) => h("option", { value: i }, `${l} — ${ips}`)),
    h("option", { value: "manual" }, "Вручную…"));
  const dnsIn = h("input", { placeholder: "1.1.1.1, 8.8.8.8", inputmode: "decimal" });
  const mtu = h("input", { type: "number", min: 1280, max: 1500 });
  const net = h("input", { placeholder: "случайная 10.x.y.0/24", autocapitalize: "off", autocomplete: "off" });
  const port = h("input", { type: "number", min: 1024, max: 65535, placeholder: "случайный" });
  const ep = h("input", { placeholder: "IP этого сервера", autocapitalize: "off", autocomplete: "off" });
  const first = h("input", { placeholder: "случайное", maxlength: 32, autocapitalize: "off", autocomplete: "off" });

  function draw() {
    const pro = f.profile === "pro", rec = pro ? "1320" : "1280";
    const mim = mims.find((p) => p.id === mimSel.value);
    mtu.placeholder = rec;
    box.replaceChildren(...[
      h("label", {}, "Где стоит сервер — от этого зависят домены мимикрии"),
      chips("region", [["world", "🌍 Мир / Европа"], ["ru", "🇷🇺 Россия"]]),
      h("label", {}, "Профиль"),
      chips("profile", [["lite", "AmneziaVPN"], ["pro", "Мощный"]]),
      hint(pro ? "Широкие диапазоны и I1-I5 — сильнее против DPI"
        : "Как официальный клиент: MTU 1280, без I1-I5 (рекомендуется)"),
      h("label", {}, "Мимикрия"),
      pro ? chips("level", [["3", "Цепочка I1-I5"], ["2", "Только I1"], ["none", "Без I1-I5"]])
        : chips("lite", [["none", "Без I1-I5"], ["dns:2", "Пакет I1 (DNS)"]]),
      pro && f.level !== "none" ? [mimSel, mim ? hint(mim.hint) : null] : null,
      hint(pro ? "Цепочка — полная; только I1 — для Keenetic; без I1-I5 — для WireSock"
        : "У официального клиента AmneziaVPN строк I нет; пакет I1 — один компактный DNS-запрос"),
      h("label", {}, "Версия протокола — на весь сервер"),
      chips("proto", info.proto31 ? [["3.1", "AWG 3.1"], ["2.0", "AWG 2.0"]] : [["2.0", "AWG 2.0"]]),
      hint(info.proto31 ? "3.1 — быстрее, заголовки под шифром; клиентам нужен AmneziaVPN 5.0.1.5+ или AmneziaWG с 3.1. "
        + "2.0 — подключится любой клиент AmneziaWG" : "▲ Модуль и tools не умеют 3.1 — обнови их: Сервер → Модуль ядра"),
      h("label", {}, "DNS для клиентов"), dnsSel, dnsSel.value === "manual" ? dnsIn : null,
      h("label", {}, `MTU — рекомендуется ${rec}`), mtu,
      h("label", {}, "Подсеть клиентов"), net,
      hint("Случайная — меньше шансов совпасть с домашней сетью клиента"),
      h("label", {}, "UDP-порт"), port,
      h("label", {}, "Домен для конфигов (необязательно)"), ep,
      hint("С доменом сервер можно перенести без перевыдачи конфигов. A-запись должна указывать сюда"),
      h("label", {}, "Имя первого клиента"), first,
    ].flat(Infinity).filter((n) => n != null));
  }
  draw();

  function args() {
    const pro = f.profile === "pro", a = [`profile=${f.profile}`, `proto=${f.proto}`, `region=${f.region}`];
    let dns = dnsSel.value === "manual" ? dnsIn.value : DNS[+dnsSel.value][1];
    const ips = dns.split(",").map((x) => x.trim()).filter(Boolean);
    if (!ips.length || !ips.every((x) => IP_RE.test(x))) throw new Error("DNS: IPv4-адреса через запятую");
    dns = ips.join(", ");
    const m = mtu.value.trim() || (pro ? "1320" : "1280");
    if (!/^\d+$/.test(m) || +m < 1280 || +m > 1500) throw new Error("MTU — число 1280-1500");
    const mimicry = !pro ? f.lite : f.level === "none" ? "none" : `${mimSel.value}:${f.level}`;
    a.push(`dns=${dns}`, `mtu=${m}`, `mimicry=${mimicry}`);
    const n = net.value.trim();
    if (n) {
      const g = n.match(/^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.\d{1,3}\/24$/);
      if (!g || g.slice(1).some((x) => +x > 255)) throw new Error("Подсеть — сеть /24, например 10.8.0.0/24");
      a.push(`net=${g[1]}.${g[2]}.${g[3]}.0/24`);
    }
    const p = port.value.trim();
    if (p) {
      if (!validPort(p, 1024)) throw new Error("Порт — число 1024-65535");
      a.push(`port=${p}`);
    }
    const e = ep.value.trim().toLowerCase();
    if (e) {
      if (!DOMAIN_RE.test(e)) throw new Error("Домен — имя вида vpn.example.com");
      a.push(`endpoint=${e}`);
    }
    const c = first.value.trim();
    if (c) {
      if (!/^[A-Za-z0-9_-]{1,32}$/.test(c)) throw new Error("Имя клиента: латиница, цифры, _ и -, до 32");
      a.push(`client=${c}`);
    }
    return a;
  }
  ctx.put(h("h1", {}, "✨ Создание сервера"), box,
    h("button", { class: "btn-primary btn-block", onclick: (ev) => busy(ev.currentTarget, async () => {
      const a = args();
      await runJob(ctx, "Создание сервера", ["server", "create", ...a], (res) => {
        const name = res && res.client;
        return name ? [
          h("div", { class: "card" }, kv("Первый клиент", name)),
          h("button", { class: "btn-primary btn-block", onclick: () => replace(`/client/${encodeURIComponent(name)}/qr`) }, "📄 Конфиг и QR"),
          h("button", { class: "btn-block", onclick: (e2) => busy(e2.currentTarget, async () => {
            await post("/api/send", { what: "conf", name }); haptic(); toast("Файл и QR — в чате с ботом");
          }) }, "✉️ Отправить файл в чат"),
        ] : null;
      }, { onBack: () => replace("/server") });
    }) }, "✨ Создать сервер"));
});

route(/^\/server\/proto$/, async (ctx) => {
  const d = (await call("server", "info")) || {};
  const cur = d.proto || "2.0", n = d.clients || 0;
  const doIt = async (target) => {
    if (!await confirmTg(`Перегенерировать параметры на AWG ${target}? Все клиенты потеряют связь до получения нового конфига.`)) return;
    await runJob(ctx, `Переход на AWG ${target}`, ["server", "proto", target], () => [
      h("button", { class: "btn-primary btn-block", onclick: (ev) => busy(ev.currentTarget, async () => {
        await post("/api/send", { what: "export" }); haptic(); toast("Архив всех конфигов — в чате с ботом");
      }) }, "📦 Все конфиги архивом в чат"),
      h("button", { class: "btn-block", onclick: () => go("/clients") }, "👥 Клиенты"),
    ], { onBack: () => replace("/server") });
  };
  ctx.put(h("h1", {}, "🔀 Протокол"),
    h("div", { class: "card" }, kv("Сейчас", `AWG ${cur}`), kv("Клиентов", n)),
    h("div", { class: "card small" },
      h("div", {}, "• 3.1 — быстрее, заголовки под шифром; 2.0 — для старых клиентов"),
      h("div", {}, "• 🔁 — новые параметры той же версии"),
      h("div", { class: "muted", style: "margin-top:6px" }, "Ключи, адреса, имена и сроки сохраняются. Все клиенты получают "
        + "новые конфиги и до их замены не подключатся."),
      d.proto31 ? null : h("div", { class: "warn", style: "margin-top:6px" }, "▲ Модуль не умеет 3.1 — при переходе он обновится (долго)")),
    btn(cur === "3.1" ? "🔁 Новые параметры 3.1" : "⬆️ Перейти на 3.1", () => doIt("3.1"), "btn-primary btn-block"),
    btn(cur === "2.0" ? "🔁 Новые параметры 2.0" : "⬇️ Вернуть 2.0", () => doIt("2.0"), "btn-block"));
});

route(/^\/server\/endpoint$/, async (ctx) => {
  const d = (await call("server", "info")) || {};
  let all = true;
  const dom = h("input", { value: d.domain || "", placeholder: "vpn.example.com", autocapitalize: "off", autocomplete: "off" });
  const save = (b, value) => quick(b, "Endpoint изменён", ["server", "endpoint", value, ...(all ? [] : ["keep"])], () => back());
  ctx.put(h("h1", {}, "🌍 Endpoint"),
    h("div", { class: "card" }, kv("В конфигах", d.endpoint || ""),
      h("div", { class: "muted small" }, d.domain ? "Домен задан — сервер можно переносить без перевыдачи конфигов."
        : "Сейчас IP. С доменом переезд сервера не требует новых конфигов.")),
    h("label", {}, "Домен — A-запись должна указывать на этот сервер"), dom,
    switchRow("Переписать в выданных конфигах", "иначе — только для новых клиентов", all, (on) => { all = on; }),
    btn("💾 Сохранить домен", (b) => {
      const v = dom.value.trim().toLowerCase();
      if (!DOMAIN_RE.test(v)) return fail(new Error("Нужно имя вида vpn.example.com"));
      return save(b, v);
    }, "btn-primary btn-block"),
    d.domain ? btn("🔢 Вернуть публичный IP", (b) => save(b, "ip"), "btn-block") : null);
});

route(/^\/server\/module$/, async (ctx) => {
  const r = await callR(["module", "report"]);
  const d = r.data || {};
  const upd = (v) => (v ? h("span", { class: "ok" }, " · ⬆️ есть " + v) : null);
  async function pickTag(b) {
    const tags = await busy(b, () => call("module", "tags"));
    if (!tags) return;
    const tag = await sheet("📋 Версия модуля — сверху новые", tags.map((t) => ({ label: t, value: t })));
    if (tag) await jobAsk(ctx, `Собрать и поставить модуль ${tag}?`, `Модуль ${tag}`, ["module", "update", tag, "force"]);
  }
  async function rollback(b) {
    const rows = await busy(b, () => call("module", "backups"));
    if (!rows) return;
    const path = await sheet("⏪ Копии исходников — сверху новые", rows.map((x) => ({ label: `${fmtTime(x.time)} · ${x.name}`, value: x.path })));
    if (path) await jobAsk(ctx, `Вернуть модуль из ${path.split("/").pop()}?`, "Откат модуля", ["module", "rollback", path]);
  }
  ctx.put(h("h1", {}, "🧩 Модуль ядра"),
    d.reboot || d.secure_boot ? h("div", { class: "card warn small" }, d.reboot ? h("div", {}, "▲ " + d.reboot) : null,
      d.secure_boot ? h("div", {}, "▲ Secure Boot включён — неподписанный модуль ядро не загрузит") : null) : null,
    h("div", { class: "card" },
      kv("Ядро", d.kernel || ""),
      kv("Установлены", (d.kernels || []).join(", ") || "—"),
      kv("Модуль", h("span", {}, d.module || "не установлен", " ", d.loaded ? h("span", { class: "ok" }, "● загружен")
        : h("span", { class: "bad" }, "● не загружен"), upd(d.module_update))),
      kv("tools", h("span", {}, d.tools || "не установлены", upd(d.tools_update)))),
    h("div", { class: "actions" },
      btn("⬆️ Модуль", () => jobAsk(ctx, "Собрать и поставить последнюю версию модуля? Туннели лягут на несколько секунд "
        + "при перезагрузке модуля.", "Обновление модуля", ["module", "update"]), d.module_update ? "btn-primary" : null),
      btn("⬆️ Tools", () => runJob(ctx, "Обновление amneziawg-tools", ["module", "tools"]), d.tools_update ? "btn-primary" : null),
      btn("📋 Версия модуля", pickTag),
      btn("🔁 Перезагрузить", () => jobAsk(ctx, "Перезагрузить модуль? Туннели лягут на несколько секунд, клиенты "
        + "переподключатся сами.", "Перезагрузка модуля", ["module", "reload"])),
      btn("🧱 Под все ядра", () => runJob(ctx, "Сборка модуля под все ядра", ["module", "rebuild"])),
      d.backups ? btn("⏪ Откат", rollback) : null,
      btn("🔎 Проверить", (b) => quick(b, "Версии проверены", ["module", "check"])),
      btn("📜 Журнал сборки", () => go("/log/module"))),
    hint("⬆️ — до последней версии · 🔁 — перезагрузить модуль без ребута · 🧱 — собрать под все установленные ядра"),
    h("details", { class: "card" }, h("summary", {}, "📄 Полный отчёт"), h("pre", {}, plainLog(r.log))));
});

// ── Туннели и DNS ─────────────────────────────────────────
const STATE_WORD = { up: "включён", off: "выключен", none: "не настроен" };
const TUNNELS = [["warp", "☁️", "WARP", "Cloudflare"], ["xray", "🛰", "Xray", "VLESS, VMess, Trojan, SS"],
  ["tun2socks", "🧦", "tun2socks", "внешний SOCKS5"], ["exits", "🚪", "Exit-ноды", "другие AWG/WG-серверы"]];
const navItem = (path, title, sub, on) => h("div", { class: "item", onclick: () => go(path) },
  h("div", { class: "dot" + (on ? " on" : "") }),
  h("div", { class: "main" }, h("div", { class: "title" }, title), h("div", { class: "sub" }, sub)),
  h("div", { class: "side" }, "›"));

route(/^\/tunnels$/, async (ctx) => {
  const d = (await call("tunnels", "status")) || {};
  const n = d.cascade || 0;
  ctx.put(h("h1", {}, "🌐 Туннели и DNS"),
    h("div", { class: "card small" }, "Клиенты выходят в интернет через один туннель за раз.",
      d.active ? h("div", { style: "margin-top:4px" }, "Сейчас: ", h("b", { class: "ok" }, d.active)) : null),
    h("h2", {}, "Выход клиентов"),
    h("div", { class: "card list" }, TUNNELS.map(([k, ico, title, sub]) =>
      navItem("/tunnels/" + k, `${ico} ${title}`, `${STATE_WORD[d[k]] || d[k] || "—"} · ${sub}`, d[k] === "up"))),
    h("h2", {}, "Ещё"),
    h("div", { class: "card list" },
      navItem("/tunnels/cascade", "🔀 Каскад портов", n ? `правил: ${n}` : "правил нет", n > 0),
      navItem("/tunnels/dns", "🔐 Шифрованный DNS", `${STATE_WORD[d.dns] || d.dns || "—"} · DoH для клиентов`, d.dns === "up")),
    h("button", { class: "btn-danger btn-block", onclick: (ev) => quickAsk(ev.currentTarget, "Выключить все туннели (WARP, Xray, "
      + "tun2socks, exit-ноды)? Клиенты пойдут напрямую через сервер, настройки сохранятся.", "Туннели выключены",
    ["tunnels", "panic"]) }, "🚨 Всё напрямую"),
    hint("Аварийно выключить туннели — если клиенты остались без интернета"));
});

// Кто из клиентов идёт через туннель (WARP, Xray)
route(/^\/tunnels\/(warp|xray)\/clients$/, async (ctx, kind) => {
  const t = kind === "warp" ? "WARP" : "Xray";
  const rows = (await call("tunnels", "clients", kind)) || [];
  const list = h("div", { class: "card list" });
  const draw = () => list.replaceChildren(...(rows.length ? rows.map((c) => h("div", { class: "item", onclick: () => busy(null, async () => {
    await call("tunnels", "client", kind, c.name, c.on ? "off" : "on");
    c.on = !c.on; haptic(); draw();
  }) }, h("div", { class: "main" }, h("div", { class: "title" }, c.name), h("div", { class: "sub" }, `${c.ip} · ${c.on ? "через " + t : "напрямую"}`)),
  h("div", { class: "switch" + (c.on ? " on" : "") }))) : [h("div", { class: "empty" }, "Клиентов нет")]));
  draw();
  ctx.put(h("h1", {}, `👥 Клиенты в ${t}`), hint(`Включено — клиент выходит через ${t}, выключено — напрямую через сервер.`), list,
    rows.length ? h("div", { class: "bar" },
      btn("✅ Все через " + t, (b) => quick(b, "Все через " + t, ["tunnels", "client", kind, "all"])),
      btn("➖ Все напрямую", (b) => quick(b, "Все напрямую", ["tunnels", "client", kind, "none"]))) : null);
});

// WARP
route(/^\/tunnels\/warp$/, async (ctx) => {
  const r = await callR(["warp", "status"]);
  const d = r.data || {}, wg = d.backend === "wg", conf = d.configured;
  async function backend(b) {
    const opts = [["wg", "wg — WireGuard ядра, быстрее", d.wg_possible], ["usque", "usque — MASQUE (HTTP/3), когда WireGuard к Cloudflare режут", d.usque_possible]]
      .filter(([v, , ok]) => v !== d.backend && ok).map(([v, label]) => ({ label, value: v }));
    if (!opts.length) return toast("Другой бэкенд здесь недоступен");
    const v = await sheet(`🔀 Бэкенд WARP — сейчас ${d.backend || "?"}`, opts);
    if (v) await runJob(ctx, `WARP: бэкенд ${v}`, ["warp", "backend", v]);
  }
  ctx.put(h("h1", {}, "☁️ WARP"), logCard(r.log),
    conf ? switchRow("🩺 Health-check", "сам перезапускает WARP, если тот перестал отвечать", d.health,
      (on) => call("warp", "health", on ? "on" : "off")) : null,
    h("div", { class: "actions" },
      conf && !d.up ? btn("▶️ Включить", () => runJob(ctx, "Включение WARP", ["warp", "up"]), "btn-primary") : null,
      d.up ? btn("⏹ Выключить", (b) => quick(b, "WARP выключен", ["warp", "down"])) : null,
      conf ? btn("👥 Клиенты", () => go("/tunnels/warp/clients")) : null,
      btn(conf ? "📦 Переустановить" : "📦 Установить", () => runJob(ctx, conf ? "Переустановка WARP" : "Установка WARP", ["warp", "install"]),
        conf ? null : "btn-primary"),
      wg && conf ? btn("🔑 Ключ Warp+", () => go("/tunnels/warp/key")) : null,
      wg ? btn("📥 Импорт", () => go("/tunnels/warp/import")) : null,
      wg && conf ? btn("🔎 Поиск endpoint", () => go("/tunnels/warp/endpoint")) : null,
      btn("🔀 Бэкенд", backend),
      btn("📜 Журнал", () => go(d.backend === "usque" ? "/log/usque" : "/log/warp")),
      conf ? btn("🗑 Удалить", (b) => quickAsk(b, "Удалить WARP: аккаунт, профиль, службы?", "WARP удалён", ["warp", "remove"]), "btn-danger") : null),
    hint(`📦 — ${conf ? "переустановить" : "установить"} и зарегистрироваться в Cloudflare (бэкенд ${d.backend || "?"})`
      + (wg ? " · 📥 — свой wgcf-profile.conf, если регистрация отсюда не проходит" : "")));
});

route(/^\/tunnels\/warp\/key$/, async (ctx) => {
  const key = h("input", { placeholder: "xxxxxxxx-xxxxxxxx-xxxxxxxx", autocapitalize: "off", autocomplete: "off" });
  ctx.put(h("h1", {}, "🔑 Ключ Warp+"), h("label", {}, "В приложении 1.1.1.1: Аккаунт → Ключ"), key,
    btn("Сохранить", (b) => {
      const v = key.value.trim();
      if (!/^[A-Za-z0-9]+-[A-Za-z0-9]+-[A-Za-z0-9]+$/.test(v)) return fail(new Error("Неверный формат ключа"));
      return quick(b, "Ключ Warp+ применён", ["warp", "license", v], () => back());
    }, "btn-primary btn-block"));
});

route(/^\/tunnels\/warp\/import$/, async (ctx) => {
  const ta = h("textarea", { placeholder: "[Interface]\nPrivateKey = …\n\n[Peer]\n…", style: "min-height:160px" });
  ctx.put(h("h1", {}, "📥 Профиль WARP"),
    h("div", { class: "card small" }, "Зарегистрируй профиль там, где Cloudflare доступен (например, shell.cloud.google.com):",
      h("pre", { style: "margin:8px 0 0" }, "./wgcf register --accept-tos && ./wgcf generate")),
    h("label", {}, "wgcf-profile.conf"), fileField(ta), ta,
    btn("📥 Импортировать", (b) => {
      const text = ta.value.trim();
      if (!text.includes("[Interface]") || !text.includes("[Peer]")) return fail(new Error("Это не похоже на wgcf-profile.conf"));
      return busy(b, async () => {
        const r = await callR(["warp", "import"], { stdin: text + "\n" });
        haptic(); toast("✅ " + outcome(r.log, "Профиль импортирован"), 3500); back();
      });
    }, "btn-primary btn-block"));
});

route(/^\/tunnels\/warp\/endpoint$/, async (ctx) => {
  const cc = h("input", { placeholder: "DE", maxlength: 2, autocapitalize: "characters", autocomplete: "off" });
  const find = (code) => runJob(ctx, `Поиск endpoint WARP${code ? ` (${code})` : ""}`, ["warp", "endpoint", ...(code ? [code] : [])],
    null, { onBack: back });
  ctx.put(h("h1", {}, "🔎 Endpoint WARP"), hint("Перебирает адреса Cloudflare и ставит тот, что отвечает быстрее всех."),
    btn("🌍 Любая страна", () => find(""), "btn-primary btn-block"),
    h("label", {}, "Или страна выхода — две буквы (DE, NL, FI…)"), cc,
    btn("🔎 Искать в этой стране", () => {
      const v = cc.value.trim().toUpperCase();
      if (!/^[A-Z]{2}$/.test(v)) return fail(new Error("Две латинские буквы, например DE"));
      return find(v);
    }, "btn-block"));
});

// Xray
const BALANCERS = [["random", "случайный выход"], ["roundRobin", "по очереди"], ["leastPing", "наименьший пинг"],
  ["leastLoad", "наименьшая нагрузка"], ["off", "выключить"]];

route(/^\/tunnels\/xray$/, async (ctx) => {
  const r = await callR(["xray", "status"]);
  const d = r.data || {}, inst = d.installed, tags = d.tags || [];
  async function balancer(b) {
    const v = await sheet("⚖️ Как делить трафик между выходами", BALANCERS.map(([k, l]) =>
      ({ label: `${d.balancer === k ? "🔘" : "⚪️"} ${k} — ${l}`, value: k })));
    if (v) await quick(b, "Балансировщик: " + v, ["xray", "balancer", v]);
  }
  ctx.put(h("h1", {}, "🛰 Xray"), logCard(r.log),
    inst ? switchRow("🇷🇺 РФ напрямую", "российские сайты мимо Xray", d.ru,
      (on) => runJob(ctx, `РФ-сайты напрямую: ${on ? "вкл" : "выкл"}`, ["xray", "ru", on ? "on" : "off"])) : null,
    inst ? [h("h2", {}, "Выходы"),
      h("div", { class: "card list" }, tags.length ? tags.map((t) => h("div", { class: "item", onclick: () =>
        quickAsk(null, `Удалить выход ${t}?`, "Выход удалён", ["xray", "del", t]) },
      h("div", { class: "main" }, h("div", { class: "title" }, t)), h("div", { class: "side" }, "🗑")))
        : h("div", { class: "empty" }, "Выходов нет — добавь ссылкой")),
      btn("➕ Добавить выход", () => go("/tunnels/xray/add"), "btn-block" + (tags.length ? "" : " btn-primary")),
      tags.length > 1 ? btn(`⚖️ Балансировщик: ${d.balancer || "off"}`, balancer, "btn-block") : null,
      h("h2", {}, "Управление")] : null,
    inst ? null : [hint("Клиенты выходят в интернет через твой сервер VLESS, VMess, Trojan, Shadowsocks или Hysteria2 — "
      + "выходы добавляются ссылками. Можно несколько, с балансировкой."),
    btn("📦 Установить Xray", () => runJob(ctx, "Установка Xray", ["xray", "install"]), "btn-primary btn-block")],
    inst ? h("div", { class: "actions" },
      btn("📦 Обновить", () => runJob(ctx, "Обновление Xray", ["xray", "install"])),
      tags.length && !d.up ? btn("▶️ Включить", () => runJob(ctx, "Включение Xray", ["xray", "up"]), "btn-primary") : null,
      d.up ? btn("⏹ Выключить", (b) => quick(b, "Xray выключен", ["xray", "down"])) : null,
      d.up ? btn("🔄 Перезапустить", () => runJob(ctx, "Перезапуск Xray", ["xray", "restart"])) : null,
      btn("👥 Клиенты", () => go("/tunnels/xray/clients")),
      btn("🩺 Диагностика", () => runJob(ctx, "Диагностика Xray", ["xray", "diag"])),
      btn("🛠 Починить", (b) => busy(b, async () => {
        const res = await callR(["xray", "fix"], { timeout: 300 });
        haptic(); logSheet("🛠 Исправление конфига Xray", res.log);
      })),
      btn("📜 Журнал", () => go("/log/xray")),
      btn("🗑 Удалить", (b) => quickAsk(b, "Удалить Xray: бинарь, конфиг с выходами, службы?", "Xray удалён", ["xray", "remove"]), "btn-danger")) : null);
});

route(/^\/tunnels\/xray\/add$/, async (ctx) => {
  const link = h("textarea", { placeholder: "vless://…", style: "min-height:110px", autocapitalize: "off" });
  ctx.put(h("h1", {}, "➕ Выход Xray"), h("label", {}, "Ссылка на сервер: vless://, vmess://, trojan://, ss:// или hysteria2://"), link,
    btn("Добавить", (b) => {
      const v = link.value.trim();
      if (!/^(vless|vmess|trojan|ss|hysteria2|hy2):\/\//.test(v)) return fail(new Error("Это не ссылка Xray"));
      return quick(b, "Выход добавлен", ["xray", "add", v], () => back());
    }, "btn-primary btn-block"));
});

// tun2socks
route(/^\/tunnels\/tun2socks$/, async (ctx) => {
  const d = (await call("t2s", "status")) || {};
  const proxy = h("input", { value: d.proxy || "", placeholder: "5.6.7.8:1080", autocapitalize: "off", autocomplete: "off" });
  ctx.put(h("h1", {}, "🧦 tun2socks"),
    h("div", { class: "card" }, h("div", { class: "muted small" }, "Все клиенты выходят через внешний SOCKS5-прокси."),
      kv("Статус", d.up ? h("span", { class: "ok" }, "● включён") : h("span", { class: "muted" }, "○ выключен")),
      d.proxy ? kv("Прокси", d.proxy) : null),
    d.up ? null : [h("label", {}, "Адрес SOCKS5-прокси: IP:ПОРТ"), proxy,
      btn("▶️ Включить", () => {
        const v = proxy.value.trim();
        if (!/^[A-Za-z0-9._-]+:\d{1,5}$/.test(v)) return fail(new Error("Нужен адрес вида IP:ПОРТ"));
        return runJob(ctx, "Включение tun2socks", ["t2s", "up", v]);
      }, "btn-primary btn-block")],
    h("div", { class: "actions", style: "margin-top:8px" },
      d.up ? btn("⏹ Выключить", (b) => quick(b, "tun2socks выключен", ["t2s", "down"])) : null,
      btn("📜 Журнал", () => go("/log/tun2socks")),
      d.proxy ? btn("🗑 Удалить", (b) => quickAsk(b, "Удалить tun2socks (служба, бинарь, адрес прокси)?", "tun2socks удалён",
        ["t2s", "remove"]), "btn-danger") : null));
});

// AWG exit-ноды
route(/^\/tunnels\/exits$/, async (ctx) => {
  const r = await callR(["exits", "status"]);
  const d = r.data || {}, nodes = d.nodes || [], up = d.up;
  async function balance(b) {
    const cur = d.balancer === "ecmp" ? "ecmp" : d.single || "";
    const v = await sheet("⚖️ Балансировка: одна нода — весь общий трафик через неё; ECMP — поровну между поднятыми",
      [...nodes.map((n) => ({ label: `${cur === n.name ? "🔘" : "⚪️"} Нода ${n.name}`, value: "single|" + n.name })),
        { label: `${cur === "ecmp" ? "🔘" : "⚪️"} ECMP`, value: "ecmp|" }]);
    if (!v) return;
    const [mode, node] = v.split("|");
    await quick(b, "Балансировка", ["exits", "balance", mode, ...(node ? [node] : [])]);
  }
  ctx.put(h("h1", {}, "🚪 Exit-ноды"), hint("Клиенты выходят в интернет через другие AWG/WG-серверы."), logCard(r.log),
    h("h2", {}, "Ноды"),
    h("div", { class: "card list" }, nodes.length ? nodes.map((n) => h("div", { class: "item", onclick: () =>
      quickAsk(null, `Удалить ноду ${n.name}? Её клиенты перейдут на общий выход.`, `Нода ${n.name} удалена`, ["exits", "del", n.name]) },
    h("div", { class: "dot" + (n.up ? " on" : " blocked") }),
    h("div", { class: "main" }, h("div", { class: "title" }, n.name), h("div", { class: "sub" }, n.up ? "поднята" : "лежит")),
    h("div", { class: "side" }, "🗑"))) : h("div", { class: "empty" }, "Нод нет")),
    btn("➕ Добавить ноду", () => go("/tunnels/exits/add"), "btn-block" + (nodes.length ? "" : " btn-primary")),
    nodes.length ? [h("h2", {}, "Маршруты"),
      h("div", { class: "actions" },
        !up || d.mode !== "all" ? btn("▶️ Все клиенты", () => runJob(ctx, "Маршруты: все клиенты", ["exits", "up", "all"]), up ? null : "btn-primary") : null,
        !up || d.mode !== "peers" ? btn("🎯 Выбранные", () => runJob(ctx, "Маршруты: выбранные клиенты", ["exits", "up", "peers"])) : null,
        up ? btn("⏹ Выключить", (b) => quick(b, "Маршруты выключены", ["exits", "down"])) : null,
        btn("⚖️ Балансировка", balance),
        btn("👥 Клиенты и ноды", () => go("/tunnels/exits/clients")),
        btn("📜 Журнал", () => go("/log/exits"))),
      hint("▶️ — все клиенты через ноды · 🎯 — только выбранные, остальные напрямую")] : null);
});

route(/^\/tunnels\/exits\/add$/, async (ctx) => {
  const name = h("input", { placeholder: "de1", maxlength: 6, autocapitalize: "off", autocomplete: "off" });
  const ta = h("textarea", { placeholder: "[Interface]\n…\n\n[Peer]\nEndpoint = …", style: "min-height:160px" });
  ctx.put(h("h1", {}, "➕ Exit-нода"),
    h("label", {}, "Имя: латиница, цифры, _, до 6 символов"), name,
    h("label", {}, "Клиентский конфиг AWG/WG этой ноды"), fileField(ta), ta,
    hint("Маршрут всего сервера конфиг не заберёт: awg2 ставит Table = off."),
    btn("Добавить", (b) => {
      const n = name.value.trim(), text = ta.value.trim();
      if (!/^[A-Za-z0-9_]{1,6}$/.test(n)) return fail(new Error("Имя: латиница, цифры, _, до 6 символов"));
      if (!text.includes("[Interface]") || !text.includes("Endpoint")) return fail(new Error("Нужен клиентский конфиг с [Interface] и Endpoint"));
      return runJob(ctx, "Exit-нода " + n, ["exits", "add", n], null, { stdin: text + "\n", onBack: back });
    }, "btn-primary btn-block"));
});

// Какой выход у каждого клиента, когда маршруты — «выбранные клиенты»
route(/^\/tunnels\/exits\/clients$/, async (ctx) => {
  const [cl, d] = await Promise.all([loadClients(), call("exits", "status")]);
  const mode = (d && d.mode) || "all", nodes = (d && d.nodes) || [];
  const exitOf = (c) => (mode !== "peers" || c.exit == null ? "shared" : c.exit);
  const label = (v) => ({ off: "напрямую", shared: "общий выход" }[v] || "нода " + v);
  async function pick(c) {
    const cur = exitOf(c);
    const v = await sheet(`🚪 Выход: ${c.name}`, [["off", "Напрямую"], ["shared", "Общий выход"], ...nodes.map((n) => [n.name, "Нода " + n.name])]
      .map(([val, l]) => ({ label: `${cur === val ? "🔘" : "⚪️"} ${l}`, value: val })));
    if (v && v !== cur) await quick(null, "Выход изменён", ["exits", "client", c.name, v]);
  }
  ctx.put(h("h1", {}, "👥 Клиенты и ноды"),
    hint((d && d.up ? "Нажми клиента, чтобы выбрать его выход." : "Маршруты выключены — выбор вступит в силу, когда их включишь.")
      + (mode !== "peers" ? " Выбор переводит маршруты в режим «выбранные клиенты»: остальные остаются на общем выходе." : "")),
    h("div", { class: "card list" }, cl.rows.length ? cl.rows.map((c) => h("div", { class: "item", onclick: () => pick(c) },
      h("div", { class: "main" }, h("div", { class: "title" }, c.name), h("div", { class: "sub" }, c.ip)),
      h("div", { class: "side" }, "→ " + label(exitOf(c))))) : h("div", { class: "empty" }, "Клиентов нет")));
});

// Каскад портов
route(/^\/tunnels\/cascade$/, async (ctx) => {
  const rows = (await call("cascade", "list")) || [];
  ctx.put(h("h1", {}, "🔀 Каскад портов"), hint("Трафик на порт этого сервера уходит на другой сервер."),
    h("div", { class: "card list" }, rows.length ? rows.map((x) => h("div", { class: "item", onclick: () =>
      quickAsk(null, `Удалить правило ${x.proto.toUpperCase()} ${x.in} → ${x.dst}:${x.out}?`, "Правило удалено", ["cascade", "del", x.proto, String(x.in)]) },
    h("div", { class: "dot" + (x.applied ? " on" : " blocked") }),
    h("div", { class: "main" }, h("div", { class: "title" }, `${x.proto.toUpperCase()} ${x.in} → ${x.dst}:${x.out}`),
      h("div", { class: "sub" }, [x.applied ? "применено" : "записано, но в iptables нет", x.comment].filter(Boolean).join(" · "))),
    h("div", { class: "side" }, "🗑"))) : h("div", { class: "empty" }, "Правил нет")),
    btn("➕ Добавить правило", () => go("/tunnels/cascade/add"), "btn-primary btn-block"),
    h("div", { class: "actions", style: "margin-top:8px" },
      rows.length ? btn("🔁 Переприменить", (b) => quick(b, "Правила переприменены", ["cascade", "reapply"])) : null,
      btn("🩺 Диагностика", (b) => busy(b, async () => logSheet("🩺 Каскад", (await callR(["cascade", "diag"])).log))),
      btn("📜 Журнал", () => go("/log/cascade")),
      rows.length ? btn("🧹 Удалить все", (b) => quickAsk(b, "Удалить все правила каскада?", "Правила удалены", ["cascade", "clear"])) : null,
      btn("🗑 Удалить каскад", (b) => quickAsk(b, "Удалить каскад полностью: правила и службу?", "Каскад удалён", ["cascade", "remove"]), "btn-danger")));
});

route(/^\/tunnels\/cascade\/add$/, async (ctx) => {
  let proto = "udp";
  const protoBox = h("div", { class: "chips" });
  const drawP = () => protoBox.replaceChildren(...[["udp", "UDP"], ["tcp", "TCP"], ["both", "UDP и TCP"]].map(([v, l]) =>
    h("button", { class: "chip" + (proto === v ? " on" : ""), onclick: () => { proto = v; drawP(); } }, l)));
  drawP();
  const pin = h("input", { type: "number", min: 1, max: 65535, placeholder: "51820" });
  const dst = h("input", { placeholder: "5.6.7.8", inputmode: "decimal", autocomplete: "off" });
  const pout = h("input", { type: "number", min: 1, max: 65535, placeholder: "тот же" });
  const cm = h("input", { maxlength: 60, placeholder: "например, имя сервера" });
  ctx.put(h("h1", {}, "➕ Правило каскада"),
    h("label", {}, "Протокол — UDP для AWG и WireGuard"), protoBox,
    h("label", {}, "Порт на этом сервере"), pin,
    h("label", {}, "Публичный IPv4 сервера назначения"), dst,
    h("label", {}, "Порт на сервере назначения"), pout,
    h("label", {}, "Комментарий (необязательно)"), cm,
    btn("Добавить", (b) => {
      const a = pin.value.trim(), ip = dst.value.trim(), o = pout.value.trim() || a, c = cm.value.trim();
      if (!validPort(a)) return fail(new Error("Порт на этом сервере — число 1-65535"));
      if (!IP_RE.test(ip)) return fail(new Error("Нужен IPv4, например 5.6.7.8"));
      if (!validPort(o)) return fail(new Error("Порт назначения — число 1-65535"));
      return quick(b, "Правило добавлено", ["cascade", "add", proto, a, ip, o, ...(c ? [c] : [])], () => back());
    }, "btn-primary btn-block"));
});

// Шифрованный DNS
route(/^\/tunnels\/dns$/, async (ctx) => {
  const r = await callR(["dns", "status"]);
  const d = r.data || {}, inst = d.installed;
  const norm = (s) => (s || "").split(/[\s,]+/).filter(Boolean).join(" ");
  const cur = norm(d.upstream);
  async function off(b) {
    const v = await sheet("Выключить шифрованный DNS? Клиенты вернутся к DNS из своих конфигов.",
      [{ label: "⏹ Выключить", value: "off" }, { label: "🗑 Удалить совсем, с dnscrypt-proxy", value: "purge", cls: "bad" }]);
    if (v) await quick(b, "DNS выключен", ["dns", "remove", ...(v === "purge" ? ["purge"] : [])]);
  }
  ctx.put(h("h1", {}, "🔐 Шифрованный DNS"), hint("Запросы клиентов идут через dnscrypt-proxy по DoH, DoT (853) закрыт."),
    logCard(r.log),
    inst ? [h("h2", {}, "Резолверы"),
      h("div", { class: "card list" }, (d.presets || []).map((p) => h("div", { class: "item", onclick: () =>
        (norm(p.names) === cur ? null : quick(null, "Резолверы изменены", ["dns", "upstream", p.names])) },
      h("div", { class: "radio" + (norm(p.names) === cur ? " on" : "") }),
      h("div", { class: "main" }, h("div", { class: "title" }, p.label), h("div", { class: "sub" }, p.names)))),
      h("div", { class: "item", onclick: () => go("/tunnels/dns/manual") }, h("div", { class: "radio" }),
        h("div", { class: "main" }, h("div", { class: "title" }, "✏️ Вручную…"), h("div", { class: "sub" }, "имена из public-resolvers"))))] : null,
    h("div", { class: "actions", style: "margin-top:8px" },
      !inst ? btn("▶️ Включить", () => runJob(ctx, "Шифрованный DNS", ["dns", "install"]), "btn-primary") : null,
      !inst ? btn("⚠️ Принудительно", () => jobAsk(ctx, "Если на сервере работает свой DNS (Pi-hole, Unbound, bind), "
        + "перехват уведёт клиентов мимо него. Включить всё равно?", "Шифрованный DNS", ["dns", "install", "force"])) : null,
      inst ? btn("🔄 Перезапустить", (b) => quick(b, "DNS перезапущен", ["dns", "restart"])) : null,
      btn("📜 Журнал", () => go("/log/dns")),
      inst ? btn("⏹ Выключить", off, "btn-danger") : null),
    inst ? null : hint("⚠️ Принудительно — если на сервере уже работает свой DNS (Pi-hole, Unbound, bind)"));
});

route(/^\/tunnels\/dns\/manual$/, async (ctx) => {
  const d = (await call("dns", "status")) || {};
  const names = h("input", { value: d.upstream || "", placeholder: "cloudflare, google", autocapitalize: "off", autocomplete: "off" });
  ctx.put(h("h1", {}, "✏️ Резолверы"),
    h("label", {}, "Имена через запятую — из списка public-resolvers (github.com/DNSCrypt/dnscrypt-resolvers)"), names,
    btn("Сохранить", (b) => {
      const v = names.value.trim();
      if (!/^[A-Za-z0-9_, -]+$/.test(v)) return fail(new Error("Допустимы латиница, цифры, дефис и запятая"));
      return quick(b, "Резолверы изменены", ["dns", "upstream", v], () => back());
    }, "btn-primary btn-block"));
});

// Строка меню раздела: заголовок, пояснение, «›»
const menuItem = (title, sub, onclick) => h("div", { class: "item", onclick },
  h("div", { class: "main" }, h("div", { class: "title" }, title), sub ? h("div", { class: "sub" }, sub) : null),
  h("div", { class: "side" }, "›"));
// Внешняя ссылка — браузером Telegram, не внутри панели
const extLink = (url, text) => h("a", { href: url, onclick: (ev) => {
  ev.preventDefault();
  if (tg && tg.openLink) tg.openLink(url); else window.open(url, "_blank");
} }, text || url);

// ── Диагностика ───────────────────────────────────────────
route(/^\/diag$/, async (ctx) => {
  const r = await callR(["diag", "status"]);
  ctx.put(h("h1", {}, "🩺 Диагностика"), logCard(r.log),
    btn("🔄 Обновить сводку", () => render(), "btn-block"),
    h("h2", {}, "Проверки"),
    h("div", { class: "card list" },
      menuItem("🌍 Домены мимикрии: мир", "какие домены пула отвечают отсюда", () => runJob(ctx, "Домены мимикрии (мир)", ["diag", "domains", "world"])),
      menuItem("🇷🇺 Домены мимикрии: Россия", "пул для серверов в РФ", () => runJob(ctx, "Домены мимикрии (Россия)", ["diag", "domains", "ru"])),
      menuItem("🎯 Тест мимикрии", "захват первых пакетов клиента", () => go("/diag/sniff")),
      menuItem("🔍 DPI у клиента", "проверка со стороны клиента", () => go("/diag/dpi"))),
    h("h2", {}, "Ещё"),
    h("div", { class: "card list" },
      menuItem("📜 Журналы служб", "последние строки журнала", () => go("/diag/logs")),
      menuItem("🧩 Модуль ядра", "версии, пересборка, откат", () => go("/server/module"))));
});

route(/^\/diag\/logs$/, async (ctx) => {
  ctx.put(h("h1", {}, "📜 Журналы"),
    h("div", { class: "card list" }, Object.entries(LOGS).map(([name, label]) => menuItem(label, name, () => go("/log/" + name)))));
});

route(/^\/diag\/sniff$/, async (ctx) => {
  const rows = (await call("diag", "sniff-list")) || [];
  async function listen(name) {
    if (!await confirmTg(`На устройстве ${name} отключись от VPN. Нажми OK — и в течение 20 секунд подключись снова.`)) return;
    await runJob(ctx, `Тест мимикрии: ${name}`, ["diag", "sniff", name], null, { onBack: back });
  }
  ctx.put(h("h1", {}, "🎯 Тест мимикрии"),
    hint("Сервер 20 секунд слушает первые пакеты клиента и проверяет, видны ли пакеты мимикрии и на что они похожи."),
    rows.length ? [h("h2", {}, "Клиент"),
      h("div", { class: "card list" }, rows.slice(0, 60).map((c) =>
        menuItem(c.name, (c.endpoint || "").replace(/:\d+$/, ""), () => listen(c.name))))]
      : [h("div", { class: "card empty" }, "Нет клиентов, которые уже подключались. Подключись с устройства и обнови."),
        btn("🔄 Обновить", () => render(), "btn-block")]);
});

const DPI_CMD = {
  docker: "docker run --rm -it --pull=always ghcr.io/runnin4ik/dpi-detector:latest",
  python: "git clone https://github.com/Runnin4ik/dpi-detector.git\ncd dpi-detector && python -m pip install -r requirements.txt && python dpi_detector.py",
};
route(/^\/diag\/dpi$/, async (ctx) => {
  const code = (text) => h("pre", { style: "cursor:pointer", onclick: () => copy(text) }, text);
  ctx.put(h("h1", {}, "🔍 DPI у клиента"),
    hint("Запускать на устройстве клиента, не на сервере. Нажми на команду — она скопируется."),
    h("label", {}, "Docker"), code(DPI_CMD.docker),
    h("label", {}, "Python"), code(DPI_CMD.python),
    hint(["Windows и macOS — готовые сборки в ", extLink("https://github.com/Runnin4ik/dpi-detector/releases", "Releases"), "."]),
    h("h2", {}, "Что делать с результатом"),
    h("div", { class: "card small" },
      h("div", {}, "• рабочий у провайдера клиента домен → домен мимикрии (карточка клиента → Мимикрия)"),
      h("div", {}, "• подмена DNS / перехват UDP 53 → Туннели → Шифрованный DNS"),
      h("div", {}, "• обрыв после первых КБ → профиль «AmneziaVPN» и короче I1-I5")),
    hint("Сторонний проект (MIT), awg2 его не ставит."));
});

// ── Бэкапы ────────────────────────────────────────────────
const BACKUP_MAX = 20 * 1024 * 1024;
// «20260930_035321» из метаданных бэкапа → «30.09.2026 03:53»
const fmtStamp = (s) => { const m = /^(\d{4})(\d\d)(\d\d)_(\d\d)(\d\d)/.exec(s || ""); return m ? `${m[3]}.${m[2]}.${m[1]} ${m[4]}:${m[5]}` : s; };
// Отправка бэкапа в чат с отметкой на экране
function sendBackup(path, note) {
  note.textContent = "📥 Отправляю в чат…";
  return post("/api/send", { what: "backup", path }).then(() => {
    note.textContent = "✅ Файл — в чате с ботом. В нём приватные ключи — храни как пароль.";
    haptic();
  }, (e) => { note.textContent = "❌ " + e.message; });
}
async function uploadBackup(file) {
  if (file.size > BACKUP_MAX) throw new Error("Файл больше 20 МБ — это не бэкап awg2");
  const r = await fetch("/api/backup/upload", { method: "POST", body: file,
    headers: { Authorization: "tma " + (tg ? tg.initData : ""), "Content-Type": "application/octet-stream" } });
  const d = await r.json().catch(() => ({}));
  if (!r.ok || d.ok === false) throw new Error(d.error || `HTTP ${r.status}`);
  return d.path;
}

route(/^\/backup$/, async (ctx) => {
  const rows = ((await call("backup", "list")) || []).slice(0, 30);
  // Без accept: на части Android фильтр по типу прячет .tar.gz; что это бэкап, проверит awg2
  const file = h("input", { type: "file", style: "display:none",
    onchange: () => busy(null, async () => {
      const f = file.files[0];
      if (!f) return;
      toast("Загружаю " + f.name + "…", 4000);
      S.restore = { path: await uploadBackup(f), name: f.name };
      go("/backup/restore");
    }) });
  async function pick(b) {
    const v = await sheet(`${b.full ? "📁" : "🗜"} ${b.name}`, [{ label: "📥 Прислать в чат", value: "send" },
      { label: "♻️ Восстановить из него", value: "restore" }]);
    if (v === "send") {
      await busy(null, async () => {
        toast("📥 Отправляю в чат…", 4000);
        await post("/api/send", { what: "backup", path: b.path });
        haptic(); toast("✅ Бэкап — в чате с ботом", 3000);
      });
    } else if (v === "restore") {
      S.restore = { path: b.path, name: b.name };
      go("/backup/restore");
    }
  }
  ctx.put(h("h1", {}, "💾 Бэкапы"),
    hint("Полный бэкап: сервер и клиенты, аккаунт WARP, WG + обфускатор, настройки туннелей. Хранятся в ~/awg_backup на сервере."),
    h("div", { class: "actions" },
      btn("💾 Создать", () => runJob(ctx, "Бэкап", ["backup", "create"], (d) => {
        const note = h("div", { class: "small", style: "margin-top:6px" });
        if (d && d.path) sendBackup(d.path, note);
        return h("div", { class: "card" }, kv("Файл", (d && d.path || "").split("/").pop()), kv("Размер", fmtBytes(d && d.size)), note);
      }), "btn-primary"),
      btn("📤 Из файла", () => file.click())), file,
    h("h2", {}, "На сервере"),
    h("div", { class: "card list" }, rows.length ? rows.map((b) => h("div", { class: "item", onclick: () => pick(b) },
      h("div", { style: "font-size:20px;width:28px;text-align:center;flex:none" }, b.full ? "📁" : "🗜"),
      h("div", { class: "main" }, h("div", { class: "title" }, fmtTime(b.time)),
        h("div", { class: "sub" }, `${b.full ? "полный, каталог" : "архив"} · ${fmtBytes(b.size)}`)),
      h("div", { class: "side" }, "›"))) : h("div", { class: "empty" }, "Бэкапов на сервере нет")),
    hint("📁 — полный бэкап каталогом, 🗜 — архив. Восстановить можно и из архива прежнего бота."));
});

route(/^\/backup\/restore$/, async (ctx) => {
  const rs = S.restore;
  if (!rs) return replace("/backup");
  const d = (await call("backup", "inspect", rs.path)) || {};
  const meta = Object.fromEntries((d.meta || "").split("\n").filter((l) => l.includes("="))
    .map((l) => [l.slice(0, l.indexOf("=")), l.slice(l.indexOf("=") + 1)]));
  const opt = { wgobf: !!d.wgobf, tunnels: !!d.tunnels };
  ctx.put(h("h1", {}, "♻️ Восстановление"),
    h("div", { class: "card" },
      kv("Файл", rs.name),
      meta.timestamp ? kv("Создан", fmtStamp(meta.timestamp)) : null,
      meta.hostname ? kv("Сервер", meta.hostname) : null,
      meta.toolza ? kv("Версия", meta.toolza) : null,
      meta.awg_version ? kv("Протокол", "AWG " + meta.awg_version) : null,
      kv("Клиентов", d.clients || 0),
      kv("WARP", d.warp ? "аккаунт есть" : "нет")),
    h("div", { class: "card warn small" },
      h("div", {}, "Сервер и клиенты восстанавливаются всегда — текущий сервер будет заменён; его awg0.conf сохраняется рядом."),
      h("div", { style: "margin-top:4px" }, "Туннели восстанавливаются выключенными — их включают вручную.")),
    d.wgobf ? switchRow("🛡 Обфускатор", "WG + обфускатор из бэкапа", true, (on) => { opt.wgobf = on; }) : null,
    d.tunnels ? switchRow("🌐 Туннели", "настройки Xray, exit-нод, каскада и DNS", true, (on) => { opt.tunnels = on; }) : null,
    btn("♻️ Восстановить", async () => {
      if (!await confirmTg("Заменить текущий сервер и клиентов данными из бэкапа?")) return;
      S.restore = null;
      await runJob(ctx, "Восстановление из бэкапа", ["backup", "restore", rs.path, ...["wgobf", "tunnels"].filter((k) => opt[k])],
        null, { onBack: () => replace("/backup") });
    }, "btn-danger btn-block"),
    btn("✖️ Отмена", () => { S.restore = null; back(); }, "btn-block"));
});

// ── Обновление ────────────────────────────────────────────
function updateBot(ctx) {
  return jobAsk(ctx, "Обновить бота из канала обновлений? Он перезапустится, панель подождёт и покажет итог.",
    "Обновление бота", ["bot", "update"], () => [
      hint("Панель уже старая — открой её заново, чтобы загрузилась новая версия."),
      btn("🔄 Открыть панель заново", () => location.reload(), "btn-primary btn-block")]);
}

route(/^\/update$/, async (ctx) => {
  const [d, me] = await Promise.all([call("update", "status"), post("/api/me")]);
  const beta = d.channel === "beta", latest = d.available || "";
  async function check(b) {
    await busy(b, async () => {
      const r = await call("update", "check");
      haptic();
      toast(r.newer ? `⬆️ Доступна ${r.latest}` : `Обновлений нет — в канале ${r.latest}`, 3000);
      render();
    });
  }
  async function channel(b) {
    const to = beta ? "stable" : "beta";
    if (to === "beta" && !await confirmTg("Бета — ранние сборки: правки приезжают раньше, но могут быть сырыми. Переключиться?")) return;
    await busy(b, async () => {
      await call("update", "channel", to);
      await call("update", "check").catch(() => null);
      haptic(); toast(to === "beta" ? "Канал: бета" : "Канал: стабильный"); render();
    });
  }
  ctx.put(h("h1", {}, "⬆️ Обновление"),
    h("div", { class: "card" },
      kv("awg2", d.version || "?"),
      kv("Канал", beta ? "🧪 бета — ранние сборки" : "стабильный"),
      kv("Доступна", latest ? h("b", { class: "ok" }, latest) : h("span", { class: "muted" }, "новее нет")),
      kv("Бот", me.bot || "?"),
      h("div", { class: "muted small" }, d.repo || "")),
    latest ? btn(`⬆️ Обновить до ${latest}`, () => runJob(ctx, "Обновление awg2", ["update", "install"], (res) => [
      h("div", { class: "card" }, kv("Установлена", (res && res.version) || latest)),
      hint("Бот обновляется отдельно — из того же канала."),
      btn("🤖 Обновить бота", () => updateBot(ctx), "btn-primary btn-block")]), "btn-ok btn-block") : null,
    h("div", { class: "actions", style: "margin-top:8px" },
      btn("🔎 Проверить", check),
      btn("🤖 Обновить бота", () => updateBot(ctx)),
      btn("♻️ Переустановить", () => jobAsk(ctx, "Поставить версию из канала поверх текущей? Если в канале версия старше — это откат.",
        "Переустановка awg2", ["update", "install", "force"])),
      btn(beta ? "🔀 На стабильный" : "🧪 Бета-канал", channel)),
    hint("♻️ Переустановить — заново из текущего канала, даже без новой версии."));
});

// ── Журналы служб ─────────────────────────────────────────
const LOGS = { manager: "awg2 — действия", install: "компоненты", module: "сборка модуля", awg: "awg0 (awg-quick)",
  expire: "сроки клиентов", warp: "WARP", "warp-health": "WARP health-check", usque: "usque (WARP MASQUE)", xray: "Xray",
  "xray-routing": "маршруты Xray", tun2socks: "tun2socks", exits: "exit-ноды", cascade: "каскад", dns: "dnscrypt-proxy",
  "dns-health": "DNS health-check", wgobf: "WG + обфускатор", bot: "Telegram-бот" };

route(/^\/log\/([a-z0-9-]+)$/, async (ctx, name) => {
  const r = await callR(["log", name, "150"]);
  const pre = h("pre", { style: "max-height:70vh" }, (r.log || "").trim() || "пусто");
  ctx.put(h("h1", {}, "📜 " + (LOGS[name] || name)), pre, btn("🔄 Обновить", () => render(), "btn-block"));
  pre.scrollTop = pre.scrollHeight;
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
