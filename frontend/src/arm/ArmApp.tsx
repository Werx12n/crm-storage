// Boundary «ВебІнтерфейсАРМ»: показатиЗвіт(), показатиЗалишки(), редагуватиДовідник().
import { useCallback, useEffect, useState } from "react";
import { NavLink, Route, Routes, useNavigate } from "react-router-dom";
import { download, get, getUser, logout, post, put } from "../api";
import { Msg, Table, errText, fmt, type Message } from "../components";
import { isGtin } from "../gs1";

const MGR = "warehouse_manager", ADM = "admin", ACC = "accountant", SAL = "sales_manager";
const can = (...roles: string[]) => !!getUser()?.roles.some((r) => roles.includes(r));

const PAGES: [string, string, string[], () => JSX.Element][] = [
  ["", "Панель KPI", [MGR, ACC, ADM], Dashboard],
  ["stock", "Доступні залишки", [SAL, MGR, ACC, ADM], Stock],
  ["receiving", "Приймання (ASN)", [MGR, ADM, ACC], Receiving],
  ["orders", "Замовлення і хвилі", [MGR, ADM, SAL, ACC], Orders],
  ["shipping", "Відвантаження", [MGR, ADM, ACC, SAL], Shipping],
  ["inventory", "Інвентаризація", [MGR, ADM, ACC], Inventory],
  ["reports", "Звіти", [MGR, ACC, ADM], Reports],
  ["directories", "Довідники", [MGR, ADM], Directories],
  ["users", "Користувачі і ролі", [ADM], Users],
  ["labels", "Етикетки", [MGR, ADM], Labels],
  ["integration", "Інтеграція", [MGR, ADM], Integration],
  ["journal", "Журнал", [MGR, ADM], Journal],
];

export function ArmApp() {
  const nav = useNavigate();
  const u = getUser();
  const pages = PAGES.filter((p) => can(...p[2]));
  return (
    <div className="arm">
      <nav>
        <div className="who"><b>WMS · АРМ</b><br />{u?.full_name}</div>
        {pages.map(([path, title]) => (
          <NavLink key={path} to={`/arm/${path}`} end={path === ""}>{title}</NavLink>
        ))}
        {can(MGR) && <NavLink to="/tzd">ТЗД</NavLink>}
        <a href="/docs" target="_blank" rel="noreferrer">API (OpenAPI)</a>
        <a href="#" onClick={(e) => { e.preventDefault(); logout(); nav("/login"); }}>Вийти</a>
      </nav>
      <main>
        <Routes>
          {pages.map(([path, , , C]) => <Route key={path} path={path === "" ? "/" : path} element={<C />} />)}
          <Route path="*" element={pages.length ? (() => { const C = pages[0][3]; return <C />; })() : <p>Немає доступу</p>} />
        </Routes>
      </main>
    </div>
  );
}

function useLoad<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [err, setErr] = useState<Message>(null);
  const reload = useCallback(() => { fn().then((d) => { setData(d); setErr(null); }).catch((e) => setErr({ kind: "err", text: errText(e) })); }, deps); // eslint-disable-line
  useEffect(() => { reload(); }, [reload]);
  return { data, err, reload, setErr };
}

async function openDoc(url: string, body?: unknown) {
  const w = window.open("", "_blank");
  const blobUrl = await download(url, body);
  if (w) w.location.href = blobUrl; else window.location.href = blobUrl;
}

const Badge = ({ s }: { s: string }) => {
  const ok = ["COMPLETED", "DONE", "SHIPPED", "SENT", "PROCESSED", "APPROVED", "PICKED", "DELIVERED"].includes(s);
  const bad = ["FAILED", "ESCALATED", "PARTIAL"].includes(s);
  return <span className={`badge ${ok ? "badge-ok" : bad ? "badge-err" : "badge-warn"}`}>{s}</span>;
};

