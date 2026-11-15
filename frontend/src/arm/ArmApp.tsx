// Boundary «ВебІнтерфейсАРМ»: показатиЗвіт(), показатиЗалишки(), редагуватиДовідник().
import { useCallback, useEffect, useState, type ComponentType } from "react";
import { NavLink, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import {
  Barcode, BookOpen, Boxes, ChartColumn, ClipboardCheck, Download, ExternalLink, FileText, Info, LayoutDashboard, ListChecks,
  LogOut, Minus, PackageOpen, Plus, Printer, RefreshCw, ScrollText, Smartphone, Trash2, TrendingDown, TrendingUp, Truck,
  Users as UsersIcon, Warehouse, Waves,
} from "lucide-react";
import { download, get, getUser, logout, post, put } from "../api";
import {
  Alert, DataTable, Empty, Field, PageHead, StatusBadge, Stepper, errText, fmt, statusTitle, toast, toastError, type Message,
} from "../components";
import { isGtin } from "../gs1";

const MGR = "warehouse_manager", ADM = "admin", ACC = "accountant", SAL = "sales_manager";
const can = (...roles: string[]) => !!getUser()?.roles.some((r) => roles.includes(r));
const ROLE_TITLES: Record<string, string> = {
  admin: "Адміністратор системи", warehouse_manager: "Начальник складу", accountant: "Бухгалтер", sales_manager: "Менеджер з продажу",
  receiver: "Комірник-приймальник", forklift_driver: "Водій навантажувача", picker: "Комплектувальник", packer: "Контролер-пакувальник",
  stock_worker: "Працівник складу", integration: "Інтеграція",
};

type Page = { path: string; title: string; group: string; icon: ComponentType; roles: string[]; C: () => JSX.Element };
const PAGES: Page[] = [
  { path: "", title: "Дашборд", group: "Огляд", icon: LayoutDashboard, roles: [MGR, ACC, ADM], C: Dashboard },
  { path: "receiving", title: "Поставки (ASN)", group: "Приймання", icon: PackageOpen, roles: [MGR, ADM, ACC], C: Receiving },
  { path: "stock", title: "Залишки", group: "Розміщення", icon: Warehouse, roles: [SAL, MGR, ACC, ADM], C: Stock },
  { path: "orders", title: "Замовлення і хвилі", group: "Комплектація", icon: ListChecks, roles: [MGR, ADM, SAL, ACC], C: Orders },
  { path: "shipping", title: "Відправлення і рампи", group: "Відвантаження", icon: Truck, roles: [MGR, ADM, ACC, SAL], C: Shipping },
  { path: "inventory", title: "Інвентаризація", group: "Інвентаризація", icon: ClipboardCheck, roles: [MGR, ADM, ACC], C: Inventory },
  { path: "reports", title: "Звіти ВП-01…ВП-10", group: "Звіти", icon: ChartColumn, roles: [MGR, ACC, ADM], C: Reports },
  { path: "integration", title: "Обмін з ERP", group: "Звіти", icon: RefreshCw, roles: [MGR, ADM], C: Integration },
  { path: "labels", title: "Етикетки", group: "Етикетки", icon: Barcode, roles: [MGR, ADM], C: Labels },
  { path: "directories", title: "Довідники", group: "Довідники", icon: BookOpen, roles: [MGR, ADM], C: Directories },
  { path: "users", title: "Користувачі і ролі", group: "Довідники", icon: UsersIcon, roles: [ADM], C: Users },
  { path: "journal", title: "Журнал операцій", group: "Довідники", icon: ScrollText, roles: [MGR, ADM], C: Journal },
];

export function ArmApp() {
  const nav = useNavigate();
  const loc = useLocation();
  const u = getUser();
  const pages = PAGES.filter((p) => can(...p.roles));
  const groups = [...new Set(pages.map((p) => p.group))];
  const current = pages.find((p) => loc.pathname === `/arm/${p.path}`.replace(/\/$/, "") || loc.pathname === `/arm/${p.path}`) ?? pages[0];
  const role = u?.roles.map((r) => ROLE_TITLES[r] ?? r).join(", ");
  const initials = (u?.full_name ?? "?").split(" ").slice(0, 2).map((w) => w[0]).join("");
  return (
    <div className="arm">
      <aside className="sidebar">
        <div className="brand"><div className="logo"><Boxes /></div>WMS · Склад</div>
        <nav className="nav">
          {groups.map((g) => (
            <div key={g} style={{ display: "contents" }}>
              <div className="nav-group">{g}</div>
              {pages.filter((p) => p.group === g).map((p) => (
                <NavLink key={p.path} to={`/arm/${p.path}`} end={p.path === ""}><p.icon />{p.title}</NavLink>
              ))}
            </div>
          ))}
          <div className="nav-group">Інше</div>
          {can(MGR) && <NavLink to="/tzd"><Smartphone />Термінал (ТЗД)</NavLink>}
          <a href="/docs" target="_blank" rel="noreferrer"><ExternalLink />API (OpenAPI)</a>
        </nav>
      </aside>
      <div className="main">
        <header className="topbar">
          <div className="crumb">{current?.group} / <b>{current?.title}</b></div>
          <div className="spacer" />
          <div className="user-chip">
            <div className="avatar">{initials}</div>
            <div className="who"><b>{u?.full_name}</b><small>{role}</small></div>
            <button className="btn btn-ghost btn-sm" title="Вийти" onClick={() => { logout(); nav("/login"); }}><LogOut />Вийти</button>
          </div>
        </header>
        <div className="content">
          <Routes>
            {pages.map((p) => <Route key={p.path} path={p.path === "" ? "/" : p.path} element={<p.C />} />)}
            <Route path="*" element={pages.length ? (() => { const C = pages[0].C; return <C />; })() : <Empty title="Немає доступу" />} />
          </Routes>
        </div>
      </div>
    </div>
  );
}

function useLoad<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [err, setErr] = useState<Message>(null);
  const reload = useCallback(() => {
    fn().then((d) => { setData(d); setErr(null); }).catch((e) => setErr({ kind: "err", text: errText(e) }));
  }, deps); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { reload(); }, [reload]);
  return { data, err, reload };
}

async function openDoc(url: string, body?: unknown) {
  const w = window.open("", "_blank");
  try {
    const blobUrl = await download(url, body);
    if (w) w.location.href = blobUrl; else window.location.href = blobUrl;
  } catch (e) {
    w?.close();
    toastError(e);
  }
}

const isoDay = (d: Date) => d.toISOString().slice(0, 10);
const daysAgo = (n: number) => isoDay(new Date(Date.now() - n * 864e5));

// ===================== Дашборд (ВП-06, FR-7.1) =====================
const TASK_ICON: Record<string, ComponentType> = { PUTAWAY: Warehouse, PICK: ListChecks, COUNT: ClipboardCheck, RECOUNT: ClipboardCheck, REPLENISH: RefreshCw };
const TASK_TITLE: Record<string, string> = { PUTAWAY: "Розміщення", PICK: "Відбір", COUNT: "Перерахунок", RECOUNT: "Повторний перерахунок", REPLENISH: "Поповнення" };

