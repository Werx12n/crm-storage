// Boundary «ЕкранТЗД»: показатиЗавдання(), сканувати(код), підтвердити(). Мобільний макет, кроки, великий відгук.
import { useCallback, useEffect, useState, type ComponentType, type ReactNode } from "react";
import { Link, NavLink, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import {
  AlertTriangle, ArrowLeft, CheckCircle2, ChevronRight, ClipboardCheck, Home, ListChecks, LogOut, PackageOpen, ScanBarcode,
  Truck, Warehouse, XCircle,
} from "lucide-react";
import { ApiError, get, getUser, isQueued, logout, post, postOffline } from "../api";
import { Empty, OfflineBanner, ScanInput, errText, fmt } from "../components";
import { parseGs1 } from "../gs1";

type Section = { path: string; title: string; short: string; hint: string; icon: ComponentType; roles: string[] };
const SECTIONS: Section[] = [
  { path: "receive", title: "Приймання", short: "Приймання", hint: "Скан товарів за ASN", icon: PackageOpen, roles: ["receiver"] },
  { path: "putaway", title: "Розміщення", short: "Розміщ.", hint: "Етикетка SSCC → комірка", icon: Warehouse, roles: ["forklift_driver"] },
  { path: "pick", title: "Відбір", short: "Відбір", hint: "Завдання за маршрутом", icon: ListChecks, roles: ["picker"] },
  { path: "ship", title: "Контроль і відвантаження", short: "Відвант.", hint: "Перевірка сканом, SSCC", icon: Truck, roles: ["packer"] },
  { path: "count", title: "Перерахунок", short: "Підрахунок", hint: "Комірка → фактична к-сть", icon: ClipboardCheck, roles: ["stock_worker"] },
];
const allowed = () => {
  const u = getUser();
  return SECTIONS.filter((s) => u?.roles.some((r) => s.roles.includes(r) || r === "warehouse_manager"));
};

type Fb = { kind: "ok" | "err" | "warn" | "info"; text: string } | null;

function Feedback({ fb }: { fb: Fb }) {
  if (!fb) return null;
  const I = fb.kind === "ok" ? CheckCircle2 : fb.kind === "err" ? XCircle : AlertTriangle;
  return <div className={`feedback ${fb.kind}`} role={fb.kind === "err" ? "alert" : "status"}><I /><span>{fb.text}</span></div>;
}

function useFeedback(): [Fb, (kind: NonNullable<Fb>["kind"], text: string) => void, () => void] {
  const [fb, setFb] = useState<Fb>(null);
  const show = useCallback((kind: NonNullable<Fb>["kind"], text: string) => {
    setFb({ kind, text });
    if (kind === "err" && "vibrate" in navigator) navigator.vibrate?.([120, 60, 120]);
  }, []);
  return [fb, show, () => setFb(null)];
}

function StepBanner({ n, total, title, sub }: { n: number; total: number; title: string; sub?: ReactNode }) {
  return (
    <div className="step-banner">
      <div className="n">{n}</div>
      <div><div className="t">{title}</div><div className="s">Крок {n} з {total}{sub ? <> · {sub}</> : null}</div></div>
    </div>
  );
}

function Progress({ done, total }: { done: number; total: number }) {
  const pct = total ? Math.min(100, Math.round((100 * done) / total)) : 0;
  return <div className="progress" aria-label={`Виконано ${pct}%`}><div style={{ width: `${pct}%` }} /></div>;
}

export function TzdApp() {
  const nav = useNavigate();
  const loc = useLocation();
  const u = getUser();
  const secs = allowed();
  const current = SECTIONS.find((s) => loc.pathname.startsWith(`/tzd/${s.path}`));
  return (
    <div className="tzd">
      <header className="tzd-top">
        {current ? <button onClick={() => nav("/tzd")} aria-label="Назад"><ArrowLeft /></button> : <ScanBarcode />}
        <h1>{current?.title ?? "Термінал"}</h1>
        <div className="who">{u?.login}<br /><span style={{ opacity: .8 }}>{u?.full_name?.split(" (")[0]}</span></div>
        <button onClick={() => { logout(); nav("/login"); }} aria-label="Вийти"><LogOut /></button>
      </header>
      <OfflineBanner />
      <main className="tzd-body">
        <Routes>
          <Route index element={<Menu />} />
          <Route path="receive" element={<Receive />} />
          <Route path="putaway" element={<Putaway />} />
          <Route path="pick" element={<Pick />} />
          <Route path="ship" element={<Ship />} />
          <Route path="count" element={<Count />} />
        </Routes>
      </main>
      <nav className="tzd-nav">
        <NavLink to="/tzd" end><Home /><span>Головна</span></NavLink>
        {secs.map((s) => <NavLink key={s.path} to={`/tzd/${s.path}`}><s.icon /><span>{s.short}</span></NavLink>)}
      </nav>
    </div>
  );
}

function Menu() {
  const secs = allowed();
  return (
    <>
      <div><h2 style={{ marginBottom: 4 }}>Оберіть операцію</h2><span className="muted small">Термінал підказує, що сканувати на кожному кроці</span></div>
      {secs.length ? (
        <div className="tiles">
          {secs.map((s) => <Link key={s.path} to={`/tzd/${s.path}`} className="tile"><div className="ti"><s.icon /></div><b>{s.title}</b><small>{s.hint}</small></Link>)}
        </div>
      ) : <Empty title="Для вашої ролі немає операцій на терміналі" />}
      <div className="card small muted">Сканер працює як клавіатура (Enter — підтвердити). Камера телефона — кнопка поруч із полем сканування (потрібен HTTPS).
        Без зв'язку операції зберігаються і надсилаються пізніше.</div>
    </>
  );
}

// ---------- UC-01 Приймання ----------
function Receive() {
  const [list, setList] = useState<any[] | null>(null);
  const [sh, setSh] = useState<any>(null);
  const [batch, setBatch] = useState("");
  const [qty, setQty] = useState("");
  const [result, setResult] = useState<any>(null);
  const [fb, show, clear] = useFeedback();
  useEffect(() => {
    get("/api/receiving/shipments").then((l) => setList(l.filter((s: any) => s.status !== "COMPLETED"))).catch((e) => show("err", errText(e)));
  }, [result, show]);
  const open = async (n: string) => {
    try { setSh(await post(`/api/receiving/shipments/${n}/start`)); setResult(null); clear(); } catch (e) { show("err", errText(e)); }
  };
  const refresh = async () => setSh(await get(`/api/receiving/shipments/${sh.asn_number}`));
  const scan = async (code: string) => {
    const p = parseGs1(code);
    const body = { code, quantity: qty ? Number(qty) : p.qty ?? undefined, batch_number: batch || p.batch || undefined, expiry_date: p.expiry };
    if (!p.valid) return show("err", "Штрихкод не GS1 або невірна контрольна цифра — товар не приймається");
    if (!body.quantity) return show("warn", "Введіть кількість (або скануйте GS1 з AI 37)");
    if (!body.batch_number) return show("warn", "Введіть номер партії (або скануйте GS1 з AI 10)");
    try {
      const r: any = await postOffline(`/api/receiving/shipments/${sh.asn_number}/scan`, body, `Приймання ${sh.asn_number}: ${code}`);
      if (isQueued(r)) show("warn", `Немає зв'язку: скан × ${body.quantity} збережено в черзі`);
      else {
        if (r.warning) show("warn", r.warning);
        else show("ok", `${r.line.product_code}: +${fmt(r.quantity)} → прийнято ${fmt(r.line.accepted)} з ${fmt(r.line.expected)}`);
        refresh();
      }
      setQty("");
    } catch (e) { show("err", errText(e)); }
  };
  const complete = async () => {
    try {
      const r = await post(`/api/receiving/shipments/${sh.asn_number}/complete`);
      setResult(r); setSh(null);
      show(r.discrepancy_act ? "warn" : "ok", r.discrepancy_act ? "Приймання завершено з розбіжностями — сформовано акт" : "Приймання завершено без розбіжностей");
    } catch (e) { show("err", errText(e)); }
  };
  if (result) {
    return (
      <>
        <StepBanner n={3} total={3} title="Приймання завершено" sub="наклейте етикетки SSCC" />
        <Feedback fb={fb} />
        {result.discrepancy_act && (
          <div className="lines">
            <div className="ln"><div className="main-t"><div>Акт {result.discrepancy_act.number}</div><small>ВП-03 · передано начальнику складу</small></div></div>
            {result.discrepancy_act.lines.map((l: any) => (
              <div className="ln" key={l.product_code}><div className="main-t"><div>{l.product_code}</div><small>{l.kind}</small></div>
                <div className="qty" style={{ color: l.difference < 0 ? "var(--err)" : "var(--warn)" }}>{l.difference > 0 ? "+" : ""}{fmt(l.difference)}</div></div>
            ))}
          </div>
        )}
        <div className="lines">
          {result.labels.map((l: any) => (
            <div className="ln" key={l.sscc}><div className="main-t"><div>{l.product_code} × {fmt(l.quantity)}</div><small className="mono">{l.sscc}</small></div>
              <a className="btn btn-secondary btn-sm" href={`/api/barcodes/sscc/${l.sscc}.svg`} target="_blank" rel="noreferrer">Етикетка</a></div>
          ))}
        </div>
        <button className="btn btn-lg btn-block" onClick={() => { setResult(null); clear(); }}>До списку поставок</button>
      </>
    );
  }
  if (!sh) {
    return (
      <>
        <StepBanner n={1} total={3} title="Оберіть поставку" sub="очікувані ASN" />
        <Feedback fb={fb} />
        {list && !list.length && <Empty title="Немає очікуваних поставок" hint="ASN надходять від постачальника через EDI" />}
        {list?.map((s) => (
          <button key={s.asn_number} className="list-btn" onClick={() => open(s.asn_number)}>
            <div className="main-t"><b>{s.asn_number}</b><small>{s.supplier} · {s.status === "IN_PROGRESS" ? "приймання триває" : "очікує"}</small></div><ChevronRight />
          </button>
        ))}
      </>
    );
  }
  const exp = sh.lines.reduce((a: number, l: any) => a + l.expected, 0);
  const acc = sh.lines.reduce((a: number, l: any) => a + Math.min(l.accepted, l.expected || l.accepted), 0);
  return (
    <>
      <StepBanner n={2} total={3} title="Скануйте товар" sub={`${sh.asn_number} · партія і кількість — з GS1 або вручну`} />
      <div className="inputs">
        <input value={batch} onChange={(e) => setBatch(e.target.value)} placeholder="Партія" aria-label="Партія" />
        <input value={qty} onChange={(e) => setQty(e.target.value)} placeholder="Кількість" aria-label="Кількість" inputMode="decimal" />
      </div>
      <ScanInput onScan={scan} placeholder="Скан товару (GTIN / GS1)" />
      <Feedback fb={fb} />
      <Progress done={acc} total={exp} />
      <div className="lines">
        {sh.lines.map((l: any) => (
          <div key={l.id} className={`ln ${l.expected > 0 && l.accepted >= l.expected ? "done" : ""}`}>
            <div className="main-t"><div>{l.product_code} · {l.product_name}</div><small>{l.batch_number ? `партія ${l.batch_number}` : l.expected ? "" : "поза ASN — карантин"}</small></div>
            <div className="qty">{fmt(l.accepted)} / {fmt(l.expected)}</div>
          </div>
        ))}
      </div>
      <button className="btn btn-lg btn-block" onClick={complete}>Завершити приймання</button>
      <button className="btn btn-secondary btn-block" onClick={() => { setSh(null); clear(); }}>Інша поставка</button>
    </>
  );
}

// ---------- UC-02 Розміщення ----------
function Putaway() {
  const [sug, setSug] = useState<any>(null);
  const [replace, setReplace] = useState<string | null>(null);
  const [tasks, setTasks] = useState<any[]>([]);
  const [fb, show, clear] = useFeedback();
  useEffect(() => { get("/api/putaway/tasks").then(setTasks).catch(() => undefined); }, [sug]);
  const scanLabel = async (code: string) => {
    try { setSug(await post(`/api/putaway/${encodeURIComponent(code)}/suggest`)); setReplace(null); clear(); }
    catch (e) { show("err", errText(e)); }
  };
  const confirm = async (cell: string, confirmReplace = false) => {
    try {
      const r = await post(`/api/putaway/${sug.label}/confirm`, { cell, confirm_replace: confirmReplace });
      show("ok", r.message); setSug(null); setReplace(null);
    } catch (e) {
      if (e instanceof ApiError && e.code === "confirm_replace") { setReplace(cell); show("warn", e.message); }
      else show("err", errText(e));
    }
  };
  if (!sug) {
    return (
      <>
        <StepBanner n={1} total={2} title="Скануйте етикетку SSCC" sub="вантажна одиниця в зоні приймання" />
        <ScanInput onScan={scanLabel} placeholder="Скан етикетки SSCC" />
        <Feedback fb={fb} />
        {tasks.length > 0 && <div className="muted small">Відкриті завдання ({tasks.length}) — можна обрати без скану:</div>}
        {tasks.slice(0, 8).map((t) => (
          <button key={t.number} className="list-btn" onClick={() => scanLabel(t.label)}>
            <div className="main-t"><b>{t.lines[0]?.product_code} × {fmt(t.lines[0]?.quantity)}</b>
              <small className="mono">{t.label}{t.status === "ESCALATED" ? " · ⚠ ескальовано начальнику" : ""}</small></div><ChevronRight />
          </button>
        ))}
      </>
    );
  }
  return (
    <>
      <StepBanner n={2} total={2} title="Відвезіть і скануйте комірку" sub="система підібрала комірку за правилами" />
      <div className="target">
        <div className="lbl">Комірка</div>
        <div className="addr">{sug.cell.address}</div>
        <div className="sub">{sug.product_code} · {sug.product_name}<br />партія {sug.batch} · {fmt(sug.quantity)} од.</div>
      </div>
      <ScanInput onScan={(c) => confirm(c.toUpperCase())} placeholder="Скан комірки" validateGs1={false} />
      <Feedback fb={fb} />
      {replace && <button className="btn btn-lg btn-block" onClick={() => confirm(replace, true)}>Так, розмістити в {replace}</button>}
      <button className="btn btn-secondary btn-block" onClick={() => { setSug(null); clear(); }}>Скасувати</button>
    </>
  );
}

// ---------- UC-03 Відбір ----------
function Pick() {
  const [task, setTask] = useState<any>(null);
  const [cell, setCell] = useState<string | null>(null);
  const [none, setNone] = useState(false);
  const [fb, show, clear] = useFeedback();
  const take = async () => {
    try { const r = await post("/api/picking/tasks/next"); setTask(r.task); setNone(!r.task); setCell(null); clear(); }
    catch (e) { show("err", errText(e)); }
  };
  const next = task?.lines.find((l: any) => l.id === task.next_line_id);
  const scanCell = (c: string) => {
    const code = c.toUpperCase();
    if (next && code !== next.from_cell) show("err", `Не та комірка: очікується ${next.from_cell}`);
    else { setCell(code); show("ok", `Комірка ${code} — тепер скануйте товар`); }
  };
  const scanProduct = async (code: string) => {
    try {
      const r: any = await postOffline(`/api/picking/tasks/${task.number}/confirm`, { cell, product: code }, `Відбір ${task.number}`);
      if (isQueued(r)) return show("warn", "Немає зв'язку: підтвердження відбору в черзі");
      setTask(r.task.status === "DONE" ? null : r.task);
      setCell(null);
      show("ok", r.message);
    } catch (e) { show("err", errText(e)); }
  };
  if (!task) {
    return (
      <>
        <StepBanner n={1} total={3} title="Отримайте завдання" sub="з маршрутом обходу комірок" />
        <Feedback fb={fb} />
        {none && <Empty title="Немає завдань на відбір" hint="Спробуйте пізніше або зверніться до начальника складу" />}
        <button className="btn btn-lg btn-block" onClick={take}>Отримати завдання</button>
      </>
    );
  }
  const done = task.lines.filter((l: any) => l.status === "DONE").length;
  return (
    <>
      {!cell ? <StepBanner n={2} total={3} title="Скануйте комірку" sub={`${task.number}${task.wave ? ` · ${task.wave}` : ""}`} />
        : <StepBanner n={3} total={3} title="Скануйте товар" sub={`у комірці ${cell}`} />}
      {next && (
        <div className="target">
          <div className="lbl">{cell ? "Візьміть" : "Йдіть до комірки"}</div>
          <div className="addr">{cell ? `${fmt(next.quantity - next.done_quantity)} × ${next.product_code}` : next.from_cell}</div>
          <div className="sub">{next.product_name} · партія {next.batch}</div>
        </div>
      )}
      {!cell ? <ScanInput key="cell" onScan={scanCell} placeholder="Скан комірки" validateGs1={false} />
        : <ScanInput key="prod" onScan={scanProduct} placeholder="Скан товару" />}
      <Feedback fb={fb} />
      <Progress done={done} total={task.lines.length} />
      <div className="lines">
        {task.lines.map((l: any) => (
          <div key={l.id} className={`ln ${l.status === "DONE" ? "done" : ""} ${l.id === task.next_line_id ? "next" : ""}`}>
            <div className="main-t"><div>{l.seq}. {l.from_cell}</div><small>{l.product_code} · партія {l.batch}</small></div>
            <div className="qty">{fmt(l.done_quantity)} / {fmt(l.quantity)}</div>
          </div>
        ))}
      </div>
      <div className="muted small">Маршрут: {task.route.join(" → ")} · довжина {task.route_length}</div>
      {cell && <button className="btn btn-secondary btn-block" onClick={() => { setCell(null); clear(); }}>Сканувати іншу комірку</button>}
    </>
  );
}

// ---------- UC-04 Контроль і відвантаження ----------
function Ship() {
  const [ready, setReady] = useState<any[] | null>(null);
  const [order, setOrder] = useState<string | null>(null);
  const [state, setState] = useState<any>(null);
  const [qty, setQty] = useState("");
  const [done, setDone] = useState<any>(null);
  const [fb, show, clear] = useFeedback();
  useEffect(() => { get("/api/shipping/ready").then(setReady).catch((e) => show("err", errText(e))); }, [order, done, show]);
  const open = async (n: string) => {
    try { setState(await post(`/api/shipping/orders/${n}/check`, {})); setOrder(n); setDone(null); clear(); } catch (e) { show("err", errText(e)); }
  };
  const scan = async (code: string) => {
    try {
      const r = await post(`/api/shipping/orders/${order}/check`, { code, quantity: qty ? Number(qty) : undefined });
      setState(r); setQty("");
      if (r.complete) show("ok", "Комплектно — можна відвантажувати");
      else if (r.warning) show("warn", r.warning);
      else show("ok", "Скан зараховано");
    } catch (e) { show("err", errText(e)); }
  };
  const ship = async () => {
    try { const r = await post(`/api/shipping/orders/${order}/ship`); setDone(r); setOrder(null); show("ok", r.message); }
    catch (e) { show("err", errText(e)); }
  };
  if (done) {
    return (
      <>
        <StepBanner n={3} total={3} title="Відвантажено" sub="наклейте етикетку SSCC" />
        <Feedback fb={fb} />
        <div className="target">
          <div className="lbl">Рампа {done.dispatch.ramp} · {fmt(done.dispatch.slot_start)}</div>
          <img src={`/api/barcodes/sscc/${done.sscc}.svg`} alt={`SSCC ${done.sscc}`} style={{ width: "100%", background: "#fff", marginTop: 8 }} />
        </div>
        <button className="btn btn-lg btn-block" onClick={() => { setDone(null); clear(); }}>Готово</button>
      </>
    );
  }
  if (!order) {
    return (
      <>
        <StepBanner n={1} total={3} title="Оберіть замовлення" sub="скомплектовані, очікують контролю" />
        <Feedback fb={fb} />
        {ready && !ready.length && <Empty title="Немає замовлень до контролю" />}
        {ready?.map((o) => (
          <button key={o.order_number} className="list-btn" onClick={() => open(o.order_number)}>
            <div className="main-t"><b>{o.order_number}</b><small>{o.lines.length} поз. · перевірено {o.lines.filter((l: any) => !l.missing).length}</small></div><ChevronRight />
          </button>
        ))}
      </>
    );
  }
  const total = state?.lines.reduce((a: number, l: any) => a + l.quantity, 0) ?? 0;
  const checked = state?.lines.reduce((a: number, l: any) => a + l.checked, 0) ?? 0;
  return (
    <>
      <StepBanner n={2} total={3} title="Скануйте кожне вантажне місце" sub={`${order} · кількість за замовчуванням 1`} />
      <div className="inputs" style={{ gridTemplateColumns: "1fr" }}>
        <input value={qty} onChange={(e) => setQty(e.target.value)} placeholder="Кількість (необов'язково)" inputMode="decimal" aria-label="Кількість" />
      </div>
      <ScanInput onScan={scan} placeholder="Скан вантажного місця" />
      <Feedback fb={fb} />
      <Progress done={checked} total={total} />
      <div className="lines">
        {state?.lines.map((l: any) => (
          <div key={l.product_code} className={`ln ${l.checked >= l.quantity ? "done" : ""}`}>
            <div className="main-t"><div>{l.product_code} · {l.product_name}</div><small>відібрано {fmt(l.picked)}</small></div>
            <div className="qty">{fmt(l.checked)} / {fmt(l.quantity)}</div>
          </div>
        ))}
      </div>
      <button className="btn btn-lg btn-block" disabled={!state?.complete} onClick={ship}>{state?.complete ? "Відвантажити" : "Відскануйте всі позиції"}</button>
      <button className="btn btn-secondary btn-block" onClick={() => { setOrder(null); clear(); }}>Інше замовлення</button>
    </>
  );
}

// ---------- UC-05 Перерахунок ----------
function Count() {
  const [tasks, setTasks] = useState<any[] | null>(null);
  const [cell, setCell] = useState<string | null>(null);
  const [product, setProduct] = useState("");
  const [qty, setQty] = useState("");
  const [fb, show, clear] = useFeedback();
  const load = useCallback(() => get("/api/inventory/tasks/open").then(setTasks).catch((e) => show("err", errText(e))), [show]);
  useEffect(() => { load(); }, [load]);
  const task = tasks?.find((t) => t.cell === cell);
  const pending = task?.products.filter((p: any) => p.status === "NEW") ?? [];
  const needProduct = pending.length > 1 && !product;
  const send = async () => {
    if (qty === "") return show("warn", "Введіть фактичну кількість");
    try {
      const r: any = await postOffline("/api/inventory/count", { cell, quantity: Number(qty), product: product || undefined }, `Перерахунок ${cell}`);
      if (isQueued(r)) show("warn", "Немає зв'язку: результат збережено в черзі");
      else show(r.recount ? "warn" : "ok", r.message);
      setQty(""); setProduct("");
      await load();
    } catch (e) { show("err", errText(e)); }
  };
  if (!cell) {
    return (
      <>
        <StepBanner n={1} total={2} title="Скануйте комірку" sub="облікова кількість не показується" />
        <ScanInput onScan={(c) => { setCell(c.toUpperCase()); clear(); }} placeholder="Скан комірки" validateGs1={false} />
        <Feedback fb={fb} />
        {tasks && !tasks.length && <Empty title="Немає завдань на перерахунок" />}
        {tasks?.map((t) => (
          <button key={t.number} className="list-btn" onClick={() => { setCell(t.cell); clear(); }}>
            <div className="main-t"><b>{t.cell}</b><small>{t.type === "RECOUNT" ? "повторний перерахунок" : "перерахунок"} · {t.products.length} поз.</small></div><ChevronRight />
          </button>
        ))}
      </>
    );
  }
  return (
    <>
      <StepBanner n={2} total={2} title={needProduct ? "Скануйте товар" : "Введіть фактичну кількість"} sub={`комірка ${cell}`} />
      <div className="target"><div className="lbl">Комірка</div><div className="addr">{cell}</div>
        <div className="sub">{task ? pending.map((p: any) => `${p.product_code} (${p.batch})`).join(", ") || "усі позиції пораховано" : "немає відкритого завдання"}</div></div>
      {needProduct ? <ScanInput onScan={(c) => { setProduct(c); show("ok", "Товар обрано — введіть кількість"); }} placeholder="Скан товару" /> : (
        <>
          {product && <div className="chip">Товар: {product}</div>}
          <div className="inputs" style={{ gridTemplateColumns: "1fr" }}>
            <input value={qty} onChange={(e) => setQty(e.target.value)} placeholder="Фактична кількість" inputMode="decimal" autoFocus aria-label="Фактична кількість"
              onKeyDown={(e) => { if (e.key === "Enter") send(); }} />
          </div>
          <button className="btn btn-lg btn-block" onClick={send}>Підтвердити</button>
        </>
      )}
      <Feedback fb={fb} />
      <button className="btn btn-secondary btn-block" onClick={() => { setCell(null); setProduct(""); clear(); }}>Інша комірка</button>
    </>
  );
}