// ---------- FR-7.1 Панель KPI ----------
function Dashboard() {
  const { data, err, reload } = useLoad(() => get("/api/analytics/kpi"));
  useEffect(() => { const t = setInterval(reload, 10000); return () => clearInterval(t); }, [reload]);
  return (
    <>
      <h1>Панель KPI</h1>
      <p className="muted">Оновлюється кожні 10 с · період {data?.period.from} — {data?.period.to}</p>
      <Msg m={err} />
      <div className="kpis">
        {data?.kpi.map((k: any) => {
          const lowerBetter = ["order_cycle_time", "dock_to_stock", "receiving_discrepancy_rate"].includes(k.code);
          const good = k.value === null ? null : lowerBetter ? k.value <= k.target : k.value >= k.target;
          return (
            <div className="kpi" key={k.code}>
              <div className="t">{k.title}</div>
              <div className="v" style={{ color: good === null ? undefined : good ? "var(--ok)" : "var(--err)" }}>
                {k.value ?? "—"} <small style={{ fontSize: 14 }}>{k.unit}</small></div>
              <div className="t">ціль {lowerBetter ? "≤" : "≥"} {k.target} {k.unit}</div>
            </div>
          );
        })}
      </div>
      {data && (
        <div className="panel"><b>Лічильники:</b>{" "}
          відвантажено замовлень {data.counters.orders_shipped} · відкритих {data.counters.orders_open} · прийнято поставок {data.counters.shipments_received} ·
          рядків відбору {data.counters.pick_lines} · помилок відбору {data.counters.pick_errors} · подій у черзі {data.counters.events_pending} · невдалих {data.counters.events_failed}
        </div>
      )}
    </>
  );
}

// ---------- UC-07 Доступні залишки ----------
function Stock() {
  const [q, setQ] = useState("");
  const [res, setRes] = useState<any>(null);
  const [m, setM] = useState<Message>(null);
  const search = async (text = q) => {
    try { setRes(await get(`/api/stock/available?q=${encodeURIComponent(text)}`)); setM(null); }
    catch (e) { setM({ kind: "err", text: errText(e) }); }
  };
  return (
    <>
      <h1>Доступні залишки</h1>
      <form className="row" onSubmit={(e) => { e.preventDefault(); search(); }}>
        <div style={{ flex: 1 }}><label>Код, GTIN або назва товару</label><input style={{ width: "100%" }} value={q} onChange={(e) => setQ(e.target.value)} autoFocus /></div>
        <button className="btn">Знайти</button>
      </form>
      <Msg m={m} />
      {res && !res.found && (
        <div className="msg msg-warn">{res.message}.{" "}
          {res.suggestions.length ? <>Можливо, ви шукали: {res.suggestions.map((s: any) => (
            <button key={s.code} className="btn btn-sec btn-small" onClick={() => { setQ(s.code); search(s.code); }}>{s.code} {s.name}</button>))}</> : "Схожих позицій немає."}
        </div>
      )}
      {res?.items.map((it: any) => (
        <div className="panel" key={it.product.code}>
          <h3>{it.product.code} · {it.product.name}</h3>
          <div className="kpis">
            <div className="kpi"><div className="t">Доступно до продажу</div><div className="v" style={{ color: "var(--ok)" }}>{it.available} {it.product.unit}</div></div>
            <div className="kpi"><div className="t">Усього / резерв</div><div className="v">{it.quantity} / {it.reserved}</div></div>
            <div className="kpi"><div className="t">Приймання / карантин</div><div className="v">{it.receiving} / {it.quarantine}</div></div>
          </div>
          <Table rows={it.batches} cols={[
            { key: "batch", title: "Партія" }, { key: "expiry_date", title: "Придатний до" },
            { key: "sellable", title: "Термін ОК", render: (r) => r.sellable ? "так" : <span className="badge badge-err">замалий</span> },
            { key: "quantity", title: "Кількість" }, { key: "reserved", title: "Резерв" }, { key: "available", title: "Доступно" },
            { key: "cells", title: "Комірки", render: (r) => r.cells.map((c: any) => `${c.cell}: ${c.quantity}`).join(", ") },
          ]} />
        </div>
      ))}
      {res?.found && <p className="muted">{res.message}. Мінімальний термін придатності: {res.min_expiry_date}.</p>}
    </>
  );
}