function Dashboard() {
  const cur = useLoad(() => get("/api/analytics/kpi"));
  const prev = useLoad(() => get(`/api/analytics/kpi?date_from=${daysAgo(60)}&date_to=${daysAgo(31)}`));
  const tasks = useLoad(() => get("/api/picking/tasks"));
  const { reload } = cur;
  useEffect(() => { const t = setInterval(reload, 300000); return () => clearInterval(t); }, [reload]);
  const prevBy: Record<string, number | null> = Object.fromEntries((prev.data?.kpi ?? []).map((k: any) => [k.code, k.value]));
  const active = (tasks.data ?? []).filter((t: any) => t.status !== "DONE");
  const c = cur.data?.counters;
  return (
    <>
      <PageHead title="Панель KPI складу" sub={<>ВП-06 · показники табл. 1.1 за {cur.data?.period.from} — {cur.data?.period.to} · оновлюється кожні 5 хв</>}>
        <button className="btn btn-secondary" onClick={() => { reload(); tasks.reload(); toast("info", "Показники оновлено"); }}><RefreshCw />Оновити</button>
      </PageHead>
      <Alert m={cur.err} />
      <div className="kpis">
        {(cur.data?.kpi ?? []).map((k: any) => <KpiCard key={k.code} k={k} prev={prevBy[k.code]} />)}
      </div>
      <div className="grid-2 section">
        <div className="card">
          <div className="card-head"><h3>Активні завдання</h3><span className="chip">{active.length}</span></div>
          {!active.length ? <Empty title="Активних завдань немає" hint="Нові завдання з'являються після приймання, замовлень ERP та планів інвентаризації" /> : (
            <div className="task-list">
              {active.slice(0, 8).map((t: any) => {
                const I = TASK_ICON[t.type] ?? ListChecks;
                const done = t.lines.filter((l: any) => l.status === "DONE" || l.status === "COUNTED").length;
                return (
                  <div className="task-item" key={t.number}>
                    <div className="task-icon"><I /></div>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <b>{TASK_TITLE[t.type] ?? t.type} · {t.number}</b>
                      <div className="small muted">{t.lines.length} ряд. · виконано {done}{t.assignee ? ` · ${t.assignee}` : ""}{t.wave ? ` · ${t.wave}` : ""}</div>
                    </div>
                    <StatusBadge s={t.status} />
                  </div>
                );
              })}
            </div>
          )}
        </div>
        <div className="card">
          <div className="card-head"><h3>Операційні лічильники</h3></div>
          {c && (
            <dl className="dl">
              <dt>Замовлень за період</dt><dd>{c.orders} (відвантажено {c.orders_shipped}, OTIF {c.orders_otif})</dd>
              <dt>Рядків відбору</dt><dd>{c.pick_lines} (з помилками {c.pick_error_lines})</dd>
              <dt>Перевірено позицій</dt><dd>{c.checked_positions}</dd>
              <dt>Зайнято місць</dt><dd>{c.occupied_places} з {c.places}</dd>
              <dt>Оброблено рядків</dt><dd>{c.processed_lines} за {c.man_hours} люд-год</dd>
              <dt>Відвантажено од.</dt><dd>{fmt(c.shipped_qty)} · середній запас {fmt(c.avg_stock)}</dd>
              <dt>Обмін з ERP</dt><dd>у черзі {c.events_pending}, помилок {c.events_failed}</dd>
            </dl>
          )}
        </div>
      </div>
    </>
  );
}

function KpiCard({ k, prev }: { k: any; prev: number | null | undefined }) {
  const has = k.value !== null && k.value !== undefined;
  const better = (a: number, b: number) => (k.better === "min" ? a <= b : a >= b);
  const state = !has || k.target == null ? "k-na" : better(k.value, k.target) ? "k-good" : "k-bad";
  let trend = null;
  if (has && prev !== null && prev !== undefined) {
    const d = Math.round((k.value - prev) * 100) / 100;
    const good = d === 0 ? null : k.better === "min" ? d < 0 : d > 0;
    const I = d > 0 ? TrendingUp : d < 0 ? TrendingDown : Minus;
    trend = <span className={`trend ${good === null ? "flat" : good ? "good" : "bad"}`} title="Порівняно з попередніми 30 днями"><I />{d > 0 ? "+" : ""}{fmt(d)}</span>;
  }
  return (
    <div className={`kpi ${state}`}>
      <div className="k-title">{k.title}<span title={`Формула: ${k.formula}`}><Info /></span></div>
      <div className="k-value">{has ? fmt(k.value) : "n/a"}<small>{has ? k.unit : ""}</small></div>
      <div className="k-foot">
        <span>{k.target != null ? `ціль ${k.better === "min" ? "≤" : "≥"} ${fmt(k.target)} ${k.unit}` : "ціль не задано"}</span>
        {trend ?? <span className="trend flat">—</span>}
      </div>
      <div className="k-formula">{k.formula}</div>
    </div>
  );
}

// ===================== Приймання =====================
const RECEIVING_STEPS = [
  { title: "ASN отримано", hint: "через EDI або вручну" }, { title: "Приймання на ТЗД", hint: "скан GS1, партія, к-сть" },
  { title: "Завершено", hint: "залишки, акт розбіжностей, SSCC" }, { title: "Розміщення", hint: "водій сканує етикетку і комірку" },
];

