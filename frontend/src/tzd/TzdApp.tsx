// Boundary «ЕкранТЗД»: показатиЗавдання(), сканувати(код), підтвердити(). Великі кнопки, поле сканування.
import { useCallback, useEffect, useState } from "react";
import { Link, Route, Routes, useNavigate } from "react-router-dom";
import { ApiError, get, getUser, isQueued, logout, post, postOffline } from "../api";
import { Msg, OfflineBanner, ScanInput, errText, fmt, type Message } from "../components";
import { parseGs1 } from "../gs1";

const has = (...roles: string[]) => {
  const u = getUser();
  return !!u && u.roles.some((r) => roles.includes(r) || r === "warehouse_manager");
};

export function TzdApp() {
  const nav = useNavigate();
  const u = getUser();
  return (
    <>
      <OfflineBanner />
      <div className="tzd">
        <header>
          <h1><Link to="/tzd" style={{ textDecoration: "none" }}>ТЗД</Link></h1>
          <span className="muted" style={{ fontSize: 14 }}>{u?.login}
            {" · "}<a href="#" onClick={(e) => { e.preventDefault(); logout(); nav("/login"); }}>вийти</a>
          </span>
        </header>
        <Routes>
          <Route index element={<Menu />} />
          <Route path="receive" element={<Receive />} />
          <Route path="putaway" element={<Putaway />} />
          <Route path="pick" element={<Pick />} />
          <Route path="ship" element={<Ship />} />
          <Route path="count" element={<Count />} />
        </Routes>
      </div>
    </>
  );
}

function Menu() {
  const tiles = [
    ["receive", "📥", "Приймання", ["receiver"]],
    ["putaway", "🏗️", "Розміщення", ["forklift_driver"]],
    ["pick", "🧺", "Відбір", ["picker"]],
    ["ship", "🚚", "Контроль і відвантаження", ["packer"]],
    ["count", "🔢", "Перерахунок", ["stock_worker"]],
  ] as const;
  const visible = tiles.filter((t) => has(...t[3]));
  return (
    <>
      <div className="tiles">
        {visible.map(([to, icon, title]) => (
          <Link key={to} to={`/tzd/${to}`} className="tile"><span>{icon}</span>{title}</Link>
        ))}
      </div>
      {!visible.length && <p className="muted">Для вашої ролі немає операцій на ТЗД.</p>}
      <p className="muted" style={{ fontSize: 14, marginTop: 20 }}>
        Поле сканування приймає введення USB/Bluetooth-сканера (працює як клавіатура, Enter — завершення)
        або камеру телефона (кнопка «Камера», потрібен HTTPS).
      </p>
    </>
  );
}

