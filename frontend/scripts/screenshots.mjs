// Скріншоти основних екранів (Playwright, встановлений Chrome/Chromium).
// Використання: WMS_URL=http://localhost:4173 node scripts/screenshots.mjs [вихідна_папка]
// Скрипт заповнює демо-стенд операціями через API, тож запускайте на окремому (тимчасовому) стенді.
import { chromium } from "playwright-core";
import { existsSync, mkdirSync } from "node:fs";
import path from "node:path";

const BASE = process.env.WMS_URL ?? "http://localhost:4173";
const OUT = path.resolve(process.argv[2] ?? "../docs/screenshots");
const CHROME = process.env.CHROME_PATH ?? [
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  "/opt/pw-browsers/chromium",
  "/usr/bin/chromium",
].find((p) => existsSync(p));
mkdirSync(OUT, { recursive: true });

const cd = (b) => { let s = 0; [...b].reverse().forEach((d, i) => { s += Number(d) * (i % 2 ? 1 : 3); }); return String((10 - (s % 10)) % 10); };
const gtin = (i) => { const b = "4820000" + String(i).padStart(5, "0"); return b + cd(b); };

async function api(method, url, body, login) {
  const tok = login ? await token(login) : null;
  const r = await fetch(BASE + url, { method, headers: { "Content-Type": "application/json", ...(tok ? { Authorization: `Bearer ${tok}` } : {}) },
    body: body ? JSON.stringify(body) : undefined });
  const data = await r.json().catch(() => null);
  if (!r.ok) throw new Error(`${method} ${url}: ${r.status} ${JSON.stringify(data)}`);
  return data;
}
const tokens = {};
async function token(login) {
  if (!tokens[login]) {
    const r = await fetch(BASE + "/api/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ login, password: "demo123" }) });
    tokens[login] = await r.json();
  }
  return tokens[login].access_token;
}

async function populate() {
  // приймання ASN-0002 з недостачею → акт, етикетки
  await api("POST", "/api/receiving/shipments/ASN-0002/start", null, "receiver");
  await api("POST", "/api/receiving/shipments/ASN-0002/scan", { code: gtin(8), quantity: 55, batch_number: "B2708B" }, "receiver");
  await api("POST", "/api/receiving/shipments/ASN-0002/scan", { code: gtin(12), quantity: 80, batch_number: "G2803B" }, "receiver");
  const rec = await api("POST", "/api/receiving/shipments/ASN-0002/complete", null, "receiver");
  const s = rec.labels[0].sscc;
  const sug = await api("POST", `/api/putaway/${s}/suggest`, null, "driver");
  await api("POST", `/api/putaway/${s}/confirm`, { cell: sug.cell.address }, "driver");
  // відбір ORD-1001 з однією помилкою скану, контроль і відвантаження
  const { task } = await api("POST", "/api/picking/tasks/next", null, "picker");
  const first = task.lines[0];
  await api("POST", `/api/picking/tasks/${task.number}/confirm`, { cell: first.from_cell, product: gtin(9) }, "picker").catch(() => null);
  for (const l of task.lines) await api("POST", `/api/picking/tasks/${task.number}/confirm`, { cell: l.from_cell, product: l.gtin, quantity: l.quantity }, "picker");
  const order = await api("GET", "/api/picking/orders/ORD-1001", null, "manager");
  for (const l of order.lines) await api("POST", "/api/shipping/orders/ORD-1001/check", { code: l.gtin, quantity: l.picked }, "packer");
  await api("POST", "/api/shipping/orders/ORD-1001/ship", null, "packer");
  await api("POST", "/api/integration/sync", null, "erp");
  await api("POST", "/api/integration/erp/operations-file", null, "erp");
  await api("POST", "/api/integration/sync", null, "erp");
  // хвиля з ORD-1002/1003
  await api("POST", "/api/picking/waves", { wave: true }, "manager");
  // інвентаризація
  const inv = await api("POST", "/api/inventory", { cells: ["ST-04-03-1", "ST-04-04-1"], threshold: 2 }, "manager");
  await api("POST", "/api/inventory/count", { cell: "ST-04-03-1", quantity: 120 }, "counter");
  await api("POST", "/api/inventory/count", { cell: "ST-04-04-1", quantity: 199 }, "counter");
  await api("POST", `/api/inventory/${inv.number}/approve`, null, "manager");
  // ASN-0001: приймання в процесі
  await api("POST", "/api/receiving/shipments/ASN-0001/start", null, "receiver");
  await api("POST", "/api/receiving/shipments/ASN-0001/scan", { code: gtin(1), quantity: 60, batch_number: "L2702D" }, "receiver");
}

async function loginAs(page, login) {
  await page.goto(BASE + "/login");
  const t = await token(login);
  await page.evaluate(([tk, u]) => { localStorage.setItem("wms.token", tk); localStorage.setItem("wms.user", JSON.stringify(u)); }, [t, tokens[login].user]);
}

const browser = await chromium.launch({ executablePath: CHROME, headless: true });
try {
  if (!process.env.SKIP_POPULATE) await populate();
  const desk = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2, locale: "uk-UA" });
  const page = await desk.newPage();
  const shot = async (name, full = false) => { await page.waitForTimeout(600); await page.screenshot({ path: path.join(OUT, name), fullPage: full }); console.log("✓", name); };

  await page.goto(BASE + "/login");
  await page.waitForSelector("text=Демо-ролі");
  await shot("01-login.png");

  await loginAs(page, "manager");
  await page.goto(BASE + "/arm");
  await page.waitForSelector(".kpi");
  await page.waitForSelector(".task-item, .empty");
  await shot("02-dashboard.png");

  await page.goto(BASE + "/arm/receiving");
  await page.click("text=ASN-0001");
  await page.waitForSelector(".stepper");
  await page.locator(".stepper").scrollIntoViewIfNeeded();
  await shot("03-receiving.png");

  await page.goto(BASE + "/arm/labels");
  await page.waitForSelector(".pick-list label");
  const plabels = page.locator(".pick-list").first().locator("label");
  for (const i of [0, 4, 5]) await plabels.nth(i).click();
  const clabels = page.locator(".pick-list").nth(1).locator("label");
  for (const i of [0, 1]) await clabels.nth(i).click();
  await page.fill("input[type=number]", "1");
  await page.click("button:has-text('Переглянути')");
  await page.waitForSelector(".label-card img");
  await page.waitForFunction(() => [...document.querySelectorAll(".label-card img")].every((i) => i.complete));
  await shot("04-labels.png");

  await page.goto(BASE + "/arm/reports");
  await page.waitForSelector("select option", { state: "attached" });
  await page.selectOption("select", "movement");
  await page.click("button:has-text('Сформувати')");
  await page.waitForSelector("table");
  await shot("05-report.png");

  await page.selectOption("select", "kpi");
  await page.click("button:has-text('Сформувати')");
  await page.waitForSelector("text=Формула");
  await shot("06-report-kpi.png");

  await page.goto(BASE + "/arm/orders");
  await page.waitForSelector("table");
  await shot("07-orders.png");

  // ТЗД — мобільний розмір
  const mob = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 3, isMobile: true, hasTouch: true, locale: "uk-UA" });
  const m = await mob.newPage();
  const mshot = async (name) => { await m.waitForTimeout(600); await m.screenshot({ path: path.join(OUT, name) }); console.log("✓", name); };
  await m.goto(BASE + "/login");
  const tk = await token("manager");
  await m.evaluate(([t, u]) => { localStorage.setItem("wms.token", t); localStorage.setItem("wms.user", JSON.stringify(u)); }, [tk, tokens.manager.user]);
  await m.goto(BASE + "/tzd");
  await m.waitForSelector(".tile");
  await mshot("10-tzd-menu.png");

  await m.goto(BASE + "/tzd/receive");
  await m.click("text=ASN-0001");
  await m.waitForSelector(".scan-box input");
  await m.fill("input[aria-label='Партія']", "M2703B");
  await m.fill("input[aria-label='Кількість']", "10");
  await m.fill(".scan-box input", gtin(5));
  await m.press(".scan-box input", "Enter");
  await m.waitForSelector(".feedback.ok");
  await mshot("11-tzd-receive-ok.png");
  await m.fill(".scan-box input", gtin(1).slice(0, -1) + ((Number(gtin(1).slice(-1)) + 1) % 10));
  await m.press(".scan-box input", "Enter");
  await m.waitForSelector(".feedback.err");
  await mshot("12-tzd-receive-error.png");

  await m.goto(BASE + "/tzd/pick");
  await m.click("button:has-text('Отримати завдання')");
  await m.waitForSelector(".target");
  await mshot("13-tzd-pick.png");
  await desk.close();
  await mob.close();
} finally {
  await browser.close();
}