function Receiving() {
  const { data, err, reload } = useLoad(() => get("/api/receiving/shipments"));
  const products = useLoad(() => get("/api/admin/directories/products"));
  const [sel, setSel] = useState<any>(null);
  const [form, setForm] = useState<{ asn: string; supplier: string; lines: { product_code: string; quantity: string; batch_number: string }[] }>(
    { asn: "", supplier: "", lines: [{ product_code: "", quantity: "", batch_number: "" }] });
  const open = (n: string) => get(`/api/receiving/shipments/${n}`).then(setSel).catch(toastError);
  const importAsn = async () => {
    try {
      const lines = form.lines.filter((l) => l.product_code && l.quantity)
        .map((l) => ({ product_code: l.product_code, quantity: Number(l.quantity), batch_number: l.batch_number || undefined }));
      await post("/api/integration/edi/asn", { asn_number: form.asn, supplier: form.supplier, lines });
      toast("ok", `ASN ${form.asn} зареєстровано — його видно на ТЗД комірника`);
      setForm({ asn: "", supplier: "", lines: [{ product_code: "", quantity: "", batch_number: "" }] });
      reload();
    } catch (e) { toastError(e); }
  };
  const step = sel ? ({ REGISTERED: 1, IN_PROGRESS: 1, COMPLETED: 3 } as Record<string, number>)[sel.status] ?? 0 : 0;
  return (
    <>
      <PageHead title="Поставки (ASN)" sub="UC-01 · очікувані поставки, хід приймання, акти розбіжностей (ВП-03)" />
      <Alert m={err} />
      <DataTable rows={data ?? []} filters={[{ key: "status", title: "Статус", label: statusTitle }]} empty="Поставок немає"
        emptyHint="Зареєструйте ASN нижче або надішліть його через EDI API" cols={[
          { key: "asn_number", title: "ASN", render: (r) => <a href="#" onClick={(e) => { e.preventDefault(); open(r.asn_number); }}>{r.asn_number}</a>, sort: true, value: (r) => r.asn_number },
          { key: "date", title: "Дата" }, { key: "supplier", title: "Постачальник" },
          { key: "status", title: "Статус", render: (r) => <StatusBadge s={r.status} />, value: (r) => r.status },
          { key: "has_discrepancies", title: "Розбіжності", render: (r) => r.status !== "COMPLETED" ? "—" : r.has_discrepancies ? <span className="badge b-warn">є акт</span> : <span className="badge b-ok">немає</span> },
          { key: "completed_at", title: "Завершено" },
        ]} />
      {sel && (
        <div className="card section">
          <div className="card-head"><h2>{sel.asn_number}</h2><StatusBadge s={sel.status} /><div className="spacer" /><span className="muted">{sel.supplier}</span></div>
          <Stepper steps={RECEIVING_STEPS} current={step} />
          <DataTable rows={sel.lines} cols={[{ key: "product_code", title: "Код" }, { key: "product_name", title: "Товар" },
            { key: "batch_number", title: "Партія" }, { key: "expected", title: "Очікувано", num: true },
            { key: "accepted", title: "Прийнято", num: true, render: (r) => <b style={{ color: r.accepted === r.expected ? "var(--ok)" : r.accepted ? "var(--warn)" : undefined }}>{fmt(r.accepted)}</b>, value: (r) => r.accepted }]} />
          {sel.discrepancy_act && (
            <div className="section">
              <div className="card-head"><h3>Акт розбіжностей {sel.discrepancy_act.number} (ВП-03)</h3><div className="spacer" />
                <button className="btn btn-secondary btn-sm no-print" onClick={() => window.print()}><Printer />Друк</button></div>
              <DataTable rows={sel.discrepancy_act.lines} cols={[{ key: "product_code", title: "Код" }, { key: "product_name", title: "Товар" },
                { key: "expected", title: "Очікувано", num: true }, { key: "accepted", title: "Прийнято", num: true },
                { key: "difference", title: "Різниця", num: true, render: (r) => <b style={{ color: r.difference < 0 ? "var(--err)" : "var(--warn)" }}>{r.difference > 0 ? "+" : ""}{fmt(r.difference)}</b>, value: (r) => r.difference },
                { key: "kind", title: "Тип" }]} />
            </div>
          )}
        </div>
      )}
      {can(MGR, ADM) && (
        <div className="card section">
          <div className="card-head"><h3>Зареєструвати ASN вручну</h3><span className="muted small">FR-1.1 · те саме, що надходить від постачальника через EDI</span></div>
          <div className="row">
            <Field label="Номер ASN" hint="Унікальний номер документа постачальника"><input value={form.asn} onChange={(e) => setForm({ ...form, asn: e.target.value })} placeholder="ASN-0100" /></Field>
            <Field label="Постачальник"><input value={form.supplier} onChange={(e) => setForm({ ...form, supplier: e.target.value })} /></Field>
          </div>
          <div className="stack" style={{ marginTop: 16, gap: 8 }}>
            {form.lines.map((l, i) => (
              <div className="row" key={i}>
                <Field label={i ? "" : "Товар"}><select value={l.product_code} onChange={(e) => { const ls = [...form.lines]; ls[i] = { ...l, product_code: e.target.value }; setForm({ ...form, lines: ls }); }}>
                  <option value="">— оберіть —</option>{products.data?.map((p: any) => <option key={p.code} value={p.code}>{p.code} · {p.name}</option>)}</select></Field>
                <Field label={i ? "" : "Очікувана кількість"}><input type="number" min={1} value={l.quantity} style={{ width: 140 }} onChange={(e) => { const ls = [...form.lines]; ls[i] = { ...l, quantity: e.target.value }; setForm({ ...form, lines: ls }); }} /></Field>
                <Field label={i ? "" : "Партія (необов'язково)"}><input value={l.batch_number} onChange={(e) => { const ls = [...form.lines]; ls[i] = { ...l, batch_number: e.target.value }; setForm({ ...form, lines: ls }); }} /></Field>
                {form.lines.length > 1 && <button className="btn btn-ghost" title="Прибрати рядок" onClick={() => setForm({ ...form, lines: form.lines.filter((_, j) => j !== i) })}><Trash2 /></button>}
              </div>
            ))}
          </div>
          <div className="row" style={{ marginTop: 16 }}>
            <button className="btn btn-secondary" onClick={() => setForm({ ...form, lines: [...form.lines, { product_code: "", quantity: "", batch_number: "" }] })}><Plus />Рядок</button>
            <button className="btn" disabled={!form.asn} onClick={importAsn}>Зареєструвати ASN</button>
          </div>
        </div>
      )}
    </>
  );
}

// ===================== Залишки (UC-07, FR-2.3) =====================
function Stock() {
  const [tab, setTab] = useState<"available" | "cells">("available");
  return (
    <>
      <PageHead title="Залишки" sub="UC-07 · доступна кількість (залишок − резерв) за партіями; облік «товар — партія — комірка»" />
      <div className="tabs">
        <button className={tab === "available" ? "active" : ""} onClick={() => setTab("available")}>Доступні до продажу</button>
        {can(MGR, ADM, ACC) && <button className={tab === "cells" ? "active" : ""} onClick={() => setTab("cells")}>По комірках</button>}
      </div>
      {tab === "available" ? <Available /> : <StockByCell />}
    </>
  );
}

function Available() {
  const [q, setQ] = useState("");
  const [res, setRes] = useState<any>(null);
  const search = async (text = q) => {
    try { setRes(await get(`/api/stock/available?q=${encodeURIComponent(text)}`)); } catch (e) { toastError(e); }
  };
  return (
    <>
      <form className="row" onSubmit={(e) => { e.preventDefault(); search(); }}>
        <Field label="Товар" hint="Код (P-001), GTIN або частина назви"><input style={{ width: 360 }} value={q} onChange={(e) => setQ(e.target.value)} autoFocus placeholder="наприклад, молоко" /></Field>
        <button className="btn" disabled={!q.trim()}>Перевірити залишок</button>
      </form>
      {res && !res.found && (
        <div className="card section">
          <Empty title={res.message} hint={res.suggestions.length ? "Можливо, ви шукали:" : "Схожих позицій немає"} />
          <div className="row-c" style={{ justifyContent: "center" }}>
            {res.suggestions.map((s: any) => <button key={s.code} className="btn btn-secondary btn-sm" onClick={() => { setQ(s.code); search(s.code); }}>{s.code} · {s.name}</button>)}
          </div>
        </div>
      )}
      {res?.items.map((it: any) => (
        <div className="card section" key={it.product.code}>
          <div className="card-head"><h2>{it.product.name}</h2><span className="chip">{it.product.code}</span><span className="chip mono">{it.product.gtin}</span></div>
          <div className="kpis" style={{ marginBottom: 16 }}>
            <div className="kpi k-good"><div className="k-title">Можна продати</div><div className="k-value" style={{ color: "var(--ok)" }}>{fmt(it.available)}<small>{it.product.unit}</small></div></div>
            <div className="kpi k-na"><div className="k-title">Усього на складі</div><div className="k-value">{fmt(it.quantity)}<small>{it.product.unit}</small></div></div>
            <div className="kpi k-na"><div className="k-title">Зарезервовано</div><div className="k-value">{fmt(it.reserved)}</div></div>
            <div className="kpi k-na"><div className="k-title">Приймання / карантин</div><div className="k-value">{fmt(it.receiving)} / {fmt(it.quarantine)}</div></div>
          </div>
          <DataTable rows={it.batches} cols={[
            { key: "batch", title: "Партія" }, { key: "expiry_date", title: "Придатний до" },
            { key: "sellable", title: "Термін", render: (r) => r.sellable ? <span className="badge b-ok">достатній</span> : <span className="badge b-err">замалий (BRL-03)</span> },
            { key: "quantity", title: "Кількість", num: true }, { key: "reserved", title: "Резерв", num: true },
            { key: "available", title: "Доступно", num: true, render: (r) => <b>{fmt(r.available)}</b>, value: (r) => r.available },
            { key: "cells", title: "Комірки", render: (r) => r.cells.map((c: any) => `${c.cell}: ${fmt(c.quantity)}`).join(", ") },
          ]} />
        </div>
      ))}
      {res?.found && <p className="muted small section">{res.message}. Мінімальний термін придатності для відвантаження — до {res.min_expiry_date}.</p>}
      {!res && <div className="card section"><Empty title="Введіть товар, щоб побачити доступну кількість" hint="Доступно = залишок − резерв, без карантину і партій із замалим терміном" /></div>}
    </>
  );
}