// ---------- Приймання ----------
function Receiving() {
  const { data, err, reload } = useLoad(() => get("/api/receiving/shipments"));
  const [sel, setSel] = useState<any>(null);
  const [m, setM] = useState<Message>(null);
  const [asn, setAsn] = useState(`{"asn_number": "ASN-${Date.now() % 100000}", "supplier": "Постачальник", "lines": [{"product_code": "P-001", "quantity": 10, "batch_number": "L1"}]}`);
  const importAsn = async () => {
    try { await post("/api/integration/edi/asn", JSON.parse(asn)); setM({ kind: "ok", text: "ASN імпортовано" }); reload(); }
    catch (e) { setM({ kind: "err", text: errText(e) }); }
  };
  return (
    <>
      <h1>Приймання</h1>
      <Msg m={err} />
      <Table rows={data ?? []} cols={[
        { key: "asn_number", title: "ASN", render: (r) => <a href="#" onClick={(e) => { e.preventDefault(); get(`/api/receiving/shipments/${r.asn_number}`).then(setSel); }}>{r.asn_number}</a> },
        { key: "date", title: "Дата" }, { key: "supplier", title: "Постачальник" },
        { key: "status", title: "Статус", render: (r) => <Badge s={r.status} /> },
        { key: "has_discrepancies", title: "Розбіжності" }, { key: "completed_at", title: "Завершено" },
      ]} />
      {sel && (
        <div className="panel">
          <h3>{sel.asn_number} <Badge s={sel.status} /></h3>
          <Table rows={sel.lines} cols={[{ key: "product_code", title: "Код" }, { key: "product_name", title: "Товар" },
            { key: "batch_number", title: "Партія" }, { key: "expected", title: "Очікувано" }, { key: "accepted", title: "Прийнято" }]} />
          {sel.discrepancy_act && (
            <>
              <h3>Акт розбіжностей {sel.discrepancy_act.number} (ВП-03)</h3>
              <Table rows={sel.discrepancy_act.lines} cols={[{ key: "product_code", title: "Код" }, { key: "product_name", title: "Товар" },
                { key: "expected", title: "Очікувано" }, { key: "accepted", title: "Прийнято" }, { key: "difference", title: "Різниця" }, { key: "kind", title: "Тип" }]} />
              <button className="btn btn-sec no-print" onClick={() => window.print()}>Друк</button>
            </>
          )}
        </div>
      )}
      <div className="panel">
        <h3>Імпорт ASN (ШлюзEDI, FR-1.1)</h3>
        <textarea style={{ width: "100%", minHeight: 90, fontFamily: "monospace" }} value={asn} onChange={(e) => setAsn(e.target.value)} />
        <button className="btn" onClick={importAsn}>Імпортувати</button>
        <Msg m={m} />
      </div>
    </>
  );
}

// ---------- Замовлення і хвилі ----------
function Orders() {
  const { data, err, reload } = useLoad(() => get("/api/picking/orders"));
  const tasks = useLoad(() => get("/api/picking/tasks?status=NEW"));
  const [m, setM] = useState<Message>(null);
  const wave = async () => {
    try { const r = await post("/api/picking/waves", { wave: true }); setM({ kind: "ok", text: `Сформовано ${r.wave}: ${r.orders.join(", ")}` }); reload(); tasks.reload(); }
    catch (e) { setM({ kind: "err", text: errText(e) }); }
  };
  const repl = async () => {
    try { const r = await post("/api/picking/replenishment/check"); setM({ kind: "ok", text: r.created.length ? `Створено завдань на поповнення: ${r.created.join(", ")}` : "Поповнення не потрібне" }); tasks.reload(); }
    catch (e) { setM({ kind: "err", text: errText(e) }); }
  };
  return (
    <>
      <h1>Замовлення</h1>
      <Msg m={err} />
      {can(MGR, ADM) && <div className="row"><button className="btn" onClick={wave}>Сформувати хвилю з зарезервованих</button>
        <button className="btn btn-sec" onClick={repl}>Перевірити поповнення зони відбору</button></div>}
      <Msg m={m} />
      <Table rows={data ?? []} cols={[
        { key: "number", title: "Номер" }, { key: "client", title: "Клієнт" }, { key: "status", title: "Статус", render: (r) => <Badge s={r.status} /> },
        { key: "partial", title: "Частково", render: (r) => r.partial ? <span className="badge badge-err">частково</span> : "—" },
        { key: "wave", title: "Хвиля" },
        { key: "lines", title: "Рядки", render: (r) => r.lines.map((l: any) => `${l.product_code}: ${l.reserved}/${l.quantity}`).join("; ") },
        { key: "created_at", title: "Створено" },
      ]} />
      <h3 style={{ marginTop: 20 }}>Нові завдання</h3>
      <Table rows={tasks.data ?? []} cols={[{ key: "number", title: "Завдання" }, { key: "type", title: "Тип" }, { key: "wave", title: "Хвиля" },
        { key: "lines", title: "Маршрут", render: (r) => r.lines.map((l: any) => l.from_cell).join(" → ") }]} />
    </>
  );
}