// ---------- UC-01 Приймання ----------
function Receive() {
  const [list, setList] = useState<any[]>([]);
  const [sh, setSh] = useState<any>(null);
  const [m, setM] = useState<Message>(null);
  const [batch, setBatch] = useState("");
  const [qty, setQty] = useState("");
  const [result, setResult] = useState<any>(null);
  useEffect(() => {
    get("/api/receiving/shipments").then((l) => setList(l.filter((s: any) => s.status !== "COMPLETED"))).catch((e) => setM({ kind: "err", text: errText(e) }));
  }, [result]);
  const open = async (n: string) => {
    try {
      setSh(await post(`/api/receiving/shipments/${n}/start`));
      setResult(null);
      setM(null);
    } catch (e) { setM({ kind: "err", text: errText(e) }); }
  };
  const refresh = async () => setSh(await get(`/api/receiving/shipments/${sh.asn_number}`));
  const scan = async (code: string) => {
    const p = parseGs1(code);
    const body = { code, quantity: qty ? Number(qty) : p.qty ?? undefined, batch_number: batch || p.batch || undefined,
      expiry_date: p.expiry };
    if (!body.quantity) return setM({ kind: "warn", text: "Введіть кількість (або скануйте GS1 з AI 37)" });
    if (!body.batch_number) return setM({ kind: "warn", text: "Введіть партію (або скануйте GS1 з AI 10)" });
    try {
      const r: any = await postOffline(`/api/receiving/shipments/${sh.asn_number}/scan`, body, `Приймання ${sh.asn_number}: ${code}`);
      if (isQueued(r)) setM({ kind: "warn", text: `Немає зв'язку: скан ${code} × ${body.quantity} збережено в черзі` });
      else {
        setM(r.warning ? { kind: "warn", text: r.warning } : { kind: "ok", text: `${r.line.product_code}: прийнято ${r.line.accepted} з ${r.line.expected}` });
        refresh();
      }
      setQty("");
    } catch (e) { setM({ kind: "err", text: errText(e) }); }
  };
  const complete = async () => {
    try {
      const r = await post(`/api/receiving/shipments/${sh.asn_number}/complete`);
      setResult(r);
      setSh(null);
      setM({ kind: r.discrepancy_act ? "warn" : "ok", text: r.discrepancy_act ? "Приймання завершено з розбіжностями — сформовано акт" : "Приймання завершено без розбіжностей" });
    } catch (e) { setM({ kind: "err", text: errText(e) }); }
  };
  if (result) {
    return (
      <>
        <Msg m={m} />
        {result.discrepancy_act && (
          <div className="card"><b>Акт {result.discrepancy_act.number}</b>
            {result.discrepancy_act.lines.map((l: any) => (
              <div className="line" key={l.product_code}><span>{l.product_code} {l.kind}</span><b>{l.difference > 0 ? "+" : ""}{l.difference}</b></div>
            ))}
          </div>
        )}
        <div className="card"><b>Етикетки SSCC ({result.labels.length})</b>
          {result.labels.map((l: any) => (
            <div className="line" key={l.sscc}><span>{l.product_code} × {l.quantity}<br /><small>{l.sscc}</small></span>
              <a className="btn btn-sec btn-small" href={`/api/barcodes/sscc/${l.sscc}.svg`} target="_blank" rel="noreferrer">Етикетка</a></div>
          ))}
        </div>
        <button className="btn big" onClick={() => setResult(null)}>До списку поставок</button>
      </>
    );
  }
  if (!sh) {
    return (
      <>
        <h2>Оберіть поставку</h2>
        <Msg m={m} />
        {list.map((s) => (
          <button key={s.asn_number} className="btn big" onClick={() => open(s.asn_number)}>{s.asn_number} · {s.supplier}</button>
        ))}
        {!list.length && <p className="muted">Немає очікуваних поставок</p>}
      </>
    );
  }
  return (
    <>
      <h2>{sh.asn_number}</h2>
      <div className="card">
        {sh.lines.map((l: any) => (
          <div key={l.id} className={`line ${l.accepted >= l.expected && l.expected > 0 ? "done" : ""}`}>
            <span>{l.product_code} {l.product_name}<br /><small>{l.batch_number ?? ""}</small></span>
            <b>{l.accepted}/{l.expected}</b>
          </div>
        ))}
      </div>
      <div className="row">
        <div style={{ flex: 1 }}><label>Партія</label><input className="num" value={batch} onChange={(e) => setBatch(e.target.value)} /></div>
        <div style={{ flex: 1 }}><label>Кількість</label><input className="num" inputMode="decimal" value={qty} onChange={(e) => setQty(e.target.value)} /></div>
      </div>
      <ScanInput label="Штрихкод товару (GTIN / GS1)" onScan={scan} />
      <Msg m={m} />
      <button className="btn big" onClick={complete}>Завершити приймання</button>
      <button className="btn btn-sec big" onClick={() => setSh(null)}>Назад</button>
    </>
  );
}

// ---------- UC-02 Розміщення ----------
function Putaway() {
  const [sug, setSug] = useState<any>(null);
  const [m, setM] = useState<Message>(null);
  const [replace, setReplace] = useState<string | null>(null);
  const [tasks, setTasks] = useState<any[]>([]);
  const load = useCallback(() => get("/api/putaway/tasks").then(setTasks).catch(() => undefined), []);
  useEffect(() => { load(); }, [load, sug]);
  const scanLabel = async (code: string) => {
    try {
      setSug(await post(`/api/putaway/${encodeURIComponent(code)}/suggest`));
      setM(null);
      setReplace(null);
    } catch (e) { setM({ kind: "err", text: errText(e) }); }
  };
  const confirm = async (cell: string, confirmReplace = false) => {
    try {
      const r = await post(`/api/putaway/${sug.label}/confirm`, { cell, confirm_replace: confirmReplace });
      setM({ kind: "ok", text: r.message });
      setSug(null);
      setReplace(null);
    } catch (e) {
      if (e instanceof ApiError && e.code === "confirm_replace") {
        setReplace(cell);
        setM({ kind: "warn", text: e.message });
      } else setM({ kind: "err", text: errText(e) });
    }
  };
  return (
    <>
      <h2>Розміщення</h2>
      {!sug ? (
        <>
          <ScanInput label="Скануйте етикетку вантажної одиниці (SSCC)" onScan={scanLabel} />
          <Msg m={m} />
          <p className="muted">Відкриті завдання: {tasks.length}</p>
          {tasks.slice(0, 8).map((t) => (
            <button key={t.number} className="btn btn-sec big" onClick={() => scanLabel(t.label)}>
              {t.lines[0]?.product_code} × {t.lines[0]?.quantity} · {t.status === "ESCALATED" ? "⚠ ескальовано" : t.label}
            </button>
          ))}
        </>
      ) : (
        <>
          <div className="card">
            <div>{sug.product_code} {sug.product_name}</div>
            <div className="muted">Партія {sug.batch} · {sug.quantity} од.</div>
            <div style={{ marginTop: 10 }}>Комірка:</div>
            <div className="addr">{sug.cell.address}</div>
          </div>
          <ScanInput label="Скануйте штрихкод комірки" onScan={(c) => confirm(c.toUpperCase())} validateGs1={false} />
          <Msg m={m} />
          {replace && <button className="btn big" onClick={() => confirm(replace, true)}>Підтвердити заміну на {replace}</button>}
          <button className="btn btn-sec big" onClick={() => { setSug(null); setM(null); }}>Скасувати</button>
        </>
      )}
    </>
  );
}