function StockByCell() {
  const { data, err } = useLoad(() => get("/api/stock"));
  return (
    <>
      <Alert m={err} />
      <DataTable rows={data ?? []} filters={[{ key: "zone", title: "Зона" }]} cols={[
        { key: "cell", title: "Комірка" }, { key: "zone", title: "Зона" }, { key: "product_code", title: "Код" },
        { key: "product_name", title: "Товар" }, { key: "batch", title: "Партія" }, { key: "expiry_date", title: "Придатний до" },
        { key: "quantity", title: "Кількість", num: true }, { key: "reserved", title: "Резерв", num: true }, { key: "available", title: "Доступно", num: true },
      ]} />
    </>
  );
}

// ===================== Замовлення і хвилі =====================
function Orders() {
  const { data, err, reload } = useLoad(() => get("/api/picking/orders"));
  const tasks = useLoad(() => get("/api/picking/tasks?type=PICK"));
  const repl = useLoad(() => get("/api/picking/tasks?type=REPLENISH"));
  const products = useLoad(() => get("/api/admin/directories/products"));
  const ready = (data ?? []).filter((o: any) => ["RESERVED", "PARTIAL"].includes(o.status)).length;
  const emptyLine = { product_code: "", quantity: "" };
  const [form, setForm] = useState<{ number: string; client: string; toWave: boolean; lines: { product_code: string; quantity: string }[] }>(
    { number: "", client: "", toWave: false, lines: [emptyLine] });
  const setLine = (i: number, patch: Partial<{ product_code: string; quantity: string }>) => {
    const ls = [...form.lines]; ls[i] = { ...ls[i], ...patch }; setForm({ ...form, lines: ls });
  };
  const createOrder = async () => {
    try {
      const lines = form.lines.filter((l) => l.product_code && Number(l.quantity) > 0)
        .map((l) => ({ product_code: l.product_code, quantity: Number(l.quantity) }));
      const r = await post("/api/integration/erp/orders", { number: form.number.trim(), client: form.client.trim(), lines, create_task: !form.toWave });
      toast(r.partial ? "info" : "ok", r.partial ? `Замовлення ${r.number}: частковий резерв — товару недостатньо`
        : `Замовлення ${r.number} зарезервовано${r.tasks?.length ? ` · завдання ${r.tasks.join(", ")}` : " · чекає на хвилю"}`);
      setForm({ number: "", client: "", toWave: form.toWave, lines: [emptyLine] });
      reload(); tasks.reload();
    } catch (e) { toastError(e); }
  };
  const wave = async () => {
    try { const r = await post("/api/picking/waves", { wave: true }); toast("ok", `Сформовано хвилю ${r.wave}: ${r.orders.join(", ")}`); reload(); tasks.reload(); }
    catch (e) { toastError(e); }
  };
  const replenish = async () => {
    try { const r = await post("/api/picking/replenishment/check"); toast(r.created.length ? "ok" : "info", r.created.length ? `Створено завдань на поповнення: ${r.created.join(", ")}` : "Поповнення зони відбору не потрібне"); repl.reload(); }
    catch (e) { toastError(e); }
  };
  return (
    <>
      <PageHead title="Замовлення і хвилі" sub="UC-03 · замовлення з ERP резервуються за FEFO; завдання на відбір формуються з оптимальним маршрутом">
        {can(MGR, ADM) && <>
          <button className="btn btn-secondary" onClick={replenish}><RefreshCw />Перевірити поповнення</button>
          <button className="btn" onClick={wave} disabled={!ready} title={ready ? "" : "Немає зарезервованих замовлень без завдань"}><Waves />Сформувати хвилю ({ready})</button>
        </>}
      </PageHead>
      <Alert m={err} />
      <DataTable rows={data ?? []} filters={[{ key: "status", title: "Статус", label: statusTitle }]} empty="Замовлень немає" emptyHint="Замовлення надходять з ERP або створюються формою нижче" cols={[
        { key: "number", title: "Номер" }, { key: "client", title: "Клієнт" },
        { key: "status", title: "Статус", render: (r) => <span className="row-c"><StatusBadge s={r.status} />{r.partial && <span className="badge b-warn">частковий резерв</span>}</span>, value: (r) => r.status },
        { key: "wave", title: "Хвиля" },
        { key: "lines", title: "Рядки (резерв / замовлено)", render: (r) => r.lines.map((l: any) => `${l.product_code}: ${fmt(l.reserved)}/${fmt(l.quantity)}`).join(" · ") },
        { key: "due_at", title: "Строк" }, { key: "created_at", title: "Отримано" },
      ]} />
      <div className="grid-2 section">
        <div className="card"><div className="card-head"><h3>Завдання на відбір</h3></div>
          <DataTable rows={(tasks.data ?? []).filter((t: any) => t.status !== "DONE")} empty="Відкритих завдань немає" cols={[
            { key: "number", title: "Завдання" }, { key: "status", title: "Статус", render: (r) => <StatusBadge s={r.status} />, value: (r) => r.status },
            { key: "wave", title: "Хвиля" }, { key: "route", title: "Маршрут", render: (r) => r.lines.map((l: any) => l.from_cell).join(" → ") }]} /></div>
        <div className="card"><div className="card-head"><h3>Поповнення зони відбору</h3><span className="muted small">FR-3.4</span></div>
          <DataTable rows={(repl.data ?? []).filter((t: any) => t.status !== "DONE")} empty="Поповнення не потрібне" cols={[
            { key: "number", title: "Завдання" }, { key: "status", title: "Статус", render: (r) => <StatusBadge s={r.status} /> },
            { key: "move", title: "Переміщення", render: (r) => r.lines.map((l: any) => `${l.product_code} × ${fmt(l.quantity)}: ${l.from_cell} → ${l.to_cell}`).join("; ") }]} /></div>
      </div>
      {can(MGR, ADM) && (
        <div className="card section">
          <div className="card-head"><h3>Нове замовлення в магазин</h3><span className="muted small">UC-03 · те саме, що надходить з ERP; резерв за FEFO</span></div>
          <div className="row">
            <Field label="Номер замовлення" hint="Унікальний номер"><input value={form.number} onChange={(e) => setForm({ ...form, number: e.target.value })} placeholder="ORD-2001" /></Field>
            <Field label="Магазин (клієнт)"><input value={form.client} onChange={(e) => setForm({ ...form, client: e.target.value })} placeholder="Магазин №5" /></Field>
          </div>
          <div className="stack" style={{ marginTop: 16, gap: 8 }}>
            {form.lines.map((l, i) => (
              <div className="row" key={i}>
                <Field label={i ? "" : "Товар"}><select value={l.product_code} onChange={(e) => setLine(i, { product_code: e.target.value })}>
                  <option value="">— оберіть —</option>{products.data?.map((p: any) => <option key={p.code} value={p.code}>{p.code} · {p.name}</option>)}</select></Field>
                <Field label={i ? "" : "Кількість"}><input type="number" min={1} value={l.quantity} style={{ width: 140 }} onChange={(e) => setLine(i, { quantity: e.target.value })} /></Field>
                {form.lines.length > 1 && <button className="btn btn-ghost" title="Прибрати рядок" onClick={() => setForm({ ...form, lines: form.lines.filter((_, j) => j !== i) })}><Trash2 /></button>}
              </div>
            ))}
          </div>
          <label className="row-c" style={{ marginTop: 16, gap: 8 }}>
            <input type="checkbox" checked={form.toWave} onChange={(e) => setForm({ ...form, toWave: e.target.checked })} />
            Не створювати завдання одразу — додати до наступної хвилі
          </label>
          <div className="row" style={{ marginTop: 16 }}>
            <button className="btn btn-secondary" onClick={() => setForm({ ...form, lines: [...form.lines, emptyLine] })}><Plus />Рядок</button>
            <button className="btn" disabled={!form.number.trim() || !form.lines.some((l) => l.product_code && Number(l.quantity) > 0)} onClick={createOrder}>Створити замовлення</button>
          </div>
        </div>
      )}
    </>
  );
}

