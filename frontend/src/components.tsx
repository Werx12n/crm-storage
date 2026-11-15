import { useEffect, useRef, useState, type ReactNode } from "react";
import { describe } from "./gs1";
import { clearQueueErrors, queue, queueErrors, syncQueue } from "./api";

export type Message = { kind: "ok" | "err" | "warn" | "info"; text: string } | null;

export function Msg({ m }: { m: Message }) {
  if (!m) return null;
  return <div className={`msg msg-${m.kind}`} role={m.kind === "err" ? "alert" : "status"}>{m.text}</div>;
}

export function errText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

/** Поле сканування ТЗД: USB/Bluetooth-сканер працює як клавіатура (Enter завершує скан),
 *  ручне введення, або сканування камерою телефона (html5-qrcode). */
export function ScanInput({ label, onScan, placeholder, autoFocus = true, validateGs1 = true }: {
  label: string; onScan: (code: string) => void; placeholder?: string; autoFocus?: boolean; validateGs1?: boolean;
}) {
  const [value, setValue] = useState("");
  const [camera, setCamera] = useState(false);
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (autoFocus) ref.current?.focus();
  }, [autoFocus, label]);
  useEffect(() => {
    // сканер працює як клавіатура: повертаємо фокус у поле, якщо він «загубився»
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
    <div className="scan">
      <label>{label}</label>
      <div className="scan-row">
        <input ref={ref} value={value} inputMode="text" autoComplete="off" placeholder={placeholder ?? "Скануйте або введіть код"}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); submit(value); } }} />
        <button type="button" className="btn" onClick={() => submit(value)}>OK</button>
        <button type="button" className="btn btn-sec" title="Сканувати камерою" onClick={() => setCamera(true)}>Камера</button>
      </div>
      {hint.text && <div className={`hint ${hint.ok === false ? "bad" : hint.ok ? "good" : ""}`}>{hint.text}</div>}
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
    <div className="camera">
      <div id={id.current} className="camera-view" />
      {err && <div className="msg msg-err">{err}</div>}
      <button type="button" className="btn btn-sec" onClick={onClose}>Закрити камеру</button>
    </div>
  );
}

export function Table({ cols, rows, empty = "Немає даних" }: {
  cols: { key: string; title: string; render?: (r: any) => ReactNode }[]; rows: any[]; empty?: string;
}) {
  if (!rows.length) return <p className="muted">{empty}</p>;
  return (
    <div className="table-wrap">
      <table>
        <thead><tr>{cols.map((c) => <th key={c.key}>{c.title}</th>)}</tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>{cols.map((c) => <td key={c.key}>{c.render ? c.render(r) : fmt(r[c.key])}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function fmt(v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "boolean") return v ? "так" : "ні";
  if (typeof v === "string" && /^\d{4}-\d{2}-\d{2}T/.test(v)) return v.slice(0, 16).replace("T", " ");
  return String(v);
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
      {!online && <b>Немає зв'язку — операції зберігаються на терміналі. </b>}
      {n > 0 && <span>У черзі: {n}. </span>}
      {online && n > 0 && <button className="btn btn-small" onClick={() => syncQueue().then(() => force((x) => x + 1))}>Синхронізувати</button>}
      {errors.length > 0 && (
        <div>
          Помилки синхронізації: {errors.map((e, i) => <div key={i}>• {e}</div>)}
          <button className="btn btn-small btn-sec" onClick={clearQueueErrors}>Очистити</button>
        </div>
      )}
    </div>
  );
}