// ---------- Відвантаження ----------
function Shipping() {
  const { data, err } = useLoad(() => get("/api/shipping/dispatches"));
  const ramps = useLoad(() => get("/api/shipping/ramps"));
  return (
    <>
      <h1>Відвантаження</h1>
      <Msg m={err} />
      <Table rows={data ?? []} cols={[
        { key: "order_number", title: "Замовлення" }, { key: "client", title: "Клієнт" }, { key: "sscc", title: "SSCC" },
        { key: "ttn_number", title: "ТТН" }, { key: "status", title: "Статус", render: (r) => <Badge s={r.status} /> },
        { key: "ramp", title: "Рампа" }, { key: "slot_start", title: "Слот" },
        { key: "docs", title: "Документи", render: (r) => <>
          <button className="btn btn-sec btn-small" onClick={() => openDoc(`/api/shipping/dispatches/${r.id}/packing-list`)}>Пакувальний лист</button>{" "}
          <button className="btn btn-sec btn-small" onClick={() => openDoc(`/api/shipping/dispatches/${r.id}/label`)}>Етикетка SSCC</button></> },
      ]} />
      <h3 style={{ marginTop: 20 }}>Розклад рамп (FR-4.3)</h3>
      <Table rows={ramps.data ?? []} cols={[{ key: "ramp", title: "Рампа" }, { key: "name", title: "Назва" },
        { key: "slots", title: "Зайняті слоти", render: (r) => r.slots.map((s: string) => fmt(s)).join(", ") || "вільна" }]} />
    </>
  );
}

// ---------- UC-05 Інвентаризація ----------
function Inventory() {
  const { data, err, reload } = useLoad(() => get("/api/inventory"));
  const [zone, setZone] = useState("STORAGE");
  const [cells, setCells] = useState("");
  const [threshold, setThreshold] = useState("2");
  const [sel, setSel] = useState<any>(null);
  const [m, setM] = useState<Message>(null);
  const create = async () => {
    try {
      const body = cells.trim() ? { cells: cells.split(/[\s,;]+/).filter(Boolean), threshold: Number(threshold) } : { zone, threshold: Number(threshold) };
      const r = await post("/api/inventory", body);
      setSel(r); setM({ kind: "ok", text: `План ${r.number} створено: ${r.tasks.length} завдань` }); reload();
    } catch (e) { setM({ kind: "err", text: errText(e) }); }
  };
  const approve = async () => {
    try { const st = await post(`/api/inventory/${sel.number}/approve`); setM({ kind: "ok", text: `Затверджено. Відомість ${st.number}` }); setSel(await get(`/api/inventory/${sel.number}`)); reload(); }
    catch (e) { setM({ kind: "err", text: errText(e) }); }
  };
  return (
    <>
      <h1>Інвентаризація</h1>
      {can(MGR) && (
        <div className="panel">
          <h3>Новий план циклічного перерахунку</h3>
          <div className="row">
            <div><label>Зона</label><select value={zone} onChange={(e) => setZone(e.target.value)}>
              {["STORAGE", "PICKING", "RECEIVING", "QUARANTINE", "SHIPPING"].map((z) => <option key={z}>{z}</option>)}</select></div>
            <div style={{ flex: 1 }}><label>або комірки (через кому)</label><input style={{ width: "100%" }} value={cells} onChange={(e) => setCells(e.target.value)} placeholder="ST-01-01-1, ST-01-02-1" /></div>
            <div><label>Поріг розбіжності</label><input value={threshold} onChange={(e) => setThreshold(e.target.value)} style={{ width: 90 }} /></div>
            <button className="btn" onClick={create}>Створити план</button>
          </div>
        </div>
      )}
      <Msg m={m} /><Msg m={err} />
      <Table rows={data ?? []} cols={[
        { key: "number", title: "Номер", render: (r) => <a href="#" onClick={(e) => { e.preventDefault(); get(`/api/inventory/${r.number}`).then(setSel); }}>{r.number}</a> },
        { key: "date", title: "Дата" }, { key: "zone", title: "Зона" }, { key: "status", title: "Статус", render: (r) => <Badge s={r.status} /> },
        { key: "approved_by", title: "Затвердив" },
      ]} />
      {sel && (
        <div className="panel">
          <h3>{sel.number} <Badge s={sel.status} /></h3>
          <Table rows={sel.tasks.flatMap((t: any) => t.lines.map((l: any) => ({ ...l, task: t.number, type: t.type, cell: t.cell })))} cols={[
            { key: "task", title: "Завдання" }, { key: "type", title: "Тип" }, { key: "cell", title: "Комірка" }, { key: "product_code", title: "Товар" },
            { key: "batch", title: "Партія" }, { key: "book", title: "Облік" }, { key: "counted", title: "Факт" }, { key: "status", title: "Статус" }]} />
          {sel.statement && (
            <>
              <h3>Відомість розбіжностей {sel.statement.number} (ВП-04) · точність {sel.statement.accuracy ?? "—"} %</h3>
              <Table rows={sel.statement.discrepancies} empty="Розбіжностей немає" cols={[{ key: "cell", title: "Комірка" }, { key: "product_code", title: "Товар" },
                { key: "batch", title: "Партія" }, { key: "book", title: "Облік" }, { key: "counted", title: "Факт" }, { key: "difference", title: "Різниця" }]} />
            </>
          )}
          {sel.status === "AWAITING_APPROVAL" && can(MGR) && <button className="btn" onClick={approve}>Затвердити коригування (BRL-02)</button>}
        </div>
      )}
    </>
  );
}