// ===================== Відвантаження =====================
const SHIP_STEPS = [
  { title: "Скомплектовано", hint: "товар у зоні відвантаження" }, { title: "Контроль сканом", hint: "контролер на ТЗД" },
  { title: "Відвантажено", hint: "списання, ВП-08, рампа" }, { title: "ТТН", hint: "заявка в службу доставки (ВП-10)" },
];

function Shipping() {
  const { data, err } = useLoad(() => get("/api/shipping/dispatches"));
  const ready = useLoad(() => get("/api/shipping/ready"));
  const ramps = useLoad(() => get("/api/shipping/ramps"));
  return (
    <>
      <PageHead title="Відправлення і рампи" sub="UC-04 · відвантаження можливе лише після повної перевірки скануванням" />
      <div className="card">
        <Stepper steps={SHIP_STEPS} current={-1} />
        <div className="row-c small muted"><Info size={14} />Очікують контролю: <b style={{ color: "var(--text)" }}>{ready.data?.length ?? 0}</b> замовл. — виконується на ТЗД у розділі «Відвантаження».</div>
      </div>
      <Alert m={err} />
      <div className="section">
        <DataTable rows={data ?? []} filters={[{ key: "status", title: "Статус", label: statusTitle }, { key: "ramp", title: "Рампа" }]} empty="Відправлень ще немає" cols={[
          { key: "order_number", title: "Замовлення" }, { key: "client", title: "Клієнт" }, { key: "sscc", title: "SSCC", render: (r) => <span className="mono">{r.sscc}</span>, value: (r) => r.sscc },
          { key: "ttn_number", title: "ТТН" }, { key: "status", title: "Статус", render: (r) => <StatusBadge s={r.status} />, value: (r) => r.status },
          { key: "ramp", title: "Рампа" }, { key: "slot_start", title: "Слот" },
          { key: "docs", title: "ВП-08", render: (r) => <span className="row-c">
            <button className="btn btn-secondary btn-sm" onClick={() => openDoc(`/api/shipping/dispatches/${r.id}/packing-list`)}><FileText />Пакувальний лист</button>
            <button className="btn btn-secondary btn-sm" onClick={() => openDoc(`/api/shipping/dispatches/${r.id}/label`)}><Barcode />SSCC</button></span> },
        ]} />
      </div>
      <div className="card section">
        <div className="card-head"><h3>Розклад рамп</h3><span className="muted small">FR-4.3 · 30-хвилинні слоти</span></div>
        <DataTable rows={ramps.data ?? []} cols={[{ key: "ramp", title: "Рампа" }, { key: "name", title: "Назва" },
          { key: "slots", title: "Зайняті слоти", render: (r) => r.slots.length ? r.slots.map((s: string) => <span key={s} className="chip" style={{ marginRight: 4 }}>{fmt(s)}</span>) : <span className="badge b-ok">вільна</span> }]} />
      </div>
    </>
  );
}

// ===================== Інвентаризація (UC-05) =====================
const INV_STEPS = [
  { title: "План", hint: "зона або комірки, поріг" }, { title: "Перерахунок", hint: "працівник на ТЗД, наосліп" },
  { title: "Повтор", hint: "якщо розбіжність > порогу" }, { title: "Затвердження", hint: "лише начальник складу" },
];