// ---------- UC-03 Відбір ----------
function Pick() {
  const [task, setTask] = useState<any>(null);
  const [cell, setCell] = useState<string | null>(null);
  const [m, setM] = useState<Message>(null);
  const [none, setNone] = useState(false);
  const take = async () => {
    try {
      const r = await post("/api/picking/tasks/next");
      setTask(r.task);
      setNone(!r.task);
      setCell(null);
    } catch (e) { setM({ kind: "err", text: errText(e) }); }
  };
  const next = task?.lines.find((l: any) => l.id === task.next_line_id);
  const scanCell = (c: string) => {
    const code = c.toUpperCase();
    if (next && code !== next.from_cell) setM({ kind: "warn", text: `Очікується комірка ${next.from_cell}` });
    else { setCell(code); setM(null); }
  };
  const scanProduct = async (code: string) => {
    try {
      const r: any = await postOffline(`/api/picking/tasks/${task.number}/confirm`, { cell, product: code }, `Відбір ${task.number}`);
      if (isQueued(r)) {
        setM({ kind: "warn", text: "Немає зв'язку: підтвердження відбору в черзі" });
        return;
      }
      setTask(r.task.status === "DONE" ? null : r.task);
      setM({ kind: "ok", text: r.message });
      setCell(null);
    } catch (e) { setM({ kind: "err", text: errText(e) }); }
  };
  if (!task) {
    return (
      <>
        <h2>Відбір</h2>
        <Msg m={m} />
        {none && <p className="muted">Немає завдань на відбір</p>}
        <button className="btn big" onClick={take}>Отримати завдання</button>
      </>
    );
  }
  return (
    <>
      <h2>{task.number} {task.wave ? `· ${task.wave}` : ""}</h2>
      <div className="muted" style={{ fontSize: 14 }}>Маршрут: {task.route.join(" → ")} (довжина {task.route_length})</div>
      <div className="card">
        {task.lines.map((l: any) => (
          <div key={l.id} className={`line ${l.status === "DONE" ? "done" : ""} ${l.id === task.next_line_id ? "next" : ""}`}>
            <span>{l.seq}. {l.from_cell} · {l.product_code} {l.product_name}<br /><small>партія {l.batch}</small></span>
            <b>{l.done_quantity}/{l.quantity}</b>
          </div>
        ))}
      </div>
      {next && (
        <div className="card">
          <div>Далі: <b>{next.product_code}</b> × {next.quantity - next.done_quantity}</div>
          <div className="addr">{next.from_cell}</div>
        </div>
      )}
      {!cell ? (
        <ScanInput label="1. Скануйте комірку" onScan={scanCell} validateGs1={false} />
      ) : (
        <ScanInput label={`2. Скануйте товар у ${cell}`} onScan={scanProduct} />
      )}
      <Msg m={m} />
    </>
  );
}