// ---------- UC-06 Звіти ----------
function Reports() {
  const list = useLoad(() => get("/api/analytics/reports"));
  const today = new Date().toISOString().slice(0, 10);
  const monthAgo = new Date(Date.now() - 30 * 864e5).toISOString().slice(0, 10);
  const [type, setType] = useState("stock");
  const [from, setFrom] = useState(monthAgo);
  const [to, setTo] = useState(today);
  const [rep, setRep] = useState<any>(null);
  const [m, setM] = useState<Message>(null);
  const qs = `date_from=${from}&date_to=${to}`;
  const run = async () => {
    try { setRep(await get(`/api/analytics/reports/${type}?${qs}`)); setM(null); } catch (e) { setM({ kind: "err", text: errText(e) }); }
  };
  const exp = async (format: string) => {
    try {
      const url = await download(`/api/analytics/reports/${type}?${qs}&format=${format}`);
      const a = document.createElement("a");
      a.href = url; a.download = `${type}_${from}_${to}.${format}`; a.click();
    } catch (e) { setM({ kind: "err", text: errText(e) }); }
  };
  return (
    <>
      <h1>Звіти</h1>
      <div className="row">
        <div><label>Звіт</label><select value={type} onChange={(e) => setType(e.target.value)}>
          {list.data?.map((r: any) => <option key={r.type} value={r.type}>{r.code}. {r.title}</option>)}</select></div>
        <div><label>З</label><input type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></div>
        <div><label>По</label><input type="date" value={to} onChange={(e) => setTo(e.target.value)} /></div>
        <button className="btn" onClick={run}>Сформувати</button>
        <button className="btn btn-sec" onClick={() => exp("xlsx")}>XLSX</button>
        <button className="btn btn-sec" onClick={() => exp("pdf")}>PDF</button>
      </div>
      <Msg m={m} />
      {rep && (
        <div className="panel">
          <h3>{rep.title}</h3>
          <p className="muted">Період {rep.period.from} — {rep.period.to} · сформовано {fmt(rep.generated_at)}</p>
          {rep.message ? <div className="msg msg-info">{rep.message}</div> :
            <Table rows={rep.rows} cols={rep.columns.map((c: any) => ({ key: c.key, title: c.title }))} />}
        </div>
      )}
    </>
  );
}