function Inventory() {
  const { data, err, reload } = useLoad(() => get("/api/inventory"));
  const [zone, setZone] = useState("STORAGE");
  const [cells, setCells] = useState("");
  const [threshold, setThreshold] = useState("2");
  const [sel, setSel] = useState<any>(null);
  const create = async () => {
    try {
      const body = cells.trim() ? { cells: cells.split(/[\s,;]+/).filter(Boolean), threshold: Number(threshold) } : { zone, threshold: Number(threshold) };
      const r = await post("/api/inventory", body);
      setSel(r); toast("ok", `План ${r.number} створено: ${r.tasks.length} завдань на перерахунок`); reload();
    } catch (e) { toastError(e); }
  };
  const approve = async () => {
    try { const st = await post(`/api/inventory/${sel.number}/approve`); toast("ok", `Коригування затверджено. Відомість ${st.number}`); setSel(await get(`/api/inventory/${sel.number}`)); reload(); }
    catch (e) { toastError(e); }
  };
  const step = sel ? ({ COUNTING: 1, AWAITING_APPROVAL: 3, APPROVED: 4 } as Record<string, number>)[sel.status] ?? 0 : 0;
  return (
    <>
      <PageHead title="Інвентаризація" sub="UC-05 · циклічний перерахунок без блокування складу; коригування — лише після затвердження (BRL-02)" />
      {can(MGR) && (
        <div className="card">
          <div className="card-head"><h3>Новий план перерахунку</h3></div>
          <div className="row">
            <Field label="Зона" hint="Усі комірки зони із залишками"><select value={zone} onChange={(e) => setZone(e.target.value)} disabled={!!cells.trim()}>
              {[["STORAGE", "Зберігання"], ["PICKING", "Відбір"], ["RECEIVING", "Приймання"], ["QUARANTINE", "Карантин"], ["SHIPPING", "Відвантаження"]].map(([z, t]) => <option key={z} value={z}>{t}</option>)}</select></Field>
            <Field label="або конкретні комірки" hint="Через кому — має пріоритет над зоною"><input style={{ width: 280 }} value={cells} onChange={(e) => setCells(e.target.value)} placeholder="ST-01-01-1, ST-01-02-1" /></Field>
            <Field label="Поріг розбіжності, од." hint="Більше — повторний перерахунок"><input type="number" min={0} value={threshold} onChange={(e) => setThreshold(e.target.value)} style={{ width: 140 }} /></Field>
            <button className="btn" onClick={create}><Plus />Створити план</button>
          </div>
        </div>
      )}
      <Alert m={err} />
      <div className="section">
        <DataTable rows={data ?? []} filters={[{ key: "status", title: "Статус", label: statusTitle }]} empty="Інвентаризацій ще не було" cols={[
          { key: "number", title: "Номер", render: (r) => <a href="#" onClick={(e) => { e.preventDefault(); get(`/api/inventory/${r.number}`).then(setSel).catch(toastError); }}>{r.number}</a>, value: (r) => r.number },
          { key: "date", title: "Дата" }, { key: "zone", title: "Зона" }, { key: "threshold", title: "Поріг", num: true },
          { key: "status", title: "Статус", render: (r) => <StatusBadge s={r.status} />, value: (r) => r.status }, { key: "approved_by", title: "Затвердив" },
        ]} />
      </div>
      {sel && (
        <div className="card section">
          <div className="card-head"><h2>{sel.number}</h2><StatusBadge s={sel.status} /><div className="spacer" />
            {sel.status === "AWAITING_APPROVAL" && can(MGR) && <button className="btn" onClick={approve}>Затвердити коригування</button>}</div>
          <Stepper steps={INV_STEPS} current={step} />
          <DataTable rows={sel.tasks.flatMap((t: any) => t.lines.map((l: any) => ({ ...l, task: t.number, type: t.type, cell: t.cell })))} cols={[
            { key: "task", title: "Завдання" }, { key: "type", title: "Тип", render: (r) => r.type === "RECOUNT" ? "повторний" : "перерахунок" }, { key: "cell", title: "Комірка" },
            { key: "product_code", title: "Товар" }, { key: "batch", title: "Партія" }, { key: "book", title: "За обліком", num: true },
            { key: "counted", title: "Фактично", num: true }, { key: "status", title: "Статус", render: (r) => <StatusBadge s={r.status} />, value: (r) => r.status }]} />
          {sel.statement && (
            <div className="section">
              <div className="card-head"><h3>Відомість розбіжностей {sel.statement.number} (ВП-04)</h3><span className="chip">точність {sel.statement.accuracy ?? "—"} %</span></div>
              <DataTable rows={sel.statement.discrepancies} empty="Розбіжностей немає" cols={[{ key: "cell", title: "Комірка" }, { key: "product_code", title: "Товар" },
                { key: "batch", title: "Партія" }, { key: "book", title: "За обліком", num: true }, { key: "counted", title: "Фактично", num: true },
                { key: "difference", title: "Різниця", num: true }]} />
            </div>
          )}
        </div>
      )}
    </>
  );
}

// ===================== Звіти (UC-06) =====================
function Reports() {
  const list = useLoad(() => get("/api/analytics/reports"));
  const [type, setType] = useState("stock");
  const [from, setFrom] = useState(daysAgo(30));
  const [to, setTo] = useState(isoDay(new Date()));
  const [costs, setCosts] = useState("");
  const [rep, setRep] = useState<any>(null);
  const qs = `date_from=${from}&date_to=${to}${costs ? `&costs=${costs}` : ""}`;
  const run = async (t = type) => { try { setRep(await get(`/api/analytics/reports/${t}?${qs}`)); } catch (e) { toastError(e); } };
  const exp = async (format: string) => {
    try {
      const url = await download(`/api/analytics/reports/${type}?${qs}&format=${format}`);
      const a = document.createElement("a");
      a.href = url; a.download = `${type}_${from}_${to}.${format}`; a.click();
      toast("ok", `Файл ${format.toUpperCase()} сформовано`);
    } catch (e) { toastError(e); }
  };
  const meta = list.data?.find((r: any) => r.type === type);
  return (
    <>
      <PageHead title="Звіти" sub="UC-06 · вихідні повідомлення ВП-01…ВП-10 з експортом у XLSX і PDF" />
      <div className="card">
        <div className="row">
          <Field label="Звіт"><select value={type} onChange={(e) => { setType(e.target.value); setRep(null); }} style={{ minWidth: 380 }}>
            {list.data?.map((r: any) => <option key={r.type} value={r.type}>{r.code} · {r.title}</option>)}</select></Field>
          <Field label="З"><input type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></Field>
          <Field label="По"><input type="date" value={to} onChange={(e) => setTo(e.target.value)} /></Field>
          {type === "kpi" && <Field label="Витрати за період, грн" hint="Для KPI «вартість обробки»"><input type="number" min={0} value={costs} onChange={(e) => setCosts(e.target.value)} style={{ width: 160 }} /></Field>}
          <button className="btn" onClick={() => run()}><ChartColumn />Сформувати</button>
          <button className="btn btn-secondary" onClick={() => exp("xlsx")}><Download />XLSX</button>
          <button className="btn btn-secondary" onClick={() => exp("pdf")}><Download />PDF</button>
        </div>
      </div>
      <div className="card section">
        {!rep ? <Empty icon={<ChartColumn />} title={meta ? `${meta.code} · ${meta.title}` : "Оберіть звіт"} hint="Вкажіть період і натисніть «Сформувати»" /> : (
          <>
            <div className="card-head"><h2>{rep.title}</h2><div className="spacer" /><span className="muted small">{rep.period.from} — {rep.period.to} · сформовано {fmt(rep.generated_at)}</span></div>
            {rep.message ? <Empty title={rep.message} hint="Змініть період або виконайте операції на складі" /> :
              <DataTable rows={rep.rows} cols={rep.columns.map((c: any) => ({ key: c.key, title: c.title, num: typeof rep.rows[0]?.[c.key] === "number" }))} />}
          </>
        )}
      </div>
    </>
  );
}

// ===================== Довідники (UC-08) =====================
const DIR_FIELDS: Record<string, [string, string, string?][]> = {
  products: [["code", "Код"], ["name", "Назва"], ["gtin", "GTIN", "13 цифр з контрольною цифрою GS1"], ["unit", "Одиниця"], ["weight", "Вага, кг"], ["abc_class", "ABC-клас", "A, B або C"], ["min_pick_level", "Мін. рівень у зоні відбору", "Поповнення, якщо менше"]],
  cells: [["address", "Адреса", "Напр. ST-01-02-1"], ["zone", "Зона", "STORAGE, PICKING, RECEIVING, QUARANTINE, SHIPPING"], ["capacity", "Місткість, кг"], ["abc_class", "ABC-клас"], ["aisle", "Прохід"], ["rack", "Стелаж"], ["level", "Ярус"], ["warehouse", "Склад"]],
  counterparties: [["code", "Код"], ["name", "Назва"], ["kind", "Тип", "SUPPLIER, CLIENT або CARRIER"]],
  rules: [["code", "Код"], ["value", "Значення"], ["description", "Опис"]],
  ramps: [["code", "Код"], ["name", "Назва"]],
};
const DIR_TITLES: Record<string, string> = { products: "Товари", cells: "Комірки", counterparties: "Контрагенти", rules: "Правила", ramps: "Рампи" };
const NUMERIC = new Set(["weight", "capacity", "min_pick_level", "aisle", "rack", "level"]);

