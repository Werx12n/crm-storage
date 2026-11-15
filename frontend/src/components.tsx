import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  AlertTriangle, ArrowDown, ArrowUp, Camera, CheckCircle2, CornerDownLeft, Inbox, Info, Search, WifiOff, XCircle,
} from "lucide-react";
import { describe } from "./gs1";
import { clearQueueErrors, queue, queueErrors, syncQueue } from "./api";

export type Kind = "ok" | "err" | "warn" | "info";
export type Message = { kind: Kind; text: string } | null;

export function errText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

const ICON = { ok: CheckCircle2, err: XCircle, warn: AlertTriangle, info: Info };

export function Alert({ m }: { m: Message }) {
  if (!m) return null;
  const I = ICON[m.kind];
  return <div className={`alert alert-${m.kind}`} role={m.kind === "err" ? "alert" : "status"}><I />{m.text}</div>;
}
export const Msg = Alert;

// ---------- Toast ----------
type ToastItem = { id: number; kind: Kind; text: string };
let toastId = 0;

export function toast(kind: Kind, text: string) {
  window.dispatchEvent(new CustomEvent<ToastItem>("wms-toast", { detail: { id: ++toastId, kind, text } }));
}
export const toastError = (e: unknown) => toast("err", errText(e));

export function Toasts() {
  const [items, setItems] = useState<ToastItem[]>([]);
  useEffect(() => {
    const on = (e: Event) => {
      const t = (e as CustomEvent<ToastItem>).detail;
      setItems((xs) => [...xs.slice(-3), t]);
      setTimeout(() => setItems((xs) => xs.filter((x) => x.id !== t.id)), t.kind === "err" ? 6000 : 3500);
    };
    window.addEventListener("wms-toast", on);
    return () => window.removeEventListener("wms-toast", on);
  }, []);
  return (
    <div className="toasts" aria-live="polite">
      {items.map((t) => { const I = ICON[t.kind]; return <div key={t.id} className={`toast toast-${t.kind}`}><I /><span>{t.text}</span></div>; })}
    </div>
  );
}

// ---------- Статуси ----------
const STATUS: Record<string, [string, string]> = {
  NEW: ["Нове", "b-info"], IN_PROGRESS: ["В роботі", "b-accent"], DONE: ["Виконано", "b-ok"], ESCALATED: ["Ескальовано", "b-err"],
  REGISTERED: ["Зареєстровано", "b-info"], COMPLETED: ["Завершено", "b-ok"],
  RESERVED: ["Зарезервовано", "b-accent"], PARTIAL: ["Частково", "b-warn"], IN_PICKING: ["Комплектується", "b-accent"],
  PICKED: ["Скомплектовано", "b-ok"], SHIPPED: ["Відвантажено", "b-ok"],
  AWAITING_TTN: ["Очікує ТТН", "b-warn"], SENT: ["Передано перевізнику", "b-ok"], DELIVERED: ["Доставлено", "b-ok"],
  PENDING: ["У черзі", "b-warn"], PROCESSED: ["Оброблено", "b-ok"], FAILED: ["Помилка", "b-err"],
  COUNTING: ["Перерахунок", "b-accent"], AWAITING_APPROVAL: ["Очікує затвердження", "b-warn"], APPROVED: ["Затверджено", "b-ok"],
  COUNTED: ["Пораховано", "b-ok"], RECOUNT: ["Повторний перерахунок", "b-warn"],
};
export const statusTitle = (s: string) => STATUS[s]?.[0] ?? s;

export function StatusBadge({ s }: { s: string }) {
  const [t, c] = STATUS[s] ?? [s, "b-info"];
  return <span className={`badge ${c}`}>{t}</span>;
}

export function Empty({ title = "Немає даних", hint, icon }: { title?: string; hint?: ReactNode; icon?: ReactNode }) {
  return <div className="empty">{icon ?? <Inbox />}<b>{title}</b>{hint && <span className="small">{hint}</span>}</div>;
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return <label className="field"><span className="label">{label}</span>{children}{hint && <span className="hint">{hint}</span>}</label>;
}

export function PageHead({ title, sub, children }: { title: string; sub?: ReactNode; children?: ReactNode }) {
  return (
    <div className="page-head">
      <div><h1>{title}</h1>{sub && <p>{sub}</p>}</div>
      <div className="spacer" />
      {children}
    </div>
  );
}

export function Stepper({ steps, current }: { steps: { title: string; hint?: string }[]; current: number }) {
  return (
    <div className="stepper">
      {steps.map((s, i) => (
        <div key={s.title} className={`step ${i < current ? "done" : i === current ? "current" : ""}`}>
          <b>{s.title}</b>{s.hint && <span className="small">{s.hint}</span>}
        </div>
      ))}
    </div>
  );
}