// ---------- UC-08 Довідники ----------
const DIR_FIELDS: Record<string, [string, string][]> = {
  products: [["code", "Код"], ["name", "Назва"], ["gtin", "GTIN"], ["unit", "Одиниця"], ["weight", "Вага, кг"], ["abc_class", "ABC"], ["min_pick_level", "Мін. рівень відбору"]],
  cells: [["address", "Адреса"], ["zone", "Зона"], ["capacity", "Місткість, кг"], ["abc_class", "ABC"], ["aisle", "Прохід"], ["rack", "Стелаж"], ["level", "Ярус"], ["warehouse", "Склад"]],
  counterparties: [["code", "Код"], ["name", "Назва"], ["kind", "Тип (SUPPLIER/CLIENT/CARRIER)"]],
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
      setM({ kind: "ok", text: "Збережено" }); setEdit(null); reload();
    } catch (e) { setM({ kind: "err", text: errText(e) }); }
  };
  return (
    <>
      <h1>Довідники</h1>
      <div className="row">{Object.keys(DIR_FIELDS).map((k) => (
        <button key={k} className={`btn ${k === kind ? "" : "btn-sec"}`} onClick={() => { setKind(k); setEdit(null); setM(null); }}>{DIR_TITLES[k]}</button>))}
        <button className="btn" onClick={() => setEdit({})}>+ Додати</button></div>
      <Msg m={m} /><Msg m={err} />
      {edit && (
        <div className="panel">
          <h3>{edit.id ? "Зміна запису" : "Новий запис"}</h3>
          <div className="row">{fields.map(([k, t]) => (
            <div key={k}><label>{t}</label><input value={edit[k] ?? ""} onChange={(e) => setEdit({ ...edit, [k]: e.target.value })} /></div>))}</div>
          <button className="btn" onClick={save}>Зберегти</button> <button className="btn btn-sec" onClick={() => setEdit(null)}>Скасувати</button>
        </div>
      )}
      <Table rows={data ?? []} cols={[...fields.map(([k, t]) => ({ key: k, title: t })),
        { key: "_e", title: "", render: (r: any) => <button className="btn btn-sec btn-small" onClick={() => setEdit({ ...r })}>Змінити</button> }]} />
    </>
  );
}

function Users() {
  const users = useLoad(() => get("/api/admin/directories/users"));
  const roles = useLoad(() => get("/api/admin/roles"));
  const [form, setForm] = useState({ login: "", full_name: "", password: "" });
  const [m, setM] = useState<Message>(null);
  const act = async (fn: () => Promise<unknown>, ok: string) => {
    try { await fn(); setM({ kind: "ok", text: ok }); users.reload(); } catch (e) { setM({ kind: "err", text: errText(e) }); }
  };
  return (
    <>
      <h1>Користувачі і ролі</h1>
      <div className="panel">
        <h3>Новий користувач</h3>
        <div className="row">
          <div><label>Логін</label><input value={form.login} onChange={(e) => setForm({ ...form, login: e.target.value })} /></div>
          <div><label>ПІБ</label><input value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} /></div>
          <div><label>Пароль</label><input type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} /></div>
          <button className="btn" onClick={() => act(() => post("/api/admin/directories/users", form), "Користувача створено")}>Створити</button>
        </div>
      </div>
      <Msg m={m} />
      <Table rows={users.data ?? []} cols={[
        { key: "login", title: "Логін" }, { key: "full_name", title: "ПІБ" },
        { key: "is_active", title: "Активний", render: (r) => <button className="btn btn-sec btn-small" onClick={() => act(() => put(`/api/admin/directories/users/${r.id}`, { is_active: !r.is_active }), "Збережено")}>{r.is_active ? "так" : "ні"}</button> },
        { key: "roles", title: "Ролі", render: (r) => r.roles.map((x: string) => (
          <span key={x} className="badge" style={{ marginRight: 4 }}>{x} <a href="#" title="Відкликати" onClick={(e) => { e.preventDefault(); act(() => post(`/api/admin/users/${r.login}/roles`, { role: x, revoke: true }), "Роль відкликано"); }}>×</a></span>)) },
        { key: "add", title: "Призначити роль", render: (r) => (
          <select value="" onChange={(e) => e.target.value && act(() => post(`/api/admin/users/${r.login}/roles`, { role: e.target.value }), "Роль призначено")}>
            <option value="">—</option>{roles.data?.map((x: any) => <option key={x.name} value={x.name}>{x.title}</option>)}</select>) },
      ]} />
    </>
  );
}