function Directories() {
  const [kind, setKind] = useState("products");
  const { data, err, reload } = useLoad(() => get(`/api/admin/directories/${kind}`), [kind]);
  const [edit, setEdit] = useState<any>(null);
  const [m, setM] = useState<Message>(null);
  const fields = DIR_FIELDS[kind];
  const save = async () => {
    const body: any = {};
    for (const [k] of fields) if (edit[k] !== undefined && edit[k] !== "") body[k] = NUMERIC.has(k) ? Number(edit[k]) : edit[k];
    if (kind === "products" && body.gtin && !isGtin(String(body.gtin))) return setM({ kind: "err", text: "GTIN: невірна контрольна цифра GS1" });
    try {
      if (edit.id) await put(`/api/admin/directories/${kind}/${edit.id}`, body); else await post(`/api/admin/directories/${kind}`, body);
      toast("ok", "Запис збережено і записано в журнал"); setEdit(null); setM(null); reload();
    } catch (e) { setM({ kind: "err", text: errText(e) }); }
  };
  return (
    <>
      <PageHead title="Довідники" sub="UC-08 · унікальність перевіряється при збереженні; усі зміни потрапляють у журнал">
        <button className="btn" onClick={() => { setEdit({}); setM(null); }}><Plus />Додати запис</button>
      </PageHead>
      <div className="tabs">{Object.keys(DIR_FIELDS).map((k) => (
        <button key={k} className={k === kind ? "active" : ""} onClick={() => { setKind(k); setEdit(null); setM(null); }}>{DIR_TITLES[k]}</button>))}</div>
      <Alert m={err} />
      {edit && (
        <div className="card" style={{ marginBottom: 16 }}>
          <div className="card-head"><h3>{edit.id ? "Зміна запису" : `Новий запис: ${DIR_TITLES[kind].toLowerCase()}`}</h3></div>
          <div className="row">{fields.map(([k, t, h]) => (
            <Field key={k} label={t} hint={h}><input value={edit[k] ?? ""} onChange={(e) => setEdit({ ...edit, [k]: e.target.value })} /></Field>))}</div>
          <Alert m={m} />
          <div className="row" style={{ marginTop: 16 }}><button className="btn" onClick={save}>Зберегти</button><button className="btn btn-secondary" onClick={() => setEdit(null)}>Скасувати</button></div>
        </div>
      )}
      <DataTable rows={data ?? []} filters={kind === "cells" ? [{ key: "zone", title: "Зона" }] : kind === "products" ? [{ key: "abc_class", title: "ABC" }] : []}
        cols={[...fields.map(([k, t]) => ({ key: k, title: t, num: NUMERIC.has(k) })),
          { key: "_e", title: "", sort: false, render: (r: any) => <button className="btn btn-ghost btn-sm" onClick={() => { setEdit({ ...r }); setM(null); }}>Змінити</button> }]} />
    </>
  );
}

function Users() {
  const users = useLoad(() => get("/api/admin/directories/users"));
  const roles = useLoad(() => get("/api/admin/roles"));
  const [form, setForm] = useState({ login: "", full_name: "", password: "" });
  const act = async (fn: () => Promise<unknown>, ok: string) => {
    try { await fn(); toast("ok", ok); users.reload(); } catch (e) { toastError(e); }
  };
  return (
    <>
      <PageHead title="Користувачі і ролі" sub="Змінювати ролі може лише адміністратор (UC-08, FR-6.4)" />
      <div className="card">
        <div className="card-head"><h3>Новий користувач</h3></div>
        <div className="row">
          <Field label="Логін"><input value={form.login} onChange={(e) => setForm({ ...form, login: e.target.value })} /></Field>
          <Field label="ПІБ"><input value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} style={{ width: 280 }} /></Field>
          <Field label="Пароль" hint="Щонайменше 6 символів"><input type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} /></Field>
          <button className="btn" disabled={!form.login || !form.password} onClick={() => act(() => post("/api/admin/directories/users", form), "Користувача створено — призначте йому роль")}><Plus />Створити</button>
        </div>
      </div>
      <div className="section">
        <DataTable rows={users.data ?? []} cols={[
          { key: "login", title: "Логін" }, { key: "full_name", title: "ПІБ" },
          { key: "is_active", title: "Статус", render: (r) => <button className={`badge ${r.is_active ? "b-ok" : "b-err"}`} style={{ border: 0, cursor: "pointer" }} title="Перемкнути"
            onClick={() => act(() => put(`/api/admin/directories/users/${r.id}`, { is_active: !r.is_active }), r.is_active ? "Користувача деактивовано" : "Користувача активовано")}>{r.is_active ? "активний" : "вимкнений"}</button> },
          { key: "roles", title: "Ролі", render: (r) => <span className="row-c">{r.roles.map((x: string) => (
            <span key={x} className="chip">{ROLE_TITLES[x] ?? x}<button className="btn btn-ghost btn-sm" style={{ height: 18, padding: "0 4px" }} title="Відкликати роль"
              onClick={() => act(() => post(`/api/admin/users/${r.login}/roles`, { role: x, revoke: true }), "Роль відкликано")}>×</button></span>))}</span> },
          { key: "add", title: "Призначити роль", sort: false, render: (r) => (
            <select value="" onChange={(e) => e.target.value && act(() => post(`/api/admin/users/${r.login}/roles`, { role: e.target.value }), "Роль призначено")}>
              <option value="">+ роль…</option>{roles.data?.filter((x: any) => !r.roles.includes(x.name)).map((x: any) => <option key={x.name} value={x.name}>{x.title}</option>)}</select>) },
        ]} />
      </div>
    </>
  );
}