// ---------- UC-04 Контроль і відвантаження ----------
function Ship() {
  const [ready, setReady] = useState<any[]>([]);
  const [order, setOrder] = useState<string | null>(null);
  const [state, setState] = useState<any>(null);
  const [qty, setQty] = useState("");
  const [done, setDone] = useState<any>(null);
  const [m, setM] = useState<Message>(null);
  useEffect(() => { get("/api/shipping/ready").then(setReady).catch((e) => setM({ kind: "err", text: errText(e) })); }, [order, done]);
  const open = async (n: string) => {
    try {
      setState(await post(`/api/shipping/orders/${n}/check`, {}));
      setOrder(n);
      setDone(null);
      setM(null);
    } catch (e) { setM({ kind: "err", text: errText(e) }); }
  };
  const scan = async (code: string) => {
    try {
      const r = await post(`/api/shipping/orders/${order}/check`, { code, quantity: qty ? Number(qty) : undefined });
      setState(r);
      setQty("");
      setM(r.complete ? { kind: "ok", text: "Комплектно — можна відвантажувати" } : r.warning ? { kind: "warn", text: r.warning } : null);
    } catch (e) { setM({ kind: "err", text: errText(e) }); }
  };
  const ship = async () => {
    try {
      const r = await post(`/api/shipping/orders/${order}/ship`);
      setDone(r);
      setOrder(null);
      setM({ kind: "ok", text: r.message });
    } catch (e) { setM({ kind: "err", text: errText(e) }); }
  };
  if (done) {
    return (
      <>
        <Msg m={m} />
        <div className="card">
          <div>SSCC: <b>{done.sscc}</b></div>
          <div>Рампа {done.dispatch.ramp} · {fmt(done.dispatch.slot_start)}</div>
          <img src={`/api/barcodes/sscc/${done.sscc}.svg`} alt="SSCC" style={{ width: "100%", background: "#fff" }} />
        </div>
        <button className="btn big" onClick={() => setDone(null)}>Готово</button>
      </>
    );
  }
  if (!order) {
    return (
      <>
        <h2>Скомплектовані замовлення</h2>
        <Msg m={m} />
        {ready.map((o) => <button key={o.order_number} className="btn big" onClick={() => open(o.order_number)}>{o.order_number}</button>)}
        {!ready.length && <p className="muted">Немає замовлень до контролю</p>}
      </>
    );
  }
  return (
    <>
      <h2>Контроль {order}</h2>
      <div className="card">
        {state?.lines.map((l: any) => (
          <div key={l.product_code} className={`line ${l.checked >= l.quantity ? "done" : ""}`}>
            <span>{l.product_code} {l.product_name}<br /><small>відібрано {l.picked}</small></span>
            <b>{l.checked}/{l.quantity}</b>
          </div>
        ))}
      </div>
      <div className="row"><div style={{ flex: 1 }}><label>Кількість (за замовчуванням 1)</label>
        <input className="num" inputMode="decimal" value={qty} onChange={(e) => setQty(e.target.value)} /></div></div>
      <ScanInput label="Скануйте вантажне місце / товар" onScan={scan} />
      <Msg m={m} />
      <button className="btn big" disabled={!state?.complete} onClick={ship}>Відвантажити</button>
      <button className="btn btn-sec big" onClick={() => setOrder(null)}>Назад</button>
    </>
  );
}

// ---------- UC-05 Перерахунок ----------
function Count() {
  const [tasks, setTasks] = useState<any[]>([]);
  const [cell, setCell] = useState<string | null>(null);
  const [product, setProduct] = useState<string>("");
  const [qty, setQty] = useState("");
  const [m, setM] = useState<Message>(null);
  const load = useCallback(() => get("/api/inventory/tasks/open").then(setTasks).catch((e) => setM({ kind: "err", text: errText(e) })), []);
  useEffect(() => { load(); }, [load]);
  const task = tasks.find((t) => t.cell === cell);
  const pending = task?.products.filter((p: any) => p.status === "NEW") ?? [];
  const send = async () => {
    if (qty === "") return setM({ kind: "warn", text: "Введіть фактичну кількість" });
    try {
      const r: any = await postOffline("/api/inventory/count", { cell, quantity: Number(qty), product: product || undefined }, `Перерахунок ${cell}`);
      if (isQueued(r)) setM({ kind: "warn", text: "Немає зв'язку: результат збережено в черзі" });
      else setM({ kind: r.recount ? "warn" : "ok", text: r.message });
      setQty("");
      setProduct("");
      await load();
    } catch (e) { setM({ kind: "err", text: errText(e) }); }
  };
  return (
    <>
      <h2>Перерахунок</h2>
      {!cell ? (
        <>
          <ScanInput label="Скануйте комірку" onScan={(c) => { setCell(c.toUpperCase()); setM(null); }} validateGs1={false} />
          <Msg m={m} />
          {tasks.map((t) => (
            <button key={t.number} className="btn btn-sec big" onClick={() => setCell(t.cell)}>
              {t.cell} · {t.type === "RECOUNT" ? "повторний" : "перерахунок"}</button>
          ))}
          {!tasks.length && <p className="muted">Немає завдань на перерахунок</p>}
        </>
      ) : (
        <>
          <div className="card"><div className="addr">{cell}</div>
            {pending.map((p: any) => <div key={p.product_code + p.batch} className="line"><span>{p.product_code} {p.product_name}</span><small>{p.batch}</small></div>)}
            {!task && <div className="muted">Для цієї комірки немає відкритого завдання</div>}
          </div>
          {pending.length > 1 && <ScanInput label="Скануйте товар" onScan={setProduct} />}
          {product && <div className="muted">Товар: {product}</div>}
          <label>Фактична кількість</label>
          <input className="num" inputMode="decimal" value={qty} onChange={(e) => setQty(e.target.value)} />
          <button className="btn big" onClick={send}>Підтвердити</button>
          <Msg m={m} />
          <button className="btn btn-sec big" onClick={() => { setCell(null); setM(null); }}>Інша комірка</button>
        </>
      )}
    </>
  );
}