// ---------- Етикетки (FR-1.4) ----------
function Labels() {
  const products = useLoad(() => get("/api/admin/directories/products"));
  const cells = useLoad(() => get("/api/admin/directories/cells"));
  const [selP, setSelP] = useState<string[]>([]);
  const [selC, setSelC] = useState<string[]>([]);
  const [newSscc, setNewSscc] = useState(0);
  const [preview, setPreview] = useState<any[]>([]);
  const [m, setM] = useState<Message>(null);
  const toggle = (arr: string[], set: (x: string[]) => void, v: string) => set(arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v]);
  const body = { products: selP, cells: selC, new_sscc: newSscc };
  const show = async () => {
    try { setPreview(await post("/api/barcodes/sheet/preview", body)); setM(null); } catch (e) { setM({ kind: "err", text: errText(e) }); }
  };
  const pdf = async () => {
    try { await openDoc("/api/barcodes/sheet", { products: selP, cells: selC, sscc: preview.filter((p) => p.kind === "sscc").map((p) => p.value) }); }
    catch (e) { setM({ kind: "err", text: errText(e) }); }
  };
  return (
    <>
      <h1>Етикетки і штрихкоди</h1>
      <div className="panel no-print">
        <div className="row">
          <div style={{ flex: 1 }}><label>Товари → EAN-13 (GTIN)</label>
            <div style={{ maxHeight: 180, overflow: "auto" }}>{products.data?.map((p: any) => (
              <div key={p.code}><input type="checkbox" checked={selP.includes(p.code)} onChange={() => toggle(selP, setSelP, p.code)} /> {p.code} {p.name}</div>))}</div></div>
          <div style={{ flex: 1 }}><label>Комірки → Code128</label>
            <div style={{ maxHeight: 180, overflow: "auto" }}>{cells.data?.map((c: any) => (
              <div key={c.address}><input type="checkbox" checked={selC.includes(c.address)} onChange={() => toggle(selC, setSelC, c.address)} /> {c.address} ({c.zone})</div>))}</div></div>
          <div><label>Нових SSCC для палет</label><input type="number" min={0} max={100} value={newSscc} onChange={(e) => setNewSscc(Number(e.target.value))} style={{ width: 90 }} /></div>
        </div>
        <div className="row">
          <button className="btn" onClick={show}>Переглянути</button>
          <button className="btn btn-sec" onClick={() => window.print()} disabled={!preview.length}>Друк із браузера</button>
          <button className="btn btn-sec" onClick={pdf} disabled={!preview.length}>PDF-аркуш (A4, 3×7)</button>
        </div>
        <Msg m={m} />
      </div>
      <div className="labels">
        {preview.map((l, i) => (
          <div className="label-card" key={i}>
            <div className="t"><b>{l.title}</b><br />{l.subtitle}</div>
            <img alt={l.value} src={`/api/barcodes/${l.kind}/${encodeURIComponent(l.value)}.svg`} />
          </div>
        ))}
      </div>
    </>
  );
}

// ---------- Інтеграція ----------
function Integration() {
  const { data, err, reload } = useLoad(() => get("/api/integration/events?limit=50"));
  const [m, setM] = useState<Message>(null);
  const sync = async () => { try { const r = await post("/api/integration/sync"); setM({ kind: "ok", text: `Оброблено ${r.processed}, помилок ${r.failed}, у черзі ${r.pending}` }); reload(); } catch (e) { setM({ kind: "err", text: errText(e) }); } };
  const toggle = async (svc: string, available: boolean) => { await fetch(`/mock/${svc}/config`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ available }) }); setM({ kind: "info", text: `Mock ${svc}: ${available ? "доступний" : "недоступний"}` }); };
  return (
    <>
      <h1>Інтеграція (outbox)</h1>
      <div className="row">
        <button className="btn" onClick={sync}>Синхронізувати зараз</button>
        <button className="btn btn-sec" onClick={() => toggle("delivery", false)}>Вимкнути mock доставки</button>
        <button className="btn btn-sec" onClick={() => toggle("delivery", true)}>Увімкнути mock доставки</button>
        <button className="btn btn-sec" onClick={() => toggle("erp", false)}>Вимкнути mock ERP</button>
        <button className="btn btn-sec" onClick={() => toggle("erp", true)}>Увімкнути mock ERP</button>
      </div>
      <Msg m={m} /><Msg m={err} />
      <Table rows={data ?? []} cols={[{ key: "id", title: "#" }, { key: "type", title: "Подія" }, { key: "status", title: "Статус", render: (r) => <Badge s={r.status} /> },
        { key: "attempts", title: "Спроб" }, { key: "created_at", title: "Створено" }, { key: "processed_at", title: "Оброблено" }, { key: "last_error", title: "Помилка" }]} />
    </>
  );
}

function Journal() {
  const { data, err } = useLoad(() => get("/api/admin/journal?limit=300"));
  return (
    <>
      <h1>Журнал операцій</h1>
      <Msg m={err} />
      <Table rows={data ?? []} cols={[{ key: "time", title: "Час" }, { key: "user", title: "Користувач" }, { key: "action", title: "Дія" },
        { key: "status", title: "Код" }, { key: "details", title: "Деталі" }]} />
    </>
  );
}