// ===================== Етикетки (FR-1.4) =====================
function Labels() {
  const products = useLoad(() => get("/api/admin/directories/products"));
  const cells = useLoad(() => get("/api/admin/directories/cells"));
  const [selP, setSelP] = useState<string[]>([]);
  const [selC, setSelC] = useState<string[]>([]);
  const [newSscc, setNewSscc] = useState(0);
  const [zone, setZone] = useState("");
  const [preview, setPreview] = useState<any[]>([]);
  const toggle = (arr: string[], set: (x: string[]) => void, v: string) => set(arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v]);
  const show = async () => {
    try { const r = await post("/api/barcodes/sheet/preview", { products: selP, cells: selC, new_sscc: newSscc }); setPreview(r); setNewSscc(0); }
    catch (e) { toastError(e); }
  };
  const pdf = () => openDoc("/api/barcodes/sheet", { products: selP, cells: selC, sscc: preview.filter((p) => p.kind === "sscc").map((p) => p.value) });
  const visibleCells = (cells.data ?? []).filter((c: any) => !zone || c.zone === zone);
  const total = selP.length + selC.length + newSscc;
  return (
    <>
      <PageHead title="Етикетки і штрихкоди" sub="EAN-13 для товарів · Code128 для адрес комірок · GS1-128 (SSCC) для палет">
        <button className="btn btn-secondary" disabled={!preview.length} onClick={() => window.print()}><Printer />Друк із браузера</button>
        <button className="btn" disabled={!preview.length} onClick={pdf}><FileText />PDF-аркуш A4</button>
      </PageHead>
      <div className="card no-print">
        <Stepper steps={[{ title: "Оберіть об'єкти", hint: "товари, комірки, нові SSCC" }, { title: "Перегляньте", hint: "контрольні цифри GS1 перевіряються" }, { title: "Друкуйте", hint: "браузер або PDF 3×7" }]} current={preview.length ? 2 : total ? 1 : 0} />
        <div className="grid-2">
          <div>
            <div className="card-head"><h3>Товари → EAN-13</h3><div className="spacer" /><button className="btn btn-ghost btn-sm" onClick={() => setSelP(selP.length ? [] : (products.data ?? []).map((p: any) => p.code))}>{selP.length ? "Зняти всі" : "Обрати всі"}</button></div>
            <div className="pick-list">{products.data?.map((p: any) => (
              <label key={p.code}><input type="checkbox" checked={selP.includes(p.code)} onChange={() => toggle(selP, setSelP, p.code)} /><b>{p.code}</b> {p.name}</label>))}</div>
          </div>
          <div>
            <div className="card-head"><h3>Комірки → Code128</h3><div className="spacer" />
              <select value={zone} onChange={(e) => setZone(e.target.value)} style={{ height: 28 }}><option value="">усі зони</option>{["STORAGE", "PICKING", "RECEIVING", "QUARANTINE", "SHIPPING"].map((z) => <option key={z}>{z}</option>)}</select>
              <button className="btn btn-ghost btn-sm" onClick={() => setSelC(selC.length ? [] : visibleCells.map((c: any) => c.address))}>{selC.length ? "Зняти всі" : "Обрати всі"}</button></div>
            <div className="pick-list">{visibleCells.map((c: any) => (
              <label key={c.address}><input type="checkbox" checked={selC.includes(c.address)} onChange={() => toggle(selC, setSelC, c.address)} /><b>{c.address}</b> <span className="muted">{c.zone}</span></label>))}</div>
          </div>
        </div>
        <div className="row" style={{ marginTop: 16 }}>
          <Field label="Нові SSCC для палет" hint="Генеруються з контрольною цифрою GS1"><input type="number" min={0} max={100} value={newSscc} onChange={(e) => setNewSscc(Number(e.target.value))} style={{ width: 140 }} /></Field>
          <button className="btn" disabled={!total} onClick={show}>Переглянути {total ? `(${total})` : ""}</button>
        </div>
      </div>
      <div className="section">
        {!preview.length ? <div className="card no-print"><Empty icon={<Barcode />} title="Етикетки з'являться тут" hint="Оберіть товари або комірки і натисніть «Переглянути»" /></div> : (
          <div className="labels">
            {preview.map((l, i) => (
              <div className="label-card" key={i}>
                <div className="t"><b>{l.title}</b><br />{l.subtitle}</div>
                <img alt={l.value} src={`/api/barcodes/${l.kind}/${encodeURIComponent(l.value)}.svg`} />
              </div>
            ))}
          </div>
        )}
      </div>
    </>
  );
}

// ===================== Інтеграція (FR-6.2, ВП-09) =====================
function Integration() {
  const { data, err, reload } = useLoad(() => get("/api/integration/events?limit=100"));
  const files = useLoad(() => get("/api/integration/erp/operations-files"));
  const sync = async () => { try { const r = await post("/api/integration/sync"); toast("ok", `Оброблено ${r.processed}, помилок ${r.failed}, у черзі ${r.pending}`); reload(); files.reload(); } catch (e) { toastError(e); } };
  const file = async () => { try { const r = await post("/api/integration/erp/operations-file"); toast(r.file_name ? "ok" : "info", r.file_name ? `Сформовано ${r.file_name} (${r.count} операцій)` : r.message); files.reload(); reload(); } catch (e) { toastError(e); } };
  const toggle = async (svc: string, available: boolean) => {
    await fetch(`/mock/${svc}/config`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ available }) });
    toast(available ? "ok" : "warn", `Mock ${svc === "erp" ? "ERP" : "служби доставки"}: ${available ? "доступний" : "недоступний"}`);
  };
  return (
    <>
      <PageHead title="Обмін з ERP і службою доставки" sub="Outbox: події обробляє воркер; файл операцій ВП-09 — кожні 15 хв">
        <button className="btn btn-secondary" onClick={file}><FileText />Сформувати файл ВП-09</button>
        <button className="btn" onClick={sync}><RefreshCw />Синхронізувати зараз</button>
      </PageHead>
      <div className="card">
        <div className="card-head"><h3>Імітація збоїв</h3><span className="muted small">UC-04 4а: заявка ставиться в чергу і надсилається повторно</span></div>
        <div className="row-c">
          <button className="btn btn-secondary btn-sm" onClick={() => toggle("delivery", false)}>Вимкнути доставку</button>
          <button className="btn btn-secondary btn-sm" onClick={() => toggle("delivery", true)}>Увімкнути доставку</button>
          <button className="btn btn-secondary btn-sm" onClick={() => toggle("erp", false)}>Вимкнути ERP</button>
          <button className="btn btn-secondary btn-sm" onClick={() => toggle("erp", true)}>Увімкнути ERP</button>
        </div>
      </div>
      <div className="card section">
        <div className="card-head"><h3>Файли операцій для ERP (ВП-09)</h3></div>
        <DataTable rows={files.data ?? []} empty="Файлів ще немає" cols={[{ key: "file_name", title: "Файл", render: (r) => <span className="mono">{r.file_name}</span>, value: (r) => r.file_name },
          { key: "count", title: "Операцій", num: true }, { key: "generated_at", title: "Сформовано" },
          { key: "status", title: "Передача", render: (r) => <StatusBadge s={r.status} />, value: (r) => r.status },
          { key: "dl", title: "", sort: false, render: (r) => <button className="btn btn-ghost btn-sm" onClick={() => openDoc(`/api/integration/erp/operations-files/${r.id}`)}><Download />JSON</button> }]} />
      </div>
      <Alert m={err} />
      <div className="section">
        <DataTable rows={data ?? []} filters={[{ key: "status", title: "Статус", label: statusTitle }, { key: "type", title: "Подія" }]} cols={[
          { key: "id", title: "#", num: true }, { key: "type", title: "Подія" }, { key: "status", title: "Статус", render: (r) => <StatusBadge s={r.status} />, value: (r) => r.status },
          { key: "attempts", title: "Спроб", num: true }, { key: "created_at", title: "Створено" }, { key: "processed_at", title: "Оброблено" }, { key: "last_error", title: "Помилка" }]} />
      </div>
    </>
  );
}

function Journal() {
  const { data, err } = useLoad(() => get("/api/admin/journal?limit=500"));
  return (
    <>
      <PageHead title="Журнал операцій" sub="FR-6.4 · усі зміни даних, входи і відмови" />
      <Alert m={err} />
      <DataTable rows={data ?? []} filters={[{ key: "user", title: "Користувач" }]} cols={[
        { key: "time", title: "Час" }, { key: "user", title: "Користувач" }, { key: "action", title: "Дія" },
        { key: "status", title: "Код", render: (r) => r.status ? <span className={`badge ${r.status < 300 ? "b-ok" : r.status < 500 ? "b-warn" : "b-err"}`}>{r.status}</span> : "—", value: (r) => r.status },
        { key: "details", title: "Деталі" }]} />
    </>
  );
}