// ---------- Таблиця з пошуком, фільтрами, сортуванням ----------
export type Col = { key: string; title: string; render?: (r: any) => ReactNode; num?: boolean; sort?: boolean; value?: (r: any) => any };

export function DataTable({ cols, rows, searchKeys, filters = [], empty, emptyHint, pageSize = 50 }: {
  cols: Col[]; rows: any[]; searchKeys?: string[]; filters?: { key: string; title: string; options?: string[]; label?: (v: string) => string }[];
  empty?: string; emptyHint?: ReactNode; pageSize?: number;
}) {
  const [q, setQ] = useState("");
  const [f, setF] = useState<Record<string, string>>({});
  const [sort, setSort] = useState<{ key: string; dir: 1 | -1 } | null>(null);
  const [limit, setLimit] = useState(pageSize);
  const keys = searchKeys ?? cols.map((c) => c.key);
  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    let xs = rows.filter((r) => (!needle || keys.some((k) => String(r[k] ?? "").toLowerCase().includes(needle)))
      && Object.entries(f).every(([k, v]) => !v || String(r[k]) === v));
    if (sort) {
      const col = cols.find((c) => c.key === sort.key);
      const val = (r: any) => (col?.value ? col.value(r) : r[sort.key]);
      xs = [...xs].sort((a, b) => {
        const x = val(a), y = val(b);
        if (x == null) return 1;
        if (y == null) return -1;
        return (typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y), "uk")) * sort.dir;
      });
    }
    return xs;
  }, [rows, q, f, sort, cols, keys]);
  const opts = (key: string, given?: string[]) => given ?? [...new Set(rows.map((r) => String(r[key] ?? "")).filter(Boolean))].sort();
  const toggle = (key: string) => setSort((s) => (s?.key === key ? (s.dir === 1 ? { key, dir: -1 } : null) : { key, dir: 1 }));
  return (
    <div>
      {(rows.length > 8 || filters.length > 0) && (
        <div className="table-tools">
          <div className="search"><Search /><input placeholder="Пошук…" value={q} onChange={(e) => setQ(e.target.value)} /></div>
          {filters.map((fl) => (
            <select key={fl.key} value={f[fl.key] ?? ""} onChange={(e) => setF({ ...f, [fl.key]: e.target.value })}>
              <option value="">{fl.title}: усі</option>
              {opts(fl.key, fl.options).map((o) => <option key={o} value={o}>{fl.label ? fl.label(o) : o}</option>)}
            </select>
          ))}
        </div>
      )}
      {!shown.length ? (
        <div className="table-wrap"><Empty title={rows.length ? "Нічого не знайдено" : (empty ?? "Немає даних")}
          hint={rows.length ? "Змініть пошук або фільтри" : emptyHint} /></div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead><tr>{cols.map((c) => {
              const sortable = c.sort ?? (!c.render || !!c.value);
              return (
                <th key={c.key} className={`${c.num ? "num" : ""} ${sortable ? "sortable" : ""}`} onClick={() => sortable && toggle(c.key)}>
                  {c.title} {sortable && <span className="sort">{sort?.key === c.key ? (sort.dir === 1 ? <ArrowUp size={12} /> : <ArrowDown size={12} />) : ""}</span>}
                </th>
              );
            })}</tr></thead>
            <tbody>
              {shown.slice(0, limit).map((r, i) => (
                <tr key={i}>{cols.map((c) => <td key={c.key} className={c.num ? "num" : ""}>{c.render ? c.render(r) : fmt(r[c.key])}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {shown.length > 0 && (
        <div className="table-foot row-c">
          Показано {Math.min(limit, shown.length)} з {shown.length}{shown.length !== rows.length ? ` (усього ${rows.length})` : ""}
          {shown.length > limit && <button className="btn btn-ghost btn-sm" onClick={() => setLimit(limit + pageSize)}>Показати ще</button>}
        </div>
      )}
    </div>
  );
}

export function fmt(v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "boolean") return v ? "так" : "ні";
  if (typeof v === "number") return v.toLocaleString("uk-UA", { maximumFractionDigits: 3 });
  if (typeof v === "string" && /^\d{4}-\d{2}-\d{2}T/.test(v)) return v.slice(0, 16).replace("T", " ");
  return String(v);
}

// ---------- Поле сканування ----------
/** USB/Bluetooth-сканер працює як клавіатура (Enter завершує скан), ручне введення або камера телефона. */
export function ScanInput({ onScan, placeholder, autoFocus = true, validateGs1 = true }: {
  onScan: (code: string) => void; placeholder?: string; autoFocus?: boolean; validateGs1?: boolean;
}) {
  const [value, setValue] = useState("");
  const [camera, setCamera] = useState(false);
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => { if (autoFocus) ref.current?.focus(); }, [autoFocus, placeholder]);
  useEffect(() => {
    if (autoFocus && !camera && (document.activeElement === document.body || !document.activeElement)) ref.current?.focus();
  });
  const submit = (code: string) => {
    const c = code.trim();
    if (!c) return;
    onScan(c);
    setValue("");
    ref.current?.focus();
  };
  const hint = validateGs1 ? describe(value) : { ok: null, text: "" };
  return (
    <div className="scan-box">
      <div className="scan-row">
        <input ref={ref} value={value} autoComplete="off" autoCapitalize="characters" spellCheck={false}
          placeholder={placeholder ?? "Скануйте штрихкод"} aria-label={placeholder ?? "Поле сканування"}
          onChange={(e) => setValue(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); submit(value); } }} />
        <button type="button" className="btn" onClick={() => submit(value)} aria-label="Підтвердити"><CornerDownLeft /></button>
        <button type="button" className="btn btn-secondary" onClick={() => setCamera(true)} aria-label="Сканувати камерою"><Camera /></button>
      </div>
      <div className={`scan-hint ${hint.ok === false ? "bad" : hint.ok ? "good" : ""}`}>
        {hint.text || "Сканер працює як клавіатура · Enter — підтвердити · камера — кнопка праворуч"}
      </div>
      {camera && <CameraScanner onClose={() => setCamera(false)} onResult={(c) => { setCamera(false); submit(c); }} />}
    </div>
  );
}

function CameraScanner({ onResult, onClose }: { onResult: (c: string) => void; onClose: () => void }) {
  const [err, setErr] = useState<string | null>(null);
  const id = useRef("cam-" + Math.random().toString(36).slice(2));
  const cb = useRef(onResult);
  cb.current = onResult;
  useEffect(() => {
    let scanner: any = null;
    let stopped = false;
    (async () => {
      if (!window.isSecureContext) {
        setErr("Камера доступна лише через HTTPS або localhost. Відкрийте https://<адреса>:8443");
        return;
      }
      try {
        const mod = await import("html5-qrcode");
        const F = mod.Html5QrcodeSupportedFormats;
        scanner = new mod.Html5Qrcode(id.current, {
          formatsToSupport: [F.EAN_13, F.EAN_8, F.CODE_128, F.QR_CODE, F.DATA_MATRIX, F.UPC_A], verbose: false,
        });
        await scanner.start({ facingMode: "environment" }, { fps: 10, qrbox: { width: 260, height: 160 } },
          (text: string) => { if (!stopped) { stopped = true; cb.current(text); } }, () => undefined);
      } catch (e) {
        setErr("Не вдалося запустити камеру: " + errText(e));
      }
    })();
    return () => {
      stopped = true;
      if (scanner) scanner.stop().catch(() => undefined).finally(() => scanner.clear?.());
    };
  }, []);
  return (
    <div className="stack">
      <div id={id.current} className="camera-view" />
      {err && <Alert m={{ kind: "err", text: err }} />}
      <button type="button" className="btn btn-secondary btn-block" onClick={onClose}>Закрити камеру</button>
    </div>
  );
}

/** Банер офлайн-режиму і черги синхронізації (NFR-2.3). */
export function OfflineBanner() {
  const [online, setOnline] = useState(navigator.onLine);
  const [, force] = useState(0);
  useEffect(() => {
    const up = () => { setOnline(true); syncQueue().then(() => force((x) => x + 1)); };
    const down = () => setOnline(false);
    const q = () => force((x) => x + 1);
    window.addEventListener("online", up);
    window.addEventListener("offline", down);
    window.addEventListener("wms-queue", q);
    const t = setInterval(() => { if (navigator.onLine && queue().length) syncQueue(); }, 10000);
    return () => {
      window.removeEventListener("online", up);
      window.removeEventListener("offline", down);
      window.removeEventListener("wms-queue", q);
      clearInterval(t);
    };
  }, []);
  const n = queue().length;
  const errors = queueErrors();
  if (online && !n && !errors.length) return null;
  return (
    <div className={`banner ${online ? "banner-sync" : "banner-off"}`}>
      {!online && <><WifiOff /><b>Немає зв'язку — операції зберігаються на терміналі.</b></>}
      {n > 0 && <span>У черзі: {n}.</span>}
      {online && n > 0 && <button className="btn btn-sm" onClick={() => syncQueue().then(() => force((x) => x + 1))}>Синхронізувати</button>}
      {errors.length > 0 && (
        <div style={{ width: "100%" }}>
          Помилки синхронізації: {errors.map((e, i) => <div key={i}>• {e}</div>)}
          <button className="btn btn-sm btn-secondary" onClick={clearQueueErrors}>Очистити</button>
        </div>
      )}
    </div>
  );
}
